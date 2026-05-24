# Dating Booster Product Architecture Blueprint

Status: accepted draft
Date: 2026-05-25

## Purpose

This document defines the ideal mature Dating Booster product first, then defines the MVP as a reusable vertical slice of that mature architecture. The goal is to avoid an MVP that proves a narrow demo but conflicts with the future system.

Dating Booster is a local-first, agent-first copilot for dating workflows. It uses authorized local GUI observation and action, structured memory, LLM reasoning, and strict policy controls to help the user understand matches, draft messages, stage replies, and optionally execute high-risk actions under explicit user control.

## Product North Star

The mature product should feel like a competent local dating operator:

1. It remembers the user, each match, and conversation history.
2. It understands dating app screens through perception, not private APIs.
3. It drafts high-quality replies using memory, context, persona, and stance controls.
4. It can stage actions in the real app through semantic actions.
5. It defaults to human confirmation for high-risk actions.
6. It is local-first, auditable, and clear about platform account risk.
7. It can support multiple dating apps through app adapters.

The product is not a scraping platform, account farm, anti-detection system, or private API client.

## Mature Product Surfaces

### CLI

The CLI remains the developer and power-user surface.

Responsibilities:

- run local setup checks.
- inspect current state.
- refresh match memory.
- draft replies.
- run offline evals.
- start or stop the local daemon.
- expose advanced commands before a GUI exists.

### Local Desktop UI

A later desktop UI can provide review and control.

Responsibilities:

- show current match memory.
- compare draft options.
- edit user profile, persona range, and stance range.
- review policy prompts.
- inspect audit logs.
- manage privacy export and delete flows.

### MCP and Skill Adapters

External coding or agent hosts should call semantic tools, not raw GUI controls.

Responsibilities:

- expose stable local tools to Codex, Claude Code, Hermes, OpenClaw, and similar hosts.
- keep host agents outside the raw click/type layer.
- route all high-risk actions through the local policy engine.

### Menu Bar or Background App

A later menu bar app can make the local daemon approachable for non-technical users.

Responsibilities:

- show connection status.
- display current screen classification.
- notify when user confirmation is needed.
- provide quick pause and privacy controls.

## System Architecture

```text
User Surfaces
  CLI / Desktop UI / MCP Adapter / Menu Bar
        |
Local API Boundary
        |
dating-boostd
  Policy Engine
  Privacy Manager
  Audit Log
  App Session Manager
  Perception System
  Memory System
  Intelligence Layer
  Semantic Action Controller
        |
App Adapter Layer
  Generic Dating Adapter
  Tinder Adapter
  Future App Adapters
        |
macOS Harness
  iPhone Mirroring Window
  Screenshot Capture
  Accessibility / CoreGraphics Input
```

The mature architecture has one hard rule: model backends and external agents never receive direct raw GUI authority. They can request semantic actions; the local controller decides how to execute and verify them.

## Core Layers

### dating-boostd

`dating-boostd` is the local daemon and authority boundary.

Responsibilities:

- own the local data directory.
- manage permissions and app session state.
- expose a local API to CLI, UI, and MCP adapters.
- coordinate perception, memory, intelligence, policy, and actions.
- write an audit log for user-visible decisions and high-risk events.

The MVP can run daemon responsibilities in-process through the CLI, but module boundaries must match the future daemon.

### macOS Harness

The harness interacts with the user's local Mac.

Responsibilities:

- discover and focus the iPhone Mirroring window.
- capture screenshots.
- send keyboard, paste, click, scroll, and gesture events.
- report action results and low-level errors.

The harness must be treated as unreliable. Every action that changes app state needs post-action verification from perception.

### Perception System

The perception system converts screenshots into structured app state.

Responsibilities:

- classify page type.
- extract visible text.
- detect important UI elements.
- identify modal, paywall, network, permission, and loading states.
- emit confidence and evidence.
- verify whether an action reached the expected state.

Perception should support both live screenshots and offline screenshot fixtures using the same interface.

### Memory System

The memory system stores and retrieves structured local state.

Responsibilities:

- user profile.
- match profile.
- conversation memory.
- strategy state.
- memory provenance.
- match identity resolution.
- feedback events.
- export and delete flows.

The memory system should not depend on a specific app. App-specific observations are normalized before entering durable memory.

### Intelligence Layer

The intelligence layer turns context into analysis and drafts.

Responsibilities:

- analyze profile text and photos into structured observations.
- summarize conversations.
- build context packs.
- generate drafts in Self, Adaptive, and Recipient-Optimized modes.
- support persona and stance modulation.
- flag missing information and unsupported assumptions.
- produce structured outputs for UI and eval.

The intelligence layer can use different model backends but must keep stable local contracts.

### Semantic Action Controller

The semantic action controller maps high-level user or agent intents to app-specific actions.

Examples:

- `observe_current_screen`
- `refresh_match_profile`
- `refresh_conversation`
- `stage_reply`
- `paste_draft`
- `request_human_confirmation`
- `send_message`
- `like_profile`
- `open_match`

No external model or MCP host should receive a raw `click(x, y)` or `type(text)` tool. Raw GUI primitives stay inside the harness.

### Policy Engine

The policy engine authorizes every semantic action.

Default allowed:

- observe.
- summarize.
- draft reply.
- paste or stage a draft without sending.
- export or inspect local memory.

Default gated:

- send message.
- like or super-like.
- unmatch.
- report.
- edit profile.
- propose concrete meeting logistics.
- exchange contact information.

Autonomous mode is an explicit local switch. It can allow high-risk actions, but it must not bypass perception verification, audit logging, app adapter checks, or privacy controls.

### App Adapter Layer

The app adapter layer isolates app-specific details.

`GenericDatingAdapter` defines shared concepts:

- profile card.
- profile detail.
- match list.
- chat list.
- chat thread.
- input box.
- send button.
- match identity cues.
- modal and exceptional states.

`TinderAdapter` implements those concepts for Tinder through screenshots and semantic actions.

Future adapters can support Bumble, Hinge, Instagram DM, or other apps without rewriting memory or intelligence.

### Evaluation System

Evaluation is a first-class subsystem.

Eval categories:

- reply quality eval.
- memory correctness eval.
- profile analysis eval.
- perception eval.
- action verification eval.
- policy eval.
- privacy regression checks.

No major capability should ship without an offline eval path.

## Ideal Data Flow

### Draft Reply Flow

```text
observe screen
-> classify page and extract conversation
-> resolve match identity
-> refresh conversation memory
-> build context pack
-> generate structured draft options
-> run policy and safety checks
-> show drafts to user
-> stage selected draft
-> collect feedback event
```

### Profile Refresh Flow

```text
observe profile page
-> extract profile text and photo cues
-> resolve match identity
-> analyze profile into structured match profile
-> record provenance and confidence
-> update match memory
-> report conflicts or low-confidence identity
```

### High-Risk Action Flow

```text
semantic action requested
-> policy check
-> human confirmation or autonomous switch check
-> adapter precondition check
-> harness action
-> perception verification
-> audit log
-> memory update or failure report
```

High-risk actions fail closed. If verification fails, the system reports uncertainty and stops.

## Trust Boundaries

### Local Authority Boundary

Only the local daemon or in-process equivalent can execute app actions.

External agents, MCP hosts, model backends, and prompts can suggest semantic actions but cannot bypass policy.

### Data Boundary

Raw screenshots, raw profile photos, and full conversation dumps are not stored by default.

The default durable state is structured, local, and minimal:

- summaries.
- evidence snippets.
- confidence labels.
- provenance metadata.
- feedback events.

### Model Boundary

Model providers receive only the smallest context pack required for the task.

The system should support multiple model backends:

- OpenAI.
- Anthropic.
- local or open-weight models later.

Model-specific prompts are implementation details behind stable contracts.

### App Boundary

The product does not use private dating app APIs, reverse engineering, anti-detection, account farming, or rate-limit evasion.

It uses user-authorized local GUI operation and still clearly states that target apps may consider this a terms violation.

## Privacy and Retention

Mature product requirements:

1. Local data directory outside the repository checkout.
2. Export command for all local knowledge.
3. Delete command for one match.
4. Delete command for all archived matches.
5. Delete command for all local data.
6. No raw screenshot storage by default.
7. Opt-in raw vault only after explicit user setting.
8. Audit logs avoid full message dumps by default.
9. Redaction utilities for screenshot fixtures.
10. Clear display of what data is sent to model providers.

## Screenshot Fixture Dataset

The screenshot fixture dataset is important, but it belongs under the perception system, not the whole product plan.

It should support:

- page taxonomy.
- fixture image.
- JSON annotation.
- redaction status.
- expected elements.
- expected extraction output.
- confidence requirements.

The fixture path should use the same perception interface as live screenshots. That keeps offline eval reusable when live iPhone Mirroring arrives.

## Mature App Page Taxonomy

For Tinder, the adapter should eventually understand:

- app launch state.
- main card page.
- profile detail page.
- match list.
- chat list.
- chat thread.
- keyboard-open chat thread.
- draft-staged chat thread.
- new match modal.
- subscription or paywall modal.
- permission modal.
- network error state.
- loading state.
- empty state.
- settings or profile edit page.

MVP does not need every page, but its taxonomy must allow expansion.

## MVP Vertical Slice

The MVP should prove one reusable path through the mature architecture:

```text
local fixture or manual input
-> normalized observation
-> memory repository
-> context pack builder
-> reply generator
-> policy decision
-> staged output
-> feedback event
-> eval result
```

MVP should not require live iPhone Mirroring to prove intelligence quality. It should use fixtures and manual input first, then connect perception and live harness after contracts are stable.

### MVP Included

1. Local JSON storage behind repository interfaces.
2. User profile schema.
3. Match profile schema.
4. Conversation memory schema.
5. Memory provenance schema.
6. Match identity resolver for fixture/manual data.
7. Context pack builder.
8. Draft generation contract.
9. Self, Adaptive, and Recipient-Optimized modes.
10. Persona and stance divergence fields.
11. Feedback event storage.
12. CLI commands for fixture/manual workflows.
13. Offline eval fixtures and scoring.
14. Existing action policy gate.

### MVP Deferred

1. Live iPhone Mirroring harness.
2. Automatic screenshot capture.
3. Real GUI action execution.
4. MCP server.
5. Desktop UI.
6. Daily background refresh.
7. Multiple app adapters.
8. Encrypted raw vault.
9. Autonomous high-risk action execution.

Deferred does not mean incompatible. MVP interfaces must be shaped so these capabilities can be added without changing memory, intelligence, or policy contracts.

## MVP Reuse Rules

1. Do not write prompt-only code that bypasses schemas.
2. Do not store app-specific raw blobs as durable memory.
3. Do not expose raw GUI primitives as public tools.
4. Do not put model-provider logic inside business objects.
5. Do not make fixture-only APIs that cannot accept live observations.
6. Do not let eval fixtures become the only source of truth for production behavior.
7. Do not use mocks or fallbacks as the main product path.
8. Do keep every MVP command aligned with a future daemon API.

## Proposed Repository Shape

```text
dating_boost/
  policy.py
  cli.py
  core/
    models.py
    repositories.py
    context_pack.py
    feedback.py
  intelligence/
    profile_analyzer.py
    conversation_summarizer.py
    reply_generator.py
    prompts.py
  perception/
    observations.py
    taxonomy.py
    fixture_loader.py
  adapters/
    generic.py
    tinder.py
  evals/
    runner.py
    rubrics.py
tests/
  fixtures/
    intelligence/
    perception/
docs/
  superpowers/
    specs/
    plans/
```

This shape is illustrative. The implementation plan can adjust names, but the boundaries should remain.

## Ideal Roadmap

### Phase 1: Intelligence MVP

Build the reusable intelligence vertical slice with fixture/manual inputs.

Success criteria:

- memory schemas exist.
- context packs are deterministic and inspectable.
- reply generation outputs structured alternatives.
- evals compare memory-aware replies against generic baseline.
- policy gate remains in the loop.

### Phase 2: Offline Perception

Build screenshot fixture dataset and perception eval.

Success criteria:

- fixture annotations exist.
- page classifier works on core pages.
- extraction emits normalized observations.
- perception output feeds the same memory refresh path used by manual data.

### Phase 3: Live Harness

Connect iPhone Mirroring observation and safe staging.

Success criteria:

- live screenshots use the same perception interface.
- paste or stage draft works with post-action verification.
- send remains gated by policy.

### Phase 4: Local Operator

Add daemon, MCP adapter, and optional desktop/menu bar controls.

Success criteria:

- CLI and MCP call the same local API.
- user can inspect, export, and delete data.
- high-risk actions are auditable.

### Phase 5: Multi-App Expansion

Add more app adapters.

Success criteria:

- memory and intelligence layers remain app-agnostic.
- app adapters provide only observation normalization and semantic action execution.

## Open Design Questions

1. Whether the first model backend should be OpenAI-only or provider-abstracted from day one.
2. Whether local JSON storage is enough for Phase 1 or SQLite should be introduced immediately.
3. Whether user profile onboarding should be CLI-only at first or fixture-file based.
4. Whether screenshot fixtures should use synthetic UI, redacted real screenshots, or both.
5. Whether the initial eval scorer should be human rubric only, model-assisted, or hybrid.

## Non-Goals

- No private dating app API use.
- No anti-detection, ban evasion, or rate-limit evasion.
- No account farming or multi-account automation.
- No public claim that target apps permit automation.
- No fully autonomous MVP.
- No production GUI before the intelligence and perception contracts are stable.
