# App Profile Contract

App profiles are the product-level contract for adapting Dating Booster to a
specific dating or chat app. They define what can be observed, how a thread is
identified, how draft staging must be verified, which GUI pitfalls are known,
and which actions remain unsupported.

The formal schema lives at `schemas/app_profile.schema.json`; tests validate
every `app_profiles/*.json` file against the same required contract shape.

## Files

- `tinder.json`: Tinder host-loop, iPhone Mirroring navigation, and
  explicitly authorized managed live-send contract.
- `wechat.json`: macOS WeChat desktop observation, draft-staging, and
  explicitly authorized managed live-send contract.
- `bumble.json`: Bumble iPhone Mirroring launch, observation, profile/chat
  navigation, role-sensitive Opening Move observation/drafting policy, and
  explicitly authorized managed ordinary-chat live-send contract.

## Required Fields

- `schema_version`: current profile schema version.
- `app_id`: stable lowercase id used by CLI, capabilities, host loop, and tests.
- `display_name`: human-readable app name.
- `support_level`: current implementation level such as `native_observation`,
  `native_navigation`, `native_draft_staging`, or `managed_live_send`.
- `host_loop_supported`: whether `dating-boost-host-loop` may run this app.
- `host_loop_send_modes`: allowed host-loop send modes for this app. `live`
  means a gated live-send path exists; it does not mean live send is enabled by
  default.
- `message_list_observation`: rules for visible conversation-list scanning.
- `thread_observation`: rules for thread-level observation and turn boundaries.
- `stage_send_verification`: rules for staged draft verification.
- `adapter`: runtime adapter backend/module/class/default-window-title.
- `cli_aliases`: optional compatibility CLI commands generated from profile
  metadata, such as Tinder's `open-profile` alias for `open_profile`.
- `capabilities`: supported actions, workflows, send modes, stage actions, and
  live actions as consumed by the registry.
- `selectors`: app-owned coordinates/selectors and blocked native actions.
- `target_binding`: generic target-binding requirements, target-specific marker
  policy, generic-marker blacklist, and visual-only verification boundary.
- `live_send_requirements`: exact evidence required before/after live send.
- `managed_session`: profile-owned precheck failure status and recovery action.
- `special_policies`: app-specific social rules such as Bumble Opening Move.
- `post_send_verification`: rules for recording a send result.
- `known_gui_pitfalls`: app-specific failure modes that should stop or slow a
  host run.
- `unsupported_actions`: high-risk or unavailable actions for the app.

## Native Harness Field

`native_gui_harness` remains the legacy coordinate/source declaration for
runtime app profiles; v2 profiles also expose normalized `adapter`,
`capabilities`, `selectors`, `target_binding`, and `live_send_requirements`
blocks for registry consumers. Unsupported apps do not get placeholder
profiles. Current backends:

- `iphone_mirroring_macos`: macOS iPhone Mirroring harness used by Tinder and
  Bumble.
- `macos_wechat_desktop`: desktop WeChat window harness used by WeChat.

Every native harness block should define:

- `backend`: platform backend consumed by the app adapter.
- `supported_stage_actions`: exact action names exposed by the harness.
- `supported_live_actions`: exact high-risk live actions exposed only through
  explicit authorization gates.
- Navigation or staging sections that define intent, prerequisites, and
  verification requirements.
- `blocked_actions`: actions blocked by default. If an action has a conditional
  live-send exception, document it separately under `live_send`.

## Support Levels

- Native observation: screenshot/OCR/layout hints exist, with redaction.
- Native navigation: app can be moved through safe read-only screens.
- Native draft staging: app can paste a prepared draft into an input box.
- Managed live send: app can execute a tightly gated `send_message` only when
  the profile exposes `live_send`, the CLI receives explicit authorization,
  safety is active, a policy-checked action request is bound to the target chat,
  the target binding includes app-specific identity evidence, staged text is
  exactly verified, and the outbound bubble is verified from fresh post-action
  evidence. Visual-only button or bubble evidence is never exact-text
  verification.

## Adding A New Dating App

Use `docs/ARCHITECTURE.md` before expanding app support. App profiles are one
axis of the architecture; do not mix a new app contract with host-agent adapter,
goal-type, or memory-evolution changes unless the same product increment truly
requires it.

1. Create `app_profiles/<app_id>.json` with schema v2 fields above.
2. Do not create a placeholder profile for an unsupported app. Keep roadmap
   candidates in `docs/ARCHITECTURE.md` until the runtime path is testable.
3. Add `dating_boost/apps/<app_id>/adapter.py` implementing the standard
   adapter methods: `doctor`, `launch`, `observe`, `run_action`, `run_workflow`,
   `stage_draft`, `send_message`, `target_binding_policy`, and
   `required_send_evidence`.
4. Register the adapter in `dating_boost/apps/registry.py`. Capabilities, CLI
   harness app commands, managed sessions, and host loop must derive support
   from that registry/profile pair.
5. If the app needs a backward-compatible harness command, declare it in
   `cli_aliases` rather than adding an app-specific argparse branch.
6. Add fixtures that represent message-list and thread observations.
7. Add unit tests for classification, dry-run behavior, redaction, blocked
   screens/actions, target binding, send evidence, and success-path command
   construction.
8. Use `dating-boost harness <app_id> action|workflow --options-json <path>`
   for app-specific parameters. Do not add new app-specific argparse flags to
   global CLI code.
9. Update the Codex skill and runbook references before publishing.

## Review Checklist

- The profile does not authorize private APIs, bypasses, anti-detection logic,
  or scale-out behavior.
- Unsupported apps are absent from `app_profiles/`, capabilities, and native
  harness commands.
- Managed live send defaults to off and is represented as a conditional
  exception, not by removing `send` from default blocked actions.
- Latest inbound messages are clearly separated from old visible context.
- Draft staging requires exact staged-text verification. For Bumble, paste is
  primary and direct typing is only a fallback; OCR must still verify the exact
  payload text before Send.
- Raw OCR text is not exposed in normal JSON output when it could contain
  private chat history.
- Unsupported actions include app-specific high-risk operations such as likes,
  unmatches, reports, calls, payments, contact exchange, or profile edits.
