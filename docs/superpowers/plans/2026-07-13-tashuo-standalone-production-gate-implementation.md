# TaShuo Standalone Production Gate Implementation Plan

> Execute this plan test-first. The design contract in
> `docs/superpowers/specs/2026-07-12-tashuo-standalone-production-gate-design.md`
> is authoritative when this plan is less specific.

**Goal:** Implement the complete stage-only TaShuo `mac-ios-app` production
qualification protocol: fixed ten-cycle canary, separately authorized
100-cycle/eight-hour soak, crash-safe encrypted evidence, shared runtime
fencing, target-bound cleanup, independent negative-send verification,
finalization, and offline validation.

**Non-goals:** No live send, no other app/runtime, no fixture result counted as
real GUI evidence, no use of the primary Dating Booster data directory as a
qualification runtime store.

## Delivery Rules

- Write a failing test before each behavioral change.
- Keep GUI-independent contract, storage, scheduling, and validation logic pure
  and injectable.
- Store all active qualification state through `JsonStorage`; do not create
  plaintext mirrors for logical records.
- Treat stdout and process exit status as diagnostics only. Durable receipts in
  the encrypted ledger are the commit source of truth.
- Do not open TaShuo until all automatic tests and non-GUI preflight gates pass.
- Do not start soak automatically. It remains a separate explicit user command.

## Task 1: Repair the Alpha encrypted evidence reader

**Files:**

- Modify `dating_boost/apps/tashuo/standalone_alpha_gate.py`.
- Add or extend `tests/test_tashuo_standalone_alpha_gate.py`.

**Behavior:**

- Read `audit/stage_results.jsonl` through `JsonStorage.read_jsonl`.
- Report `audit_stream=audit/stage_results.jsonl` and
  `storage_backend=encrypted_sqlite` separately.
- Convert storage/key/decryption failures into a structured blocked result.
- Prove an encrypted-only store passes without a plaintext mirror.

## Task 2: Implement the production contract and scheduler

**Files:**

- Add `dating_boost/apps/tashuo/standalone_production_contract.py`.
- Add `tests/test_tashuo_standalone_production_contract.py`.

**Behavior:**

- Define protocol/schema/reason versions, immutable thresholds and timeouts.
- Normalize and validate authorization, environment and protocol config.
- Implement outcome/finalization state transitions and terminal mapping.
- Implement exact retry allowlist and mutation-aware retry classification.
- Generate fixed canary and soak planned-slot schedules.
- Enforce predecessor, defer, 80/20 quota, no catch-up and monotonic interval
  predicates.
- Derive claim codes and user text mechanically.

## Task 3: Implement a crash-safe encrypted production ledger

**Files:**

- Add `dating_boost/apps/tashuo/standalone_production_ledger.py`.
- Add `tests/test_tashuo_standalone_production_ledger.py`.

**Behavior:**

- Provide insert-if-absent records with same-digest replay and conflict reject.
- Provide versioned compare-and-swap for mutable qualification/cycle state.
- Append immutable events transactionally with sequence and hash-chain linkage.
- Store qualification, cycle, attempt, outcome and receipt logical records.
- Enforce complete qualification bindings and unique final attempt selection.
- Validate attempt/stage-result cardinality, orphan attempts and event chains.
- Expose SQLite quick-check without leaking the database key or raw evidence.

## Task 4: Implement local and shared runtime locks

**Files:**

- Add `dating_boost/core/gui_runtime_lock.py`.
- Add `dating_boost/apps/tashuo/standalone_production_lock.py`.
- Extend `dating_boost/core/safety.py` and relevant CLI handlers.
- Add `tests/test_gui_runtime_lock.py`.
- Add `tests/test_tashuo_standalone_production_lock.py`.

**Behavior:**

- Hold non-inheritable OS file locks for qualification and shared TaShuo runtime.
- Persist CAS leases, monotonic fencing tokens, owner nonce, parent identity and
  heartbeat metadata with 0700/0600 permissions.
- Validate delegated child capabilities before every mutation/evidence commit.
- Reject stale heartbeat, dead parent, stale token and competing data-dir calls.
- Implement identity-safe takeover and worker PID/PGID/start-time/executable/
  nonce checks; never signal on identity mismatch.
- Add runtime-scoped safety pause/status/resume requiring the current pause id.
- Wire the shared runtime guard into every TaShuo `mac-ios-app` GUI entry path.

## Task 5: Implement dedicated-root ownership and user-model import

**Files:**

- Add root/snapshot functions to
  `dating_boost/apps/tashuo/standalone_production_artifacts.py`.
- Extend user readiness helpers only where required.
- Add `tests/test_tashuo_standalone_production_artifacts.py`.

**Behavior:**

- Create an owned empty qualification root and reject existing data stores,
  primary data directories, symlink escapes and cross-qualification reuse.
- Import only the allowlisted user-model records through `JsonStorage`.
- Sanitize memory projection and force `thread_disclosures=[]`.
- Persist only the canonical snapshot digest; never persist the source path.
- Encrypt canonical authorization in the dedicated store and verify external
  authorization digest/revocation before every probe/attempt and resume.
- Build a minimal child environment rooted under work/vault, including TMP and
  cache paths, and reject out-of-root writes or sensitive output.

## Task 6: Add guarded AX composer primitives

**Files:**

- Modify `dating_boost/apps/tashuo/send_input_ax.py`.
- Modify `dating_boost/apps/tashuo/stage_runtime.py`.
- Modify `dating_boost/apps/tashuo/standalone.py`.
- Add or extend TaShuo AX/stage runtime tests.

**Behavior:**

- Implement single-script guarded `set-if-empty` and `clear-if-exact`.
- Qualification staging never reads, writes or restores the system clipboard.
- Never clear a non-empty baseline or a composer that differs byte-for-byte from
  the persisted observed AX string.
- Separate canonical payload hash from normalized planned composer hash and exact
  observed composer hash; normalize NFC and line endings only where specified.
- Require a fresh pre-stage target/tail/composer revalidation no older than two
  seconds and continuous no-user-input sentinel coverage.
- Audit and block any qualification command containing clipboard, paste,
  send-click, Enter-send or live-send operations.

## Task 7: Implement evidence-only conversation-tail v2

**Files:**

- Add evidence capture interfaces to the TaShuo perception layer.
- Add `dating_boost/apps/tashuo/standalone_production_evidence.py`.
- Add `tests/test_tashuo_standalone_production_evidence.py`.

**Behavior:**

- Certify ordered bubbles with direction, normalized exact-text hash, geometry,
  anchor/order, viewport/capture/observation ids and confidence.
- Salt target identities per qualification and export no chat text or nickname.
- Evaluate same-target fresh post-cleanup tails independently from executor
  declarations.
- Accept an unchanged tail or inbound-only suffix; reject outbound, payload
  outbound, ambiguous order/direction, viewport mismatch, missing geometry,
  stale/reused capture and ordinary non-v2 observations.
- Include prohibited-command audit predicates in negative-send verification.

## Task 8: Implement attempt binding, checkpoints, cleanup and consumption

**Files:**

- Add `dating_boost/apps/tashuo/standalone_production_attempt.py`.
- Modify standalone session/operator/action audit schemas as needed.
- Add `tests/test_tashuo_standalone_production_attempt.py`.

**Behavior:**

- Carry the complete binding through session, work item, action request, target,
  payload, stage result, support event, receipt and terminal audit.
- Persist every mutation checkpoint and enforce the fixed phase order.
- Record exactly one outcome and receipt; derive required stage-result
  cardinality from mutation phase.
- Implement target-bound clear-if-exact, empty verification and fresh negative
  send verification.
- Implement qualification-only
  `stage_consumed_after_verified_cleanup`; release sticky work/active request only
  after verified cleanup and negative-send, preserving predecessor binding.
- Implement recovery decisions for all mutation phases and all four composer
  states, including shared-runtime pause for unknown state.

## Task 9: Add support-session ownership and command coverage

**Files:**

- Modify `dating_boost/core/support.py`.
- Modify command-audit context propagation paths.
- Add or extend support tests.

**Behavior:**

- CAS start/stop against qualification and phase owner.
- Reject competing or wrong-owner support sessions.
- Propagate immutable support/qualification/attempt-or-probe context rather than
  relying on the mutable active pointer.
- Require paired command start/finish or explicit interrupted finish for every
  probe and attempt.

## Task 10: Implement the attempt worker and production runner

**Files:**

- Add `dating_boost/apps/tashuo/standalone_production_runner.py`.
- Add worker entry support if a separate module is clearer.
- Add `tests/test_tashuo_standalone_production_runner.py`.

**Behavior:**

- Run release/skill/data/capabilities/runtime/readiness/provider/environment
  preflight before any app adapter creation.
- Start phase-owned support only after migration and before visible observation.
- Execute selection probes separately from attempts and never count inconclusive
  probes in success denominators.
- Launch one worker process group at a time behind a registered parent barrier.
- Execute the existing standalone/operator-created stage request; never fabricate
  an executor-internal send request.
- Enforce hard probe/attempt timeouts, mutation-aware recovery, fixed retry waits,
  canary no-retry and soak retry limits.
- Commit attempt and cycle state via CAS checkpoints without duplicate staging.
- Implement read-only status, active-phase-only resume and non-GUI finalize.
- Recheck authorization/provider/environment/fencing/support before each action.

## Task 11: Implement certificates, finalization and offline validation

**Files:**

- Complete `dating_boost/apps/tashuo/standalone_production_artifacts.py`.
- Complete `dating_boost/apps/tashuo/standalone_production_evidence.py`.
- Add artifact/finalization/validator fault-injection tests.

**Behavior:**

- Encrypt raw evidence and quarantine; leave no plaintext mirrors.
- Generate immutable no-replace Canary certificate with support bundle, chain
  range, attempt index and recomputable predicate inputs.
- Assemble provisional evidence, validate it, purge sensitive data, seal a final
  bundle, verify detached digest, validate final content, then publish the exact
  terminal manifest atomically.
- Make every finalization checkpoint idempotently resumable and fail closed.
- Offline validation recomputes event chain, counts, bindings, interval/quota,
  receipt indexes, phase bundles, Canary prefix and environment/config equality;
  it never trusts a stored `verified=true` flag.
- Implement retention states and mutating-command root janitor while keeping
  status read-only.

## Task 12: Add the thin production CLI

**Files:**

- Add `scripts/tashuo_mac_ios_standalone_production_gate.py`.
- Add CLI tests.
- Update capability/release metadata and documentation where required.

**Behavior:**

- Expose exactly `canary`, `soak`, `status`, `resume`, `finalize`, `validate`.
- Keep 10/100/eight-hour/timeout/retry constants out of user-settable CLI flags.
- Return structured JSON with reason codes and exact next command.
- Permit root-level status discovery without target/chat information.
- Require explicit authorization again for soak and resume.

## Task 13: Fault injection and integration regression

**Files:**

- Add focused test modules for every Section 20 predicate.
- Extend existing standalone, managed, operator, storage, safety, support and
  release tests.

**Behavior:**

- Cover every mutation phase crash and every commit/finalization boundary.
- Cover macOS FD non-inheritance, flock release, delegated capabilities,
  process-group identity and PID/PGID reuse without opening TaShuo.
- Cover all statistical/quota/interval/retry counterexamples.
- Cover sensitive sentinel scans across stdout/stderr/root/cache/archives.
- Verify direct harness, standalone, host-loop and managed-session all compete on
  the same runtime lock and honor runtime safety pause.

## Task 14: Full verification and release readiness

Run, in order:

1. Focused production-gate tests and all affected existing tests.
2. Full Python 3.11 and supported-current Python suites.
3. Ruff and mypy.
4. Release doctor, skill doctor, data doctor/migrate on a fresh dedicated store,
   capabilities check and clean environment fingerprint.
5. Wheel build/install and host-native agent smoke.
6. Offline validator corruption fixtures.

Only after every automatic and non-GUI gate is green may the real ten-cycle
Canary command be offered/run. The 100-cycle soak remains a later, separately
invoked user action after inspection of the Canary certificate.
