"""Round-11 job-board readers, with saved fixtures (no network): Klimb, Deel, the generic cards reader, BillDesk's
JS bundle, and the sitemap reader's page_data option (Joveo's __NEXT_DATA__ job pages).

Usage: python3 tests/test_sources_round11.py <path to the job-search folder>
Fixtures: tests/fixtures/round11/ (synthetic pages that copy each site's structure).
"""
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
import crawl  # noqa: E402
from portals import billdesk, cards, deel, klimb, sitemap  # noqa: E402

FX = Path(sys.argv[1]).resolve() / "tests" / "fixtures" / "round11"
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def fx(name):
    return (FX / name).read_text()


def raises(fn, exc=ValueError):
    try:
        list(fn())
    except exc:
        return True
    return False


def fake_h(json_by_url=None, pages=None, calls=None):
    """h for the readers: h.get answers JSON, SESSION.get answers page text; the first key contained in the URL wins."""
    def pick(table, url):
        for k, v in (table or {}).items():
            if k in url:
                return v
        raise crawl.requests.RequestException(f"no fixture for {url}")

    def page(url, **k):
        if calls is not None:
            calls.append(url)
        text = pick(pages, url)
        return SimpleNamespace(text=text, status_code=200, content=text.encode(), raise_for_status=lambda: None)

    def get(url, params=None, **k):
        if calls is not None:
            calls.append(url + " " + json.dumps(params or {}))
        v = pick(json_by_url, url + " " + json.dumps(params or {}))
        return v(params) if callable(v) else v
    return SimpleNamespace(Job=crawl.Job, title_ok=crawl.title_ok, in_india=crawl.in_india, strip_html=crawl.strip_html,
                           parse_ts=crawl.parse_ts, get=get, SESSION=SimpleNamespace(get=page, headers={"User-Agent": "test"}))


# --- Klimb (India Mart) ---------------------------------------------------------------------------------------
calls = []
p1, p2 = json.loads(fx("klimb_p1.json")), json.loads(fx("klimb_p2.json"))
h = fake_h({'"lastPosId": "ffffffffffffffffffffffff"': p1, '"lastPosId": "6af6a347c8c46ac30f8f4cf6"': p2}, calls=calls)
got = list(klimb.fetch({"name": "IM", "company": "acme", "delay": 0}, h))
check("klimb: pages from the top cursor to showLoadMore=false, cursor = last id of the page before",
      [c for c in calls if "joblist.klimb.io/acme" in c] == ['https://joblist.klimb.io/acme {"lastPosId": "ffffffffffffffffffffffff"}',
                                                           'https://joblist.klimb.io/acme {"lastPosId": "6af6a347c8c46ac30f8f4cf6"}'], calls)
check("klimb: India + fitting titles only (sales role, Dubai role and a remote role without remote_india dropped)",
      [(j.title, j.location) for j in got] == [("Software Engineer - Backend", "Noida, Uttar Pradesh, India"),
                                               ("Android Developer", "Noida, Uttar Pradesh, India")], [(j.title, j.location) for j in got])
check("klimb: widget link, ObjectId creation time as the posting date, years asked, script text dropped, feed salary in meta only",
      got and got[0].url == "https://jobs.klimb.io/acme/6afe8f11959ab66da6cf450e" and got[0].posted and got[0].posted.year == 2026
      and got[0].text.startswith("Experience: 2-5 years") and "alert" not in got[0].text and "Own APIs" in got[0].text
      and got[0].pay_posted == "" and "1500000" in got[0].meta.get("salary_feed", ""), got and (got[0].url, got[0].text, got[0].meta))
got = list(klimb.fetch({"name": "IM", "company": "acme", "delay": 0, "remote_india": True}, h))
check("klimb: remote_india keeps a remote role", ("Software Engineer", "India (remote)") in [(j.title, j.location) for j in got])
check("klimb: a reply without jobs.positions raises (not 'every role closed')",
      raises(lambda: klimb.fetch({"name": "IM", "company": "acme", "delay": 0}, fake_h({"klimb.io": {"error": "not found"}}))))
check("klimb: positions that all fail to parse (id renamed) raise instead of reading as no openings",
      raises(lambda: klimb.fetch({"name": "IM", "company": "acme", "delay": 0},
                                 fake_h({"klimb.io": {"jobs": {"positions": [dict(p, _id=p["id"], id=None) for p in p1["jobs"]["positions"]]},
                                                      "showLoadMore": False}}))))
check("klimb: an empty positions list is still a board with no openings",
      list(klimb.fetch({"name": "IM", "company": "acme", "delay": 0}, fake_h({"klimb.io": {"jobs": {"positions": []}, "showLoadMore": False}}))) == [])
rem = dict(p1["jobs"]["positions"][0], id="6afe8f11959ab66da6cf4501", remote=True,
           location={"searchText": "Noida, India", "gPlace": {"formatted_address": "Noida, India"}})
got = list(klimb.fetch({"name": "IM", "company": "acme", "delay": 0}, fake_h({"klimb.io": {"jobs": {"positions": [rem]}, "showLoadMore": False}})))
check("klimb: a remote role keeps its India place ('Noida, India (Remote)'), even without remote_india",
      [(j.location, j.remote) for j in got] == [("Noida, India (Remote)", True)], [(j.location, j.remote) for j in got])
check("klimb: place() of a remote role with no place is 'Remote'", klimb.place({"remote": True, "location": None}) == "Remote")
counter = iter(range(100))


def endless(params):
    row = dict(p1["jobs"]["positions"][0], id=f"6afe8f11959ab66da6cf45{next(counter):02d}")
    return {"jobs": {"positions": [row]}, "showLoadMore": True}


check("klimb: a board that never stops saying 'load more' raises after max_pages",
      raises(lambda: klimb.fetch({"name": "IM", "company": "acme", "delay": 0, "max_pages": 3}, fake_h({"klimb.io": endless}))))

# --- Deel (Zema Global) -----------------------------------------------------------------------------------------
h = fake_h(pages={"jobs.deel.com/acme": fx("deel_board.html")})
got = list(deel.fetch({"name": "Z", "board": "acme"}, h))
check("deel: jobPostings read from the RSC payload; India + fitting titles; ' | RQ-..' cut from the title; DBA and London dropped",
      [(j.title, j.location) for j in got] == [("Software Engineer (India)", "Navi Mumbai, India"), ("Backend Developer", "Pune, India")],
      [(j.title, j.location) for j in got])
check("deel: description resolved from its text row (byte length, non-ASCII safe); board link; createdAt date",
      got and "Build data pipelines in Python." in got[0].text and got[0].text.rstrip().endswith("Python.")
      and got[0].url == "https://jobs.deel.com/acme/job-details/f5fc6ab6-7fef-423b-a607-ed90a5169590/overview"
      and got[0].posted and got[0].posted.isoformat().startswith("2026-10-22"), got and (got[0].text, got[0].url))
check("deel: HTML in a title is stripped; REMOTE work arrangement flagged; a missing text row leaves an empty text",
      len(got) > 1 and "<" not in got[1].title and got[1].remote and got[1].text == "", got and [(j.title, j.remote, j.text) for j in got])
check("deel: a page without the jobPostings list (challenge page, redesign) raises",
      raises(lambda: deel.fetch({"name": "Z", "board": "acme"}, fake_h(pages={"jobs.deel.com": fx("deel_challenge.html")}))))

# --- cards (Indifi, TBX, Graph AI, Atomicwork, IgniteTech, IEX) -------------------------------------------------
cfg = {"name": "I", "url": "https://acme.test/careers", "card": ".tab-content div.panel", "title": "h3", "location": "h3 span.location",
       "detail": "div > p.margin-b-0, div.panel-body"}
got = list(cards.fetch(cfg, fake_h(pages={"acme.test/careers": fx("cards_panels.html")})))
check("cards: one job per card; title without its nested location; commented-out cards, managers and US roles dropped",
      [(j.title, j.location) for j in got] == [("Java Backend Developer", "Gurgaon, India"), ("NodeJs developer", "Gurgaon, India")],
      [(j.title, j.location) for j in got])
check("cards: page URL + '#<title slug>' as the link; detail text from the configured parts; script and svg text dropped",
      [j.url for j in got] == ["https://acme.test/careers#java-backend-developer", "https://acme.test/careers#nodejs-developer"]
      and "3+ years of experience in Java" in got[0].text and "solid Java Backend" in got[0].text
      and "document.write" not in got[1].text and "icon" not in got[1].text and "Node & MongoDB" in got[1].text,
      [(j.url, j.text) for j in got])
got = list(cards.fetch({"name": "T", "url": "https://tbx.test/careers", "card": "div.rounded-3xl", "title": "h2", "location": "div.text-gray-500 span"},
                       fake_h(pages={"tbx.test": fx("cards_tailwind.html")})))
check("cards: first matching span is the location; a repeated title gets its location in every copy's key; an exact repeat is one role",
      [(j.title, j.location, j.url) for j in got] == [("Junior java developer", "Mumbai", "https://tbx.test/careers#junior-java-developer-mumbai"),
                                                       ("Junior java developer", "Pune", "https://tbx.test/careers#junior-java-developer-pune")],
      [(j.title, j.location, j.url) for j in got])
check("cards: the whole card is the text when no detail selector is set (inline spans keep their spaces)",
      got and "Mumbai • Full Time • 1-4 years" in got[0].text, got and got[0].text)
got = list(cards.fetch({"name": "G", "url": "https://g.test/careers/", "card": "div.job-post-loop-item", "title": "h3", "location": "div.jd-info",
                        "location_re": "\\|\\s*([^|]+?)\\s*\\|"}, fake_h(pages={"g.test": fx("cards_elementor.html")})))
check("cards: location_re picks the place out of '3-5 years | Hyderabad, Telangana, India | In-office'; US role dropped",
      [(j.title, j.location) for j in got] == [("Full-stack Developer", "Hyderabad, Telangana, India")], [(j.title, j.location) for j in got])
calls = []
h = fake_h(pages={"/careers/i8caogrnrpsx": fx("cards_links_job.html"), "w.test/company/careers": fx("cards_links.html")}, calls=calls)
got = list(cards.fetch({"name": "A", "url": "https://w.test/company/careers", "card": "div.oj-item", "title": "h4", "location": ".location",
                        "link": "a[href]", "fetch_detail": "div.jd_wrapper", "delay": 0}, h))
check("cards: title from the card when links read 'Apply Now'; the card's own link kept, '#apply-now' and javascript: links replaced",
      [(j.title, j.url) for j in got] == [("Backend Engineer", "https://w.test/careers/i8caogrnrpsx"),
                                          ("Frontend Engineer", "https://w.test/company/careers#frontend-engineer"),
                                          ("Software Engineer", "https://w.test/company/careers#software-engineer")], [(j.title, j.url) for j in got])
check("cards: fetch_detail reads the linked job page's description (only for roles with their own link)",
      got and "2-4 years of experience building backend services" in got[0].text and "Platform Solutions" not in got[0].text
      and sum("/careers/" in u and "company" not in u for u in calls) == 1, (got and got[0].text, calls))
got = list(cards.fetch({"name": "K", "url": "https://ig.test/jobs", "card": "a[href^=/jobs/]", "title": "h3", "location": "div[class*=gap-3.5]",
                        "location_re": "\\b(Remote)\\s*$", "remote_worldwide": "open to candidates worldwide", "link": "a[href]"},
                       fake_h(pages={"ig.test": fx("cards_remote.html")})))
check("cards: remote_worldwide (stated on the page) makes a 'Remote' card India-eligible; the card itself is the link",
      [(j.title, j.location, j.remote, j.url) for j in got] == [("Software Engineer, AI-DNA, $100k/year USD", cards.WORLDWIDE, True,
                                                                  "https://ig.test/jobs/4adf68b4-4e1b-4fc3-bab0-afd02dc3d6a9")],
      [(j.title, j.location, j.url) for j in got])
page = fx("cards_remote.html").replace("open to candidates worldwide", "open to US candidates")
got = list(cards.fetch({"name": "K", "url": "https://ig.test/jobs", "card": "a[href^=/jobs/]", "title": "h3", "location": "div[class*=gap-3.5]",
                        "location_re": "\\b(Remote)\\s*$", "remote_worldwide": "open to candidates worldwide"}, fake_h(pages={"ig.test": page})))
check("cards: without the page saying 'worldwide', a remote card is dropped", got == [], [(j.title, j.location) for j in got])
got = list(cards.fetch({"name": "X", "url": "https://iex.test/career", "card": "h6.MuiTypography-h6", "card_parent": 1, "title": "h6",
                        "location_re": "^Location:\\s*(.+)$"}, fake_h(pages={"iex.test": fx("cards_parent.html")})))
check("cards: card_parent climbs from the heading to its box; location_re reads the card text; value headings without a place dropped",
      [(j.title, j.location) for j in got] == [("Software Engineer – Trading Systems", "Noida")], [(j.title, j.location) for j in got])
# cards: keys that don't depend on card order (review fix, 21 Nov 2026)
TWO = """<html><body>
<div class="job"><h3>Software Engineer</h3><span class="loc">Bangalore, India</span></div>
<div class="job"><h3>Software Engineer</h3><span class="loc">Pune, India</span></div>
<div class="job"><h3>Backend Engineer</h3><span class="loc">Pune, India</span></div>
</body></html>"""
kc = {"name": "O", "url": "https://o.test/careers", "card": "div.job", "title": "h3", "location": "span.loc"}
urls_fwd = sorted(j.url for j in cards.fetch(kc, fake_h(pages={"o.test": TWO})))
check("cards: a title shown twice carries its place in every copy's key (Bangalore and Pune); a unique title keeps '#<slug>'",
      urls_fwd == ["https://o.test/careers#backend-engineer", "https://o.test/careers#software-engineer-bangalore-india",
                   "https://o.test/careers#software-engineer-pune-india"], urls_fwd)
swapped = TWO.split("\n")
swapped[1], swapped[2] = swapped[2], swapped[1]
urls_rev = sorted(j.url for j in cards.fetch(kc, fake_h(pages={"o.test": "\n".join(swapped)})))
check("cards: the same cards in another order give the same keys", urls_fwd == urls_rev, (urls_fwd, urls_rev))
gone = TWO.replace('<div class="job"><h3>Software Engineer</h3><span class="loc">Bangalore, India</span></div>', "")
after = {j.location: j.url for j in cards.fetch(kc, fake_h(pages={"o.test": gone})) if "software" in j.url}
check("cards: when the Bangalore card goes away, Pune does not take over Bangalore's key",
      list(after) == ["Pune, India"] and after["Pune, India"] != "https://o.test/careers#software-engineer-bangalore-india", after)
HREFS = """<html><body>
<div class="job"><h3>Software Engineer</h3><span class="loc">Bangalore, India</span><a href="/jobs/101">Apply</a></div>
<div class="job"><h3>Software Engineer</h3><span class="loc">Bangalore, India</span><a href="/jobs/102">Apply</a></div>
<div class="job"><h3>Software Engineer</h3><span class="loc">Bangalore, India</span><a href="/jobs/102">Apply</a></div>
<div class="job"><h3>Software Engineer</h3><span class="loc">Bangalore, India</span></div>
</body></html>"""
got = [j.url for j in cards.fetch(kc | {"link": "a[href]"}, fake_h(pages={"o.test": HREFS}))]
check("cards: cards with their own href are keyed and deduplicated on it (same title and place, two hrefs: both kept)",
      got == ["https://o.test/jobs/101", "https://o.test/jobs/102", "https://o.test/careers#software-engineer"], got)

# cards: require (selectors that also match non-job boxes)
REQ = """<html><body>
<div class="shadow-xs"><h2>Software Engineering at Acme</h2><p>How we build.</p></div>
<div class="shadow-xs"><h2>Backend Developer</h2><p>Location: Noida</p></div>
</body></html>"""
rc = {"name": "R", "url": "https://r.test/career", "card": "div.shadow-xs", "title": "h2", "default_location": "Noida, India"}
check("cards: without require a non-job box with a role-like heading reads as a job",
      [j.title for j in cards.fetch(rc, fake_h(pages={"r.test": REQ}))] == ["Software Engineering at Acme", "Backend Developer"])
check("cards: require keeps only cards whose text matches it",
      [j.title for j in cards.fetch(rc | {"require": "^Location:"}, fake_h(pages={"r.test": REQ}))] == ["Backend Developer"])
check("cards: cards matched but none matches require raises (not 'no openings')",
      raises(lambda: cards.fetch(rc | {"require": "^Location:"}, fake_h(pages={"r.test": REQ.replace("Location:", "Place:")}))))
got = list(cards.fetch({"name": "X", "url": "https://iex.test/career", "card": "h6.MuiTypography-h6", "card_parent": 1, "title": "h6",
                        "location_re": "^Location:\\s*(.+)$", "require": "^Location:"}, fake_h(pages={"iex.test": fx("cards_parent.html")})))
check("cards: IEX's require '^Location:' drops the values box and keeps the job", [j.title for j in got] == ["Software Engineer – Trading Systems"],
      [j.title for j in got])
check("cards: a card selector that matches nothing raises (a redesign is not 'no openings')",
      raises(lambda: cards.fetch(cfg | {"card": "div.job-card"}, fake_h(pages={"acme.test": fx("cards_panels.html")}))))
check("cards: cards without any title raise too",
      raises(lambda: cards.fetch(cfg | {"title": "h5"}, fake_h(pages={"acme.test": fx("cards_panels.html")}))))
check("cards: default_location stands in for cards naming no place",
      [j.location for j in cards.fetch({"name": "A", "url": "https://a.test/c", "card": "div.rounded-3xl", "title": "h2",
                                        "default_location": "Bengaluru, India"}, fake_h(pages={"a.test": fx("cards_tailwind.html")}))]
      == ["Bengaluru, India"])
check("cards: selector subset (descendant, child, attribute operators)",
      [n.attrs.get("href") for n in cards.select(cards.parse('<div id="a"><p><a href="/x">1</a></p><a href="/y" data-k="v1">2</a></div>'),
                                                    '#a > a[data-k^=v], #a p > a[href*=x]')] == ["/y", "/x"])
check("cards: an unsupported selector is an error, not an empty match", raises(lambda: cards.select(cards.parse("<p></p>"), "p:has(a)")))

# --- BillDesk (jobs in the Vite bundle) ----------------------------------------------------------------------------
calls = []
h = fake_h(pages={"/web/assets/index-i6m0P47r.js": fx("billdesk_bundle.js"), "bd.test/web/careers": fx("billdesk_page.html")}, calls=calls)
got = list(billdesk.fetch({"name": "B", "url": "https://bd.test/web/careers", "delay": 0}, h))
check("billdesk: bundle found from the page's module script; currentOpenings parsed ('\\'' escapes too); India + fitting titles only",
      [(j.title, j.location, j.url) for j in got] == [("Java Backend Developer", "Mumbai, India", "https://bd.test/web/careers#java-backend-developer")]
      and calls == ["https://bd.test/web/careers", "https://bd.test/web/assets/index-i6m0P47r.js"], ([(j.title, j.location) for j in got], calls))
check("billdesk: years asked and every text field kept",
      got and got[0].text.startswith("Experience: 4-7 years") and "project's progress" in got[0].text and "Spring Boot" in got[0].text,
      got and got[0].text)
check("billdesk: a page without the bundle tag raises",
      raises(lambda: billdesk.fetch({"name": "B", "url": "https://bd.test/web/careers", "delay": 0},
                                    fake_h(pages={"bd.test": "<html><script src='/app.js'></script></html>"}))))
check("billdesk: a bundle without currentOpenings raises",
      raises(lambda: billdesk.fetch({"name": "B", "url": "https://bd.test/web/careers", "delay": 0},
                                    fake_h(pages={"index-i6m0P47r.js": "const a=1;", "bd.test": fx("billdesk_page.html")}))))

bd_js = """const t=JSON.parse(`{"currentOpenings":[
{"jobId":1,"jobHeader":"Java Developer","location":"Mumbai","info":"2 to 4 years | Tech | Mumbai"},
{"jobId":2,"jobHeader":"Java Developer","location":"Pune","info":"2 to 4 years | Tech | Pune"},
{"jobId":3,"jobHeader":"Java Developer","location":"Pune","info":"2 to 4 years | Tech | Pune"},
{"jobId":4,"jobHeader":"Backend Developer","location":"Mumbai","info":"2 to 4 years | Tech | Mumbai"}]}`);"""
got = [(j.title, j.location, j.url) for j in billdesk.fetch({"name": "B", "url": "https://bd.test/web/careers", "delay": 0},
       fake_h(pages={"index-i6m0P47r.js": bd_js, "bd.test": fx("billdesk_page.html")}))]
check("billdesk: same title in two places is two jobs, each key with its place; an exact repeat is one; a unique title keeps '#<slug>'",
      got == [("Java Developer", "Mumbai, India", "https://bd.test/web/careers#java-developer-mumbai"),
              ("Java Developer", "Pune, India", "https://bd.test/web/careers#java-developer-pune"),
              ("Backend Developer", "Mumbai, India", "https://bd.test/web/careers#backend-developer")], got)

# --- sitemap: page_data (Joveo) -------------------------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
real_out, real_session = crawl.OUT, crawl.SESSION
crawl.OUT = tmp / "output"
jv_pages = {"robots.txt": "User-agent: *\nAllow: /\nSitemap: https://careers.jv.test/job-sitemap.xml",
            "job-sitemap.xml": fx("joveo_sitemap.xml"), "job-sitemap-0.xml": fx("joveo_sitemap0.xml"),
            "/job/01a0481d": fx("joveo_job_unlocated.html"), "/job/01a048a1": fx("joveo_job_us.html"),
            "/job/01a04826": fx("joveo_job_india.html"), "/job/01a0482c": fx("joveo_job_closed.html")}


def jv_get(url, **kw):
    hit = next((v for k, v in jv_pages.items() if k in url), None)
    return SimpleNamespace(status_code=200 if hit is not None else 404, content=(hit or "").encode(), text=hit or "")


crawl.SESSION = SimpleNamespace(get=jv_get, headers={"User-Agent": "test"})
jc = {"name": "Joveo", "portal": "sitemap", "host": "careers.jv.test", "sitemaps": ["https://careers.jv.test/job-sitemap.xml"],
      "job_path": "careers\\.jv\\.test/job/[0-9a-f-]{36}$", "cache_pages": True,
      "page_data": {"script": "__NEXT_DATA__", "item": "props.pageProps.jobDetails", "title": "title",
                    "location": ["locations.*.city", "locations.*.state", "locations.*.country"], "description": "description",
                    "posted": "createdAt", "remote": "jobLocationType", "where": {"status": "OPEN"}, "default_location": "India"}}
got = sorted((j.title, j.location, j.remote) for j in sitemap.fetch(jc, crawl))
check("sitemap page_data: jobs read from __NEXT_DATA__; closed and US roles dropped; default_location only for an unlocated job",
      got == [("Backend Developer", "Bangalore, India", True), ("Software Engineer (AWS)", "India", False)], got)
got = list(sitemap.fetch({k: v for k, v in jc.items() if k != "page_data"} | {"name": "Joveo without page_data"}, crawl))
check("sitemap: without page_data such pages yield nothing (no JobPosting markup), as before", got == [], [j.title for j in got])
# sitemap page_data + cache_pages: cached jobs are read again after PAGE_DATA_RECHECK_DAYS (a job that turned CLOSED leaves)
from datetime import date, timedelta  # noqa: E402
cache_file = sitemap.cache_path(crawl, jc)
cached = json.loads(cache_file.read_text())
check("sitemap page_data: cached summaries carry the day they were read",
      all(s.get("read") == date.today().isoformat() for v in cached.values() if isinstance(v, list) for s in v), cached)
india_url = next(u for u in cached if "01a04826" in u)
reads = []


def counting_get(url, **kw):
    reads.append(url)
    return jv_get(url, **kw)


crawl.SESSION = SimpleNamespace(get=counting_get, headers={"User-Agent": "test"})
list(sitemap.fetch(jc, crawl))
check("sitemap page_data: a fresh cache entry is not read again", not any("/job/" in u for u in reads), reads)
old_day = (date.today() - timedelta(days=sitemap.PAGE_DATA_RECHECK_DAYS)).isoformat()
cached[india_url] = [dict(s, read=old_day) for s in cached[india_url]]
cache_file.write_text(json.dumps(cached))
jv_pages["/job/01a04826"] = fx("joveo_job_india.html").replace('"status": "OPEN"', '"status": "CLOSED"')
reads.clear()
got = sorted(j.title for j in sitemap.fetch(jc, crawl))
check("sitemap page_data: an entry older than the recheck window is read again, and a now-CLOSED job is dropped",
      got == ["Software Engineer (AWS)"] and any("01a04826" in u for u in reads), (got, reads))
jv_pages["/job/01a04826"] = fx("joveo_job_india.html")
cached = json.loads(cache_file.read_text())
cached[india_url] = [{"title": "Backend Developer", "locs": ["Bangalore, India"], "url": india_url, "posted": "", "until": "",
                      "remote": True, "remote_india": False, "text": "x", "type": ""}]  # cached before the "read" stamp existed
cache_file.write_text(json.dumps(cached))
del jv_pages["/job/01a04826"]  # the re-read fails (404)
got = sorted(j.title for j in sitemap.fetch(jc, crawl))
check("sitemap page_data: an unstamped (older) entry is due; a re-read that fails keeps the cached job",
      got == ["Backend Developer", "Software Engineer (AWS)"], got)
jv_pages["/job/01a04826"] = fx("joveo_job_india.html")
multi = {"locations": [{"city": "Reston", "state": "Virginia", "country": "United States"},
                       {"city": "Bangalore", "state": "Karnataka", "country": "India"}]}
check("sitemap page_data: each city paired with its own region and country",
      sitemap.paired_places(crawl, multi, ["locations.*.city", "locations.*.state", "locations.*.country"])
      == "Reston, Virginia, United States / Bangalore, Karnataka, India")
check("sitemap page_data: paths not under one list read as before (None from paired_places)",
      sitemap.paired_places(crawl, {"city": "Pune", "country": "India"}, ["city", "country"]) is None)
mpage = fx("joveo_job_india.html").replace('"locations": [{"city": "Bangalore", "state": null, "country": "India"}]',
                                           '"locations": ' + json.dumps(multi["locations"]))
got = sitemap.data_summaries(jc, crawl, mpage, "https://careers.jv.test/job/x")
check("sitemap page_data: a two-place job keeps both places, each whole",
      got and got[0]["locs"] == ["Reston, Virginia, United States / Bangalore, Karnataka, India"], got and got[0]["locs"])
crawl.OUT, crawl.SESSION = real_out, real_session

print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
