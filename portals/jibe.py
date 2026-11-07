"""iCIMS Jibe careers sites (careers.amd.com, careers.docusign.com…): the site's own search feed, /api/jobs,
returns jobs with full descriptions. companies.json: {"ats": "portal", "portal": "jibe", "host": "careers.amd.com"}"""


def fetch(c, h):
    seen = set()
    for keywords in ("software engineer", "software developer", "backend"):
        for page in range(1, 11):
            d = h.get(f"https://{c['host']}/api/jobs", params={"keywords": keywords, "location": "India", "page": page, "limit": 100})
            rows = d.get("jobs") or []
            for row in rows:
                j = row.get("data", row)
                if j.get("req_id") in seen or (j.get("country") or "").lower() != "india" or not h.title_ok(j.get("title", "")):
                    continue
                seen.add(j.get("req_id"))
                text = "\n".join(h.strip_html(j.get(k) or "") for k in ("description", "qualifications", "responsibilities"))
                loc = ", ".join(x for x in (j.get("city"), j.get("state"), "India") if x)
                yield h.Job(c["name"], j["title"], loc, f"https://{c['host']}/jobs/{j.get('slug') or j.get('req_id')}?lang=en-us",
                            h.parse_ts(j.get("posted_date")), text, meta={"employmentType": str(j.get("employment_type") or "")})
            if len(rows) < 100:
                break
