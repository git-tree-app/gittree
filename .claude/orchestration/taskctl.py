#!/usr/bin/env python3
"""Durable coordinator-owned workflow ledger; not a scheduler or security boundary.

Workers return reports to the coordinator and never write this ledger. A review
records evidence supplied by a human/agent; it cannot prove tests were executed.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

AGENTS = (
    "gt-scout", "gt-task-builder", "gt-architect", "gt-implementer", "gt-desktop",
    "gt-investigator", "gt-bug-fixer", "gt-test-manager", "gt-reviewer",
    "gt-risk-reviewer", "gt-doc-writer", "gt-script-writer",
)
REVIEWERS = ("gt-reviewer", "gt-risk-reviewer")
OPUS_AGENTS = ("gt-architect", "gt-desktop")
ACTIVE = ("running", "review")
MAX_ACTIVE_TASKS = 2
MAX_CLAIMS = 3
MAX_REVIEW_CHANGES = 2
# Opus is reserved for high-risk work; a routine task reviewed by Opus is wasted cost.
MODEL_OF = {"gt-scout": "haiku", "gt-architect": "opus", "gt-desktop": "opus", "gt-risk-reviewer": "opus"}


class WorkflowError(Exception):
    """A rejected operation; the previous ledger remains intact."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise WorkflowError(message)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def nonempty(value: str) -> str:
    require(bool(value.strip()), "Text/evidence must not be empty")
    return value.strip()


def identifier(value: str) -> str:
    require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value)),
            "Identifiers must be 1-80 letters, digits, underscores or hyphens")
    return value


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    require(result.returncode == 0, f"Git failed in {repo}: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def repo_root(value: str) -> str:
    return str(Path(git(Path(value).resolve(), "rev-parse", "--show-toplevel")
                    .decode().strip()).resolve())


def excluded(name: bytes) -> bool:
    return b".claude/task-runs/" in b"/" + name


SNAPSHOT_FORMAT = "v2"


def head_of(repo: str) -> str:
    result = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "HEAD"], capture_output=True)
    return result.stdout.decode().strip() if result.returncode == 0 else "UNBORN"


def tree_matches_head(repo: str) -> bool:
    """True when index and working tree equal HEAD for every tracked path."""
    for args in (("diff", "--cached", "--quiet", "HEAD"), ("diff", "--quiet", "HEAD")):
        result = subprocess.run(["git", "-C", repo, *args], capture_output=True)
        if result.returncode == 1:
            return False
        require(result.returncode == 0, f"Git failed in {repo}: {result.stderr.decode(errors='replace').strip()}")
    return True


def listed(repo: str, *selector: str) -> list[str]:
    names = git(Path(repo), "ls-files", *selector, "--exclude-standard", "-z").split(b"\0")
    return sorted(os.fsdecode(name) for name in names if name and not excluded(name))


def untracked(repo: str) -> list[str]:
    return listed(repo, "--others")


def tracked_present(repo: str) -> list[str]:
    """Tracked paths that exist on disk; a deleted-but-still-indexed file counts as gone."""
    root = Path(repo)
    return [name for name in listed(repo, "--cached") if os.path.lexists(root / name)]


def names_digest(names: list[str]) -> str:
    return hashlib.sha256("\0".join(sorted(names)).encode()).hexdigest()


def snapshot(repo: str, baseline_untracked: list[str] | None = None) -> str:
    """Record `v2:<content>:<head>:<tracked-set digest>:<files the task created>`.

    A review binds to content. `current()` accepts the record when the content digest is
    unchanged and either HEAD and the tracked set are unchanged, or the committed tree now
    equals that content: index and working tree clean against HEAD, every file the task
    created tracked, and no other tracked-set change. Committing an accepted diff keeps
    its approval; staged-but-unreviewed blobs, partial staging, `commit -am` dropping new
    files, untracking a file or resets invalidate it. Untracked files that predate the
    claim are the owner's and may stay untracked. A reviewed deletion made with plain
    `rm` is absent content; committing it keeps the record current.
    """
    # With a task boundary, the task's new files MUST be committed with it. Without one
    # (dependency/integration records) any untracked file MAY be committed later: consumers
    # depend on content, which the digest already covers.
    bound = baseline_untracked is not None
    created = sorted(set(untracked(repo)) - set(baseline_untracked or []))
    tracked = names_digest(tracked_present(repo))
    record = json.dumps({"created": created, "bound": bound}, separators=(",", ":"))
    return f"{SNAPSHOT_FORMAT}:{content_digest(repo)}:{head_of(repo)}:{tracked}:{record}"


def current(repo: str, recorded: str | None) -> bool:
    """Does the checkout still hold the recorded reviewed content?"""
    if not recorded or not recorded.startswith(SNAPSHOT_FORMAT + ":"):
        return False  # legacy or missing record: never silently accepted
    _, content, head, tracked, created = recorded.split(":", 4)
    if content != content_digest(repo):
        return False
    now = tracked_present(repo)
    if head == head_of(repo):
        return names_digest(now) == tracked
    record = json.loads(created)
    created_files = set(record["created"])
    committed = set(now) & created_files
    if record["bound"] and created_files & set(untracked(repo)):
        return False  # a file the task created was left out of the commit
    return tree_matches_head(repo) and names_digest(sorted(set(now) - committed)) == tracked


def content_digest(repo: str) -> str:
    root = Path(repo)
    digest = hashlib.sha256()

    def feed(data: bytes) -> None:
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)

    for entry in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if entry and not excluded(entry.split(b"\t", 1)[1]):
            # Tracked set, mode and merge stage matter; the staged blob id does not, so
            # `git add` of already-reviewed working-tree content leaves the digest unchanged.
            meta, name = entry.split(b"\t", 1)
            mode, blob, stage = meta.split(b" ")
            # Gitlinks keep their commit pointer (repointing a submodule is a content change) and
            # unresolved merge stages are content; plain index membership is tracked separately.
            if mode == b"160000" or stage != b"0":
                feed(b"INDEX " + mode + b" " + stage + b" " + blob + b" " + name)
    names = set(git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0"))
    for name in sorted(names):
        if not name or excluded(name):
            continue
        path = root / os.fsdecode(name)
        if not os.path.lexists(path):
            # A tracked path deleted on disk is absent content: committing that deletion
            # (`git rm`, `commit -a`) yields the same digest, while deleting after review
            # still changes it because the content line disappears.
            continue
        feed(name)
        if path.is_symlink():
            feed(b"LINK" + os.fsencode(os.readlink(path)))
        elif path.is_file():
            feed(str(path.stat().st_mode & 0o777).encode())
            feed(path.read_bytes())
        elif path.is_dir():
            # Gitlinks/submodules need their nested working state, not just their commit.
            # Uninitialized submodules have no .git; recursing would find the parent.
            feed(content_digest(str(path)).encode() if (path / ".git").exists() else b"UNINITIALIZED_DIRECTORY")
        else:
            feed(b"SPECIAL")
    return digest.hexdigest()


def save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(state, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextlib.contextmanager
def locked(root: Path):
    base = root.resolve() / ".claude" / "task-runs"
    base.mkdir(parents=True, exist_ok=True)
    with (base / ".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield base


def event(state: dict, action: str, **details) -> None:
    state["updated_at"] = now()
    state["history"].append({"at": state["updated_at"], "action": action, **details})


def reservation_path(repo: str) -> Path:
    directory = Path(git(Path(repo), "rev-parse", "--absolute-git-dir").decode().strip())
    return directory / "gittree-taskctl-reservation.json"


def read_reservation(repo: str) -> dict | None:
    """Current checkout owner (any run, any coordinator root), None, or an error record."""
    try:
        path = reservation_path(repo)
    except WorkflowError as error:
        return {"error": str(error)}
    return json.loads(path.read_text()) if path.exists() else None


def reservation(repo: str, action: str, identity: dict, allow_other: bool = False) -> bool:
    """Persistent checkout ownership survives process crashes and coordinator roots."""
    path = reservation_path(repo)
    directory = path.parent
    with (directory / "gittree-taskctl.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        current = json.loads(path.read_text()) if path.exists() else None
        matches = current is not None and all(current.get(key) == value for key, value in identity.items())
        if action == "acquire":
            require(current is None,
                    f"Checkout is reserved by {current}; explicitly resume its task with --workers-stopped after stopping workers")
            save(path, {**identity, "reserved_at": now()})
        elif action == "verify":
            require(matches, f"Checkout reservation does not match this task: {current}")
        elif action == "release":
            require(current is None or matches or allow_other, f"Checkout is reserved by another task: {current}")
            if matches:
                path.unlink()
                descriptor = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        return matches


def dependency_repos(state: dict, task: dict) -> set[str]:
    """Include transitive inputs; writes in the task's own checkout are expected."""
    pending = list(task["depends"])
    visited = set()
    repos = set()
    while pending:
        key = pending.pop()
        if key in visited:
            continue
        visited.add(key)
        dependency = state["tasks"][key]
        repos.add(dependency["repo"])
        pending.extend(dependency["depends"])
    return repos - {task["repo"]}


def integration_coverage_current(state: dict, gate: dict) -> bool:
    """A passed gate supersedes exactly the reviewed task revisions it validated."""
    covered = gate.get("integration_approvals")
    return bool(gate.get("integration") and gate["status"] == "done" and covered is not None
                and all(key in state["tasks"] and state["tasks"][key]["status"] == "done"
                        and state["tasks"][key]["approval"] == approval
                        for key, approval in covered.items()))


def integrated(state: dict, task: dict) -> bool:
    return any(integration_coverage_current(state, gate)
               and any(state["tasks"][key] is task for key in gate["integration_approvals"])
               for gate in state["tasks"].values())


def stale_dependencies(state: dict, task: dict) -> set[str]:
    """Only an explicit integration review can supersede old consumer evidence."""
    if task.get("integration") or integrated(state, task):
        return set()
    inputs = task.get("dependency_snapshots") or {}
    return {repo for repo in dependency_repos(state, task)
            if not current(repo, inputs.get(repo))}


def require_current_dependencies(state: dict, task: dict) -> None:
    if task.get("integration"):
        inputs = task.get("integration_snapshots") or {}
        stale = {repo for repo in state["repos"] if not current(repo, inputs.get(repo))}
        require(not stale, f"Integration checkout changed: {sorted(stale)}. Integration is read-only; block and reconcile before rerunning")
        expected = task.get("integration_approvals") or {}
        actual = {key: value["approval"] for key, value in state["tasks"].items() if value is not task}
        require(expected == actual and all(value["status"] == "done" for value in state["tasks"].values() if value is not task),
                "Integration task scope or approvals changed; create a fresh final gate")
        return
    stale = stale_dependencies(state, task)
    require(not stale,
            f"Dependency checkout changed: {sorted(stale)}. Reconcile inputs; invalidate accepted work or block/resume active work, then submit fresh evidence")


def completion(state: dict) -> tuple[bool, list[str]]:
    """All work must pass, and a final integration gate must bind the whole run."""
    tasks = list(state["tasks"].values())
    if not tasks or any(task["status"] != "done" for task in tasks):
        return False, []
    gates = [task for task in tasks if task.get("integration")]
    if gates:
        gate = max(gates, key=lambda task: task["approval"]["at"])
        covered = gate.get("integration_approvals") or {}
        scope = {key for key, task in state["tasks"].items() if task is not gate}
        stale = {repo for repo in state["repos"] if not current(repo, (gate.get("integration_snapshots") or {}).get(repo))}
        valid = set(covered) == scope and integration_coverage_current(state, gate)
        return valid and not stale, sorted(stale)
    latest = {}
    for task in tasks:
        previous = latest.get(task["repo"])
        if previous is None or task["approval"]["at"] > previous["at"]:
            latest[task["repo"]] = task["approval"]
    stale = {repo for repo, approval in latest.items() if not current(repo, approval["snapshot"])}
    for task in tasks:
        stale.update(stale_dependencies(state, task))
    return not stale, sorted(stale)


def require_current_approvals(state: dict, repos: set[str], check_dependencies: bool = True) -> None:
    """Prevent a new task from silently absorbing changes to accepted work."""
    for repo in repos:
        if check_dependencies:
            for task in state["tasks"].values():
                if task["repo"] == repo and task["status"] == "done" and not task.get("integration"):
                    require_current_dependencies(state, task)
        approvals = [task["approval"] for task in state["tasks"].values()
                     if task["repo"] == repo and task["status"] == "done" and task["approval"]]
        for gate in state["tasks"].values():
            if integration_coverage_current(state, gate) and repo in gate.get("integration_snapshots", {}):
                approvals.append({"at": gate["approval"]["at"], "snapshot": gate["integration_snapshots"][repo]})
        if approvals:
            latest = max(approvals, key=lambda approval: approval["at"])
            require(current(repo, latest["snapshot"]),
                    f"Accepted checkout changed: {repo}. Reconcile the diff and use invalidate before new work"
                    + ("" if str(latest["snapshot"]).startswith(SNAPSHOT_FORMAT + ":") else
                       " (legacy snapshot format: verify the accepted content, then `rebind`)"))


def reserved_repos(state: dict, task: dict) -> list[str]:
    return sorted(state["repos"] if task.get("integration") else [task["repo"]])


def reservations(repos: list[str], action: str, identity: dict, allow_other: bool = False) -> bool:
    """Acquire in stable order; roll back only this attempt's new reservations."""
    acquired = []
    matches = []
    try:
        for repo in repos:
            matches.append(reservation(repo, action, identity, allow_other))
            if action == "acquire":
                acquired.append(repo)
    except (WorkflowError, OSError, ValueError):
        for repo in reversed(acquired):
            reservation(repo, "release", identity)
        raise
    return any(matches)


def record_usage(task: dict, stage: str, actor: str, agent: str, args: argparse.Namespace) -> None:
    """Optional per-dispatch cost evidence; the coordinator copies it from the native agent result."""
    tokens = getattr(args, "tokens", None)
    model = getattr(args, "model", None)
    if tokens is None and not model:
        return
    require(tokens is None or tokens >= 0, "Tokens must be a non-negative integer")
    task.setdefault("usage", []).append({"stage": stage, "actor": actor, "agent": agent,
                                         "tokens": tokens, "model": model, "at": now()})


def usage_summary(state: dict) -> dict:
    """Totals by agent and model family so Opus share is visible in `status`."""
    by_agent: dict[str, int] = {}
    by_model: dict[str, int] = {}
    dispatches = 0
    for task in state["tasks"].values():
        for item in task.get("usage") or []:
            dispatches += 1
            tokens = item.get("tokens") or 0
            family = (item.get("model") or MODEL_OF.get(item["agent"], "sonnet")).lower()
            family = next((name for name in ("opus", "sonnet", "haiku") if name in family), family)
            by_agent[item["agent"]] = by_agent.get(item["agent"], 0) + tokens
            by_model[family] = by_model.get(family, 0) + tokens
    total = sum(by_model.values())
    return {"dispatches": dispatches, "total_tokens": total, "by_model": by_model, "by_agent": by_agent,
            "opus_share": round(by_model.get("opus", 0) / total, 3) if total else None}


def gate_baseline(tasks: dict, gate: dict, repo: str) -> list[str]:
    baselines = [set(task["baseline_untracked"]) for task in tasks.values()
                 if task is not gate and task["repo"] == repo and task.get("baseline_untracked") is not None]
    return sorted(set.intersection(*baselines)) if baselines else untracked(repo)


def validate_graph(tasks: dict) -> None:
    visiting, visited = set(), set()

    def visit(key: str) -> None:
        require(key in tasks, f"Unknown dependency: {key}")
        require(key not in visiting, "Task dependency cycle")
        if key in visited:
            return
        visiting.add(key)
        for dependency in tasks[key]["depends"]:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)
    for key in tasks:
        visit(key)


def run(args: argparse.Namespace) -> dict:
    with locked(Path(args.root)) as base:
        if args.command == "init":
            repos = sorted({repo_root(value) for value in args.repo})
            state = {"version": 2, "id": dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8],
                     "goal": nonempty(args.goal), "tier": args.tier, "repos": repos,
                     "created_at": now(), "tasks": {}, "carryovers": [], "history": []}
            event(state, "init")
            save(base / state["id"] / "state.json", state)
            return {"run": state["id"]}
        path = base / identifier(args.run) / "state.json"
        require(path.is_file(), f"Unknown run: {args.run}")
        state = json.loads(path.read_text())
        tasks = state["tasks"]
        validate_graph(tasks)
        if args.command == "status":
            complete, stale = completion(state)
            return {**state, "complete": complete, "stale_repositories": stale,
                    "open_carryovers": [item for item in state.get("carryovers", []) if item["open"]],
                    "reservations": {repo: read_reservation(repo) for repo in state["repos"]},
                    "usage": usage_summary(state)}
        release = None
        if args.command == "checkpoint":
            event(state, "checkpoint", evidence=nonempty(args.evidence))
        elif args.command == "carry":
            # Reviewer minors that are accepted as follow-up work instead of being lost in evidence text.
            items = state.setdefault("carryovers", [])
            if args.close is not None:
                match = next((item for item in items if item["id"] == args.close), None)
                require(match is not None and match["open"], f"No open carryover with id {args.close}")
                match.update(open=False, closed_at=now(), closure=nonempty(args.evidence))
                event(state, "carry", carryover=args.close, closed=True, evidence=match["closure"])
            else:
                require(args.task is None or args.task in tasks, f"Unknown task: {args.task}")
                item = {"id": len(items) + 1, "task": args.task, "evidence": nonempty(args.evidence),
                        "at": now(), "open": True}
                items.append(item)
                event(state, "carry", carryover=item["id"], task=args.task, evidence=item["evidence"])
        elif args.command == "rebind":
            # Migration only: records written by the pre-v2 digest can never match again.
            # The coordinator attests it compared the checkout with the accepted diffs.
            repo = repo_root(args.repo)
            require(repo in state["repos"], "Repository is outside this run's scope")
            require(not any(task["status"] in ACTIVE for task in tasks.values()),
                    "Stop and recover all active tasks before rebinding approvals")
            legacy = lambda value: bool(value) and not str(value).startswith(SNAPSHOT_FORMAT + ":")
            fresh = snapshot(repo, untracked(repo))  # bound: the tracked set may not change silently
            rebound = []
            for key, task in tasks.items():
                fields = {}
                if task["status"] == "done" and task["repo"] == repo and legacy(task["approval"]["snapshot"]):
                    task["approval"]["snapshot"] = fresh
                    fields["approval"] = True
                if legacy(task.get("retry_snapshot")) and task["repo"] == repo:
                    task["retry_snapshot"] = fresh
                    fields["retry_snapshot"] = True
                for name in ("dependency_snapshots", "integration_snapshots"):
                    if legacy((task.get(name) or {}).get(repo)):
                        task[name][repo] = fresh
                        fields[name] = True
                if fields:
                    rebound.append(key)
            require(bool(rebound), "No legacy-format snapshots to rebind in this checkout")
            event(state, "rebind", repo=repo, tasks=sorted(rebound), evidence=nonempty(args.evidence))
        elif args.command == "invalidate":
            repo = repo_root(args.repo)
            require(repo in state["repos"], "Repository is outside this run's scope")
            require(not any(task["status"] in ACTIVE for task in tasks.values()),
                    "Stop and recover all active tasks before invalidating approvals")
            affected = {key for key, task in tasks.items() if task["repo"] == repo and task["status"] == "done"}
            require(bool(affected), "No accepted tasks to invalidate in this checkout")
            while True:
                expanded = affected | {key for key, task in tasks.items() if affected.intersection(task["depends"])}
                if expanded == affected:
                    break
                affected = expanded
            for key in affected:
                tasks[key].update(status="pending", owner=None, evidence=None, snapshot=None, approval=None, retry_snapshot=None, dependency_snapshots=None)
            event(state, "invalidate", repo=repo, tasks=sorted(affected), evidence=nonempty(args.evidence))
        elif args.command == "add":
            key = identifier(args.id)
            require(key not in tasks, f"Task already exists: {key}")
            repo = repo_root(args.repo)
            require(repo in state["repos"], "Repository is outside this run's declared scope")
            require(args.agent not in REVIEWERS, "Review is a stage of an implementation task; use review, not add reviewer task")
            require(not any(task.get("integration") and task["status"] in ACTIVE for task in tasks.values()),
                    "Cannot add work while the final integration gate is active")
            require(not args.integration or args.agent == "gt-test-manager", "Integration requires the Sonnet gt-test-manager")
            require(not args.integration or args.risk != "low", "Integration requires Opus risk review")
            require(args.agent not in OPUS_AGENTS or args.risk != "low",
                    "Architecture and desktop specialist tasks cannot downgrade their Opus review requirement")
            require(args.agent not in OPUS_AGENTS or bool((args.route_reason or "").strip()),
                    "Opus profiles need --route-reason naming the ROUTING.md rule; routine work goes to Sonnet")
            tasks[key] = {"title": nonempty(args.title), "agent": args.agent, "repo": repo,
                          "risk": args.risk or ("high" if args.integration or args.agent in OPUS_AGENTS else "low"),
                          "route_reason": (args.route_reason or "").strip() or None,
                          "integration": args.integration,
                          "depends": list(tasks) if args.integration else list(dict.fromkeys(args.depends)),
                          "acceptance": [nonempty(item) for item in args.accept],
                          "status": "pending", "claims": 0, "changes": 0,
                          "owner": None, "evidence": None, "snapshot": None, "approval": None,
                          "dependency_snapshots": None}
            validate_graph(tasks)
            event(state, "add", task=key)
        else:
            require(args.id in tasks, f"Unknown task: {args.id}")
            task = tasks[args.id]
            identity = {"root": str(base.parent.parent), "run": state["id"], "task": args.id}
            checkouts = reserved_repos(state, task)
            if task["status"] in ACTIVE and args.command != "recover":
                reservations(checkouts, "verify", identity)
            if args.command == "claim":
                require(task["status"] == "pending", "Only pending tasks may be claimed")
                require(task["claims"] < MAX_CLAIMS, "Claim limit reached; checkpoint and create an explicitly revised plan")
                if task.get("integration"):
                    require(all(value["status"] == "done" for key, value in tasks.items() if key != args.id),
                            "Integration requires all other tasks to be done")
                    task["depends"] = [key for key in tasks if key != args.id]
                    validate_graph(tasks)
                require(all(tasks[key]["status"] == "done" for key in task["depends"]), "Dependencies are not done")
                input_repos = dependency_repos(state, task)
                if task.get("integration"):
                    require_current_approvals(state, set(state["repos"]), check_dependencies=False)
                else:
                    require_current_approvals(state, input_repos)
                    for key in task["depends"]:
                        if not tasks[key].get("integration"):
                            require_current_dependencies(state, tasks[key])
                    if task.get("retry_snapshot"):
                        require(current(task["repo"], task["retry_snapshot"]),
                                "Checkout changed after the repair handoff; block and explicitly resume after reconciling")
                    else:
                        require_current_approvals(state, {task["repo"]})
                # Inspect every run under this coordinator root to avoid sibling-run collisions.
                active = []
                for other in base.glob("*/state.json"):
                    other_state = state if other == path else json.loads(other.read_text())
                    active.extend(t for t in other_state["tasks"].values() if t["status"] in ACTIVE)
                require(len(active) < MAX_ACTIVE_TASKS, "At most two tasks may be active under this coordinator root")
                require(not any(t["repo"] == task["repo"] for t in active), "This checkout is already owned by an active task")
                task.update(status="running", owner=nonempty(args.owner), claims=task["claims"] + 1,
                            evidence=None, snapshot=None, approval=None,
                            baseline_untracked=untracked(task["repo"]),
                            dependency_snapshots={repo: snapshot(repo) for repo in sorted(input_repos)})
                event(state, "claim", task=args.id, owner=task["owner"])
                reservations(checkouts, "acquire", identity)
                if task.get("integration"):
                    # Bind the gate to everything the covered tasks created: only files that
                    # predate every covered task in a checkout may stay untracked after commit.
                    task["integration_snapshots"] = {repo: snapshot(repo, gate_baseline(tasks, task, repo)) for repo in checkouts}
                    task["integration_approvals"] = {key: value["approval"] for key, value in tasks.items() if key != args.id}
            elif args.command == "finish":
                require(task["status"] == "running", "Only running tasks may finish")
                require(args.owner == task["owner"], "Task owner does not match")
                evidence = nonempty(args.evidence)
                if args.outcome == "review":
                    require_current_dependencies(state, task)
                task.update(status=args.outcome, evidence=evidence, resubmitted=False,
                            snapshot=snapshot(task["repo"], task.get("baseline_untracked")) if args.outcome == "review" else None)
                record_usage(task, "implement", args.owner, task["agent"], args)
                event(state, "finish", task=args.id, owner=args.owner, outcome=args.outcome, evidence=evidence)
                if args.outcome == "blocked":
                    release = (checkouts, identity)
            elif args.command == "resubmit":
                # Coordinator-applied follow-up (a reviewer-requested one-liner, a lint fix) before any
                # verdict: rebind the submission to the current content without spending a claim.
                require(task["status"] == "review", "Only a task awaiting review may be resubmitted")
                require(args.owner == task["owner"], "Task owner does not match")
                require(not task.get("resubmitted"),
                        "Only one resubmit per submission; a further change is a CHANGES cycle (resume, claim, finish)")
                evidence = nonempty(args.evidence)
                require_current_dependencies(state, task)
                require(not current(task["repo"], task["snapshot"]), "Checkout is unchanged since submission; nothing to resubmit")
                task.update(snapshot=snapshot(task["repo"], task.get("baseline_untracked")), resubmitted=True,
                            evidence=f"{task['evidence']}\nRESUBMIT: {evidence}")
                event(state, "resubmit", task=args.id, owner=args.owner, evidence=evidence)
            elif args.command == "risk":
                require(task["status"] != "done", "Accepted tasks keep their reviewed risk; create a follow-up task")
                require(task.get("risk", "low") != "high", "Task is already high risk")
                task["risk"] = "high"
                event(state, "risk", task=args.id, level="high", evidence=nonempty(args.evidence))
            elif args.command == "review":
                require(task["status"] == "review", "Task must await review")
                require(args.reviewer != task["agent"] and nonempty(args.owner) != task["owner"],
                        "Review requires an independent role and owner")
                risk = task.get("risk", "low")
                require(risk != "high" or args.reviewer == "gt-risk-reviewer",
                        "High-risk tasks require gt-risk-reviewer")
                require(risk == "high" or args.reviewer == "gt-reviewer",
                        "Low-risk tasks use the Sonnet gt-reviewer; record `risk RUN TASK` or an escalate verdict first")
                require(args.verdict != "escalate" or args.reviewer == "gt-reviewer",
                        "Only gt-reviewer escalates; gt-risk-reviewer must return pass or changes")
                evidence = nonempty(args.evidence)
                require_current_dependencies(state, task)
                require(current(task["repo"], task["snapshot"]),
                        "Checkout changed since submission; resubmit once for an owner-applied follow-up, else resume explicitly")
                record_usage(task, "review", args.owner, args.reviewer, args)
                if args.verdict == "escalate":
                    # Sonnet found rule-1 territory: hand the same submission to Opus without a retry charge.
                    task["risk"] = "high"
                    event(state, "review", task=args.id, verdict="escalate",
                          reviewer=args.reviewer, owner=args.owner, evidence=evidence)
                elif args.verdict == "pass":
                    task.update(status="done", approval={"reviewer": args.reviewer, "owner": args.owner,
                                "evidence": evidence, "snapshot": task["snapshot"], "at": now()})
                    event(state, "review", task=args.id, verdict=args.verdict,
                          reviewer=args.reviewer, owner=args.owner, evidence=evidence)
                    release = (checkouts, identity)
                else:
                    task["changes"] += 1
                    task.update(status="blocked" if task["changes"] >= MAX_REVIEW_CHANGES or task["claims"] >= MAX_CLAIMS else "pending",
                                evidence=None, snapshot=None, approval=None,
                                retry_snapshot=snapshot(task["repo"], task.get("baseline_untracked")))
                    event(state, "review", task=args.id, verdict=args.verdict,
                          reviewer=args.reviewer, owner=args.owner, evidence=evidence)
                    release = (checkouts, identity)
            elif args.command == "block":
                require(task["status"] != "done", "Completed tasks cannot be blocked; create a follow-up task")
                owns_reservation = reservations(checkouts, "inspect", identity)
                require((task["status"] not in ACTIVE and not owns_reservation) or args.workers_stopped,
                        "Confirm workers stopped before releasing an active checkout with --workers-stopped")
                task.update(status="blocked", approval=None, snapshot=None, evidence=nonempty(args.evidence))
                record_usage(task, "block", task.get("owner") or "coordinator", task["agent"], args)
                event(state, "block", task=args.id, evidence=task["evidence"])
                release = (checkouts, identity)
            elif args.command == "resume":
                orphaned = task["status"] == "pending" and reservations(checkouts, "inspect", identity)
                require(task["status"] in ("running", "review", "blocked") or orphaned,
                        "Only interrupted, orphaned or blocked work may resume")
                require(args.workers_stopped, "Confirm workers stopped with --workers-stopped; never reclaim a live worker")
                require(task["claims"] < MAX_CLAIMS and task["changes"] < MAX_REVIEW_CHANGES,
                        "Retry/review budget exhausted; checkpoint and create an explicitly revised plan")
                task.update(status="pending", owner=None, evidence=None, snapshot=None, approval=None,
                            retry_snapshot=snapshot(task["repo"], task.get("baseline_untracked")))
                event(state, "resume", task=args.id, evidence=nonempty(args.evidence), workers_stopped=True)
                release = (checkouts, identity)
            elif args.command == "recover":
                require(args.workers_stopped, "Recovery requires --workers-stopped; never reclaim a live worker")
                require(reservations(checkouts, "inspect", identity), "No orphaned reservation owned by this task")
                task.update(status="blocked", owner=None, evidence=None, snapshot=None, approval=None)
                event(state, "recover", task=args.id, evidence=nonempty(args.evidence), workers_stopped=True)
                release = (checkouts, identity)
        save(path, state)
        if release:
            reservations(release[0], "release", release[1], allow_other=True)
        return {"run": state["id"], "task": getattr(args, "id", None), "command": args.command,
                "status": tasks[args.id]["status"] if getattr(args, "id", None) else "recorded"}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", default=os.getcwd(), help="Coordinator project root; default current directory")
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--goal", required=True)
    init.add_argument("--repo", action="append", required=True)
    init.add_argument("--tier", choices=("small", "standard", "large"), default="standard")
    for name in ("add", "claim", "finish", "resubmit", "review", "risk", "block", "resume", "recover",
                 "checkpoint", "carry", "invalidate", "rebind", "status"):
        command = commands.add_parser(name)
        command.add_argument("run")
        if name not in ("checkpoint", "carry", "invalidate", "rebind", "status"):
            if name == "add":
                command.add_argument("--id", required=True)
            else:
                command.add_argument("id")
        if name == "add":
            command.add_argument("--title", required=True)
            command.add_argument("--agent", choices=AGENTS, required=True)
            command.add_argument("--repo", required=True)
            command.add_argument("--integration", action="store_true", help="Final read-only all-repository validation by gt-test-manager, with Opus review")
            command.add_argument("--risk", choices=("low", "high"), help="Default high for architect/desktop; low otherwise")
            command.add_argument("--route-reason", help="Required for gt-architect/gt-desktop: the ROUTING.md rule that needs Opus")
            command.add_argument("--depends", action="append", default=[])
            command.add_argument("--accept", action="append", required=True)
        if name in ("claim", "finish", "resubmit", "review"):
            command.add_argument("--owner", required=True, help="Worker session identity; reviewers must use a different identity")
        if name in ("finish", "resubmit", "review", "risk", "block", "resume", "recover", "checkpoint", "carry", "invalidate", "rebind"):
            command.add_argument("--evidence", required=True, help="Concrete report, checks/results, or durable artifact paths")
        if name in ("finish", "review", "block"):
            command.add_argument("--tokens", type=int, help="Total tokens reported by the native agent result for this dispatch")
            command.add_argument("--model", help="Model observed in the native agent result, when available")
        if name == "carry":
            command.add_argument("--task", help="Task the carried-over finding belongs to")
            command.add_argument("--close", type=int, help="Close carryover id with the given evidence")
        if name in ("invalidate", "rebind"):
            command.add_argument("--repo", required=True)
        if name == "finish":
            command.add_argument("--outcome", choices=("review", "blocked"), default="review")
        if name == "review":
            command.add_argument("--verdict", choices=("pass", "changes", "escalate"), required=True)
            command.add_argument("--reviewer", choices=REVIEWERS, required=True)
        if name in ("resume", "recover", "block"):
            command.add_argument("--workers-stopped", action="store_true")
    return result


def main() -> int:
    try:
        print(json.dumps(run(parser().parse_args()), indent=2, ensure_ascii=False))
        return 0
    except (WorkflowError, OSError, ValueError, RecursionError) as error:
        print(f"taskctl: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
