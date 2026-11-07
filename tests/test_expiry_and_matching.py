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
kept, closed = crawl.keep_open_earlier("LinkedIn search", fresh, 30)
ids = sorted(crawl.li_job_id(j.url) for j in kept)
check("old posting confirmed open is kept (older active jobs survive)", "1" in ids and "3" in ids, ids)
check("posting confirmed closed is dropped", "2" not in ids and "6" not in ids, ids)
check("old posting never confirmed open is dropped", "4" not in ids, ids)
check("young unchecked posting is kept", "5" in ids, ids)
check("re-seen postings are not re-checked", "7" not in asked, asked)
check("checks old postings first and stays within budget", sorted(asked) == ["1", "2", "3"], asked)
check("young and recently checked postings are not re-checked", not {"5", "6"} & set(asked), asked)
check("closed count reported", closed == 2, closed)
state = json.loads(crawl.LIVENESS_FILE.read_text())
check("state merge keeps the other pass's entries", "999" in state and state["2"]["status"] == "closed", sorted(state))
# rate limit: stop checking, keep previous state
crawl.save_raw("LinkedIn search", [mk(8, 45), mk(9, 46)])
crawl.li_status = lambda jid: None
kept2, _ = crawl.keep_open_earlier("LinkedIn search", [], 30)
check("rate-limited: unknown old postings are dropped, nothing crashes", kept2 == [], [j.url for j in kept2])

print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
