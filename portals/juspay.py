"""Juspay: juspay.io/careers loads every opening (with description and years asked) from joinus.juspay.in.
The page has no per-job URL, so the link is the careers page with the job id (opens the careers page)."""
API = "https://joinus.juspay.in/api/careerJobOpening"
INDIA_CITIES = ("bangalore", "bengaluru", "mumbai", "pune", "hyderabad", "delhi", "gurgaon", "chennai", "india")


def fetch(c, h):
    rows = h.get(API, params={"limit": 1000}, headers={"Origin": "https://juspay.io", "Referer": "https://juspay.io/"}).get("allJobs") or []
    for r in rows:
        loc = r.get("job_location") or ""
        if str(r.get("opening_status")).lower() != "true" or not h.title_ok(r.get("job_title", "")) \
                or not any(k in loc.lower() for k in INDIA_CITIES):
            continue
        years = r.get("experience_year")
        text = (r.get("job_description_career") or "") + (f"\n\nRequires {years}+ years of experience." if years not in (None, "") else "")
        yield h.Job(c["name"], r["job_title"].strip(), f"{loc}, India", f"https://juspay.io/careers?job={r['job_id']}", None, text,
                    meta={"commitment": r.get("job_type") or ""})
