"""Klimb (klimb.io) job widgets: careers pages that call klimb_init({company: "<slug>"}) (IndiaMART: "indiamart").

companies.json: {"name": "India Mart", "ats": "portal", "portal": "klimb", "company": "indiamart"}

The widget loads joblist.klimb.io/<slug> (an HTML fragment with the first 20 cards) and its "load more" button then
calls joblist.klimb.io/<slug>?lastPosId=<id of the last card shown>, which answers JSON:
{"jobs": {"positions": [...20 jobs, newest first, with the full description...]}, "showLoadMore": true}.
Positions are ordered by their id (a MongoDB ObjectId, so by creation time, newest first) and lastPosId returns the
ones below it, so the reader starts the same call from a cursor above every id and pages on until showLoadMore is
false. The posting date is the ObjectId's creation time. Job links are the widget's own: jobs.klimb.io/<slug>/<id>.
A reply without jobs.positions raises (a broken read must not look like "every role closed"), and so do a page of
positions none of which parses (a renamed id field) and a board that still says "load more" after max_pages pages.
A remote role keeps its place ("Noida, India (Remote)"); one with no India place counts only with "remote_india". The feed's salary field is not shown on the page, so it is kept in
meta only.
"""
import re
import time
from datetime import datetime, timezone

from portals.jsonlist import clean

LIST = "https://joblist.klimb.io/{slug}"
JOB = "https://jobs.klimb.io/{slug}/{id}"
TOP = "f" * 24  # above every ObjectId: the first page


def place(p):
    """The position's place; a remote one keeps it: 'Noida, India (Remote)', or 'Remote' when it names none."""
    loc = p.get("location") or {}
    if not isinstance(loc, dict):
        loc = str(loc)
    else:
        g = loc.get("gPlace") or {}
        loc = str(loc.get("searchText") or (g.get("formatted_address") if isinstance(g, dict) else "") or "")
    if p.get("remote"):
        return f"{loc} (Remote)" if loc.strip() else "Remote"
    return loc


def created(pid):
    try:
        return datetime.fromtimestamp(int(pid[:8], 16), timezone.utc)
    except (TypeError, ValueError):
        return None


def fetch(c, h):
    slug = c["company"]
    cursor, seen = TOP, set()
    for _ in range(c.get("max_pages", 40)):
        data = h.get(LIST.format(slug=slug), params={"lastPosId": cursor})
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, dict) or not isinstance(jobs.get("positions"), list):
            raise ValueError(f"no jobs.positions in Klimb's reply for {slug}")
        rows = [p for p in jobs["positions"] if isinstance(p, dict) and re.fullmatch(r"[0-9a-f]{24}", str(p.get("id", "")))]
        if jobs["positions"] and not rows:
            raise ValueError(f"none of the {len(jobs['positions'])} positions in Klimb's reply for {slug} has an id (feed changed?)")
        for p in rows:
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            title = re.sub(r"\s+", " ", clean(h, str(p.get("title") or ""))).strip()
            loc = clean(h, place(p))
            remote = bool(p.get("remote")) or bool(re.search(r"\bremote\b", loc, re.I))  # flag, or a place that reads "Remote"
            india = h.in_india(loc)
            if not title or not h.title_ok(title) or not (india or (remote and c.get("remote_india"))):
                continue
            exp = p.get("expRange") or {}
            years = f"Experience: {exp['minimum']}-{exp.get('maximum') or exp['minimum']} years\n\n" if isinstance(exp, dict) and exp.get("minimum") not in (None, "") else ""
            meta = {"department": str(p.get("department") or ""), "role": str(p.get("role") or "")}
            sal = p.get("salary")
            if isinstance(sal, dict) and sal.get("minimum"):
                meta["salary_feed"] = f"INR {sal['minimum']} - {sal.get('maximum') or sal['minimum']} {p.get('salType') or ''}".strip()
            yield h.Job(c["name"], title, loc if india else "India (remote)", JOB.format(slug=slug, id=p["id"]), created(p["id"]),
                        years + clean(h, str(p.get("description") or "")), remote=remote, meta=meta)
        if not data.get("showLoadMore") or not rows:
            return
        cursor = rows[-1]["id"]
        time.sleep(c.get("delay", 1))  # about one request a second
    raise ValueError(f"Klimb board {slug} still lists more jobs after {c.get('max_pages', 40)} pages")
