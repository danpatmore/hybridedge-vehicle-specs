#!/usr/bin/env python3
"""
merge-check-log.py: takes a routine's update to checks/last-checked.json and
merges it into main's copy (22 Nov 2026). Routines push it on a
claude/check-log-* branch; .github/workflows/check-log.yml runs this and
commits the result to main. Only dates and short results are accepted, never
a figure the apps use.

Usage: python3 tools/merge-check-log.py MAIN.json BRANCH.json OUT.json

For each dataset (plans, vehicles, providers, ato) the later date wins. An
entry must be {"date": "YYYY-MM-DD", "result": "<up to 300 characters>"},
dated no later than tomorrow. Anything else is refused and nothing is written.
"""

import datetime
import json
import sys

KEYS = ("plans", "vehicles", "providers", "ato")


def entry_problems(name, e, latest):
    if not isinstance(e, dict) or set(e) - {"date", "result"}:
        return [f"{name}: must be {{\"date\": ..., \"result\": ...}} and nothing else"]
    p = []
    try:
        d = datetime.date.fromisoformat(e.get("date", ""))
        if d > latest:
            p.append(f"{name}: date {d} is in the future")
    except (TypeError, ValueError):
        p.append(f"{name}: date {e.get('date')!r} is not YYYY-MM-DD")
    r = e.get("result")
    if not isinstance(r, str) or not r.strip() or len(r) > 300:
        p.append(f"{name}: result must be text of 1 to 300 characters")
    return p


def merge(main, branch, today=None):
    latest = (today or datetime.date.today()) + datetime.timedelta(days=1)
    problems = [f"unexpected key '{k}'" for k in branch if k not in KEYS + ("note",)]
    out = dict(main)
    for k in KEYS:
        if k not in branch or branch[k] == main.get(k):
            continue
        problems += entry_problems(k, branch[k], latest)
        if not problems and branch[k]["date"] >= (main.get(k) or {}).get("date", ""):
            out[k] = branch[k]
    return out, problems


def main():
    main_path, branch_path, out_path = sys.argv[1:4]
    try:
        m, b = json.load(open(main_path)), json.load(open(branch_path))
    except ValueError as e:
        print(f"not valid JSON: {e}")
        raise SystemExit(1)
    out, problems = merge(m, b)
    if problems:
        print("Refused:\n" + "\n".join(f"- {p}" for p in problems))
        raise SystemExit(1)
    open(out_path, "w").write(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print("merged: " + ", ".join(f"{k} {out[k]['date']}" for k in KEYS if k in out))


if __name__ == "__main__":
    main()
