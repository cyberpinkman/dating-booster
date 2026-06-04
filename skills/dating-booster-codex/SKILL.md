---
name: dating-booster-codex
description: Codex-first workflow for using Dating Booster as local memory, context, policy, and audit tools for dating-app assistance.
---

# Dating Booster Codex Workflow

Use this skill when the user asks Codex to assist with dating-app workflows through Dating Booster local tools.

## Mandatory Startup Check

Before observing any dating app screen, screenshots, profile text, or conversation text, choose a local data directory for this workflow. Prefer `.local/dating-boost` unless the user gives another path. Then run this package's doctor:

```bash
python3 scripts/doctor.py --json --data-dir .local/dating-boost
```

If doctor returns `needs_bootstrap`, run:

```bash
python3 scripts/bootstrap_cli.py
```

Then run `python3 scripts/doctor.py --json --data-dir .local/dating-boost` again. Continue only when doctor returns `status: ok`.

Finally run:

```bash
dating-boost release doctor --json
dating-boost data doctor --data-dir .local/dating-boost --json
dating-boost capabilities --json --data-dir .local/dating-boost
```

If data doctor reports `needs_migration`, run:

```bash
dating-boost data migrate --data-dir .local/dating-boost --json
```

Load this package's `skill-package.json` and compare it with the capabilities JSON before continuing:

- `tool_version` must be greater than or equal to `dating_boost_min_version`.
- Every `required_schema_versions` entry must exist in `schema_versions` with the same version.
- Every `required_commands` entry must exist in `supported_commands`.
- `schema_version` for capabilities must be supported by this skill package.
- `storage_capabilities.storage_backend` should be `sqlite` before production smoke.
- `storage_capabilities.encrypted_default` must be true for public production.
- `storage_capabilities.backup_requires_recovery_passphrase` must be true for public backups.
- `agent_native_capabilities.ci_tested_version` should match the installed tool version.
- `agent_native_capabilities.local_daemon` should be true for public production workflows.
- `diagnostic_capabilities.local_redacted_bundle` should be true.
- `diagnostic_capabilities.support_log`, `encrypted_evidence_vault`, `topic_provenance`, and `clipboard_fingerprint` should be true for private-beta support.
- If `source_spec_commit` differs from the local repo commit, report a warning. Continue only if version, schema, and command checks pass.

If doctor, bootstrap, data doctor, migration, or capabilities fails; returns invalid JSON; has an incompatible `schema_version`; is too old; lacks a required schema version; or does not list the required commands, stop before observing dating app content and tell the user the local Dating Booster tool is incompatible.

After compatibility checks pass and the target app id is known, start a local support session before observing dating-app content:

```bash
dating-boost support session start --data-dir .local/dating-boost --host codex --app-id tinder --json
```

Keep the returned `session_id` for this run. Commands with `--data-dir` record redacted command boundaries; draft policy checks, GUI harness stage/send commands, and `dating-boost-host-loop` commands using the same `--data-dir` also record topic provenance, hashes, clipboard fingerprints, timeline events, and encrypted sensitive evidence. Before ending the workflow, stop the session:

```bash
dating-boost support session stop --data-dir .local/dating-boost --session-id <session_id> --json
```

Do not run `data migrate` or `data delete` on that same data dir between support session start and support bundle export.

## Privacy Boundary

In this mode, Codex is the host agent. The host agent may process visible dating app content, screenshots, profile text, conversation text, and generated drafts. Dating Booster stores local memory, context, policy decisions, feedback, and action audit records; it does not own the LLM in this workflow.

For user bug reports, export a strict support bundle by default:

```bash
dating-boost support bundle --data-dir .local/dating-boost --session-id <session_id> --output dating-boost-support.zip --redaction strict --json
```

Strict bundles must not contain raw draft text, raw conversation text, raw profile text, raw screenshots, or clipboard contents. They may contain hashes, character counts, topic labels, command names, schema versions, target ids, and action outcomes. Use `--redaction full-with-consent --include-sensitive ... --confirm export-sensitive:<session_id>` only when the user explicitly asks to export sensitive evidence; never use it as the default.

## Default Action Policy

Allowed by default:

- Observe visible screen content after the capability check and user intent are clear.
- Summarize profile or conversation context.
- Run `dating-boost workflow draft` after the host agent has authored an observation JSON and draft JSON.
- Run `dating-boost automation session` commands after the user has explicitly authorized a host-orchestrated automation session.
- Build context with `dating-boost context build` when debugging or using lower-level commands.
- Draft replies inside the host agent.
- Check drafts with `dating-boost policy check-draft`.
- Paste a draft only when the user requested it.

High-risk actions require explicit user confirmation and the local policy switch:

- Sending a message.
- Liking, super-liking, unmatching, reporting, or editing profile data.
- Proposing a meeting or exchanging contact details.

Do not treat autonomous mode as permission to bypass app rules, rate limits, verification, account restrictions, or user judgment.

For public production, treat the local safety switch as authoritative. If
`dating-boost safety status --data-dir .local/dating-boost --json` reports
paused, do not send, paste, stage, or continue a live host loop until the user
explicitly resumes it. Live sends require `--send-mode live`, authorization with
`live_send: true`, exact staged-text verification, and post-action verification.
For Tinder or macOS WeChat fully managed sending, also require
`--managed-gui-send` and the app-specific `harness <app> send-message
--text-file ...` path.

## Default Draft Output

Naturalness review is an internal QA step. Before showing any draft, silently apply
`references/naturalness-checklist.md` and revise the draft if needed.

By default, show only the final draft and at most a small number of alternatives.
Do not show checklist results, validation notes, or reasoning about why the draft
does or does not trigger specific checklist items. Show that material only when
the user explicitly asks for explanation, critique, review, or debug output.

## Goal-Oriented Planning

For autonomous or semi-autonomous sessions, this is a goal-oriented workflow.
Autonomous progression requires a user self model before any dating app content
is processed for managed sending. Run:

```bash
dating-boost user readiness --data-dir .local/dating-boost --mode autonomous --json
```

If it returns `needs_user_profile`, stop managed automation and ask the user to
provide/import their dating profile and self interview with
`dating-boost user ingest-profile` and `dating-boost user ingest-interview`.
Do not start `operator session`, `automation session`, or `dating-boost-host-loop run`
for autonomous sends until readiness passes. Readiness requires both sources
plus at least five low-risk shareable materials, at least two materials usable
for `low_investment_repair`, and at least one date/meeting preference material.

Before generating a draft for an opened thread, read
`references/planner-authoring.md` and author a `planner_assessment` that
describes conversation stage, scores, topic lifecycle, next milestone, and
whether a soft invite is allowed. Dating Booster stores this as a `goal_plan`
and returns a planner recommendation. Drafts should align with the planner move;
if they do not, stop instead of sending.

Use planner scores as strategy state, not as truth about the person. Low
confidence, stale turn boundaries, topic loops, appointment details, or contact
exchange must stop automatic sending for that match. Low-investment threads
must not be pushed by repeated questions: track question debt, self-disclosure
debt, reciprocity balance, and low-investment streak, then use
`low_investment_repair`, `light_self_disclosure`, `reciprocal_disclosure`, or
`slow_down_wait` when appropriate.

When a draft uses a self-disclosure move, set `disclosure_source` explicitly:
`user_material` with `used_user_material_ids` whenever possible, or
`simulated_soft` only when the user profile `simulation_policy` is
`free_simulation_soft`. If the policy is `material_only`, do not simulate. If it
is `user_confirmed_only`, stop for user confirmation. For low-investment repair,
set `question_count: 0` or `reply_shape: "statement"` unless there is a strong
reason to hand off.

## Workflow

1. Run `python3 scripts/doctor.py --json --data-dir .local/dating-boost`; bootstrap with `python3 scripts/bootstrap_cli.py` only if doctor says `needs_bootstrap`.
2. Run `dating-boost capabilities --json --data-dir .local/dating-boost` and verify compatibility against `skill-package.json`.
3. For managed/autonomous work, run `dating-boost user readiness --data-dir .local/dating-boost --mode autonomous --json`; stop if it returns `needs_user_profile`.
4. Convert visible screen content to an observation JSON using `references/observation-authoring.md`.
5. When working toward a long-term goal, author a `planner_assessment` and run `dating-boost planner update`.
6. Read `references/drafting-framework.md`, then generate the draft JSON in Codex using the visible profile/chat context and planner recommendation.
7. Before using the draft, silently apply `references/naturalness-checklist.md` and revise anything that reads like AI-written Chinese.
8. Run `dating-boost workflow draft --data-dir .local/dating-boost --observation observation.json --draft draft.json --mode adaptive`.
9. If the workflow returns `blocked`, do not show or paste the blocked draft.
10. If the workflow returns `ok`, show only the final draft or paste it when the user requested paste.
11. For any high-risk action, run `dating-boost policy check-action` and ask for explicit confirmation.
12. After the host executes an action, perform post-action verification from a fresh observation.
13. Record the result with `dating-boost action record-result`.
14. Record user feedback with `dating-boost feedback record` when useful.

## iPhone Mirroring Input

Before relying on iPhone Mirroring for real Tinder work, run:

```bash
dating-boost harness doctor --app-id tinder --json
dating-boost harness tinder launch --dry-run --json
dating-boost harness tinder open-profile --dry-run --json
dating-boost harness tinder open-profile --launch-if-needed --json
dating-boost harness tinder observe --output-dir .local/dating-boost-harness --json
dating-boost harness tinder action profile-photo-next --dry-run --json
dating-boost harness tinder workflow self-profile-read --dry-run --photo-steps 2 --scroll-steps 2 --json
dating-boost harness tinder workflow chat-read-match-profile --dry-run --conversation-row 1 --profile-scroll-steps 2 --json
dating-boost harness tinder workflow new-match-open --dry-run --carousel-swipes 1 --match-index 2 --json
dating-boost harness tinder workflow new-match-read-profile --dry-run --carousel-swipes 1 --match-index 2 --profile-scroll-steps 2 --json
dating-boost harness tinder action open-conversation --visible-name Iris --target-binding target-binding.json --json
dating-boost harness tinder action dismiss-subscription-paywall --json
dating-boost harness tinder action dismiss-feedback-survey --json
dating-boost harness tinder send-message --text-file tinder-draft.txt --dry-run --json
```

Use `dating-boost harness tinder open-profile --json` only for safe navigation
to the Tinder profile tab after doctor confirms the mirrored window is unlocked.
If Tinder is not already verified foreground, use `--launch-if-needed`; the
harness returns iPhone Mirroring to Home Screen and opens Tinder through
Spotlight before opening the profile tab. Use `harness tinder action` for one
bounded navigation step and `harness tinder workflow` for supported chains:
`self-profile-read`, `chat-read-match-profile`, `new-match-open`, and
`new-match-read-profile`. Use `chat-read-match-profile` only for existing
message-list rows. Use `new-match-open` or `new-match-read-profile` for
unopened matches in the top carousel; after a live-send opener, run
`harness tinder action return-to-chats` before selecting the next match. Use
`harness tinder observe` to get redacted page/layout hints before choosing a chain; it reports page
state and markers such as new-match carousel presence, conversation-list
presence, `等你回应`, and visible profile expand controls without returning raw
OCR text. The native harness may diagnose the mirrored window, capture
screenshots/OCR, launch Tinder, move through profile photo/read states, open
chats, open visible conversations, open unopened matches, open profile previews
from thread avatars, return from a thread to chats, and execute a fully managed
`send_message` only through
`harness tinder send-message --text-file ... --data-dir ... --authorization ...
--action-request ...`. Real Tinder sends require unexpired authorization with
`app_id: tinder`, `autonomous_send: true`, `live_send: true`, `send_message`
allowed, an unpaused safety switch, a policy-checked/hash-bound action request,
target-chat binding, staged-text OCR verification, outbound-bubble verification,
and a `post_action_observation_id`. It must not like, super-like, unmatch,
report, or edit profile data.

If observe, navigation, or send returns `tinder_subscription_paywall`,
`subscription_paywall_visible`, or `tinder_subscription_paywall_dismissed`, do
not ask the user to confirm a subscription and do not discuss plans. Immediately
run `dating-boost harness tinder action dismiss-subscription-paywall --json`,
then re-navigate to the verified chats/conversation path. Subscription purchase
or plan selection is never an agent action.

If observe, navigation, or post-send verification returns `tinder_feedback_survey`
or `feedback_survey_visible`, run
`dating-boost harness tinder action dismiss-feedback-survey --json`. This must
use the ignore/no-rating path; `rating_submitted` must remain false.

## macOS WeChat Input

For real macOS WeChat work, use the desktop WeChat harness instead of iPhone
Mirroring:

```bash
dating-boost harness doctor --app-id wechat --window-title WeChat --json
dating-boost harness wechat launch --dry-run --json
dating-boost harness wechat observe --output-dir .local/dating-boost-harness --json
dating-boost harness wechat stage-draft --text-file wechat-draft.txt --dry-run --json
dating-boost harness wechat send-message --text-file wechat-draft.txt --dry-run --json
```

Use `harness wechat observe` to get redacted page/layout hints before drafting
or staging. Use `harness wechat stage-draft` only to paste an already
policy-checked draft into the current WeChat input box. It copies the draft to
the macOS clipboard and sends `Cmd+V`; stage mode must not press Enter or click Send.
Prefer `--text-file` so private draft text is not written into shell history or
process arguments. Real WeChat staging must include `--data-dir` so the global
safety pause can block paste.

Use `harness wechat send-message --text-file ...` only when the user has
explicitly authorized fully managed macOS WeChat sending. Real execution must
include `--data-dir`, `--authorization`, and `--action-request`; the
authorization must be unexpired, match `app_id: wechat`, set
`autonomous_send: true`, set `live_send: true`, allow `send_message`, and
require post-action verification. The action request must be policy-checked,
hash-bound to the text file, and include target-chat binding evidence. The
harness must verify the target chat, exactly verify the focused input text
before pressing Return, then verify the outbound bubble from fresh post-action
evidence and return a `post_action_observation_id`. If target binding,
staged-text, outbound-bubble, or post-action verification is missing, do not
record `succeeded`.

When executing a `send_message` action through iPhone Mirroring, treat text
entry as unreliable until verified. For Chinese or long messages, prefer:

1. Use foreground app copy when possible: put the exact payload text in a
   normal Mac app, select it, and copy it with a real `Cmd+C`. Do not assume
   `pbcopy` alone will trigger Universal Clipboard.
2. Focus the iOS input box.
3. Try `Cmd+V` as a staging shortcut only after the input box is focused and
   positioned normally. If it stages the exact text, continue to verification.
4. If `Cmd+V` does not stage text, long-press or two-finger/right-click the iOS
   input box until the edit menu appears, then tap Paste.
5. Verify staged text in the input box before sending.
6. Do not send if the staged text is missing, truncated, garbled, or differs
   materially from the action request payload.

Do not rely on direct `type_text`, `Cmd+V`, or keyboard return as sufficient
evidence by itself. `Cmd+V` may be a valid staging shortcut, and Return may send
in some apps after staging, but success still requires staged-text and outbound
bubble verification from a fresh observation. If the sent text differs from the
requested payload, record `result_status` as `failed` or `unknown`, not
`succeeded`.

If the iPhone Mirroring input box shows position drift after full-screen input,
keyboard layout changes, or viewport changes, do not keep probing coordinates.
Back out and reopen the chat thread so the input box returns to its normal
location, then restart staging from a fresh observation.

## Goal-Oriented Operator Session

Use this mode when the user asks Codex to fully manage a bounded dating session
toward a goal such as meeting in person. Codex remains the host agent: it
observes the app screen, opens threads, authors observations, drafts ordinary
messages, and performs GUI actions. Dating Booster CLI is the local operator
state engine: it decides the next work item, tracks planner state, prevents
duplicates, gates risky actions, and writes reports.

1. Run the mandatory startup check.
2. Run `dating-boost user readiness --data-dir .local/dating-boost --mode autonomous --json`; if it is not ready, import the user's profile/interview before continuing.
3. Record goal and availability JSON with `dating-boost automation goal set` and `dating-boost automation availability set`.
4. Start with `dating-boost operator session start --data-dir .local/dating-boost --authorization auth.json`.
5. Call `dating-boost operator next --data-dir .local/dating-boost`.
6. If the work item is `scan_message_list`, observe the visible message list and call `dating-boost operator ingest-observation --data-dir .local/dating-boost --input list_observation.json`.
7. If the work item is `open_thread`, open that thread, author a thread observation, author `planner_assessment`, draft only if the planner move requires a reply, and call `dating-boost operator ingest-observation --data-dir .local/dating-boost --input thread_observation.json`.
8. If the work item is `send_message`, execute only ordinary `send_message` requests whose planner alignment is `ok`.
9. After each send, perform post-action verification and call `dating-boost operator record-action-result --data-dir .local/dating-boost --input action_result.json`.
10. If the work item is `handoff`, appointment details, contact exchange, or high-risk content, stop automation for that match and ask the user to take over.
11. Continue calling `operator next` until the user stops the session or the operator returns `wait`.
12. Stop with `dating-boost operator stop --data-dir .local/dating-boost` and show `dating-boost operator report latest --data-dir .local/dating-boost --format md`.
13. On a later run, use `dating-boost operator report latest` and local state to continue without relying on host-agent memory.

For each opened thread, read `references/planner-authoring.md` and author
`planner_assessment` before allowing autonomous send: include engagement,
warmth, curiosity, comfort, momentum, topic_saturation, logistics_readiness,
risk, recommended stage, recommended move, next milestone, avoid_next, and
soft_invite_allowed. Also include reciprocity state when possible: question
debt, self-disclosure debt, reciprocity balance, low-investment streak, match
curiosity about the user, and last user turn type. The naturalness checklist is
internal QA; do not show it by default.

## Tinder Host Loop

For real Tinder host-loop testing, prefer `dating-boost-host-loop` over
manually calling every operator command. Read `references/host-loop.md` first.

Preferred one-command path:

```bash
dating-boost support session start --data-dir .local/dating-boost --host codex --app-id tinder --json
dating-boost-host-loop doctor --data-dir .local/dating-boost --app-id tinder --json
dating-boost-host-loop init --data-dir .local/dating-boost --work-dir .local/dating-boost-host-loop --app-id tinder --json
dating-boost-host-loop run --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tinder --send-mode stage --work-dir .local/dating-boost-host-loop --json
dating-boost support session stop --data-dir .local/dating-boost --session-id <session_id> --json
dating-boost support bundle --data-dir .local/dating-boost --session-id <session_id> --output dating-boost-support.zip --redaction strict --json
```

Use `dating-boost-host-loop status` to inspect the current waiting state,
`dating-boost-host-loop resume` to continue after interruption, and
`dating-boost-host-loop confirm-staged` only after a stage-mode send has been
reviewed by the user.

Default to `--send-mode stage`: paste the draft into Tinder, verify the staged
text, and stop before clicking send. Use `--send-mode live` only after explicit
user authorization for ordinary automatic sends. Live mode still requires staged
text verification before send and post-action verification after send.

The host must write only the requested work-dir files named with the current
`work_item_id`: `message_list_observation.<work_item_id>.json`,
`thread_observation.<work_item_id>.json`,
`staged_verification.<work_item_id>.json`, or
`action_result.<work_item_id>.json`. Legacy examples may mention
`staged_verification.json` or `action_result.json`; for host loop recovery, use
the scoped names. Do not infer success from a requested action alone.

Every message-list/thread observation must pass:

```bash
dating-boost observation validate --input OBSERVATION.json --json
```

Then the supervisor ingests it. `latest_inbound_messages` must include only
messages after the user's latest outbound and must include turn boundary
evidence; old visible bubbles are background context.

After a run, use:

```bash
dating-boost replay latest --data-dir .local/dating-boost --format md
dating-boost eval run --suite conversation --json
```

## Host-Orchestrated Automation Session Fallback

Use this mode only after explicit user authorization. Codex remains the host
agent: it observes the dating app screen, opens message threads, authors
`scan_batch` JSON, and executes ordinary send requests. Dating Booster CLI is
the local state engine; it does not scan the screen or click the app.

1. Run the mandatory startup check.
2. Run `dating-boost user readiness --data-dir .local/dating-boost --mode autonomous --json`; stop if the user profile/interview is missing.
3. Record goal and availability JSON with `dating-boost automation goal set` and `dating-boost automation availability set`.
4. Start with `dating-boost automation session start --data-dir .local/dating-boost --authorization auth.json`.
5. Generate a scan skeleton with `dating-boost automation scan template --json` when useful.
6. Scan the visible message list and a bounded set of relevant threads. Prefer writing separate message-list and thread JSON files, then run `dating-boost automation scan assemble --message-list list.json --threads threads.json --session-id SESSION --captured-at TIME --json`.
7. For each opened thread, author `planner_assessment` before the draft: include engagement, warmth, curiosity, comfort, momentum, topic_saturation, logistics_readiness, risk, recommended stage, recommended move, next milestone, avoid_next, soft_invite_allowed, and reciprocity state.
8. Run `dating-boost automation scan validate --input scan_batch.json --json` before every session step.
9. Run `dating-boost automation session step --data-dir .local/dating-boost --scan-batch scan_batch.json`.
10. Execute only allowed ordinary `send_message` action requests whose planner alignment is `ok`.
11. After each send, perform post-action verification and call `dating-boost action record-result`.
12. Stop with `dating-boost automation session stop --data-dir .local/dating-boost` and show `dating-boost automation report latest --data-dir .local/dating-boost --format md`.
13. On a later run, use `dating-boost automation report latest` and local state to continue without relying on host-agent memory.

If the step output contains `handoffs`, appointment details, contact exchange,
or high-risk content, stop automation for that match and ask the user to take
over.

Use `references/workflows.md` for reusable workflow details and lower-level command fallbacks, `references/contracts.md` for JSON input/output contract examples, and the drafting/naturalness references for Chinese reply quality. This package is the Codex host agent adapter; future Claude Code, Hermes, OpenClaw, or MCP-oriented adapters should reuse the same CLI/capabilities/app-profile contracts instead of copying Codex-only assumptions. For cross-agent, cross-app, goal, workflow, and memory expansion rules, read `docs/ARCHITECTURE.md` in the source repository. These reference files are summaries; core code and committed specs remain the source of truth.

## Post-Action Verification

For sent messages or other high-risk actions, do not record success unless the post-action observation confirms the expected state. If the result cannot be verified, record `result_status` as `unknown`, not `succeeded`.

## Prohibited

- Private APIs, reverse engineering, or non-GUI service automation.
- Account farming, bulk swiping, scraping member-only data, or evading bans/checks.
- Claiming an action succeeded without post-action verification.
- Leaking a draft that `dating-boost policy check-draft` blocks.
