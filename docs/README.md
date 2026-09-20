# 文档导航

第一次使用请从[项目 README](../README.md) 开始。本页按任务找资料；agent 的执行规则以 [`AGENTS.md`](../AGENTS.md) 为准。

## 安装与使用

| 你要做什么 | 文档 |
| --- | --- |
| 了解项目、支持范围和真实验证状态 | [项目 README](../README.md) |
| 让 agent 检查环境、准备资料并运行 | [`AGENTS.md`](../AGENTS.md) |
| 安装 Codex skill | [Codex 安装说明](../skills/dating-booster-codex/INSTALL.md) |
| 安装 Claude Code adapter | [Claude Code 安装说明](../agent_adapters/claude-code/INSTALL.md) |
| 安装 OpenClaw / Hermes adapter | [OpenClaw 兼容安装说明](../agent_adapters/openclaw/INSTALL.md) |
| 查各 app 的观察、导航、草稿和发送限制 | [App 能力契约](../app_profiles/README.md) |

首次安装、源码或 adapter 更新、迁移、权限变化后，先完成兼容性检查再观察真实内容。已验证的同一环境可直接启动日常任务；Support session 仅用于实机验收、诊断或导出，不是每次启动的必经步骤。

## 选择运行入口

| 入口 | 用途与限制 |
| --- | --- |
| Host 草稿流程 | 由 Codex、Claude Code、OpenClaw 或 Hermes 读取上下文、起草；默认不发送 |
| `manage` / ManagedRun | 新的限时全托管，当前仅聚焦她说 `mac-ios-app`；本地实机连续发送验收未完成 |
| `managed-session` / `host-loop` | 既有多 app 兼容路径，沿用各自授权和配置流程 |
| `standalone-session` | 用户显式选择的独立运行时；当前 GUI 只暂存草稿，不实发 |

ManagedRun 的用户入口见[README 全托管说明](../README.md#实验性全托管)，操作与恢复细节见 [`AGENTS.md`](../AGENTS.md)。不要在不同入口之间混用授权、运行状态或 app 环境。

## 性能与当前开发进展

[ManagedRun 性能与 Jev 说明](managed-run-performance.md) 记录队列复用、短消息连续发送、AX 与视觉的分工、TypeSafe / Jev 配置和实测限制。

**截至 2026-09-20，这些重构代码仍在本地，尚未推送到远端。** 该文档中的新配置、`manage reconcile` 和基准脚本适用于本地开发版本，不是当前远端安装承诺。离线测试、单步导航、一次历史发送的证据确认与完整连续实发是不同层级的验证；最新结论见[验证状态](managed-run-performance.md#当前状态2026-09-20)。

## Agent 操作参考

- [跨 host 契约](../agent_adapters/shared/references/contracts.md)：JSON、隐私、capabilities 与执行边界。
- [跨 host 工作流](../agent_adapters/shared/references/workflows.md)：共享操作步骤。
- [Codex skill](../skills/dating-booster-codex/SKILL.md)：Codex 的执行契约。
- [Codex 参考资料](../skills/dating-booster-codex/references/README.md)：观察转录、规划、草稿、host-loop 和生产暂存手册。

安装说明和兼容手册保留了既有流程；涉及新的日常 ManagedRun 启动时，优先使用根目录 [`AGENTS.md`](../AGENTS.md) 的对应章节。

## 架构与贡献

先读 [`docs/ARCHITECTURE.md`](ARCHITECTURE.md)，再按修改范围进入代码：

| 目录 | 职责 |
| --- | --- |
| `dating_boost/core/` | 本地存储、记忆、调度、运行状态、策略与恢复 |
| `dating_boost/apps/` | 每个 app 的页面、对象定位与操作验证 |
| `dating_boost/harness/` | 共享 GUI 基础能力 |
| `dating_boost/intelligence/` | 模型调用、视觉与回复生成 |
| `app_profiles/`、`schemas/` | 能力契约与数据格式 |
| `agent_adapters/`、`skills/` | Host 接入和操作文档的权威源文件 |
| `scripts/`、`tests/` | 安装检查、模拟流程与回归验证 |

`dating_boost/resources/agent_adapters/` 是随 wheel 打包的镜像，不是独立编辑入口；修改源 adapter 文档时，应同步对应镜像并通过发布检查。

常规验证见[README 验证说明](../README.md#验证)。能力声明可用 `dating-boost capabilities --json --data-dir .local/dating-boost` 查看；它表示当前安装实现了哪些接口，不证明本机已通过实发验收。

## 历史记录

`docs/superpowers/specs/` 和 `docs/superpowers/plans/` 保存历史设计、评审和实施记录，用于追溯设计原因，不是安装或运行入口。若与现状冲突，以当前代码、能力契约、执行规则和验证证据为准。
