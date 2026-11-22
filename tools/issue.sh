#!/usr/bin/env bash
# issue.sh: one GitHub issue per alarm, found by its exact title (22 Nov 2026).
# Run inside GitHub Actions with GH_TOKEN set; uses the gh CLI on the runner.
#
#   issue.sh raise   "<title>" BODY.md   open it, or comment on the open one (notifies)
#   issue.sh refresh "<title>" BODY.md   open it, or quietly replace the open one's text
#   issue.sh clear   "<title>" "<note>"  close the open one with a note, if there is one
set -euo pipefail
mode=$1 title=$2 arg=$3
label=data-refresh
gh label create "$label" --color FBCA04 --description "Scheduled data jobs" >/dev/null 2>&1 || true
num=$(gh issue list --state open --label "$label" --limit 100 --json number,title \
      --jq ".[] | select(.title == \"$title\") | .number" | head -1)
case $mode in
  raise)
    if [ -n "$num" ]; then gh issue comment "$num" --body-file "$arg"
    else gh issue create --title "$title" --label "$label" --body-file "$arg"; fi ;;
  refresh)
    if [ -n "$num" ]; then gh issue edit "$num" --body-file "$arg"
    else gh issue create --title "$title" --label "$label" --body-file "$arg"; fi ;;
  clear)
    if [ -n "$num" ]; then gh issue close "$num" --comment "$arg"; fi ;;
esac
