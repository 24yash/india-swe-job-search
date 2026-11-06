"""Grow the company bank (tiers.json) from public lists of Indian product companies and funded startups.

Usage: python3 import_lists.py
Sources (read-only, public GitHub):
  - Kaustubh-Natuskar/moreThanFAANGM (MIT): ~480 product companies and startups with careers-page links
  - pHequals7/isjb: portfolio companies of India-focused VC funds (Accel, Peak XV, Lightspeed, Nexus,
    Bessemer, General Catalyst, Blume) with domains and job-board links
New companies are added with pay "unclear" (to be checked) and their source and careers URL, so
discover_ats.py --careers can read the job board straight from the URL. Existing entries are left alone.
"""
import html
import json
import re
from pathlib import Path

import requests

from crawl import is_excluded_company  # same services/staffing rule as the crawler

ROOT = Path(__file__).parent
RAW = "https://raw.githubusercontent.com"
ISJB_FILES = {"accel": "Accel", "peakxv": "Peak XV", "lightspeed": "Lightspeed", "nexus": "Nexus",
              "bessemer": "Bessemer", "gc": "General Catalyst", "blume": "Blume", "publicly-listed": "listed"}


def norm(name):  # same rule as crawl.py
    return re.sub(r"\b(pvt|private|ltd|limited|inc|llc|technologies|technology|india|solutions|labs|software|the)\b|[^a-z0-9]", "",
                  name.lower())


def more_than_faangm():
    md = requests.get(f"{RAW}/Kaustubh-Natuskar/moreThanFAANGM/main/README.md", timeout=30).text
    for url, name in re.findall(r'<li><a href="([^"]+)">([^<]+)</a>', md):
        yield html.unescape(name).strip(), url.strip(), "moreThanFAANGM (product companies list)", 10


def isjb():
    for f, fund in ISJB_FILES.items():
        r = requests.get(f"{RAW}/pHequals7/isjb/main/data/{f}.json", timeout=30)
        if not r.ok:
            continue
        d = r.json()
        for c in d.get("companies", d if isinstance(d, list) else []):
            name = re.sub(r"\s*\([^)]*\)$", "", c.get("name", "")).strip()  # "Spindle Ai (spindle.ai)" -> "Spindle Ai"
            url = c.get("careersUrl") or (f"https://{c['domain']}" if c.get("domain") else c.get("jobsBoardUrl", ""))
            label = "listed Indian tech company (ISJB)" if fund == "listed" else f"{fund}-backed startup (ISJB)"
            yield name, url, label, 11 if fund != "listed" else 10


def main():
    tiers = json.loads((ROOT / "tiers.json").read_text())
    companies = json.loads((ROOT / "companies.json").read_text())["companies"]
    have = {norm(c["name"]) for c in tiers["known"] + companies}
    added, by_source = [], {}
    for name, url, source, quality in list(more_than_faangm()) + list(isjb()):
        n = norm(name)
        if not n or n in have or is_excluded_company(name):
            continue
        have.add(n)
        tiers["known"].append({"name": name, "type": source, "quality": quality, "pay": "unclear",
                               "pay_note": "not yet checked", "careers_url": url, "source": source})
        added.append(name)
        by_source[source] = by_source.get(source, 0) + 1
    (ROOT / "tiers.json").write_text(json.dumps(tiers, indent=1, ensure_ascii=False))
    print(f"added {len(added)} companies; bank now {len(tiers['known'])}")
    for s, k in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"  {k:>4}  {s}")


if __name__ == "__main__":
    main()
