# Dating Booster

> Agent 入口：如果你是 Codex、Claude Code、OpenClaw、Hermes 或其他 host agent，请先读 [`AGENTS.md`](AGENTS.md)。安装、启动检查、harness、managed session、host-loop 和安全执行规则都放在那里。这个 README 只面向人类阅读。

Dating Booster 是一个本地优先的 dating workflow 工具层。它帮助用户在 Tinder、Bumble、她说、微信等聊天场景里管理本地记忆、上下文、草稿、策略检查、GUI staging、审计和诊断。

它不是 dating app 客户端，不使用私有 API，不提供绕过风控、批量运营、刷赞、账号池、自动邀约或规模化滥用能力。

## 这个项目解决什么

Dating Booster 的核心假设是：LLM host agent 负责看屏幕、理解可见上下文和起草回复；Dating Booster 负责把这些动作变成本地、可审计、可暂停、可恢复的工具流程。

它现在主要覆盖四件事：

- **本地记忆**：记录用户、对象、对话、承诺和反馈，减少每次从零开始。
- **上下文组装**：把 profile、聊天历史、目标、策略状态整理成可用于起草的 context。
- **安全边界**：默认只 stage 草稿；发送、邀约、交换联系方式等高风险动作需要明确授权和验证。
- **GUI harness**：在 macOS 上通过 iPhone Mirroring 或桌面微信窗口做可测试的观察、导航和草稿 staging。

## 安全边界

默认路径是 `stage`：只准备、粘贴或暂存草稿，不点击发送。

高风险动作默认阻止，包括：

- 发送消息
- like、super-like、pass、unmatch、report
- 修改 profile
- 发起通话、处理支付
- 自动提出见面、交换联系方式
- 任何规模化运营或绕过检测

实验性 live send 只用于用户明确授权的普通聊天消息，并且必须通过 safety switch、目标绑定、草稿精确校验和发送后验证。
Host agent 的 live send 应走 managed-session 或 host-loop；直接 `harness <app> send-message` 是 executor-internal 路径，do not handcraft action requests。

## 当前支持范围

| 场景 | 当前状态 | GUI 依赖 |
| --- | --- | --- |
| Tinder | profile/chat 观察、只读导航、草稿 workflow、可选托管发送 | macOS iPhone Mirroring |
| Bumble | profile/chat 观察、Opening Move 相关流程、可选托管发送 | macOS iPhone Mirroring |
| 她说 / TaShuo | profile/chat 观察、问答门槛相关流程、可选托管发送；Apple Silicon Mac 可试验本地 iOS app runtime（launch/observe/stage 和受控普通聊天 live send） | macOS iPhone Mirroring；可选 mac-ios-app |
| 微信 / WeChat | 桌面窗口观察、草稿 staging、可选托管发送 | macOS 微信桌面端 |

微信在产品语义上是 dating app 转化后的承接场景，不是和 Tinder/Bumble/她说完全同类的 discovery app。用户可以手动授权把某个 dating app 对象的记忆一次性继承到某个微信对象，用于在微信继续聊天。

未支持 app 不会出现在 `app_profiles/` 或 capabilities 里。Hinge 等其他 app 先作为 roadmap candidate 保留，只有具备 fixture、preflight 和可测试 runtime path 后才新增 app profile。

## 全对象托管

`managed-session` 是显式启动后的 session-scoped runner，不是后台监听器。它可以在一个托管窗口内自动管理多个对象，但执行模型是串行 work item：全局 managed-session/operator 按机会窗口、due nudge、新回复、补资料、新匹配等优先级调度；具体 runtime 只执行当前 work item。

启动托管或真实 GUI 操作前先选择目标 app/runtime：

```bash
dating-boost runtime select --data-dir .local/dating-boost --app-id tashuo --runtime mac-ios-app --json
```

选择后，同一个 `data-dir` 下的 harness、host-loop、managed-session 只能使用这个 app/runtime。请求其他 app，或 TaShuo 漏传 `--runtime mac-ios-app` 导致请求 default runtime，会被 `runtime_scope_mismatch` 阻断，不会唤起 iPhone Mirroring、微信或其他无关 app。切换目标时先 `runtime clear`，再重新 select。

生产默认使用 `--management-mode conservative`。链路压测可显式使用 `--management-mode high-throughput --max-threads-per-cycle N --max-pages-per-cycle N --cycle-send-limit N`，但高吞吐只提高每轮预算，不绕过 live-send 授权、target binding、staged-text verification 或 post-send verification。

TaShuo 本地 iOS app 托管需要显式传 `--harness-runtime mac-ios-app`。如果 scope 已选择 mac-ios-app 而命令漏传 runtime，系统会阻断，不会回落到 app profile 默认的 iPhone Mirroring。

`managed-session run/tick` 会返回 `relationship_progress_snapshot`，用于展示本轮全对象状态摘要、下一优先队列和每个对象下一步；`managed-session stop` 和 host-loop final response 会输出用户可读的 `relationship_progress_report`。

TaShuo mac-ios-app 真实托管 smoke 入口：

```bash
python3 scripts/tashuo_mac_ios_managed_smoke.py --data-dir .local/dating-boost --work-dir .local/dating-boost-tashuo-mac-ios-smoke --authorization auth.json --goal goal.json --availability availability.json --json
```

## 给人类的快速开始

如果你只是想试用，最稳定的方式是把仓库链接交给你的 host agent，并明确告诉它：

> 先阅读仓库根目录的 `AGENTS.md`，按里面的安装和启动检查执行。

如果你要自己在本地跑最小 fixture 流程：

```bash
git clone https://github.com/cyberpinkman/dating-booster.git
cd dating-booster
python3 -m pip install --user -e .
python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost
python3 -m dating_boost.cli init-profile --data-dir .local/dating-boost --input tests/fixtures/intelligence/user_profile.json
MATCH_ID=$(python3 -m dating_boost.cli import-observation --data-dir .local/dating-boost --input tests/fixtures/intelligence/app_observation_chat.json | python3 -c 'import json, sys; print(json.load(sys.stdin)["match_id"])')
python3 -m dating_boost.cli draft --data-dir .local/dating-boost --match-id "$MATCH_ID" --mode adaptive --backend scripted --scripted-backend-output tests/fixtures/intelligence/scripted_reply.json
```

Codex skill 的安装细节见 [`skills/dating-booster-codex/INSTALL.md`](skills/dating-booster-codex/INSTALL.md)。Claude Code、OpenClaw、Hermes 的 agent 安装入口见 [`AGENTS.md`](AGENTS.md)。

## 本地数据

生产默认使用本地数据目录，例如 `.local/dating-boost`。macOS 生产路径优先使用 Keychain 管理加密 key；CI 和本地测试可以使用本地 key provider。

常用数据命令：

```bash
dating-boost data migrate --data-dir .local/dating-boost --json
dating-boost data backup --data-dir .local/dating-boost --output dating-boost-backup.zip --json
dating-boost diagnostics bundle --data-dir .local/dating-boost --output diagnostics.zip --json
dating-boost safety pause --data-dir .local/dating-boost --reason manual-stop --json
```

严格 diagnostics/support bundle 默认不包含原始聊天、原始 profile 文本、截图、剪贴板内容或完整草稿。敏感证据需要用户显式同意才会导出。

## 仓库地图

| 路径 | 用途 |
| --- | --- |
| `AGENTS.md` | host agent 的安装、启动检查和运行入口 |
| `dating_boost/cli.py` | memory、policy、workflow、data、diagnostics、harness 等 CLI 入口 |
| `dating_boost/core/` | 本地存储、记忆、策略、规划、生产数据、daemon/safety、GUI harness |
| `dating_boost/apps/` | 各 app 的 adapter、workflow、target binding 和发送验证 |
| `dating_boost/host_loop.py` | supervised host-loop runner |
| `app_profiles/` | app runtime contract，见 `app_profiles/README.md` |
| `agent_adapters/` | Codex、Claude Code、OpenClaw/Hermes 等 host adapter 文档和包 |
| `skills/dating-booster-codex/` | Codex skill、脚本、示例和运行手册 |
| `docs/ARCHITECTURE.md` | 扩展架构：host agent、app、goal、workflow、memory |
| `docs/README.md` | 更细的项目地图 |
| `tests/` | contract、policy、storage、host-loop、skill、harness 测试 |

## 扩展原则

新增 app、host agent、goal 或 memory/workflow 能力时，先看 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)，确认它属于哪条扩展轴。

新增 app 的基本要求：

1. 先有 `app_profiles/<app_id>.json` 和可验证 runtime contract。
2. 至少具备 fixture、preflight、observation/navigation/staging/live-send 边界测试。
3. app 语义归 `dating_boost/apps/<app_id>/adapter.py` 和 app profile，不把 app-specific 参数塞进全局 argparse。
4. CLI、capabilities、managed session 和 host loop 从 registry/profile 派生。
5. 更新 `AGENTS.md`、`app_profiles/README.md`、`docs/README.md` 和相关 skill/adapter 文档。

## 验证

常用回归：

```bash
PYTHONPATH=. uv run pytest -q
```

没有 `uv` 时，可按项目环境安装 test extras 后运行 pytest。

## 许可证

MIT License，见 [`LICENSE`](LICENSE)。
