"""Coverage report: for every company in the bank, do we read its own job listings, and if not, why not?

Usage: python3 coverage.py
Reads the latest company-bank CSV, companies.json, output/raw/*.json (each source's last crawl), the latest
jobs / leads / rejected CSVs, output/careers-sites.json (discovery) and output/coverage-notes.json (findings from
probes and hand checks: blocked, nothing to read, dead, retryable…). Writes output/coverage-<date>.csv with one
row per company (status, detail, reason) and prints the summary.

Statuses:
  A  have a source: A1 fitting roles on the shortlist · A2 fitting roles, pay unverified (leads) ·
     A3 software openings at your level by title, none fit (years / pay) · A4 none at your level today ·
     A5 source failing on the last crawl · A6 not crawled yet
  B  not pursued (pay below the bar, services / staffing, your employer)
  C  checked, nothing to read (email-only, LinkedIn-only, forms, referral-only, 0 openings, no India roles)
  D  blocked (403, bot protection, token, sign-in)
  F  website: retryable (timeouts, TLS, 5xx) · dead (404, parked, no domain, wrong site)
  E  pending: E1 careers page found, no source yet · E2 searched, not readable yet · E3 site found, no careers page ·
     E4 never studied / unresolved
"""
import collections
import csv
import json
import re
from datetime import datetime
from pathlib import Path

import crawl

ROOT = Path(__file__).parent
OUT = ROOT / "output"


def latest(prefix):
    files = sorted(p for p in OUT.glob(f"{prefix}-*.csv") if re.fullmatch(rf"{prefix}-\d{{4}}-\d{{2}}-\d{{2}}\.csv", p.name))
    return list(csv.DictReader(open(files[-1]))) if files else []


def main():
    bank = latest("company-bank")
    companies = json.loads((ROOT / "companies.json").read_text())["companies"]
    direct = {crawl.norm(c["name"]): c for c in companies if c["ats"] != "linkedin"}
    notes = json.loads((OUT / "coverage-notes.json").read_text()) if (OUT / "coverage-notes.json").exists() else {}
    cache = json.loads((OUT / "careers-sites.json").read_text()) if (OUT / "careers-sites.json").exists() else {}
    tiers = {c["name"]: c for c in crawl.TIERS["known"]}
    per = lambda rows: collections.Counter(r["company"] for r in rows)  # noqa: E731
    short, leads, rej = per(latest("jobs")), per(latest("leads-unverified-pay")), per(latest("rejected"))

    def source_of(name):
        k = crawl.norm(name)
        if k in direct:
            return direct[k]
        return next((c for d, c in direct.items() if crawl.same_or_alias(k, d)), None)

    rows, seen_src = [], set()
    for b in bank:
        n = b["company"]
        if "<" in n:
            continue  # parser debris from an old LinkedIn crawl (fixed)
        src, note = source_of(n), notes.get(n, {})
        if src:
            if src["name"] in seen_src:
                continue  # another bank name for the same company (Mastercard / Mastercard Incorporated): count it once
            seen_src.add(src["name"])
            raw = crawl.raw_path(src["name"])
            d = json.loads(raw.read_text()) if raw.exists() else None
            names = {n, src["name"]}
            s, l, r = sum(short[x] for x in names), sum(leads[x] for x in names), sum(rej[x] for x in names)
            if d is None:
                st, detail = "A6", "not crawled yet"
            elif d.get("note", "").split(" — ")[0].startswith(("HTTPError", "ConnectionError", "Timeout", "JSONDecodeError", "KeyError", "TypeError")):
                st, detail = "A5", d["note"].split(" — ")[0][:120]
            elif s:
                st, detail = "A1", f"{s} shortlisted"
            elif l:
                st, detail = "A2", f"{l} leads (pay not yet evidenced)"
            elif r or (sw := sum(1 for j in d["jobs"] if crawl.title_ok(j.get("title", "")) and crawl.in_india(j.get("location") or ""))):
                st, detail = "A3", f"{r or sw} India software openings at your level by title, none fit (years / pay)"
            else:
                st, detail = "A4", f"source works; no India software openings at your level today ({len(d['jobs'])} other roles read)"
            rows.append({"company": n, "status": st, "detail": detail, "source": f"{src['ats']}:{src.get('portal') or src.get('slug') or src.get('host') or src.get('tenant', '')}"})
            continue
        t = tiers.get(n, {})
        if b["pay"] == "below" or t.get("pay") == "below":
            st, detail = "B", "pay below the bar"
        elif crawl.is_excluded_company(n):
            st, detail = "B", "services / staffing / your employer"
        elif note.get("status") == "excluded":
            st, detail = "B", note["reason"]
        elif note.get("status") == "blocked":
            st, detail = "D", note["reason"]
        elif note.get("status") == "nothing_to_read":
            st, detail = "C", note["reason"]
        elif note.get("status") == "retryable":
            st, detail = "F-retryable", note["reason"]
        elif note.get("status") == "dead":
            st, detail = "F-dead", note["reason"]
        else:
            e = cache.get(n)
            if note.get("status") == "pending" and note.get("by") == "checked by hand":
                st, detail = "E2", note["reason"]
            elif not e:
                st, detail = "E4", "never studied by discovery"
            elif e.get("careers"):
                st, detail = "E1", f"careers page {e['careers'][:80]}"
            elif e.get("site"):
                st, detail = "E3", f"site {e['site'][:80]}, no careers page found"
            else:
                st, detail = "E4", note.get("reason") or "website not found yet"
        rows.append({"company": n, "status": st, "detail": detail, "source": ""})

    date = datetime.now().strftime("%Y-%m-%d")
    with open(OUT / f"coverage-{date}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["company", "status", "detail", "source"])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["status"], r["company"].lower())))
    c = collections.Counter(r["status"] for r in rows)
    labels = {"A1": "fitting roles on the shortlist", "A2": "fitting roles, pay unverified (leads)", "A3": "openings at your level, none fit (years/pay)",
              "A4": "no openings at your level today", "A5": "source failing on last crawl", "A6": "not crawled yet",
              "B": "not pursued (pay below / excluded)", "C": "checked, nothing to read", "D": "blocked",
              "F-retryable": "website unreachable, retryable", "F-dead": "website dead / wrong / no domain",
              "E1": "careers page found, no source yet", "E2": "searched by hand, not readable yet",
              "E3": "site found, no careers page", "E4": "never studied / website not found yet"}
    print(f"{len(rows)} companies (output/coverage-{date}.csv)")
    for group in ("A", "B", "C", "D", "F", "E"):
        keys = sorted(k for k in c if k.startswith(group))
        print(f"  {group}: {sum(c[k] for k in keys)}")
        for k in keys:
            if len(keys) > 1 or k != group:
                print(f"     {k:12} {c[k]:4}  {labels.get(k, '')}")


if __name__ == "__main__":
    main()
