# Codex Adapter

The Codex adapter is currently packaged as `skills/dating-booster-codex/` so it
can be installed through Codex skill discovery.

This directory keeps the adapter taxonomy explicit alongside the current
Claude Code and OpenClaw-compatible adapters, including the Hermes compatibility
wrapper. Do not move the installable Codex skill here unless the installer path
is changed and tested.

Use the shared contract in `agent_adapters/shared/` for host-agnostic behavior.
Use `skills/dating-booster-codex/` for Codex-specific installation and operating
instructions.
