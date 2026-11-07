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
- Run adapter doctor, release doctor, data doctor, and capabilities after
  installation, updates, migration, permission changes, or for diagnostics;
  match the original adapter scope and target. Daily ManagedRun reuses the
  verified setup and begins with `manage start`.
- Select the matching app/runtime in the same data dir on first use or an
  explicit target change. Use a `--host openclaw` or `--host hermes` support
  session for real-GUI Canary, diagnostics, or a support bundle; stop it afterward.
- TaShuo mac-ios-app full management uses flagship ManagedRun for both hosts:
  start, then immediately hold `manage run --wait`; status/pause/resume/stop
  operate on that same run. Read the installed `references/workflows.md`.
- Other apps/runtimes and existing workflows use the `managed-session` /
  `dating-boost-host-loop` compatibility path with explicit authorization,
  target binding, staged-text verification, and post-action verification.
  Direct harness send is executor-internal; do not handcraft action requests.
- Keep private screenshots, OCR text, drafts, and app content local to the
  active task.
