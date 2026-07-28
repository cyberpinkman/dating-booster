# Codex Lower-Level Draft Workflow

This is an offline/lower-level example for an already installed and initialized
data directory. It does not observe an app, authorize live send, or replace the
startup, support-session, runtime-selection, and GUI rules in `SKILL.md`.

```bash
dating-boost capabilities --json --data-dir .local/dating-boost
dating-boost memory ingest-observation --data-dir .local/dating-boost --input observation.json
dating-boost memory get-match --data-dir .local/dating-boost --match-id match_alex
dating-boost context build --data-dir .local/dating-boost --match-id match_alex --mode adaptive
dating-boost policy check-draft --input draft.json --context context.json
dating-boost feedback record --data-dir .local/dating-boost --match-id match_alex --draft-id draft_1 --mode adaptive --label accepted
```

For real app work, default to stage-only. Direct harness send is
executor-internal; do not handcraft action requests.
