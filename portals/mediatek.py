"""MediaTek careers (careers.mediatek.com): the site's own tRPC endpoint job.getJobs lists every job with its description,
city (properties.location.code) and experience band, 100 per page, so no detail calls are needed.

companies.json: {"ats": "portal", "portal": "mediatek"}
"""
import json

API = "https://careers.mediatek.com/api/trpc/job.getJobs"


def page(h, n):
    q = {"0": {"json": {"locales": "en_US", "page": n, "jobQueryInfo": {}, "sortBy": "publishedDate", "order": "DESC", "limit": 100,
                        "filters": {"categorys": [], "workExperiences": [], "locations": [], "programs": []}}}}
    return h.get(API, params={"batch": 1, "input": json.dumps(q)})[0]["result"]["data"]["json"]


def fetch(c, h):
    n, last = 1, 1
    while n <= min(last, 30):
        d = page(h, n)
        last = (d.get("pagination") or {}).get("total_pages") or 1
        for j in d.get("jobs") or []:
            props = j.get("properties") or {}
            loc = (((props.get("location") or {}).get("code")) or "").strip()  # city names carry a stray tab
            if j.get("jobPostStatus") not in (None, "posted") or not h.title_ok(j.get("title") or "") or not h.in_india(loc):
                continue
            band = (props.get("workExperience") or {}).get("code") or ""
            yield h.Job(c["name"], j["title"], loc, f"https://careers.mediatek.com/en/jobs/{j['id']}", h.parse_ts((j.get("publishedDate") or "")[:10] or None),
                        (f"Experience: {band}\n" if band else "") + h.strip_html(j.get("description") or ""))
        n += 1
