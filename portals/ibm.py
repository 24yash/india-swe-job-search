"""IBM careers search (www.ibm.com/careers/search): the page POSTs to IBM's public search API (appId "careers",
scope "careers2") and gets every job's title, location ("Bangalore, IN"), posting date and full description, so no
detail calls are needed (the careers.ibm.com job pages answer scripts with an empty 202). Used for Confluent, whose
careers.confluent.io now redirects to ibm.com/careers/search?q=confluent.

companies.json: {"ats": "portal", "portal": "ibm", "query": "confluent"}
Only jobs naming the query in their title or description are kept (the search also ranks loosely related IBM jobs).
"""
API = "https://www-api.ibm.com/search/api/v2"
FIELDS = ["keywords^1", "body^1", "url^2", "description^2", "h1s_content^2", "title^3", "field_text_01"]
SOURCE = ["_id", "title", "url", "description", "body", "dcdate", "field_keyword_08", "field_keyword_17", "field_keyword_18",
          "field_keyword_19"]


def fetch(c, h):
    q = c["query"]
    start, total = 0, None
    while total is None or start < min(total, 1000):
        d = h.post(API, {"appId": "careers", "scopes": ["careers2"], "size": 100, "from": start, "lang": "zz", "localeSelector": {},
                         "query": {"bool": {"must": [{"simple_query_string": {"query": q, "fields": FIELDS}}]}},
                         "sm": {"query": q, "lang": "zz"}, "_source": SOURCE})
        hits = (d.get("hits") or {}).get("hits") or []
        total = ((d.get("hits") or {}).get("total") or {}).get("value", 0)
        for x in hits:
            s = x.get("_source") or {}
            title, loc, body = (s.get("title") or "").strip(), s.get("field_keyword_19") or "", s.get("body") or s.get("description") or ""
            if q.lower() not in f"{title} {body}".lower() or not h.title_ok(title) or not h.in_india(loc):
                continue
            yield h.Job(c["name"], title, loc, s.get("url") or "", h.parse_ts(s.get("dcdate")), h.strip_html(body),
                        remote=(s.get("field_keyword_17") or "").lower() == "remote")
        if not hits:
            break
        start += 100
