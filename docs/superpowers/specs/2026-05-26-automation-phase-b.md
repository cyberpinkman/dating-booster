# Dating Booster Automation Phase B

Status: accepted draft
Date: 2026-05-26

## Purpose

Automation Phase B adds the first autonomous layer on top of the agent-native
Dating Booster workflow. After explicit user authorization, the system should be
able to notice incoming messages, verify the relevant thread, decide whether a
reply or later nudge is appropriate, draft through the host agent, run local
policy checks, and advance conversations toward a user-configured goal such as
meeting in person.

This phase must not jump directly to a live GUI bot. The first implementation
should build a reusable automation orchestrator, state machine, schemas, audit
events, and dry-run fixtures. Live iPhone Mirroring harness work can attach to
the same contracts later.

## Core Decision

Phase B is an automation decision layer, not a new model loop.

The host agent remains responsible for visual understanding, language
generation, and final GUI operation in agent-native mode. Dating Booster owns
the local state, goal configuration, policy gates, audit records, and workflow
contracts that prevent the host agent from becoming an unbounded send loop.

The default implementation path is:

```text
externally scheduled run-once
-> inbox snapshot
-> candidate unread detection
-> verified chat-thread observation
-> opportunity assessment
-> per-match state transition
-> draft workflow
-> policy check
-> dry-run output or authorized send request
-> post-action verification
-> audit and feedback
```

## Scope

Included in Phase B:

- a run-once automation loop that can be called by an external timer every two
  minutes.
- an inbox snapshot contract for visible message-list state.
- a verified chat-thread observation requirement before reply generation.
- per-match automation state.
- one-shot proactive nudge scheduling.
- a host-agent opportunity assessment contract.
- user-defined goal configuration, starting with `meet_in_person`.
- user availability and rough area preferences for meeting-oriented goals.
- dry-run output by default.
- explicit authorization for autonomous ordinary chat sends.
- mandatory handoff when the conversation enters appointment details.
- audit events for every automation decision and host-executed action.

Not included in Phase B:

- live iPhone Mirroring harness implementation.
- background daemon implementation.
- an in-repo scheduler, resident process, or hidden background worker.
- MCP implementation.
- bypassing app rate limits, platform controls, bans, verification, or account
  restrictions.
- private APIs, reverse engineering, or direct service automation.
- automatic like, super-like, unmatch, report, profile edit, contact exchange,
  or final appointment commitment.

## Product Requirements

### Scheduling Ownership

Phase B implements `automation run-once`, not a resident scheduler.

The scheduler is outside Dating Booster in this phase. It may be a host-agent
workflow, a user-run shell loop, a Codex heartbeat, launchd, cron, or a future
daemon. The repository should provide deterministic run-once behavior and may
document example scheduler wiring, but it must not require a long-running
process for tests.

Rules:

1. Every run must be safe to call repeatedly.
2. Every run must acquire a local automation lock before processing.
3. If another run is active, the new run must return `blocked` or `dry_run`
   with a lock warning rather than processing the same match concurrently.
4. Lock records must include `run_id`, `started_at`, `expires_at`, and
   `owner`.
5. If a lock is expired, a later run may take it over and must write an audit
   warning.

### Incoming Message Handling

The system should support a scheduled loop, normally every two minutes.

The loop must not treat an inbox preview as complete context. It may use the
message list only to discover candidates. Before drafting or sending, the host
agent must open or otherwise observe the specific chat thread and produce a
fresh `AppObservation` for that thread.

Rules:

1. No thread observation, no reply.
2. Low-confidence match identity may create a draft only in dry-run mode.
3. Autonomous send requires a high-confidence target match and latest-message
   verification.
4. If the thread changed between draft and send, the draft must be rebuilt or
   rechecked.
5. A fresh observation id is not enough to prove a new message. The automation
   layer must compare the latest inbound message fingerprint before resetting
   nudge or reply state.

First-version candidate handling:

1. A single `automation run-once` execution processes at most one selected
   candidate.
2. If the inbox snapshot contains multiple unread candidates, the run selects
   the first eligible entry by visible order unless `--candidate-key` is
   provided.
3. Remaining candidates are reported in `scheduled_actions` or `warnings` for
   later runs.
4. Multi-match batch processing belongs to the daemon phase.

### Idempotency And Duplicate Prevention

Automation must be idempotent at run, draft, and action boundaries.

Required identifiers:

- `run_id`: unique id for this run.
- `idempotency_key`: stable key supplied by the scheduler or derived from
  `snapshot_id`, `candidate_key`, and latest inbound fingerprint.
- `action_request_id`: stable id for a semantic action request.
- `latest_inbound_fingerprint`: stable fingerprint of the latest visible
  inbound message.
- `last_outbound_payload_hash`: hash of the latest outbound payload.

Rules:

1. The same `idempotency_key` must not create multiple send requests.
2. The same `action_request_id` must not be executed twice.
3. A match may have at most one pending action for the same
   `latest_inbound_fingerprint`.
4. Re-running after a crash should return the prior decision when possible or
   move the match to `thread_verification_needed`, not send blindly.
5. Action success must be based on post-action verification, not on the click or
   keyboard event returning successfully.

### Proactive Follow-Up

If the latest meaningful outbound message has not received a reply, and the
host agent judges the conversation still has continuation opportunity, the
system may schedule one proactive nudge after roughly 30 minutes.

Rules:

1. Only one nudge is allowed after a match's latest inbound message.
2. If the match still does not reply after the nudge, the match enters
   `waiting_for_match`.
3. The nudge allowance resets only when the match sends a new message.
4. If the host agent marks the thread as `temporarily_closed`, `closed`, or
   `unknown` with low confidence, no nudge is sent.
5. The nudge delay should support jitter later, but the first local state
   contract can store a deterministic `not_before` timestamp.
6. The one-shot nudge key is `latest_inbound_fingerprint`, not observation id.

This should not be implemented as a hard phrase detector. The host agent must
read the visible context and return a structured assessment.

### Goal-Oriented Conversation

The first supported automation goal is `meet_in_person`.

The goal is not to fully book a date without the user. The goal is to move the
conversation from open chat to a state where meeting is plausible, then hand off
when details become concrete.

The agent may:

- build rapport.
- ask low-pressure questions.
- test interest in meeting.
- mention broad availability or rough area only if the user configured it.
- suggest a meeting category, such as coffee, meal, exhibition, walk, or drink,
  if consistent with the user's configured preferences and current context.

The agent must hand off when:

- the match agrees to meet.
- the match asks for a specific day, time, venue, or route.
- the agent would need to choose among user availability slots.
- the agent would need to make a concrete commitment.
- the conversation moves to contact exchange.
- the host agent is unsure whether the suggestion is acceptable.

Communication boundary:

- Allowed without handoff: broad wording such as `我这周末应该有空，可以找个近点的地方喝杯咖啡`.
- Allowed without handoff: rough area wording such as `朝阳/海淀我都还算方便`.
- Requires handoff: exact day, exact time, exact venue, exact route, exact
  address, reservation, ticket purchase, or travel commitment.
- Requires handoff: any statement that would contradict the user's configured
  availability, boundaries, or already-sent commitments.
- Requires handoff: contact exchange or moving the conversation to another app.

## Authorization Model

Automation must be scoped, explicit, and revocable.

Authorization fields:

- `authorization_id`: local stable id.
- `scope`: allowed automation scope.
- `app_id`: app being operated, such as `tinder`.
- `data_dir`: local data directory.
- `expires_at`: time when the authorization stops applying.
- `allowed_match_ids`: optional match allowlist.
- `allowed_actions`: allowed semantic actions.
- `autonomous_send`: whether ordinary chat messages may be sent.
- `autonomous_nudge`: whether one-shot follow-ups may be sent.
- `goal_ids`: goals that may be pursued.
- `quiet_hours`: optional local times when the loop should not send.
- `requires_post_action_verification`: must be true for send-capable modes.
- `created_at`: timestamp.
- `revoked_at`: timestamp or null.

Recommended scopes:

- `observe_only`: can inspect and summarize.
- `draft_only`: can generate and policy-check drafts, cannot paste or send.
- `stage_only`: can paste/stage drafts, cannot send.
- `send_chat_messages`: can send ordinary chat messages after policy and state
  checks.

Even in `send_chat_messages`, high-risk actions remain blocked unless the user
confirms them at the moment of action.

Revocation rules:

1. The user must be able to pause all automation immediately.
2. A revoked authorization must stop future send requests even if a prior run
   scheduled a nudge.
3. Expired or revoked authorization may still allow dry-run summaries if the
   user requested them, but must not allow host-executed sends.

## State Machine

Each match has independent automation state.

States:

- `idle`: no current work.
- `unread_detected`: inbox snapshot suggests a new message.
- `thread_verification_needed`: a specific chat thread must be observed before
  taking action.
- `needs_reply`: the verified thread contains a reply opportunity.
- `draft_ready`: an allowed draft exists.
- `send_pending`: the host agent is allowed to send but has not verified the
  action yet.
- `sent_waiting`: an outbound message was sent and the system is waiting.
- `nudge_scheduled`: one follow-up is scheduled.
- `waiting_for_match`: no more proactive sends until the match replies.
- `appointment_handoff`: the conversation reached concrete appointment details
  and needs the user.
- `paused`: user or policy paused automation for this match.
- `closed`: host agent judged that the match should not be pursued.

Allowed transitions:

```text
idle -> unread_detected
unread_detected -> thread_verification_needed
thread_verification_needed -> needs_reply
thread_verification_needed -> idle
needs_reply -> draft_ready
draft_ready -> send_pending
draft_ready -> idle
send_pending -> sent_waiting
send_pending -> draft_ready
sent_waiting -> nudge_scheduled
sent_waiting -> waiting_for_match
nudge_scheduled -> send_pending
nudge_scheduled -> waiting_for_match
waiting_for_match -> unread_detected
needs_reply -> appointment_handoff
draft_ready -> appointment_handoff
sent_waiting -> appointment_handoff
any non-terminal state -> paused
paused -> idle
any non-terminal state -> closed
```

Forbidden transitions:

- `waiting_for_match -> nudge_scheduled` without a new inbound match message.
- `closed -> needs_reply` without explicit user reactivation.
- `appointment_handoff -> send_pending` without user confirmation.
- `thread_verification_needed -> draft_ready` without a chat-thread observation.

## Host-Agent Opportunity Assessment

The host agent must produce a structured assessment after reading the verified
chat thread.

Fields:

- `schema_version`: integer, starts at 1.
- `match_id`: local match id.
- `latest_match_message`: latest visible inbound message, if any.
- `latest_user_message`: latest visible outbound message, if any.
- `latest_inbound_fingerprint`: stable fingerprint for the latest visible
  inbound message, if any.
- `reply_window_status`: `open`, `temporarily_closed`, `closed`, or `unknown`.
- `continuation_opportunity`: `yes`, `no`, or `unknown`.
- `appointment_stage`: `none`, `invite_probe`, `interest_confirmed`,
  `details_requested`, `scheduled`, or `unknown`.
- `recommended_next`: `reply`, `nudge_later`, `wait`, `handoff`, or `stop`.
- `confidence`: `high`, `medium`, or `low`.
- `evidence`: short visible-message evidence.
- `risk_flags`: short stable flags.

Example:

```json
{
  "schema_version": 1,
  "match_id": "match_123",
  "latest_match_message": "你定",
  "latest_user_message": "你猜猜会有什么奖励",
  "latest_inbound_fingerprint": "match_123:2026-05-26:sha256:...",
  "reply_window_status": "open",
  "continuation_opportunity": "yes",
  "appointment_stage": "none",
  "recommended_next": "reply",
  "confidence": "high",
  "evidence": "The match delegated the choice back to the user.",
  "risk_flags": []
}
```

### Assessment Priority Mapping

When host-agent assessment fields conflict, deterministic state mapping wins.

Priority order:

1. If `appointment_stage` is `details_requested` or `scheduled`, transition to
   `appointment_handoff`.
2. If `recommended_next` is `handoff`, transition to `appointment_handoff`.
3. If `reply_window_status` is `closed` or `recommended_next` is `stop`,
   transition to `closed`.
4. If `reply_window_status` is `temporarily_closed`, do not nudge; transition
   to `sent_waiting` when there is a recent outbound message, otherwise `idle`.
5. If `confidence` is `low`, allow dry-run draft metadata only; do not create
   an authorized send request.
6. If `recommended_next` is `reply` and `continuation_opportunity` is `yes`,
   transition to `needs_reply`.
7. If `recommended_next` is `nudge_later`,
   `continuation_opportunity` is `yes`, and nudge allowance remains,
   transition to `nudge_scheduled`.
8. If `recommended_next` is `wait`, transition to `sent_waiting` or `idle`
   based on whether the latest visible message is outbound.
9. Otherwise transition to `thread_verification_needed` or `idle` with an
   uncertainty warning.

## Data Contracts

### Inbox Snapshot

`InboxSnapshot` records only what is visible in the match or message list.

Fields:

- `schema_version`: integer, starts at 1.
- `snapshot_id`: local stable id.
- `app_id`: app id.
- `captured_at`: timestamp.
- `entries`: list of visible inbox entries.
- `page_confidence`: `high`, `medium`, or `low`.
- `provenance`: evidence and redaction status.

`InboxEntry` fields:

- `candidate_key`: stable key derived from visible row evidence for this
  snapshot.
- `visible_name`: displayed name when visible.
- `match_identity_hints`: visible cues used for identity resolution.
- `latest_preview`: latest visible preview text, if any.
- `latest_preview_hash`: hash of preview text when present.
- `timestamp_cue`: visible timestamp text, if any.
- `unread_cue`: `present`, `absent`, or `unknown`.
- `position`: optional row index or bounding box hint.
- `evidence`: short visible evidence.

The preview is never treated as a complete message.

### Match Automation State

Fields:

- `schema_version`: integer, starts at 1.
- `match_id`: local match id.
- `state`: state-machine value.
- `goal_id`: active goal, if any.
- `last_inbound_observation_id`: latest match message observation.
- `latest_inbound_fingerprint`: stable fingerprint of the latest visible
  inbound message.
- `latest_inbound_text_hash`: hash of the latest visible inbound text.
- `latest_inbound_timestamp_cue`: visible timestamp cue for the latest inbound
  message.
- `last_nudged_inbound_fingerprint`: inbound fingerprint that already received
  a proactive nudge, or null.
- `last_outbound_action_id`: latest sent-message action id.
- `last_outbound_payload_hash`: hash of the latest outbound payload.
- `last_draft_id`: latest generated draft id.
- `nudge_count_since_inbound`: integer.
- `nudge_not_before`: timestamp or null.
- `last_assessment`: latest opportunity assessment summary.
- `paused_reason`: optional reason.
- `updated_at`: timestamp.

### Goal Config

`AutomationGoal` fields:

- `goal_id`: local stable id.
- `kind`: starts with `meet_in_person`.
- `status`: `active`, `paused`, or `archived`.
- `match_scope`: `all`, `allowlist`, or `single_match`.
- `allowed_match_ids`: optional allowlist.
- `tone_preferences`: short user preference notes.
- `meeting_preferences`: meeting category preferences.
- `handoff_triggers`: trigger list.
- `created_at`: timestamp.
- `updated_at`: timestamp.

`UserAvailability` fields:

- `availability_id`: local stable id.
- `date`: local date or date range.
- `time_window`: rough time range.
- `area`: rough area, not exact address.
- `constraints`: user-provided constraints.
- `confidence`: `user_confirmed` or `tentative`.
- `expires_at`: timestamp.

### Automation Run Result

Every run-once execution returns structured JSON.

Fields:

- `schema_version`: integer, starts at 1.
- `run_id`: local stable id.
- `idempotency_key`: run-level duplicate-prevention key.
- `status`: `ok`, `dry_run`, `blocked`, `handoff`, or `error`.
- `started_at`: timestamp.
- `finished_at`: timestamp.
- `data_dir`: local data directory.
- `lock`: lock acquisition result and owner metadata.
- `inbox_snapshot_id`: snapshot id, if available.
- `processed_matches`: list of per-match results.
- `scheduled_actions`: list of nudge or handoff reminders.
- `audit_path`: local audit path.
- `warnings`: compatibility or risk warnings.

Per-match result fields:

- `match_id`.
- `candidate_key`.
- `previous_state`.
- `next_state`.
- `latest_inbound_fingerprint`.
- `assessment`.
- `draft`: allowed draft metadata only, not blocked draft text.
- `policy`.
- `action_request`: semantic action request, if any.
- `handoff_reason`: reason if user must take over.

## CLI Surface

The first implementation should prefer explicit run-once commands over a
long-running background process.

Candidate commands:

```text
dating-boost automation run-once
dating-boost automation get-state
dating-boost automation update-state
dating-boost automation record-authorization
dating-boost automation revoke-authorization
dating-boost automation pause
dating-boost automation resume
dating-boost automation list-due
dating-boost automation record-assessment
```

`automation run-once` should support:

- `--data-dir`.
- `--inbox-snapshot`.
- `--chat-observation`.
- `--authorization`.
- `--mode dry-run|authorized`.
- `--now` for deterministic tests.
- `--candidate-key` to process a specific inbox entry.
- `--idempotency-key` to make scheduler retries safe.

Dry-run mode must be the default.

First-version processing rule:

- A single `automation run-once` call processes at most one candidate.
- If no `--candidate-key` is provided, the first eligible unread candidate is
  selected.
- If a selected candidate lacks a verified chat observation, the run returns
  `thread_verification_needed` and does not draft.

## Capabilities Compatibility

Phase B must extend the machine-readable capabilities contract before host
skills depend on automation.

Required `schema_versions` additions:

- `inbox_snapshot`: 1.
- `automation_authorization`: 1.
- `automation_state`: 1.
- `automation_assessment`: 1.
- `automation_run`: 1.

Required `supported_commands` additions:

- `automation run-once`.
- `automation get-state`.
- `automation update-state`.
- `automation record-authorization`.
- `automation revoke-authorization`.
- `automation pause`.
- `automation resume`.
- `automation list-due`.
- `automation record-assessment`.

Required `agent_native_capabilities` additions:

- `automation_run_once`: true.
- `automation_dry_run_default`: true.
- `automation_external_scheduler`: true.
- `automation_live_gui_harness`: false.

## Policy Rules

Automation must compose existing draft and action policy. It must not create a
parallel policy system.

Additional automation policy:

1. No autonomous send without active authorization.
2. No autonomous send without a verified chat-thread observation.
3. No autonomous send when match identity confidence is low.
4. No second proactive nudge before a new inbound message.
5. No autonomous final appointment commitment.
6. No autonomous contact exchange.
7. No autonomous reply when the host assessment says `closed`,
   `temporarily_closed`, or low-confidence `unknown`.
8. No blocked draft text in run results or logs.
9. No fabricated user facts, availability, intent, or prior experience.
10. No action success record without post-action verification.
11. No processing while another unexpired automation lock is active.
12. No duplicate send request for the same `idempotency_key`,
    `action_request_id`, or `latest_inbound_fingerprint`.

## Audit

Every automation run should append an event to a local JSONL audit file.

Recommended path:

```text
audit/automation_runs.jsonl
```

Audit events should include:

- run id.
- idempotency key.
- lock acquisition result.
- authorization id, if any.
- input snapshot and observation ids.
- state transitions.
- host-agent assessment summary.
- policy result.
- action request summary.
- post-action verification result.
- handoff reason.
- warnings.

Audit logs must omit blocked draft text.

## Evals And Fixtures

Phase B should add fixture-based regression cases before live GUI operation.

Required cases:

1. Inbox snapshot shows unread; verified thread is open; run produces a draft.
2. Inbox snapshot shows unread; thread verification finds no new message; run
   returns to `idle`.
3. Match says they are sleeping or busy; host assessment says
   `temporarily_closed`; no nudge is scheduled.
4. Match has not replied for 30 minutes; host assessment says open; one nudge is
   scheduled.
5. After one nudge, no reply; state becomes `waiting_for_match`.
6. A new inbound message after waiting resets nudge allowance.
7. Match asks for concrete date, time, or place; state becomes
   `appointment_handoff`.
8. Meeting goal is active but no availability is configured; agent may build
   rapport but must not propose a concrete slot.
9. Draft policy blocks a generated draft; run result hides blocked draft text.
10. Authorization expired; run returns dry-run or blocked output.
11. A second scheduler call starts while a lock is active; run returns blocked
    or dry-run without processing.
12. A repeated `idempotency_key` does not create a second send request.
13. A new observation with the same latest inbound fingerprint does not reset
    nudge allowance.
14. Multiple unread inbox entries are present; run processes only one selected
    candidate and reports the rest for later runs.
15. The match asks for an exact time or venue; broad meeting automation stops
    at `appointment_handoff`.

## Success Criteria

Phase B is complete when:

1. Automation state can be created, read, updated, and tested without a live app.
2. `automation run-once` can process fixture inbox and chat observations.
3. The run result explains what the system would do in dry-run mode.
4. Authorized mode can produce semantic send requests only when policy and state
   allow it.
5. One-shot nudge behavior is enforced by state, not prompts alone.
6. Meeting-oriented conversations hand off before concrete appointment details.
7. Audit events are written for decisions and post-action results.
8. The existing agent-native draft workflow remains the drafting path.
9. No live iPhone Mirroring harness is required for the tests.
10. Repeated scheduler calls are safe because locks and idempotency keys prevent
    duplicate sends.
11. Host skills can discover automation support through `capabilities --json`.

## Relationship To Existing Specs

This spec extends:

- `2026-05-25-agent-native-launch-strategy.md`: host agent still owns LLM and
  computer use in agent-native mode.
- `2026-05-25-product-architecture-blueprint.md`: automation state and audit
  should fit the later `dating-boostd` daemon boundary.
- `2026-05-25-intelligence-layer-design.md`: reply quality, memory, persona,
  stance, hard-fact constraints, and naturalness rules still apply.

It does not replace the existing draft workflow. Automation must call or reuse
the current draft workflow rather than duplicating reply generation, context
construction, or policy logic.
