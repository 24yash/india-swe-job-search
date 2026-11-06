"""Generic reader for careers portals that render their job list as plain links on the server
(Nutanix, Intuit's Radancy site, D. E. Shaw India…). Configured per company in companies.json:

  {"name": "Nutanix", "ats": "portal", "portal": "links",
   "list_urls": ["https://careers.nutanix.com/en/jobs/?search=software+engineer&country=India&page={page}"],
   "job_link": "/en/jobs/\\d+/[^\"/]+/", "max_pages": 10, "location": "India"}

The title is the link text (cut at a ':' or a run of spaces); detail pages are fetched only for India-fitting
titles. "location" is used when the detail page names no Indian city (only set it when the list URL is
already filtered to India)."""
import html as htmllib
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

CITIES = ("Bengaluru", "Bangalore", "Hyderabad", "Pune", "Mumbai", "Gurugram", "Gurgaon", "Noida", "Chennai", "New Delhi", "Delhi",
          "Ahmedabad", "Kolkata", "Thiruvananthapuram", "Trivandrum", "Kochi", "Coimbatore", "Jaipur", "Indore", "Remote")


def page_text(h, url):
    r = h.SESSION.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def fetch(c, h):
    seen, todo = set(), []
    for tmpl in c["list_urls"]:
        for page in range(1, (c.get("max_pages", 1) if "{page}" in tmpl else 1) + 1):
            url = tmpl.format(page=page)
            body = page_text(h, url)
            found = 0
            for href, inner in re.findall(r'<a\b[^>]{0,1500}?href="(' + c["job_link"] + r'[^"]{0,600})"[^>]{0,1500}>(.{0,3000}?)</a>', body[:3_000_000], re.S | re.I):
                link = urljoin(url, htmllib.unescape(href))
                inner = re.sub(r"<svg.*?</svg>", " ", inner, flags=re.S | re.I)
                named = re.search(r'class="[^"]*(?:title|name)[^"]*"[^>]*>(.*?)<', inner, re.S | re.I)
                name = htmllib.unescape(re.sub(r"<[^>]+>", " ", named.group(1) if named else inner))
                title = re.split(r"\s{3,}|:\s", name.strip())[0].strip()
                found += 1
                if link in seen or not title or not h.title_ok(title):
                    continue
                seen.add(link)
                todo.append((title, link))
            if not found:
                break

    def detail(item):
        title, link = item
        try:
            body = page_text(h, link)
        except Exception:
            return None
        main = re.search(r"<main.*?</main>", body, re.S | re.I)
        text = h.strip_html(main.group(0) if main else body)
        cities = [x for x in CITIES if re.search(rf"\b{x}\b", text[:4000])]
        loc = " / ".join(dict.fromkeys(cities)) + (", India" if cities else "")
        if not cities and not c.get("location"):
            return None
        return h.Job(c["name"], title, loc or c["location"], link, None, text, remote="Remote" in cities)

    with ThreadPoolExecutor(4) as pool:
        yield from filter(None, pool.map(detail, todo))
