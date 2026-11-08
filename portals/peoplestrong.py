"""PeopleStrong (Altone) candidate portals (<company>careers.peoplestrong.com, used by L&T and other Indian employers):
the portal's own list call, POST /api/cp/rest/altone/cp/jobs/v1?offset=&limit=100 with an empty JSON body, returns
every requisition with title, location path, experience range and skills (no description in the list).
companies.json: {"ats": "portal", "portal": "peoplestrong", "host": "larsentoubrocareers.peoplestrong.com"}"""


def fetch(c, h):
    base, offset = f"https://{c['host']}", 0
    while offset < 10000:
        r = h.SESSION.post(f"{base}/api/cp/rest/altone/cp/jobs/v1?offset={offset}&limit=100", json={}, timeout=40)
        r.raise_for_status()
        d = r.json()
        rows = d.get("response") or []
        for j in rows:
            title, loc = (j.get("jobTitle") or "").strip(), (j.get("locationHierarchyComplete") or "").replace(">", ", ")
            if not h.title_ok(title) or not (h.in_india(loc) or loc.lower().startswith("india")):
                continue
            sk = j.get("skills") or {}
            text = f"Experience: {j['expRange']}\n\n" if j.get("expRange") else ""
            text += "Skills: " + ", ".join(str(x) for x in (sk.get("mustTohave") or []) + (sk.get("goodtohave") or []) if x) if isinstance(sk, dict) else ""
            yield h.Job(c["name"], title, loc, j.get("jobDetailUrl") or f"{base}/job/detail/{j.get('jobCode') or j.get('requisitionId')}",
                        h.parse_ts(j.get("jobPostedDate")), text, meta={"employmentType": ""})
        offset += len(rows)
        if not rows or offset >= int(d.get("totalRecords") or 0):
            break
