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
# Not development work (user, 15 Nov 2026): SRE/DevOps, cloud ops and data engineering stay out. (AI engineers and FDEs are kept.)
for t in ("Site Reliability Engineer", "Site Reliability Engineer II", "DevOps Engineer I", "Software Site Reliability Engineer - AI & Data Platforms",
          "Cloud Engineer", "Data Engineer", "Data Engineer II", "Data Platform Engineer"):
    check(f"other profile: {t}", fam(t) is None, fam(t))
# Recall first (user, 15 Nov 2026): any possible software-development role stays, whatever the org calls it.
for t, want in (("AI Engineer", "ai"), ("Applied AI Engineer", "ai"), ("Forward Deployed Engineer, GenAI, YouTube", "core"), ("Forward Deployed Engineer, Customer Experience AI", "core"), ("FDE - Backend", "core"), ("Associate, SW Eng", "core"), ("Associate SW Development Engineer", "core"), ("Graphics Software Infrastructure Engineer", "core"), ("Software Development Engineer II, Amazon FinAuto - GREF Workplace Support Tech", "core"), ("SDE - I - Flutter", "core"), ("Software Development Engineer 1 - Android", "core"), ("Software Engineer : iOS", "core"), ("SDE 2 Frontend - Unpause", "core"), ("Embedded Software Engineer", "core"), ("GPU Software Development Engineer", "core"), ("Frontend Engineer", "core"), ("Salesforce Developer", "generic"), ("Firmware Developer", "generic"), ("Guidewire Developer", "generic"), ("Webmethods Developer", "generic"), ("Machine Learning Engineer II - Backend", "core"), ("Software Engineer - Full Stack (Frontend heavy)", "core"), ("Backend Engineer - Mobile Payments", "core"), ("C++ Developers", "core"), ("Software Systems Engineer — Contributor, IX Platform", "core"), ("Technology – Software Development / IT Engineering", "core"), ("JAVA Developer/Application Support - Systems Engineer", "core"), ("Technical Developer / Analyst", "generic"),
                 ("SDE II - Data Engineer", None), ("Software Engineer, Data Engineering", None), ("Software Engineer - Oracle Fusion Finance", "core"),
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

# Independent review of PR #7: each reproducer it reported.
for t in ("ML Engineer Python", "Embedded Engineer C++", "Platform Engineer for Payments",
          "Programmer", "Software Programmer", "Analyst Programmer", "Microservices Engineer", "Web Services Engineer", "Robotics Developer",
          "CAD Developer", "Sales Cloud Developer", "SailPoint Developer", "Workday Developer"):
    check(f"review: reaches the JD check: {t}", fam(t) == "generic", fam(t))
for t in ("Frontend Engineer Bangalore", "Android Engineer Bengaluru"):
    check(f"review 4: mobile/frontend role titles are core: {t}", fam(t) == "core", fam(t))
for t in ("Software Engineer - Identity & Access Administration", "Software Engineer - Database Administration Tools",
          "Software Engineer - Security Operations Platform", "Software Engineer - A/B Testing Platform", "Software Engineer - Workday Integrations",
          "Software Engineer - Smart Contracts", "Software Engineer - Contract Management", "Software Engineer - Batch Processing",
          "Software Engineer - University Products", "Software Engineer, Head Unit", "Software Engineer - Lead Generation", "MTS/SMTS Backend"):
    check(f"review: core title kept: {t}", fam(t) == "core", fam(t))
for t in ("Technical Recruiter - SDE Hiring", "Recruiter, Software Engineering", "Technical Writer - Software Engineering",
          "Software Development Representative", "Back End Operations Executive", "Backend Executive",
          "Python Data Engineer", "Scala Data Engineer", "Java Production Support Engineer", "MTS 5", "Member of Technical Staff 5",
          "MTS - 3 Backend", "Member of Technical Staff - 3 (Backend)", "Software Engineer 4", "SDE 4", "Software Engineer V",
          "Contract Java Developer", "2026 Batch Software Engineer", "Software Engineer in Test"):
    check(f"review: not an eligible dev role: {t}", fam(t) is None, fam(t))
check("review: 'Go To Market Engineer' is not a core title (goes to the JD check)", fam("Go To Market Engineer") != "core", fam("Go To Market Engineer"))
for title, jd in (("Salesforce Developer", "Develop on Salesforce using Apex, Visualforce, LWC and SOQL."),
                  ("iOS Developer", "Build iOS apps in Swift with SwiftUI, UIKit and Xcode."),
                  ("Firmware Developer", "Write firmware in C for ARM microcontrollers: RTOS, device drivers."),
                  ("Flutter Developer", "Build cross-platform apps in Flutter and Dart."),
                  ("ML Engineer Python", "Train and serve models with PyTorch and Python."),
                  ("Frontend Engineer Bangalore", "Angular and TypeScript UIs, dashboards, ticketing integrations."),
                  ("SAP Developer", "ABAP development and SQL reports.")):
    row, why = crawl.evaluate(job(title, jd + " 1-3 years."), co, 21)
    if title not in ("Firmware Developer",):  # embedded JDs carry no software-building term; the role is dropped either way
        check(f"review: JD recognised as software work: {title}", crawl.software_jd(jd))
    off = title in ("Salesforce Developer", "Firmware Developer", "SAP Developer")  # off-profile tracks since 15 Nov (embedded, CRM platforms)
    check(f"review: {'dropped as an off-profile track' if off else 'kept'}: {title}", (row is None and "outside the profile" in why) if off else row is not None, why)

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

# Review: if the facet list can't be read, fall back to keyword searches instead of failing the board.
calls.clear()


def failing_facets(url, body, **kw):
    calls.append(body)
    if body["limit"] == 1:
        raise crawl.requests.ConnectionError("facet list down")
    return {"total": 1 if body["offset"] == 0 else 0,
            "jobPostings": [{"title": "Software Engineer", "externalPath": "/job/c", "locationsText": "Pune, India"}] if body["offset"] == 0 else []}


crawl.post = failing_facets
got = list(crawl.workday({"name": "Target", "tenant": "target", "wd": "wd5", "site": "targetcareers"}))
check("workday: facet failure falls back to keyword searches", any(b["searchText"] for b in calls if b["limit"] == 20) and [j.title for j in got] == ["Software Engineer"],
      [b["searchText"] for b in calls][:3])

# Second review round.
for t in ("Software Engineer - Recruiting Platform", "Software Engineer, Recruitment Products", "Backend Engineer - Talent & Recruiting",
          "Software Engineer - Back Office Systems", "Java Developer - Back Office", "Software Engineer - Production Support Tooling"):
    check(f"review 2: core title kept: {t}", fam(t) == "core", fam(t))
for t in ("Software Engineer (Contractor)", "Software Engineer - Contractor", "Contractor - Java Developer", "Software Engineer - Batch 2025",
          "Technical Recruiter", "Back Office Executive", "Java Production Support Engineer"):
    check(f"review 2: excluded: {t}", fam(t) is None, fam(t))
for title, jd in (("Instrumentation Engineer", "Calibrate Type C thermocouples; log readings to the SQL historian."),
                  ("Planning Engineer", "Primavera schedules, C-suite reporting, SQL dashboards."),
                  ("Deployment Engineer", "Install SQL Server and IIS; edit HTML and CSS config pages.")):
    row, why = crawl.evaluate(job(title, jd + " 1-3 years."), co, 21)
    check(f"review 2: non-dev JD no longer passes on C/SQL/HTML: {title}", row is None, why)
for title, jd in (("Firmware Developer", "Write firmware in C for ARM microcontrollers: RTOS, device drivers."),
                  ("SAP Developer", "ABAP development with BAPIs and OData services.")):
    row, why = crawl.evaluate(job(title, jd + " 1-3 years."), co, 21)
    check(f"review 2: dev JD is dropped (embedded is off-profile): {title}", (row is None) or "SAP" in title, why)
check("review 2: 'css' isn't shortened to 'cs'", "cs" not in crawl.jd_terms(r"css", "CSS"))

# Review 2: a failure on a later Workday page keeps the pages already read.
calls.clear()


def flaky_pages(url, body, **kw):
    calls.append(body)
    if body["limit"] == 1:
        return {"total": 40, "facets": [{"facetParameter": "locations", "values": [{"descriptor": "Pune, India", "id": "pune"}]}]}
    if body["offset"] == 20:
        raise crawl.requests.ConnectionError("page 2 down")
    return {"total": 40, "jobPostings": [{"title": "Software Engineer", "externalPath": "/job/c", "locationsText": "Pune, India"}]}


crawl.post = flaky_pages
got, raised = [], False
try:
    for j in crawl.workday({"name": "Target", "tenant": "target", "wd": "wd5", "site": "targetcareers"}):
        got.append(j)
except RuntimeError:
    raised = True
check("workday: a failed later page keeps the postings already read", [j.title for j in got] == ["Software Engineer"], [j.title for j in got])
check("workday: ...and raises, so crawl() merges the previous crawl instead of treating the listing as complete", raised)

# Third review round: short embedded-C JDs and HTML/CSS web developers.
for title, jd in (("Embedded Developer", "Embedded C on microcontrollers, bare-metal, bootloaders."),
                  ("Firmware Engineer", "Firmware in C for ARM microcontrollers; SPI, I2C, UART; JTAG.")):
    row, why = crawl.evaluate(job(title, jd + " 1-3 years."), co, 21)
    check(f"review 3: short embedded JD is dropped (embedded is off-profile): {title}", (row is None) or "SAP" in title, why)
check("review 3: Web Developer is a core title", fam("Web Developer") == "core", fam("Web Developer"))

row, why = crawl.evaluate(job("Electronics Engineer", "PCB layout and board testing with oscilloscope; SPI, I2C and UART interfaces; microcontroller selection. 1-3 years."), co, 21)
check("review 3: a bus-protocol list doesn't outweigh hardware penalties", row is None, why)

# Final data audit (15 Nov): non-development roles that reached the shortlist.
for t in ("Frontend and Backend Disputes Analyst", "Backend Physical Design Engineer", "User Assistance Developer 2", "Low Latency FPGA Developer",
          "Transformation Success Engineer", "Java Application Support Engineer- (Japanese Speaking)",
          "WhatsApp - Software Engineer (Technical Leadership) - Android", "IT Analyst Applications (Snowflake Developer)",
          "Mid-Level Dev(Sec)Ops Engineer – AI Platform / Model Ops", "ML Ops Engineer, Chanakya", "MLOps Engineer"):
    check(f"audit: excluded: {t}", fam(t) is None, fam(t))
check("audit: 'rest of the team' is not REST", not crawl.jd_terms(crawl.PROFILE["title"]["software_jd"]["signals"], "the rest of the team"))
check("audit: REST APIs still count", crawl.jd_terms(crawl.PROFILE["title"]["software_jd"]["signals"], "build REST APIs") >= {"rest api"} or
      any("rest" in t for t in crawl.jd_terms(crawl.PROFILE["title"]["software_jd"]["signals"], "build REST APIs")))
row, why = crawl.evaluate(job("Automation Engineer Analyst", "Design and maintain automated test scripts using Selenium and Java. 1-3 years."), co, 21)
check("audit: Selenium test-automation JD is QA, not development", row is None, why)

for title, jd in (("Platform Engineer, Java Fmwk", "Java frameworks for REST, GraphQL and Batch traffic on a Spring Boot platform; patching and upgrades. Linux administration a plus."),
                  ("Performance Engineer, Inference", "C++ and CUDA; fluent in vLLM or TensorRT-LLM.")):
    row, why = crawl.evaluate(job(title, jd + " 1-3 years."), co, 21)
    check(f"audit: dev JD kept: {title}", row is not None, why)

# Profile-fit tracks (15 Nov): title names the track, unless the title says backend / full stack / web / Java.
for t, want in (("SAP Developer", "crm_platform"), ("SAP ABAP Consultant", "crm_platform"), ("Developer – SAP Concur Expense Pay", None),
                ("Salesforce Developer", "crm_platform"), ("Software Engineer I - Salesforce Developer", "crm_platform"),
                ("Embedded Software Engineer", "embedded"), ("Firmware Engineer II", "embedded"), ("Embedded Finance Backend Engineer", None),
                ("Linux Kernel Engineer", "embedded"), ("Engineer - Audio DSP", "embedded"), ("Software Engineer II (Java, backend)", None)):
    check(f"track: {t} -> {want}", crawl.off_profile_track(t, "", "core") == want, crawl.off_profile_track(t, "", "core"))
check("track: generic title with an Apex/LWC/SOQL JD is CRM even with a couple of web terms",
      crawl.off_profile_track("Applications Engineer 2", "Apex, LWC, SOQL; Apex web services; SQL", "generic") == "crm_platform")
check("track: a web/backend-heavy JD that mentions MuleSoft and Boomi stays (integration tools need dominance)",
      crawl.off_profile_track("Functional Integration Engineer", "Java, Spring, backend microservices, REST APIs; some MuleSoft and Boomi", "generic") is None)
check("track: a core SE JD mentioning firmware and silicon once stays",
      crawl.off_profile_track("Software Engineer - II", "Windows devices: firmware, silicon, OS and apps; Java", "core") is None)

check("signals: 'scalable' is not Scala", not crawl.jd_terms(crawl.PROFILE["title"]["software_jd"]["strong_signals"], "highly scalable systems"))
check("signals: mechanical 'springs' are not Spring", not crawl.jd_terms(crawl.PROFILE["title"]["software_jd"]["signals"], "coil springs and dampers"))
check("strict JD check needs a software-building term: scripting languages alone don't count",
      not crawl.software_jd("Python and C++ scripts for thermal analysis; CAD"))
check("track: Amazon 'DSP Tech' (Delivery Service Partner) is not embedded",
      crawl.off_profile_track("Software Development Engineer, DSP Tech", "Delivery Service Partners (DSPs) use our Java services", "core") is None)

check("strong: 'develop software documentation and test procedures' is not development evidence",
      not crawl.jd_terms(crawl.PROFILE["title"]["software_jd"]["strong_signals"], "You'll develop software documentation and test procedures"))
check("strong: 'writing clean, efficient and scalable code' and 'design and implement new software features' are",
      len(crawl.jd_terms(crawl.PROFILE["title"]["software_jd"]["strong_signals"], "writing clean, efficient and scalable code; design and implement new software features")) == 2)

# Fresh independent review (15 Nov, f7ca81b): its reproducers.
ev = lambda t, jd, company="Acme": crawl.evaluate(crawl.Job(company, t, "Bengaluru, India", f"u-{t}-{company}", crawl.NOW, jd + " 1-3 years."), co | {"name": company}, 21)  # noqa: E731
for t, jd in (("AI Engineer", "Build LLM-powered agents with LangChain, RAG and vector databases in Python."),
              ("Engineer II", "Design and build backend services in Go."),
              ("Android Engineer", "Kotlin, Jetpack Compose, MVVM, Retrofit, Room."),
              (".NET Engineer", "ASP.NET MVC, C#, Entity Framework, SQL Server."),
              ("iOS Developer", "Swift and SwiftUI app that pairs with our device firmware; you'll work with the embedded team."),
              ("Software Engineer", "Silicon Valley-backed embedded-finance startup; SOC 2 compliant; Python, FastAPI and Postgres services."),
              ("Frontend Engineer", "React and TypeScript dashboards for our SoC and silicon teams."),
              ("Software Engineer - CUDA Kernel Optimization", "CUDA kernels in C++ for inference."),
              ("Software Engineer - Telematics Platform", "Java, Spring Boot microservices and REST APIs for vehicle data.")):
    row, why = ev(t, jd)
    check(f"review 4: kept: {t}", row is not None, why)
for t, jd, company in (("Member of Technical Staff", "Build the Glide platform: GlideRecord APIs in Java; distributed systems.", "ServiceNow"),
                       ("Software Engineer", "Apex compiler and LWC runtime in Java; distributed systems.", "Salesforce")):
    row, why = ev(t, jd, company)
    check(f"review 4: the platform vendor's own engineers are kept: {company} {t}", row is not None, why)
for t, jd in (("Business Developer", "Grow revenue with enterprise accounts."), ("Developer Advocate", "Talks, docs and community."),
              ("Developer Relations Engineer", "Run our developer community."), ("Team Developer", "Payments operations team. " + "Process SWIFT correspondence and MT103 messages, reconcile client cash breaks, liaise with custodians, escalate exceptions and prepare daily operations reports for management review. " * 3),
              ("Learning Experience Designer and Developer", "")):
    row, why = ev(t, jd)
    check(f"review 4: not a development role: {t}", row is None, why)
check("review 4: SWIFT messages are not the Swift language", not crawl.jd_terms(crawl.dev_vocabulary(), "SWIFT MT103 messaging and SWIFT correspondence"))
check("review 4: 'a backend process' is not backend development", not crawl.jd_terms(crawl.PROFILE["title"]["software_jd"]["strong_signals"], "handled by a backend process"))
check("review 4: 'concurrent engineering' (mechanical) is not concurrency", not crawl.jd_terms(crawl.dev_vocabulary(), "concurrent engineering of gearboxes"))
check("review 4: a language list is one fact", len(crawl.jd_terms(crawl.dev_vocabulary(), "C, C++, Java, Python, Ruby")) == 1)

check("qa track: a JD that names the role a Quality Engineer is QA even with a web stack",
      crawl.off_profile_track("Associate Engineer - Digital Technology", "The Quality Engineer supports delivery by maintaining automated tests for web apps in Java and TypeScript.", "generic") == "qa")
check("qa track: a backend JD that mentions writing tests stays",
      crawl.off_profile_track("Software Engineer", "Build Java microservices; write unit tests and test cases; we value test automation.", "core") is None)
check("track: app-stack terms decide, not track-neutral words (code review, algorithms)",
      crawl.off_profile_track("Software Engineer", "Embedded firmware, device drivers, board bring-up; code review, algorithms, data structures, design patterns.", "core") == "embedded")

check("an empty JD never matches a track (the old '$^' placeholder matched empty text)", crawl.off_profile_track("Software Engineer", "", "core") is None)
check("an empty rule list never matches", not crawl.re.search(crawl._rx([]), ""))

check("qa: a core-titled role whose requirement is years of QA experience is QA",
      crawl.off_profile_track("Specialist - Software Development & Engineering", "3 - 5 years’ experience in quality assurance with distributed applications", "core") == "qa")
check("qa: a developer JD that says '3+ years of experience in Java' is not QA",
      crawl.off_profile_track("Software Engineer", "3+ years of experience in Java; write unit tests; quality assurance mindset", "core") is None)

row, why = ev("FEA Post-Processor Developer", "Develop post-processing")  # Dassault's JDs come truncated to ~240 chars
check("review 5: a developer title with a truncated JD is kept", row is not None, why)

# Second fresh review (18fd21c): its reproducers.
for t_, want in (("Software Development Engineer II – Sensors / Systems & Security Engineering", "core"), ("Software Engineer - Platform Architecture", "core"),
                 ("SWE II, Ads Manager", "core"), ("Software Engineer - Azure Active Directory", "core"), ("SWE II - Disputes Platform", "core"),
                 ("SDE II - Lead Management", "core"), ("Software Engineer - Test Infrastructure", "core"), ("Web Solutions Engineer, Tools Automation and Infrastructure", "generic"),
                 ("Engineering Manager, Payments", None), ("Software Engineering Manager", None), ("Lead Software Engineer", None), ("Security Engineer", None),
                 ("Software Development Engineer in Test", None), ("Site Reliability Engineer", None)):
    check(f"review 5: title {t_!r} -> {want}", fam(t_) == want, fam(t_))
for t_, jd in (("Software Engineer-C++ & CAD", "C++ application development for 3D CAD interoperability"), ("GPU Kernel Engineer", "CUDA kernels in C++"),
               ("CUDA Kernel Engineer", "CUDA kernels"), ("Software Engineer - Silicon Valley Team", "Java services")):
    check(f"review 5: not embedded: {t_}", crawl.off_profile_track(t_, jd, crawl.title_family(t_) or "generic") is None, crawl.off_profile_track(t_, jd, "core"))
for t_, jd in (("Associate Engineer", "Designs and implements small software features for our chipset tools in C++; code reviews."),
               ("Compiler Engineer", "LLVM compiler backend work in C++; data structures and algorithms."),
               ("OS Development Engineer", "Operating systems development in C; Linux internals and scheduling.")):
    row, why = ev(t_, jd)
    check(f"review 5: systems-software JD kept: {t_}", row is not None, why)
check("review 5: 'work with the QA engineer' in a developer JD is not a QA role",
      crawl.off_profile_track("Engineer II", "You will work with the QA engineer to automate releases; Java microservices, REST APIs.", "generic") is None)
check("review 5: 'partner with sales and pre-sales teams' in a SWE JD is not pre-sales",
      crawl.off_profile_track("Software Engineer", "Java services; partner with sales and pre-sales teams on requirements.", "core") is None)
check("review 5: the vendor's own platform engineer is kept by title", crawl.off_profile_track("Software Engineer, Workday Extend", "Java", "core", "Workday") is None)
check("review 5: a CRM developer at a non-vendor still drops", crawl.off_profile_track("Software Engineer, Workday Extend", "", "core", "Acme") == "crm_platform")

check("review 5: a certification ('as an AWS Solutions Architect') is not a pre-sales role",
      crawl.off_profile_track("Cloud Software Engineer", "Node.js services. Certification as an AWS Solutions Architect a plus.", "core") is None)
for t_ in ("Software Development Engineer - Test II, Alexa Endpoint Experience", "Software Engineer - Test", "SDE-T"):
    check(f"review 5: SDET forms excluded: {t_}", fam(t_) is None, fam(t_))
check("review 5: 'Software Engineer - Test Infrastructure' is development", fam("Software Engineer - Test Infrastructure") == "core")
row, why = ev("Apps Dev Intmd Programmer Analyst - C11 - CHENNAI", "Participate in the establishment and implementation of new or revised application systems and programs in coordination with the Technology team. " * 5)
check("review 5: core title with a long boilerplate JD is kept (Citi)", row is not None, why)

print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
