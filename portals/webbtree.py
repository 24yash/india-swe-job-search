"""Webbtree job boards (IdeaForge): https://app.webbtree.com/company/<slug>/jobs is server-rendered with every opening.
Titles and job URLs come from the page's BreadcrumbList ld+json; each job card shows the title and "City,Country (Mode)".
Job pages render only in the browser, and the board's JSON API needs a client-side-encrypted header, so only the list
page is read (no descriptions). companies.json: {"ats": "portal", "portal": "webbtree", "slug": "ideaforge"}

A page without the BreadcrumbList, or whose cards don't match it one for one, raises (layout changed), and so does a
fitting India job whose @id isn't a webbtree job URL (the board URL would give every such job the same key)."""
import json
import re

from portals.jsonlist import clean

JOB_URL = re.compile(r"https://app\.webbtree\.com/[^/?#\s]+/jobs/[^/?#\s]+")
CARD = re.compile(r'jobnameHover"[^>]{0,300}>\s*<a\b[^>]{0,300}>(.{0,500}?)</a>.{0,3000}?class="f-14"[^>]{0,300}>\s*<a\b[^>]{0,300}>(.{0,500}?)</a>',
                  re.S)


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def fetch(c, h):
    url = f"https://app.webbtree.com/company/{c['slug']}/jobs"
    r = h.SESSION.get(url, timeout=30)
    r.raise_for_status()
    crumbs = None
    for block in re.findall(r'<script type="application/ld\+json"[^>]{0,200}>(.*?)</script>', r.text[:3_000_000], re.S):
        d = json.loads(block)
        if isinstance(d, dict) and d.get("@type") == "BreadcrumbList":
            crumbs = d.get("itemListElement") or []
    cards = CARD.findall(r.text[:3_000_000])
    if crumbs is None or len(cards) != len(crumbs):
        raise ValueError(f"{url}: {'no BreadcrumbList' if crumbs is None else f'{len(crumbs)} listed jobs but {len(cards)} cards'}")
    places = {}
    for t, l in cards:
        places.setdefault(norm(clean(h, t)), []).append(re.sub(r"\s*,\s*", ", ", clean(h, l)))
    for it in crumbs:
        item = it.get("item") or {}
        title = re.sub(r"\s+", " ", clean(h, str(item.get("name") or "")))
        spots = places.get(norm(title)) or [""]
        loc = spots.pop(0) if len(spots) > 1 else spots[0]  # same title twice: cards in order
        mode = re.search(r"\(([^)]*)\)\s*$", loc)
        loc = re.sub(r"\s*\([^)]*\)\s*$", "", loc)
        if not title or not h.title_ok(title) or not h.in_india(loc):
            continue
        link = str(item.get("@id") or "").strip()
        if not JOB_URL.match(link):
            raise ValueError(f"{url}: {title!r} has no webbtree job URL in the BreadcrumbList (@id {link[:200]!r})")
        yield h.Job(c["name"], title, loc, link, None, "",
                    remote=bool(mode and "remote" in mode.group(1).lower()), meta={"workMode": mode.group(1) if mode else ""})
