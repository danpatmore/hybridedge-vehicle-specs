#!/usr/bin/env python3
"""
fetch-energy-plans.py — Tariff data pipeline (30 Jul 2026).

Pulls current residential electricity plans from the AER's public Consumer
Data Right endpoints behind energymadeeasy.gov.au and converts them to the
HybridEdge energy-plans schema. Covers NSW/QLD/SA/ACT/TAS/VIC; WA/NT
entries stay hand-maintained and are merged from the existing file.

Usage: python3 tools/fetch-energy-plans.py [--keep-from older-list.json ...]
                                           [--confirm-delisted 'STATE|Provider|identity' ...]
       python3 tools/fetch-energy-plans.py --selftest
Writes: energy-plans-au.json at the top of the specs repo, the published list
both apps download (and prints a summary).

22 Nov 2026: moved from the HybridEdge app repo to the specs repo, where a
weekly GitHub Actions job runs it (.github/workflows/plans-weekly.yml). This is
the only copy. Hand edits (WA/NT plans, ALWAYS_INCLUDE) go here and in the
published file, never the app's bundled copy.

19 Oct 2026 rebuild (the developer's EnergyAustralia notice): reads the
shipped list rather than the July copy in Docs/Data, names each NSW plan for
its network (Ausgrid, Endeavour, Essential: one plan name, three rate cards),
takes the season covering today, applies a GUARANTEED discount to the unit
rates, carries the retailer's flat feed-in tariff, and always picks the plans
in ALWAYS_INCLUDE.

A plan already in the list STAYS while the feed still offers it, refreshed
to today's rates, however many plans that makes (19 Oct, for the app's plan
watch): an owner's plan must leave the list only when the retailer stops
offering it, or the app would tell them their plan had ended when it had
not. --keep-from adds the plans of an older list to the ones kept.

20 Oct 2026 (Codex round 108): one identity rule with the app (base_id), every
carried plan reconciled before the list is marked complete, the page shape
checked, and the list certifies only the feed providers it read in full
(completeFor). A plan no longer in the feed is written but the list is NOT
marked complete, and the plan is held in pendingReview, until someone has
checked it on the retailer's own site and runs the tool with
--confirm-delisted.

20 Oct 2026 (Codex round 109): a confirmation names each plan checked, as
the tool prints it ('QLD|1st Energy|1st1161464mre'), and must be a plan the
last run held for review that is still missing; any other plan missing stays
held. Every provider the list carries or holds a plan for must answer, or
nothing is written. Plans are reconciled by state, provider and identity, and
a provider's state is certified (completeFor) only where the feed lists its
plans or a plan of its was confirmed gone, and never while one is held.

5 Nov 2026 (a tester: "OVO's The One Plan isn't listed"): the feed has
carried Victoria all along, on its five networks, and the tool knew none of
them, so every Victorian plan was set aside and the state stayed hand-kept.
Victoria is read now, each plan named for its network like NSW. It is NOT
certified: Victorian plans are reissued about monthly under new ids and
dated names ("The One Plan - NOV2026"), so an id leaving the feed says
nothing about the owner's plan, and the app must say nothing either. A
Victorian plan that leaves the feed leaves the list without being held for
review. Hand-kept Victorian plans stay. Fifteen retailers the tool never
asked were added (the scan of the CDR register's 85 energy brands that day).
And a business plan is never a NEW pick: 56 had taken household places.
One already listed stays while the feed offers it, so no owner on one is
told it has gone.

GST canary: Ergon's regulated Tariff 11 is 28.89 c/kWh inc GST. If the CDR
value for it decodes near 26.3c the feed is ex-GST and we multiply by 1.1.
"""

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

BASE = "https://cdr.energymadeeasy.gov.au/{brand}/cds-au/v1/energy/plans"

BRANDS = [
    "agl", "origin", "energyaustralia", "red-energy", "alinta-energy",
    "ovo-energy", "engie", "momentum", "lumo", "energy-locals",
    "globird", "1st-energy", "ergon", "aurora", "actewagl",
    # 5 Nov 2026: retailers with current household plans the tool never
    # asked (from the CDR register's energy brands).
    "powershop", "kogan", "flow-power", "nectr", "tango", "sumo-power",
    "dodo", "diamond", "covau", "gee-energy", "flipped", "arcline",
    "solstice", "radian", "silver-asset",
    # common alternate slugs
    "ergon-energy", "aurora-energy", "momentum-energy", "lumo-energy",
    "globird-energy", "red", "ovo", "alinta",
]

DISTRIBUTOR_STATE = {
    "ausgrid": "NSW", "endeavour": "NSW", "essential": "NSW",
    "energex": "QLD", "ergon": "QLD",
    "sa power": "SA", "sapn": "SA",
    "evoenergy": "ACT", "actewagl": "ACT",
    "tasnetworks": "TAS", "tasmania": "TAS",
    "citipower": "VIC", "powercor": "VIC", "jemena": "VIC",
    "united energy": "VIC", "ausnet": "VIC",
}

MAX_PLANS_PER_BRAND_STATE = 4
# A state whose plans differ by network gets this many per network instead.
MULTI_NETWORK_STATES = {"NSW", "VIC"}
MAX_PLANS_PER_BRAND_NETWORK = 3
NETWORK_NAMES = {"ausgrid": "Ausgrid", "endeavour": "Endeavour", "essential": "Essential",
                 "citipower": "CitiPower", "powercor": "Powercor", "jemena": "Jemena",
                 "united energy": "United Energy", "ausnet": "AusNet"}
# Plans an owner has told us about, picked whatever their score (base ids).
ALWAYS_INCLUDE = {
    "ene745432mre",   # EnergyAustralia Flexi Plan, Endeavour: where EA moves
                      # Night Saver EV customers (the developer's notice, 19 Oct)
}
# The states the feed covers: a provider read in full is certified complete
# in these, and only these (Codex round 108, P1).
FEED_STATES = ("NSW", "QLD", "SA", "ACT", "TAS")
# Read from the feed and never certified (5 Nov 2026): Victorian plans are
# reissued about monthly under new ids, so a plan leaving the feed there is
# not evidence the owner's plan has gone. It leaves the list, unheld, and
# the app, finding the state uncertified, says nothing.
UNCERTIFIED_FEED_STATES = ("VIC",)
SOURCE = "AER Energy Made Easy CDR feed"
ctx = ssl.create_default_context()


def get(url, xv):
    # Three tries for a dropped connection, a timeout or a busy server (the
    # weekly cloud job, 22 Nov 2026). A 404 or other refusal is an answer and
    # is never retried; a third failure goes up as before.
    for attempt in range(3):
        req = urllib.request.Request(url, headers={"x-v": str(xv), "User-Agent": "HybridEdge-plans/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except Exception:
            if attempt == 2:
                raise
        time.sleep(5 * (attempt + 1))


class PartialList(Exception):
    """A page, a brand or a listed plan's details could not be read. A list
    written without it would show listed plans as gone when the feed simply
    did not answer, and the app's plan watch reads a plan missing from the
    list as no longer offered (Codex round 106, P1). So nothing is written."""


def state_for(distributors):
    for d in distributors or []:
        dl = d.lower()
        for key, st in DISTRIBUTOR_STATE.items():
            if key in dl:
                return st
    return None


def network_of(distributors):
    """The one network (NSW or Victoria) a plan is for, or None."""
    found = {NETWORK_NAMES[k] for d in distributors or [] for k in NETWORK_NAMES if k in d.lower()}
    return found.pop() if len(found) == 1 else None


def base_id(plan_id):
    """A plan's identity without the version the feed adds, the ONE rule the
    app's plan watch uses too (`EnergyPlanWatch.planIdentity`, Codex round
    108, P1): lower case, anything from "@" dropped, a hand-kept id (with a
    hyphen) whole, and a feed id of the shape <letters and digits><digit>
    <letters><version digits> without its version digits.

      ENE745432MRE23@EME -> ene745432mre
      1st1161464mre1     -> 1st1161464mre   (round 108: the old rule wanted a
                                              letter first, so 1st Energy's
                                              ids kept their version)
      agl123456          -> agl123456       (no letters after the number:
                                              nothing is a version)

    Both sides read the same cases from
    tools/fixtures/plan-identity-cases.json (a copy of the app's test cases)."""
    import re
    s = plan_id.split("@")[0].lower()
    if "-" in s:
        return s
    m = re.match(r"^([a-z0-9]*[0-9][a-z]+)[0-9]*$", s)
    return m.group(1) if m else s


def current_period(periods, today=None):
    """The tariff period covering today (periods carry MM-DD bounds that may
    wrap the new year, like Summer 11-01 to 03-31); the first if none does."""
    import datetime
    t = (today or datetime.date.today()).strftime("%m-%d")
    for tp in periods:
        a, b = tp.get("startDate"), tp.get("endDate")
        if not (a and b):
            continue
        if (a <= b and a <= t <= b) or (a > b and (t >= a or t <= b)):
            return tp
    return periods[0]


def guaranteed_discount(contract):
    """A GUARANTEED percentage off the energy charges, as a fraction (0.12),
    or 0. Conditional discounts (pay on time, direct debit) are not taken."""
    total = 0.0
    for d in contract.get("discounts") or []:
        if d.get("type") != "GUARANTEED":
            continue
        for key in ("percentOfBill", "percentOfUse"):
            rate = (d.get(key) or {}).get("rate")
            if rate:
                total += float(rate)
    return total if 0 < total < 0.5 else 0.0


def feed_in(contract):
    """The retailer's flat feed-in tariff, $/kWh (no GST on household exports)."""
    for f in contract.get("solarFeedInTariff") or []:
        if f.get("payerType") != "RETAILER" or f.get("tariffUType") != "singleTariff":
            continue
        rates = (f.get("singleTariff") or {}).get("rates") or []
        if rates:
            v = float(rates[0].get("unitPrice", -1))
            if 0 <= v <= 0.5:
                return round(v, 4)
    return None


def day_bucket(days):
    days = set(days or [])
    weekdays = {"MON", "TUE", "WED", "THU", "FRI"}
    weekend = {"SAT", "SUN"}
    if days >= weekdays | weekend or not days:
        return "all"
    if days <= weekdays:
        return "weekday"
    if days <= weekend:
        return "weekend"
    return "all"   # mixed odd sets collapse to all — confirm screen catches it


def hhmm(t):
    # CDR uses "HH:MM" or "HHMM"; end times like 23:59 mean "to midnight"
    t = t.replace(":", "")
    h, m = int(t[:2]), int(t[2:4])
    if (h, m) == (23, 59):
        return "24:00"
    if m == 59:
        m += 1
        if m == 60:
            h, m = h + 1, 0
    return f"{h:02d}:{m:02d}"


GENERIC_LABEL = __import__("re").compile(r"^(tariff|rate|block|band|period)\s*\d*$", __import__("re").I)


def price_labels(windows):
    """Names a plan's windows by what they cost when every label the feed
    gave is only a number (5 Nov 2026: 56 Victorian plans arrive as
    'Tariff 1', 'Tariff 2', which tells an owner nothing). Free for a zero
    rate; of the paid rates, Off-peak for the cheapest and Peak for the
    dearest, Shoulder between (numbered when there are several); one paid
    rate is Standard. A plan with any real label keeps all of its own. The
    app compares plans without labels, so renaming changes no rate card."""
    if not windows or not all(GENERIC_LABEL.match(w["label"].strip()) for w in windows):
        return windows
    paid = sorted({w["ratePerKWh"] for w in windows if w["ratePerKWh"] > 0})
    names = {}
    if len(paid) == 1:
        names[paid[0]] = "Standard"
    elif paid:
        names[paid[0]], names[paid[-1]] = "Off-peak", "Peak"
        middle = paid[1:-1]
        for i, r in enumerate(middle):
            names[r] = "Shoulder" if len(middle) == 1 else f"Shoulder {i + 1}"
    return [{**w, "label": "Free" if w["ratePerKWh"] <= 0 else names[w["ratePerKWh"]]}
            for w in windows]


def convert_plan(detail, brand_name, gst_factor, network=None):
    plan = detail.get("data", detail)
    contract = plan.get("electricityContract") or {}
    periods = contract.get("tariffPeriod") or []
    if not periods:
        return None
    tp = current_period(periods)
    name = plan.get("displayName") or plan.get("planId", "Plan")
    if network and network.lower() not in name.lower():
        name = f"{name} ({network})"
    pid = plan.get("planId", name).split("@")[0].lower()
    discount = guaranteed_discount(contract)
    gst_factor = gst_factor * (1 - discount)
    source = SOURCE
    if discount:
        source += f"; rates include the plan's guaranteed {discount * 100:.0f}% discount"
    if len(periods) > 1:
        source += f"; {tp.get('displayName') or 'current season'} rates"
    fit = feed_in(contract)
    extra = {"feedInTariffPerKWh": fit} if fit is not None else {}

    if tp.get("rateBlockUType") == "singleRate" and tp.get("singleRate"):
        rates = tp["singleRate"].get("rates") or []
        if not rates:
            return None
        price = float(rates[0].get("unitPrice", 0)) * gst_factor
        if not (0.03 <= price <= 1.2):
            return None
        return {
            "id": pid, "name": name, "type": "flat",
            "flatRatePerKWh": round(price, 4),
            "indicative": False,
            "source": source,
            **extra,
        }

    tou = tp.get("timeOfUseRates") or []
    if not tou:
        return None
    windows = []
    for band in tou:
        rates = band.get("rates") or []
        if not rates:
            continue
        price = float(rates[0].get("unitPrice", 0)) * gst_factor
        if price < 0 or price > 1.5:
            return None
        label = (band.get("displayName") or band.get("type") or "Rate").title()
        for w in band.get("timeOfUse") or []:
            try:
                windows.append({
                    "label": label,
                    "start": hhmm(w.get("startTime", "00:00")),
                    "end": hhmm(w.get("endTime", "00:00")),
                    "days": day_bucket(w.get("days")),
                    "ratePerKWh": round(price, 4),
                })
            except Exception:
                return None
    if not windows or len(windows) > 12:
        return None
    return {
        "id": pid, "name": name, "type": "timeOfUse",
        "windows": price_labels(windows),
        "indicative": False,
        "source": source,
        **extra,
    }


def interesting(display_name, plan_type):
    """Pick representative plans: EV / free-window / saver names first."""
    n = (display_name or "").lower()
    score = 0
    # A controlled-load copy carries the same usage rates plus a second
    # circuit's tariff: the plain plan comes first.
    if "ctl" in n or "controlled load" in n or "+ cl" in n:
        score -= 40
    for kw, s in [("ev", 30), ("free", 25), ("night", 15), ("saver", 10),
                  ("solar", 8), ("online", 5), ("basic", 5), ("flexi", 5)]:
        if kw in n:
            score += s
    return score


class Listing(dict):
    """A brand's plans by (state, network), plus what reconciling the list
    needs (Codex round 108): every identity the feed listed for the brand,
    and the ones set aside because their geography was not recognised."""
    def __init__(self, groups, listed, unplaced, listed_in=()):
        super().__init__(groups)
        self.listed = listed        # identities in the full raw listing
        self.unplaced = unplaced    # identity -> why it was set aside
        # (state, identity) for every plan placed in a state (Codex round
        # 109): a plan is reconciled where it was listed, not anywhere.
        self.listed_in = set(listed_in)


def page_of(data, brand, page):
    """The plans on one page, after checking the page is the shape the feed
    promises (Codex round 108, P1). A page with no plan list, or no page
    count, was read as a whole brand on one page, so it is refused."""
    if not isinstance(data, dict):
        raise PartialList(f"{brand}: page {page} is not a JSON object")
    body = data.get("data")
    if not isinstance(body, dict) or not isinstance(body.get("plans"), list):
        raise PartialList(f"{brand}: page {page} carries no plan list")
    meta = data.get("meta")
    total = meta.get("totalPages") if isinstance(meta, dict) else None
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise PartialList(f"{brand}: page {page} carries no page count")
    # A retailer with no current market plans answers page 1 of 0 with an
    # empty list (Ergon, Aurora and the empty alinta-energy slug, Oct 2026).
    # That is an answer, not a broken page; refusing it stopped every weekly
    # run from 20 Oct (the developer: "Fix it", 2 Nov). Zero pages with plans
    # on it is not the feed's shape. (A later page saying 0 is already caught:
    # every page must agree with page 1's count.)
    if total == 0 and body["plans"]:
        raise PartialList(f"{brand}: page {page} lists plans but says there are no pages")
    for p in body["plans"]:
        if not isinstance(p, dict) or not isinstance(p.get("planId"), str) or not p["planId"]:
            raise PartialList(f"{brand}: page {page} lists a plan with no id")
    return body["plans"], total


def fetch_brand(brand):
    """Returns a Listing {(state, network): [raw plan list-entries]} or None
    if the brand slug 404s. Network is None outside MULTI_NETWORK_STATES."""
    plans, page, total = [], 1, None
    while True:
        url = (f"{BASE.format(brand=brand)}?fuelType=ELECTRICITY&effective=CURRENT"
               f"&type=MARKET&page-size=1000&page={page}")
        try:
            data = get(url, 1)
        except urllib.error.HTTPError as e:
            # A 404 on the first page is a slug the feed does not know: the
            # caller tries the brand's other spelling. Anything else is the
            # feed failing, and a brand read in part is not written.
            if page == 1 and e.code == 404:
                return None
            raise PartialList(f"{brand}: page {page} answered HTTP {e.code}")
        except Exception as e:
            raise PartialList(f"{brand}: page {page} could not be read ({type(e).__name__})")
        got, pages = page_of(data, brand, page)
        # Every page must agree on how many there are, or the walk is not
        # the listing it claims to be.
        if total is not None and pages != total:
            raise PartialList(f"{brand}: page {page} says {pages} pages, page 1 said {total}")
        total = pages
        plans += got
        if page >= total:
            break
        page += 1
    by_group = defaultdict(list)
    listed, unplaced, listed_in = set(), {}, set()
    for p in plans:
        ident = base_id(p["planId"])
        listed.add(ident)
        dists = (p.get("geography") or {}).get("distributors")
        st = state_for(dists)
        if not st:
            unplaced[ident] = f"distributors {dists!r} are not a network the tool knows"
            continue
        net = network_of(dists) if st in MULTI_NETWORK_STATES else None
        if st in MULTI_NETWORK_STATES and not net:
            unplaced[ident] = f"no single {st} network in {dists!r}"
            continue
        by_group[(st, net)].append(p)
        listed_in.add((st, ident))
    return Listing(dict(by_group), listed, unplaced, listed_in)


def validate(db):
    """What the app's decoder needs (EnergyPlanFetcher.swift: EnergyPlanDatabase,
    EnergyState, EnergyProvider, EnergyPlan, RateWindow). The app decodes the
    whole file in one go, so ONE bad entry and every phone falls back to the
    list it already had. Returns a list of problems; empty means it will read."""
    probs = []
    def need(obj, key, kind, where):
        if key not in obj or not isinstance(obj[key], kind):
            probs.append(f"{where}: '{key}' missing or not {kind.__name__ if isinstance(kind, type) else kind}")
            return False
        return True
    def opt(obj, key, kind, where):
        if key in obj and obj[key] is not None and not isinstance(obj[key], kind):
            probs.append(f"{where}: '{key}' is not {kind}")
    num = (int, float)
    def plan_ok(pl, where):
        for k in ("id", "name"):
            need(pl, k, str, where)
        if pl.get("type") not in ("flat", "timeOfUse"):
            probs.append(f"{where}: type {pl.get('type')!r} is not flat or timeOfUse")
        opt(pl, "flatRatePerKWh", num, where)
        opt(pl, "indicative", bool, where)
        for k in ("source", "notes"):
            opt(pl, k, str, where)
        opt(pl, "feedInTariffPerKWh", num, where)
        if pl.get("windows") is not None:
            if not isinstance(pl["windows"], list):
                probs.append(f"{where}: windows is not a list")
            else:
                for i, w in enumerate(pl["windows"]):
                    ww = f"{where} window {i}"
                    for k in ("label", "start", "end"):
                        need(w, k, str, ww)
                    need(w, "ratePerKWh", num, ww)
                    opt(w, "days", str, ww)
                    opt(w, "freeCapKWhPerDay", num, ww)
                    opt(w, "overCapRatePerKWh", num, ww)
    for k in ("version", "asOf", "currency", "disclaimer"):
        need(db, k, str, "file")
    opt(db, "complete", bool, "file")
    if db.get("completeFor") is not None and not (
            isinstance(db["completeFor"], list) and all(isinstance(x, str) for x in db["completeFor"])):
        probs.append("file: completeFor is not a list of strings")
    if need(db, "fallbackPlans", list, "file"):
        for i, pl in enumerate(db["fallbackPlans"]):
            plan_ok(pl, f"fallback {i}")
    if need(db, "states", list, "file"):
        for st in db["states"]:
            w = f"state {st.get('code')}"
            need(st, "code", str, w); need(st, "name", str, w)
            if need(st, "providers", list, w):
                for pr in st["providers"]:
                    pw = f"{w} / {pr.get('name')}"
                    need(pr, "name", str, pw); opt(pr, "note", str, pw)
                    if need(pr, "plans", list, pw):
                        for pl in pr["plans"]:
                            plan_ok(pl, f"{pw} / {pl.get('name')}")
    return probs


def report(old, new):
    """What changed between two lists, by plan (ids lose their version)."""
    def index(db):
        out = {}
        for st in db["states"]:
            for pr in st["providers"]:
                for pl in pr["plans"]:
                    out[(st["code"], base_id(pl["id"]))] = (pr["name"], pl)
        return out
    a, b = index(old), index(new)
    gone = sorted(k for k in a if k not in b)
    added = sorted(k for k in b if k not in a)
    changed = []
    for k in sorted(set(a) & set(b)):
        pa, pb = a[k][1], b[k][1]
        if (pa.get("flatRatePerKWh"), pa.get("windows")) != (pb.get("flatRatePerKWh"), pb.get("windows")):
            changed.append(k)
    hand = sorted((k, v[0], v[1]["name"]) for k, v in b.items()
                  if not (v[1].get("source") or "").startswith(SOURCE))
    print(f"\nREPORT v{old['version']} -> v{new['version']}")
    print(f"  left the list (the retailer's feed no longer offers them): {len(gone)}")
    for k in gone:
        print(f"    - {k[0]} {a[k][0]}: {a[k][1]['name']}")
    print(f"  new: {len(added)}")
    for k in added:
        print(f"    + {k[0]} {b[k][0]}: {b[k][1]['name']}")
    print(f"  rates or windows changed: {len(changed)}")
    for k in changed:
        print(f"    ~ {k[0]} {b[k][0]}: {b[k][1]['name']}")
    print(f"  hand-kept plans the feed cannot check ({len(hand)}): verify on the retailer's own site")
    for (k, prov, name) in hand:
        print(f"    ? {k[0]} {prov}: {name}")


def main():
    import sys
    root = Path(__file__).resolve().parent.parent
    src = root / "energy-plans-au.json"
    keep_files = [a for i, a in enumerate(sys.argv[1:]) if i > 0 and sys.argv[i] == "--keep-from"]
    confirm = []
    if "--confirm-delisted" in sys.argv:
        for a in sys.argv[sys.argv.index("--confirm-delisted") + 1:]:
            if a.startswith("--"):
                break
            confirm.append(a)
        if not confirm:
            print("--confirm-delisted names each plan checked, as the tool printed it:")
            print("  --confirm-delisted 'QLD|1st Energy|1st1161464mre'")
            raise SystemExit(2)
    if not generate(src, keep_files, confirm=confirm):
        raise SystemExit(1)


def review_key(state, provider, identity):
    """How a plan held for review is named, and confirmed (Codex round 109)."""
    return f"{state}|{provider}|{identity}"


def generate(src, keep_files=(), quiet=False, confirm=()):
    """Read the feed, merge, reconcile and write `src`. Returns True when
    written; on any refusal nothing is written and `src` is left as it was.
    `quiet` is the self-test's."""
    say = (lambda *a, **k: None) if quiet else print
    hand = json.load(open(src))

    # --- GST: EMPIRICALLY PROVEN ex-GST (30 Jul 2026): Ergon T11 regulated
    # rate is 28.895 c/kWh inc GST; the CDR feed returns 0.26268, and
    # 0.26268 x 1.1 = 0.28895 exactly. All CDR unitPrices get the 1.1.
    import copy
    original = copy.deepcopy(hand)   # the report compares against this
    gst_factor = 1.1
    say("GST: applying 1.1 (CDR feed proven ex-GST against Ergon T11)")

    # Plans already listed stay while the feed still offers them, by the one
    # identity rule, from this list and every older one named with
    # --keep-from (Codex round 108, P1). Each is held by WHERE it was listed,
    # its state and provider as well as its identity (Codex round 109): the
    # same identity listed in another state or under another provider does
    # not answer for it.
    carried = {}   # (state, provider, identity) -> name
    for db_ in [hand] + [json.load(open(f)) for f in keep_files]:
        for s_ in db_["states"]:
            for p_ in s_["providers"]:
                for pl in p_["plans"]:
                    if (pl.get("source") or "").startswith(SOURCE):
                        carried.setdefault((s_["code"], p_["name"], base_id(pl["id"])), pl["name"])
    # Plans an earlier run found missing from the feed stay under watch until
    # someone has checked each on the retailer's own site and confirmed it by
    # name (--confirm-delisted, Codex round 109).
    held = {}      # review key -> the record the last run wrote
    for r in hand.get("pendingReview") or []:
        carried.setdefault((r["state"], r["provider"], r["identity"]), r["name"])
        held[review_key(r["state"], r["provider"], r["identity"])] = r
    confirm = set(confirm)
    say(f"carrying forward {len(carried)} listed plans while the feed still offers them")

    brand_names = {
        "agl": "AGL", "origin": "Origin Energy", "energyaustralia": "EnergyAustralia",
        "red-energy": "Red Energy", "red": "Red Energy",
        "alinta-energy": "Alinta Energy", "alinta": "Alinta Energy", "ovo-energy": "OVO Energy", "ovo": "OVO Energy",
        "engie": "Engie", "momentum": "Momentum Energy", "momentum-energy": "Momentum Energy",
        "lumo": "Lumo Energy", "lumo-energy": "Lumo Energy",
        "energy-locals": "Energy Locals", "globird": "GloBird Energy",
        "globird-energy": "GloBird Energy", "1st-energy": "1st Energy",
        "ergon": "Ergon Energy", "ergon-energy": "Ergon Energy",
        "aurora": "Aurora Energy", "aurora-energy": "Aurora Energy",
        "actewagl": "ActewAGL",
        # 5 Nov 2026, each as its plans name it in the feed.
        "powershop": "Powershop", "kogan": "Kogan Energy", "flow-power": "Flow Power",
        "nectr": "Nectr", "tango": "Tango Energy", "sumo-power": "Sumo", "dodo": "Dodo",
        "diamond": "Diamond Energy", "covau": "CovaU", "gee-energy": "GEE Energy",
        "flipped": "Flipped Energy", "arcline": "Arcline by RACV",
        "solstice": "Solstice Energy", "radian": "iO Energy", "silver-asset": "Ezi Power",
    }

    # Every provider the list carries a feed plan for, in this list, an older
    # one named with --keep-from, or held for review: each must be read
    # again, or its plans would vanish, or a held plan be let go, for want of
    # an answer (Codex round 109, P1: a provider with no plan left in the list
    # but one held for review was not asked about, and the hold was dropped).
    required_providers = {prov for (_, prov, _) in carried}
    failures = []

    cdr_states = defaultdict(lambda: defaultdict(list))   # state -> provider -> plans
    seen_brands = set()
    listed_by_brand = {}     # provider -> identities the feed listed for it
    listed_in_by_brand = {}  # provider -> (state, identity) placed in a state
    unplaced_by_brand = {}   # provider -> identity -> why it was set aside
    for slug in BRANDS:
        bname = brand_names.get(slug, slug)
        if bname in seen_brands:
            continue
        try:
            listing = fetch_brand(slug)
        except PartialList as e:
            failures.append(str(e))
            continue
        if listing is None or not listing.listed:
            continue   # an empty answer can be the wrong slug: try the next
        seen_brands.add(bname)
        listed_by_brand[bname] = listing.listed
        listed_in_by_brand[bname] = listing.listed_in
        unplaced_by_brand[bname] = listing.unplaced
        total = sum(len(v) for v in listing.values())
        say(f"  {slug}: {total} current market plans across "
              f"{sorted({f'{s}' + (f' {n}' if n else '') for s, n in listing})}")
        for (st, net), plans in listing.items():
            # Owner-reported plans first, then the scored ones.
            def forced_(p):
                b = base_id(p["planId"])
                return b in ALWAYS_INCLUDE or (st, bname, b) in carried
            # Score order, ties by name then id, so a week's run picks the
            # same plans as the week before and the list does not creep.
            plans.sort(key=lambda p: (-interesting(p.get("displayName"), None),
                                      p.get("displayName") or "", p["planId"]))
            cap = MAX_PLANS_PER_BRAND_NETWORK if net else MAX_PLANS_PER_BRAND_STATE
            picked, seen_names, seen_ids, new_picks = [], set(), set(), 0
            for p in plans:
                dn = p.get("displayName") or ""
                key = dn.lower()
                forced = forced_(p)
                # A business plan is never a new pick (5 Nov 2026); one the
                # list already carries stays while the feed offers it.
                if (p.get("customerType") or "").upper() == "BUSINESS" and not forced:
                    continue
                # The top `cap` plans by score, plus every plan already listed
                # (or reported by an owner) wherever it ranks.
                within_cap = new_picks < cap and key not in seen_names
                if not (within_cap or forced):
                    continue
                try:
                    det = get(f"{BASE.format(brand=slug)}/{urllib.parse.quote(p['planId'])}", 3)
                except Exception as e:
                    # A plan the list already carries must be read again, or
                    # it vanishes as though the retailer had stopped offering
                    # it. A new pick that cannot be read was never listed.
                    if forced:
                        failures.append(f"{slug} {p['planId']}: details could not be read ({type(e).__name__})")
                    continue
                conv = convert_plan(det, bname, gst_factor, network=net)
                if not conv and forced:
                    failures.append(f"{slug} {p['planId']}: listed before, and its details no longer convert")
                    continue
                if not conv or conv["id"] in seen_ids:
                    continue
                seen_names.add(key)
                seen_ids.add(conv["id"])
                picked.append(conv)
                if within_cap:
                    new_picks += 1
            if picked:
                cdr_states[st][bname].extend(picked)

    # A provider the list needs that gave no conclusive answer (a slug the
    # feed does not know, an empty listing, a failure on the way) leaves its
    # plans unknown: nothing is written, so a plan held for review stays held
    # and nothing is certified for it (Codex round 109, P1).
    for name in sorted(required_providers - seen_brands):
        failures.append(f"{name}: the list carries or holds for review its plans, "
                        "and the feed gave no answer for it")

    # RECONCILE EVERY CARRIED PLAN, BY STATE, PROVIDER AND IDENTITY, before
    # anything is certified (Codex rounds 108 and 109). A plan the list
    # carried is in the new list in the same state under the same provider,
    # or the feed read in full does not list it there (the retailer's own
    # feed no longer offers it there, reported, not refused), or something
    # else lost it and nothing is written: a geography the tool does not
    # recognise, or the feed listing it there while the tool did not keep it.
    kept_keys = {(st_, prov_, base_id(pl["id"])) for st_, provs_ in cdr_states.items()
                 for prov_, plans_ in provs_.items() for pl in plans_}
    missing = []   # (state, provider, name, identity) no longer in the feed there
    reissued = []  # the same, in a state never certified: let go, unheld
    for (st, prov, ident), name in sorted(carried.items()):
        if (st, prov, ident) in kept_keys:
            continue
        if prov not in listed_by_brand:
            continue   # its provider gave no answer: a failure above
        if ident in unplaced_by_brand.get(prov, {}):
            failures.append(f"{prov} {name} ({ident}, {st}): listed by the feed, but set aside: "
                            + unplaced_by_brand[prov][ident])
        elif (st, ident) in listed_in_by_brand.get(prov, set()):
            failures.append(f"{prov} {name} ({ident}, {st}): the feed lists it and the tool did not keep it")
        elif st in UNCERTIFIED_FEED_STATES:
            reissued.append((st, prov, name, ident))
        else:
            missing.append((st, prov, name, ident))

    # A CONFIRMATION NAMES THE PLAN A PERSON CHECKED (Codex round 109, P1).
    # It must be one the last run held for review and still be missing now:
    # a plan nobody was shown, or one back in the feed, is refused, and every
    # plan missing that nobody confirmed stays held.
    missing_keys = {review_key(st, prov, ident) for (st, prov, _, ident) in missing}
    for key in sorted(confirm):
        if key not in held:
            failures.append(f"--confirm-delisted {key!r}: not held for review in this list, "
                            "so nobody was shown it (run without the flag to see what is held)")
        elif key not in missing_keys:
            failures.append(f"--confirm-delisted {key!r}: it is back in the feed or no longer "
                            "carried, so there is nothing to confirm")
    generate.last_failures = list(failures)
    if failures:
        say("\nNOT WRITTEN: the list would be partial, and the app would read a plan the")
        say("feed did not answer for as one the retailer no longer offers:")
        for f_ in failures[:40]:
            say("  ", f_)
        return False

    # Drop plans from any previous CDR run — they are fully regenerated.
    for s_ in hand["states"]:
        for p_ in s_["providers"]:
            p_["plans"] = [pl for pl in p_["plans"]
                           if not (pl.get("source") or "").startswith(SOURCE)]
        s_["providers"] = [p_ for p_ in s_["providers"] if p_["plans"]]

    # --- merge: CDR replaces the providers it found; hand entries kept for
    # WA/NT, for providers the CDR missed, and every hand-kept (dashed) plan,
    # Victoria's included, and a tester's own plan.
    out_states = []
    for s in hand["states"]:
        code = s["code"]
        if code in cdr_states:
            merged_providers = []
            cdr_provs = cdr_states[code]
            hand_provs = {p["name"]: p for p in s["providers"]}
            for pname, plans in sorted(cdr_provs.items()):
                extra = []
                if pname in hand_provs:
                    # keep tester-sourced or verified hand plans not superseded
                    for hp in hand_provs[pname]["plans"]:
                        # Preserve every hand-crafted plan: tester-reported,
                        # bill-verified, and hand-built sets all carry dashed
                        # ids; CDR planIds are bare alphanumerics. (2 Aug:
                        # the old rule deleted the Engie bill plan.)
                        if ("tester-reported" in (hp.get("source") or "")
                                or "-" in hp.get("id", "")):
                            extra.append(hp)
                note = hand_provs.get(pname, {}).get("note")
                merged_providers.append({"name": pname,
                                         **({"note": note} if note else {}),
                                         "plans": extra + plans})
            for pname, hp in hand_provs.items():
                if pname not in cdr_provs:
                    merged_providers.append(hp)
            out_states.append({"code": code, "name": s["name"],
                               "providers": merged_providers})
        else:
            out_states.append(s)

    import datetime
    out = dict(hand)
    major, minor = (int(x) for x in hand["version"].split(".")[:2])
    out["version"] = f"{major}.{minor + 1}.0"
    out["asOf"] = datetime.date.today().isoformat()
    out["states"] = out_states
    # Every brand, page and listed plan was read and every carried plan
    # accounted for (Codex rounds 106 and 108). The list certifies only what
    # was checked (Codex round 109): each feed provider read in full, in a
    # feed state where it lists plans, or where a plan of its was confirmed
    # gone. Hand-kept plans and the states the feed does not cover are not
    # certified, and the app says nothing about a plan missing from them.
    #
    # A PLAN THE FEED NO LONGER LISTS cannot be told apart from a listing cut
    # short with no error (Codex round 108: "require review where it cannot
    # be distinguished"). So it is held for review, by name, and its
    # provider's state is not certified while it is held; the app says
    # nothing about a missing plan there until someone has checked it on the
    # retailer's own site and confirmed it with --confirm-delisted.
    confirmed = [m for m in missing if review_key(m[0], m[1], m[3]) in confirm]
    pending = [m for m in missing if review_key(m[0], m[1], m[3]) not in confirm]
    out.pop("pendingReview", None)
    out.pop("complete", None)
    out.pop("completeFor", None)
    if pending:
        out["pendingReview"] = [
            {"identity": i, "state": st, "provider": prov, "name": name,
             "since": held.get(review_key(st, prov, i), {}).get("since", out["asOf"])}
            for (st, prov, name, i) in pending]
        say(f"\nHELD FOR REVIEW: {len(pending)} listed plan(s) are no longer in the feed, and their")
        say("provider's state is not certified. Check each on the retailer's own site, then confirm")
        say("the ones that have really gone, by name:")
        for (st, prov, name, i) in pending:
            say(f"    --confirm-delisted '{review_key(st, prov, i)}'   ({name})")
    held_scopes = {(st, prov) for (st, prov, _, _) in pending}
    gone_scopes = {(st, prov) for (st, prov, _, _) in confirmed}
    certified = sorted(
        f"{st}|{prov}" for prov in seen_brands for st in FEED_STATES
        if (st, prov) not in held_scopes
        and (any(s == st for (s, _) in listed_in_by_brand.get(prov, set())) or (st, prov) in gone_scopes))
    if certified:
        out["complete"] = True
        out["completeFor"] = certified
    for (st, prov, name, i) in confirmed:
        say(f"  confirmed gone from the feed: {st} {prov}: {name} ({i})")
    problems = validate(out)
    if problems:
        say("\nNOT WRITTEN: the app could not read this list:")
        for pr in problems[:40]:
            say("  ", pr)
        return False
    if not quiet:
        report(original, out)
    # Two current plans with one identity in a state: the app cannot tell
    # which an owner is on, and says nothing about either (round 108).
    for st_ in out_states:
        seen_ = defaultdict(list)
        for pr_ in st_["providers"]:
            for pl in pr_["plans"]:
                seen_[base_id(pl["id"])].append(pl["id"])
        for ident, ids in seen_.items():
            if len(ids) > 1:
                say(f"  ambiguous identity in {st_['code']}: {ident} is {', '.join(ids)}")
    say(f"  left the feed in a state never certified, let go ({len(reissued)}):")
    for (st, prov, name, ident) in reissued:
        say(f"    - {st} {prov}: {name} ({ident})")
    say(f"  no longer in the retailer's feed ({len(missing)}):")
    for (st, prov, name, ident) in missing:
        say(f"    - {st} {prov}: {name} ({ident})")
    open(src, "w").write(json.dumps(out, indent=2, ensure_ascii=False))

    provs = sum(len(s["providers"]) for s in out_states)
    plans = sum(len(p["plans"]) for s in out_states for p in s["providers"])
    verified = sum(1 for s in out_states for p in s["providers"]
                   for pl in p["plans"] if not pl.get("indicative", True))
    say(f"\nWROTE v{out['version']}: {len(out_states)} states, {provs} providers, "
          f"{plans} plans, {verified} verified")
    return True


def selftest():
    """The partial-list rule, with the feed's answers stood in (19 Oct)."""
    import io
    global get
    real = get
    def http(code):
        return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b""))
    try:
        def wrong_slug(url, xv): raise http(404)
        get = wrong_slug
        assert fetch_brand("nobody") is None, "a 404 on page 1 is a wrong slug"
        def page_two_fails(url, xv):
            if "page=1" in url:
                return {"data": {"plans": []}, "meta": {"totalPages": 2}}
            raise http(503)
        get = page_two_fails
        try:
            fetch_brand("agl"); raise AssertionError("a failed page 2 was taken as the whole brand")
        except PartialList:
            pass
        # A retailer with nothing on offer answers page 1 of 0 (2 Nov).
        def nothing_on_offer(url, xv):
            return {"data": {"plans": []}, "meta": {"totalPages": 0}}
        get = nothing_on_offer
        empty = fetch_brand("ergon")
        assert empty is not None and not empty.listed, \
            "a retailer with nothing on offer was refused or read as a wrong slug"
        def zero_but_plans(url, xv):
            return {"data": {"plans": [{"planId": "AGL1@EME"}]}, "meta": {"totalPages": 0}}
        get = zero_but_plans
        try:
            fetch_brand("agl"); raise AssertionError("a page of 0 that lists plans was taken")
        except PartialList:
            pass
        def unavailable(url, xv): raise http(503)
        get = unavailable
        try:
            fetch_brand("agl"); raise AssertionError("a 503 on page 1 was taken as a wrong slug")
        except PartialList:
            pass
        def timeout(url, xv): raise TimeoutError()
        get = timeout
        try:
            fetch_brand("agl"); raise AssertionError("a timeout on page 1 was taken as a wrong slug")
        except PartialList:
            pass
        # ── The one identity rule, the same cases the app reads ──
        root = Path(__file__).resolve().parent.parent
        cases = json.load(open(root / "tools/fixtures/plan-identity-cases.json"))["cases"]
        for c in cases:
            assert base_id(c["id"]) == c["identity"], f"{c['id']} -> {base_id(c['id'])}, not {c['identity']}"
        # Every id in the shipped list: a feed id loses only its version.
        shipped = json.load(open(root / "energy-plans-au.json"))
        import re as _re
        for st in shipped["states"]:
            for pr in st["providers"]:
                for pl in pr["plans"]:
                    if (pl.get("source") or "").startswith(SOURCE):
                        assert _re.match(r"^[a-z0-9]*[0-9][a-z]+$", base_id(pl["id"])), pl["id"]

        # ── Windows named by price when the feed only numbers them (5 Nov) ──
        def W(label, rate, start="00:00", end="24:00"):
            return {"label": label, "start": start, "end": end, "days": "all", "ratePerKWh": rate}
        free4 = price_labels([W("Tariff 1", 0.4333), W("Tariff 2", 0.2339), W("Tariff 2", 0.2339),
                              W("Tariff 3", 0.0)])
        assert [w["label"] for w in free4] == ["Peak", "Off-peak", "Off-peak", "Free"], free4
        ev = price_labels([W("Tariff 1", 0.2906), W("Tariff 2", 0.045)])
        assert [w["label"] for w in ev] == ["Peak", "Off-peak"], ev
        three = price_labels([W("Tariff 1", 0.40), W("Tariff 2", 0.25), W("Tariff 3", 0.30)])
        assert [w["label"] for w in three] == ["Peak", "Off-peak", "Shoulder"], three
        four = price_labels([W("Rate 1", 0.40), W("Rate 2", 0.20), W("Rate 3", 0.30), W("Rate 4", 0.25)])
        assert [w["label"] for w in four] == ["Peak", "Off-peak", "Shoulder 2", "Shoulder 1"], four
        one = price_labels([W("Tariff 1", 0.28), W("Tariff 2", 0.0)])
        assert [w["label"] for w in one] == ["Standard", "Free"], one
        named = [W("Peak", 0.40), W("Off Peak", 0.20)]
        assert price_labels(named) == named, "a plan's own names were replaced"
        mixed = [W("Tariff 1", 0.40), W("Solar Soak", 0.0)]
        assert price_labels(mixed) == mixed, "a plan with one real label lost it"
        tas = [W("Tariff 93 Peak", 0.38), W("Tariff 93 Op Rates", 0.20)]
        assert price_labels(tas) == tas, "Tasmania's tariff names were replaced"
        assert [w["ratePerKWh"] for w in free4] == [0.4333, 0.2339, 0.2339, 0.0], "a rate moved"
        tou_detail = {"data": {"planId": "OVO803472MR@VEC", "displayName": "The Free 4 Plan - OCT2026",
            "electricityContract": {"tariffPeriod": [{"rateBlockUType": "timeOfUseRates", "timeOfUseRates": [
                {"displayName": "Tariff 1", "rates": [{"unitPrice": "0.3552"}],
                 "timeOfUse": [{"days": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
                                "startTime": "15:00", "endTime": "21:00"}]},
                {"displayName": "Tariff 2", "rates": [{"unitPrice": "0.1963"}],
                 "timeOfUse": [{"days": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
                                "startTime": "21:00", "endTime": "11:00"}]},
                {"displayName": "Tariff 3", "rates": [{"unitPrice": "0"}],
                 "timeOfUse": [{"days": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
                                "startTime": "11:00", "endTime": "15:00"}]}]}]}}}
        conv = convert_plan(tou_detail, "OVO Energy", 1.1, network="CitiPower")
        assert [w["label"] for w in conv["windows"]] == ["Peak", "Off-peak", "Free"], conv["windows"]

        # ── The whole run, tool to output, against a stand-in feed ──
        end_to_end(http)
    finally:
        get = real
    print("selftest ok")


def end_to_end(http):
    """Codex round 108, P1: the generation and merge, start to finish, with
    the feed stood in. Each refusal leaves the existing list byte for byte."""
    import tempfile
    global get
    QLD = ["Energex"]
    hand = {
        "version": "0.10.0", "asOf": "2026-10-19", "currency": "AUD", "disclaimer": "x",
        "fallbackPlans": [],
        "states": [
            {"code": "QLD", "name": "Queensland", "providers": [
                {"name": "1st Energy", "plans": [
                    {"id": "1st1161464mre1", "name": "Low pick", "type": "flat",
                     "flatRatePerKWh": 0.3, "indicative": False, "source": SOURCE}]}]},
            {"code": "WA", "name": "Western Australia", "providers": [
                {"name": "Synergy", "plans": [
                    {"id": "synergy-home-plan", "name": "Home Plan (A1)", "type": "flat",
                     "flatRatePerKWh": 0.31, "indicative": True, "source": "retailer site"}]}]},
        ],
    }

    def entry(pid, name, dists=QLD, customer=None):
        e = {"planId": pid, "displayName": name, "geography": {"distributors": dists}}
        if customer:
            e["customerType"] = customer
        return e

    def detail(pid, name):
        return {"data": {"planId": pid, "displayName": name, "electricityContract": {"tariffPeriod": [
            {"rateBlockUType": "singleRate", "singleRate": {"rates": [{"unitPrice": "0.25"}]}}]}}}

    # Five plans that out-score the stored one, so it sits below the cap,
    # and the stored plan under its next version.
    top = [entry(f"1ST200000{i}MRE1@EME", f"EV Saver {i}") for i in range(5)]
    low = entry("1ST1161464MRE2@EME", "Low pick")

    def feed(pages, details=None, fail_detail=()):
        def fake(url, xv):
            brand = url.split("cdr.energymadeeasy.gov.au/")[1].split("/")[0]
            if brand != "1st-energy":
                raise http(404)
            if "?" in url:
                n = int(url.rsplit("page=", 1)[1])
                page = pages[n - 1]
                if isinstance(page, Exception):
                    raise page
                return page
            pid = urllib.parse.unquote(url.rsplit("/", 1)[1])
            if pid in fail_detail:
                raise http(503)
            name = next(p["displayName"] for pg in pages if isinstance(pg, dict)
                        for p in (pg.get("data") or {}).get("plans") or [] if p["planId"] == pid)
            return detail(pid, name)
        return fake

    def one_page(plans, total=1):
        return {"data": {"plans": plans}, "meta": {"totalPages": total}}

    def run(fake, start=hand, **kw):
        global get
        d = tempfile.mkdtemp()
        src = Path(d) / "plans.json"
        src.write_text(json.dumps(start))
        before = src.read_bytes()
        get = fake
        ok = generate(src, quiet=True, **kw)
        after = json.loads(src.read_text())
        if not ok:
            assert src.read_bytes() == before, "a refused run changed the list"
        return ok, after

    def qld_ids(db):
        return [pl["id"] for st in db["states"] if st["code"] == "QLD"
                for pr in st["providers"] for pl in pr["plans"]]

    # 1. 1st Energy's next version, below the cap: kept, certified.
    ok, out = run(feed([one_page(top + [low])]))
    assert ok, "the preservation run was refused"
    assert "1st1161464mre2" in qld_ids(out), "a stored plan's next version was dropped below the cap"
    assert out.get("complete") is True and "QLD|1st Energy" in out["completeFor"]
    assert "WA|Synergy" not in out["completeFor"], "a hand-kept state was certified"
    assert any(pl["id"] == "synergy-home-plan" for st in out["states"] for pr in st["providers"]
               for pl in pr["plans"]), "a hand-kept plan was lost"

    # 2. A page with no page count, or no plan list: refused, list intact.
    ok, _ = run(feed([{"data": {"plans": top + [low]}}]))
    assert not ok and any("no page count" in f for f in generate.last_failures), \
        "a page with no page count was read as the whole brand"
    ok, _ = run(feed([{"meta": {"totalPages": 1}}]))
    assert not ok and any("no plan list" in f for f in generate.last_failures), \
        f"a page with no plan list was read as an empty brand: {generate.last_failures}"

    # 3. A later page that fails, and pages that disagree on the count.
    ok, _ = run(feed([one_page(top, total=2), http(503)]))
    assert not ok, "a failed page 2 was taken as the whole brand"
    ok, _ = run(feed([one_page(top, total=2), one_page([low], total=3), one_page([])]))
    assert not ok, "pages that disagree on the count were taken as the listing"

    # 4. The stored plan on a network the tool does not know, beside a valid
    #    plan of the same brand: a named failure, not a removal.
    ok, _ = run(feed([one_page(top + [entry("1ST1161464MRE2@EME", "Low pick", ["Mystery Grid"])])]))
    assert not ok and any("set aside" in f for f in generate.last_failures), \
        f"a carried plan set aside for its geography was not named: {generate.last_failures}"
    # The control: an unknown network on a plan nobody carried is only set aside.
    ok, _ = run(feed([one_page(top + [low, entry("1ST3000000MRE1@EME", "Odd", ["Mystery Grid"])])]))
    assert ok, "an unplaced plan nobody carried refused the list"

    # 5. The stored plan's details fail to read, or to convert.
    ok, _ = run(feed([one_page(top + [low])], fail_detail=("1ST1161464MRE2@EME",)))
    assert not ok, "a carried plan whose details could not be read was dropped"

    # 6. A genuine delisting: written, not certified, kept for review, and
    #    certified only once confirmed, by name.
    A = "QLD|1st Energy|1st1161464mre"
    ok, out = run(feed([one_page(top)]))
    assert ok and "QLD|1st Energy" not in (out.get("completeFor") or []), \
        "a list missing a carried plan was certified for it"
    assert [r["identity"] for r in out["pendingReview"]] == ["1st1161464mre"]
    ok, again = run(feed([one_page(top)]), start=out)
    assert ok and "QLD|1st Energy" not in (again.get("completeFor") or []), \
        "a second run certified the unreviewed plan"
    ok, confirmed = run(feed([one_page(top)]), start=out, confirm=[A])
    assert ok and confirmed.get("complete") is True and "pendingReview" not in confirmed
    assert "QLD|1st Energy" in confirmed["completeFor"]
    assert "NSW|1st Energy" not in confirmed["completeFor"], \
        "a state where the provider lists nothing was certified"

    # ── Codex round 109, P1: a held plan is never let go for want of an answer ──
    # Generation 1: the carried plan leaves the feed and the provider's only
    # other raw entry is on a network the tool does not know, so the list
    # keeps no 1st Energy plan at all, and the missing plan is held.
    odd = entry("1ST3000000MRE1@EME", "Odd", ["Mystery Grid"])
    ok, gen1 = run(feed([one_page([odd])]))
    assert ok and qld_ids(gen1) == [], "the precondition: no 1st Energy plan left in the list"
    assert [r["identity"] for r in gen1["pendingReview"]] == ["1st1161464mre"]
    assert "QLD|1st Energy" not in (gen1.get("completeFor") or [])
    # Generation 2: every 1st Energy slug answers 404. The held plan's
    # provider gave no answer, so nothing is written: the hold stands.
    def all_404(url, xv): raise http(404)
    ok, gen2 = run(all_404, start=gen1)
    assert not ok and any("1st Energy" in f and "no answer" in f for f in generate.last_failures), \
        f"a held plan's provider gave no answer and the list was written: {generate.last_failures}"
    assert gen2["pendingReview"] == gen1["pendingReview"], "the hold was dropped"
    # The same with an empty listing, and with a timeout.
    ok, _ = run(feed([one_page([])]), start=gen1)
    assert not ok, "an empty listing let a held plan go"
    ok, _ = run(feed([TimeoutError()]), start=gen1)
    assert not ok, "a timeout let a held plan go"
    # Generation 3: the provider returns with other plans. The held plan is
    # still missing, so it is still held and the provider's state uncertified.
    aged = json.loads(json.dumps(gen1))
    aged["pendingReview"][0]["since"] = "2026-10-01"   # held since an earlier run
    ok, gen3 = run(feed([one_page(top)]), start=aged)
    assert ok and [r["identity"] for r in gen3["pendingReview"]] == ["1st1161464mre"], \
        "the provider's return let the held plan go"
    assert "QLD|1st Energy" not in (gen3.get("completeFor") or []), \
        "the provider's state was certified with a plan still held"
    assert gen3["pendingReview"][0]["since"] == "2026-10-01", \
        "the hold forgot when it began"
    # Recovery: the plan comes back; nothing is held, and the state is certified.
    ok, back = run(feed([one_page(top + [low])]), start=gen1)
    assert ok and "pendingReview" not in back and "QLD|1st Energy" in back["completeFor"]
    # A provider known only from --keep-from must answer too.
    bare = json.loads(json.dumps(hand))
    bare["states"][0]["providers"] = []
    d = tempfile.mkdtemp()
    keep = Path(d) / "keep.json"
    keep.write_text(json.dumps(hand))
    ok, _ = run(all_404, start=bare, keep_files=[str(keep)])
    assert not ok and any("1st Energy" in f for f in generate.last_failures), \
        "a provider known only from --keep-from was let off answering"

    # ── Codex round 109, P1: a confirmation covers only the plan checked ──
    # Two carried plans; A leaves the feed and is held. Before A is confirmed,
    # B leaves too. Confirming A confirms A alone: B is held, and the state
    # stays uncertified while B is.
    B = {"id": "1st1122748mbe1", "name": "Other pick", "type": "flat",
         "flatRatePerKWh": 0.3, "indicative": False, "source": SOURCE}
    two = json.loads(json.dumps(hand))
    two["states"][0]["providers"][0]["plans"].append(B)
    b_entry = entry("1ST1122748MBE2@EME", "Other pick")
    ok, held_a = run(feed([one_page(top + [b_entry])]), start=two)
    assert ok and [r["identity"] for r in held_a["pendingReview"]] == ["1st1161464mre"]
    ok, both = run(feed([one_page(top)]), start=held_a, confirm=[A])
    assert ok, f"confirming the checked plan was refused: {generate.last_failures}"
    assert [r["identity"] for r in both.get("pendingReview") or []] == ["1st1122748mbe"], \
        "a plan nobody checked was confirmed with the one that was"
    assert "QLD|1st Energy" not in (both.get("completeFor") or []), \
        "the state was certified while a plan in it is held"
    # A first run with a confirmation: nobody was shown anything. Refused.
    ok, _ = run(feed([one_page(top)]), confirm=[A])
    assert not ok and any("not held for review" in f for f in generate.last_failures), \
        "a confirmation of a plan nobody was shown was taken"
    # A confirmation of a plan back in the feed is stale. Refused.
    ok, _ = run(feed([one_page(top + [low])]), start=gen1, confirm=[A])
    assert not ok and any("back in the feed" in f for f in generate.last_failures), \
        "a stale confirmation was taken"
    # The provider failing while a plan is confirmed. Refused, list intact.
    ok, _ = run(feed([http(503)]), start=gen1, confirm=[A])
    assert not ok, "a confirmation went through with the provider failing"

    # ── Codex round 109, P2: one identity in two states is two plans ──
    nsw = entry("1ST1161464MRE2@EME", "Low pick", ["Ausgrid"])
    twostate = json.loads(json.dumps(hand))
    twostate["states"].append({"code": "NSW", "name": "New South Wales", "providers": [
        {"name": "1st Energy", "plans": [
            {"id": "1st1161464mre1", "name": "Low pick (Ausgrid)", "type": "flat",
             "flatRatePerKWh": 0.3, "indicative": False, "source": SOURCE}]}]})
    # Both listed: both kept, both states certified.
    ok, out = run(feed([one_page(top + [low, nsw])]), start=twostate)
    assert ok and "pendingReview" not in out
    assert "QLD|1st Energy" in out["completeFor"] and "NSW|1st Energy" in out["completeFor"]
    # Only the QLD one listed: QLD's copy does not answer for NSW's.
    ok, out = run(feed([one_page(top + [low])]), start=twostate)
    assert ok and [(r["state"], r["identity"]) for r in out.get("pendingReview") or []] == \
        [("NSW", "1st1161464mre")], "one state's copy answered for the other's"
    assert "QLD|1st Energy" in out["completeFor"] and "NSW|1st Energy" not in out["completeFor"]
    # A hand-kept plan under a feed provider stays, whatever the feed says.
    handkept = json.loads(json.dumps(hand))
    handkept["states"][0]["providers"][0]["plans"].append(
        {"id": "1st-tester-plan", "name": "Tester's plan", "type": "flat",
         "flatRatePerKWh": 0.2, "indicative": True, "source": "tester-reported"})
    ok, out = run(feed([one_page(top + [low])]), start=handkept)
    assert ok and "1st-tester-plan" in qld_ids(out), "a hand-kept plan under a feed provider was lost"

    # 7. --keep-from: a plan from an older list is carried too.
    older = json.loads(json.dumps(hand))
    older["states"][0]["providers"][0]["plans"].append(
        {"id": "1st1122748mbe1", "name": "Older pick", "type": "flat",
         "flatRatePerKWh": 0.3, "indicative": False, "source": SOURCE})
    d = tempfile.mkdtemp()
    old_path = Path(d) / "older.json"
    old_path.write_text(json.dumps(older))
    ok, out = run(feed([one_page(top + [low, entry("1ST1122748MBE2@EME", "Older pick")])]),
                  keep_files=[str(old_path)])
    assert ok and "1st1122748mbe2" in qld_ids(out), "a plan from --keep-from was not carried"

    # 8. Retailers with nothing on offer (2 Nov: Ergon, Aurora and the empty
    #    alinta-energy slug answer page 1 of 0). An answer, not a broken page:
    #    the list is written and certified as before.
    normal = feed([one_page(top + [low])])
    def with_empty(url, xv):
        brand = url.split("cdr.energymadeeasy.gov.au/")[1].split("/")[0]
        if brand in ("ergon", "aurora", "alinta-energy"):
            return one_page([], total=0)
        return normal(url, xv)
    ok, out = run(with_empty)
    assert ok, f"a retailer with nothing on offer refused the list: {generate.last_failures}"
    assert out.get("complete") is True and "QLD|1st Energy" in out["completeFor"]
    assert not any(c.endswith(("Ergon Energy", "Aurora Energy")) for c in out["completeFor"]), \
        "a retailer that listed nothing was certified"
    # Zero pages from a provider the list carries is no answer: refused, list intact.
    ok, _ = run(feed([one_page([], total=0)]))
    assert not ok and any("1st Energy" in f and "no answer" in f for f in generate.last_failures), \
        f"a carried provider answering 0 pages let its plans go: {generate.last_failures}"
    ok, _ = run(feed([one_page([], total=0)]), start=gen1)
    assert not ok, "a held plan's provider answering 0 pages let the hold go"
    # Zero pages that list plans: refused.
    ok, _ = run(feed([one_page(top + [low], total=0)]))
    assert not ok and any("says there are no pages" in f for f in generate.last_failures), \
        f"a page of 0 listing plans was taken: {generate.last_failures}"

    # 9. VICTORIA (5 Nov 2026): read from the feed on its five networks,
    #    each plan named for its network, never certified; a Victorian plan
    #    that leaves the feed leaves the list unheld; hand-kept ones stay.
    for d_, net_ in [("Citipower", "CitiPower"), ("Powercor", "Powercor"), ("Jemena", "Jemena"),
                     ("United Energy", "United Energy"), ("AusNet Services (electricity)", "AusNet")]:
        assert state_for([d_]) == "VIC", f"{d_} is not read as Victoria"
        assert network_of([d_]) == net_, f"{d_} is not the {net_} network"
    assert state_for(["Ausgrid"]) == "NSW" and network_of(["Ausgrid"]) == "Ausgrid"
    vic = json.loads(json.dumps(hand))
    vic["states"].append({"code": "VIC", "name": "Victoria", "providers": [
        {"name": "1st Energy", "plans": [
            {"id": "1st-vic-hand", "name": "Hand-kept", "type": "flat",
             "flatRatePerKWh": 0.3, "indicative": True, "source": "retailer site"}]}]})
    one = entry("1ST811723MR@VEC", "The One Plan - NOV2026", ["Citipower"])
    ok, v1 = run(feed([one_page(top + [low, one])]), start=vic)
    assert ok, f"a Victorian plan refused the list: {generate.last_failures}"
    vic_plans = [pl for st in v1["states"] if st["code"] == "VIC"
                 for pr in st["providers"] if pr["name"] == "1st Energy" for pl in pr["plans"]]
    assert any(pl["id"] == "1st811723mr" and pl["name"] == "The One Plan - NOV2026 (CitiPower)"
               for pl in vic_plans), f"the Victorian plan was not kept by its network: {vic_plans}"
    assert any(pl["id"] == "1st-vic-hand" for pl in vic_plans), "a hand-kept Victorian plan was lost"
    assert "VIC|1st Energy" not in v1["completeFor"], "Victoria was certified"
    assert "QLD|1st Energy" in v1["completeFor"]
    # Next month: reissued under a new id, the old one gone. Written, not
    # held, Queensland still certified, the new one in, the old one out.
    dec = entry("1ST822001MR@VEC", "The One Plan - DEC2026", ["Citipower"])
    ok, v2 = run(feed([one_page(top + [low, dec])]), start=v1)
    assert ok and "pendingReview" not in v2, \
        f"a reissued Victorian plan was held for review: {v2.get('pendingReview')}"
    assert "QLD|1st Energy" in v2["completeFor"], "a Victorian reissue uncertified Queensland"
    vic_ids = [pl["id"] for st in v2["states"] if st["code"] == "VIC"
               for pr in st["providers"] for pl in pr["plans"]]
    assert "1st822001mr" in vic_ids and "1st811723mr" not in vic_ids, vic_ids
    # The control: the same departure in Queensland is still held.
    ok, q = run(feed([one_page(top)]), start=v1)
    assert ok and [r["identity"] for r in q["pendingReview"]] == ["1st1161464mre"]

    # 10. BUSINESS PLANS (5 Nov 2026): never a new pick, whatever they
    #     score; one the list already carries stays while it is offered.
    biz = entry("1ST4000000MBE1@EME", "EV Free Night Saver Business", customer="BUSINESS")
    home = entry("1ST4000001MRE1@EME", "Plain Home", customer="RESIDENTIAL")
    ok, out = run(feed([one_page([biz, home, low])]))
    assert ok and "1st4000000mbe" not in [base_id(i) for i in qld_ids(out)], \
        "a business plan was picked"
    assert "1st4000001mre" in [base_id(i) for i in qld_ids(out)], "the household plan was not picked"
    carried_biz = json.loads(json.dumps(hand))
    carried_biz["states"][0]["providers"][0]["plans"].append(
        {"id": "1st4000000mbe1", "name": "EV Free Night Saver Business", "type": "flat",
         "flatRatePerKWh": 0.3, "indicative": False, "source": SOURCE})
    ok, out = run(feed([one_page([biz, home, low])]), start=carried_biz)
    assert ok and "1st4000000mbe1" in qld_ids(out), \
        f"a business plan the list carried was dropped while still offered: {generate.last_failures}"


if __name__ == "__main__":
    import sys as _sys
    if "--selftest" in _sys.argv:
        selftest()
    else:
        main()
