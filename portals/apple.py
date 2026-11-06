"""Apple: jobs.apple.com renders its search and job pages on the server with the data embedded as JSON
(window.__staticRouterHydrationData). India search, 20 per page; one detail page per fitting role."""
import json
import re

BASE = "https://jobs.apple.com/en-in"


def page_data(h, url):
    r = h.SESSION.get(url, timeout=30)
    r.raise_for_status()
    m = re.search(r'window\.__staticRouterHydrationData\s*=\s*JSON\.parse\("(.*?)"\);', r.text, re.S)
    return json.loads(json.loads('"' + m.group(1) + '"'))["loaderData"] if m else {}


def fetch(c, h):
    seen = set()
    for query in ("software engineer", "backend engineer"):
        for page in range(1, 15):
            res = page_data(h, f"{BASE}/search?location=india-INDC&search={query.replace(' ', '%20')}&page={page}").get("search") or {}
            rows = res.get("searchResults") or []
            for j in rows:
                if j["positionId"] in seen or not h.title_ok(j.get("postingTitle", "")):
                    continue
                seen.add(j["positionId"])
                url = f"{BASE}/details/{j['positionId']}/{j.get('transformedPostingTitle') or 'job'}"
                try:
                    d = page_data(h, url).get("jobDetails", {}).get("jobsData") or {}
                except Exception:
                    continue
                text = "\n".join(h.strip_html(d.get(k) or "") for k in ("jobSummary", "description", "minimumQualifications", "preferredQualifications"))
                locs = " / ".join(dict.fromkeys(", ".join(filter(None, [l.get("city") or l.get("name"), l.get("stateProvince"), l.get("countryName")]))
                                                for l in (d.get("locations") or j.get("locations") or []))) or "India"
                yield h.Job(c["name"], j["postingTitle"], locs, url, h.parse_ts(j.get("postDateInGMT")), text,
                            remote=bool(j.get("homeOffice")))
            if len(rows) < 20:
                break
