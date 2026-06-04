# Start Prompts

Use these user-facing prompts to trigger the stable Codex-host workflows.

## Tinder Stage Loop

“开始 Tinder host loop，默认 stage 模式。”

Expected host behavior:

1. Run `dating-boost-host-loop doctor --data-dir .local/dating-boost --app-id tinder --json`.
2. If configuration is missing, run `dating-boost-host-loop init`.
3. Run `dating-boost-host-loop run --send-mode stage`.
4. Observe the requested Tinder screen, write scoped work-dir files, and stop before clicking send.

## Resume

“继续上次 Tinder host loop。”

Expected host behavior:

1. Run `dating-boost-host-loop status`.
2. Use `dating-boost-host-loop resume` if a session is active or recoverable.
3. Do not rely on Codex conversation memory; use local state, replay, and reports.

## Live Ordinary Sends

“进入 live 模式，但只发送普通聊天消息。”

Expected host behavior:

1. Confirm the user's explicit authorization.
2. Run `dating-boost-host-loop run --send-mode live`.
3. Stage and verify text before sending.
4. Record `succeeded` only after a fresh sent-bubble observation.
5. Handoff for appointment details, contact exchange, profile edits, likes, unmatches, reports, or unclear verification.
