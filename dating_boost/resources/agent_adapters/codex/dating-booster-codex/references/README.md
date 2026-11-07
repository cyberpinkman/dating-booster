# Dating Booster Codex References

The operational source of truth is the current CLI capabilities, schemas, app
profiles, core code, and tests. Files under `docs/superpowers/` are historical
design provenance, not current operating instructions. Files in this directory
are short host-agent references and must stay compatible with
`skill-package.json`.

Compatibility checks after installation, updates, migration, permission changes,
or for explicit diagnostics (match the original adapter scope and target):

```bash
dating-boost adapter codex doctor --scope user --data-dir .local/dating-boost --json
dating-boost release doctor --json
dating-boost data doctor --data-dir .local/dating-boost --json
dating-boost capabilities --json --data-dir .local/dating-boost
```

Migrate before a support session if data doctor returns `needs_migration`.
Select app/runtime on first use or explicit target change. Support sessions are
for real-GUI Canary, diagnostics, or support bundles. Stop before viewing app
content if compatibility fails. Daily ManagedRun reuses the verified setup;
start with `manage start`, then hold `manage run --wait` as described in
`workflows.md`.

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
