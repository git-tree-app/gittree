## Working mode

Work directly in the main session. Do not spawn subagents, agent teams, workflows
or any agent orchestration, and do not keep task ledgers.

Tools in use:
- **caveman** (`.caveman.json`, mode `lite`): terse replies; code, commits and
  security notes stay normal.
- **code-review-graph** MCP (`.mcp.json`): before reading many files or reviewing a
  change, use `get_minimal_context_tool`, `query_graph_tool`, `get_impact_radius_tool`,
  `detect_changes_tool` and `get_review_context_tool` to find context and impact.

<!-- BEGIN GITTREE ENGINEERING SKILLS -->
## Shared engineering skills

For substantive engineering work, read [.agents/skills/gittree-engineering/SKILL.md](.agents/skills/gittree-engineering/SKILL.md) and apply the
relevant skills it routes to. The skills are shared procedures for this session;
they do not authorize subagents, orchestration, task ledgers or external actions.
Keep this repository's binding architecture, contracts and verification gates.
Use current manifests for versions and commands. Read selected skill files before
implementation; finish with actual test evidence and unverified coverage.
<!-- END GITTREE ENGINEERING SKILLS -->
