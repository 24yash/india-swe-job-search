"""RippleHire careers sites (<slug>.ripplehire.com: HDFC Bank, Axis Bank, FreeCharge, Cimpress). The careers link each
company publishes carries a career-site token (?token=…, or a /candidate/careers link that redirects to one). The page
posts its search with that token to /candidate/candidatejobsearch (XML: title, locations, years asked; 10 per page) and
loads each job from /candidate/candidatejobdetail. The token is taken from the published link on every run (never
stored), so a rotated token keeps working.

companies.json: {"ats": "portal", "portal": "ripplehire", "slug": "axisbank", "careers_link": "https://www.axis.bank.in/careers"}
"careers_link" is the company's own careers page (the token is read from its RippleHire link) or a RippleHire link that
redirects to a tokened page (HDFC Bank). "source" defaults to CAREERSITE (Cimpress: DIRECTCHANNEL). Optional "searches": the
site's Solr search terms, default ["*:*"] (everything); banks list thousands of branch roles, so they use
["engineer OR developer OR software"] (Axis: 9,756 jobs -> 88).
"""
import html as htmllib
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

JOB = re.compile(r"<jobVoList>(.*?)</jobVoList>", re.S)


def tag(block, name):
    m = re.search(rf"<{name}>(.*?)</{name}>", block, re.S)
    return htmllib.unescape(m.group(1)).strip() if m else ""


def token_and_source(c, h):
    """Follow the published careers link (redirects included) and read token/source from where it lands."""
    r = h.SESSION.get(c["careers_link"], timeout=30)
    r.raise_for_status()
    q = parse_qs(urlparse(r.url).query) or parse_qs(urlparse(c["careers_link"]).query)
    # a ripplehire link landed on, or one inside the company's own careers page (only RippleHire links count)
    tok = (q.get("token") or [None])[0] if "ripplehire.com" in r.url else None
    tok = tok or next(iter(re.findall(rf"{re.escape(c['slug'])}\.ripplehire\.com/candidate/[^\"'\s]*?[?&](?:amp;)?token=([A-Za-z0-9]+)", r.text)), None)
    if not tok:
        raise ValueError(f"no career-site token behind {c['careers_link']}")
    return tok, (q.get("source") or [c.get("source", "CAREERSITE")])[0]


def listing(base, token, source, search, h):
    """Every job block for one site search, 10 per page."""
    page, seen = 0, 0
    while page < 200:
        params = {"page": page, "search": search, "token": token, "source": source, "pagesize": 10}
        r = h.SESSION.post(f"{base}/candidatejobsearch", data={"careerSiteUrlParams": json.dumps(params), "lang": "en"}, timeout=40)
        r.raise_for_status()
        jobs = [b for b in JOB.findall(r.text) if "<jobSeq>" in b]
        yield from jobs
        seen += len(jobs)
        page += 1
        if not jobs or seen >= int(tag(r.text, "totalJobCount") or 0):
            return


def fetch(c, h):
    base = f"https://{c['slug']}.ripplehire.com/candidate"
    token, source = token_and_source(c, h)
    done = set()
    for search in c.get("searches", ["*:*"]):
        for b in listing(base, token, source, search, h):
            seq = tag(b, "jobSeq")
            if seq in done:
                continue  # the same job matched an earlier search
            done.add(seq)
            title, loc = tag(b, "jobTitle"), tag(b, "locations") or tag(b, "jobLocation")
            remote = loc.lower() == "remote"
            if not h.title_ok(title) or not (remote or h.in_india(loc)):
                continue
            try:
                d = h.SESSION.get(f"{base}/candidatejobdetail", params={"token": token, "jobSeq": seq, "source": source, "lang": "en"},
                                  timeout=30).text
            except Exception:
                continue  # closed between the list and the detail call
            if tag(d, "jobStatus") not in ("", "ACTIVE"):
                continue
            lo, hi = tag(b, "jobMinExp"), tag(b, "jobMaxExp")
            years = f"Experience: {lo}-{hi or lo} years\n" if lo else ""
            try:
                posted = datetime.strptime(tag(d, "jobPostingDate"), "%d-%b-%Y").replace(tzinfo=timezone.utc)
            except ValueError:
                posted = None
            yield h.Job(c["name"], title, "India (remote)" if remote and "india" in (tag(d, "jobDesc") or "").lower()[:2000] else loc,
                        f"{base}/?token={token}&source={source}#detail/job/{seq}", posted, years + h.strip_html(tag(d, "jobDesc")),
                        remote=remote)
