"""Deel ATS job boards (jobs.deel.com/<board>; the shareable link jobs.deel.com/job-boards/<board> redirects there).

companies.json: {"name": "Zema Global Data Corporation", "ats": "portal", "portal": "deel", "board": "zema.global"}

The board is a Next.js app-router page: the list is server-rendered into the page's React Server Components payload
(the self.__next_f.push([1, "..."]) scripts) as "jobPostings":[{id, title, createdAt, richtextDescription,
job: {workArrangementEnum, jobLocations: [{location: {name, country: {name}}}], currentCompensation}}].
Each description is a reference ("$24") to a text row ("24:T<length in bytes>,<html>") elsewhere in the same payload.
One GET reads the whole board. A page without the jobPostings list (a redesign, a challenge page) raises, so a broken
read never looks like "every role closed". Job links are the board's own: jobs.deel.com/<board>/job-details/<id>/overview.
"""
import json
import re

from portals.jsonlist import clean

BOARD = "https://jobs.deel.com/{board}"
JOB = "https://jobs.deel.com/{board}/job-details/{id}/overview"
PUSH = re.compile(r'self\.__next_f\.push\(\[1,\s*("(?:[^"\\]|\\.)*")\]\)', re.S)


def payload(page):
    """The page's RSC payload as one string (each pushed chunk is a JSON string literal)."""
    out = []
    for lit in PUSH.findall(page):
        try:
            out.append(json.loads(lit))
        except ValueError:
            continue
    return "".join(out)


def text_row(rsc_bytes, ref):
    """The text a "$<hex>" reference points to, or "" when it isn't a text row."""
    m = re.fullmatch(r"\$([0-9a-f]{1,6})", ref or "")
    if not m:
        return ""
    row = re.search(rb"(?<![0-9a-zA-Z])" + m.group(1).encode() + rb":T([0-9a-f]{1,8}),", rsc_bytes)
    if not row:
        return ""
    return rsc_bytes[row.end(): row.end() + int(row.group(1), 16)].decode("utf-8", "ignore")


def postings(rsc):
    m = re.search(r'"jobPostings"\s*:\s*(?=\[)', rsc)
    if not m:
        return None
    try:
        arr, _ = json.JSONDecoder().raw_decode(rsc, m.end())
    except ValueError:
        return None
    return arr if isinstance(arr, list) else None


def places(p):
    out = []
    for jl in (p.get("job") or {}).get("jobLocations") or []:
        loc = (jl or {}).get("location") or {}
        country = (loc.get("country") or {}).get("name") if isinstance(loc.get("country"), dict) else ""
        out.append(", ".join(x for x in (str(loc.get("name") or "").strip(), str(country or "").strip()) if x))
    return [x for x in out if x]


def fetch(c, h):
    url = BOARD.format(board=c["board"])
    r = h.SESSION.get(url, timeout=30)
    r.raise_for_status()
    rsc = payload(r.text)
    items = postings(rsc)
    if items is None:
        raise ValueError(f"no jobPostings list in the Deel board page {url}")
    raw = rsc.encode("utf-8")
    for p in items:
        if not isinstance(p, dict) or not re.fullmatch(r"[0-9a-f-]{36}", str(p.get("id", ""))):
            continue
        title = re.sub(r"\s+", " ", clean(h, str(p.get("title") or "")).split(" | ")[0]).strip()  # "Software Engineer (India) | RQ-0023"
        india = [clean(h, l) for l in places(p) if h.in_india(l)]
        if not title or not h.title_ok(title) or not india:
            continue
        job = p.get("job") or {}
        pay = ""
        comp = job.get("currentCompensation") or {}
        if p.get("isCompensationVisible") and isinstance(comp, dict) and comp.get("currencyIsoCode") == "INR" and comp.get("minAmount"):
            pay = f"INR {comp['minAmount']} - INR {comp.get('maxAmount') or comp['minAmount']} per year"
        desc = p.get("richtextDescription") or ""
        text = text_row(raw, desc) if desc.startswith("$") else desc
        yield h.Job(c["name"], title, " / ".join(dict.fromkeys(india)), JOB.format(board=c["board"], id=p["id"]),
                    h.parse_ts(str(p.get("createdAt") or "")), clean(h, text), remote=job.get("workArrangementEnum") == "REMOTE",
                    pay_posted=pay, meta={"workArrangement": str(job.get("workArrangementEnum") or "")})
