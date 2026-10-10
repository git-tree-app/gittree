## Working mode

Work directly in the main session. Do not spawn subagents, agent teams, workflows
or any agent orchestration, and do not keep task ledgers.

Tools in use:
- **caveman** (`.caveman.json`, mode `lite`): terse replies; code, commits and
  security notes stay normal.
- **code-review-graph** MCP (`.mcp.json`): before reading many files or reviewing a
  change, use `get_minimal_context_tool`, `query_graph_tool`, `get_impact_radius_tool`,
  `detect_changes_tool` and `get_review_context_tool` to find context and impact.
