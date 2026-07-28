# Dating Booster

> **Agent 入口：**如果你是 Codex、Claude Code、OpenClaw、Hermes 或其他 host agent，请先完整阅读 [`AGENTS.md`](AGENTS.md)。它包含安装、启动检查、app/runtime 选择和安全执行规则。

Dating Booster 是一个本地优先的 dating workflow 工具层。它让 host agent 负责理解当前可见的资料和聊天，自己负责本地记忆、上下文组装、回复策略检查、草稿暂存、审计和恢复。

它不是 dating app 客户端，也不是无人值守的“自动聊天机器人”。默认模式只把草稿放进输入框，不点击发送。

> **当前状态：预发布。** 核心 CLI、fixture workflow 和发布检查可测试；真实 GUI 能力目前以 macOS 为主，并依赖本机已安装、已登录的 app，以及授予 host/终端必要的屏幕录制、辅助功能和自动化权限。当前安装的真实能力请以 `dating-boost capabilities --json` 为准。

## 它能做什么

- **保留上下文**：在本地记录用户资料、对象资料、对话事实、承诺和反馈。
- **辅助回复**：为 host agent 组装 context，检查草稿的内容风险、自然度和当前对话策略。
- **安全操作 GUI**：在受支持的 macOS app 中观察、只读导航和暂存草稿。
- **管理一个明确开启的会话窗口**：按优先级串行处理多个聊天对象，并输出进度报告；不会在会话外持续监听。
- **保留审计与恢复证据**：记录操作边界、验证结果和可恢复状态，提供默认脱敏的诊断包。

典型流程是：

1. Host agent 读取当前任务中可见的 app 内容。
2. Dating Booster 从本地记忆和目标中构建上下文。
3. Host agent 起草回复，Dating Booster 执行策略和安全检查。
4. 默认只暂存草稿；只有普通聊天消息在获得明确授权并通过发送前后验证后，才可能走托管发送。

## 当前支持范围

### Host agent

| Host | 当前接入方式 |
| --- | --- |
| Codex | 可安装的 Codex skill |
| Claude Code | 可安装的 Claude Code adapter |
| OpenClaw | 可安装的 OpenClaw-compatible adapter |
| Hermes | 复用 OpenClaw-compatible skill contract |

### App 与运行环境

| 场景 | 已实现能力 | 本机依赖 |
| --- | --- | --- |
| Tinder | 资料/聊天观察、只读导航、草稿暂存、可选普通聊天托管发送 | macOS iPhone Mirroring |
| Bumble | 资料/聊天观察、只读导航、Opening Move 辅助、草稿暂存、可选普通聊天托管发送 | macOS iPhone Mirroring |
| 她说 / TaShuo | 资料/聊天观察、question-gate 辅助、草稿暂存、可选普通聊天托管发送；支持本地 iOS app 的 stage-first standalone 路径 | macOS iPhone Mirroring；本地 iOS app 路径需要 Apple Silicon Mac |
| 微信 / WeChat | 桌面聊天观察、草稿暂存、可选普通聊天托管发送 | macOS 微信桌面端 |

微信是 dating app 转化后的 continuation channel，不是 discovery app。Dating Booster 只会在用户确认双方是同一个现实对象后，执行一次性的 dating-app → 微信记忆继承。

Opening Move、question gate、邀约细节、联系方式交换和其他需要社会判断的节点不会因为开启托管模式而自动放行。

## 给人类的快速开始

### 最省事：把仓库交给你的 agent

把仓库地址和下面这段话发给 Codex、Claude Code、OpenClaw 或 Hermes：

> 请克隆 `https://github.com/cyberpinkman/dating-booster.git`，先阅读根目录的 `AGENTS.md`，再安装 CLI 和与你对应的 adapter，完成 startup check。默认使用 stage mode；除非我在当前任务中明确授权，否则不要发送消息或执行任何匹配、账号、支付操作。

### 从源码安装

需要 Python 3.11 或更高版本；CI 当前覆盖 3.11–3.13。真实 GUI workflow 目前需要 macOS。

```bash
git clone https://github.com/cyberpinkman/dating-booster.git
cd dating-booster
python3 -m pip install --user -e .
python3 -m dating_boost.cli release doctor --json
python3 -m dating_boost.cli data doctor --data-dir .local/dating-boost --json
```

如果本机 Python 不允许 user-site 安装，可以改用虚拟环境，但之后每个 agent
任务都必须激活同一个环境，或显式使用该环境中的 Python。

新数据目录的 data doctor 会先返回 `needs_migration`。此时先迁移并复查：

```bash
python3 -m dating_boost.cli data migrate --data-dir .local/dating-boost --json
python3 -m dating_boost.cli data doctor --data-dir .local/dating-boost --json
```

确认数据目录正常后，再查看当前安装能力：

```bash
python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost
```

然后只安装你使用的 host adapter：

```bash
# Codex
python3 -m dating_boost.cli adapter codex install --scope user --json

# Claude Code
python3 -m dating_boost.cli adapter claude-code install --scope user --json

# OpenClaw
python3 -m dating_boost.cli adapter openclaw install --scope user --json

# Hermes（OpenClaw-compatible）
python3 -m dating_boost.cli adapter hermes install --scope user --json
```

安装后运行对应的 `adapter <host> doctor`，验证 CLI 与 adapter contract 的兼容性。
当前 doctor 不判断已复制到用户目录的文件是否过期；更新源码后，需要重新执行
editable install 和 adapter install，单独 `git pull` 不会更新 host skill 副本。

Codex 的详细安装说明见 [`skills/dating-booster-codex/INSTALL.md`](skills/dating-booster-codex/INSTALL.md)，其他 host 见 [`agent_adapters/`](agent_adapters/)。

### 不打开 app 的安装验证

下面的 fixture smoke 不会打开 dating app、调用真实模型或发送消息。`local` key provider 仅用于这个可丢弃的测试数据目录：

```bash
DATING_BOOST_KEY_PROVIDER=local \
python3 scripts/agent_native_smoke.py --data-dir .local/dating-boost-smoke
```

成功时会返回 `status: ok`，并验证 capabilities、加密存储、memory/context/policy、operator、host-loop stage 和脱敏 support bundle。

## 使用真实 app 前

不要从 README 复制一串固定坐标或直接发送命令。让 host agent 按 [`AGENTS.md`](AGENTS.md) 完成以下步骤：

1. 运行 skill/adapter doctor、release doctor、data doctor 和 capabilities 检查。
2. 为本次任务启动 support session。
3. 选择唯一的目标 app/runtime；同一数据目录不会自动漂移到其他 app。
4. 托管或自主 workflow 开始前，完成用户 profile/interview readiness。
5. 先观察和规划，再进入具体聊天。
6. 默认只 stage 草稿；发送必须使用系统生成的 work item，不能手工拼 action request（do not handcraft action requests）。

## Host-native 与 standalone

Host-native 是默认路径：Codex、Claude Code、OpenClaw 或 Hermes 负责观察和起草，Dating Booster 提供本地工具与安全契约。

`standalone-session` 是显式选择的独立运行时，不是默认模式。当前主要路径是 TaShuo `mac-ios-app` 的 stage-first workflow；Tinder、Bumble、微信的 standalone provider 仍属于跨 app 开发路径。

当前 standalone GUI executor 只支持 stage，standalone live send 未启用。普通聊天
live send 仍必须由 host agent 通过 managed-session/host-loop 执行。

使用 standalone 模型 backend 前，需要安装 `.[models]` 可选依赖，并由用户通过
环境变量提供模型供应商 API key；仓库不附带密钥。

TaShuo `mac-ios-app` 另有环境限定的 stage-only production qualification 协议。仓库实现了 Gate，但没有附带任何本机通过证书；“协议已实现”不等于“当前环境 qualification passed”。它只证明某一个固定环境通过了对应验证，不认证 live send，也不代表其他机器或配置已经通过。操作入口和接受条件只放在 [`AGENTS.md`](AGENTS.md) 与 agent runbook 中。

## 安全与隐私

- 不使用私有 API，不提供绕过风控、批量运营、刷赞、账号池或反检测能力。
- Like、super-like、pass、unmatch、report、profile edit、通话、支付等动作不在 agent 执行范围内。
- 默认不发送。可选 live send 仅限明确授权的普通聊天消息，并要求确认目标聊天、精确核对输入文本和验证发送结果。
- Direct harness send is executor-internal; do not handcraft action requests.
- 本地业务数据使用加密 SQLite；macOS 生产路径默认使用 Keychain 管理数据密钥。
- Dating Booster 不发送网络遥测。Host agent 或用户显式配置的模型供应商仍可能按其自身设置处理当前任务中的可见内容。
- 严格 support bundle 默认不包含原始聊天、profile 文本、截图、剪贴板内容或完整草稿；导出敏感证据需要用户再次明确同意。
- 全局 safety pause 会阻止真实 staging、paste 和 send。

## 本地数据

生产数据目录通常是 `.local/dating-boost`。常用检查与控制命令：

```bash
dating-boost data doctor --data-dir .local/dating-boost --json
dating-boost data migrate --data-dir .local/dating-boost --json
dating-boost safety status --data-dir .local/dating-boost --json
dating-boost safety pause --data-dir .local/dating-boost --reason manual-stop --json
```

备份必须提供恢复口令，优先使用只允许当前用户读取的文件，不要把口令直接放在命令参数中：

```bash
dating-boost data backup \
  --data-dir .local/dating-boost \
  --output dating-boost-backup.zip \
  --recovery-passphrase-file /secure/path/recovery-passphrase.txt \
  --json
```

## 文档导航

| 你要做什么 | 从这里开始 |
| --- | --- |
| 让 agent 安装和运行 | [`AGENTS.md`](AGENTS.md) |
| 安装 Codex skill | [`skills/dating-booster-codex/INSTALL.md`](skills/dating-booster-codex/INSTALL.md) |
| 安装其他 host adapter | [`agent_adapters/`](agent_adapters/) |
| 查看 app 能力契约 | [`app_profiles/README.md`](app_profiles/README.md) |
| 理解架构或贡献代码 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| 查看完整文档地图 | [`docs/README.md`](docs/README.md) |

`docs/superpowers/` 保存的是开发阶段的设计与实施记录，供维护者追溯，不是用户操作手册，也不是当前能力的 source of truth。

## 验证

```bash
python3 -m pip install --user -e ".[test]"
python3 -m pytest -q
```

如果使用 `uv` 管理临时环境：

```bash
uv run --extra test python -m pytest -q
```

发布前还应运行：

```bash
python3 -m dating_boost.cli release doctor --json
```

## 许可证

MIT License，见 [`LICENSE`](LICENSE)。
