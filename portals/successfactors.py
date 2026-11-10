"""SAP SuccessFactors career sites (Standard Chartered, Fujitsu, Alstom…): the site's job feed /sitemal.xml is one RSS
document with every open job (title, link, location "City, CC", expiry date, full description). robots.txt allows it
(it disallows /services/, so the site's search API is not used). One request per company; India and title are checked
before any description is decoded, which keeps the 20 MB feeds cheap.

companies.json: {"ats": "portal", "portal": "successfactors", "host": "jobs.standardchartered.com"}
"""
import html as htmllib
import re
from datetime import date

ITEM = re.compile(r"<item>(.*?)</item>", re.S)


def tag(block, name):
    m = re.search(rf"<{name}>(.*?)</{name}>", block, re.S)
    v = m.group(1).strip() if m else ""
    return htmllib.unescape(v[9:-3] if v.startswith("<![CDATA[") else v)


def fetch(c, h):
    r = h.SESSION.get(f"https://{c['host']}/sitemal.xml", timeout=90)
    r.raise_for_status()
    today = date.today().isoformat()
    for m in ITEM.finditer(r.text):
        block = m.group(1)
        loc = tag(block, "g:location")
        if loc.endswith(", IN"):  # these feeds use country codes, so "IN" is India; spell it out for later checks
            loc = loc[:-4] + ", India"
        elif not h.in_india(loc):
            continue
        title = re.sub(r"\s*\([^()]*\)\s*$", "", tag(block, "title"))  # titles end with " (City, CC)"
        expires = tag(block, "g:expiration_date")
        if not h.title_ok(title) or (expires and expires < today):
            continue
        yield h.Job(c["name"], title, loc, tag(block, "link"), None, h.strip_html(tag(block, "description")))
