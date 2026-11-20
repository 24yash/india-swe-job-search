"""Build the shortlist table from today's crawl CSVs, in the column order the brief asks for.

Usage: python3 report.py [--top 40] [--per-company 3]
Writes output/shortlist-table-<date>.md. The agent adds the top-5 picks, CV emphasis and
any manual verification notes on top of it.
"""
import argparse
import collections
import csv
import os
from pathlib import Path

OUT = Path(__file__).parent / "output"


def run_date():
    """The crawl run's date (its file stamp), so a run that crosses midnight writes one set of dated files."""
    import crawl
    return crawl.TODAY


def rows(name, stamp):
    p = OUT / f"{name}-{stamp}.csv"
    return list(csv.DictReader(open(p))) if p.exists() else []


def cell(s):
    return (s or "").replace("|", "/").replace("\n", " ").strip()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--per-company", type=int, default=3)
    args = ap.parse_args(argv)

    stamp = run_date()
    jobs, leads, rejected = rows("jobs", stamp), rows("leads-unverified-pay", stamp), rows("rejected", stamp)
    per = collections.Counter()
    picked = []
    for r in sorted(jobs, key=lambda r: -int(r["score"])):
        if per[r["company"]] < args.per_company:
            per[r["company"]] += 1
            picked.append(r)
        if len(picked) == args.top:
            break

    md = [f"# Shortlist table — {stamp}", "",
          f"{len(jobs)} roles passed every filter; showing the top {len(picked)} (max {args.per_company} per company). "
          f"{len(leads)} more pass everything except pay evidence (leads file).", "",
          "| # | Company | Company type / stage (latest round) | Role title | Location / mode | Exp asked | Pay (₹ LPA) + confidence + source | Key stack from JD | Score | Gaps vs my profile | Apply link | Posted date |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(picked, 1):
        reqs = f" ({r['reqs']} reqs)" if r.get("reqs", "1") != "1" else ""
        src = "" if r.get("source", "").startswith("company") else " (via LinkedIn)"
        md.append(f"| {i} | {cell(r['company'])} | {cell(r['type'])} | {cell(r['title'])}{reqs} | {cell(r['location'])} | "
                  f"{r['exp_asked']} | {cell(r['pay'])} | {cell(r['stack'])} | {r['score']} | {cell(r['gaps'])} | "
                  f"[apply]({r['url']}){src} | {r['posted']} |")

    md += ["", "## Leads: pass every filter except pay evidence", "",
           "| Company | Role | Location | Exp | Score | Link |", "|---|---|---|---|---|---|"]
    for r in sorted(leads, key=lambda r: -int(r["score"]))[:25]:
        md.append(f"| {cell(r['company'])} | {cell(r['title'])} | {cell(r['location'])} | {r['exp_asked']} | {r['score']} | [link]({r['url']}) |")

    reasons = collections.Counter(r["reason"].split(" (")[0] for r in rejected)
    md += ["", "## Rejected after the title filter, by reason", ""]
    md += [f"- {why}: {n}" for why, n in reasons.most_common(12)]
    md += ["", "Examples:", ""]
    shown = collections.Counter()
    for r in rejected:
        key = r["reason"].split(" (")[0]
        if shown[key] < 2:
            shown[key] += 1
            md.append(f"- {cell(r['company'])}: {cell(r['title'])} ({cell(r['location'])}) → {cell(r['reason'])}")

    out = OUT / f"shortlist-table-{stamp}.md"
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    tmp.write_text("\n".join(md) + "\n")
    tmp.replace(out)  # atomic: never a half-written table
    print(out)


if __name__ == "__main__":
    main()
