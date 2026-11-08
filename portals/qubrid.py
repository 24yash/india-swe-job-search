"""Qubrid AI's own careers API (qubrid.com/careers/api/v1/jobs). Roles are listed as Remote with India working hours.
companies.json: {"ats": "portal", "portal": "qubrid"}"""


def fetch(c, h):
    cursor, n = None, 0
    while n < 20:
        d = h.get("https://qubrid.com/careers/api/v1/jobs" + (f"?cursor={cursor}" if cursor else ""))
        for j in d.get("items") or []:
            if (j.get("status") or "open").lower() not in ("open", "published", "active") or not h.title_ok(j.get("title", "")):
                continue
            yield h.Job(c["name"], j["title"].strip(), "India (remote)", f"https://www.qubrid.com/careers/jobs/{j['public_id']}",
                        h.parse_ts(j.get("published_at")), j.get("description") or "", remote=True,
                        meta={"employmentType": j.get("employment_type") or ""})
        cursor, n = d.get("next_cursor"), n + 1
        if not cursor:
            break
