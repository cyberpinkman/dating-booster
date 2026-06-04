# Shared Workflows

These workflow boundaries are shared across host agents. Host-specific adapters
can describe their own command syntax, but they should not fork the product
logic.

## Preflight

1. Run capabilities.
2. Confirm the requested app id is supported.
3. Confirm host-loop or native harness support before touching app UI.
4. Stop on unsupported app ids.

## Observe And Draft

1. Observe message list or thread through the app-specific supported path.
2. Normalize observation JSON.
3. Build context.
4. Generate draft.
5. Run policy checks.
6. Stage only when the host has exact target and text evidence.

## Unopened Match

For a matched but unopened conversation, the host can open one match, read
visible profile context, create an opener, send through the same gated flow, and
return to the message list for the next candidate. It does not need to count all
unopened matches before beginning work.

## Unsupported App

Unsupported apps are roadmap candidates only. Do not create runtime app profile
files or expose them in capabilities until fixtures, profile contract, and
native or host-loop behavior are testable.
