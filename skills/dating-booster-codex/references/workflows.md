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

1. Convert visible profile/chat context into the observation contract.
   Use `observation-authoring.md` when converting screen content to JSON.
2. Run `dating-boost memory ingest-observation --data-dir .local/dating-boost --input observation.json`.
3. Run `dating-boost memory get-match --data-dir .local/dating-boost --match-id MATCH_ID`.
4. Run `dating-boost context build --data-dir .local/dating-boost --match-id MATCH_ID --mode adaptive`.
5. Generate the draft in the host agent.
6. Save the draft JSON locally.
7. Run `dating-boost policy check-draft --input draft.json --context context.json`.
8. If blocked, do not show or paste the blocked draft.
9. If allowed, show the draft to the user or paste it when the user requested paste.

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
