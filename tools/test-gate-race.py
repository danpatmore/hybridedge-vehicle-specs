#!/usr/bin/env python3
"""
test-gate-race.py: the gate with GitHub stood in, pushed to between its
reads (Codex round 159, P1; its probe tests/gate_race.py, made a pass/fail
regression). Nothing touches GitHub.

Usage: python3 -I tools/test-gate-race.py [path/to/gate.py]
Exit 1 if any case fails. Run against the gate before 23 Nov 2026's fix, the
race cases fail: it read the PR at one commit and its files at another, and
posted the second commit's approval on the first.

A commit is a set of changed files with their contents. The developer has
approved commit B, and only B. The rule every case checks: the gate posts
success only on B.

Base cases (Codex round 160, P2): main moves from base0 to base1 while the
PR's head stays at B. The gate must post nothing from the old snapshot, and
the next run must read main's data at base1, not the workflow's checkout.
"""

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "tools/gate.py"
REPO, N, OWNER = "owner/specs", 99, "owner"


def blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def load_gate():
    spec = importlib.util.spec_from_file_location("gate_under_test", GATE)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate


def commit(changes):
    """{path: bytes or None (removed)} -> the PR-files entries and blobs."""
    files, blobs = [], {}
    for path, data in changes.items():
        if data is None:
            files.append({"filename": path, "status": "removed", "sha": "0" * 40})
            continue
        sha = blob_sha(data)
        blobs[sha] = data
        files.append({"filename": path, "status": "added" if not (ROOT / path).exists() else "modified",
                      "sha": sha})
    return {"files": files, "blobs": blobs, "content": changes}


def code_for(gate, files, needs):
    try:
        return gate.approval_code(files, needs, "main")
    except TypeError:          # the gate before round 160 hashed no branch
        return gate.approval_code(files, needs)


def run(gate, commits, heads, approved, bases=None):
    """Run gate.main() on a PR whose head is heads[i], and base bases[i], at
    its i-th read of the PR or its file list. Returns (check runs posted,
    every base commit main's data was read at, compare bases used)."""
    state = {"reads": 0}
    posted, base_reads, compares = [], [], []
    blobs = {s: b for c in commits.values() for s, b in c["blobs"].items()}
    phrase = gate.phrase_for(code_for(gate, commits[approved]["files"], approved_needs[0]), approved_needs[0])
    comments = [{"id": 1, "body": phrase, "user": {"login": OWNER, "type": "User"}, "author_association": "OWNER",
                 "performed_via_github_app": None, "created_at": "t", "updated_at": "t",
                 "html_url": "https://example/c1"}]

    def head():
        i = state["reads"]
        state["reads"] += 1
        b = bases or ["base0"]
        return heads[min(i, len(heads) - 1)], b[min(i, len(b) - 1)]

    def api(path, token=None, method="GET", data=None, raw=False):
        if method == "POST" and path.endswith("/check-runs"):
            posted.append(data)
            return {}
        if method in ("POST", "PATCH"):
            return {}
        if path == f"/repos/{REPO}/pulls/{N}":
            h, b = head()
            return {"state": "open", "head": {"sha": h},
                    "base": {"sha": b, "ref": "main", "repo": {"owner": {"login": OWNER}}}}
        if path.startswith(f"/repos/{REPO}/compare/"):
            b, sha = path.split("/compare/")[1].split("?")[0].split("...")
            compares.append(b)
            return {"files": copy.deepcopy(commits[sha]["files"])}
        if path.startswith(f"/repos/{REPO}/git/blobs/"):
            data = blobs[path.rsplit("/", 1)[1]]
            import base64
            return {"content": base64.b64encode(data).decode(), "encoding": "base64", "size": len(data)}
        if "/contents/" in path and "?ref=" in path:
            name, sha = path.split("/contents/")[1].split("?ref=")
            if sha in MAINS:
                base_reads.append(sha)
                data = MAINS[sha].get(name)
                if data is None and not (ROOT / name).exists():
                    import urllib.error
                    raise urllib.error.HTTPError(path, 404, "Not Found", {}, None)
                return data if data is not None else (ROOT / name).read_bytes()
            data = commits[sha]["content"].get(name)
            return data if data is not None else (ROOT / name).read_bytes()
        raise AssertionError(f"unexpected call {method} {path}")

    def paged(path, token):
        if path == f"/repos/{REPO}/pulls/{N}/files":
            return copy.deepcopy(commits[head()[0]]["files"])
        if path == f"/repos/{REPO}/issues/{N}/comments":
            return comments
        raise AssertionError(f"unexpected paged {path}")

    gate.api, gate.paged = api, paged
    gate.app_token = lambda repo, permissions=None: "token"
    os.environ["REPO"] = REPO
    os.environ.pop("GITHUB_STEP_SUMMARY", None)
    argv = sys.argv
    sys.argv = ["gate.py", str(N)]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            gate.main()
    finally:
        sys.argv = argv
    return posted, base_reads, compares


approved_needs = [{}]
# main's data at each base commit: base0 is this checkout; base1 is main after
# another PR changed a car's note (MAINS["base1"] is filled in main()).
MAINS = {"base0": {}, "base1": {}}


def main():
    specs = json.loads((ROOT / "phev-specs-au.json").read_text())
    plans = json.loads((ROOT / "energy-plans-au.json").read_text())

    def dumps(obj):
        return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode()

    benign = copy.deepcopy(specs)
    benign["version"] = "999.0.0"
    benign["vehicles"][0]["notes"] = (benign["vehicles"][0].get("notes") or "") + " (sweep note)"
    battery = copy.deepcopy(specs)
    battery["version"] = "999.0.0"
    car = next(v for v in battery["vehicles"] if "batteryUsableKWh" in v)
    car["batteryUsableKWh"] = round(car["batteryUsableKWh"] * 1.5, 1)
    closing = copy.deepcopy(plans)
    closing["version"] = "99.0.0"
    closing["states"][0]["providers"][0]["plans"][0]["closing"] = True

    B = commit({"phev-specs-au.json": dumps(benign)})
    commits = {
        "B": B,
        # M changes a car figure the developer never saw.
        "M": commit({"phev-specs-au.json": dumps(battery)}),
        # M2 leaves the car list alone and edits the plans output and adds a
        # workflow: files B's list doesn't name, so the old gate never read them.
        "M2": commit({"energy-plans-au.json": dumps(closing),
                      ".github/workflows/x.yml": b"on: push\njobs: {}\n"}),
    }
    moved = copy.deepcopy(specs)
    moved["version"] = "998.0.0"
    moved["vehicles"][1]["notes"] = (moved["vehicles"][1].get("notes") or "") + " (merged on main)"
    MAINS["base1"] = {"phev-specs-au.json": dumps(moved)}
    gate = load_gate()
    cases = [
        ("no push mid-run, PR at the approved commit B", ["B"], True),
        ("no push mid-run, PR at the unapproved commit M", ["M"], False),
        ("no push mid-run, PR at M2 (plans output and a workflow)", ["M2"], False),
        ("race: PR read at M, then B before its files are read", ["M", "B"], False),
        ("race: PR read at M2, then B before its files are read", ["M2", "B"], False),
        ("race: PR read at B, then M", ["B", "M"], False),
        ("race: PR read at M, then B, then M again", ["M", "B", "M"], False),
        ("race: PR at B for two reads, then M", ["B", "B", "M"], True),
    ]
    bad = 0
    for label, heads, success_on_b_ok in cases:
        posted, _, _ = run(gate, commits, heads, "B")
        wrong = [p for p in posted if p["conclusion"] == "success" and p["head_sha"] != "B"]
        missing = success_on_b_ok and heads[:2] == ["B", "B"] and not any(
            p["conclusion"] == "success" and p["head_sha"] == "B" for p in posted)
        ok = not wrong and not missing
        bad += not ok
        what = "; ".join(f"{p['conclusion']} on {p['head_sha']}" for p in posted) or "nothing posted"
        print(f"{'PASS' if ok else 'FAIL'}  {label}: {what}")
    # The base moves, the head doesn't (Codex round 160, P2).
    base_cases = [
        ("base: main moves from base0 to base1 mid-run, head stays B", ["base0", "base1"],
         lambda posted, reads, compares: not posted),
        ("base: the next run, at base1, reads main's data at base1", ["base1"],
         lambda posted, reads, compares: any(p["conclusion"] == "success" and p["head_sha"] == "B" for p in posted)
         and compares and set(compares) == {"base1"} and reads and set(reads) == {"base1"}),
    ]
    for label, bases, good in base_cases:
        posted, reads, compares = run(gate, commits, ["B"], "B", bases)
        ok = bool(good(posted, reads, compares))
        bad += not ok
        what = "; ".join(f"{p['conclusion']} on {p['head_sha']}" for p in posted) or "nothing posted"
        print(f"{'PASS' if ok else 'FAIL'}  {label}: {what}; compared against {sorted(set(compares))}, "
              f"main's data read at {sorted(set(reads)) or ('the checkout, not a commit' if posted else 'nothing')}")
    cases += base_cases
    print(f"gate race test {'ok' if not bad else 'FAILED'} ({len(cases)} cases, {bad} failed) on {GATE}")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
