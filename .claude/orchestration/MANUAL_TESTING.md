# Manual acceptance tests

Use a fresh Claude Code session after installing or updating the package. Keep the
runtime tool/model evidence: an agent's prose about its identity is not proof.
These tests check orchestration; they do not establish application release readiness.

## 1. Configuration and authentication

From the workspace root (or any standalone installed repository):

```sh
claude auth status
python3 .claude/orchestration/setup.py doctor
python3 -m unittest discover -s .claude/orchestration -p 'test_*.py'
python3 .claude/orchestration/extensions.py check
claude mcp get code-review-graph
```

Expected: logged in, doctor succeeds, helper tests pass, extension configuration is
current, MCP connects. Doctor alone does not test authentication. If auth fails,
run `claude auth login` in the same terminal environment and recheck. Never send
credentials, OAuth tokens or full private settings with a test report.

## 2. Live routing without product changes

From the workspace container:

```sh
python3 .claude/orchestration/setup.py launch --repo git_tree_app
```

Paste:

```text
/orchestrate Run a read-only routing smoke test in git_tree_app.
Do not edit files, run full suites, commit, push, or deploy.
Sequentially delegate:
1. gt-scout: locate the desktop test commands.
2. gt-test-manager: inspect those commands and propose one focused check.
3. gt-risk-reviewer: review the plan using the actual package scripts.
Use each profile's configured model without overrides. Stop after three workers.
Report roles, results, permission/model errors and PASS/FAIL. Keep configured model
families separate from actual runtime model evidence; do not guess identities.
```

Expected routing: scout Haiku, test manager Sonnet, risk reviewer Opus, main Sonnet.
Exact versions depend on the installed CLI/provider alias. Inspect the expanded
Agent calls/transcript and usage details. Three agents should finish sequentially;
no worker should wait for a sibling or spawn a nested coordinator.

## 3. A complete small task in a disposable checkout

Avoid a first write test on valuable dirty work. Create a tiny repository outside
your application checkouts, then install the package into it:

```sh
test_repo=$(mktemp -d "${TMPDIR:-/tmp}/gittree-manual.XXXXXX")
git init "$test_repo"
python3 .claude/orchestration/setup.py install --target "$test_repo"
cd "$test_repo"
claude
```

Paste:

```text
/orchestrate This is a disposable Python fixture, scoped only to this checkout.
Create parity.py with is_even(value: int) -> bool and test_parity.py using unittest.
Acceptance: even integers including zero and negative evens return True; odd
integers return False. Use only the standard library. No dependency installation,
network, other repo access, commits, pushes, or deployment. No graph is needed.
Use Sonnet implementation, Sonnet test-manager to run the tests, then an independent
Sonnet reviewer. Record the real evidence in the task ledger and report the run ID.
Keep the workflow proportional to this small task; stop if blocked.
```

Then verify independently in another terminal in that same disposable checkout:

```sh
python3 -m unittest test_parity -v
python3 .claude/orchestration/taskctl.py status RUN_ID
git diff
git status --short
```

Expected: passing real tests, correct contents, task complete, independent reviewer
owner, no out-of-scope edits. Newly created untracked files are shown by `git status`
and must also be inspected; `git diff` alone does not show them.

## 4. Checkpoint and resume

In the disposable checkout, ask for a second small behavior (for example is_odd)
but append: `Create the run and plan, then checkpoint and stop before dispatch.`
Record its RUN_ID. Exit Claude only after it confirms no active workers remain.
Start a fresh `claude` session in the same checkout, then paste:

```text
/orchestrate resume RUN_ID. Inspect the saved ledger and current Git state first.
Previous workers have stopped. Continue only the recorded in-scope work, preserving
attempt counters and completed evidence. Run the required checks and independent
review. Do not reset files or manufacture completed work.
```

Expected: the same run is used, pending work continues, no duplicated completed
work, no indefinite wait. If a worker was actually interrupted, confirm its exit
before allowing recovery; stopping a parent session alone is not proof of exit.

## 5. Single/multiple repository scope

These previews make no model request:

```sh
# Run from the workspace container:
python3 .claude/orchestration/setup.py launch --repo git_tree_app --dry-run
python3 .claude/orchestration/setup.py launch --repo git-tree-backend --repo git-tree-web --dry-run
python3 .claude/orchestration/setup.py launch --all --dry-run
# Run from a standalone repository:
python3 .claude/orchestration/setup.py launch --dry-run
```

Expected: exact selected roots; standalone defaults to itself. --all discovers
current immediate Git repositories. It does not require editing all of them.
Actual concurrent writes should be tested only on disposable independent checkouts:
two active workers maximum, one owner per checkout, dependency consumers wait for
producer approval. The helper regression suite exercises concurrent reservation,
stale review, changed producer inputs, recovery and exhausted retry rejection.

## Direct Opus for one task

First ask the current coordinator to stop its workers and checkpoint. In Claude,
open `/model`, select Opus and use the session-only choice (`s` on supported CLI
versions) if you do not want to save a new default. `/model opus` switches directly
but may also save the user default. Then paste:

```text
For this task only, work directly as Opus in the main session.
Do not delegate or use the orchestration workflow or ledger for this task.
Keep repository engineering rules and required checks.
Task: [concrete task]
Scope: [repository and allowed changes]
Do not modify files owned by an active worker. Report changes, checks and gaps.
Do not claim independent review when you performed the work yourself.
```

A prompt cannot switch models by itself. For simultaneous direct work use a separate
worktree at the intended starting state; integrate and revalidate afterwards. To
return, select Sonnet and ask `/orchestrate resume RUN_ID`; direct edits can make
old approvals stale and must be reconciled. The checked launcher intentionally
selects Sonnet for coordinated work; do not use it to start a direct Opus task.

Model selection: [official Claude documentation](https://code.claude.com/docs/en/model-config#setting-your-model).

## Send back this compact report

```text
Test number / PASS, FAIL or BLOCKED:
CLI version / working directory:
Run ID (if any):
Actual runtime models visible:
Command and exit code / test counts:
Exact error or unexpected behavior:
Did all workers stop?:
```
