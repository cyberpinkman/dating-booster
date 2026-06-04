# Claude Code Adapter

Status: P1 planned adapter.

Claude Code should reuse the same Dating Booster CLI, capabilities, app profile,
policy, memory, planner, and audit contracts as Codex. The first implementation
should document Claude Code-specific setup and tool invocation only; it should
not copy Codex domain logic.

Initial checklist:

1. Confirm Claude Code shell/filesystem affordances.
2. Confirm screenshot/computer-use path or document that the host observes
   through user-provided artifacts.
3. Reuse `dating-boost capabilities --json --data-dir ...` as startup preflight.
4. Reuse `agent_adapters/shared/` workflow boundaries.
5. Add adapter-specific smoke or install checks only after the package becomes
   installable.
