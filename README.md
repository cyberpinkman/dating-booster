# dating-booster

## 结论 / Summary

Dating Booster 是一个本地优先的 dating workflow 工具层。它为 Codex
这类 host agent 提供本地记忆、上下文、策略检查、草稿生成、GUI stage harness、
审计、诊断和恢复能力。它不是私有 API 客户端，也不负责绕过 App 风控。

Dating Booster is a local-first tool layer for dating workflows. It
gives host agents such as Codex local memory, context, policy checks, draft
workflows, GUI stage harnesses, audit logs, diagnostics, and recovery. It is
not a private API client and does not provide app risk-control bypasses.

## 开源许可 / License

本项目使用 MIT License 开源，见 `LICENSE`。

This project is open-sourced under the MIT License. See `LICENSE`.

## 安全边界 / Safety Boundary

这是一个不使用私有 API、不做绕过、由用户本地授权运行的 GUI automation
experiment；它仍可能违反目标 App 的条款，并可能导致账号封禁。项目不提供规避
检测、批量运营、账号池、刷赞、自动邀约或规模化滥用能力。

This is a GUI automation experiment that uses local user
authorization, not private APIs or bypasses. It may still violate target app
terms and may cause account restrictions. The project does not provide
anti-detection, bulk operation, account farming, like automation, auto-invite,
or scale-out abuse features.

| 类别 / Category | 默认行为 / Default |
| --- | --- |
| 允许 / Allowed | observe, summarize, draft replies, paste or stage drafts |
| 阻止 / Blocked | send messages, like, super-like, unmatch, report, edit profile, propose meetings, payments, calls |
| 高风险动作 / High-risk actions | require explicit human confirmation unless one experimental action is deliberately authorized |
| 自主模式 / Autonomous mode | off by default, experimental, local switch only |
| 生产默认 / Production defaults | macOS-only, encrypted local storage, stage-first GUI operation, local-only diagnostics |

`--send-mode stage` 是默认路径：只准备、粘贴或 staging 草稿，不点击发送。
`--send-mode live` 只用于明确授权的普通聊天消息。GUI harness 全托管发送还必须显式传
`--managed-gui-send`，并且仍需要 `live_send: true`、安全开关未暂停、
planner-backed 且 policy-checked 的 action request、目标聊天绑定、草稿文本精确校验和发送后验证。

`--send-mode stage` is the default path: it prepares, pastes, or stages drafts
without clicking send. `--send-mode live` is only for explicitly authorized
ordinary chat messages. Managed GUI harness sending must also pass
`--managed-gui-send` and still requires `live_send: true`, an unpaused safety
switch, a planner-backed and policy-checked action request, target-chat
binding, staged-text verification, and post-action verification.

## 当前 App 支持 / Current App Support

| App | 支持状态 / Support | Native harness | 发送归属 / Send ownership |
| --- | --- | --- | --- |
| Tinder | host loop, profile/chat navigation, observation, draft workflow, opt-in managed live send | iPhone Mirroring on macOS | stage by default; `send-message` can click Send only after explicit live-send authorization and verification |
| WeChat / 微信 | app profile, host-loop app id, desktop observation, draft staging, opt-in managed live send | macOS WeChat desktop window | stage by default; `send-message` can press Enter only after explicit live-send authorization and verification |
| Bumble | host loop, iPhone Mirroring launch/observation, profile/chat navigation, Opening Move observation, opt-in managed live send | iPhone Mirroring on macOS | stage by default; ordinary chat `send-message` can click Send only after explicit live-send authorization and verification |
| 她说 / TaShuo | host loop, iPhone Mirroring launch/observation, profile/chat navigation, question-gate observation, opt-in managed live send | iPhone Mirroring on macOS | stage by default; ordinary chat `send-message` can click Send only after explicit live-send authorization, target-specific binding, exact OCR verification, and post-send evidence |

未支持 app 不进入 `app_profiles/` 或 `supported_app_profiles`。Hinge
以及其他主流 dating app 先作为 roadmap candidate 记录在
`docs/ARCHITECTURE.md`；只有具备 fixture、preflight、harness 或 host-loop 测试后，
才新增 runtime app profile。

Unsupported apps do not appear in `app_profiles/` or `supported_app_profiles`.
Hinge and other mainstream dating apps are roadmap candidates until fixtures,
preflight, harness, or host-loop tests justify a runtime app profile.

未来扩展蓝图见 `docs/ARCHITECTURE.md`。它把扩展拆成四条独立轴：更多 host
agent（Codex、Claude Code、Hermes、OpenClaw）、更多 dating app、更多目标类型，
以及更智能的 workflow/memory evolution。

See `docs/ARCHITECTURE.md` for the expansion architecture. It separates future
work into four independent axes: more host agents, more dating apps, more goal
types, and smarter workflow/memory evolution.

## 安装和启动检查 / Install And Startup Checks

Current `main` source-checkout version is `1.0.0-rc.2.dev0`. For current app
support such as Bumble/TaShuo, run the module CLI from the checkout and verify
capabilities:

```bash
git pull --ff-only
python3 -m pip install --user -e .
python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost
python3 -m dating_boost.cli adapter claude-code install --scope project --target . --json
```

任何 host agent 在观察 dating app 可见内容前，必须先跑 capabilities 并
检查版本、schema、命令和存储能力是否兼容。

Before any host agent observes visible dating app content, run
capabilities and verify version, schema, command, and storage compatibility.

Codex-first skill package:

- Skill path: `skills/dating-booster-codex/`
- Install doc: `skills/dating-booster-codex/INSTALL.md`
- Agent references: `skills/dating-booster-codex/references/`

Claude Code adapter:

```bash
dating-boost adapter claude-code install --scope project --target . --json
dating-boost adapter claude-code doctor --data-dir .local/dating-boost --json
```

项目级安装会写入 `.claude/skills/dating-booster/`，适合把 Dating Booster 能力随
当前仓库交给 Claude Code 使用。用户级安装使用：

```bash
dating-boost adapter claude-code install --scope user --json
```

这会写入 `~/.claude/skills/dating-booster/`。Claude Code skill 只描述
Claude Code 如何调用 Dating Booster；memory、policy、planner、harness、app profile
和 audit 仍由同一套 CLI/core contract 承担。

Project installs write `.claude/skills/dating-booster/`, which lets Claude Code
discover the Dating Booster skill for the current repository. User installs
write `~/.claude/skills/dating-booster/`. The Claude Code skill only explains
how Claude Code should call Dating Booster; memory, policy, planner, harness,
app profiles, and audit still come from the same CLI/core contracts.

After `git pull`, reinstall the editable package and the copied Claude Code
skill before asking Claude Code to use new app support:

```bash
python3 -m pip install --user -e .
python3 -m dating_boost.cli adapter claude-code install --scope project --target . --json
python3 -m dating_boost.cli adapter claude-code doctor --data-dir .local/dating-boost --json
python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost
```

Pulling source code alone does not update `.claude/skills/dating-booster/`.
If the `dating-boost capabilities` console-script output disagrees with the
`python3 -m dating_boost.cli capabilities` module output, the console script is
stale; use the module CLI from the checkout until the editable install and PATH
are fixed.

OpenClaw adapter:

```bash
dating-boost adapter openclaw install --scope project --target . --json
dating-boost adapter openclaw doctor --data-dir .local/dating-boost --json
```

项目级安装会写入 `.openclaw/skills/dating-booster/`。Hermes 通过同一个
OpenClaw-compatible skill contract 使用 Dating Booster，不声明独立 Hermes-native
adapter：

```bash
dating-boost adapter hermes install --scope project --target . --json
dating-boost adapter hermes doctor --data-dir .local/dating-boost --json
```

The OpenClaw adapter writes `.openclaw/skills/dating-booster/`. Hermes uses the
same OpenClaw-compatible skill contract through the `adapter hermes` commands;
it is not a separate Hermes-native adapter package.

For test users, send the repository URL to their host agent and let the agent
clone, inspect, and install from source:

```bash
git clone https://github.com/cyberpinkman/dating-booster.git
cd dating-booster
python3 -m pip install --user -e .
python3 -m dating_boost.cli adapter claude-code install --scope user --json
python3 -m dating_boost.cli adapter claude-code doctor --data-dir ~/.dating-boost --json
```

When that source checkout is updated later, the agent must rerun the editable
install and `adapter claude-code install`; otherwise Claude Code may keep using
an older copied skill.

Codex users should replace the last two commands with:

```bash
python3 -m dating_boost.cli adapter codex install --scope user --json
python3 -m dating_boost.cli adapter codex doctor --data-dir ~/.dating-boost --json
```

OpenClaw or Hermes-compatible users should replace the last two commands with:

```bash
python3 -m dating_boost.cli adapter openclaw install --scope user --json
python3 -m dating_boost.cli adapter openclaw doctor --data-dir ~/.dating-boost --json
python3 -m dating_boost.cli adapter hermes doctor --data-dir ~/.dating-boost --json
```

测试用户入口是仓库链接。让 agent 自己 clone、阅读 README/skill、安装 CLI，并用
对应 host 的 `adapter <host> install|doctor` 完成安装。后续新增其他 host 时，
新增对应 adapter，不修改 Claude Code、Codex 或 OpenClaw 的既有安装语义。

## 本地数据和守护进程 / Local Data And Supervisor

macOS 生产默认加密 SQLite payload。生产 key provider 首选 macOS
Keychain；CI 和本地测试可设置 `DATING_BOOST_KEY_PROVIDER=local`。备份恢复口令
从 `DATING_BOOST_RECOVERY_PASSPHRASE` 或 `--recovery-passphrase-file` 读取。

On macOS, production defaults encrypt SQLite payloads. The preferred
production key provider is macOS Keychain; CI and local tests may set
`DATING_BOOST_KEY_PROVIDER=local`. Backup recovery passphrases come from
`DATING_BOOST_RECOVERY_PASSPHRASE` or `--recovery-passphrase-file`.

```bash
dating-boost data migrate --data-dir .local/dating-boost --json
dating-boost data backup --data-dir .local/dating-boost --output dating-boost-backup.zip --json
dating-boost data rekey --data-dir .local/dating-boost --json
dating-boost diagnostics bundle --data-dir .local/dating-boost --output diagnostics.zip --json
dating-boost support session start --data-dir .local/dating-boost --host codex --app-id tinder --json
dating-boost support bundle --data-dir .local/dating-boost --session-id <session_id> --output dating-boost-support.zip --redaction strict --json
```

Support sessions record redacted command boundaries, topic provenance, payload
hashes, character counts, and clipboard fingerprints. Strict support bundles do
not include raw drafts, raw conversations, raw profile text, screenshots, or
clipboard contents. Sensitive evidence stays encrypted locally unless the user
explicitly requests `--redaction full-with-consent` with the required confirm
token.

The daemon is a local supervisor only. It owns locks, heartbeat, recovery, and
kill-switch state. It does not observe screens or click apps.

```bash
dating-boost daemon install --data-dir .local/dating-boost --json
dating-boost daemon status --data-dir .local/dating-boost --json
dating-boost safety pause --data-dir .local/dating-boost --reason manual-stop --json
```

## Agent-native 工作流 / Agent-native Workflow

Dating Booster 不需要拥有 LLM 调用。Codex 或其他 host agent 负责可见屏幕
理解和草稿生成；Dating Booster 负责本地状态、上下文、策略、工作流契约和
host-executed action audit。

Dating Booster does not need to own the LLM call. Codex or another
host agent owns visible-screen understanding and draft generation. Dating
Booster owns local state, context, policy, workflow contracts, and
host-executed action audit.

Startup command:

```bash
python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost
```

Host agents may process visible dating app content, screenshots, profile text,
conversation text, and generated drafts. Users should only run this mode if
they accept that privacy boundary.

## Native GUI Harness 快速路径 / Native GUI Harness Quick Paths

### Tinder via iPhone Mirroring

```bash
dating-boost harness doctor --app-id tinder --json
dating-boost harness tinder launch --dry-run --json
dating-boost harness tinder open-profile --dry-run --json
dating-boost harness tinder open-profile --launch-if-needed --json
dating-boost harness tinder observe --output-dir .local/dating-boost-harness --json
dating-boost harness tinder workflow self-profile-read --dry-run --photo-steps 2 --scroll-steps 2 --json
dating-boost harness tinder workflow chat-read-match-profile --dry-run --conversation-row 1 --profile-scroll-steps 2 --json
dating-boost harness tinder workflow new-match-open --dry-run --carousel-swipes 1 --match-index 2 --json
dating-boost harness tinder workflow new-match-read-profile --dry-run --carousel-swipes 1 --match-index 2 --profile-scroll-steps 2 --json
dating-boost harness tinder action open-conversation --visible-name Iris --target-binding target-binding.json --json
dating-boost harness tinder action dismiss-subscription-paywall --json
dating-boost harness tinder action dismiss-feedback-survey --json
dating-boost harness tinder send-message --text-file tinder-draft.txt --dry-run --json
```

Tinder harness 可诊断 iPhone Mirroring、截图/OCR，并在当前不确定处于 Tinder
内时强制回到 iPhone Mirroring Home Screen，再通过 Spotlight 搜索打开 Tinder。
它支持只读导航：self profile、profile preview、照片切换、full profile、
profile wheel scroll/expand、chat tab、new-match carousel wheel、已有会话打开、
未开聊匹配打开、thread-avatar profile opening 和退出 preview/full profile。
`chat-read-match-profile` 只用于已有消息行；`new-match-open` 用于打开一个未开聊匹配并停在会话页，方便后续破冰发送；`new-match-read-profile` 用于读取未开聊匹配资料后回到当前会话。
默认路径不会点击 Send。全托管发送只能走 `harness tinder send-message`，
并且必须满足显式授权、`live_send: true`、安全开关未暂停、
planner-backed 且 policy-checked action request、目标聊天绑定校验、staged text OCR 校验和
发送后 outbound bubble 校验。它不会授权 like、super-like、unmatch、report 或
profile edit。

The Tinder harness can diagnose iPhone Mirroring, screenshot/OCR the
mirrored window, and force iPhone Mirroring back to Home Screen before opening
Tinder through Spotlight whenever Tinder is not already verified foreground.
It can perform read-only navigation through self profile, profile preview,
photos, full profile, profile wheel scroll/expand, chat tab, new-match carousel
wheel, existing conversation opening, unopened match opening, thread-avatar
profile opening, and preview/full-profile exits. `chat-read-match-profile`
is for existing message rows only; `new-match-open` opens one unopened match and
leaves the agent in that conversation for an opener; `new-match-read-profile`
reads an unopened match profile and returns to the current conversation. It does
not click Send by default. Prefer `open-conversation --visible-name ...` or
`--target-binding target-binding.json` for existing conversations; raw row
coordinates are a compatibility fallback. If a Tinder subscription, Gold, Likes You, or
plan-selection paywall appears, the harness treats it as accidental navigation:
it dismisses the paywall and requires re-navigation to a verified conversation;
subscription purchase or plan selection is never an agent action. If Tinder
shows a feedback survey after send/navigation, `dismiss-feedback-survey` closes
it through the ignore path and reports `rating_submitted: false`. Fully managed
sending is available only through
`harness tinder send-message` with explicit authorization, `live_send: true`,
an active safety switch, a planner-backed and policy-checked action request,
target-chat binding verification, staged-text OCR verification, and
outbound-bubble post-action verification. It does not authorize like,
super-like, unmatch, report, or profile edit.

### Bumble via iPhone Mirroring

```bash
dating-boost harness doctor --app-id bumble --json
dating-boost harness bumble launch --dry-run --json
dating-boost harness bumble observe --output-dir .local/dating-boost-harness --json
dating-boost harness bumble action open-chats --dry-run --json
dating-boost harness bumble workflow browse-profile-read --dry-run --options-json bumble-profile-options.json --json
dating-boost harness bumble workflow chat-read-match-profile --dry-run --options-json bumble-chat-profile-options.json --json
dating-boost harness bumble workflow opening-move-open --dry-run --options-json bumble-opening-move-options.json --json
dating-boost harness bumble send-message --text-file bumble-draft.txt --dry-run --json
```

Bumble can launch the app, classify Bumble pages, open bottom tabs, read
visible profile cards with vertical scroll, open visible chat rows, open
match-circle Opening Move prompts, open an empty Opening Move reply composer,
and run opt-in managed sends for verified ordinary chat conversations. It must
not like, pass, SuperSwipe, unmatch, report, edit profile, or purchase Premium.
Horizontal swipes on browse cards are treated as high risk because they can
like or pass.

Opening Move handling is role-sensitive. For female users, the agent must not
decide whether to enable/skip Opening Move or whether a male reply is good
enough; it can observe or summarize and then ask the user to decide. For male
users, the agent may draft an Opening Move reply for user review; Opening Move
send still requires explicit user confirmation and is not eligible for
autonomous Opening Move send. Ordinary Bumble chat managed send requires
`harness bumble send-message` with explicit authorization, `live_send: true`,
planner-backed and policy-checked action request, target-specific binding, staged-text OCR
verification, and fresh post-send outbound-bubble evidence. Visual send-button
or yellow-bubble evidence alone does not satisfy exact-text verification.

### TaShuo / 她说

```bash
dating-boost harness tashuo launch --dry-run --json
dating-boost harness tashuo observe --output-dir .local/dating-boost-harness --json
dating-boost harness tashuo action open-chats --dry-run --json
dating-boost harness tashuo workflow chat-read-match-profile --dry-run --options-json tashuo-chat-profile-options.json --json
dating-boost harness tashuo workflow question-gate-open --dry-run --options-json tashuo-question-gate-options.json --json
dating-boost harness tashuo send-message --text-file tashuo-draft.txt --dry-run --json
```

TaShuo can launch through iOS search using `tashu` and a verified `她说`/`TaShuo`
result, open the four top-level tabs (`推荐`, `飞行`, `消息`, `我的`), read ordinary
chat rows, open a thread profile, and run opt-in managed sends for verified
ordinary chat conversations. `飞行` screen-tap chat starts, recommendation likes,
passes, unmatches, reports, profile edits, premium purchases, and question-gate
decisions are blocked actions.

TaShuo question-gate handling is role-sensitive like Bumble Opening Move. For
female users, the agent must not decide whether to enable/skip the question
gate or whether a male reply is good enough; it can observe or summarize and
ask the user to decide. For male users, the agent may draft a question-gate
reply for user review, but the current harness does not stage or send
question-gate replies; the user must handle that path manually. Ordinary
TaShuo chat managed send requires `harness tashuo send-message` with explicit
authorization, `live_send: true`, planner-backed and policy-checked action request,
target-specific binding, staged-text OCR verification, and fresh post-send
outbound evidence. Visual-only evidence is not exact-text verification.

### macOS WeChat / 微信桌面端

```bash
dating-boost harness doctor --app-id wechat --window-title WeChat --json
dating-boost harness wechat launch --dry-run --json
dating-boost harness wechat observe --output-dir .local/dating-boost-harness --json
dating-boost harness wechat stage-draft --text-file wechat-draft.txt --dry-run --json
dating-boost harness wechat send-message --text-file wechat-draft.txt --dry-run --json
```

WeChat harness 可激活微信桌面窗口、截图/OCR、返回已脱敏的布局提示，
并通过剪贴板粘贴把草稿放入当前消息输入框。默认路径不会按 Enter、不会点击
Send；全托管发送只能走 `harness wechat send-message`，并且必须满足显式授权、
`live_send: true`、安全开关未暂停、planner-backed 且 policy-checked action request、目标聊天绑定校验、
输入框文本精确匹配和发送后 outbound bubble 校验。它不会发起通话、不会处理支付、
不会交换联系方式。优先使用 `--text-file`，避免私密草稿进入 shell history 或进程参数。
真实 staging/send 必须传 `--data-dir`，以便全局安全暂停能阻断 paste/send。

The WeChat harness can activate the desktop WeChat window,
screenshot/OCR it, return redacted layout hints, and paste a prepared draft into
the current message input with the clipboard. The default path never presses
Enter or clicks Send. Fully managed sending is available only through
`harness wechat send-message` with explicit authorization, `live_send: true`,
an active safety switch, a planner-backed and policy-checked action request,
target-chat binding verification, exact input-text verification, and
outbound-bubble post-action verification. It does not start calls, handle
payments, or exchange contacts.
Prefer `--text-file` so private drafts do not enter shell history or process
args. Real staging/send must pass `--data-dir` so the global safety pause can
block paste/send.

## Host Loop 快速路径 / Host Loop Quick Path

```bash
dating-boost-host-loop doctor --data-dir .local/dating-boost --app-id tinder --json
dating-boost-host-loop init --data-dir .local/dating-boost --work-dir .local/dating-boost-host-loop --app-id tinder --json
dating-boost-host-loop run --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --app-id tinder --send-mode stage --work-dir .local/dating-boost-host-loop --json
dating-boost-host-loop run --data-dir .local/dating-boost --authorization bumble-auth.json --goal goal.json --availability availability.json --app-id bumble --send-mode live --managed-gui-send --work-dir .local/dating-boost-host-loop --json
dating-boost-host-loop run --data-dir .local/dating-boost --authorization wechat-auth.json --goal goal.json --availability availability.json --app-id wechat --send-mode live --managed-gui-send --work-dir .local/dating-boost-host-loop --json
```

使用 `dating-boost-host-loop status` 检查等待点，使用
`dating-boost-host-loop resume` 从中断恢复，使用
`dating-boost replay latest --data-dir .local/dating-boost --format md` 查看
run replay。高风险结果必须来自新的 post-action observation；无法验证时记录
`unknown`，不能记录 `succeeded`。

Use `dating-boost-host-loop status` to inspect the current wait point,
`dating-boost-host-loop resume` after interruption, and
`dating-boost replay latest --data-dir .local/dating-boost --format md` for a
run replay. High-risk results require a fresh post-action observation. If a
result cannot be verified, record `unknown`, not `succeeded`.

Host-executed action results are appended to:

```text
.local/dating-boost/audit/action_results.jsonl
```

## Session-scoped Managed Runner / 会话期托管 Runner

`managed-session` 只在用户显式启动后的当前托管窗口内运行。Tinder session
绑定 iPhone Mirroring：镜像窗口不可用时立即停止。WeChat session 从用户启动
持续到用户 `stop`；窗口不可读时暂停，不发送。session 外不监听、不扫描、不自动回复。

`managed-session` runs only inside the user-authorized session window. Tinder
sessions are bound to iPhone Mirroring and stop when the mirroring window is no
longer available. WeChat sessions run until user `stop`; if the window is not
readable, they pause and do not send. Outside a session, nothing is monitored,
scanned, or auto-replied.

```bash
dating-boost managed-session start --app-id tinder --data-dir .local/dating-boost --authorization auth.json --goal goal.json --availability availability.json --send-mode stage --scan-interval 120 --nudge-delay-minutes 30 --json
dating-boost managed-session run --data-dir .local/dating-boost --wait --json
dating-boost managed-session notify --data-dir .local/dating-boost --source manual --app-id tinder --json
dating-boost managed-session status --data-dir .local/dating-boost --json
dating-boost managed-session stop --data-dir .local/dating-boost --json
```

The local runner performs tokenless checks for app availability, safety pause,
authorization, quiet hours, unread cues, scan interval, and due nudges. It
returns `no_work` while idle. When it returns `host_work_required`, the host
agent should process the included `operator` work item. When using the host-loop
supervisor for that work, run `dating-boost-host-loop resume` with the same
data/work dirs; do not start a fresh `dating-boost-host-loop run`, because a
fresh run starts a new operator session. After resume or equivalent manual
operator processing, return to `managed-session run --wait`. Live sends still require
`--send-mode live --managed-gui-send` plus the existing managed send gates.

## 用户自我模型和自主准备 / User Model And Autonomous Readiness

完全托管或自主 runs 需要用户自我模型。自主 readiness 需要 dating profile 和
self interview 两类输入，至少五条 low-risk shareable materials，至少两条
low-investment repair materials，以及至少一条 date/meeting preference material。

Fully managed or autonomous runs require the user self model.
Autonomous readiness requires both dating profile and self interview inputs, at
least five low-risk shareable materials, at least two low-investment repair
materials, and at least one date/meeting preference material.

```bash
python3 -m dating_boost.cli user interview template --json
python3 -m dating_boost.cli user ingest-profile --data-dir .local/dating-boost --input user_dating_profile.json
python3 -m dating_boost.cli user ingest-interview --data-dir .local/dating-boost --input self_interview.json
python3 -m dating_boost.cli user readiness --data-dir .local/dating-boost --mode autonomous --json
```

Preferred Codex-first draft workflow:

```bash
python3 -m dating_boost.cli workflow draft --data-dir .local/dating-boost --observation observation.json --draft draft.json --mode adaptive
python3 -m dating_boost.cli memory ingest-observation --data-dir .local/dating-boost --input observation.json
python3 -m dating_boost.cli memory get-match --data-dir .local/dating-boost --match-id match_alex
python3 -m dating_boost.cli context build --data-dir .local/dating-boost --match-id match_alex --mode adaptive
python3 -m dating_boost.cli policy check-draft --input draft.json --context context.json
python3 -m dating_boost.cli policy check-action send_message --autonomous
python3 -m dating_boost.cli action record-result --data-dir .local/dating-boost --input action_result.json
python3 -m dating_boost.cli feedback record --data-dir .local/dating-boost --match-id match_alex --draft-id draft_1 --mode adaptive --label accepted
```

## Fixture MVP / Local Intelligence Workflow

下面路径使用 fixture 和手工 observation，可在不执行 GUI action、不发送消息的
情况下跑完整本地智能流程。

The path below uses fixtures and manual observations. It runs the
local intelligence workflow without executing GUI actions or sending messages.

```bash
python3 -m dating_boost.cli init-profile --data-dir .local/dating-boost --input tests/fixtures/intelligence/user_profile.json
MATCH_ID=$(python3 -m dating_boost.cli import-observation --data-dir .local/dating-boost --input tests/fixtures/intelligence/app_observation_chat.json | python3 -c 'import json, sys; print(json.load(sys.stdin)["match_id"])')
python3 -m dating_boost.cli draft --data-dir .local/dating-boost --match-id "$MATCH_ID" --mode adaptive --backend scripted --scripted-backend-output tests/fixtures/intelligence/scripted_reply.json
python3 -m dating_boost.cli feedback --data-dir .local/dating-boost --match-id "$MATCH_ID" --draft-id draft_1 --mode adaptive --label accepted
python3 -m unittest discover -s tests
```

Production LLM backend:

```bash
python3 -m dating_boost.cli draft --data-dir .local/dating-boost --match-id "$MATCH_ID" --mode adaptive --backend openai --model gpt-4.1-mini
```

The OpenAI backend requires the optional OpenAI SDK:

```bash
pip install 'dating-booster[openai]'
```

Screenshots can be imported without GUI actions:

```bash
python3 -m dating_boost.cli observe-screenshot --data-dir .local/dating-boost --screenshot path/to/screenshot.png --analysis path/to/analysis.json
```

Draft output is privacy-minimized by default. Add `--debug-context` only when
you explicitly want to inspect the context pack in terminal output.

## 项目结构 / Project Structure

| Path | 作用 / Purpose |
| --- | --- |
| `dating_boost/cli.py` | CLI routing for memory, policy, operator, data, diagnostics, release, daemon/safety, confirmation, and harness commands |
| `dating_boost/core/gui_harness.py` | native GUI harness adapters: Tinder uses iPhone Mirroring, WeChat uses macOS desktop |
| `dating_boost/host_loop.py` | supervised host-loop runner for staged/live work items |
| `dating_boost/core/capabilities.py` | machine-readable startup contract for agents and skill installers |
| `dating_boost/core/goals.py` | goal type registry; `meet_in_person` is the first registered goal |
| `dating_boost/harness/` | shared native harness building blocks: window parsing, screen state, input backends |
| `app_profiles/` | app-specific contracts; see `app_profiles/README.md` |
| `agent_adapters/` | shared and host-specific adapter packages/docs for Codex, Claude Code, and future hosts |
| `schemas/app_profile.schema.json` | formal app profile schema used by profile contract tests |
| `docs/ARCHITECTURE.md` | expansion architecture for host agents, dating apps, goals, workflows, and memory |
| `skills/dating-booster-codex/` | installable Codex skill plus operational references and smoke/runbook docs |
| `agent_adapters/claude-code/` | installable Claude Code adapter package and skill content |
| `agent_adapters/openclaw/` | installable OpenClaw-compatible adapter package; Hermes uses this skill contract |
| `docs/README.md` | repository map, current app support matrix, and expansion path |
| `tests/fixtures/` | deterministic fixtures for local and host-loop tests |
| `tests/test_gui_harness.py` | GUI harness contracts for Tinder and macOS WeChat |

## 新 App 扩展路径 / App Expansion Path

1. 新增或更新 `app_profiles/<app_id>.json`。
2. 先证明它是 runtime-supported app：至少有 fixture、preflight 和可测试的
   observation/navigation/staging/live-send 边界。
3. 在 `dating_boost/apps/<app_id>/adapter.py` 和 adapter-owned session 代码实现
   app 语义、workflow、target binding、send verification 和特殊社交规则。
4. 在 `dating_boost/apps/registry.py` 注册 adapter；CLI、capabilities、
   managed session 和 host loop 必须从 registry/profile 派生。
5. app-specific 参数通过 `harness <app_id> action|workflow --options-json` 传入，
   不为新增 app 修改全局 argparse 分支。
6. 在 `tests/fixtures/` 和 `tests/` 增加 deterministic fixtures 与 focused tests。
7. 更新 `README.md`、`app_profiles/README.md`、`docs/README.md` 和 Codex skill
   references。
8. 发布前运行 targeted unit tests 和 `dating-boost capabilities --json`。

1. Add or update `app_profiles/<app_id>.json`.
2. Prove it is a runtime-supported app with fixtures, preflight, and testable
   observation/navigation/staging/live-send boundaries.
3. Implement app semantics, workflows, target binding, send verification, and
   special social rules in `dating_boost/apps/<app_id>/adapter.py` and
   adapter-owned session code.
4. Register the adapter in `dating_boost/apps/registry.py`; CLI, capabilities,
   managed sessions, and host loop must derive support from registry/profile.
5. Pass app-specific parameters through
   `harness <app_id> action|workflow --options-json`; do not add global argparse
   branches for new apps.
6. Add deterministic fixtures and focused tests under `tests/fixtures/` and
   `tests/`.
7. Update `README.md`, `app_profiles/README.md`, `docs/README.md`, and Codex
   skill references.
8. Before publishing, run targeted unit tests and `dating-boost capabilities --json`.

## 验证 / Verification

```bash
python3 -m unittest tests.test_gui_harness tests.test_skill_package
python3 -m unittest tests.test_claude_code_adapter
python3 -m pytest tests/test_openclaw_adapter.py
python3 -m unittest tests.test_operator_host_loop.OperatorHostLoopTests.test_wechat_host_loop_init_writes_wechat_authorization_template
python3 -m py_compile dating_boost/core/gui_harness.py dating_boost/cli.py dating_boost/core/capabilities.py dating_boost/host_loop.py
```

旧的最小 action gate 仍可用于策略检查演示；它不执行 GUI action：

```bash
python3 -m dating_boost.cli observe
python3 -m dating_boost.cli send_message
python3 -m dating_boost.cli send_message --autonomous
```

The minimal action gate remains available for policy-check demos. It does not
execute GUI actions.
