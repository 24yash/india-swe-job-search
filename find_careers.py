"""Find the careers site of every bank company that has no readable job board yet, and work out which
job platform its openings come from.

Usage: python3 find_careers.py                 # all bank companies without a direct board (cached; ~20-40 min)
       python3 find_careers.py --only "Upstox" "JPMorgan Chase & Co."
       python3 find_careers.py --refresh       # ignore the cache
       python3 find_careers.py --more          # second pass: Keka/Zoho/Kula pages, Eightfold tenants, Jibe feeds,
                                               # sitemaps with JobPosting pages (writes output/discovered-more.json)
Writes output/careers-sites.json (one entry per company, reused for 30 days) and output/discovered-sites.json
(verified boards a crawler can read, to copy into companies.json). Read-only: plain page loads, robots.txt
respected, nothing submitted, no sign-ins, nothing that gets around bot protection.

Steps per company:
1. Website: `site` in tiers.json if recorded, else the careers URL from the imported lists, else guessed
   domains (name.com/.in/.io/.ai/.co/.tech), accepted only if the page names the company.
2. Careers pages: /careers, /jobs, careers.<domain>, jobs.<domain>, and links on the homepage that say careers/jobs.
3. Each careers page is read as served; if it names no job platform, it is rendered in headless Chrome (most
   careers pages build their job list with JavaScript), and up to 3 "open roles / view jobs" links on it are
   followed the same way.
4. Platforms found are verified (India roles, right company) with discover_ats.verify.
"""
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

import discover_ats as da

# Bounded patterns: an unclosed <a> on a multi-megabyte page made an unbounded (.*?)</a> backtrack for minutes.
ANCHOR = re.compile(r'<a\b[^>]{0,1500}?href="([^"#]{1,600})"[^>]{0,1500}>(.{0,1500}?)</a>', re.S | re.I)

ROOT = Path(__file__).parent
OUT = ROOT / "output"
CACHE = OUT / "careers-sites.json"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
TLDS = ("com", "in", "io", "ai", "co", "tech", "app")
# Pages that are not the company's own site (VC portfolio boards, aggregators, social, docs).
NOT_OWN = r"peakxv\.com|lsvp\.com|accel\.com|sequoia|getro|cutshort|wellfound|angel\.co|linkedin\.com|notion\.(site|so|com)|" \
          r"instahyre|naukri|glassdoor|indeed|google\.com|github\.com|medium\.com|twitter\.com|x\.com|facebook\.com|crunchbase"
JOB_LINK = re.compile(r"open (roles|positions)|view (all )?(jobs|openings|roles|positions)|current openings|see (all )?(jobs|openings|roles)|"
                      r"job openings|explore (jobs|roles|opportunities)|all jobs|search jobs|find (jobs|your role)|join (us|our team)|careers?$|jobs?$",
                      re.I)
RECHECK_DAYS = 30


def session():
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


S = session()
ROBOTS = {}


def allowed(url):
    """robots.txt check for our page loads (cached per host; unreadable robots.txt = allowed)."""
    p = urlparse(url)
    host = f"{p.scheme}://{p.netloc}"
    if host not in ROBOTS:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = S.get(host + "/robots.txt", timeout=8)
            rp.parse(r.text.splitlines() if r.ok else [])
        except requests.RequestException:
            rp.parse([])
        ROBOTS[host] = rp
    return ROBOTS[host].can_fetch(UA, url)


def fetch(url):
    """(final url, html) or (None, '') — plain request, no JavaScript."""
    if not allowed(url):
        return None, ""
    try:
        r = S.get(url, timeout=12, allow_redirects=True)
        if r.status_code < 400 and "html" in r.headers.get("content-type", "html"):
            return r.url, r.text[:1_500_000]
    except requests.RequestException:
        pass
    return None, ""


def render(url):
    """HTML after JavaScript runs (headless Chrome, fresh throwaway profile)."""
    if not allowed(url):
        return ""
    prof = tempfile.mkdtemp(prefix="careers-")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={prof}",
                            "--virtual-time-budget=10000", f"--user-agent={UA}", "--dump-dom", url],
                           capture_output=True, text=True, timeout=45)
        return r.stdout[:3_000_000]
    except (subprocess.TimeoutExpired, OSError):
        return ""
    finally:
        shutil.rmtree(prof, ignore_errors=True)


def resolves(host):
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def names_company(name, html):
    """The page mentions the company (title or text), so a guessed domain belongs to it."""
    key = da.norm(name)
    text = re.sub(r"[^a-z0-9]", "", re.sub(r"<[^>]+>", " ", html[:300_000]).lower())
    return len(key) >= 3 and key in text


def guess_sites(name):
    words = re.sub(r"[^a-z0-9 ]", " ", re.sub(da.SUFFIX, " ", name.lower())).split()
    full = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    stems = list(dict.fromkeys(s for s in ("".join(words), "-".join(words), "".join(full), "get" + "".join(words),
                                           "".join(words) + "hq") if len(s) >= 3))
    return [f"{s}.{t}" for s in stems for t in TLDS]


def careers_candidates(home_url, html):
    """Careers page URLs for a site: links on the homepage that say careers/jobs, then the usual paths."""
    p = urlparse(home_url)
    root = f"{p.scheme}://{p.netloc}"
    bare = p.netloc.removeprefix("www.")
    found = []
    for href, text in ANCHOR.findall(html[:1_500_000]):
        label = re.sub(r"<[^>]+>|\s+", " ", text).strip()
        if re.search(r"\b(careers?|jobs|join us|work with us|we'?re hiring|hiring)\b", label + " " + href, re.I) and len(label) < 40:
            found.append(urljoin(home_url, href))
    found += [f"{root}/careers", f"{root}/jobs", f"https://careers.{bare}", f"https://jobs.{bare}", f"{root}/company/careers",
              f"{root}/about/careers"]
    return [u for u in dict.fromkeys(found) if not re.search(NOT_OWN, u) and u.startswith("http")][:8]


def job_links(page_url, html):
    """Links on a careers page that lead to the job list ("View open roles", "Current openings"…)."""
    out = []
    for href, text in ANCHOR.findall(html[:1_500_000]):
        label = re.sub(r"<[^>]+>|\s+", " ", text).strip()
        if JOB_LINK.search(label) or re.search(r"/(jobs|openings|positions|search-jobs|job-search|open-roles)\b", href, re.I):
            u = urljoin(page_url, href)
            if u.startswith("http") and u != page_url:
                out.append(u)
    return list(dict.fromkeys(out))[:3]


def platforms(text):
    return [p for p, pat in PLATFORM_HINTS.items() if re.search(pat, text, re.I)]


# Platforms with no board slug in the URL: recorded so we know what reader to build next.
PLATFORM_HINTS = {"darwinbox": r"darwinbox\.", "keka": r"keka\.com", "zohorecruit": r"zohorecruit\.", "freshteam": r"freshteam\.com",
                  "turbohire": r"turbohire\.co", "phenom": r"phenompeople|cdn\.phenom", "successfactors": r"successfactors\.|rmkcdn",
                  "eightfold": r"eightfold\.ai", "oracle": r"oraclecloud\.com/hcmUI", "icims": r"icims\.com", "taleo": r"taleo\.net",
                  "avature": r"avature\.net", "kula": r"kula\.ai", "superset": r"joinsuperset", "mynexthire": r"mynexthire",
                  "skillate": r"skillate", "ripplehire": r"ripplehire", "talentrecruit": r"talentrecruit", "peoplestrong": r"peoplestrong",
                  "hirist": r"hirist\.", "instahyre": r"instahyre\.com/(?:company|jobs)", "workable": r"workable\.com"}


def study(company):
    """One company: website → careers page → job platform. Returns a cache entry."""
    name = company["name"]
    entry = {"company": name, "checked": datetime.now().strftime("%Y-%m-%d"), "site": None, "careers": None,
             "boards": [], "platforms": [], "rendered": False, "how": ""}
    starts = []
    if company.get("site"):
        starts.append(("recorded", "https://" + company["site"].removeprefix("https://").removeprefix("http://")))
    cu = company.get("careers_url")
    if cu and not re.search(NOT_OWN, cu):
        starts.append(("imported", cu))
    if not starts:
        starts += [("guessed", f"https://{d}") for d in guess_sites(name) if resolves(d)][:4]

    for how, url in starts:
        final, html = fetch(url)
        if not final or re.search(NOT_OWN, final):
            continue
        if how == "guessed" and not names_company(name, html):
            continue
        entry["site"], entry["how"] = final, how
        refs = da.boards_in(final + " " + html)
        if refs:  # the start page already names the platform (common for imported careers URLs)
            entry |= {"careers": final, "boards": refs, "platforms": platforms(final + html)}
            return entry
        pages = [final] if re.search(r"career|job|join|hiring|opening", final, re.I) else []
        pages += careers_candidates(final, html)
        for page in pages[:6]:
            purl, phtml = (final, html) if page == final else fetch(page)
            if not purl:
                continue
            if purl != final and not re.search(r"career|job|join|hiring|opening|talent|work", purl + phtml[:5000], re.I):
                continue
            entry["careers"] = purl
            seen_text = purl + " " + phtml
            refs = da.boards_in(seen_text)
            if not refs:  # JavaScript-built page: render it, then follow its "open roles" links
                rhtml = render(purl)
                entry["rendered"] = True
                seen_text += " " + rhtml
                refs = da.boards_in(seen_text)
                for link in ([] if refs else job_links(purl, rhtml or phtml)):
                    refs = da.boards_in(link)
                    if not refs:
                        lu, lhtml = fetch(link)
                        seen_text += " " + (lu or "") + " " + lhtml
                        refs = da.boards_in((lu or "") + " " + lhtml) or da.boards_in(render(link))
                    if refs:
                        break
            entry |= {"boards": refs, "platforms": platforms(seen_text)}
            return entry
        return entry  # site found but no careers page
    return entry


def main(argv):
    refresh = "--refresh" in argv
    only = argv[argv.index("--only") + 1:] if "--only" in argv else None
    tiers = json.loads((ROOT / "tiers.json").read_text())["known"]
    companies = json.loads((ROOT / "companies.json").read_text())["companies"]
    direct = {da.norm(c["name"]) for c in companies if c["ats"] != "linkedin"}
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    cutoff = (datetime.now() - timedelta(days=RECHECK_DAYS)).strftime("%Y-%m-%d")
    todo = [c for c in tiers if (only is None and da.norm(c["name"]) not in direct and c.get("pay") != "below")
            or (only and c["name"] in only)]
    todo = [c for c in todo if refresh or only or cache.get(c["name"], {}).get("checked", "") < cutoff]
    print(f"studying {len(todo)} companies' careers sites", file=sys.stderr)
    started = time.time()
    with ThreadPoolExecutor(8) as pool:
        for i, entry in enumerate(pool.map(study, todo), 1):
            cache[entry["company"]] = entry
            if i % 25 == 0:
                CACHE.write_text(json.dumps(cache, indent=1))
                print(f"  {i}/{len(todo)} ({time.time() - started:.0f}s)", file=sys.stderr)
    CACHE.write_text(json.dumps(cache, indent=1))

    links = {e["company"]: [tuple(b) if isinstance(b, list) else b for b in e["boards"]]
             for e in cache.values() if e["boards"] and da.norm(e["company"]) not in direct}
    links = {k: [(a, tuple(s) if isinstance(s, list) else s) for a, s in v] for k, v in links.items()}
    hits, unsupported, tally = da.verify(links)
    out = da.best_hits(hits)
    (OUT / "discovered-sites.json").write_text(json.dumps({"boards": out, "unsupported": unsupported}, indent=1))

    entries = [e for e in cache.values() if not only or e["company"] in only]
    n = len(entries)
    print(f"\n{n} companies: website found {sum(1 for e in entries if e['site'])}, careers page {sum(1 for e in entries if e['careers'])}, "
          f"job platform named {sum(1 for e in entries if e['boards'] or e['platforms'])}")
    print("boards referenced, by platform:", dict(sorted(tally.items(), key=lambda x: -x[1])))
    plat = {}
    for e in entries:
        for p in e["platforms"]:
            plat[p] = plat.get(p, 0) + 1
    print("platform hints (incl. ones without a reader):", dict(sorted(plat.items(), key=lambda x: -x[1])))
    print(f"\nverified boards with India roles ({len(out)}):")
    for h in out:
        print(" ", h["company"], h["ats"], h.get("slug") or h.get("host") or (h.get("tenant"), h.get("site")), h["india"],
              "verified" if h["name_verified"] else "CHECK NAME")


if __name__ == "__main__" and "--more" not in sys.argv:
    main(sys.argv[1:])


# --- second pass: sources beyond the classic job boards ---------------------------------------------------
# For companies discovery found but couldn't read: Keka / Zoho Recruit / Kula pages, Eightfold tenants (checked with
# the company's own domain), iCIMS Jibe search feeds, and sitemaps whose job pages carry schema.org JobPosting data.

def _domain(url):
    host = urlparse(url or "").netloc.lower()
    return re.sub(r"^(www|careers|jobs|career)\.", "", host)


def more_sources(entry):
    """Candidate readers for one company: [{"ats": ..., config..., "india": count or None, "how": ...}]."""
    import crawl
    from portals import sitemap as sm
    out = []
    boards = [(b[0], b[1]) for b in entry.get("boards") or []]
    for ats, slug in boards:
        try:
            if ats == "keka":
                jobs = crawl.get(f"https://{slug}.keka.com/careers/api/jobs/default/active")
                n = sum(1 for j in jobs if any("india" in json.dumps(l).lower() or l.get("countryCode") == "IN" for l in j.get("jobLocations") or []))
                out.append({"ats": "portal", "portal": "keka", "slug": slug, "india": n, "how": "keka feed"})
            elif ats == "zohorecruit":
                for tld in ("com", "in"):
                    r = S.get(f"https://{slug}.zohorecruit.{tld}/careers", timeout=20)
                    if r.ok and 'id="jobs"' in r.text:
                        out.append({"ats": "portal", "portal": "zohorecruit", "slug": slug, "tld": tld, "india": r.text.count("India"), "how": "zoho page"})
                        break
            elif ats == "kula":
                r = S.get(f"https://careers.kula.ai/{slug}?jobs=true", timeout=20)
                n = len(set(re.findall(rf'/{slug}/\d+-[a-z0-9-]+', r.text))) if r.ok else 0
                if n:
                    out.append({"ats": "portal", "portal": "kula", "slug": slug, "india": n, "how": "kula page"})
            elif ats == "eightfold":
                dom = _domain(entry.get("site"))
                s2 = session()
                s2.get(f"https://{slug}.eightfold.ai/careers?domain={dom}", timeout=15)
                r = s2.get(f"https://{slug}.eightfold.ai/api/pcsx/search", timeout=15,
                           params={"domain": dom, "query": "software engineer", "location": "India", "start": 0, "num": 10})
                if r.ok and "json" in r.headers.get("content-type", ""):
                    n = (r.json().get("data") or {}).get("count")
                    if n:
                        out.append({"ats": "eightfold", "host": f"{slug}.eightfold.ai", "domain": dom, "india": n, "how": "eightfold pcsx"})
        except (requests.RequestException, ValueError, AttributeError):
            continue
    if "kula" in (entry.get("platforms") or []) and not any(o["portal"] == "kula" for o in out if o.get("portal")):
        for slug in dict.fromkeys([_domain(entry.get("site")).split(".")[0]] + da.slug_variants(entry["company"])[:3]):
            try:
                r = S.get(f"https://careers.kula.ai/{slug}?jobs=true", timeout=20)
            except requests.RequestException:
                continue
            n = len(set(re.findall(rf'/{re.escape(slug)}/\d+-[a-z0-9-]+', r.text))) if r.ok else 0
            if n:
                out.append({"ats": "portal", "portal": "kula", "slug": slug, "india": n, "how": "kula page"})
                break
    if out:
        return out
    dom = _domain(entry.get("site") or entry.get("careers"))
    hosts = [urlparse(entry.get("careers") or "").netloc, urlparse(entry.get("site") or "").netloc]
    hosts += [f"careers.{dom}", f"jobs.{dom}"] if dom else []
    hosts = list(dict.fromkeys(h for h in hosts if h and resolves(h)))
    for host in hosts:
        try:
            r = S.get(f"https://{host}/api/jobs", params={"location": "India", "keywords": "software", "limit": 1}, timeout=15)
            if r.ok and "json" in r.headers.get("content-type", "") and "jobs" in r.json():
                n = r.json().get("totalCount") or r.json().get("count")
                if n:
                    return [{"ats": "portal", "portal": "jibe", "host": host, "india": n, "how": "jibe feed"}]
        except (requests.RequestException, ValueError):
            pass
        import crawl as _c
        robots = {}
        urls = sm.job_urls(_c, {"host": host}, robots, max_maps=12)
        if not urls:
            continue
        sample = ([u for u, _ in urls if sm.INDIA.search(u)] or [u for u, _ in urls])[:2]
        if any(sm.job_postings(sm._get(_c, u, robots, 3_000_000) or "") for u in sample):
            india = sum(1 for u, _ in urls if sm.INDIA.search(u))
            return [{"ats": "portal", "portal": "sitemap", "host": host, "india": india or None, "jobs": len(urls), "how": "sitemap + JobPosting"}]
    return []


def more(argv):
    """python3 find_careers.py --more: second pass over cached companies without a direct source."""
    import crawl
    cache = json.loads(CACHE.read_text())
    companies = json.loads((ROOT / "companies.json").read_text())["companies"]
    direct = {crawl.norm(c["name"]) for c in companies if c["ats"] != "linkedin"}
    tiers = {c["name"]: c for c in json.loads((ROOT / "tiers.json").read_text())["known"]}
    todo = [e for e in cache.values() if (e.get("careers") or e.get("site")) and crawl.norm(e["company"]) not in direct
            and not any(crawl.same_or_alias(crawl.norm(e["company"]), d) for d in direct) and tiers.get(e["company"], {}).get("pay") != "below"]
    print(f"second pass over {len(todo)} companies", file=sys.stderr)
    hits = []
    with ThreadPoolExecutor(8) as pool:
        for i, (e, found) in enumerate(zip(todo, pool.map(more_sources, todo)), 1):
            for f in found:
                hits.append({"company": e["company"], **f})
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}, {len(hits)} sources so far", file=sys.stderr)
    (OUT / "discovered-more.json").write_text(json.dumps(hits, indent=1))
    tally = {}
    for h in hits:
        tally[h["how"]] = tally.get(h["how"], 0) + 1
    print(f"\n{len(hits)} readable sources found:", tally)
    for h in sorted(hits, key=lambda h: -(h.get("india") or 0)):
        print(" ", h["company"], h["how"], h.get("slug") or h.get("host"), "india:", h.get("india"))


if __name__ == "__main__" and "--more" in sys.argv:
    more(sys.argv[1:])
