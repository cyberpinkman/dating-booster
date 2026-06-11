---
name: dating-booster
description: Use Dating Booster from Claude Code for local-first dating workflow memory, policy, drafts, GUI harnesses, host-loop operation, and audited managed sends.
---

# Dating Booster For Claude Code

Use this skill when a Claude Code user asks for help with Dating Booster dating-app workflows. Claude Code is the host agent: it reads visible app context, writes observations and drafts, and calls the Dating Booster CLI for local memory, policy, planner, harness, audit, diagnostics, and recovery.

## Mandatory Startup

Before observing any visible dating app content, screenshots, profile text, conversation text, or generated drafts, choose a local data directory. Prefer `.local/dating-boost` unless the user gives another path.

If this is a freshly cloned or recently pulled repository, or if the installed Claude Code skill disagrees with `dating-boost capabilities`, refresh the local editable install and reinstall this adapter before startup checks:

```bash
python3 -m pip install --user -e .
python3 -m dating_boost.cli adapter claude-code install --scope project --target . --json
python3 -m dating_boost.cli adapter claude-code doctor --data-dir .local/dating-boost --json
python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost
```

Run:

```bash
dating-boost adapter claude-code doctor --data-dir .local/dating-boost --json
dating-boost release doctor --json
dating-boost data doctor --data-dir .local/dating-boost --json
dating-boost capabilities --json --data-dir .local/dating-boost
python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost
```

If data doctor returns `needs_migration`, run:

```bash
dating-boost data migrate --data-dir .local/dating-boost --json
```

Stop before app observation if the adapter doctor, release doctor, data doctor, migration, or capabilities check fails; if required schemas or commands are missing; or if `agent_native_capabilities.claude_code_adapter` is not true.

Treat capabilities output as the current machine truth for supported apps and commands. Do not infer app support from version strings, README prose, cached memory, or an older installed `.claude/skills/dating-booster` copy. If `dating-boost capabilities` and `python3 -m dating_boost.cli capabilities` disagree, report `stale console script`, prefer the `python3 -m dating_boost.cli ...` command from the checked-out repo, and reinstall the editable package before deciding an app is unsupported.

After startup checks pass and the target app id is known, start a local support session before observing dating-app content:

```bash
dating-boost support session start --data-dir .local/dating-boost --host claude-code --app-id tinder --json
```

Keep the returned `session_id`. Commands with `--data-dir` record redacted command boundaries; draft policy checks, GUI harness stage/send commands, and `dating-boost-host-loop` commands using the same `--data-dir` also record topic provenance, hashes, clipboard fingerprints, timeline events, and encrypted sensitive evidence. Stop the session before ending the workflow:

```bash
dating-boost support session stop --data-dir .local/dating-boost --session-id <session_id> --json
```

## Shared Contracts

Read and follow `references/contracts.md` and `references/workflows.md` from this installed skill directory. They are host-neutral. Do not copy Codex-specific assumptions into this workflow, and do not fork memory, policy, planner, app-profile, or harness business logic in Claude Code.

## Privacy Boundary

Claude Code may process visible dating app content only for the active task after startup checks pass. Raw screenshots and OCR text should stay local. Normal diagnostics should use redacted counts, hashes, layout hints, schema versions, and machine reports rather than private message text.

Dating Booster stores local memory, context, policy decisions, feedback, and host-executed action audit records. It does not own the LLM call in this workflow.

For user bug reports, export a strict support bundle by default:

```bash
dating-boost support bundle --data-dir .local/dating-boost --session-id <session_id> --output dating-boost-support.zip --redaction strict --json
```

Strict bundles must not contain raw draft text, raw conversation text, raw profile text, raw screenshots, or clipboard contents. They may contain hashes, character counts, topic labels, command names, schema versions, target ids, and action outcomes. Use `--redaction full-with-consent --include-sensitive ... --confirm export-sensitive:<session_id>` only when the user explicitly asks to export sensitive evidence; never use it as the default.

## Core Workflow

1. Run `dating-boost capabilities --json --data-dir .local/dating-boost`.
2. Confirm the app id is listed in `supported_app_profiles`.
3. For autonomous or managed work, run `dating-boost user readiness --data-dir .local/dating-boost --mode autonomous --json`; stop if it returns `needs_user_profile`.
4. Convert visible screen content into an observation JSON with `dating-boost observation template`, `dating-boost observation validate`, and `dating-boost observation normalize`.
5. Run `dating-boost memory ingest-observation`, build context with `dating-boost context build`, then check the authored draft with `dating-boost policy check-draft`.
6. Check every draft through `dating-boost policy check-draft`.
7. Check high-risk actions through `dating-boost policy check-action`.
8. After any host action, verify from fresh screen evidence and record the result with `dating-boost action record-result`.

## User Model And Planning

For fully managed or autonomous sessions, collect both dating profile and self interview data:

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

Low confidence, stale context, topic loops, appointment details, contact exchange, or unclear user preference should stop automatic sending for that match.

## Tinder iPhone Mirroring Harness

Use the Tinder harness for iPhone Mirroring work:

```bash
dating-boost harness doctor --app-id tinder --json
dating-boost harness tinder launch --dry-run --json
dating-boost harness tinder open-profile --dry-run --json
dating-boost harness tinder observe --output-dir .local/dating-boost-harness --json
dating-boost harness tinder workflow self-profile-read --dry-run --options-json tinder-self-profile-options.json --json
dating-boost harness tinder workflow chat-read-match-profile --dry-run --options-json tinder-chat-profile-options.json --json
dating-boost harness tinder workflow new-match-open --dry-run --options-json tinder-new-match-open-options.json --json
dating-boost harness tinder workflow new-match-read-profile --dry-run --options-json tinder-new-match-profile-options.json --json
dating-boost harness tinder action open-conversation --options-json tinder-open-iris-options.json --json
dating-boost harness tinder action dismiss-subscription-paywall --json
dating-boost harness tinder action dismiss-feedback-survey --json
dating-boost harness tinder send-message --text-file tinder-draft.txt --dry-run --json
```

Use `new-match-open` for an unopened match when the agent should enter one conversation, write an opener from visible profile context, and then return to chats for the next candidate. Use `chat-read-match-profile` for existing conversation rows.
For existing conversations, prefer `open-conversation --options-json <path>` with `visible_name` or `target_binding`; row coordinates are compatibility
fallbacks only. Keep target-binding evidence inside the options JSON.

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

Prefer `--text-file` so private draft text does not enter shell history or process arguments.

## Bumble iPhone Mirroring Harness

Use the Bumble harness for iPhone Mirroring work:

```bash
dating-boost harness doctor --app-id bumble --json
dating-boost harness bumble launch --dry-run --json
dating-boost harness bumble observe --output-dir .local/dating-boost-harness --json
dating-boost harness bumble action open-chats --dry-run --json
dating-boost harness bumble workflow chat-read-match-profile --dry-run --options-json bumble-chat-profile-options.json --json
dating-boost harness bumble workflow opening-move-open --dry-run --options-json bumble-opening-move-options.json --json
dating-boost harness bumble send-message --text-file bumble-draft.txt --dry-run --json
```

Bumble live send is limited to ordinary chat messages. Opening Move is role-sensitive: for women, the user decides whether to start, skip, or accept Opening Move; for men, Claude Code may draft a response for user confirmation, but must not autonomously send an Opening Move response.

## TaShuo Harness

Use the TaShuo harness for iPhone Mirroring work. Launch search should use `tashu` when Spotlight/Siri does not suggest the app for the full pinyin `tashuo`.

```bash
dating-boost harness doctor --app-id tashuo --json
dating-boost harness tashuo launch --dry-run --json
dating-boost harness tashuo observe --output-dir .local/dating-boost-harness --json
dating-boost harness tashuo action open-chats --dry-run --json
dating-boost harness tashuo workflow chat-read-match-profile --dry-run --options-json tashuo-chat-profile-options.json --json
dating-boost harness tashuo workflow question-gate-open --dry-run --options-json tashuo-question-gate-options.json --json
dating-boost harness tashuo action prepare-message-page --runtime mac-ios-app --output-dir .local/dating-boost-harness --json
dating-boost harness tashuo stage-draft --runtime mac-ios-app --text-file tashuo-draft.txt --dry-run --json
dating-boost harness tashuo send-message --text-file tashuo-draft.txt --dry-run --json
```

If the user has installed and logged into the TaShuo iOS app on an Apple Silicon Mac, use `action prepare-message-page --runtime mac-ios-app` at task startup. It opens the local app, verifies the top-level page from the visual bottom-tab highlight, taps the messages tab when needed, then stops with `next_host_action=visual_plan_message_list`. After that point, plan from visual analysis; do not OCR-first and do not use fixed row coordinates to enter a chat thread. The mac-ios-app runtime currently supports launch/observe/prepare-message-page/stage-draft only. Managed live send is marked `experimental_blocked_cjk_stage_verification` and host-loop must block `--send-mode live --managed-gui-send --harness-runtime mac-ios-app` before attempting a real send. Direct harness live send remains executor-internal/experimental and must not be used as an agent workaround.

TaShuo question-gate behaves like Bumble Opening Move: the user decides female-side question/skip/accept choices; male-side replies may be drafted for user confirmation, but autonomous question-gate sending is not supported.

## Managed Live-Send

Managed live-send is allowed only for ordinary chat messages and only after explicit authorization. It is never a bypass for app rules, rate limits, verification, account restrictions, or user judgment.

Before any live send, require all of these:

- explicit authorization with `live_send: true`
- unpaused safety switch
- planner-backed action request with `planner_alignment: ok`, `conversation_stage`, and `conversation_move`
- policy-checked action request
- target binding
- verified conversation page
- exact staged text verification
- post-action verification

For Tinder, Bumble, TaShuo, and WeChat, the agent-facing managed live-send path
is `managed-session` or `dating-boost-host-loop`; do not handcraft
`action_request.json`.

```bash
dating-boost managed-session start --app-id <app_id> --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --send-mode live --managed-gui-send --json
dating-boost managed-session run --data-dir .local/dating-boost --wait --json
dating-boost-host-loop run --adapter-package agent_adapters/claude-code/adapter-package.json --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id <app_id> --send-mode live --managed-gui-send --work-dir .local/dating-boost-host-loop --json
```

TaShuo mac-ios-app is not currently a managed live-send runtime. If invoked with
`--harness-runtime mac-ios-app`, host-loop must block with
`runtime_live_send_not_supported:tashuo:mac-ios-app`.

The direct `harness <app> send-message --authorization --action-request` command
is executor-internal only. It may consume only a `send_message` work item
returned by `dating-boost operator next` or `dating-boost automation session
step`, or a confirmed confirmation flow with hashes. Do not handcraft
`action_request.json`, do not add a bare `confirmation_id`, and do not call
direct harness live-send as a shortcut. If operator/session state is
unavailable, stop with `operator_unavailable` or `planner_evidence_missing`
instead of sending.

If page identity, target binding, planner evidence, staged text, or post-send evidence is missing, block or return `needs_verification`. Do not manually click Send around the gate.

## Session-scoped Managed Runner

Use this when the user explicitly starts a bounded managed window. It is not a
global background agent. iPhone Mirroring apps stop when the mirrored phone is unavailable;
WeChat runs until user stop and pauses while unreadable. `run --wait` is local
and tokenless while idle; when it returns `host_work_required`, process the
included operator work item. When using the host-loop supervisor for that work,
run `dating-boost-host-loop resume` with the same data/work dirs; do not start a
fresh `dating-boost-host-loop run`, because a fresh run starts a new operator
session. After resume or equivalent manual operator processing, return to
`managed-session run --wait`.

```bash
dating-boost managed-session start --app-id tinder --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --send-mode stage --scan-interval 120 --nudge-delay-minutes 30 --json
dating-boost managed-session run --data-dir .local/dating-boost --wait --json
dating-boost managed-session notify --data-dir .local/dating-boost --source manual --app-id tinder --json
dating-boost managed-session status --data-dir .local/dating-boost --json
dating-boost managed-session stop --data-dir .local/dating-boost --json
```

Only add `--send-mode live --managed-gui-send` when authorization permits live
ordinary message sends; all target binding, staged text, and post-send gates
still apply.

## Host Loop

Use the host loop when Claude Code should act as the executor for queued work items:

```bash
dating-boost support session start --data-dir .local/dating-boost --host claude-code --app-id tinder --json
dating-boost-host-loop doctor --adapter-package agent_adapters/claude-code/adapter-package.json --data-dir .local/dating-boost --app-id tinder --json
dating-boost-host-loop init --adapter-package agent_adapters/claude-code/adapter-package.json --data-dir .local/dating-boost --work-dir .local/dating-boost-host-loop --app-id tinder --json
dating-boost-host-loop run --adapter-package agent_adapters/claude-code/adapter-package.json --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tinder --send-mode stage --work-dir .local/dating-boost-host-loop --json
dating-boost support session stop --data-dir .local/dating-boost --session-id <session_id> --json
dating-boost support bundle --data-dir .local/dating-boost --session-id <session_id> --output dating-boost-support.zip --redaction strict --json
```

For fully managed sends, add `--send-mode live --managed-gui-send` only when the authorization and action request are valid.
