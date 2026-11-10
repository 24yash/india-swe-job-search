# Design notes

How the job-search tool works, the decisions behind it, what was tried and rejected, and what is left to improve. Keep this file updated whenever a decision changes.

## Goal

Find every open software-engineering role in India that fits the profile in `profile.json`: level and title, years asked ≤ `max_min_years`, pay ≥ `min_pay_lpa` (₹ LPA), not a services or staffing firm. Rank the roles, and track applications in a dashboard. Read-only: no logins, no applying, nothing personal sent anywhere.

## Architecture

```
tiers.json (company bank, ~1,200)   companies.json (~335 direct sources + 2 LinkedIn sources)   profile.json (criteria)
            │                                   │
            ▼                                   ▼
crawl.py ── fast phase: boards, platform feeds, portals/, 16 at a time (~1 min) ┐
        └─ LinkedIn phase: throttled guest search, in the background ────┤  each source → output/raw/<source>.json
                                                                         ▼
           evaluate_all (no network, ~2 s): resolve company → exclude services/staffing → drop duplicates
           → title/location/contract filters → pay floor → years asked → score → group requisitions
                                                                         ▼
           jobs / leads / rejected / company-bank CSVs, report.py table, build_dashboard.py → dashboard.html
```

Supporting tools: `discover_ats.py` (find direct boards), `coverage.py` (per-company coverage status), `find_careers.py` (find each company's careers site and the platform behind it; see `CAREERS_DISCOVERY.md`), `import_lists.py` (grow the bank from public lists), `refresh.sh` (fast phase, then LinkedIn in the background).

## Key decisions

| Decision | Why |
|---|---|
| **Read company job boards directly** (Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Amazon, Microsoft, Atlassian, Google) | Complete, current, has the full description, and the apply link is the company's own. A role that disappears from the board has closed. |
| **Read companies' own careers sites** (Oracle Recruiting Cloud, Eightfold, Rippling feeds; `portals/` for custom sites) | A study of 100 board-less companies showed most careers pages load jobs from a public feed. JPMorgan, Apple, Goldman Sachs, Qualcomm, Juspay and others were LinkedIn-only before. Details in `CAREERS_DISCOVERY.md`. |
| **Custom portals: one small module each, plus a configurable job-links reader** | Sites differ too much for one generic scraper, but each needs only ~30 lines. Server-rendered link lists need only config (`portals/links.py`). |
| **Sitemaps + job-page JobPosting data as a generic reader** (`portals/sitemap.py`) | Phenom, iCIMS, Avature, SuccessFactors and many custom sites have no public list feed, but their sitemaps list every job and each job page carries schema.org JobPosting data (for Google for Jobs). One reader covers them all: URLs are filtered by wording before any page is fetched, robots.txt is honoured, and expired `validThrough` dates are dropped. The idea came from strata-harvest (MIT); its "stealth"/"impersonating" fetchers were deliberately not used. |
| **Small readers for Indian ATS pages: Keka, Zoho Recruit, Kula, PyjamaHR, Zappyhire, Zwayam, RippleHire, TurboHire pass-through feeds; iCIMS Jibe feeds; Jobvite lists; SuccessFactors `sitemal.xml` feeds** | Each careers page loads a public feed or embeds its list. One reader per platform covers dozens of companies that were LinkedIn-only. SuccessFactors sites disallow `/services/` in robots.txt, so their RSS job feed (one request, every job) is read instead of the search API. |
| **RippleHire: the token is read from the company's own careers page on every run, never stored** | RippleHire's search needs the career-site token that each company puts in its published careers link (user agreed 10 Nov 2026). Reading it fresh keeps working if it rotates and keeps tokens out of `companies.json`; job links still carry the token, as the company's own published link does. Banks list thousands of branch roles, so they search `engineer OR developer OR software` (Axis 9,756 -> 88 jobs). |
| **Hand-built readers only for companies whose pay clears the bar** | A custom site needs its own ~30-line reader, so pending companies are pay-checked on levels.fyi first (75 on 10 Nov 2026) and readers are built for good and borderline payers only (Khatabook, MediaTek, PayU, Nomura, DTCC, MiQ, HSBC…). Low payers stay on LinkedIn. |
| **"City, IN" alone is Indiana, not India** | SuccessFactors writes India as "City, IN" or "City, ST, IN", and US sites write Indiana as "City, IN". A two-part "City, IN" counts as India only with another India marker (a known city or state); the three-part form always counts. |
| **Job portals are never taken as an employer's source** | Apna's and GoodSpace's sitemaps list other employers' jobs; reading them would mislabel roles. |
| **Company domains from Clearbit's autocomplete, careers URLs from search** | Guessed domains picked other companies; Clearbit's keyless lookup (exact name match) is accurate. Search in the user's browser finds careers sites the scripts can't; scripted DuckDuckGo and LinkedIn company pages refuse automated use. |
| **`coverage.py` keeps a per-company status** | Every bank company gets a status: source with/without fitting roles, nothing to read, blocked, dead/retryable, or pending, so gaps are measured instead of guessed. |
| **Discovery renders careers pages in headless Chrome** | Plain HTML of modern careers pages rarely names the job platform (the list is built by JavaScript); rendering found boards the plain fetch missed. Bounded regexes keep huge pages fast. |
| **LinkedIn public guest search as the second source** | Covers companies with no readable board (Flipkart, Meta, Netflix, Zepto…). In a measured run it supplied 6 of the top 10 roles. |
| **Two speeds** (`--sources fast` vs `linkedin`) | LinkedIn must be slow (rate limits). Company boards give a usable dashboard in ~1 min, and LinkedIn fills in every ~40 postings. |
| **One raw file per source** | A slow or failed source never empties the results; it keeps its last good data. `--rescore` re-filters without the network. |
| **LinkedIn light mode by default**, `--deep` optional | India-wide role searches plus a 40-company sweep give nearly all LinkedIn value. Per-city searches and big sweeps added ~5 roles for hours of crawling. |
| **The company bank never drops a company for being quiet** | Hiring is cyclical. Each run re-checks every company, and `bank-history.json` shows when a quiet one starts hiring. |
| **Pay evidence lives in `tiers.json`** | Levels.fyi blocks scripts (403), so an agent looks pay up with WebFetch and records it once; every run reuses it. Total comp, not fixed CTC. An overall-only median ≥ 30 L counts as likely; 20–30 L stays borderline (overall medians lean senior). `below_title` excludes the levels that pay below the floor (e.g. Mastercard SE-I, BlackRock Analyst). |
| **Pay confidence on every role**: Posted › Strong (levels.fyi) › Likely (tier judgement, with the reason) › Unverified (goes to leads) | Your brief allows "Likely" if the reason is stated. Unverified roles never reach the shortlist. |
| **Score weights: pay 35, level fit 30, company 15, stack 10, freshness and link 10** (`profile.json` `score_weights`) | Pay and years asked are prerequisites; a stack can be learned. Stack weighs less than company quality, and less than the gap between Strong and Likely pay evidence (0.3 x 35 = 10.5), so a well-paying role with little stack overlap outranks a perfect stack match whose pay is only a guess. Changed 10 Nov 2026 from stack 35 / level 20 / pay 20 / company 15 / fresh 10, which ranked Google, Microsoft and Amazon SDE roles 70-90th for not naming Java/Spring. |
| **Experience = the smallest "N+ years" / "N–M years" near experience words; years in the title override** | Lenient on purpose ("2+ required, 5+ preferred" counts as 2). A role with no years stated gets a neutral score, not a rejection. |
| **Experience focus: 0–2 years is the sweet spot; campus hiring excluded** | Every role gets an experience band (0–1, 2, 3 yrs, not stated). A role is a *sweet spot* when it asks ≤ 2 years and its pay is backed by salary data (not a tier judgement). Level fit (raw 0-20, scaled to its weight): 1-2 yrs 20, 0 yrs 19, 3 yrs 12. New-grad, graduate, early-career, campus and fresher titles are excluded, as are descriptions that say "campus hiring/drive/placement", "graduating in …", "2026 batch". A duty like "help with campus recruitments" doesn't count (Graviton false positive, fixed with a test). |
| **Exclusions match leading words** ("EY" matches "EY GDS", not "Honeywell"); staffing keywords match whole words anywhere | The old substring match silently dropped Disney+ Hotstar, Honeywell, Palo Alto Networks, Anthropic, Northern Trust… |
| **Company matching: exact name, or a prefix with ≥ 5 characters** | Merges real aliases (AWS → Amazon, DeepMind → Google) without merging different companies (CRED ≠ Credgenics/CredHive). |
| **LinkedIn duplicate = same title on the company's own board (today's listing)** | Some companies post roles on LinkedIn that their board doesn't show (e.g. Clearwater SDE-II); those are kept. |
| **Expiry** (below) | Dead jobs go; older active jobs stay. |
| **Marks live in the browser (localStorage), keyed by job link, plus a company + title + location match for reposts; `job-archive.json` keeps closed roles** | No server needed, and refreshes never lose marks. Export/Import backs them up. |

## Expiry: dead jobs out, older active jobs kept

| Situation | What happens |
|---|---|
| Role listed on the company's own board | Kept at any age (the board is authoritative) |
| Role gone from the company's board | Removed (closed) |
| LinkedIn role seen again this run | Kept |
| LinkedIn role not seen again | Checked on LinkedIn's public job page (404 or "No longer accepting applications" = closed). Up to `liveness_checks_per_run` per pass, ones about to age out first, rechecked after `liveness_recheck_days` |
| … confirmed open | Kept at any age |
| … confirmed closed | Dropped |
| … not yet checked (budget or rate limit) | Kept only while posted within `max_age_days` (30) |
| Dashboard | A closed role you marked stays visible, tagged "no longer listed"; unmarked ones are hidden |

## Tried and rejected

| Idea | Outcome |
|---|---|
| **JobSpy** for Naukri, Indeed, Google | Not used. For Naukri it forges the app's anti-bot token, which gets around the reCAPTCHA; for Indeed it uses the mobile app's private API key; for Google it replays internal search parameters. All of these get around access controls. |
| **Naukri, Instahyre, Hirist, Cutshort** | Need a reCAPTCHA or login; not scripted. A possible legitimate route is an importer for result pages the user saves themselves. |
| **Darwinbox** (Zepto, BookMyShow…), **TurboHire** (Flipkart), **Myntra's portal** | Darwinbox's job endpoint returns 403, TurboHire has no public data source, and Myntra's portal has bot detection. Covered through LinkedIn instead. |
| **Walmart Workday board (old host)** | `wd5` refused requests (422). Discovery found the board on `wd504`, which answers; it is now a direct source. |
| **VC portfolio boards (Getro: Accel, General Catalyst) as a job source** | Job data is public, but jobs from acquired companies are filed under the old startup's name (Salesforce roles as "Airkit", PayPal as "Simility"…), so as a source it adds mislabelled duplicates. **Used for discovery only**: their apply links reveal company boards. |
| **Consider-based VC boards** (Peak XV, Lightspeed, Bessemer) | The search endpoint needs a session token from the page; not used. Their portfolio company names come from the ISJB dataset instead. |
| **LinkedIn company sweep with OR-batched names** | The biggest poster crowds out the rest (Walmart took 24/30 results). One search per company instead, rotating. |
| **LinkedIn "engineering function" filter** | Ignored by the public search. |
| **Hiring.cafe, Apify ATS actors** | No public API (hiring.cafe) or commercial (Apify). |
| **schema.org JobPosting on careers *list* pages** | 0 of 100 sampled list pages had it. Job *detail* pages do (see the sitemap reader). |
| **LinkedIn "apply on company site" links to find boards** | LinkedIn hides them unless signed in. |
| **Wikidata for company websites** | Many Indian companies missing, and it rate-limits; recorded `site` values plus checked domain guesses instead. |
| **JioStar (Disney+ Hotstar) Workday; Walmart's new careers site** | JioStar's Workday returns 403 to scripts, so it stays on LinkedIn. Walmart's new site ignores the search and lists US store jobs, but its Workday board (`walmart.wd504`) answers again and is read directly. |

## Sources of companies

- Hand-curated tiers: big tech, Indian product companies, fintech, banks, trading firms, R&D centres, SaaS, AI.
- `import_lists.py`: [moreThanFAANGM](https://github.com/Kaustubh-Natuskar/moreThanFAANGM) (MIT, ~480 product companies with careers links) and [ISJB](https://github.com/pHequals7/isjb) (portfolio companies of Accel, Peak XV, Lightspeed, Nexus, Bessemer, General Catalyst, Blume).
- `discover_ats.py --bank` (board-name guessing, with the company name verified), `--careers` (reads boards from careers URLs and VC apply links). Each new board is checked for India roles and the right company before it's added.
- LinkedIn surfaces unknown companies; their roles go to leads until pay is checked.

## Known limits

- Pay figures are levels.fyi **total comp** (base + stock + bonus), not fixed CTC.
- 17 roles from 8 companies rely on tier judgement (no public salary data): IMC, Citadel Securities, NK Securities, Sarvam, Onehouse, ClickHouse, Hevo, Urban Company.
- ~170 of ~300 shortlisted roles ask "3+ years": allowed by the brief (≤ 3), but stretch roles at ~1.5 years. The dashboard's "Sweet spot only" filter shows the 0–2-year roles with evidenced pay.
- Many good companies currently list only senior roles in India (e.g. Coupang 42, Celonis 27, Roku). They stay in the bank and appear when they post SDE-level roles.
- Companies on Darwinbox (403 to scripts), TurboHire (token-gated), and sites blocked by bot protection, are visible only through LinkedIn.
- The sitemap reader reads at most 150 job pages per company per run, chosen by URL wording (software/engineer/developer…, not senior). A site whose job URLs carry no title words (bare IDs) is read only if it has a search feed (e.g. Jibe).
- Goldman Sachs and Juspay roles have no posting date in their feeds (freshness gets a neutral score). Juspay's links open the careers page, not the single role.
- LinkedIn liveness checks are budgeted; under heavy rate limiting some old postings may age out before being confirmed open.

## Improvement backlog

1. Pay-check the remaining single-lead companies on levels.fyi, recorded in `tiers.json`. Every company with two or more leads was checked on 7 Nov; see `CAREERS_DISCOVERY.md`.
2. More platform readers where discovery finds many companies (counts in `CAREERS_DISCOVERY.md`, "Where we still can't get data"): iCIMS, Phenom; CEIPAL (Simplilearn). Done: Avature, SuccessFactors, Jobvite, Zappyhire, PyjamaHR, Zwayam, RippleHire, MyNextHire.
3. An importer for result pages the user saves from Naukri, Instahyre or Hirist.
4. Use posted salary ranges more (Ashby and some Greenhouse boards publish INR ranges).
5. Track fixed-vs-total comp where sources split it.
6. A small CI job running the test suites on every push to the public repo.
7. Small HTML readers for good payers whose portals put jobs in the page text (Upstox, Media.net, Zerodha).

## Tests

`tests/test_sources.py` covers the Oracle, Eightfold and Rippling readers, every `portals/` reader, board recognition and the discovery helpers, including two regex-speed regressions that once froze discovery. Its weaker checks were found by mutation testing and strengthened. The older fixture-based suites run against a temp folder (never real data), and each was mutation-tested: every fixed bug was reintroduced and the suite failed. They cover filters, Greenhouse and Workday fetching (failures don't abort a board), duplicate detection against today's boards, aliases, the concurrency of the board-title table, company matching, exclusions, LinkedIn expiry and state merging, board-link recognition, and the importer's exclusion rule.
