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
  navigation, and Opening Move observation without draft staging or live send.

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
- `post_send_verification`: rules for recording a send result.
- `known_gui_pitfalls`: app-specific failure modes that should stop or slow a
  host run.
- `unsupported_actions`: high-risk or unavailable actions for the app.

## Native Harness Field

`native_gui_harness` is required for runtime app profiles. Unsupported apps do
not get placeholder profiles. Current backends:

- `iphone_mirroring_macos`: macOS iPhone Mirroring harness used by Tinder.
- `macos_wechat_desktop`: desktop WeChat window harness used by WeChat.

Every native harness block should define:

- `backend`: adapter id implemented in `dating_boost/core/gui_harness.py`.
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
  staged text is exactly verified, and the outbound bubble is verified from
  fresh post-action evidence.

## Adding A New Dating App

Use `docs/ARCHITECTURE.md` before expanding app support. App profiles are one
axis of the architecture; do not mix a new app contract with host-agent adapter,
goal-type, or memory-evolution changes unless the same product increment truly
requires it.

1. Create `app_profiles/<app_id>.json` with the required fields above.
2. Do not create a placeholder profile for an unsupported app. Keep roadmap
   candidates in `docs/ARCHITECTURE.md` until the runtime path is testable.
3. Add `app_id` to `supported_app_profiles` only when the profile is backed by
   fixtures and tests. Add it to `host_loop_app_profiles` only after
   `host_loop_supported` is true and preflight/tests prove it can run.
4. Add fixtures that represent message-list and thread observations.
5. If native GUI support is needed, implement the adapter in
   `dating_boost/core/gui_harness.py` and expose app-specific CLI commands in
   `dating_boost/cli.py`.
6. Add capability flags and supported commands in
   `dating_boost/core/capabilities.py`.
7. Add unit tests for classification, dry-run behavior, redaction, blocked
   screens/actions, and success-path command construction.
8. Update the Codex skill and runbook references before publishing.

## Review Checklist

- The profile does not authorize private APIs, bypasses, anti-detection logic,
  or scale-out behavior.
- Unsupported apps are absent from `app_profiles/`, capabilities, and native
  harness commands.
- Managed live send defaults to off and is represented as a conditional
  exception, not by removing `send` from default blocked actions.
- Latest inbound messages are clearly separated from old visible context.
- Draft staging requires exact staged-text verification.
- Raw OCR text is not exposed in normal JSON output when it could contain
  private chat history.
- Unsupported actions include app-specific high-risk operations such as likes,
  unmatches, reports, calls, payments, contact exchange, or profile edits.
