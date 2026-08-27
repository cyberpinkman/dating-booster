# Agent 引导文档

本文档给 Codex、Claude Code、OpenClaw、Hermes 或其他 host agent 阅读。人类入口在 `README.md`。

Dating Booster 是本地优先的 dating workflow 工具层。Host agent 负责观察可见 app UI、理解上下文和起草回复；Dating Booster 负责本地记忆、上下文、策略检查、工作流契约、GUI staging、审计、诊断和恢复。

## 必读边界

- 不使用私有 API，不做风控绕过，不做批量运营。
- 未开启 bounded live workflow 时默认只 stage 草稿，不发送。
- 用户明确开启 ManagedRun 或既有 managed executor 后，Live send 只允许授权窗口内的普通聊天消息。
- `harness <app> send-message --authorization --action-request` 是 executor-internal 路径，只能消费系统生成的 work item 或确认流结果；do not handcraft action requests。
- 不得执行 like、super-like、pass、unmatch、report、profile edit、premium purchase、call、payment、自动邀约或自动交换联系方式。
- 首次安装、更新、迁移或权限变化后，观察可见 app 内容前先完成对应兼容性检查；
  日常 ManagedRun 复用已经验证的环境。Support session 只用于 real-GUI Canary、
  明确诊断或导出 support bundle。

## 克隆和安装

测试用户入口是仓库链接。agent 自己 clone、阅读本文件、安装 CLI，再按目标 host 安装 adapter。

```bash
git clone https://github.com/cyberpinkman/dating-booster.git
cd dating-booster
python3 -m pip install --user -e .
python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost
```

Codex:

```bash
python3 -m dating_boost.cli adapter codex install --scope user --json
python3 -m dating_boost.cli adapter codex doctor --data-dir .local/dating-boost --json
```

Claude Code:

```bash
python3 -m dating_boost.cli adapter claude-code install --scope user --json
python3 -m dating_boost.cli adapter claude-code doctor --data-dir .local/dating-boost --json
```

项目级 Claude Code 安装会写入 `.claude/skills/dating-booster/`；用户级安装写入 `~/.claude/skills/dating-booster/`。

OpenClaw:

```bash
python3 -m dating_boost.cli adapter openclaw install --scope user --json
python3 -m dating_boost.cli adapter openclaw doctor --data-dir .local/dating-boost --json
```

项目级 OpenClaw 安装会写入 `.openclaw/skills/dating-booster/`；用户级安装写入 `~/.openclaw/skills/dating-booster/`。

Hermes 使用 OpenClaw-compatible skill contract：

```bash
python3 -m dating_boost.cli adapter hermes install --scope user --json
python3 -m dating_boost.cli adapter hermes doctor --data-dir .local/dating-boost --json
```

更新 source checkout 后必须重新运行 editable install 和对应 adapter install；只 `git pull` 不会更新已复制到 host skill 目录里的内容。

Codex skill 的细节在 `skills/dating-booster-codex/INSTALL.md`。

## 安装/更新检查与日常快启

完整 doctor 用于首次安装、源码或 adapter 更新、数据迁移、macOS 权限变化，以及
明确的故障诊断；它不再是每次 ManagedRun 日常启动的同步热路径。需要完整检查时运行：

```bash
python3 -m dating_boost.cli adapter codex doctor --data-dir .local/dating-boost --json
python3 -m dating_boost.cli release doctor --json
python3 -m dating_boost.cli data doctor --data-dir .local/dating-boost --json
python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost
```

示例使用 Codex；其他 host 把 `codex` 替换为 `claude-code`、`openclaw` 或
`hermes`。

如果 data doctor 返回 `needs_migration`，运行
`python3 -m dating_boost.cli data migrate --data-dir .local/dating-boost --json`，
然后重新运行 data doctor 和 capabilities。迁移失败或检查不兼容时，不得观察
app 内容。

检查：

- adapter/skill doctor、release doctor 和 data doctor 均通过。
- CLI 版本和 skill/adapter 要求兼容。
- `supported_app_profiles` 包含目标 app。
- `schema_versions` 覆盖当前 workflow 需要的 contract。
- `managed_live_send_guidance.direct_harness_scope` 仍为 executor-internal only。

日常启动同一个已经安装、迁移并验证过的 TaShuo ManagedRun 时，直接执行
`manage start`。该入口同步检查用户 readiness、授权范围和持久化 run；provider 在
触碰 GUI 前检查 runtime scope、模型配置和全局 pause。若返回一个具体阻断原因，
只执行对应恢复动作后重试；不要无条件串行重跑四个 deep doctor。

Support session 用于首次 real-GUI Canary、用户明确的诊断或需要导出 support bundle
的任务，不是每次日常 run 的启动条件。需要诊断时开启：

```bash
dating-boost support session start --data-dir .local/dating-boost --host codex --app-id tinder --json
```

示例使用 Codex/Tinder；按当前 host 和已确认的目标 app 替换这两个值。

把返回的 `session_id` 用于后续 support bundle。任务结束时先停止 session；需要诊断时再导出 strict bundle：

```bash
dating-boost support session stop --data-dir .local/dating-boost --session-id <session_id> --json
dating-boost support bundle --data-dir .local/dating-boost --session-id <session_id> --output dating-boost-support.zip --redaction strict --json
```

严格 bundle 默认不含 raw chat、raw profile、截图、剪贴板内容或完整草稿。不要在
support session start 和 bundle export 之间对同一个 data dir 运行 `data migrate`
或 `data delete`。

首次选择或用户明确切换目标时，在同一个 `data-dir` 里选择 app/runtime：

```bash
dating-boost runtime select --data-dir .local/dating-boost --app-id tashuo --runtime mac-ios-app --json
dating-boost runtime status --data-dir .local/dating-boost --json
```

选择会持久化；相同 data-dir 和相同目标的日常 run 不需要重复 select。所有真实 GUI
harness 命令仍传同一个 `--data-dir`；如果命令请求其他 app/runtime，CLI 必须返回
`runtime_scope_mismatch`，不得创建错误 adapter 或唤起无关 app。只有用户明确切换
目标时，才运行 `dating-boost runtime clear --data-dir .local/dating-boost --json` 后
重新 select。

## 当前 app 语义

| App | 当前用途 | Harness |
| --- | --- | --- |
| Tinder | discovery app；profile/chat 观察、只读导航、草稿 workflow、可选托管发送 | macOS iPhone Mirroring |
| Bumble | discovery app；profile/chat 观察、Opening Move 相关流程、可选托管发送 | macOS iPhone Mirroring |
| 她说 / TaShuo | discovery app；profile/chat 观察、question-gate 相关流程、可选托管发送 | macOS iPhone Mirroring；可选 mac-ios-app |
| WeChat / 微信 | continuation channel；承接 dating app 转化后的聊天 | macOS 微信桌面端 |

微信不是 discovery dating app。用户说“从 Tinder/Bumble/她说加到微信了”时，先让用户确认 source 和 target 是同一个现实对象，再使用一次性单向记忆继承：

```json
{
  "action": "inherit_memory",
  "source_match_id": "<dating_app_match_id>",
  "target_match_id": "<wechat_match_id>",
  "direction": "dating_app_to_wechat",
  "confirmed_by": "user",
  "confirmation_token": "inherit_memory:<dating_app_match_id>:<wechat_match_id>"
}
```

执行：

```bash
dating-boost memory update-match --data-dir .local/dating-boost --match-id <wechat_match_id> --input inherit.json
```

这不是 identity merge：不删除 source，不双向同步，不继承 source 的 identity conflict。

## Draft workflow

Host agent 起草，Dating Booster 做本地记忆、上下文和策略检查。

```bash
dating-boost memory ingest-observation --data-dir .local/dating-boost --input observation.json
dating-boost context build --data-dir .local/dating-boost --match-id <match_id> --mode adaptive > context.json
dating-boost policy check-draft --input draft.json --context context.json
```

内部自然度检查不要默认展示给用户。除非用户明确要求解释、debug、review，否则只展示最终草稿。

## Tinder quick path

```bash
dating-boost runtime select --data-dir .local/dating-boost --app-id tinder --runtime default --json
dating-boost harness doctor --app-id tinder --data-dir .local/dating-boost --json
dating-boost harness tinder launch --dry-run --data-dir .local/dating-boost --json
dating-boost harness tinder observe --output-dir .local/dating-boost-harness --data-dir .local/dating-boost --json
dating-boost harness tinder action prepare-message-page --data-dir .local/dating-boost --output-dir .local/dating-boost-harness --json
dating-boost harness tinder workflow self-profile-read --dry-run --options-json tinder-self-profile-options.json --data-dir .local/dating-boost --json
dating-boost harness tinder workflow chat-read-match-profile --dry-run --options-json tinder-chat-profile-options.json --data-dir .local/dating-boost --json
dating-boost harness tinder workflow new-match-open --dry-run --options-json tinder-new-match-options.json --data-dir .local/dating-boost --json
dating-boost harness tinder workflow new-match-read-profile --dry-run --options-json tinder-new-match-profile-options.json --data-dir .local/dating-boost --json
dating-boost harness tinder action open-conversation --options-json tinder-open-conversation-options.json --data-dir .local/dating-boost --json
dating-boost harness tinder action dismiss-subscription-paywall --data-dir .local/dating-boost --json
dating-boost harness tinder action dismiss-feedback-survey --data-dir .local/dating-boost --json
dating-boost harness tinder stage-draft --text-file tinder-draft.txt --data-dir .local/dating-boost --dry-run --json
```

`prepare-message-page` 会把 Tinder 规整到消息列表：如果已在普通会话则返回列表，如果在顶层页则点聊天 tab，然后返回 `next_host_action=visual_plan_message_list`。后续由 host agent 视觉规划消息列表；不要先跑 OCR 再回退视觉，也不要用固定 row 坐标直接进入聊天线程。
`stage-draft` 是 stage-only：只粘贴草稿并验证输入框 staged text，不点击 Send；真实执行必须传 `--data-dir`，让 safety pause 可以阻断 staging。
`chat-read-match-profile` 只用于已有消息行。`new-match-open` 打开未开聊匹配并停在会话页。`new-match-read-profile` 读取未开聊匹配资料后回到当前会话。
已有普通会话优先用 `open-conversation` 的 `visible_name` 或 `target_binding` 让 harness 用 OCR TSV 定位行。emoji 或非 OCR 昵称使用 `chat_list_row_to_thread` 结构证据，并在 options JSON 里携带 `message_list_evidence.visual_anchor_hash`、`visual_anchor_region`、可选 `tap_ratio`/`visual_anchor_scan_region`，让 harness 在当前消息列表截图中重定位该行；固定 `row_index` 只是兼容 fallback。若已经在目标线程内，可用 `current_thread_visual_identity` 绑定 `thread_evidence.visual_anchor_hash` 验证当前线程视觉身份；若发送/预 staging 前该视觉身份不匹配，且同一目标绑定里有 `message_list_evidence` 视觉锚点，harness 会返回消息列表、按视觉锚点重开同一行并重新验证目标。它不替代 staged-text OCR 或 outbound verification。Tinder managed live send 必须携带 `chat_list_row_to_thread` 或 `current_thread_visual_identity` 结构化目标绑定，不能只靠 `visible_name`/OCR 名字。不要用 `Aa`、`GIF`、`Send`、`聊天`、`等你回应` 这类通用 UI marker 代替目标绑定。

如果出现订阅、Gold、Likes You、plan-selection paywall，只能关闭并重新导航；subscription purchase 或 plan selection 不是 agent action。反馈问卷用 ignore/no-rating 路径关闭，`rating_submitted` 必须是 false。

## Bumble quick path

```bash
dating-boost runtime select --data-dir .local/dating-boost --app-id bumble --runtime default --json
dating-boost harness doctor --app-id bumble --data-dir .local/dating-boost --json
dating-boost harness bumble launch --dry-run --data-dir .local/dating-boost --json
dating-boost harness bumble observe --output-dir .local/dating-boost-harness --data-dir .local/dating-boost --json
dating-boost harness bumble action open-chats --dry-run --data-dir .local/dating-boost --json
dating-boost harness bumble action prepare-message-page --data-dir .local/dating-boost --output-dir .local/dating-boost-harness --json
dating-boost harness bumble action open-conversation --options-json bumble-open-conversation-options.json --data-dir .local/dating-boost --json
dating-boost harness bumble workflow browse-profile-read --dry-run --options-json bumble-profile-options.json --data-dir .local/dating-boost --json
dating-boost harness bumble workflow chat-read-match-profile --dry-run --options-json bumble-chat-profile-options.json --data-dir .local/dating-boost --json
dating-boost harness bumble workflow opening-move-open --dry-run --options-json bumble-opening-move-options.json --data-dir .local/dating-boost --json
dating-boost harness bumble stage-draft --text-file bumble-draft.txt --data-dir .local/dating-boost --dry-run --json
```

Opening Move 是 role-sensitive：女性用户场景下 agent 不决定是否启用/跳过，也不判断男性回复是否足够好；男性用户场景下可以为用户 review 起草 Opening Move 回复。
`prepare-message-page` 会把 Bumble 规整到聊天列表：如果已在普通会话或 Opening Move 页则返回列表，如果在顶层页则点聊天 tab，然后返回 `next_host_action=visual_plan_message_list`。后续由 host agent 视觉规划聊天列表；不要用固定 row 坐标直接进入聊天线程。
`stage-draft` 是 stage-only：只粘贴草稿并验证输入框 staged text，不点击 Send；OCR 不足时等待 host staged verification，不记录发送结果。
已有普通会话优先用 `open-conversation` 的 `visible_name` 或 `target_binding` 让 harness 用 OCR TSV 定位行。emoji 或非 OCR 昵称使用 `chat_list_row_to_thread` 结构证据，并在 options JSON 里携带 `message_list_evidence.visual_anchor_hash`、`visual_anchor_region`、可选 `tap_ratio`/`visual_anchor_scan_region`，让 harness 在当前聊天列表截图中重定位该行；固定 `row_index` 只是兼容 fallback。若已经在目标线程内，可用 `current_thread_visual_identity` 绑定 `thread_evidence.visual_anchor_hash` 验证当前线程视觉身份；若发送/预 staging 前该视觉身份不匹配，且同一目标绑定里有 `message_list_evidence` 视觉锚点，harness 会返回聊天列表、按视觉锚点重开同一行并重新验证目标。它不替代 staged-text OCR 或 outbound verification。Bumble managed live send 必须携带 `chat_list_row_to_thread` 或 `current_thread_visual_identity` 结构化目标绑定，不能只靠 `visible_name`/OCR 名字。不要用 `Aa`、`GIF`、`Send`、`Opening Move`、`聊天` 这类通用 UI marker 代替目标绑定。

## TaShuo quick path

TaShuo 的 iPhone Mirroring `default` runtime 和本地 `mac-ios-app` runtime 是
互斥分支，不是顺序步骤。为当前 data dir 选择其中一个后，只能继续使用该分支；
只有用户明确切换目标时，才先运行 `dating-boost runtime clear` 再选择另一个
runtime。

### iPhone Mirroring (`default`)

```bash
dating-boost runtime select --data-dir .local/dating-boost --app-id tashuo --runtime default --json
dating-boost harness doctor --app-id tashuo --data-dir .local/dating-boost --json
dating-boost harness tashuo launch --data-dir .local/dating-boost --dry-run --json
dating-boost harness tashuo observe --data-dir .local/dating-boost --output-dir .local/dating-boost-harness --json
dating-boost harness tashuo action open-chats --data-dir .local/dating-boost --dry-run --json
dating-boost harness tashuo workflow chat-read-match-profile --data-dir .local/dating-boost --dry-run --options-json tashuo-chat-profile-options.json --json
dating-boost harness tashuo workflow question-gate-open --data-dir .local/dating-boost --dry-run --options-json tashuo-question-gate-options.json --json
```

Apple Silicon Mac 上如果用户已经安装并登录 Mac App Store 的她说 iOS app，可优先试验本地 `mac-ios-app` runtime。该 runtime 不占用真实手机，当前支持 launch/observe/prepare-message-page/stage-draft，以及受托管 live-send gate 保护的普通聊天 `send-message`。`send-message --runtime mac-ios-app` 仍是 executor-internal 路径，只能消费系统生成的 action request 或确认流结果；发送前必须有结构化目标绑定、exact staged-text verification，发送后必须有 input-cleared 和 outbound exact-text verification。question-gate staging/sending 仍不支持。

### 本地 iOS app (`mac-ios-app`)

```bash
dating-boost runtime select --data-dir .local/dating-boost --app-id tashuo --runtime mac-ios-app --json
dating-boost harness doctor --app-id tashuo --data-dir .local/dating-boost --runtime mac-ios-app --json
dating-boost harness tashuo action prepare-message-page --data-dir .local/dating-boost --runtime mac-ios-app --output-dir .local/dating-boost-harness --json
dating-boost harness tashuo stage-draft --data-dir .local/dating-boost --runtime mac-ios-app --text-file tashuo-draft.txt --dry-run --json
```

`prepare-message-page` 会打开 TaShuo Mac iOS app，用底部 tab 的视觉高亮判断当前一级页；如果不在 `消息` 页，只点击底部 `消息` tab。进入消息页后停止固定坐标流程，返回 `next_host_action=visual_plan_message_list`，后续由 host agent 进行视觉分析和规划，不要先跑 OCR 再回退视觉，也不要用固定 row 坐标直接进入聊天线程。

TaShuo mac-ios-app 的既有兼容 executor 支持通过 host-loop/managed-session 发送普通聊天；下方命令属于兼容路径。新的旗舰 ManagedRun 使用本文件后述的四段 action seam，不消费手工或 operator 生成的 action request。两条路径都不得绕过结构绑定、staged-text 和 post-send verification：

```bash
dating-boost-host-loop run --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tashuo --send-mode live --managed-gui-send --harness-runtime mac-ios-app --work-dir .local/dating-boost-host-loop --json
```

TaShuo mac-ios-app 的辅助脚本默认 stage mode，不真实发送。当前脚本只跑到
managed-session 配置提案，并应以
`managed_session_config_confirmation_required` 停止；它没有接受配置的参数，
不能作为完整托管 smoke 成功证明。用户确认配置后，使用下方通用
`managed-session start` 两阶段流程继续：

```bash
python3 scripts/tashuo_mac_ios_managed_smoke.py --data-dir .local/dating-boost --work-dir .local/dating-boost-tashuo-mac-ios-smoke --authorization auth.json --goal goal.json --availability availability.json --json
```

TaShuo 启动搜索使用 `tashu` 并通过截图/OCR 确认 `她说` 或 `TaShuo`。`飞行` screen-tap chat starts、recommendation likes、passes、question-gate decisions 都是 blocked actions。

## WeChat quick path

```bash
dating-boost runtime select --data-dir .local/dating-boost --app-id wechat --runtime default --json
dating-boost harness doctor --app-id wechat --data-dir .local/dating-boost --window-title WeChat --json
dating-boost harness wechat launch --data-dir .local/dating-boost --dry-run --json
dating-boost harness wechat observe --data-dir .local/dating-boost --output-dir .local/dating-boost-harness --json
dating-boost harness wechat stage-draft --text-file wechat-draft.txt --data-dir .local/dating-boost --dry-run --json
```

微信 stage 使用剪贴板把已通过 policy check 的草稿放入当前输入框；stage mode 不按 Enter、不点击 Send。真实 staging 必须传 `--data-dir`，让全局 safety pause 能阻断 paste。

## ManagedRun

新的实验性旗舰入口是 `ManagedRun`。`managed-session`/`host-loop` 保留为兼容路径；
不要因为新入口仍处于实验阶段，就把用户明确要求的全托管降级成只起草一句回复。

### Experimental ManagedRun（TaShuo mac-ios-app）

当前唯一重点纵切面是 TaShuo `mac-ios-app`。用户只确认一次 app/runtime、时长、
普通聊天范围、quiet hours、nudge 和发送预算；窗口内合格普通消息不逐条确认。
Like/pass/question-gate/具体邀约/联系方式/资料编辑/通话/支付等仍永久 handoff。

首次安装、更新、迁移或权限变化后，先完成上文的兼容性检查；日常启动只同步检查
用户 readiness、授权和已经持久化的同一 data-dir runtime scope。Support session
只在 real-GUI Canary、明确诊断或需要 bundle 时开启。默认模型和视觉 backend 复用
TaShuo standalone 的 MiniMax 配置；
安装 `.[models]` 并设置 `MINIMAX_API_KEY`。用户不需要准备 authorization、goal、
availability 或 provider JSON。

```bash
dating-boost runtime select --data-dir .local/dating-boost --app-id tashuo --runtime mac-ios-app --json
dating-boost manage start --data-dir .local/dating-boost --duration-minutes 120 --send-budget 5 --nudge --quiet-hours 23:00-08:00 --json
```

`start` 只创建并绑定 durable run，不扫描、不打开 GUI，也不启动后台 worker。
Host 随后立即持有一个前台阻塞的 wait loop，不把第二条命令暴露成用户步骤；
host/task/进程退出后不会继续运行：

```bash
dating-boost manage run --data-dir .local/dating-boost --wait --poll-interval 30 --json
```

对用户只展示 `manage start/status/pause/resume/stop`。Pause 在下一次 GUI mutation
前生效并让当前 wait loop 退出；Resume 只恢复 durable 状态，host 还必须用同一
data-dir 为同一 run 重新启动 `run --wait`，不能新建 run。Stop 返回
`relationship_progress_report`。`run/tick` 是公开 CLI 子命令，“内部”只是产品交互
分层，不是访问控制边界。

ManagedRun live action 只能通过四段 adapter seam：composer observe、exact stage、
Return-only click、fresh post-send observe。它不调用一体化 `send_message`。任何
`unknown_after_click` 都暂停整个 run，禁止自动重发。真实 GUI Canary 尚未在代码
实现过程中自动执行；只有用户明确授权并完成本节所有前置检查后才能做小预算实发。

高级开发环境可通过 `DATING_BOOST_MANAGED_RUN_TASHUO_CONFIG` 覆盖默认模型配置；
fixture 只在同时设置 `DATING_BOOST_MANAGED_RUN_FIXTURE_DIR` 和
`DATING_BOOST_MANAGED_RUN_SCRIPTED_BACKEND_OUTPUT` 时启用，不能把 fixture send
称为真实 GUI send。

## Managed session（兼容路径）

`managed-session` 只在用户显式启动后的当前托管窗口内运行。Session 外不监听、不扫描、不自动回复。全对象自动管理是全局 `managed-session`/`operator` 能力：runner 按机会窗口优先级串行处理多个对象，runtime 只执行当前 work item，不决定全局优先级。

启动前先运行
`dating-boost user readiness --data-dir .local/dating-boost --mode autonomous --json`。
如果返回 `needs_user_profile`，先完成“用户自我模型”步骤，不得启动
managed-session。

启动前先选择目标 app/runtime；`managed-session start` 会校验并写入同一个 runtime scope。运行中不能从 TaShuo mac-ios-app 自动漂移到默认 iPhone Mirroring，也不能切到微信等其他 app。

```bash
dating-boost managed-session start --app-id tinder --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --send-mode stage --scan-interval 120 --nudge-delay-minutes 30 --management-mode conservative --json
```

第一次 `managed-session start` 可能返回
`managed_session_config_confirmation_required`。向用户展示并核对
`proposed_config`；只有用户确认后，才使用返回的
`--config-confirm managed-session-config:<hash>` 以其余参数完全相同的命令重跑。
未确认前不要进入 `run`。

```bash
dating-boost managed-session start --app-id tinder --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --send-mode stage --scan-interval 120 --nudge-delay-minutes 30 --management-mode conservative --config-confirm managed-session-config:<hash> --json
dating-boost managed-session run --wait --data-dir .local/dating-boost --json
dating-boost managed-session notify --data-dir .local/dating-boost --source manual --app-id tinder --json
dating-boost managed-session status --data-dir .local/dating-boost --json
dating-boost managed-session stop --data-dir .local/dating-boost --json
```

生产默认 `--management-mode conservative`；真实链路压测可显式使用 `--management-mode high-throughput --max-threads-per-cycle N --cycle-send-limit N`。高吞吐只提高每轮处理/发送预算，不绕过授权、target binding、staged-text verification 或 post-send verification。不要让用户设置 `max_pages_per_cycle`；消息列表扫描到第一个 7 天无进展的历史行后停止，后面的行不属于本轮托管窗口。
TaShuo 本地 iOS app 托管必须显式传 `--harness-runtime mac-ios-app`。如果当前 `runtime select` 已选择 mac-ios-app 而命令漏传 runtime，会被 `runtime_scope_mismatch` 阻断，不允许回落到默认 iPhone Mirroring runtime。
`managed-session run/tick` 返回 `relationship_progress_snapshot`，用于 host 展示本轮全对象状态摘要、下一优先队列和每个对象下一步；`managed-session stop` 和 host-loop final response 返回用户可读 `relationship_progress_report`。

Tinder/Bumble iPhone Mirroring 托管 stage smoke：

```bash
python3 scripts/iphone_mirroring_managed_smoke.py --app-id tinder --data-dir .local/dating-boost --work-dir .local/dating-boost-iphone-smoke --authorization auth.json --goal goal.json --availability availability.json --json
python3 scripts/iphone_mirroring_managed_smoke.py --app-id bumble --data-dir .local/dating-boost --work-dir .local/dating-boost-iphone-smoke --authorization auth.json --goal goal.json --availability availability.json --json
```

该 smoke 会先运行 skill doctor、release doctor、data doctor/migrate 和 capabilities 兼容性检查，并确认 direct harness 仍是 executor-internal only；任何前置 gate 失败都会在启动真实 GUI 前阻断。该 smoke 默认不自动确认 managed-session 配置；如果返回 `managed_session_config_confirmation_required`，先展示/检查 `proposed_config`，用户确认后再用 `--accept-managed-session-config` 重跑。iPhone Mirroring 锁定或不可用时返回 blocked reason，按实机不可用跳过，不伪造成功。
Tinder/Bumble iPhone Mirroring stage/send 在粘贴前必须检查当前输入框是否已有未发送内容；若 baseline composer 看起来已占用，必须在读取剪贴板或粘贴前阻断，不能把新草稿追加到旧文本上。

当 `managed-session run --wait` 返回 `host_work_required`，host agent 处理其中的 operator work item。如果用 host-loop supervisor 处理，使用同一个 data/work dir 运行：

```bash
dating-boost-host-loop resume --data-dir .local/dating-boost --work-dir .local/dating-boost-host-loop --json
dating-boost managed-session run --wait --data-dir .local/dating-boost --json
```

不要启动新的 `dating-boost-host-loop run` 来处理同一个 wait point，因为新 run 会创建新的 operator session。

## Standalone session

For Codex, Claude Code, OpenClaw, and Hermes, host-native remains the default route. Use `standalone-session` only when the user explicitly asks to run Dating Booster's local standalone agent runtime.

Primary standalone mode is TaShuo mac-ios-app stage-first with MiniMax Coding Plan:

```bash
export MINIMAX_API_KEY="<coding-plan-subscription-key>"
dating-boost runtime select --data-dir .local/dating-boost --app-id tashuo --runtime mac-ios-app --json
python3 scripts/tashuo_mac_ios_standalone_doctor.py --data-dir .local/dating-boost --json
DATING_BOOST_KEY_PROVIDER=local python3 scripts/tashuo_mac_ios_standalone_smoke.py --data-dir .local/dating-boost --authorization auth.json --json
```

Stage-only `auth.json` must allow managed stage work item creation while disabling live send:

```json
{
  "schema_version": 1,
  "authorization_id": "auth_tashuo_standalone_stage",
  "app_id": "tashuo",
  "scope": "send_chat_messages",
  "allowed_actions": ["send_message"],
  "allowed_match_ids": [],
  "goal_ids": [],
  "autonomous_send": true,
  "autonomous_nudge": false,
  "live_send": false,
  "requires_post_action_verification": true,
  "quiet_hours": [],
  "created_at": "2026-06-22T00:00:00Z",
  "expires_at": "2099-01-01T00:00:00Z",
  "revoked_at": null
}
```

MiniMax Coding Plan is the default standalone TaShuo smoke backend and vision backend through the MiniMax China OpenAI-compatible endpoint, matching the local Hermes `minimax-cn` route. Put the Coding Plan subscription key in `.env` or an environment variable; standalone session state stores only the env var name. The standalone smoke wrapper runs the alpha release gate before reporting success. A successful smoke returns `status=ok`, `reason=tashuo_standalone_stage_smoke_complete`, with `alpha_release_gate.status=ok`, final tick `stage_recorded`, and durable proof in the logical `audit/stage_results.jsonl` stream backed by encrypted SQLite: `stage_attempt_status=completed`, `staged_text_verified=true`, `staged_text_verification.status=verified`, `target_verification.status=ok`, `evidence.stage_mode=true`, and `evidence.live_send_executed=false`.

If the smoke JSON is saved, rerun the same acceptance gate without opening the app:

```bash
python3 scripts/tashuo_mac_ios_standalone_alpha_gate.py --data-dir .local/dating-boost --smoke-json tashuo-standalone-smoke.json --json
```

TaShuo standalone production qualification is a separate, stage-only protocol pinned to `tashuo/mac-ios-app`; it does not qualify live send. Do not open the App for a real qualification until the automated suite, release doctor, wheel smoke, and clean-environment fingerprint all pass. A real Canary requires the user's explicit instruction:

```bash
python3 scripts/tashuo_mac_ios_standalone_production_gate.py canary \
  --root-dir .local/tashuo-production-qualifications \
  --user-model-source-data-dir .local/dating-boost \
  --authorization auth.json \
  --json
```

`canary_passed` means only `canary passed for the pinned environment; soak not run; qualification not passed`. Never start Soak automatically. Show the qualification id, config hash, certificate digest, acceptance token, and 24-hour expiry; only after the user inspects and explicitly accepts them may the agent run the returned 100-cycle, at-least-8-hour Soak command.

The Gate exposes exactly `canary`, `soak`, `status`, `resume`, `finalize`, and `validate`. `status` is read-only. Mutating commands run the root janitor. `resume` must preserve the active phase, reconcile worker/support/attempt state, and never repeat staging after a committed boundary. Unknown target/composer state requires the shared runtime safety pause and retained encrypted recovery state.

Source mode requires a clean checkout. `--built-artifact <wheel>` is valid only when the actually loaded package is outside the source checkout and its Python-file digest matches the wheel. Passing an unused wheel is not an override. Final success is valid only when offline `validate` returns `artifact_valid=true`, `qualification_passed=true`, and `claim_code=PROTOCOL_PASSED_PINNED_ENVIRONMENT`.

Manual standalone start, if not using the smoke wrapper:

```bash
DATING_BOOST_KEY_PROVIDER=local dating-boost standalone-session start --data-dir .local/dating-boost --authorization auth.json --app-id tashuo --runtime mac-ios-app --send-mode stage --observation-source live-gui --vision-backend minimax --backend minimax --model MiniMax-M3 --vision-model MiniMax-M3 --minimax-api-key-env MINIMAX_API_KEY --json
```

第一次 `standalone-session start` 只返回配置提案。若返回
`managed_session_config_confirmation_required`，先向用户展示
`proposed_config`；用户确认后，以相同参数加返回的
`--config-confirm managed-session-config:<hash>` 重跑 start，成功后才能 tick。

```bash
DATING_BOOST_KEY_PROVIDER=local dating-boost standalone-session start --data-dir .local/dating-boost --authorization auth.json --app-id tashuo --runtime mac-ios-app --send-mode stage --observation-source live-gui --vision-backend minimax --backend minimax --model MiniMax-M3 --vision-model MiniMax-M3 --minimax-api-key-env MINIMAX_API_KEY --config-confirm managed-session-config:<hash> --json
DATING_BOOST_KEY_PROVIDER=local dating-boost standalone-session tick --data-dir .local/dating-boost --json
DATING_BOOST_KEY_PROVIDER=local dating-boost standalone-session status --data-dir .local/dating-boost --json
```

Fixture and cross-app development can still use the Tinder scripted path:

```bash
DATING_BOOST_KEY_PROVIDER=local dating-boost standalone-session start --data-dir .local/dating-boost --authorization tests/fixtures/standalone/auth_tinder_stage.json --app-id tinder --send-mode stage --observation-source fixture --observation-fixture-dir tests/fixtures/standalone --backend scripted --scripted-backend-output tests/fixtures/intelligence/scripted_reply.json --json
```

The fixture path uses the same two-phase confirmation contract. After the user
confirms the returned proposal:

```bash
DATING_BOOST_KEY_PROVIDER=local dating-boost standalone-session start --data-dir .local/dating-boost --authorization tests/fixtures/standalone/auth_tinder_stage.json --app-id tinder --send-mode stage --observation-source fixture --observation-fixture-dir tests/fixtures/standalone --backend scripted --scripted-backend-output tests/fixtures/intelligence/scripted_reply.json --config-confirm managed-session-config:<hash> --json
DATING_BOOST_KEY_PROVIDER=local dating-boost standalone-session tick --data-dir .local/dating-boost --json
DATING_BOOST_KEY_PROVIDER=local dating-boost standalone-session stop --data-dir .local/dating-boost --json
```

The current standalone GUI executor is stage-only and returns
`standalone_live_gui_send_not_enabled` for live send. Ordinary-chat live send
must remain host-native through ManagedRun or the managed-session/host-loop
compatibility path. Both require user authorization, runtime scope, target
binding, exact staged-text verification, and post-action evidence. Only the
compatibility executor consumes an operator-generated action request;
ManagedRun uses its durable decision and send-attempt checkpoint instead.

## Host loop

Before `run`, require
`dating-boost user readiness --data-dir .local/dating-boost --mode autonomous --json`
to pass. If it returns `needs_user_profile`, do not start host-loop.

```bash
dating-boost-host-loop doctor --data-dir .local/dating-boost --app-id tinder --json
dating-boost-host-loop init --data-dir .local/dating-boost --work-dir .local/dating-boost-host-loop --app-id tinder --json
dating-boost-host-loop run --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tinder --send-mode stage --work-dir .local/dating-boost-host-loop --json
```

Live managed GUI send 只能在用户明确授权时启用：

```bash
dating-boost-host-loop run --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tinder --send-mode live --managed-gui-send --work-dir .local/dating-boost-host-loop --json
```

发送结果必须来自新的 post-action observation。无法验证时记录 `unknown`，不能记录 `succeeded`。

## 用户自我模型

托管或自主 workflow 需要用户自我模型：

```bash
dating-boost user interview template --json
dating-boost user ingest-profile --data-dir .local/dating-boost --input user_dating_profile.json
dating-boost user ingest-interview --data-dir .local/dating-boost --input self_interview.json
dating-boost user readiness --data-dir .local/dating-boost --mode autonomous --json
```

如果 readiness 返回 `needs_user_profile`，不要启动 `operator session`、`automation session` 或 host-loop run。

## 本地数据和诊断

```bash
dating-boost data migrate --data-dir .local/dating-boost --json
dating-boost data backup --data-dir .local/dating-boost --output dating-boost-backup.zip --recovery-passphrase-file /secure/path/recovery-passphrase.txt --json
dating-boost data export --data-dir .local/dating-boost --output dating-boost-export.zip --json
dating-boost diagnostics bundle --data-dir .local/dating-boost --output diagnostics.zip --json
dating-boost support bundle --data-dir .local/dating-boost --session-id <session_id> --output dating-boost-support.zip --redaction strict --json
```

Backup requires a recovery passphrase from an environment variable or file;
prefer a user-readable-only file and never place the passphrase value directly
in argv.

不要在 support session start 和 support bundle export 之间对同一个 data dir 运行 `data migrate` 或 `data delete`。

## 参考文档

- `README.md`：人类阅读入口。
- `docs/ARCHITECTURE.md`：扩展架构。
- `app_profiles/README.md`：app profile contract。
- `agent_adapters/shared/references/contracts.md`：host-agent neutral contracts。
- `agent_adapters/shared/references/workflows.md`：host-agent reusable workflows。
- `skills/dating-booster-codex/SKILL.md`：Codex-specific operating contract。
- `skills/dating-booster-codex/references/workflows.md`：Codex workflow details。
- `skills/dating-booster-codex/references/drafting-framework.md`：中文 dating reply drafting。
- `skills/dating-booster-codex/references/naturalness-checklist.md`：中文自然度内部检查。
