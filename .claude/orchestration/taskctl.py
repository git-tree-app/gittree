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
ACTIVE = ("running", "review")
MAX_ACTIVE_TASKS = 2
MAX_CLAIMS = 3
MAX_REVIEW_CHANGES = 2


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


def snapshot(repo: str) -> str:
    """Hash HEAD, index and tracked/untracked nonignored file contents, including deletions."""
    root = Path(repo)
    digest = hashlib.sha256()

    def feed(data: bytes) -> None:
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)

    head = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "HEAD"], capture_output=True)
    feed(head.stdout if head.returncode == 0 else b"UNBORN")
    for entry in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if entry and not excluded(entry.split(b"\t", 1)[1]):
            feed(entry)
    names = set(git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0"))
    for name in sorted(names):
        if not name or excluded(name):
            continue
        feed(name)
        path = root / os.fsdecode(name)
        if path.is_symlink():
            feed(b"LINK" + os.fsencode(os.readlink(path)))
        elif path.is_file():
            feed(str(path.stat().st_mode & 0o777).encode())
            feed(path.read_bytes())
        elif path.is_dir():
            # Gitlinks/submodules need their nested working state, not just their commit.
            # Uninitialized submodules have no .git; recursing would find the parent.
            feed(snapshot(str(path)).encode() if (path / ".git").exists() else b"UNINITIALIZED_DIRECTORY")
        else:
            feed(b"MISSING")
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


def reservation(repo: str, action: str, identity: dict, allow_other: bool = False) -> bool:
    """Persistent checkout ownership survives process crashes and coordinator roots."""
    directory = Path(git(Path(repo), "rev-parse", "--absolute-git-dir").decode().strip())
    path = directory / "gittree-taskctl-reservation.json"
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


def stale_dependencies(state: dict, task: dict) -> set[str]:
    """A later producer approval cannot retroactively validate a consumer's tests."""
    inputs = task.get("dependency_snapshots") or {}
    return {repo for repo in dependency_repos(state, task)
            if inputs.get(repo) != snapshot(repo)}


def require_current_dependencies(state: dict, task: dict) -> None:
    stale = stale_dependencies(state, task)
    require(not stale,
            f"Dependency checkout changed: {sorted(stale)}. Reconcile inputs; invalidate accepted work or block/resume active work, then submit fresh evidence")


def completion(state: dict) -> tuple[bool, list[str]]:
    """Later accepted tasks supersede earlier repo snapshots; external edits do not."""
    tasks = list(state["tasks"].values())
    if not tasks or any(task["status"] != "done" for task in tasks):
        return False, []
    latest = {}
    for task in tasks:
        previous = latest.get(task["repo"])
        if previous is None or task["approval"]["at"] > previous["at"]:
            latest[task["repo"]] = task["approval"]
    stale = {repo for repo, approval in latest.items() if snapshot(repo) != approval["snapshot"]}
    for task in tasks:
        stale.update(stale_dependencies(state, task))
    return not stale, sorted(stale)


def require_current_approvals(state: dict, repos: set[str]) -> None:
    """Prevent a new task from silently absorbing changes to accepted work."""
    for repo in repos:
        for task in state["tasks"].values():
            if task["repo"] == repo and task["status"] == "done":
                require_current_dependencies(state, task)
        approvals = [task["approval"] for task in state["tasks"].values()
                     if task["repo"] == repo and task["status"] == "done" and task["approval"]]
        if approvals:
            latest = max(approvals, key=lambda approval: approval["at"])
            require(snapshot(repo) == latest["snapshot"],
                    f"Accepted checkout changed: {repo}. Reconcile the diff and use invalidate before new work")


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
            state = {"version": 1, "id": dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8],
                     "goal": nonempty(args.goal), "tier": args.tier, "repos": repos,
                     "created_at": now(), "tasks": {}, "history": []}
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
            return {**state, "complete": complete, "stale_repositories": stale}
        release = None
        if args.command == "checkpoint":
            event(state, "checkpoint", evidence=nonempty(args.evidence))
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
            require(args.agent not in ("gt-architect", "gt-desktop") or args.risk != "low",
                    "Architecture and desktop specialist tasks cannot downgrade their Opus review requirement")
            tasks[key] = {"title": nonempty(args.title), "agent": args.agent, "repo": repo,
                          "risk": args.risk or ("high" if args.agent in ("gt-architect", "gt-desktop") else "low"),
                          "depends": list(dict.fromkeys(args.depends)),
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
            if task["status"] in ACTIVE and args.command != "recover":
                reservation(task["repo"], "verify", identity)
            if args.command == "claim":
                require(task["status"] == "pending", "Only pending tasks may be claimed")
                require(task["claims"] < MAX_CLAIMS, "Claim limit reached; checkpoint and create an explicitly revised plan")
                require(all(tasks[key]["status"] == "done" for key in task["depends"]), "Dependencies are not done")
                input_repos = dependency_repos(state, task)
                require_current_approvals(state, input_repos)
                for key in task["depends"]:
                    require_current_dependencies(state, tasks[key])
                if task.get("retry_snapshot"):
                    require(snapshot(task["repo"]) == task["retry_snapshot"],
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
                            dependency_snapshots={repo: snapshot(repo) for repo in sorted(input_repos)})
                event(state, "claim", task=args.id, owner=task["owner"])
                reservation(task["repo"], "acquire", identity)
            elif args.command == "finish":
                require(task["status"] == "running", "Only running tasks may finish")
                require(args.owner == task["owner"], "Task owner does not match")
                evidence = nonempty(args.evidence)
                if args.outcome == "review":
                    require_current_dependencies(state, task)
                task.update(status=args.outcome, evidence=evidence,
                            snapshot=snapshot(task["repo"]) if args.outcome == "review" else None)
                event(state, "finish", task=args.id, owner=args.owner, outcome=args.outcome, evidence=evidence)
                if args.outcome == "blocked":
                    release = (task["repo"], identity)
            elif args.command == "review":
                require(task["status"] == "review", "Task must await review")
                require(args.reviewer != task["agent"] and nonempty(args.owner) != task["owner"],
                        "Review requires an independent role and owner")
                require(task.get("risk", "low") != "high" or args.reviewer == "gt-risk-reviewer",
                        "High-risk tasks require gt-risk-reviewer")
                evidence = nonempty(args.evidence)
                require_current_dependencies(state, task)
                require(task["snapshot"] == snapshot(task["repo"]),
                        "Checkout changed since submission; resume explicitly and submit fresh evidence")
                if args.verdict == "pass":
                    task.update(status="done", approval={"reviewer": args.reviewer, "owner": args.owner,
                                "evidence": evidence, "snapshot": task["snapshot"], "at": now()})
                else:
                    task["changes"] += 1
                    task.update(status="blocked" if task["changes"] >= MAX_REVIEW_CHANGES or task["claims"] >= MAX_CLAIMS else "pending",
                                evidence=None, snapshot=None, approval=None, retry_snapshot=snapshot(task["repo"]))
                event(state, "review", task=args.id, verdict=args.verdict,
                      reviewer=args.reviewer, owner=args.owner, evidence=evidence)
                release = (task["repo"], identity)
            elif args.command == "block":
                require(task["status"] != "done", "Completed tasks cannot be blocked; create a follow-up task")
                owns_reservation = reservation(task["repo"], "inspect", identity)
                require((task["status"] not in ACTIVE and not owns_reservation) or args.workers_stopped,
                        "Confirm workers stopped before releasing an active checkout with --workers-stopped")
                task.update(status="blocked", approval=None, snapshot=None, evidence=nonempty(args.evidence))
                event(state, "block", task=args.id, evidence=task["evidence"])
                release = (task["repo"], identity)
            elif args.command == "resume":
                orphaned = task["status"] == "pending" and reservation(task["repo"], "inspect", identity)
                require(task["status"] in ("running", "review", "blocked") or orphaned,
                        "Only interrupted, orphaned or blocked work may resume")
                require(args.workers_stopped, "Confirm workers stopped with --workers-stopped; never reclaim a live worker")
                require(task["claims"] < MAX_CLAIMS and task["changes"] < MAX_REVIEW_CHANGES,
                        "Retry/review budget exhausted; checkpoint and create an explicitly revised plan")
                task.update(status="pending", owner=None, evidence=None, snapshot=None, approval=None,
                            retry_snapshot=snapshot(task["repo"]))
                event(state, "resume", task=args.id, evidence=nonempty(args.evidence), workers_stopped=True)
                release = (task["repo"], identity)
            elif args.command == "recover":
                require(args.workers_stopped, "Recovery requires --workers-stopped; never reclaim a live worker")
                require(reservation(task["repo"], "inspect", identity), "No orphaned reservation owned by this task")
                task.update(status="blocked", owner=None, evidence=None, snapshot=None, approval=None)
                event(state, "recover", task=args.id, evidence=nonempty(args.evidence), workers_stopped=True)
                release = (task["repo"], identity)
        save(path, state)
        if release:
            reservation(release[0], "release", release[1], allow_other=True)
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
    for name in ("add", "claim", "finish", "review", "block", "resume", "recover", "checkpoint", "invalidate", "status"):
        command = commands.add_parser(name)
        command.add_argument("run")
        if name not in ("checkpoint", "invalidate", "status"):
            if name == "add":
                command.add_argument("--id", required=True)
            else:
                command.add_argument("id")
        if name == "add":
            command.add_argument("--title", required=True)
            command.add_argument("--agent", choices=AGENTS, required=True)
            command.add_argument("--repo", required=True)
            command.add_argument("--risk", choices=("low", "high"), help="Default high for architect/desktop; low otherwise")
            command.add_argument("--depends", action="append", default=[])
            command.add_argument("--accept", action="append", required=True)
        if name in ("claim", "finish", "review"):
            command.add_argument("--owner", required=True, help="Worker session identity; reviewers must use a different identity")
        if name in ("finish", "review", "block", "resume", "recover", "checkpoint", "invalidate"):
            command.add_argument("--evidence", required=True, help="Concrete report, checks/results, or durable artifact paths")
        if name == "invalidate":
            command.add_argument("--repo", required=True)
        if name == "finish":
            command.add_argument("--outcome", choices=("review", "blocked"), default="review")
        if name == "review":
            command.add_argument("--verdict", choices=("pass", "changes"), required=True)
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
