"""Careers lists served by a site's own JSON "filter stream" (Keywords Studios, which also lists Helpshift's roles): the
browse page names a feed token, /ajax/filter_stream/<token>/?offset&limit returns jobs with url, title and location;
JobPosting data on the job page gives date and description (fetched only for fitting India roles).
companies.json: {"ats": "portal", "portal": "filterstream", "page": "https://www.keywordsstudios.com/en/careers/browse-careers/"}"""
import re
from urllib.parse import urlparse

from portals import sitemap


def fetch(c, h):
    page = h.SESSION.get(c["page"], timeout=30).text
    token = re.search(r"filter_stream\\?/([A-Za-z0-9=_-]+)", page).group(1)
    host = f"https://{urlparse(c['page']).netloc}"
    offset, rows = 0, []
    while offset < 5000:
        got = h.get(f"{host}/ajax/filter_stream/{token}/?offset={offset}&limit=50")
        rows += got
        if len(got) < 50:
            break
        offset += 50
    for j in rows:
        raw = j.get("location") or ""
        raw = " / ".join(str(x) for x in raw) if isinstance(raw, list) else str(raw)
        title, loc = (j.get("title") or "").strip(), ", ".join(p for p in raw.split("\n") if p)
        if not h.title_ok(title) or not (h.in_india(loc) or "india" in loc.lower()):
            continue
        posted, text = None, h.strip_html(j.get("text") or "")
        try:
            jp = sitemap.job_postings(h.SESSION.get(j["url"], timeout=30).text)
            if jp:
                posted, text = h.parse_ts(jp[0].get("datePosted")), h.strip_html(jp[0].get("description") or text)
        except Exception:
            pass
        yield h.Job(c["name"], title, loc, j.get("url") or "", posted, text)
