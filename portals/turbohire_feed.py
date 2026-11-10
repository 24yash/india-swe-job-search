"""TurboHire job lists that a company's own careers page serves as JSON (Khatabook: khatabook.com/hiring/recruiter/list).
TurboHire's own feed needs a session token, but these pages pass the public list through: title, locations, years asked,
description and apply link in one response, so no detail calls are needed.

companies.json: {"ats": "portal", "portal": "turbohire_feed", "feed": "https://khatabook.com/hiring/recruiter/list?category=Technology"}
The unfiltered list stops at 10 jobs, so point "feed" at a category view; a response holding fewer jobs than its
FilteredCount raises (after yielding what it has), so a truncated feed shows up as a source problem, not silent loss.
"""
import ast
import json


def _load(v, default):
    """Fields come as JSON ('[{"Address": ...}]') or Python-literal strings ("{'MinExp': 1}")."""
    if not isinstance(v, str):
        return v if v is not None else default
    for parse in (json.loads, ast.literal_eval):
        try:
            return parse(v)
        except (ValueError, SyntaxError):
            continue
    return default


def fetch(c, h):
    data = (h.get(c["feed"]) or {}).get("data") or {}
    jobs = data.get("Jobs") or []
    yield from _jobs(c, h, jobs)
    if len(jobs) < (data.get("FilteredCount") or 0):
        raise ValueError(f"feed truncated: {len(jobs)} of {data['FilteredCount']} jobs (use a category view)")


def _jobs(c, h, jobs):
    for j in jobs:
        title = j.get("JobTitle") or ""
        locs = [l.get("Address", "") for l in _load(j.get("Location"), []) if isinstance(l, dict)]
        india = [l for l in locs if h.in_india(l)]
        if not h.title_ok(title) or not india:
            continue
        exp = _load(j.get("Experience"), {}) or {}
        years = f"Experience: {exp['MinExp']}-{exp.get('MaxExp', exp['MinExp'])} years\n" if isinstance(exp, dict) and exp.get("MinExp") is not None else ""
        text = "\n".join(h.strip_html(j.get(k) or "") for k in ("JobDescription", "RolesAndResponsibilities", "Eligibility"))
        yield h.Job(c["name"], title, " / ".join(india), j.get("ApplyUrl") or c["feed"],
                    h.parse_ts((j.get("PublishedDate") or "")[:19] + "+00:00" if j.get("PublishedDate") else None), years + text)
