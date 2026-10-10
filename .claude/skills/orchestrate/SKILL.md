---
name: orchestrate
description: Execute or resume a GitTree task with scoped Claude model routing, bounded workers, independent review and a durable ledger. Works in one repo or a workspace of repos.
argument-hint: <task, or resume RUN_ID>
---

Remain in the main conversation. Read `.claude/orchestration/WORKFLOW.md` and
`.claude/orchestration/ROUTING.md` from the current project root, then handle:

$ARGUMENTS

If this is a resume request, inspect `.claude/task-runs/<RUN_ID>/state.json` before
planning. Confirm old workers stopped and reconcile current Git state. Do not
restart completed work. In a single repository keep that scope unless the user
explicitly expands it. In the workspace container select and state the minimum
relevant repositories. Follow the conditional small/standard/large paths; never
invoke all roles just because they exist.
