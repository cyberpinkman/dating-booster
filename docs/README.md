# Dating Booster 文档地图

这个目录索引区分了三类内容：用户入口、agent 运行手册和维护者资料。不要把历史设计文档当成当前产品说明；当前能力以代码、app profile、CLI capabilities 和测试为准。

## 从哪里开始

| 读者 / 目标 | 入口 |
| --- | --- |
| 第一次了解或安装 | [`README.md`](../README.md) |
| Host agent 执行真实任务 | [`AGENTS.md`](../AGENTS.md) |
| Codex 安装与 startup check | [`skills/dating-booster-codex/INSTALL.md`](../skills/dating-booster-codex/INSTALL.md) |
| Claude Code 安装 | [`agent_adapters/claude-code/INSTALL.md`](../agent_adapters/claude-code/INSTALL.md) |
| OpenClaw / Hermes 安装 | [`agent_adapters/openclaw/INSTALL.md`](../agent_adapters/openclaw/INSTALL.md) |
| 查看 app contract | [`app_profiles/README.md`](../app_profiles/README.md) |
| 理解扩展边界 | [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) |

真实 dating-app 内容只能在 startup check、support session 和目标 app/runtime 确定后观察。默认只 stage 草稿；普通聊天 live send 也必须经过明确授权、目标验证、输入文本验证和发送后验证。

## 当前产品事实

### 支持的 host

- Codex：安装 `skills/dating-booster-codex/`。
- Claude Code：安装独立 adapter package。
- OpenClaw：安装 OpenClaw-compatible adapter package。
- Hermes：通过兼容命令使用同一份 OpenClaw-compatible skill contract。

新增 host 接入应继续复用同一组 CLI、capabilities、app profile、policy 和
audit contract，不复制 dating-specific 逻辑。

### 支持的 app/runtime

| App | Runtime | 主要能力 |
| --- | --- | --- |
| Tinder | macOS iPhone Mirroring | 观察、只读导航、stage、可选普通聊天托管发送 |
| Bumble | macOS iPhone Mirroring | 观察、只读导航、Opening Move 辅助、stage、可选普通聊天托管发送 |
| TaShuo / 她说 | macOS iPhone Mirroring；Apple Silicon `mac-ios-app` | 观察、只读导航、question-gate 辅助、stage、可选普通聊天托管发送；`mac-ios-app` 是 standalone 主路径 |
| WeChat / 微信 | macOS 桌面微信 | continuation-channel 观察、stage、可选普通聊天托管发送 |

不要从静态文档推断本机能力。使用机器可读命令确认：

```bash
dating-boost capabilities --json --data-dir .local/dating-boost
```

`supported_app_profiles` 中不存在的 app 视为未支持；不要创建 placeholder profile，也不要用固定坐标或通用 UI marker 临时绕过。

## Agent 运行资料

- [`agent_adapters/shared/references/contracts.md`](../agent_adapters/shared/references/contracts.md)：跨 host 的 JSON、隐私和执行契约。
- [`agent_adapters/shared/references/workflows.md`](../agent_adapters/shared/references/workflows.md)：跨 host 的可复用 workflow。
- [`skills/dating-booster-codex/SKILL.md`](../skills/dating-booster-codex/SKILL.md)：Codex 运行契约。
- [`skills/dating-booster-codex/references/`](../skills/dating-booster-codex/references/)：observation、planner、drafting、host-loop 和生产 stage runbook。
- [`app_profiles/README.md`](../app_profiles/README.md)：app profile schema 与支持等级。

`dating_boost/resources/agent_adapters/` 下的文件是构建 wheel 时使用的打包镜像，不是文档编辑入口。权威源文件位于 `skills/` 和 `agent_adapters/`；发布检查会验证源文件与打包镜像一致。

## 代码与架构

- `dating_boost/cli.py`：CLI 总入口。
- `dating_boost/core/`：存储、memory、planner、policy、operator、managed session、safety、diagnostics。
- `dating_boost/apps/`：各 app 的页面语义、runtime、target binding 和发送验证。
- `dating_boost/harness/`：跨 app 的 GUI 基础能力。
- `dating_boost/intelligence/`：模型 backend 与回复生成 wiring。
- `dating_boost/host_loop.py`：host-loop supervisor。
- `app_profiles/` 与 `schemas/`：app 产品契约及 JSON schema。
- `agent_adapters/` 与 `skills/`：host-specific 安装包和操作文档。
- `scripts/`：fixture、managed 和 standalone smoke/qualification 入口。
- `tests/`：contract、storage、policy、adapter、host-loop、GUI 和 production qualification 回归。

扩展 host agent、app、goal 或 memory/workflow 前，先读 [`docs/ARCHITECTURE.md`](ARCHITECTURE.md)。架构按 host agent adapter、app support profile、goal type registry 和 memory evolution 四条轴拆分，避免把一个 app 或 host 的特殊逻辑写进全局 contract。

## 历史设计记录

`docs/superpowers/specs/` 和 `docs/superpowers/plans/` 保存开发阶段的设计、评审和实施记录，适合维护者追溯“为什么曾经这样设计”。

这些文件：

- 不是用户安装或运行入口；
- 不保证描述当前 CLI 或成熟度；
- 不应从根 README 作为主要产品能力展示；
- 与当前实现冲突时，以代码、capabilities、app profile、agent contract 和测试为准。

## 验证文档与实现

```bash
python3 -m dating_boost.cli release doctor --json
python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost
python3 -m pytest -q
```

无 GUI 的完整 fixture workflow：

```bash
DATING_BOOST_KEY_PROVIDER=local \
python3 scripts/agent_native_smoke.py --data-dir .local/dating-boost-smoke
```
