# Model routing policy

This is GitTree's engineering policy, not a benchmark or a claim that a model
guarantees correctness. Model aliases are intentionally portable; record resolved
models from runtime metadata when available. Check availability in the current
Claude account. No automatic downgrade of an Opus task to Sonnet or Haiku.

| Profile | Model | Effort | Assignment |
|---|---|---|---|
| gt-orchestrator (main session only) | Sonnet | medium | Intake, scope, routing, dependencies, state, handoffs and final evidence |
| gt-scout | Haiku | low | Bounded file lookup, extracting known facts; no design or edits |
| gt-task-builder | Sonnet | medium | Acceptance criteria and small task DAG from clear requirements |
| gt-architect | Opus | high | Architecture, infrastructure, contracts, Rust/Git semantics, security-sensitive implementation |
| gt-desktop | Opus | high | Desktop UX, navigation, screens, interaction flows, integrations, graph and complex UI |
| gt-implementer | Sonnet | high | Routine implementation against accepted contracts; website UI; small desktop controls |
| gt-investigator | Sonnet | high | Reproduce and isolate ordinary bugs; read code and run bounded diagnostics |
| gt-bug-fixer | Sonnet | high | Fix a reproduced ordinary bug and add a meaningful regression check |
| gt-test-manager | Sonnet | high | Tests, fixtures, focused gates, integration and evidence collection |
| gt-reviewer | Sonnet | high | Independent review of low-risk changes; strictly read-only tools |
| gt-risk-reviewer | Opus | high | Architecture, complex desktop UX, infra, security, Git safety, cross-repo contracts; read-only |
| gt-doc-writer | Sonnet | medium | Documentation and evidence-based progress updates |
| gt-script-writer | Sonnet | high | Local tooling, generators, checks and ordinary scripts |

Routing decisions, in priority order:

1. User scope and repository rules first. An easy-looking task touching destructive
   Git actions, credentials, permissions, billing/entitlements, production infra,
   concurrency, data migrations, unsafe Rust, process execution, signing/updating,
   public IPC contracts or new cross-layer design goes to **gt-architect**, followed
   by **gt-risk-reviewer**. Routine wiring under an approved design can go to Sonnet
   with precise allowed files; the risky contract itself stays with Opus.
2. **Desktop app UX is Opus-owned.** Screens, integration flows, navigation,
   workspace state, focus architecture, keyboard interaction, complex dialogs,
   graph rendering and performance-sensitive behavior go to gt-desktop. A button,
   label, spacing change or simple dialog can go to Sonnet ONLY when it reuses an
   established component/pattern and changes no flow, state ownership, destructive
   action, accessibility model or IPC contract. Borderline cases go to Opus.
3. Website/dashboard presentation can use Sonnet, including responsive AR/EN/RTL.
   Authentication, billing and shared behavioral contracts still follow rule 1.
4. An unclear architecture or repeated unexplained bug goes to Opus. A missing
   file location goes to Haiku only if the search is bounded; broad diagnosis goes
   to Sonnet. Haiku never approves code, designs flows or implements business logic.
5. Documentation follows verified implementation. Haiku may extract an inventory;
   Sonnet writes the document. ADR decisions must first come from Opus.
6. Scripts that deploy, sign, change permissions, migrate data or orchestrate
   privileged infrastructure go to Opus. Routine local helpers go to Sonnet.

Use fixed profile effort on Claude Code 2.1.284. Do not pass per-call Agent effort
overrides requiring newer versions. No max-effort defaults. Escalation means a
better-scoped Opus assignment, not Sonnet repeatedly thinking harder. An explicit
owner-requested deep investigation can use a separate approved effort setting;
do not globally raise every worker's effort.

For small low-risk edits: implementer -> independent reviewer, with focused checks
in the implementation packet. Skip scouts, planners, separate docs and separate
validators unless they add evidence. Standard feature: task-builder only if useful,
implementer -> validator -> reviewer. Large/risky feature: architect -> dependency
ordered vertical slices -> validator -> risk-reviewer, then documentation and final
integration gate. These are conditional paths, not a mandatory parade of 12 agents.

Existing desktop agents without `gt-` remain manual compatibility tools. Their old
fleet-wide high-effort policy does not govern this workflow. Do not use them as an
automatic second fleet. Their specialized domain checklists can be read as needed.
