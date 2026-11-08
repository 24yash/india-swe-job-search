"""Darwinbox careers sites (<company>.darwinbox.in/ms/candidatev2/main/careers): the page loads its open jobs from
POST /ms/candidateapi/job/alljobs?companyId=main. It's the same public call the careers page makes; no token or sign-in.
(An older Darwinbox job endpoint answers 403 to scripts; this one doesn't.)
companies.json: {"ats": "portal", "portal": "darwinbox", "slug": "mobikwik", "tld": "in"}"""
import html as htmllib
from datetime import datetime, timezone


def fetch(c, h):
    base = f"https://{c['slug']}.darwinbox.{c.get('tld', 'in')}"
    company_id = c.get("company_id", "main")
    now = datetime.now(timezone.utc).timestamp()
    page, seen = 1, 0
    while page <= 20:
        # the careers page also sends companyId in the body; tenants with a hex id (PhysicsWallah) need it there
        d = h.post(f"{base}/ms/candidateapi/job/alljobs?companyId={company_id}", {"companyId": company_id, "page": page, "limit": 100},
                   headers={"Accept": "application/json"})
        rows = d.get("data") or []
        for j in rows:
            title = (j.get("title") or j.get("designation_display_name") or j.get("designation_name") or "").strip()
            loc = (j.get("locations") or j.get("officelocation_show_arr") or "").replace("\r", "").strip()
            until = ((j.get("job_posting") or {}).get("careers") or {}).get("to") if isinstance(j.get("job_posting"), dict) else None
            if (until and float(until) < now) or not h.title_ok(title) or not (h.in_india(loc) or (j.get("country") or "").lower() == "india"):
                continue
            exp = j.get("experience") or ""
            text = h.strip_html(htmllib.unescape(j.get("jd") or "")) + (f"\n\nExperience: {exp} years" if exp and "year" not in str(exp) else f"\n\nExperience: {exp}" if exp else "")
            yield h.Job(c["name"], title, loc or "India", f"{base}/ms/candidatev2/{company_id}/careers/jobDetails/{j['id']}",
                        h.parse_ts(j.get("created_on")), text, remote=str(j.get("is_remote")) == "1",
                        meta={"employmentType": j.get("emp_type_name") or ""})
        seen += len(rows)
        if not rows or seen >= int(d.get("job_counts") or 0):
            break
        page += 1
