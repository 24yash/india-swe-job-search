"""Homerun job boards (Ghost: careers.ghost.org): the board's public Atom feed, https://feed.homerun.co/<slug>, lists
every open job with its full description. companies.json: {"ats": "portal", "portal": "homerun", "slug": "ghost"}

Remote-first boards often name a timezone band instead of a place ("UTC-6 - UTC+2"). A band that covers India
(UTC+5:30) counts as remote India, as do "Anywhere" / "Worldwide"; any other band, and a bare "Remote", don't.
A reply that isn't an Atom feed raises (a feed with no <entry> is a board with no openings)."""
import re

from portals.jsonlist import clean

BAND = re.compile(r"UTC\s*([+-]\d{1,2})(?::(\d\d))?\s*(?:-|–|to)\s*UTC\s*([+-]\d{1,2})(?::(\d\d))?", re.I)


def tag(block, name):
    m = re.search(rf"<{name}\b[^>]{{0,300}}>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</{name}>", block, re.S | re.I)
    return m.group(1) if m else ""


def place(h, raw):
    """(location, remote) for a Homerun location name; location is '' when the job isn't open to India."""
    loc = clean(h, raw)
    m = BAND.search(loc)
    if m:
        lo, hi = (int(m.group(i)) + (1 if m.group(i)[0] != "-" else -1) * int(m.group(i + 1) or 0) / 60 for i in (1, 3))
        return (f"Remote ({loc}), India", True) if min(lo, hi) <= 5.5 <= max(lo, hi) else ("", True)
    if re.search(r"\b(anywhere|worldwide)\b", loc, re.I):
        return f"Remote ({loc}), India", True
    return (loc, "remote" in loc.lower()) if h.in_india(loc) else ("", False)


def fetch(c, h):
    r = h.SESSION.get(f"https://feed.homerun.co/{c['slug']}", timeout=30)
    r.raise_for_status()
    if not re.search(r"<feed\b[^>]{0,300}Atom", r.text[:3000], re.I):
        raise ValueError(f"feed.homerun.co/{c['slug']} is not an Atom feed (board moved?)")
    for block in re.findall(r"<entry\b[^>]*>(.*?)</entry>", r.text, re.S):
        title = re.sub(r"\s+", " ", clean(h, tag(block, "title")))
        loc, remote = place(h, tag(tag(block, "location"), "name"))
        if not title or not loc or not h.title_ok(title):
            continue
        link = re.search(r'<link\b[^>]{0,300}href="(https?://[^"]{1,500})"', block)
        updated = tag(block, "updated").strip()
        yield h.Job(c["name"], title, loc, link.group(1) if link else f"https://feed.homerun.co/{c['slug']}#{clean(h, tag(block, 'id'))}",
                    h.parse_ts(updated[:10]) if updated else None, clean(h, tag(block, "description") or tag(block, "content")),
                    remote=remote, pay_posted=clean(h, tag(block, "salary_indication")))
