"""Custom readers for companies whose careers site runs on their own portal (no shared job platform).

Each module defines `fetch(c, h)` and yields `h.Job` objects, where `c` is the companies.json entry
({"name", "ats": "portal", "portal": "<module>"}) and `h` is the crawl module (Job, get, post, title_ok,
in_india, strip_html, parse_ts, SESSION). Rules for every reader: read only the public data the careers page
itself loads, no sign-ins, nothing submitted, and no getting around bot protection. Keep each reader small,
filter to India + fitting titles before any detail calls, and let a failed detail call skip just that job.
"""
import importlib


def fetch(c, h):
    yield from importlib.import_module(f"portals.{c['portal']}").fetch(c, h)
