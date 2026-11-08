"""BambooHR careers pages (<slug>.bamboohr.com/careers): /careers/list gives every opening with its location; one
detail call per fitting India role gives the description. companies.json: {"ats": "portal", "portal": "bamboohr", "slug": "bitly"}"""


def fetch(c, h):
    base = f"https://{c['slug']}.bamboohr.com/careers"
    for j in h.get(f"{base}/list").get("result") or []:
        a, l = j.get("atsLocation") or {}, j.get("location") or {}
        loc = ", ".join(x for x in (a.get("city") or l.get("city"), a.get("state") or l.get("state"), a.get("country")) if x)
        title = (j.get("jobOpeningName") or "").strip()
        if not h.title_ok(title) or not (h.in_india(loc) or "india" in loc.lower()):
            continue
        try:
            d = (h.get(f"{base}/{j['id']}/detail").get("result") or {}).get("jobOpening") or {}
        except Exception:
            d = {}
        yield h.Job(c["name"], title, loc, f"{base}/{j['id']}", h.parse_ts(d.get("datePosted")), h.strip_html(d.get("description") or ""),
                    remote=bool(j.get("isRemote")), meta={"employmentType": j.get("employmentStatusLabel") or ""})
