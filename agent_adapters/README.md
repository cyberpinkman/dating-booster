# Agent Adapters

Dating Booster is host-agent native. Codex is the first adapter, not the only
shape. This directory separates shared agent contracts from host-specific
installation and operating notes.

## Layout

- `shared/`: host-agnostic workflow, privacy, CLI, capabilities, and app-profile
  contracts. Future adapters should reuse this before adding host-specific text.
- `codex/`: notes for the current Codex adapter. The installable package remains
  under `skills/dating-booster-codex/` for Codex discovery compatibility.
- `claude-code/`: P1 placeholder for Claude Code integration.

## Rules

- Do not copy Codex-specific assumptions into other adapters.
- Do not fork memory, policy, planner, or app-profile domain logic.
- If a host differs only in tool invocation wording, keep the core contract in
  `shared/` and document the host-specific invocation in that adapter.
- Future Hermes, OpenClaw, and MCP-oriented adapters should follow the same
  structure.
