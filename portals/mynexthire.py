"""MyNextHire careers boards (<slug>.mynexthire.com, an Indian ATS; often embedded in an iframe on the company's own
careers page, e.g. Amagi). The board's own page POSTs to /employer/careers/reqlist/get and gets every open
requisition with title, location, min/max experience and the full description.

companies.json: {"ats": "portal", "portal": "mynexthire", "slug": "amagi"}
Optional "jd_page": the company page that shows one job (the board links there, e.g. "https://www.amagi.com/job-description");
without it, links go to the board's list page.
"""
import base64
import json

BODY = {"source": "careers", "code": "", "filterByBuId": -1, "filterByLocation": "", "filterByCompany": -1, "reqIds": [], "src": "careers"}


def link(c, req_id):
    board = f"https://{c['slug']}.mynexthire.com/employer/jobs/careers"
    if not c.get("jd_page"):
        return f"{board}#req{req_id}"
    p = {"pageType": "jd", "cvSource": "careers", "reqId": req_id, "requester": {"id": "", "code": "", "name": ""},
         "page": "careers", "bufilter": -1, "customFields": {}}
    return f"{c['jd_page']}?src%3Dcareers%26p%3D{base64.b64encode(json.dumps(p, separators=(',', ':')).encode()).decode()}"


def fetch(c, h):
    r = h.SESSION.post(f"https://{c['slug']}.mynexthire.com/employer/careers/reqlist/get", json=BODY, timeout=30)
    r.raise_for_status()
    for j in r.json().get("reqDetailsBOList") or []:
        title = (j.get("reqTitle") or "").strip()
        locs = [l.get("office") or l.get("address") or "" for l in j.get("locationList") or []] or [j.get("location") or ""]
        loc = " / ".join(x for x in locs if x)
        if not h.title_ok(title) or not (h.in_india(loc) or "india" in loc.lower()):
            continue
        exp = ""
        if j.get("expMin") is not None and j.get("expMax"):
            exp = f"Experience: {j['expMin']:g}-{j['expMax']:g} years\n\n"  # the board's own range, read by the experience parser
        yield h.Job(c["name"], title, loc, link(c, j.get("reqId")), h.parse_ts(j.get("approvedOn")),
                    exp + (j.get("jdDisplay") or ""), meta={"employmentType": j.get("employmentType") or ""})
