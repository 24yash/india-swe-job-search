"""What changed since the previous run: roles added, roles that left and why, sources that grew, shrank or failed,
and companies that started or stopped hiring. Writes output/changes-<date>.md and .json.

Called by crawl.py after every evaluation (cheap, no network); the baseline is the latest earlier day's
shortlist and leads, so rebuilding several times in one day always compares against the same previous run.
Run on its own (python3 changes.py) it only reprints the latest report.
"""
import csv
import json
import re
from pathlib import Path

from crawl import write_atomic

ROOT = Path(__file__).parent
OUT = ROOT / "output"


def dated(out, prefix, before):
    """The latest <out>/<prefix>-<date>.csv dated before `before`, as (rows, date)."""
    files = sorted(p for p in out.glob(f"{prefix}-*.csv")
                   if re.fullmatch(rf"{prefix}-\d{{4}}-\d{{2}}-\d{{2}}\.csv", p.name) and p.stem[-10:] < before)
    return (list(csv.DictReader(open(files[-1]))), files[-1].stem[-10:]) if files else ([], "")


def leaving_reason(r, raw_urls, rejected, title_rejected, failing, liveness):
    """Why a role from the previous run is not in today's shortlist or leads."""
    u = r["url"]
    if u in rejected:
        return "still listed, now filtered out: " + re.sub(r"\(.*", "", rejected[u]).strip()
    if u in title_rejected:
        return "still listed, now filtered out: title/level"
    if u in raw_urls:
        return "still listed, now skipped (duplicate of the company's own board, outside India or excluded company)"
    if r.get("source", "").startswith("LinkedIn"):
        st = liveness.get((re.search(r"/view/(\d+)", u) or [None, u])[1], {}).get("status")
        return "closed on LinkedIn (checked)" if st == "closed" else "aged out of the LinkedIn window, never confirmed open"
    if r["company"] in failing:
        return "source failed, last good read too old to carry"
    return "closed: no longer on the company's board"


def build(stamp, keep, leads, rejected_rows, title_rows, raw_counts, raw_urls, notes, first_seen, bank_hist, out=OUT):
    """Write <out>/changes-<stamp>.md/.json; also records today's per-source counts in <out>/source-counts.json."""
    prev_jobs, prev_date = dated(out, "jobs", stamp)
    prev_leads, _ = dated(out, "leads-unverified-pay", stamp)
    counts_file = out / "source-counts.json"  # {date: {source: postings in its raw file}}
    counts = json.loads(counts_file.read_text()) if counts_file.exists() else {}
    counts[stamp] = raw_counts
    write_atomic(counts_file, json.dumps(counts, indent=0))
    if not prev_date:
        return None
    liveness_file = out / "linkedin-liveness.json"
    liveness = json.loads(liveness_file.read_text()) if liveness_file.exists() else {}

    def urls(rows):  # a grouped row stands for every link in it (other reqs of the same role)
        return {u for r in rows for u in [r["url"], *(r.get("other_links") or "").split()]}

    now_short, now_leads = urls(keep), urls(leads)
    was_short, was_leads = urls(prev_jobs), urls(prev_leads)
    rejected = {r["url"]: r["reason"] for r in rejected_rows}
    title_rejected = {r["url"] for r in title_rows}
    failing = {name for name, note in notes.items() if "nothing carried" in note}  # failed with nothing to fall back on

    now_all, was_all = now_short | now_leads, was_short | was_leads
    gone = {}
    for r in prev_jobs + prev_leads:
        if not ({r["url"], *(r.get("other_links") or "").split()} & now_all):  # a sibling req still listed keeps the role
            why = leaving_reason(r, raw_urls, rejected, title_rejected, failing, liveness)
            gone.setdefault(why, []).append(r | {"was": "shortlist" if r["url"] in was_short else "lead"})
    added = [r for r in keep + leads if not ({r["url"], *(r.get("other_links") or "").split()} & was_all)]
    brand_new = [r for r in added if first_seen.get(r["url"]) == stamp]

    base_date = max((d for d in counts if d < stamp), default=None)
    base = counts.get(base_date, {})
    src = []
    for name in sorted(set(base) | set(raw_counts)):
        a, b = base.get(name), raw_counts.get(name)
        if a != b:
            src.append({"source": name, "before": a, "now": b, "delta": (b or 0) - (a or 0)})
    src.sort(key=lambda s: s["delta"])

    started, stopped = [], []
    for h in bank_hist.values():
        runs = h["runs"]
        earlier = [d for d in runs if d < stamp]
        if stamp in runs and earlier:
            then, now = runs[max(earlier)][1], runs[stamp][1]
            if now and not then:
                started.append((h["name"], now))
            elif then and not now:
                stopped.append((h["name"], then))

    summary = {
        "date": stamp, "previous_run": prev_date, "source_baseline": base_date,
        "shortlist": {"before": len(prev_jobs), "now": len(keep)}, "leads": {"before": len(prev_leads), "now": len(leads)},
        "added": len(added), "added_never_seen_before": len(brand_new), "added_seen_in_older_runs": len(added) - len(brand_new),
        "moved_lead_to_shortlist": len((was_leads - was_short) & now_short), "moved_shortlist_to_lead": len((was_short - was_leads) & now_leads),
        "left": {why: len(rs) for why, rs in sorted(gone.items(), key=lambda kv: -len(kv[1]))},
        "sources_failing": sorted(failing), "sources_suspect": sorted(n for n, note in notes.items() if note.startswith("suspect")),
        "sources_failed_but_carried": sorted(n for n, note in notes.items() if "carried from the last good read" in note),
        "companies_started_hiring": sorted(started), "companies_stopped_hiring": sorted(stopped),
        "source_changes": src,
    }
    write_atomic(out / f"changes-{stamp}.json", json.dumps(summary | {
        "left_roles": {why: [{k: r[k] for k in ("company", "title", "url", "was")} for r in rs] for why, rs in gone.items()},
        "added_roles": [{k: r[k] for k in ("company", "title", "url", "pay_conf", "score")} for r in added]}, indent=1, ensure_ascii=False))

    md = [f"# Changes {stamp} (vs run of {prev_date})", "",
          f"- Shortlist {len(prev_jobs)} → {len(keep)}; leads {len(prev_leads)} → {len(leads)} (rows; one row can hold several reqs)",
          f"- Added {len(added)} roles: {len(brand_new)} never seen before, {len(added) - len(brand_new)} back from older runs",
          f"- Moved lead → shortlist {summary['moved_lead_to_shortlist']}, shortlist → lead {summary['moved_shortlist_to_lead']}",
          f"- Left {sum(summary['left'].values())} roles:"]
    md += [f"  - {n}: {why}" for why, n in summary["left"].items()]
    md += ["", f"## Sources ({len(raw_counts)} read; baseline {base_date or 'none'})", ""]
    md += [f"- Failed, nothing to carry: {', '.join(sorted(failing)) or 'none'}",
           f"- Failed, last good postings carried: {', '.join(summary['sources_failed_but_carried']) or 'none'}",
           f"- Suspect reads (kept previous postings): {', '.join(summary['sources_suspect']) or 'none'}"]
    if src and base_date:  # first run: no baseline, every source would read "new"
        md += ["", "| Source | Before | Now | Δ |", "|---|---|---|---|"]
        md += [f"| {s['source']} | {s['before'] if s['before'] is not None else 'new'} | {s['now'] if s['now'] is not None else 'gone'} | {s['delta']:+d} |"
               for s in src if abs(s["delta"]) >= 5 or s["before"] is None or s["now"] is None]
    md += ["", f"## Companies that started hiring ({len(started)})", ""] + [f"- {n} ({k})" for n, k in sorted(started, key=lambda x: -x[1])]
    md += ["", f"## Companies with no fitting role now ({len(stopped)})", ""] + [f"- {n} (had {k})" for n, k in sorted(stopped, key=lambda x: -x[1])]
    md += ["", "## Top new roles", ""] + [f"- {r['company']} — {r['title']} ({r['pay_conf']}, score {r['score']}) {r['url']}"
                                          for r in sorted(added, key=lambda r: -int(r["score"]))[:40]]
    write_atomic(out / f"changes-{stamp}.md", "\n".join(md) + "\n")
    return summary


if __name__ == "__main__":
    import sys
    files = sorted(OUT.glob("changes-*.md"))
    print(files[-1].read_text() if files else "no changes report yet", file=sys.stdout)
