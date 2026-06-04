# Dating Booster Project Map / 项目地图

Dating Booster 是本地优先的 dating workflow 工具层：host agent 负责观察可见
App UI，Dating Booster 负责本地记忆、策略、规划、审计和安全 staging 契约。

Dating Booster is a local-first dating workflow tool layer: the host agent
observes visible app UI, while Dating Booster owns local memory, policy,
planning, audit, and safe staging contracts.

The repository is open-sourced under the MIT License. See `LICENSE`.

本仓库使用 MIT License 开源，见 `LICENSE`。

Stable test-user installers are host-specific:

```bash
curl -fsSL https://raw.githubusercontent.com/cyberpinkman/dating-booster/main/scripts/install-claude-code.sh | bash
curl -fsSL https://raw.githubusercontent.com/cyberpinkman/dating-booster/main/scripts/install-codex.sh | bash
```

稳定测试安装入口按 host 拆分。新增 host 时新增自己的 installer，不修改已有
Claude Code 或 Codex installer。

## Top-Level Layout / 顶层结构

- `dating_boost/`: Python package and CLI entrypoints。核心 Python 包和 CLI 入口。
- `dating_boost/core/`: storage, policy, planning, diagnostics, production data,
  daemon/safety state, and native GUI harness adapters。本地存储、策略、规划、
  诊断、生产数据、daemon/safety 状态和原生 GUI harness。
- `dating_boost/harness/`: shared native harness building blocks, including
  window parsing, screen-state classification, and input backends。原生 harness
  共享模块，包括窗口解析、屏幕状态识别和输入后端。
- `dating_boost/host_loop.py`: supervised host-loop runner for app-specific work
  items。面向具体 App work item 的 host-loop supervisor。
- `dating_boost/intelligence/`: reply generation backends and prompt wiring。
  草稿生成 backend 与 prompt wiring。
- `dating_boost/perception/`: screenshot and observation contract helpers。截图
  与 observation contract 辅助。
- `dating_boost/policy/`: action and content safety rules。动作与内容安全规则。
- `dating_boost/evals/`: conversation and reply quality evaluation helpers。对话
  与回复质量评估。
- `app_profiles/`: app-specific product contracts。具体 App 契约，见
  `app_profiles/README.md`。
- `schemas/`: formal JSON contracts such as `app_profile.schema.json`。正式
  JSON contract。
- `agent_adapters/`: shared and host-specific adapter packages/docs for Codex,
  Claude Code, and future hosts。面向 Codex、Claude Code 和后续 host 的 adapter
  包与文档。
- `docs/ARCHITECTURE.md`: expansion architecture for host agents, dating apps,
  goals, workflows, and memory。面向更多 agent、更多 app、更多目标和更智能
  workflow/memory 的扩展架构。
- `skills/dating-booster-codex/`: installable Codex skill, scripts, examples,
  and operational references。Codex skill、脚本、示例和运行手册。
- `agent_adapters/claude-code/`: installable Claude Code adapter package and
  skill content。Claude Code adapter package 与 skill 内容。
- `scripts/`: local smoke and host-loop helper scripts。本地 smoke 与 host-loop
  辅助脚本。
- `tests/`: contract, policy, storage, host-loop, skill, and harness tests。契约、
  策略、存储、host-loop、skill 和 harness 测试。
- `docs/superpowers/specs/`: product/architecture specs used while building the
  project。项目构建阶段的产品/架构规格。
- `.github/workflows/`: CI and release workflows。CI 与发布流程。

## Current App Targets / 当前 App 支持

| App | Current support / 当前支持 | Native harness | Send ownership / 发送归属 |
| --- | --- | --- | --- |
| Tinder | Host-loop, profile/chat navigation, observation, draft workflow, opt-in managed live send | iPhone Mirroring on macOS | Stage by default; managed send only with explicit authorization and verification |
| WeChat / 微信 | App profile, host-loop app id, desktop observation, draft staging, opt-in managed live send | macOS WeChat desktop window | Stage by default; managed send only with explicit authorization and verification |

`supported_app_profiles` 只列 runtime-supported app。未支持 app 不创建 placeholder
profile，也不进入 capabilities。

`supported_app_profiles` only lists runtime-supported apps. Unsupported apps do
not get placeholder profiles and do not appear in capabilities.

## Expansion Architecture / 扩展架构

Use `docs/ARCHITECTURE.md` as the source map for future expansion. It separates
four axes that should not be mixed in one-off patches:

- host agent adapters: Codex and Claude Code are installable now; Hermes,
  OpenClaw, and MCP-compatible hosts should reuse the same adapter contract.
- app support profiles: Tinder and WeChat at runtime; Bumble, Ta Shuo/tashuo,
  Hinge, and other mainstream apps stay as roadmap candidates until testable.
- goal type registry: `meet_in_person` first, then additional goals with their
  own milestones, policy constraints, and handoff rules.
- workflow and memory evolution: smarter scenario workflows, provenance-backed
  memory, feedback events, and eval-driven improvement.

后续扩展应先查 `docs/ARCHITECTURE.md`。新增 agent、app、goal 或 memory/workflow
能力时，先确认它属于哪条轴，再同步 core contract、capabilities、docs 和 tests。

## Runtime Surfaces / 运行面

- CLI: `dating_boost/cli.py` exposes data, policy, workflow, diagnostics,
  release, daemon/safety, confirmation, and harness commands。所有本地命令入口。
- Host loop: `dating-boost-host-loop` supervises work directories,
  authorization, recovery, and staged/live send mode checks。监督 work dir、授权、
  恢复和 send mode 检查。
- GUI harness: `dating_boost/core/gui_harness.py` is the only place for native
  app-window automation details。原生窗口自动化细节只应在这里。
- Capabilities: `dating_boost/core/capabilities.py` is the machine-readable
  startup contract for agents and skill installers。agent/skill 的机器可读启动契约。
- Host adapters: `skills/dating-booster-codex/SKILL.md` and
  `agent_adapters/claude-code/skills/dating-booster/SKILL.md` are host-specific
  operating contracts。Codex 与 Claude Code 的运行契约必须和 CLI capabilities
  保持一致。

## App Expansion Path / App 扩展路径

1. Add or update `app_profiles/<app_id>.json`。新增或更新 App profile。
2. Add a runtime profile only after fixtures and preflight can prove the app is
   supported。不为未支持 app 创建 placeholder profile。
3. Keep the app out of capabilities until host-loop or harness tests prove it
   can run。未验证前不要进入 capabilities。
4. If native GUI support is needed, add the backend adapter in
   `dating_boost/core/gui_harness.py`。需要原生 GUI 时再实现 backend。
5. Expose app-specific CLI commands only after the harness contract is
   testable。只有 contract 可测试后才暴露 CLI。
6. Add capability flags, deterministic fixtures, and focused tests。补
   capabilities、fixtures 和 focused tests。
7. Update `README.md`, `app_profiles/README.md`, and Codex skill references。
   同步顶层 README、profile 文档和 Codex skill。
8. Run targeted unit tests plus `dating-boost capabilities --json` before
   publishing。发布前跑 targeted tests 和 capabilities。

## Non-Negotiable Boundaries / 不可放松的边界

- Do not add private APIs, scraping bypasses, anti-detection logic, or account
  scale-out automation。不要加入私有 API、绕过、反检测或账号规模化能力。
- Do not let a harness send messages, likes, reports, payments, calls, or
  profile edits unless policy, confirmation, staged-text verification, and
  post-action verification explicitly support that action。Managed Tinder/WeChat send
  also needs policy-checked action requests, target-chat binding, and outbound
  bubble verification。除非策略、确认、staged-text verification 和 post-action
  verification 明确支持，否则 harness 不得执行高风险动作；Tinder/WeChat 全托管发送还必须有
  policy-checked action request、目标聊天绑定和 outbound bubble 校验。
- Prefer paste-based draft staging for Chinese text。中文草稿优先 paste staging，
  避免直接输入导致文本损坏。
- Treat raw OCR/screenshot content as sensitive。原始 OCR/截图内容视为敏感数据，
  public logs 和 diagnostics 只能暴露 redacted layout hints。
- Safety pause must block real staging/paste/send paths。安全暂停必须阻断真实
  staging、paste 和 send 路径。
- Managed live send must stay opt-in and must not remove `send` from the
  default blocked-action list。全托管发送必须显式开启，不能把默认 blocked
  actions 里的 `send` 直接删除。

## Useful Verification / 常用验证

```bash
python3 -m unittest tests.test_gui_harness tests.test_skill_package
python3 -m unittest tests.test_claude_code_adapter
python3 -m unittest tests.test_operator_host_loop.OperatorHostLoopTests.test_wechat_host_loop_init_writes_wechat_authorization_template
python3 -m py_compile dating_boost/core/gui_harness.py dating_boost/cli.py dating_boost/core/capabilities.py dating_boost/host_loop.py
```
