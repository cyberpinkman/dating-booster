# Host-Native Maturity Phase C

## Summary

Mature the Codex/host-native route without building an independent agent,
native macOS harness, daemon, or CLI-owned LLM calls. Codex remains responsible
for visual observation, screen operation, and LLM interpretation. Dating Booster
owns local state, constraints, audit, recovery, reports, deterministic evals,
and workflow contracts.

## Scope

- Host-loop recovery subcommands: `doctor`, `init`, `run`, `resume`, `status`,
  and `confirm-staged`.
- Work item scoped files in the loop work dir to prevent stale-file pollution.
- Observation authoring commands for host-written message-list and thread
  observations.
- Deterministic conversation eval fixture suite.
- User self-model readiness thresholds for autonomous operation.
- Replay timeline for run review.
- Runtime app support profiles for Tinder and WeChat; Bumble, 她说, Hinge, and
  other apps remain roadmap candidates until tests prove support.

## Non-Goals

- No native ScreenCaptureKit/CoreGraphics/Accessibility harness.
- No daemon or background scheduler.
- No private dating app APIs.
- No external LLM calls inside the CLI.

## Success Criteria

After installing the Codex skill and completing user profile, authorization,
goal, and availability setup, the user can ask Codex to start a Tinder host
loop. The host loop can stop, resume, report next host action, replay the last
run, and run deterministic conversation evals. Future app support should change
app-profile instructions rather than core operator/planner state.
