#!/usr/bin/env python3
"""
check-staleness.py: the daily alarm (22 Nov 2026). Exits 1 if any dataset
has gone unchecked longer than its limit, with a short markdown report.

Usage: python3 tools/check-staleness.py [--today YYYY-MM-DD] [--summary FILE]

A dataset's age runs from the later of the date inside its own file and the
date the scheduled job last checked it (checks/last-checked.json), so a
quiet month with nothing to change does not set the alarm off. Today is the
Sydney date.
"""

import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIMITS = {"plans": 14, "vehicles": 45, "providers": 60, "ato": 60}
NAMES = {"plans": "Electricity plans", "vehicles": "Vehicle specs",
         "providers": "Lease provider rules", "ato": "ATO home charging rate"}
FIX = {"plans": "The weekly plans job (Actions tab, \"Electricity plans (weekly)\") has not published. Its last run says why.",
       "vehicles": "The fortnightly vehicle routine has not logged a check. See claude.ai/code/routines.",
       "providers": "The monthly provider and ATO routine has not logged a check. See claude.ai/code/routines.",
       "ato": "The monthly provider and ATO routine has not logged a check. See claude.ai/code/routines."}


def sydney_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Australia/Sydney")).date()
    except Exception:
        return (datetime.datetime.utcnow() + datetime.timedelta(hours=10)).date()


def day(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def last_checked(root=ROOT):
    """{dataset: (date, where)}, the later of the file's own date and the log's."""
    def load(name):
        try:
            return json.load(open(root / name))
        except (OSError, ValueError):
            return {}
    log = load("checks/last-checked.json")
    own = {"plans": load("energy-plans-au.json").get("asOf"),
           "vehicles": load("phev-specs-au.json").get("lastUpdated"),
           "providers": load("lease-rules-au.json").get("asOf"),
           "ato": None}
    out = {}
    for k in LIMITS:
        dates = [(day(own[k]), "data file"), (day((log.get(k) or {}).get("date")), "check log")]
        dates = [d for d in dates if d[0]]
        out[k] = max(dates) if dates else (None, "nowhere")
    return out


def report(today, checked):
    stale, lines = [], []
    for k, limit in LIMITS.items():
        d, where = checked[k]
        age = (today - d).days if d else None
        ok = age is not None and age <= limit
        lines.append(f"| {NAMES[k]} | {d or 'never'} ({where}) | {'?' if age is None else age} days | {limit} days | {'OK' if ok else '**out of date**'} |")
        if not ok:
            stale.append(k)
    text = [f"Checked {today} (Sydney).", "",
            "| Data | Last checked | Age | Limit | |", "|---|---|---|---|---|"] + lines
    if stale:
        text += ["", "**What to look at:**"] + [f"- {NAMES[k]}: {FIX[k]}" for k in stale]
    return stale, "\n".join(text) + "\n"


def main():
    args = sys.argv[1:]
    today, summary = sydney_today(), None
    if "--today" in args and args[args.index("--today") + 1]:
        today = datetime.date.fromisoformat(args[args.index("--today") + 1])
    if "--summary" in args:
        summary = args[args.index("--summary") + 1]
    stale, text = report(today, last_checked())
    print(text)
    if summary:
        Path(summary).write_text(text)
    raise SystemExit(1 if stale else 0)


if __name__ == "__main__":
    main()
