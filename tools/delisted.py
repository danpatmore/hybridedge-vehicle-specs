#!/usr/bin/env python3
"""
delisted.py: the approved list of plans confirmed gone,
checks/confirm-delisted.json (22 Nov 2026).

  python3 tools/delisted.py args PLANS.json        print one confirmation per line,
                                                   only for plans still held in PLANS.json
  python3 tools/delisted.py prune PLANS.json       drop entries no longer held
  python3 tools/delisted.py check BASE_PLANS.json [LIST.json]
                                                   exit 1 if the list (default: the repo's)
                                                   is malformed or names a plan
                                                   BASE_PLANS.json does not hold

The fetch tool refuses a confirmation of a plan that is not held (one back in
the feed, or already confirmed), so only held ones are passed. An entry needs
the plan's key as the tool prints it ('STATE|Provider|identity'), the date it
was checked, the retailer page read, and what that page showed.
"""

import datetime
import json
import sys
from pathlib import Path

LIST = Path(__file__).resolve().parent.parent / "checks/confirm-delisted.json"


def held(plans_path):
    db = json.load(open(plans_path))
    return {f"{h['state']}|{h['provider']}|{h['identity']}" for h in db.get("pendingReview") or []}


def problems(lst, held_keys):
    p = []
    entries = lst.get("plans")
    if not isinstance(entries, list):
        return ["'plans' missing or not a list"]
    keys = [e.get("key") for e in entries if isinstance(e, dict)]
    if len(keys) != len(set(keys)):
        p.append("a plan is listed twice")
    for e in entries:
        if not isinstance(e, dict):
            p.append(f"not an entry: {e!r}")
            continue
        k = e.get("key")
        if k not in held_keys:
            p.append(f"{k!r} is not held for review on main, so there is nothing to confirm")
        try:
            datetime.date.fromisoformat(e.get("checked", ""))
        except (TypeError, ValueError):
            p.append(f"{k}: 'checked' must be YYYY-MM-DD")
        if not str(e.get("page", "")).startswith("https://"):
            p.append(f"{k}: 'page' must be the https link to the retailer page checked")
        if not str(e.get("finding", "")).strip():
            p.append(f"{k}: 'finding' must say what the page showed")
    return p


def main():
    cmd, plans_path = sys.argv[1], sys.argv[2]
    list_path = Path(sys.argv[3]) if cmd == "check" and len(sys.argv) > 3 else LIST
    lst = json.load(open(list_path)) if list_path.exists() else {"plans": []}
    keys = held(plans_path)
    if cmd == "args":
        for e in lst.get("plans", []):
            if e.get("key") in keys:
                print(e["key"])
    elif cmd == "prune":
        before = len(lst.get("plans", []))
        lst["plans"] = [e for e in lst.get("plans", []) if e.get("key") in keys]
        LIST.write_text(json.dumps(lst, indent=2, ensure_ascii=False) + "\n")
        print(f"confirmations kept: {len(lst['plans'])} of {before}")
    elif cmd == "check":
        p = problems(lst, keys)
        print("\n".join(f"- confirm-delisted: {x}" for x in p) or "confirm-delisted list OK")
        raise SystemExit(1 if p else 0)


if __name__ == "__main__":
    main()
