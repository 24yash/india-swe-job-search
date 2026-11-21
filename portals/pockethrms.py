"""PocketHRMS career portals (Agilitas): the same two calls the portal page makes in a browser. Opening the portal page
sets plain session cookies; the page then POSTs its job search, which answers every opening with its description.
Nothing is taken from the page (the schema and company ids are the ones in the company's own careers link).
companies.json: {"ats": "portal", "portal": "pockethrms", "schema": "0OE/OA9NNuq9lGOJjhAZRg==", "company": "74nptQxi3x8gf4Sn3roRfQ=="}

There are no public job URLs (a job opens in a panel; applying needs sign-in), so the link is the portal + '#<JobCode>'.
A reply without the Jobs list (a 302 to the start page when the session is missing) raises. Paging stops at a short
page, or once TotalCount postings are in (when the reply gives one); a board still sending full pages after MAX_PAGES
pages raises (a cut-off list must not read as complete)."""
import re
import time
from urllib.parse import urlencode

import requests

from portals.jsonlist import clean

BASE = "https://ess.pockethrms.com/RecruitmentCareerPortalV2/CareerPortalV2/"
PAGE = 50
MAX_PAGES = 20


def session(h):
    """A session of its own per company: the portal keeps the company in cookies, so a shared one would mix boards."""
    s = requests.Session()
    s.headers.update(getattr(h.SESSION, "headers", {}) or {})
    return s


def fetch(c, h):
    s = session(h)
    page = BASE + "MainCareerPageV2?" + urlencode({"schemaName": c["schema"], "companyId": c["company"]})
    s.get(page, timeout=30).raise_for_status()
    jobs = []
    for n in range(1, MAX_PAGES + 1):
        r = s.post(BASE + "SearchJobs", timeout=30, allow_redirects=False,
                   json={"PageIndex": n, "PageSize": PAGE, "SearchText": "", "PostedWithinDays": None, "JobTypes": [], "Cities": [],
                         "MinExperience": None, "MaxExperience": None, "MinSalary": None, "MaxSalary": None, "ViewMode": 0})
        r.raise_for_status()
        d = r.json() if r.status_code == 200 else None
        if not isinstance(d, dict) or not isinstance(d.get("Jobs"), list):
            raise ValueError(f"PocketHRMS search for {c['name']} answered {r.status_code} without a Jobs list")
        jobs += d["Jobs"]
        total = d.get("TotalCount")
        if len(d["Jobs"]) < PAGE or (isinstance(total, int) and not isinstance(total, bool) and total > 0 and len(jobs) >= total):
            break  # without a usable TotalCount, only a short page ends the list
        time.sleep(1)
    else:
        raise ValueError(f"PocketHRMS search for {c['name']} still returns full pages after {MAX_PAGES} pages")
    for j in jobs:
        title = re.sub(r"\s+", " ", clean(h, str(j.get("Title") or "")))
        loc = ", ".join(dict.fromkeys(x for x in (clean(h, str(j.get(k) or "")) for k in ("City", "Region", "CountryName")) if x))
        if not title or not h.title_ok(title) or not h.in_india(loc):
            continue
        lo, hi = j.get("ExperienceFrom"), j.get("ExperienceTo")
        text = (f"Experience: {lo}-{hi} years\n\n" if lo not in (None, "") and hi not in (None, "") else "") + clean(h, str(j.get("Description") or ""))
        pay = re.fullmatch(r"\s*INR\s*@\s*(\d+)\s*,\s*(\d+)\s*", str(j.get("Salary") or ""))
        mode = next((f.get("FieldValue") for f in j.get("DynamicFields") or [] if f.get("FieldName") == "WorkMode"), "") or ""
        yield h.Job(c["name"], title, loc, f"{page}#{clean(h, str(j.get('JobCode') or j.get('Id') or ''))}",
                    h.parse_ts(str(j.get("PublishedDate") or "")[:10]), text, remote="remote" in mode.lower(),
                    pay_posted=f"INR {pay.group(1)} - INR {pay.group(2)}" if pay and int(pay.group(1)) > 0 else "",
                    meta={"workMode": mode})
