# Dating Booster 产品优先优化规划：全托管修订版

状态：实施中（首个代码纵切面完成；真实 GUI Canary 与产品 Gate 待执行）
时间窗口：6–8 周
修订原则：全托管是产品本体；回复质量、速度和安全是使全托管成立的子系统

## 0. 当前实施进度（2026-08-27）

本轮已经完成的代码里程碑：

- 单一 durable `ManagedRun` 核心循环和 typed observation/decision/action ports；
- 多对象扫描、确定性优先级、等待、handoff、谨慎 nudge 和连续前台调度；
- 原子 `SendTransaction`、click 前 checkpoint、crash reconciliation、
  `unknown_after_click` 全局暂停和重复发送抑制；
- `manage start/status/pause/resume/stop` 用户生命周期，以及 host-runner
  `run/tick`；
- fixture 的完整 start→scan→open→draft→stage→click→verify→continue→stop 纵切面；
- TaShuo `mac-ios-app` 的 composer observe、exact stage、Return-only click、
  fresh post-send observe 四段真实 GUI action seam；
- 正常 fresh-send 热路径把 composer-empty、exact stage 和 post-stage freshness 合并成
  一次原子 stage observation，并用组合 AX snapshot 同时读取 conversation revision 与
  composer；按静态调用图，thread observation 后到 Return 前的 AX 遍历由约 10 次降为
  5 次（真实 GUI 延迟仍待 Canary 测量）；
- 单次生成、确定性 review、只有必要时一次重写的模型调用路径；
- 仅普通消息可自主发送，其余动作永久 handoff 的动作策略；
- Critical Managed / PR Core / cross-platform contracts / nightly qualification/coverage
  测试分层；
- 日常 ManagedRun 从重复 deep doctor/support session 热路径中移出；完整检查只在
  安装更新、迁移、权限变化或诊断时执行；
- 自主用户画像 readiness、时长、quiet hours、发送预算和结束进度报告。

本机当前反馈基线（2026-08-27，Python 3.11）：Critical Managed 65 项约 0.35 秒；
PR Core 1186 项约 83.42 秒；qualification/crash 193 项转入 nightly/manual；
nightly canonical coverage 约 133.82 秒。真实 CI 会受 runner 和安装缓存影响。

尚未完成、且不能由单元测试替代的产品里程碑：

- 当前 `start` 后仍由 host 立即拉起一个前台 `run --wait` 进程；两者共享同一
  durable run，但尚未由 `start` 自己托管后台 runner；
- 未执行真实 GUI shadow、单对象 live Canary、多对象 Canary 和 nudge beta；
- 未取得 30/75/200 次真实 verified send 或内测 acceptable/再次开启指标；
- 未完成 15 秒真实启动基准、自然语言 onboarding 和单状态卡 UI；
- 未删除 managed-session/operator/host-loop 等兼容入口。

因此，当前完成的是可进入真实实验验证的首个纵切面，不是对 6–8 周产品 Gate 的
提前宣告。

## 1. 战略修订

上一版把旗舰场景收缩成了“读取当前线程、生成一句回复、用户亲自发送”。这个方向虽然容易验证，但失去了 Dating Booster 相比通用 agent 的实验价值。

本项目需要回答的核心问题不是：

> AI 能否写出一句还不错的回复？

而是：

> 用户只授权一次后，系统能否在多个真实关系之间持续发现机会、正确排序、理解上下文、发送自然回复、适时跟进、记住进展，并在真正需要本人决定时停下来？

因此，未来 6–8 周的旗舰产品必须是一条完整的 bounded full-management 链路。Stage 只作为 shadow、调试和故障 fallback，不再作为最终产品合同。

## 2. 旗舰产品合同

### 2.1 单一旗舰路径

- App：TaShuo / 她说；
- Runtime：Apple Silicon `mac-ios-app`；
- Host：Codex host-native；
- 模式：bounded managed session；
- 发送：live managed GUI send；
- 对象：当前消息列表中的多个合格普通聊天；
- 运行方式：用户明确开始、可随时暂停、到期自动停止；
- Standalone：暂不作为旗舰，因为当前 executor 仍是 stage-only。

如果现有内测用户主要使用其他 App，可以整体迁移这条产品合同，但仍只能选一个 App/runtime，不同时维护四条旗舰路线。

### 2.2 “全托管”的准确含义

用户在会话开始时一次性确认范围。随后系统自主完成：

1. 进入消息列表并扫描合格对象；
2. 识别新入站、等待中、可跟进和必须 handoff 的状态；
3. 按确定性优先级选择一个对象；
4. 打开并验证目标线程；
5. 读取新鲜上下文和必要记忆；
6. 判断 reply、nudge、wait、skip 或 handoff；
7. 生成一个最终版本并做一次自动修订；
8. 自动 stage、核对并发送普通消息；
9. 从新鲜界面验证发送结果；
10. 更新对象状态、记忆和下一步；
11. 返回列表继续处理，或进入等待；
12. 停止时输出全局关系进度报告。

在授权窗口内，普通消息不逐条请求用户确认。

### 2.3 允许系统自主完成

- 多对象扫描和机会识别；
- 回复优先级排序；
- 普通聊天回复；
- 接梗、轻自曝、深化或切换话题；
- 低投入修复；
- 非具体的 soft invite probe；
- 用户明确授权后的谨慎 nudge；
- 等待、跳过和稍后唤醒；
- 关系状态、commitment 和下一步更新；
- session 结束报告。

### 2.4 必须 handoff 的边界

全托管不等于操作 App 的所有功能。以下节点仍交给用户：

- 具体邀约时间、地点和承诺；
- 联系方式交换；
- question gate 的启用、跳过、接受、拒绝和发送；
- like、pass、super-like、unmatch、report；
- profile edit；
- 支付、会员、通话和视频通话；
- 明确的亲密升级或可能越界的内容；
- 拒绝、冲突、威胁或其他高风险情境；
- identity conflict 或跨 App 同一人确认；
- 目标无法可靠识别；
- 输入框已有未知文本；
- 最新上下文缺失或过期；
- 发送结果为 unknown；
- 模型必须编造用户事实才能继续。

全托管的价值不是“永远不问用户”，而是让用户只处理确实需要本人判断的节点。

## 3. 北极星指标与产品 Gate

### 3.1 北极星指标

北极星指标：

> Verified Autonomous Handling Rate，验证通过的自主处理率。

定义：

```text
系统正确处理的合格机会
÷
managed session 发现的全部合格普通聊天机会
```

“正确处理”包括：

- 自动回复已准确发送并验证；
- 合格 nudge 已准确发送并验证；
- wait/skip 判断合理；
- 系统正确识别必须 handoff 的节点。

为避免通过“多发消息”或“全部 handoff”刷指标，必须同时满足：

- 用户事后认为自动消息可以接受；
- 没有 wrong target、duplicate send、事实编造和边界违规；
- handoff 被用户认为必要；
- 不需要用户再发送补救消息。

### 3.2 配套指标

- 每 managed hour 的 verified autonomous turns；
- eligible opportunity 到 verified send 的耗时；
- 事后 `acceptable / off_tone / unsafe / needs_repair`；
- false handoff 和 missed handoff；
- wrong-target、duplicate、unauthorized、unknown-send；
- 每 session 用户被打断次数；
- nudge 的可接受率和负面反馈率；
- progress report 与真实状态一致率；
- 用户节省的主动操作时间；
- 次周再次开启 managed session 的比例；
- 同一上下文下，相对简单 host baseline 的自然度盲测胜率。

回复率、转微信率和见面率可以作为用户自愿提供的下游观察，不作为自动策略的主要优化目标。

### 3.3 第 6 周产品 Gate

建议小规模 Gate：

- 至少 200 次 verified autonomous send；
- 至少 50 次目标切换；
- 至少 20 次 nudge；
- wrong-target、duplicate、unauthorized 和 handoff boundary breach 为 0；
- unknown-after-click 不发生自动重发；
- 事后 acceptable `>= 90%`；
- verified autonomous handling rate `>= 70%`；
- progress report 准确率 `>= 90%`；
- 每 session 平均主动打断用户不超过一次；
- 至少一半完成多次体验的用户在下一周再次开启全托管。

这些数字是产品决策门槛，不是统计学上的市场证明。

## 4. 最简用户体验

### 4.1 首次使用

- 安装、doctor、数据迁移和 macOS 权限检查只做一次；
- 用户自我模型改成 6–8 个自然语言问题，不要求填写 JSON；
- 用户提供少量本人真实消息、表达禁区和明确事实；
- 目标：一次性 onboarding 不超过 6 分钟。

### 4.2 日常启动

用户只需说：

> 全托管她说 2 小时，普通聊天允许自动发送，保守推进；涉及具体邀约、联系方式或目标不确定时找我。

系统只展示一张确认卡：

```text
App：她说 · 本地 iOS
时长：2 小时
范围：全部合格普通聊天
允许：扫描、排序、自动回复、一次谨慎跟进
暂停点：具体邀约、联系方式、目标不确定、输入框异常
静默时间：23:00–08:00
发送预算：本次最多 5 条

[确认全托管] [调整]
```

一次确认同时绑定 app、runtime、时长、普通消息范围、quiet hours、nudge 和发送预算。用户不接触 auth、goal、availability JSON，也不复制 config hash 或重放长命令。

目标：健康环境 15 秒内进入运行状态；异常时只显示一个具体恢复动作。

### 4.3 运行中

默认只显示一张低干扰状态卡：

```text
运行中 · 37 分钟
已检查 8 人 · 自动回复 3 · 等待回复 4 · 需你处理 1
当前：等待下一轮扫描

[暂停] [查看详情] [停止并报告]
```

只在以下情况主动通知：

- 发生 verified send；
- 出现 handoff；
- 发送结果 unknown；
- safety pause 或运行故障；
- session 到期。

普通扫描、等待和内部 policy 结果不刷屏。

### 4.4 暂停、恢复和停止

- Pause 在下一次 stage/paste/send 前立即生效；
- 两秒内向用户确认已经暂停；
- Resume 继续同一个 run 和 active target，不新建 operator session；
- 停止后三秒内给出五行摘要；
- 详细审计、support bundle 和逐对象证据按需展开。

## 5. 最小完整技术纵切面

### 5.1 当前问题

当前 managed path 由四层接力：

- `managed-session` 负责调度和等待；
- `automation` 负责状态、优先级和 send request；
- `operator` 负责 durable work item 和队列；
- `host-loop` 再通过 CLI 子进程、work-dir 文件和 host 回调执行观察与发送。

Host-loop 的 scan/open/observe/draft 仍会停下来等待 host 写 observation JSON。这是一套“可被 host 接力的编排协议”，还不是用户启动后可以持续运行的完整全托管产品。

### 5.2 唯一外部概念：ManagedRun

对外只保留：

```text
dating-boost manage start
dating-boost manage status
dating-boost manage pause
dating-boost manage resume
dating-boost manage stop
```

内部状态机：

```text
start
  → scan message list
  → prioritize one target
  → open target thread
  → observe fresh thread
  → assess + draft + review
  → send transaction
  → verify fresh post-send state
  → update state
  → continue / wait / handoff / stop
```

一次 start 后，在同一个进程和同一个 durable run 中持续推进，不再让用户或 host 手工拼接多个 session engine。

### 5.3 四层合并

| 现有层 | 合并后的职责 |
| --- | --- |
| managed-session | 公共 start/status/pause/resume/stop 和 wake scheduler |
| automation | 无 session 的纯 domain reducer：优先级、handoff、nudge 和 send eligibility |
| operator | 内嵌为 ManagedRun 的 active step、queue 和 checkpoint，不再独立启动 session |
| host-loop | 薄 host facade；observe/model/send 通过 typed ports 在同一进程执行 |
| managed GUI send | 独立原子的 `SendTransaction` |

不要新建第五套 workflow engine。可以复用现有 standalone runtime 的 in-process 消费结构作为骨架，但旗舰执行仍是 host-native managed live send。

### 5.4 单一持久化真相源

合并为三类数据：

- `managed_run`：phase、active target、cursor、budget、next wake；
- `thread_state`：每个对象的状态、inbound revision、next action；
- `run_event/send_attempt`：必要恢复记录。

删除或退出热路径：

- managed/automation/operator 三份 session state；
- host-loop 第二份 current work item；
- work-dir 中的 observation、draft、staged verification 和长期 consumed 副本；
- 每条 CLI 的 started/finished support event；
- 多份 generation/review/evidence audit alias。

持久化只保留恢复所需的最小 checkpoint，不追求完整 forensic event sourcing。

### 5.5 每轮执行

Scan：

- 一次 observation 原子完成识别、校验和 reducer input；
- 返回可见 rows、unread/preview/age、结构 locator、cursor 和历史截止；
- 不再生成模板文件后等待 host 回填。

Prioritize：

1. unknown/composer recovery；
2. 新入站 continuation；
3. 其他 unread/reply-required；
4. 新开启的合格普通聊天；
5. 合格 nudge。

Nudge 永远低于真实 inbound。同一 tier 可使用 freshness、用户显式优先级、关系阶段和 commitment，不使用颜值、付费价值或不可解释成功率。

Open/Observe：

- 使用本轮 locator 打开线程；
- 打开失败或目标绑定不一致时重新 scan；
- 打开后取得新鲜 thread observation、inbound revision 和 composer 状态；
- 只在草稿引用 profile 事实时读取对应资料，不每次完整读 profile。

DraftDecision：

```json
{
  "target_id": "...",
  "inbound_revision": "...",
  "messages": ["..."],
  "outcome": "send|wait|handoff|blocked",
  "reason_codes": []
}
```

一次模型生成、最多一次自动重写、一次确定性 policy review。复杂 planner 分数和多套 evidence 可以作为内部调试信息，但不能在多个层之间复制并阻塞执行。

SendTransaction：

- session 仍 active；
- app/runtime/target 授权仍有效；
- 不在 quiet hours；
- target binding 和 inbound revision 未变化；
- composer baseline 为空；
- paste 后 exact staged text 一致；
- click 前保存 idempotency checkpoint；
- click 前最后检查 pause；
- click 后立即取得新鲜 observation。

发送结果只有：

- `confirmed`：目标一致、composer 清空、outbound exact text 可见；
- `failed_before_click`：确定未发送，可以安全重试；
- `unknown_after_click`：可能已发送，禁止自动重发并 handoff。

Continue：

- confirmed 后原子更新 thread state；
- 仍有候选和预算时重新 scan；
- 无工作时 waiting；
- quiet hours、授权到期、用户 stop 时 stopped；
- handoff/unknown 时暂停对应对象；beta 期间 unknown 暂停整个 run。

## 6. 安全策略：只保留事故不变量

主要威胁是误操作，不是公网攻击。必须保留：

- 用户一次明确开启 live managed session；
- app/runtime 和时长范围；
- 全局 pause/stop；
- 永久禁止非普通聊天动作；
- target binding；
- 新鲜 inbound revision；
- composer-empty baseline；
- exact staged text；
- pre-click idempotency checkpoint；
- fresh post-send verification；
- unknown-after-click 禁止自动重试；
- bounded time、scan 和 send budget；
- crash resume 从 checkpoint 对账，不从 phase 起点重放。

这些检查同时也是全托管功能正确性，不应视为安全过度设计。

可以从热路径移除或异步化：

- 每次任务重复的 release/data/capabilities 深 doctor；
- 每条消息单独授权或确认；
- 每条消息多层 payload/action-request hash 搬运；
- planner debt、milestone 等字段在多个契约中复制；
- support session 的逐命令审计；
- relationship full report 的同步生成；
- Canary、Soak、production certificate 作为日常启动条件；
- 防篡改账本、复杂 encrypted evidence vault 和 crash-perfect 全历史重放。

本地临时目录使用 `0700`、文件 `0600` 和 TTL 即可，不再为短生命周期 handoff 文件建设独立安全子系统。

## 7. 回复质量与关系策略

全托管不能以“成功发出去”作为产品成功。自动发送的质量必须直接进入 Gate。

### 7.1 最小生成合同

- 先回应当前 live thread，再使用 profile hook；
- 每次只生成一个准备发送的版本；
- 不为了推进强行提问；
- 不堆 MBTI、星座和兴趣标签；
- 不使用分析报告式语言；
- 不重复已知信息和已经问过的问题；
- 长度、标点和 emoji 接近用户真实样例；
- 自我披露来自用户确认材料；
- 低投入时优先轻自曝、接梗、等待或低压力修复；
- 最多自动重写一次，仍不合格则 wait/handoff，不能勉强发送。

### 7.2 用户个性化

将 raw JSON self-interview 改成自然语言 onboarding：

- 5–10 条本人真实消息；
- 重要事实和绝对不能编造的内容；
- 语气偏好；
- 关系目标；
- 自我披露边界；
- 邀约和联系方式 handoff 偏好。

系统从用户事后标记和补救文本中学习本地偏好。用户不必维护 material id、usable move 和 schema。

### 7.3 真实评估

- 建立 60–100 个真实脱敏上下文；
- 当前全托管 draft 与简单 host baseline 在相同上下文生成；
- 随机盲评自然度、本人感、上下文贴合、愿不愿意发送和事实正确性；
- 内测发送后记录 `acceptable / off_tone / unsafe / needs_repair`；
- 内容、target/GUI 和策略优先级分别统计；
- 每周只修出现频率最高的三个失败类别；
- 静态预评分 reply-quality 只作为 fixture/schema regression，不再作为产品质量声明。

## 8. 测试与研发反馈周期

### 8.1 每次必跑的是全托管纵切面

不能再把 host-loop/live managed send 全部移到 nightly。每个 PR 必须证明：

```text
start → scan → prioritize → open → observe
→ draft → exact stage → send → verify
→ update → continue → stop/report
```

Critical Managed 必须覆盖四个核心不变量：

1. 不会发错人；
2. 不会发错文本；
3. 无法确认发送结果时不会重发；
4. pause/stop 后不会继续 GUI mutation。

同时覆盖：

- authorization expiry/runtime mismatch；
- duplicate inbound 不重复处理；
- nudge 最多一次且低于 inbound；
- handoff 边界；
- resume 延续同一个 run；
- progress report 不隐藏 unknown。

### 8.2 测试分层

| 层级 | 内容 | 目标 |
| --- | --- | --- |
| Critical Managed | reducer、SendTransaction、一个完整 fixture live-managed 纵切面 | 本地 <= 30 秒，coverage <= 45 秒 |
| PR Core | storage、migration、flagship adapter contract、CLI wiring | 测试 <= 90 秒，required feedback <= 3 分钟 |
| Nightly/Lab | 全 App UI fallback、进程/crash 矩阵、高吞吐、qualification | <= 10 分钟 |
| Real GUI Canary | flagship bounded live session | 人工触发，不伪装成单元测试 |

### 8.3 测试结构收敛

保留四组：

1. reducer 表驱动：unread、waiting、nudge、history cutoff、handoff、priority；
2. SendTransaction invariant：target、composer、stage、click、verify、unknown 和 resume；
3. App adapter contract matrix：locator、binding、stage、send、verify；
4. 两条纵切面：正常 full-managed 和 pre/post-click crash recovery。

直接减负：

- 删除 pytest 内重复的完整 agent-native smoke，只留独立 CI job；
- CI/config/README 字符串断言改为非阻断 lint；
- automation/operator/host-loop 不再各自复制同一发送不变量；
- Tinder/Bumble/TaShuo 共用 target/stage/send contract matrix；
- CLI subprocess 只保留一个 wiring smoke，其余直接测状态机；
- GUI 注入 fake clock/sleeper，移除单元测试真实等待；
- PR 的同步反馈不再跑 coverage；coverage 改为 nightly/manual 的单一 canonical
  Python job，避免每次小调整都等待 instrumentation；
- 功能分支不同时触发 push 和 pull_request 全矩阵；
- build、wheel smoke、agent smoke 和静态检查各跑一次。

目标不是测试数减半，而是日常只等待旗舰闭环和事故不变量。

## 9. 产品面处置

### 9.1 未来 6–8 周保留并投入

- 一个 App/runtime；
- bounded managed live session；
- 多对象扫描和优先级；
- 普通聊天自动发送；
- nudge；
- memory、goal 和 progress report；
- pause/resume/stop；
- stage/shadow 作为 beta fallback；
- 真实生成质量评估。

### 9.2 冻结，只修严重回归

- Tinder、Bumble、WeChat 新能力；
- 新 host adapter；
- standalone live；
- high-throughput 变体；
- 全局 24x7 daemon；
- discovery/like/pass；
- question-gate 自动化；
- 新 goal type；
- 新 production qualification 协议。

### 9.3 退出公开产品面

- stage-only 作为最终产品；
- automation/operator/host-loop/managed-session 四个并列入口；
- 四个 App 同等级成熟的表述；
- 144 个 CLI 命令直接暴露给用户；
- 静态 reply-quality 平均分；
- `release doctor ok` 等同真实全托管可用；
- production qualification 协议等同用户价值。

两个产品周期后，删除被 ManagedRun 取代的独立 session 入口、重复状态、work-dir 文件协议及对应测试。按完整纵切面删除，不留下半冻结兼容层。

## 10. 6–8 周执行路线

### 第 1 周：锁定合同并降低开发反馈成本

- 签订单一 App/runtime/full-managed 产品合同；
- 定义 eligible、priority、handoff、nudge 和 session budget；
- 将主 Codex skill 缩成全托管核心契约和按需路由；
- 建立 Critical Managed/PR/Nightly 分层；
- 消除重复 CI event、矩阵和 smoke；
- 建立简单 host draft baseline 和真实质量 taxonomy。

退出条件：团队能用一页说明系统何时自主发送、何时必须停；Critical Managed <= 30 秒。

### 第 2 周：多对象 shadow 与统一 ManagedRun

- 合并 managed、automation、operator、host-loop 的外部入口；
- 在 fixture 中跑通包含 `SendTransaction` 的完整 start→scan→prioritize→open→observe→draft→send→verify→continue→stop 纵切面；
- 真实 GUI 暂时采用 shadow，不点击发送，但使用真实消息列表和真实目标切换；shadow 是发布节奏，不是产品架构的终点；
- 收集至少 100 个候选决策、30 次目标切换、20 个 handoff/skip；
- 校验优先级、候选识别、send-worthy draft 和 stale/composer 检测。

Gate：wrong-target planning 为 0；必须 handoff 召回率 100%；优先级认可约 85%；send-worthy draft 约 70%。

### 第 3 周：单对象 live canary

- 2–3 位高触达用户；
- 每次只允许一个白名单对象；
- 每 session 最多 3 次 verified send；
- 暂不启用 nudge；
- unknown 立即暂停整个 run；
- 每条发送后做事后 review。

Gate：至少 30 次真实发送；wrong-target、duplicate、unauthorized 为 0；post-send verification 100%；acceptable 约 90%；无需补救消息。

### 第 4 周：多对象 live canary

- 3–5 位用户，每人 2–5 个对象；
- 每轮串行发送一条，完成后重新扫描；
- 每 session 总发送上限 5 条；
- 验证 cursor、目标切换、queue、resume 和 progress report。

Gate：累计 75 次 verified send；40 次目标切换；wrong-target/duplicate 为 0；verified autonomous handling rate 约 60%。

### 第 5 周：加入谨慎 Nudge

- 只有通过多对象 live 的用户启用；
- 用户最后发言至少 24 小时；
- 每对象 7 天最多一次；
- 永远低于真实 inbound；
- 没有第二次自动追击；
- 先积累 15–20 次事后 review。

Gate：错误触发为 0；时机和措辞可接受约 85%；不产生补救消息。

### 第 6 周：完整 bounded managed beta

- 8–12 位用户；
- 每次 1–2 小时；
- 多对象扫描、排序、回复、nudge、handoff、等待和报告；
- session-level 一次授权，不逐条确认；
- 按第 3.3 节执行产品 Gate。

### 第 7–8 周：有条件扩大或回退

Gate 通过：

- 扩到 15–20 位用户；
- 增加 session 时长，不提高单轮并发发送数；
- 固化唯一公开的 full-management 入口；
- 继续保持其他 App、standalone 和 high-throughput 冻结。

内容质量失败：保留全托管目标，退回 shadow 修 drafting。

GUI/目标绑定失败：暂停 live beta，不能用 stage 成功替代全托管 Gate。

用户不愿再次开启：说明托管价值没有成立，应重新做用户研究，而不是增加 App 或安全层。

## 11. 完成定义

产品：

- 用户一次授权后，系统能独立完成多对象普通聊天闭环；
- verified autonomous handling rate 和事后 acceptable 达到 Gate；
- 用户只在 handoff、unknown 和故障时被打断；
- 用户愿意再次开启全托管。

体验：

- 健康环境 15 秒内启动；
- 运行期间只有一张状态卡；
- pause 两秒内确认；
- stop 三秒内输出摘要；
- 不暴露 JSON、hash token 和内部 session engine。

研发：

- 只有一个 ManagedRun 真相源；
- 只有一个 SendTransaction owning boundary；
- Critical Managed <= 30 秒；
- PR required feedback <= 3 分钟；
- 全量环境矩阵不阻塞日常开发；
- 没有为了合并四层而新建第五套架构。

如果系统只是更快地生成草稿，却不能在授权窗口内持续自主处理多个关系，这轮优化应判定失败。
