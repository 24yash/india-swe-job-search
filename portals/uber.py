"""Uber: jobs.uber.com loads its list from /api/jobs/search (10 per page, full descriptions included)."""
API = "https://jobs.uber.com/api/jobs/search/"


def fetch(c, h):
    seen = set()
    for keyword in ("software engineer", "backend", "engineer"):
        page = 1
        while page <= 60:
            d = h.get(API, params={"keyword": keyword, "page": page})
            for j in d.get("jobs", []):
                locs = [", ".join(filter(None, [l.get("City"), l.get("Region"), l.get("Country")])) for l in j.get("Locations") or []]
                if j["Id"] in seen or not h.title_ok(j.get("Title", "")) or not any(h.in_india(l) for l in locs):
                    continue
                seen.add(j["Id"])
                url = next((u["Url"] for u in j.get("Urls") or [] if u.get("IsDefault")), f"/en/jobs/{j['Id']}/")
                text = "\n".join(h.strip_html(j.get(k)) for k in ("Description", "Summary", "AdditionalText", "AdditionalDescription1") if j.get(k))
                yield h.Job(c["name"], j["Title"], " / ".join(l for l in locs if h.in_india(l)), "https://jobs.uber.com" + url,
                            h.parse_ts(j.get("DisplayDate")), text, remote=bool(j.get("Remote")),
                            meta={"commitment": j.get("ContractType") or ""})
            if page >= d.get("totalPages", 0):
                break
            page += 1
