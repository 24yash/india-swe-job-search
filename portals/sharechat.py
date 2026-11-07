"""ShareChat / Moj: sharechat.com/careers loads openings from /api/careersList (grouped by department, with years
asked and posting date, no description). The apply link is the MyNextHire job page the careers site links to."""
import base64
import json
from datetime import datetime, timezone

API = "https://sharechat.com/api/careersList"


def link(req_id):
    p = {"pageType": "jd", "cvSource": "careers", "reqId": req_id, "requester": {"id": "", "code": "", "name": ""},
         "page": "careers", "bufilter": -1, "customFields": {}}
    token = base64.b64encode(json.dumps(p, separators=(",", ":")).encode()).decode()
    return f"https://sharechat.mynexthire.com/employer/jobs?src=careers&p={token}"


def fetch(c, h):
    params, seen = {"limit": 100}, set()
    for _ in range(20):
        d = h.get(API, params=params, headers={"Referer": "https://sharechat.com/careers"}).get("data") or {}
        for group in d.get("careersList") or []:
            for j in group.get("data") or []:
                locs = j.get("officeLocationNames") or []
                title = (j.get("requisitionTitle") or "").strip()
                if j["requisitionId"] in seen or not h.title_ok(title) or not any(h.in_india(l) for l in locs):
                    continue
                seen.add(j["requisitionId"])
                lo, hi = j.get("yrsOfExpMin"), j.get("yrsOfExpMax")
                text = f"{title}. {group.get('title', '')} team. Requires {lo}-{hi} years of experience." if lo is not None else title
                posted = datetime.fromtimestamp(j["createdDate"] / 1000, timezone.utc) if j.get("createdDate") else None
                yield h.Job(c["name"], title, " / ".join(locs), link(j["requisitionId"]), posted, text,
                            meta={"commitment": j.get("employmentType") or ""})
        if not d.get("hasNext") or not d.get("offsetToken"):
            break
        params = {"limit": 100, "offsetToken": d["offsetToken"]}
