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

The current CLI only authorizes actions. It does not execute GUI actions and does not include a mock dating-app harness.
