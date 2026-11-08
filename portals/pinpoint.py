"""Pinpoint ATS boards (<slug>.pinpointhq.com/postings.json): every posting with location, description and often
posted pay. Used by Vena Solutions. companies.json: {"ats": "portal", "portal": "pinpoint", "slug": "vena"}"""


def fetch(c, h):
    for j in h.get(f"https://{c['slug']}.pinpointhq.com/postings.json").get("data") or []:
        l = j.get("location") or {}
        loc = ", ".join(x for x in (l.get("city"), l.get("province"), l.get("name")) if x)
        if not h.title_ok(j.get("title", "")) or not (h.in_india(loc) or "india" in loc.lower()):
            continue
        text = "\n".join(h.strip_html(j.get(k) or "") for k in ("description", "key_responsibilities", "skills_knowledge_expertise"))
        if j.get("compensation_visible") and j.get("compensation"):
            text += f"\n\nCompensation: {j['compensation']}"
        yield h.Job(c["name"], j["title"].strip(), loc, j.get("url") or "", None, text,
                    remote=(j.get("workplace_type") == "remote"), meta={"employmentType": j.get("employment_type_text") or ""})
