# GitTree Claude orchestration

One Sonnet main session routes bounded tasks to 12 specialists, collects evidence,
requests independent review and records recovery state. Installed at the GitTree
workspace root and as a self-contained copy in each repository. This is the Claude
phase; it does not install or configure a GPT/Codex fleet.

See [MANUAL_TESTING.md](MANUAL_TESTING.md) for copyable routing, task completion,
pause/resume and direct-Opus checks.

[Caveman and Code Review Graph](EXTENSIONS.md) are configured per project for
concise communication and bounded source context. See that guide for setup,
graph refresh, portability and verification.

## Start working

**Claude Desktop:** open the **Code** tab, choose **Local**, select this workspace
or one installed repository, and select **Sonnet / Medium** for the coordinator.
Type your feature request normally. Project `CLAUDE.md` automatically starts the
workflow; no terminal command or `/orchestrate` prefix is required. Worker profiles
still choose Opus for complex desktop UX/architecture and Sonnet for ordinary work.
Use the app's existing Auto permission mode when appropriate; this setup does not
enable bypass permissions. Restart old sessions after a configuration update.

The model picker controls the main session: selecting Opus there keeps an Opus
coordinator and does not disable delegation. To work directly, explicitly request
the direct-work override described in MANUAL_TESTING.md. Desktop may use a worktree;
the package must be committed on its starting branch to be present in that checkout.
Runtime task records belong to the active checkout and are intentionally not copied
into fresh worktrees: resume the original checkout/run to continue saved work.

From **one repository**, start a fresh Claude Code session normally:

```sh
cd /path/to/git_tree_project/git_tree_app
claude
```

Project settings select `gt-orchestrator`, Sonnet, medium. Give your task normally,
or use `/orchestrate <task>`. Default scope is this repository only. A pre-existing
Claude session must be restarted to pick up the new configuration reliably.

The checked launcher verifies CLI version and common routing overrides:

```sh
python3 .claude/orchestration/setup.py doctor
python3 .claude/orchestration/setup.py launch "Fix the selected task"
```

From the **workspace root**, select one, several, or all immediate Git checkouts:

```sh
python3 .claude/orchestration/setup.py launch --repo git_tree_app "Improve the desktop flow"
python3 .claude/orchestration/setup.py launch --repo git-tree-backend --repo git-tree-web "Implement the shared feature"
python3 .claude/orchestration/setup.py launch --all "Audit integration compatibility, then fix confirmed issues"
```

`--all` discovers actual immediate Git roots, including worktrees, at invocation time.
It does not mean every repo must change. Plain `claude` at the container root also
works; the coordinator selects and states the smallest relevant scope from your task.
The launcher requires explicit container scope to make it reviewable before startup.
Use `--dry-run` to inspect argv/cwd without starting Claude. Paths with spaces work.
The launcher also accepts absolute paths to independently located Git checkouts.

## Who does what

See [ROUTING.md](ROUTING.md) for the complete task/model/effort matrix and escalation
rules. The important defaults are:

- Sonnet medium: coordinator, task decomposition and document writing.
- Sonnet high: ordinary implementation, website UI, simple desktop controls,
  bug reproduction/fixes, tests, ordinary scripts and low-risk review.
- Opus high: architecture, infrastructure, risky behavior/contracts, complex
  desktop UX/screens/integrations, and their independent review.
- Haiku low: small read-only fact lookup. No code approval or business decisions.

Small code changes use implementation plus review; no obligatory planner/scout.
Large features become dependency-ordered milestones. Parallel work is limited to
two tasks, with exclusive ownership of each checkout. Model choice is risk-based,
not based only on file extension. A website auth change can still need Opus.

`gt-test-manager` is the dedicated **Sonnet high** agent for test planning, writing
tests, focused and full-suite runs, failure analysis and the consolidated test report.
Fixing production failures is routed separately by the coordinator.

The policies are [WORKFLOW.md](WORKFLOW.md) and
[worker-contract.md](worker-contract.md). They include AR/EN/RTL, native desktop
verification, cross-repo contracts, preserved dirty work and scoped deployment authority.

## Durable task records

`taskctl.py` is a small Python standard-library state machine. It does not call a
model, execute tests, or dispatch workers; the main Claude session does those things.
It stores `.claude/task-runs/<RUN_ID>/state.json` outside version control. Do not put
secrets, credentials or customer data in evidence. Keep reports short and link to
local artifacts when full output is needed.

Example coordinator sequence (replace RUN with the ID returned by init):

```sh
python3 .claude/orchestration/taskctl.py init --goal "A bounded change" --repo /absolute/repo --tier small
python3 .claude/orchestration/taskctl.py add RUN --id T1 --title "Implement change" --agent gt-implementer --repo /absolute/repo --accept "Expected behavior and regression check"
python3 .claude/orchestration/taskctl.py claim RUN T1 --owner worker-1
# Dispatch the assigned native Claude worker; collect implementation and checks.
python3 .claude/orchestration/taskctl.py finish RUN T1 --owner worker-1 --evidence "Check command, cwd, result and changed files"
# Dispatch an independent reviewer against the captured state.
python3 .claude/orchestration/taskctl.py review RUN T1 --reviewer gt-reviewer --owner reviewer-1 --verdict pass --evidence "Acceptance and diff reviewed; no blocking findings"
python3 .claude/orchestration/taskctl.py status RUN
```

Use `--risk high` on risky tasks; Opus implementation profiles default to high risk
and need `--route-reason` naming the ROUTING.md rule. High risk requires
`gt-risk-reviewer`; low risk requires `gt-reviewer`, which can return
`--verdict escalate` to hand the same submission to Opus. Raise risk explicitly with
`risk RUN TASK --evidence`. Use `--depends T1` for downstream tasks. Other commands:
`resubmit RUN TASK --owner --evidence` rebinds a submission after a coordinator
follow-up without spending a claim; `carry RUN [--task T] --evidence` records a
reviewer minor as follow-up work (`--close ID` closes it); `--tokens`/`--model` on
`finish`, `review` and `block` feed `status` → `usage` (tokens by model, Opus share).
`status` also lists `reservations` (which run owns each checkout) and
`open_carryovers`. Snapshots (`v2:<content>:<head>:<tracked set>:<files the task created>`) bind
to working-tree content; when HEAD moves, the committed tree must equal that content
(index and working tree clean against HEAD, task-created files tracked), so
committing accepted work keeps admission while committing staged-but-unreviewed
blobs, partial stagings or `commit -am` without the new files blocks it; a reviewed
`rm` committed with `commit -a` or `git rm` stays current. Keep one run per program
across milestones. One `resubmit` per submission; a further change is a CHANGES
cycle. Runs recorded before the v2 digest report `stale_repositories`: compare the
checkout with the accepted diffs, then `rebind RUN --repo PATH --evidence` (no active
tasks) rewrites only legacy-format snapshots; it never accepts new content.
`--root /absolute/coordinator` before the command selects another ledger location.
One run has one coordinator; do not have workers manipulate the ledger.

Task lifecycle is pending -> running -> review -> done. A changes verdict returns
work for repair, subject to a maximum of 3 claims and 2 change-request cycles.
Blocked/partial work is not done. The helper binds approvals to a Git content digest,
rejects stale review, validates dependency order and records operation history.
The workflow still requires real acceptance/testing evidence; arbitrary evidence text
is not a cryptographic proof that a test ran or a reviewer is independent.

## Pause, failure and resume

Ask Claude to checkpoint/stop. It must stop active workers and confirm exit before
releasing ownership. A killed coordinator does not imply its worker has exited.
Checkpoint the run ID, session/agent IDs, current Git state, evidence, decisions,
blocked reason and exact next action. Do not automatically retry rate limits,
permission failures, missing models or environment failures forever.

To continue the Claude conversation, use `claude --resume SESSION_ID`, or the checked
launcher with the same scope:

```sh
python3 .claude/orchestration/setup.py launch --repo git_tree_app --resume SESSION_ID "Resume RUN from its checkpoint"
```

If the session is unavailable, start fresh and use `/orchestrate resume RUN`.
The ledger survives session loss. Recovery reconciles the current files, invalidates
stale evidence and requires explicit confirmation that old workers stopped:

```sh
python3 .claude/orchestration/taskctl.py checkpoint RUN --evidence "Stopped; next exact step; relevant session IDs"
python3 .claude/orchestration/taskctl.py resume RUN T1 --workers-stopped --evidence "Confirmed previous worker exited; current state checked"
```

Recovery never resets Git files or replenishes exhausted retries. A fundamentally
changed task requires an explicit revised plan, not renamed retries of the same failure.
External drift after approval blocks admission of subsequent work. Once workers
stop and the diff is reconciled, `taskctl.py invalidate RUN --repo PATH --evidence
"reconciliation details"` clears that checkout's approvals and dependent tasks for
revalidation, preserving attempt budgets.
Use the CLI `--help` on each subcommand for the full interface.

## Install, update and portability

The workspace `.claude/` package is the canonical editing location in this checkout.
Child repos receive real copies, so cloning/moving one repo does not require its parent.
Commit each repository's configuration with its own Git history when ready; the parent
container has no Git history. No commits or pushes are performed by setup.

```sh
python3 .claude/orchestration/setup.py install --target . --target git_tree_app --target git-tree-web
python3 .claude/orchestration/setup.py check --target . --target git_tree_app --target git-tree-web
python3 -m unittest discover -s .claude/orchestration -p 'test_*.py'
```

Repeat `--target` for the other repos. The installer merges only orchestration keys,
preserves permissions/hooks and settings.local.json, appends a marked CLAUDE.md block,
and adds ignores for local run records/cache. It checks collisions across all targets
before writing. Managed-file hashes detect independent child edits and refuse to
overwrite them; reconcile intentionally instead of using a force switch. To update
the workspace's own canonical files, edit them there, then run install again.
Preflight is collision-safe; installation is atomic per file, not a multi-repo database
transaction. If interrupted, rerun it and check all targets before starting work.

The original desktop specialist files are retained for manual reference; the default coordinator
routes only to `gt-*` workers. No Fable dependency is added.

## Cost, permissions and verified limits

Profiles use native `model`, `effort`, `maxTurns` and tool allowlists. Reviewers have
Read/Grep/Glob only. Other workers with Bash are constrained by workflow and normal
Claude permissions, not an OS sandbox. No bypass-permission mode or automatic
deployment is installed. The launcher rejects common global effort/forced-model
overrides; provider alias remapping and managed policies still need account-level
verification. Stop a task if a runtime fallback violates its required model family.

Depth 1 and concurrency 2 are configured. Do not enable ultracode or resume workers
in a way that bypasses these limits. Native turn limits bound a dispatch; the coordinator
must classify partial results correctly. Run/milestone call limits are workflow controls,
not a hard token or dollar cap. API `--max-budget-usd` applies to print mode, not normal
interactive subscription sessions. Review actual usage; do not promise a savings rate.
This setup resumes work across days when you restart a session; it is not a daemon
that wakes itself after shutdown, lost connectivity, quota limits or missing approval.

CLI compatibility baseline: locally observed Claude Code **2.1.284** on 2026-10-10.
Use the current installed version and account availability; aliases can change.
Static checks and helper tests do not establish a live multi-model implementation run.
Helpers require Python 3.10+ on macOS/Linux (or WSL); checkout locks use `fcntl`.
See [VALIDATION.md](VALIDATION.md) for completed checks and authenticated
model-routing and isolated implementation smoke tests.

Official references checked for this design:

- [Custom subagents](https://code.claude.com/docs/en/sub-agents): native profiles,
  main-session agent mode and delegation controls. Per-call effort requires a newer
  CLI than this baseline, so this package sets effort in each profile.
- [Model configuration](https://code.claude.com/docs/en/model-config): alias and
  effort behavior. Avoid global overrides that flatten role-specific routing.
- [Agent-team limitations](https://code.claude.com/docs/en/agent-teams#limitations):
  why this package uses one coordinator with workers and disk state.
- [Settings](https://code.claude.com/docs/en/settings): project configuration and
  precedence. Higher-priority user/managed settings can affect runtime behavior.
