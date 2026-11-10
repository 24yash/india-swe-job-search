"""Zappyhire careers pages (recruitcareers.zappyhire.com/en/<slug>): the page loads its list from the tenant's public
search API (12 per page; title, location, posting time) and each job from a detail call (description, years asked).

companies.json: {"ats": "portal", "portal": "zappyhire", "slug": "credgenics"}
"""


def fetch(c, h):
    slug = c["slug"]
    api = f"https://{slug}.zappyhire-multitenant-be-prod.zappyhire.com/api"
    hits, page = [], 1
    while page <= 20:  # the site pages 12 at a time; larger page sizes return nothing
        res = h.get(f"{api}/jobs/jobsearch/", params={"page": page, "page_size": 12}).get("results") or {}
        batch = res.get("hits") or []
        hits += batch
        if len(batch) < 12 or len(hits) >= (res.get("total") or {}).get("value", 0):
            break
        page += 1
    for hit in hits:
        s = hit.get("_source") or {}
        title, loc = s.get("title") or "", (s.get("location") or "").replace(",", " / ")
        if not h.title_ok(title) or not h.in_india(loc):
            continue
        try:
            d = h.get(f"{api}/careers/jobs/{s['job']}/").get("results") or {}
        except Exception:
            continue  # closed between the list and the detail call
        years = f"Experience: {d['experience']}-{d.get('max_experience') or d['experience']} years\n" if d.get("experience") else ""
        yield h.Job(c["name"], title, loc, f"https://recruitcareers.zappyhire.com/en/{slug}/apply?job={s['job']}",
                    h.parse_ts((d.get("job_publish_date") or "")[:19] + "+00:00" if d.get("job_publish_date") else (hit.get("sort") or [None])[0]),
                    years + h.strip_html(d.get("description") or ""))
