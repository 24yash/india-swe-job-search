"""PyjamaHR careers pages (jobs.pyjamahr.com/<slug>): the public career API lists jobs (title, locations, years asked);
each job page carries schema.org JobPosting data (description, posting date). Unknown slugs answer with 0 jobs, so
take the slug from a job link on the company's own careers page.

companies.json: {"ats": "portal", "portal": "pyjamahr", "slug": "zoid-technologies-pvt-ltd"}
"""
import ast
import json

from portals.sitemap import job_postings


def parse_list(v):
    """other_locations arrives as a list, a JSON string or a Python-literal string; anything unreadable counts as none."""
    if isinstance(v, list):
        return v
    for parse in (json.loads, ast.literal_eval):
        try:
            out = parse(v) if isinstance(v, str) else None
            return out if isinstance(out, list) else []
        except (ValueError, SyntaxError):
            continue
    return []


def fetch(c, h):
    slug, page, jobs = c["slug"], 1, []
    while page <= 20:
        d = h.get("https://api.pyjamahr.com/api/career/jobs/", params={"company_slug": slug, "page": page})
        jobs += d.get("results") or []
        if not d.get("next"):
            break
        page += 1
    for j in jobs:
        others = parse_list(j.get("other_locations"))
        locs = [j.get("location") or j.get("country") or ""] + [o if isinstance(o, str) else o.get("location", "") for o in others]
        india = [l for l in locs if h.in_india(l)]
        if not h.title_ok(j.get("title") or "") or not india:
            continue
        url = f"https://jobs.pyjamahr.com/{slug}/{j['slug']}"
        try:
            jp = next(iter(job_postings(h.SESSION.get(url, timeout=30).text)), {})
        except Exception:
            continue  # closed between the list and the detail call
        lo, hi = j.get("min_experience"), j.get("max_experience")
        years = f"Experience: {float(lo):g}-{float(hi or lo):g} years\n" if lo not in (None, "") else ""
        yield h.Job(c["name"], j["title"], " / ".join(india), url, h.parse_ts((jp.get("datePosted") or "")[:10] or None),
                    years + h.strip_html(jp.get("description") or ""), remote=j.get("workplace_type") == "REMOTE")
