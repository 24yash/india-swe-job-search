"""Generic reader for careers sites that list every job in their sitemap and describe each job with schema.org
JobPosting data (the markup Google for Jobs reads). Works across Phenom, iCIMS, Avature, SuccessFactors, Radancy
and many custom sites (Fiserv, Lowe's, Arm, MSCI, DocuSign, Synopsys, Moody's, SAP, AMD, NetApp, BlackRock…).
Idea from strata-harvest (MIT), which uses sitemaps and job-page structured data for these platforms.

companies.json: {"name": "Fiserv", "ats": "portal", "portal": "sitemap", "host": "careers.fiserv.com"}
Optional: "sitemaps": [explicit sitemap URLs], "max_pages": detail pages to read per run (default 150),
"india_in_url": true when every job URL names its city (Eightfold: .../full-stack-developer-bangalore-karnataka-india),
so only URLs naming an Indian city are read.
"cache_pages": true for sites whose job URLs are bare IDs (Meta: /profile/job_details/<id>/): every job page is read
once and its JobPosting summary kept in output/sitemap-cache/<company>.json, so a run reads only new URLs (at most
max_pages) and drops jobs that left the sitemap (closed).

Steps: sitemap URLs from robots.txt (+ /sitemap.xml, /sitemal.xml) → job URLs → keep those whose URL reads
like a software role (and isn't senior by its wording) → newest first → read each page's JobPosting data →
keep India roles that haven't passed their closing date. robots.txt is respected for every request.
"""
import gzip
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

JOB_PATH = re.compile(r"/(jobs?|job[-_]details?|careers?/jobs?|positions?|vacanc\w*|requisitions?|openings?)/", re.I)
ROLE_SLUG = re.compile(r"software|engineer|developer|\bsde\b|sde-|backend|back-end|full-?stack|platform|devops|\bsre\b|site-reliability|"
                       r"java|python|golang|cloud|data-engineer|member-of-technical|mts", re.I)
SENIOR_SLUG = re.compile(r"senior|\bsr\b|sr-|staff|principal|lead|manager|director|architect|head-of|vice-president|\bvp\b|"
                         r"distinguished|fellow|intern\b|internship|apprentice", re.I)
INDIA = re.compile(r"\b(india|bengaluru|bangalore|hyderabad|pune|mumbai|gurugram|gurgaon|noida|chennai|new delhi|delhi|kolkata|"
                   r"ahmedabad|kochi|thiruvananthapuram|trivandrum|coimbatore|jaipur|indore|karnataka|telangana|maharashtra|"
                   r"tamil nadu|haryana)\b", re.I)


class Robots:
    """robots.txt rules as RFC 9309 (and Google) read them: the group naming our user agent, else '*'; the longest
    matching rule wins and Allow wins a tie. Python's urllib.robotparser applies the first matching line instead, so
    'Disallow: /' followed by 'Allow: /careers' (Eightfold sites such as Millennium's) wrongly blocked every job page."""

    def __init__(self, text, agent):
        self.text = text or ""
        groups, current, rules_started = {}, [], False
        for line in (text or "").splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, val = (x.strip() for x in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if rules_started:
                    current, rules_started = [], False
                current.append(val.lower())
                for a in current:
                    groups.setdefault(a, [])
            elif key in ("allow", "disallow") and current:
                rules_started = True
                if val or key == "allow":
                    for a in current:
                        groups[a].append((key == "allow", val))
        ua = agent.lower()
        named = [a for a in groups if a != "*" and a and a in ua]
        rules = [r for a in named for r in groups[a]] if named else groups.get("*", [])
        self.rules = [(allow, len(rule), self._pattern(rule)) for allow, rule in rules]

    @staticmethod
    def _pattern(rule):
        """'*' matches any run of characters, a trailing '$' anchors the end; everything else is literal."""
        pat = re.escape(rule).replace(r"\*", ".*")
        if pat.endswith(r"\$"):
            pat = pat[:-2] + "$"
        return re.compile(pat)

    def can_fetch(self, url):
        u = urlparse(url)
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        best = (-1, True)
        for allow, length, pattern in self.rules:
            if (length, allow) > best and pattern.match(path):
                best = (length, allow)
        return best[1]


def _get(h, url, robots, limit=8_000_000):
    host = urlparse(url).netloc
    if host not in robots:
        try:
            r = h.SESSION.get(f"https://{host}/robots.txt", timeout=15)
            text = r.text if r.status_code < 400 else ""
        except Exception:
            text = ""
        robots[host] = Robots(text, h.SESSION.headers.get("User-Agent", "*"))
    if urlparse(url).path == "/robots.txt":
        return robots[host].text or None  # already fetched for the rules above
    if not robots[host].can_fetch(url):
        return None
    try:
        r = h.SESSION.get(url, timeout=30)
    except Exception:
        return None
    if r.status_code >= 400:
        return None
    body = r.content[:limit]
    if body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except OSError:
            return None
    return body.decode("utf-8", "ignore")


def sitemap_urls(h, c, robots):
    host = c["host"]
    found = list(c.get("sitemaps") or [])
    rb = _get(h, f"https://{host}/robots.txt", robots) or ""
    found += re.findall(r"(?im)^\s*sitemap:\s*(\S+)", rb)
    found += [f"https://{host}/sitemap.xml", f"https://{host}/sitemal.xml"]  # 'sitemal' is SAP SuccessFactors' real path
    return list(dict.fromkeys(found))


def job_urls(h, c, robots, max_maps=40):
    """[(url, lastmod)] for job pages listed in the site's sitemaps. Raises when no sitemap could be read at all
    (network, 4xx/5xx, robots.txt): an empty answer would otherwise count as every role on the board having closed,
    and would empty the page cache."""
    todo, seen, jobs, read = sitemap_urls(h, c, robots), set(), {}, 0
    while todo and len(seen) < max_maps:
        sm = todo.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        xml = _get(h, sm, robots)
        if not xml or "<loc>" not in xml:
            continue
        read += 1
        if "<sitemapindex" in xml:
            subs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
            # job sitemaps first; skip other languages' copies when an English one exists
            subs.sort(key=lambda u: (not re.search(r"job|career|posting|position|vacanc", u, re.I), bool(re.search(r"/(?!en)[a-z]{2}[-_][a-z]{2}/", u, re.I))))
            todo = subs + todo
            continue
        for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
            loc = re.search(r"<loc>\s*([^<\s]+)\s*</loc>", block)
            if not loc or not JOB_PATH.search(urlparse(loc.group(1)).path):
                continue
            mod = re.search(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", block)
            jobs.setdefault(loc.group(1), mod.group(1) if mod else "")
    if not read:
        raise RuntimeError(f"no sitemap could be read for {c['host']} (network, HTTP error or robots.txt)")
    return list(jobs.items())


def job_postings(page):
    out = []
    for blob in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(blob.strip())
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        out += [i for i in items if isinstance(i, dict) and "JobPosting" in str(i.get("@type"))]
    return out


def place(jp):
    """'City, Region, Country' strings from a JobPosting's jobLocation (dict or list)."""
    locs = jp.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    out = []
    for l in locs:
        if not isinstance(l, dict):
            continue
        a = l.get("address") or {}
        if isinstance(a, list):  # some sites (Gartner) give a list of addresses
            a = next((x for x in a if isinstance(x, dict)), {})
        if isinstance(a, str):
            out.append(a)
            continue
        country = a.get("addressCountry")
        country = country.get("name") if isinstance(country, dict) else country
        parts = [str(x).strip() for x in (a.get("addressLocality"), a.get("addressRegion"), country) if x]
        out.append(", ".join(dict.fromkeys(p for part in parts for p in part.split(", ") if p)))  # no "India, India"
    return [o for o in out if o]


def summary(jp, url):
    """What a run needs from one JobPosting, kept small enough to cache."""
    return {"title": (jp.get("title") or jp.get("name") or "").strip(), "locs": place(jp), "url": jp.get("url") or url,
            "posted": jp.get("datePosted") or "", "until": jp.get("validThrough") or "",
            "remote": "TELECOMMUTE" in str(jp.get("jobLocationType", "")).upper(),
            "remote_india": "india" in json.dumps(jp.get("applicantLocationRequirements", "")).lower(),
            "text": jp.get("description") or "", "type": str(jp.get("employmentType") or "")}


def to_job(c, h, s, now):
    """A Job for a fitting India role that hasn't passed its closing date, else None."""
    india = [l for l in s["locs"] if INDIA.search(l)]
    if not s["title"] or not h.title_ok(s["title"]) or not (india or (s["remote"] and s["remote_india"])):
        return None
    until = h.parse_ts(s["until"]) if s["until"] else None
    if until and until < now:
        return None  # closing date passed
    return h.Job(c["name"], s["title"], " / ".join(india) or "India", s["url"], h.parse_ts(s["posted"]) if s["posted"] else None,
                 h.strip_html(s["text"]), remote=s["remote"], meta={"employmentType": s["type"]})


def page_summaries(h, url, robots):
    if ".icims.com" in url and "in_iframe=1" not in url:  # classic iCIMS: JobPosting data only in the iframe view
        url += ("&" if "?" in url else "?") + "in_iframe=1"
    page = _get(h, url, robots, 3_000_000)
    return None if page is None else [summary(jp, url) for jp in job_postings(page)]


def cache_path(h, c):
    return h.OUT / "sitemap-cache" / (re.sub(r"[^a-z0-9]+", "-", c["name"].lower()).strip("-") + ".json")


def fetch_cached(c, h, robots, urls, now):
    """Bare-ID job URLs: read each page once, keep its summary (description only for India roles), reuse it while
    the URL stays in the sitemap. A failed page is retried next run; a page with no JobPosting is remembered as such."""
    path = cache_path(h, c)
    old = json.loads(path.read_text()) if path.exists() else {}
    listed = dict(urls)
    cache = {u: v for u, v in old.items() if u in listed}  # gone from the sitemap = closed
    new = [u for u, _ in sorted(urls, key=lambda x: x[1], reverse=True) if u not in cache][: c.get("max_pages", 150)]

    def read(u):
        got = page_summaries(h, u, robots)
        if got is None:
            return u, None
        for s in got:
            if not any(INDIA.search(l) for l in s["locs"]) and not s["remote_india"]:
                s["text"] = ""  # only India roles are ever shown; keep the cache small
        return u, got

    with ThreadPoolExecutor(4) as pool:
        for u, got in pool.map(read, new):
            if got is not None:
                cache[u] = got
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=0))
    seen = set()
    for summaries in cache.values():
        for s in summaries:
            job = to_job(c, h, s, now)
            if job and (job.title.lower(), job.location.lower()) not in seen:
                seen.add((job.title.lower(), job.location.lower()))
                yield job


def fetch(c, h):
    robots = {}
    urls = job_urls(h, c, robots)
    now = datetime.now(timezone.utc)
    if c.get("cache_pages"):
        yield from fetch_cached(c, h, robots, urls, now)
        return
    picked = [(u, m) for u, m in urls if ROLE_SLUG.search(urlparse(u).path) and not SENIOR_SLUG.search(urlparse(u).path)
              and (not c.get("india_in_url") or INDIA.search(u))]  # sites whose job URLs always name the city (Eightfold)
    newest = sorted(picked, key=lambda x: x[1], reverse=True)
    # URLs that name an Indian city first (many sites put the location in the URL), then the newest of the rest
    todo = ([x for x in newest if INDIA.search(x[0])] + [x for x in newest if not INDIA.search(x[0])])[: c.get("max_pages", 150)]

    def detail(item):
        for s in page_summaries(h, item[0], robots) or []:
            job = to_job(c, h, s, now)
            if job:
                return job
        return None

    with ThreadPoolExecutor(6) as pool:
        seen = set()
        for job in filter(None, pool.map(detail, todo)):
            key = (job.title.lower(), job.location.lower())
            if key not in seen:  # sitemaps often list each job once per language
                seen.add(key)
                yield job
