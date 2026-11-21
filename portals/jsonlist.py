"""Generic reader for careers pages that load their whole job list from one public JSON call (the same call the page
makes in a visitor's browser): in-house APIs (Gnani.ai, Dezerv, Garuda Aerospace, Maxim AI, Navera), small hosted
ATSs (Flexiele: Moglix; Auzmor Hire; Polymer: Atomicwork; Symphony Talent's JSONP search: Deltek) and Next.js pages
that embed the list in their __NEXT_DATA__ script (Sahi). Configured per company in companies.json:

  {"name": "Gnani.ai", "ats": "portal", "portal": "jsonlist", "url": "https://careers.gnani.ai/api/jobs",
   "items": "data.jobs", "title": "title", "location": "location", "default_location": "India",
   "link": "https://careers.gnani.ai/apply/{code}", "posted": "positionPublishDate",
   "min_exp": "minExperience", "max_exp": "maxExperience"}

Keys:
  url (or urls: several pages or feeds read the same way), method ("GET" default | "POST"), params, body (POST JSON), jsonp (true: strip a callback(...) wrapper),
  html_json ("__NEXT_DATA__": the URL is a page; read the JSON in <script id="__NEXT_DATA__">)
  items: dot path to the job list ("" = the response itself; "*" steps into every element of a list, so
         "data.*.jobs" flattens jobs grouped by department)
  title / location / description / posted / min_exp / max_exp / url_field: a dot path, or a list of dot paths
         (location parts are joined with ", ", description parts with blank lines). A list value is joined too.
  link: a URL template filled from the item's fields ({id}, {company.slug}; values are URL-quoted), used when
         there is no url_field. Without either, the careers page itself ("page", else "url") + "#<id>" is the link.
  default_location: used when the item names no location (only for companies that hire in India only)
  where: {dot path: value or [alternatives]}: keep only items that match every entry (status "active", IsOpen true)
  date_format: strptime format when the date isn't ISO ("%d-%m-%Y")
  page_param + page_step (+ max_pages, default 20): read further pages by adding page_step to that parameter
         until a page comes back short (Deltek: "offset", 100)
  total: dot path to the feed's own job count; the read fails when it is more than the items read (a single fixed
         page that has grown past its size would otherwise drop jobs silently)
A missing `items` path (a renamed field, a {"success": false} reply) and a list whose items lack the title field
raise, so a broken read is never taken for "every role closed". Links from the feed must be http(s).
Titles and every other field are treated as untrusted text: HTML is stripped. Only India + fitting titles are yielded.
"""
import html as htmllib
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote, urljoin


SCRIPT = re.compile(r"<(script|style)\b.*?(</\1\s*>|$)", re.S | re.I)  # dropped with their contents, not just the tags


def dig(obj, path):
    """Values at a dot path; '*' fans out over a list. Always returns a list (empty when the path is missing)."""
    cur = [obj]
    for part in [p for p in (path or "").split(".") if p]:
        nxt = []
        for o in cur:
            if part == "*":
                nxt += o if isinstance(o, list) else list(o.values()) if isinstance(o, dict) else []
            elif isinstance(o, dict) and part in o:
                nxt.append(o[part])
            elif isinstance(o, list) and part.isdigit() and int(part) < len(o):
                nxt.append(o[int(part)])
        cur = nxt
    return cur


def flat(v):
    if isinstance(v, list):
        return [x for i in v for x in flat(i)]
    if isinstance(v, dict):  # a place or label object: every value of the first naming key that has one
        return next((flat(v[k]) for k in ("name", "label", "city", "title", "value") if flat(v.get(k))), [])
    return [] if v is None or v == "" or isinstance(v, bool) else [v]


def clean(h, s):
    """Untrusted feed text as plain text: entities decoded until stable (so &amp;lt;img&amp;gt; can't come back as a
    tag), script/style blocks dropped with their contents, then the remaining tags stripped."""
    for _ in range(3):
        u = htmllib.unescape(s)
        if u == s:
            break
        s = u
    return re.sub(r"<[^>]{0,2000}>", " ", h.strip_html(SCRIPT.sub(" ", s))).strip()


def text_at(h, item, paths, sep):
    paths = paths if isinstance(paths, list) else [paths] if paths else []
    vals = [clean(h, str(x)) for p in paths for v in dig(item, p) for x in flat(v)]
    return sep.join(dict.fromkeys(v for v in vals if v))


def load(c, h, url):
    method = c.get("method", "GET").upper()
    if c.get("html_json") or c.get("jsonp"):
        r = h.SESSION.post(url, json=c.get("body"), timeout=30) if method == "POST" else \
            h.SESSION.get(url, params=c.get("params"), timeout=30)
        r.raise_for_status()
        body = r.text
        if c.get("html_json"):
            m = re.search(r'<script[^>]{0,500}?id="' + re.escape(c["html_json"]) + r'"[^>]{0,500}>(.*?)</script>', body, re.S)
            if not m:
                raise ValueError(f"no {c['html_json']} script in {url}")
            return json.loads(m.group(1))
        m = re.match(r"\s*[\w$.]{1,100}\s*\((.*)\)\s*;?\s*$", body, re.S)
        return json.loads(m.group(1) if m else body)
    if method == "POST":
        return h.post(url, c.get("body") or {})
    return h.get(url, params=c.get("params"))


def matches(item, where):
    for path, want in (where or {}).items():
        alts = want if isinstance(want, list) else [want]
        if not any(v in alts for v in dig(item, path)):
            return False
    return True


def posted_at(h, v, fmt):
    if not v or isinstance(v, bool):
        return None
    if fmt:
        try:
            d = datetime.strptime(str(v).strip(), fmt)
        except ValueError:
            return None
        return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        return h.parse_ts(v)
    s = str(v).strip()
    return h.parse_ts(s) or h.parse_ts(s[:10])  # "2026-11-11 10:00:59" and other ISO-like forms: the date is enough


def first(item, paths):
    for p in paths if isinstance(paths, list) else [paths]:
        for v in dig(item, p):
            if v not in (None, "", []):
                return v
    return None


def fetch(c, h):
    for url in c.get("urls") or [c["url"]]:
        yield from read(c, h, url)


def read(c, h, url):
    path, items, step = c.get("items", ""), [], c.get("page_step")
    for n in range(c.get("max_pages", 20) if step else 1):  # "page_param" + "page_step": offset paging (Deltek: offset, 100)
        cfg = c | {"params": {**(c.get("params") or {}), c["page_param"]: n * step}} if step else c
        data = load(cfg, h, url)
        if path and not dig(data, path.split(".*")[0]):  # the list itself is missing, not merely empty
            raise ValueError(f"no '{path}' in the reply from {url}")
        got = [x for v in dig(data, path) for x in (v if isinstance(v, list) else [v]) if isinstance(x, dict)]
        items += got
        if not step or len(got) < step:
            break
    total = first(data, c["total"]) if c.get("total") else None
    if isinstance(total, (int, float)) and total > len(items):
        raise ValueError(f"{url} reports {total} jobs but {len(items)} were read (page size too small)")
    if items and not any(dig(it, p) for it in items for p in (c.get("title", "title") if isinstance(c.get("title"), list) else [c.get("title", "title")])):
        raise ValueError(f"no item in {url} has the title field '{c.get('title', 'title')}' (feed changed?)")
    page = c.get("page") or url
    for it in items:
        if not matches(it, c.get("where")):
            continue
        title = re.sub(r"\s+", " ", text_at(h, it, c.get("title", "title"), " ")).strip()
        loc = text_at(h, it, c.get("location"), ", ") or c.get("default_location", "")
        if not title or not h.title_ok(title) or not h.in_india(loc):
            continue
        ident = it.get("id") or it.get("_id") or quote(title)
        link = ""
        if c.get("url_field"):
            link = urljoin(page, text_at(h, it, c["url_field"], ""))
        elif c.get("link"):
            vals = {k: first(it, k) for k in re.findall(r"\{([\w.]+)\}", c["link"])}
            if all(v not in (None, "") for v in vals.values()):
                link = re.sub(r"\{([\w.]+)\}", lambda m: quote(str(vals[m.group(1)]), safe=""), c["link"])
        if not re.match(r"https?://", link):  # missing template field, or a javascript:/data: link from the feed
            link = f"{page}#{ident}"
        text = text_at(h, it, c.get("description"), "\n\n")
        lo, hi = text_at(h, it, c.get("min_exp"), ""), text_at(h, it, c.get("max_exp"), "")
        if lo:  # years asked, in words the experience parser reads (a maximum alone says nothing about the minimum)
            text = f"Experience: {lo}{'-' + hi if hi else '+'} years\n\n{text}"
        posted = posted_at(h, first(it, c["posted"]) if c.get("posted") else None, c.get("date_format"))
        yield h.Job(c["name"], title, loc, link, posted, text, remote="remote" in loc.lower())
