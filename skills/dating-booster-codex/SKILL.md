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
Before generating a draft for an opened thread, read
`references/planner-authoring.md` and author a `planner_assessment` that
describes conversation stage, scores, topic lifecycle, next milestone, and
whether a soft invite is allowed. Dating Booster stores this as a `goal_plan`
and returns a planner recommendation. Drafts should align with the planner move;
if they do not, stop instead of sending.

Use planner scores as strategy state, not as truth about the person. Low
confidence, stale turn boundaries, topic loops, appointment details, or contact
exchange must stop automatic sending for that match.

## Workflow

1. Run `python3 scripts/doctor.py --json --data-dir .local/dating-boost`; bootstrap with `python3 scripts/bootstrap_cli.py` only if doctor says `needs_bootstrap`.
2. Run `dating-boost capabilities --json --data-dir .local/dating-boost` and verify compatibility against `skill-package.json`.
3. Convert visible screen content to an observation JSON using `references/observation-authoring.md`.
4. When working toward a long-term goal, author a `planner_assessment` and run `dating-boost planner update`.
5. Read `references/drafting-framework.md`, then generate the draft JSON in Codex using the visible profile/chat context and planner recommendation.
6. Before using the draft, silently apply `references/naturalness-checklist.md` and revise anything that reads like AI-written Chinese.
7. Run `dating-boost workflow draft --data-dir .local/dating-boost --observation observation.json --draft draft.json --mode adaptive`.
8. If the workflow returns `blocked`, do not show or paste the blocked draft.
9. If the workflow returns `ok`, show only the final draft or paste it when the user requested paste.
10. For any high-risk action, run `dating-boost policy check-action` and ask for explicit confirmation.
11. After the host executes an action, perform post-action verification from a fresh observation.
12. Record the result with `dating-boost action record-result`.
13. Record user feedback with `dating-boost feedback record` when useful.

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

## Host-Orchestrated Automation Session

Use this mode only after explicit user authorization. Codex remains the host
agent: it observes the dating app screen, opens message threads, authors
`scan_batch` JSON, and executes ordinary send requests. Dating Booster CLI is
the local state engine; it does not scan the screen or click the app.

1. Run the mandatory startup check.
2. Record goal and availability JSON with `dating-boost automation goal set` and `dating-boost automation availability set`.
3. Start with `dating-boost automation session start --data-dir .local/dating-boost --authorization auth.json`.
4. Generate a scan skeleton with `dating-boost automation scan template --json` when useful.
5. Scan the visible message list and a bounded set of relevant threads. Prefer writing separate message-list and thread JSON files, then run `dating-boost automation scan assemble --message-list list.json --threads threads.json --session-id SESSION --captured-at TIME --json`.
6. For each opened thread, author `planner_assessment` before the draft: include engagement, warmth, curiosity, comfort, momentum, topic_saturation, logistics_readiness, risk, recommended stage, recommended move, next milestone, avoid_next, and soft_invite_allowed.
7. Run `dating-boost automation scan validate --input scan_batch.json --json` before every session step.
8. Run `dating-boost automation session step --data-dir .local/dating-boost --scan-batch scan_batch.json`.
9. Execute only allowed ordinary `send_message` action requests whose planner alignment is `ok`.
10. After each send, perform post-action verification and call `dating-boost action record-result`.
11. Stop with `dating-boost automation session stop --data-dir .local/dating-boost` and show `dating-boost automation report latest --data-dir .local/dating-boost --format md`.
12. On a later run, use `dating-boost automation report latest` and local state to continue without relying on host-agent memory.

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
