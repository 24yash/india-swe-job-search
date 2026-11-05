"""Probe public ATS job-board APIs to find which board slug a company uses.

Usage: python3 discover_ats.py razorpay groww phonepe ...
       python3 discover_ats.py --workday ebay walmart mastercard ...
Prints one line per hit: <slug> <ats> <total jobs> <india jobs> (Workday: tenant wd site total).
Copy the hits into companies.json.
"""
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

INDIA = ("india", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai",
         "gurgaon", "gurugram", "noida", "chennai", "delhi")

PROBES = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{s}/jobs",
                   lambda d: [j.get("location", {}).get("name", "") for j in d.get("jobs", [])]),
    "lever": ("https://api.lever.co/v0/postings/{s}?mode=json",
              lambda d: [(j.get("categories") or {}).get("location", "") or "" for j in d]),
    "ashby": ("https://api.ashbyhq.com/posting-api/job-board/{s}",
              lambda d: [j.get("location", "") or "" for j in d.get("jobs", [])]),
    "smartrecruiters": ("https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=100",
                        lambda d: [(j.get("location") or {}).get("country", "") or "" for j in d.get("content", [])]),
}


def probe(slug, ats):
    url, locs = PROBES[ats]
    try:
        r = requests.get(url.format(s=slug), timeout=15)
        if r.status_code != 200:
            return None
        names = locs(r.json())
        if not names:
            return None
        india = sum(1 for n in names if any(k in n.lower() for k in INDIA) or n.lower() == "in")
        return slug, ats, len(names), india
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


def main(slugs):
    if slugs and slugs[0] == "--workday":
        with ThreadPoolExecutor(8) as pool:
            for hit in filter(None, pool.map(probe_workday, slugs[1:])):
                print(*hit)
        return
    with ThreadPoolExecutor(16) as pool:
        results = pool.map(lambda a: probe(*a), [(s, a) for s in slugs for a in PROBES])
    for hit in filter(None, results):
        print(*hit)


if __name__ == "__main__":
    main(sys.argv[1:])
