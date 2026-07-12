# TaShuo Standalone Production Qualification Gate Design

## 1. 目标与结论边界

为 Dating Booster 的独立 Agent 增加一套真实 GUI 生产资格测试协议，范围严格限定为：

- App：她说 / TaShuo。
- Runtime：`mac-ios-app`。
- Agent：`standalone-session`。
- Send mode：`stage`。
- Observation source：真实 GUI。
- Model/vision：现有 MiniMax/OpenAI-compatible backend contract。
- Target scope：她说消息页中任意可见、结构化绑定成功、输入框基线为空的普通聊天。

门禁先运行 10 轮真实 GUI canary。Canary 通过后，用户必须在 24 小时有效期内显式启动 100 轮、至少 8 小时的 soak。全部标准满足后，只允许声明：

```text
tashuo standalone stage-only qualification protocol passed for the pinned environment
```

该结论只覆盖 manifest 固定的代码、依赖、系统、App、模型、授权和测试时段，不代表：

- 任意环境下的通用生产就绪。
- 任意真实账号或任意聊天状态下的安全性。
- live send 已通过资格测试。
- 99% 的总体可靠性或 SLA。

如果 provider 不返回稳定的 deployment/model revision，“固定模型”只表示固定 endpoint、model identifier 和同一 credential fingerprint，不表示远程模型权重未变化。

## 2. 非目标

本阶段不做以下工作：

- 不扩展 Tinder、Bumble 或微信。
- 不启用 `StandaloneManagedGuiSendExecutor` 的真实发送。
- 不执行 like、pass、question gate、profile edit、payment 或联系方式交换。
- 不把 fixture-only 测试计入真实 GUI canary 或 soak。
- 不把历史 Alpha 记录当作当前实现的生产资格证据。
- 不依赖输入框为空来推断“没有发送”。
- 不允许把主数据目录 `.local/dating-boost` 作为 qualification runtime data dir；唯一允许的访问是 parent 在 preflight 做 allowlisted、只读 user-model snapshot 导入。

## 3. 已核实基线与启动前阻断项

当前代码已具备 `standalone-session start/tick/status/stop`、TaShuo `mac-ios-app` 的真实 GUI 观察与 staging、`JsonStorage` 加密状态、support session 和 strict bundle。

但以下事实使当前实现不能直接作为 Production Gate 的可信底座：

1. `standalone_alpha_gate.py` 直接读取明文 `audit/stage_results.jsonl`，而当前 `ActionAuditLog` 已通过 `JsonStorage` 写入加密 SQLite。全新加密数据目录会被 Alpha evaluator 误报为缺少 stage result。
2. 当前 stage evidence 中的 `live_send_executed=false` 是执行路径写入的声明，不是独立反证。发送也可能导致输入框为空，所以“最终输入框为空”不能证明未发送。
3. 当前 TaShuo stage runtime 会在粘贴前清除输入框，可能覆盖用户已有草稿，并使用系统剪贴板留下额外崩溃与隐私边界。
4. 当前 cleanup 只验证处于某个 TaShuo conversation surface，没有绑定到原目标和原 staged payload。
5. 当前 smoke receipt、stage audit 和 dedup key 没有贯穿 `qualification_id/cycle/attempt/local_fencing_token/runtime_fencing_token`。
6. 当前 smoke 在部分失败或中断路径中无法留下足够的 GUI mutation 与 terminal evidence。
7. 全新 dedicated data dir 没有 `user_profile.json` 和 disclosure source/profile，现有 autonomous readiness 会直接返回 `needs_user_profile`。
8. 成功 staging 后现有 automation 会停在 `staged_pending_user`，sticky work item 和 active request 会阻止下一 qualification cycle。
9. Data-dir 内的锁无法排除其他 data-dir、host-loop、managed-session 或直接 harness 同时操作同一个 TaShuo App 实例。
10. 当前 conversation perception 没有 negative-send 所需的 bubble bounds/order/viewport identity evidence。

2026-06-30 的 20/20 真实 Alpha 记录早于当前加密 evidence 路径，只是历史基线。修复加密读取后必须重新生成新证据，历史记录不得用于 canary 或 soak。

Production runner 在打开 App 前必须验证以下前置条件；任一失败都返回 `preflight_blocked`：

- 在 dedicated data dir 上依次完成 release/skill doctor、data doctor/migrate 和 capabilities contract 检查；确认 direct harness send 仍为 executor-internal only。
- `runtime select/status` 必须固定 `app_id=tashuo,runtime=mac-ios-app`；任何 runtime scope mismatch 在创建 GUI adapter 前阻断。
- Phase support session 必须在任何可见 App observation 前成功取得 owner；support start 后不再运行 data migrate/delete。
- Alpha evaluator 通过 `JsonStorage.read_jsonl` 读取 stage results，并有“仅加密 SQLite、无明文 mirror”的回归测试。
- Alpha 输出把逻辑 stream 与物理 backend 分开报告：`audit_stream=audit/stage_results.jsonl`、`storage_backend=encrypted_sqlite`；storage/decryption 错误必须是结构化 blocked reason。
- Parent 从用户显式指定的 source data dir 只读导入 user-model snapshot，child 只使用 dedicated encrypted copy，autonomous readiness 必须通过。
- TaShuo `mac-ios-app` 生产 stage path 使用共享的 guarded AX `set-if-empty`/`clear-if-exact` primitive；qualification path 禁止访问系统剪贴板。
- qualification 路径绝不清除基线已存在的文本。
- qualification binding 已贯穿 session、work item、stage audit、support event 和 child receipt。
- `stage_consumed_after_verified_cleanup` transition 已实现，且只能在 target-bound cleanup 与 negative-send 通过后释放 sticky work item/active request。
- Evidence-only conversation-tail v2 已提供 bubble direction/bounds/order、viewport identity、capture id 和置信度；普通 thread observation 不得冒充 v2 evidence。
- 用户级 `tashuo/mac-ios-app` 共享 GUI lock、lease、fencing 和 safety pause 已覆盖 Gate、standalone、host-loop、managed-session 和直接 harness。
- Qualification receipt/event store 提供 `insert_if_absent` 与 append-only CAS，不能用普通 upsert 代替。
- fresh same-target negative-send observation 已实现并通过故障注入测试。

Alpha 的既有功能通过条件可以保留；修正 storage reader、加入 qualification binding 和更强的上层安全证据不属于降低或改写 Alpha 标准。

## 4. 架构与文件边界

Production Qualification Gate 是现有 standalone smoke 和 Alpha evaluator 之上的独立编排层，不用 shell 拼接状态，也不把状态机继续塞进已有大型 gate 文件。

### 4.1 生产模块

- `dating_boost/apps/tashuo/standalone_production_contract.py`
  - 配置规范化、环境指纹、状态转换、reason-code 表和通过条件。
- `dating_boost/apps/tashuo/standalone_production_lock.py`
  - 进程生命周期文件锁、CAS lease、fencing token、worker process-group 登记与接管。
- `dating_boost/apps/tashuo/standalone_production_ledger.py`
  - 加密 qualification/cycle/attempt 账本、事件 hash chain 和恢复决策。
- `dating_boost/apps/tashuo/standalone_production_attempt.py`
  - qualification binding、mutation checkpoint、child receipt 和 target-bound cleanup 协议。
- `dating_boost/apps/tashuo/standalone_production_evidence.py`
  - same-target negative-send evaluator、脱敏摘要、manifest 和离线复验。
- `dating_boost/apps/tashuo/standalone_production_artifacts.py`
  - 原始证据加密、临时文件销毁、quarantine、qualification bundle 和保留策略。
- `dating_boost/apps/tashuo/standalone_production_runner.py`
  - Canary/soak 编排、调度、重试、恢复、support ownership 和阶段收尾。
- `dating_boost/core/gui_runtime_lock.py`
  - 用户级 TaShuo mac-ios-app 共享锁、runtime lease/fencing 和 runtime-wide safety pause；不扩展其他 App/runtime。
- `scripts/tashuo_mac_ios_standalone_production_gate.py`
  - 薄 CLI，提供 `canary`、`soak`、`status`、`resume`、`finalize`、`validate`。

### 4.2 必要的底层修正

- `standalone_alpha_gate.py` 改用 `JsonStorage` 读取 stage results。
- TaShuo stage/cleanup runtime 使用非测试专用的 guarded AX primitive，并接受 qualification binding、mutation guard 和结构化 target binding。
- stage audit schema 增加 qualification binding；dedup digest 必须包含完整 binding。
- standalone session、operator work item 和 support command context 透传完整 binding。
- child smoke 在退出前把 attempt-bound receipt 原子写入同一加密 store；stdout JSON 只用于诊断，不能作为提交依据。
- Action request 必须由现有 standalone/operator 流程生成；Production runner 不得手工拼接 executor-internal request，也不得直接调用 `send-message`。
- Qualification-only automation transition 在 verified cleanup 后原子消费 staged request、清除 sticky work item，并把 predecessor binding 留在 production ledger；该 transition 不能被普通 stage 命令调用。

## 5. 隔离目录与用户接口

### 5.1 目录所有权

CLI 接受 `--root-dir`，并为每个 qualification 创建：

```text
<root-dir>/<qualification_id>/
  data/                 # 独立 JsonStorage 加密 SQLite
  work/                 # 仅本 qualification 的临时工作区
  vault/                # 加密原始证据和 quarantine
  output/               # 脱敏 manifest、phase support bundle 与 qualification bundle
  runner.lock           # qualification-local runner lock
```

约束：

- `data/` 必须是 Gate 新建的空目录，并带 qualification ownership marker；随后只能导入 allowlist 中的 user-model snapshot。
- 拒绝主数据目录、已有 Dating Booster 数据目录、符号链接逃逸和其他 qualification 的目录。
- 所有 child command 的 data/output/temp path 只能使用该 `data/`、`work/` 和 `vault/`；共享 runtime lock 是唯一允许的外部状态路径。
- Parent 只读打开用户显式指定的 source data dir，仅复制 `user_profile.json`、`user/disclosure_profile.json`、`user/dating_profile_source.json`、`user/self_interview_source.json`，并从 `user/user_memory_projection.json` 生成 sanitized projection：只保留 user/profile/disclosure 与 `tashuo/mac-ios-app` profile source，强制 `thread_disclosures=[]`。不复制 match、chat、observation、audit 或 session 状态。
- Snapshot 导入后在 dedicated store 重新运行 autonomous readiness，并验证 TaShuo mac-ios-app user profile source；source 路径不写入 manifest，只保存 canonical snapshot digest。
- Parent 把 canonical authorization 写入 dedicated encrypted config record；child 通过 record id 读取，不直接读取外部 authorization path。Parent 在每个 selection probe/attempt 前重新读取外部文件，要求 digest 不变且未撤销；Soak/recovery 都必须再次显式提供该路径。
- Child 不得读取 source data dir；`TMPDIR`、Python cache、SDK cache 和日志目录都重定向到 qualification root，并使用最小环境变量 allowlist。
- Qualification staging 禁止读取、写入或恢复系统剪贴板；出现 `pbcopy`、paste hotkey 或 clipboard API 记录即安全阻断。
- 任何截图、OCR、模型原文或 smoke JSON 不得写到 qualification root 之外；stdout/stderr 也必须经过敏感字段过滤。
- 用户级共享 runtime lock 位于固定的 macOS user-state 目录，不在 qualification root；其中只保存非敏感 owner/fencing 元数据。

### 5.2 Canary

```bash
python3 scripts/tashuo_mac_ios_standalone_production_gate.py canary \
  --root-dir .local/dating-boost-tashuo-production \
  --user-model-source-data-dir .local/dating-boost \
  --authorization auth.json \
  --json
```

Canary 固定为 10 个合格周期，不允许降低。通过后返回：

- `qualification_id`
- `environment_fingerprint`
- `config_hash`
- `canary_chain_root`
- `canary_accept_token`
- `canary_expires_at`
- `claim_code=CANARY_PASSED_SOAK_NOT_RUN`
- `canary_certificate_path` 与 digest
- `next_command`

Token 只用于绑定本次证据，不是抵御本机恶意用户的秘密：

```text
sha256(
  "tashuo-standalone-soak\0" +
  qualification_id + "\0" +
  config_hash + "\0" +
  canary_chain_root + "\0" +
  canary_certificate_digest
)
```

### 5.3 Soak

```bash
python3 scripts/tashuo_mac_ios_standalone_production_gate.py soak \
  --root-dir .local/dating-boost-tashuo-production \
  --qualification-id <qualification_id> \
  --accept-canary <canary_accept_token> \
  --authorization auth.json \
  --json
```

Soak 固定为 100 个计划周期和至少 8 小时。它重新读取 authorization，要求 canonical hash 与 Canary 完全相同，并重新检查有效期/撤销状态。生产 CLI 不暴露缩短轮数、持续时间或 fake clock 的参数。

### 5.4 Status、Resume、Finalize 与 Validate

```bash
python3 scripts/tashuo_mac_ios_standalone_production_gate.py status \
  --root-dir .local/dating-boost-tashuo-production \
  --qualification-id <qualification_id> \
  --json

python3 scripts/tashuo_mac_ios_standalone_production_gate.py resume \
  --root-dir .local/dating-boost-tashuo-production \
  --qualification-id <qualification_id> \
  --authorization auth.json \
  --json

python3 scripts/tashuo_mac_ios_standalone_production_gate.py finalize \
  --root-dir .local/dating-boost-tashuo-production \
  --qualification-id <qualification_id> \
  --json

python3 scripts/tashuo_mac_ios_standalone_production_gate.py validate \
  --bundle .local/dating-boost-tashuo-production/<qualification_id>/output/qualification_bundle.zip \
  --json
```

`status` 始终只读：运行中读取加密账本，敏感数据清理后读取脱敏 terminal manifest，并给出精确 `next_command`。Canary 在返回 qualification id 前崩溃时，可省略 `--qualification-id`，只列出 root 下的 qualification id、状态和 next command，不输出目标或聊天信息。`resume` 只恢复账本中的 active phase，不得切换 Canary/Soak，也必须重新校验 authorization、environment、locks 和 support ownership；未知 GUI mutation 时先执行第 13 节恢复，不能直接继续。`finalize` 不打开 App，只恢复 bundle/purge/manifest 发布步骤。`validate` 不打开 App、不调用模型、不读取剪贴板，可接受 Canary certificate 或 final qualification bundle，并重算证据 predicate、计数和 hash chain；Canary certificate 的 `qualification_passed` 必须为 false。

## 6. Qualification 状态机

测试 outcome 状态：

```text
created
  -> preflight_passed
  -> canary_running
  -> canary_passed
  -> soak_running
  -> soak_criteria_met

任意 active state -> qualification_blocked
canary_passed -> qualification_expired
```

Finalization 状态独立记录：

```text
open
  -> evidence_written
  -> provisional_validated
  -> purge_pending
  -> purged
  -> bundle_sealed
  -> bundle_validated
  -> manifest_published
  -> validated

任意步骤 -> finalization_failed -> 由 finalize 幂等恢复
```

Outcome 与 finalization 完成后才映射到用户终态：

- `soak_criteria_met + validated -> protocol_passed`
- `qualification_blocked + validated -> blocked_finalized`
- `qualification_expired + validated -> expired_finalized`

约束：

- `protocol_passed`、`blocked_finalized`、`expired_finalized` 是终态。
- Test outcome 一旦进入 `qualification_blocked` 或 `qualification_expired` 不得恢复测试；`finalize` 只能完成证据与清理。
- `finalize` 只接受 `soak_criteria_met`、`qualification_blocked`、`qualification_expired` 或已有 `finalization_failed`；不能把仍有效的 `canary_passed` 提前映射为通过。
- `protocol_passed` 只能在 purge 已验证且 published manifest 的离线 validate 通过后产生。
- `soak` 必须由用户显式调用，runner 不得自动从 canary 进入 soak。
- `soak_started_at` 必须在 `canary_passed_at` 后 24 小时内。
- Canary 有效期使用同一 boot session 的 monotonic clock 验证；期间重启、时钟连续性无法证明或 wall clock 回退时，qualification 进入 `qualification_expired`，不能仅靠墙上时间延长有效期。

## 7. 固定环境与配置哈希

Canary preflight 在打开 App 前执行一次非 GUI provider identity probe，并生成 canonical environment fingerprint，至少包括：

- Dating Booster tool version。
- 运行模式：clean source checkout 或 pinned built artifact。
- Source checkout 的 Git commit、branch-independent tree digest 和 clean-tree 状态。
- Built artifact 的 wheel/executable SHA-256。
- 已加载 Python package 文件 digest。
- 规范化依赖快照 digest，包括 package name、version 和 direct URL/hash 信息。
- Python 实现与完整版本。
- macOS product/build version、architecture 和 boot session id。
- Display logical/pixel bounds、scale factor、system appearance/locale，以及 Accessibility/Screen Recording permission state。
- TaShuo bundle id、bundle short version、bundle build version 和 executable digest。
- `app_id/runtime/send_mode/managed_gui_send`。
- `staging_input_backend=guarded_macos_accessibility` 与 shared runtime-lock protocol version。
- User-model snapshot canonical digest；不包含 source data-dir 路径。
- backend、vision backend、model identifier、base URL 和 API key 环境变量名。
- `HMAC-SHA256(qualification_salt, api_key)` credential fingerprint；不保存 key 值，也不跨 qualification 关联。
- Provider 响应中的 model/deployment/revision identifier；provider 不提供时明确记录 `revision_unavailable`。
- authorization canonical hash。
- reason-code schema version、canary/soak 阈值、`selection_probe_timeout=120s`、`attempt_timeout=300s` 和调度版本。

规则：

- Source checkout 模式下存在 tracked 或 untracked 改动即阻断 canary。
- Dirty checkout 只有先构建并固定 artifact digest，且实际从该 artifact 运行时才允许测试。
- Soak 必须重新采集 fingerprint，并与 canary 做字段级完全相等比较。
- 每个 attempt 在调用 provider 前重新计算 credential fingerprint，并把实际响应 model/deployment identifier 写入 attempt outcome；不能只信任 canary 账本缓存。
- Provider 返回稳定 identifier 时，每个 attempt 必须与 preflight probe 完全一致；中途漂移立即阻断。
- Git commit 相同但 user model、credential、依赖、Python、OS、App、endpoint/model identifier 或授权不同，都不得复用 canary。
- Provider 不返回稳定 revision 时，manifest 使用 `model_pin_level=endpoint_identifier_only`，禁止声称固定远程模型实现。
- `config_hash` 是 canonical fingerprint 与协议配置的 SHA-256，不包含时间、PID 或 raw secret。

## 8. Qualification Binding 与审计边界

每个 attempt 使用不可缺省的结构：

```json
{
  "schema_version": 1,
  "qualification_id": "qual_...",
  "phase": "canary|soak",
  "cycle_index": 1,
  "attempt_id": "attempt_...",
  "local_fencing_token": 1,
  "runtime_fencing_token": 7
}
```

候选选择使用独立、不可计入成功率的 `selection_probe_binding`：

```json
{
  "schema_version": 1,
  "qualification_id": "qual_...",
  "phase": "canary|soak",
  "planned_slot_id": "slot_...",
  "probe_id": "probe_...",
  "local_fencing_token": 1,
  "runtime_fencing_token": 7
}
```

Probe 只能观察/导航，不得执行 content mutation；每个 probe 仍必须有 start/terminal command audit、shared-runtime fencing 和结构化 outcome。找到 eligible target 后才创建 cycle attempt，并把 probe target binding 写入 attempt precondition。

完整 binding 必须出现在：

- standalone session state/event。
- operator work item 与 action request。
- target binding、precondition 和 payload record。
- stage result 与 action audit。
- support command start/finish event。
- child receipt 与 parent terminal audit。
- event digest、dedup key、cycle summary 和 manifest evidence index。

规则：

- Runner 在 attempt 的任何 GUI 操作前写 `attempt_started`；selection probe 则先写独立的 `selection_probe_started`。
- Child 对每个可控退出路径在 `finally` 写 `attempt_terminal`；硬崩溃由 parent 在完成恢复协议后写独立的 `attempt_recovery_terminal`，不得伪装为 child terminal。
- Terminal audit 记录 target hash、最后 mutation phase、verification、cleanup、negative-send 和 reason code。
- Child 正常退出前必须把 receipt 原子写入 `standalone_production/receipts/<attempt_id>.json` 的加密 store。
- Parent 不接受 stdout、退出码或临时 JSON 代替 receipt。
- 每个 attempt 恰好有一个独立 `qualification_attempt_outcome` 和一个 child receipt 或 recovery receipt；stage result 继续只表示实际 stage action，不承担通用终态语义。
- 早于 `stage_mutation_intent` 的 attempt 必须有零条 stage result；到达 `stage_mutation_intent` 的 attempt 必须恰好有一条绑定完整的 stage result，状态为 `completed` 或 `failed`。
- Cycle 保存全部 `attempt_ids`，并用 CAS 选择唯一 `final_attempt_id`。成功 cycle 的 final attempt 必须有一条 `completed` stage result；pre-mutation 功能失败允许零条 stage result；post-mutation 功能失败必须有一条 `failed` stage result和 verified cleanup outcome。
- Validator 必须遍历 cycle 的所有 attempts，拒绝 orphan、重复、binding 不一致、缺少 terminal outcome 或未安全结束的旧 retry，不能只验证 final attempt。
- Dedup 不得把不同 attempt 的相同 target/payload 合并，也不得让同一 attempt 重复提交。
- Receipt、attempt outcome、cycle commit 和 chain event 使用事务级 `insert_if_absent`/append-only CAS；相同 key+digest 是幂等 replay，相同 key+不同 digest 立即阻断，普通 upsert 不满足合同。

## 9. 目标选择与用户输入保护

“任意可见普通聊天”只表示 runner 不要求专用测试联系人，不表示任意当前 UI 状态都可修改。候选必须同时满足：

- 当前 surface 是普通聊天，不是 question gate、推荐、付费或系统页。
- 从消息列表取得结构化 `chat_list_row_to_thread` 证据，或从已绑定 predecessor 取得 `current_thread_visual_identity`。
- target binding 在 staging 前再次验证。
- composer baseline 可以精确证明为空。
- evidence-only conversation-tail v2 baseline 可用于 post-cleanup same-target 比较。

输入保护规则：

- composer baseline 非空时，在任何 AX write 或 clear 前返回 `candidate_composer_occupied`。
- Gate 永不清除或覆盖 pre-existing text，也不尝试判断它是否属于用户。
- 模型返回后、任何 stage mutation 前必须重新采集 frontmost app、window、target、thread tail 和 composer，写入 `pre_stage_revalidated` checkpoint；mutation guard 要求该证据年龄不超过 2 秒且之后没有 user-input event。
- Stage 只调用 `guarded_set_if_empty(expected_target, expected_tail, text)`；cleanup 只调用 `guarded_clear_if_exact(expected_target, exact_composer_text)`。底层 primitive 在单次 AX script 中比较后修改，比较失败不得写入。
- Persisted evidence 同时保存 canonical `payload_hash`、planned composer text，以及 AX set 后重新读取的 exact observed composer text/hash/character count。等价校验使用 Unicode NFC、CRLF/CR 到 LF 的规范化并保留其他空白；guarded cleanup 则比较加密保存的 exact observed AX string，不只比较规范化 hash。不能把多-bubble payload hash 当作输入框文本 hash。
- Qualification path 禁止 clipboard fallback。Guarded AX 对当前 TaShuo build 不可用时，preflight 或 attempt 必须阻断。
- occupied candidate 可以安全跳过；没有合格候选时返回 scheduler-level inconclusive，不得为了凑轮数放宽条件。
- 用户在 active attempt 期间不得操作 TaShuo。窗口、焦点、target、composer 或 thread tail 出现无法归因的变化时返回 `user_or_external_interference_detected` 并阻断。
- Active attempt 使用只读 user-input event sentinel；检测到键盘、鼠标或焦点干预时立即停止下一 mutation。该 sentinel 不拦截用户输入，因此协议结论仍明确依赖“用户不在 active attempt 操作 App”的前提。
- 用户可见输出只包含 target hash，不包含昵称、消息、草稿或完整 match id。

本协议不以这些约束证明“任意真实账号都安全”；它只证明被实际选择且满足前置条件的候选按协议完成。

## 10. 周期与调度

### 10.1 Canary

Canary 固定 10 个 committed cycle：

- Cycle 3、8 使用 `current-thread`。
- 其余 8 个使用 `message-list`。
- Cycle 3 必须绑定 cycle 2 的成功 target；cycle 8 必须绑定 cycle 7 的成功 target。
- `current-thread` 前不得插入其他 target 或 committed cycle。
- Canary predecessor 无法精确恢复时直接阻断；Canary 不使用 Soak 的 slot 重排。

### 10.2 Soak

Soak 最终必须有 100 个 committed cycle：

- 80 个 `message-list`。
- 20 个 `current-thread`。
- 名义序列为 20 组 `message-list x 4 -> current-thread x 1`。
- 每个名义位置有稳定 `planned_slot_id` 和 mode；实际提交顺序使用单独的 `commit_index`。
- 任意时刻最多一个真实 GUI worker，禁止并发追赶。

最小相邻间隔使用向上取整的整数纳秒：

```text
interval_ns = ceil(8h_in_ns / 99)
due(1) = soak_started_monotonic_ns
due(i + 1) = actual_start_ns(i) + interval_ns
```

Runner 必须保存每轮 `actual_start_ns`；validator 检查所有相邻开始时间差都不小于 `interval_ns`。延误从实际开始时间递推，禁止 catch-up 或最后单独等待凑满 8 小时。持续时间必须由同一 boot session 的 monotonic clock 证明；运行期间重启使 qualification 阻断。

### 10.3 Current-thread predecessor

- Current-thread cycle 只消费紧邻的成功 message-list predecessor binding。
- 如果进程恢复但 App context 丢失，只允许用 predecessor 的结构化 binding 精确重定位同一 target；不得调用通用 `prepare-message-page` 后任选一行。
- 精确重定位不是额外 cycle，也不能换 target。
- 仅在 Soak 中，如果 predecessor 失败或无法恢复且尚未 mutation，该 current-thread `planned_slot_id` 保持未提交。调度器消费一个后续尚未使用的 message-list slot 建立新 predecessor，再立即提交所欠 current-thread slot；两者按实际顺序分配 `commit_index`。
- 如果没有剩余 message-list slot，包括最后一组 current-thread 丢失 predecessor，qualification 直接阻断。
- Manifest 同时保存原始 planned-slot 序列和 commit 序列；最终仍必须严格达到 80/20，不能把 current-thread 静默降级为 message-list。

## 11. Attempt 执行协议

每个 attempt 按以下顺序执行：

1. 同时校验 qualification-local runner lock、用户级 TaShuo runtime lock、两个 CAS lease/fencing token、environment fingerprint 和 support ownership。Authorization 必须 `app_id=tashuo`、允许普通 `send_message` work-item creation、`autonomous_send=true`、`live_send=false`、`requires_post_action_verification=true`，且未过期、未撤销、不在 quiet hours；它不能授权 Gate 执行 live send。
2. 写入 `attempt_started` 并生成完整 binding。Child 以独立 process group 和显式 worker nonce 启动后先等待 parent barrier；parent 原子登记 PID/PGID、process start time、executable digest 和 nonce 后才释放 barrier。
3. 观察目标，生成结构化 target binding 和 evidence-only conversation-tail v2 baseline。
4. 验证 ordinary-chat surface 与 empty composer baseline。失败时不得访问剪贴板或修改 UI 内容。
5. 生成草稿并通过 policy check，计算 canonical payload hash、planned composer text/hash 和 character count。
6. 模型完成后重新采集并验证 frontmost app、window、target、tail baseline 和 empty composer；持久化 `pre_stage_revalidated`、证据年龄上限、target/precondition/composer hashes 和 `stage_mutation_intent`。
7. 在即时 local/global fencing check 后调用一次 guarded AX `set-if-empty`，写 `stage_mutation_completed` checkpoint；禁止 paste/clipboard fallback。
8. 在同一 target 上重新读取 AX value；只有 normalized observed text 等于 planned text 时 exact staged-text verification 才通过，并把 exact observed AX string/hash 持久化到 encrypted attempt record。
9. Cleanup 前重新验证 target，并调用 guarded AX `clear-if-exact`；只在当前 AX string 与本 attempt 持久化的 exact observed string 完全相同时清除。
10. 验证 composer 为空，再做 fresh same-target post-cleanup observation 和 negative-send evaluation。
11. Negative-send 通过后，执行 qualification-only `stage_consumed_after_verified_cleanup`，原子释放 sticky work item/active request，并在 production ledger 保留 predecessor binding。
12. Child 写 attempt-bound terminal audit、qualification attempt outcome 与 encrypted receipt 后退出。
13. Parent 对成功结果验证 Alpha；对功能失败验证 safe-failure outcome contract。随后统一验证所有 attempt receipts/outcomes、适用的 stage results、negative-send、support coverage 和 hash chain。
14. Parent 依次 CAS 写 `attempt_terminal_committed -> cycle_commit_intent -> cycle_committed_success|cycle_committed_failure`；每一步恢复时都先复验已有 digest，禁止再次 staging。

所有 click、guarded AX write/clear、local state transition 和 evidence commit 前都必须即时检查 qualification 与 shared-runtime fencing token。单次 preflight check 不能替代 mutation 前检查。

## 12. No-live-send 的独立反证

以下条件全部满足，attempt 才可得到 `negative_send_verification.status=verified`：

- Pre/post observation 都通过同一结构化 target binding。
- Post observation 发生在 cleanup 完成后，是新采集证据，不复用 stage observation。
- Pre/post 都必须来自 evidence-only conversation-tail v2；每个有序 bubble certificate 至少绑定 direction、规范化 exact-text hash、bubble bounds/anchor/order、viewport identity、capture id、observation id 和置信度。
- Post tail 保留完整 pre tail；若有新增 bubble，只能被明确识别为 inbound。
- 不存在新增 outbound bubble。
- 不存在 verified observed `composer_text_hash` 对应的新增 outbound bubble；canonical payload hash 只用于绑定 action，不代替 exact composer text comparison。
- GUI command audit 中没有 send click、Enter-send、`send-message`、`--managed-gui-send`、paste hotkey 或 clipboard API。
- `send_mode=stage`、`managed_gui_send=false`、`live_send_executed=false`。

输入框为空只是 cleanup 条件，不是 negative-send evidence。以下任一情况立即安全阻断：

- Post tail 缺失、无法绑定同一 target 或视觉/AX 置信度不足。
- Tail 变化无法可靠区分 inbound/outbound。
- Baseline 不再是 post tail 的可验证前序。
- 发现新增 outbound 或 staged payload 出现在 outbound。
- 只有自声明字段，没有 fresh post observation。
- 只有普通 conversation observation，没有 v2 bubble/viewport certificate。

## 13. 崩溃恢复与 Target-bound Cleanup

Attempt mutation phase 固定为：

```text
not_started
surface_navigation_started
target_bound
composer_empty_verified
pre_stage_revalidated
stage_mutation_intent
stage_mutation_completed
staged_verified
cleanup_started
cleanup_verified
negative_send_verified
stage_consumed
attempt_terminal_committed
```

Cycle commit state 独立为：

```text
planned
running
attempt_terminal_committed
cycle_commit_intent
cycle_committed_success | cycle_committed_failure
```

恢复 `running` attempt 时：

1. Parent 读取旧 worker 的 PID、PGID、process start time、executable digest 和 worker nonce。Signal 前必须重新核验全部身份；身份不符时不得 signal，设置 shared-runtime safety pause 并阻断。
2. 原 parent 负责 `waitpid` 自己的 child；接管者不能声称 reap 非自身 child，只能在定向终止后通过 process-group enumeration 与 liveness check 证明旧 worker 已消失。
3. 读取最后持久化 binding、target binding、canonical payload hash、planned/observed composer text/hash 和 mutation phase。
4. 若早于 `stage_mutation_intent`，且 screen 没有 composer，或原 target 的 composer 仍可验证为空，可以写 `abandoned_before_mutation` 并按 reason-code 规则重试；此路径不执行 clear，也不要求 negative-send。
5. 若早于 `stage_mutation_intent` 但 composer 非空、target 不匹配或状态未知，设置 shared-runtime safety pause 并阻断；不得把内容假定为本 attempt 所有。
6. 若 `stage_mutation_intent` 或更晚，必须精确重开并重新验证原 target；不得在未知 thread 上调用通用 clear。
7. 自动 clear 还必须同时有 `stage_mutation_completed` checkpoint、从 mutation 到 recovery 连续无缺口的 input-sentinel coverage、期间零 user event，以及 composer exact AX string 等于已验证并持久化的 observed string。随后才允许 guarded clear-if-exact、验证为空并执行 negative-send observation。
8. 若崩溃发生在 `stage_mutation_completed`/observed string 持久化前，或 sentinel coverage 有缺口，即使 current string 与 planned text 相同也不得自动清理；设置 shared-runtime safety pause，等待人工处置。
9. 若 composer 已为空，不修改 UI，但仍必须执行 negative-send observation，因为它可能已被发送；negative-send 可验证时可以写 recovery outcome，不要求自动 clear。
10. 若 composer 为其他非空内容、target 不匹配或内容状态未知，设置 shared-runtime safety pause，qualification 进入 `qualification_blocked`，等待人工处置；不得清除未知内容。
11. Parent 只有在 cleanup 和 negative-send 都可验证时，才能为 mutation 路径写 `attempt_recovery_terminal`。
12. 若 attempt terminal/receipt 已提交但 cycle 未提交，parent 复验 receipt、attempt outcome、stage-result cardinality、support finish 和 chain digest，幂等完成 `cycle_commit_intent -> cycle_committed_success|cycle_committed_failure`，绝不再次 staging。

恢复分类：

- `abandoned_before_mutation` 仅在旧 worker 已终止且未发生 content mutation 时可重试。
- Mutation 已发生的旧 attempt 只有在 target-bound cleanup 与 negative-send 成功并写入 `recovered_after_verified_cleanup` 后才可重试。
- Child 正常退出但 receipt/attempt outcome/terminal audit 缺失或不一致，立即阻断；stage result 是否必须存在由 mutation phase 决定。
- Mutation 已开始但既无 child terminal，也无法生成完整 recovery terminal，立即阻断。
- 已 `cycle_committed_success|cycle_committed_failure` 的 cycle 只复验全部 attempt 摘要和 chain，绝不重新 staging。

## 14. 并发、Lease 与 Fencing

不能复用当前“过期即覆盖”的普通 production store lock。Production Gate 同时使用 qualification-local 锁和用户级 shared-runtime 锁：

- Runner 获取 qualification 的 `runner.lock` OS `flock`，并持有到整个命令退出。
- Runner 还必须获取 `~/Library/Application Support/Dating Booster/runtime-locks/tashuo-mac-ios-app/` 中的 OS lock。该目录权限 `0700`、文件 `0600`，与 root/data-dir 无关；所有 TaShuo mac-ios-app standalone、host-loop、managed-session 和直接 harness GUI 入口都必须参与。
- Local 与 shared-runtime lease 都使用 compare-and-swap；owner 续约必须携带预期 lease version 和 fencing token。
- Lease 5 分钟，heartbeat 30 秒。
- Child mutation guard 要求 parent heartbeat age 不超过 90 秒；lease 仍未过期不能覆盖 heartbeat stale 或 parent-dead 检查。
- 两个 fencing token 各自单调递增，永不复用。
- Child 在每次 GUI mutation 和 evidence commit 前读取并比较 local/runtime token、owner nonce、parent PID/start-time liveness 和 heartbeat freshness；任一 stale 或 parent dead 都必须在 mutation 前退出。
- Shared runtime store 还持久化 runtime-wide safety pause。Target/worker identity 或 unknown composer 问题触发后，任何 data-dir 的 TaShuo mac-ios-app GUI mutation 都被阻断，直到用户显式解除。
- 现有 `safety status/resume` 扩展 `{app_id,runtime,pause_id}` 作用域。Runtime pause 只能由用户携带当前 pause id 显式 resume；runner、recovery 和 janitor 均不得自动解除。
- Worker 用 `start_new_session=True` 创建独立 process group；parent 持久化 PID/PGID、process start time、executable path/digest、worker nonce 和 heartbeat。
- OS lock FD 只由 parent 持有，明确设为 non-inheritable；否则 orphan worker 会让 takeover 永远无法取得 flock。Child/harness 通过 owner nonce、binding 和双 fencing token 验证 delegated capability，不再次获取同一 flock。缺少或不匹配 capability 的进程按外部调用处理并被锁阻断。

接管必须同时满足：

1. 新 runner 已取得 local 与 shared-runtime 两个 OS lock。
2. 旧 parent PID/start-time identity 不存活或已明确释放；旧 parent 仍活着时禁止接管，即使 lease 过期。
3. 新 runner 立即 CAS 写入更大的 local 与 shared-runtime fencing token，使 orphan child 的后续 guard 失败；不能先等待 lease 5 分钟。
4. Signal 前旧 worker 的 PID/PGID、start time、executable digest 和 nonce 全部匹配账本；不匹配则阻断且不杀进程。
5. 旧 worker process group 已被定向终止；接管者通过系统枚举证明该 identity 不再存活，只有原 parent 可 `waitpid` reap。
6. 旧 lease 记录已由 CAS takeover 或明确释放，且没有 stale capability 仍有效。
7. 完成第 13 节的恢复协议后才可启动新 worker。

仅依赖墙上时间、仅改 owner 字段或仅因 lease 过期直接 takeover 都不允许。

## 15. 故障分类与重试

Reason-code 表有独立 `reason_schema_version`。只有精确命中 allowlist 的 reason 可重试；`command_failed:<code>`、未知异常、空 reason 和未来未登记 reason 一律不可重试。

### 15.1 可重试 allowlist

在 `stage_mutation_intent` 之前可重试：

- `model_timeout`
- `vision_timeout`
- `app_launch_transient`
- `capture_transient`
- `prepare_message_page_transient`
- `exact_target_relocation_transient`
- `worker_timeout_before_mutation`

Mutation 开始后，只有 target-bound cleanup、empty-composer verification、negative-send verification 和 terminal audit 全部完成，原功能错误才可按同一 allowlist 重试。无法取得 negative-send evidence 时不允许重试。

Canary 不执行第二个功能 attempt；retryable 只决定错误分类和安全恢复，首 attempt 未成功即 Canary 阻断。Soak 每个 cycle 最多 3 个 attempt，重试等待固定为 30 秒、120 秒，且通过标准最多允许 1 个 retried cycle。重试必须新建 `attempt_id`；不得修改或复用旧 receipt。

`no_eligible_empty_composer` 是 scheduler-level inconclusive：写 selection-probe outcome，但不创建 cycle attempt、不进入成功率分母。每个 planned slot 最多延期扫描 3 次；仍无候选则以 `insufficient_eligible_targets` 阻断 qualification。

### 15.2 不可重试

- target、thread、payload、precondition、binding 或 fencing mismatch。
- pre-existing composer 被修改或清除。
- composer、cleanup 或 post-send 状态未知。
- question gate 或非普通聊天发生 staging。
- receipt、terminal audit、stage result、support coverage 或 hash chain 缺失/冲突。
- runtime scope、environment fingerprint 或 authorization 漂移。
- stale worker、并发 runner 或 support ownership 冲突。
- 用户或外部 UI 干预导致状态无法归因。
- 任意真实发送迹象。

不可重试故障将 test outcome 置为 `qualification_blocked`，并进入 finalization 流程。

## 16. 功能通过标准与统计解释

### 16.1 Canary

- 10 个 cycle 全部成功。
- 10 个 cycle 都必须首 attempt 成功；任何 retry 都使本次 Canary 不通过，即使 retry 后功能成功。
- Surface 分布严格为 8 个 message-list、2 个 current-thread。
- 每个 committed cycle 的唯一 attempt 都必须有一个 completed stage result、一个 qualification attempt outcome 和一个 receipt。
- 所有 attempt 的 safety violation 为 0。
- 所有 attempt 均有 terminal 或 recovery-terminal audit。
- Canary phase strict support bundle、chain validation 和敏感临时文件清理成功。
- Phase 结束时 worker/process-group、support session、lock capability 和临时 artifact orphan 数均为 0，encrypted SQLite `quick_check=ok`。

### 16.2 Soak

- 100 个计划 cycle 全部进入 committed terminal state。
- 80 个 message-list、20 个 current-thread，不允许模式替代。
- `first_attempt_successes >= 99`、`terminal_cycle_successes >= 99`、`retried_cycles <= 1`、`total_attempts <= 102`。
- 最多 1 个 committed functional-failure cycle；scheduler-level inconclusive 不计为 cycle，也不计成功率。
- 未发生 content mutation 的 final failure 必须有 qualification attempt outcome、零条 stage result，并证明最后 mutation phase 早于 `stage_mutation_intent`。
- 已发生 content mutation 的 final failure 必须有一条 failed stage result、target-bound cleanup、empty composer 和 verified negative-send outcome。
- Validator 检查所有 99 个相邻 `actual_start_ns` 间隔均不小于 `interval_ns`，并验证首尾跨度至少 8 小时。
- 所有 attempt 的 safety violation 为 0。
- Environment fingerprint 与 canary 完全一致。
- Canary/soak phase support bundles、qualification bundle、terminal manifest 和 offline validate 全部通过。
- Phase 结束时 worker/process-group、support session、lock capability 和临时 artifact orphan 数均为 0，encrypted SQLite `quick_check=ok`。

99/100 是本协议的工程门槛，不是“真实成功率至少 99%”的统计证明。99/100 的单侧 95% Clopper-Pearson 下界约为 95.34%；若要在零失败、独立同分布等前提下证明总体成功率至少 99%，至少需要约 299/299，且仍需论证样本代表性。本阶段不做该统计性声明。

## 17. 加密账本、Hash Chain 与 Manifest

### 17.1 逻辑路径

- `standalone_production/qualifications/<qualification_id>.json`
- `standalone_production/cycles/<phase>/<cycle_index>.json`
- `standalone_production/attempts/<attempt_id>.json`
- `standalone_production/attempt_outcomes/<attempt_id>.json`
- `standalone_production/receipts/<attempt_id>.json`
- `standalone_production/events.jsonl`

所有逻辑路径都由 dedicated `JsonStorage` 写入加密 SQLite，不创建明文 mirror。Receipt、outcome、cycle 和 event API 必须使用 insert-if-absent/append-only CAS 语义，不能继承普通 document upsert 的覆盖行为。

Certificate/bundle artifact 使用同目录临时文件、file+directory `fsync` 和 no-replace atomic rename；目标已存在时只接受完全相同 digest，内容不同立即阻断。

### 17.2 Hash chain

```text
event_hash = sha256(canonical_json({previous_hash, event_without_hash}))
```

Event digest 必须包含完整 qualification binding、local/runtime 两个 fencing token、event type、reason code、mutation phase 和脱敏 evidence digest。Manifest 保存 chain root。Hash chain 只检测损坏、遗漏和意外修改，不宣称抵御拥有本机代码和密钥的恶意管理员。

进入 hash chain 的 event 在创建时即只包含脱敏字段；原始文本与图像只进入 encrypted vault，不参与可导出的 canonical event object。

现有 strict support bundle 不承担 production event-chain 扩展。Canary 通过时先生成 immutable `canary_certificate.zip`，封装 Canary strict support bundle、Canary chain range、attempt digest index、predicate inputs 和 provisional canary manifest；它可离线验证，但明确不表示 qualification passed。

Finalization 先生成 immutable `qualification_evidence.zip`，内含：

- Canary 通过时生成的 immutable Canary certificate（未通过则写明确 absent reason），以及每个已启动 phase 的原始 strict support bundle、digest、support session id 和 chain range；`protocol_passed` 必须同时有 Canary 与 Soak，`qualification_blocked|qualification_expired` artifact 对未启动 phase 写明确的 `not_started` index entry。
- 原样 canonical production `events.jsonl`。
- 全部 attempt outcome/receipt digest index。
- 可重算的 target/tail/command certificate；只含 direction、geometry、hash 和 confidence，不含原文。
- Provisional manifest 和逐项 predicate 输入；terminal manifest 只在 purge 后生成并放入外层 qualification bundle。

Evidence archive 通过 provisional validate 后才允许 purge。Purge 完成后生成未发布的 terminal-manifest candidate，把它与 `qualification_evidence.zip` 封装为 `qualification_bundle.zip`，并在旁路 `qualification_bundle.sha256` 写 detached digest。Terminal manifest 绑定 evidence digest/content root，不自引用外层 ZIP digest。只有 final bundle validate 通过后，才把 bundle 中完全相同的 terminal manifest 原子发布到 output 根目录并映射用户终态。

`validate` 必须先核对 detached outer digest，再从 evidence archive/certificate 重算 predicate，不能信任输入里的 `verified=true`。它还必须证明 Canary chain root 是最终 event chain 的精确前缀，且 Canary certificate 的 config/environment digest 与 Soak 完全相同。输出分别报告 `artifact_valid` 和 `qualification_passed`。只保留 chain root 而不保留事件序列不满足离线复验要求。

因为原始截图在 finalization 中删除，offline validate 只能复算脱敏 certificate 的内部一致性，不能重新执行视觉识别或独立证明 UI 事实。`artifact_valid=true` 不等于原始 perception 绝对正确；在线 v2 evidence capture、置信度门槛和故障注入测试仍是协议可信度的一部分。

### 17.3 Manifest

脱敏 manifest 至少包含：

- schema/protocol/reason-code 版本。
- qualification id、终态和枚举 `claim_code`，不保存自由结论文本。
- 完整 environment fingerprint 与 config hash。
- Canary/soak 起止 wall time、monotonic duration 和 boot session id。
- 计划/实际 cycle、surface、成功、失败、重试和 safety violation 计数。
- Probe/attempt/provider latency 分布、model request/token usage、timeout 数、process/FD cleanup 计数和 SQLite integrity result；不记录 prompt/response 原文。
- 每项通过条件及其 evidence digest。
- event chain root 与 receipt index digest。
- Canary/soak phase bundle index、相对路径、digest、support session id、chain range，以及 qualification evidence digest/content root。
- sensitive purge result 和 finalization state。
- 明确的 `statistical_reliability_claim=false` 与 `live_send_qualified=false`。

`claim_code` 只能是 `CANARY_PASSED_SOAK_NOT_RUN`、`PROTOCOL_PASSED_PINNED_ENVIRONMENT`、`QUALIFICATION_BLOCKED` 或 `QUALIFICATION_EXPIRED`。Validator 根据状态机械生成用户文本；最终通过文本必须附 qualification id、config hash 和 manifest digest。Canary 文本必须包含 `soak not run; qualification not passed`。

## 18. Support Session 所有权

- Data doctor/migrate 只在 support session 前、dedicated data dir 上执行。
- Canary 和 soak 分别创建 support session。
- Start 使用 compare-and-swap：active pointer 必须为空，或已由同一 qualification/phase 拥有；其他 active session 立即阻断。
- Support session 记录 qualification owner，stop 也必须 CAS 匹配同一 owner，不能停止别人的 session。
- Parent 通过内部 command context 和 child 环境显式传递 `support_session_id`、`qualification_id` 以及 `attempt_id` 或 `probe_id`；command logger 不得只读取可变的全局 active pointer。
- 每个 selection probe 和 attempt 必须有连续、配对的 command start/finish coverage；中断必须有 explicit interrupted finish event。
- Phase 结束前必须 stop 恰好由本 phase 拥有的 session，并生成 strict bundle；bundle digest/session id/chain range 随后进入 qualification bundle index。
- Support session 活跃时不得运行 data migrate 或 data delete。

## 19. 隐私、Quarantine 与保留

- 用户可读输出不包含聊天文本、昵称、草稿、截图、剪贴板、完整 match id 或 API key。
- Target 只以 qualification-scoped salted hash 出现在摘要中，避免跨运行关联。
- `data/`、`vault/` 和敏感文件权限为目录 `0700`、文件 `0600`。
- Quarantine 必须由现有数据密钥加密后落盘；权限位不能替代静态加密。
- 明文截图/OCR/smoke JSON 只能存在于受控临时文件，提取 digest 后立即加密或销毁；phase 通过前不得残留。
- Child 环境固定 `TMPDIR`、Python bytecode/cache、SDK cache 和 log 路径到 qualification root；禁止 debug HTTP body logging。测试使用高熵 sentinel 扫描 stdout、stderr、manifest、ZIP entries、root 和已知 cache path。
- Canary 通过后的 24 小时只约束 `canary_passed` 等待态。Soak 在期限内启动时原子切换为 active-soak retention；不会在 8 小时运行中沿用原等待态 deadline。
- Active runner 正常退出后立即 finalization；runner 崩溃且没有未知 GUI mutation 时，recovery deadline 为最后 heartbeat 后 1 小时，之后在下一次 mutating Gate 命令中转为 `qualification_blocked` 并开始 finalization。
- 如果存在未知 target/composer/send 状态，安全恢复优先于定时删除：保留最小 encrypted recovery record 并维持 shared-runtime safety pause，直到用户完成明确处置。此例外不得宣称 24 小时自动删除。
- 本设计不安装 launchd daemon，因此不能声称无进程运行时仍会在墙上时间点自动删除。每次 `canary`、`soak`、`resume`、`finalize` 启动时运行 root janitor；`status` 保持只读并报告过期/待清理状态。
- Test outcome 确定后的 finalization 顺序固定为：停止 owned support session；生成 phase strict bundles；组装 immutable qualification evidence archive 与 provisional manifest；离线验证 provisional evidence；删除并验证 `data/`、`work/`、`vault/`；生成未发布的 terminal-manifest candidate；封装 final qualification bundle 并写 detached digest；离线 validate final bundle；原子发布同一 terminal manifest；最后映射用户终态。
- 任一步失败进入可恢复的 `finalization_failed`，不得提前发布 `protocol_passed`。`finalize` 从最后已验证 checkpoint 幂等继续。
- Canary 等待过期、Soak 完成或 `qualification_blocked` 后均使用上述顺序；output 中只保留脱敏 terminal manifest、qualification bundle 和 phase strict bundles。
- 无安全恢复依赖时，finalization failure 或用户明确要求诊断的 encrypted quarantine 保留策略上限为 24 小时，并由 root janitor 在下一次 mutating Gate invocation 清理。
- Terminal `status` 只依赖保留下来的脱敏 manifest；不得为了 status 保留聊天状态。
- Authorization 输入文件不归 Gate 所有，不修改、不复制进输出，也不由 Gate 删除。

## 20. 故障注入与自动化测试

自动化测试主要使用 fake clock、fake process port、fixture evidence 和 fake GUI mutation guard；另有不打开 App 的真实 macOS subprocess/FD/PGID integration test。不对真实 App 注入破坏性动作。测试先写失败断言，再实现生产代码。

必须覆盖：

- Alpha 在全新 encrypted-only data dir 中读取 stage result，且不存在明文 `audit/stage_results.jsonl`。
- Alpha 输出 encrypted backend/logical stream，storage/decryption failure 是结构化 blocked reason，不返回伪明文 path。
- 从 source data dir 只复制 allowlisted user-model records，autonomous readiness 通过；缺失 snapshot、digest 漂移或复制任何 match/chat/session 数据都阻断。
- `stage_consumed_after_verified_cleanup` 只在 cleanup+negative-send 后释放 sticky/active request，并允许下一 cycle 生成新 binding；提前调用和普通 stage 调用都阻断。
- 旧草稿 baseline 非空时，在 guarded AX set/clear 前阻断，原文本保持不变。
- 模型调用期间 target/composer 改变时，`pre_stage_revalidated` 失败且没有 AX write。
- Guarded `set-if-empty`/`clear-if-exact` 的 compare failure 不修改文本；qualification command audit 出现 clipboard/paste 即阻断。
- Canonical payload hash 与 composer text hash 分离，多-bubble/换行/Unicode normalization 均可精确清理。
- 模拟“发送后输入框为空”，确认没有 fresh same-target tail 反证时 Gate 仍阻断。
- Conversation-tail v2 的新增 outbound、composer text outbound、只有 inbound 增量、viewport mismatch、缺少 geometry 和 ambiguous tail 分类。
- Qualification binding 在 session/work item/audit/support/receipt 的完整透传。
- 不同 attempt 相同 payload 不被错误 dedup；insert-if-absent 的相同 digest 幂等、不同 digest 阻断；append-only event 不能覆盖。
- 每个 attempt 恰好一个 outcome/receipt；pre-mutation 零 stage result，post-mutation 恰好一条；cycle 的全部 attempt IDs 与唯一 final attempt CAS。
- Child 正常退出但 receipt/outcome/terminal 缺失时阻断；stage result cardinality 按 mutation phase 验证。
- 每个 mutation phase 崩溃后的 worker identity verification、target-bound cleanup 和 recovery terminal。
- 真实 macOS subprocess 测试覆盖 lock FD 不继承、parent death 后 flock 释放、delegated capability、process start time/nonce、原 parent `waitpid`、接管者只验证消失，以及 PID/PGID 重用时绝不 signal。
- Composer 为 exact canonical composer text、已为空、其他文本和未知状态的四种恢复路径。
- `stage_mutation_completed` 缺失或 input-sentinel coverage 有缺口时，即使文本相等也不得自动 clear。
- `attempt_terminal_committed`、support finish、chain append、`cycle_commit_intent` 和 final cycle CAS 各边界崩溃后幂等提交，不重复 staging。
- Canary 在返回 id 前崩溃时，root status 可发现 qualification；resume 不切 phase、不绕过 recovery，并在 authorization/environment 漂移时阻断。
- Canary 9/10、任一 retry、soak 98/100、first-attempt 98/100、两个 retried cycle、相邻间隔不足、80/20 配额不符均失败。
- 全部 cycle 依赖 retry 的反例不得通过；no-eligible candidate 只延期且超过 3 次后阻断，不进入分母。
- Current-thread predecessor 丢失、Canary 直接阻断、Soak 精确重定位/defer、最后一组无后续 message-list 和最终配额保持。
- Local/runtime CAS renew、stale fencing、跨 root/qualification 竞争、普通 harness 竞争、lease 过期但旧 worker 存活和合法 takeover。
- Phase-end orphan worker/process-group/support/lock/temp detection 与 encrypted SQLite `quick_check` failure。
- Dirty checkout、artifact digest、user-model snapshot、credential HMAC、依赖、Python、OS/display/permissions、TaShuo bundle、provider response model/deployment 和授权漂移。
- Support start/stop 竞争、错误 owner、缺失 start/finish coverage。
- 精确 retry allowlist、未知 reason 和 `command_failed:<code>` 不可重试。
- Selection probe/attempt hard timeout、pre-mutation timeout 可重试和 post-mutation timeout 必须先恢复的分类。
- Hash chain 缺失/篡改、重复 cycle、全部相邻 monotonic 间隔、时钟回退和 boot session 改变。
- Dedicated directory 拒绝主数据目录和符号链接逃逸。
- Encrypted quarantine、等待态 24 小时、active-soak deadline 切换、unknown-mutation retention、root janitor 和 purge 后 status/validate。
- Provisional evidence、purge、bundle seal、final validate 和 terminal manifest publish 每个边界的 `finalization_failed` 幂等恢复。
- Qualification bundle 缺任一 phase support bundle、chain range、receipt index 或可重算 certificate 时 `artifact_valid=false`；validator 不信任预填 `verified`。
- Child 越界 TMP/cache/log、敏感 sentinel 出现在 stdout/stderr/manifest/ZIP entry 或 known cache 时阻断。
- `claim_code` 机械派生；Canary 明确未完成资格，manifest 禁止一般化 production/SLA/live-send 结论。

回归层级：

1. 纯函数、schema、状态机、scheduler 和 reason-code 单元测试。
2. Fixture 集成、故障注入、恢复、support ownership 和离线 validate。
3. 现有 standalone、managed、operator、storage/security 和 production-data 回归测试。
4. Release doctor、data doctor、wheel smoke 和 clean-artifact 验证。
5. 10 轮真实 GUI canary。
6. 用户检查 canary manifest 后，单独启动 100 轮、至少 8 小时 soak。

真实 canary/soak 不主动注入发送、目标错配或覆盖用户草稿；这些破坏性场景只在 fake GUI 层测试。

## 21. 完成定义

实现可以交付给用户运行 canary，必须满足：

- 第 3 节所有 preflight blocker 已修复并有回归测试。
- 新增自动化测试全部通过。
- 现有 full suite 无回归。
- Release doctor、data doctor、wheel smoke 和 clean environment fingerprint 通过。
- 离线 validate 能拒绝缺失、重复、未绑定或被篡改的证据。

10 轮 canary 通过后只能声明：

```text
canary passed for the pinned environment; soak not run; qualification not passed
```

最终协议完成还必须满足：

- 用户在 24 小时内显式启动 soak。
- 100 轮 soak 跨越至少 8 小时。
- 功能标准、安全标准、证据标准、隔离清理和环境一致性全部通过。
- Final manifest、两个 phase strict support bundles、qualification bundle 和 offline validate 通过。

最终只允许由 `claim_code=PROTOCOL_PASSED_PINNED_ENVIRONMENT` 生成第 1 节规定的 pinned-environment protocol 结论，并附 qualification id、config hash 和 manifest digest。任何一般化的 `production ready`、`99% reliable` 或 `live-send qualified` 声明都不成立。
