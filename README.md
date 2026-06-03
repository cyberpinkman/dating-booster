# dating-booster

Local-first GUI automation experiments for dating workflows.

## Boundary statement

这是一个不使用私有 API、不做绕过、由用户本地授权运行的 GUI automation experiment；它仍可能违反目标 App 的条款，并可能导致账号封禁。项目不提供规避检测或规模化滥用能力。

## Default behavior

- Allowed by default: observe, summarize, draft replies, and paste drafts.
- Blocked by default: sending messages, liking profiles, super-likes, unmatching, reporting, profile edits, and proposing meetings.
- High-risk actions require explicit human confirmation unless experimental autonomous mode is enabled for a single action.
- Autonomous mode is off by default. Users can explicitly enable it after reading and accepting the risk.
- Public production defaults are macOS-only, encrypted local storage, stage-first GUI operation, and local-only diagnostics.

## Autonomous mode

Autonomous mode is experimental and high-risk. It is controlled by an explicit local switch and remains disabled by default. Enabling it is not a claim that a target app permits automation; it only means the local tool is allowed to execute high-risk actions after the user has accepted the risk.

## CLI

```bash
python3 -m dating_boost.cli observe
python3 -m dating_boost.cli send_message
python3 -m dating_boost.cli send_message --autonomous
```

The action gate does not execute GUI actions. It only reports whether a local
workflow is allowed to proceed.

## Public production install

The public production channel is `1.0.0-rc.1`. Install from PyPI or from the
GitHub release artifact, then run the local release and skill checks:

```bash
python3 -m pip install "dating-booster==1.0.0rc1"
dating-boost release doctor --json
dating-boost data doctor --data-dir .local/dating-boost --json
dating-boost capabilities --data-dir .local/dating-boost --json
```

On macOS, Dating Booster encrypts SQLite payloads by default. The preferred
production key provider is macOS Keychain; CI and local tests may set
`DATING_BOOST_KEY_PROVIDER=local`. Backups read
`DATING_BOOST_RECOVERY_PASSPHRASE` from the environment; restore automation can
use `--recovery-passphrase-file`. Use:

```bash
dating-boost data migrate --data-dir .local/dating-boost --json
dating-boost data backup --data-dir .local/dating-boost --output dating-boost-backup.zip --json
dating-boost data rekey --data-dir .local/dating-boost --json
dating-boost diagnostics bundle --data-dir .local/dating-boost --output diagnostics.zip --json
```

The daemon is a local supervisor only. It owns locks, heartbeat, recovery, and
kill-switch state; it does not observe screens or click apps:

```bash
dating-boost daemon install --data-dir .local/dating-boost --json
dating-boost daemon status --data-dir .local/dating-boost --json
dating-boost safety pause --data-dir .local/dating-boost --reason manual-stop --json
```

Default to `--send-mode stage`. `--send-mode live` requires explicit
authorization with `live_send: true`, an unpaused safety switch, staged-text
verification, and post-action verification.

## Agent-native Codex workflow

Dating Booster can also be used as a lightweight local tool layer for a host
agent such as Codex. In this mode, Codex can use computer use plus iPhone
Mirroring after the user authorizes the Mac to operate the iPhone screen.
Dating Booster does not need to own the LLM call; it provides local
memory/context/policy/workflow contracts and host-executed action audit.

Before any host agent observes visible dating app content, run:

```bash
python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost
```

The host agent may process visible dating app content, screenshots, profile
text, conversation text, and generated drafts. Users should only run this mode
if they accept that privacy boundary. High-risk actions still require explicit
policy checks and user confirmation unless autonomous mode is deliberately
enabled.

The Codex-first skill package lives at `skills/dating-booster-codex/`.
Installation and startup instructions live at
`skills/dating-booster-codex/INSTALL.md`.

## Project structure

- `dating_boost/cli.py`: CLI routing for local memory, policy, operator, data,
  diagnostics, and native harness commands.
- `dating_boost/core/gui_harness.py`: native GUI harness adapters. Tinder uses
  iPhone Mirroring; WeChat uses the macOS desktop application window.
- `dating_boost/host_loop.py`: host-loop supervisor for staged/live work items.
- `app_profiles/`: app-specific contracts. `tinder.json` and `wechat.json`
  declare each app's observation, staging, GUI harness, and blocked-action
  rules. `app_profiles/README.md` defines the profile contract and extension
  checklist for new dating apps.
- `skills/dating-booster-codex/`: installable Codex skill plus operational
  references and smoke/runbook docs.
- `docs/README.md`: repository map, current app support matrix, and app
  expansion path.
- `tests/fixtures/host_loop/tinder/`: deterministic Tinder host-loop fixtures.
- `tests/test_gui_harness.py`: GUI harness contracts for Tinder and macOS
  WeChat.

Shortest Codex-host path:

```bash
dating-boost harness doctor --app-id tinder --json
dating-boost harness tinder launch --dry-run --json
dating-boost harness tinder open-profile --dry-run --json
dating-boost harness tinder open-profile --launch-if-needed --json
dating-boost harness tinder observe --output-dir .local/dating-boost-harness --json
dating-boost harness tinder workflow self-profile-read --dry-run --photo-steps 2 --scroll-steps 2 --json
dating-boost harness tinder workflow chat-read-match-profile --dry-run --carousel-swipes 1 --conversation-row 1 --profile-scroll-steps 2 --json
dating-boost-host-loop doctor --data-dir .local/dating-boost --app-id tinder --json
dating-boost-host-loop init --data-dir .local/dating-boost --work-dir .local/dating-boost-host-loop --app-id tinder --json
dating-boost-host-loop run --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tinder --send-mode stage --work-dir .local/dating-boost-host-loop --json
```

Mac WeChat desktop harness path:

```bash
dating-boost harness doctor --app-id wechat --window-title WeChat --json
dating-boost harness wechat launch --dry-run --json
dating-boost harness wechat observe --output-dir .local/dating-boost-harness --json
dating-boost harness wechat stage-draft --text-file wechat-draft.txt --dry-run --json
```

Use `--send-mode stage` first. It only stages text and verifies the input box;
it does not click send. Use `dating-boost-host-loop status` to inspect the
current wait point, `dating-boost-host-loop resume` after interruption, and
`dating-boost replay latest --data-dir .local/dating-boost --format md` for a
run replay. `--send-mode live` is only for explicitly authorized ordinary
chat messages and still requires staged-text and post-send verification.
The native GUI harness can diagnose iPhone Mirroring, screenshot/OCR the
mirrored window, launch Tinder from a verified iOS home screen, and navigate
Tinder through navigation-only profile and chat reading chains. Covered
navigation includes the self profile tab, self profile preview, photo
next/previous, full profile read mode, profile scroll/visible-section expand,
chat tab, new-match carousel movement, conversation opening, thread-avatar
profile opening, and preview/full-profile exit. `harness tinder observe`
returns redacted page/layout hints for the self profile, chat page, new-match
carousel, conversation list, visible expand controls, and `等你回应` markers.
It does not provide an
autonomous live-send harness and never authorizes send, like, super-like,
unmatch, report, or profile-edit actions by itself.

The macOS WeChat harness can activate WeChat, screenshot/OCR the desktop
window, return redacted chat/layout hints, and stage a draft into the current
message input via clipboard paste. It never presses Enter, clicks Send, starts
calls, opens payments, or exchanges contacts by itself. The host must visually
verify staged text before any manual send.

Fully managed/autonomous runs require the user self model first:

```bash
python3 -m dating_boost.cli user interview template --json
python3 -m dating_boost.cli user ingest-profile --data-dir .local/dating-boost --input user_dating_profile.json
python3 -m dating_boost.cli user ingest-interview --data-dir .local/dating-boost --input self_interview.json
python3 -m dating_boost.cli user readiness --data-dir .local/dating-boost --mode autonomous --json
```

Autonomous readiness requires both profile sources, at least five low-risk
shareable materials, at least two low-investment repair materials, and at least
one date/meeting preference material.
Its required commands are:

```bash
python3 -m dating_boost.cli workflow draft --data-dir .local/dating-boost --observation observation.json --draft draft.json --mode adaptive
python3 -m dating_boost.cli memory ingest-observation --data-dir .local/dating-boost --input observation.json
python3 -m dating_boost.cli memory get-match --data-dir .local/dating-boost --match-id match_alex
python3 -m dating_boost.cli context build --data-dir .local/dating-boost --match-id match_alex --mode adaptive
python3 -m dating_boost.cli policy check-draft --input draft.json --context context.json
python3 -m dating_boost.cli policy check-action send_message --autonomous
python3 -m dating_boost.cli action record-result --data-dir .local/dating-boost --input action_result.json
python3 -m dating_boost.cli feedback record --data-dir .local/dating-boost --match-id match_alex --draft-id draft_1 --mode adaptive --label accepted
```

`workflow draft` is the preferred Codex-first path. The host agent still owns
screen understanding and draft generation; Dating Booster ingests the
observation, builds context, checks the host draft against policy, and can
record feedback in one local command.

Goal-oriented operator sessions use the same boundary: the host agent observes
Tinder and executes ordinary sends, while Dating Booster owns local state,
next-work selection, scheduling, duplicate prevention, appointment handoff, and
progress reports.

```bash
python3 -m dating_boost.cli operator session start --data-dir .local/dating-boost --authorization auth.json
python3 -m dating_boost.cli operator next --data-dir .local/dating-boost
python3 -m dating_boost.cli operator ingest-observation --data-dir .local/dating-boost --input observation.json
python3 -m dating_boost.cli operator record-action-result --data-dir .local/dating-boost --input action_result.json
python3 -m dating_boost.cli operator stop --data-dir .local/dating-boost
python3 -m dating_boost.cli operator report latest --data-dir .local/dating-boost
```

This mode includes a stage/navigation iPhone Mirroring harness for diagnostics,
screenshots, OCR, safe Tinder profile navigation, profile reading, and chat
navigation. It does not include a live-send harness. After each ordinary send,
the host agent must verify the result and call `operator record-action-result`.

Host-executed action results are appended to
`.local/dating-boost/audit/action_results.jsonl`. If a sent message or other
high-risk action cannot be verified from a fresh post-action observation, record
the result as `unknown`, not `succeeded`.

## MVP intelligence workflow

The current MVP can run a local fixture/manual-observation workflow end to end:

```bash
python3 -m dating_boost.cli init-profile --data-dir .local/dating-boost --input tests/fixtures/intelligence/user_profile.json
MATCH_ID=$(python3 -m dating_boost.cli import-observation --data-dir .local/dating-boost --input tests/fixtures/intelligence/app_observation_chat.json | python3 -c 'import json, sys; print(json.load(sys.stdin)["match_id"])')
python3 -m dating_boost.cli draft --data-dir .local/dating-boost --match-id "$MATCH_ID" --mode adaptive --backend scripted --scripted-backend-output tests/fixtures/intelligence/scripted_reply.json
python3 -m dating_boost.cli feedback --data-dir .local/dating-boost --match-id "$MATCH_ID" --draft-id draft_1 --mode adaptive --label accepted
python3 -m unittest discover -s tests
```

`--backend scripted --scripted-backend-output ...` is for deterministic local
tests and fixture demos. The production LLM path is `--backend openai`:

```bash
python3 -m dating_boost.cli draft --data-dir .local/dating-boost --match-id "$MATCH_ID" --mode adaptive --backend openai --model gpt-4.1-mini
```

The OpenAI backend requires the optional OpenAI SDK, e.g.
`pip install 'dating-booster[openai]'` after packaging/installing the project, or
`pip install 'openai>=2,<3'` in a local development environment.

Draft output is privacy-minimized by default. Add `--debug-context` only when
you explicitly want to inspect the context pack in terminal output.

Screenshots can be imported without GUI actions by pairing an image with a
manual/OCR/VLM analysis JSON that maps to the same `AppObservation` contract:

```bash
python3 -m dating_boost.cli observe-screenshot --data-dir .local/dating-boost --screenshot path/to/screenshot.png --analysis path/to/analysis.json
```

The fixture MVP path above still does not execute GUI actions or send messages.
Use `dating-boost harness ...` only for native stage/navigation paths such as
iPhone Mirroring Tinder navigation or macOS WeChat draft staging.
