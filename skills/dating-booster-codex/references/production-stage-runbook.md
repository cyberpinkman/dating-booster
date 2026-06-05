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
7. For Tinder, run `dating-boost harness doctor --app-id tinder --json` and
   stop if iPhone Mirroring is locked, unavailable, or cannot be
   screenshot/OCR checked. For macOS WeChat, run
   `dating-boost harness doctor --app-id wechat --window-title WeChat --json`
   and stop if WeChat cannot be activated, screenshot, or OCR checked.
8. Run `dating-boost harness tinder launch --dry-run --json` and
   `dating-boost harness tinder open-profile --dry-run --json` to verify the
   safe launch/profile-tab navigation plan.
   Run `dating-boost harness tinder observe --output-dir .local/dating-boost-harness --json`
   once iPhone Mirroring is unlocked to record redacted page/layout hints.
   Also dry-run `dating-boost harness tinder workflow self-profile-read --options-json tinder-self-profile-options.json --dry-run --json`
   `dating-boost harness tinder workflow chat-read-match-profile --options-json tinder-chat-profile-options.json --dry-run --json`,
   `dating-boost harness tinder workflow new-match-open --options-json tinder-new-match-open-options.json --dry-run --json`,
   and `dating-boost harness tinder workflow new-match-read-profile --options-json tinder-new-match-profile-options.json --dry-run --json`
   before using those chains on the real GUI.
9. Stop if capabilities, required schema versions, data doctor, harness doctor, or required
   commands mismatch.
10. Stop and report dirty source state when the local checkout has uncommitted
   source changes during a claimed production smoke.

## Tinder Stage Smoke

Tinder, WeChat, and Bumble have host-loop GUI smoke coverage for their supported
send surfaces. Bumble supports managed ordinary chat send, but Opening Move
autonomous send remains unsupported. Ta Shuo, Hinge, and other apps remain
roadmap candidates until runtime profiles, fixtures, and harness or host-loop
tests prove support.
WeChat has a macOS desktop harness for launch, redacted observation, and draft
staging, but no WeChat-specific profile navigation chain.

1. Start with `dating-boost-host-loop doctor --data-dir .local/dating-boost --app-id tinder --json`.
2. If the user profile needs refresh, run `dating-boost harness tinder open-profile --launch-if-needed --output-dir .local/dating-boost-harness --json`; stop if it returns `blocked` or `needs_verification`.
   Then run `dating-boost harness tinder workflow self-profile-read --options-json tinder-self-profile-options.json --output-dir .local/dating-boost-harness --json` only after a fresh observation confirms the self profile page.
   Save the before/after screenshots and author the user profile observation from visible content only.
3. Run `dating-boost-host-loop run --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tinder --send-mode stage --work-dir .local/dating-boost-host-loop --json`.
4. Codex must run `dating-boost harness tinder observe --output-dir .local/dating-boost-harness --json`
   before selecting a bounded navigation chain and again after each chain when
   collecting smoke artifacts.
5. Codex may use `dating-boost harness tinder action open-chats --json`,
   `dating-boost harness tinder action open-conversation --options-json tinder-open-row-options.json --json`,
   and `dating-boost harness tinder action open-thread-profile --json` for
   bounded navigation after each screen is freshly observed. For match profile
   refreshes, it may use `dating-boost harness tinder workflow chat-read-match-profile --options-json tinder-chat-profile-options.json --output-dir .local/dating-boost-harness --json`
   after confirming the chat page layout.
   For unopened matches, use `dating-boost harness tinder workflow new-match-open --options-json tinder-new-match-open-options.json --output-dir .local/dating-boost-harness --json`
   or `dating-boost harness tinder workflow new-match-read-profile --options-json tinder-new-match-profile-options.json --output-dir .local/dating-boost-harness --json`.
   Process one unopened match at a time; after a managed opener send, return
   with `dating-boost harness tinder action return-to-chats --output-dir .local/dating-boost-harness --json`
   before selecting the next visible unopened match.
6. Codex may observe the message list, open the requested thread, paste the
   staged text into the input box, and verify the staged text.
7. The run must stop at `staged_waiting_user_confirmation`.
8. Do not tap Send in the stage smoke.
9. Save replay, audit export, current work item, and staged verification
   artifact before reporting the smoke.

## macOS WeChat Stage Smoke

Use this only for a user-authorized WeChat test chat. Desktop chat history can
expose unrelated personal content, so keep the test boundary explicit.

1. Run `dating-boost harness doctor --app-id wechat --window-title WeChat --json`.
2. Run `dating-boost harness wechat launch --dry-run --json`, then execute
   launch only if the plan is expected.
3. Run `dating-boost harness wechat observe --output-dir .local/dating-boost-harness --json`.
4. Convert visible post-boundary chat content to an observation JSON and run
   `dating-boost workflow draft`.
5. If the draft passes policy, write the approved draft to a local text file
   and run `dating-boost harness wechat stage-draft --text-file wechat-draft.txt --dry-run --json`.
6. Execute `stage-draft` only after confirming the active WeChat chat input is
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
3. Run `dating-boost harness wechat send-message --text-file wechat-draft.txt
   --data-dir .local/dating-boost --authorization wechat-auth.json
   --action-request action-request.json --dry-run --json`.
4. For a host-loop run, use `dating-boost-host-loop run ... --app-id wechat
   --send-mode live --managed-gui-send`.
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
3. Run `dating-boost harness tinder send-message --text-file tinder-draft.txt
   --data-dir .local/dating-boost --authorization tinder-auth.json
   --action-request action-request.json --dry-run --json`.
4. For a host-loop run, use `dating-boost-host-loop run ... --app-id tinder
   --send-mode live --managed-gui-send`.
5. Record `succeeded` only when the action request is policy-checked and
   hash-bound to the draft, the target chat is verified, the harness returns
   staged-text OCR verification, the outbound bubble is verified, and a
   `post_action_observation_id` exists.
6. Record `unknown`, not `succeeded`, if post-action evidence is missing,
   stale, truncated, or mismatched.
7. Save only redacted replay, export, diagnostic bundle, and smoke result.

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
