# Routine: fortnightly vehicle sweep

Run by a Claude scheduled cloud routine on the 2nd and 16th of each month
(9am Sydney). You start with no other context: everything you need is here,
in `SWEEP-PROTOCOL.md` and in the newest report in `sweeps/`.

## Steps

1. Read `SWEEP-PROTOCOL.md` in full. Its rules are not optional.
2. Work out the window: from the `vehicles` date in
   `checks/last-checked.json` or the newest report in `sweeps/`, whichever is
   older, to today. A missed run must lose nothing, so never start from "the
   last run" alone.
3. Check for an open pull request from an earlier sweep (branch
   `claude/vehicle-sweep-*`). If there is one, you will update that branch
   instead of opening another.
4. Research, with web search and reading pages:
   - AU PHEV and REEV launches, pricing and spec changes in the window
   - the open items in the newest report (blocked cars, coming cars, rows
     flagged for correction)
   - a completeness check against the newest FCAI or VFACTS per-model list
   Manufacturer AU pages first. A figure needs its source; one outlet alone
   is "single" and stays out unless it is the maker. Never use another car's
   figure for a blank.
5. Write `sweeps/Vehicle-Sweep-<YYYY-MM-DD>.md` in the style of the newest
   one, with a numbered source list (URLs, and the date read).
6. Apply only the changes that meet every rule in `SWEEP-PROTOCOL.md` to
   `phev-specs-au.json`: dated note and source on every changed entry,
   `version` bumped (patch for fixes, minor for new cars), `lastUpdated` set
   to today. Keep the file's existing formatting so the diff shows only real
   changes. Do not touch ids or the tester-log keys, and never add
   `showCarsWithBlanks`.
7. Run `python3 tools/check-pr.py <dir with main's files> .` before pushing
   and fix anything it reports. It must list nothing under "Needs your word": those
   are changes only the developer makes.
8. If anything changed: commit on `claude/vehicle-sweep-<YYYY-MM-DD>` (or
   the open sweep branch, brought up to date with main), push, and open a
   pull request titled `Vehicle sweep <date>: <short summary>`. The PR text:
   a plain-language summary of each change with its source, what is held and
   why, and a link to the report. Also list every new car that has a blank
   (null) in any of `batteryChemistry`, the battery warranty fields,
   `acChargerKW`, `acChargerPhases`, `acPlugType`, `estimatedHomeChargeHours`,
   `engineCC` or `engineCylinders`: phones on build 242 and later hide such
   cars until the developer turns on `showCarsWithBlanks`, so a merge does
   not put them in front of owners yet. Never merge it.
9. Always, last: from current main, make a branch
   `claude/check-log-vehicles-<YYYY-MM-DD>` that changes only the `vehicles`
   entry of `checks/last-checked.json` to
   `{"date": "<today, Sydney>", "result": "<one line: PR link, or 'no changes'>"}`,
   commit and push it, and open a pull request titled
   `Check log: vehicles <date>` for the developer to merge. Never merge it.

## Never

- Merge anything, push to main, or edit workflows or tools.
- Comment "approve" (or anything like the data gate's phrase) on a pull
  request. Only the developer approves, and the gate ignores a comment made
  through the Claude app anyway.
- Put tester names, support codes or the developer's name in anything you
  write: this repo is public.
- Change `energy-plans-au.json`, `lease-rules-au.json` or anything in `inputs/`.
