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
