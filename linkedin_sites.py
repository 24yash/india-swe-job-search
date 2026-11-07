"""Official websites for companies seen only through LinkedIn search, from LinkedIn's own public pages.

Usage: python3 linkedin_sites.py            # the 200 LinkedIn-only companies with the most postings not yet looked up
LinkedIn answers some automated page loads with 999 ("request denied"); the script waits, and stops after three
refusals in a row rather than pushing through.
Reads one public job page per company (it links the company's LinkedIn page), then the company page's "Website"
field. Uses crawl.li_get, the same slow throttle and 429 backoff as the LinkedIn crawl; nothing is signed in to.
Writes output/linkedin-company-sites.json: {company: {"page": ..., "website": ...}}. find_careers.py then uses the
website as the company's site.
"""
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import crawl

OUT = Path(__file__).parent / "output"
CACHE = OUT / "linkedin-company-sites.json"
GAP = 5  # seconds between LinkedIn page loads, on top of crawl.li_get's own throttle
LIMIT = 200  # companies per run, those with the most LinkedIn postings first


class Refused(Exception):
    """LinkedIn answered 999 (its 'request denied' code for automated traffic): stop, don't push through."""


def _get(url):
    time.sleep(GAP)
    r = crawl.li_get(url)
    if r.status_code == 999:
        raise Refused(url)
    return r


def company_page(job_id):
    r = _get(f"{crawl.LI_API}/jobPosting/{job_id}")
    if r.status_code != 200:
        return None
    m = re.search(r'topcard__org-name-link[^>]*href="(https://[a-z]{2,3}\.linkedin\.com/company/[^"?]+)', r.text) or \
        re.search(r'href="(https://[a-z]{2,3}\.linkedin\.com/company/[^"?]+)[^"]*"[^>]*topcard__org-name-link', r.text)
    return m.group(1) if m else None


def website(page):
    r = _get(page.replace("://in.", "://www."))
    if r.status_code != 200:
        return None
    m = re.search(r'href="([^"]+)"[^>]*data-tracking-control-name="about_website"', r.text) or \
        re.search(r'data-tracking-control-name="about_website"[^>]*href="([^"]+)"', r.text)
    if not m:
        return None
    url = m.group(1).replace("&amp;", "&")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("url")
    return q[0] if q else url


def main():
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    companies = json.loads((Path(__file__).parent / "companies.json").read_text())["companies"]
    direct = {crawl.norm(c["name"]) for c in companies if c["ats"] != "linkedin"}
    seen = {}
    for f in ("linkedin-search", "linkedin-company-sweep"):
        p = OUT / "raw" / f"{f}.json"
        for j in json.loads(p.read_text())["jobs"] if p.exists() else []:
            n = j["company"]
            if "<" in n or crawl.norm(n) in direct or any(crawl.same_or_alias(crawl.norm(n), d) for d in direct):
                continue
            v = seen.setdefault(n, {"job": crawl.li_job_id(j["url"]), "page": (j.get("meta") or {}).get("company_page", ""), "n": 0})
            v["n"] += 1
    todo = sorted(((n, v) for n, v in seen.items() if n not in cache), key=lambda x: -x[1]["n"])[:LIMIT]
    print(f"{len(todo)} LinkedIn-only companies to look up ({len(cache)} cached)", file=sys.stderr)
    blocked, refused = 0, 0
    for i, (n, v) in enumerate(todo, 1):
        try:
            page = v["page"] or (company_page(v["job"]) if v["job"] else None)
            site = website(page) if page else None
        except (crawl.RateLimited, Refused):
            refused += 1
            if refused >= 3:
                print("LinkedIn is refusing automated requests (429/999); stopping. Re-run later to resume.", file=sys.stderr)
                break
            time.sleep(60)
            continue
        refused = 0
        if page is None and site is None:
            blocked += 1
            if blocked >= 8:
                print("LinkedIn is refusing requests (rate limit); stopping. Re-run later to resume.", file=sys.stderr)
                break
        else:
            blocked = 0
        cache[n] = {"page": page, "website": site}
        if i % 20 == 0:
            CACHE.write_text(json.dumps(cache, indent=1))
            print(f"  {i}/{len(todo)}, websites found: {sum(1 for x in cache.values() if x.get('website'))}", file=sys.stderr)
    CACHE.write_text(json.dumps(cache, indent=1))
    print(f"done: {sum(1 for x in cache.values() if x.get('website'))} websites for {len(cache)} companies")


if __name__ == "__main__":
    main()
