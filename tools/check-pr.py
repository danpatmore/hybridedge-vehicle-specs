#!/usr/bin/env python3
"""
check-pr.py: the automatic check on every pull request that changes a data
file (22 Nov 2026). It backs up the developer's review; it does not replace it.

Usage: python3 tools/check-pr.py BASE_DIR HEAD_DIR [--summary FILE] [--allow-tester-log]
       python3 tools/check-pr.py --selftest
BASE_DIR holds main's data files, HEAD_DIR the pull request's (same layout,
checks/ included). The gate workflow (.github/workflows/pr-check.yml) runs
main's copy of this file on data copied out of the PR, never the PR's code
(Codex round 157).

phev-specs-au.json (HybridEdge has no version check on the car list, so
whatever is merged reaches every phone within a day):
  - valid JSON, with version and lastUpdated as strings
  - car ids unique; no id on main changed or removed
  - the keys that come from tester logs match main exactly (compared with
    main, not a fixed list, because those keys change on tester evidence).
    --allow-tester-log lets them change: the gate passes it only for a
    branch in this repo that is not a routine's (claude/*), which is how the
    HybridEdge session sends tester-log updates now main is locked. The
    summary still lists every such change for the developer's review.
  - no showCarsWithBlanks anywhere
  - version higher than main's when any car changed
energy-plans-au.json: the apps can still read it, and every per-kWh rate is
  between 0c and $1.50.
lease-rules-au.json: valid JSON, version and asOf strings, provider ids
  unique, and every provider with a rule has a source or says why not.
checks/last-checked.json: only dated, short results (tools/merge-check-log.py).
checks/confirm-delisted.json: every entry well formed and held on main
  (tools/delisted.py).
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


def check_specs(base, head, allow_tester_log=False, notes=None):
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
                    car = f"{oc.get('make')} {oc.get('model')} {oc.get('variant') or ''} ({i})"
                    if allow_tester_log:
                        notes.append(f"car list: {car}: tester-log key '{k}' changed; check it matches the tester's log")
                    else:
                        p.append(f"car list: {car}: '{k}' differs from main (tester-log keys are never changed in a sweep)")
        for i, nc in new.items():
            if i not in old:
                added = [k for k in TESTER_LOG_KEYS if k in nc]
                if added and allow_tester_log:
                    notes.append(f"car list: new car {i} carries tester-log keys {added}; check they match the tester's log")
                elif added:
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


DATA_FILES = ("phev-specs-au.json", "energy-plans-au.json", "lease-rules-au.json",
              "checks/last-checked.json", "checks/confirm-delisted.json")


def check_log(base, head):
    _, p = _load_tool("merge-check-log").merge(base or {}, head)
    return [f"check log: {x}" for x in p]


def check_confirmations(head, base_dir):
    plans = base_dir / "energy-plans-au.json"
    if not plans.exists():
        return ["confirmations: main has no plans file to check them against"]
    tool = _load_tool("delisted")
    return [f"confirmations: {x}" for x in tool.problems(head, tool.held(plans))]


def check_dirs(base_dir, head_dir, allow_tester_log=False, notes=None):
    """(problems, files checked). Allowed tester-log changes go in notes."""
    problems, checked = [], []
    notes = [] if notes is None else notes
    for name in DATA_FILES:
        base, bp = read(base_dir / name)
        head, hp = read(head_dir / name)
        if hp:
            problems.append(hp)
            continue
        if head is None or head == base:
            continue
        checked.append(name)
        if name == "phev-specs-au.json":
            problems += check_specs(base, head, allow_tester_log, notes)
        elif name == "energy-plans-au.json":
            problems += check_plans(head)
        elif name == "lease-rules-au.json":
            problems += check_rules(head)
        elif name == "checks/last-checked.json":
            problems += check_log(base, head)
        else:
            problems += check_confirmations(head, base_dir)
    return problems, checked


def main():
    args = sys.argv[1:]
    summary = None
    if "--summary" in args:
        i = args.index("--summary")
        summary = args[i + 1]
        del args[i:i + 2]
    allow = "--allow-tester-log" in args
    if allow:
        args.remove("--allow-tester-log")
    base_dir, head_dir = Path(args[0]), Path(args[1])
    notes = []
    problems, checked = check_dirs(base_dir, head_dir, allow, notes)
    text = (f"Checked: {', '.join(checked) or 'no data file changed'}.\n\n"
            + ("**Problems:**\n" + "\n".join(f"- {x}" for x in problems) if problems else "All checks passed.")
            + "\n")
    if notes:
        text += "\n**Tester-log changes to review:**\n" + "\n".join(f"- {x}" for x in notes) + "\n"
    print(text)
    if summary:
        Path(summary).write_text(text)
    raise SystemExit(1 if problems else 0)


def selftest():
    """The gate's own cases (Codex round 157's outside runner, made part of the
    repo), each run against a changed copy of this repo's current data."""
    import copy
    import shutil
    import tempfile
    root = Path(__file__).resolve().parent.parent
    tmp = Path(tempfile.mkdtemp())
    base = tmp / "base"
    for name in DATA_FILES:
        if (root / name).exists():
            (base / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(root / name, base / name)
    specs = json.load(open(base / "phev-specs-au.json"))
    plans = json.load(open(base / "energy-plans-au.json"))
    log = json.load(open(base / "checks/last-checked.json"))
    results = []

    def case(label, expect_fail, must=None, files=None, raw=None, allow=False, note=None):
        d = tmp / f"case{len(results)}"
        shutil.copytree(base, d)
        for name, obj in (files or {}).items():
            (d / name).write_text(json.dumps(obj, indent=1))
        for name, text in (raw or {}).items():
            (d / name).write_text(text)
        notes = []
        p, _ = check_dirs(base, d, allow, notes)
        ok = bool(p) == expect_fail and (must is None or must.lower() in " ".join(p).lower())
        ok = ok and (note is None or note.lower() in " ".join(notes).lower())
        results.append((ok, label, p[:1]))

    def cars(edit, bump=True):
        s = copy.deepcopy(specs)
        edit(s)
        if bump:
            s["version"] = "999.0.0"
        return {"phev-specs-au.json": s}

    case("nothing changed", False)
    case("a car removed", True, "removed", cars(lambda s: s["vehicles"].pop(0)))
    case("a car id changed", True, "removed", cars(lambda s: s["vehicles"][5].update(id="00000000-0000-0000-0000-000000000000")))
    case("a duplicate id", True, "duplicate", cars(lambda s: s["vehicles"].append(copy.deepcopy(s["vehicles"][3]))))
    case("a tester-log key removed", True, "petrolFromFuelFlow",
         cars(lambda s: [v.pop("petrolFromFuelFlow", None) for v in s["vehicles"]]))
    case("a tester-log key changed", True, "packSoC",
         cars(lambda s: next(v for v in s["vehicles"] if v.get("packSoC")).update(packSoC={"changed": True})))
    case("a new car carrying tester-log keys", True, "tester-log",
         cars(lambda s: s["vehicles"].append(dict(copy.deepcopy(next(v for v in s["vehicles"] if v.get("packSoC"))), id="NEW-ID-1"))))
    case("a tester-log key changed in a developer PR", False, None,
         cars(lambda s: next(v for v in s["vehicles"] if v.get("packSoC")).update(packSoC={"changed": True})),
         allow=True, note="packSoC")
    case("a new car carrying tester-log keys in a developer PR", False, None,
         cars(lambda s: s["vehicles"].append(dict(copy.deepcopy(next(v for v in s["vehicles"] if v.get("packSoC"))), id="NEW-ID-1"))),
         allow=True, note="NEW-ID-1")
    case("a car removed in a developer PR", True, "removed", cars(lambda s: s["vehicles"].pop(0)), allow=True)
    case("showCarsWithBlanks in a developer PR", True, "showCarsWithBlanks",
         cars(lambda s: s.update(showCarsWithBlanks=True)), allow=True)
    case("showCarsWithBlanks added", True, "showCarsWithBlanks", cars(lambda s: s.update(showCarsWithBlanks=True)))
    case("a car changed, version not bumped", True, "version",
         cars(lambda s: s["vehicles"][10].update(notes=(s["vehicles"][10].get("notes") or "") + " x"), bump=False))
    case("a car note changed, version bumped", False, None,
         cars(lambda s: s["vehicles"][10].update(notes=(s["vehicles"][10].get("notes") or "") + " x")))
    case("lastUpdated dropped", True, "lastUpdated", cars(lambda s: s.pop("lastUpdated")))
    case("invalid JSON", True, "json", raw={"phev-specs-au.json": "{ not json"})
    p2 = copy.deepcopy(plans)
    p2["states"][0]["providers"][0]["plans"][0]["flatRatePerKWh"] = 2.5
    case("a plan rate of $2.50", True, "outside", {"energy-plans-au.json": p2})
    p3 = copy.deepcopy(plans)
    p3.pop("states")
    case("a plans file the apps cannot read", True, "could not read", {"energy-plans-au.json": p3})
    l1 = copy.deepcopy(log)
    l1["vehicles"] = {"date": str(__import__("datetime").date.today()), "result": "no changes"}
    case("a check log with a dated result", False, None, {"checks/last-checked.json": l1})
    l2 = copy.deepcopy(log)
    l2["vehicles"] = {"date": "2026-11-22", "result": "x", "version": "9.9.9"}
    case("a check log entry carrying a figure", True, "vehicles", {"checks/last-checked.json": l2})
    l3 = copy.deepcopy(log)
    l3["kerbMassKg"] = 1
    case("a check log with an unexpected key", True, "unexpected", {"checks/last-checked.json": l3})
    held = plans.get("pendingReview") or []
    if held:
        k = f"{held[0]['state']}|{held[0]['provider']}|{held[0]['identity']}"
        good = {"key": k, "checked": "2026-11-22", "page": "https://example.com/plan", "finding": "not offered"}
        case("a confirmation of a held plan", False, None, {"checks/confirm-delisted.json": {"plans": [good]}})
        case("a confirmation of a plan main does not hold", True, "not held",
             {"checks/confirm-delisted.json": {"plans": [dict(good, key="NSW|Nobody|xyz123abc")]}})
        case("a confirmation with no https page", True, "https",
             {"checks/confirm-delisted.json": {"plans": [dict(good, page="http://x")]}})
    shutil.rmtree(tmp, ignore_errors=True)
    bad = [r for r in results if not r[0]]
    for ok, label, p in results:
        print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  [{p[0]}]" if p else ""))
    assert not bad, f"{len(bad)} case(s) failed"
    print(f"check-pr selftest ok ({len(results)} cases)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
