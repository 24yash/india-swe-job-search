"""Generic reader for careers sites that list every job in their sitemap and describe each job with schema.org
JobPosting data (the markup Google for Jobs reads). Works across Phenom, iCIMS, Avature, SuccessFactors, Radancy
and many custom sites (Fiserv, Lowe's, Arm, MSCI, DocuSign, Synopsys, Moody's, SAP, AMD, NetApp, BlackRock…).
Idea from strata-harvest (MIT), which uses sitemaps and job-page structured data for these platforms.

companies.json: {"name": "Fiserv", "ats": "portal", "portal": "sitemap", "host": "careers.fiserv.com"}
Optional: "sitemaps": [explicit sitemap URLs], "max_pages": detail pages to read per run (default 150).

Steps: sitemap URLs from robots.txt (+ /sitemap.xml, /sitemal.xml) → job URLs → keep those whose URL reads
like a software role (and isn't senior by its wording) → newest first → read each page's JobPosting data →
keep India roles that haven't passed their closing date. robots.txt is respected for every request.
"""
import gzip
import json
import re
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

JOB_PATH = re.compile(r"/(jobs?|job-detail|job-details|careers?/jobs?|positions?|vacanc\w*|requisitions?|openings?)/", re.I)
ROLE_SLUG = re.compile(r"software|engineer|developer|\bsde\b|sde-|backend|back-end|full-?stack|platform|devops|\bsre\b|site-reliability|"
                       r"java|python|golang|cloud|data-engineer|member-of-technical|mts", re.I)
SENIOR_SLUG = re.compile(r"senior|\bsr\b|sr-|staff|principal|lead|manager|director|architect|head-of|vice-president|\bvp\b|"
                         r"distinguished|fellow|intern\b|internship|apprentice", re.I)
INDIA = re.compile(r"\b(india|bengaluru|bangalore|hyderabad|pune|mumbai|gurugram|gurgaon|noida|chennai|new delhi|delhi|kolkata|"
                   r"ahmedabad|kochi|thiruvananthapuram|trivandrum|coimbatore|jaipur|indore|karnataka|telangana|maharashtra|"
                   r"tamil nadu|haryana)\b", re.I)


def _get(h, url, robots, limit=8_000_000):
    host = urlparse(url).netloc
    if host not in robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = h.SESSION.get(f"https://{host}/robots.txt", timeout=15)
            rp.parse(r.text.splitlines() if r.status_code < 400 else [])
        except Exception:
            rp.parse([])
        robots[host] = rp
    if not robots[host].can_fetch(h.SESSION.headers.get("User-Agent", "*"), url):
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
    """[(url, lastmod)] for job pages listed in the site's sitemaps."""
    todo, seen, jobs = sitemap_urls(h, c, robots), set(), {}
    while todo and len(seen) < max_maps:
        sm = todo.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        xml = _get(h, sm, robots)
        if not xml or "<loc>" not in xml:
            continue
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


def fetch(c, h):
    robots = {}
    urls = job_urls(h, c, robots)
    picked = [(u, m) for u, m in urls if ROLE_SLUG.search(urlparse(u).path) and not SENIOR_SLUG.search(urlparse(u).path)]
    newest = sorted(picked, key=lambda x: x[1], reverse=True)
    # URLs that name an Indian city first (many sites put the location in the URL), then the newest of the rest
    todo = ([x for x in newest if INDIA.search(x[0])] + [x for x in newest if not INDIA.search(x[0])])[: c.get("max_pages", 150)]
    now = datetime.now(timezone.utc)

    def detail(item):
        url, _ = item
        page = _get(h, url, robots, 3_000_000)
        if not page:
            return None
        for jp in job_postings(page):
            title = (jp.get("title") or jp.get("name") or "").strip()
            locs = place(jp)
            remote = "TELECOMMUTE" in str(jp.get("jobLocationType", "")).upper()
            if not title or not h.title_ok(title) or not (any(INDIA.search(l) for l in locs) or
                                                            (remote and "india" in json.dumps(jp.get("applicantLocationRequirements", "")).lower())):
                continue
            until = h.parse_ts(jp.get("validThrough")) if jp.get("validThrough") else None
            if until and until < now:
                continue  # closing date passed
            return h.Job(c["name"], title, " / ".join(l for l in locs if INDIA.search(l)) or "India", jp.get("url") or url,
                         h.parse_ts(jp.get("datePosted")), h.strip_html(jp.get("description") or ""), remote=remote,
                         meta={"employmentType": str(jp.get("employmentType") or "")})
        return None

    with ThreadPoolExecutor(6) as pool:
        seen = set()
        for job in filter(None, pool.map(detail, todo)):
            key = (job.title.lower(), job.location.lower())
            if key not in seen:  # sitemaps often list each job once per language
                seen.add(key)
                yield job
