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
dating-boost capabilities --json --data-dir .local/dating-boost
```

Load this package's `skill-package.json` and compare it with the capabilities JSON before continuing:

- `tool_version` must be greater than or equal to `dating_boost_min_version`.
- Every `required_schema_versions` entry must exist in `schema_versions` with the same version.
- Every `required_commands` entry must exist in `supported_commands`.
- `schema_version` for capabilities must be supported by this skill package.
- If `source_spec_commit` differs from the local repo commit, report a warning. Continue only if version, schema, and command checks pass.

If doctor, bootstrap, or capabilities fails; returns invalid JSON; has an incompatible `schema_version`; is too old; lacks a required schema version; or does not list the required commands, stop before observing dating app content and tell the user the local Dating Booster tool is incompatible.

## Privacy Boundary

In this mode, Codex is the host agent. The host agent may process visible dating app content, screenshots, profile text, conversation text, and generated drafts. Dating Booster stores local memory, context, policy decisions, feedback, and action audit records; it does not own the LLM in this workflow.

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
dating-boost-host-loop doctor --data-dir .local/dating-boost --app-id tinder --json
dating-boost-host-loop init --data-dir .local/dating-boost --work-dir .local/dating-boost-host-loop --app-id tinder --json
dating-boost-host-loop run --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tinder --send-mode stage --work-dir .local/dating-boost-host-loop --json
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

Use `references/workflows.md` for reusable workflow details and lower-level command fallbacks, `references/contracts.md` for JSON input/output contract examples, and the drafting/naturalness references for Chinese reply quality. These reference files are summaries; core code and committed specs remain the source of truth.

## Post-Action Verification

For sent messages or other high-risk actions, do not record success unless the post-action observation confirms the expected state. If the result cannot be verified, record `result_status` as `unknown`, not `succeeded`.

## Prohibited

- Private APIs, reverse engineering, or non-GUI service automation.
- Account farming, bulk swiping, scraping member-only data, or evading bans/checks.
- Claiming an action succeeded without post-action verification.
- Leaking a draft that `dating-boost policy check-draft` blocks.
