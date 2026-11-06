"""Urban Company: careers.urbancompany.com loads all openings (with descriptions) from one public POST call."""
API = "https://www.urbanclap.com/api/v2/platform-gateway/getAllJobs"


def fetch(c, h):
    jobs = h.post(API, {}, headers={"Origin": "https://careers.urbancompany.com", "Referer": "https://careers.urbancompany.com/"}).get("jobs") or []
    for j in jobs:
        locs = j.get("location") or []
        if not h.title_ok(j.get("job_title", "")) or not any(h.in_india(l) for l in locs):
            continue
        yield h.Job(c["name"], j["job_title"], " / ".join(locs), f"https://careers.urbancompany.com/jobDetail?id={j['job_id']}",
                    None, h.strip_html(j.get("job_description") or ""))
