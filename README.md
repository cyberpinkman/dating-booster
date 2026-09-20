# Dating Booster

> **给 agent：**请先阅读 [`AGENTS.md`](AGENTS.md)，再安装、检查环境和执行任务。

Dating Booster 帮助你的 AI 助手记住聊天背景、起草回复，并在你明确授权的一段时间内代管普通聊天。它通过可见的应用界面操作，本地保存记忆和执行记录；你可以随时暂停或停止。

**目前是预发布实验版。** 全托管的重点是 Apple Silicon Mac 上的「她说」iOS app。本地开发版已有真实导航验证，一条历史发送已通过证据核对确认；**2–3 条短消息连续发送仍未完成实机验收**，尚不能承诺稳定性或端到端速度。

[快速开始](#给人类的快速开始) · [支持范围](#当前支持范围) · [全托管怎么用](#实验性全托管) · [最新进展](#最新进展与验证状态) · [文档地图](docs/README.md)

## 它能做什么

- **记住上下文**：保存你的资料、对方资料、已知事实、约定和反馈，减少每次重新解释。
- **辅助回复**：结合上下文生成草稿，检查内容与表达；可以只展示，或暂存到输入框而不发送。
- **限时全托管**：在授权时长和消息预算内，依次处理多个普通聊天，核对发送对象、文本和结果。
- **遇到问题停下来**：需要你判断、目标不明确或发送结果不确定时暂停或交回处理，保留诊断记录。

未开启托管时默认不发送。托管也不包含点赞、筛选对象、具体邀约、交换联系方式、通话或支付。

## 当前支持范围

可由 **Codex、Claude Code、OpenClaw、Hermes** 驱动；各自安装对应的 skill 或 adapter。Hermes 复用 OpenClaw 兼容适配器。

| App / 环境 | 当前入口与范围 |
| --- | --- |
| **她说 / TaShuo：Apple Silicon Mac 本地 iOS app** | 新全托管入口 `manage` 的重点路径；支持观察、导航、草稿暂存和受控发送，实机验收尚未完成 |
| 她说：macOS iPhone Mirroring | 既有观察、导航、草稿与托管兼容路径 |
| Tinder / Bumble：macOS iPhone Mirroring | 既有观察、导航、草稿与普通聊天托管兼容路径 |
| 微信 / WeChat：macOS 桌面端 | 承接已有关系的聊天、草稿与普通聊天托管兼容路径 |

“已有发送路径”不代表当前机器已经通过实发验证。其他 app 使用 `managed-session` / `host-loop`，不能直接套用下文的她说 `manage` 命令。具体能力由 [`app_profiles/`](app_profiles/) 和本机 `dating-boost capabilities --json` 确认。

她说的本地 app 与 iPhone Mirroring 是两种独立运行环境，不能在一次任务里自动切换。本地 app 不支持 question-gate 暂存或发送；Bumble Opening Move 等特殊互动也不属于普通聊天自动放行范围。微信记忆继承需先由你确认两个账号对应同一个人。

## 给人类的快速开始

### 让你的 agent 安装

将仓库地址和这段话交给你使用的 agent：

> 请安装 https://github.com/cyberpinkman/dating-booster ，先阅读 AGENTS.md，再安装 CLI 和与你对应的 adapter，完成首次环境检查。先帮我准备资料和草稿；只有我明确开启限时全托管后，才允许发送普通聊天消息。

### 手动安装

需要 **Python 3.11+**。真实应用操作需要 macOS；她说本地 iOS app 还需要 Apple Silicon Mac、已安装并登录的 app，以及对应的辅助功能和屏幕录制权限。

```bash
git clone https://github.com/cyberpinkman/dating-booster.git
cd dating-booster
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .

# 以 Codex 为例；其他 host 替换为 claude-code、openclaw 或 hermes
dating-boost adapter codex install --scope user --json
dating-boost adapter codex doctor --data-dir .local/dating-boost --json
dating-boost release doctor --json
dating-boost data doctor --data-dir .local/dating-boost --json
```

若 data doctor 返回 `needs_migration`，先初始化或迁移，再复查：

```bash
dating-boost data migrate --data-dir .local/dating-boost --json
dating-boost data doctor --data-dir .local/dating-boost --json
```

检查通过后确认可用能力：

```bash
dating-boost capabilities --json --data-dir .local/dating-boost
```

后续命令和 agent 都应使用同一个虚拟环境与数据目录。更新源码后，重新执行 `pip install -e .` 和对应的 `adapter … install`；只运行 `git pull` 不会更新已复制的 skill。首次安装、源码或 adapter 更新、迁移、权限变化后重新检查；相同环境的日常启动不必重复完整检查。

详细说明：[Codex 安装](skills/dating-booster-codex/INSTALL.md) · [其他 agent 安装](agent_adapters/README.md)。实际运行规则以 [`AGENTS.md`](AGENTS.md) 为准。

## 实验性全托管

完成安装后，还需设置模型密钥、准备你的用户资料，并选定 app 环境。当前她说 ManagedRun 默认使用 MiniMax 进行视觉理解和回复生成：

```bash
python3 -m pip install -e ".[models]"
# 在运行 agent / CLI 的环境中设置 MINIMAX_API_KEY，不要写入仓库
dating-boost runtime select --data-dir .local/dating-boost --app-id tashuo --runtime mac-ios-app --json
dating-boost user readiness --data-dir .local/dating-boost --mode autonomous --json
```

若返回 `needs_user_profile`，让 agent 先完成资料访谈。选定的 app 环境会保存下来，日常使用无需重复选择。

之后，你可以这样授权：

> 全托管她说 2 小时，只回复普通聊天，最多发送 5 条，不主动追问，23:00–08:00 不发送。需要具体邀约、交换联系方式或遇到不确定情况时交给我。

Agent 会创建本次运行并持有执行进程；你不需要手写授权 JSON。以下是对应的开发者命令，**第二条会开始处理真实界面和合格消息，只应在明确授权后执行**：

```bash
dating-boost manage start \
  --data-dir .local/dating-boost \
  --duration-minutes 120 --send-budget 5 \
  --no-nudge --quiet-hours 23:00-08:00 --json

dating-boost manage run --data-dir .local/dating-boost --wait --poll-interval 30 --json
```

`start` 只保存本次运行，不打开界面、不启动后台任务；`run --wait` 才持续执行。Host 应持有这个进程，进程结束后不会继续托管。主动跟进默认关闭，只有你明确允许时才加 `--nudge`。首次实发应使用短时长、小预算。

你可以直接对 agent 说“查看进度”“暂停”“继续”或“停止”，也可使用：

| 操作 | 命令 | 行为 |
| --- | --- | --- |
| 查看进度 | `dating-boost manage status --data-dir .local/dating-boost --json` | 查看当前运行 |
| 暂停 | `dating-boost manage pause --data-dir .local/dating-boost --json` | 在下一次界面修改前停止推进，执行循环退出 |
| 继续 | `dating-boost manage resume --data-dir .local/dating-boost --json` | 恢复同一次运行；agent 随后重新持有 `run --wait` |
| 停止 | `dating-boost manage stop --data-dir .local/dating-boost --json` | 结束本次运行并返回进度报告 |

Host-native 是默认路径，即由现有 agent 接入、管理任务。普通草稿可由 host 起草；ManagedRun 在本地执行循环中调用模型。另一个显式选择的入口 `standalone-session` 用于独立运行：目前 standalone GUI executor 只支持 stage（暂存草稿），standalone live send 未启用，不应与 ManagedRun 混用。

## 最新进展与验证状态

**截至 2026-09-20，本节是本地开发进展。** 本次先同步文档；下列 Jev、连发与视觉验证重构的代码尚未推送到远端。仅克隆当前 `main` 不会获得这些改动，配置与开发验证见[性能与 Jev 说明](docs/managed-run-performance.md)。

| 本地改动 | 解决的问题 |
| --- | --- |
| 复用短期消息列表队列 | 避免每处理一个对象都重新扫描同一列表；进入会话后仍重新核对对象 |
| 可选 TypeSafe / Jev 文本判断 | 先判断是否值得回复、是否需要你接手，减少不必要的起草；Jev 不读图、不生成回复 |
| 一次起草 2–3 条短消息，本地顺序发送 | 组内不再反复返回 host 分析、重新起草或等待下一轮轮询；每条仍独立验证并占用预算 |
| 输入框与聊天正文分别取证 | AX（macOS 辅助功能）检查输入框；视觉模型理解聊天和核对新增气泡，不再强求 AX 读取气泡正文 |
| 文字框辅助定位与统一草稿改写规则 | 减少含表情昵称的定位偏差，让可修订草稿进入一次改写后再审核 |

最近一次本地常规回归记录为 **2192 项通过、193 项夜间测试未运行**。真实设备已验证多个会话的导航与身份核对；历史一次发送经原始证据核对确认，未重发。最近一轮实测在应用前台／窗口绑定处受阻，已暂停，新增发送 0 条。

**尚未验收：**完整的两条连续实发、实际消息间隔，以及稳定的端到端耗时。局部计时和离线模拟不能替代这些结果；本项目也未据此取得生产环境认证。

## 安全与隐私

- **发送有范围**：限于你授权窗口内的普通聊天；不自动点赞、pass、unmatch、举报、改资料、安排具体邀约、交换联系方式、通话或支付。不使用私有 API 或风控绕过。
- **结果要核对**：确认对象与输入文本后才发送，发送后读取新鲜界面核验；结果不确定时暂停，禁止自动重发。底层发送命令仅供受控执行器使用，不手工拼装发送请求。
- **数据在本地加密保存**：业务数据使用加密 SQLite，macOS 默认通过 Keychain 管理密钥。项目不发送网络遥测。
- **模型调用有数据边界**：host 或配置的模型服务可能处理本次任务的可见内容。本地开发版若显式开启 Jev，也会将必要的可见聊天文本发送给 TypeSafe；它不接收截图或整库记忆。
- **诊断默认脱敏**：严格诊断包不含原始聊天、资料、截图、剪贴板或完整草稿。Support session 用于实机验收、诊断或导出，不是每次日常启动的前置条件。

## 本地数据

示例统一使用 `.local/dating-boost`；请持续使用同一目录，避免把不同运行状态混在一起。检查数据用 `data doctor`，只有提示需要迁移时才运行 `data migrate`。

全局暂停与单次 ManagedRun 暂停不同：它会阻止真实草稿写入和发送，可用于阻止后续界面修改：

```bash
dating-boost safety pause --data-dir .local/dating-boost --reason manual-stop --json
dating-boost safety status --data-dir .local/dating-boost --json
```

## 文档导航

| 你要做什么 | 入口 |
| --- | --- |
| 让 agent 安装和执行任务 | [`AGENTS.md`](AGENTS.md) |
| 安装 Codex / 其他 host | [Codex 安装](skills/dating-booster-codex/INSTALL.md) · [适配器目录](agent_adapters/README.md) |
| 理解 Jev、连发与实测进度 | [性能与 Jev 说明](docs/managed-run-performance.md)，本地开发中 |
| 查各 app 的能力与限制 | [`app_profiles/README.md`](app_profiles/README.md) |
| 理解架构或贡献代码 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| 找运行手册和维护资料 | [`docs/README.md`](docs/README.md) |

`docs/superpowers/` 是历史设计与实施记录，不是用户操作手册。

## 验证

不打开 app、不调用真实模型、不发送消息的安装检查（`local` 密钥仅用于这个可丢弃的测试目录）：

```bash
DATING_BOOST_KEY_PROVIDER=local \
python3 scripts/agent_native_smoke.py --data-dir .local/dating-boost-smoke
```

开发者在已激活的虚拟环境中运行常规回归，与 CI 的主要反馈路径一致：

```bash
python3 -m pip install -e ".[test]"
python3 -m pytest -m "not nightly_lab" -q
```

完整测试（含较慢的夜间协议）使用 `python3 -m pytest -q`。这些测试不能证明真实应用已通过发送验收。

## 许可证

[MIT License](LICENSE)。
