"""Cornerstone OnDemand career sites (<corp>.csod.com/ux/ats/careersite/<id>): the career page embeds a short-lived
public token and its API region; the page's own job search posts to <cloud>/rec-job-search/external/jobs with it.
Same anonymous calls the page makes, nothing else. Used by Linde (site 25 lists the India jobs).
companies.json: {"ats": "portal", "portal": "csod", "corp": "linde", "site": 25}"""
import re

BODY = {"pageNumber": 1, "pageSize": 100, "cultureId": 1, "cultureName": "en-US", "searchText": "", "states": [], "countryCodes": [],
        "cities": [], "placeID": "", "radius": None, "postingsWithinDays": None, "customFieldCheckboxKeys": [],
        "customFieldDropdowns": [], "customFieldRadios": []}


def fetch(c, h):
    home = f"https://{c['corp']}.csod.com/ux/ats/careersite/{c['site']}/home?c={c['corp']}"
    page = h.SESSION.get(home, timeout=30).text
    token, cloud = re.search(r'"token"\s*:\s*"([^"]+)"', page).group(1), re.search(r'"cloud"\s*:\s*"([^"]+)"', page).group(1).rstrip("/")
    seen, n = 0, 1
    while n <= 30:
        r = h.SESSION.post(f"{cloud}/rec-job-search/external/jobs", json={**BODY, "careerSiteId": c["site"], "careerSitePageId": c["site"], "pageNumber": n},
                           headers={"Authorization": f"Bearer {token}"}, timeout=40)
        r.raise_for_status()
        d = r.json().get("data") or {}
        rows = d.get("requisitions") or []
        for j in rows:
            title = (j.get("displayJobTitle") or "").strip()
            locs = [", ".join(x for x in (l.get("city"), l.get("state"), l.get("country")) if x) for l in j.get("locations") or []]
            india = [l for l in locs if h.in_india(l) or l.endswith(", IN")]
            if not h.title_ok(title) or not india:
                continue
            yield h.Job(c["name"], title, " / ".join(india),
                        f"https://{c['corp']}.csod.com/ux/ats/careersite/{c['site']}/home/requisition/{j['requisitionId']}?c={c['corp']}",
                        h.parse_ts(_us_date(j.get("postingEffectiveDate"))), h.strip_html(j.get("externalDescription") or ""))
        seen += len(rows)
        if not rows or seen >= int(d.get("totalCount") or 0):
            break
        n += 1


def _us_date(s):
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else None
