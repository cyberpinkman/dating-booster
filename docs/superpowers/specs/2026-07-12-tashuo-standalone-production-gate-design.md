# TaShuo Standalone Production Qualification Gate Design

## 1. 目标

为 Dating Booster 的独立 Agent 增加一套生产资格测试门禁，范围严格限定为：

- App：她说 / TaShuo。
- Runtime：`mac-ios-app`。
- Agent：`standalone-session`。
- Send mode：`stage`。
- Observation source：真实 GUI。
- Model/vision：现有 MiniMax/OpenAI-compatible backend contract。
- Target scope：她说消息页中任意可见的普通聊天；非普通聊天 surface 只能跳过。

门禁先运行 10 轮真实 GUI canary。Canary 通过后，由用户显式启动 100 轮、至少 8 小时的 soak。只有 soak 达到本设计的全部通过标准，才能声明 `tashuo standalone stage-only production qualified`。

## 2. 非目标

本阶段不做以下工作：

- 不扩展 Tinder、Bumble 或微信的 standalone live GUI provider。
- 不启用 `StandaloneManagedGuiSendExecutor` 的真实发送。
- 不执行 like、pass、question gate、profile edit、payment 或联系方式交换。
- 不改变现有 TaShuo standalone Alpha gate 的通过标准。
- 不把 2026-06-30 的 20/20 Alpha 记录等同于生产资格。
- 不把 fixture-only 测试计入真实 GUI canary 或 soak 轮数。

## 3. 当前基线

当前实现已经具备：

- `standalone-session start/tick/status/stop`。
- TaShuo `mac-ios-app` 消息列表观察、会话观察、草稿生成、staging、目标验证和输入框清理。
- 加密本地状态、managed-session/operator 协议、support session 和严格脱敏 bundle。
- 2026-06-30 的 20/20 真实 Alpha 记录，所有轮次均为 stage-only，且目标、文本和最终空输入框验证通过。
- 115 个 standalone 专项自动化测试。

Production Gate 在此基线上增加持续时间、恢复、幂等、并发排他、故障分类、证据链和离线复验。

## 4. 选定方案

新增独立 Production Qualification Gate，作为现有 standalone smoke 和 Alpha evaluator 的上层编排器。

不直接扩展已经较大的 `stage_alpha_release_gate.py`，也不使用 shell 脚本拼接状态。Production Gate 拥有独立状态机和证据合同，并复用已经验证过的底层动作。

### 4.1 文件边界

- `dating_boost/apps/tashuo/standalone_production_contract.py`
  - 配置规范化、配置哈希、状态转换、错误分类和通过条件。
- `dating_boost/apps/tashuo/standalone_production_ledger.py`
  - 加密账本、事件流、运行锁和恢复决策。
- `dating_boost/apps/tashuo/standalone_production_evidence.py`
  - 每轮摘要、脱敏、hash chain、manifest、bundle 和离线验证。
- `dating_boost/apps/tashuo/standalone_production_runner.py`
  - Canary/soak 编排、调度、子进程端口、重试、清理和阶段收尾。
- `scripts/tashuo_mac_ios_standalone_production_gate.py`
  - 薄 CLI，提供 `canary`、`soak`、`status`、`validate`。

测试文件按同一职责拆分，避免重新形成单个超大 gate 文件。

## 5. 用户接口

### 5.1 Canary

```bash
python3 scripts/tashuo_mac_ios_standalone_production_gate.py canary \
  --data-dir .local/dating-boost \
  --work-dir .local/dating-boost-tashuo-production \
  --authorization auth.json \
  --json
```

Canary 固定为 10 个合格周期，不接受用户降低轮数。通过后返回：

- `qualification_id`
- `config_hash`
- `canary_chain_root`
- `canary_accept_token`
- `next_command`

`canary_accept_token` 是配置哈希、qualification id 和 canary chain root 的确定性绑定。它用于防止误用旧证据，不作为对抗本机恶意用户的安全秘密。

Token 计算固定为：

```text
sha256("tashuo-standalone-soak\0" + qualification_id + "\0" + config_hash + "\0" + canary_chain_root)
```

### 5.2 Soak

```bash
python3 scripts/tashuo_mac_ios_standalone_production_gate.py soak \
  --data-dir .local/dating-boost \
  --work-dir .local/dating-boost-tashuo-production \
  --qualification-id <qualification_id> \
  --accept-canary <canary_accept_token> \
  --json
```

Soak 固定为 100 个计划周期和至少 8 小时。不能通过参数缩短生产门禁。测试代码可以通过注入 fake clock 使用较短时间，但生产 CLI 不暴露该能力。

### 5.3 Status 与 Validate

```bash
python3 scripts/tashuo_mac_ios_standalone_production_gate.py status \
  --data-dir .local/dating-boost \
  --qualification-id <qualification_id> \
  --json

python3 scripts/tashuo_mac_ios_standalone_production_gate.py validate \
  --manifest .local/dating-boost-tashuo-production/<qualification_id>/production_manifest.json \
  --json
```

`status` 读取加密账本。`validate` 不打开 App、不调用模型、不读取剪贴板，完全离线复验脱敏证据。

## 6. 状态机

资格测试状态固定为：

```text
created
  -> canary_running
  -> canary_passed
  -> soak_running
  -> soak_passed

任意非终态 -> blocked
```

只允许以下转换：

- `created -> canary_running`
- `canary_running -> canary_passed | blocked`
- `canary_passed -> soak_running | blocked`
- `soak_running -> soak_running | soak_passed | blocked`

`blocked` 和 `soak_passed` 是终态。不得把 blocked 账本直接改回运行态；必须创建新的 `qualification_id`。

## 7. 周期与调度

### 7.1 Canary 分布

Canary 固定为 10 个周期：

- 周期 3、8 使用 `current-thread`。
- 其余 8 个周期使用 `message-list`。
- `current-thread` 必须紧跟在已成功定位普通聊天的周期之后。

Canary 必须 10/10 成功。重试不会增加合格周期数。

### 7.2 Soak 分布

Soak 固定为 100 个周期：

- 每第 5 个周期使用 `current-thread`，共 20 个。
- 其余 80 个使用 `message-list`。
- 周期串行执行，任何时刻最多有一个真实 GUI worker。

计划开始时间为：

```text
target_start(i) = soak_started_at + (i - 1) * 8h / 99
```

最后一个周期不能早于第一个周期开始后 8 小时。若前一周期延迟，后续周期按实际完成时间顺延，不并发追赶。

## 8. 周期提交与崩溃恢复

每个周期采用两阶段证据提交：

```text
planned -> running -> evidence_committed
```

账本在启动子进程前写入 `running`，并包含唯一 `attempt_id`。子进程完成后，runner 必须先验证 smoke/Alpha 证据，再写入 `evidence_committed`。

若进程恢复时发现 `running`：

1. 先调用 TaShuo `clear-message-input`。
2. 必须验证输入框字符数为 0。
3. 检查该 attempt 的现有证据。
4. 证据完整且所有安全条件通过时，幂等提交原 attempt。
5. 证据不完整时标记 `abandoned`，创建新的 attempt。
6. 输入框无法确认为空时，整个 qualification 进入 `blocked`。

已经 `evidence_committed` 的周期不能再次 staging。恢复时只能重新验证摘要和 hash chain。

## 9. 并发与配置锁定

Production Gate 使用现有加密 SQLite store 和进程级文件锁实现双重排他：

- 同一 data-dir 同时只允许一个 TaShuo Production Gate。
- 锁记录 owner、pid、qualification id、启动时间和租约。
- 锁租约为 5 分钟，runner 每 30 秒续约。
- 过期锁只能在完成输入框清理和中断周期恢复后接管。

配置在 `created` 时规范化并计算 SHA-256：

- `app_id=tashuo`
- `runtime=mac-ios-app`
- `send_mode=stage`
- `managed_gui_send=false`
- backend/vision backend 类型、模型和 base URL
- API key 的环境变量名，不包含 key 值
- canary/soak 固定阈值
- authorization 内容哈希

恢复时配置哈希必须相同。禁止中途更换 runtime、模型、授权或阈值。

## 10. 安全不变量

以下条件对所有 attempt 零容忍：

- `live_send_executed` 必须为 `false`。
- 命令执行记录中不得出现直接 `send-message` 或 `--managed-gui-send`。
- `send_mode` 必须为 `stage`，`managed_gui_send` 必须为 `false`。
- App/runtime 必须为 `tashuo/mac-ios-app`。
- action request、target match、payload hash、precondition hash 和 observation id 必须与当前 work item 匹配。
- 目标验证状态必须为 `ok`。
- staged exact-text verification 必须为 `verified`。
- 成功、失败、中断和重试之前的最终输入框都必须验证为空。
- question gate、推荐页、付费页和非普通聊天不得 staging。
- safety pause、runtime mismatch、明文 managed-state 残留或缺失证据立即阻断。

字段中出现未来可能使用的 send-action 描述不等于发送证据。门禁只根据已执行命令、post-action evidence 和 `live_send_executed` 判断是否发生发送。

## 11. 功能通过标准

### 11.1 Canary

- 10 个周期全部成功。
- 每个周期可以有 1 次初始 attempt 和最多 2 次可重试 attempt。
- 所有 attempt 均满足安全不变量。

### 11.2 Soak

- 100 个计划周期全部进入终态。
- 至少 99 个周期成功。
- 最多 1 个功能性失败。
- 功能性失败也必须有 `final_input_empty=true`。
- 首轮到末轮开始时间跨度至少 8 小时。
- 所有 attempt 的安全违规数为 0。

只有同时满足上述条件，状态才能转为 `soak_passed`。

## 12. 故障分类与重试

### 12.1 可重试

- 模型或视觉 backend 超时。
- App 临时启动失败。
- 临时截图、观察或 prepare-message-page 失败。
- 可确认没有 staging、且输入框为空的短暂无结果。

每周期最多 3 个 attempt。重试延迟固定为 30 秒、120 秒。每次重试前必须重新清空输入框、重新打开消息页并重新定位目标。

### 12.2 不可重试

- 目标或线程身份错配。
- staged text、payload hash 或 work-item binding 错配。
- 输入框状态未知或清理失败。
- question gate 或非普通聊天上发生 staging。
- 证据缺失、摘要不一致、hash chain 损坏。
- runtime scope 漂移。
- 任何真实发送迹象。

不可重试故障立即把整个 qualification 置为 `blocked`。

## 13. 证据合同

### 13.1 加密账本

逻辑路径：

- `standalone_production/qualifications/<qualification_id>.json`
- `standalone_production/events.jsonl`

由 `JsonStorage` 写入现有加密 SQLite，不创建明文 mirror。

账本至少记录：

- qualification id、状态和 config hash
- canary/soak 起止时间
- 当前周期和 attempt
- 周期结果摘要
- retry/terminal error 分类
- support session id
- 前一事件 hash 和当前事件 hash

### 13.2 Hash chain

每个脱敏事件按以下方式计算：

```text
event_hash = sha256(canonical_json({previous_hash, event_without_hash}))
```

Manifest 保存 chain root。Hash chain 用于检测损坏、遗漏和意外修改，不宣称可以抵御拥有本机代码和密钥的恶意管理员。

### 13.3 最终 Manifest

最终 manifest 固定包含：

- schema version
- qualification id 和 phase
- git commit、工具版本和 Python 版本
- config hash
- 起止时间、计划/实际持续时间
- 成功、失败、重试和安全违规数量
- surface 分布
- canary/soak 通过条件逐项结果
- event chain root
- strict support bundle 路径与摘要

## 14. 隐私与保留

- 用户可读输出不得包含聊天文本、可见昵称、草稿、截图、剪贴板或完整 match id。
- 目标只以稳定哈希出现在 Production Gate 汇总中。
- 成功周期完成证据提取后，删除原始截图和未脱敏 smoke JSON，仅保留脱敏摘要和文件哈希。
- 首个失败周期的原始证据保存在权限为 `0700` 的本地 quarantine 目录，默认最长保留 24 小时。
- Quarantine 不进入 strict bundle；导出 support bundle 后可以立即清理。
- 成功周期的原始证据无法完成清理时，该 phase 不得进入通过状态。
- Gate 启动和 `status` 会清理已超过 24 小时的 quarantine。
- Production Gate 不读取或保存 API key 值，只保存环境变量名和 provider 类型。

## 15. Support Session 规则

- data doctor/migrate 在 support session 开始前完成。
- Canary 和 soak 分别使用独立 support session。
- 进程恢复时复用账本中的 active support session；终态时必须 stop。
- support session 活跃期间不得运行 data migrate 或 data delete。
- strict support bundle 缺失时，canary 或 soak 不得通过。

## 16. 故障注入与自动化测试

自动化测试使用 fake clock、fake subprocess port 和 fixture evidence，不对真实 App 注入破坏性动作。

必须覆盖：

- 合法状态转换和非法状态转换。
- Canary 9/10、soak 98/100、持续时间不足 8 小时均失败。
- 模型超时、App 启动失败和重试耗尽。
- staged text、target binding 和 runtime 错配。
- 输入框清理失败。
- `running` 阶段崩溃后恢复。
- evidence 写入后、ledger 提交前崩溃后的幂等提交。
- 重复周期和重复 attempt。
- config hash 变化。
- 并发 gate 和过期锁接管。
- 损坏 manifest、缺失事件和 hash chain 篡改。
- 时钟回退。
- live-send 命令或 evidence 注入。
- 成功证据清理和失败 quarantine 保留策略。

测试必须先写失败断言，再实现生产代码。

## 17. 验证层级

1. 纯函数与状态机单元测试。
2. Fixture 集成、故障注入、恢复和离线 validate。
3. 现有 standalone/managed/operator/production-data 回归测试。
4. 10 轮真实 GUI canary。
5. 用户确认 canary 结果后，单独启动 100 轮、至少 8 小时 soak。

真实 canary 不主动注入目标错配、输入框残留或发送动作；这些故障只在自动化层验证。

## 18. 完成定义

实现阶段完成必须满足：

- 新增自动化测试全部通过。
- 现有 full suite 无回归。
- release doctor、data doctor 和 wheel smoke 通过。
- 10 轮真实 canary 为 10/10，安全违规为 0。
- Canary strict bundle 和离线 validate 通过。

此时只能声明 `production gate ready; canary passed`。

生产资格完成必须额外满足：

- 用户显式启动 soak。
- 100 轮 soak 跨越至少 8 小时。
- 成功率至少 99%，安全违规为 0。
- 最终 manifest、strict bundle 和离线 validate 全部通过。

只有此时才能声明 `tashuo standalone stage-only production qualified`。
