# dating-booster

Local-first GUI automation experiments for dating workflows.

## Boundary statement

这是一个不使用私有 API、不做绕过、由用户本地授权运行的 GUI automation experiment；它仍可能违反目标 App 的条款，并可能导致账号封禁。项目不提供规避检测或规模化滥用能力。

## Default behavior

- Allowed by default: observe, summarize, draft replies, and paste drafts.
- Blocked by default: sending messages, liking profiles, super-likes, unmatching, reporting, profile edits, and proposing meetings.
- High-risk actions require explicit human confirmation unless experimental autonomous mode is enabled for a single action.
- Autonomous mode is off by default. Users can explicitly enable it after reading and accepting the risk.

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

This MVP still does not execute GUI actions, send messages, operate iPhone
Mirroring, or include a mock dating-app harness.
