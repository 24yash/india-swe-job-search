"""Kula careers pages (careers.kula.ai/<company>): server-rendered job links, and each job page carries schema.org
JobPosting data. A thin wrapper over the generic links reader. companies.json: {"ats": "portal", "portal": "kula", "slug": "slice"}"""
from portals import links


def fetch(c, h):
    s = c["slug"]
    yield from links.fetch(c | {"list_urls": [f"https://careers.kula.ai/{s}?jobs=true"], "job_link": rf"(?:https://careers\.kula\.ai)?/{s}/\d+-[a-z0-9-]+", "title_from_url": True}, h)
