"""Jobvite careers sites (jobs.jobvite.com/<slug>): the server-rendered "view all" page lists every job with its title
and location, in either theme (a table, or a list of links). Only fitting India roles cost a detail request; the job page
carries the description and schema.org JobPosting data (posting date).

companies.json: {"ats": "portal", "portal": "jobvite", "slug": "aryaka"}
"""
import html as htmllib
import re

from portals.sitemap import job_postings, place

# One block per job: the link may wrap the name (list theme) or sit inside it (table theme); the location follows.
# A multi-location job shows only "<div class="jv-meta">2 Locations</div>"; its places come from the job page.
ITEM = re.compile(r'href="(/[^"/]+/job/[A-Za-z0-9]+)"[^>]*>\s*(?:<[^>]+>\s*)*?(?:<div class="jv-job-list-name">)?\s*([^<]+?)\s*<'
                  r'.{0,400}?jv-job-list-location">\s*(?:<div class="jv-meta">)?\s*([^<]*?)\s*<', re.S)
MULTI = re.compile(r"^\d+ locations?$", re.I)


def items(page):
    """(path, title, location) for every job on a "view all" page; location "" when the list only gives a count."""
    out = []
    for p, t, l in ITEM.findall(page):
        l = re.sub(r"\s+", " ", htmllib.unescape(l)).strip()
        out.append((p, htmllib.unescape(t).strip(), "" if MULTI.match(l) else l))
    return out


def fetch(c, h):
    base = "https://jobs.jobvite.com"
    r = h.SESSION.get(f"{base}/{c['slug']}/jobs/viewall", timeout=30)
    r.raise_for_status()
    for path, title, loc in dict.fromkeys(items(r.text)):
        if not h.title_ok(title) or (loc and not h.in_india(loc)):
            continue
        url = base + path
        try:
            page = h.SESSION.get(url, timeout=30).text
        except Exception:
            continue  # closed between the list and the detail call
        jp = next(iter(job_postings(page)), {})
        if not loc:  # multi-location job: keep it only if one of its places is in India
            loc = " / ".join(dict.fromkeys(x for x in place(jp) if h.in_india(x)))
            if not loc:
                continue
        i = page.find("jv-job-detail-description")
        text = h.strip_html(jp.get("description") or (page[i:i + 60000] if i >= 0 else ""))
        yield h.Job(c["name"], title, loc, url, h.parse_ts((jp.get("datePosted") or "")[:10] or None), text)
