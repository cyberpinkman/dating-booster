# Dating Booster

> **Agent 入口：**如果你是 Codex、Claude Code、OpenClaw、Hermes 或其他 host agent，请先完整阅读 [`AGENTS.md`](AGENTS.md)。它包含安装、启动检查、app/runtime 选择和安全执行规则。

Dating Booster 是一个本地优先的实验性 dating workflow。它的核心目标不是只起草一句回复，而是在用户明确开启的有限时间窗口内，持续扫描多个普通聊天、理解上下文、生成并发送回复、验证结果，并在真正需要本人判断时 handoff。

它不是 dating app 客户端，也不会在托管窗口之外监听或运行。未开启全托管时不会自动发送；stage 仍保留为 shadow、调试和故障 fallback。

> **当前状态：预发布实验版。** 新的 `ManagedRun` 已覆盖 fixture 全链路，并接通 TaShuo `mac-ios-app` 的分段 live action port；真实 GUI Canary 尚未执行，因此不应解读为当前机器已经通过实发验证。当前安装能力请以 `dating-boost capabilities --json` 为准。

## 它能做什么

- **保留上下文**：在本地记录用户资料、对象资料、对话事实、承诺和反馈。
- **全托管普通聊天（实验路径）**：fixture 已覆盖一次 bounded 授权内的扫描、排序、回复、验证和继续处理；TaShuo live seam 已接线，真实 GUI Canary 待执行。
- **辅助回复**：为 host agent 组装 context，检查草稿的内容风险、自然度和当前对话策略。
- **安全操作 GUI**：在受支持的 macOS app 中观察、只读导航和暂存草稿。
- **管理一个明确开启的会话窗口**：按优先级串行处理多个聊天对象，并输出进度报告；不会在会话外持续监听。
- **保留审计与恢复证据**：记录操作边界、验证结果和可恢复状态，提供默认脱敏的诊断包。

全托管的目标流程如下；当前 fixture 已完整覆盖，真实 TaShuo GUI 仍处于 Canary 前状态：

1. 用户一次确认 app/runtime、时长、普通聊天范围、quiet hours、nudge 和发送预算。
2. `ManagedRun` 扫描消息列表并确定性选择一个合格对象。
3. 系统读取新鲜线程、构建本地上下文，并用一次生成、最多一次修订得到回复。
4. 普通消息自动 stage、精确核对、发送并从新鲜界面验证。
5. 系统更新对象状态并继续；邀约细节、联系方式、目标不确定或发送结果 unknown 时 handoff。

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
| 她说 / TaShuo | 资料/聊天观察、question-gate 辅助、草稿暂存；`mac-ios-app` 已接通普通聊天 ManagedRun 候选 seam，真实 GUI Canary 待执行 | macOS iPhone Mirroring；本地 iOS app 路径需要 Apple Silicon Mac |
| 微信 / WeChat | 桌面聊天观察、草稿暂存、可选普通聊天托管发送 | macOS 微信桌面端 |

微信是 dating app 转化后的 continuation channel，不是 discovery app。Dating Booster 只会在用户确认双方是同一个现实对象后，执行一次性的 dating-app → 微信记忆继承。

Opening Move、question gate、邀约细节、联系方式交换和其他需要社会判断的节点不会因为开启托管模式而自动放行。

## 给人类的快速开始

### 最省事：把仓库交给你的 agent

把仓库地址和下面这段话发给 Codex、Claude Code、OpenClaw 或 Hermes：

> 请克隆 `https://github.com/cyberpinkman/dating-booster.git`，先阅读根目录的 `AGENTS.md`，再安装 CLI 和与你对应的 adapter；首次安装、更新、迁移或权限变化后完成兼容性检查，日常托管启动不要重复跑完整 doctor。除非我明确开启一个 bounded 全托管窗口，否则不要发送消息；任何情况下都不要执行 like、pass、unmatch、资料编辑、联系方式交换、通话或支付操作。

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

## 实验性全托管

当前唯一重点路径是 TaShuo / 她说的 Apple Silicon `mac-ios-app` runtime。完成 models/key、App 安装登录、macOS 权限、用户自我模型和初次 doctor 后，用户日常只需告诉 agent：

> 全托管她说 2 小时，普通聊天自动发送，允许一次谨慎跟进，保守推进；涉及具体邀约、联系方式或目标不确定时找我。本次最多 5 条，23:00–08:00 不发送。

Host agent 复用已验证的安装，并完成 readiness/runtime scope 检查后，会先创建 durable run，再立即持有一个前台 `run --wait` 轮询进程。`start` 本身不扫描、不打开 GUI，也不启动后台 worker；host/task/进程退出后不会继续运行。用户不需要准备 authorization、goal、availability 或 provider JSON。开发者等价命令是：

```bash
dating-boost manage start \
  --data-dir .local/dating-boost \
  --duration-minutes 120 \
  --send-budget 5 \
  --nudge \
  --quiet-hours 23:00-08:00 \
  --json

# host-owned foreground wait loop
dating-boost manage run --data-dir .local/dating-boost --wait --poll-interval 30 --json
```

`manage pause/resume/stop/status` 都默认作用于同一数据目录中的当前 run。Pause 会在下一次 GUI mutation 前生效并让前台轮询退出；Resume 只恢复 durable 状态，host 还要为同一个 run 重新启动 `run --wait`；Stop 返回紧凑的关系进度报告。`run/tick` 是公开 CLI 子命令，“host-internal”只是产品交互分层，不是访问控制边界。

模型与视觉默认复用 TaShuo standalone 的 MiniMax 配置，需要安装 `.[models]` 并设置 `MINIMAX_API_KEY`（也兼容现有备用 key 环境变量）。真实运行还要求先选择 `tashuo/mac-ios-app` runtime。高级开发环境可以用 `DATING_BOOST_MANAGED_RUN_TASHUO_CONFIG` 覆盖默认 provider 配置。

这条路径目前是实验能力：代码和 deterministic fixture 已验证，真实 App Canary 尚未在本次实现中执行。第一次实发应使用小预算、短时长并由用户明确授权。

## 使用真实 app 前

不要从 README 复制固定坐标或 direct harness send。首次安装/更新、迁移或权限变化后，让 host agent 按 [`AGENTS.md`](AGENTS.md) 完成完整 preflight；相同环境的日常 ManagedRun 不重复串行执行 deep doctor：

1. 日常直接 `manage start`；若被阻断，只执行返回的具体恢复动作。
2. 首次选择 app/runtime 后会持久化，只有明确切换目标时才重新 select。
3. 用户 profile/interview readiness 由入口强制检查。
4. Support session 只用于首次 real-GUI Canary、诊断或需要导出 bundle 的任务。
5. 普通聊天实发只走 ManagedRun 或既有受控 executor；do not handcraft action requests。

## Host-native 与 standalone

Host-native 是默认路径：Codex、Claude Code、OpenClaw 或 Hermes 负责观察和起草，Dating Booster 提供本地工具与安全契约。

`standalone-session` 是显式选择的独立运行时，不是默认模式。当前主要路径是 TaShuo `mac-ios-app` 的 stage-first workflow；Tinder、Bumble、微信的 standalone provider 仍属于跨 app 开发路径。

当前 standalone GUI executor 只支持 stage，standalone live send 未启用。TaShuo
`mac-ios-app` 的实验性 live 全托管由 host-native `ManagedRun` 执行；其他既有路径仍通过 managed-session/host-loop。

使用 standalone 模型 backend 前，需要安装 `.[models]` 可选依赖，并由用户通过
环境变量提供模型供应商 API key；仓库不附带密钥。

TaShuo `mac-ios-app` 另有环境限定的 stage-only production qualification 协议。仓库实现了 Gate，但没有附带任何本机通过证书；“协议已实现”不等于“当前环境 qualification passed”。它只证明某一个固定环境通过了对应验证，不认证 live send，也不代表其他机器或配置已经通过。操作入口和接受条件只放在 [`AGENTS.md`](AGENTS.md) 与 agent runbook 中。

## 安全与隐私

- 不使用私有 API，不提供绕过风控、批量运营、刷赞、账号池或反检测能力。
- Like、super-like、pass、unmatch、report、profile edit、通话、支付等动作不在 agent 执行范围内。
- 未开启 bounded 托管窗口时不发送。窗口内仅普通聊天消息可自动发送，并要求确认目标聊天、精确核对输入文本和验证发送结果。
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

## 文档导航

| 你要做什么 | 从这里开始 |
| --- | --- |
| 让 agent 安装和运行 | [`AGENTS.md`](AGENTS.md) |
| 安装 Codex skill | [`skills/dating-booster-codex/INSTALL.md`](skills/dating-booster-codex/INSTALL.md) |
| 安装其他 host adapter | [`agent_adapters/`](agent_adapters/) |
| 查看 app 能力契约 | [`app_profiles/README.md`](app_profiles/README.md) |
| 理解架构或贡献代码 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| 查看完整文档地图 | [`docs/README.md`](docs/README.md) |

`docs/superpowers/` 保存开发阶段的设计和实施记录，不是用户操作手册。

## 验证

```bash
python3 -m pip install --user -e ".[test]"
python3 -m pytest -q
uv run --extra test python -m pytest -q
```

## 许可证

MIT License，见 [`LICENSE`](LICENSE)。
