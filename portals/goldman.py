"""Goldman Sachs: higher.gs.com loads roles from its public GraphQL gateway (GetRoles search, GetRoleById detail).
Titles there read like "Division-Team-City-Associate-Software Engineering", so the fit check uses the job
function and corporate title. The title is kept as Goldman writes it (LinkedIn copies match it as duplicates), plus the job
function in brackets when the title alone doesn't say it is a software role."""
API = "https://api-higher.gs.com/gateway/api/v1/graphql"
HEAD = {"Origin": "https://higher.gs.com", "Referer": "https://higher.gs.com/"}
SEARCH = ("query GetRoles($searchQueryInput: RoleSearchQueryInput!) { roleSearch(searchQueryInput: $searchQueryInput) "
          "{ totalCount items { roleId corporateTitle jobTitle jobFunction locations { city country } status externalSource { sourceId } } } }")
DETAIL = ("query GetRoleById($externalSourceId: String!, $externalSourceFetch: Boolean) { role(externalSourceId: $externalSourceId, "
          "externalSourceFetch: $externalSourceFetch) { roleId corporateTitle jobTitle descriptionHtml "
          "compensation { minSalary maxSalary currency } status locations { city country } } }")
FUNCTIONS = ("software engineering", "engineering", "site reliability", "platform")
LEVELS = ("analyst", "associate")  # Vice President and above are senior


def gql(h, op, query, variables):
    r = h.SESSION.post(API, json={"operationName": op, "query": query, "variables": variables}, headers=HEAD, timeout=30)
    r.raise_for_status()
    return r.json()["data"]


def fetch(c, h):
    page, seen = 1, set()
    while page <= 20:
        v = {"searchQueryInput": {"page": {"pageSize": 20, "pageNumber": page}, "sort": {"sortStrategy": "POSTED_DATE", "sortOrder": "DESC"},
                                  "filters": [{"filterCategoryType": "LOCATION", "filters": [{"filter": "India", "subFilters": []}]}],
                                  "experiences": ["PROFESSIONAL"], "searchTerm": "engineer"}}
        items = gql(h, "GetRoles", SEARCH, v)["roleSearch"]["items"]
        for x in items:
            func, level = (x.get("jobFunction") or "").lower(), (x.get("corporateTitle") or "").lower()
            if x["roleId"] in seen or level not in LEVELS or not any(f in func for f in FUNCTIONS) or x.get("status") != "POSTED":
                continue
            seen.add(x["roleId"])
            src = (x.get("externalSource") or {}).get("sourceId") or x["roleId"].split("_")[0]
            try:
                d = gql(h, "GetRoleById", DETAIL, {"externalSourceId": src, "externalSourceFetch": False})["role"] or {}
            except Exception:
                continue
            locs = " / ".join(dict.fromkeys(f"{l['city']}, India" for l in x.get("locations") or [] if l.get("city") and l.get("country") == "India"))
            comp = d.get("compensation") or {}
            pay = f"{comp.get('currency')} {comp.get('minSalary'):,}" if comp.get("currency") == "INR" and comp.get("minSalary") else ""
            title = x["jobTitle"].strip()
            if not h.title_ok(title):  # e.g. "Tax - Tax Engineering - Analyst - Bengaluru": say what the job function is
                title += f" ({x['jobFunction']})"
            yield h.Job(c["name"], title, locs or "India", f"https://higher.gs.com/roles/{src}", None,
                        h.strip_html(d.get("descriptionHtml") or ""), pay_posted=pay)
        if len(items) < 20:
            break
        page += 1
