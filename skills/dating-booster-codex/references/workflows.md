# Dating Booster Agent-Native Workflows

These workflows are for host agents using Dating Booster as local memory, context,
policy, and audit tools. They do not replace the repository specs.

## Startup

1. Choose a data directory, usually `.local/dating-boost`.
2. Run `python3 scripts/doctor.py --json --data-dir .local/dating-boost`.
3. If doctor returns `needs_bootstrap`, run `python3 scripts/bootstrap_cli.py`, then run doctor again.
4. Run `dating-boost skill doctor --package skill-package.json --data-dir .local/dating-boost --json` when debugging package compatibility from the CLI.
5. Run `dating-boost capabilities --json --data-dir .local/dating-boost`.
6. Load `skill-package.json` and compare `dating_boost_min_version`,
   `required_schema_versions`, and `required_commands`.
7. Stop before viewing dating app content if compatibility fails.
8. Warn, but do not automatically stop, if `source_spec_commit` differs while
   version, schema, and command checks pass.

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
   `usable_shareable_material_count` must be at least three.

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
2. Focus the iOS chat input box.
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

If the input box has position drift after full-screen input, a keyboard mode
change, or a viewport shift, do not keep probing stale coordinates. Back out
and reopen the chat thread, verify the input box is back in its normal location,
then repeat foreground app copy, long-press, Paste, and staged-text
verification.

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

## Tinder Host Loop Supervisor

For real Tinder/iPhone Mirroring runs, prefer:

```bash
python3 scripts/operator_host_loop.py --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tinder --send-mode stage --work-dir .local/dating-boost-host-loop --json
```

Use `--send-mode stage` by default. It writes work items and templates, waits
for host-authored observation or verification files, stages text, and stops
before clicking send. Use `--send-mode live` only when the user explicitly
authorizes ordinary sends; live mode still requires staged verification before
`action_result.json`.

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
