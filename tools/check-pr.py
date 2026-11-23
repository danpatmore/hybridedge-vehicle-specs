#!/usr/bin/env python3
"""
check-pr.py: the data rules every pull request must pass (22 Nov 2026,
reworked after Codex round 158 on 23 Nov). The gate (tools/gate.py) runs
main's copy of this file on data copied out of the PR as text, never the PR's
code, and on top of these rules no PR merges without the developer's own
approval comment.

Usage: python3 tools/check-pr.py BASE_DIR HEAD_DIR [--summary FILE]
       python3 tools/check-pr.py --selftest
BASE_DIR holds main's data files, HEAD_DIR the pull request's (same layout).

Two kinds of finding:
  problems  the PR can't merge, whoever approves it
  needs     changes a routine must never make; they merge only when the
            developer's approval comment names them (tools/gate.py)

phev-specs-au.json (HybridEdge has no version check on the car list, so
whatever is merged reaches every phone within a day):
  - valid JSON, with version and lastUpdated as strings
  - car ids unique; no id on main changed or removed
  - version higher than main's when any car changed
  - a tester-log key that differs from main: needs "tester-log keys"
  - showCarsWithBlanks only at the top, true or false; a change to it
    needs "showCarsWithBlanks"
energy-plans-au.json: never changed by a PR (Codex round 158, P1). It is the
  weekly plans job's output; its inputs are below.
inputs/plans-hand-kept.json: the builder's own checks (every plan readable,
  dashed ids, 0c to $1.50); any change needs "hand-kept plans".
inputs/ato-home-charging-rates.json: dollars per km by FBT year, each with
  its ato.gov.au page; any change needs "ATO home-charging rates", listing
  each year's old and new rate and its page (Codex round 159, P2).
inputs/plans-options.json: skipGstCheckUntil null, or a date no more than 14
  days away; setting one needs "GST check off".
lease-rules-au.json: valid JSON, version and asOf strings, provider ids
  unique, and every provider with a rule has a source or says why not; any
  change needs "lease provider rules", listing each provider's changed
  fields, old and new, and its sources (Codex round 159, P2).
checks/last-checked.json: only dated, short results (tools/merge-check-log.py).
checks/confirm-delisted.json: every entry well formed and held on main
  (tools/delisted.py).
Paths (check_paths): a data file may not be deleted or renamed; a sweep
report (sweeps/*.md) may be added or edited; anything else needs "workflows"
(.github/) or "code". A rename counts as both its old and its new path.
"""

import importlib.util
import json
import re
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


def need(needs, category, detail):
    needs.setdefault(category, []).append(detail)


def check_specs(base, head, needs):
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
    if any(has_key(v, "showCarsWithBlanks") for k, v in head.items() if k != "showCarsWithBlanks"):
        p.append("car list: showCarsWithBlanks may only be a top-level key")
    if "showCarsWithBlanks" in head and not isinstance(head["showCarsWithBlanks"], bool):
        p.append("car list: showCarsWithBlanks must be true or false")
    if ("showCarsWithBlanks" in head, head.get("showCarsWithBlanks")) != \
            ("showCarsWithBlanks" in (base or {}), (base or {}).get("showCarsWithBlanks")):
        need(needs, "showCarsWithBlanks",
             f"car list: showCarsWithBlanks set to {json.dumps(head.get('showCarsWithBlanks'))}")
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
                    need(needs, "tester-log keys", f"car list: {car}: '{k}' changed; check it matches the tester's log")
        for i, nc in new.items():
            if i not in old:
                added = [k for k in TESTER_LOG_KEYS if k in nc]
                if added:
                    need(needs, "tester-log keys", f"car list: new car {i} carries {added}; check they match the tester's log")
        if base.get("vehicles") != cars:
            try:
                if vtuple(head.get("version")) <= vtuple(base.get("version")):
                    p.append(f"car list: cars changed but version {head.get('version')} is not higher than {base.get('version')}")
            except ValueError:
                p.append("car list: version could not be compared")
    return p


PLANS_OUTPUT = ("plans: energy-plans-au.json is the weekly plans job's output, and no pull request may "
                "change it (Codex round 158). Change its inputs instead: inputs/plans-hand-kept.json, "
                "inputs/ato-home-charging-rates.json or checks/confirm-delisted.json.")


def check_hand_kept(base, head, needs):
    p = _load_tool("fetch-energy-plans").hand_kept_problems(head)
    def index(doc):
        return {(s.get("code"), pr.get("name"), pl.get("id")): pl for s in (doc or {}).get("states") or []
                for pr in s.get("providers") or [] for pl in pr.get("plans") or []}
    a, b = index(base), index(head)
    changed = [f"{'added' if k not in a else 'removed' if k not in b else 'changed'} {' '.join(map(str, k))}"
               for k in sorted(set(a) | set(b), key=str) if a.get(k) != b.get(k)]
    need(needs, "hand-kept plans", "hand-kept plans: " + ("; ".join(changed[:20]) or "notes or order changed"))
    return p


def short(v, n=120):
    t = json.dumps(v, ensure_ascii=False)
    return t if len(t) <= n else t[:n] + "…"


def check_ato(base, head, needs):
    p = _load_tool("fetch-energy-plans").ato_problems(head)
    old, new = (base or {}).get("rates") or {}, head.get("rates") or {}
    rows = [f"ATO rate for the FBT year from 1 April {y}: {short(old.get(y))} to {short(new.get(y))} dollars per km"
            f" (source: {(head.get('sources') or {}).get(y) or (base or {}).get('sources', {}).get(y)})"
            for y in sorted(set(old) | set(new)) if old.get(y) != new.get(y)]
    need(needs, "ATO home-charging rates", "; ".join(rows) or "ATO rates file changed (sources or notes)")
    return p


def check_options(head, needs, today=None):
    import datetime
    today = today or datetime.date.today()
    extra = set(head) - {"about", "skipGstCheckUntil"}
    if extra:
        return [f"plans options: unexpected keys {sorted(extra)}"]
    until = head.get("skipGstCheckUntil")
    if until is None:
        return []
    try:
        d = datetime.date.fromisoformat(until)
    except (TypeError, ValueError):
        return ["plans options: skipGstCheckUntil must be null or YYYY-MM-DD"]
    if not today <= d <= today + datetime.timedelta(days=14):
        return ["plans options: skipGstCheckUntil must be from today to 14 days away"]
    need(needs, "GST check off", f"plans options: the GST check is skipped until {until}")
    return []


def rules_changes(base, head):
    """Each provider's changed fields, old and new, with its sources."""
    old = {x.get("id"): x for x in (base or {}).get("providers") or []}
    new = {x.get("id"): x for x in head.get("providers") or [] if isinstance(x, dict)}
    rows = []
    for pid in sorted(set(old) | set(new), key=str):
        a, b = old.get(pid), new.get(pid)
        if a == b:
            continue
        if a is None or b is None:
            rows.append(f"provider {pid} {'added' if a is None else 'removed'}")
            continue
        fields = [f"{k}: {short(a.get(k))} to {short(b.get(k))}" for k in sorted(set(a) | set(b))
                  if a.get(k) != b.get(k) and k != "sources"]
        if a.get("sources") != b.get("sources"):
            fields.append("sources changed")
        rows.append(f"provider {pid}: " + "; ".join(fields) + f" (sources: {', '.join(b.get('sources') or []) or 'none'})")
    for k in sorted(set(base or {}) | set(head)):
        if k != "providers" and (base or {}).get(k) != head.get(k):
            rows.append(f"{k}: {short((base or {}).get(k))} to {short(head.get(k))}")
    return rows


def check_rules(base, head, needs):
    need(needs, "lease provider rules", "lease rules: " + (" | ".join(rules_changes(base, head)) or "changed"))
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
              "checks/last-checked.json", "checks/confirm-delisted.json",
              "inputs/plans-hand-kept.json", "inputs/ato-home-charging-rates.json",
              "inputs/plans-options.json")


def check_paths(files):
    """(problems, needs) for the PR's paths, from the PR-files API: each
    {"filename", "status", "previous_filename"?}. A rename is both paths
    (Codex round 158, P2)."""
    problems, needs = [], {}
    for f in files:
        status = f.get("status")
        # A rename adds its new path and removes its old one.
        each = [(f["filename"], "added" if status == "renamed" else status)]
        if f.get("previous_filename"):
            each.append((f["previous_filename"], "removed"))
        for path, effect in each:
            if path in DATA_FILES:
                if status not in ("added", "modified", "changed"):
                    problems.append(f"{path} is {status} in this PR; data files are never deleted or renamed")
            elif re.fullmatch(r"sweeps/[^/]+\.md", path) and effect in ("added", "modified", "changed"):
                continue
            elif path.startswith(".github/"):
                need(needs, "workflows", f"{effect}: {path}")
            else:
                need(needs, "code", f"{effect}: {path}")
    return problems, needs


def check_log(base, head):
    _, p = _load_tool("merge-check-log").merge(base or {}, head)
    return [f"check log: {x}" for x in p]


def check_confirmations(head, base_dir):
    plans = base_dir / "energy-plans-au.json"
    if not plans.exists():
        return ["confirmations: main has no plans file to check them against"]
    tool = _load_tool("delisted")
    return [f"confirmations: {x}" for x in tool.problems(head, tool.held(plans))]


def check_dirs(base_dir, head_dir, needs=None):
    """(problems, files checked); what needs the developer's word goes in
    `needs`, {category: [details]}."""
    problems, checked = [], []
    needs = {} if needs is None else needs
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
            problems += check_specs(base, head, needs)
        elif name == "energy-plans-au.json":
            problems.append(PLANS_OUTPUT)
        elif name == "inputs/plans-hand-kept.json":
            problems += check_hand_kept(base, head, needs)
        elif name == "inputs/ato-home-charging-rates.json":
            problems += check_ato(base, head, needs)
        elif name == "inputs/plans-options.json":
            problems += check_options(head, needs)
        elif name == "lease-rules-au.json":
            problems += check_rules(base, head, needs)
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
    base_dir, head_dir = Path(args[0]), Path(args[1])
    needs = {}
    problems, checked = check_dirs(base_dir, head_dir, needs)
    text = summary_text(problems, checked, needs)
    print(text)
    if summary:
        Path(summary).write_text(text)
    raise SystemExit(1 if problems else 0)


def summary_text(problems, checked, needs):
    text = (f"Checked: {', '.join(checked) or 'no data file changed'}.\n\n"
            + ("**Problems (this can't merge):**\n" + "\n".join(f"- {x}" for x in problems)
               if problems else "All data checks passed.")
            + "\n")
    for cat, details in needs.items():
        text += f"\n**Needs your word: {cat}**\n" + "\n".join(f"- {x}" for x in details[:30]) + "\n"
    return text


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

    hand = json.load(open(base / "inputs/plans-hand-kept.json"))
    ato = json.load(open(base / "inputs/ato-home-charging-rates.json"))

    def case(label, expect_fail, must=None, files=None, raw=None, need=None, paths=None):
        """`need`: the category the change must be listed under (or None:
        nothing may be listed)."""
        d = tmp / f"case{len(results)}"
        shutil.copytree(base, d)
        for name, obj in (files or {}).items():
            (d / name).write_text(json.dumps(obj, indent=1))
        for name, text in (raw or {}).items():
            (d / name).write_text(text)
        needs = {}
        p, _ = check_dirs(base, d, needs)
        if paths is not None:
            pp, pn = check_paths(paths)
            p += pp
            for k, v in pn.items():
                needs.setdefault(k, []).extend(v)
        ok = bool(p) == expect_fail and (must is None or must.lower() in " ".join(p).lower())
        ok = ok and (set(needs) == ({need} if need else set()) or (expect_fail and need is None))
        results.append((ok, label, p[:1] or [f"needs {sorted(needs)}"] if needs else p[:1]))

    def cars(edit, bump=True):
        s = copy.deepcopy(specs)
        edit(s)
        if bump:
            s["version"] = "999.0.0"
        return {"phev-specs-au.json": s}

    def plans_edit(edit):
        d = copy.deepcopy(plans)
        edit(d)
        return {"energy-plans-au.json": d}

    def first_plan(d):
        return d["states"][0]["providers"][0]["plans"][0]

    case("nothing changed", False)
    case("a car removed", True, "removed", cars(lambda s: s["vehicles"].pop(0)))
    case("a car id changed", True, "removed", cars(lambda s: s["vehicles"][5].update(id="00000000-0000-0000-0000-000000000000")))
    case("a duplicate id", True, "duplicate", cars(lambda s: s["vehicles"].append(copy.deepcopy(s["vehicles"][3]))))
    case("a tester-log key removed: needs the developer's word", False, None,
         cars(lambda s: [v.pop("petrolFromFuelFlow", None) for v in s["vehicles"]]), need="tester-log keys")
    case("a tester-log key changed: needs the developer's word", False, None,
         cars(lambda s: next(v for v in s["vehicles"] if v.get("packSoC")).update(packSoC={"changed": True})),
         need="tester-log keys")
    case("a new car carrying tester-log keys: needs the developer's word", False, None,
         cars(lambda s: s["vehicles"].append(dict(copy.deepcopy(next(v for v in s["vehicles"] if v.get("packSoC"))), id="NEW-ID-1"))),
         need="tester-log keys")
    case("a car removed alongside a tester-log change", True, "removed",
         cars(lambda s: [s["vehicles"].pop(0), next(v for v in s["vehicles"] if v.get("packSoC")).update(packSoC={})]))
    case("showCarsWithBlanks set true at the top: needs the developer's word", False, None,
         cars(lambda s: s.update(showCarsWithBlanks=True), bump=False), need="showCarsWithBlanks")
    case("showCarsWithBlanks inside a car", True, "top-level",
         cars(lambda s: s["vehicles"][0].update(showCarsWithBlanks=True)))
    case("showCarsWithBlanks as a string", True, "true or false", cars(lambda s: s.update(showCarsWithBlanks="yes")))
    case("a car changed, version not bumped", True, "version",
         cars(lambda s: s["vehicles"][10].update(notes=(s["vehicles"][10].get("notes") or "") + " x"), bump=False))
    case("a car note changed, version bumped", False, None,
         cars(lambda s: s["vehicles"][10].update(notes=(s["vehicles"][10].get("notes") or "") + " x")))
    case("lastUpdated dropped", True, "lastUpdated", cars(lambda s: s.pop("lastUpdated")))
    case("invalid JSON", True, "json", raw={"phev-specs-au.json": "{ not json"})

    # The plans file is the builder's output only (Codex round 158, P1): every
    # transition its probes and review found, and any other edit, fails.
    held = plans.get("pendingReview") or []
    case("plans: a lower version", True, "output", plans_edit(lambda d: d.update(version="0.1.0")))
    case("plans: closing true with version 99.0.0", True, "output",
         plans_edit(lambda d: [first_plan(d).update(closing=True), d.update(version="99.0.0")]))
    case("plans: a rate changed within 0c to $1.50", True, "output",
         plans_edit(lambda d: first_plan(d).update(flatRatePerKWh=0.31, windows=None)))
    case("plans: a plan dropped from a certified scope", True, "output",
         plans_edit(lambda d: d["states"][0]["providers"][0]["plans"].pop()))
    if held:
        case("plans: a pendingReview entry removed", True, "output", plans_edit(lambda d: d["pendingReview"].pop(0)))
        case("plans: completeFor gains a scope with a plan held", True, "output",
             plans_edit(lambda d: d["completeFor"].append(f"{held[0]['state']}|{held[0]['provider']}")))
    case("plans: atoHomeChargingRates edited in", True, "output",
         plans_edit(lambda d: d.update(atoHomeChargingRates={"2027": 0.06})))
    case("plans: a file the apps cannot read", True, "output", plans_edit(lambda d: d.pop("states")))

    # Its inputs.
    h1 = copy.deepcopy(hand)
    h1["states"][0]["providers"][0]["plans"][0]["flatRatePerKWh"] = 0.29
    case("hand-kept plans: a rate changed: needs the developer's word", False, None,
         {"inputs/plans-hand-kept.json": h1}, need="hand-kept plans")
    h2 = copy.deepcopy(hand)
    h2["states"][0]["providers"][0]["plans"][0]["id"] = "agl1175227mre1"
    case("hand-kept plans: an id like a feed plan's", True, "dash", {"inputs/plans-hand-kept.json": h2})
    h3 = copy.deepcopy(hand)
    h3["states"][0]["providers"][0]["plans"][0]["flatRatePerKWh"] = 1.60
    case("hand-kept plans: a $1.60 rate", True, "outside", {"inputs/plans-hand-kept.json": h3})
    src = "https://www.ato.gov.au/businesses-and-organisations/x"
    case("ATO: a rate with its ATO page: needs the developer's word", False, None,
         {"inputs/ato-home-charging-rates.json": dict(ato, rates={"2027": 0.0612}, sources={"2027": src})},
         need="ATO home-charging rates")
    rules = json.load(open(base / "lease-rules-au.json"))
    r1 = copy.deepcopy(rules)
    r1["providers"][0]["needsDedicatedMeter"] = not r1["providers"][0].get("needsDedicatedMeter")
    case("lease rules: a provider rule changed: needs the developer's word", False, None,
         {"lease-rules-au.json": r1}, need="lease provider rules")
    r2 = copy.deepcopy(rules)
    r2["providers"][0]["sources"] = []
    r2["providers"][0]["notes"] = ""
    case("lease rules: a provider with no source or note", True, "no source", {"lease-rules-au.json": r2})
    case("ATO: a rate with no source", True, "ato.gov.au",
         {"inputs/ato-home-charging-rates.json": dict(ato, rates={"2027": 0.0612}, sources={})})

    import datetime
    soon = str(datetime.date.today() + datetime.timedelta(days=7))
    case("GST check off for a week: needs the developer's word", False, None,
         {"inputs/plans-options.json": {"skipGstCheckUntil": soon}}, need="GST check off")
    case("GST check off for a year", True, "14 days",
         {"inputs/plans-options.json": {"skipGstCheckUntil": str(datetime.date.today() + datetime.timedelta(days=365))}})

    l1 = copy.deepcopy(log)
    l1["vehicles"] = {"date": str(__import__("datetime").date.today()), "result": "no changes"}
    case("a check log with a dated result", False, None, {"checks/last-checked.json": l1})
    l2 = copy.deepcopy(log)
    l2["vehicles"] = {"date": "2026-11-22", "result": "x", "version": "9.9.9"}
    case("a check log entry carrying a figure", True, "vehicles", {"checks/last-checked.json": l2})
    l3 = copy.deepcopy(log)
    l3["kerbMassKg"] = 1
    case("a check log with an unexpected key", True, "unexpected", {"checks/last-checked.json": l3})
    if held:
        k = f"{held[0]['state']}|{held[0]['provider']}|{held[0]['identity']}"
        good = {"key": k, "checked": "2026-11-22", "page": "https://example.com/plan", "finding": "not offered"}
        case("a confirmation of a held plan", False, None, {"checks/confirm-delisted.json": {"plans": [good]}})
        case("a confirmation of a plan main does not hold", True, "not held",
             {"checks/confirm-delisted.json": {"plans": [dict(good, key="NSW|Nobody|xyz123abc")]}})
        case("a confirmation with no https page", True, "https",
             {"checks/confirm-delisted.json": {"plans": [dict(good, page="http://x")]}})

    # Paths (Codex round 158, P2: a rename is both its paths).
    case("a sweep report added", False, None, paths=[{"filename": "sweeps/x.md", "status": "added"}])
    case("a workflow renamed to a sweep report", False, None, need="workflows",
         paths=[{"filename": "sweeps/x.md", "status": "renamed", "previous_filename": ".github/workflows/pr-check.yml"}])
    case("a tool renamed to a sweep report", False, None, need="code",
         paths=[{"filename": "sweeps/x.md", "status": "renamed", "previous_filename": "tools/check-pr.py"}])
    case("a data file renamed", True, "renamed",
         paths=[{"filename": "x.json", "status": "renamed", "previous_filename": "phev-specs-au.json"}])
    case("a data file deleted", True, "removed", paths=[{"filename": "lease-rules-au.json", "status": "removed"}])
    case("a sweep report deleted", False, None, need="code", paths=[{"filename": "sweeps/x.md", "status": "removed"}])
    case("a workflow added", False, None, need="workflows",
         paths=[{"filename": ".github/workflows/x.yml", "status": "added"}])
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
