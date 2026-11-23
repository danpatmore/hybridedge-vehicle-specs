#!/usr/bin/env python3
"""
gate.py: the gate on every pull request (23 Nov 2026, Codex round 158).

Usage: python3 tools/gate.py PR_NUMBER [--dry-run]
       python3 tools/gate.py --selftest
Run by .github/workflows/pr-check.yml (a PR opened or pushed) and
gate-approval.yml (a comment), always from main's checkout, never the PR's.

What it decides, and posts as the check "data-gate":
  1. The PR's data, copied out as text, against main's rules
     (tools/check-pr.py): a problem means it can't merge, whoever approves.
  2. The developer's approval. Nothing merges without a comment from the
     repository owner that is exactly the phrase the gate gives, e.g.
     "approve 3f9a1c27d0b4e851 with tester-log keys". It counts only when:
       - its author is the owner, as a person (not a bot);
       - GitHub says no app made it (performed_via_github_app is empty).
         The Claude app acts as the developer, so a routine's comment has
         the developer's name, but GitHub marks it as made through the app;
       - it was never edited (an app could edit an old comment of the
         developer's into a new approval);
       - its code matches this PR's changes now. The code is a hash of every
         changed path, its status and its file contents (blob), and of what
         needs the developer's word (tester-log keys, showCarsWithBlanks,
         hand-kept plans, workflows, code), so any new change needs a new
         approval, but bringing the branch up to date with main does not
         unless it changes the PR's own files.
One commit per decision (Codex round 159, P1): the gate reads the PR, lists
its changes with GitHub's compare of the PR's base and head commits (fixed
ids, so the list belongs to that head and no other), reads the PR again and
posts nothing if the head moved (the run for the new head decides). Every
changed data file is fetched by its blob id from that list and checked
against it, so what is validated, what the approval code hashes and the
commit the check is posted on are the same commit.
Who posts it: the "data-gate" check comes from the developer's own GitHub App
(GATE_APP_ID, GATE_APP_KEY in the main-only "gate" environment), and main's
ruleset requires the check from that app. Any workflow can post a check
called data-gate as GitHub Actions; only this job holds the app's key
(Codex round 158, P1).
"""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"
CHECK = "data-gate"
MARKER = "<!-- data-gate -->"
PLAN_INPUTS = ("inputs/plans-hand-kept.json", "inputs/ato-home-charging-rates.json", "checks/confirm-delisted.json")


def load(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / f"tools/{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


check_pr = load("check-pr")


def api(path, token=None, method="GET", data=None, raw=False):
    req = urllib.request.Request(path if path.startswith("http") else API + path, method=method,
                                 data=json.dumps(data).encode() if data is not None else None)
    req.add_header("Accept", "application/vnd.github.raw" if raw else "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
                return body if raw else (json.loads(body) if body else None)
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(3 * (attempt + 1))


def paged(path, token):
    out, page = [], 1
    while True:
        sep = "&" if "?" in path else "?"
        batch = api(f"{path}{sep}per_page=100&page={page}", token)
        out += batch
        if len(batch) < 100:
            return out
        page += 1


def b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


# GitHub needs pull request write, not issues write, for a comment on a pull
# request (a 403 on PR #9, 23 Nov 2026).
GATE_PERMISSIONS = {"checks": "write", "issues": "write", "contents": "read", "pull_requests": "write"}


def app_token(repo, permissions=GATE_PERMISSIONS):
    """An installation token for the developer's gate app, from its key,
    with only `permissions`."""
    app_id, key = os.environ["GATE_APP_ID"], os.environ["GATE_APP_KEY"]
    now = int(time.time())
    signing = (b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()) + "."
               + b64url(json.dumps({"iat": now - 60, "exp": now + 540, "iss": app_id}).encode()))
    fd, keyfile = tempfile.mkstemp()
    try:
        os.write(fd, key.encode())
        os.close(fd)
        sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", keyfile], input=signing.encode(),
                             capture_output=True, check=True).stdout
    finally:
        os.unlink(keyfile)
    jwt = signing + "." + b64url(sig)
    inst = api(f"/repos/{repo}/installation", jwt)
    tok = api(f"/app/installations/{inst['id']}/access_tokens", jwt, "POST",
              {"repositories": [repo.split("/")[1]], "permissions": permissions})
    return tok["token"]


def approval_code(files, categories):
    """16 hex digits: every changed path, its status and contents, and what
    needs the developer's word. 64 bits, so no routine can search out a
    different change with the same code."""
    rows = sorted([f["filename"], f.get("status"), f.get("previous_filename"), f.get("sha")] for f in files)
    return hashlib.sha256(json.dumps([rows, sorted(categories)]).encode()).hexdigest()[:16]


def phrase_for(code, categories):
    return f"approve {code}" + (f" with {' and '.join(sorted(categories))}" if categories else "")


def norm(text):
    return " ".join(text.replace("`", "").lower().split()).rstrip(".!")


def approval(comments, owner, phrase):
    """The developer's own, unedited comment saying exactly `phrase`, or None."""
    for c in comments:
        if (c["user"]["login"] == owner and c["user"].get("type") == "User"
                and c.get("author_association") == "OWNER"
                and c.get("performed_via_github_app") is None
                and c["created_at"] == c["updated_at"]
                and norm(c["body"]) == norm(phrase)):
            return c
    return None


MAX_FILES = 300   # GitHub's compare lists at most this many changed files


def blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def snapshot(repo, number, token):
    """(pr, files) for one head commit, or None if the PR's head moved while
    its changes were listed (Codex round 159, P1)."""
    pr = api(f"/repos/{repo}/pulls/{number}", token)
    head, base = pr["head"]["sha"], pr["base"]["sha"]
    files = api(f"/repos/{repo}/compare/{base}...{head}?per_page=1", token).get("files") or []
    if api(f"/repos/{repo}/pulls/{number}", token)["head"]["sha"] != head:
        return None
    return pr, files


def gather(repo, pr, files, token, base_dir, head_dir):
    """(problems, checked, needs, cars changed) for the PR's snapshot, its data fetched by
    blob id next to main's."""
    problems, needs = check_pr.check_paths(files)
    if len(files) >= MAX_FILES:
        problems.append(f"{len(files)} or more files changed, more than the gate can list; split the PR")
    changed = {f["filename"]: f for f in files}
    for name in check_pr.DATA_FILES:
        for d in (base_dir, head_dir):
            (d / name).parent.mkdir(parents=True, exist_ok=True)
        if (ROOT / name).exists():
            shutil.copy(ROOT / name, base_dir / name)
        f = changed.get(name)
        if f and f["status"] in ("added", "modified", "changed"):
            blob = api(f"/repos/{repo}/git/blobs/{f['sha']}", token)
            data = base64.b64decode(blob["content"])
            if blob_sha(data) != f["sha"]:
                problems.append(f"{name}: GitHub's copy doesn't match its blob id")
            (head_dir / name).write_bytes(data)
        elif (ROOT / name).exists() and not f:
            shutil.copy(ROOT / name, head_dir / name)
    info = []
    p, checked = check_pr.check_dirs(base_dir, head_dir, needs, info)
    return problems + p, checked, needs, info


def decide(problems, needs, files, comments, owner):
    """(conclusion, title, phrase, approver comment or None)."""
    phrase = phrase_for(approval_code(files, needs), needs)
    ok = approval(comments, owner, phrase)
    if problems:
        return "failure", f"Can't merge: {len(problems)} problem(s)", phrase, ok
    if ok:
        return "success", "Approved by the developer", phrase, ok
    return "failure", "Waiting for the developer's approval", phrase, None


def comment_body(title, summary, phrase, approver, plan_inputs):
    lines = [MARKER, f"**Data gate: {title}**", "", summary.strip(), ""]
    if approver:
        lines += [f"Approved in {approver['html_url']}. Merge when ready."]
    else:
        lines += ["To approve, reply with exactly this (copy it):", "", f"`{phrase}`", "",
                  "Only a comment you type yourself counts. One posted through the Claude app (a routine) "
                  "or edited afterwards doesn't. The code covers these exact changes, so a new push needs a "
                  "new approval."]
    if plan_inputs:
        lines += ["", "This changes what the plans job reads. After merging, it publishes on Monday, or "
                      "now: Actions, Electricity plans (weekly), Run workflow."]
    return "\n".join(lines) + "\n"


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    number = int([a for a in args if not a.startswith("--")][0])
    repo = os.environ.get("REPO", "danpatmore/hybridedge-vehicle-specs")
    token = os.environ.get("GH_TOKEN") if dry else app_token(repo)
    tmp = Path(tempfile.mkdtemp())
    base_dir, head_dir = tmp / "base", tmp / "head"
    snap = snapshot(repo, number, token)
    if snap is None:
        print(f"PR {number} moved to a new commit while this ran; the run for that commit decides. Nothing posted.")
        return
    pr, files = snap
    if pr["state"] != "open" and not dry:
        print(f"PR {number} is {pr['state']}; nothing to do")
        return
    problems, checked, needs, info = gather(repo, pr, files, token, base_dir, head_dir)
    owner = pr["base"]["repo"]["owner"]["login"]
    comments = paged(f"/repos/{repo}/issues/{number}/comments", token)
    conclusion, title, phrase, approver = decide(problems, needs, files, comments, owner)
    summary = check_pr.summary_text(problems, checked, needs, info)
    plan_inputs = any(f["filename"] in PLAN_INPUTS for f in files)
    body = comment_body(title, summary, phrase, approver, plan_inputs)
    print(body)
    print(f"conclusion: {conclusion}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(body)
    if dry:
        return
    api(f"/repos/{repo}/check-runs", token, "POST",
        {"name": CHECK, "head_sha": pr["head"]["sha"], "status": "completed", "conclusion": conclusion,
         "output": {"title": title, "summary": body[:60000]}})
    mine = [c for c in comments if MARKER in c["body"] and c["user"].get("type") == "Bot"]
    if mine and mine[-1]["body"] != body:
        api(f"/repos/{repo}/issues/comments/{mine[-1]['id']}", token, "PATCH", {"body": body})
    elif not mine:
        api(f"/repos/{repo}/issues/{number}/comments", token, "POST", {"body": body})


def selftest():
    owner = "dev"
    files = [{"filename": "phev-specs-au.json", "status": "modified", "sha": "a" * 40}]
    code = approval_code(files, {})
    phrase = phrase_for(code, {})
    def c(body, login=owner, kind="User", assoc="OWNER", app=None, edited=False):
        return {"body": body, "user": {"login": login, "type": kind}, "author_association": assoc,
                "performed_via_github_app": app, "created_at": "t1", "updated_at": "t2" if edited else "t1",
                "html_url": "u"}
    assert approval([c(phrase)], owner, phrase), "the developer's own approval was refused"
    assert approval([c(f"`{phrase.upper()}`.")], owner, phrase), "backticks, capitals or a full stop broke it"
    assert not approval([c(phrase, app={"slug": "claude"})], owner, phrase), "an approval made through an app counted"
    assert not approval([c(phrase, edited=True)], owner, phrase), "an edited comment counted"
    assert not approval([c(phrase, login="someone", assoc="CONTRIBUTOR")], owner, phrase), "another person counted"
    assert not approval([c(phrase, login=owner, kind="Bot")], owner, phrase), "a bot counted"
    assert not approval([c("approve")], owner, phrase), "a bare 'approve' counted"
    assert not approval([c(phrase + " please")], owner, phrase), "a different phrase counted"
    other = [dict(files[0], sha="b" * 40)]
    assert approval_code(other, {}) != code, "new file contents kept the old code"
    assert approval_code(files, {"tester-log keys": []}) != code, "a new category kept the old code"
    assert approval_code(files + [{"filename": "sweeps/x.md", "status": "added", "sha": "c" * 40}], {}) != code, \
        "an added file kept the old code"
    assert approval_code(list(reversed(files + other)), {}) == approval_code(files + other, {}), "file order changed it"
    with_cat = phrase_for(code, {"tester-log keys": [], "code": []})
    assert with_cat == f"approve {code} with code and tester-log keys", with_cat
    concl, _, ph, _ = decide([], {"tester-log keys": ["x"]}, files, [c(phrase)], owner)
    assert concl == "failure", "an approval without the category it needs counted"
    concl, _, _, _ = decide([], {"tester-log keys": ["x"]}, files, [c(ph)], owner)
    assert concl == "success", "the right phrase with its category was refused"
    concl, title, _, _ = decide(["car list: car ids removed"], {}, files, [c(phrase)], owner)
    assert concl == "failure" and "Can't merge" in title, "an approval let a problem through"
    concl, title, _, _ = decide([], {}, files, [], owner)
    assert concl == "failure" and "Waiting" in title, "no approval passed"
    print("gate selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
