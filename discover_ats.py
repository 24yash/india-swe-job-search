"""Probe public ATS job-board APIs to find which board slug a company uses.

Usage: python3 discover_ats.py razorpay groww phonepe ...
       python3 discover_ats.py --workday ebay walmart mastercard ...
       python3 discover_ats.py --bank            # every bank company in tiers.json without a direct board
       python3 discover_ats.py --careers         # read boards from careers URLs and VC portfolio job boards
Prints one line per hit: <slug> <ats> <total jobs> <india jobs> (Workday: tenant wd site total).
--bank also writes output/discovered-boards.json for review; copy the confirmed hits into companies.json.
"""
import difflib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).parent
INDIA = ("india", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai",
         "gurgaon", "gurugram", "noida", "chennai", "delhi")


def _workable(d):
    return [", ".join(filter(None, [j.get("city"), j.get("country")])) for j in d.get("jobs", [])], d.get("name")


def _smartrecruiters(d):
    posts = d.get("content", [])
    return [(j.get("location") or {}).get("country", "") or "" for j in posts], \
        ((posts[0].get("company") or {}).get("name") if posts else None)


# ats -> (url, parse(json) -> (locations, board's own company name or None))
PROBES = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{s}/jobs",
                   lambda d: ([j.get("location", {}).get("name", "") for j in d.get("jobs", [])], None)),
    "lever": ("https://api.lever.co/v0/postings/{s}?mode=json",
              lambda d: ([(j.get("categories") or {}).get("location", "") or "" for j in d], None)),
    "ashby": ("https://api.ashbyhq.com/posting-api/job-board/{s}",
              lambda d: ([j.get("location", "") or "" for j in d.get("jobs", [])], None)),
    "smartrecruiters": ("https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=100", _smartrecruiters),
    "workable": ("https://apply.workable.com/api/v1/widget/accounts/{s}", _workable),
    "recruitee": ("https://{s}.recruitee.com/api/offers/",
                  lambda d: ([", ".join(filter(None, [o.get("city"), o.get("country")])) for o in d.get("offers", [])],
                             (d.get("offers") or [{}])[0].get("company_name"))),
}


def probe(slug, ats):
    url, parse = PROBES[ats]
    try:
        r = requests.get(url.format(s=slug), timeout=15)
        if r.status_code != 200:
            return None
        names, board_name = parse(r.json())
        if not names:
            return None
        if ats == "greenhouse":  # the board's own name, to check it is the company we meant
            board_name = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}", timeout=15).json().get("name")
        india = sum(1 for n in names if any(k in n.lower() for k in INDIA) or n.lower() in ("in", "india"))
        return slug, ats, len(names), india, board_name
    except Exception:
        return None


WD_HOSTS = ("wd1", "wd3", "wd5", "wd12", "wd103", "wd108")
WD_SITES = ("External", "Careers", "careers", "External_Careers", "ExternalCareers", "ExternalCareerSite",
            "External_Career_Site", "jobs", "Jobs", "{t}", "{T}", "{T}Careers", "{T}_Careers", "{t}careers", "Global")


def probe_workday(tenant):
    for wd in WD_HOSTS:
        for site in WD_SITES:
            site = site.format(t=tenant, T=tenant.capitalize())
            url = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
            try:
                r = requests.post(url, json={"limit": 1, "offset": 0, "searchText": "software engineer India", "appliedFacets": {}}, timeout=10)
            except Exception:
                break  # host does not exist
            if r.ok:
                return tenant, wd, site, r.json().get("total")
    return None


# Platforms crawl.py can read. Discovery also probes Workable and Recruitee so they show up, but their
# boards can't be added to companies.json until crawl.py has a fetcher for them.
CRAWLED = {"greenhouse", "lever", "ashby", "smartrecruiters"}

SUFFIX = r"\b(pvt|private|ltd|limited|inc|llc|corp|corporation|technologies|technology|tech|india|solutions|labs|software|group|global|the|ai|\.ai|hq)\b"


def norm(name):
    return re.sub(r"[^a-z0-9]", "", re.sub(SUFFIX, "", name.lower()))


def slug_variants(name):
    """Likely board slugs for a company name: 'Urban Company' -> urbancompany, urban-company, urban, urbancompanyhq..."""
    base = re.sub(r"[^a-z0-9 ]", " ", re.sub(SUFFIX, " ", name.lower())).split()
    full = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    out = []
    for words in (base, full):
        if words:
            out += ["".join(words), "-".join(words), "".join(words) + "hq", "".join(words) + "india"]
    if len(base) > 1 and len(base[0]) >= 5:
        out.append(base[0])
    return list(dict.fromkeys(s for s in out if len(s) >= 3))


def same_company(name, board_name):
    if not board_name:
        return None  # platform doesn't say; needs a human look
    a, b = norm(name), norm(board_name)
    if not a or not b:
        return None  # nothing left to compare after removing suffixes like "Labs Inc"
    return a == b or a.startswith(b) or b.startswith(a) or difflib.SequenceMatcher(None, a, b).ratio() >= 0.75


def bank():
    tiers = json.loads((ROOT / "tiers.json").read_text())["known"]
    companies = json.loads((ROOT / "companies.json").read_text())["companies"]
    direct = {norm(c["name"]) for c in companies if c["ats"] != "linkedin"}
    targets = {norm(c["name"]): c["name"] for c in tiers
               if c.get("pay") in ("likely", "unclear") and norm(c["name"]) not in direct}
    jobs = [(name, s, ats) for name in targets.values() for s in slug_variants(name) for ats in PROBES]
    print(f"probing {len(targets)} companies, {len(jobs)} requests", file=sys.stderr)
    with ThreadPoolExecutor(32) as pool:
        results = list(pool.map(lambda a: (a[0], probe(a[1], a[2])), jobs))
    found = {}
    for name, hit in results:
        if not hit or not hit[3]:  # keep boards with India postings only
            continue
        slug, ats, total, india, board_name = hit
        match = same_company(name, board_name)
        if match is False:
            continue
        best = found.get(name)
        if not best or india > best["india"]:
            found[name] = {"company": name, "ats": ats, "slug": slug, "total": total, "india": india,
                           "board_name": board_name, "name_verified": match, "crawler": ats in CRAWLED}
    out = sorted(found.values(), key=lambda h: -h["india"])
    (ROOT / "output" / "discovered-boards.json").write_text(json.dumps(out, indent=1))
    for h in out:
        print(h["company"], h["ats"], h["slug"], h["total"], h["india"], h["board_name"] or "-",
              "verified" if h["name_verified"] else "CHECK NAME", "" if h["crawler"] else "(no crawler yet: don't add)")


# Job-board links as they appear in careers URLs and pages: (ats, regex capturing the board slug).
ATS_LINKS = [
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]{1,100})"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([a-z0-9_.-]{1,100})"),
    ("ashby", r"jobs\.ashbyhq\.com/([a-z0-9_.%-]{1,100})"),
    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]{1,100})"),
    ("workday", r"(?<![a-z0-9-])([a-z0-9-]{1,63})\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]{1,100})"),
    # Subdomain parts are bounded and must start at a boundary: unbounded ([a-z0-9-]+)\. went quadratic on
    # long base64 blobs in page source and froze discovery.
    # Indian and other platforms crawl.py can't read yet: counted so we know which reader to build next
    ("darwinbox", r"(?<![a-z0-9-])([a-z0-9-]{1,63})\.darwinbox\.(?:in|com)"),
    ("keka", r"(?<![a-z0-9-])([a-z0-9-]{1,63})\.keka\.com"),
    ("freshteam", r"(?<![a-z0-9-])([a-z0-9-]{1,63})\.freshteam\.com"),
    ("zohorecruit", r"(?<![a-z0-9-])([a-z0-9-]{1,63})\.zohorecruit\.(?:in|com)"),
    ("turbohire", r"(?<![a-z0-9-])([a-z0-9-]{1,63})\.turbohire\.co"),
    ("workable", r"apply\.workable\.com/([a-z0-9_-]{1,100})"),
    ("rippling", r"ats\.rippling\.com/([a-z0-9_-]{1,100})"),
    ("oracle", r"(?<![a-z0-9.])([a-z0-9]{1,63}\.fa(?:\.[a-z0-9]+)?\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z]{2}/sites/([A-Za-z0-9_]{1,100})"),
    ("eightfold", r"(?<![a-z0-9-])([a-z0-9-]{1,63})\.eightfold\.ai"),
    ("successfactors", r"career\d*\.successfactors\.(?:com|eu)/career\?company=([A-Za-z0-9_]{1,100})"),
    ("bamboohr", r"(?<![a-z0-9-])([a-z0-9-]{1,63})\.bamboohr\.com"),
    ("recruitee", r"(?<![a-z0-9-])([a-z0-9-]{1,63})\.recruitee\.com"),
    ("breezy", r"(?<![a-z0-9-])([a-z0-9-]{1,63})\.breezy\.hr"),
    ("teamtailor", r"(?<![a-z0-9-])([a-z0-9-]{1,63})\.teamtailor\.com"),
    ("gem", r"jobs\.gem\.com/([a-z0-9_-]{1,100})"),
    ("recruiterflow", r"recruiterflow\.com/([a-z0-9_-]{1,100})/jobs"),
    ("icims", r"(?<![a-z0-9-])careers-([a-z0-9-]{1,63})\.icims\.com"),
    ("jobvite", r"jobs\.jobvite\.com/([a-z0-9_-]{1,100})"),
    ("phenom", r"(phenompeople\.com|phenom\.com/[a-z])"),
    ("kula", r"careers\.kula\.ai/([a-z0-9_-]{1,100})"),
    # Oracle behind a company's own domain: the page's scripts still name the real tenant
    ("oracle", r"(?<![a-z0-9.])([a-z0-9]{1,63}\.fa(?:\.[a-z0-9]+)?\.oraclecloud\.com)/hcmRestApi/CandidateExperience/[a-z]{2}/(?:siteSettings|sites)/([A-Za-z0-9_]{1,100})"),
]
NOT_A_BOARD = {"embed", "jobs", "careers", "api", "www", "boards", "apply", "app", "static"}


def boards_in(text):
    """Every job-board reference in a URL or page: [(ats, slug or (tenant, wd, site))]."""
    found = []
    for ats, pat in ATS_LINKS:
        for m in re.finditer(pat, text, re.I):
            slug = m.groups() if ats in ("workday", "oracle") else m.group(1).lower()
            if ats != "workday" and slug in NOT_A_BOARD:
                continue
            found.append((ats, slug))
    return list(dict.fromkeys(found))


def getro_apply_links(network, queries=("software engineer", "backend", "developer", "sde")):
    """Company names and apply links of India engineering jobs on a VC portfolio job board (Getro)."""
    S = requests.Session()
    S.headers.update({"User-Agent": "Mozilla/5.0", "Content-Type": "application/json", "Accept": "application/json"})
    out = {}
    for q in queries:
        for page in range(0, 40):
            r = S.post(f"https://api.getro.com/api/v2/collections/{network}/search/jobs", timeout=30,
                       json={"hitsPerPage": 100, "page": page, "query": q, "filters": {"searchable_locations": ["India"]}})
            jobs = r.json().get("results", {}).get("jobs", []) if r.ok else []
            for j in jobs:
                name = re.sub(r"\s*\([^)]*\)$", "", (j.get("organization") or {}).get("name", "")).strip()
                out.setdefault(name, set()).add(j.get("url", ""))
            if len(jobs) < 100:
                break
    return out


def verify(links):
    """links: company -> [(ats, slug)]. Probe each readable board for India roles and check it is that company.
    Returns (hits, unsupported platform -> companies, tally of platforms)."""
    tally, hits, unsupported = {}, [], {}
    for name, refs in links.items():
        for ats, slug in dict.fromkeys(refs):
            tally[ats] = tally.get(ats, 0) + 1
            if ats not in CRAWLED and ats not in ("workday", "oracle", "eightfold", "rippling"):
                unsupported.setdefault(ats, []).append(name)  # platforms crawl.py can't read yet
            elif ats in CRAWLED:
                hit = probe(slug, ats)
                if hit and hit[3]:
                    hits.append({"company": name, "ats": ats, "slug": slug, "total": hit[2], "india": hit[3],
                                 "board_name": hit[4], "name_verified": same_company(name, hit[4]), "crawler": True})
            elif ats == "rippling":
                try:
                    jobs = requests.get(f"https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs", timeout=15).json()
                    india = sum(1 for j in jobs if any(k in ((j.get("workLocation") or {}).get("label") or "").lower() for k in INDIA))
                except (requests.RequestException, ValueError, AttributeError):
                    india = 0
                if india:
                    hits.append({"company": name, "ats": "rippling", "slug": slug, "india": india, "name_verified": None, "crawler": True})
            elif ats == "oracle":
                host, site = slug
                finder = f'findReqs;siteNumber={site},keyword="software engineer",location=India,limit=1'
                try:
                    r = requests.get(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
                                     params={"onlyData": "true", "finder": finder}, timeout=20)
                    india = (r.json().get("items") or [{}])[0].get("TotalJobsCount") if r.ok else None
                except (requests.RequestException, ValueError):
                    india = None
                if india:
                    hits.append({"company": name, "ats": "oracle", "host": host, "site": site, "india": india,
                                 "name_verified": None, "crawler": True})
            elif ats == "eightfold":
                unsupported.setdefault(ats, []).append(name)  # reader not built yet
            else:  # workday: count India engineering roles on the board
                tenant, wd, site = slug
                try:
                    r = requests.post(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs", timeout=15,
                                      json={"limit": 1, "offset": 0, "searchText": "software engineer India", "appliedFacets": {}})
                    india = r.json().get("total") if r.ok else None
                except requests.RequestException:
                    india = None
                if india:
                    hits.append({"company": name, "ats": "workday", "tenant": tenant, "wd": wd, "site": site,
                                 "india": india, "name_verified": None, "crawler": True})
    return hits, unsupported, tally


def best_hits(hits):
    best = {}
    for h in hits:
        if h["name_verified"] is not False and (h["company"] not in best or (h["india"] or 0) > (best[h["company"]]["india"] or 0)):
            best[h["company"]] = h
    return sorted(best.values(), key=lambda h: -(h["india"] or 0))


def careers():
    tiers = json.loads((ROOT / "tiers.json").read_text())["known"]
    companies = json.loads((ROOT / "companies.json").read_text())["companies"]
    direct = {norm(c["name"]) for c in companies if c["ats"] != "linkedin"}
    pages = {c["name"]: c["careers_url"] for c in tiers if c.get("careers_url") and norm(c["name"]) not in direct}
    links = {}  # company -> set of URLs/pages that may reference its board

    def scan(item):
        name, url = item
        refs = boards_in(url)
        if not refs:
            try:
                r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
                refs = boards_in(r.url + " " + r.text[:400000])
            except requests.RequestException:
                pass
        return name, refs

    print(f"scanning {len(pages)} careers URLs", file=sys.stderr)
    with ThreadPoolExecutor(16) as pool:
        for name, refs in pool.map(scan, pages.items()):
            if refs:
                links.setdefault(name, []).extend(refs)
    for network in (8672, 222):  # Accel, General Catalyst portfolio job boards
        for name, urls in getro_apply_links(network).items():
            if norm(name) in direct:
                continue
            for u in urls:
                links.setdefault(name, []).extend(boards_in(u))
    hits, unsupported, tally = verify(links)
    out = best_hits(hits)
    (ROOT / "output" / "discovered-careers.json").write_text(json.dumps({"boards": out, "unsupported": unsupported}, indent=1))
    print("boards referenced, by platform:", dict(sorted(tally.items(), key=lambda x: -x[1])))
    for ats, names in sorted(unsupported.items(), key=lambda x: -len(x[1])):
        print(f"  no reader yet ({ats}): {', '.join(sorted(names))}")
    for h in out:
        print(h["company"], h["ats"], h.get("slug") or (h.get("tenant"), h.get("site")), h["india"],
              "verified" if h["name_verified"] else "CHECK NAME")


def main(slugs):
    if slugs and slugs[0] == "--careers":
        return careers()
    if slugs and slugs[0] == "--bank":
        return bank()
    if slugs and slugs[0] == "--workday":
        with ThreadPoolExecutor(8) as pool:
            for hit in filter(None, pool.map(probe_workday, slugs[1:])):
                print(*hit)
        return
    with ThreadPoolExecutor(16) as pool:
        results = pool.map(lambda a: probe(*a), [(s, a) for s in slugs for a in PROBES])
    for hit in filter(None, results):
        print(*hit[:4], hit[4] or "")


if __name__ == "__main__":
    main(sys.argv[1:])
