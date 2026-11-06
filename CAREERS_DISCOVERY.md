# Reading companies' own careers sites

Most companies in the bank had no job board the crawler could read, so their roles reached us only through LinkedIn's public search, which is slow, rate-limited, and misses postings. Almost every company publishes its openings on its own careers site. This note covers how we find those sites, how we work out where their jobs come from, which readers we built, the results, and how to add more companies.

## The study

We sampled 100 board-less companies: 40 good payers (Flipkart, Uber, JPMorgan, Goldman Sachs, Apple…) and 60 random companies from the imported lists. For each one we checked how its careers site publishes jobs.

| Method | What it found |
|---|---|
| Plain page download, looking for a known job platform's link | A few (Lever, Workday, Workable). Most careers pages build their job list with JavaScript, so the plain HTML has no jobs. |
| schema.org `JobPosting` data in the page (the markup Google for Jobs reads) | 0 of 100. Not worth a generic reader. |
| Careers URLs from the imported lists | Often useless: VC portfolio pages, homepages, dead links. |
| Rendering the page in headless Chrome (JavaScript runs), then reading links and scripts | Works. 4 of 20 rendered pages named a platform we already read (Arcesium → Greenhouse, PhonePe → SmartRecruiters, Postman → Workday, ThoughtSpot → Rippling). |
| Opening the careers page in a browser and watching its network calls | Shows the exact public data feed the page uses. This is how every custom reader below was found. |
| The "apply on company site" link in LinkedIn postings | LinkedIn now hides it unless you're signed in. Not usable. |

Takeaways:

1. Many big companies run on an enterprise platform with a public data feed behind the careers page: Workday, Oracle Recruiting Cloud, Eightfold, Rippling, iCIMS, Phenom, Avature, SuccessFactors. One reader per platform covers every company on it.
2. Some companies run their own portal. Most still load jobs from a simple public JSON or GraphQL feed (Uber, Goldman Sachs, Juspay, Urban Company) or put them in the page itself (Apple, Nutanix, Intuit, D. E. Shaw India). Each needs a small custom reader.
3. Indian startups often use Darwinbox, TurboHire, MyNextHire, Kula or Keka. Darwinbox's feed refuses scripted requests (403), so those stay on LinkedIn.

## What we built

### 1. `find_careers.py`: discovery at scale

For every bank company without a readable board (pay below the bar excluded):

1. **Website.** In order: a `site` recorded in `tiers.json` (124 good payers have one); the imported careers URL, unless it's a VC/aggregator page; guessed domains (`name.com/.in/.io/.ai/.co/.tech/.app`), resolved by DNS and accepted only if the page names the company.
2. **Careers page.** Links on the homepage that say careers/jobs, then `/careers`, `/jobs`, `careers.<domain>`, `jobs.<domain>`, `/company/careers`, `/about/careers`.
3. **Platform.**
   - Read the careers page as served.
   - If it names no platform, render it in headless Chrome (fresh throwaway profile).
   - Then follow up to 3 "open roles / view jobs" links the same way.
4. **Verify.** `discover_ats.verify` checks each platform found for India roles and the right company name, then writes `output/discovered-sites.json` for review.

Results are cached in `output/careers-sites.json` (saved every 25 companies, so an interrupted run resumes where it stopped) and rechecked after 30 days. It runs 8 companies at a time.

Discovery honours robots.txt for every page it loads or renders. The crawler's readers call the same public data feeds the careers pages call in a visitor's browser, at the slow, small volumes described in the main README.

```bash
python3 find_careers.py                    # all board-less companies (~45-60 min, cached)
python3 find_careers.py --only "Upstox"    # one or a few companies
python3 find_careers.py --refresh          # ignore the cache
```

### 2. Readers for shared platforms (`crawl.py`)

| Reader | Data source | Companies so far |
|---|---|---|
| `oracle` | Oracle Recruiting Cloud: `/hcmRestApi/resources/latest/recruitingCEJobRequisitions` plus details | JPMorgan Chase, Oracle, Honeywell, Emerson, BNY, DP World, Icertis |
| `eightfold` | Eightfold PCSX: `/api/pcsx/search` plus `position_details` (Microsoft now uses this reader too) | Qualcomm, Autodesk, Microsoft |
| `rippling` | Rippling ATS: `api.rippling.com/platform/api/ats/v1/board/<slug>/jobs` | ThoughtSpot |
| `workday`, `greenhouse`, `lever`, `ashby`, `smartrecruiters` (already existed) | Fed by discovery | Walmart Global Tech, Citi, Cadence, Capital One, KLA, Postman, Expedia, HighLevel, Warner Music Group, PhonePe… |

### 3. Custom portals (`portals/`)

One small module per portal, run in the fast phase like any board (`"ats": "portal", "portal": "<module>"` in `companies.json`):

| Module | How the site exposes jobs |
|---|---|
| `apple.py` | Search and job pages carry their data as embedded JSON (`__staticRouterHydrationData`) |
| `goldman.py` | Public GraphQL gateway (`GetRoles`, `GetRoleById`). Analyst/Associate software roles only. |
| `uber.py` | `jobs.uber.com/api/jobs/search`: full descriptions in the list |
| `juspay.py` | `joinus.juspay.in/api/careerJobOpening`: every opening with years asked |
| `urbancompany.py` | One public POST call returns all openings with descriptions |
| `sharechat.py` | `sharechat.com/api/careersList` gives titles, locations, years asked and dates (no description). The link opens the MyNextHire job page. |
| `links.py` | **Generic**: server-rendered job links, configured per company (list URL, job-link pattern, pages, fallback location). Used for Nutanix, Intuit (Radancy) and D. E. Shaw India. |

Rules for every reader (repeated in `portals/__init__.py`):
- Read only the public data the careers page itself loads.
- No sign-ins, nothing submitted, and no getting around bot protection. A 403/422 means stop.
- Filter to India and fitting titles before any detail calls.
- A failed detail call skips only that job.

## Results

First crawl of the new sources (7 Nov 2026), before the full discovery run:

- **Shortlist 296 → 323 roles**: +31 from careers sites, minus LinkedIn copies of the same roles now recognised as duplicates.
- New roles that match the brief, all with salary evidence:
  - Apple "Software Engineer – Java, Spring Boot and Microservices" (2 yrs), and 20 more Apple India roles.
  - JPMorgan "Software Engineer II – Java, Spring Boot, Kubernetes" (2 yrs) and 7 more.
  - Goldman Sachs Analyst (0–1 yrs) and Associate engineering roles.
  - Qualcomm SE roles (0–1 yrs), Expedia SDE II and Postman SE (2 yrs).
  - Juspay SDE Backend (0–1 yrs).
- Every sampled link was live, with its title on the page.

### Full discovery run (7 Nov 2026)

`find_careers.py` over every bank company with no readable board (pay below the bar excluded): **999 companies**. It took ~45 min at 8 at a time.

| Step | Companies |
|---|---|
| Website found | 766 (86 from a recorded `site`, 327 from imported careers URLs, 353 from checked domain guesses) |
| Careers page found | 620 |
| A job platform named on the page or its "open roles" links | 283 |
| Boards verified with India roles, on a platform we can read | 60 (50 after merging aliases such as Citi/Citigroup and skipping Bank of America's US-only board) |

Platforms named: Workday 49, Darwinbox 34, Keka 30, Phenom 27, Greenhouse 23, Ashby 21, Eightfold 17, iCIMS 13, Oracle 10, Zoho Recruit 10, Lever 8, TurboHire 8, Workable 6, SmartRecruiters 4, Jobvite 4, others ≤ 3.

All 50 boards were added to `companies.json` (`"found_by": "find_careers.py"`). Among them:
- Walmart Global Tech India, Citi, Oracle (found via Cerner), Cadence, Honeywell, Emerson (via National Instruments), BNY, KLA, Commonwealth Bank, Northern Trust, Capital One, HighLevel, Warner Music Group, Zendesk, Qualys, Samsung, Palo Alto Networks, Broadcom…
- Walmart's Workday board now answers scripted requests (it used to refuse). Today it lists only senior roles in India.

**Totals after both stages:**

| | Before | After |
|---|---|---|
| Shortlist | 296 | 335 |
| Sweet-spot roles (≤ 2 yrs, pay evidenced) | 69 | 83 |
| Shortlist roles from company sites/boards (not LinkedIn) | — | 265 |
| Leads (pay not yet checked) | 228 | 278 |

The 50 discovered boards gave 14 shortlist roles (Oracle 6, HighLevel 4, Warner Music Group 2, Zendesk, QuantBox) and 41 leads (Emerson, Qualys, Eurofins, Cadence, Citi…). The leads become shortlist roles once their pay is checked on levels.fyi.

### Audit of sampled results

One top role per company from company sources (18 companies). Each link was opened in headless Chrome, then checked for:
- the title and an Indian location on the page;
- the years asked against the dashboard's experience band;
- pay evidence (levels.fyi notes in `tiers.json`, or a stated tier judgement).

| Company | List | Link live, title on page | India on page | Years: page vs band | Pay basis |
|---|---|---|---|---|---|
| Apple | shortlist | ✓ | ✓ | 2 = 2 yrs | levels.fyi ICT2/ICT3 |
| JPMorgan Chase | shortlist | ✓ | ✓ | 2 = 2 yrs | levels.fyi 601 |
| Goldman Sachs | shortlist | ✓ | ✓ | not stated = not stated | levels.fyi Analyst |
| Qualcomm | shortlist | ✓ (direct fetch; robots.txt disallows automated page loads, so the renderer skipped it) | ✓ | band from the API description: 0–1 yrs | levels.fyi |
| Juspay | shortlist | ~ link opens the careers page, not the role (the site has no per-role URL) | ✓ | years come from the feed (0) | tier judgement (stated) |
| Expedia | shortlist | ✓ | ✓ | 2 = 2 yrs | levels.fyi |
| Postman | shortlist | ✓ | ✓ | 2 = 2 yrs | levels.fyi IC1 |
| PhonePe | shortlist | ✓ | ✓ | 3 = 3 yrs | levels.fyi SE1 |
| Oracle | shortlist | ✓ | ✓ | 3 = 3 yrs | levels.fyi IC-2 |
| HighLevel | shortlist | ✓ | ✓ | 2 = 2 yrs | levels.fyi |
| Warner Music Group | shortlist | ✓ | ✓ | not stated = not stated | levels.fyi |
| Zendesk | shortlist | ✓ | ✓ | not stated = not stated | tier judgement (stated) |
| QuantBox | shortlist | ✓ | ✓ | not stated = not stated | tier judgement (stated) |
| Emerson | lead | ✓ | ✓ | not stated = not stated | unverified (correctly a lead) |
| Citi | lead | ✓ (direct fetch; robots.txt disallows automated page loads) | ✓ | not stated | unverified (correctly a lead) |
| Cadence | lead | ✓ | ✓ | 2 = 2 yrs | unverified (correctly a lead) |
| Qualys | lead | ✓ | ✓ | 2 = 2 yrs | unverified (correctly a lead) |
| D. E. Shaw India | — | no fitting role open today (reader returns only senior and non-tech roles) | | | |

Result: 17 of 17 roles are real, open, in India and correctly banded. One (Juspay) links to the careers page rather than the role. Every shortlist role's pay rests on levels.fyi data or a stated tier judgement, and roles without either sit in leads.

Bugs found while verifying, all fixed and covered by tests:
1. Discovery froze on huge pages: unbounded `<a …>(.*?)</a>` matching took ~70 s per page.
2. Discovery froze on long base64 runs: unbounded `([a-z0-9-]+)\.` subdomain patterns went quadratic.
3. Evaluation crashed on an Oracle job whose schedule field was null.
4. Goldman Sachs titles were rewritten, so LinkedIn copies weren't recognised as duplicates; Goldman's own titles are kept now.

## Where we still can't get data

931 bank companies still have no direct source and rely on LinkedIn. Why, from the discovery cache (`output/careers-sites.json`):

| Reason | Companies | Examples (good payers in bold) |
|---|---|---|
| **Website not reachable by a plain fetch** (bot protection, robots.txt, or not found) | 228 | **Meta, Netflix, LinkedIn, Flipkart, Zomato, Blinkit, SAP, NetApp, Dropbox, Bloomberg, Citadel, Revolut, Wayfair, Mastercard, Arista, Indeed** |
| Website found, no careers page found | 146 | **Games24x7, Couchbase, Moj** |
| Careers page found but no platform named (custom site, or JavaScript the renderer couldn't resolve) | 329 | **Walmart (store site), Zerodha, Media.net, Dream11, Myntra (bot protection), BlackRock, Chargebee, Confluent, HubSpot, VMware, Spotify, HashiCorp, Ramp, Deel, Two Sigma, DRW, Akuna, Optiver, Quadeye, AlphaGrep, iRage** |
| Darwinbox (job feed returns 403 to scripts) | 34 | **Zepto**, BharatPe, MobiKwik, KreditBee, Moneyview, Perfios, Go Digit |
| Keka (no reader yet) | 27 | GoKwik, WebEngage, Zluri, Scrut, Wingify/VWO |
| Phenom (no reader yet) | 20 | **Splunk, WEX**, Philips, GE HealthCare, Lowe's, Fiserv, Disney, Franklin Templeton |
| iCIMS (no reader yet) | 14 | **DocuSign, Booking.com, Planview**, AMD, Arm, MSCI, ICE, Highspot, Cvent |
| Eightfold tenants (reader exists, but the API host/domain wasn't found automatically) | 11 | **American Express, Millennium**, Micron, NAB, Lam Research |
| SuccessFactors (no reader yet) | 11 | Moody's, OneCard (FPL), Seagate, Alstom |
| Zoho Recruit (no reader yet) | 11 | Increff, e6data, Fyers, GeeksForGeeks |
| TurboHire (feed needs a session token) | 8 | **Navi**, Flipkart, Cleartrip, Ola Electric, Purplle, Khatabook |
| Kula (jobs in the page's streamed data; no reader yet) | 8 | **Slice, Acko**, CleverTap, MoEngage, Cashfree |
| Avature (no reader yet) | 6 | **CommBank (main site)**, Synopsys, Ansys, MetLife |
| Others: Workable, RippleHire, MyNextHire, Gem, BambooHR, Jobvite, Recruiterflow, Freshteam, Skillate, Taleo, PeopleStrong | 1–5 each | **Trexquant, Innovaccer, Hasura**, HDFC Bank, Axis Bank, CoinSwitch |

Some rows include aliases of companies already covered (e.g. AWS, Google Cloud, Microsoft Research under "not reachable"). Those are covered through their parent's board.

Roles at these companies still reach the dashboard through LinkedIn's public search, as before.

## Dead ends (don't retry)

| Idea | Why not |
|---|---|
| Darwinbox (Zepto, Unacademy…) | The job feed returns 403 to scripts |
| JioStar (Disney+ Hotstar) Workday | 403 to scripts |
| Walmart's new careers site | Ignores the search and lists US store jobs. (Walmart's tech roles are now read from its Workday board, `walmart.wd504`, which discovery found answering again.) |
| Myntra's portal | Bot detection |
| Flipkart's TurboHire page | Lists departments for résumé drops, not jobs, and its feed needs a session token. Flipkart stays on LinkedIn. |
| LinkedIn "apply on company site" links | Hidden unless signed in |
| Wikidata for company websites | Many Indian companies missing, and it rate-limits. Recorded `site` values plus guessed domains work better. |
| schema.org JobPosting scraping | None of the 100 sampled careers pages had it |

## Adding more companies

**A. Re-run discovery.** Run it monthly, or after importing companies:
1. `python3 find_careers.py`
2. Review `output/discovered-sites.json`.
3. Copy verified boards into `companies.json` (name, `ats`, slug/tenant/host fields, with `type`/`quality`/`pay`/`pay_note` from `tiers.json`).
4. Run `python3 crawl.py --sources fast --only "<names>"` and check the new roles.

**B. Record websites for good payers.** If a good-paying company had no site found, add `"site": "example.com"` to its `tiers.json` entry and re-run discovery with `--only`.

**C. Add a platform reader.** When `find_careers.py` prints many "no reader yet" hits for one platform (iCIMS, Phenom, Avature, SuccessFactors so far):
1. Open one such careers page in a browser and watch the network calls for the job list.
2. If the feed is public, add a fetcher to `crawl.py` and a probe in `discover_ats.verify`.
3. Add a fixture test in `tests/test_sources.py`.

**D. Add a custom portal.** For a good payer on its own portal:
1. Open the careers page with the browser's network panel and find the call that returns jobs (JSON, GraphQL, or jobs embedded in the HTML).
2. If the jobs are plain links in the HTML, configure `portals/links.py` in `companies.json`; no code needed.
3. Otherwise copy the smallest module (`juspay.py`, `uber.py`) and adapt it.
4. Add a fixture test, then crawl with `--only`.

**Next candidates, by expected payoff:**
1. A **Phenom** reader (Splunk, WEX, Fiserv, Lowe's, Disney… 20 companies) and an **iCIMS** reader (DocuSign, Booking.com, AMD, Arm, MSCI… 14). Check first that their feeds are public.
2. **Eightfold host lookup**: try `<tenant>.eightfold.ai` with the company's domain, as with AmEx, Millennium and Micron.
3. **Pay checks for the new leads** (Citi, Cadence, Emerson, Qualys, BNY, Northern Trust…) on levels.fyi, recorded in `tiers.json`. They move to the shortlist once pay is evidenced.
4. **Record `site` for good payers whose website wasn't reachable** (see the table above) and re-run with `--only`.

**Other good payers still LinkedIn-only:**
- Indian product companies: Navi (TurboHire, token-gated like Flipkart), Slice (Kula; jobs are in the page's streamed data), Zepto (Darwinbox, blocked).
- Upstox, Media.net and Zerodha: jobs are in the page text, and `links.py` doesn't fit, so each needs a small HTML reader.
- Enterprise platforms seen in discovery: iCIMS, Phenom (Cisco), Avature (Bloomberg), SuccessFactors.
