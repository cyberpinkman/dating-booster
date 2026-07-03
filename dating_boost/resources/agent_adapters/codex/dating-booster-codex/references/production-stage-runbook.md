# Production Stage-Mode Runbook

This runbook is for private production smoke only. It keeps Codex as the host
agent and uses iPhone Mirroring only for observe, paste, and verify.

## Preflight

0. Run `dating-boost release doctor --json` and stop if it is not `ok`.
1. Run `dating-boost data doctor --data-dir .local/dating-boost --json`.
2. If the store is not SQLite, run `dating-boost data migrate --data-dir .local/dating-boost --json`.
3. Run `dating-boost capabilities --json --data-dir .local/dating-boost`.
4. Verify `tool_version` is CI-tested for this skill package and that
   `storage_capabilities.storage_backend` is `sqlite`.
5. Verify `storage_capabilities.encrypted_default` is true and data doctor
   reports `encryption.status: encrypted`.
6. Run `dating-boost safety status --data-dir .local/dating-boost --json` and
   stop if it is paused.
7. Select the target runtime before app-specific checks. For Tinder, run `dating-boost runtime select --data-dir .local/dating-boost --app-id tinder --runtime default --json`, then `dating-boost harness doctor --app-id tinder --data-dir .local/dating-boost --json` and
   stop if iPhone Mirroring is locked, unavailable, or cannot be
   screenshot/OCR checked. For macOS WeChat, first run `dating-boost runtime select --data-dir .local/dating-boost --app-id wechat --runtime default --json`, then run
   `dating-boost harness doctor --app-id wechat --data-dir .local/dating-boost --window-title WeChat --json`
   and stop if WeChat cannot be activated, screenshot, or OCR checked.
8. Run `dating-boost harness tinder launch --dry-run --data-dir .local/dating-boost --json` and
   `dating-boost harness tinder open-profile --dry-run --data-dir .local/dating-boost --json` to verify the
   safe launch/profile-tab navigation plan.
   Run `dating-boost harness tinder observe --output-dir .local/dating-boost-harness --data-dir .local/dating-boost --json`
   once iPhone Mirroring is unlocked to record redacted page/layout hints.
   Also dry-run `dating-boost harness tinder workflow self-profile-read --options-json tinder-self-profile-options.json --dry-run --data-dir .local/dating-boost --json`
   `dating-boost harness tinder workflow chat-read-match-profile --options-json tinder-chat-profile-options.json --dry-run --data-dir .local/dating-boost --json`,
   `dating-boost harness tinder workflow new-match-open --options-json tinder-new-match-open-options.json --dry-run --data-dir .local/dating-boost --json`,
   and `dating-boost harness tinder workflow new-match-read-profile --options-json tinder-new-match-profile-options.json --dry-run --data-dir .local/dating-boost --json`
   before using those chains on the real GUI.
9. Stop if capabilities, required schema versions, data doctor, harness doctor, or required
   commands mismatch.
10. Stop and report dirty source state when the local checkout has uncommitted
   source changes during a claimed production smoke.

## Tinder/Bumble Stage Smoke

Tinder, WeChat, Bumble, and TaShuo have host-loop GUI smoke coverage for their
supported send surfaces. Bumble supports managed ordinary chat send, but
Opening Move autonomous send remains unsupported. TaShuo supports managed
ordinary chat send, but current harness question-gate staging/sending is not
supported.
Hinge and other apps remain roadmap candidates until runtime profiles,
fixtures, and harness or host-loop tests prove support.
WeChat has a macOS desktop harness for launch, redacted observation, and draft
staging, but no WeChat-specific profile navigation chain.

1. Start with `dating-boost-host-loop doctor --data-dir .local/dating-boost --app-id tinder --json`.
2. If the user profile needs refresh, run `dating-boost harness tinder open-profile --launch-if-needed --output-dir .local/dating-boost-harness --data-dir .local/dating-boost --json`; stop if it returns `blocked` or `needs_verification`.
   Then run `dating-boost harness tinder workflow self-profile-read --options-json tinder-self-profile-options.json --output-dir .local/dating-boost-harness --data-dir .local/dating-boost --json` only after a fresh observation confirms the self profile page.
   Save the before/after screenshots and author the user profile observation from visible content only.
3. Run `dating-boost-host-loop run --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tinder --send-mode stage --work-dir .local/dating-boost-host-loop --json`.
4. Codex must run `dating-boost harness tinder observe --output-dir .local/dating-boost-harness --data-dir .local/dating-boost --json`
   before selecting a bounded navigation chain and again after each chain when
   collecting smoke artifacts.
5. Codex should use `dating-boost harness tinder action prepare-message-page --data-dir .local/dating-boost --output-dir .local/dating-boost-harness --json`
   before visual message-list planning. It may then use
   `dating-boost harness tinder action open-conversation --options-json tinder-open-row-options.json --data-dir .local/dating-boost --json`,
   and `dating-boost harness tinder action open-thread-profile --data-dir .local/dating-boost --json` for
   bounded navigation after each screen is freshly observed. For match profile
   refreshes, it may use `dating-boost harness tinder workflow chat-read-match-profile --options-json tinder-chat-profile-options.json --output-dir .local/dating-boost-harness --data-dir .local/dating-boost --json`
   after confirming the chat page layout.
   For unopened matches, use `dating-boost harness tinder workflow new-match-open --options-json tinder-new-match-open-options.json --output-dir .local/dating-boost-harness --data-dir .local/dating-boost --json`
   or `dating-boost harness tinder workflow new-match-read-profile --options-json tinder-new-match-profile-options.json --output-dir .local/dating-boost-harness --data-dir .local/dating-boost --json`.
   Process one unopened match at a time; after a managed opener send, return
   with `dating-boost harness tinder action return-to-chats --output-dir .local/dating-boost-harness --data-dir .local/dating-boost --json`
   before selecting the next visible unopened match.
6. Codex may observe the message list and open the requested thread. Stage mode
   should then use `dating-boost-host-loop` auto staging or
   `dating-boost harness tinder stage-draft --text-file tinder-draft.txt --data-dir .local/dating-boost --json`
   to paste and verify the staged text without clicking Send.
   If the thread was already open, use `current_thread_visual_identity`; when
   that visual identity mismatches and same-target `message_list_evidence`
   carries a row visual anchor, the harness may return to the message list,
   relocate the row, reopen it, and retry target verification before staging.
7. The run must stop at `staged_waiting_user_confirmation`.
8. Do not tap Send in the stage smoke.
9. Save replay, audit export, current work item, and staged verification
   artifact before reporting the smoke.

For Bumble ordinary-chat stage smoke, use the same stage-mode host-loop shape
with `--app-id bumble`. Use
`dating-boost harness bumble action prepare-message-page --data-dir .local/dating-boost --output-dir .local/dating-boost-harness --json`
before visual chat-list planning, then prefer
`dating-boost harness bumble action open-conversation --options-json bumble-open-row-options.json --data-dir .local/dating-boost --json`
where the options JSON carries `visible_name` or `target_binding` for OCR-readable
rows. The harness locates the row with OCR TSV and verifies the opened ordinary
conversation. For non-OCR rows, carry `chat_list_row_to_thread` structural
binding plus `message_list_evidence.visual_anchor_hash` and
`visual_anchor_region`; the harness scans the current chat list for that row
anchor before opening. Use fixed `row_index` only as a fallback; Opening Move
prompts are observation/review surfaces and are not eligible for autonomous send.
If the intended thread is already open, use `current_thread_visual_identity`
with `thread_evidence.visual_anchor_hash` as target verification evidence; it
does not replace staged-text OCR or post-send outbound verification. If that
visual identity mismatches and same-target `message_list_evidence` carries a row
visual anchor, the harness may return to the chat list, relocate the row,
reopen it, and retry target verification before staging.
Bumble live send requires `chat_list_row_to_thread` or
`current_thread_visual_identity` structural target binding; OCR-readable
`visible_name` alone is navigation assistance, not live-send target proof.
Bumble stage smoke should use the same host-loop auto staging or
`dating-boost harness bumble stage-draft --text-file bumble-draft.txt --data-dir .local/dating-boost --json`
after the target ordinary conversation is open. It must stop after staged-text
verification and must not click Send.

For a bounded preflight wrapper around the same Tinder/Bumble managed stage
surface, run:

```bash
python3 scripts/iphone_mirroring_managed_smoke.py --app-id tinder --data-dir .local/dating-boost --work-dir .local/dating-boost-iphone-smoke --authorization auth.json --goal goal.json --availability availability.json --json
python3 scripts/iphone_mirroring_managed_smoke.py --app-id bumble --data-dir .local/dating-boost --work-dir .local/dating-boost-iphone-smoke --authorization auth.json --goal goal.json --availability availability.json --json
```

The wrapper runs skill doctor, release doctor, data doctor/migrate, capabilities
compatibility checks, and verifies direct harness scope is executor-internal
only before starting real GUI work. It does not auto-confirm managed-session
config. If it returns
`managed_session_config_confirmation_required`, inspect `proposed_config` and
rerun with `--accept-managed-session-config` only after explicit confirmation.
If iPhone Mirroring is locked or unavailable, record that blocked reason and
skip real-device smoke.

## macOS WeChat Stage Smoke

Use this only for a user-authorized WeChat test chat. Desktop chat history can
expose unrelated personal content, so keep the test boundary explicit.

1. Run `dating-boost runtime select --data-dir .local/dating-boost --app-id wechat --runtime default --json`.
2. Run `dating-boost harness doctor --app-id wechat --data-dir .local/dating-boost --window-title WeChat --json`.
3. Run `dating-boost harness wechat launch --data-dir .local/dating-boost --dry-run --json`, then execute
   launch only if the plan is expected.
4. Run `dating-boost harness wechat observe --data-dir .local/dating-boost --output-dir .local/dating-boost-harness --json`.
5. Convert visible post-boundary chat content to an observation JSON and run
   `dating-boost memory ingest-observation`, `dating-boost context build`, and
   `dating-boost policy check-draft`.
6. If the draft passes policy, write the approved draft to a local text file
   and run `dating-boost harness wechat stage-draft --text-file wechat-draft.txt --data-dir .local/dating-boost --dry-run --json`.
7. Execute `stage-draft` only after confirming the active WeChat chat input is
   the intended target. Real staging must include `--data-dir .local/dating-boost`
   so the global safety pause can block paste. Stage mode must not press Enter
   or click Send.
7. The host must visually verify exact staged text before any manual send.
8. Record the final action result only from a fresh post-action observation.

## WeChat Managed Live Smoke

Managed live smoke is opt-in and should use a dedicated test contact.

1. Confirm the safety switch is not paused.
2. Use an authorization JSON with `app_id: wechat`, `live_send: true`,
   `autonomous_send: true`, `allowed_actions: ["send_message"]`, unexpired
   timestamps, and `requires_post_action_verification: true`.
3. Run `dating-boost-host-loop run --data-dir .local/dating-boost
   --authorization wechat-auth.json --goal goal.json --availability
   availability.json --app-id wechat --send-mode live --managed-gui-send
   --work-dir .local/dating-boost-host-loop --json`.
4. Direct `harness wechat send-message --authorization --action-request` is
   executor-internal only. Use it only with a system-generated work item or
   confirmed confirmation-flow hashes; do not handcraft action requests.
5. Record `succeeded` only when the action request is policy-checked and
   hash-bound to the draft, the target chat is verified, the harness returns
   exact staged-text verification, the input is cleared after pressing Return,
   the outbound bubble is verified, and a `post_action_observation_id` exists.

## Tinder Live Smoke

Managed live smoke is opt-in and requires a dedicated Tinder test account. It
is not the default public workflow.

1. Confirm the safety switch is not paused.
2. Use an authorization JSON with `app_id: tinder`, `live_send: true`,
   `autonomous_send: true`, `allowed_actions: ["send_message"]`, unexpired
   timestamps, and `requires_post_action_verification: true`.
3. Ensure the operator work item carries `chat_list_row_to_thread` or
   `current_thread_visual_identity` structural target binding. `visible_name`
   or header OCR alone is insufficient for Tinder live send.
4. Run `dating-boost-host-loop run --data-dir .local/dating-boost
   --authorization tinder-auth.json --goal goal.json --availability
   availability.json --app-id tinder --send-mode live --managed-gui-send
   --work-dir .local/dating-boost-host-loop --json`.
5. Direct `harness tinder send-message --authorization --action-request` is
   executor-internal only. Use it only with a system-generated work item or
   confirmed confirmation-flow hashes; do not handcraft action requests.
6. Record `succeeded` only when the action request is policy-checked and
   hash-bound to the draft, the target chat is verified, the harness returns
   staged-text OCR verification, the outbound bubble is verified, and a
   `post_action_observation_id` exists.
7. Record `unknown`, not `succeeded`, if post-action evidence is missing,
   stale, truncated, or mismatched.
8. Save only redacted replay, export, diagnostic bundle, and smoke result.

## Artifacts

Required artifacts:

- `dating-boost replay latest --data-dir .local/dating-boost --format json`
- `dating-boost data export --data-dir .local/dating-boost --output export.json --json`
- `.local/dating-boost-host-loop/current_work_item.json`
- The staged verification JSON for the send work item
- The host-loop JSON result showing `staged_waiting_user_confirmation`
- For live smoke only: redacted diagnostic bundle and the action result showing
  post-action verification.

## Confirmation Contract

Live send or autonomous send success must bind to either:

- `dating-boost confirmation create`, then `confirmation confirm`, then a valid
  `confirmation validate` result for the same action, target match, payload, and
  precondition.
- An autonomous audit binding emitted by `automation session step` and recorded
  with the post-action result.

Payload changes, target changes, precondition changes, and expired
confirmations must block.
