#!/usr/bin/env python3
"""
check-plans.py: the weekly job's checks on a rebuilt energy-plans-au.json,
before it is published (22 Nov 2026).

Usage: python3 tools/check-plans.py OLD.json NEW.json [--summary FILE] [--confirmed KEYS.txt]

Exits 1, with the reasons, if any check fails:
  - the new list reads and its version is higher than the old one's
  - the plan count is within 15% of the old list's
  - every per-kWh rate is between 0c (free windows are real) and $1.50;
    daily supply charges are not checked here
  - the GST check: the median per-kWh rate of the plans in both lists moved
    no more than 5%. The fetch tool always multiplies by 1.1, so a jump like
    that most likely means the feed changed how it reports prices. Skipped
    from 20 June to 31 July, when retailers publish their 1 July prices, and
    up to the date in inputs/plans-options.json's skipGstCheckUntil (a
    change the developer approves, never a switch on the run).
  - the hand-kept plans are exactly inputs/plans-hand-kept.json's, and
    atoHomeChargingRates exactly inputs/ato-home-charging-rates.json's rates
  - what the builder must never do (Codex round 158, P1), checked here again
    on its output: a plan held for review leaves pendingReview only when the
    feed lists it again or it was confirmed gone (--confirmed, one key per
    line, the confirmations this run passed to the builder); no scope in
    completeFor has a plan held; a plan in a scope the old list certified
    leaves it only by being held or confirmed gone; complete is true exactly
    when completeFor names a scope.
Rates and closing flags that change are the feed's word and are published;
no pull request can change them, because the published file is the
builder's output only.
Also writes, to --summary, a short markdown report for the job page.
"""

import datetime
import importlib.util
import json
import statistics
import sys
from pathlib import Path

COUNT_TOLERANCE = 0.15
ROOT = Path(__file__).resolve().parent.parent
OPTIONS = "inputs/plans-options.json"
GST_TOLERANCE = 0.05

# The one identity rule, from the fetch tool itself.
_spec = importlib.util.spec_from_file_location(
    "fetch_energy_plans", Path(__file__).resolve().parent / "fetch-energy-plans.py")
_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tool)
base_id = _tool.base_id
MAX_RATE = _tool.MAX_RATE


def version_tuple(v):
    return tuple(int(x) for x in v.split("."))


def plans(db):
    """{(state, identity): plan} for every listed plan."""
    out = {}
    for st in db.get("states", []):
        for pr in st.get("providers", []):
            for pl in pr.get("plans", []):
                out[(st.get("code"), base_id(pl["id"]))] = pl
    return out


def unit_rates(pl):
    """Every per-kWh usage rate a plan carries (not feed-in, not supply)."""
    rates = []
    if pl.get("flatRatePerKWh") is not None:
        rates.append(pl["flatRatePerKWh"])
    for w in pl.get("windows") or []:
        rates.append(w.get("ratePerKWh"))
        if w.get("overCapRatePerKWh") is not None:
            rates.append(w["overCapRatePerKWh"])
    return rates


def placed(db):
    """{(state, provider, identity)} for every listed plan."""
    return {(st.get("code"), pr.get("name"), base_id(pl["id"]))
            for st in db.get("states", []) for pr in st.get("providers", []) for pl in pr.get("plans", [])}


def held_keys(db):
    return {f"{h['state']}|{h['provider']}|{h['identity']}" for h in db.get("pendingReview") or []}


def transitions(old, new, confirmed):
    """What the builder must never publish (Codex round 158, P1)."""
    problems = []
    now = placed(new)
    for key in sorted(held_keys(old) - held_keys(new)):
        st, prov, ident = key.split("|", 2)
        if (st, prov, ident) not in now and key not in confirmed:
            problems.append(f"{key} left pendingReview without being listed again or confirmed gone")
    held_scopes = {k.rsplit("|", 1)[0] for k in held_keys(new)}
    cert = new.get("completeFor") or []
    for scope in sorted(set(cert) & held_scopes):
        problems.append(f"{scope} is certified while a plan in it is held for review")
    if bool(new.get("complete")) != bool(cert):
        problems.append("'complete' does not match completeFor")
    old_cert = set(old.get("completeFor") or [])
    for st in old.get("states", []):
        for pr in st.get("providers", []):
            if f"{st['code']}|{pr['name']}" not in old_cert:
                continue
            for pl in pr.get("plans", []):
                if not _tool.is_feed(pl):
                    continue
                key = f"{st['code']}|{pr['name']}|{base_id(pl['id'])}"
                if (st["code"], pr["name"], base_id(pl["id"])) not in now \
                        and key not in held_keys(new) and key not in confirmed:
                    problems.append(f"{key} left a certified scope without being held or confirmed gone")
    return problems


def in_july_window(today):
    return (today.month == 6 and today.day >= 20) or today.month == 7


def check(old, new, skip_gst=False, today=None, confirmed=(), hand_kept=None, ato=None):
    """Returns (problems, notes). `hand_kept` and `ato` are the input files
    (main() reads the repo's)."""
    today = today or datetime.date.today()
    problems, notes = [], []
    problems += [f"the apps could not read it: {p}" for p in _tool.validate(new)[:20]]
    try:
        if version_tuple(new["version"]) <= version_tuple(old["version"]):
            problems.append(f"version {new['version']} is not higher than {old['version']}")
    except (KeyError, ValueError) as e:
        problems.append(f"version could not be compared ({e})")

    a, b = plans(old), plans(new)
    if a and abs(len(b) - len(a)) / len(a) > COUNT_TOLERANCE:
        problems.append(f"plan count went from {len(a)} to {len(b)}, more than {COUNT_TOLERANCE:.0%}")

    everything = list(b.items()) + [(("fallback", p.get("id")), p) for p in new.get("fallbackPlans", [])]
    bad = []
    for key, pl in everything:
        for r in unit_rates(pl) + ([pl["feedInTariffPerKWh"]] if pl.get("feedInTariffPerKWh") is not None else []):
            if not isinstance(r, (int, float)) or r < 0 or r > MAX_RATE:
                bad.append(f"{key[0]} {pl.get('name')}: {r!r}")
    if bad:
        problems.append(f"{len(bad)} per-kWh rate(s) outside 0c to ${MAX_RATE:.2f}: " + "; ".join(bad[:10]))

    both = set(a) & set(b)
    old_rates = [r for k in both for r in unit_rates(a[k]) if isinstance(r, (int, float)) and r > 0]
    new_rates = [r for k in both for r in unit_rates(b[k]) if isinstance(r, (int, float)) and r > 0]
    if old_rates and new_rates:
        mo, mn = statistics.median(old_rates), statistics.median(new_rates)
        move = mn / mo - 1
        notes.append(f"median per-kWh rate of the {len(both)} plans in both lists: "
                     f"{mo * 100:.2f}c to {mn * 100:.2f}c ({move:+.1%})")
        if abs(move) > GST_TOLERANCE:
            if skip_gst:
                notes.append("GST check skipped (skipGstCheckUntil in inputs/plans-options.json)")
            elif in_july_window(today):
                notes.append("GST check skipped (20 June to 31 July, 1 July price changes)")
            else:
                problems.append(f"GST check: the median per-kWh rate moved {move:+.1%} in a week, "
                                f"more than {GST_TOLERANCE:.0%}")

    if hand_kept is not None:
        want = {"states": hand_kept.get("states")}
        got = _tool.extract_hand_kept(new)
        if got != _tool.extract_hand_kept(want):
            problems.append("the hand-kept plans differ from inputs/plans-hand-kept.json")
    if ato is not None and (new.get("atoHomeChargingRates") or {}) != ato.get("rates"):
        problems.append("atoHomeChargingRates differs from inputs/ato-home-charging-rates.json")
    problems += transitions(old, new, set(confirmed))

    gone, added = set(a) - set(b), set(b) - set(a)
    notes.insert(0, f"v{old.get('version')} to v{new.get('version')}: {len(a)} to {len(b)} plans, "
                    f"{len(added)} new, {len(gone)} left, "
                    f"{len(new.get('pendingReview') or [])} held for review")
    return problems, notes


def main():
    args = sys.argv[1:]
    summary = None
    if "--summary" in args:
        i = args.index("--summary")
        summary = args[i + 1]
        del args[i:i + 2]
    confirmed = set()
    if "--confirmed" in args:
        i = args.index("--confirmed")
        confirmed = {x.strip() for x in open(args[i + 1]) if x.strip()}
        del args[i:i + 2]
    old_path, new_path = args
    until = json.load(open(ROOT / OPTIONS)).get("skipGstCheckUntil")
    skip_gst = bool(until) and datetime.date.today() <= datetime.date.fromisoformat(until)
    old = json.load(open(old_path))
    hand_kept = json.load(open(ROOT / _tool.HAND_KEPT))
    ato = json.load(open(ROOT / _tool.ATO_RATES))
    try:
        new = json.load(open(new_path))
    except ValueError as e:
        problems, notes = [f"the new list is not valid JSON ({e})"], []
    else:
        problems, notes = check(old, new, skip_gst, confirmed=confirmed, hand_kept=hand_kept, ato=ato)
    lines = [f"- {n}" for n in notes]
    if problems:
        lines += ["", "**Not published, because:**"] + [f"- {p}" for p in problems]
    else:
        lines += ["", "All checks passed."]
    text = "\n".join(lines) + "\n"
    print(text)
    if summary:
        Path(summary).write_text(text)
    raise SystemExit(1 if problems else 0)


def selftest():
    base = {"version": "0.13.0", "asOf": "2026-11-05", "currency": "AUD", "disclaimer": "x",
            "fallbackPlans": [], "states": [{"code": "QLD", "name": "Queensland", "providers": [
                {"name": "P", "plans": [{"id": f"p{i}mre1", "name": f"Plan {i}", "type": "flat",
                                         "flatRatePerKWh": 0.30, "source": _tool.SOURCE}
                                        for i in range(20)]}]}]}
    def bump(db, rate=0.30, n=20, version="0.14.0"):
        d = json.loads(json.dumps(db))
        d["version"] = version
        d["states"][0]["providers"][0]["plans"] = [
            {"id": f"p{i}mre2", "name": f"Plan {i}", "type": "flat", "flatRatePerKWh": rate,
             "source": _tool.SOURCE} for i in range(n)]
        return d
    nov = datetime.date(2026, 11, 23)
    assert check(base, bump(base), today=nov)[0] == [], "a normal week failed"
    assert check(base, bump(base, version="0.13.0"), today=nov)[0], "same version passed"
    assert check(base, bump(base, n=15), today=nov)[0], "a 25% drop in plans passed"
    assert check(base, bump(base, rate=1.60), today=nov)[0], "a $1.60 rate passed"
    assert check(base, bump(base, rate=-0.01), today=nov)[0], "a negative rate passed"
    free = bump(base)
    free["states"][0]["providers"][0]["plans"][0] = {"id": "p0mre2", "name": "Plan 0", "type": "timeOfUse",
        "source": _tool.SOURCE,
        "windows": [{"label": "Free", "start": "11:00", "end": "14:00", "ratePerKWh": 0.0},
                    {"label": "Peak", "start": "14:00", "end": "11:00", "ratePerKWh": 0.30}]}
    assert check(base, free, today=nov)[0] == [], "a 0c free window failed"
    assert check(base, bump(base, rate=0.33), today=nov)[0], "a 10% median move passed in November"
    assert check(base, bump(base, rate=0.33), skip_gst=True, today=nov)[0] == [], "--skip-gst did not skip"
    assert check(base, bump(base, rate=0.33), today=datetime.date(2027, 6, 20))[0] == [], "20 June not skipped"
    assert check(base, bump(base, rate=0.33), today=datetime.date(2027, 7, 31))[0] == [], "31 July not skipped"
    assert check(base, bump(base, rate=0.33), today=datetime.date(2027, 8, 1))[0], "1 August skipped"
    rates = {"rates": {"2027": 0.06}, "sources": {}}
    assert check(base, dict(bump(base), atoHomeChargingRates={"2027": 0.06}), today=nov, ato=rates)[0] == []
    assert check(base, bump(base), today=nov, ato=rates)[0], "a lost ATO rate passed"
    assert check(base, dict(bump(base), atoHomeChargingRates={"2027": 0.07}), today=nov, ato=rates)[0], \
        "an ATO rate unlike the input passed"
    hk = {"states": [{"code": "WA", "name": "WA", "providers": [{"name": "S", "plans": [
        {"id": "s-a1", "name": "A1", "type": "flat", "flatRatePerKWh": 0.3, "source": "site"}]}]}]}
    with_hk = bump(base)
    with_hk["states"].append(json.loads(json.dumps(hk["states"][0])))
    assert check(base, with_hk, today=nov, hand_kept=hk)[0] == [], "the input's hand-kept plans failed"
    with_hk["states"][-1]["providers"][0]["plans"][0]["flatRatePerKWh"] = 0.31
    assert check(base, with_hk, today=nov, hand_kept=hk)[0], "a hand-kept plan unlike the input passed"

    # What the builder must never publish (Codex round 158, P1).
    SRC = _tool.SOURCE
    def feedlist(version, ids, held=(), cert=("QLD|P",)):
        d = json.loads(json.dumps(base))
        d["version"] = version
        d["states"][0]["providers"][0]["plans"] = [
            {"id": f"p{i}mre1", "name": f"Plan {i}", "type": "flat", "flatRatePerKWh": 0.30, "source": SRC}
            for i in ids]
        d["pendingReview"] = [{"identity": f"p{i}mre", "state": "QLD", "provider": "P", "name": f"Plan {i}",
                               "since": "2026-11-01"} for i in held]
        if not d["pendingReview"]:
            d.pop("pendingReview")
        if cert:
            d["complete"], d["completeFor"] = True, list(cert)
        return d
    ids = range(20)
    held_old = feedlist("0.13.0", range(1, 20), held=[0], cert=())
    assert check(held_old, feedlist("0.14.0", range(1, 20), held=[0], cert=()), today=nov)[0] == [], \
        "a plan still held failed"
    assert check(held_old, feedlist("0.14.0", ids), today=nov)[0] == [], "a held plan back in the feed failed"
    assert check(held_old, feedlist("0.14.0", range(1, 20)), today=nov, confirmed={"QLD|P|p0mre"})[0] == [], \
        "a confirmed plan failed"
    assert check(held_old, feedlist("0.14.0", range(1, 20)), today=nov)[0], \
        "a held plan dropped from pendingReview, unconfirmed, passed"
    assert check(held_old, feedlist("0.14.0", range(1, 20), held=[0]), today=nov)[0], \
        "a scope certified while a plan in it is held passed"
    cert_old = feedlist("0.13.0", ids)
    assert check(cert_old, feedlist("0.14.0", range(1, 20)), today=nov)[0], \
        "a plan dropped from a certified scope passed"
    assert check(cert_old, feedlist("0.14.0", range(1, 20), held=[0], cert=()), today=nov)[0] == [], \
        "a plan leaving a certified scope and held failed"
    lying = feedlist("0.14.0", ids)
    lying["complete"] = False
    assert check(cert_old, lying, today=nov)[0], "'complete' unlike completeFor passed"
    assert check(cert_old, feedlist("0.13.0", ids), today=nov)[0], "the same version passed"
    print("check-plans selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
