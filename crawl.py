"""Crawl public job-board APIs, filter roles against profile.json, score and rank them.

Usage:
    python3 crawl.py                 # all companies in companies.json
    python3 crawl.py --only Stripe   # one or more company names (comma-separated)
    python3 crawl.py --max-age 30    # widen freshness window (days)

Writes output/jobs-<date>.csv, output/jobs-<date>.md and output/rejected-<date>.csv,
and keeps output/seen.json so each run flags roles that are new since the last run.
Read only: it calls public GET/search endpoints and never applies or signs in.
"""
import argparse
import collections
import csv
import html
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).parent
OUT = ROOT / "output"
UA = {"User-Agent": "Mozilla/5.0 (job-search research script; read-only)"}
NOW = datetime.now(timezone.utc)  # for posting ages
TODAY = datetime.now().strftime("%Y-%m-%d")  # local date, for file names and history (matches report.py)

PROFILE = json.loads((ROOT / "profile.json").read_text())
INDIA = PROFILE["location"]["india_markers"]
HOME = PROFILE["location"]["home_markers"]


@dataclass
class Job:
    company: str
    title: str
    location: str
    url: str
    posted: datetime | None
    text: str
    remote: bool = False
    pay_posted: str = ""
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------- fetchers

SESSION = requests.Session()  # some boards (Microsoft) rate-limit cookieless clients
SESSION.headers.update(UA)


def get(url, **kw):
    for attempt in range(5):
        r = SESSION.get(url, timeout=30, **kw)
        if r.status_code != 429:
            break
        time.sleep(2 ** attempt * 3)  # rate limited: back off and retry
    r.raise_for_status()
    return r.json()


def post(url, body, **kw):
    r = SESSION.post(url, json=body, timeout=30, **kw)
    r.raise_for_status()
    return r.json()


def strip_html(s):
    s = html.unescape(s or "")
    s = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", s, flags=re.I)
    return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", " ", s))


def parse_ts(v):
    if not v:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d", "%B %d, %Y", "%Y-%m-%d %I:%M %p"):
        try:
            d = datetime.strptime(v.replace("Z", "+00:00"), fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def workday_age(s):
    """'Posted 3 Days Ago' / 'Posted Today' / 'Posted 30+ Days Ago' -> datetime."""
    s = (s or "").lower()
    if "today" in s:
        return NOW
    if "yesterday" in s:
        return NOW - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*day", s)
    return NOW - timedelta(days=int(m.group(1))) if m else None


def in_india(loc):
    l = loc.lower()
    return any(k in l for k in INDIA)


def title_ok(title):
    t = title.lower()
    return (re.search(PROFILE["title"]["include"], t) and not re.search(PROFILE["title"]["exclude"], t))


def greenhouse(c):
    """List first (no descriptions: ~12x smaller for big boards), then fetch descriptions only for
    India roles whose title fits."""
    base = f"https://boards-api.greenhouse.io/v1/boards/{c['slug']}/jobs"
    for j in get(base)["jobs"]:
        loc = j.get("location", {}).get("name", "")
        if not (title_ok(j["title"]) and (in_india(loc) or "remote" in loc.lower())):
            continue
        try:
            detail = get(f"{base}/{j['id']}")
        except requests.RequestException:
            continue  # closed between the list and the detail call
        yield Job(c["name"], j["title"], loc, j["absolute_url"],
                  parse_ts(j.get("first_published") or j.get("updated_at")),
                  strip_html(detail.get("content")), remote="remote" in loc.lower())


def lever(c):
    for j in get(f"https://api.lever.co/v0/postings/{c['slug']}?mode=json"):
        cat = j.get("categories") or {}
        locs = cat.get("allLocations") or [cat.get("location") or ""]
        text = j.get("descriptionPlain", "") + "\n" + "\n".join(
            l.get("text", "") + "\n" + strip_html(l.get("content")) for l in j.get("lists", [])
        ) + "\n" + (j.get("additionalPlain") or "")
        yield Job(c["name"], j["text"], " / ".join(locs), j["hostedUrl"], parse_ts(j.get("createdAt")),
                  text, remote=j.get("workplaceType") == "remote", meta={"commitment": cat.get("commitment", "")})


def ashby(c):
    d = get(f"https://api.ashbyhq.com/posting-api/job-board/{c['slug']}?includeCompensation=true")
    for j in d["jobs"]:
        locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations", [])]
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        yield Job(c["name"], j["title"], " / ".join(filter(None, locs)), j["jobUrl"],
                  parse_ts(j.get("publishedAt")), j.get("descriptionPlain", ""),
                  remote=bool(j.get("isRemote")), pay_posted=comp,
                  meta={"employmentType": j.get("employmentType", "")})


def smartrecruiters(c):
    base = f"https://api.smartrecruiters.com/v1/companies/{c['slug']}/postings"
    offset = 0
    while True:
        d = get(base, params={"limit": 100, "offset": offset})
        for j in d.get("content", []):
            if (j.get("location") or {}).get("country", "").lower() != "in" or not title_ok(j["name"]):
                continue
            det = get(f"{base}/{j['id']}")
            sec = (det.get("jobAd") or {}).get("sections") or {}
            text = "\n".join(strip_html((sec.get(k) or {}).get("text")) for k in ("jobDescription", "qualifications", "additionalInformation"))
            loc = j.get("location") or {}
            yield Job(c["name"], j["name"], ", ".join(filter(None, [loc.get("city"), loc.get("country", "").upper()])),
                      det.get("postingUrl") or f"https://jobs.smartrecruiters.com/{c['slug']}/{j['id']}",
                      parse_ts(j.get("releasedDate")), text, remote=bool(loc.get("remote")))
        offset += 100
        if offset >= d.get("totalFound", 0) or offset >= 1000:
            break


def workday(c):
    host = f"https://{c['tenant']}.{c['wd']}.myworkdayjobs.com"
    api = f"{host}/wday/cxs/{c['tenant']}/{c['site']}"
    seen, todo = set(), []
    # Workday has no country filter without facet IDs, so put the place in the search text.
    for query in ("software engineer", "software engineer Bangalore", "software engineer India", "backend engineer", "software developer India"):
        offset = 0
        while offset < 200:
            d = post(f"{api}/jobs", {"limit": 20, "offset": offset, "searchText": query, "appliedFacets": {}})
            posts = d.get("jobPostings", [])
            for j in posts:
                path = j.get("externalPath", "")
                if path in seen or not title_ok(j.get("title", "")):
                    continue
                seen.add(path)
                loc = j.get("locationsText", "")
                if in_india(loc) or "location" in loc.lower():  # "3 Locations" needs the detail call
                    todo.append(j)
            offset += 20
            if not posts or offset >= d.get("total", 0):
                break

    def detail(j):  # one request per job: run a few at a time instead of one after another
        try:
            info = get(f"{api}{j['externalPath']}").get("jobPostingInfo", {})
        except requests.RequestException:
            return None  # closed between the search and the detail call; don't lose the rest of the board
        locs = " / ".join([info.get("location", "")] + info.get("additionalLocations", []))
        return Job(c["name"], info.get("title", j["title"]), locs, info.get("externalUrl") or f"{host}/{c['site']}{j['externalPath']}",
                   parse_ts(info.get("startDate")) or workday_age(j.get("postedOn")),
                   strip_html(info.get("jobDescription")), remote="remote" in (info.get("remoteType") or "").lower())

    with ThreadPoolExecutor(6) as pool:
        yield from filter(None, pool.map(detail, todo))


def oracle(c):
    """Oracle Recruiting Cloud (JPMorgan, Oracle…): the public REST API behind the company's own careers site."""
    api = f"https://{c['host']}/hcmRestApi/resources/latest"
    seen, todo = set(), []
    for query in ("software engineer", "software developer", "backend engineer"):
        offset = 0
        while offset < 500:
            finder = (f'findReqs;siteNumber={c["site"]},keyword="{query}",location=India,limit=25,offset={offset},'
                      f'sortBy=POSTING_DATES_DESC')
            d = get(f"{api}/recruitingCEJobRequisitions", params={"onlyData": "true", "finder": finder,
                                                                  "expand": "requisitionList.secondaryLocations"})
            page = ((d.get("items") or [{}])[0]).get("requisitionList") or []
            for j in page:
                locs = [j.get("PrimaryLocation") or ""] + [s.get("Name", "") for s in j.get("secondaryLocations") or []]
                if j["Id"] in seen or not title_ok(j.get("Title", "")) or not any(in_india(l) for l in locs):
                    continue
                seen.add(j["Id"])
                todo.append((j, locs))
            offset += 25
            if len(page) < 25:
                break

    def detail(item):
        j, locs = item
        try:
            finder = f'ById;Id="{j["Id"]}",siteNumber={c["site"]}'
            info = (get(f"{api}/recruitingCEJobRequisitionDetails", params={"expand": "all", "onlyData": "true", "finder": finder})
                    .get("items") or [{}])[0]
        except requests.RequestException:
            return None
        text = "\n".join(strip_html(info.get(k)) for k in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr"))
        return Job(c["name"], j["Title"], " / ".join(filter(None, locs)),
                   f"https://{c['host']}/hcmUI/CandidateExperience/en/sites/{c['site']}/job/{j['Id']}",
                   parse_ts(info.get("ExternalPostedStartDate") or j.get("PostedDate")), text,
                   remote="remote" in (info.get("WorkplaceType") or "").lower(), meta={"commitment": info.get("JobSchedule") or ""})

    with ThreadPoolExecutor(6) as pool:
        yield from filter(None, pool.map(detail, todo))


def rippling(c):
    """Rippling ATS public board (ats.rippling.com/<slug>)."""
    base = f"https://api.rippling.com/platform/api/ats/v1/board/{c['slug']}/jobs"
    for j in get(base):
        loc = (j.get("workLocation") or {}).get("label", "")
        if not title_ok(j.get("name", "")) or not (in_india(loc) or "remote" in loc.lower()):
            continue
        try:
            d = get(f"{base}/{j['uuid']}")
        except requests.RequestException:
            continue
        desc = d.get("description") or {}
        text = "\n".join(strip_html(v) for v in (desc.values() if isinstance(desc, dict) else [desc]) if isinstance(v, str))
        inr = [p for p in d.get("payRangeDetails") or [] if p.get("currency") == "INR"]
        pay = f"INR {inr[0]['rangeStart']:,.0f}–{inr[0]['rangeEnd']:,.0f}" if inr else ""
        yield Job(c["name"], j["name"], " / ".join(d.get("workLocations") or [loc]), j["url"], parse_ts(d.get("createdOn")),
                  text, remote="remote" in loc.lower(), pay_posted=pay,
                  meta={"employmentType": (d.get("employmentType") or {}).get("label", "")})


def amazon(c):
    for q in ("software development engineer", "backend engineer"):
        for offset in range(0, 300, 100):
            d = get("https://www.amazon.jobs/en/search.json", params={
                "base_query": q, "country": "IND", "result_limit": 100, "offset": offset, "sort": "recent"})
            for j in d.get("jobs", []):
                yield Job(c["name"], j["title"], j.get("normalized_location") or j.get("location", ""),
                          "https://www.amazon.jobs" + j["job_path"], parse_ts(j.get("posted_date")),
                          "\n".join(strip_html(j.get(k)) for k in ("description", "basic_qualifications", "preferred_qualifications")))
            if len(d.get("jobs", [])) < 100:
                break


def recruitee(c):
    """Recruitee careers sites (<slug>.recruitee.com): the public offers feed the careers page uses."""
    d = get(f"https://{c['slug']}.recruitee.com/api/offers/")
    for o in d.get("offers") or []:
        locs = [", ".join(x for x in (l.get("city"), l.get("state"), l.get("country")) if x) for l in o.get("locations") or []] \
            or [", ".join(x for x in (o.get("city"), o.get("country")) if x)]
        india = [l for l in locs if in_india(l) or "india" in l.lower()]
        if not title_ok(o.get("title", "")) or not (india or (o.get("country_code") or "").upper() == "IN"):
            continue
        text = strip_html((o.get("description") or "") + "\n" + (o.get("requirements") or ""))
        yield Job(c["name"], o["title"], " / ".join(india) or "India", o.get("careers_url") or f"https://{c['slug']}.recruitee.com/o/{o['slug']}",
                  parse_ts(o.get("published_at") or o.get("created_at")), text, remote=bool(o.get("remote")),
                  meta={"employmentType": o.get("employment_type_code") or ""})


def eightfold(c):
    """Eightfold PCSX careers sites (Microsoft, Qualcomm, Autodesk…): the public search API behind the site."""
    host, domain = c["host"], c["domain"]
    api = f"https://{host}/api/pcsx"
    SESSION.get(f"https://{host}/careers?domain={domain}")  # sets the cookies the API expects
    seen = set()
    for q in ("software engineer", "backend"):
        for start in range(0, 200, 10):
            d = get(f"{api}/search", params={"domain": domain, "query": q, "location": "India", "start": start, "num": 10})
            pos = d.get("data", {}).get("positions", [])
            for p in pos:
                if p["id"] in seen or not title_ok(p["name"]):
                    continue
                seen.add(p["id"])
                time.sleep(0.5)
                try:
                    det = get(f"{api}/position_details", params={"position_id": p["id"], "domain": domain, "hl": "en"})["data"]
                except (requests.RequestException, KeyError):
                    continue
                yield Job(c["name"], p["name"], " / ".join(p.get("standardizedLocations") or p.get("locations", [])),
                          det.get("publicUrl") or f"https://{host}/careers/job/{p['id']}",
                          parse_ts(p.get("postedTs")), strip_html(det.get("jobDescription")),
                          remote=(p.get("workLocationOption") or "") == "remote")
            if len(pos) < 10:
                break


def portal(c):
    """A company's own careers portal: see portals/."""
    import portals
    yield from portals.fetch(c, sys.modules[__name__])


def microsoft(c):
    yield from eightfold(c | {"host": "apply.careers.microsoft.com", "domain": "microsoft.com"})


def atlassian(c):
    for j in get("https://www.atlassian.com/endpoint/careers/listings"):
        url = (j.get("portalJobPost") or {}).get("portalUrl", "")
        yield Job(c["name"], j["title"], " / ".join(j.get("locations", [])), url,
                  parse_ts((j.get("portalJobPost") or {}).get("updatedDate")),
                  "\n".join(strip_html(j.get(k)) for k in ("overview", "responsibilities", "qualifications")),
                  remote="remote" in " ".join(j.get("locations", [])).lower())


def google(c):
    """Google careers embeds results as JSON in AF_initDataCallback('ds:1'); 20 per page."""
    base = "https://www.google.com/about/careers/applications/jobs/results/"
    seen = set()
    for q in ("software engineer", "backend", "software developer"):
        for page in range(1, 11):
            r = SESSION.get(base, timeout=30, params={"location": "India", "q": q, "page": page,
                                                      "target_level": ["EARLY", "MID"]})
            m = re.search(r"AF_initDataCallback\(\{key: 'ds:1'.*?data:(.*?), sideChannel", r.text, re.S)
            jobs = json.loads(m.group(1))[0] if m else None
            if not jobs:
                break
            for j in jobs:
                if j[0] in seen:
                    continue
                seen.add(j[0])
                locs = " / ".join(l[0] for l in (j[9] or []))
                text = "\n".join(strip_html((j[k] or [None, ""])[1]) for k in (10, 3, 4, 19) if isinstance(j[k], list))
                yield Job(c["name"], j[1], locs, f"{base}{j[0]}", parse_ts(j[12][0]) if j[12] else None, text,
                          remote="remote" in locs.lower())


LI_API = "https://www.linkedin.com/jobs-guest/jobs/api"
LI_DETAILS_FILE = ROOT / "output" / "linkedin-details.json"
LI_DETAILS = json.loads(LI_DETAILS_FILE.read_text()) if LI_DETAILS_FILE.exists() else {}  # job id -> description
LI_LOCK = threading.Lock()
LI_STATE = {"last": 0.0, "strikes": 0}
LI_SEEN = set()  # job ids already handled this run, shared by both LinkedIn passes
DEEP = False  # --deep: add per-city role searches and a much bigger company sweep (slow; LinkedIn rate-limits)


class RateLimited(Exception):
    pass


def li_get(url, **params):
    """Every LinkedIn request goes through here: one request per LI_GAP seconds across both LinkedIn
    passes, and a growing back-off on 429. After 4 consecutive 429s, LinkedIn has blocked us for now,
    so stop instead of waiting on it for hours; the caller keeps what it already has."""
    while True:
        with LI_LOCK:
            wait = LI_STATE["last"] + PROFILE["linkedin"]["seconds_between_requests"] - time.time()
            if wait > 0:
                time.sleep(wait)
            r = SESSION.get(url, timeout=30, params=params)
            LI_STATE["last"] = time.time()
            if r.status_code != 429:
                LI_STATE["strikes"] = 0
                return r
            LI_STATE["strikes"] += 1
            if LI_STATE["strikes"] >= 4:
                raise RateLimited("LinkedIn returned 429 four times in a row; stopping LinkedIn for this run")
            time.sleep(30 * 2 ** (LI_STATE["strikes"] - 1))  # 30s, 60s, 120s


def linkedin_cards(params, max_results):
    """One LinkedIn guest search, paged. Yields (job id, title, company, location, date, company LinkedIn page) per card."""
    for start in range(0, max_results, 25):
        r = li_get(f"{LI_API}/seeMoreJobPostings/search", **params, start=start)
        if r.status_code != 200 or "base-card" not in r.text:
            return
        for card in r.text.split("<li>")[1:]:
            jid = re.search(r"jobPosting:(\d+)", card)
            title = re.search(r'base-search-card__title">\s*(.*?)\s*</h3>', card, re.S)
            sub = re.search(r'base-search-card__subtitle">(.{0,600}?)</h4>', card, re.S)  # company is usually a link, sometimes plain text
            link = re.search(r'href="(https://[a-z]{2,3}\.linkedin\.com/company/[^"?]+)', sub.group(1)) if sub else None
            name = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>|<!--.*?-->", " ", sub.group(1)))).strip() if sub else ""
            comp = re.search(r"\S.*\S|\S", name) if name and "<" not in name and len(name) <= 120 else None  # never an HTML fragment
            loc = re.search(r'job-search-card__location">\s*(.*?)\s*</span>', card, re.S)
            date = re.search(r'datetime="([\d-]+)"', card)
            if jid and title and comp:
                yield (jid.group(1), html.unescape(title.group(1)), comp.group(0),
                       loc.group(1) if loc else "India", date.group(1) if date else None, link.group(1) if link else "")


def linkedin(c):
    """LinkedIn's public guest job search (no sign-in). The role pass searches role keywords across
    India and per city (LinkedIn returns different sets per location). The sweep pass searches the
    company bank by name, several companies per query ("A" OR "B" ...), keeping only their cards.
    Descriptions are cached across runs, and companies we read directly are skipped.
    main() looks each company up in companies.json / tiers.json afterwards."""
    cfg = PROFILE["linkedin"]
    window = f"r{PROFILE['max_age_days'] * 86400}"
    skip = c.get("skip_companies", set())
    mode = cfg["deep"] if DEEP else {}
    if c.get("sweep_companies") is None:
        searches = [({"keywords": q, "location": "India", "f_TPR": window, "f_E": "2,3,4"}, cfg["max_results_per_query"], None)
                    for q in cfg["queries"]]
        searches += [({"keywords": q, "location": loc, "f_TPR": window, "f_E": "2,3,4"}, mode["max_results_per_city"], None)
                     for loc in mode.get("cities", []) for q in mode["city_queries"]]
    else:  # one search per company: OR-batching lets the biggest poster crowd out the rest
        pages = cfg["company_sweep"]["deep_pages" if DEEP else "pages"]
        searches = [({"keywords": n, "location": "India", "f_TPR": window}, pages * 25, {norm(n)})
                    for n in c["sweep_companies"]]
    seen = LI_SEEN
    c["searched"] = []
    label = "company sweep" if c.get("sweep_companies") is not None else "role search"
    for n, (params, limit, only) in enumerate(searches, 1):
        if n % 20 == 0 or n == len(searches):  # the LinkedIn passes are the slow part, so show where they are
            print(f"  LinkedIn {label}: {n}/{len(searches)} searches, {len(seen)} postings so far", file=sys.stderr, flush=True)
        if only:
            c["searched"].extend(only)
        for jid, title, comp, loc, date, company_page in linkedin_cards(params, limit):
            nc = norm(comp)
            if jid in seen or (only and not any(nc.startswith(o) or o.startswith(nc) for o in only)):
                continue
            seen.add(jid)
            if not title_ok(title) or is_excluded_company(comp) or nc in skip \
                    or on_own_board(c["boards"]["titles"], comp, title=title):
                continue
            if jid not in LI_DETAILS:
                d = li_get(f"{LI_API}/jobPosting/{jid}")
                i = d.text.find("show-more-less-html__markup") if d.ok else -1
                LI_DETAILS[jid] = strip_html(d.text[i:i + 20000]) if i > 0 else ""
            yield Job(comp, title, loc, f"https://www.linkedin.com/jobs/view/{jid}/", parse_ts(date),
                      LI_DETAILS[jid], remote="remote" in loc.lower(), meta={"source": "LinkedIn (aggregator)", "company_page": company_page})


FETCHERS = {f.__name__: f for f in (greenhouse, lever, ashby, smartrecruiters, workday, oracle, rippling, eightfold, recruitee, portal, amazon, microsoft, atlassian, google, linkedin)}


def title_key(title):
    return " ".join(re.findall(r"[a-z0-9]+", title.lower()))


def same_or_alias(n, k):
    """Normalised names of the same company: equal, or one a prefix of the other ('amazonwebservicesaws' / 'amazon').
    The shorter name must have 5+ characters, so 'cred' doesn't swallow 'credgenics'."""
    return n == k or (min(len(n), len(k)) >= 5 and (n.startswith(k) or k.startswith(n)))


def on_own_board(board_titles, *names, title):
    """True if the company's own board lists this title. Matches aliases by prefix, e.g.
    'Amazon Web Services (AWS)' or 'Walmart Global Tech India' against the 'Amazon' / 'Walmart' boards."""
    key = title_key(title)
    for n in {norm(x) for x in names}:
        for k, titles in board_titles.items():
            if key in titles and same_or_alias(n, k):
                return True
    return False


def board_titles_now(companies):
    """Titles each company currently lists on its own board, from the latest raw files."""
    return {norm(c["name"]): {title_key(j.title) for j in load_raw(c["name"])[0]}
            for c in companies if c["ats"] != "linkedin"}


def norm(name):
    return re.sub(r"\b(pvt|private|ltd|limited|inc|llc|technologies|technology|india|solutions|labs|software|the)\b|[^a-z0-9]", "",
                  name.lower())


TIERS = json.loads((ROOT / "tiers.json").read_text())


def words(name):
    return re.findall(r"[a-z0-9]+", name.lower())


EXCLUDED_NAMES = [w for w in (words(x) for x in PROFILE["exclude_companies"] + TIERS["services_and_staffing"]) if w]
STAFFING_WORDS = [w for w in (words(x) for x in TIERS.get("staffing_keywords", [])) if w]


def is_excluded_company(name):
    """Services/staffing firms and the user's own exclusions. A listed name must be the company name's
    leading words ('EY' matches 'EY GDS' but not 'Honeywell'; 'UST' not 'Northern Trust'); staffing
    keywords ('Recruitment', 'Staffing'...) match as whole words anywhere in the name."""
    w = words(name)
    if any(w[:len(x)] == x for x in EXCLUDED_NAMES):
        return True
    padded = f" {' '.join(w)} "
    return any(f" {' '.join(k)} " in padded for k in STAFFING_WORDS)


# ---------------------------------------------------------------- evaluation

EXP_RE = re.compile(
    r"(?<![\d.])(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*\+?)?\s*(?:years?|yrs?)(?:\s+of)?(?=[^.\n]{0,80}(?:experience|exp\b|industry|software|engineering|development|professional|building))",
    re.I)


# "Years of Experience: Minimum 6-8 years", "Experience: 2+ yrs", "Experience required - 3 to 5 years".
# A bare dash is not a label: in bulleted JDs "...development experience\n- 2+ years of..." is the next bullet.
EXP_LABEL_RE = re.compile(
    r"(?:years?\s+of\s+)?experience(?:\s*(?:required|needed)\s*[:\-–]?|\s*:)\s*(?:minimum|min\.?|at\s*least)?\s*(\d{1,2})\s*(?:\+|plus)?\s*"
    r"(?:(?:-|–|to)\s*\d{1,2}\s*)?(?:years?|yrs?)", re.I)


def min_experience(text):
    """Smallest minimum-years figure the JD asks for, plus the snippet it came from."""
    found = []
    for m in list(EXP_RE.finditer(text)) + list(EXP_LABEL_RE.finditer(text)):
        lo = int(m.group(1))
        if lo <= 15:
            found.append((lo, text[max(0, m.start() - 20): m.end() + 40].replace("\n", " ").strip()))
    if not found:
        return None, ""
    return min(found, key=lambda x: x[0])


def posted_pay_lpa(s):
    """Lowest INR figure in a posted range, as LPA. None if no INR amount."""
    if not s or not re.search(r"₹|INR|LPA|lakh", s, re.I):
        return None
    vals = []
    for m in re.finditer(r"(?:₹|INR)\s*([\d,.]+)\s*([KkLM]|lakhs?|lpa)?", s):
        n = float(m.group(1).replace(",", ""))
        unit = (m.group(2) or "").lower()
        n *= {"k": 1e3, "m": 1e6, "l": 1e5, "lakh": 1e5, "lakhs": 1e5, "lpa": 1e5}.get(unit, 1)
        vals.append(n / 1e5)
    vals += [float(x) for x in re.findall(r"([\d.]+)\s*(?:LPA|lakhs?)", s, re.I)]
    vals = [v for v in vals if 1 <= v <= 500]
    return min(vals) if vals else None


def location_mode(job, company):
    loc = job.location.lower()
    text = job.text.lower()
    mode = "remote" if job.remote or "remote" in loc else "hybrid" if "hybrid" in text or "hybrid" in loc else "on-site/hybrid (check JD)"
    if any(k in loc for k in HOME):
        return True, f"Bengaluru, {mode}"
    if not in_india(job.location):
        return False, "outside India"
    if mode == "remote":
        return True, "Remote (India)"
    if company["quality"] >= PROFILE["location"]["other_city_min_quality"]:
        return True, f"{job.location.split('/')[0].strip()} ({mode})"
    return False, "other Indian city, not remote"


def stack_score(text):
    t = text.lower()
    hits = [(label, w) for label, pat, w in PROFILE["stack"] if re.search(pat, t)]
    score = sum(w for _, w in hits)
    gaps = [g for g, pat in PROFILE["gaps"].items() if re.search(pat, t)]
    # A JD built around a language I don't use gets capped even if infra words match.
    if any(g in gaps for g in ("Go", "C++", "Rust", "Scala", "C#/.NET", "Kotlin")) and not re.search(r"\bjava\b", t):
        score = min(score, 20)
    return min(score, 35), [label for label, _ in hits], gaps


def level_score(title, years):
    t = title.lower()
    if years is None:
        if re.search(r"\b(i|1|associate)\b", t):
            return 17
        if re.search(r"\b(ii|2)\b", t):
            return 16
        return 13
    return {0: 17, 1: 20, 2: 19, 3: 13}.get(years, 0)  # ~1-2 years is the sweet spot; 3+ is a stretch


def exp_band(years):
    return "not stated" if years is None else "0–1 yrs" if years <= 1 else f"{years} yrs"


def fresh_score(posted):
    if posted is None:
        return 3 + 3
    age = (NOW - posted).days
    base = 7 if age <= 7 else 6 if age <= 14 else 5 if age <= 21 else 2
    return base + 3  # +3 for a company careers/ATS link; main() takes it back for aggregator links


def evaluate(job, company, max_age):
    if "<" in job.company or len(job.company) > 120:
        return None, "malformed company name (parser)"
    if not title_ok(job.title):
        return None, "title/level"
    ok, mode = location_mode(job, company)
    if not ok:
        return None, mode
    if re.search(PROFILE["exclude_text"], job.text, re.I) or re.search(r"intern|contract|temporary", (job.meta.get("commitment") or "") + (job.meta.get("employmentType") or ""), re.I):
        return None, "contract/intern/temporary"
    years, snippet = min_experience(job.text)
    m = re.search(r"(\d{1,2})\s*(?:\+|-|–|to)\s*(?:\d{1,2}\s*)?(?:years?|yrs?)", job.title, re.I)
    if m:  # "4 to 8 years" in the title beats boilerplate in the body
        years, snippet = int(m.group(1)), job.title
    if years is not None and years > PROFILE["max_min_years"]:
        return None, f"{years}+ yrs asked"
    if company.get("below_title") and re.search(company["below_title"], job.title, re.I):
        return None, f"pay below bar at this level ({company['pay_note']})"
    if company["pay"] == "below":
        return None, f"pay below bar ({company['pay_note']})"
    pay_lpa = posted_pay_lpa(job.pay_posted or job.text)
    if pay_lpa is not None and pay_lpa < PROFILE["min_pay_lpa"]:
        return None, f"posted pay {pay_lpa:.0f} LPA below bar"
    if pay_lpa is not None:
        pay_conf, pay_pts, pay_txt = "Posted", 20, f"≥{pay_lpa:.0f} (Posted: {job.pay_posted[:60] or 'JD'})"
    elif company["pay"] == "likely" and "levels.fyi" in company["pay_note"].lower():
        pay_conf, pay_pts, pay_txt = "Strong evidence", 16, f"Strong — {company['pay_note']} (total comp, not fixed CTC)"
    elif company["pay"] == "likely":
        pay_conf, pay_pts, pay_txt = "Likely", 10, f"Likely ≥20 — {company['pay_note']} (tier judgement, no direct data)"
    else:  # no evidence either way: goes to the leads file, not the shortlist
        pay_conf, pay_pts, pay_txt = "Unverified", 0, f"Unverified — {company['pay_note']}"
    stale = job.posted is not None and (NOW - job.posted).days > max_age
    s_stack, hits, gaps = stack_score(job.text)
    s_level = level_score(job.title, years)
    score = s_stack + s_level + pay_pts + company["quality"] + fresh_score(job.posted)
    return {
        "score": score,
        "company": job.company,
        "type": company["type"] + (f"; {company['funding']}" if company.get("funding") else ""),
        "title": job.title.strip(),
        "location": mode,
        "exp_asked": f"{years}+ yrs" if years is not None else "not stated",
        "exp_band": exp_band(years),
        # Sweet spot: asks at most 2 years (campus hiring is already excluded) and pay is evidenced, not guessed.
        "sweet_spot": "yes" if years is not None and years <= 2 and pay_conf in ("Posted", "Strong evidence") else "",
        "exp_snippet": snippet,
        "pay": pay_txt,
        "source": job.meta.get("source", "company careers/ATS"),
        "pay_conf": pay_conf,
        "stack": ", ".join(hits[:8]),
        "gaps": ", ".join(gaps) or "none obvious",
        "url": job.url,
        "posted": job.posted.date().isoformat() if job.posted else "unknown",
        "listed_open": "yes (live on ATS)",
        "older_than_window": "yes" if stale else "",
        "breakdown": f"stack {s_stack}/35, level {s_level}/20, pay {pay_pts}/20, company {company['quality']}/15, fresh {fresh_score(job.posted)}/10",
    }, ""


# ---------------------------------------------------------------- main

RAW = OUT / "raw"  # one file per source, so a slow or failed source never blocks or empties the others
EVAL_LOCK = threading.Lock()


def raw_path(name):
    return RAW / (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") + ".json")


def load_raw(name):
    p = raw_path(name)
    if not p.exists():
        return [], None
    d = json.loads(p.read_text())
    return [Job(**j | {"posted": parse_ts(j["posted"])}) for j in d["jobs"]], d


def save_raw(name, jobs, note=""):
    RAW.mkdir(parents=True, exist_ok=True)
    raw_path(name).write_text(json.dumps({"source": name, "fetched_at": NOW.isoformat(timespec="seconds"), "note": note,
                                          "jobs": [asdict(j) | {"posted": j.posted.isoformat() if j.posted else None} for j in jobs]}))


def with_previous(name, fresh):
    """Fresh jobs topped up with the source's previous jobs that weren't seen again (yet)."""
    old, _ = load_raw(name)
    have = {j.url for j in fresh}
    return fresh + [j for j in old if j.url not in have]


def crawl(company, ctx):
    """Fetch one source and save its raw file. LinkedIn sources checkpoint every few dozen postings:
    the raw file (fresh + not-yet-refreshed previous jobs) is saved and the shortlist and dashboard
    are rebuilt, so results appear while LinkedIn is still running."""
    started = time.time()
    jobs, err = [], None
    is_li = company["ats"] == "linkedin"
    try:
        for job in FETCHERS[company["ats"]](company):
            jobs.append(job)
            if is_li and len(jobs) % PROFILE["linkedin"]["checkpoint_every"] == 0:
                checkpoint(company, jobs, ctx)
    except Exception as e:  # one broken board should not kill the run; keep what it fetched before failing
        err = f"{type(e).__name__}: {str(e)[:120]}"
    if is_li:
        kept, closed = keep_open_earlier(company["name"], jobs, ctx["max_age"])
        note = f"{len(jobs)} fresh + {len(kept)} earlier still open; {closed} closed dropped"
        save_raw(company["name"], jobs + kept, f"{err} — {note}" if err else "")
    elif err:
        merged = with_previous(company["name"], jobs)
        save_raw(company["name"], merged, f"{err} — {len(jobs)} fresh + {len(merged) - len(jobs)} from previous crawl")
    else:
        save_raw(company["name"], jobs)  # a board's own listing is authoritative: anything missing has closed
    if is_li:
        checkpoint(company, None, ctx)
    print(f"{company['name']:<22} {len(jobs):>4} fetched  {time.time() - started:5.1f}s{'  ERROR ' + err if err else ''}",
          file=sys.stderr, flush=True)
    return company["name"], err


LIVENESS_FILE = OUT / "linkedin-liveness.json"
LIVENESS_LOCK = threading.Lock()  # both LinkedIn passes update the same state file


def li_job_id(url):
    m = re.search(r"/view/(\d+)", url)
    return m.group(1) if m else url


def li_status(job_id):
    """'open' or 'closed' from LinkedIn's public job page (removed postings return 404; closed ones say
    'No longer accepting applications'). None if LinkedIn rate-limits or errors."""
    try:
        r = li_get(f"{LI_API}/jobPosting/{job_id}")
    except (RateLimited, requests.RequestException):
        return None
    if r.status_code in (404, 410) or (r.ok and "no longer accepting applications" in r.text.lower()):
        return "closed"
    return "open" if r.ok else None


def keep_open_earlier(name, fresh, max_age):
    """Earlier LinkedIn postings that this run didn't see again: keep the ones still open, drop the closed.
    The company sweep rotates and searches only cover the last max_age days, so not seeing a posting
    doesn't mean it closed. Each run checks a budget of them on LinkedIn, the ones about to age out first.
    Unchecked postings are kept while younger than max_age; older ones only once confirmed open,
    so long-running open roles stay and dead ones go."""
    seen = {j.url for j in fresh}
    earlier = [j for j in load_raw(name)[0] if j.url not in seen]
    with LIVENESS_LOCK:
        state = json.loads(LIVENESS_FILE.read_text()) if LIVENESS_FILE.exists() else {}
    cutoff = NOW - timedelta(days=max_age)
    recheck_after = (NOW - timedelta(days=PROFILE["linkedin"]["liveness_recheck_days"])).strftime("%Y-%m-%d")
    last = lambda j: state.get(li_job_id(j.url), {}).get("checked", "")  # noqa: E731
    due = sorted((j for j in earlier if last(j) < recheck_after),
                 key=lambda j: (bool(j.posted and j.posted >= cutoff), last(j)))  # about to age out first
    updates = {}
    for j in due[:PROFILE["linkedin"]["liveness_checks_per_run"]]:
        status = li_status(li_job_id(j.url))
        if status is None:
            break  # rate-limited: stop; the rest keep their previous state
        updates[li_job_id(j.url)] = {"status": status, "checked": TODAY}
    with LIVENESS_LOCK:  # merge only our changes: the other pass may have saved in the meantime
        current = json.loads(LIVENESS_FILE.read_text()) if LIVENESS_FILE.exists() else {}
        current.update(updates)
        LIVENESS_FILE.write_text(json.dumps(current))
    state.update(updates)
    kept, closed = [], 0
    for j in earlier:
        status = state.get(li_job_id(j.url), {}).get("status")
        if status == "closed":
            closed += 1
        elif status == "open" or (j.posted and j.posted >= cutoff):
            kept.append(j)
    return kept, closed


def checkpoint(company, jobs, ctx):
    with EVAL_LOCK:
        if jobs is not None:
            save_raw(company["name"], with_previous(company["name"], jobs), "in progress")
        LI_DETAILS_FILE.write_text(json.dumps(LI_DETAILS))
        state = ctx["sweep_state"]
        state.update({norm(n): TODAY for n in company.get("searched", [])})
        (OUT / "sweep-state.json").write_text(json.dumps(state, indent=0))
        evaluate_all(ctx, quiet=jobs is not None)


def write_bank(companies, activity, direct, sweep):
    """The company bank: every company we track, whether or not it is hiring today, with run history,
    so quiet companies stay on the watchlist and a company that starts hiring again stands out."""
    stamp = TODAY
    hist_file = OUT / "bank-history.json"
    hist = json.loads(hist_file.read_text()) if hist_file.exists() else {}
    swept = {norm(n) for n in sweep}
    tracked = {norm(c["name"]): c for c in TIERS["known"]}
    tracked.update({norm(c["name"]): c for c in companies if c["ats"] != "linkedin"})
    for name, act in activity.items():  # companies discovered this run (not yet in tiers.json)
        if norm(name) not in tracked and act["leads"]:
            tracked[norm(name)] = {"name": name, "type": "Discovered via LinkedIn — add to tiers.json", "quality": 0,
                                   "pay": "unclear", "pay_note": "not yet checked"}
    rows = []
    for key, c in tracked.items():
        act = activity.get(c["name"], {"seen": 0, "fitting": 0, "leads": 0})
        h = hist.setdefault(key, {"name": c["name"], "runs": {}})
        h["runs"][stamp] = [act["seen"], act["fitting"]]
        fit_dates = sorted(d for d, (_, f) in h["runs"].items() if f)
        before = [d for d in fit_dates if d < stamp]
        status = ("hiring now (new since last run)" if act["fitting"] and not before and len(h["runs"]) > 1 else
                  "hiring now" if act["fitting"] else
                  "pay unverified — check levels.fyi" if act["leads"] else
                  "quiet — keep watching" if c.get("pay") != "below" else "pay below bar")
        rows.append({"company": c["name"], "type": c.get("type", ""), "pay": c.get("pay", ""), "pay_note": c.get("pay_note", ""),
                     "covered_by": "own job board" if key in direct else "LinkedIn company sweep" if key in swept else "LinkedIn generic search only",
                     "eng_postings_seen_today": act["seen"], "fitting_today": act["fitting"], "leads_today": act["leads"],
                     "last_date_with_fitting_role": fit_dates[-1] if fit_dates else "never (so far)", "status": status})
    hist_file.write_text(json.dumps(hist, indent=0))
    rows.sort(key=lambda r: (-r["fitting_today"], -r["leads_today"], r["company"].lower()))
    with open(OUT / f"company-bank-{stamp}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def build_context(args):
    companies = json.loads((ROOT / "companies.json").read_text())["companies"]
    excluded = [x.lower() for x in PROFILE["exclude_companies"]]
    companies = [c for c in companies if c["name"].lower() not in excluded]

    # Pay evidence gathered into tiers.json also applies to companies crawled from their own boards.
    evidence = {norm(c["name"]): c for c in TIERS["known"]}  # the bank is the record of pay research
    for c in companies:
        e = evidence.get(norm(c["name"]))
        if e:
            c.update({k: e[k] for k in ("pay", "pay_note", "below_title") if k in e})
    direct = {norm(c["name"]) for c in companies if c["ats"] != "linkedin"}
    sweep = sorted({c["name"] for c in TIERS["known"]
                    if not any(same_or_alias(norm(c["name"]), d) for d in direct) and c.get("pay") in ("likely", "unclear")
                    and (c.get("pay") == "likely" or c.get("quality", 0) >= PROFILE["linkedin"]["company_sweep"]["min_quality"])},
                   key=norm)
    sweep = list({norm(n): n for n in sweep}.values())  # one search per company, not per alias
    # Rotating sweep: LinkedIn rate-limits unsigned clients, so each run searches a budget of companies.
    # Companies active last run come first, then never-searched ones, then the least recently searched,
    # higher quality first within each group, so the whole bank is covered every couple of runs.
    state_file = OUT / "sweep-state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    hist_file = OUT / "bank-history.json"
    hist = json.loads(hist_file.read_text()) if hist_file.exists() else {}
    def active(n):
        runs = hist.get(norm(n), {}).get("runs", {})
        return bool(runs) and runs[max(runs)][1] > 0
    quality = {norm(c["name"]): c.get("quality", 0) for c in TIERS["known"]}
    # Light runs: companies active last run, then top-tier ones (quality >= 13: the big employers with no
    # readable job board), each group least-recently-searched first; deep runs rotate through the whole bank.
    tier = PROFILE["linkedin"]["company_sweep"]["top_tier_quality"]
    sweep.sort(key=lambda n: (not active(n), not DEEP and quality.get(norm(n), 0) < tier, norm(n) in state,
                              state.get(norm(n), ""), -quality.get(norm(n), 0)))
    sweep = sweep[:PROFILE["linkedin"]["company_sweep"]["deep_companies_per_run" if DEEP else "companies_per_run"]]
    below = {norm(c["name"]) for c in TIERS["known"] if c.get("pay") == "below"}
    # Titles each company lists on its own board: a LinkedIn posting is a duplicate only if its title is
    # there too (some companies post roles on LinkedIn that their board doesn't show).
    # Shared holder: evaluation swaps in a fresh table with one assignment while the LinkedIn passes read
    # it from other threads, so readers always see a complete table.
    boards = {"titles": board_titles_now(companies)}
    for c in companies:
        if c["ats"] == "linkedin":
            c["skip_companies"] = below  # their LinkedIn postings would be dropped anyway
            c["boards"] = boards
            if c.get("mode") == "sweep":
                c["sweep_companies"] = sweep
    lookup = {norm(c["name"]): c for c in TIERS["known"]}
    lookup.update({norm(c["name"]): c for c in companies})
    return {"companies": companies, "direct": direct, "boards": boards, "sweep": sweep, "lookup": lookup, "sweep_state": state,
            "max_age": args.max_age}


def evaluate_all(ctx, quiet=False):
    """Score every source's latest raw file and write the shortlist, leads, rejected, company bank,
    report table and dashboard. Fast: no network, so it can run after every LinkedIn checkpoint."""
    companies, lookup, direct = ctx["companies"], ctx["lookup"], ctx["direct"]

    def resolve(name):
        n = norm(name)
        if n in lookup:
            return lookup[n]
        hit = next((v for k, v in lookup.items() if same_or_alias(n, k)), None)
        return hit or {"name": name, "type": "Unknown — check stage/funding", "quality": 8, "pay": "unclear",
                       "pay_note": "company not in tiers.json"}

    ctx["boards"]["titles"] = titles = board_titles_now(companies)  # boards may have just been re-crawled
    keep, leads, rejected, errors, seen_urls = [], [], [], [], set()
    activity = collections.defaultdict(lambda: {"seen": 0, "fitting": 0, "leads": 0})
    for source in companies:
        jobs, meta = load_raw(source["name"])
        if meta and meta.get("note"):
            errors.append(f"{source['name']}: {meta['note']} (fetched {meta['fetched_at']})")
        for job in jobs:
            if job.url in seen_urls or not in_india(job.location + (" india" if job.remote and "india" in job.text.lower()[:400] else "")):
                continue
            seen_urls.add(job.url)
            company = source
            if source["ats"] == "linkedin":
                company = resolve(job.company)
                if on_own_board(titles, company["name"], job.company, title=job.title) or is_excluded_company(job.company):
                    continue  # the company's own board lists this role, or a services/staffing firm
            row, why = evaluate(job, company, ctx["max_age"])
            act = activity[company["name"] if company.get("pay") != "unclear" or norm(company["name"]) in lookup else job.company]
            act["seen"] += 1
            act["fitting"] += bool(row) and row["pay_conf"] != "Unverified"
            act["leads"] += bool(row) and row["pay_conf"] == "Unverified"
            if row and source["ats"] == "linkedin":  # both LinkedIn passes
                row["score"] -= 3  # aggregator link, not the company's own page
                row["company"] = job.company
            if row and row["pay_conf"] == "Unverified":
                leads.append(row)
            elif row:
                keep.append(row)
            elif why != "title/level":
                rejected.append({"company": job.company, "title": job.title, "location": job.location, "reason": why, "url": job.url})

    write_bank(companies, activity, direct, ctx["sweep"])
    keep.sort(key=lambda r: (-r["score"], r["posted"]))
    groups = {}
    for r in keep:
        key = (r["company"], re.sub(r"\W+", " ", r["title"].lower()).strip(), r["location"])
        if key in groups:
            groups[key]["reqs"] += 1
            groups[key]["other_links"] += " " + r["url"]
        else:
            groups[key] = r | {"reqs": 1, "other_links": ""}
    keep = list(groups.values())

    # NEW = first seen today. Stored per URL with its first-seen date, so rebuilding several times
    # in one day (LinkedIn checkpoints, --rescore) doesn't reset the flag.
    stamp = TODAY
    seen_file = OUT / "seen.json"
    first_seen = json.loads(seen_file.read_text()) if seen_file.exists() else {}
    if isinstance(first_seen, list):  # older format: plain list of URLs
        first_seen = {u: "2026-11-05" for u in first_seen}
    for r in keep + leads:
        first_seen.setdefault(r["url"], stamp)
        r["new"] = "NEW" if first_seen[r["url"]] == stamp and len(set(first_seen.values())) > 1 else ""
    seen_file.write_text(json.dumps(first_seen, indent=0))

    cols = list(keep[0].keys()) if keep else []
    with open(OUT / f"jobs-{stamp}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(keep)
    leads.sort(key=lambda r: -r["score"])
    with open(OUT / f"leads-unverified-pay-{stamp}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, list(leads[0].keys()) if leads else ["company"])
        w.writeheader()
        w.writerows(leads)
    with open(OUT / f"rejected-{stamp}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, ["company", "title", "location", "reason", "url"])
        w.writeheader()
        w.writerows(rejected)

    md = [f"# Job crawl {stamp}", "", f"{len(keep)} roles kept, {len(leads)} leads with unverified pay (see leads CSV), {len(rejected)} rejected after title filter.", "",
          "| # | Company | Type / stage | Role | Location / mode | Exp asked | Pay + confidence | Key stack | Score | Gaps | Link | Posted |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(keep, 1):
        md.append(f"| {i} | {r['company']} | {r['type']} | {r['title']}{f" ({r['reqs']} reqs)" if r['reqs'] > 1 else ""} {r['new']} | {r['location']} | {r['exp_asked']} | {r['pay']} | {r['stack']} | {r['score']} | {r['gaps']} | [link]({r['url']}) | {r['posted']} |")
    if errors:
        md += ["", "## Sources with problems", ""] + [f"- {e}" for e in errors]
    (OUT / f"jobs-{stamp}.md").write_text("\n".join(md) + "\n")

    import build_dashboard, report  # local modules; imported here to keep crawl.py usable on its own
    report.main([])
    build_dashboard.main()
    if not quiet:
        print(f"\n{len(keep)} roles, {len(leads)} leads, {len(rejected)} rejected, {len(errors)} sources with problems "
              f"-> dashboard.html rebuilt", file=sys.stderr, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", choices=("fast", "linkedin", "all"), default="all",
                    help="fast = company job boards (~3 min); linkedin = LinkedIn passes (slow, rebuilds as it goes); all = fast then linkedin")
    ap.add_argument("--only", help="comma-separated company names to re-crawl")
    ap.add_argument("--max-age", type=int, default=PROFILE["max_age_days"])
    ap.add_argument("--deep", action="store_true",
                    help="LinkedIn deep mode: per-city searches + big company sweep (hours; occasional use)")
    ap.add_argument("--rescore", action="store_true", help="re-score the saved raw data (after editing tiers.json/profile.json) without fetching")
    args = ap.parse_args()
    global DEEP
    DEEP = args.deep
    ctx = build_context(args)
    if not args.rescore:
        sources = [c for c in ctx["companies"] if c["name"].lower() in {x.strip().lower() for x in args.only.split(",")}] \
            if args.only else ctx["companies"]
        fast = [c for c in sources if c["ats"] != "linkedin"]
        slow = [c for c in sources if c["ats"] == "linkedin"]
        if args.sources in ("fast", "all") and fast:
            with ThreadPoolExecutor(16) as pool:  # boards are on different hosts, so this is polite per host
                list(pool.map(lambda c: crawl(c, ctx), fast))
            evaluate_all(ctx)  # results from company boards are usable now; LinkedIn data is the previous crawl's
        if args.sources in ("linkedin", "all") and slow:
            with ThreadPoolExecutor(len(slow)) as pool:  # both passes share one throttle, so this stays polite
                list(pool.map(lambda c: crawl(c, ctx), slow))
        return
    evaluate_all(ctx)


if __name__ == "__main__":
    main()
