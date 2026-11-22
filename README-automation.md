# Scheduled data jobs

Set up 22 Nov 2026. Everything runs on GitHub's or Anthropic's servers.

| Job | When (Sydney) | How | Result |
|---|---|---|---|
| Electricity plans | Mondays 5am, and daily 1 to 7 July | GitHub Actions, `.github/workflows/plans-weekly.yml` running `tools/fetch-energy-plans.py` then `tools/check-plans.py` | Publishes `energy-plans-au.json` if every check passes; otherwise an issue says why |
| Vehicle sweep | 9am on the 2nd and 16th | Claude routine, following `SWEEP-PROTOCOL.md` | A pull request with a report in `sweeps/`, never merged automatically |
| Provider rules and ATO rate | 9am on the 6th, plus 25 March and 25 June | Claude routine | A pull request changing `lease-rules-au.json` or `atoHomeChargingRates` in the plans file |
| Staleness alarm | 7am daily | GitHub Actions, `tools/check-staleness.py` | One issue if plans are over 14 days, vehicles 45, providers or ATO 60 |
| PR check | every data pull request | GitHub Actions, `tools/check-pr.py` | Fails a PR that breaks a database rule |
| Check log | when a routine finishes | GitHub Actions, `tools/merge-check-log.py` | Merges the routine's `claude/check-log-*` branch (dates only) into `checks/last-checked.json` |

`tools/fetch-energy-plans.py` is the only copy of the plan builder. Hand
edits to plans (WA and NT, `ALWAYS_INCLUDE`) go here. `--keep-from` is for
manual recovery only. A plan the feed stops listing is held in
`pendingReview` and confirmed gone only with `--confirm-delisted`, never by
editing the file. The monthly provider routine checks held plans on the
retailers' own sites and opens a pull request adding the ones really gone to
`checks/confirm-delisted.json`; once merged, the plans job runs the script
with those confirmations and drops each from the list once it is no longer
held (`tools/delisted.py`).

`lease-rules-au.json` is not downloaded by ChargeBack yet: an approved
change there needs an app update until the app reads it. ATO rates go in
`atoHomeChargingRates` in `energy-plans-au.json` (keyed by FBT start year,
as `"2027": <dollars per km>`), which ChargeBack already reads.
