# Dating Booster OpenClaw Adapter

Status: production adapter for the OpenClaw-compatible skill contract.

This package lets an OpenClaw-compatible host agent use Dating Booster without
forking domain logic. The host agent reads visible app context and executes
host-visible steps. Dating Booster remains the local CLI/core for memory,
policy, planner, workflow contracts, harnesses, audit, diagnostics, and release
checks.

Hermes uses the OpenClaw-compatible skill contract. The Hermes CLI entry points
install and diagnose this same package and report `compatibility_target:
openclaw`. This is not a separate Hermes-native adapter claim.

## Quick Start

```bash
dating-boost adapter openclaw install --scope project --target . --json
dating-boost adapter openclaw doctor --data-dir .local/dating-boost --json
```

Project installs write `.openclaw/skills/dating-booster/`.

For Hermes-compatible hosts:

```bash
dating-boost adapter hermes install --scope project --target . --json
dating-boost adapter hermes doctor --data-dir .local/dating-boost --json
```

The target path remains `.openclaw/skills/dating-booster/` because Hermes is
consuming the OpenClaw-compatible skill package.

## Boundaries

- Do not fork memory, policy, planner, app-profile, harness, or audit logic.
- Run adapter doctor, release doctor, data doctor, and capabilities before
  observing dating app content.
- Use managed live-send only through Dating Booster harness commands with
  authorization, target binding, staged text verification, and post-action
  verification.
- Keep private screenshots, OCR text, drafts, and app content local to the
  active task.
