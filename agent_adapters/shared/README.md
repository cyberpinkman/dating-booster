# Shared Host-Agent Contract

All host agents should treat Dating Booster as the dating-specific local tool
layer:

1. Run `dating-boost capabilities --json --data-dir ...` before observing dating
   app content.
2. Use app profiles as the source of app support truth.
3. Use CLI JSON contracts and future MCP tools instead of copying core logic.
4. Keep raw screenshots and OCR text private; normal diagnostics should use
   redacted layout hints.
5. Draft in the host agent, then run Dating Booster policy checks and action
   audit.
6. Use managed live send only through explicit authorization, policy-checked
   action requests, target binding, staged-text verification, and post-action
   verification.

Shared references:

- `docs/ARCHITECTURE.md`
- `docs/README.md`
- `app_profiles/README.md`
- `agent_adapters/shared/references/contracts.md`
- `agent_adapters/shared/references/workflows.md`
