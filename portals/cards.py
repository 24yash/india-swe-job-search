"""Generic reader for careers pages that server-render their openings as cards with no page per job (Indifi,
TransBnk/TBX, Graph AI, Accord), or whose only link per card reads "Apply Now" (Atomicwork). Configured per company:

  {"name": "Indifi", "ats": "portal", "portal": "cards", "url": "https://www.indifi.com/careers",
   "card": ".tab-content div.panel", "title": "h3", "location": "h3 span.location", "detail": "div > p.margin-b-0, div.panel-body"}

Keys:
  url (or urls): the careers page(s)
  card: selector for one job card. A page where it matches nothing raises (a redesign must not read as "no openings"),
        and so does a page where no card has a title. "card_parent": n climbs n levels up from each match, for pages
        whose card containers carry only generated class names (IEX's MUI boxes: card "h6.MuiTypography-h6", 1).
  title: selector for the title inside the card (first match). Text of a nested location element is left out.
  location: selector for the location inside the card (first match); "location_re": a regex whose group 1 is the place
        within that text ("3-5 years | Hyderabad, India | In-office": "\\|\\s*([^|]+?)\\s*\\|"), or within the whole
        card's text when there is no location selector (IEX: "Location:\\s*(.+)").
  default_location: used when the card names no place (only for companies that hire in India only).
  remote_worldwide: a regex the page itself must match (IgniteTech: "open to candidates worldwide"); a card placed
        only "Remote" then counts as open to India ("Remote (open worldwide, incl. India)"). Without the page saying
        so, a remote card is dropped.
  detail: selector(s) for the description inside the card (all matches joined); default: the whole card's text.
  require: a regex a card's text must match to count as a job (IEX: "^Location:", for pages where the card selector
        also matches company-values headings or a contact box). A page where cards matched but none matches raises.
  link: selector for the card's own job link (an <a href>; a card that is itself an <a> is its own link). A card with
        its own link is keyed (and deduplicated) on that link. Without one, or when it is only an in-page "#..."
        anchor or not http(s), the URL is the page URL + "#<slug of the title>". When the page shows the same title in
        more than one place, every copy's key also carries its location's slug ("#software-engineer-pune-india"), so
        no key depends on card order; a unique title keeps its plain "#<slug>" key; an exact repeat (same title, same
        place) is the same role, shown once.
  fetch_detail: a selector for the description on the linked job page (Atomicwork: "div.jd_wrapper"), read only
        for fitting India roles that have their own link; true reads the page's <main> (else the whole page). A failed
        detail read keeps the card's own text.

Selectors are a small CSS subset: tag, .class, #id, [attr], [attr=v], [attr*=v], [attr^=v], combined with
descendant (space) and child (>) steps; "a, b" tries a then b. HTML comments, <script>, <style>, <svg> and
<template> contents are ignored (commented-out jobs stay out; page text is never run). Only India + fitting titles
are yielded.
"""
import re
import time
from html.parser import HTMLParser
from urllib.parse import urljoin

from portals.jsonlist import clean

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
SKIP = {"script", "style", "svg", "template", "noscript"}
BLOCK = {"p", "div", "li", "ul", "ol", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "header", "footer"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.children, self.parent = tag, attrs, [], parent

    def classes(self):
        return (self.attrs.get("class") or "").split()

    def iter(self):
        for ch in self.children:
            if isinstance(ch, Node):
                yield ch
                yield from ch.iter()


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.cur, self.skip = self.root, 0

    def handle_starttag(self, tag, attrs):
        if self.skip:
            self.skip += tag in SKIP and tag not in VOID
            return
        if tag in SKIP:
            self.skip = 1
            return
        node = Node(tag, {k: v or "" for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        if not self.skip and tag not in SKIP:
            self.cur.children.append(Node(tag, {k: v or "" for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        if self.skip:
            self.skip -= tag in SKIP
            return
        n = self.cur
        while n is not None and n.tag != tag:  # close up to the matching open tag; a stray end tag is ignored
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        if not self.skip:
            self.cur.children.append(data)


def parse(page):
    t = Tree()
    t.feed(page[:5_000_000])
    t.close()
    return t.root


STEP = re.compile(r"\s*(>)?\s*([a-zA-Z0-9*-]*)((?:[.#][\w-]+|\[[\w-]+(?:[*^]?=(?:\"[^\"]*\"|'[^']*'|[^\]]*))?\])*)")


def compile_selector(sel):
    """'#tech div.panel > h3' -> [(combinator, tag, [(kind, name, op, value)])]."""
    steps, pos = [], 0
    sel = sel.strip()
    while pos < len(sel):
        m = STEP.match(sel, pos)
        if not m or m.end() == pos:
            raise ValueError(f"unsupported selector {sel!r}")
        comb, tag, rest = m.groups()
        conds = []
        for c in re.findall(r"[.#][\w-]+|\[[^\]]*\]", rest):
            if c[0] == ".":
                conds.append(("class", c[1:], "", ""))
            elif c[0] == "#":
                conds.append(("attr", "id", "=", c[1:]))
            else:
                a = re.match(r"\[([\w-]+)(?:([*^]?=)(.*))?\]", c)
                conds.append(("attr", a.group(1), a.group(2) or "", (a.group(3) or "").strip("\"'")))
        if not tag and not conds:
            raise ValueError(f"unsupported selector {sel!r}")
        steps.append((comb or " ", tag.lower(), conds))
        pos = m.end()
    return steps


def node_ok(n, tag, conds):
    if tag and tag != "*" and n.tag != tag:
        return False
    for kind, name, op, val in conds:
        if kind == "class":
            if name not in n.classes():
                return False
            continue
        if name not in n.attrs:
            return False
        have = n.attrs[name]
        if (op == "=" and have != val) or (op == "*=" and val not in have) or (op == "^=" and not have.startswith(val)):
            return False
    return True


def select(root, sel):
    """Nodes under root matching sel (document order, no repeats)."""
    out = []
    for one in sel.split(","):
        steps = compile_selector(one)
        cur = [root]
        for comb, tag, conds in steps:
            nxt = []
            for base in cur:
                pool = [c for c in base.children if isinstance(c, Node)] if comb == ">" else base.iter()
                nxt += [n for n in pool if node_ok(n, tag, conds)]
            cur = list(dict.fromkeys(nxt))
        out += [n for n in cur if n not in out]
    return out


def text(n, drop=()):
    parts = []

    def walk(x):
        for ch in x.children:
            if isinstance(ch, str):
                parts.append(ch)
            elif ch not in drop:
                sep = "\n" if ch.tag in BLOCK else " "  # <span>Remote</span><span>Full-time</span> stays two words
                parts.append(sep)
                walk(ch)
                parts.append(sep)
    walk(n)
    s = re.sub(r"[ \t\r\f\v\xa0]+", " ", "".join(parts))
    return re.sub(r"\s*\n\s*", "\n", s).strip()


WORLDWIDE = "Remote (open worldwide, incl. India)"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def page_text(h, url):
    r = h.SESSION.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def cards(c, h, url, page):
    root = parse(page)
    found = select(root, c["card"])
    for _ in range(int(c.get("card_parent", 0))):
        found = list(dict.fromkeys(n.parent for n in found if n.parent is not None))
    if not found:
        raise ValueError(f"card selector {c['card']!r} matches nothing on {url} (page changed?)")
    if c.get("require"):
        found = [n for n in found if re.search(c["require"], text(n), re.M | re.I)]
        if not found:
            raise ValueError(f"no card on {url} matches require {c['require']!r} (page changed?)")
    rows = []
    for card in found:
        loc_node = next(iter(select(card, c["location"])), None) if c.get("location") else None
        t_node = next(iter(select(card, c["title"])), None)
        title = re.sub(r"\s+", " ", clean(h, text(t_node, drop={loc_node} if loc_node else ()))) if t_node else ""
        loc = re.sub(r"\s+", " ", clean(h, text(loc_node))) if loc_node else ""
        if c.get("location_re") and (loc or not c.get("location")):
            m = re.search(c["location_re"], loc or clean(h, text(card)), re.M)
            loc = m.group(1).strip() if m else ""
        details = [text(d) for d in select(card, c["detail"])] if c.get("detail") else [text(card)]
        href = ""
        if c.get("link"):
            own = [card] if card.tag == "a" else []  # the card itself is the link (IgniteTech)
            a = next((x for x in own + select(card, c["link"]) if x.attrs.get("href")), None)
            href = urljoin(url, a.attrs["href"].strip()) if a else ""
            if not re.match(r"https?://", href) or href.split("#")[0] == url.split("#")[0]:
                href = ""  # an in-page anchor (#apply-now) or a javascript:/mailto: link is not the job's own page
        rows.append((title, loc or c.get("default_location", ""), clean(h, "\n\n".join(details)), href))
    if not any(t for t, *_ in rows):
        raise ValueError(f"no card on {url} has a title matching {c['title']!r} (page changed?)")
    if c.get("remote_worldwide") and re.search(c["remote_worldwide"], text(root), re.I):
        rows = [(t, WORLDWIDE if re.fullmatch(r"\W*(fully\s+)?remote\W*", l, re.I) else l, b, u) for t, l, b, u in rows]
    return rows


def fetch(c, h):
    for n, url in enumerate(c.get("urls") or [c["url"]]):
        if n:
            time.sleep(c.get("delay", 1))
        rows = [r for r in cards(c, h, url, page_text(h, url)) if r[0] and h.title_ok(r[0]) and h.in_india(r[1])]
        places = {}  # title slug -> location slugs of the cards without their own link
        for title, loc, _, href in rows:
            if not href:
                places.setdefault(slug(title), set()).add(slug(loc))
        seen = set()
        for title, loc, body, href in rows:
            key = slug(title)
            if not href and len(places[key]) > 1:
                key = f"{key}-{slug(loc)}"  # a repeated title: every copy carries its place, whatever the card order
            if (href or key) in seen:
                continue  # the same role shown twice (desktop and mobile copies)
            seen.add(href or key)
            if href and c.get("fetch_detail"):
                try:
                    time.sleep(c.get("delay", 1))
                    detail = parse(page_text(h, href))
                    sel = c["fetch_detail"] if isinstance(c["fetch_detail"], str) else "main"
                    main = next(iter(select(detail, sel)), detail)
                    body = clean(h, text(main)) or body
                except Exception:
                    pass  # the card's own text stands in
            yield h.Job(c["name"], title, loc, href or f"{url.split('#')[0]}#{key}", None, body,
                        remote=bool(re.search(r"\bremote\b", loc, re.I)))
