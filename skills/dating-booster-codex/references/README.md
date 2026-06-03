# Dating Booster Codex References

The source of truth remains the repository specs under `docs/superpowers/specs/`.
Files in this directory are short operational references for host agents and
must stay compatible with `skill-package.json`.

Required startup command:

```bash
dating-boost capabilities --json --data-dir .local/dating-boost
```

Stop before viewing dating-app content if the capability check fails.

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
