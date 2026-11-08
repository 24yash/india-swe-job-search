"""Spire2Grow / iXchange career portals (Tata Communications): the portal asks io.spire2grow.com for its workspace id by
domain, then lists requisitions with that id in a header. Public calls, no sign-in.
companies.json: {"ats": "portal", "portal": "spire2grow", "domain": "jobs.tatacommunications.com"}"""
API = "https://io.spire2grow.com/ies/v1/p"


def fetch(c, h):
    ws = c.get("workspace") or h.SESSION.get(f"{API}/workspaceId?domain={c['domain']}", timeout=30).text.strip().strip('"')
    hdr = {"WorkspaceId": ws, "language": "en", "Accept": "application/json"}
    page = 1
    while page <= 40:
        r = h.SESSION.get(f"{API}/requisition/_search?page={page}&size=50&selectedSortOrder=desc&selectedSortField=postedOn", headers=hdr, timeout=40)
        r.raise_for_status()
        d = r.json()
        rows = d.get("entities") or []
        for j in rows:
            title = (j.get("jobTitle") or "").strip()
            locs = [l.get("fqLocationName") or ", ".join(x for x in (l.get("city"), l.get("state"), l.get("country")) if x) for l in j.get("jobLocation") or []]
            india = [l for l in locs if h.in_india(l) or "india" in l.lower()]
            if not h.title_ok(title) or not india:
                continue
            exp = j.get("requiredExperienceInMonths") or {}
            text = f"Experience: {exp['from'] // 12}-{exp['to'] // 12} years\n\n" if exp.get("from") is not None and exp.get("to") else ""
            yield h.Job(c["name"], title, " / ".join(india), f"https://{c['domain']}/#/job/{j.get('id')}", h.parse_ts(j.get("createdOn")),
                        text + h.strip_html(j.get("jobDescription") or ""), meta={"employmentType": j.get("employmentType") or ""})
        if len(rows) < 50 or page * 50 >= int(d.get("total") or 0):
            break
        page += 1
