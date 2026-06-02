# Production Stage-Mode Runbook

This runbook is for private production smoke only. It keeps Codex as the host
agent and uses iPhone Mirroring only for observe, paste, and verify.

## Preflight

1. Run `dating-boost data doctor --data-dir .local/dating-boost --json`.
2. If the store is not SQLite, run `dating-boost data migrate --data-dir .local/dating-boost --json`.
3. Run `dating-boost capabilities --json --data-dir .local/dating-boost`.
4. Verify `tool_version` is CI-tested for this skill package and that
   `storage_capabilities.storage_backend` is `sqlite`.
5. Stop if capabilities, required schema versions, data doctor, or required
   commands mismatch.
6. Stop and report dirty source state when the local checkout has uncommitted
   source changes during a claimed production smoke.

## Tinder Stage Smoke

Tinder is the only real GUI stage smoke target for this release. Bumble,
WeChat, and Ta Shuo remain app-profile contracts with offline validation only.

1. Start with `dating-boost-host-loop doctor --data-dir .local/dating-boost --app-id tinder --json`.
2. Run `dating-boost-host-loop run --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tinder --send-mode stage --work-dir .local/dating-boost-host-loop --json`.
3. Codex may observe the message list, open the requested thread, paste the
   staged text into the input box, and verify the staged text.
4. The run must stop at `staged_waiting_user_confirmation`.
5. Do not tap Send in the stage smoke.
6. Save replay, audit export, current work item, and staged verification
   artifact before reporting the smoke.

## Artifacts

Required artifacts:

- `dating-boost replay latest --data-dir .local/dating-boost --format json`
- `dating-boost data export --data-dir .local/dating-boost --output export.json --json`
- `.local/dating-boost-host-loop/current_work_item.json`
- The staged verification JSON for the send work item
- The host-loop JSON result showing `staged_waiting_user_confirmation`

## Confirmation Contract

Live send or autonomous send success must bind to either:

- `dating-boost confirmation create`, then `confirmation confirm`, then a valid
  `confirmation validate` result for the same action, target match, payload, and
  precondition.
- An autonomous audit binding emitted by `automation session step` and recorded
  with the post-action result.

Payload changes, target changes, precondition changes, and expired
confirmations must block.
