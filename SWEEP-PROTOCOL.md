# Specs sweep protocol

The database feeds HybridEdge over the air (`VehicleSpecFetcher` pulls this
repo's `phev-specs-au.json`). New PHEVs launch in AU near-monthly, so this is
a standing maintenance loop. First run: 18 Jul 2026 (v1.7.2 → v1.7.3). Since
22 Nov 2026 it runs as a Claude scheduled cloud routine on the 2nd and 16th
of each month, and the developer reviews its pull request.

## The loop

1. **Sweep**: research AU plug-in hybrid (PHEV) and range-extender (REEV)
   models: anything launched, priced or changed since the database was last
   checked (the `vehicles` date in `checks/last-checked.json`, or the newest
   report in `sweeps/`, whichever is older), plus the open items in the newest
   report. Manufacturer AU primary sources first; check each claim against a
   second source before it counts.
2. **Report**: write a dated curation report, `sweeps/Vehicle-Sweep-<date>.md`,
   in the style of the earlier ones: what is ready to add, what is blocked and
   by which missing figure, corrections to existing rows, what is coming, and
   a numbered source list.
3. **Curate**: apply only changes that meet every rule below, in a branch,
   and open a pull request with the report. The developer reviews it in the
   GitHub app. Never merged automatically. An automatic check
   (`tools/check-pr.py`) runs on the PR and backs up the review.
4. **Ship**: on merge, every install picks it up within a day; no app release
   needed. There is no version check on the car list, so the review is the
   only gate.

## Rules of the database

- Manufacturer primary sources beat press; press beats aggregator.
- `batteryUsableIsEstimated` stays TRUE until owner-measured (the B5's
  28.6-assumed vs 31.8-measured lesson: spec sheets can't settle
  gross-vs-usable; Chinese brands never label it at all).
- Chinese-brand EV ranges are NEDC/ADR 81/02 with SoC windows: never store
  them as WLTP. If no WLTP figure exists, the field is null.
- Blended L/100km (0.9–2.0 type figures) is NOT charge-sustaining: only
  store `fuelConsumptionL100kmDepleted` when a genuine CS figure is published
  (rare; Shark 6's 7.9 is the only one so far).
- Every changed entry gets a dated note and a source appended. Never a
  number without a source.
- Pre-launch vehicles wait for AU launch before getting an entry.
- Unknown is null, never another car's number.
- `kerbMassKg` is kerb mass, not GVM or tare. EU figures include a 75 kg
  driver: say which convention in the note.
- Never change or reuse a car's `id`, and never delete a car. Phones store
  the id for the active car, calibration, tyres, backups and household sync.
  A car no longer sold stays for its owners.
- Never add, change or remove the keys that come from tester logs, not web
  research: `packSoC`, `udsFallbackHeader`, `calibrationSeeds`,
  `socCalibrationSlope`, `socCalibrationIntercept`, `socNotReadable`,
  `quietOnKeyOff`, `fullScaleFuelPct`, `petrolFromEngine`,
  `petrolFromFuelFlow`, `fuelSenderLine`. A value present in the download
  always beats the app's own copy, so a wrong one here is worse than none.
- A new car with a blank in a field build 242 made optional (chemistry,
  battery warranty, AC rating, phases, plug, home-charge hours, engine cc and
  cylinders) is hidden on phones until `showCarsWithBlanks` is on. The PR
  lists those cars, so the developer knows what a merge actually shows.
- Never add `showCarsWithBlanks`. The developer flips it by hand, and only
  after 1.0.2 is in the App Store, 5 Dec 2026 has passed and old TestFlight
  builds have expired: it unhides cars with blanks on every phone within a day.
- Bump `version` (patch for spec fixes, minor for new vehicles) and set
  `lastUpdated` whenever a car changes. Both are required strings, or every
  phone silently keeps its old copy.
- This repo is public: no tester names, support codes or the developer's
  name in notes, reports, commits or PRs.

## What each scheduled run leaves

- Always: a `claude/check-log-<date>` branch that changes only the
  `vehicles` entry of `checks/last-checked.json`
  (`{"date": "YYYY-MM-DD", "result": "<one line>"}`). A workflow checks it and
  merges it into main, so the daily staleness alarm knows the sweep ran even
  when nothing changed.
- When something changed: one pull request with the data change and the
  report. If an earlier sweep PR is still open, update that one instead of
  opening another, brought up to date with main.

## Backlog

The current to-do lists are in the newest report in `sweeps/` (from
10 Nov 2026: `sweeps/Vehicle-Sweep-2026-11-10.md`).

## Census yardstick

zecar's AU PHEV census (Jun 2026): 35 brands / 50 models / ~90 variants.
Compare each sweep: the gap between census and database is the new-vehicle
to-do list. (zecar's spec pages are JS-rendered; unusable as a source, fine
as a count.) The FCAI half-year per-model list (via Drive) is the other
completeness check.

## Powertrain field (added 20 Jul 2026)

Entries MAY carry `"powertrain": "phev" | "bev" | "reev"`. Absent means
`phev` (the founding population, app-side default). The field exists so
pure EVs can enter this same database when the EVEdge path opens; the app
hides petrol surfaces when `powertrain` is `bev`. Do not backfill the
existing PHEV entries: absence already means phev, and a no-op diff over
80+ entries pollutes blame history.
