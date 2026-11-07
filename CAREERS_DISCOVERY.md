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
| `sitemap.py` | **Generic**: sitemap job URLs → schema.org JobPosting on each job page (Phenom, iCIMS, Avature, SuccessFactors and custom sites) |
| `jibe.py` | iCIMS Jibe search feed `/api/jobs` (AMD, DocuSign, Cvent, ICE, ZS…) |
| `keka.py`, `zohorecruit.py`, `kula.py` | Indian ATS careers pages: Keka's public feed, Zoho's embedded list, Kula's job links plus JobPosting data |
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

## Round two: companies we still couldn't read

After round one, 931 companies still had no direct source. We sampled 47 of them across every failure type:
- Phenom, iCIMS, Avature and SuccessFactors sites;
- Eightfold tenants we couldn't locate;
- Keka, Zoho Recruit and Kula pages;
- big names whose site a plain fetch couldn't reach (Meta, Netflix, Flipkart, SAP, Mastercard…);
- custom sites (Zerodha, Media.net, trading firms, BlackRock…).

### What existing tools do

- Hosted scrapers (Apify actors) cover these platforms commercially; we didn't use them.
- The open-source [strata-harvest](https://github.com/andrewcrenshaw/strata-harvest) (MIT) has parsers for Phenom, iCIMS, SuccessFactors and Eightfold. Its key idea: Phenom has no public list API, but job pages carry schema.org `JobPosting` data and sites list every job in a sitemap. SuccessFactors serves its sitemap at `/sitemal.xml`, a typo in SAP's platform that is kept on purpose.
- We took the idea, not the code. strata-harvest also ships "stealth" and "impersonating" fetchers that get past bot protection; **we did not use them**.

### Methods tried on the sample

| Method | Worked for |
|---|---|
| **Sitemap → job URLs → schema.org JobPosting on each job page** | 19 of the sample: Phenom (Fiserv, Lowe's, GE HealthCare, Philips, WEX, Cisco), iCIMS (Arm, MSCI, DocuSign), Avature (Synopsys), SuccessFactors (Moody's), SAP, AMD, NetApp, Mastercard, BlackRock, Optiver, Akuna, Quadeye |
| **iCIMS Jibe search feed** (`/api/jobs?keywords=&location=`) | AMD (97 India software results) and DocuSign (39), whose job URLs are bare IDs the sitemap method can't pre-filter |
| **Keka feed** (`<co>.keka.com/careers/api/jobs/default/active`) | Wingify, WebEngage, GoKwik |
| **Zoho Recruit**: list embedded in the careers page (hidden `jobs` field) | GeeksForGeeks, Increff |
| **Kula**: server-rendered job links, with JobPosting data on each job page | Slice, Acko, Cashfree |
| **Eightfold tenant checked with the company's own domain** | Micron (183 India results), Lam Research (59), Citi (304). Millennium returned 403, so it stays blocked. |
| **Oracle behind a company's own domain**: the page's scripts name the real tenant | American Express (`careers.americanexpress.com` fronts `egug.fa.us2.oraclecloud.com`) |
| Nothing found | Meta, Netflix, Flipkart, Citadel, Two Sigma, DRW, Bloomberg, Zerodha, Media.net, AlphaGrep, iRage, Chargebee |

### Built and run at scale

- `portals/sitemap.py`: the generic sitemap + JobPosting reader. It works like this:
  - Job URLs are kept only if their wording reads like a software role and not a senior one, so pages are filtered before they are fetched.
  - URLs naming an Indian city come first, then the newest; at most 150 pages per run.
  - robots.txt is honoured, and roles past their `validThrough` closing date are dropped.
- `portals/jibe.py`, `portals/keka.py`, `portals/zohorecruit.py` and `portals/kula.py`. The links reader now uses job-page JobPosting data when it's present, and can read titles from URLs.
- Discovery learned Oracle-on-own-domain and Kula patterns.
- **`find_careers.py --more`**: a second pass over every cached company without a source. It tries Keka, Zoho and Kula pages, Eightfold tenants with the company's domain, Jibe feeds and sitemaps on the careers host and on `careers.`/`jobs.<domain>`.
  - It ran over 690 companies and found **98 readable sources**: 39 sitemaps, 27 Keka, 10 Zoho, 10 Jibe, 8 Kula and 4 Eightfold.
  - After removing job portals (Apna and GoodSpace list other employers' jobs) and aliases (Cisco/Splunk/Duo, Cvent/Jifflenow…), **89 were added**, plus AmEx by hand. Citi moved from its Workday board to its Eightfold tenant: 31 fitting roles instead of 8.
- **Pay checked on levels.fyi** for the companies with the most new leads:
  - Now likely: AMD (L5 ₹27.9L), Citi (C10 ₹22.4L), Arm (Grade 2 ₹21.9L), Disney (median ₹38.7L).
  - Below the bar at junior levels: Lowe's (L3/L4 ₹14.5/18.9L), GE HealthCare (₹16.7L), Viasat (SE1 ₹13.0L).
  - Borderline: Micron (E1 ₹13.9L, E2 ₹24.2L) and Lam Research (median ₹22.3L).

### Round-two results

| | After round one | After round two |
|---|---|---|
| Direct sources (boards, feeds, portals) | ~245 | **335** |
| Shortlist | 335 | **356** |
| Sweet-spot roles | 83 | **94** |
| Shortlist roles from company sources (not LinkedIn) | 265 | **295** |
| Leads | 278 | 293 |

New sweet-spot roles include DocuSign "Software Engineer", WEX "SDE 1" (two openings), American Express "Software Engineer II" and Acko "SDE-1". Some LinkedIn copies (DocuSign, AmEx) now match their company's own posting and are deduplicated.

### Pay checks for the leads (7 Nov 2026)

Leads are roles with no salary evidence for their company. We checked levels.fyi India software-engineer pay for every lead company with two or more leads, and for the notable single-lead product companies: about 40 companies. Each result is recorded in `tiers.json` with its figures.

| Result | Companies |
|---|---|
| **Above the ₹20 LPA bar** (now shortlisted) | Guidewire (SE ₹22.2L), Cashfree (SDE1 ₹25.4L), BNY (E ₹19.9L / F ₹21.7L), Safe Security (median ₹31.5L), Socure (median ₹38.4L) |
| **Above the bar except entry level** (`below_title` drops "Engineer I"/"Associate" titles) | Cadence (SE I ₹16.6L, SE II ₹21.2L), Applied Materials (SE I ₹14.3L, SE II ₹25.6L), Sigmoid (SE1 ₹14.6L, SE2 ₹23.4L), Sophos (SE1 ₹15.6L, SE2 ₹22.4L) |
| **Below the bar** (now rejected, with the reason) | Emerson (₹12.2L), Eurofins (₹13.0L), NCR Voyix (Grade 10 ₹18.2L), HighRadius (₹9.3L), UPS (L1 ₹8.7L), Wolters Kluwer (T2 ₹16.0L), FIS (SE2 ₹16.7L) |
| **Borderline or level-dependent** (stay leads) | HPE, BCG, Qualys, Amagi, Smartsheet, GE Vernova, DHL, Sage, LogicMonitor, Flexera, Micron, Lam Research |
| **No India data on levels.fyi** (stay leads) | Proofpoint, PAR Technology, QuinStreet, Nationwide, Fampay, Spreetail, Truveta, isolved, Moneyview |

Six lead companies turned out to be IT-services, staffing or job-board firms, which the brief excludes. They were added to `services_and_staffing`: HTC Global Services, Kumaran Systems, Kanerika, NonStop io, HYrEzy, Searchjob.ai.

**Result:**
- Shortlist 356 → **375**; sweet-spot roles 94 → **104**; leads 293 → **242**.
- New fits include Safe Security SDE I (×3, 0–1 yrs), Guidewire "Software Engineer II (Java, backend)", Cadence SE II, Socure SE II, Cashfree SDE 2 and BNY.

The 242 remaining leads:
- 138 are from small companies seen only on LinkedIn, mostly one role each;
- 37 are borderline or level-dependent after checking;
- 25 have no levels.fyi India data;
- 42 are single-lead bank companies not yet checked.

### Round-two audit

One top role per new company, 20 companies. Each was opened in headless Chrome, or fetched directly where robots.txt disallows automated page loads.

| Company (reader) | Link live, title on page | India | Years: page vs band |
|---|---|---|---|
| WEX (sitemap) | ✓ | ✓ | 3 = 3 |
| DocuSign (Jibe) | ✓ | ✓ | 2 = 2 |
| American Express (Oracle) | ✓ | ✓ | 2 = 2 |
| Acko (Kula) | ✓ | ✓ | 1 = 0–1 |
| Slice (Kula) | ✓ | ✓ | 3 = 3 |
| BlackRock (sitemap) | ✓ | ✓ | not stated |
| Citi (Eightfold) | ✓ | ✓ | 2 = 2 |
| Disney (sitemap) | ✓ | ✓ | 3 = 3 |
| Fiserv (sitemap) | ✓ | ✓ | 3 = 3 |
| BCG (sitemap) | ✓ | ✓ | 2 = 2 |
| Cashfree (Kula) | ✓ | ✓ | 3 = 3 |
| Testsigma (Keka) | ✓ | ✓ | 3 = 3 |
| Arm (sitemap) | ✓ | ✓ | not stated |
| Viasat (Jibe) | ✓ | ✓ | 3 = 3 |
| GE HealthCare (sitemap) | ✓ | ✓ | 2 = 2 |
| Lowe's (sitemap) | ✓ | ✓ | 2 = 2 |
| Scimplify (Keka) | ✓ | ✓ | 3 = 3 |
| Franklin Templeton (sitemap) | ✓ | ✓ | 2 = 2 |
| **Lam Research (Eightfold)** | ✓ | ✓ | **✗: page asks 6–8 yrs, band said "not stated"** |
| **Renesas (sitemap)** | ✓ | ✓ | **✗: "Mgr, Software Engineering" should not have passed the title filter** |

Both failures were fixed and tested:
- The experience parser now reads labelled requirements ("Years of Experience: Minimum 6-8 years", "Experience: 2+ yrs"). A first version also read a bullet dash as a label and moved 105 Amazon roles from 3 to 2 years; a before/after diff caught it, it was fixed, and a test now covers it.
- The title filter now excludes "Mgr" and titles ending in level 3 ("Software Engineer Apps 3"), while keeping "Web3" titles.
- A Gartner page giving its address as a list crashed the sitemap reader; that's fixed and tested too.

## Where we still can't get data

**819 bank companies** still have no direct source after both rounds (931 after round one). Their roles still reach the dashboard through LinkedIn's public search.

| Reason | Companies | Examples (good payers in bold) |
|---|---|---|
| **Website not reachable by a plain fetch** (bot protection, robots.txt, or not found) | 220 | **Meta, Netflix, LinkedIn, Flipkart, Zomato, Blinkit, NetApp main site, Dropbox, Bloomberg, Citadel, Revolut, Wayfair, Indeed** |
| Website found, no careers page found | 144 | **Games24x7, Couchbase, Moj** |
| Careers page found but no platform, feed or JobPosting sitemap (custom or JavaScript-only) | 311 | **Eternal/Zomato, Myntra (bot protection), Zerodha, Dream11, Media.net, Rippling, VMware, Chargebee, Confluent (now IBM careers), HubSpot, Spotify, HashiCorp, Ramp, Deel, Two Sigma, DRW, Da Vinci, AlphaGrep, iRage, Dolat** |
| Darwinbox (job feed returns 403 to scripts) | 33 | **Zepto**, BharatPe, MobiKwik, KreditBee, Moneyview, Perfios, Go Digit, InsuranceDekho, Delhivery, Tata 1mg |
| Boards found but with no India roles today (Greenhouse 17, Workday 11, Ashby 9, Lever 5) | ~40 | They are checked again on every discovery run |
| SuccessFactors without a sitemap | 10 | Seagate, Alstom, OneCard (FPL) |
| TurboHire (feed needs a session token) | 8 | **Navi**, Flipkart, Cleartrip, Ola Electric, Purplle, Khatabook |
| Eightfold tenants that refuse scripts or weren't found | 5 | **Millennium (403)**, NAB |
| Phenom / Avature without a usable sitemap | 9 | Franklin Templeton (corporate site), Bloomberg, MetLife, Ansys |
| RippleHire, MyNextHire, Workable and others | 1–5 each | HDFC Bank, Axis Bank, Licious, Amagi, **Trexquant, Innovaccer** |

Some rows include aliases of companies already covered (e.g. AWS under "not reachable"); those are covered through the parent company's board.

## Dead ends (don't retry)

| Idea | Why not |
|---|---|
| Darwinbox (Zepto, Unacademy…) | The job feed returns 403 to scripts |
| Millennium's Eightfold tenant | 403 to scripts |
| Job portals as a source for their listed companies (Apna, GoodSpace) | Their sitemaps list other employers' jobs, which would be mislabelled |
| strata-harvest's "stealth"/"impersonating" fetchers, hosted scraping services | They get around bot protection, or are commercial. Only the sitemap + JobPosting idea was adopted. |
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

**E. Run the second pass.** After a discovery run, `python3 find_careers.py --more` finds Keka/Zoho/Kula pages, Eightfold tenants, Jibe feeds and JobPosting sitemaps. Review `output/discovered-more.json`, drop job portals and aliases, and add the rest.

**Next candidates, by expected payoff:**
1. **Pay checks for the single-lead companies** still unchecked (42 in the bank, 138 seen only on LinkedIn). Companies with two or more leads were all checked on 7 Nov.
2. **Small readers for the biggest custom sites still LinkedIn-only:** Zerodha, Media.net, Dream11, Upstox and the trading firms (Two Sigma, DRW, AlphaGrep, iRage). Check each in the browser's network panel first.
3. **Record `site` for good payers whose website wasn't reachable** (Meta, Netflix, Bloomberg…) and re-run with `--only`. Some will stay blocked, and that's fine.

**Other good payers still LinkedIn-only:**
- Indian product companies: Navi (TurboHire, token-gated like Flipkart), Slice (Kula; jobs are in the page's streamed data), Zepto (Darwinbox, blocked).
- Upstox, Media.net and Zerodha: jobs are in the page text, and `links.py` doesn't fit, so each needs a small HTML reader.
- Enterprise platforms seen in discovery: iCIMS, Phenom (Cisco), Avature (Bloomberg), SuccessFactors.
