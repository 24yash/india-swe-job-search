"""Gem job boards (jobs.gem.com/<slug>): the public job-board API lists every post with offices and plain-text
description. Used by Groq, PromptQL. companies.json: {"ats": "portal", "portal": "gem", "slug": "groq"}"""


def fetch(c, h):
    for j in h.get(f"https://api.gem.com/job_board/v0/{c['slug']}/job_posts/") or []:
        locs = [(o.get("location") or {}).get("name") or o.get("name") or "" for o in j.get("offices") or []] or [(j.get("location") or {}).get("name") or ""]
        india = [l for l in locs if h.in_india(l) or "india" in l.lower()]
        if not h.title_ok(j.get("title", "")) or not india:
            continue
        yield h.Job(c["name"], j["title"].strip(), " / ".join(india), j.get("absolute_url") or "", h.parse_ts(j.get("first_published_at")),
                    j.get("content_plain") or h.strip_html(j.get("content") or ""), remote=j.get("location_type") == "remote",
                    meta={"employmentType": j.get("employment_type") or ""})
