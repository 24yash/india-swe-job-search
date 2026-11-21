"""BillDesk (www.billdesk.com/web/careers): a Vite single-page app whose job list is hard-coded in its JS bundle, inside
the site's text table (JSON.parse(`{..."currentOpenings":[{jobId, jobHeader, location, info, responsiblities,
qualifications, skills, description, desire, goodtohave}, ...]...}`)).

companies.json: {"name": "Billdesk", "ats": "portal", "portal": "billdesk", "url": "https://www.billdesk.com/web/careers"}

Two GETs: the careers page (for the bundle's hashed name, /web/assets/index-<hash>.js, which changes with every
release) and the bundle. Nothing in the bundle is run: the array is read as JSON. A page without the bundle tag,
or a bundle without the "currentOpenings" array, raises (a broken read must not look like "every role closed").
There is no page per job, so each link is the careers page + "#<slug of the title>"; applying is by email. A title
listed in more than one place keeps one job per place, and every copy's key carries its place's slug
("#java-developer-pune"), so no key depends on the order of the list; an exact repeat (same title and place) is one job.
"""
import json
import re
import time
from urllib.parse import urljoin

from portals.jsonlist import clean

BUNDLE = re.compile(r'<script\b[^>]{0,300}\bsrc="(/web/assets/index-[\w-]{4,40}\.js)"', re.I)
KEY = re.compile(r'"currentOpenings"\s*:\s*(?=\[)')


def openings(js):
    m = KEY.search(js)
    if not m:
        return None
    rest = js[m.end():]
    for text in (rest, rest.replace("\\'", "'").replace("\\`", "`")):
        try:
            arr, _ = json.JSONDecoder().raw_decode(text)
            return arr if isinstance(arr, list) else None
        except ValueError:
            continue
    return None


def bundle_url(page_url, page):
    m = BUNDLE.search(page)
    return urljoin(page_url, m.group(1)) if m else None


def get_text(h, url):
    r = h.SESSION.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def lines(v):
    v = v if isinstance(v, list) else [v] if v else []
    return "\n".join(f"- {x}" if len(v) > 1 else str(x) for x in v if isinstance(x, (str, int, float)))


def fetch(c, h):
    page_url = c.get("url", "https://www.billdesk.com/web/careers")
    src = bundle_url(page_url, get_text(h, page_url))
    if not src:
        raise ValueError(f"no index-<hash>.js bundle named in {page_url} (site rebuilt?)")
    time.sleep(c.get("delay", 1))
    jobs = openings(get_text(h, src))
    if jobs is None:
        raise ValueError(f"no currentOpenings array in {src}")
    def slug(s):
        return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

    rows = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        title = re.sub(r"\s+", " ", clean(h, str(j.get("jobHeader") or ""))).strip()
        loc = clean(h, str(j.get("location") or ""))
        if title and h.title_ok(title) and h.in_india(loc):
            rows.append((j, title, loc))
    places = {}
    for _, title, loc in rows:
        places.setdefault(slug(title), set()).add(slug(loc))
    seen = set()
    for j, title, loc in rows:
        key = slug(title)
        if len(places[key]) > 1:
            key = f"{key}-{slug(loc)}"
        if key in seen:
            continue  # same title, same place: one job
        seen.add(key)
        info = clean(h, str(j.get("info") or ""))  # "4 to 7 years | Corporate Development | Mumbai"
        years = re.match(r"\s*(\d{1,2})\s*(?:to|-)\s*(\d{1,2})\s*years", info, re.I)
        parts = [f"Experience: {years.group(1)}-{years.group(2)} years" if years else info]
        for field, label in (("description", ""), ("responsiblities", "Responsibilities"), ("qualifications", "Qualifications"),
                             ("skills", "Skills"), ("desire", "Desired"), ("goodtohave", "Good to have")):
            body = clean(h, lines(j.get(field)))
            if body:
                parts.append(f"{label}:\n{body}" if label else body)
        yield h.Job(c["name"], title, loc if re.search(r"india", loc, re.I) else f"{loc}, India", f"{page_url}#{key}", None,
                    "\n\n".join(parts), meta={"jobId": str(j.get("jobId") or ""), "department": str(j.get("department") or "")})
