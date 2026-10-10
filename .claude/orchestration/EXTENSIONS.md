# Token-conscious extensions

These extensions support the existing coordinator. They do not replace its task
ledger, model policy, acceptance criteria or independent reviewers.

## Caveman

[Caveman](https://github.com/juliusbrussee/caveman) is enabled as the native Claude
plugin `caveman@caveman` in each project, including the parent workspace. The existing
installed revision was `0d95a81d35a9f2d123a5e9430d1cfc43d55f1bb0`; setup reuses the
registered marketplace and records project enablement. Project `.caveman.json` sets
`defaultMode: lite` for concise full sentences. Automatic marketplace updates are
disabled in these project declarations; inspect an update before adopting it.

Use concise prose, but preserve exact commands, paths, code, error text, numbers,
negations, acceptance criteria, findings and uncertainty. Handoffs must keep every
worker-contract report field. Do not shorten a test failure into an unsupported
"passed" summary. Write product documentation, UI copy, ADRs, commits and PRs normally.
Clarity wins when discussing architecture, permissions, failures or recovery.

Do not invoke cavecrew or a second orchestration fleet. Do not run caveman-compress
on governing instructions or task records automatically. This installation uses the
plugin's output style; no traffic proxy, API endpoint change, automatic prompt rewriting
or CLI telemetry component is installed. `/caveman lite` selects the style explicitly;
`/caveman off` stops it. Plugin version behavior should be checked after updates.

## Code Review Graph

[Code Review Graph](https://github.com/tirth8205/code-review-graph) **2.3.9** is
available through `.mcp.json`, pinned through `uvx --from code-review-graph==2.3.9`.
Only six context/query tools are exposed to reduce tool-description overhead:
minimal context, impact radius, review context, relationship query, changed-file
analysis and graph statistics. The coordinator retains MCP discovery/access;
reviewers remain Read/Grep/Glob-only and receive its compact relevant graph evidence.

Each Git repo owns its `.code-review-graph/graph.db` (ignored by Git). The container
has an MCP entry but no aggregate graph. In multi-repo work always pass the exact
absolute `repo_root` for the selected repo; never query the container as if it were
a Git checkout, or assume graph edges prove cross-repo compatibility.

Before broad code exploration or a review:

1. Once per changed batch, run `code-review-graph update --repo /absolute/repo`;
   use `build` only when its graph is absent or incompatible. The Sonnet test manager
   can run updates when explicitly assigned; never race an index update in the same repo.
2. Call `get_minimal_context_tool` with `repo_root`, actual task, explicit changed
   files and the correct diff base. For uncommitted work use `HEAD`; for a branch use
   its recorded merge base. Do not inherit a default `HEAD~1` blindly.
3. Request bounded impact/review context only if needed, then read the actual changed
   source, contracts, callers and relevant tests. Pass the compact result to workers.
4. For missing/empty/partial/stale graphs, unsupported syntax or dynamic references,
   fall back to rg and direct source reads. A graph is a navigation aid, not evidence
   of complete test coverage or absence of defects. Record parsing gaps.

No embeddings, cloud provider, watcher daemon, pre-commit hook or per-edit refresh
hook is enabled. Updating once at a workflow boundary avoids repeated indexing and
duplicate hook invocations. Source stays local to this graph process; normal Claude
requests still include whatever code/context the coordinator chooses to read.

## Commands

From the root, repeat `--target` for each selected project. From a standalone repo,
omit it. Configuration check is read-only and makes no model call.

```sh
python3 .claude/orchestration/extensions.py install --target . --target git_tree_app --target git-tree-web
python3 .claude/orchestration/extensions.py check --target . --target git_tree_app --target git-tree-web
python3 .claude/orchestration/extensions.py build --target git_tree_app --target git-tree-web
python3 .claude/orchestration/extensions.py status --target git_tree_app --target git-tree-web
claude mcp get code-review-graph
```

The installer enables only this explicitly requested project MCP server, preserves
other MCP servers and Claude settings, and requires Claude Code plus uv/uvx. It
installs the pinned graph CLI if absent; an incompatible existing version must be
reconciled rather than silently replaced. Graph databases are generated locally;
rebuild them after moving/cloning a repo because stored file paths are absolute.

Restart Claude after installation. Verify actual tool connection with `claude mcp
get code-review-graph` in each relevant project. Configuration success is distinct
from connection success, graph build success, model execution and feature acceptance.
No advertised token-reduction percentage is guaranteed for this project. Compare
observed usage on representative tasks before claiming savings.
