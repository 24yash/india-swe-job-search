# Design notes

How the job-search tool works, the decisions behind it, what was tried and rejected, and what is left to improve. Keep this file updated whenever a decision changes.

## Goal

Find every open software-engineering role in India that fits the profile in `profile.json`: level and title, years asked ≤ `max_min_years`, pay ≥ `min_pay_lpa` (₹ LPA), not a services or staffing firm. Rank the roles, and track applications in a dashboard. Read-only: no logins, no applying, nothing personal sent anywhere.

## Architecture

```
tiers.json (company bank, ~1,200)   companies.json (~250 direct sources + 2 LinkedIn sources)   profile.json (criteria)
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

Supporting tools: `discover_ats.py` (find direct boards), `find_careers.py` (find each company's careers site and the platform behind it; see `CAREERS_DISCOVERY.md`), `import_lists.py` (grow the bank from public lists), `refresh.sh` (fast phase, then LinkedIn in the background).

## Key decisions

| Decision | Why |
|---|---|
| **Read company job boards directly** (Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Amazon, Microsoft, Atlassian, Google) | Complete, current, has the full description, and the apply link is the company's own. A role that disappears from the board has closed. |
| **Read companies' own careers sites** (Oracle Recruiting Cloud, Eightfold, Rippling feeds; `portals/` for custom sites) | A study of 100 board-less companies showed most careers pages load jobs from a public feed. JPMorgan, Apple, Goldman Sachs, Qualcomm, Juspay and others were LinkedIn-only before. Details in `CAREERS_DISCOVERY.md`. |
| **Custom portals: one small module each, plus a configurable job-links reader** | Sites differ too much for one generic scraper, but each needs only ~30 lines. Server-rendered link lists need only config (`portals/links.py`). |
| **Discovery renders careers pages in headless Chrome** | Plain HTML of modern careers pages rarely names the job platform (the list is built by JavaScript); rendering found boards the plain fetch missed. Bounded regexes keep huge pages fast. |
| **LinkedIn public guest search as the second source** | Covers companies with no readable board (Flipkart, Meta, Netflix, Zepto…). In a measured run it supplied 6 of the top 10 roles. |
| **Two speeds** (`--sources fast` vs `linkedin`) | LinkedIn must be slow (rate limits). Company boards give a usable dashboard in ~1 min, and LinkedIn fills in every ~40 postings. |
| **One raw file per source** | A slow or failed source never empties the results; it keeps its last good data. `--rescore` re-filters without the network. |
| **LinkedIn light mode by default**, `--deep` optional | India-wide role searches plus a 40-company sweep give nearly all LinkedIn value. Per-city searches and big sweeps added ~5 roles for hours of crawling. |
| **The company bank never drops a company for being quiet** | Hiring is cyclical. Each run re-checks every company, and `bank-history.json` shows when a quiet one starts hiring. |
| **Pay evidence lives in `tiers.json`** | Levels.fyi blocks scripts (403), so an agent looks pay up with WebFetch and records it once; every run reuses it. Total comp, not fixed CTC. An overall-only median ≥ 30 L counts as likely; 20–30 L stays borderline (overall medians lean senior). `below_title` excludes the levels that pay below the floor (e.g. Mastercard SE-I, BlackRock Analyst). |
| **Pay confidence on every role**: Posted › Strong (levels.fyi) › Likely (tier judgement, with the reason) › Unverified (goes to leads) | Your brief allows "Likely" if the reason is stated. Unverified roles never reach the shortlist. |
| **Experience = the smallest "N+ years" / "N–M years" near experience words; years in the title override** | Lenient on purpose ("2+ required, 5+ preferred" counts as 2). A role with no years stated gets a neutral score, not a rejection. |
| **Experience focus: 0–2 years is the sweet spot; campus hiring excluded** | Every role gets an experience band (0–1, 2, 3 yrs, not stated). A role is a *sweet spot* when it asks ≤ 2 years and its pay is backed by salary data (not a tier judgement). Level score: 1 yr 20, 2 yrs 19, 0 yrs 17, 3 yrs 13. New-grad, graduate, early-career, campus and fresher titles are excluded, as are descriptions that say "campus hiring/drive/placement", "graduating in …", "2026 batch". A duty like "help with campus recruitments" doesn't count (Graviton false positive, fixed with a test). |
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
| **schema.org JobPosting in careers pages** | 0 of 100 sampled careers pages had it; no generic reader built. |
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
- Companies on Darwinbox, Keka, Zoho Recruit, TurboHire, MyNextHire or Kula are visible only through LinkedIn. Darwinbox refuses scripts (403); the others have no reader yet.
- Goldman Sachs and Juspay roles have no posting date in their feeds (freshness gets a neutral score). Juspay's links open the careers page, not the single role.
- LinkedIn liveness checks are budgeted; under heavy rate limiting some old postings may age out before being confirmed open.

## Improvement backlog

1. Pay-check the leads in bulk (an agent loop over levels.fyi, recorded in `tiers.json`), starting with the companies that have the most leads, including the boards discovery added (Citi, Cadence, Emerson, Qualys, BNY…).
2. More platform readers where discovery finds many companies (counts in `CAREERS_DISCOVERY.md`, "Where we still can't get data"): iCIMS, Phenom, Avature, SuccessFactors; and Keka, Zoho Recruit, TurboHire, MyNextHire, Kula if their feeds are public (Darwinbox is not).
3. An importer for result pages the user saves from Naukri, Instahyre or Hirist.
4. Use posted salary ranges more (Ashby and some Greenhouse boards publish INR ranges).
5. Track fixed-vs-total comp where sources split it.
6. A small CI job running the test suites on every push to the public repo.
7. Small HTML readers for good payers whose portals put jobs in the page text (Upstox, Media.net, Zerodha).

## Tests

`tests/test_sources.py` covers the Oracle, Eightfold and Rippling readers, every `portals/` reader, board recognition and the discovery helpers, including two regex-speed regressions that once froze discovery. Its weaker checks were found by mutation testing and strengthened. The older fixture-based suites run against a temp folder (never real data), and each was mutation-tested: every fixed bug was reintroduced and the suite failed. They cover filters, Greenhouse and Workday fetching (failures don't abort a board), duplicate detection against today's boards, aliases, the concurrency of the board-title table, company matching, exclusions, LinkedIn expiry and state merging, board-link recognition, and the importer's exclusion rule.
