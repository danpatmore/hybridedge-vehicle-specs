#!/usr/bin/env python3
"""
settings-check.py: reads back the repository settings the data jobs depend
on, from GitHub itself, every day (23 Nov 2026, Codex round 158). Codex could
not read these from outside, and some can't be seen without the owner's
access, so the developer's gate app reads them (Administration, Actions and
Secrets read-only; it can change nothing) and the job prints them in its
public log. Anything unlike what is written here raises one issue.

Usage: python3 tools/settings-check.py [--summary FILE]
       (GATE_APP_ID and GATE_APP_KEY from the "gate" environment)

What it expects:
  - one active ruleset on the default branch: no deletion, no force push,
    every change through a pull request merged with a merge commit, and the
    check "data-gate" required from the gate app only, with the branch up to
    date; the bypass list is deploy keys only
  - exactly one deploy key, the plans job's (by fingerprint), because the
    bypass covers every deploy key: GitHub can't name one
  - environments "publish" and "gate", each usable from main only
  - no repository-level Actions secrets (a workflow on any branch could
    read those; ours live in the main-only environments)
  - Actions' own token read-only, unable to approve pull requests
"""

import base64
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("gate", ROOT / "tools/gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)

DEPLOY_KEY = ("Weekly plans job", "SHA256:4Qp4Creqed/l8Hr8V1hpsXDqSxbUV5P4bLXXrSFobs8")
ENVIRONMENTS = ("gate", "publish")
PERMISSIONS = {"administration": "read", "actions": "read", "secrets": "read", "metadata": "read"}


def fingerprint(key):
    return "SHA256:" + base64.b64encode(hashlib.sha256(base64.b64decode(key.split()[1])).digest()).decode().rstrip("=")


def check(get, app_id):
    """(lines read back, problems). `get` reads one API path."""
    lines, problems = [], []

    def read(label, path):
        try:
            return get(path)
        except Exception as e:
            problems.append(f"{label}: could not be read ({e})")
            return None

    sets = read("rulesets", "/rulesets?includes_parents=true") or []
    active = [r for r in sets if r.get("enforcement") == "active" and r.get("target") == "branch"]
    lines.append(f"Active branch rulesets: {[r['name'] for r in active]}")
    if len(active) != 1:
        problems.append(f"expected one active branch ruleset, found {len(active)}")
    for r in active:
        d = read(f"ruleset {r['name']}", f"/rulesets/{r['id']}") or {}
        rules = {x["type"]: x.get("parameters") or {} for x in d.get("rules") or []}
        lines.append(f"  applies to: {d.get('conditions')}")
        lines.append(f"  rules: {sorted(rules)}")
        if d.get("conditions", {}).get("ref_name", {}).get("include") != ["~DEFAULT_BRANCH"]:
            problems.append("the ruleset does not cover the default branch alone")
        for t in ("deletion", "non_fast_forward", "pull_request", "required_status_checks"):
            if t not in rules:
                problems.append(f"the ruleset lacks '{t}'")
        methods = rules.get("pull_request", {}).get("allowed_merge_methods")
        lines.append(f"  merge methods: {methods}")
        if methods != ["merge"]:
            problems.append(f"merge methods are {methods}, expected merge commits only")
        rsc = rules.get("required_status_checks", {})
        checks = rsc.get("required_status_checks")
        lines.append(f"  required checks: {checks}; up to date first: {rsc.get('strict_required_status_checks_policy')}")
        if checks != [{"context": "data-gate", "integration_id": app_id}]:
            problems.append(f"required checks are {checks}, expected data-gate from the gate app ({app_id}) only")
        if rsc.get("strict_required_status_checks_policy") is not True:
            problems.append("branches need not be up to date before merging")
        # GitHub shows the bypass list only to someone who can edit the
        # ruleset, and this app only reads (first run, 23 Nov 2026: None). It
        # is checked when GitHub does show it; otherwise the readback says so.
        bypass = d.get("bypass_actors")
        if bypass is None:
            lines.append("  bypass list: not shown to a read-only app (the developer's screen: deploy keys only)")
        else:
            lines.append(f"  bypass list: {bypass}")
            if [(b.get("actor_type"), b.get("bypass_mode")) for b in bypass] != [("DeployKey", "always")]:
                problems.append(f"the bypass list is {bypass}, expected deploy keys only")

    keys = read("deploy keys", "/keys") or []
    seen = [(k.get("title"), fingerprint(k["key"]), k.get("read_only")) for k in keys]
    lines.append(f"Deploy keys: {seen}")
    if [(t, f) for t, f, _ in seen] != [DEPLOY_KEY]:
        problems.append(f"expected only the deploy key {DEPLOY_KEY}, found {[(t, f) for t, f, _ in seen]}")

    envs = read("environments", "/environments") or {}
    names = sorted(e["name"] for e in envs.get("environments", []))
    lines.append(f"Environments: {names}")
    for name in ENVIRONMENTS:
        e = next((x for x in envs.get("environments", []) if x["name"] == name), None)
        if not e:
            problems.append(f"environment '{name}' is missing")
            continue
        pol = e.get("deployment_branch_policy")
        branches = read(f"{name} branches", f"/environments/{name}/deployment-branch-policies") or {}
        allowed = sorted((b.get("type"), b.get("name")) for b in branches.get("branch_policies", []))
        lines.append(f"  {name}: {pol}, {allowed}")
        if pol != {"protected_branches": False, "custom_branch_policies": True} or allowed != [("branch", "main")]:
            problems.append(f"environment '{name}' is not limited to main")

    secrets = read("repository secrets", "/actions/secrets") or {}
    lines.append(f"Repository-level Actions secrets: {[x['name'] for x in secrets.get('secrets', [])]}")
    if secrets.get("total_count"):
        problems.append("there are repository-level Actions secrets, which a workflow on any branch could read")

    wf = read("Actions token permissions", "/actions/permissions/workflow") or {}
    lines.append(f"Actions token: {wf}")
    if wf.get("default_workflow_permissions") != "read" or wf.get("can_approve_pull_request_reviews") is not False:
        problems.append("Actions' own token is not read-only, or can approve pull requests")
    return lines, problems


def main():
    repo = os.environ.get("REPO", "danpatmore/hybridedge-vehicle-specs")
    app_id = int(os.environ["GATE_APP_ID"])
    token = gate.app_token(repo, PERMISSIONS)
    lines, problems = check(lambda path: gate.api(f"/repos/{repo}{path}", token), app_id)
    text = "**Read back from GitHub:**\n\n```\n" + "\n".join(lines) + "\n```\n\n" + (
        "**Not as expected:**\n" + "\n".join(f"- {p}" for p in problems) if problems else "All as expected.") + "\n"
    print(text)
    if "--summary" in sys.argv:
        Path(sys.argv[sys.argv.index("--summary") + 1]).write_text(text)
    raise SystemExit(1 if problems else 0)


def selftest():
    key = "ssh-ed25519 " + base64.b64encode(b"k" * 51).decode()
    good = {
        "/rulesets?includes_parents=true": [{"id": 1, "name": "Protect main", "enforcement": "active", "target": "branch"}],
        "/rulesets/1": {"conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
                        "rules": [{"type": "deletion"}, {"type": "non_fast_forward"},
                                  {"type": "pull_request", "parameters": {"allowed_merge_methods": ["merge"]}},
                                  {"type": "required_status_checks", "parameters": {
                                      "strict_required_status_checks_policy": True,
                                      "required_status_checks": [{"context": "data-gate", "integration_id": 7}]}}],
                        "bypass_actors": [{"actor_id": None, "actor_type": "DeployKey", "bypass_mode": "always"}]},
        "/keys": [{"title": "Weekly plans job", "key": key, "read_only": False}],
        "/environments": {"environments": [{"name": n, "deployment_branch_policy": {
            "protected_branches": False, "custom_branch_policies": True}} for n in ENVIRONMENTS]},
        "/environments/gate/deployment-branch-policies": {"branch_policies": [{"name": "main", "type": "branch"}]},
        "/environments/publish/deployment-branch-policies": {"branch_policies": [{"name": "main", "type": "branch"}]},
        "/actions/secrets": {"total_count": 0, "secrets": []},
        "/actions/permissions/workflow": {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False},
    }
    global DEPLOY_KEY
    DEPLOY_KEY = ("Weekly plans job", fingerprint(key))
    assert check(good.get, 7)[1] == [], check(good.get, 7)[1]
    def broken(edit):
        d = json.loads(json.dumps(good))
        edit(d)
        def get(path):
            if path not in d:
                raise KeyError(path)
            return d[path]
        return check(get, 7)[1]
    assert broken(lambda d: d["/rulesets/1"]["rules"][3]["parameters"]["required_status_checks"][0].update(integration_id=15368))
    assert broken(lambda d: d["/rulesets/1"]["rules"][3]["parameters"].update(strict_required_status_checks_policy=False))
    assert broken(lambda d: d["/rulesets/1"]["bypass_actors"].append({"actor_type": "RepositoryRole", "bypass_mode": "always"}))
    assert broken(lambda d: d["/rulesets/1"]["rules"][2]["parameters"].update(allowed_merge_methods=["merge", "rebase"]))
    assert broken(lambda d: d["/keys"].append({"title": "another", "key": key, "read_only": True}))
    assert broken(lambda d: d["/environments/gate/deployment-branch-policies"]["branch_policies"].append({"name": "*", "type": "branch"}))
    assert broken(lambda d: d.update({"/actions/secrets": {"total_count": 1, "secrets": [{"name": "X"}]}}))
    assert broken(lambda d: d["/actions/permissions/workflow"].update(default_workflow_permissions="write"))
    assert broken(lambda d: d.pop("/keys")), "an unreadable setting passed"
    assert not broken(lambda d: d["/rulesets/1"].update(bypass_actors=None)), "a hidden bypass list failed"
    print("settings-check selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
