"""Workable careers pages (apply.workable.com/<slug>): the public widget feed lists jobs; one detail call per fitting
India role gives the description. companies.json: {"ats": "portal", "portal": "workable", "slug": "trexquant"}"""


def fetch(c, h):
    slug = c["slug"]
    for j in h.get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}").get("jobs") or []:
        locs = [", ".join(x for x in (l.get("city"), l.get("region"), l.get("country")) if x) for l in j.get("locations") or []] \
            or [", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)]
        india = [l for l in locs if h.in_india(l) or "india" in l.lower()]
        if not h.title_ok(j.get("title", "")) or not india:
            continue
        try:
            d = h.get(f"https://apply.workable.com/api/v2/accounts/{slug}/jobs/{j['shortcode']}")
        except Exception:
            continue
        text = "\n".join(h.strip_html(d.get(k) or "") for k in ("description", "requirements"))
        yield h.Job(c["name"], j["title"], " / ".join(india), j.get("url") or f"https://apply.workable.com/{slug}/j/{j['shortcode']}/",
                    h.parse_ts(j.get("published_on") or j.get("created_at")), text, remote=bool(j.get("telecommuting")),
                    meta={"employmentType": j.get("employment_type") or ""})
