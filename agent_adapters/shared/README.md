# Shared Host-Agent Contract

All host agents should treat Dating Booster as the dating-specific local tool
layer:

1. Complete the adapter/skill doctor, release doctor, data doctor/migration,
   and capabilities sequence in
   `agent_adapters/shared/references/contracts.md#startup` before observing app
   content.
2. Start a support session after the app is known, and keep the selected
   app/runtime fixed for that data dir.
3. Use app profiles as the source of app support truth.
4. Use CLI JSON contracts instead of copying core logic into a host adapter.
5. Keep raw screenshots and OCR text private; normal diagnostics should use
   redacted layout hints.
6. Draft in the host agent, then run Dating Booster policy checks and action
   audit.
7. Use managed live send only through explicit authorization, policy-checked
   action requests, target binding, staged-text verification, and post-action
   verification.

Minimum machine-readable startup gate:

```bash
dating-boost release doctor --json
dating-boost data doctor --data-dir .local/dating-boost --json
dating-boost capabilities --json --data-dir .local/dating-boost
```

Shared references:

- `docs/ARCHITECTURE.md`
- `docs/README.md`
- `app_profiles/README.md`
- `agent_adapters/shared/references/contracts.md`
- `agent_adapters/shared/references/workflows.md`
