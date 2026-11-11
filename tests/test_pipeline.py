"""Tests for the local crawler changes. Runs against fixtures in a temp folder; never touches real data.

Usage: python3 test_changes.py <path to job-search folder>
"""
import csv
import json
import shutil
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

SRC = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SRC))
import requests  # noqa: E402

import build_dashboard  # noqa: E402
import crawl  # noqa: E402
import discover_ats  # noqa: E402
import report  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# ---------------------------------------------------------------- title_key / on_own_board
check("title_key normalises punctuation/case", crawl.title_key("Software Engineer - II (Backend)") == "software engineer ii backend")
boards = {"amazon": {"software development engineer ii"}, "arc": {"software engineer"}, "acme": {"backend engineer"}}
check("exact company + title -> duplicate", crawl.on_own_board(boards, "Amazon", title="Software Development Engineer II"))
check("alias by prefix -> duplicate", crawl.on_own_board(boards, "Amazon Web Services (AWS)", title="Software Development Engineer II"))
check("same company, different title -> kept", not crawl.on_own_board(boards, "Amazon", title="Software Development Engineer I"))
check("short board names never prefix-match (Arc vs Arcesium)", not crawl.on_own_board(boards, "Arcesium", title="Software Engineer"))
check("short prefix doesn't merge different companies (CRED vs Credgenics)", not crawl.same_or_alias(crawl.norm("Credgenics"), crawl.norm("CRED")))
check("real aliases still merge (AWS -> Amazon, DeepMind -> Google)", crawl.same_or_alias(crawl.norm("Amazon Web Services (AWS)"), "amazon") and crawl.same_or_alias(crawl.norm("Google DeepMind"), "google"))
check("any of several names may match", crawl.on_own_board(boards, "Unknown Co", "ACME", title="Backend Engineer"))

# ---------------------------------------------------------------- greenhouse: list then detail, failures skipped
gh_list = {"jobs": [
    {"id": 1, "title": "Software Engineer II", "location": {"name": "Bengaluru, India"}, "absolute_url": "u1", "first_published": "2026-11-01T00:00:00Z"},
    {"id": 2, "title": "Senior Software Engineer", "location": {"name": "Bengaluru, India"}, "absolute_url": "u2"},
    {"id": 3, "title": "Software Engineer", "location": {"name": "San Francisco"}, "absolute_url": "u3"},
    {"id": 4, "title": "Backend Engineer", "location": {"name": "Pune, India"}, "absolute_url": "u4"},
    {"id": 5, "title": "Software Engineer", "location": {"name": "Hyderabad"}, "absolute_url": "u5"},
]}
calls = []


def fake_get(url, **kw):
    calls.append(url)
    if url.endswith("/jobs"):
        return gh_list
    if url.endswith("/4"):
        raise requests.HTTPError("404 closed")
    return {"content": "&lt;p&gt;2+ years of experience in Java&lt;/p&gt;"}


orig_get = crawl.get
crawl.get = fake_get
try:
    jobs = list(crawl.greenhouse({"name": "Acme", "slug": "acme"}))
except Exception as e:  # noqa: BLE001
    jobs = []
    check("greenhouse does not crash on a failed detail", False, repr(e))
crawl.get = orig_get
check("greenhouse keeps only India + fitting titles", [j.url for j in jobs] == ["u1", "u5"], [j.url for j in jobs])
check("greenhouse skips a failed detail without aborting", "u5" in [j.url for j in jobs])
check("greenhouse fetches descriptions only for matches", len([c for c in calls if not c.endswith("/jobs")]) == 3, calls)
check("greenhouse description parsed", bool(jobs) and "2+ years" in jobs[0].text)
check("greenhouse posted date from list", bool(jobs) and jobs[0].posted and jobs[0].posted.year == 2026)

# ---------------------------------------------------------------- workday: parallel details, order kept, failures skipped
TEAMS = "ABCDEFGH"
posts = [{"title": f"Software Engineer - Team {TEAMS[i]}", "externalPath": f"/job/{i}", "locationsText": "Bangalore, India", "postedOn": "Posted 2 Days Ago"} for i in range(8)]
posts.append({"title": "Software Engineer X", "externalPath": "/job/x", "locationsText": "Austin, TX"})


def wd_post(url, body, **kw):
    return {"jobPostings": posts if body["offset"] == 0 else [], "total": len(posts)}


def wd_get(url, **kw):
    if url.endswith("/job/3"):
        raise requests.ConnectionError("reset")
    i = url.rsplit("/", 1)[1]
    return {"jobPostingInfo": {"title": f"Software Engineer - Team {TEAMS[int(i)]}", "location": "Bangalore", "jobDescription": "1+ years"}}


orig_post = crawl.post
crawl.post, crawl.get = wd_post, wd_get
check("workday fixture titles all pass the title filter", all(crawl.title_ok(p["title"]) for p in posts[:8]))
try:
    wjobs = list(crawl.workday({"name": "Acme", "tenant": "acme", "wd": "wd1", "site": "ext"}))
except Exception as e:  # noqa: BLE001
    wjobs = []
    check("workday does not crash on a failed detail", False, repr(e))
crawl.post, crawl.get = orig_post, orig_get
titles = [j.title for j in wjobs]
check("workday: failed detail skipped, rest kept", len(wjobs) == 7 and "Software Engineer - Team D" not in titles, titles)
check("workday: foreign single-location roles not fetched", "Software Engineer X" not in titles)
check("workday: order preserved", titles == [f"Software Engineer - Team {TEAMS[i]}" for i in range(8) if i != 3], titles)

# ---------------------------------------------------------------- discover_ats helpers
check("same_company: empty after suffix strip -> needs review", discover_ats.same_company("Labs Inc", "Labs") is None)
check("same_company: true match", discover_ats.same_company("Squarepoint Capital", "Squarepoint Capital") is True)
check("same_company: different company rejected", discover_ats.same_company("Plum", "Applied Intuition") is False)
check("same_company: no board name -> needs review", discover_ats.same_company("Ema", None) is None)
check("slug variants", "urbancompany" in discover_ats.slug_variants("Urban Company") and "urban-company" in discover_ats.slug_variants("Urban Company"))
check("only platforms crawl.py can read are marked addable", discover_ats.CRAWLED <= set(crawl.FETCHERS) and "workable" not in discover_ats.CRAWLED)

# ---------------------------------------------------------------- concurrency: readers vs atomic table swaps
holder = {"titles": {f"co{i}": {"software engineer"} for i in range(300)}}
errors = []
stop = threading.Event()


def reader():
    try:
        while not stop.is_set():
            crawl.on_own_board(holder["titles"], "co150", title="Software Engineer")
    except Exception as e:  # noqa: BLE001
        errors.append(repr(e))


def writer():
    for i in range(2000):
        holder["titles"] = {f"co{k}": {"software engineer"} for k in range(300)}  # what evaluate_all does
    stop.set()


threads = [threading.Thread(target=reader) for _ in range(3)] + [threading.Thread(target=writer)]
[t.start() for t in threads]
[t.join() for t in threads]
check("no race between LinkedIn readers and table swaps", not errors, errors[:1])

# ---------------------------------------------------------------- evaluate_all: dedupe with fresh board titles (isolated folder)
tmp = Path(tempfile.mkdtemp())
(tmp / "output").mkdir()
shutil.copy(SRC / "dashboard_template.html", tmp / "dashboard_template.html")
crawl.OUT, crawl.RAW = tmp / "output", tmp / "output" / "raw"
report.OUT = tmp / "output"
build_dashboard.ROOT, build_dashboard.OUT = tmp, tmp / "output"
crawl.TIERS = {"known": [{"name": "Acme", "type": "Product", "quality": 12, "pay": "likely", "pay_note": "Levels.fyi India SE1 25 LPA"},
                         {"name": "Amazon", "type": "Big tech", "quality": 14, "pay": "likely", "pay_note": "Levels.fyi India L4 29.7 LPA"}],
               "services_and_staffing": ["Staffing Co"]}
now = datetime.now(timezone.utc)
mk = lambda co, t, u: crawl.Job(co, t, "Bengaluru, India", u, now, "2+ years of experience in Java, Spring, Kubernetes")  # noqa: E731
companies = [{"name": "Acme", "ats": "greenhouse", "slug": "acme", "type": "Product", "quality": 12, "pay": "likely",
              "pay_note": "Levels.fyi India SE1 25 LPA"},
             {"name": "Amazon", "ats": "amazon", "type": "Big tech", "quality": 14, "pay": "likely", "pay_note": "Levels.fyi India L4 29.7 LPA"},
             {"name": "LinkedIn search", "ats": "linkedin", "type": "aggregator", "quality": 0, "pay": "unclear", "pay_note": ""}]
crawl.save_raw("Acme", [mk("Acme", "Software Engineer II", "acme-board-1")])
crawl.save_raw("Amazon", [mk("Amazon", "Software Development Engineer II", "amzn-1")])
# stale context: built before the boards had these titles (the bug being fixed)
ctx = {"companies": companies, "direct": {"acme", "amazon"}, "boards": {"titles": {}}, "sweep": [],
       "lookup": {crawl.norm(c["name"]): c for c in crawl.TIERS["known"] + companies}, "sweep_state": {}, "max_age": 30}
crawl.save_raw("LinkedIn search", [
    mk("Acme", "Software Engineer II", "li-dup"),                                   # on Acme's board -> drop
    mk("Acme", "Backend Engineer", "li-keep"),                                      # not on board -> keep
    mk("Amazon Web Services (AWS)", "Software Development Engineer II", "li-alias"),  # alias dup -> drop
    mk("Staffing Co", "Software Engineer II", "li-staff"),                          # excluded firm -> drop
])
build_dashboard.main = lambda: None  # page building is covered in the end-to-end test
crawl.evaluate_all(ctx, quiet=True)
rows = list(csv.DictReader(open(tmp / "output" / f"jobs-{crawl.TODAY}.csv"))) + \
       list(csv.DictReader(open(tmp / "output" / f"leads-unverified-pay-{crawl.TODAY}.csv")))
urls = {r["url"] for r in rows} | {u for r in rows for u in (r.get("other_links") or "").split()}  # grouped duplicates too
check("evaluate: stale context refreshed from today's boards", "li-dup" not in urls, sorted(urls))
check("evaluate: LinkedIn role missing from the board is kept", "li-keep" in urls, sorted(urls))
check("evaluate: alias duplicate dropped", "li-alias" not in urls, sorted(urls))
check("evaluate: staffing firm dropped", "li-staff" not in urls)
check("evaluate: board roles present", {"acme-board-1", "amzn-1"} <= urls, sorted(urls))
check("evaluate: shared holder updated for LinkedIn readers", "acme" in ctx["boards"]["titles"])

# ---------------------------------------------------------------- LinkedIn sweep: unreadable boards every run
import argparse  # noqa: E402
(tmp / "companies.json").write_text(json.dumps({"companies": [{"name": "LinkedIn sweep", "ats": "linkedin", "mode": "sweep"}]}))
real_root, real_profile = crawl.ROOT, crawl.PROFILE
crawl.ROOT = tmp
crawl.PROFILE = json.loads(json.dumps(real_profile))
crawl.PROFILE["linkedin"]["company_sweep"]["companies_per_run"] = 2
crawl.TIERS = {"known": [{"name": f"Co{i}", "quality": 14, "pay": "likely"} for i in range(5)] +
                        [{"name": "Walled", "quality": 10, "pay": "likely", "linkedin_every_run": True},
                         {"name": "Lowq", "quality": 5, "pay": "unclear", "linkedin_every_run": True},
                         {"name": "Payslow", "quality": 12, "pay": "below", "linkedin_every_run": True}], "services_and_staffing": []}
(tmp / "output" / "sweep-state.json").write_text(json.dumps({"walled": "2026-11-10"}))  # searched recently: would rotate to the back
sw = crawl.build_context(argparse.Namespace(max_age=30))["sweep"]
check("sweep: companies whose board no script can read are searched every run, on top of the rotating budget",
      set(sw[:2]) == {"Walled", "Lowq"} and len(sw) == 4, sw)
check("sweep: the every-run flag works below the quality bar, but not for a company that pays below the bar",
      "Lowq" in sw and "Payslow" not in sw, sw)
crawl.ROOT, crawl.PROFILE = real_root, real_profile
shutil.rmtree(tmp)

print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
