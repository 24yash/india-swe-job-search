"""Zerodha: careers.zerodha.com loads its openings from its own public JSON (/api/jobs), one request, with the
description. The page itself sits behind a Cloudflare check in some browsers, but the list endpoint it calls answers plainly.
companies.json: {"name": "Zerodha", "ats": "portal", "portal": "zerodha"}"""
URL = "https://careers.zerodha.com/api/jobs"


def fetch(c, h):
    for j in (h.get(URL) or {}).get("data") or []:
        title, loc = (j.get("job_title") or "").strip(), j.get("location") or ""
        loc = loc if h.in_india(loc) else ""
        if not h.title_ok(title) or not loc:
            continue
        yield h.Job(c["name"], title, f"{loc}, India", f"https://careers.zerodha.com/#{j.get('name', '')}", None,
                    h.strip_html(j.get("description") or ""), remote=(j.get("location_type") or "").lower() == "remote")
