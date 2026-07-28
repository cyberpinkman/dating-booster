# Dating Booster Codex References

The operational source of truth is the current CLI capabilities, schemas, app
profiles, core code, and tests. Files under `docs/superpowers/` are historical
design provenance, not current operating instructions. Files in this directory
are short host-agent references and must stay compatible with
`skill-package.json`.

Required startup sequence:

```bash
dating-boost skill doctor --package skills/dating-booster-codex/skill-package.json --data-dir .local/dating-boost --json
dating-boost release doctor --json
dating-boost data doctor --data-dir .local/dating-boost --json
dating-boost capabilities --json --data-dir .local/dating-boost
```

Migrate before the support session if data doctor returns `needs_migration`.
After the target app is known, start a support session and select its
app/runtime. Stop before viewing dating-app content if any compatibility check
fails.

Reference files:

- `workflows.md`: reusable draft, profile refresh, send, and feedback flows.
- `contracts.md`: minimal JSON contracts for observations, drafts, and action results.
- `observation-authoring.md`: rules for converting visible screen content into
  observation JSON without over-inference.
- `production-stage-runbook.md`: production install, diagnostics, Tinder stage
  smoke, and macOS WeChat stage smoke.
- `host-loop.md`: supervised host-loop command sequence and recovery notes.
- `planner-authoring.md`: planner update and recommendation authoring rules.
- `drafting-framework.md`: Chinese host-agent drafting strategy for dating replies.
- `naturalness-checklist.md`: human-context validation checklist and bad to better examples.
- `start-prompts.md`: operator-facing start prompts for Codex runs.
