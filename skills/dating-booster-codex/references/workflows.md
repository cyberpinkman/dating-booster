# Dating Booster Agent-Native Workflows

These workflows are for host agents using Dating Booster as local memory, context,
policy, and audit tools. They do not replace the repository specs.

## Startup

1. Choose a data directory, usually `.local/dating-boost`.
2. Run `dating-boost capabilities --json --data-dir .local/dating-boost`.
3. Load `skill-package.json` and compare `dating_boost_min_version`,
   `required_schema_versions`, and `required_commands`.
4. Stop before viewing dating app content if compatibility fails.
5. Warn, but do not automatically stop, if `source_spec_commit` differs while
   version, schema, and command checks pass.

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

## Feedback

Use this when the user accepts, edits, rejects, or rates a draft.

1. Identify the `match_id`, `draft_id`, `mode`, and label.
2. Run `dating-boost feedback record --data-dir .local/dating-boost --match-id MATCH_ID --draft-id DRAFT_ID --mode adaptive --label accepted`.
3. Keep labels short and stable, such as `accepted`, `edited`, `rejected`, or
   `sent`.

## Automation Session

Use this when the user explicitly asks the host agent to manage multiple matches
toward a goal such as meeting in person.

1. Run `dating-boost capabilities --json --data-dir .local/dating-boost` and verify compatibility.
2. Save the user's goal with `dating-boost automation goal set --data-dir .local/dating-boost --input goal.json`.
3. Save availability with `dating-boost automation availability set --data-dir .local/dating-boost --input availability.json`.
4. Start the session with `dating-boost automation session start --data-dir .local/dating-boost --authorization auth.json`.
5. The host agent scans the visible message list and opens a bounded set of relevant threads.
6. Convert the scan into a `scan_batch` JSON. Include host-authored `assessment` and `draft` objects for threads that are ready for ordinary replies.
7. Run `dating-boost automation session step --data-dir .local/dating-boost --scan-batch scan_batch.json`.
8. Execute only ordinary `send_message` action requests. Do not execute `handoffs`.
9. After each send, verify the sent state from a fresh observation and run `dating-boost action record-result --data-dir .local/dating-boost --input action_result.json`.
10. Stop with `dating-boost automation session stop --data-dir .local/dating-boost`.
11. Resume later by reading `dating-boost automation report latest --data-dir .local/dating-boost` and continuing from local state.

Do not use automation session output to commit to exact meeting details, contact
exchange, likes, unmatches, reports, or profile edits.
