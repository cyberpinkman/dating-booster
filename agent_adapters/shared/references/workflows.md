# Shared Workflows

These workflow boundaries are shared across host agents. Host-specific adapters
can describe their own command syntax, but they should not fork the product
logic.

## Preflight

1. Run capabilities.
2. Confirm the requested app id is supported.
3. Confirm host-loop or native harness support before touching app UI.
4. Start a local support session for the host, app id, and exact data dir that
   subsequent CLI, harness, or host-loop commands will use.
5. Stop on unsupported app ids.

## Observe And Draft

1. Observe message list or thread through the app-specific supported path.
2. Normalize observation JSON.
3. Build context.
4. Generate draft.
5. Run policy checks.
6. Stage only when the host has exact target and text evidence.
7. Keep `--data-dir` on commands so the active support session records redacted
   command boundaries, topic provenance, and clipboard fingerprints.
8. If a host-loop uses a separate data dir, start/stop/bundle support logging in
   that host-loop data dir; the main workflow bundle will not contain those
   timeline events.
9. Do not run `data migrate` or `data delete` on the same data dir after support
   session start and before support bundle export.

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

## Session-scoped Managed Runner

Use `dating-boost managed-session` only after explicit user start. It is a
session-local wake loop, not a global background agent. `run --wait` should
return `no_work` while idle; hosts should avoid further token use until it
returns `host_work_required`, then execute the included operator work item and
use `dating-boost-host-loop resume` when delegating that work to the host-loop
supervisor. Do not start a fresh `dating-boost-host-loop run` for managed work,
because a fresh run starts a new operator session. After resume or equivalent
manual operator processing, return to `managed-session run --wait`. Tinder
sessions stop when iPhone Mirroring disappears; WeChat sessions pause while
unreadable and continue until user stop.

## Managed Live Send

Agent-facing live sends must use `managed-session` or `dating-boost-host-loop`
with `--send-mode live --managed-gui-send`. Direct
`harness <app> send-message --authorization --action-request` is
executor-internal only: it may consume only a `send_message` work item returned
by `operator next` / `automation session step`, or a confirmed confirmation
flow with hashes. Do not handcraft action requests.

## Conversation Targeting

For existing Tinder conversations, prefer visible-name or target-binding
navigation. Raw row coordinates are compatibility fallbacks only after the
visible message-list target is clearly stable.

## Unsupported App

Unsupported apps are roadmap candidates only. Do not create runtime app profile
files or expose them in capabilities until fixtures, profile contract, and
native or host-loop behavior are testable.
