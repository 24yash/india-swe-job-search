"""Avature careers sites (EA, Macquarie…): the server-rendered SearchJobs list, paged with jobOffset. Each list item carries
the job link, title and location, so only fitting India roles cost a detail request. Reading every page matters: the
first page alone made these companies look like they had no openings.

companies.json: {"ats": "portal", "portal": "avature", "base": "https://jobs.ea.com/en_US/careers"}
Optional "list_path" (default "SearchJobs"; Two Sigma: "ExperiencedRoles"), "searches" (site keyword searches, default
["engineer", "developer"]), "per_page" (default 20; sites may cap it lower), "max_pages" per search (default 80).
"""
import html as htmllib
import re

ARTICLE = re.compile(r'<article class="article article--result.*?</article>', re.S)
LINK = re.compile(r'<a [^>]*href="(https?://[^"]+/JobDetail[^"]*)"[^>]*>\s*([^<]+?)\s*</a>')
# themes differ: <span class="list-item-location">City</span> (EA) or an icon whose alt says "Location", then <p>City</p> (Macquarie)
# or a bare <span class="paragraph_inner-span">Country - City</span> (Two Sigma), or a labelled field
# <div class="...label"> Location: </div> <div class="...value"> City </div> (Koch)
LOC = (re.compile(r'list-item-location">\s*([^<]+?)\s*<'), re.compile(r'(?i)location[^<>]*>\s*(?:<(?!/?a\b)[^>]*>\s*)*([^<>]{2,160}?)\s*<'),
       re.compile(r'paragraph_inner-span">\s*([^<]+?)\s*<'), re.compile(r'Location:\s*</div>\s*<div[^>]*>\s*([^<]+?)\s*<'))


def items(page):
    out = []
    for block in ARTICLE.findall(page):
        m = LINK.search(block)
        if not m:
            continue
        loc = next((x.group(1) for x in (p.search(block) for p in LOC) if x), "")
        out.append((m.group(1), htmllib.unescape(m.group(2)), htmllib.unescape(loc)))
    return out


def fetch(c, h):
    base, per = c["base"].rstrip("/"), c.get("per_page", 20)
    seen = {}
    # The site's own keyword search (it matches descriptions too) keeps a refresh to the engineering slice:
    # Macquarie 570 jobs / 64 pages -> ~23 pages. "searches": [""] reads everything.
    for q in c.get("searches", ["engineer", "developer"]):
        offset, last = 0, None
        for _ in range(c.get("max_pages", 80)):
            # "list_path": sites that name their list page differently (Two Sigma: ExperiencedRoles)
            r = h.SESSION.get(f"{base}/{c.get('list_path', 'SearchJobs')}/?search={q}&jobRecordsPerPage={per}&jobOffset={offset}", timeout=40)
            if r.status_code == 404 and offset:
                break  # past the last page some sites redirect to an error page
            r.raise_for_status()
            got = items(r.text)
            if not got or [x[0] for x in got] == last:
                break  # end of the list, or a site that ignores the offset
            last = [x[0] for x in got]
            for u, t, l in got:
                seen.setdefault(u, (t, l))
            offset += len(got)  # sites cap the page size (Macquarie shows 9), so step by what came back
    for url, (title, loc) in seen.items():
        if not h.title_ok(title) or not (h.in_india(loc) or "india" in loc.lower()):
            continue
        try:
            page = h.SESSION.get(url, timeout=30).text
            i = page.find("article__content")
            text = h.strip_html(page[i:i + 60000]) if i >= 0 else ""
        except Exception:
            text = ""
        yield h.Job(c["name"], title, loc, url, None, text)
