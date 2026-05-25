# Codex-First Workflow Example

```bash
dating-boost capabilities --json --data-dir .local/dating-boost
dating-boost memory ingest-observation --data-dir .local/dating-boost --input observation.json
dating-boost memory get-match --data-dir .local/dating-boost --match-id match_alex
dating-boost context build --data-dir .local/dating-boost --match-id match_alex --mode adaptive
dating-boost policy check-draft --input draft.json --context context.json
dating-boost policy check-action send_message --autonomous
dating-boost action record-result --data-dir .local/dating-boost --input action_result.json
dating-boost feedback record --data-dir .local/dating-boost --match-id match_alex --draft-id draft_1 --mode adaptive --label accepted
```
