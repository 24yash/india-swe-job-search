"""Build dashboard.html: one static page with the latest crawl's roles, leads and company bank embedded.

Usage: python3 build_dashboard.py
Open dashboard.html in a browser. Status and comments are stored in the browser (localStorage),
keyed by job link, so rebuilding after a new crawl keeps them. Use Export/Import in the page to back them up.
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "output"


def latest(prefix):
    files = sorted(p for p in OUT.glob(f"{prefix}-*.csv") if re.fullmatch(rf"{prefix}-\d{{4}}-\d{{2}}-\d{{2}}\.csv", p.name))
    return (list(csv.DictReader(open(files[-1]))), files[-1].stem[-10:]) if files else ([], "")


def city(loc):
    l = loc.lower()
    for name, keys in (("Remote", ("remote",)), ("Bengaluru", ("bengaluru", "bangalore", "karnataka")),
                       ("Hyderabad", ("hyderabad", "telangana")), ("Pune", ("pune",)),
                       ("NCR", ("gurugram", "gurgaon", "noida", "delhi", "haryana")), ("Chennai", ("chennai", "tamil nadu")),
                       ("Mumbai", ("mumbai", "maharashtra"))):
        if any(k in l for k in keys):
            return name
    return "Other India"


def job(r, kind):
    return {"kind": kind, "url": r["url"], "company": r["company"], "type": r["type"], "title": r["title"],
            "location": r["location"], "city": city(r["location"]), "exp": r["exp_asked"], "expSnippet": r["exp_snippet"],
            "pay": r["pay"], "payConf": r["pay_conf"], "stack": r["stack"], "gaps": r["gaps"], "score": int(r["score"]),
            "posted": r["posted"], "source": r.get("source", ""), "reqs": int(r.get("reqs") or 1),
            "otherLinks": (r.get("other_links") or "").split(), "breakdown": r.get("breakdown", ""), "isNew": r.get("new") == "NEW",
            "expBand": r.get("exp_band", ""), "sweet": r.get("sweet_spot") == "yes"}


def main():
    jobs, date = latest("jobs")
    leads, _ = latest("leads-unverified-pay")
    bank, _ = latest("company-bank")
    current = [job(r, "shortlist") for r in jobs] + [job(r, "lead") for r in leads]

    # Every role ever shown stays in the archive, so a role you marked Applied is still on the
    # dashboard after it closes or ages out of the crawl window (shown as "no longer listed").
    archive_file = OUT / "job-archive.json"
    archive = json.loads(archive_file.read_text()) if archive_file.exists() else {}
    for j in archive.values():
        j["inLatest"] = False
    for j in current:
        j |= {"inLatest": True, "firstSeen": archive.get(j["url"], {}).get("firstSeen", date), "lastSeen": date}
        archive[j["url"]] = j
    archive_file.write_text(json.dumps(archive, ensure_ascii=False))

    data = {"generated": date, "jobs": list(archive.values()), "companies": bank}
    page = (ROOT / "dashboard_template.html").read_text().replace(
        "/*__DATA__*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    (ROOT / "dashboard.html").write_text(page)
    print(f"dashboard.html: {len(jobs)} shortlist, {len(leads)} leads, {len(archive) - len(current)} archived, "
          f"{len(bank)} companies (crawl {date})")


if __name__ == "__main__":
    main()
