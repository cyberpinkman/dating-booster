# Dating Booster Agent-Native Workflows

These workflows are for host agents using Dating Booster as local memory, context,
policy, and audit tools. They do not replace the repository specs.

## Startup

1. Choose a data directory, usually `.local/dating-boost`.
2. Run `python3 scripts/doctor.py --json --data-dir .local/dating-boost`.
3. If doctor returns `needs_bootstrap`, run `python3 scripts/bootstrap_cli.py`, then run doctor again.
4. Run `dating-boost skill doctor --package skill-package.json --data-dir .local/dating-boost --json` when debugging package compatibility from the CLI.
5. Run `dating-boost data doctor --data-dir .local/dating-boost --json`.
6. If the data doctor reports `needs_migration`, run `dating-boost data migrate --data-dir .local/dating-boost --json`.
7. Run `dating-boost capabilities --json --data-dir .local/dating-boost`.
8. Load `skill-package.json` and compare `dating_boost_min_version`,
   `required_schema_versions`, and `required_commands`.
9. Stop before viewing dating app content if compatibility fails.
10. Warn, but do not automatically stop, if `source_spec_commit` differs while
   version, schema, and command checks pass.
11. After the target app id is known, run `dating-boost support session start --data-dir .local/dating-boost --host codex --app-id <app-id> --json` and keep `session_id`. If host-loop runs with a different `--data-dir`, start a separate support session for that host-loop data dir before `dating-boost-host-loop run`.
12. For real iPhone Mirroring work, run `dating-boost harness doctor --app-id tinder --json`.
13. Use `dating-boost harness tinder launch --dry-run --json`,
    `dating-boost harness tinder open-profile --dry-run --json`, and the
    relevant `harness tinder action/workflow --dry-run --json` before executing
    Tinder navigation.
14. For real macOS WeChat work, run `dating-boost harness doctor --app-id wechat --window-title WeChat --json`,
    `dating-boost harness wechat launch --dry-run --json`, and
    `dating-boost harness wechat observe --json` before staging any draft.
15. Before ending, run `dating-boost support session stop --data-dir .local/dating-boost --session-id <session_id> --json`.

For manual diagnostics, write a redacted payload JSON and optional sensitive
payload JSON, then run `dating-boost support record-event --data-dir
.local/dating-boost --session-id <session_id> --event-type <event_type>
--payload payload.json --sensitive sensitive.json --sensitive-kind <kind>
--json`.

For bug reports, run `dating-boost support bundle --data-dir .local/dating-boost
--session-id <session_id> --output dating-boost-support.zip --redaction strict
--json` and share only the strict bundle by default.

Do not run `dating-boost data migrate` or `dating-boost data delete` on the same
data dir after support session start and before support bundle export.

## Native GUI Harness

The native harness is stage/navigation-first. It may diagnose iPhone Mirroring,
capture a screenshot/OCR artifact, navigate Tinder, Bumble, and TaShuo through
bounded profile/chat reading chains, and execute `send_message` only through
gated app-specific `harness <app> send-message` paths. Bumble and TaShuo
ordinary chat managed send are supported with the same authorization,
target-specific binding, staged-text OCR, and post-send evidence gates. Visual
send-button or bubble evidence alone is not exact-text verification. Bumble
must not like, pass, SuperSwipe, unmatch, report, edit profile data, or purchase
Premium. TaShuo must not like, pass, start a 飞行 chat, unmatch, report, edit
profile data, purchase Premium, or make question-gate decisions.

Bumble Opening Move is role-sensitive. On a female user's account, observe or
summarize the prompt/reply and ask the user whether to enable Opening Move,
skip it, accept the male reply, or reject it. On a male user's account, drafting
an Opening Move reply is allowed for user review, but autonomous Opening Move
send remains unsupported.

TaShuo question gate is role-sensitive. On a female user's account, observe or
summarize the prompt/reply and ask the user whether to enable the question,
skip the gate, accept the male reply, or reject it. On a male user's account,
drafting a question-gate reply is allowed for user review, but the current
harness does not stage or send question-gate replies.

```bash
dating-boost harness doctor --app-id tinder --json
dating-boost harness screenshot --app-id tinder --output iphone-mirroring.png --json
dating-boost harness tinder launch --dry-run --json
dating-boost harness tinder launch --output-dir .local/dating-boost-harness --json
dating-boost harness tinder open-profile --dry-run --json
dating-boost harness tinder open-profile --launch-if-needed --output-dir .local/dating-boost-harness --json
dating-boost harness tinder observe --output-dir .local/dating-boost-harness --json
dating-boost harness tinder action profile-photo-next --dry-run --json
dating-boost harness tinder action open-conversation --options-json tinder-open-row-options.json --dry-run --json
dating-boost harness tinder action open-conversation --options-json tinder-open-iris-options.json --json
dating-boost harness tinder action dismiss-subscription-paywall --json
dating-boost harness tinder action dismiss-feedback-survey --json
dating-boost harness tinder workflow self-profile-read --dry-run --options-json tinder-self-profile-options.json --json
dating-boost harness tinder workflow chat-read-match-profile --dry-run --options-json tinder-chat-profile-options.json --json
dating-boost harness tinder workflow new-match-open --dry-run --options-json tinder-new-match-open-options.json --json
dating-boost harness tinder workflow new-match-read-profile --dry-run --options-json tinder-new-match-profile-options.json --json
dating-boost harness tinder send-message --text-file tinder-draft.txt --dry-run --json
dating-boost harness doctor --app-id bumble --json
dating-boost harness screenshot --app-id bumble --output bumble.png --json
dating-boost harness bumble launch --dry-run --json
dating-boost harness bumble observe --output-dir .local/dating-boost-harness --json
dating-boost harness bumble action open-chats --dry-run --json
dating-boost harness bumble workflow browse-profile-read --dry-run --options-json bumble-profile-options.json --json
dating-boost harness bumble workflow chat-read-match-profile --dry-run --options-json bumble-chat-profile-options.json --json
dating-boost harness bumble workflow opening-move-open --dry-run --options-json bumble-opening-move-options.json --json
dating-boost harness bumble send-message --text-file bumble-draft.txt --dry-run --json
dating-boost harness doctor --app-id tashuo --json
dating-boost harness screenshot --app-id tashuo --output tashuo.png --json
dating-boost harness tashuo launch --dry-run --json
dating-boost harness tashuo observe --output-dir .local/dating-boost-harness --json
dating-boost harness tashuo action open-chats --dry-run --json
dating-boost harness tashuo workflow chat-read-match-profile --dry-run --options-json tashuo-chat-profile-options.json --json
dating-boost harness tashuo workflow question-gate-open --dry-run --options-json tashuo-question-gate-options.json --json
dating-boost harness tashuo send-message --text-file tashuo-draft.txt --dry-run --json
dating-boost harness doctor --app-id wechat --window-title WeChat --json
dating-boost harness screenshot --app-id wechat --window-title WeChat --output wechat.png --json
dating-boost harness wechat launch --dry-run --json
dating-boost harness wechat observe --output-dir .local/dating-boost-harness --json
dating-boost harness wechat stage-draft --text-file wechat-draft.txt --dry-run --json
dating-boost harness wechat send-message --text-file wechat-draft.txt --dry-run --json
```

If doctor reports `iphone_mirroring_locked`, ask the user to unlock iPhone
Mirroring. Tinder launch first checks only whether Tinder is already foreground.
If it is not, the harness returns iPhone Mirroring to Home Screen, opens
Spotlight/search, types `Tinder`, and presses Return. If profile or chat
navigation returns `tinder_foreground_not_verified`, or launch returns
`needs_verification`, do not click arbitrary coordinates; first establish the
foreground screen from a fresh screenshot/OCR observation.

Supported atomic Tinder actions:

- `open-chats`
- `matches-carousel-next`
- `matches-carousel-previous`
- `open-new-match`
- `open-conversation`
- `open-thread-profile`
- `open-self-profile-preview`
- `profile-photo-next`
- `profile-photo-previous`
- `open-full-profile`
- `profile-scroll-down`
- `profile-scroll-up`
- `expand-visible-profile-section`
- `close-full-profile`
- `close-preview`
- `return-to-chats`

Supported high-level workflows:

- `self-profile-read`: from the user's profile page, tap the avatar, move
  through preview photos, enter full-profile read mode, scroll profile content,
  tap the visible expand-control area, exit full read mode, and return to the
  self profile page.
- `chat-read-match-profile`: open the chats tab, open a visible existing
  conversation row, tap the thread avatar, move through the match profile
  preview, enter full-profile read mode, scroll profile content, tap the visible
  expand-control area, and return to the conversation.
- `new-match-open`: open the chats tab, optionally move the new-match carousel
  with wheel events, open one visible unopened match by `match_index` in `--options-json`, and
  stop in that conversation so the host agent can draft and gated-send an
  opener.
- `new-match-read-profile`: open the chats tab, optionally move the new-match
  carousel with wheel events, open one visible unopened match by `match_index` in `--options-json`,
  read the match profile, and return to that conversation for the next opener
  step.

Use `open-conversation --options-json <path>` for existing message-list rows. Keep target-binding evidence inside that options file.  The options JSON may contain `visible_name` when OCR-readable, `row_index`, `target`, and `target_binding`; for emoji or non-OCR nicknames, carry `chat_list_row_to_thread` evidence for the intended row. Use avatar targeting only as a compatibility fallback when the visible target is clear and stable. Treat the
top horizontal carousel as new or not-yet-started matches; treat the vertical
message list as opened conversations. The text marker `等你回应` is only an
observation cue that the match sent the latest message; it is not by itself an
authorization to draft or send.

For unopened matches, do not pre-count the whole carousel unless a goal requires
inventory. Open one visible match with `new-match-open` or
`new-match-read-profile`, plan the opener without prior conversation context,
send only through the managed send gate when authorized, then run
`harness tinder action return-to-chats` and select the next visible unopened
match.

Use `harness tinder observe` before and after bounded navigation. It returns
redacted `layout_hints`, not raw OCR text. The hints distinguish `page:
chats`, `new_matches_carousel_present`, `conversation_list_present`,
`reply_required_marker_present`, `page: self_profile`, active tab hints, and
visible profile expand controls. If `observe` returns `needs_verification`,
do not execute a navigation action until the current screen has been understood
from a fresh screenshot.

If `observe` or any Tinder harness result reports `page:
subscription_paywall`, `subscription_paywall_visible`,
`tinder_subscription_paywall`, or `tinder_subscription_paywall_dismissed`, treat
it as accidental navigation. Do not ask the user whether to subscribe, do not
discuss subscription plans, and do not click purchase or continue controls. Run
`dating-boost harness tinder action dismiss-subscription-paywall --json`, then
re-navigate to a verified chat or profile path before staging or sending.

If `observe` or any Tinder harness result reports `page: feedback_survey`,
`feedback_survey_visible`, or `tinder_feedback_survey`, treat it as a recoverable
survey overlay. Run `dating-boost harness tinder action dismiss-feedback-survey --json`;
the recovery must use the ignore/no-rating path and report
`rating_submitted: false`.

For macOS WeChat, `harness wechat observe` returns redacted `layout_hints`, not
raw OCR text. The hints distinguish `page: conversation`, `page: chat_list`,
message-input markers, and unread markers. `harness wechat stage-draft` copies
the draft to the macOS clipboard and sends `Cmd+V` to the current WeChat input
focus. Stage mode does not press Enter or click Send. Prefer `--text-file` so
private draft text is not written into shell history or process arguments. Real
staging must include `--data-dir` so the global safety pause can block paste.
Use it only after the draft has passed `workflow draft` or `policy check-draft`.

For explicitly authorized fully managed Tinder or macOS WeChat sends, use
`harness <app> send-message --text-file ... --data-dir ... --authorization ...
--action-request ...` or `dating-boost-host-loop run --app-id <app>
--send-mode live --managed-gui-send ...`. The authorization must include
`live_send: true` and `autonomous_send: true`; the action request must be
policy-checked, hash-bound to the text file, and include target-chat binding.
The harness must verify the target chat, verify the staged text exactly
before clicking Send or pressing Return, and verify the outbound bubble from
fresh post-action evidence before the result can be recorded as `succeeded`.

The action `expand-visible-profile-section` is a bounded tap for a visibly
folded profile section such as `查看所有...项信息`. Use it only after a fresh
observation confirms such an expand control is currently visible. If the
profile layout, subscription state, language, or viewport differs from the
expected contract, stop and capture a new observation instead of probing stale
coordinates.

## Production Data And Confirmation

Use these commands before private production smoke or when auditing local state:

1. Run `dating-boost data doctor --data-dir .local/dating-boost --json`.
2. Run `dating-boost data migrate --data-dir .local/dating-boost --json` before production smoke when JSON data has not been migrated.
3. Run `dating-boost data export --data-dir .local/dating-boost --output export.json --json` to produce a restorable JSON audit/export artifact.
4. Run `dating-boost data delete --data-dir .local/dating-boost --scope match --match-id MATCH_ID --confirm delete:match:MATCH_ID --json` for match-scoped deletion.
5. Use `dating-boost confirmation create`, `dating-boost confirmation confirm`,
   and `dating-boost confirmation validate` for live sends requiring an explicit
   confirmation contract.
6. Read `production-stage-runbook.md` before any real Tinder stage-mode smoke.

## User Self Model

Use this before any fully managed/autonomous session. Without the user's own
dating profile and self interview, the agent will over-rely on asking the match
questions.

1. Run `dating-boost user interview template --json` when the user needs the
   interview shape.
2. Import the user's dating profile with `dating-boost user ingest-profile --data-dir .local/dating-boost --input user_profile.json`.
3. Import the self interview with `dating-boost user ingest-interview --data-dir .local/dating-boost --input interview.json`.
4. Inspect the merged material with `dating-boost user disclosure-profile --data-dir .local/dating-boost --json` when debugging.
5. Run `dating-boost user readiness --data-dir .local/dating-boost --mode autonomous --json`.
6. If readiness returns `needs_user_profile`, do not start `operator session` or
   `automation session` for autonomous sending. Ask the user to provide missing
   profile/interview material. `shareable_material_count` alone is not enough;
   autonomous readiness requires at least five low-risk materials, two
   `low_investment_repair` materials, and one date/meeting preference material.

## Draft

Use this when the user wants a reply suggestion for a known match.

Preferred runner path:

1. Convert visible profile/chat context into the observation contract.
   Use `observation-authoring.md` when converting screen content to JSON.
2. Read `drafting-framework.md` and choose the conversation move.
3. Generate the draft in the host agent using the expanded draft contract.
4. Apply `naturalness-checklist.md` as an internal QA step; revise AI-sounding Chinese before using the draft.
5. Save the observation JSON and draft JSON locally.
6. Run `dating-boost workflow draft --data-dir .local/dating-boost --observation observation.json --draft draft.json --mode adaptive`.
7. Add `--feedback-label accepted --draft-id DRAFT_ID` only when the user has accepted or rated the draft.
8. If the workflow returns `blocked`, do not show or paste the blocked draft.
9. If the workflow returns `ok`, show only the final draft to the user or paste it when the user requested paste.
   Do not list checklist results unless the user explicitly asks for explanation, critique, review, or debug output.

Lower-level fallback path:

1. Convert visible profile/chat context into the observation contract.
   Use `observation-authoring.md` when converting screen content to JSON.
2. Run `dating-boost memory ingest-observation --data-dir .local/dating-boost --input observation.json`.
3. Run `dating-boost memory get-match --data-dir .local/dating-boost --match-id MATCH_ID`.
4. Run `dating-boost context build --data-dir .local/dating-boost --match-id MATCH_ID --mode adaptive`.
5. Read `drafting-framework.md` and choose the conversation move.
6. Generate the draft in the host agent using the expanded draft contract.
7. Apply `naturalness-checklist.md` as an internal QA step; revise AI-sounding Chinese before showing the draft.
8. Save the draft JSON locally.
9. Run `dating-boost policy check-draft --input draft.json --context context.json`.
10. If blocked, do not show or paste the blocked draft.
11. If allowed, show only the final draft to the user or paste it when the user requested paste.
    Do not list checklist results unless the user explicitly asks for explanation, critique, review, or debug output.

## Profile Refresh

Use this when the user wants match memory updated from a profile page or fresh
chat screen.

1. Capture visible profile text, photo cues, hook candidates, messages, and page
   type into an observation JSON object using `observation-authoring.md`.
2. Run `dating-boost memory ingest-observation --data-dir .local/dating-boost --input observation.json`.
3. If the result requires user confirmation, ask the user whether this is the
   same match before relying on the merged memory.
4. Run `dating-boost memory get-match --data-dir .local/dating-boost --match-id MATCH_ID`.
5. If the user confirms identity, corrects a fact, rejects an assumption, or
   asks to merge two identities, write the correction JSON and run
   `dating-boost memory update-match --data-dir .local/dating-boost --match-id MATCH_ID --input correction.json`.

## Memory Maintenance

Use this for local privacy requests, local recovery, or regression checks.

1. Rebuild one match with `dating-boost memory rebuild --data-dir .local/dating-boost --match-id MATCH_ID`.
2. Rebuild all local match projections with `dating-boost memory rebuild --data-dir .local/dating-boost --all`.
3. Export one match with `dating-boost memory export --data-dir .local/dating-boost --match-id MATCH_ID`.
4. Delete one match only after exact confirmation with
   `dating-boost memory delete-match --data-dir .local/dating-boost --match-id MATCH_ID --confirm delete-match:MATCH_ID`.
5. Run deterministic memory regressions with
   `dating-boost eval run --suite memory --input tests/fixtures/evals/memory_cases.jsonl --json`.

## Send

Use this only after the user asks the host agent to send or explicitly enables a
high-risk experiment.

1. Build or update context with the Draft workflow.
2. Run `dating-boost policy check-draft --input draft.json --context context.json`.
3. Run `dating-boost policy check-action send_message` or
   `dating-boost policy check-action send_message --autonomous`, depending on
   the user's chosen experiment mode.
4. If policy blocks, stop.
5. Execute the host action.
6. Take a fresh post-action observation.
7. Record the action with `dating-boost action record-result --data-dir .local/dating-boost --input action_result.json`.
8. Use `result_status: "unknown"` when post-action verification is inconclusive.

### iPhone Mirroring Send Execution

For iPhone Mirroring, the host harness must assume text input can be lossy.
This is especially true for Chinese and longer messages.

Preferred execution path:

1. Use foreground app copy when possible: put the exact
   `action_request.payload_text` in a normal Mac app, select it, and copy it
   with a real `Cmd+C`. Do not assume `pbcopy` alone will trigger Universal
   Clipboard.
2. Focus the current iOS chat input box from a fresh observation. Use the
   harness/window coordinate system, not coordinates estimated from a rendered
   screenshot in chat. Re-focus before every keyboard command.
3. Try `Cmd+V` as a staging shortcut only after the input box is focused and
   positioned normally. If it stages the exact text, continue to verification.
4. If `Cmd+V` does not stage text, long-press or two-finger/right-click the iOS
   input box to open the edit menu, then tap Paste.
5. Verify staged text in the input box before sending.
6. Do not send if the staged text is missing, truncated, garbled, or materially
   different from `action_request.payload_text`.
7. Tap Send only after the staged text matches.
8. After sending, take a fresh observation and compare the outbound bubble with
   the requested payload.

Do not treat `type_text`, `Cmd+V`, `Return`, or a visible outbound bubble alone
as proof of success. `Cmd+V` may be a valid staging shortcut, and Return may
send in apps such as WeChat after staging, but success still requires
staged-text and outbound-bubble verification. If the sent text is incomplete or
different, record the action result with `result_status: "failed"` when the
mismatch is clear, or `result_status: "unknown"` when verification is
inconclusive. Do not send a second recovery message until the current mismatch
is recorded and a fresh thread observation produces a new action request.

If paste produces a literal shortcut key such as `v`, an IME candidate, or any
other wrong text, cancel the candidate if present, re-focus the exact input box,
Backspace the wrong text, verify the input is empty or safe, and block the
action. Do not continue with direct typing on top of an occupied input.

If the input box has position drift after full-screen input, a keyboard mode
change, or a viewport shift, do not keep probing stale coordinates. Back out
and reopen the chat thread, verify the input box is back in its normal location,
then repeat foreground app copy, long-press, Paste, and staged-text
verification.

For iOS Spotlight app launch under Chinese input methods, type the app search
term without a trailing space, verify the app result by screenshot/OCR, and tap
only after verification. A trailing space can commit a Pinyin candidate such as
`tashu` -> `他书` and hide the intended app.

Target binding is not interchangeable with target selection. If the requested
target has an emoji or otherwise non-OCR nickname, keep the same target and
collect app-specific structural evidence, such as message-list row index/bounds
plus the `open-conversation` transition into an ordinary thread. Blocking is
only a fail-safe when same-target evidence cannot be collected or verified
before any send attempt; never choose another OCR-friendly conversation.

## Feedback

Use this when the user accepts, edits, rejects, or rates a draft.

1. Identify the `match_id`, `draft_id`, `mode`, and label.
2. Run `dating-boost feedback record --data-dir .local/dating-boost --match-id MATCH_ID --draft-id DRAFT_ID --mode adaptive --label accepted`.
3. Keep labels short and stable, such as `accepted`, `edited`, `rejected`, or
   `sent`.

## Goal-Oriented Operator Session

Use this when the user explicitly asks the host agent to manage multiple matches
toward a goal such as meeting in person.

1. Run startup doctor and `dating-boost capabilities --json --data-dir .local/dating-boost`, then verify compatibility.
2. Run `dating-boost user readiness --data-dir .local/dating-boost --mode autonomous --json`; stop if it returns `needs_user_profile`.
3. Save the user's goal with `dating-boost automation goal set --data-dir .local/dating-boost --input goal.json`.
4. Save availability with `dating-boost automation availability set --data-dir .local/dating-boost --input availability.json`.
5. Start the session with `dating-boost operator session start --data-dir .local/dating-boost --authorization auth.json`.
6. Call `dating-boost operator next --data-dir .local/dating-boost` and execute exactly the returned work item.
7. For `scan_message_list`, observe the visible list and ingest it with `dating-boost operator ingest-observation --data-dir .local/dating-boost --input list_observation.json`.
8. For `open_thread`, open that candidate's thread, read `planner-authoring.md`, author `planner_assessment`, author a draft only when the planner move requires a reply, then ingest with `dating-boost operator ingest-observation --data-dir .local/dating-boost --input thread_observation.json`. For disclosure moves, include `disclosure_source` and `used_user_material_ids`; for low-investment repair, include `question_count` or `reply_shape`.
9. For `send_message`, execute only ordinary requests with `planner_alignment: ok`; verify the sent state from a fresh observation and run `dating-boost operator record-action-result --data-dir .local/dating-boost --input action_result.json`.
10. For `handoff`, appointment details, contact exchange, likes, unmatches, reports, or profile edits, stop automation for that match and ask the user to take over.
11. Continue `operator next -> observe/act -> ingest/result` until the user stops or the operator returns `wait`.
12. Stop with `dating-boost operator stop --data-dir .local/dating-boost`.
13. Show `dating-boost operator report latest --data-dir .local/dating-boost --format md`.
14. Resume later by reading `dating-boost operator report latest --data-dir .local/dating-boost` and continuing from local state.

## Session-scoped Managed Runner

Use this when the user wants a bounded managed window without keeping the host
agent active between events. The local runner performs tokenless checks and
returns only when host work is needed, paused, blocked, or stopped.

```bash
dating-boost managed-session start --app-id tinder --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --send-mode stage --scan-interval 120 --nudge-delay-minutes 30 --json
dating-boost managed-session run --data-dir .local/dating-boost --wait --json
```

If `run` returns `no_work`, do not continue screenshot analysis or drafting.
If it returns `host_work_required`, execute the included operator work item
using the normal `scan_message_list`, `open_thread`, or `send_message` path.
When using the host-loop supervisor for that work, run
`dating-boost-host-loop resume` with the same data/work dirs; do not start a
fresh `dating-boost-host-loop run`, because a fresh run starts a new operator
session. After resume or equivalent manual operator processing, call
`managed-session run --wait` again. Use `managed-session notify` only as an
event hint; it does not bypass fresh observation, planner, or send gates.
Stop with `dating-boost managed-session stop --data-dir .local/dating-boost`.

## Tinder Host Loop Supervisor

For real Tinder/iPhone Mirroring runs, prefer:

```bash
dating-boost support session start --data-dir .local/dating-boost --host codex --app-id tinder --json
dating-boost-host-loop doctor --data-dir .local/dating-boost --app-id tinder --json
dating-boost-host-loop init --data-dir .local/dating-boost --work-dir .local/dating-boost-host-loop --app-id tinder --json
dating-boost-host-loop run --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tinder --send-mode stage --work-dir .local/dating-boost-host-loop --json
dating-boost support session stop --data-dir .local/dating-boost --session-id <session_id> --json
dating-boost support bundle --data-dir .local/dating-boost --session-id <session_id> --output dating-boost-support.zip --redaction strict --json
```

Use `dating-boost-host-loop status` to inspect what the host must do next,
`dating-boost-host-loop resume` after interruption, and
`dating-boost-host-loop confirm-staged` after a stage-mode send is reviewed.
Use `--send-mode stage` by default. It writes work items and templates, waits
for host-authored observation or verification files, stages text, and stops
before clicking send. Files are scoped by `work_item_id`, such as
`staged_verification.<work_item_id>.json`; old examples may mention
`staged_verification.json`. Use `--send-mode live` only when the user
explicitly authorizes ordinary sends; live mode still requires staged
verification before `action_result.<work_item_id>.json`.

Validate host observations with:

```bash
dating-boost observation validate --input OBSERVATION.json --json
```

Use `dating-boost replay latest --data-dir .local/dating-boost --format md`
for run review and `dating-boost eval run --suite conversation --json` for
deterministic fixture regression.

## Automation Session Fallback

Use lower-level `automation session` commands for batch debugging or fixture
tests. Prefer the operator workflow for real host-managed sessions.

1. Run `dating-boost user readiness --data-dir .local/dating-boost --mode autonomous --json`; stop if it returns `needs_user_profile`.
2. Start with `dating-boost automation session start --data-dir .local/dating-boost --authorization auth.json`.
3. Use `dating-boost automation scan template --json` for a skeleton when needed.
4. The host agent scans the visible message list and opens a bounded set of relevant threads.
5. For each opened thread, read `planner-authoring.md` and author `planner_assessment`.
6. Prefer separate files for the list and opened threads, then run `dating-boost automation scan assemble --message-list list.json --threads threads.json --session-id SESSION --captured-at TIME --json`.
7. Run `dating-boost automation scan normalize --input scan_batch.json --json` only when safe defaults are missing.
8. Run `dating-boost automation scan validate --input scan_batch.json --json`; stop if validation fails.
9. Optionally run `dating-boost planner update --data-dir .local/dating-boost --match-id MATCH_ID --goal-id GOAL_ID --observation observation.json --assessment planner_assessment.json --json` and inspect `dating-boost planner recommend --data-dir .local/dating-boost --match-id MATCH_ID --json` when debugging one thread.
10. Run `dating-boost automation session step --data-dir .local/dating-boost --scan-batch scan_batch.json`.
11. Stop with `dating-boost automation session stop --data-dir .local/dating-boost`.
12. Show `dating-boost automation report latest --data-dir .local/dating-boost --format md`.

Do not use automation session output to commit to exact meeting details, contact
exchange, likes, unmatches, reports, or profile edits.
