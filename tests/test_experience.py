"""Experience focus: campus hiring excluded, experience bands, sweet spot, level scores.

Usage: python3 tests/test_experience.py <path to the job-search folder>
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
import crawl  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        failures.append(name)


campus_titles = ["Software Engineer, New Grad", "Graduate Software Engineer", "Software Engineer - Early Career 2026",
                 "Campus Hire - SDE 1", "SDE 1 (Freshers)", "University Grad Software Engineer"]
junior_titles = ["Software Engineer I", "Associate Software Engineer", "SDE-1 Backend", "Software Engineer II", "Junior Backend Developer"]
check("campus / new-grad / fresher titles are excluded", not [t for t in campus_titles if crawl.title_ok(t)],
      [t for t in campus_titles if crawl.title_ok(t)])
check("junior (non-campus) titles are kept", all(crawl.title_ok(t) for t in junior_titles),
      [t for t in junior_titles if not crawl.title_ok(t)])

company = {"name": "Acme", "type": "Product", "quality": 12, "pay": "likely", "pay_note": "Levels.fyi India SE1 25 LPA"}
now = datetime.now(timezone.utc)
job = lambda title, text: crawl.Job("Acme", title, "Bengaluru, India", "u", now, text)  # noqa: E731
row, why = crawl.evaluate(job("Software Engineer I", "This is a campus hiring drive for the 2026 batch."), company, 30)
check("campus hiring in the description is excluded", row is None and "contract" in why, why)
row, _ = crawl.evaluate(job("Software Engineer (C++)", "Growing the team through the regular hiring process and occasional campus recruitments. 2+ years of C++ experience"), company, 30)
check("a duty like 'campus recruitments' doesn't make the role campus hiring", row is not None)
for text in ["B.Tech graduating in 2027 in Computer Science", "Open to the class of 2026", "2026 pass-outs only",
             "Expected graduation: June 2026", "B.Tech 2026 / M.Tech 2026"]:
    r, _ = crawl.evaluate(job("Software Engineer I", text + ". 0-1 years of experience"), company, 30)
    check(f"campus wording excluded: {text!r}", r is None)
r, _ = crawl.evaluate(job("Software Engineer I", "B.Tech in Computer Science (graduated 2025), 1+ years of experience"), company, 30)
check("a 2025 graduate with 1 year of experience is not treated as campus hiring", r is not None)
row, _ = crawl.evaluate(job("Software Engineer I", "1-2 years of experience with Java and Spring"), company, 30)
check("1-year role: band 0-1 yrs and sweet spot", row and row["exp_band"] == "0–1 yrs" and row["sweet_spot"] == "yes", row and (row["exp_band"], row["sweet_spot"]))
row, _ = crawl.evaluate(job("Software Engineer II", "2+ years of software engineering experience"), company, 30)
check("2-year role: band 2 yrs and sweet spot", row and row["exp_band"] == "2 yrs" and row["sweet_spot"] == "yes")
row, _ = crawl.evaluate(job("Software Engineer II", "3+ years of software engineering experience"), company, 30)
check("3-year role: kept, band 3 yrs, not sweet spot", row and row["exp_band"] == "3 yrs" and row["sweet_spot"] == "")
row, why = crawl.evaluate(job("Software Engineer II", "4+ years of software engineering experience"), company, 30)
check("4-year role: rejected", row is None and "4+" in why, why)
row, _ = crawl.evaluate(job("Software Engineer I", "1+ years of experience"), company | {"pay_note": "tier judgement"}, 30)
check("sweet spot needs salary evidence, not a tier judgement", row and row["pay_conf"] == "Likely" and row["sweet_spot"] == "")
for text, want in [("Years of Experience: Minimum 6-8 years", 6), ("Experience: 2+ yrs", 2), ("Experience required - 3 to 5 years", 3),
                   ("Founded 25 years ago", None), ("Experience: Java, Spring", None),
                   # a bullet after "experience" is not a label: the next bullet's 2 years belong to no requirement here
                   ("- 3+ years of non-internship professional software development experience\n- 2+ years in a fast-moving team", 3)]:
    check(f"labelled experience parsed: {text!r} -> {want}", crawl.min_experience(text)[0] == want, crawl.min_experience(text))
check("'Mgr' and trailing level-3 titles are senior; Web3 and level-2 titles are not",
      not crawl.title_ok("Mgr, Software Engineering") and not crawl.title_ok("Software Engineer Apps 3")
      and crawl.title_ok("Web3 Backend Engineer") and crawl.title_ok("SDE 2 - Data Platform"))
check("level score favours 1-2 years over 3", crawl.level_score("x", 1) > crawl.level_score("x", 3) and crawl.level_score("x", 2) > crawl.level_score("x", 3))

print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
