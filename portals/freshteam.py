"""Freshteam careers pages (<slug>.freshteam.com/jobs): the public jobs widget feed, with descriptions and branches
(office locations). companies.json: {"ats": "portal", "portal": "freshteam", "slug": "zolve"}"""


def fetch(c, h):
    d = h.get(f"https://{c['slug']}.freshteam.com/hire/widgets/jobs.json")
    branches = {str(b.get("id")): ", ".join(x for x in (b.get("city"), b.get("state"), b.get("country_name")) if x) for b in d.get("branches") or []}
    for j in d.get("jobs") or []:
        loc = branches.get(str(j.get("branch_id")), "")
        if str(j.get("deleted")).lower() == "true" or not h.title_ok(j.get("title", "")) or not (h.in_india(loc) or "india" in loc.lower()):
            continue
        yield h.Job(c["name"], j["title"], loc or "India", j.get("url") or "", h.parse_ts(j.get("created_at")),
                    h.strip_html(j.get("description") or ""), remote=str(j.get("remote")).lower() == "true")
