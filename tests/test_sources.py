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
patched({"/api/apply/v2/jobs/7": {"job_description": "<p>1-3 years of Java</p>"},
         "/api/apply/v2/jobs/8": crawl.requests.RequestException("closed"),
         "/api/apply/v2/jobs": lambda k: {"positions": [
             {"id": 7, "name": "Software Engineer", "locations": ["Mumbai,India"], "t_create": 1793000000, "canonicalPositionUrl": "https://n.example/job/7"},
             {"id": 8, "name": "Software Engineer", "locations": ["Mumbai,India"], "t_create": 1793000000},
             {"id": 9, "name": "Publicity Manager - India", "locations": ["Mumbai,India"]}] if '"start": 0' in k else []}})
jobs = list(crawl.eightfold({"name": "Netflix", "host": "explore.jobs.netflix.net", "domain": "netflix.com", "api": "v2"}))
check("eightfold v2 (Netflix): India list, fitting titles only, description from the detail call, closed detail skipped",
      [(j.url, j.text.strip()) for j in jobs] == [("https://n.example/job/7", "1-3 years of Java")], [(j.url, j.text) for j in jobs])
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
patched({"/JobDetail/Software-Development-Engineer-II/216221": ld("Software Development Engineer II", "Bengaluru"),
         "SearchJobs": '<a href="https://careers.tesco.com/en_GB/careers/JobDetail/Software-Development-Engineer-II/216221">Read more</a>'
                       '<a href="https://careers.tesco.com/en_GB/careers/JobDetail/Store-Colleague/216222">Read more</a>'}, raw=True)
tesco = list(portals.fetch({"name": "Tesco", "portal": "links", "title_from_url": True, "job_link": r"https://careers\.tesco\.com/en_GB/careers/JobDetail/[^/\"]+/\d+",
                            "list_urls": ["https://careers.tesco.com/en_GB/careers/SearchJobs/software"]}, crawl))
check("links: URL titles skip a trailing numeric id (Avature: .../Title-Words/216221)", [j.title for j in tesco] == ["Software Development Engineer II"],
      [j.title for j in tesco])
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
check("boards_in: Oracle tenant hosts with hyphens (Akamai) are matched whole",
      ("oracle", ("fa-extu-saasfaprod1.fa.ocs.oraclecloud.com", "CX_1")) in da.boards_in(
          "https://fa-extu-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/CandidateExperience/en/siteSettings/CX_1"))
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
check("VC portfolio pages and aggregators are not taken as a company's own careers page",
      fc.not_own("https://careers.peakxv.com/jobs/trell") and fc.not_own("https://cutshort.io/company/x") and fc.not_own("https://x.com/acme"))
check("domains merely ending in 'x.com' are not mistaken for x.com (netflix.com, dropbox.com, nutanix.com were rejected)",
      not any(fc.not_own(u) for u in ("https://jobs.netflix.com/", "https://www.dropbox.com/", "https://www.nutanix.com/", "https://careers.equinix.com/")))
check("a company's own domain on an aggregator list is its own site (careers.linkedin.com for LinkedIn)",
      not fc.not_own("https://careers.linkedin.com/", "LinkedIn") and fc.not_own("https://www.linkedin.com/company/acme/jobs", "Acme"))
check("boards_in: MyNextHire iframe boards and Rippling's embedded job board are detected",
      ("mynexthire", "amagi") in da.boards_in('<iframe src="https://amagi.mynexthire.com/employer/jobs/careers#?src=careers">')
      and ("rippling", "daloopa") in da.boards_in('<div id="rr-job-board" data-job-board-id="daloopa"></div>'))

# MyNextHire: board feed -> Job, with the board's own experience range carried into the text for the years parser
import base64
from types import SimpleNamespace
from portals import mynexthire as mnh


class _Resp:
    def __init__(self, data): self.data = data
    def raise_for_status(self): pass
    def json(self): return self.data


feed = {"reqDetailsBOList": [
    {"reqId": 459, "reqTitle": "Software Development Engineer II", "expMin": 2.0, "expMax": 5.0, "location": "Bangalore",
     "locationList": [{"office": "Bangalore"}], "jdDisplay": "Build playout services.", "approvedOn": "2026-10-23T05:04:12.345+0000"},
    {"reqId": 460, "reqTitle": "Head of Global Growth Marketing", "expMin": 10.0, "expMax": 15.0, "locationList": [{"office": "Bangalore"}]},
    {"reqId": 461, "reqTitle": "Software Engineer II", "expMin": 2.0, "expMax": 4.0, "locationList": [{"office": "United Kingdom"}]}]}
h = SimpleNamespace(**{k: getattr(crawl, k) for k in ("Job", "title_ok", "in_india", "parse_ts")},
                    SESSION=SimpleNamespace(post=lambda url, json, timeout: _Resp(feed)))
jobs = list(mnh.fetch({"name": "Amagi", "slug": "amagi", "jd_page": "https://www.amagi.com/job-description"}, h))
check("MyNextHire: only India roles with fitting titles", [j.title for j in jobs] == ["Software Development Engineer II"], [j.title for j in jobs])
check("MyNextHire: experience range carried into the text", jobs and jobs[0].text.startswith("Experience: 2-5 years"))
p = jobs[0].url.split("p%3D")[1] if jobs else ""
check("MyNextHire: job link is the company's JD page with the board's encoded request", '"reqId":459' in base64.b64decode(p).decode() if p else False, jobs and jobs[0].url)

# --- round five readers (fed canned responses; no network) ---
check("in_india: whole words (North Dakota is not Kota; Kota Kinabalu is Malaysia), city list widened",
      crawl.in_india("Kota") and crawl.in_india("Mysuru") and crawl.in_india("Bangalore, IN")
      and not crawl.in_india("North Dakota, US") and not crawl.in_india("Kota Kinabalu, Malaysia") and not crawl.in_india("Indianapolis"))

from portals import avature, xmlfeed
ea_page = ('<article class="article article--result x"><h3><a class="link link_result" href="https://jobs.example.com/en_US/careers/JobDetail/SE/1">'
           ' Software Engineer II </a></h3><div class="article__header__text__subtitle"><span class="list-item-location">Hyderabad, India</span></div></article>')
mq_page = ('<article class="article article--result clearfix "><h3><a class="link" href="https://r.example.com/en_US/careers/JobDetail?jobId=9">'
           ' Full Stack Developer </a></h3><div class="article__details__data"><img class="icon" src="x.svg" alt="Office Location:" /> <p> Gurugram Office </p></div></article>')
check("Avature: list items parsed from both theme layouts (span location / icon + <p> location)",
      avature.items(ea_page) == [("https://jobs.example.com/en_US/careers/JobDetail/SE/1", "Software Engineer II", "Hyderabad, India")]
      and avature.items(mq_page) == [("https://r.example.com/en_US/careers/JobDetail?jobId=9", "Full Stack Developer", "Gurugram Office")],
      (avature.items(ea_page), avature.items(mq_page)))
ts_page = ('<article class="article article--result" id="article--1"><h3 class="article__header__text__title"><a class="link" '
           'href="https://c.example.com/careers/JobDetail/Software-Engineer/1"> Software Engineer </a></h3>'
           '<div class="article__header__content__text"><span class="paragraph_inner-span">India - Bengaluru</span></div></article>')
check("Avature: bare paragraph_inner-span location (Two Sigma theme)",
      avature.items(ts_page) == [("https://c.example.com/careers/JobDetail/Software-Engineer/1", "Software Engineer", "India - Bengaluru")], avature.items(ts_page))
asked = []
_av = SimpleNamespace(SESSION=SimpleNamespace(get=lambda url, **k: (asked.append(url), SimpleNamespace(status_code=200, text="", raise_for_status=lambda: None))[1]),
                      title_ok=crawl.title_ok, in_india=crawl.in_india, strip_html=crawl.strip_html, Job=crawl.Job)
list(avature.fetch({"name": "T", "base": "https://c.example.com/careers", "list_path": "ExperiencedRoles", "searches": ["engineer"]}, _av))
list(avature.fetch({"name": "E", "base": "https://e.example.com/careers", "searches": ["engineer"]}, _av))
check("Avature: list_path picks the list page, SearchJobs by default",
      asked[0].startswith("https://c.example.com/careers/ExperiencedRoles/?") and asked[1].startswith("https://e.example.com/careers/SearchJobs/?"), asked)
check("XML feed: CDATA fields read", xmlfeed.field("<job><title><![CDATA[Software Engineer & Co]]></title></job>", "title") == "Software Engineer & Co")


def fake(get=None, post=None):
    class R:
        def __init__(self, d): self.d, self.status_code, self.text = d, 200, ""
        def raise_for_status(self): pass
        def json(self): return self.d
    return SimpleNamespace(**{k: getattr(crawl, k) for k in ("Job", "title_ok", "in_india", "parse_ts", "strip_html")},
                           get=lambda url, *a, **k: get(url), SESSION=SimpleNamespace(post=lambda url, **k: R(post(url)), get=lambda url, **k: R(get(url))))


rb = {"meta": {"total": 2}, "objects": [
    {"title": "Full Stack Developer", "location": {"city": "Kota", "state": None, "country": None}, "hosted_url": "u1", "description": "<p>x</p>"},
    {"title": "Software Engineer", "location": {"city": "Austin", "state": "TX", "country": "United States"}, "hosted_url": "u2"}]}
from portals import recruiterbox, peoplestrong, pinpoint
got = list(recruiterbox.fetch({"name": "ALLEN Digital", "slug": "allendigital"}, fake(get=lambda u: rb)))
check("Trakstar/Recruiterbox: India roles by city even without a country", [(j.title, j.location) for j in got] == [("Full Stack Developer", "Kota")], got)
ps = {"totalRecords": 2, "response": [
    {"jobTitle": "Software Engineer", "locationHierarchyComplete": "India>Karnataka>Bengaluru", "expRange": "2-4 years", "jobPostedDate": "2026-10-07", "jobDetailUrl": "u"},
    {"jobTitle": "Site Manager", "locationHierarchyComplete": "India>Gujarat>Hazira"}]}
got = list(peoplestrong.fetch({"name": "L&T", "host": "x.peoplestrong.com"}, fake(post=lambda u: ps)))
check("PeopleStrong: fitting India roles, experience range kept for the years parser",
      len(got) == 1 and got[0].location == "India, Karnataka, Bengaluru" and got[0].text.startswith("Experience: 2-4 years"), got)
pp = {"data": [{"title": "Software Developer 2", "location": {"city": "Pune", "province": "Maharashtra", "name": "India - Pune"}, "url": "u",
                "description": "d", "compensation_visible": True, "compensation": "Rs3,334,976 - Rs4,512,026 / year"}]}
got = list(pinpoint.fetch({"name": "Vena", "slug": "vena"}, fake(get=lambda u: pp)))
check("Pinpoint: India role with posted pay carried into the text", len(got) == 1 and "Rs3,334,976" in got[0].text, got)

# --- readers added 10 Nov 2026: Jobvite, Zappyhire, PyjamaHR, Zwayam, SuccessFactors, Avature labelled location ------
from portals import jobvite, zappyhire, pyjamahr, zwayam, successfactors


def page_h(pages=None, json_by_url=None, post=None):
    """h for readers that read pages (SESSION.get -> .text) and JSON (h.get); the first matching key wins."""
    def pick(table, url):
        for k, v in (table or {}).items():
            if k in url:
                if isinstance(v, Exception):
                    raise v
                return v
        raise crawl.requests.RequestException(f"no fixture for {url}")
    resp = lambda text: SimpleNamespace(text=text, status_code=200, raise_for_status=lambda: None)  # noqa: E731
    return SimpleNamespace(Job=crawl.Job, title_ok=crawl.title_ok, in_india=crawl.in_india, strip_html=crawl.strip_html, parse_ts=crawl.parse_ts,
                           get=lambda url, params=None, **k: pick(json_by_url, url + " " + json.dumps(params or {})),
                           SESSION=SimpleNamespace(get=lambda url, **k: resp(pick(pages, url)),
                                                   post=lambda url, **k: SimpleNamespace(json=lambda: post(k), raise_for_status=lambda: None)))


ld_jobvite = ('<script type="application/ld+json">{"@type":"JobPosting","title":"Software Engineer","datePosted":"2026-11-01",'
              '"description":"<p>2+ years Java</p>","jobLocation":[{"address":{"addressLocality":"Pune","addressCountry":"India"}},'
              '{"address":{"addressLocality":"Pune","addressCountry":"India"}}]}</script>')
table_theme = ('<tr><td class="jv-job-list-name"><a href="/acme/job/oA1">Software Engineer</a></td><td class="jv-job-list-location"> Bengaluru, Karnataka </td></tr>'
               '<tr><td class="jv-job-list-name"><a href="/acme/job/oB2">Software Engineer</a></td><td class="jv-job-list-location"> <div class="jv-meta"> 2 Locations </div> </td></tr>'
               '<tr><td class="jv-job-list-name"><a href="/acme/job/oC3">Software Engineer</a></td><td class="jv-job-list-location"> Austin, Texas </td></tr>'
               '<tr><td class="jv-job-list-name"><a href="/acme/job/oD4">Software Engineer</a></td><td class="jv-job-list-location"> Pune, India </td></tr>')
list_theme = ('<li><a class="flex-row" href="/acme/job/oE5"> <div class="flex-col"> <div class="jv-job-list-name"> Backend Engineer </div>'
              ' <div class="jv-job-list-location"> Hyderabad, Telangana </div> </div></a></li>')
check("Jobvite: both themes parsed; a '2 Locations' cell becomes an empty location",
      jobvite.items(table_theme + list_theme) == [("/acme/job/oA1", "Software Engineer", "Bengaluru, Karnataka"), ("/acme/job/oB2", "Software Engineer", ""),
                                                  ("/acme/job/oC3", "Software Engineer", "Austin, Texas"), ("/acme/job/oD4", "Software Engineer", "Pune, India"),
                                                  ("/acme/job/oE5", "Backend Engineer", "Hyderabad, Telangana")], jobvite.items(table_theme + list_theme))
got = list(jobvite.fetch({"name": "Acme", "slug": "acme"},
                         page_h(pages={"/jobs/viewall": table_theme, "/job/oA1": ld_jobvite, "/job/oB2": ld_jobvite,
                                       "/job/oD4": crawl.requests.RequestException("closed")})))
check("Jobvite: India rows read, multi-location job kept via its JobPosting places (deduped), US row skipped, failed detail skips one job",
      [(j.url.rsplit("/", 1)[1], j.location, j.text.strip(), str(j.posted)[:10]) for j in got]
      == [("oA1", "Bengaluru, Karnataka", "2+ years Java", "2026-11-01"), ("oB2", "Pune, India", "2+ years Java", "2026-11-01")],
      [(j.url, j.location, j.text) for j in got])

zh_page = lambda n, total: {"results": {"total": {"value": total}, "hits": [  # noqa: E731
    {"_source": {"job": i, "title": "Software Engineer" if i % 2 else "Sales Manager", "location": "Noida,Chennai"}, "sort": [1793000000000]}
    for i in range(n)]}}
got = list(zappyhire.fetch({"name": "Cg", "slug": "cg"}, page_h(json_by_url={
    '"page": 1': zh_page(12, 13), '"page": 2': {"results": {"total": {"value": 13}, "hits": [{"_source": {"job": 99, "title": "Backend Engineer", "location": "Pune"}}]}},
    "/careers/jobs/3/": crawl.requests.RequestException("closed"),
    "/careers/jobs/": {"results": {"description": "<p>Build APIs</p>", "experience": "1.0", "max_experience": "3.0", "job_publish_date": "2026-10-16T10:24:40Z"}}})))
check("Zappyhire: pages until the total, fitting India titles only, years asked in the text, closed detail skipped",
      len(got) == 6 and got[-1].title == "Backend Engineer" and got[0].text.startswith("Experience: 1.0-3.0 years") and "apply?job=1" in got[0].url
      and got[0].location == "Noida / Chennai" and str(got[0].posted)[:10] == "2026-10-16", [(j.title, j.url, j.text[:30]) for j in got])

pj = {"count": 3, "next": None, "results": [
    {"id": 1, "slug": "se", "title": "Software Engineer", "location": "Remote", "country": "", "other_locations": '[{"location": "Noida, India"}]',
     "min_experience": "2.0", "max_experience": "4.0", "workplace_type": "REMOTE"},
    {"id": 2, "slug": "be", "title": "Backend Engineer", "location": "Dubai, UAE", "other_locations": "[]"},
    {"id": 3, "slug": "bd", "title": "Business Development Associate", "location": "Noida, India", "other_locations": "[]"}]}
got = list(pyjamahr.fetch({"name": "Z", "slug": "z"}, page_h(json_by_url={"company_slug": pj},
                                                            pages={"/z/se": '<script type="application/ld+json">{"@type":"JobPosting","description":"Go","datePosted":"2026-10-23"}</script>'})))
check("PyjamaHR: India found in other_locations, non-India and non-fitting titles skipped, years asked in the text",
      [(j.title, j.location, j.text.split("\n")[0], j.remote) for j in got] == [("Software Engineer", "Noida, India", "Experience: 2-4 years", True)], got)

zw_rows = lambda start: [{"_source": {"jobTitle": t, "location": loc, "minYearOfExperience": 1, "maxYearOfExperience": 3, "jobUrl": f"j{start + i}",  # noqa: E731
                                      "mediumDescription": "<p>Java</p>", "jobCreatedDate": 1793000000000, "showSal": sal, "minJobSalary": "2500000",
                                      "maxJobSalary": "4000000", "currencyType": "INR"}}
                         for i, (t, loc, sal) in enumerate([("Backend SDE 1", "Bengaluru, Karnataka, India", True),
                                                            ("Backend SDE 2", "Dubai, UAE;Gurugram, Haryana, India", False)])]
sent = []
def zw_post(k):  # noqa: E302
    crit = json.loads(k["files"]["filterCri"][1]); sent.append((crit["paginationStartNo"], k["files"]["companyId"][1]))
    return {"data": {"data": zw_rows(crit["paginationStartNo"]), "totalCount": 4, "hasMoreData": crit["paginationStartNo"] == 0}}
got = list(zwayam.fetch({"name": "S", "base": "https://careers.s.com/s/", "domain": "careers.s.com", "company_id": "MTE="}, page_h(post=zw_post)))
check("Zwayam: pages by offset until hasMoreData ends, India part of multi-locations kept, salary only when the site shows it",
      sent == [(0, "MTE="), (2, "MTE=")] and [(j.location, j.url, bool(j.pay_posted)) for j in got][:2]
      == [("Bengaluru, Karnataka, India", "https://careers.s.com/s/job/j0", True), ("Gurugram, Haryana, India", "https://careers.s.com/s/job/j1", False)]
      and crawl.posted_pay_lpa(got[0].pay_posted) == 25 and got[0].text.startswith("Experience: 1-3 years"), (sent, [(j.location, j.url, j.pay_posted) for j in got]))

sf_feed = ('<rss><channel>'
           '<item><title>Java Developer (Bangalore, IN)</title><description>&lt;p&gt;2+ years&lt;/p&gt;</description><link>https://x/job/1/</link>'
           '<g:expiration_date>2099-01-01</g:expiration_date><g:location>Bangalore, IN</g:location></item>'
           '<item><title>Java Developer (Bangalore, IN)</title><description>old</description><link>https://x/job/2/</link>'
           '<g:expiration_date>2020-01-01</g:expiration_date><g:location>Bangalore, IN</g:location></item>'
           '<item><title>Java Developer (London, GB)</title><description>x</description><link>https://x/job/3/</link><g:location>London, GB</g:location></item>'
           '<item><title><![CDATA[Software Engineer & Co (Pune, MH, IN)]]></title><description>y</description><link>https://x/job/4/</link><g:location>Pune, MH, IN</g:location></item>'
           '</channel></rss>')
got = list(successfactors.fetch({"name": "SC", "host": "x"}, page_h(pages={"/sitemal.xml": sf_feed})))
check("SuccessFactors feed: India only, expired jobs dropped, '(City, CC)' cut from titles, CDATA read",
      [(j.title, j.url) for j in got] == [("Java Developer", "https://x/job/1/"), ("Software Engineer & Co", "https://x/job/4/")] and "2+ years" in got[0].text,
      [(j.title, j.url) for j in got])
check("SuccessFactors feed: country code IN spelled out, so the scorer's India check keeps small cities",
      [j.location for j in got] == ["Bangalore, India", "Pune, MH, India"] and crawl.in_india(got[0].location), [j.location for j in got])
check("PyjamaHR: other_locations read from JSON, Python-literal or broken strings without crashing",
      pyjamahr.parse_list('[{"location": "Pune"}]') == [{"location": "Pune"}] and pyjamahr.parse_list("[{'location': 'Pune'}]") == [{"location": "Pune"}]
      and pyjamahr.parse_list("[broken") == [] and pyjamahr.parse_list(None) == [] and pyjamahr.parse_list([1]) == [1])

koch = ('<article class="article article--result"><h3><a href="https://k.example/careers/JobDetail/SE/1"> Software Engineer </a></h3>'
        '<div class="article__content__field__label"> Location: </div> <div class="article__content__field__value"> Bengaluru, Karnataka </div></article>')
check("Avature: labelled 'Location:' field (Koch theme)", avature.items(koch) == [("https://k.example/careers/JobDetail/SE/1", "Software Engineer", "Bengaluru, Karnataka")],
      avature.items(koch))

from portals import ripplehire
rh_jobs = {"*:*": [("1", "Software Engineer", "Gurgaon"), ("2", "Software Engineer", "Remote"), ("3", "Branch:Teller", "Pune"),
                   ("4", "Software Engineer", "Dubai"), ("5", "Software Engineer", "Mumbai")],
           "engineer": [("1", "Software Engineer", "Gurgaon"), ("6", "Backend Engineer", "Pune")]}
rh_calls = []
def rh_post(url, data=None, **k):  # noqa: E302
    p = json.loads(data["careerSiteUrlParams"]); rh_calls.append((p["search"], p["page"], p["token"]))
    rows = rh_jobs[p["search"]][p["page"] * 2:p["page"] * 2 + 2]  # pages of 2 to exercise paging
    body = "".join(f"<jobVoList><jobSeq>{s}</jobSeq><jobTitle>{t}</jobTitle><locations>{l}</locations><jobMinExp>1</jobMinExp><jobMaxExp>3</jobMaxExp></jobVoList>"
                   for s, t, l in rows)
    return SimpleNamespace(text=f"<JobPageVO><totalJobCount>{len(rh_jobs[p['search']])}</totalJobCount><jobVoList>{body}</jobVoList></JobPageVO>",
                           raise_for_status=lambda: None)
def rh_get(url, params=None, **k):  # noqa: E302
    if "candidatejobdetail" not in url:  # the published careers link redirects to the tokened list page
        return SimpleNamespace(url="https://x.ripplehire.com/candidate/?token=TOK1&source=CAREERSITE#list", text="", raise_for_status=lambda: None)
    seq = params["jobSeq"]
    status = "CLOSED" if seq == "5" else "ACTIVE"
    desc = "&lt;p&gt;Remote, India. Java&lt;/p&gt;" if seq == "2" else "&lt;p&gt;Java&lt;/p&gt;"
    return SimpleNamespace(text=f"<x><jobDesc>{desc}</jobDesc><jobPostingDate>03-Sep-2026</jobPostingDate><jobStatus>{status}</jobStatus></x>")
rh_h = SimpleNamespace(Job=crawl.Job, title_ok=crawl.title_ok, in_india=crawl.in_india, strip_html=crawl.strip_html,
                       SESSION=SimpleNamespace(get=rh_get, post=rh_post))
got = list(ripplehire.fetch({"name": "Bank", "slug": "x", "careers_link": "https://x.ripplehire.com/candidate/careers", "searches": ["*:*", "engineer"]}, rh_h))
check("RippleHire: token read from the published link's redirect, every page of every search, duplicates across searches once, "
      "India/remote only, closed jobs skipped, years and posting date read",
      [(j.url.rsplit("/", 1)[1], j.location, j.remote) for j in got] == [("1", "Gurgaon", False), ("2", "India (remote)", True), ("6", "Pune", False)]
      and {t for _, _, t in rh_calls} == {"TOK1"} and [(s, p) for s, p, _ in rh_calls] == [("*:*", 0), ("*:*", 1), ("*:*", 2), ("engineer", 0)]
      and got[0].text.startswith("Experience: 1-3 years") and str(got[0].posted)[:10] == "2026-09-03",
      ([(j.url, j.location) for j in got], rh_calls))

# --- hand-built readers round: TurboHire pass-through feed, MediaTek tRPC, Indiana vs India --------------------------
check("in_india: two-part 'City, IN' is Indiana unless another India marker is present; 'City, ST, IN' stays India",
      not crawl.in_india("Greenwood, IN") and not crawl.in_india("Greenwood, IN / Savannah, GA") and crawl.in_india("Hubli, KA, IN")
      and crawl.in_india("Bengaluru, IN") and crawl.in_india("India"))

from portals import turbohire_feed, mediatek
th = {"data": {"FilteredCount": 3, "Jobs": [
    {"JobTitle": "Full Stack Developer - SDE - I", "Location": '[{"Address":"Bengaluru, Karnataka, India"}]', "Experience": "{'MinExp': 1, 'MaxExp': 2}",
     "JobDescription": "<p>Java</p>", "ApplyUrl": "https://k.turbohire.co/job/1", "PublishedDate": "2026-11-07T11:12:29.3555867Z"},
    {"JobTitle": "Product Manager", "Location": '[{"Address":"Bengaluru, Karnataka, India"}]'},
    {"JobTitle": "Backend Engineer", "Location": '[{"Address":"Dubai, UAE"}]'}]}}
got = list(turbohire_feed.fetch({"name": "K", "feed": "https://k.com/list?category=Technology"}, page_h(json_by_url={"k.com/list": th})))
check("TurboHire feed: JSON and Python-literal fields parsed, India + fitting titles only, years in the text",
      [(j.title, j.url, j.text.split("\n")[0], str(j.posted)[:10]) for j in got]
      == [("Full Stack Developer - SDE - I", "https://k.turbohire.co/job/1", "Experience: 1-2 years", "2026-11-07")], got)
try:
    list(turbohire_feed.fetch({"name": "K", "feed": "https://k.com/list"}, page_h(json_by_url={"k.com/list": {"data": {"FilteredCount": 17, "Jobs": th["data"]["Jobs"]}}})))
    truncated = False
except ValueError:
    truncated = True
check("TurboHire feed: fewer jobs than FilteredCount raises (truncated feed is visible, not silent)", truncated)

mt_pages = {1: {"pagination": {"total_pages": 2}, "jobs": [
                {"id": "MIN1", "title": "Software Engineer", "jobPostStatus": "posted", "publishedDate": "2026-11-09T16:00:00.000+00:00", "description": "<p>C++</p>",
                 "properties": {"location": {"code": "Bangalore\t"}, "workExperience": {"code": "1~3 Years"}}},
                {"id": "MUS1", "title": "Software Engineer", "jobPostStatus": "posted", "properties": {"location": {"code": "West Lafayette, IN"}}}]},
            2: {"pagination": {"total_pages": 2}, "jobs": [
                {"id": "MIN2", "title": "Software Engineer", "jobPostStatus": "closed", "properties": {"location": {"code": "Noida"}}},
                {"id": "MIN3", "title": "Backend Engineer", "jobPostStatus": "posted", "properties": {"location": {"code": "Noida"}}}]}}
mt_h = page_h(); mt_h.get = lambda url, params=None, **k: [{"result": {"data": {"json": mt_pages[json.loads(params["input"])["0"]["json"]["page"]]}}}]
got = list(mediatek.fetch({"name": "MediaTek"}, mt_h))
check("MediaTek: every page read, Indiana ('City, IN') and closed jobs skipped, city trimmed, experience band in the text",
      [(j.url.rsplit("/", 1)[1], j.location) for j in got] == [("MIN1", "Bangalore"), ("MIN3", "Noida")] and got[0].text.startswith("Experience: 1~3 Years"),
      [(j.url, j.location) for j in got])

# --- robots.txt rules, cached sitemap pages (Meta), saved pages ------------------------------------------
from portals.sitemap import Robots  # noqa: E402
eightfold = Robots("User-agent: *\nDisallow: /\nAllow: /$\nAllow: /careers\nAllow: /api/pcsx\n", "test")
check("robots: longest rule wins (Eightfold's 'Disallow: /' + 'Allow: /careers' allows job pages; first-match parsers blocked them)",
      eightfold.can_fetch("https://x.eightfold.ai/careers/job/1-dev?domain=x.com") and not eightfold.can_fetch("https://x.eightfold.ai/admin")
      and eightfold.can_fetch("https://x.eightfold.ai/"))
rb = Robots("User-agent: other\nDisallow: /\n\nUser-agent: *\nDisallow: /search$\nDisallow: /*.pdf\nDisallow: /private/\nAllow: /private/jobs/\n", "test")
check("robots: '*' group used when no group names us; '*' and '$' patterns; Allow inside a disallowed folder",
      rb.can_fetch("https://a.com/searching/x") and not rb.can_fetch("https://a.com/search") and not rb.can_fetch("https://a.com/x/y.pdf") and not rb.can_fetch("https://a.com/private/a")
      and rb.can_fetch("https://a.com/private/jobs/1"))

import tempfile  # noqa: E402
from pathlib import Path as _P  # noqa: E402
tmp = _P(tempfile.mkdtemp())
real_out, real_root = crawl.OUT, crawl.ROOT
crawl.OUT, crawl.ROOT = tmp / "output", tmp
meta_map = "<urlset>" + "".join(f"<url><loc>https://careers.meta.test/profile/job_details/{i}/</loc></url>" for i in (1, 2, 3)) + "</urlset>"
fetched = []


def meta_get(url, **kw):
    fetched.append(url)
    pages = {"/1/": ld("Software Engineer, Product", "Bangalore", "IN"), "/2/": ld("Software Engineer", "Menlo Park", "US"),
             "/3/": ld("Data Center Technician", "Bangalore", "IN")}
    body = {"robots.txt": "", "sitemap.xml": meta_map}
    hit = next((v for k, v in {**pages, **body}.items() if url.endswith(k) or k in url), None)
    return SimpleNamespace(status_code=200 if hit is not None else 404, content=(hit or "").encode(), text=hit or "")


crawl.SESSION = SimpleNamespace(get=meta_get, headers={"User-Agent": "test"})
mc = {"name": "Meta", "portal": "sitemap", "host": "careers.meta.test", "sitemaps": ["https://careers.meta.test/sitemap.xml"], "cache_pages": True}
first = [(j.title, j.location) for j in portals.fetch(mc, crawl)]
pages_first = sum("/job_details/" in u for u in fetched)
fetched.clear()
meta_map = meta_map.replace("<url><loc>https://careers.meta.test/profile/job_details/1/</loc></url>", "") \
    .replace("</urlset>", "<url><loc>https://careers.meta.test/profile/job_details/4/</loc></url></urlset>")
second = [j.title for j in portals.fetch(mc, crawl)]
check("sitemap cache: bare-ID job URLs are all read once, India + title filter applied after reading",
      first == [("Software Engineer, Product", "Bangalore, IN")] and pages_first == 3, (first, pages_first))
check("sitemap cache: the next run reads only new URLs; a job gone from the sitemap is dropped (closed)",
      [u for u in fetched if "/job_details/" in u] == ["https://careers.meta.test/profile/job_details/4/"] and second == [], (fetched, second))
cache = json.loads((tmp / "output" / "sitemap-cache" / "meta.json").read_text())
check("sitemap cache: non-India roles keep no description", cache["https://careers.meta.test/profile/job_details/2/"][0]["text"] == "")
before = (tmp / "output" / "sitemap-cache" / "meta.json").read_text()
crawl.SESSION = SimpleNamespace(get=lambda url, **kw: SimpleNamespace(status_code=503, content=b"", text=""), headers={"User-Agent": "test"})
try:
    list(portals.fetch(mc, crawl))
    raised = False
except RuntimeError:
    raised = True
check("sitemap: no readable sitemap (5xx, network) raises, so the crawl keeps the previous jobs instead of closing them all",
      raised and (tmp / "output" / "sitemap-cache" / "meta.json").read_text() == before)
ef_map = ("<urlset><url><loc>https://x.eightfold.ai/careers/job/1-software-engineer-bangalore-karnataka-india</loc></url>"
          "<url><loc>https://x.eightfold.ai/careers/job/2-software-engineer-london-united-kingdom</loc></url></urlset>")
read_pages = []


def ef_get(url, **kw):
    if "/careers/job/" in url:
        read_pages.append(url)
    body = ef_map if url.endswith("sitemap.xml") else "" if url.endswith("robots.txt") else ld("Software Engineer", "Bengaluru")
    return SimpleNamespace(status_code=200, content=body.encode(), text=body)


crawl.SESSION = SimpleNamespace(get=ef_get, headers={"User-Agent": "test"})
got = list(portals.fetch({"name": "EF", "portal": "sitemap", "host": "x.eightfold.ai", "sitemaps": ["https://x.eightfold.ai/sitemap.xml"],
                          "india_in_url": True}, crawl))
check("sitemap: india_in_url reads only job pages whose URL names an Indian city",
      len(got) == 1 and read_pages == ["https://x.eightfold.ai/careers/job/1-software-engineer-bangalore-karnataka-india"], read_pages)

crawl.OUT, crawl.ROOT, crawl.SESSION = real_out, real_root, real_session

# --- Navi (TurboHire list without the "data" wrapper), Zerodha ------------------------------------------
navi = {"Total": 2, "FilteredCount": 2, "Jobs": [
    {"JobTitle": "CloudOps Engineer - I", "Location": '[{"Address":"Bangalore, Karnataka, India"}]', "Experience": "{'MinExp': 0, 'MaxExp': 2}",
     "JobDescription": "<p>AWS</p>", "ApplyUrl": "https://navi.turbohire.co/job/publicjobs/1", "PublishedDate": "2026-11-11T10:00:59.38198Z"},
    {"JobTitle": "Senior Associate - HR", "Location": '[{"Address":"Hyderabad, Telangana, India"}]'}]}
got = [(j.title, j.url, j.text.split("\n")[0]) for j in turbohire_feed.fetch({"name": "Navi", "feed": "https://navi.com/api/careers/jobs"},
                                                                              page_h(json_by_url={"navi.com/api/careers/jobs": navi}))]
check("TurboHire feed: Navi's own API (list at the top level, no 'data' wrapper) is read completely",
      got == [("CloudOps Engineer - I", "https://navi.turbohire.co/job/publicjobs/1", "Experience: 0-2 years")], got)
from portals import zerodha  # noqa: E402
zd = {"count": 3, "data": [{"job_title": "Backend Developer", "location": "Bangalore", "location_type": "Onsite", "name": "backend-developer",
                            "description": "<p>2+ years of Go</p>"},
                           {"job_title": "Legal Manager", "location": "Bangalore", "name": "legal-manager"},
                           {"job_title": "Backend Developer", "location": "Singapore", "name": "backend-sg"}]}
got = [(j.title, j.location, j.url) for j in zerodha.fetch({"name": "Zerodha"}, page_h(json_by_url={"careers.zerodha.com/api/jobs": zd}))]
check("Zerodha: its careers page's /api/jobs list; India + title filter; link names the opening",
      got == [("Backend Developer", "Bangalore, India", "https://careers.zerodha.com/#backend-developer")], got)

print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
