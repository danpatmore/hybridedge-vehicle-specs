# Routine: lease provider rules and the ATO rate

Run by a Claude scheduled cloud routine at 9am Sydney on the 6th of each
month, and again on 25 March (before the FBT year starts on 1 April) and
25 June (before 1 July). You start with no other context: everything you need
is here and in the files named.

## What you are checking

- `lease-rules-au.json`: what each novated lease provider says about home
  charging claims, as ChargeBack ships it. For each provider: whether it
  offers actual cost (`offersActualCost`), whether it pays home charging for
  plug-in hybrids (`paysPHEVHomeCharging`: true, false, or null when it does
  not say or its pages disagree), whether actual cost needs a dedicated meter
  (`needsDedicatedMeter`), whether the method is fixed for the whole lease
  (`methodFixedForWholeLease`), what it asks for with a claim (`checklist`,
  in the provider's own terms), and `notes` (including the per-km rate the
  provider quotes).
- The ATO EV home charging rate (PCG 2024/2, dollars per km, by FBT year
  starting 1 April). ChargeBack has these built in: 4.20c for the FBT years
  starting 2022 to 2025, and 5.47c for the year starting 1 April 2026. A
  rate for a later year goes into `atoHomeChargingRates` in
  `energy-plans-au.json`, keyed by the FBT start year as a string, value in
  dollars per km (for example `{"2027": <rate>}`), which ChargeBack already
  reads.

## Steps

1. Work out the window: from the `providers` and `ato` dates in
   `checks/last-checked.json` to today. A missed run must lose nothing.
2. Check for an open pull request from an earlier run (branch
   `claude/provider-rules-*`). If there is one, update that branch instead of
   opening another.
3. For every provider in `lease-rules-au.json`: open EACH of its `sources`
   (not just the first), and search the provider's own site for anything newer (EV charging pages,
   claim forms, FAQs). A provider with no sources needs one found, or a note
   saying none is public. Compare what each says with every field. Only the
   provider's own pages and forms count; press and comparison sites do not.
4. For the ATO rate: read the ATO's EV home charging rate page and PCG 2024/2
   on ato.gov.au. A rate counts only when the ATO publishes it, and only a
   page you actually read counts: a search result summary is not the ATO's
   word. ato.gov.au often refuses automated requests (HTTP 403); try the
   page, the ATO's "Rates" pages and the legal database, and if none can be
   read, the ATO has NOT been checked this run (see step 10).
5. If a rule changed: edit `lease-rules-au.json` (the provider's fields,
   `notes`, `sources`, `checked` set to today), bump `version` (minor for a
   change of rule, patch for wording) and set `asOf` to today. Keep the
   existing formatting.
6. If the ATO published a rate ChargeBack doesn't have: add it to
   `atoHomeChargingRates` in `energy-plans-au.json`, placed right after
   `disclaimer`, and change nothing else in that file. Do not bump its
   `version` (the weekly plans job does that within 7 days). Edit it with
   Python, `json.load` then `json.dumps(db, indent=2, ensure_ascii=False)`
   with no trailing newline, so the rest of the file is byte-for-byte the same.
7. Run `python3 tools/check-pr.py <dir with main's files> .` and fix anything
   it reports.
8. If anything changed: commit on `claude/provider-rules-<YYYY-MM-DD>` (or
   the open branch; when it touches `energy-plans-au.json`, redo the change
   on main's current file rather than merging text), push, and open a pull
   request titled `Provider rules <date>: <short summary>`. In the PR text,
   for each change: the provider, what changed, a quote of under 15 words
   from the page, and its link. Say plainly: "Provider rule changes reach
   phones only after ChargeBack's built-in rules are updated in an app
   release (until the app downloads lease-rules-au.json). ATO rate changes
   reach phones without a release." Never merge it.
9. Plans held for review (a separate pull request). `pendingReview` in
   `energy-plans-au.json` lists plans the government feed stopped listing;
   the apps say nothing to owners on them until each is confirmed gone. For
   each held plan not already in `checks/confirm-delisted.json`, look on the
   retailer's own site (its plan list or the plan's own page or fact sheet
   for that state and network; Energy Made Easy or comparison sites do not
   count). Confirm a plan only when the retailer's own site clearly shows it
   is no longer offered: its page is gone or says closed, or the retailer's
   current plan list for that network leaves it out. If you can't tell (the
   page won't load, the site needs an address, or anything is ambiguous),
   leave it held and say so in the PR text. This step is not optional: check
   every held plan, oldest first. If there are too many to finish, check at
   least 20 and say in your reply how many are left. For each plan confirmed, add to
   `plans` in `checks/confirm-delisted.json`:
   `{"key": "<STATE|Provider|identity, built from the pendingReview entry>",
   "name": "<plan name>", "checked": "<today>", "page": "<https link you
   read>", "finding": "<what the page showed, in under 25 words>"}`.
   Change nothing else, and never edit `energy-plans-au.json` for this: once
   the developer merges the PR, the plans job runs the script with these
   confirmations. Run `python3 tools/delisted.py check energy-plans-au.json`
   before pushing. Commit on `claude/delisted-<YYYY-MM-DD>` (or update the
   open one), push, and open a pull request titled
   `Plans confirmed gone <date>: <count>`, listing each plan with its page.
   Say plainly what a merge does. HybridEdge never says a plan ended: once
   a provider's state is certified again, an owner on a confirmed plan gets
   one "Check your <retailer> plan" alert ("Your plan isn't in the current
   list. Check your bill or ask your retailer before changing anything.").
   A provider's state is certified only when NONE of its plans there is
   still held, so confirming some but not all of a retailer's held plans in
   a state notifies nobody yet. Work through each retailer and state as a
   group where you can, and in the PR text list, for each retailer and
   state, how many held plans are confirmed and how many are still held, and
   so which ones a merge would actually certify. If none could be confirmed,
   no PR.
10. Always, last: from current main, make a branch
   `claude/check-log-providers-<YYYY-MM-DD>` that changes only the
   `providers` and `ato` entries of `checks/last-checked.json`, each
   `{"date": "<today, Sydney>", "result": "<one line: PR link, or 'no changes'>"}`,
   commit and push it. A workflow merges it into main. Do not open a PR for it.
   Record only what you really checked. If you could not read the ATO's own
   page, leave the `ato` entry exactly as it is. If you could not read a
   provider's own pages, name it in the `providers` result ("no changes;
   not readable: SG Fleet"), and leave the `providers` entry as it is if you
   could not read most of them. The daily alarm relies on these dates being
   true. When anything could not be checked, also send a push notification
   saying what and why.

## Never

- Merge anything, push to main, or edit workflows or tools.
- Touch plans, `pendingReview` or `completeFor` in `energy-plans-au.json`.
  Delistings go only through `checks/confirm-delisted.json` (step 9).
- Put tester names, support codes or the developer's name in anything you
  write: this repo is public.
