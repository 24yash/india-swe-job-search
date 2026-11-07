"""Find the careers site of every bank company that has no readable job board yet, and work out which
job platform its openings come from.

Usage: python3 find_careers.py                 # all bank companies without a direct board (cached; ~20-40 min)
       python3 find_careers.py --only "Upstox" "JPMorgan Chase & Co."
       python3 find_careers.py --refresh       # ignore the cache
       python3 find_careers.py --linkedin-companies   # also companies seen only in LinkedIn results
       python3 find_careers.py --more          # second pass: Keka/Zoho/Kula/Darwinbox pages, Eightfold tenants, Jibe feeds,
                                               # sitemaps with JobPosting pages (writes output/discovered-more.json)
       python3 find_careers.py --lists         # third pass: custom careers pages listing jobs as plain links
                                               # (writes output/discovered-lists.json)
Writes output/careers-sites.json (one entry per company, reused for 30 days) and output/discovered-sites.json
(verified boards a crawler can read, to copy into companies.json). Read-only: plain page loads, robots.txt
respected, nothing submitted, no sign-ins, nothing that gets around bot protection.

Steps per company:
1. Website: `site` in tiers.json if recorded, else the careers URL from the imported lists, else the domain from
   Clearbit's company autocomplete (name must match), else guessed domains (name.com/.in/.io/.ai/.co/.tech),
   accepted only if the page names the company.
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
ANCHOR = re.compile(r'<a\b[^>]{0,1500}?href=["\']([^"\'#]{1,600})["\'][^>]{0,1500}>(.{0,1500}?)</a>', re.S | re.I)  # either quote style

ROOT = Path(__file__).parent
OUT = ROOT / "output"
CACHE = OUT / "careers-sites.json"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
TLDS = ("com", "in", "io", "ai", "co", "tech", "app")
# Pages that are not the company's own site (VC portfolio boards, aggregators, social, docs).
NOT_OWN_DOMAINS = ("peakxv.com", "lsvp.com", "accel.com", "sequoiacap.com", "getro.com", "cutshort.io", "wellfound.com", "angel.co",
                   "linkedin.com", "notion.site", "notion.so", "notion.com", "instahyre.com", "naukri.com", "glassdoor.com",
                   "glassdoor.co.in", "indeed.com", "google.com", "github.com", "medium.com", "twitter.com", "x.com", "facebook.com",
                   "crunchbase.com", "apna.co", "goodspace.ai")


def not_own(url, company=""):
    """True for pages that aren't the company's own site (VC portfolio boards, aggregators, social, docs).
    Matches whole hostnames: an earlier substring pattern ("x\\.com") also rejected netflix.com, dropbox.com,
    nutanix.com, equinix.com… A company's own domain is never rejected (careers.linkedin.com for LinkedIn)."""
    host = urlparse(url or "").netloc.lower().split(":")[0]
    if not host:
        return False
    key = da.norm(company) if company else ""
    if key and len(key) >= 4 and key in host.replace(".", "").replace("-", ""):
        return False
    return any(host == d or host.endswith("." + d) for d in NOT_OWN_DOMAINS)


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


def online():
    """A network check: when the machine sleeps or Wi-Fi drops mid-run, every company would otherwise be cached
    as 'nothing found' (this happened on 7 Nov). Runs stop instead, and resume later from the cache."""
    for url in ("https://www.wikipedia.org", "https://github.com"):
        try:
            if S.head(url, timeout=8).status_code < 500:
                return True
        except requests.RequestException:
            continue
    return False


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


DOMAINS = OUT / "company-domains.json"
_DOMAINS = json.loads(DOMAINS.read_text()) if DOMAINS.exists() else {}


def clearbit_domain(name):
    """The company's own domain from Clearbit's free, keyless company-name autocomplete (cached in
    output/company-domains.json). Only a suggestion whose name matches the company is used. Replaces most of the
    domain guessing, which picked wrong sites (S&P Global -> s-p.in, Rapido -> recharge.com)."""
    if name in _DOMAINS:
        return _DOMAINS[name]
    domain = None
    try:
        r = S.get("https://autocomplete.clearbit.com/v1/companies/suggest", params={"query": name}, timeout=10)
        if r.ok:
            key = da.norm(name)
            for sug in r.json()[:5]:
                n2 = da.norm(sug.get("name") or "")
                if key and key == n2:  # exact match only: prefix matches picked other companies (Rapido -> rapidotrains.com)
                    domain = sug.get("domain")
                    break
    except (requests.RequestException, ValueError):
        return None  # don't cache a network failure
    _DOMAINS[name] = domain
    return domain


def save_domains():
    DOMAINS.write_text(json.dumps(_DOMAINS, indent=1, ensure_ascii=False))


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
    return [u for u in dict.fromkeys(found) if not not_own(u) and u.startswith("http")][:8]


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
    if cu and not not_own(cu, name):
        starts.append(("imported", cu))
    if not starts:
        cb = clearbit_domain(name)
        if cb:  # homepage first, then the usual careers hosts in case the homepage blocks scripts (spglobal.com)
            starts += [("clearbit", f"https://{cb}"), ("clearbit", f"https://careers.{cb}"), ("clearbit", f"https://jobs.{cb}")]
        starts += [("guessed", f"https://{d}") for d in guess_sites(name) if d != cb and resolves(d)][:3]

    for how, url in starts:
        final, html = fetch(url)
        if not final or not_own(final, name):
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
    if "--linkedin-companies" in argv:  # companies seen only in LinkedIn results, never in the bank
        import crawl
        known = {da.norm(c["name"]) for c in tiers}
        for f in ("linkedin-search", "linkedin-company-sweep"):
            p = OUT / "raw" / f"{f}.json"
            for j in json.loads(p.read_text())["jobs"] if p.exists() else []:
                n = j["company"]
                if "<" not in n and da.norm(n) not in known and not crawl.is_excluded_company(n):
                    known.add(da.norm(n))
                    tiers.append({"name": n, "pay": "unclear"})
    todo = [c for c in tiers if (only is None and da.norm(c["name"]) not in direct and c.get("pay") != "below")
            or (only and c["name"] in only)]
    todo = [c for c in todo if refresh or only or cache.get(c["name"], {}).get("checked", "") < cutoff]
    print(f"studying {len(todo)} companies' careers sites", file=sys.stderr)
    started = time.time()
    with ThreadPoolExecutor(8) as pool:
        for i, entry in enumerate(pool.map(study, todo), 1):
            if not entry["site"] and not online():
                CACHE.write_text(json.dumps(cache, indent=1))
                sys.exit(f"network is down after {i - 1} companies; saved what was found. Re-run to resume.")
            cache[entry["company"]] = entry
            if i % 25 == 0:
                CACHE.write_text(json.dumps(cache, indent=1))
                save_domains()
                print(f"  {i}/{len(todo)} ({time.time() - started:.0f}s)", file=sys.stderr)
    CACHE.write_text(json.dumps(cache, indent=1))
    save_domains()

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


if __name__ == "__main__" and "--more" not in sys.argv and "--lists" not in sys.argv:
    main(sys.argv[1:])


# --- second pass: sources beyond the classic job boards ---------------------------------------------------
# For companies discovery found but couldn't read: Keka / Zoho Recruit / Kula / Darwinbox pages, Eightfold tenants (checked with
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
            elif ats == "darwinbox" and slug not in ("www", "explore", "help", "newsroom", "academy", "dbox", "ms"):
                for tld in ("in", "com"):
                    r = S.post(f"https://{slug}.darwinbox.{tld}/ms/candidateapi/job/alljobs?companyId=main", json={"page": 1, "limit": 1},
                               headers={"Accept": "application/json"}, timeout=20)
                    if r.ok and "json" in r.headers.get("content-type", ""):
                        out.append({"ats": "portal", "portal": "darwinbox", "slug": slug, "tld": tld,
                                    "india": int(r.json().get("job_counts") or 0), "how": "darwinbox candidate API"})
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
            if i % 25 == 0 and not online():
                (OUT / "discovered-more.json").write_text(json.dumps(hits, indent=1))
                sys.exit(f"network is down after {i} companies; partial results saved. Re-run to redo the pass.")
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


# --- job lists written as plain links on a careers page ------------------------------------------------------
# Many custom careers pages (iRage, AlphaGrep, D. E. Shaw India…) list jobs as ordinary links. Group the page's links by
# URL shape (digits → \d+); a shape with ≥3 links whose texts read like job titles is a job list, and the generic
# links reader can read it with no code.
TITLE_WORDS = re.compile(r"engineer|developer|\bsde\b|analyst|manager|designer|scientist|architect|specialist|associate|executive|"
                         r"lead|consultant|intern|officer|administrator|researcher|operations|devops|programmer", re.I)


def link_list(page_url, html):
    """{"job_link": regex, "count": n, "sample": [...]} for the largest job-like link group on a page, or None."""
    import crawl
    groups = {}
    for href, inner in ANCHOR.findall(html[:3_000_000]):
        url = urljoin(page_url, href.strip())
        if not url.startswith("http") or urlparse(url).netloc != urlparse(page_url).netloc and "job" not in url.lower():
            continue
        inner = re.sub(r"<svg.*?</svg>", " ", inner, flags=re.S | re.I)
        named = re.search(r'class=["\'][^"\']*(?:title|name)[^"\']*["\'][^>]*>(.*?)<', inner, re.S | re.I)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", named.group(1) if named else inner)).strip()
        if not text or len(text) > 140 or not TITLE_WORDS.search(text):
            continue
        p = urlparse(url)
        segs, wild = [], False
        for seg in p.path.split("/"):
            wild = wild or bool(re.search(r"\d{3,}", seg))  # an id segment, and the slug after it, vary per job
            segs.append(r"[^/\"'?#]+" if wild and seg else re.escape(seg))
        shape = "/".join(segs) + (r"\?" + re.sub(r"\d+", r"\\d+", re.escape(p.query)) if p.query else "")
        if not re.search(r"\\d\+|\[\^/|job|career|position|opening|role|vacanc", shape, re.I):
            continue
        groups.setdefault(shape, []).append(text)
    if not groups:
        return None
    shape, texts = max(groups.items(), key=lambda kv: len(kv[1]))
    if len(set(texts)) < 3:
        return None
    return {"job_link": shape, "count": len(set(texts)), "fitting": sum(1 for t in set(texts) if crawl.title_ok(t)), "sample": sorted(set(texts))[:5]}


def list_source(entry):
    """Third pass for one company: its careers page (or the page's 'open roles' links) as a plain job list."""
    pages = [entry["careers"]] if entry.get("careers") else []
    for page in pages:
        final, html = fetch(page)
        found = link_list(final or page, html) if html else None
        if not found:
            for link in job_links(final or page, html)[:2]:  # "View open roles" → the list page
                lf, lh = fetch(link)
                found = link_list(lf or link, lh) if lh else None
                if found:
                    final = lf or link
                    break
        if not found:
            rendered = render(page)
            found = link_list(page, rendered) if rendered else None
            final = page
        if found:
            return {"ats": "portal", "portal": "links", "list_urls": [final], "job_link": found["job_link"],
                    "jobs": found["count"], "fitting": found["fitting"], "sample": found["sample"], "how": "job-list links"}
    return None


def lists(argv):
    """python3 find_careers.py --lists: third pass, custom careers pages that list jobs as plain links."""
    import crawl
    cache = json.loads(CACHE.read_text())
    companies = json.loads((ROOT / "companies.json").read_text())["companies"]
    direct = {crawl.norm(c["name"]) for c in companies if c["ats"] != "linkedin"}
    tiers = {c["name"]: c for c in json.loads((ROOT / "tiers.json").read_text())["known"]}
    only = argv[argv.index("--only") + 1:] if "--only" in argv else None
    todo = [e for e in cache.values() if e.get("careers") and crawl.norm(e["company"]) not in direct
            and not any(crawl.same_or_alias(crawl.norm(e["company"]), d) for d in direct)
            and tiers.get(e["company"], {}).get("pay") != "below" and (only is None or e["company"] in only)]
    print(f"job-list pass over {len(todo)} careers pages", file=sys.stderr)
    hits = []
    with ThreadPoolExecutor(8) as pool:
        for i, (e, found) in enumerate(zip(todo, pool.map(list_source, todo)), 1):
            if i % 25 == 0:
                if not online():
                    sys.exit("network is down; re-run to redo the pass")
                print(f"  {i}/{len(todo)}, {len(hits)} job lists so far", file=sys.stderr)
            if found:
                hits.append({"company": e["company"], **found})
    (OUT / "discovered-lists.json").write_text(json.dumps(hits, indent=1))
    print(f"\n{len(hits)} job lists found")
    for h in sorted(hits, key=lambda h: -h["fitting"]):
        print(f"  {h['company']}: {h['jobs']} jobs ({h['fitting']} fitting titles) {h['list_urls'][0]} e.g. {h['sample'][:3]}")


if __name__ == "__main__" and "--lists" in sys.argv:
    lists(sys.argv[1:])


# --- careers URLs found by a person or a search engine ---------------------------------------------------------
def source_from_urls(name, urls):
    """Readable source configs for a company, from careers URLs found by a search (Google in the user's browser,
    or by hand): platform links in the URL, Zoho Recruit on the company's own domain, Jibe feeds, the rendered page
    (Oracle tenants behind vanity domains), job sitemaps, then plain job lists. Returns a list of candidate configs."""
    from portals import sitemap as sm
    import crawl
    out = []
    for url in urls:
        refs = da.boards_in(url)
        for ats, slug in refs:
            if ats in ("greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "rippling"):
                out.append({"ats": ats, "slug": slug, "how": f"{ats} link"})
            elif ats == "workday":
                out.append({"ats": "workday", "tenant": slug[0], "wd": slug[1], "site": slug[2], "how": "workday link"})
            elif ats == "keka":
                out.append({"ats": "portal", "portal": "keka", "slug": slug, "how": "keka link"})
            elif ats == "kula":
                out.append({"ats": "portal", "portal": "kula", "slug": slug, "how": "kula link"})
            elif ats == "teamtailor":  # Teamtailor: server-rendered job links, JobPosting data on job pages
                out.append({"ats": "portal", "portal": "links", "list_urls": [f"https://{slug}.teamtailor.com/jobs"],
                            "job_link": rf"https://{slug}\.teamtailor\.com/jobs/\d+-[^\"'/?]+", "title_from_url": True, "how": "teamtailor link"})
            elif ats == "jazzhr":  # JazzHR: server-rendered job links, JobPosting data on each job page
                out.append({"ats": "portal", "portal": "links", "list_urls": [f"https://{slug}.applytojob.com/apply"],
                            "job_link": rf"https://{slug}\.applytojob\.com/apply/[A-Za-z0-9]+/[^\"'/?]+", "title_from_url": True, "how": "jazzhr link"})
            elif ats == "workable":
                out.append({"ats": "portal", "portal": "workable", "slug": slug, "how": "workable link"})
            elif ats == "freshteam":
                out.append({"ats": "portal", "portal": "freshteam", "slug": slug, "how": "freshteam link"})
            elif ats == "zohorecruit":
                out.append({"ats": "portal", "portal": "zohorecruit", "slug": slug, "tld": "com", "how": "zoho link"})
            elif ats == "darwinbox":
                out.append({"ats": "portal", "portal": "darwinbox", "slug": slug, "tld": "in", "how": "darwinbox link"})
            elif ats == "oracle":
                out.append({"ats": "oracle", "host": slug[0], "site": slug[1], "how": "oracle link"})
        if out:
            return out
    for url in urls:
        p = urlparse(url)
        if not p.netloc or not_own(url, name):
            continue
        final, html = fetch(url)
        if "/jobs/Careers" in url and 'id="jobs"' in html:  # Zoho Recruit on the company's own domain
            return [{"ats": "portal", "portal": "zohorecruit", "base": f"{p.scheme}://{p.netloc}", "list_path": "/jobs/Careers", "how": "zoho on own domain"}]
        try:
            r = S.get(f"https://{p.netloc}/api/jobs", params={"location": "India", "keywords": "software", "limit": 1}, timeout=15)
            if r.ok and "json" in r.headers.get("content-type", "") and "jobs" in r.json():
                return [{"ats": "portal", "portal": "jibe", "host": p.netloc, "how": "jibe feed"}]
        except (requests.RequestException, ValueError):
            pass
        refs = da.boards_in((final or "") + " " + html)
        rendered = ""
        if not refs:
            rendered = render(url)
            refs = da.boards_in(rendered)
        if refs:
            found = source_from_urls(name, [_ref_url(a, s) for a, s in refs])
            if found:
                return [dict(f, how=f["how"] + " (on careers page)") for f in found]
        robots = {}
        if sm.job_urls(crawl, {"host": p.netloc}, robots, max_maps=10):
            return [{"ats": "portal", "portal": "sitemap", "host": p.netloc, "how": "job sitemap"}]
        lst = link_list(final or url, html) or (link_list(url, rendered or render(url)))
        if lst:
            return [{"ats": "portal", "portal": "links", "list_urls": [final or url], "job_link": lst["job_link"], "how": "job-list links"}]
    return out


def _ref_url(ats, slug):
    """A canonical URL for a board reference, so source_from_urls can turn it into a config."""
    if ats == "workday":
        return f"https://{slug[0]}.{slug[1]}.myworkdayjobs.com/{slug[2]}"
    if ats == "oracle":
        return f"https://{slug[0]}/hcmUI/CandidateExperience/en/sites/{slug[1]}"
    return {"greenhouse": "https://boards.greenhouse.io/{}", "lever": "https://jobs.lever.co/{}", "ashby": "https://jobs.ashbyhq.com/{}",
            "smartrecruiters": "https://jobs.smartrecruiters.com/{}", "recruitee": "https://{}.recruitee.com", "rippling": "https://ats.rippling.com/{}",
            "keka": "https://{}.keka.com", "kula": "https://careers.kula.ai/{}", "workable": "https://apply.workable.com/{}",
            "freshteam": "https://{}.freshteam.com", "jazzhr": "https://{}.applytojob.com/apply", "teamtailor": "https://{}.teamtailor.com/jobs", "zohorecruit": "https://{}.zohorecruit.com", "darwinbox": "https://{}.darwinbox.in"}.get(ats, "https://{}").format(slug if isinstance(slug, str) else "")
