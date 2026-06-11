# Agent 引导文档

本文档给 Codex、Claude Code、OpenClaw、Hermes 或其他 host agent 阅读。人类入口在 `README.md`。

Dating Booster 是本地优先的 dating workflow 工具层。Host agent 负责观察可见 app UI、理解上下文和起草回复；Dating Booster 负责本地记忆、上下文、策略检查、工作流契约、GUI staging、审计、诊断和恢复。

## 必读边界

- 不使用私有 API，不做风控绕过，不做批量运营。
- 默认只 stage 草稿，不发送。
- Live send 只允许用户明确授权的普通聊天消息。
- `harness <app> send-message --authorization --action-request` 是 executor-internal 路径，只能消费系统生成的 work item 或确认流结果；do not handcraft action requests。
- 不得执行 like、super-like、pass、unmatch、report、profile edit、premium purchase、call、payment、自动邀约或自动交换联系方式。
- 观察 dating app 或微信可见内容前，必须完成 startup check 和 support session。

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

## Startup check

每次开始处理可见 app 内容前运行：

```bash
python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost
```

检查：

- CLI 版本和 skill/adapter 要求兼容。
- `supported_app_profiles` 包含目标 app。
- `schema_versions` 覆盖当前 workflow 需要的 contract。
- `managed_live_send_guidance.direct_harness_scope` 仍为 executor-internal only。

目标 app 确定后，开启 support session：

```bash
dating-boost support session start --data-dir .local/dating-boost --host codex --app-id tinder --json
```

把返回的 `session_id` 用于后续 support bundle。严格 bundle 默认不含 raw chat、raw profile、截图、剪贴板内容或完整草稿。

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
dating-boost workflow draft --data-dir .local/dating-boost --observation observation.json --draft draft.json --mode adaptive
dating-boost policy check-draft --input draft.json --context context.json
```

内部自然度检查不要默认展示给用户。除非用户明确要求解释、debug、review，否则只展示最终草稿。

## Tinder quick path

```bash
dating-boost harness doctor --app-id tinder --json
dating-boost harness tinder launch --dry-run --json
dating-boost harness tinder observe --output-dir .local/dating-boost-harness --json
dating-boost harness tinder workflow self-profile-read --dry-run --options-json tinder-self-profile-options.json --json
dating-boost harness tinder workflow chat-read-match-profile --dry-run --options-json tinder-chat-profile-options.json --json
dating-boost harness tinder workflow new-match-open --dry-run --options-json tinder-new-match-options.json --json
dating-boost harness tinder workflow new-match-read-profile --dry-run --options-json tinder-new-match-profile-options.json --json
dating-boost harness tinder action open-conversation --options-json tinder-open-conversation-options.json --json
dating-boost harness tinder action dismiss-subscription-paywall --json
dating-boost harness tinder action dismiss-feedback-survey --json
```

`chat-read-match-profile` 只用于已有消息行。`new-match-open` 打开未开聊匹配并停在会话页。`new-match-read-profile` 读取未开聊匹配资料后回到当前会话。

如果出现订阅、Gold、Likes You、plan-selection paywall，只能关闭并重新导航；subscription purchase 或 plan selection 不是 agent action。反馈问卷用 ignore/no-rating 路径关闭，`rating_submitted` 必须是 false。

## Bumble quick path

```bash
dating-boost harness doctor --app-id bumble --json
dating-boost harness bumble launch --dry-run --json
dating-boost harness bumble observe --output-dir .local/dating-boost-harness --json
dating-boost harness bumble action open-chats --dry-run --json
dating-boost harness bumble workflow browse-profile-read --dry-run --options-json bumble-profile-options.json --json
dating-boost harness bumble workflow chat-read-match-profile --dry-run --options-json bumble-chat-profile-options.json --json
dating-boost harness bumble workflow opening-move-open --dry-run --options-json bumble-opening-move-options.json --json
```

Opening Move 是 role-sensitive：女性用户场景下 agent 不决定是否启用/跳过，也不判断男性回复是否足够好；男性用户场景下可以为用户 review 起草 Opening Move 回复。

## TaShuo quick path

```bash
dating-boost harness doctor --app-id tashuo --json
dating-boost harness tashuo launch --dry-run --json
dating-boost harness tashuo observe --output-dir .local/dating-boost-harness --json
dating-boost harness tashuo action open-chats --dry-run --json
dating-boost harness tashuo workflow chat-read-match-profile --dry-run --options-json tashuo-chat-profile-options.json --json
dating-boost harness tashuo workflow question-gate-open --dry-run --options-json tashuo-question-gate-options.json --json
```

Apple Silicon Mac 上如果用户已经安装并登录 Mac App Store 的她说 iOS app，可优先试验本地 `mac-ios-app` runtime。该 runtime 不占用真实手机，当前支持 launch/observe/prepare-message-page/stage-draft。`send-message --runtime mac-ios-app` 仅保留为 executor-internal 实验入口；由于中文 staging/exact verification 未稳定，mac-ios-app 托管 live send 当前由 capabilities 标记为 `experimental_blocked_cjk_stage_verification`，host-loop 会早期 block。question-gate staging/sending 仍不支持。

```bash
dating-boost harness doctor --app-id tashuo --runtime mac-ios-app --json
dating-boost harness tashuo action prepare-message-page --runtime mac-ios-app --output-dir .local/dating-boost-harness --json
dating-boost harness tashuo stage-draft --runtime mac-ios-app --text-file tashuo-draft.txt --dry-run --json
```

`prepare-message-page` 会打开 TaShuo Mac iOS app，用底部 tab 的视觉高亮判断当前一级页；如果不在 `消息` 页，只点击底部 `消息` tab。进入消息页后停止固定坐标流程，返回 `next_host_action=visual_plan_message_list`，后续由 host agent 进行视觉分析和规划，不要先跑 OCR 再回退视觉，也不要用固定 row 坐标直接进入聊天线程。

TaShuo mac-ios-app 托管 live send 当前不启用。下面命令应早期 block，原因是 `runtime_live_send_not_supported:tashuo:mac-ios-app`；需要 live send 时使用已声明支持的 runtime，或降级为 stage-only：

```bash
dating-boost-host-loop run --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tashuo --send-mode live --managed-gui-send --harness-runtime mac-ios-app --work-dir .local/dating-boost-host-loop --json
```

TaShuo 启动搜索使用 `tashu` 并通过截图/OCR 确认 `她说` 或 `TaShuo`。`飞行` screen-tap chat starts、recommendation likes、passes、question-gate decisions 都是 blocked actions。

## WeChat quick path

```bash
dating-boost harness doctor --app-id wechat --window-title WeChat --json
dating-boost harness wechat launch --dry-run --json
dating-boost harness wechat observe --output-dir .local/dating-boost-harness --json
dating-boost harness wechat stage-draft --text-file wechat-draft.txt --dry-run --json
```

微信 stage 使用剪贴板把已通过 policy check 的草稿放入当前输入框；stage mode 不按 Enter、不点击 Send。真实 staging 必须传 `--data-dir`，让全局 safety pause 能阻断 paste。

## Managed session

`managed-session` 只在用户显式启动后的当前托管窗口内运行。Session 外不监听、不扫描、不自动回复。

```bash
dating-boost managed-session start --app-id tinder --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --send-mode stage --scan-interval 120 --nudge-delay-minutes 30 --json
dating-boost managed-session run --wait --data-dir .local/dating-boost --json
dating-boost managed-session notify --data-dir .local/dating-boost --source manual --app-id tinder --json
dating-boost managed-session status --data-dir .local/dating-boost --json
dating-boost managed-session stop --data-dir .local/dating-boost --json
```

当 `managed-session run --wait` 返回 `host_work_required`，host agent 处理其中的 operator work item。如果用 host-loop supervisor 处理，使用同一个 data/work dir 运行：

```bash
dating-boost-host-loop resume --data-dir .local/dating-boost --work-dir .local/dating-boost-host-loop --json
dating-boost managed-session run --wait --data-dir .local/dating-boost --json
```

不要启动新的 `dating-boost-host-loop run` 来处理同一个 wait point，因为新 run 会创建新的 operator session。

## Host loop

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
dating-boost data backup --data-dir .local/dating-boost --output dating-boost-backup.zip --json
dating-boost data export --data-dir .local/dating-boost --output dating-boost-export.zip --json
dating-boost diagnostics bundle --data-dir .local/dating-boost --output diagnostics.zip --json
dating-boost support bundle --data-dir .local/dating-boost --session-id <session_id> --output dating-boost-support.zip --redaction strict --json
```

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
