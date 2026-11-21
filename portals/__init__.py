"""Custom readers for companies whose careers site runs on their own portal (no shared job platform).

Each module defines `fetch(c, h)` and yields `h.Job` objects, where `c` is the companies.json entry
({"name", "ats": "portal", "portal": "<module>"}) and `h` is the crawl module (Job, get, post, title_ok,
in_india, strip_html, parse_ts, SESSION). Rules for every reader: read only the public data the careers page
itself loads, no sign-ins, nothing submitted, and no getting around bot protection. Keep each reader small and
filter to India + fitting titles before any detail calls. A failed detail call means the posting closed only on
404/410 (crawl.posting_gone). Any other failure (429, 5xx, dropped connection) keeps the posting from the list data
with meta {"detail": "unread"}: record it with crawl.detail_failed(failed, reader, e), and once every posting is
yielded call crawl.raise_if_failed(failed), which raises DetailsUnread (the listing was complete; only some
descriptions are missing). See DESIGN.md.
"""
import importlib


def fetch(c, h):
    yield from importlib.import_module(f"portals.{c['portal']}").fetch(c, h)
