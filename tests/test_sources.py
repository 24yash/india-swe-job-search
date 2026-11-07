"""New job sources and careers-site discovery, with fixtures (no network).

Usage: python3 tests/test_sources.py <path to the job-search folder>
Covers the Oracle, Rippling and Eightfold readers, the portals/ readers (generic links, Juspay, Goldman, Uber,
Apple, Urban Company, ShareChat, sitemap, Jibe, Keka, Zoho Recruit, Kula), board recognition in URLs/pages, and find_careers helpers (bounded link parsing,
company check for guessed domains, careers-page candidates).
"""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
import crawl  # noqa: E402
import discover_ats as da  # noqa: E402
import find_careers as fc  # noqa: E402
import portals  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        failures.append(name)


class FakeResponse:
    def __init__(self, text="", data=None):
        self.text, self._data, self.status_code, self.ok = text, data, 200, True

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


def route(table):
    """get/post replacement: the first table key contained in the URL (+ params) decides the response."""
    def call(url, *a, **kw):
        key = url + " " + json.dumps(kw.get("params") or {}) + " " + json.dumps(a[0] if a else kw.get("json") or {})
        for k, v in table.items():
            if k in key:
                v = v(key) if callable(v) else v
                if isinstance(v, Exception):
                    raise v
                return v
        raise crawl.requests.RequestException(f"no fixture for {url}")
    return call


def patched(table, raw=False):
    """Point crawl.get/post (JSON) and crawl.SESSION.get/post (responses) at fixtures."""
    j = route(table)
    crawl.get = lambda url, **kw: j(url, **kw)
    crawl.post = lambda url, body, **kw: j(url, body, **kw)
    crawl.SESSION = SimpleNamespace(get=lambda url, **kw: FakeResponse(text=j(url, **kw)) if raw else FakeResponse(data=j(url, **kw)),
                                    post=lambda url, **kw: FakeResponse(data=j(url, **kw)))


real_get, real_post, real_session = crawl.get, crawl.post, crawl.SESSION

# --- Oracle Recruiting Cloud ---------------------------------------------------------------------------
page = {"items": [{"requisitionList": [
    {"Id": "1", "Title": "Software Engineer II - Java", "PrimaryLocation": "Bengaluru, Karnataka, India", "PostedDate": "2026-11-01", "secondaryLocations": []},
    {"Id": "2", "Title": "Software Engineer II - Java", "PrimaryLocation": "Plano, TX, United States", "PostedDate": "2026-11-01", "secondaryLocations": []},
    {"Id": "3", "Title": "Lead Software Engineer", "PrimaryLocation": "Mumbai, India", "PostedDate": "2026-11-01", "secondaryLocations": []},
    {"Id": "4", "Title": "Software Engineer II - Python", "PrimaryLocation": "Plano, TX", "PostedDate": "2026-11-01",
     "secondaryLocations": [{"Name": "Hyderabad, Telangana, India"}]}]}]}
details = {"items": [{"ExternalDescriptionStr": "<p>2+ years of applied experience in Java</p>", "ExternalPostedStartDate": "2026-11-01T06:00:00+00:00"}]}
patched({"recruitingCEJobRequisitionDetails": lambda k: crawl.requests.RequestException("closed") if 'Id=\\"4\\"' in k else details,
         "recruitingCEJobRequisitions": page})
jobs = list(crawl.oracle({"name": "JPMorgan", "host": "jpmc.fa.oraclecloud.com", "site": "CX_1001"}))
check("oracle: India + fitting title only, secondary locations count, failed detail skips just that job",
      [j.title for j in jobs] == ["Software Engineer II - Java"], [j.title for j in jobs])
check("oracle: link is the company's own careers page", jobs and jobs[0].url.endswith("/sites/CX_1001/job/1"))

# --- Rippling ------------------------------------------------------------------------------------------
patched({"/jobs/u1": {"description": {"company": "<p>About</p>", "role": "<p>1-3 years of experience</p>"}, "workLocations": ["Bengaluru, India"],
                      "createdOn": "2026-10-30T10:00:00Z", "payRangeDetails": [{"currency": "INR", "rangeStart": 2500000, "rangeEnd": 3500000}],
                      "employmentType": {"label": "SALARIED_FT"}},
         "/jobs": [{"uuid": "u1", "name": "Software Engineer", "url": "https://ats.rippling.com/x/jobs/u1", "workLocation": {"label": "Bengaluru, India"}},
                   {"uuid": "u2", "name": "Software Engineer", "url": "https://ats.rippling.com/x/jobs/u2", "workLocation": {"label": "Austin, TX"}}]})
jobs = list(crawl.rippling({"name": "X", "slug": "x"}))
check("rippling: India only, description parts joined, INR range posted",
      len(jobs) == 1 and "1-3 years" in jobs[0].text and crawl.posted_pay_lpa(jobs[0].pay_posted) == 25, jobs and (jobs[0].text, jobs[0].pay_posted))

# --- Eightfold (and Microsoft through it) ---------------------------------------------------------------
patched({"position_details": {"data": {"jobDescription": "<p>2+ years</p>", "publicUrl": "https://careers.qualcomm.com/careers/job/9"}},
         "/api/pcsx/search": lambda k: {"data": {"positions": [{"id": 9, "name": "Software Engineer", "locations": ["Bengaluru, India"], "postedTs": 1793000000}]
                                                  if '"start": 0' in k and '"software engineer"' in k else []}},
         "/careers?domain": {}})
crawl.time = SimpleNamespace(sleep=lambda s: None, time=time.time)
jobs = list(crawl.eightfold({"name": "Qualcomm", "host": "careers.qualcomm.com", "domain": "qualcomm.com"}))
check("eightfold: reads search + details for the given host/domain", len(jobs) == 1 and jobs[0].url.endswith("/job/9"))
check("microsoft still works through the eightfold reader", "microsoft" in crawl.FETCHERS and "eightfold" in crawl.FETCHERS and "portal" in crawl.FETCHERS)

# --- portals: generic links reader ----------------------------------------------------------------------
listing = ('<a class="job" href="/careers/software-engineer-7001"><svg><title>icon</title></svg><span class="job-display-name">Software Engineer</span>'
           '<span>: We are looking for a developer</span></a>'
           '<a href="/careers/senior-member-7002"><span class="job-name">Senior Staff Engineer</span></a>'
           '<a href="/careers/backend-developer-7003">Backend Developer   Multiple Locations</a>'
           '<a href="/careers/platform-engineer-7004"><svg viewBox="0 0 1 1"><title>icon</title></svg>Platform Engineer</a>')
patched({"/careers/software-engineer-7001": "<main>Location: Hyderabad. 1+ years of experience in Java.</main>",
         "/careers/platform-engineer-7004": "<main>Location: Pune. 2+ years.</main>",
         "/careers/backend-developer-7003": "<main>Location: London. 2+ years.</main>",
         "/careers": listing}, raw=True)
cfg = {"name": "Acme", "ats": "portal", "portal": "links", "list_urls": ["https://acme.com/careers"], "job_link": r"/careers/[a-z0-9-]+-\d+"}
jobs = list(crawl.portal(cfg))
check("links: title from the name element (svg icon ignored), senior skipped, non-India detail dropped",
      sorted((j.title, j.location) for j in jobs) == [("Platform Engineer", "Pune, India"), ("Software Engineer", "Hyderabad, India")],
      [(j.title, j.location) for j in jobs])
jobs = list(crawl.portal(cfg | {"location": "India"}))
check("links: configured location used only when the detail names no Indian city",
      sorted(j.location for j in jobs) == ["Hyderabad, India", "India", "Pune, India"], [j.location for j in jobs])
patched({"/careers": '<a href="/careers/x-1">x' * 20000 + "<div>" * 100000}, raw=True)
t = time.time()
list(crawl.portal(cfg))
check("links: an unclosed <a> on a huge page doesn't hang the reader", time.time() - t < 3, f"{time.time() - t:.1f}s")

# --- portals: Juspay, Goldman, Uber, Apple, Urban Company -----------------------------------------------
patched({"careerJobOpening": {"allJobs": [
    {"job_id": "BE1", "job_title": "Software Development Engineer Backend", "job_location": "Bangalore", "opening_status": "True", "experience_year": "1",
     "job_description_career": "Build payments", "job_type": "Full-Time"},
    {"job_id": "BE2", "job_title": "Software Development Engineer Backend", "job_location": "Bangalore", "opening_status": "False", "experience_year": "1"},
    {"job_id": "BR1", "job_title": "Software Development Engineer", "job_location": "São Paulo", "opening_status": "True", "experience_year": "1"}]}})
jobs = list(portals.fetch({"name": "Juspay", "portal": "juspay"}, crawl))
check("juspay: open India roles only, years asked readable by the experience parser",
      len(jobs) == 1 and crawl.min_experience(jobs[0].text)[0] == 1 and jobs[0].url.endswith("job=BE1"), [j.url for j in jobs])

role = {"descriptionHtml": "<p>1+ years</p>", "compensation": {}}
patched({"graphql": lambda k: {"role": role} if "GetRoleById" in k else {"roleSearch": {"items": [
    {"roleId": "1_GS", "corporateTitle": "Analyst", "jobTitle": "Tax - Tax Engineering - Analyst - Bengaluru", "jobFunction": "Software Engineering",
     "status": "POSTED", "locations": [{"city": "Bengaluru", "country": "India"}], "externalSource": {"sourceId": "1"}},
    {"roleId": "2_GS", "corporateTitle": "Vice President", "jobTitle": "Core-Bengaluru-Vice President-Software Engineering", "jobFunction": "Software Engineering",
     "status": "POSTED", "locations": [{"city": "Bengaluru", "country": "India"}], "externalSource": {"sourceId": "2"}},
    {"roleId": "3_GS", "corporateTitle": "Associate", "jobTitle": "HCM-Hyderabad-Associate-HRIS", "jobFunction": "HRIS",
     "status": "POSTED", "locations": [{"city": "Hyderabad", "country": "India"}], "externalSource": {"sourceId": "3"}}]}}})
crawl.SESSION = SimpleNamespace(post=lambda url, **kw: FakeResponse(data={"data": route({"graphql": lambda k: {"role": role} if "GetRoleById" in k else
                                                                                           crawl.get("graphql " + k)})(url, kw["json"])}))
jobs = list(portals.fetch({"name": "Goldman Sachs", "portal": "goldman"}, crawl))
check("goldman: analyst/associate software roles only; Goldman's title kept, function added when the title doesn't say it",
      [j.title for j in jobs] == ["Tax - Tax Engineering - Analyst - Bengaluru (Software Engineering)"] and crawl.title_ok(jobs[0].title),
      [j.title for j in jobs])

patched({"jobs.uber.com": lambda k: {"totalPages": 1, "jobs": [
    {"Id": 1, "Title": "Software Engineer II", "Locations": [{"City": "Bengaluru", "Region": "Karnataka", "Country": "India"}],
     "Urls": [{"Url": "/en/jobs/1/", "IsDefault": True}], "Description": "2+ years", "DisplayDate": "2026-11-01T00:00:00Z"},
    {"Id": 2, "Title": "Software Engineer II", "Locations": [{"City": "Seattle", "Country": "United States"}], "Urls": []}]}})
jobs = list(portals.fetch({"name": "Uber", "portal": "uber"}, crawl))
check("uber: India roles once across keywords", [j.url for j in jobs] == ["https://jobs.uber.com/en/jobs/1/"], [j.url for j in jobs])


def hydration(obj):
    return 'window.__staticRouterHydrationData = JSON.parse(' + json.dumps(json.dumps(obj)) + ');'


search = {"loaderData": {"search": {"searchResults": [{"positionId": "200", "postingTitle": "Software Engineer - Java", "transformedPostingTitle": "se-java",
                                                       "postDateInGMT": "2026-11-01T00:00:00Z", "locations": [{"countryName": "India"}]}]}}}
detail = {"loaderData": {"jobDetails": {"jobsData": {"description": "3+ years", "locations": [{"city": "Hyderabad", "stateProvince": "Telangana", "countryName": "India"}]}}}}
patched({"/details/200": hydration(detail), "page=1": hydration(search), "/search": hydration({"loaderData": {"search": {"searchResults": []}}})}, raw=True)
jobs = list(portals.fetch({"name": "Apple", "portal": "apple"}, crawl))
check("apple: embedded page data parsed; city from the job detail", [(j.title, j.location) for j in jobs] == [("Software Engineer - Java", "Hyderabad, Telangana, India")],
      [(j.title, j.location) for j in jobs])

patched({"getAllJobs": {"jobs": [{"job_id": "a", "job_title": "Backend Engineer", "location": ["Bangalore, Karnataka, India"], "job_description": "<p>2+ years</p>"},
                                 {"job_id": "b", "job_title": "Category Manager", "location": ["Bangalore, Karnataka, India"]}]}})
jobs = list(portals.fetch({"name": "Urban Company", "portal": "urbancompany"}, crawl))
check("urban company: fitting titles only", [j.url for j in jobs] == ["https://careers.urbancompany.com/jobDetail?id=a"])

patched({"careersList": {"data": {"hasNext": False, "careersList": [{"title": "Engineering", "data": [
    {"requisitionId": 7, "requisitionTitle": "Software Engineer - Backend", "officeLocationNames": ["Bangalore"], "yrsOfExpMin": 1, "yrsOfExpMax": 3,
     "createdDate": 1793000000000, "employmentType": "full time"},
    {"requisitionId": 8, "requisitionTitle": "AI Video Editor", "officeLocationNames": ["India"], "yrsOfExpMin": 0, "yrsOfExpMax": 2}]}]}}})
jobs = list(portals.fetch({"name": "ShareChat", "portal": "sharechat"}, crawl))
check("sharechat: fitting titles, years asked readable, link opens the MyNextHire job page",
      len(jobs) == 1 and crawl.min_experience(jobs[0].text)[0] == 1 and "mynexthire.com/employer/jobs" in jobs[0].url and jobs[0].posted is not None)

# --- sitemap + JobPosting, Jibe, Keka, Zoho Recruit, Kula -----------------------------------------------
def ld(title, city, country="India", posted="2026-11-01", until=None):
    jp = {"@context": "https://schema.org", "@type": "JobPosting", "title": title, "datePosted": posted, "description": "<p>2+ years of Java</p>",
          "jobLocation": {"@type": "Place", "address": {"addressLocality": city, "addressCountry": country}}}
    if until:
        jp["validThrough"] = until
    return f'<html><script type="application/ld+json">{json.dumps(jp)}</script></html>'


smap = ("<urlset>"
        "<url><loc>https://careers.acme.com/job/bengaluru/software-engineer-ii/1</loc><lastmod>2026-11-01</lastmod></url>"
        "<url><loc>https://careers.acme.com/job/bengaluru/senior-software-engineer/2</loc><lastmod>2026-11-02</lastmod></url>"
        "<url><loc>https://careers.acme.com/job/austin/software-engineer/3</loc><lastmod>2026-11-03</lastmod></url>"
        "<url><loc>https://careers.acme.com/job/pune/backend-developer/4</loc><lastmod>2026-11-04</lastmod></url>"
        "<url><loc>https://careers.acme.com/job/pune/sales-manager/5</loc><lastmod>2026-11-05</lastmod></url>"
        "<url><loc>https://careers.acme.com/about-us</loc></url></urlset>")
calls = []


def sm_route(k):
    calls.append(k)
    return None


patched({"robots.txt": "User-agent: *\nDisallow: /job/pune/backend-developer\nSitemap: https://careers.acme.com/jobs-sitemap.xml",
         "jobs-sitemap.xml": smap, "sitemap.xml": "", "sitemal.xml": "",
         "/job/bengaluru/software-engineer-ii/1": ld("Software Engineer II", "Bengaluru"),
         "/job/austin/software-engineer/3": ld("Software Engineer", "Austin", "United States"),
         "/job/bengaluru/senior-software-engineer/2": ld("Senior Software Engineer", "Bengaluru")}, raw=True)
crawl.SESSION.headers = {"User-Agent": "test"}
_sess_get = crawl.SESSION.get
crawl.SESSION.get = lambda url, **kw: (calls.append(url), SimpleNamespace(status_code=200, content=_sess_get(url).text.encode(), text=_sess_get(url).text))[1]
jobs = list(portals.fetch({"name": "Acme", "portal": "sitemap", "host": "careers.acme.com"}, crawl))
check("sitemap: software roles in India from JobPosting data; senior URLs, non-software URLs and other countries skipped",
      [(j.title, j.location) for j in jobs] == [("Software Engineer II", "Bengaluru, India")], [(j.title, j.location) for j in jobs])
check("sitemap: robots.txt-disallowed job pages are never fetched", not any("backend-developer" in u for u in calls))
check("sitemap: senior and non-software job pages aren't fetched at all (filtered by URL first)",
      not any("senior-software" in u or "sales-manager" in u for u in calls))
patched({"robots.txt": "", "jobs-sitemap.xml": smap.replace("<url><loc>https://careers.acme.com/job/austin/software-engineer/3</loc><lastmod>2026-11-03</lastmod></url>", ""),
         "sitemap.xml": "", "sitemal.xml": "", "/job/pune/backend-developer/4": ld("Backend Developer", "Pune", until="2026-01-01T00:00:00Z"),
         "/job/bengaluru/software-engineer-ii/1": ld("Software Engineer II", "Bengaluru")}, raw=True)
crawl.SESSION.headers = {"User-Agent": "test"}
_sess_get2 = crawl.SESSION.get
crawl.SESSION.get = lambda url, **kw: SimpleNamespace(status_code=200, content=_sess_get2(url).text.encode(), text=_sess_get2(url).text)
jobs = list(portals.fetch({"name": "Acme", "portal": "sitemap", "host": "careers.acme.com", "sitemaps": ["https://careers.acme.com/jobs-sitemap.xml"]}, crawl))
check("sitemap: a job whose closing date (validThrough) has passed is dropped", [j.title for j in jobs] == ["Software Engineer II"], [j.title for j in jobs])

from portals.sitemap import place
check("sitemap: addresses given as a list (Gartner) or missing don't crash",
      place({"jobLocation": [{"address": [{"addressLocality": "Gurugram", "addressCountry": "IN"}]}, None, {"address": None}]}) == ["Gurugram, IN"])

patched({"/api/jobs": lambda k: {"jobs": [{"data": {"req_id": "1", "slug": "1", "title": "Software Engineer", "country": "India", "city": "Bengaluru",
                                                    "posted_date": "2026-11-01T00:00:00+0000", "description": "1+ years"}},
                                          {"data": {"req_id": "2", "slug": "2", "title": "Software Engineer", "country": "Canada", "city": "Markham"}}]}
         if '"page": 1' in k else {"jobs": []}})
jobs = list(portals.fetch({"name": "AMD", "portal": "jibe", "host": "careers.amd.com"}, crawl))
check("jibe: India roles once across keywords, link to the job page", [j.url for j in jobs] == ["https://careers.amd.com/jobs/1?lang=en-us"], [j.url for j in jobs])

patched({"keka.com": [{"id": "9", "title": "Software Engineer", "description": "<p>Build</p>", "experience": "1 - 3 years",
                       "jobLocations": [{"city": "Bengaluru", "state": "Karnataka", "countryName": "India", "countryCode": "IN"}], "publishedOn": "2026-11-01T00:00:00Z"},
                      {"id": "10", "title": "Software Engineer", "jobLocations": [{"city": "Berlin", "countryName": "Germany", "countryCode": "DE"}]}]})
jobs = list(portals.fetch({"name": "Wingify", "portal": "keka", "slug": "wingify"}, crawl))
check("keka: India roles with years asked readable", len(jobs) == 1 and crawl.min_experience(jobs[0].text)[0] == 1 and jobs[0].url.endswith("/jobdetails/9"))

zjobs = [{"id": "5", "Posting_Title": "SDE -1", "City": "Noida", "Country": "India", "Publish": "True", "Work_Experience": "1-3 year"},
         {"id": "6", "Posting_Title": "SDE -1", "City": "Noida", "Country": "India", "Publish": "False"}]
zpage = '<input type="hidden" value="' + json.dumps(zjobs).replace('"', "&#34;") + '" id="jobs">'
patched({"zohorecruit.in/careers": zpage}, raw=True)
jobs = list(portals.fetch({"name": "GfG", "portal": "zohorecruit", "slug": "geeksforgeeks", "tld": "in"}, crawl))
check("zoho recruit: published India roles from the embedded list, years readable",
      len(jobs) == 1 and crawl.min_experience(jobs[0].text)[0] == 1 and jobs[0].url.endswith("/jobs/Careers/5"), [(j.title, j.text) for j in jobs])

patched({"/slice/1-sde-2-data-platform": ld("SDE 2 - Data Platform", "Bengaluru"),
         "careers.kula.ai/slice?jobs=true": '<a href="/slice/1-sde-2-data-platform?jobs=true">Apply Now</a><a href="/slice/2-fraud-analyst?jobs=true">Apply Now</a>'}, raw=True)
jobs = list(portals.fetch({"name": "Slice", "portal": "kula", "slug": "slice"}, crawl))
check("kula: titles from the URL when links say 'Apply Now'; details from the job page's JobPosting data",
      [(j.title, j.location) for j in jobs] == [("SDE 2 - Data Platform", "Bengaluru, India")], [(j.title, j.location) for j in jobs])

crawl.get, crawl.post, crawl.SESSION = real_get, real_post, real_session

company = {"name": "Acme", "type": "Product", "quality": 12, "pay": "likely", "pay_note": "Levels.fyi India SE1 25 LPA"}
nulls = crawl.Job("Acme", "Software Engineer", "Bengaluru, India", "u", None, "2+ years", meta={"commitment": None, "employmentType": None})
try:
    row, _ = crawl.evaluate(nulls, company, 30)
    check("evaluate copes with empty (null) schedule/employment-type fields from a feed", row is not None)
except TypeError as e:
    check("evaluate copes with empty (null) schedule/employment-type fields from a feed", False, str(e))

# --- board recognition and discovery helpers ------------------------------------------------------------
refs = da.boards_in("https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs "
                    "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/jobsearch "
                    "ats.rippling.com/thoughtspot/jobs/123 aexp.eightfold.ai/careers jobs.gem.com/promptql")
check("boards_in: Oracle (with and without region), Rippling, Eightfold, Gem",
      set(refs) == {("oracle", ("jpmc.fa.oraclecloud.com", "CX_1001")), ("oracle", ("eeho.fa.us2.oraclecloud.com", "jobsearch")),
                    ("rippling", "thoughtspot"), ("eightfold", "aexp"), ("gem", "promptql")}, refs)
blob = "a1b2c3d4" * 120000  # a long base64-like run, as embedded in many careers pages
t = time.time()
da.boards_in(blob + " https://acme.keka.com/careers")
check("boards_in stays fast on long alphanumeric runs (unbounded subdomain patterns went quadratic)", time.time() - t < 2, f"{time.time() - t:.1f}s")
check("guessed domain accepted only when the page names the company",
      fc.names_company("Urban Company", "<title>Urban Company | Home services</title>") and not fc.names_company("Urban Company", "<title>Parked domain</title>"))
cands = fc.careers_candidates("https://www.acme.com/", '<a href="/about/careers">Careers</a><a href="https://www.linkedin.com/company/acme/jobs">Jobs</a>')
check("careers candidates: homepage careers link first, usual paths after, social/aggregator links dropped",
      cands[0] == "https://www.acme.com/about/careers" and "https://careers.acme.com" in cands and not any("linkedin" in c for c in cands), cands)
t = time.time()
slow_page = '<a href="x">x' * 20000 + "<div>" * 100000  # the old unbounded pattern took ~70 s on this
fc.job_links("https://x.com", slow_page)
fc.careers_candidates("https://x.com", slow_page)
check("find_careers: bounded link parsing on a pathological page", time.time() - t < 2, f"{time.time() - t:.1f}s")
check("VC portfolio pages are not taken as a company's own careers page", bool(__import__("re").search(fc.NOT_OWN, "https://careers.peakxv.com/jobs/trell")))

print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
