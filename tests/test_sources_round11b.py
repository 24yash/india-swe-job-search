"""Round eleven (b) readers, with saved pages (no network): jsonlist configs for Upstox (its careers page's public jobs API),
Pratilipi (TalentZQ) and Classplus, and the Homerun (Ghost), Webbtree (IdeaForge) and PocketHRMS (Agilitas) readers.

Usage: python3 tests/test_sources_round11b.py <path to the job-search folder>
Fixtures: tests/fixtures/round11b/ (real replies saved 21 Nov 2026, trimmed).
"""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT))
import crawl  # noqa: E402
from portals import homerun, jsonlist, pockethrms, webbtree  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "round11b"
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def raises(fn):
    try:
        list(fn())
    except Exception:
        return True
    return False


def fixture(name):
    return (FIX / name).read_text()


def page(text, status=200):
    return SimpleNamespace(text=text, status_code=status, raise_for_status=lambda: None, json=lambda: json.loads(text))


def h_for(json_by_url=None, pages=None):
    """h with get (JSON) and SESSION.get (page text); the first key contained in the URL wins."""
    def pick(table, url):
        for k, v in (table or {}).items():
            if k in url:
                return v
        raise crawl.requests.RequestException(f"no fixture for {url}")
    return SimpleNamespace(Job=crawl.Job, title_ok=crawl.title_ok, in_india=crawl.in_india, strip_html=crawl.strip_html, parse_ts=crawl.parse_ts,
                           get=lambda url, params=None, **k: copy.deepcopy(pick(json_by_url, url)),
                           post=lambda url, body, **k: copy.deepcopy(pick(json_by_url, url)),
                           SESSION=SimpleNamespace(get=lambda url, **k: page(pick(pages, url)), headers={}))


# ---------------------------------------------------------------- Upstox (jsonlist on service.upstox.com)
UPSTOX = {"name": "Upstox", "ats": "portal", "portal": "jsonlist", "url": "https://service.upstox.com/content/open/v1/jobs/",
          "page": "https://upstox.com/careers/", "items": "data", "where": {"post_on_careers_page": 1}, "title": "job_title",
          "location": ["location_city", "location_country"],
          "link": "https://upstox.darwinbox.in/ms/candidatev2/main/careers/jobDetails/{job_id}?from=all", "posted": "job_created_timestamp",
          "date_format": "%d-%m-%Y %H:%M:%S", "min_exp": "experience_from", "max_exp": "experience_to"}
up = json.loads(fixture("upstox_jobs.json"))
got = list(jsonlist.fetch(UPSTOX, h_for({"service.upstox.com": up})))
check("upstox: only careers-page postings with fitting titles (SDE III kept; SRE, finance and the unposted dummy row dropped)",
      [j.title for j in got] == ["Software Developement Engineer III (JAVA+Rust)"], [j.title for j in got])
check("upstox: city list deduplicated + country, link is the page's own share link, posted from the created timestamp",
      got and got[0].location == "Mumbai, India"
      and got[0].url == "https://upstox.darwinbox.in/ms/candidatev2/main/careers/jobDetails/a6ae307ebb2428?from=all"
      and got[0].posted and got[0].posted.strftime("%Y-%m-%d") == "2026-10-29", got and (got[0].location, got[0].url, got[0].posted))
up2 = copy.deepcopy(up)
for r in up2["data"]:
    if r["job_title"] == "SRE II":
        r["job_title"] = "Backend Engineer"
got = list(jsonlist.fetch(UPSTOX, h_for({"service.upstox.com": up2})))
check("upstox: years asked become an 'Experience: 3-5 years' line; two cities kept", any(
    j.title == "Backend Engineer" and j.text.startswith("Experience: 3-5 years") and j.location == "Mumbai, Bangalore, India" for j in got),
      [(j.title, j.location, j.text[:30]) for j in got])
check("upstox: a {'success': false} reply raises", raises(lambda: jsonlist.fetch(UPSTOX, h_for({"service.upstox.com": {"success": False}}))))

# ---------------------------------------------------------------- Pratilipi (TalentZQ public JD list)
PRATILIPI = {"name": "Pratilipi", "ats": "portal", "portal": "jsonlist", "url": "https://pratilipi.talentzq.io/api/1009/jd",
             "page": "https://pratilipi.talentzq.io/careers", "link": "https://pratilipi.talentzq.io/careers#{Id}", "items": "", "where": {"Published": True, "Status": "active"},
             "title": "Title", "location": "JobLocation", "posted": "Datecreated"}
pr = json.loads(fixture("pratilipi_jd.json"))
check("pratilipi: the unpublished Backend Engineer JD is not read as an opening",
      list(jsonlist.fetch(PRATILIPI, h_for({"talentzq.io": pr}))) == [])
pr2 = copy.deepcopy(pr)
for r in pr2:
    r["Published"] = True
got = list(jsonlist.fetch(PRATILIPI, h_for({"talentzq.io": pr2})))
check("pratilipi: published dev JD read with its [[city, state, country]] place, a 7-digit-fraction date and page#Id link",
      [(j.title, j.location, j.url, j.posted.strftime("%Y-%m-%d") if j.posted else None) for j in got]
      == [("Backend Engineer", "Bangalore, Karnataka, India", "https://pratilipi.talentzq.io/careers#" + pr2[1]["Id"], "2025-11-18")],
      [(j.title, j.location, j.url, j.posted) for j in got])
check("pratilipi: an error object instead of the JD list raises", raises(lambda: jsonlist.fetch(PRATILIPI, h_for({"talentzq.io": {"error": "x"}}))))

# ---------------------------------------------------------------- Classplus (crm.classplus.co, empty today)
CLASSPLUS = {"name": "Classplus", "ats": "portal", "portal": "jsonlist", "url": "https://crm.classplus.co/ts/jobs/get-job-list",
             "page": "https://classplusapp.com/careers/open-role", "items": "data.Jobs", "title": "title", "location": "locationCity",
             "default_location": "Noida, India", "link": "https://classplusapp.com/careers/job-description?jobId={jobId}"}
cp = json.loads(fixture("classplus_jobs.json"))
check("classplus: today's empty Jobs list reads as no openings, not an error", list(jsonlist.fetch(CLASSPLUS, h_for({"classplus.co": cp}))) == [])
check("classplus: a reply without data.Jobs raises", raises(lambda: jsonlist.fetch(CLASSPLUS, h_for({"classplus.co": {"data": {}, "message": "x"}}))))
got = list(jsonlist.fetch(CLASSPLUS, h_for({"classplus.co": {"data": {"Jobs": [
    {"jobId": 77, "title": "SDE 2 - Backend", "locationCity": "Noida", "department": "Tech"},
    {"jobId": 78, "title": "Software Engineer", "locationCity": None}]}}})))
check("classplus: fields the app renders (title, locationCity, jobId) give the job-description link",
      [(j.title, j.location, j.url) for j in got] == [("SDE 2 - Backend", "Noida", "https://classplusapp.com/careers/job-description?jobId=77"),
                                                      ("Software Engineer", "Noida, India", "https://classplusapp.com/careers/job-description?jobId=78")],
      [(j.title, j.location, j.url) for j in got])

# ---------------------------------------------------------------- Homerun (Ghost's Atom feed)
GHOST = {"name": "Ghost", "ats": "portal", "portal": "homerun", "slug": "ghost"}
feed = fixture("homerun_ghost.xml")
check("homerun: Ghost's one job (Senior, band UTC-6 - UTC+2) is not an India opening",
      list(homerun.fetch(GHOST, h_for(pages={"feed.homerun.co/ghost": feed}))) == [])
entry = feed[feed.find("<entry>"):feed.find("</entry>") + len("</entry>")]
extra = (entry.replace("Senior Security Engineer", "Backend Engineer").replace("UTC-6 - UTC+2", "UTC+4 - UTC+9")
         .replace("https://careers.ghost.org/senior-security-engineer", "https://careers.ghost.org/backend-engineer")
         .replace("<p>We are looking for", "<script>alert(1)</script><p>We are looking for")
         + entry.replace("Senior Security Engineer", "Software Engineer").replace("UTC-6 - UTC+2", "Bengaluru, India")
         + entry.replace("Senior Security Engineer", "Platform Engineer").replace("UTC-6 - UTC+2", "Remote"))
got = list(homerun.fetch(GHOST, h_for(pages={"feed.homerun.co": feed.replace("</feed>", extra + "</feed>")})))
check("homerun: a band covering UTC+5:30 is remote India, an Indian city is kept, a bare 'Remote' is not",
      [(j.title, j.location, j.remote) for j in got] == [("Backend Engineer", "Remote (UTC+4 - UTC+9), India", True),
                                                         ("Software Engineer", "Bengaluru, India", False)], [(j.title, j.location) for j in got])
check("homerun: link, date, salary and a description with its script dropped",
      got and got[0].url == "https://careers.ghost.org/backend-engineer" and got[0].posted.strftime("%Y-%m-%d") == "2026-09-22"
      and "alert" not in got[0].text and "We are looking for a Backend Engineer" in got[0].text and got[0].pay_posted.startswith("$140000"), got and (got[0].url, got[0].posted, got[0].text[:80], got[0].pay_posted))
attr_feed = feed.replace("</feed>", extra.replace("<entry>", '<entry xml:lang="en">') + "</feed>")
got = list(homerun.fetch(GHOST, h_for(pages={"feed.homerun.co": attr_feed})))
check("homerun: <entry> tags with attributes (<entry xml:lang=\"en\">) are read too",
      [j.title for j in got] == ["Backend Engineer", "Software Engineer"], [j.title for j in got])
check("homerun: a non-Atom reply (an HTML error page) raises",
      raises(lambda: homerun.fetch(GHOST, h_for(pages={"feed.homerun.co": "<html><body>Not found</body></html>"}))))
check("homerun: band edges: UTC+5:30 - UTC+8 covers India, UTC+6 - UTC+9 doesn't",
      homerun.place(crawl, "UTC+5:30 - UTC+8")[0] != "" and homerun.place(crawl, "UTC+6 - UTC+9")[0] == "")

# ---------------------------------------------------------------- Webbtree (IdeaForge's server-rendered list)
IDEAFORGE = {"name": "IdeaForge", "ats": "portal", "portal": "webbtree", "slug": "ideaforge"}
wb = fixture("webbtree_ideaforge.html")
got = list(webbtree.fetch(IDEAFORGE, h_for(pages={"app.webbtree.com/company/ideaforge/jobs": wb})))
titles = {j.title: j for j in got}
check("webbtree: 58 listed jobs read, only fitting titles yielded (HR/logistics/pilot-contract roles out)",
      "Engineer ( Electronics Embedded )" in titles and "Assistant Manager - HR & Admin (Plant)" not in titles and "Logistics Manager" not in titles
      and 5 <= len(got) <= 20, sorted(titles))
j = titles.get("Engineer II (Structures)")
check("webbtree: location from the card (Bengaluru, not the first card's city), job URL from the breadcrumb, mode kept",
      j and j.location == "Bengaluru, India" and j.url.startswith("https://app.webbtree.com/ideaforge/jobs/engineer-ii-structures-")
      and j.meta.get("workMode") == "On-Site" and not j.remote, j and (j.location, j.url, j.meta))
check("webbtree: a page without the BreadcrumbList raises",
      raises(lambda: webbtree.fetch(IDEAFORGE, h_for(pages={"webbtree.com": wb.replace('"BreadcrumbList"', '"WebPage"')}))))
i = wb.find('jobnameHover"')
check("webbtree: cards that no longer match the list one for one raise",
      raises(lambda: webbtree.fetch(IDEAFORGE, h_for(pages={"webbtree.com": wb[:i] + wb[i + 12:]}))))

eng = '"name":"Engineer II (Structures)"'
k = wb.find(eng)
check("webbtree fixture: the breadcrumb for Engineer II (Structures) is found", k > 0)
at = wb.rfind('"@id":"', 0, k) if k > 0 else -1
nxt = wb.find('"', at + 7) if at >= 0 else -1
bad = wb[:at + 7] + "https://www.ideaforgetech.com/careers" + wb[nxt:] if at >= 0 and nxt > 0 else wb
check("webbtree: a fitting India job whose @id isn't a webbtree job URL raises (no falling back to the board URL)",
      bad != wb and raises(lambda: webbtree.fetch(IDEAFORGE, h_for(pages={"webbtree.com": bad}))))

# ---------------------------------------------------------------- PocketHRMS (Agilitas)
AGILITAS = {"name": "Agilitas", "ats": "portal", "portal": "pockethrms", "schema": "0OE/OA9NNuq9lGOJjhAZRg==", "company": "74nptQxi3x8gf4Sn3roRfQ=="}
ph = json.loads(fixture("pockethrms_search.json"))
calls = []


class FakeSession:
    def __init__(self, replies):
        self.replies, self.headers = list(replies), {}

    def get(self, url, **k):
        calls.append(("GET", url))
        return page("<html>portal</html>")

    def post(self, url, json=None, **k):
        calls.append(("POST", url, json["PageIndex"]))
        status, body = self.replies.pop(0)
        return page(__import__("json").dumps(body), status)


def run_pockethrms(replies):
    calls.clear()
    orig = pockethrms.session
    pockethrms.session = lambda h: FakeSession(replies)
    try:
        return list(pockethrms.fetch(AGILITAS, h_for()))
    finally:
        pockethrms.session = orig


check("pockethrms: Agilitas's real postings (marketing, warehouse, brand) yield nothing", run_pockethrms([(200, ph)]) == [])
check("pockethrms: the portal page is opened before the search POST, as in a browser",
      [c[0] for c in calls] == ["GET", "POST"] and "MainCareerPageV2?schemaName=0OE%2FOA9NNuq9lGOJjhAZRg%3D%3D" in calls[0][1], calls)
ph2 = copy.deepcopy(ph)
ph2["Jobs"][0]["Title"] = "<b>Backend Engineer</b>"
got = run_pockethrms([(200, ph2)])
check("pockethrms: a fitting title yields city/region/country, portal#JobCode link, experience line and posted pay",
      [(j.title, j.location, j.url.endswith("#JOB038"), j.text.startswith("Experience: 5-8 years"), j.pay_posted) for j in got]
      == [("Backend Engineer", "Bangalore, Karnataka, India", True, True, "INR 4000000 - INR 5000000")],
      [(j.title, j.location, j.url, j.text[:40], j.pay_posted) for j in got])
check("pockethrms: posted pay is read by the pay parser as 40 LPA", got and crawl.posted_pay_lpa(got[0].pay_posted) == 40.0)
check("pockethrms: a 302 (session missing) raises instead of reading as no openings", raises(lambda: run_pockethrms([(302, {})])))
check("pockethrms: a reply without Jobs raises", raises(lambda: run_pockethrms([(200, {"TotalCount": 0})])))
big = {"TotalCount": 51, "Jobs": [dict(ph["Jobs"][0], Id=i, JobCode=f"J{i}") for i in range(50)]}
got = run_pockethrms([(200, big), (200, {"TotalCount": 51, "Jobs": [dict(ph2["Jobs"][0], JobCode="J50")]})])
check("pockethrms: a full page of 50 reads the next page", [c[2] for c in calls if c[0] == "POST"] == [1, 2] and [j.url[-4:] for j in got] == ["#J50"],
      (calls, [j.url for j in got]))

nototal = {"Jobs": [dict(ph["Jobs"][0], Id=i, JobCode=f"J{i}") for i in range(50)]}
got = run_pockethrms([(200, nototal), (200, {"Jobs": [dict(ph2["Jobs"][0], JobCode="J50")]})])
check("pockethrms: without TotalCount a full page still reads the next page (only a short page ends the list)",
      [c[2] for c in calls if c[0] == "POST"] == [1, 2] and [j.url[-4:] for j in got] == ["#J50"], (calls, [j.url for j in got]))
full = {"Jobs": [dict(ph["Jobs"][0], Id=i, JobCode=f"J{i}") for i in range(50)]}
real_time, pockethrms.time = pockethrms.time, SimpleNamespace(sleep=lambda s: None)  # no 19 s of waits in the test
check("pockethrms: still full pages after the 20-page limit raises (a cut-off list is not complete)",
      raises(lambda: run_pockethrms([(200, full)] * pockethrms.MAX_PAGES)) and len([c for c in calls if c[0] == "POST"]) == 20, calls[-1:])
pockethrms.time = real_time
got = run_pockethrms([(200, dict(full, TotalCount=50))])
check("pockethrms: a full page that reaches TotalCount ends the list", [c[2] for c in calls if c[0] == "POST"] == [1], calls)

print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
