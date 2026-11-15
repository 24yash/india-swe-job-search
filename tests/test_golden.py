"""Golden set: real roles labelled keep / drop, run through the full evaluate() with their real job descriptions.

Usage: python3 tests/test_golden.py <path to job-search folder>
Labels live in tests/fixtures/golden_roles.json (company, title, expect, why, url). Descriptions come from the latest
crawl in output/raw/, which isn't committed: a label whose posting isn't in the local crawl is reported as SKIP
(postings close), and the suite fails if fewer than half the labels could be checked.

Why it exists: on 15 Nov 2026 a one-word rule change silently dropped three real development roles; only a manual
audit found it. Every regression found by an audit or review gets a label here.
"""
import argparse
import json
import sys
from pathlib import Path

SRC = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SRC))
import crawl  # noqa: E402

labels = json.loads((SRC / "tests" / "fixtures" / "golden_roles.json").read_text())
jobs = {}
for f in (SRC / "output" / "raw").glob("*.json"):
    for j in json.loads(f.read_text())["jobs"]:
        jobs[j["url"]] = j
        jobs.setdefault((j["company"], j["title"].strip()), j)

ctx = crawl.build_context(argparse.Namespace(max_age=21))
failures, checked, skipped = [], 0, []
for lab in labels:
    j = jobs.get(lab["url"]) or jobs.get((lab["company"], lab["title"]))
    if not j:
        skipped.append(f"{lab['company']} – {lab['title']}")
        continue
    job = crawl.Job(**j | {"posted": crawl.parse_ts(j["posted"])})
    co = ctx["lookup"].get(crawl.norm(j["company"])) or {"name": j["company"], "type": "", "quality": 8, "pay": "unclear", "pay_note": ""}
    co = co | {"pay": "likely" if co.get("pay") == "below" else co.get("pay", "unclear")}  # this suite checks role fit, not pay
    family = crawl.title_family(j["title"])
    if family is None:
        kept, why = False, "title/level"
    else:
        row, why = crawl.evaluate(job, co, 10_000)  # ignore posting age: labels outlive the freshness window
        kept = row is not None or (why and "yrs asked" in why)  # the years filter is separate from role fit
    ok = kept == (lab["expect"] == "keep")
    checked += 1
    print(("PASS " if ok else "FAIL ") + f"{lab['expect']}: {lab['company']} – {lab['title']}" + ("" if ok else f"  [{why}; {lab['why']}]"))
    if not ok:
        failures.append(f"{lab['company']} – {lab['title']}")

for s in skipped:
    print("SKIP (not in the local crawl) " + s)
if checked < len(labels) / 2:
    failures.append(f"only {checked} of {len(labels)} labels found in output/raw: run a crawl first")
print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}  ({checked} checked, {len(skipped)} skipped)")
sys.exit(1 if failures else 0)
