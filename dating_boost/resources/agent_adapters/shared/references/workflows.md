# Shared Workflows

These workflow boundaries are shared across host agents. Host-specific adapters
can describe their own command syntax, but they should not fork the product
logic.

## Preflight

Run these compatibility checks after first installation, source/adapter updates,
data migration, permission changes, or for explicit diagnostics. Daily runs in
the same verified environment start with `manage start` and follow its concrete
blocked reason; do not repeat every deep doctor or open a support session.

1. Run the installed adapter/skill doctor and release doctor.
2. Run data doctor; migrate and rerun it before support-session start if needed.
3. Run capabilities and confirm the requested app id/runtime is supported.
4. Confirm host-loop or native harness support before touching app UI.
5. For a real-GUI Canary, explicit diagnostics, or support-bundle collection,
   start a local support session for the host, app id, and exact data dir.
6. Select the app/runtime on first use or an explicit target change; keep the
   existing selection for daily runs and stop on any mismatch.

## ManagedRun (TaShuo mac-ios-app)

For Codex, Claude Code, OpenClaw, and Hermes, the flagship fully managed route
is `ManagedRun` for TaShuo `mac-ios-app`. Other apps/runtimes and existing
managed-session workflows use the compatibility path below. Host-native remains
the default; use `standalone-session` only when the user explicitly requests it.

Before the first run, complete the applicable installation checks, select
`tashuo/mac-ios-app` in the same data dir, require autonomous `user readiness`,
and make the MiniMax model dependencies and key available. The user confirms
duration, ordinary-chat scope, send budget, quiet hours, and nudge once.
Translate that scope into flags; no authorization, goal, availability, or provider
JSON is needed for this product path. Do not silently reduce full management to
drafting or stage-only, and do not require per-message confirmation.

```bash
dating-boost manage start --data-dir .local/dating-boost --app-id tashuo --runtime mac-ios-app --duration-minutes 120 --send-budget 5 --no-nudge --quiet-hours 23:00-08:00 --json
dating-boost manage run --data-dir .local/dating-boost --wait --poll-interval 30 --json
```

`start` creates a durable run; it does not scan, open the GUI, or spawn a worker.
After a successful start, the host immediately holds the foreground `run --wait`
loop. The host/task/process must remain alive; there is no background daemon.
Do not expose the second command as another user setup step.

The user-facing lifecycle is `manage start`, `manage status`, `manage pause`,
`manage resume`, and `manage stop`. Pause/stop take effect before the next GUI
mutation; pending model analysis cannot publish a stale result after a lifecycle
change. Resume restores the same run; the host must restart `manage run --wait`
with the same data dir and run id. Stop returns `relationship_progress_report`.
`run`/`tick` remain public CLI commands; their host-only presentation is not
an access-control boundary.

Model execution errors or observation failures pause the run with a concrete reason. Correct that
reason, then explicitly resume the same run and restart its wait loop. A saved
`prepared_to_click` checkpoint may recover only through the existing fresh
target/binding and exact staged-text checks; do not retype or clear the composer
to force recovery. An `unknown_after_click` blocks start/resume and must use
`manage reconcile` to verify existing evidence. Never resend an unknown attempt;
reconciliation does not send, refund its budget, or restore an unsent tail.

ManagedRun owns the model calls and durable decision/send-attempt checkpoints.
Its live action has four parts: composer observation, exact staging, Return-only
click, and fresh post-send observation. AX verifies the composer; vision verifies
the target and exact new outbound text. It does not consume handcrafted action
requests or call the legacy all-in-one `send_message`. Like/pass, question-gate,
concrete invitations, contact exchange, profile edits, calls, and payments remain
handoff actions. Direct harness send remains executor-internal only.

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

## Session-scoped Managed Runner (Compatibility)

Use this for other apps/runtimes or an existing compatibility workflow; prefer
ManagedRun above for TaShuo mac-ios-app. Use `dating-boost managed-session` only after explicit user start. It is a
session-local wake loop, not a global background agent. `run --wait` should
return `no_work` while idle; hosts should avoid further token use until it
returns `host_work_required`, then execute the included operator work item and
use `dating-boost-host-loop resume` when delegating that work to the host-loop
supervisor. Do not start a fresh `dating-boost-host-loop run` for managed work,
because a fresh run starts a new operator session. After resume or equivalent
manual operator processing, return to `managed-session run --wait`. Tinder
sessions stop when iPhone Mirroring disappears; WeChat sessions pause while
unreadable and continue until user stop.
Full-object management is implemented by the global managed-session/operator
queue: it serially advances multiple candidates by opportunity priority and uses
cursor-based message-list scans. App runtimes must only execute the current work
item. `--management-mode high-throughput` is for explicit testing and never
bypasses send gates.
Before real GUI work, select the target app/runtime with `runtime select` and
keep all harness, host-loop, and managed-session work inside that selected
scope. For TaShuo local Mac iOS app sessions, pass `--harness-runtime
mac-ios-app`; if that flag is omitted under a mac-ios-app scope, the run must
block with `runtime_scope_mismatch` instead of falling back to iPhone Mirroring.
The TaShuo mac-ios-app helper
`python3 scripts/tashuo_mac_ios_managed_smoke.py --data-dir .local/dating-boost --work-dir .local/dating-boost-tashuo-mac-ios-smoke --authorization auth.json --goal goal.json --availability availability.json --json`
is stage-only, but currently stops at
`managed_session_config_confirmation_required` and cannot accept the returned
config. Use it only for preflight/config proposal, then continue through the
generic two-phase managed-session flow after user confirmation.
`managed-session run/tick` returns `relationship_progress_snapshot` for
all-object state, waiting reasons, next wake, and next priority queue while the
session remains active. Stop/final responses should present
`relationship_progress_report` when available.

## Managed Live Send (Compatibility)

Compatibility-path live sends must use `managed-session` or `dating-boost-host-loop`
with `--send-mode live --managed-gui-send`. Direct
`harness <app> send-message --authorization --action-request` is
executor-internal only: it may consume only a `send_message` work item returned
by `operator next` / `automation session step`, or a confirmed confirmation
flow with hashes. Do not handcraft action requests.

## Conversation Targeting

For existing Tinder/Bumble conversations, a visible name may assist
navigation, but managed live send requires one of the app capability's
structural row-to-thread or current-thread visual identity bindings. Raw row
coordinates are compatibility navigation fallbacks, not send identity.

## Unsupported App

Unsupported apps remain unavailable. Do not create runtime app profile files or
expose them in capabilities until fixtures, profile contract, and native or
host-loop behavior are testable.
