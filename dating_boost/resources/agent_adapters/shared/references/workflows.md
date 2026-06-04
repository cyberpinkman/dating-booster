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

## Subscription Paywall Recovery

If Tinder shows a subscription, Gold, Likes You, plan-selection, or recurring
billing paywall, the host must treat it as accidental navigation. Do not ask the
user whether to subscribe, do not discuss plans, and do not click purchase or
continue controls. Immediately run the app-specific dismiss action, then
re-navigate to a verified chat or profile path before any draft staging or live
send.

## Feedback Survey Recovery

If Tinder shows a feedback survey after navigation or send verification, the host
must treat it as a recoverable overlay. Run the app-specific
`dismiss-feedback-survey` action through the ignore/no-rating path; the result
must report `rating_submitted: false`.

## Conversation Targeting

For existing Tinder conversations, prefer visible-name or target-binding
navigation. Raw row coordinates are compatibility fallbacks only after the
visible message-list target is clearly stable.

## Unsupported App

Unsupported apps are roadmap candidates only. Do not create runtime app profile
files or expose them in capabilities until fixtures, profile contract, and
native or host-loop behavior are testable.
