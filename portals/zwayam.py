"""Zwayam careers sites (Snapmint, GreyOrange): the page posts its search to public.zwayam.com/jobs/search, sending the
site's domain and its company id (base64 of the numeric id; the page keeps both in sessionStorage). Results come 10 per
page with title, locations, years asked and the description, so no detail calls are needed.

companies.json: {"ats": "portal", "portal": "zwayam", "base": "https://careers.snapmint.com/snapmint",
                 "domain": "careers.snapmint.com", "company_id": "MTYxMTc="}
"""
import json

API = "https://public.zwayam.com/jobs/search"


def fetch(c, h):
    offset = 0
    while offset < 2000:
        crit = {"paginationStartNo": offset, "selectedCall": "sort",
                "sortCriteria": {"name": "modifiedDate", "isAscending": False}, "anyOfTheseWords": ""}
        r = h.SESSION.post(API, files={"filterCri": (None, json.dumps(crit)), "domain": (None, c["domain"]),
                                       "companyId": (None, c["company_id"])}, timeout=40)
        r.raise_for_status()
        d = (r.json() or {}).get("data") or {}
        rows = [x.get("_source") or {} for x in d.get("data") or []]
        for s in rows:
            title = s.get("jobTitle") or ""
            india = [l.strip() for l in (s.get("location") or "").split(";") if h.in_india(l)]
            if not h.title_ok(title) or not india:
                continue
            lo, hi = s.get("minYearOfExperience"), s.get("maxYearOfExperience")
            years = f"Experience: {lo}-{hi if hi is not None else lo} years\n" if lo is not None else ""
            pay = ""
            if s.get("showSal") and s.get("minJobSalary") and s.get("currencyType") == "INR":  # only when the site shows it
                pay = f"INR {s['minJobSalary']} - INR {s.get('maxJobSalary') or s['minJobSalary']} per year"
            yield h.Job(c["name"], title, " / ".join(india), f"{c['base'].rstrip('/')}/job/{s.get('jobUrl')}",
                        h.parse_ts(s.get("jobCreatedDate")), years + h.strip_html(s.get("mediumDescription") or ""),
                        pay_posted=pay)
        offset += len(rows)
        if not rows or not d.get("hasMoreData") or offset >= (d.get("totalCount") or 0):
            break
