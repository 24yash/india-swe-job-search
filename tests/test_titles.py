"""Title filter and Workday India-facet tests. Offline; never touches real data.

Usage: python3 tests/test_titles.py <path to job-search folder>
The cases come from a 15 Nov 2026 audit of 15,380 real India titles: titles the old filter wrongly dropped,
and the ones it must keep dropping.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
import crawl  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        failures.append(name)


fam = crawl.title_family
# Wrongly dropped before the audit.
for t in ("Member of Technical Staff", "Member of Technical Staff, Backend Engineering (Go, Kubernetes)", "MTS / SMTS Backend Java Developer",
          "Software Engr II", "Associate- Software Eng", "Apps Dev Intmd Programmer Analyst - C11 - CHENNAI", "Java Spark Developer",
          "Python Cloud Developer", "Backend Engineer - Identity Verification", "Embedded Finance Backend Engineer"):
    check(f"core: {t}", fam(t) == "core", fam(t))
check("core: double space in title", fam("Software  Engineer") == "core")
# Core titles that only look like an excluded type ('security', 'sales' as a team name).
for t in ("Software Engineer - Intersight Software and Product Security", "Software Developer Engineer 1-Digital Banking Kotak 811-Regional Sales",
          "Software Dev Engineer II, Amazon Payment Services"):
    check(f"core: {t}", fam(t) == "core", fam(t))
# No role word: kept only if the JD shows development work.
for t in ("Engineer - Target India", "Engineer", "Platform Engineer, Java Fmwk", "Engineer II - Cloud", "Low Latency Developer", "Quantitative Developer"):
    check(f"generic: {t}", fam(t) == "generic", fam(t))
# The user is a core developer (CV, 15 Nov 2026): SRE/DevOps, data, AI-engineer, FDE and other role types stay out.
for t in ("Site Reliability Engineer", "Site Reliability Engineer II", "DevOps Engineer I", "Software Site Reliability Engineer - AI & Data Platforms",
          "Cloud Engineer", "Data Engineer", "Data Engineer II", "Data Platform Engineer"):
    check(f"other profile: {t}", fam(t) is None, fam(t))
# Recall first (user, 15 Nov 2026): any possible software-development role stays, whatever the org calls it.
for t, want in (("AI Engineer", "ai"), ("Applied AI Engineer", "ai"), ("Forward Deployed Engineer, GenAI, YouTube", "core"), ("Forward Deployed Engineer, Customer Experience AI", "core"), ("FDE - Backend", "core"), ("Software Development Engineer II, Amazon FinAuto - GREF Workplace Support Tech", "core"), ("SDE - I - Flutter", "core"), ("Software Development Engineer 1 - Android", "core"), ("Software Engineer : iOS", "core"), ("SDE 2 Frontend - Unpause", "core"), ("Embedded Software Engineer", "core"), ("GPU Software Development Engineer", "core"), ("Frontend Engineer", "generic"), ("Salesforce Developer", "generic"), ("Firmware Developer", "generic"), ("Guidewire Developer", "generic"), ("Webmethods Developer", "generic"), ("Machine Learning Engineer II - Backend", "core"), ("Software Engineer - Full Stack (Frontend heavy)", "core"), ("Backend Engineer - Mobile Payments", "core"), ("C++ Developers", "core"), ("Software Systems Engineer — Contributor, IX Platform", "core"), ("Technology – Software Development / IT Engineering", "core"), ("JAVA Developer/Application Support - Systems Engineer", "core"), ("Technical Developer / Analyst", "generic"),
                 ("SDE II - Data Engineer", "core"), ("Software Engineer, Data Engineering", "core"), ("Software Engineer - Oracle Fusion Finance", "core"),
                 ("Cloud Developer - Golang", "generic"), ("Systems Development Engineer", "generic"), ("Integration Engineer (SDK)", "generic"),
                 ("Security and Automation Engineer", "generic"), ("Product Engineer II - Low Power", "generic"), ("Member Technical Staff - Applied AI Engineer (US Timing)", "ai")):
    check(f"kept for the JD check or core: {t}", fam(t) == want, fam(t))
# Found by a manual audit of the shortlist: the old 'Engineer II' / 'platform/infrastructure/application engineer' rules let these in.
for t in ("Design Engineer II", "Electrical Engineer II", "Mechanical Design Engineer II", "Customer Experience Engineer II",
          "Cloud Network Engineer II", "Network Delivery Engineer 1", "SOC Engineer 1", "Server Administratior Engineer 2", "Infrastructure Engineering Associate",
          "Associate, Infrastructure Engineer", "Infrastructure Engineer - Oracle DBA", 
          "threat detection engineer", "Capacity Planning Engineer", "Technical Account Engineer I", "Research Modernization - Business Intelligence Developer"):
    check(f"not core dev: {t}", fam(t) is None, fam(t))
# Must stay out.
for t in ("Staff Software Engineer", "STAFF, SOFTWARE ENGINEER", "SMTS Software Development Eng.", "MTS 3 - Backend", "Member of Technical Staff 3",
          "Senior DevOps Engineer", "Design Verification Engineer",
          "Software Engineer Intern", "Lead Engineer", "Research Engineer", "Research Scientist", "Sales Engineer"):
    check(f"excluded: {t}", fam(t) is None, fam(t))
for t in ("Forward Deployed Strategist", "Software Development Manager", "Business Development Executive", "Tableau Developer", "Java L1 Support", "SDET", "QA Engineer", "Data Scientist"):
    check(f"excluded: {t}", fam(t) is None, fam(t))

# The JD check: titles that don't say software need a software JD.
check("generic title needs the JD check", crawl.needs_software_jd("Engineer - Target India", "generic"))
check("MTS needs the JD check (hardware firms use it too)", crawl.needs_software_jd("Member of Technical Staff", "core"))
check("plain core title skips the JD check", not crawl.needs_software_jd("Software Engineer II", "core"))
check("software JD recognised", crawl.software_jd("Build microservices in Java and Spring on AWS with PostgreSQL"))
check("civil JD rejected", not crawl.software_jd("Piling works, site supervision, AutoCAD drawings, safety audits"))
check("empty JD rejected", not crawl.software_jd(""))
check("hardware JD rejected despite Python/Linux", not crawl.software_jd("SoC validation in the lab: Python scripts, Linux, oscilloscope, silicon bring-up"))
check("'api' and 'APIs' count once; English 'go' is not Go", not crawl.software_jd("Go to market with our API and APIs"))
check("lenient (MTS, Programmer Analyst): boilerplate JD kept", crawl.software_jd("Participate in new or revised application systems.", strict=False))
check("lenient: hardware JD still rejected", not crawl.software_jd("RTL design, Verilog, silicon timing closure", strict=False))
check("excluded: Chief Engineer", fam("Chief Engineer") is None)
check("C++ and C# count as software terms", crawl.software_jd("C++ and C# services with REST APIs"))
check("ops JD rejected despite Kubernetes/Linux/AWS", not crawl.software_jd("Administer Linux servers, Kubernetes and AWS provisioning, ITIL tickets, firewall rules"))
check("lenient: one incidental admin word doesn't sink a Java/Spring JD",
      crawl.software_jd("Java, Spring microservices. Teams include database administration and network operations.", strict=False))

job = lambda title, text: crawl.Job("Acme", title, "Bengaluru, India", f"u-{title}", crawl.NOW, text)  # noqa: E731
co = {"name": "Acme", "type": "Product", "quality": 12, "pay": "likely", "pay_note": "Levels.fyi India SE median 30 LPA"}
row, why = crawl.evaluate(job("Engineer - Target India", "Java, Spring Boot, REST APIs, Kubernetes. 1-3 years."), co, 21)
check("evaluate: generic title with software JD kept, tagged generic", row is not None and row["role_family"] == "generic", why)
row, why = crawl.evaluate(job("Engineer - Piling", "Site execution of piling works. 1-3 years."), co, 21)
check("evaluate: generic title with civil JD rejected with a reason", row is None and "doesn't say software" in why, why)
row, why = crawl.evaluate(job("Software Engineer", "Build things. 1-3 years."), co, 21)
check("evaluate: core title kept without a software-heavy JD", row is not None and row["role_family"] == "core", why)

# Workday: use the board's India facet instead of capped keyword searches.
calls = []


def fake_post(url, body, **kw):
    calls.append(body)
    if body["limit"] == 1:
        return {"total": 3, "facets": [{"facetParameter": "locationMainGroup", "values": [
            {"facetParameter": "locations", "values": [{"descriptor": "Bangalore, India", "id": "blr"},
                                                        {"descriptor": "Indianapolis, IN", "id": "indy"},
                                                        {"descriptor": "Pune, India", "id": "pune"}]}]}]}
    page = [{"title": "Engineer - Target India", "externalPath": "/job/a", "locationsText": "Bangalore, India"},
            {"title": "Senior Engineer", "externalPath": "/job/b", "locationsText": "Bangalore, India"},
            {"title": "Software Engineer", "externalPath": "/job/c", "locationsText": "Pune, India"}]
    return {"total": 3 if body["offset"] == 0 else 0, "jobPostings": page if body["offset"] == 0 else []}


def fake_get(url, **kw):
    path = url.split("targetcareers")[1]
    return {"jobPostingInfo": {"title": {"/job/a": "Engineer - Target India", "/job/c": "Software Engineer"}[path],
                               "location": "Bangalore, India", "jobDescription": "Java microservices on Kubernetes",
                               "externalUrl": "https://x" + path, "startDate": "2026-11-10"}}


crawl.post, crawl.get = fake_post, fake_get
got = list(crawl.workday({"name": "Target", "tenant": "target", "wd": "wd5", "site": "targetcareers"}))
facet_calls = [b for b in calls if b["limit"] == 20]
check("workday: India facet found (city values, Indianapolis left out)",
      facet_calls and facet_calls[0]["appliedFacets"] == {"locations": ["blr", "pune"]}, facet_calls[:1])
check("workday: empty search text, so no keyword decides what we see", facet_calls and facet_calls[0]["searchText"] == "")
check("workday: title filter applied locally (generic kept, senior dropped)", sorted(j.title for j in got) == ["Engineer - Target India", "Software Engineer"],
      [j.title for j in got])

print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
