"""Trakstar Hire (formerly Recruiterbox) boards: the public widget feed jsapi.recruiterbox.com/v1/openings lists every
opening with location and description (robots.txt allows it). Used by ALLEN Digital, Drip Capital, WinZO.
companies.json: {"ats": "portal", "portal": "recruiterbox", "slug": "winzogames"}"""


def fetch(c, h):
    offset = 0
    while offset < 2000:
        d = h.get(f"https://jsapi.recruiterbox.com/v1/openings?client_name={c['slug']}&limit=100&offset={offset}")
        rows = d.get("objects") or []
        for j in rows:
            l = j.get("location") or {}
            loc = ", ".join(x for x in (l.get("city"), l.get("state"), l.get("country")) if x)
            if not h.title_ok(j.get("title", "")) or not (h.in_india(loc) or "india" in loc.lower()):
                continue
            yield h.Job(c["name"], j["title"].strip(), loc, j.get("hosted_url") or "", None, h.strip_html(j.get("description") or ""),
                        remote=bool(j.get("allows_remote")), meta={"employmentType": j.get("position_type") or ""})
        offset += len(rows)
        if not rows or offset >= int((d.get("meta") or {}).get("total") or 0):
            break
