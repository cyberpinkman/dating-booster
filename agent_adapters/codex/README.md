# Codex Adapter

The Codex adapter is currently packaged as `skills/dating-booster-codex/` so it
can be installed through Codex skill discovery.

This directory exists to keep the adapter taxonomy explicit as Dating Booster
expands to Claude Code, Hermes, OpenClaw, and MCP-oriented hosts. Do not move
the installable Codex skill here unless the installer path is changed and tested.

Use the shared contract in `agent_adapters/shared/` for host-agnostic behavior.
Use `skills/dating-booster-codex/` for Codex-specific installation and operating
instructions.
