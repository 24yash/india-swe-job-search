---
name: job-search
description: Find software-engineering openings in India that match the user's requirements, then open the job dashboard. Use when the user asks to "find jobs", "run the job search", "refresh the job list/dashboard", or wants to set up their job-search profile.
---

# Job search

Work from the repo root. **Read-only:** never apply, sign in, message recruiters or submit forms, and never send the user's personal details to any site.

## 1. Requirements → `profile.json`

If the user hasn't set up `profile.json` yet (it still says "Shipped as an example"), or wants changes, ask in one message:
- target roles (e.g. backend, platform, full-stack) and level;
- the most "years required" they'll accept;
- cities or remote;
- minimum pay in ₹ LPA;
- main stack and skills, plus skills they lack;
- companies to exclude, **including their current employer**.

Write the answers into `profile.json`: `title.include` / `title.exclude`, `max_min_years`, `min_pay_lpa`, `linkedin.locations`, `stack` (`[label, regex, weight]`, Java-style weights 1–7), `gaps`, `exclude_companies`. Replace the `_comment` "Shipped as an example" text. Don't put the user's name, employer or any other personal detail anywhere else in the repo.

## 2. Crawl

```bash
./refresh.sh
```

- **Fast phase (~1 min):** crawls every company job board, then rebuilds `output/jobs-<date>.csv`, the leads, the company bank and `dashboard.html`.
- **LinkedIn phase:** starts in the background (light mode, ~5–15 min). It rebuilds the dashboard every ~40 postings; progress is in `output/linkedin.log`.

Use `python3 crawl.py --sources linkedin --deep` (hours) only if the user asks for an exhaustive sweep. **Don't wait for LinkedIn before showing the user results.** If LinkedIn rate-limits (429), it stops itself and keeps the earlier data. That's expected; don't retry straight away.

## 3. (Optional, recommended) Pay evidence for new companies

`output/leads-unverified-pay-<date>.csv` holds roles from companies with no pay evidence. For the top ~20 companies by score:
1. Fetch `https://www.levels.fyi/companies/<slug>/salaries/software-engineer/locations/india.md` with your web-fetch tool; scripts get HTTP 403.
2. Record it in `tiers.json` → `known`:
   - `pay: "likely"` with `pay_note: "Levels.fyi India <level> median TC <x> LPA"` if the entry-level median is at or above the floor;
   - `pay: "below"` if it's under the floor;
   - otherwise leave it `unclear`.

   Use `below_title` (a regex) when only some levels fall below the floor.
3. Run `python3 crawl.py --rescore`.

## 3b. (Monthly) Find direct job boards for the bank

`python3 discover_ats.py --bank` (about 5 min) tries likely board names for every good or unclear-pay company that has no direct board, across Greenhouse, Lever, Ashby and SmartRecruiters (Workable and Recruitee hits are reported but marked "(no crawler yet: don't add)", because `crawl.py` can't read them yet). It writes `output/discovered-boards.json`. Keep only hits with India postings whose name is verified, or whose postings mention the company (slugs can belong to a different company with the same name). Never add the user's own employer. Add the good ones to `companies.json` (`ats` and `slug`, plus type, quality and pay copied from `tiers.json`). Direct boards are faster, fresher and give the company's own apply link.

## 4. Finish: open the dashboard

Right after the fast phase, tell the user the headline numbers: roles, leads, companies hiring, and any "hiring now (new since last run)". Then open the dashboard:

```bash
open dashboard.html        # macOS
xdg-open dashboard.html    # Linux
start dashboard.html       # Windows
```

Tell them LinkedIn results keep arriving in the background, so reload the page later. Remind them that their Applied/comment marks are saved in that browser and carry over to future refreshes, and to use **Export marks** for a backup.
