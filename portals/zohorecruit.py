"""Zoho Recruit careers pages (<company>.zohorecruit.com|in/careers): the full job list is embedded in the page
as a hidden "jobs" field (title, city, country, years asked; no description).
companies.json: {"ats": "portal", "portal": "zohorecruit", "slug": "increff", "tld": "com"}"""
import html as htmllib
import json
import re


def fetch(c, h):
    base = f"https://{c['slug']}.zohorecruit.{c.get('tld', 'com')}"
    r = h.SESSION.get(f"{base}/careers", timeout=30)
    r.raise_for_status()
    m = re.search(r'value="(\[[^"]*)"\s+id="jobs"', r.text)
    for j in json.loads(htmllib.unescape(m.group(1))) if m else []:
        title = (j.get("Posting_Title") or j.get("Job_Opening_Name") or "").strip()
        loc = ", ".join(x for x in (j.get("City"), j.get("State"), j.get("Country")) if x)
        if str(j.get("Publish")).lower() != "true" or not h.title_ok(title) or "india" not in loc.lower():
            continue
        exp = j.get("Work_Experience") or ""
        text = f"{title}. {j.get('Industry') or ''}. " + (f"Requires {exp.replace('year', 'years').replace('yearss', 'years')} of experience." if exp else "")
        yield h.Job(c["name"], title, loc, f"{base}/jobs/Careers/{j['id']}", None, text,
                    meta={"employmentType": j.get("Job_Type") or ""})
