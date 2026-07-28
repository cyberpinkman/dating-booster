# Dating Booster Architecture

Dating Booster is a host-agent native capability layer for dating workflows.
The durable product value is not tied to one agent, one app, one goal, or one
memory shape. The architecture keeps those four axes separate so each
integration can reuse the same product contracts.

Dating Booster 是面向 host agent 的 dating workflow 能力层。核心价值不能绑死在
某一个 agent、某一个 app、某一个目标或某一种记忆结构上。后续扩展必须沿清晰的
边界推进，不能把临时需求直接塞进现有 Codex/Tinder 路径。

## Current Layers

```text
host agent adapter
  -> CLI and host adapter tools
  -> app support profile contract
  -> native GUI harness, only when testable
  -> observation / memory / context / planner / policy / audit core
  -> local storage and diagnostics
```

Core modules stay host-agnostic, app-agnostic where possible, and model-provider
agnostic. Host-specific packages and app-specific harnesses may orchestrate the
core, but they must not fork domain rules.

核心模块保持 host-agnostic、尽量 app-agnostic，并且不绑定模型供应商。Host-specific
包和 app-specific harness 只能编排核心能力，不能复制或分叉领域规则。

## Standalone Agent Runtime

The standalone runtime is a new consumer of existing managed-session and operator contracts. It does not fork policy, planner, memory, app adapter, runtime scope, or managed-send rules.

Primary path:

```bash
export MINIMAX_API_KEY="<coding-plan-subscription-key>"
dating-boost runtime select --data-dir .local/dating-boost --app-id tashuo --runtime mac-ios-app --json
python3 scripts/tashuo_mac_ios_standalone_doctor.py --data-dir .local/dating-boost --json
DATING_BOOST_KEY_PROVIDER=local python3 scripts/tashuo_mac_ios_standalone_smoke.py --data-dir .local/dating-boost --authorization auth.json --json
```

The smoke wrapper includes the alpha release gate. It returns success only when
the smoke JSON and durable logical `audit/stage_results.jsonl` stream in encrypted SQLite show a completed
stage-only attempt, exact staged text verification, verified target, and no live
send. Saved smoke output can be rechecked with
`python3 scripts/tashuo_mac_ios_standalone_alpha_gate.py --data-dir .local/dating-boost --smoke-json tashuo-standalone-smoke.json --json`.

The TaShuo standalone production Gate composes those same neutral contracts and
remains stage-only. Its implementation lives under
`dating_boost/apps/tashuo/standalone_production_*`; operational acceptance rules
belong in `AGENTS.md` and the agent runbook. Having the Gate in source is not a
qualification certificate for any machine and does not change live-send policy.

Current rollout status:

1. Host-native workflows remain the default production route.
2. TaShuo `mac-ios-app` is the primary standalone runtime and remains
   stage-first.
3. Scripted fixtures support deterministic cross-app development; standalone
   production providers for Tinder, Bumble, and WeChat have not graduated.
4. TaShuo production qualification is environment-specific and stage-only; it
   does not change or certify live-send policy.

## Host Agent Adapter Axis

Codex is the first adapter, not the architecture. Claude Code and OpenClaw now
have installable adapter packages, and Hermes uses the verified
OpenClaw-compatible contract. Additional hosts must reuse the same local CLI
contracts.

Codex 是第一个 adapter，不是架构本体。Claude Code 和 OpenClaw 已有可安装
adapter package，Hermes 使用经过验证的 OpenClaw-compatible contract。新增
host 必须复用相同本地 CLI contract。

Rules:

- Keep `dating_boost/core/*`, `dating_boost/policy/*`, `dating_boost/perception/*`,
  and `dating_boost/intelligence/*` free of host-agent assumptions.
- Treat `skills/dating-booster-codex/` as one host agent adapter package.
  Treat `agent_adapters/claude-code/` as the Claude Code adapter package because
  Claude Code discovers `.claude/skills/<name>/` through an installer instead of
  Codex's skill package path.
- Shared workflow truth should live in core CLI schemas, capabilities, app
  profiles, and common docs. Host packages may explain how that host runs the
  tools, but no duplicated domain logic.
- A host agent adapter should document its tool affordances: shell access,
  browser/computer-use ability, filesystem access, screenshot handling, and
  whether it can install skills/plugins.
- If an adapter needs different command wording, add adapter docs. Do not add
  conditional behavior to core unless the underlying capability truly differs.

## App Support Profile Axis

Runtime app profiles are only for apps Dating Booster can actually support.
Bumble has graduated to iPhone Mirroring navigation plus opt-in managed
ordinary chat send. TaShuo supports the iPhone Mirroring path and, on Apple
Silicon Macs, the optional mac-ios-app runtime for launch/observe/stage plus
managed ordinary chat send. Unsupported apps stay outside runtime discovery
until their path is testable.

runtime app profile 只用于已经可支持的 app。Bumble 已进入 iPhone Mirroring
导航和授权托管普通聊天发送支持；她说支持 iPhone Mirroring 路径，并在 Apple
Silicon Mac 上支持可选 mac-ios-app runtime 的 launch/observe/stage 和托管普通聊天发送；
未支持的 app 在测试路径明确前不进入 capabilities。

Support levels:

- `native_observation`: screenshot/OCR/layout hints exist with redaction.
- `native_navigation`: safe read-only navigation exists and has dry-run tests.
- `native_draft_staging`: paste/stage path exists with exact staged-text
  verification.
- `managed_live_send`: send is still blocked by default and only allowed through
  explicit authorization, policy-checked action request, target-specific
  binding, runtime-supported exact staged-text verification, and post-action
  verification.

Implementation rules:

- `app_profiles/<app_id>.json` is the product contract; schema v2 declares the
  adapter backend, capabilities, selectors/coordinates, blocked actions,
  target-binding policy, live-send evidence, managed-session policy, and special
  app rules.
- `dating_boost/apps/<app_id>/adapter.py` is the runtime behavior boundary. App
  page semantics, workflows, target binding, send verification, and special
  social rules live in the adapter/profile pair or adapter-owned session
  modules under `dating_boost/apps/`, not in `dating_boost/core/gui_harness.py`.
- `dating_boost/apps/registry.py` is the only source for supported app ids,
  host-loop app ids, and app capability manifests.
- `schemas/app_profile.schema.json` is the formal profile schema and
  `tests/test_app_profiles.py` keeps profile files aligned.
- `dating_boost/core/capabilities.py`, managed sessions, host loop, and CLI
  harness commands derive supported apps from the registry.
- `dating_boost/harness/native_gui.py` owns native GUI mechanics: window
  location, screenshot/OCR, click/swipe/wheel, clipboard/paste, IME commit, and
  platform backend execution. `dating_boost/core/gui_harness.py` is only a
  compatibility import surface.
- Unsupported apps must be absent from `app_profiles/`, capabilities, native
  harness commands, and host-loop execution.

## Goal Type Axis

`dating_boost/core/goals.py` defines the current goal type registry.
`meet_in_person` is the default, alongside `build_rapport`,
`screen_compatibility`, `revive_stalled_chat`, and `maintain_connection`.
Planner behavior must come from the selected definition instead of assuming
every conversation should progress toward a meeting.

`dating_boost/core/goals.py` 已实现 goal type registry。`meet_in_person` 是默认
目标，同时支持 `build_rapport`、`screen_compatibility`、
`revive_stalled_chat` 和 `maintain_connection`。Planner 必须读取所选目标定义，
不能假设每段对话都要推进约见。

Each goal definition contains:

- `goal_type`: stable id such as `meet_in_person`, `build_rapport`,
  `screen_compatibility`, `revive_stalled_chat`, or `maintain_connection`.
- `milestones`: goal-specific progress states.
- `allowed_moves`: goal-specific recommendation set.
- `handoff_rules`: when the user must decide instead of the agent.
- `required_user_context`: user preferences needed before autonomous operation.
- `policy_constraints`: actions or claims that remain forbidden for this goal.
- `success_evidence`: what counts as progress without overclaiming.

The draft workflow should consume planner recommendations instead of directly
assuming the goal. The policy layer should validate action risk independently
from the goal.

## Workflow And Memory Axis

Current memory surfaces:

- user profile and disclosure readiness.
- match identity and profile facts.
- normalized observations.
- conversation visible context and latest inbound turn boundary.
- feedback events.
- planner goal plan, conversation scores, topic lifecycle, reciprocity, and
  low-investment repair signals.
- action audit and replay.

Memory evolution follows these rules:

- Facts require provenance. Inferences must stay marked as inferences.
- Memory summaries must be versioned and reversible from raw local event logs
  where practical.
- Match-local memory, user-global memory, app-specific state, and goal-specific
  strategy should not collapse into one blob.
- Feedback should update preferences and drafting constraints through explicit
  events, not silent prompt drift.
- Self-improving memory should prefer deterministic local updates and evals
  before adding model-generated long-term summaries.
- Workflows should be scenario-specific when behavior differs: opener for
  unopened matches, reply to recent inbound, low-investment repair, stalled chat
  nudge, profile refresh, and user handoff are different workflows.

## Anti-Debt Rules

- Do not add a new host agent by copying the Codex skill and editing wording
  only. Extract shared references or clearly mark what is host-specific.
- Do not add a new dating app by adding coordinates first. Add fixtures,
  preflight, and support-contract evidence before adding a runtime app profile.
- Do not add a new goal by branching on strings in prompts only. Add or extend
  the goal type registry and planner contract.
- Do not add memory by appending free-form text to one file. Define the event,
  owner, schema version, provenance, and retrieval path.
- Do not let docs, app profiles, capabilities, and skill references drift. Any
  extension should update all four or add a test that proves the omission is
  intentional.

## Expansion Checklist

For a new host agent adapter:

1. Add or update host adapter docs under a host-specific adapter path such as
   `agent_adapters/<host>/`.
2. Reuse CLI/capabilities contracts; avoid host-specific domain logic.
3. Document privacy boundaries for visible dating app content.
4. Add a smoke test or install check if the package becomes installable.

For a new app:

1. Keep it outside runtime discovery until fixtures and preflight are testable.
2. Add `app_profiles/<app_id>.json` using schema v2 only when the app is
   runtime-supported.
3. Add `dating_boost/apps/<app_id>/adapter.py` and register it in
   `dating_boost/apps/registry.py`.
4. Add fixtures and tests for classifier behavior, dry-run action/workflow
   planning, blocked actions, target binding, send evidence, and host-loop
   preflight.
5. Let capabilities, CLI harness, managed session, and host loop consume the
   registry; do not add app-specific branches to those global layers.
6. Update `AGENTS.md`, `docs/README.md`, `app_profiles/README.md`, and relevant
   host adapter docs. Update README only when the human-facing summary changes.

For a new goal:

1. Define the goal type contract.
2. Add planner fixtures and policy checks.
3. Add context fields needed by the host agent.
4. Keep user handoff rules explicit.

For smarter memory/workflows:

1. Start from an event/schema addition, not a prompt-only change.
2. Define provenance and redaction behavior.
3. Add eval fixtures for behavior that should improve.
4. Keep generated summaries inspectable and replaceable.
