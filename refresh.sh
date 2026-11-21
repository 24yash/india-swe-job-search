#!/bin/zsh
# Refresh the job data and dashboard in two speeds:
#   1. company job boards (~1 min), then the shortlist and dashboard are rebuilt;
#   2. LinkedIn in the background (light mode, ~5-15 min; add --deep to the crawl for an hours-long full sweep). It rebuilds the dashboard every ~40 postings, so just
#      reload dashboard.html to see it fill in. Progress goes to output/linkedin.log.
# Your Applied/comment marks live in the browser and carry over (keyed by job link, plus a
# company + title + location match for reposts).
set -e
cd "${0:A:h}"
# Both passes write files dated the day the refresh started, even when LinkedIn finishes after midnight.
export JOB_SEARCH_DATE="$(date +%F)"  # always today: a value left in the shell from a --rescore must not pin later runs
python3 crawl.py --sources fast
if pgrep -f "crawl.py --sources linkedin" >/dev/null; then
  echo "A LinkedIn crawl is already running; not starting another."
else
  nohup python3 crawl.py --sources linkedin > output/linkedin.log 2>&1 &
  echo "LinkedIn crawl started in the background (pid $!); progress: tail -f output/linkedin.log"
fi
echo "Dashboard ready: open dashboard.html (reload it later to see LinkedIn results)."
