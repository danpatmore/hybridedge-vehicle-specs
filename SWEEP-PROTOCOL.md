# Specs sweep protocol (monthly-ish)

The database feeds HybridEdge over the air (`VehicleSpecFetcher` pulls this
repo's `phev-specs-au.json`, cached with version checks). New PHEVs launch in
AU near-monthly, so this is a standing maintenance loop. First run: 18 Jul
2026 (v1.7.2 → v1.7.3).

## The loop

1. **Sweep** — ask Claude to run the deep-research vehicle sweep ("run the
   AU PHEV specs sweep"). The research question template lives in
   `Docs/Context/Specs-Sweep-2026-07-18.md` in the HybridEdge repo — scope it
   to makes/models not verified last time, plus anything newly launched.
   Adversarial 3-vote verification against manufacturer AU primary sources;
   ~30-60 min in the background.
2. **Diff** — Claude diffs surviving claims against the current JSON and
   writes a dated curation report (`Docs/Context/Specs-Sweep-<date>.md`):
   corrections, missing vehicles, flagged uncertainties.
3. **Curate** — Dan reviews the report. Rules of the database:
   - Manufacturer primary sources beat press; press beats aggregator.
   - `batteryUsableIsEstimated` stays TRUE until owner-measured (the B5's
     28.6-assumed vs 31.8-measured lesson — spec sheets can't settle
     gross-vs-usable; Chinese brands never label it at all).
   - Chinese-brand EV ranges are NEDC/ADR 81/02 with SoC windows — never
     store them as WLTP. If no WLTP figure exists, the field is null.
   - Blended L/100km (0.9–2.0 type figures) is NOT charge-sustaining — only
     store `fuelConsumptionL100kmDepleted` when a genuine CS figure is
     published (rare; Shark 6's 7.9 is the only one so far).
   - Every changed entry gets a dated note and a source appended. Never a
     number without a source.
   - Pre-launch vehicles wait for AU launch before getting an entry.
4. **Ship** — bump `version` (semver patch for spec fixes, minor for new
   vehicles), set `lastUpdated`, commit, push. Every install picks it up on
   next fetch; no app release needed.

## Backlog (as of 18 Jul 2026)

- Follow-up sweep owed: Mitsubishi Outlander PHEV, MG HS Super Hybrid, Mazda
  CX-60/CX-80, Kia Sorento, Hyundai Santa Fe, Ford Ranger PHEV, Volvo T8s,
  BMW/Mercedes/Audi/VW-group, Jeep 4xe, Land Rover PHEVs (no surviving
  verified claims in the first pass).
- Shark 6 MY26 per-trim figures (840 km combined quoted for some trims;
  first pass verified the single-variant MY25 brochure).
- Omoda 7 PHEV — add at AU launch (~H2 2026): 18.3 kWh LFP, ~90 km WLTP,
  medium confidence pre-launch.
- Sealion 6 MY26 charger figures (carried from MY25, unverified).
- Cannon Alpha fuel tank (75 L is secondary-sourced; GWM doesn't publish).

## Census yardstick

zecar's AU PHEV census (Jun 2026): 35 brands / 50 models / ~90 variants.
Compare each sweep — the gap between census and database is the new-vehicle
to-do list. (zecar's spec pages are JS-rendered; unusable as a source, fine
as a count.)

## Powertrain field (added 20 Jul 2026)

Entries MAY carry `"powertrain": "phev" | "bev" | "reev"`. Absent means
`phev` (the founding population — app-side default). The field exists so
pure EVs can enter this same database when the EVEdge path opens; the app
hides petrol surfaces when `powertrain` is `bev`. Do not backfill the
existing PHEV entries — absence already means phev, and a no-op diff over
80+ entries pollutes blame history.
