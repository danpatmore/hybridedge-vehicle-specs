# Scheduled data jobs

Set up 22 Nov 2026; locked down 23 Nov after Codex rounds 157 and 158.
Everything runs on GitHub's or Anthropic's servers.

| Job | When (Sydney) | How | Result |
|---|---|---|---|
| Electricity plans | Mondays 5am, daily 1 to 7 July, or Run workflow | GitHub Actions, `.github/workflows/plans-weekly.yml` running `tools/fetch-energy-plans.py` then `tools/check-plans.py` | Publishes `energy-plans-au.json` if every check passes; otherwise an issue says why |
| Vehicle sweep | 9am on the 2nd and 16th | Claude routine, following `SWEEP-PROTOCOL.md` | A pull request with a report in `sweeps/` |
| Provider rules and ATO rate | 9am on the 6th, plus 25 March and 25 June | Claude routine | A pull request changing `lease-rules-au.json` or `inputs/ato-home-charging-rates.json` |
| Staleness alarm | 7am daily | GitHub Actions, `tools/check-staleness.py` | One issue if plans are over 14 days, vehicles 45, providers or ATO 60 |
| Settings check | 7:30am daily | GitHub Actions, `tools/settings-check.py` | Reads the ruleset, deploy keys, environments, secrets and Actions' token back from GitHub into its public log; one issue if any differ |
| Data gate | every pull request, and every "approve" comment | GitHub Actions, `tools/gate.py` with `tools/check-pr.py` | The required check `data-gate` (below) |

## The plans file is output only

`energy-plans-au.json` is written by the weekly plans job and nothing else.
No pull request may change it, whoever approves. What people keep by hand
goes in its inputs, which the builder reads and checks on every run:

- `inputs/plans-hand-kept.json`: every plan not from the government feed
  (WA, NT, NZ, Amber, Ergon, retailers' own EV plans, a plan from a bill),
  in the published file's own shape: `states` → `providers` (`name`, optional
  `note`) → `plans`. A plan's id must contain a dash, its source must not be
  the feed, and every per-kWh and feed-in rate must be from 0 to 1.50 dollars.
  The builder puts each provider's hand-kept plans first, before its feed
  plans.
- `inputs/ato-home-charging-rates.json`: `rates` by FBT start year
  (`"2027": <dollars per km>`), each with its ato.gov.au page in `sources`.
  Copied into the plans file as `atoHomeChargingRates`, which ChargeBack
  already reads.
- `checks/confirm-delisted.json`: plans held for review that a retailer's
  own site shows are gone (the monthly provider routine's PR). The next run
  passes them to the builder with `--confirm-delisted`.
- `inputs/plans-options.json`: `skipGstCheckUntil`, null or a date at most
  14 days away, for a week when prices really moved.

The job runs only on its schedule or Run workflow: a merged input change is
published by the next run. `tools/check-plans.py` checks each new list
against the last one and the inputs: the version goes up; a held plan leaves
`pendingReview` only by being listed again or confirmed gone; no certified
scope has a plan held; a plan in a certified scope leaves it only by being
held or confirmed; the hand-kept plans and ATO rates match their inputs.

`tools/fetch-energy-plans.py` is the only copy of the plan builder.
`--keep-from` is for manual recovery only. `ALWAYS_INCLUDE` is in the tool
itself, so changing it is a code change.

## How main is protected

- **Main is locked** (ruleset "Protect main"): every change arrives as a
  pull request, merged with a merge commit, from a branch that is up to date
  with main, and only once the check `data-gate` passes. No force pushes or
  deletion.
- **`data-gate` comes from the developer's own GitHub App**, and the ruleset
  accepts it from that app only. Every workflow reports as "GitHub Actions",
  so a workflow a pull request adds could post a passing check of the same
  name; it can't post as the app, whose key is in the `gate` environment,
  which only main's workflows can use.
- **Nothing merges without the developer's approval comment.** The gate
  gives a phrase on each PR, such as `approve 3f9a1c27d0b4e851`, plus `with
  ...` naming anything a routine must never change, or a change to
  published financial guidance that the developer must read: `tester-log
  keys`, `showCarsWithBlanks`, `hand-kept plans`, `GST check off`,
  `workflows`, `code`, `ATO home-charging rates`, `lease provider rules`
  (the last two list each year or provider, old and new values, and
  sources). It counts only from the repository owner, typed by a person,
  never edited, and when GitHub says no app made it. The Claude app acts as
  the developer, but GitHub marks what it does as made through the app, so a
  routine can open a pull request and never approve one. The code is a hash
  of the PR's changed paths and file contents: any new change needs a new
  approval, but updating the branch from main doesn't unless it changes the
  PR's own files.
- **Rules no approval overrides:** a car id is never removed or changed; the
  car list's version goes up when a car changes; the plans file is never
  edited; data files are never deleted or renamed; every input passes its
  checks (`tools/check-pr.py`).
- **One exception to the lock:** the weekly plans job saves with its own
  deploy key ("Weekly plans job"), held as `PLANS_DEPLOY_KEY` in the
  `publish` environment, which only main can use. The ruleset can only let
  deploy keys through as a group, so the settings check fails if any other
  deploy key is added.
- **GitHub's own token** in every workflow is read-only by default and can't
  create or approve pull requests. There are no repository-level secrets.
- **One commit per decision** (Codex round 159): the gate lists a PR's
  changes with a compare of its base and head commit ids, reads the PR again
  and posts nothing if the head moved, and fetches each data file by the
  blob id in that list. What it checks, what the approval code covers and
  the commit it posts on are always the same commit
  (`tools/test-gate-race.py`).
- **The gate** (`pr-check.yml`) uses `pull_request_target`, so it always
  runs main's copy and never the PR's code. GitHub blocks that trigger in
  public repos from 2 Dec 2026 unless a policy allows it: the Actions policy
  "Allow PR checks from main" allows it for `pr-check.yml` (and the retired
  `pr-ping.yml`, whose ping the gate's own comment now gives) only.
  `gate-approval.yml` uses `issue_comment`, which also always runs main's
  copy.

## Checking the settings yourself

The daily settings check is an alarm, not proof: the gate app can only
read, and GitHub hides the ruleset's bypass list from it. Once a month (the
7th, after the provider routine), and whenever its issue opens, the
developer looks at:

- repo Settings → Rules → Protect main: bypass list "Deploy keys" only;
  `data-gate` from HybridEdge data gate; up to date; merge only;
- repo Settings → Deploy keys: only "Weekly plans job";
- repo Settings → Environments: `gate` and `publish`, each `main` only;
- account Settings → Applications: only Claude and HybridEdge data gate on
  this repo, with the permissions in the round 158 report;
- account Settings → Developer settings → Personal access tokens: only the
  fine-grained push token (Contents write), no classic token;
- account Settings → Security log, the last month: any ruleset, deploy
  key, environment, app or token change the developer didn't make.

## How to send a change

- **Car data, provider rules, ATO rates, confirmations, the check log:** a
  branch and a pull request (routines use `claude/*`). Sessions on the
  developer's Mac push branches only: their token can't open, comment on or
  merge a pull request, so the developer opens each one from the phone
  (`https://github.com/danpatmore/hybridedge-vehicle-specs/pull/new/<branch>`). The developer reads
  it, then replies with the gate's phrase and merges.
- **Tester-log keys, `showCarsWithBlanks`, hand-kept plans, code:** the
  same, from the HybridEdge session or the developer, never a routine. The
  phrase then names what changed, so the developer has to say so to merge.
  `showCarsWithBlanks` is a top-level `true` (or `false`) in
  `phev-specs-au.json`, nowhere else.

`lease-rules-au.json` is not downloaded by ChargeBack yet: an approved
change there needs an app update until the app reads it.
