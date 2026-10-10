# Main-session operating procedure

Apply this only in the coordinator/main session. Workers obey worker-contract.md
and their bounded assignment, not this dispatch procedure. Use native Claude Code
subagents, no agent teams, nested coordinators, hidden model CLI processes, or
self-restarting loops. The coordinator is the sole dispatcher and ledger writer.

This workflow is automatic for normal project requests in Claude Desktop's Code
tab and the CLI. It does not depend on a slash command or a special launch prompt.
Desktop's selected main-session model may override the project model setting;
Sonnet medium is the cost-conscious coordinator default. This does not change the
fixed models in worker profiles. Ordinary questions still get direct answers.

## Explicit direct-work override

The user may explicitly request direct work by the main session without delegation
or the orchestration ledger for a bounded task. Honor that override; it does not
remove repository engineering rules, required checks, or deployment boundaries.
First checkpoint any existing run and confirm its workers stopped before editing
the same checkout. Preserve reservations until worker exit is confirmed. If direct
edits change accepted work, invalidate its approval before resuming orchestration.
Do not report direct work as independently reviewed. Concurrent direct work needs
a separate checkout/worktree and a later integration/revalidation step. A prompt
cannot change the actual model: the user must select Opus in Claude first.

## 1. Intake and scope

For implementation requests, state the outcome, architectural reason, selected
repos, risk, acceptance criteria and smallest viable next step briefly. Questions
and explanations need no run. For a tiny nonbehavioral typo, the main Sonnet session
may edit and verify directly; record a brief completion without a fleet or ledger.
Any behavioral/code task uses the ledger and independent review.

In a single Git checkout, the default scope is that checkout alone. In the workspace
container choose the minimum relevant Git roots based on the request. “All repos”
includes every explicitly selected checkout, not a mandate to edit each one.
List selected repos before editing. Do not expand an explicitly single-repo task
silently; explain a dependency and ask for the missing scope while doing independent
in-scope work. Never infer authority to deploy from authority to implement.

Read applicable AGENTS.md and each selected CLAUDE.md. Record absolute checkout,
branch, HEAD and initial git status. User dirty work is not yours. Scope an unrelated
edit separately; if it overlaps required files and ownership is unclear, block that
slice. Do not stash/reset/clean it. Resolve conflicting business specs with the owner
before implementing the uncertain behavior.

## 2. Plan proportional to the task

Read EXTENSIONS.md once per session. Use Caveman lite for concise prose while
preserving every handoff field. Before broad exploration/review, refresh and query
the selected repo's Code Review Graph for compact context; fall back to direct
source reads for missing/partial/stale coverage. Do not invoke its alternate agents
or Caveman's cavecrew, proxy setup, or instruction compression.

Read ROUTING.md. Classify small, standard or large. Use gt-task-builder only when
decomposition saves work, gt-architect when a design/contract is genuinely needed.
Architecture approval does not mean owner approval for deployment. The coordinator
turns the result into the task graph; workers do not create tasks for other workers.

Use `python3 .claude/orchestration/taskctl.py --help` for the local ledger interface.
Initialize one run with goal, selected Git roots and tier. **One run spans the whole
program**: milestones are checkpoints inside it, not new runs. The ledger binds
approvals to working-tree content; when HEAD moves the committed tree must equal
that content, so committing the accepted diff keeps admission for the next task,
while a content change, a partially staged commit, a staged-but-unreviewed blob or
a commit that leaves out a file the task created (`commit -am`) blocks it. Commit
the whole reviewed tree, never `git add -p` subsets; untracked files that predate
the claim are the owner's and may stay untracked. Commit accepted producer work
before claiming its consumer so the consumer binds to the committed contract. Runs created
before this digest report stale; verify and `rebind` them once (README). Do not open a successor run to escape a
blocked task or a changed checkout; reconcile and `invalidate` inside the run.
Add small tasks with exact
repo, allowed files (in the assignment), dependencies, role and acceptance criteria.
A task is small enough when one worker can finish it and one reviewer can read its
diff inside their turn limits: split ADRs by section and features by risk slice
(ROUTING.md "Opus budget rules") before dispatch, not after two CHANGES cycles.
Dependencies point to previously created tasks. Work in vertical slices; do not
split by agent role if that only multiplies handoffs. Planning reports can be kept
in a checkpoint; they do not require standalone reviewed code tasks.
Create one ledger task per deliverable, never a second task merely to review it.
Review is the existing task's `running -> review -> done` transition. Dispatch
gt-reviewer/gt-risk-reviewer against that same task and record `review RUN TASK`;
never `add --agent gt-reviewer` or `add --agent gt-risk-reviewer`. Test-manager may
validate the same claimed task after its implementer exits, before finish-to-review.

For multi-repo changes, settle producer/consumer contract before parallel builds.
Assign each task one checkout. Make contract fixtures/generation a single-owner
task. Run consumer work after its required producer task is accepted. Final integration
must cover all changed repos and compatibility; individual unit tests are insufficient.
Never merge partially compatible repositories merely because each compiles.
Cross-repository dependencies are bound to their exact checkout contents at claim.
Any producer change, even a separately approved task, makes prior consumer evidence
stale. Finish/review/completion refuse that evidence. Stop workers, reconcile and
invalidate the producer and affected dependents, then revalidate within the existing
retry budget. Same-checkout sequential changes remain supported.

## 3. Dispatch and ownership

Before the first claim in a checkout, read `taskctl.py status RUN` → `reservations`.
A reservation held by another run or coordinator root means another session owns
that checkout: do not edit it, do not start a parallel run in it, and do not
`recover` it unless the owner confirms that session's workers stopped. **One
coordinator session per checkout.** The 2026-10-10 billing/ads collision (two
sessions editing `git-tree-web`, one committing under the other's reservation)
cost four refused reviews; the reservation is the rule, the file is only the record.

Claim a ready task in taskctl BEFORE spawning its worker. Use a unique owner/dispatch
token, record the returned native agent ID in a checkpoint, and pass this packet:

```text
run / task / owner token; goal and bounded deliverable
absolute repo / current HEAD / pre-existing edits / assigned allowed files
selected role, model family and effort; why this route applies
acceptance criteria / frozen decisions / completed dependency evidence
relevant CLAUDE.md, AGENTS.md, spec and code paths (not the entire conversation)
commands and runtime environments needed; exclusions and authorized actions
worker-contract.md absolute path; expected report; stop/partial behavior
```

Do not pass a model override to Agent that defeats the profile. Use only gt-* worker
profiles. Never spawn gt-orchestrator as a child. At most **2 active workers** across
this run, and **one active task per checkout**, including validation/review. Serialize
same-checkout implementation and review. Independent checkouts may run in parallel
only after their contracts are stable. Review work also consumes a worker slot even
if the ledger task is in review status. Do not run a validator alongside a mutating
worker in its repo. Check other open runs before dispatching.

Additional same-repo parallelism requires explicitly prepared separate worktrees at
the recorded source SHA with a plan for integration. Never enable native automatic
worktree isolation blindly: it can start at a different base and omit dirty changes.
Default to serial work within one checkout. Do not copy secret-bearing ignored files.

The Sonnet `gt-test-manager` owns test planning, test/fixture changes, focused runs,
full-suite runs and result analysis. For a full-suite request it inventories all
applicable repo-mandated commands, executes them in dependency order, reports
command/cwd/exit/duration/counts and separates failing, skipped and unavailable
coverage. It sends product failures to the coordinator for routing to a fixer;
it never launches its own agents or weakens tests. Run the required full integration
gate after a large feature settles; avoid repeating every full suite for each small fix.

The coordinator can run checks and update the ledger but does not race a worker's
source edits. Wait for real tool completion/notifications, not for an invented sibling
message. No sleep/poll busy loop. Give concise updates during long work. A worker
waiting on another task is a planning error: stop it and record its dependency.

## 4. Results, gates and independent review

Read the report and the actual diff. Reject out-of-scope changes or unsupported
completion claims. Capture the exact check command/cwd/result and remaining gaps.
Run the repo's required checks, plus focused meaningful regression tests for behavior
changes. Do not create tests that mirror a reversible copy/style change.

Record finish-to-review only after the implementation/validation evidence is ready,
passing `--tokens` and `--model` from the native agent result when shown. The ledger
snapshots Git content. Spawn a fresh reviewer with task, acceptance, baseline/current
diff file, exact files, checks and known gaps. Reviewer role/session must differ from
the implementer. Reviewers have no shell/edit tools; coordinator supplies diff
artifacts or relevant file paths and test evidence and runs any requested command.
Do not add Bash to reviewers to pretend they are read-only. Risky work always requires
gt-risk-reviewer; low-risk work always starts with gt-reviewer, whose ESCALATE verdict
(`review --verdict escalate`) hands the same submission to gt-risk-reviewer at no retry
cost. A risky subtask may not be approved by the Sonnet reviewer merely because the
implementation was mechanically small; that is what ESCALATE is for.

Findings need severity, file:line, concrete impact and reproduction or clearly labeled
risk. Style preferences are not blockers. On CHANGES, give one consolidated fix packet
to the original implementer or gt-bug-fixer; reroute deep root causes/desktop flows to
Opus. Re-run affected checks and review the changed surface, not the entire project.
Changed content invalidates previous review evidence. If unrelated work invalidated
a snapshot, recapture and review the actual final diff; never fake the old hash.
A coordinator-applied follow-up before any verdict (a reviewer-suggested one-line
alias, a lint fix) is recorded with `taskctl.py resubmit RUN TASK --owner TOKEN
--evidence "..."`, which rebinds the submission without spending a claim, once per
submission; the reviewer must then read the resubmitted diff. A second change, or
any change after a CHANGES verdict, is a normal repair cycle. Unrelated external
edits are never folded in through resubmit; reconcile them and `invalidate`. Reviewer minors accepted as later work
go to `taskctl.py carry RUN --task TASK --evidence "file:line finding"`, never only
into free-text evidence; close each with `carry RUN --close ID --evidence` when a
task fixes it or the owner waives it.
If an already accepted checkout changes before the next task, admission stops.
Reconcile the external diff and use `taskctl.py invalidate RUN --repo PATH --evidence
"reason and changed scope"` with no active workers. This invalidates accepted tasks
in that checkout and their dependent tasks without replenishing attempt budgets.
Recheck their acceptance before progressing; a later unrelated approval must not
silently cover previously reviewed behavior that changed externally.

Complete only with accepted criteria, relevant required gates passing, independent
review, true docs/ledger, and no unresolved blocking finding. Native UI, actual OAuth,
payments, OS variants, signing, updater and deployed behavior need their own evidence.
If unavailable, state the missing gate and leave the applicable task blocked/partial.
For UI, inspect real rendered AR/EN, RTL, keyboard/focus, loading/empty/error states,
small screens and applicable themes. Fixture screenshots are not native app proof.
Always run `taskctl.py status RUN` before claiming whole-run completion: it must
report `complete: true`, no stale repositories and no pending/running/review tasks.
A finished worker or a native CLI success result alone does not complete the run.
The milestone/final report lists `open_carryovers` (each becomes a task or an
explicit owner waiver) and `usage` (tokens by model, `opus_share`) so routing can
be corrected in the next plan.

Update product ledgers only after acceptance; for desktop keep phase checklist and
docs/PROGRESS.md consistent and run tooling/check-progress.sh. The orchestration
ledger tracks execution, not a replacement product source of truth. Any source edits
after approval, including fixes triggered by documentation, require fresh relevant checks
and review. Final integration checks run after all participating changes settle.

## 5. Bounds, errors, stopping and recovery

Every dispatch has maxTurns in its profile. Partial output is never approval. Default
limits: 3 worker claims per task, 2 requested-changes review cycles; no hidden resets
of counters. An exhausted task is a sign the task was too large: the owner-authorized
continuation must be a smaller follow-up task with the remaining findings as its
acceptance, not the same assignment again. Small run: target <=3 worker calls; standard <=8 per slice; large <=12
per milestone. These are admission/checkpoint limits, not hard billing caps. When
exceeded, stop to summarize progress, remaining work and a concrete next milestone;
do not manufacture new IDs to bypass a exhausted task's retry limit.

Classify a blocker: requirement/scope, failed gate, missing environment, permission,
rate limit/model unavailable, worker crash, or out-of-budget. At most one retry of an
identical transient failure. Never fall back from Opus to Sonnet for an Opus-only task.
Continue independent ready tasks only if doing so is safe and useful. If no ready task
exists, checkpoint and return BLOCKED with the exact action needed. Do not idle while
waiting for a human or external service or install a recurring automation unasked.

Before context compaction, user pause, quota exhaustion, milestone end or shutdown,
checkpoint: run ID, native session/agent IDs when known, exact repo/HEAD/dirty state,
decisions, completed evidence, active owners, next command and blocker. On user stop,
stop active workers with the native stop tool, wait for their exit, then release/recover
claims. No replacement writer until exit is confirmed. If the process was killed and
this cannot be confirmed, require the operator to stop/confirm old workers first.

Resume through the saved Claude session when available, but the disk ledger is the
portable recovery record. Read it first, re-read current Git state and governing specs,
compare scope and snapshots, invalidate stale assumptions/approvals, and recover only
after workers are confirmed stopped. Recovery clears old task evidence and consumes
remaining attempts; it does not rewind files or replenish budget. A new session can
continue from this record without the old conversation. Archive neither worktrees nor
run records until required evidence and changes are retained.

The helper also reserves the actual Git checkout across different coordinator roots.
A reservation left by a crash does not expire automatically. Use `recover` only
after confirming workers stopped, then explicitly resume within the remaining budget.

One coordinator per run. Ledger locking protects file updates, not arbitrary shell
commands or another Claude session that ignores the workflow. If another session is
editing the checkout, coordinate ownership or stop that slice. No zero-bug guarantee,
hard token ceiling or unattended multi-day daemon is implied by this setup.
