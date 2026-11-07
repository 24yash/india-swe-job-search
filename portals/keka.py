"""Keka careers pages (<company>.keka.com/careers): the page loads its openings from a public feed,
/careers/api/jobs/default/active, with descriptions, years asked and publish dates.
companies.json: {"ats": "portal", "portal": "keka", "slug": "wingify"}"""


def fetch(c, h):
    base = f"https://{c['slug']}.keka.com/careers"
    for j in h.get(f"{base}/api/jobs/default/active") or []:
        locs = [", ".join(x for x in (l.get("city"), l.get("state"), l.get("countryName") or l.get("countryCode")) if x)
                for l in j.get("jobLocations") or []]
        india = [l for l in locs if h.in_india(l) or l.endswith(", IN")]
        if not h.title_ok(j.get("title", "")) or not india:
            continue
        exp = j.get("experience") or ""
        text = h.strip_html(j.get("description") or "") + (f"\n\nExperience: {exp} of experience" if exp else "")
        yield h.Job(c["name"], j["title"].strip(), " / ".join(india), f"{base}/jobdetails/{j['id']}",
                    h.parse_ts(j.get("publishedOn")), text)
