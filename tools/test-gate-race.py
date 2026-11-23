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


def run(gate, commits, heads, approved):
    """Run gate.main() on a PR whose head is heads[i] at its i-th read of the
    PR or its file list. Returns the check runs posted."""
    state = {"reads": 0}
    posted = []
    blobs = {s: b for c in commits.values() for s, b in c["blobs"].items()}
    phrase = gate.phrase_for(gate.approval_code(commits[approved]["files"], approved_needs[0]), approved_needs[0])
    comments = [{"id": 1, "body": phrase, "user": {"login": OWNER, "type": "User"}, "author_association": "OWNER",
                 "performed_via_github_app": None, "created_at": "t", "updated_at": "t",
                 "html_url": "https://example/c1"}]

    def head():
        h = heads[min(state["reads"], len(heads) - 1)]
        state["reads"] += 1
        return h

    def api(path, token=None, method="GET", data=None, raw=False):
        if method == "POST" and path.endswith("/check-runs"):
            posted.append(data)
            return {}
        if method in ("POST", "PATCH"):
            return {}
        if path == f"/repos/{REPO}/pulls/{N}":
            return {"state": "open", "head": {"sha": head()}, "base": {"sha": "base0", "repo": {"owner": {"login": OWNER}}}}
        if path.startswith(f"/repos/{REPO}/compare/base0..."):
            sha = path.split("...")[1].split("?")[0]
            return {"files": copy.deepcopy(commits[sha]["files"])}
        if path.startswith(f"/repos/{REPO}/git/blobs/"):
            data = blobs[path.rsplit("/", 1)[1]]
            import base64
            return {"content": base64.b64encode(data).decode(), "encoding": "base64", "size": len(data)}
        if "/contents/" in path and "?ref=" in path:
            name, sha = path.split("/contents/")[1].split("?ref=")
            data = commits[sha]["content"].get(name)
            return data if data is not None else (ROOT / name).read_bytes()
        raise AssertionError(f"unexpected call {method} {path}")

    def paged(path, token):
        if path == f"/repos/{REPO}/pulls/{N}/files":
            return copy.deepcopy(commits[head()]["files"])
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
    return posted


approved_needs = [{}]


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
        posted = run(gate, commits, heads, "B")
        wrong = [p for p in posted if p["conclusion"] == "success" and p["head_sha"] != "B"]
        missing = success_on_b_ok and heads[:2] == ["B", "B"] and not any(
            p["conclusion"] == "success" and p["head_sha"] == "B" for p in posted)
        ok = not wrong and not missing
        bad += not ok
        what = "; ".join(f"{p['conclusion']} on {p['head_sha']}" for p in posted) or "nothing posted"
        print(f"{'PASS' if ok else 'FAIL'}  {label}: {what}")
    print(f"gate race test {'ok' if not bad else 'FAILED'} ({len(cases)} cases, {bad} failed) on {GATE}")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
