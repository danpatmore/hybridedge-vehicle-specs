#!/usr/bin/env python3
"""
check-pr.py: the automatic check on every pull request that changes a data
file (22 Nov 2026). It backs up the developer's review; it does not replace it.

Usage: python3 tools/check-pr.py BASE_DIR HEAD_DIR [--summary FILE]
BASE_DIR holds main's files, HEAD_DIR the pull request's.

phev-specs-au.json (HybridEdge has no version check on the car list, so
whatever is merged reaches every phone within a day):
  - valid JSON, with version and lastUpdated as strings
  - car ids unique; no id on main changed or removed
  - the keys that come from tester logs match main exactly (compared with
    main, not a fixed list, because those keys are still pushed straight to
    main by hand)
  - no showCarsWithBlanks anywhere
  - version higher than main's when any car changed
energy-plans-au.json: the apps can still read it, and every per-kWh rate is
  between 0c and $1.50.
lease-rules-au.json: valid JSON, version and asOf strings, provider ids
  unique, and every provider with a rule has a source or says why not.
"""

import importlib.util
import json
import sys
from pathlib import Path

TESTER_LOG_KEYS = ("packSoC", "udsFallbackHeader", "calibrationSeeds", "socCalibrationSlope",
                   "socCalibrationIntercept", "socNotReadable", "quietOnKeyOff", "fullScaleFuelPct",
                   "petrolFromEngine", "petrolFromFuelFlow", "fuelSenderLine")


def _load_tool(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).resolve().parent / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read(path):
    """(data, problem): None data when the file is absent."""
    if not path.exists():
        return None, None
    try:
        return json.load(open(path)), None
    except ValueError as e:
        return None, f"{path.name} is not valid JSON ({e})"


def vtuple(v):
    return tuple(int(x) for x in str(v).split("."))


def has_key(obj, key):
    if isinstance(obj, dict):
        return key in obj or any(has_key(v, key) for v in obj.values())
    if isinstance(obj, list):
        return any(has_key(v, key) for v in obj)
    return False


def check_specs(base, head):
    p = []
    for k in ("version", "lastUpdated"):
        if not isinstance(head.get(k), str):
            p.append(f"car list: '{k}' missing or not a string (every phone would keep its old list)")
    cars = head.get("vehicles")
    if not isinstance(cars, list):
        return p + ["car list: 'vehicles' missing or not a list"]
    ids = [c.get("id") for c in cars]
    dupes = sorted({i for i in ids if ids.count(i) > 1}, key=str)
    if dupes:
        p.append(f"car list: duplicate ids {dupes}")
    if has_key(head, "showCarsWithBlanks"):
        p.append("car list: showCarsWithBlanks must not be added here (the developer flips it by hand)")
    if base:
        old = {c.get("id"): c for c in base.get("vehicles", [])}
        new = {c.get("id"): c for c in cars}
        gone = [i for i in old if i not in new]
        if gone:
            p.append(f"car list: car ids removed or changed (phones store them): {gone}")
        for i, oc in old.items():
            nc = new.get(i)
            if nc is None:
                continue
            for k in TESTER_LOG_KEYS:
                if (k in oc, oc.get(k)) != (k in nc, nc.get(k)):
                    p.append(f"car list: {oc.get('make')} {oc.get('model')} {oc.get('variant') or ''} ({i}): "
                             f"'{k}' differs from main (tester-log keys are never changed in a sweep)")
        for i, nc in new.items():
            if i not in old:
                added = [k for k in TESTER_LOG_KEYS if k in nc]
                if added:
                    p.append(f"car list: new car {i} carries tester-log keys {added}")
        if base.get("vehicles") != cars:
            try:
                if vtuple(head.get("version")) <= vtuple(base.get("version")):
                    p.append(f"car list: cars changed but version {head.get('version')} is not higher than {base.get('version')}")
            except ValueError:
                p.append("car list: version could not be compared")
    return p


def check_plans(head):
    tool = _load_tool("check-plans")
    p = [f"plans: the apps could not read it: {x}" for x in tool._tool.validate(head)[:20]]
    for (st, ident), pl in tool.plans(head).items():
        for r in tool.unit_rates(pl):
            if not isinstance(r, (int, float)) or r < 0 or r > tool.MAX_RATE:
                p.append(f"plans: {st} {pl.get('name')}: rate {r!r} outside 0c to ${tool.MAX_RATE:.2f}")
    return p


def check_rules(head):
    p = []
    for k in ("version", "asOf"):
        if not isinstance(head.get(k), str):
            p.append(f"provider rules: '{k}' missing or not a string")
    provs = head.get("providers")
    if not isinstance(provs, list):
        return p + ["provider rules: 'providers' missing or not a list"]
    ids = [x.get("id") for x in provs]
    if len(ids) != len(set(ids)):
        p.append("provider rules: duplicate provider ids")
    for x in provs:
        if not x.get("sources") and not x.get("notes"):
            p.append(f"provider rules: {x.get('id')} has no source and no note saying why")
    return p


def main():
    args = sys.argv[1:]
    summary = None
    if "--summary" in args:
        i = args.index("--summary")
        summary = args[i + 1]
        del args[i:i + 2]
    base_dir, head_dir = Path(args[0]), Path(args[1])
    problems, checked = [], []
    for name, fn in (("phev-specs-au.json", "specs"), ("energy-plans-au.json", "plans"),
                     ("lease-rules-au.json", "rules")):
        base, bp = read(base_dir / name)
        head, hp = read(head_dir / name)
        if hp:
            problems.append(hp)
            continue
        if head is None or head == base:
            continue
        checked.append(name)
        if fn == "specs":
            problems += check_specs(base, head)
        elif fn == "plans":
            problems += check_plans(head)
        else:
            problems += check_rules(head)
    text = (f"Checked: {', '.join(checked) or 'no data file changed'}.\n\n"
            + ("**Problems:**\n" + "\n".join(f"- {x}" for x in problems) if problems else "All checks passed.")
            + "\n")
    print(text)
    if summary:
        Path(summary).write_text(text)
    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    main()
