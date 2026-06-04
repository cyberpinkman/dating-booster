---
name: dating-booster
description: Use Dating Booster from OpenClaw-compatible host agents for local-first dating workflow memory, policy, drafts, GUI harnesses, host-loop operation, and audited managed sends.
---

# Dating Booster For OpenClaw-Compatible Hosts

Use this skill when an OpenClaw-compatible host agent asks for help with Dating
Booster dating-app workflows. The host agent reads visible app context, writes
observations and drafts, and calls the Dating Booster CLI for local memory,
policy, planner, harness, audit, diagnostics, and recovery.

Hermes is supported through this OpenClaw-compatible skill contract. Use
`dating-boost adapter hermes doctor` when the running host is Hermes. Do not
claim a separate Hermes-native adapter unless a Hermes-specific package exists.

## Mandatory Startup

Before observing any visible dating app content, screenshots, profile text,
conversation text, or generated drafts, choose a local data directory. Prefer
`.local/dating-boost` unless the user gives another path.

Run for OpenClaw:

```bash
dating-boost adapter openclaw doctor --data-dir .local/dating-boost --json
dating-boost release doctor --json
dating-boost data doctor --data-dir .local/dating-boost --json
dating-boost capabilities --json --data-dir .local/dating-boost
```

Run for Hermes:

```bash
dating-boost adapter hermes doctor --data-dir .local/dating-boost --json
dating-boost release doctor --json
dating-boost data doctor --data-dir .local/dating-boost --json
dating-boost capabilities --json --data-dir .local/dating-boost
```

If data doctor returns `needs_migration`, run:

```bash
dating-boost data migrate --data-dir .local/dating-boost --json
```

Stop before app observation if adapter doctor, release doctor, data doctor,
migration, or capabilities fails; if required schemas or commands are missing;
or if `agent_native_capabilities.openclaw_adapter` is not true. In Hermes mode,
also require `agent_native_capabilities.hermes_openclaw_compatible_adapter`.

After startup checks pass and the target app id is known, start a local support
session before observing dating-app content:

```bash
dating-boost support session start --data-dir .local/dating-boost --host openclaw --app-id tinder --json
```

Use `--host hermes` when the running host is Hermes. Keep the returned
`session_id`. Commands with `--data-dir` record redacted command boundaries;
draft policy checks, GUI harness stage/send commands, and
`dating-boost-host-loop` commands using the same `--data-dir` also record topic
provenance, hashes, clipboard fingerprints, timeline events, and encrypted
sensitive evidence.
Stop the session before ending the workflow:

```bash
dating-boost support session stop --data-dir .local/dating-boost --session-id <session_id> --json
```

## Shared Contracts

Read and follow `references/contracts.md` and `references/workflows.md` from
this installed skill directory. They are host-neutral. Do not copy
Codex-specific assumptions into this workflow, and do not fork memory, policy,
planner, app-profile, or harness business logic in the host agent.

## Privacy Boundary

The host agent may process visible dating app content only for the active task
after startup checks pass. Raw screenshots and OCR text should stay local.
Normal diagnostics should use redacted counts, hashes, layout hints, schema
versions, and machine reports rather than private message text.

Dating Booster stores local memory, context, policy decisions, feedback, and
host-executed action audit records. It does not own the LLM call in this
workflow.

For user bug reports, export a strict support bundle by default:

```bash
dating-boost support bundle --data-dir .local/dating-boost --session-id <session_id> --output dating-boost-support.zip --redaction strict --json
```

Strict bundles must not contain raw draft text, raw conversation text, raw
profile text, raw screenshots, or clipboard contents. They may contain hashes,
character counts, topic labels, command names, schema versions, target ids, and
action outcomes. Use `--redaction full-with-consent --include-sensitive ...
--confirm export-sensitive:<session_id>` only when the user explicitly asks to
export sensitive evidence; never use it as the default.

## Core Workflow

1. Run `dating-boost capabilities --json --data-dir .local/dating-boost`.
2. Confirm the app id is listed in `supported_app_profiles`.
3. For autonomous or managed work, run `dating-boost user readiness --data-dir .local/dating-boost --mode autonomous --json`; stop if it returns `needs_user_profile`.
4. Convert visible screen content into an observation JSON with `dating-boost observation template`, `dating-boost observation validate`, and `dating-boost observation normalize`.
5. Build context with `dating-boost context build` or run `dating-boost workflow draft` after the host agent authors the observation and draft JSON.
6. Check every draft through `dating-boost policy check-draft`.
7. Check high-risk actions through `dating-boost policy check-action`.
8. After any host action, verify from fresh screen evidence and record the result with `dating-boost action record-result`.

## User Model And Planning

For fully managed or autonomous sessions, collect both dating profile and self
interview data:

```bash
dating-boost user interview template --json
dating-boost user ingest-profile --data-dir .local/dating-boost --input user_dating_profile.json
dating-boost user ingest-interview --data-dir .local/dating-boost --input self_interview.json
dating-boost user readiness --data-dir .local/dating-boost --mode autonomous --json
```

For goal-oriented work, author a planner assessment and use:

```bash
dating-boost planner update --data-dir .local/dating-boost --match-id <match_id> --goal-id <goal_id> --observation observation.json --assessment assessment.json --json
dating-boost planner recommend --data-dir .local/dating-boost --match-id <match_id> --json
```

Low confidence, stale context, topic loops, appointment details, contact
exchange, or unclear user preference should stop automatic sending for that
match.

## Tinder iPhone Mirroring Harness

Use the Tinder harness for iPhone Mirroring work:

```bash
dating-boost harness doctor --app-id tinder --json
dating-boost harness tinder launch --dry-run --json
dating-boost harness tinder open-profile --dry-run --json
dating-boost harness tinder observe --output-dir .local/dating-boost-harness --json
dating-boost harness tinder workflow self-profile-read --dry-run --photo-steps 2 --scroll-steps 2 --json
dating-boost harness tinder workflow chat-read-match-profile --dry-run --conversation-row 1 --profile-scroll-steps 2 --json
dating-boost harness tinder workflow new-match-open --dry-run --carousel-swipes 1 --match-index 2 --json
dating-boost harness tinder workflow new-match-read-profile --dry-run --carousel-swipes 1 --match-index 2 --profile-scroll-steps 2 --json
dating-boost harness tinder action open-conversation --visible-name Iris --target-binding target-binding.json --json
dating-boost harness tinder action dismiss-subscription-paywall --json
dating-boost harness tinder action dismiss-feedback-survey --json
dating-boost harness tinder send-message --text-file tinder-draft.txt --dry-run --json
```

Use `new-match-open` for an unopened match when the agent should enter one
conversation, write an opener from visible profile context, and then return to
chats for the next candidate. Use `chat-read-match-profile` for existing
conversation rows.
For existing conversations, prefer `open-conversation --visible-name ...` or
`--target-binding target-binding.json`; row coordinates are compatibility
fallbacks only.

If `harness tinder observe` or any send/navigation result reports
`tinder_subscription_paywall`, `subscription_paywall_visible`, or
`tinder_subscription_paywall_dismissed`, do not ask the user to confirm a
subscription and do not discuss plans. Immediately run
`dating-boost harness tinder action dismiss-subscription-paywall --json`, then
re-navigate to the verified chats/conversation path. Subscription purchase or
plan selection is never an agent action.

If a Tinder feedback survey appears, run
`dating-boost harness tinder action dismiss-feedback-survey --json`. This must
use the ignore/no-rating path and report `rating_submitted: false`.

## macOS WeChat Harness

Use the desktop WeChat harness for macOS WeChat:

```bash
dating-boost harness doctor --app-id wechat --window-title WeChat --json
dating-boost harness wechat launch --dry-run --json
dating-boost harness wechat observe --output-dir .local/dating-boost-harness --json
dating-boost harness wechat stage-draft --text-file wechat-draft.txt --dry-run --json
dating-boost harness wechat send-message --text-file wechat-draft.txt --dry-run --json
```

Prefer `--text-file` so private draft text does not enter shell history or
process arguments.

## Managed Live-Send

Managed live-send is allowed only for ordinary chat messages and only after
explicit authorization. It is never a bypass for app rules, rate limits,
verification, account restrictions, or user judgment.

Before any live send, require all of these:

- explicit authorization with `live_send: true`
- unpaused safety switch
- policy-checked action request
- target binding
- verified conversation page
- exact staged text verification
- post-action verification

For Tinder and WeChat, managed live-send must use:

```bash
dating-boost harness tinder send-message --text-file tinder-draft.txt --data-dir .local/dating-boost --authorization auth.json --action-request action_request.json --json
dating-boost harness wechat send-message --text-file wechat-draft.txt --data-dir .local/dating-boost --authorization auth.json --action-request action_request.json --json
```

If page identity, target binding, staged text, or post-send evidence is
missing, block or return `needs_verification`. Do not manually click Send
around the gate.

## Host Loop

Use the host loop when the host agent should act as the executor for queued
work items:

```bash
dating-boost support session start --data-dir .local/dating-boost --host openclaw --app-id tinder --json
dating-boost-host-loop doctor --adapter-package agent_adapters/openclaw/adapter-package.json --data-dir .local/dating-boost --app-id tinder --json
dating-boost-host-loop init --adapter-package agent_adapters/openclaw/adapter-package.json --data-dir .local/dating-boost --work-dir .local/dating-boost-host-loop --app-id tinder --json
dating-boost-host-loop run --adapter-package agent_adapters/openclaw/adapter-package.json --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tinder --send-mode stage --work-dir .local/dating-boost-host-loop --json
dating-boost support session stop --data-dir .local/dating-boost --session-id <session_id> --json
dating-boost support bundle --data-dir .local/dating-boost --session-id <session_id> --output dating-boost-support.zip --redaction strict --json
```

For fully managed sends, add `--send-mode live --managed-gui-send` only when
the authorization and action request are valid.
