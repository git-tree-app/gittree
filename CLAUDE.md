## Working mode

Work directly in the main session. Do not spawn subagents, agent teams, workflows
or any agent orchestration, and do not keep task ledgers.

Tools in use:
- **caveman** 4.x plugin (`.caveman.json`, `defaultMode: "caveman"`): terse replies;
  code, commits and security notes stay normal. `/caveman status` shows the mode.
- **code-review-graph** 2.3.9 MCP (`.mcp.json`; local graph in
  `.code-review-graph/graph.db`, never committed). Start with
  `get_minimal_context_tool(task=...)`; if it reports `not_ready` or a stale branch,
  call `build_or_update_graph_tool` first. Then use `query_graph_tool`,
  `semantic_search_nodes_tool`, `traverse_graph_tool`, `get_impact_radius_tool`,
  `detect_changes_tool`, `get_affected_flows_tool` and `get_review_context_tool`
  with `detail_level="minimal"` before reading many files or reviewing a change.
  The `crg-watch` daemon keeps graphs current; without it, run
  `code-review-graph update` (or `build` after a branch switch).

<!-- BEGIN GITTREE ENGINEERING SKILLS -->
## Shared engineering skills

For substantive engineering work, read [.agents/skills/gittree-engineering/SKILL.md](.agents/skills/gittree-engineering/SKILL.md) and apply the
relevant skills it routes to. The skills are shared procedures for this session;
they do not authorize subagents, orchestration, task ledgers or external actions.
Keep this repository's binding architecture, contracts and verification gates.
Use current manifests for versions and commands. Read selected skill files before
implementation; finish with actual test evidence and unverified coverage.
<!-- END GITTREE ENGINEERING SKILLS -->
