"""Golden set: real postings labelled keep / drop, run through the full evaluate() with their real job descriptions.

Usage: python3 tests/test_golden.py <path to job-search folder>

- Labels: tests/fixtures/golden_roles.json (company, title, expect, why, url; drops also carry `reason`, a substring of the
  expected rejection reason, so a role dropped for the wrong reason, e.g. pay, can't hide a regression).
- Descriptions: tests/fixtures/golden_texts.json (a snapshot taken when the label was made, so labels don't decay as
  postings close), else the latest crawl in output/raw/. The snapshot stays in the personal working copy: full job
  descriptions aren't republished. Without either, the suite prints SKIP and passes (a fresh public clone).

Why it exists: on 15 Nov 2026 one-word rule changes silently dropped real development roles three times; only manual
audits and reviews found them. Every regression found by an audit or a review gets a label here.
"""
import argparse
import json
import sys
from pathlib import Path

SRC = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SRC))
import crawl  # noqa: E402

FIX = SRC / "tests" / "fixtures"
labels = json.loads((FIX / "golden_roles.json").read_text())
texts = json.loads((FIX / "golden_texts.json").read_text()) if (FIX / "golden_texts.json").exists() else {}
raw = {}
for f in (SRC / "output" / "raw").glob("*.json"):
    for j in json.loads(f.read_text())["jobs"]:
        raw[j["url"]] = j

if not texts and not raw:
    print("SKIP: no job descriptions available (no tests/fixtures/golden_texts.json and no output/raw/). Run a crawl first.")
    sys.exit(0)

ctx = crawl.build_context(argparse.Namespace(max_age=21))
failures, checked, skipped = [], 0, []
for lab in labels:
    j = texts.get(lab["url"]) or raw.get(lab["url"])  # by URL only: two postings can share a company and title
    if not j:
        skipped.append(f"{lab['company']} – {lab['title']}")
        continue
    job = crawl.Job(j["company"], j["title"], j.get("location") or "Bengaluru, India", lab["url"], crawl.parse_ts(j.get("posted")), j.get("text") or "")
    co = ctx["lookup"].get(crawl.norm(j["company"])) or {"name": j["company"], "type": "", "quality": 8, "pay": "unclear", "pay_note": ""}
    co = co | {"pay": "likely", "below_title": None}  # this suite checks role fit, not pay
    row, why = crawl.evaluate(job, co, 100_000)  # ignore posting age: labels outlive the freshness window
    kept = row is not None or bool(why and "yrs asked" in why)  # the years filter is a separate concern
    ok = kept == (lab["expect"] == "keep")
    if ok and lab["expect"] == "drop" and lab.get("reason"):
        ok = lab["reason"] in (why or "")
    checked += 1
    print(("PASS " if ok else "FAIL ") + f"{lab['expect']}: {lab['company']} – {lab['title']}"
          + ("" if ok else f"  [got: {why or 'kept'}; expected: {lab.get('reason', lab['expect'])}; {lab['why']}]"))
    if not ok:
        failures.append(f"{lab['company']} – {lab['title']}")

for s in skipped:
    print("SKIP (no description) " + s)
if checked < len(labels) / 2:
    failures.append(f"only {checked} of {len(labels)} labels have a description: refresh tests/fixtures/golden_texts.json")
print(f"\n{'ALL PASSED' if not failures else str(len(failures)) + ' FAILED: ' + ', '.join(failures)}  ({checked} checked, {len(skipped)} skipped)")
sys.exit(1 if failures else 0)
