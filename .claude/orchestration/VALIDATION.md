# Setup verification — 2026-10-10

Initial scope: workspace container plus git_tree_app, git-tree-web, git-tree-backend,
admin_dashboard, git-tree-backend-docs, git-tree-course and gittree.
At final synchronization, git-tree-backend-docs was no longer present due to an
external workspace change. It was not recreated. Final sync covers the root and
six currently present Git repositories; its earlier build results below are historical. These are
configuration/runtime checks of the orchestration setup, not application acceptance.

- Python helper/configuration suite: **58 tests passed**. Covers task dependencies,
  atomic state, cross-run/cross-root checkout ownership, concurrent claims, stale
  review, retry/review limits, crash recovery, Opus review enforcement, standalone
  installations, collision preservation, routing overrides and extension settings.
- `claude plugin validate .claude`: passed in all eight locations.
- `setup.py check`: installed copies match the canonical package.
- Root multi-repo launcher dry-run selected the exact desktop/web checkouts.
  Standalone moved-package launch is covered by the helper tests.
- Caveman enabled per project; local mode is lite. Existing native plugin revision
  reused: `0d95a81d35a9f2d123a5e9430d1cfc43d55f1bb0`.
- Code Review Graph 2.3.9 project configuration: verified in all eight locations.
  `claude mcp get code-review-graph`: **Connected** in each location.
- Real stdio MCP tools/list returned exactly the intended six query/context tools.
  get_minimal_context_tool was called through MCP with explicit repo paths: six
  repositories returned ok; the course repository returned not_ready for an empty
  graph, as expected. Direct source reading is its documented fallback.
- Full graph builds completed for all seven repos. Every status reported
  build_incomplete=false. Graphs are local snapshots; refresh after source changes.

| Repo | Indexed files | Nodes | Edges |
|---|---:|---:|---:|
| git_tree_app | 3,119 | 35,776 | 426,474 |
| git-tree-web | 672 | 3,300 | 30,641 |
| git-tree-backend | 464 | 4,534 | 50,707 |
| admin_dashboard | 105 | 1,091 | 14,715 |
| git-tree-backend-docs | 406 | 3,711 | 37,102 |
| git-tree-course | 0 | 0 | 0 |
| gittree | 1 | 2 | 36 |

## Authenticated runtime tests

Earlier attempts failed before model execution because the CLI OAuth session had
expired. After the owner logged in again on 2026-10-10, auth status confirmed an
active claude.ai session and both tests below succeeded without permission denials.

1. Read-only native delegation in the GitTree workspace: Sonnet 5.5 coordinator
   dispatched gt-scout on **claude-haiku-4-5-20251001**, gt-test-manager on
   **claude-sonnet-5-5**, and gt-risk-reviewer on **claude-opus-5-5**, sequentially.
   Actual assistant event models and final modelUsage confirm those models. The
   coordinator's prose incorrectly described the scout's configured family; runtime
   evidence and the profile establish Haiku. Do not use self-reported identities as
   model evidence. This run only inspected files; it did not run product tests.
2. Complete isolated fix/test/review run in a disposable Git repository without
   remotes: gt-bug-fixer corrected an inverted integer parity predicate;
   gt-test-manager ran four unittest cases; a separate gt-reviewer approved it.
   All three workers and the coordinator used **claude-sonnet-5-5**. The main session
   created and claimed the task before dispatch, recorded checks, finished to review,
   recorded the independent verdict and checked completion. Independent inspection
   confirmed 4/4 tests pass, only the intended source line changed, ledger
   `complete: true`, no stale repositories and the checkout reservation released.
   Run: `20261010T134657Z-a97164ed`.

Local runtime artifacts (not committed):
- `/tmp/gittree-claude-routing-live.jsonl`
- `/tmp/gittree-orchestration-e2e-live.jsonl`
- `/tmp/gittree-orchestration-e2e-path` records the disposable fixture location.

CLI list-price estimates were USD 2.56745 for workspace routing and USD 0.31596
for the isolated full cycle; these are not subscription invoices or a representative
savings benchmark. The workspace smoke had substantially more context loaded.
Role-specific effort remains configuration-verified; the transcript did not provide
independent per-worker effort metadata. Live concurrent cross-repo edits, an actual
process crash/restart, product UX and multi-day work were not exercised. The helper
suite covers concurrent ownership, recovery, retry bounds and stale input rejection.

## Audit fixes

- Cross-repository and transitive dependency contents are captured on claim; later
  producer edits prevent consumer submission/approval and false completion, even
  when the producer edit itself received approval. Revalidation keeps retry limits.
- Extension preflight rejects higher-priority local Caveman/MCP disables and global
  MCP disables that merge into effective configuration. It preserves local files.
- The workflow documents explicit direct-main-session overrides while preserving
  checkout ownership, engineering checks and stale-approval reconciliation.

See [MANUAL_TESTING.md](MANUAL_TESTING.md) for copyable acceptance prompts and
pause/resume checks. These results do not establish zero defects or release readiness.
