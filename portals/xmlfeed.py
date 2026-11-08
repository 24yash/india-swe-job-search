"""Careers sites that publish every job in one Indeed-style XML feed (<source><job><title/><url/><city/><country/>
<date/><description/></job>…): Fidelity Investments, Box (both at /en/jobs/xml/?rss=true). One request reads the whole
list, so "no India openings" from this reader is a real answer, not a first-page guess.

companies.json: {"ats": "portal", "portal": "xmlfeed", "feed": "https://jobs.fidelity.com/en/jobs/xml/?rss=true"}
"""
import html as htmllib
import re


def field(block, tag):
    m = re.search(rf"<{tag}>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</{tag}>", block, re.S | re.I)
    return htmllib.unescape(m.group(1).strip()) if m else ""


def fetch(c, h):
    r = h.SESSION.get(c["feed"], timeout=90)
    r.raise_for_status()
    for block in re.findall(r"<job>(.*?)</job>", r.text, re.S):
        title = field(block, "title")
        loc = ", ".join(x for x in (field(block, "city"), field(block, "state"), field(block, "country")) if x)
        if not h.title_ok(title) or not (h.in_india(loc) or "india" in loc.lower() or field(block, "country").upper() == "IN"):
            continue
        yield h.Job(c["name"], title, loc, field(block, "url"), h.parse_ts(field(block, "date")) if field(block, "date") else None,
                    h.strip_html(field(block, "description")))
