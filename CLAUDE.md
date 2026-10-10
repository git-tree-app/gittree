<!-- gittree-orchestration:start -->
## GitTree orchestration

Normal feature, fix, test, review and documentation requests automatically follow
[.claude/orchestration/WORKFLOW.md](.claude/orchestration/WORKFLOW.md).
No special prompt or `/orchestrate` command is required. The main session acts as
the coordinator, including in Claude Desktop's Code tab. Before behavioral work,
read the workflow and delegate bounded work to the configured `gt-*` specialists.
Routing is defined in
[.claude/orchestration/ROUTING.md](.claude/orchestration/ROUTING.md).
In a single Git repository, scope defaults to that repository only. Expand scope
only when explicitly requested. Simple questions and explanations do not spawn subagents.
<!-- gittree-orchestration:end -->
