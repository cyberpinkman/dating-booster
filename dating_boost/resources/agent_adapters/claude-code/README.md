# Claude Code Adapter

Claude Code is a first-class host adapter for Dating Booster. It reuses the
same CLI, capabilities, app profile, policy, memory, planner, harness, and
audit contracts as Codex, but installs through Claude Code's skill discovery
path.

Claude Code 是 Dating Booster 的正式 host adapter。它复用 Codex 已使用的
本地 CLI、capabilities、app profile、policy、memory、planner、harness 和
audit contract，只在 Claude Code 的 skill 安装和调用方式上做 host-specific 适配。

## Install

Project-local install:

```bash
dating-boost adapter claude-code install --scope project --target . --json
dating-boost adapter claude-code doctor --data-dir .local/dating-boost --json
```

User-level install:

```bash
dating-boost adapter claude-code install --scope user --json
```

The project install writes `.claude/skills/dating-booster/`. The user install
writes `~/.claude/skills/dating-booster/`. Use `--dry-run --json` to inspect
the target path and files before writing.

项目级安装会写入 `.claude/skills/dating-booster/`，用户级安装会写入
`~/.claude/skills/dating-booster/`。如需先检查路径和文件列表，使用
`--dry-run --json`。

## Runtime Contract

- Run `dating-boost adapter claude-code doctor --data-dir <data-dir> --json`
  before observing visible dating app content.
- Read `agent_adapters/shared/references/contracts.md` and
  `agent_adapters/shared/references/workflows.md`.
- Use `dating-boost capabilities --json --data-dir <data-dir>` as the
  machine-readable startup contract.
- Use `dating-boost-host-loop --adapter-package
  agent_adapters/claude-code/adapter-package.json ...` when Claude Code drives
  host-loop work items.
- Do not copy Codex-specific skill text into Claude Code; keep shared product
  logic in shared references and CLI contracts.

## Supported Product Surfaces

- startup doctor, data doctor, migration, release checks
- user profile, self interview, autonomous readiness
- observation authoring, memory, context, draft workflow, policy checks
- planner, goal plan, feedback, replay, diagnostics
- Tinder iPhone Mirroring harness
- macOS WeChat harness
- opt-in managed live-send with authorization, target binding, staged-text
  verification, and post-action verification
- operator and host-loop workflows
