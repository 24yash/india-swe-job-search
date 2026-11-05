"""Probe public ATS job-board APIs to find which board slug a company uses.

Usage: python3 discover_ats.py razorpay groww phonepe ...
       python3 discover_ats.py --workday ebay walmart mastercard ...
       python3 discover_ats.py --bank            # every bank company in tiers.json without a direct board
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


def main(slugs):
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
