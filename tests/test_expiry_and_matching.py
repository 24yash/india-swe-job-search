"""Tests for this round: exclusion matching, LinkedIn expiry, board-link recognition, importer rule.

Usage: python3 test_round2.py <path to job-search folder>
"""
import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

SRC = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SRC))
import crawl  # noqa: E402
import discover_ats  # noqa: E402
import import_lists  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# ---------------------------------------------------------------- exclusion matching
real = ["Honeywell", "Disney+ Hotstar", "Palo Alto Networks", "Anthropic", "Northern Trust", "Commonwealth Bank of Australia",
        "Moneyview", "HighRadius", "Siemens Healthineers", "Commvault", "INDmoney", "GreyOrange", "Trust Wallet", "Keyrus"]
services = ["EY GDS", "Tata Consultancy Services", "UST Global", "L&T Technology Services", "Accenture Solutions Pvt Ltd", "TCS",
            "IBM India", "CGI", "Career Crafterz", "Weekday (YC W21)"]
staffing = ["ABC Staffing Services", "XYZ Recruitment Pvt Ltd", "Prime Placement Co"]
wrong = [n for n in real if crawl.is_excluded_company(n)]
check("real companies are not excluded (EY/UST/L&T/HR no longer match inside names)", not wrong, wrong)
missed = [n for n in services + staffing if not crawl.is_excluded_company(n)]
check("services firms, staffing agencies and the user's employer are excluded", not missed, missed)
check("importer uses the crawler's exclusion rule", import_lists.is_excluded_company is crawl.is_excluded_company)

# ---------------------------------------------------------------- board links
cases = {
    "https://jobs.lever.co/cred/abc": [("lever", "cred")],
    "https://boards.greenhouse.io/embed/job_board?for=razorpaysoftwareprivatelimited": [("greenhouse", "razorpaysoftwareprivatelimited")],
    "https://job-boards.greenhouse.io/groww/jobs/1": [("greenhouse", "groww")],
    "https://flipkart.turbohire.co/careerpage/x": [("turbohire", "flipkart")],
    "https://zepto.darwinbox.in/ms/candidate/careers": [("darwinbox", "zepto")],
    "https://jobs.ashbyhq.com/sarvam": [("ashby", "sarvam")],
    "https://walmart.wd5.myworkdayjobs.com/en-US/WalmartExternal/job/x": [("workday", ("walmart", "wd5", "WalmartExternal"))],
    "https://careers.smartrecruiters.com/Swiggy": [("smartrecruiters", "swiggy")],
    "https://jobs.lever.co/jobs": [],
}
bad = {u: discover_ats.boards_in(u) for u, exp in cases.items() if discover_ats.boards_in(u) != exp}
check("board links recognised from URLs (and generic paths ignored)", not bad, bad)

# ---------------------------------------------------------------- LinkedIn expiry (keep open, drop closed)
tmp = Path(tempfile.mkdtemp())
crawl.OUT, crawl.RAW = tmp, tmp / "raw"
crawl.LIVENESS_FILE = tmp / "linkedin-liveness.json"
crawl.PROFILE["linkedin"]["liveness_checks_per_run"] = 3
crawl.PROFILE["linkedin"]["liveness_recheck_days"] = 7
now = crawl.NOW
mk = lambda jid, days: crawl.Job("Acme", "Software Engineer", "Bengaluru, India", f"https://www.linkedin.com/jobs/view/{jid}/",  # noqa: E731
                                 now - timedelta(days=days), "2+ years")
earlier = [mk(1, 40), mk(2, 50), mk(3, 60), mk(4, 70), mk(5, 5), mk(6, 10)]
# 1-3: old, will be checked (budget 3); 4: old, beyond budget and never checked; 5: young unchecked; 6: young, checked closed before
crawl.save_raw("LinkedIn search", earlier)
crawl.LIVENESS_FILE.write_text(json.dumps({"6": {"status": "closed", "checked": crawl.TODAY},
                                           "999": {"status": "open", "checked": crawl.TODAY}}))  # another pass's entry
answers = {"1": "open", "2": "closed", "3": "open"}
asked = []
crawl.li_status = lambda jid: asked.append(jid) or answers.get(jid)
fresh = [mk(7, 1)]
kept, st = crawl.keep_open_earlier("LinkedIn search", fresh, 30)
closed = st["closed"]
ids = sorted(crawl.li_job_id(j.url) for j in kept)
check("old posting confirmed open is kept (older active jobs survive)", "1" in ids and "3" in ids, ids)
check("posting confirmed closed is dropped", "2" not in ids and "6" not in ids, ids)
check("old posting not reached by the check budget is kept until a check answers", "4" in ids and st["unchecked"] == 1, (ids, st))
labels = {crawl.li_job_id(j.url): j.meta.get("liveness", "") for j in kept}
check("kept postings say how their liveness is known", labels["1"].startswith("open on LinkedIn") and labels["4"].startswith("past the search window") and labels["5"].startswith("seen in an earlier"), labels)
check("young unchecked posting is kept", "5" in ids, ids)
check("re-seen postings are not re-checked", "7" not in asked, asked)
check("checks old postings first and stays within budget", sorted(asked) == ["1", "2", "3"], asked)
check("young and recently checked postings are not re-checked", not {"5", "6"} & set(asked), asked)
check("closed count reported", closed == 2, closed)
state = json.loads(crawl.LIVENESS_FILE.read_text())
check("state merge keeps the other pass's entries", "999" in state and state["2"]["status"] == "closed", sorted(state))
# rate limit: stop checking, keep previous state
crawl.save_raw("LinkedIn search", [mk(8, 45), mk(9, 46), mk(10, 120)])
crawl.li_status = lambda jid: None
kept2, st2 = crawl.keep_open_earlier("LinkedIn search", [], 30)
ids2 = sorted(crawl.li_job_id(j.url) for j in kept2)
check("rate-limited: unchecked old postings are kept, not lost", ids2 == ["8", "9"], ids2)
check("rate-limited: postings far past the window and never confirmed open age out", st2["aged_out"] == 1 and st2["checked_now"] == 0, st2)

# ---------------------------------------------------------------- company boards: failed and suspect reads
board = lambda n, prefix="b": [crawl.Job("Acme", "Software Engineer", "Bengaluru, India", f"https://acme/{prefix}{i}", now, "") for i in range(n)]  # noqa: E731
crawl.save_board("Acme", board(20), None)
meta = json.loads(crawl.raw_path("Acme").read_text())
check("clean read records last_ok and its size", meta["last_ok"] == crawl.TODAY and meta["fresh_count"] == 20 and not meta["note"], meta.get("note"))
note = crawl.save_board("Acme", board(2, "c"), "HTTPError: 500")
got, meta = crawl.load_raw("Acme")
check("failed read carries the last good postings", len(got) == 22 and "carried" in note, (len(got), note))
check("carried postings are labelled", sum("carried" in j.meta.get("liveness", "") for j in got) == 20)
note = crawl.save_board("Acme", [], None)
got, meta = crawl.load_raw("Acme")
check("an empty read without an error after a big board is suspect: previous kept", len(got) == 22 and note.startswith("suspect") and meta["suspect_since"] == crawl.TODAY, (len(got), note))
d = json.loads(crawl.raw_path("Acme").read_text()); d["suspect_since"] = crawl.days_ago(8); crawl.raw_path("Acme").write_text(json.dumps(d))
note = crawl.save_board("Acme", board(1, "d"), None)
got, meta = crawl.load_raw("Acme")
check("a drop that lasts past the confirm window is accepted", len(got) == 1 and not note and meta["fresh_count"] == 1, (len(got), note))
crawl.save_board("Small", board(2), None)
crawl.save_board("Small", [], None)
check("a 1-2 posting board going empty is taken at its word", crawl.load_raw("Small")[0] == [])
crawl.save_raw("Old", board(5), last_ok=crawl.days_ago(30), fresh_count=5)
note = crawl.save_board("Old", [], "Timeout")
check("a failed read older than the carry window carries nothing", crawl.load_raw("Old")[0] == [] and "nothing carried" in note, note)

# review findings: a failed read keeps the suspect clock; a small board going to zero is suspect; one bad page doesn't stop checks
crawl.save_raw("Flaky", board(3), last_ok=crawl.TODAY, fresh_count=50, suspect_since=crawl.days_ago(3))
crawl.save_board("Flaky", [], "HTTPError: 503")
check("a failed read keeps suspect_since", json.loads(crawl.raw_path("Flaky").read_text()).get("suspect_since") == crawl.days_ago(3))
crawl.save_board("Tiny", board(4), None)
note = crawl.save_board("Tiny", [], None)
check("a board of 3+ that suddenly reads empty is suspect", note.startswith("suspect") and len(crawl.load_raw("Tiny")[0]) == 4, note)
crawl.save_raw("LinkedIn search", [mk(11, 40), mk(12, 41)])
crawl.LIVENESS_FILE.write_text("{}")
crawl.li_status = lambda jid: "error" if jid == "11" else "closed"
kept3, st3 = crawl.keep_open_earlier("LinkedIn search", [], 30)
check("one failing posting page doesn't block the other checks", st3["closed"] == 1 and [crawl.li_job_id(j.url) for j in kept3] == ["11"], st3)
crawl.save_raw("LinkedIn search", [mk(13, 200)])
crawl.LIVENESS_FILE.write_text(json.dumps({"13": {"status": "open", "checked": crawl.days_ago(120)}}))
crawl.li_status = lambda jid: None
kept4, st4 = crawl.keep_open_earlier("LinkedIn search", [], 30)
check("a months-old 'open' answer on an old posting doesn't keep it forever", kept4 == [] and st4["aged_out"] == 1, st4)

# detail-only failures: the listing was complete, so nothing absent is carried and the read counts as good
J = crawl.Job
crawl.save_raw("Wd", [J("Wd", "Software Engineer", "Bengaluru, India", "https://wd1.myworkdaysite.com/recruiting/wd/ext/job/Blr/SE_R1", now, "full JD"),
                      J("Wd", "Software Engineer", "Bengaluru, India", "https://wd/ext/job/Blr/SE_R2", now, "closed one")],
               last_ok=crawl.days_ago(2), fresh_count=2)
stub = J("Wd", "Software Engineer", "Bengaluru, India", "https://wd.wd1.myworkdayjobs.com/ext/job/Blr/SE_R1", now, "", meta={"detail": "unread"})
crawl.save_board("Wd", [stub], None, "DetailsUnread: Workday detail call failed (429)")
got, meta = crawl.load_raw("Wd")
check("details unread: stub replaced by the last full read even when the host differs", [j.text for j in got] == ["full JD"], [j.url for j in got])
check("details unread: a posting gone from a complete listing is not carried", len(got) == 1)
check("details unread: the read still counts as good", meta["last_ok"] == crawl.TODAY and meta["note"].startswith("DetailsUnread"), meta)

# unread descriptions (detail call failed): development titles keep the benefit of the doubt, generic titles wait for a read
co = {"name": "Acme", "type": "Product", "quality": 12, "pay": "likely", "pay_note": "Levels.fyi India SE1 25 LPA"}
unread = lambda t: crawl.Job("Acme", t, "Bengaluru, India", "https://acme/" + t, now, "", meta={"detail": "unread"})  # noqa: E731
row, why = crawl.evaluate(unread("Software Engineer II"), co, 30)
check("unread description: a core title is kept and labelled", row is not None and "description not read" in row["listed_open"], why)
row, why = crawl.evaluate(unread("Quality Conformance Engineer-Airframe"), co, 30)
check("unread description: a generic title is not kept on the title alone", row is None, row and row["title"])

print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
