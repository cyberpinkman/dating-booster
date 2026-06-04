# Agent Adapters

Dating Booster is host-agent native. Codex is the first adapter, not the only
shape. This directory separates shared agent contracts from host-specific
installation and operating notes.

## Layout

- `shared/`: host-agnostic workflow, privacy, CLI, capabilities, and app-profile
  contracts. Future adapters should reuse this before adding host-specific text.
- `codex/`: notes for the current Codex adapter. The installable package remains
  under `skills/dating-booster-codex/` for Codex discovery compatibility.
- `claude-code/`: installable Claude Code adapter package. It writes
  `.claude/skills/dating-booster/` or `~/.claude/skills/dating-booster/` through
  `dating-boost adapter claude-code install`.

## Rules

- Do not copy Codex-specific assumptions into other adapters.
- Do not fork memory, policy, planner, or app-profile domain logic.
- If a host differs only in tool invocation wording, keep the core contract in
  `shared/` and document the host-specific invocation in that adapter.
- Future Hermes, OpenClaw, and MCP-oriented adapters should follow the same
  structure.

## Adapter Install Checks

```bash
dating-boost adapter claude-code install --scope project --target . --dry-run --json
dating-boost adapter claude-code doctor --data-dir .local/dating-boost --json
dating-boost-host-loop doctor --adapter-package agent_adapters/claude-code/adapter-package.json --data-dir .local/dating-boost --json
```

Host-loop keeps `--skill-package` for Codex-era compatibility, but new adapters
should use `--adapter-package`.
