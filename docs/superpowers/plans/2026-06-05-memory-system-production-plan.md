# Production Memory System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the current observation-indexed memory surface into a production-grade, event-sourced memory system tuned for dating-agent workflows: identity safety, provenance, conflict handling, time-aware facts, feedback learning, and context-budgeted retrieval.

**Architecture:** Keep raw observations as immutable evidence, write explicit memory events, and derive materialized projections for match profile, conversation memory, commitments, feedback preferences, and context packs. Do not make embeddings the source of truth; use deterministic reducers first, then add optional semantic retrieval only for hook recall after structured memory is reliable.

**Tech Stack:** Python dataclasses, existing `JsonStorage`, optional existing SQLite mirror, pytest/unittest test suite, existing CLI command patterns in `dating_boost/cli.py`.

---

## Current Baseline

The current memory system is mostly:

- `memory ingest-observation`: persists `AppObservation`, resolves match identity, updates `matches/index.json`.
- `memory get-match`: returns only the match identity/index record.
- `context build` / `draft`: derives match profile and conversation memory from the latest observation.
- `JsonMemoryRepository`: persists user profile and feedback events.
- `PlannerRepository`: persists goal/strategy state separately.

This is not enough for production dating-agent memory because latest-observation context loses older verified facts, commitments, stale hooks, user corrections, feedback learning, and conflict history.

## Target Shape

The target system has four layers:

1. **Evidence Layer**
   Raw normalized observations and user-confirmed corrections remain append-only or versioned. Memory events reference evidence by observation id, message index, hash, and short evidence summary; they do not duplicate full chat transcripts or raw screenshots.

2. **Event Layer**
   Every memory mutation is explicit: observation ingested, match identity assessed, match confirmed, fact extracted, fact corrected, assumption rejected, commitment created/resolved, feedback recorded, summary updated.

3. **Projection Layer**
   Deterministic reducers materialize current state into one first-stage projection file:
   - `matches/<match_id>/match_memory_projection.json`

   The projection contains match profile facts, conversation thread memory, commitments, feedback preferences, conflicts, and identity trust fields. Split projections into multiple files only after query/export pressure proves it is needed.

4. **Retrieval Layer**
   Context builder reads projections plus the latest observation, prioritizes safety and turn boundary, applies identity trust, freshness, and confidence filters, then emits a compact context pack.

## Round Breakdown

- **Round 1:** Introduce memory domain model, identity trust gate, fact keys, event log, reducer, and projection repository.
- **Round 2:** Integrate observation ingest, single-match rebuild, and context build with projections while preserving backward compatibility.
- **Round 3:** Add correction, identity merge/confirmation surfaces, commitment, and feedback-learning commands.
- **Round 4:** Add retrieval policy, context budgets, production privacy/export/delete surfaces, SQLite-aware erasure, and regression evals.
- **Round 5:** Optional hardening: all-match rebuild, SQLite-backed query helpers, and optional semantic hook retrieval.

Round 5 should only start if Rounds 1-4 pass all tests and local manual workflows.

---

## File Structure

Create:

- `dating_boost/core/memory/__init__.py`
  Public exports for memory models, repository, reducer, and retrieval.

- `dating_boost/core/memory/models.py`
  Dataclasses/enums for memory events, facts, projections, conflict records, commitments, freshness, and evidence references.

- `dating_boost/core/memory/repositories.py`
  JSON-backed event/projection repository using existing `JsonStorage`.

- `dating_boost/core/memory/reducers.py`
  Deterministic projection reducer from memory events to materialized match memory.

- `dating_boost/core/memory/extractors.py`
  Deterministic extraction from `AppObservation` to candidate memory events. No LLM calls in this file.

- `dating_boost/core/memory/ingest.py`
  Shared observation ingest path used by CLI and automation so memory event creation, projection rebuild, and identity trust behavior do not diverge.

- `dating_boost/core/memory/retrieval.py`
  Context item selection, priority ordering, freshness filtering, and budget trimming.

- `tests/test_memory_models.py`
  Round-trip and validation tests for memory events and projections.

- `tests/test_memory_reducers.py`
  Reducer tests for facts, conflicts, stale facts, commitments, and feedback.

- `tests/test_memory_cli.py`
  CLI tests for ingest, get, update, correction, conflict, and context integration.

- `tests/test_memory_retrieval.py`
  Context retrieval priority, budget, freshness, and safety ordering tests.

Modify:

- `dating_boost/cli.py`
  Add memory commands and route existing ingest/context paths through memory projections.

- `dating_boost/core/context_pack.py`
  Accept richer projection-derived memory items without changing safety constraints.

- `dating_boost/core/repositories.py`
  Keep existing repositories, add small identity/index helpers when needed, and delegate match-local long-term memory to `dating_boost.core.memory`.

- `dating_boost/core/automation.py`
  Use memory projection context instead of re-building conversation memory directly from one observation.

- `dating_boost/core/capabilities.py`
  Advertise new memory commands only after tests pass.

- `dating_boost/core/production_store.py`
  Add SQLite-aware document/event removal helpers only when implementing memory delete in Round 4.

- `docs/ARCHITECTURE.md`
  Update the P3 memory section after implementation, not before.

- `dating_boost/resources/agent_adapters/*`
  Update host workflow docs after CLI contract is stable.

---

## Round 1: Memory Core And Projections

### Task 1.1: Define Memory Domain Models

**Files:**
- Create: `dating_boost/core/memory/__init__.py`
- Create: `dating_boost/core/memory/models.py`
- Test: `tests/test_memory_models.py`

- [ ] **Step 1: Write failing tests for memory event round-trip**

Add tests that assert these concrete behaviors:

- A `MemoryEvent` serializes to JSON-safe dict and back.
- `evidence.source_observation_id` is required for observation-derived facts.
- `MemoryFact.status` accepts `active`, `conflicted`, `archived`, `rejected`.
- Inferences are explicitly typed and cannot be serialized as visible facts.
- `MemoryFact` has a stable conflict key built from `subject`, `predicate`, and normalized qualifiers.
- `MatchMemoryProjection` exposes `identity_status`, `trusted_for_context`, and `trusted_for_managed_send`.
- Temporal fields use ISO strings and are preserved exactly.

Run:

```bash
pytest tests/test_memory_models.py -v
```

Expected: fails because `dating_boost.core.memory.models` does not exist.

- [ ] **Step 2: Implement minimal dataclasses and enums**

Required model names:

- `MemoryEventType`
- `MemoryScope`
- `MemoryFactType`
- `MemoryFactStatus`
- `IdentityTrustStatus`
- `EvidenceRef`
- `MemoryFact`
- `CommitmentMemory`
- `MemoryConflict`
- `MemoryEvent`
- `MatchMemoryProjection`

Required event types:

- `observation_ingested`
- `match_identity_assessed`
- `profile_fact_observed`
- `conversation_fact_observed`
- `inference_recorded`
- `fact_corrected`
- `fact_rejected`
- `match_identity_confirmed`
- `match_identity_conflict`
- `commitment_created`
- `commitment_resolved`
- `feedback_recorded`
- `projection_rebuilt`

Required scopes:

- `match_profile`
- `conversation`
- `commitment`
- `feedback_preference`

Round 1 does not make `user_global`, `planner_state`, or `app_state` part of the new memory repository. User profile, planner state, and app state keep their existing owners and are joined only at context-building time.

Rules:

- Store `source_observation_id`, `source_event_id`, `source_type`, `evidence_text`, and `confidence`.
- Store `subject`, `predicate`, `value`, `qualifiers`, `normalized_key`, and `normalized_value` for facts.
- Store `valid_from`, `valid_until`, `created_at`, `last_seen_at`.
- Store `supersedes` and `status`.
- Store identity trust separately from memory confidence:
  - `identity_status`: `new`, `trusted`, `needs_confirmation`, `conflicted`, `rejected`
  - `trusted_for_context`: true only for `new` or `trusted`, or for low-risk fallback context explicitly marked as such.
  - `trusted_for_managed_send`: true only for `trusted` or high-confidence non-conflicted identity.
- Do not add vector fields in Round 1.

- [ ] **Step 3: Run model tests**

Run:

```bash
pytest tests/test_memory_models.py -v
```

Expected: all tests pass.

### Task 1.2: Implement Event And Projection Repository

**Files:**
- Create: `dating_boost/core/memory/repositories.py`
- Test: `tests/test_memory_reducers.py`

- [ ] **Step 1: Write failing repository tests**

Add tests for:

- `MemoryRepository.append_event(match_id, event)` writes to `matches/<match_id>/memory_events.jsonl`.
- `MemoryRepository.load_events(match_id)` returns events in append order.
- `MemoryRepository.save_projection(match_id, projection)` writes `matches/<match_id>/match_memory_projection.json`.
- Unsafe `match_id` values are rejected using the same rules as current repositories.
- Appending duplicate `event_id` is idempotent: repository returns the existing event stream without duplicating the event.

Run:

```bash
pytest tests/test_memory_reducers.py::MemoryRepositoryTests -v
```

Expected: fails because repository does not exist.

- [ ] **Step 2: Implement `MemoryRepository`**

Use existing `JsonStorage`; do not bypass it.

Paths:

- `matches/<match_id>/memory_events.jsonl`
- `matches/<match_id>/match_memory_projection.json`

Public methods:

- `append_event(match_id: str, event: MemoryEvent) -> None`
- `load_events(match_id: str) -> list[MemoryEvent]`
- `save_projection(match_id: str, projection: MatchMemoryProjection) -> None`
- `load_projection(match_id: str) -> MatchMemoryProjection | None`
- `rebuild_projection(match_id: str) -> MatchMemoryProjection`

Repository rule:

- Store all first-stage projection state in `match_memory_projection.json`; do not create separate projection files in Round 1.

- [ ] **Step 3: Run repository tests**

Run:

```bash
pytest tests/test_memory_reducers.py::MemoryRepositoryTests -v
```

Expected: all repository tests pass.

### Task 1.3: Implement Deterministic Reducer

**Files:**
- Create: `dating_boost/core/memory/reducers.py`
- Test: `tests/test_memory_reducers.py`

- [ ] **Step 1: Write failing reducer tests**

Add tests for these event sequences:

1. Two identical observed facts merge by normalized content and update `last_seen_at`.
2. A conflicting fact with the same `subject + predicate + normalized qualifiers` and an incompatible `normalized_value` creates a `MemoryConflict` and marks both facts as `conflicted`.
3. A `fact_corrected` event supersedes the old fact and activates the correction.
4. A `fact_rejected` event marks the target fact `rejected`.
5. A `commitment_created` event appears in active commitments.
6. A `commitment_resolved` event removes it from active commitments and preserves history.
7. A `feedback_recorded` event updates mode-scoped feedback counters without changing hard facts.

Run:

```bash
pytest tests/test_memory_reducers.py::MemoryReducerTests -v
```

Expected: fails because reducer does not exist.

- [ ] **Step 2: Implement reducer**

Public function:

- `reduce_match_memory(match_id: str, events: list[MemoryEvent]) -> MatchMemoryProjection`

Projection must include:

- `schema_version`
- `match_id`
- `facts`
- `inferences`
- `conversation_threads`
- `active_commitments`
- `resolved_commitments`
- `feedback_preferences`
- `conflicts`
- `identity_status`
- `trusted_for_context`
- `trusted_for_managed_send`
- `last_event_id`
- `updated_at`

Reducer rules:

- Facts with `fact_type="visible_fact"` can be used as grounded context.
- Facts with `fact_type="photo_cue"` remain low-confidence hypotheses unless user-confirmed.
- Inferences must stay under `inferences`, never under `facts`.
- Rejected facts are excluded from retrieval but retained in projection for audit.
- Conflicted facts are excluded from high-confidence context.
- Facts without a valid `normalized_key` are retained for audit but excluded from conflict resolution and default retrieval.

- [ ] **Step 3: Write failing identity trust reducer tests**

Add tests for:

- `match_identity_assessed` with high confidence sets `trusted_for_context=True`.
- `match_identity_assessed` with low confidence sets `identity_status="needs_confirmation"` and `trusted_for_managed_send=False`.
- `match_identity_conflict` sets `identity_status="conflicted"` and excludes projection facts from managed-send context.
- `match_identity_confirmed` restores `trusted_for_context=True` and `trusted_for_managed_send=True`.

Run:

```bash
pytest tests/test_memory_reducers.py::MemoryReducerTests -v
```

Expected: fails because identity trust behavior is not implemented yet.

- [ ] **Step 4: Implement identity trust reducer behavior and run tests**

Implement reducer support for:

- identity status transitions.
- context trust gating.
- managed-send trust gating.
- conflict status overriding prior trust.
- user confirmation restoring trust only for the confirmed match.

Run:


```bash
pytest tests/test_memory_reducers.py::MemoryReducerTests -v
```

Expected: all reducer tests pass.

---

## Round 2: Observation Ingest And Context Integration

### Task 2.1: Extract Memory Events From Observation

**Files:**
- Create: `dating_boost/core/memory/extractors.py`
- Create: `dating_boost/core/memory/ingest.py`
- Modify: `dating_boost/cli.py`
- Test: `tests/test_memory_cli.py`

- [ ] **Step 1: Write failing observation extraction tests**

Use `tests/fixtures/intelligence/app_observation_chat.json`.

Expected events:

- `observation_ingested`
- `match_identity_assessed` with identity confidence and confirmation requirements.
- `profile_fact_observed` for short hook candidates or visible profile cues, if present.
- `conversation_fact_observed` for latest inbound turn metadata.
- `inference_recorded` for photo cues and hook candidates.

Assertions:

- Every event references `obs_chat_001`.
- Photo cues are not `visible_fact`.
- Latest inbound messages preserve source references, message index, sender, hash, and character count.
- Memory events do not duplicate full chat message text; full text remains in the observation evidence layer.
- Event IDs are deterministic from `match_id`, `observation_id`, event type, and normalized content.

Run:

```bash
pytest tests/test_memory_cli.py::MemoryObservationExtractionTests -v
```

Expected: fails.

- [ ] **Step 2: Implement deterministic extraction**

Public function:

- `events_from_observation(match_id: str, observation: AppObservation, created_at: str) -> list[MemoryEvent]`

Do not call an LLM. Do not parse raw natural language into new facts beyond existing structured observation fields. Do not copy full visible message text into memory events.

- [ ] **Step 3: Implement shared ingest helper**

Create:

- `store_observation_with_memory(root: Path, observation: AppObservation) -> dict[str, Any]`

Behavior:

1. Resolve match identity with `MatchRepository`.
2. Save the observation with `ObservationRepository`.
3. Update the match index with `MatchRepository`.
4. Append extracted memory events.
5. Rebuild and save `match_memory_projection.json`.
6. Return the current ingest payload.

Use this helper from CLI first. Automation is updated in Task 2.4.

- [ ] **Step 4: Integrate shared helper into `_store_observation`**

Replace the body of CLI `_store_observation` with the shared helper while preserving validation and response compatibility.

Maintain current JSON response fields:

- `status`
- `match_id`
- `confidence`
- `requires_user_confirmation`
- `observation_id`

Add non-breaking fields:

- `memory_event_count`
- `projection_updated`
- `identity_status`
- `trusted_for_context`
- `trusted_for_managed_send`

- [ ] **Step 5: Run CLI ingest tests**

Run:

```bash
pytest tests/test_memory_cli.py::MemoryObservationExtractionTests tests/test_agent_native_cli.py tests/test_cli_mvp.py -v
```

Expected: all pass.

### Task 2.2: Add Single-Match Projection Rebuild

**Files:**
- Modify: `dating_boost/cli.py`
- Modify: `dating_boost/core/memory/repositories.py`
- Test: `tests/test_memory_cli.py`
- Test: `tests/test_production_reliability.py`

- [ ] **Step 1: Write failing rebuild tests**

Cases:

- Existing data with only `matches/<match_id>/observations.json` can rebuild `match_memory_projection.json`.
- Rebuild is idempotent.
- Existing `matches/index.json` remains valid.
- Corrupt observation files fail with a clear error and do not write a partial projection.

Run:

```bash
pytest tests/test_memory_cli.py::MemoryRebuildTests tests/test_production_reliability.py -v
```

Expected: fails.

- [ ] **Step 2: Add command**

```bash
dating-boost memory rebuild --data-dir <dir> --match-id <id>
```

Do not add `--all` in Round 2. Single-match rebuild is enough to make local debugging and existing fixture migration deterministic.

- [ ] **Step 3: Run rebuild tests**

Run:

```bash
pytest tests/test_memory_cli.py::MemoryRebuildTests tests/test_production_reliability.py -v
```

Expected: all pass.

### Task 2.3: Build Context From Projection Plus Latest Observation

**Files:**
- Create: `dating_boost/core/memory/retrieval.py`
- Modify: `dating_boost/cli.py`
- Modify: `dating_boost/core/context_pack.py`
- Test: `tests/test_memory_retrieval.py`
- Test: `tests/test_context_pack.py`

- [ ] **Step 1: Write failing retrieval tests**

Add tests for:

- User boundaries and hard facts outrank match hooks.
- Latest inbound messages outrank older conversation summary.
- Active commitments outrank inferred interests.
- Conflicted and rejected facts are excluded from default retrieval.
- Stale facts with `valid_until` before current time are excluded unless needed for audit.
- Projection with `trusted_for_context=False` contributes only low-risk identity diagnostics, not match facts.
- Context budget trimming keeps `turn_boundary`.

Run:

```bash
pytest tests/test_memory_retrieval.py -v
```

Expected: fails.

- [ ] **Step 2: Implement retrieval selector**

Public function:

- `build_memory_context(match_id: str, projection: MatchMemoryProjection, latest_observation: AppObservation | None, now: str, max_items: int | None) -> dict[str, Any]`

Output keys:

- `match_profile`
- `conversation_memory`
- `memory_items`
- `excluded_memory`

Ordering:

1. user hard constraints are still handled by existing user profile context.
2. latest inbound messages
3. turn boundary
4. active commitments
5. user-visible match facts
6. planner state
7. conversation summary
8. hooks
9. low-confidence hypotheses

- [ ] **Step 3: Route `_build_mvp_context_pack` through projections**

Behavior:

- If projection exists, use projection plus latest observation.
- If projection does not exist, preserve current latest-observation fallback.
- Do not remove existing labels used by tests unless tests are updated in the same task.

- [ ] **Step 4: Run context tests**

Run:

```bash
pytest tests/test_memory_retrieval.py tests/test_context_pack.py tests/test_policy.py tests/test_reply_generator.py -v
```

Expected: all pass.

### Task 2.4: Update Automation Context Path

**Files:**
- Modify: `dating_boost/core/automation.py`
- Test: `tests/test_automation_session.py`
- Test: `tests/test_automation_planner.py`

- [ ] **Step 1: Write failing automation context regression**

Add a test where:

- Observation A contains a useful profile hook.
- Observation B contains only a latest inbound message.
- Automation context after Observation B still includes the hook from projection and the latest inbound from Observation B.

Run:

```bash
pytest tests/test_automation_session.py::test_automation_context_uses_projection_plus_latest_observation -v
```

Expected: fails.

- [ ] **Step 2: Refactor `AutomationSession._context_pack`**

Reuse the same memory retrieval helper as CLI context build. Keep appointment constraints and global slot conflicts injected after base memory context is built.

- [ ] **Step 3: Refactor `AutomationSession._store_observation`**

Use `store_observation_with_memory(...)` so CLI and automation produce the same memory events and projections from the same observation.

- [ ] **Step 4: Run automation tests**

Run:

```bash
pytest tests/test_automation_session.py tests/test_automation_planner.py tests/test_operator_session.py -v
```

Expected: all pass.

---

## Round 3: Corrections, Conflicts, Commitments, Feedback Learning

### Task 3.1: Add `memory update-match`

**Files:**
- Modify: `dating_boost/cli.py`
- Modify: `dating_boost/core/capabilities.py`
- Test: `tests/test_memory_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Commands to test:

```bash
dating-boost memory update-match --data-dir <dir> --match-id <id> --input correction.json
```

Supported input actions:

- `confirm_identity`
- `merge_identity`
- `reject_fact`
- `correct_fact`
- `archive_fact`
- `create_commitment`
- `resolve_commitment`

Expected:

- Command appends a memory event.
- Projection rebuilds.
- Response includes `event_id`, `projection_updated`, and `status`.
- Invalid action exits non-zero with a clear error.

- [ ] **Step 2: Implement parser and handler**

Add subcommand under existing `memory` parser.

Do not remove old commands.

- [ ] **Step 3: Advertise capability**

Add `"memory update-match"` to `SUPPORTED_COMMANDS` only after tests pass.

- [ ] **Step 4: Run CLI tests**

Run:

```bash
pytest tests/test_memory_cli.py tests/test_agent_native_cli.py tests/test_skill_package.py -v
```

Expected: all pass.

### Task 3.2: Implement Identity Confirmation And Merge Safety

**Files:**
- Modify: `dating_boost/core/memory/reducers.py`
- Modify: `dating_boost/core/repositories.py`
- Modify: `dating_boost/cli.py`
- Test: `tests/test_identity.py`
- Test: `tests/test_memory_cli.py`

- [ ] **Step 1: Write failing tests**

Cases:

- Low-confidence name-only match is already untrusted for managed send before confirmation.
- `confirm_identity` marks identity as user-confirmed.
- `match_identity_conflict` appears when two active match records share strong identity hints.
- `merge_identity` preserves source observation IDs, memory event history, and merged match IDs.
- `merge_identity` refuses to run unless the input names both source and target match IDs and the confirmation token is exact.

- [ ] **Step 2: Implement identity merge handling**

Use explicit events; do not silently merge memory only because names match. Preserve old match events for audit and rebuild the target projection from the combined event stream.

- [ ] **Step 3: Run identity tests**

Run:

```bash
pytest tests/test_identity.py tests/test_memory_cli.py tests/test_confirmation_contract.py -v
```

Expected: all pass.

### Task 3.3: Turn Feedback Into Scoped Preferences

**Files:**
- Modify: `dating_boost/core/feedback.py`
- Modify: `dating_boost/core/memory/reducers.py`
- Modify: `dating_boost/cli.py`
- Test: `tests/test_feedback.py`
- Test: `tests/test_memory_reducers.py`

- [ ] **Step 1: Write failing tests**

Cases:

- `wrong_assumption` rejects or downgrades the referenced memory item.
- `not_like_me` updates mode-scoped style preference, not hard facts.
- `too_flirty` increases a negative tone counter for the selected reply mode.
- `accepted` increments accepted count for hook/move if references are present.
- `edited` records event but does not promote text to style example without explicit confirmation.

- [ ] **Step 2: Extend feedback event payload**

Allow optional fields:

- `referenced_memory_ids`
- `conversation_move`
- `hook_source`
- `edited_text_ref`
- `user_confirmed_style_promotion`

Keep old feedback payloads readable.

- [ ] **Step 3: Feed feedback into memory projection**

When `feedback record` runs, append a `feedback_recorded` memory event for the match and rebuild projection.

- [ ] **Step 4: Run feedback tests**

Run:

```bash
pytest tests/test_feedback.py tests/test_memory_reducers.py tests/test_policy.py -v
```

Expected: all pass.

---

## Round 4: Production Retrieval, Privacy, Eval Coverage

### Task 4.1: Add Context Budget And Retrieval Diagnostics

**Files:**
- Modify: `dating_boost/core/memory/retrieval.py`
- Modify: `dating_boost/cli.py`
- Test: `tests/test_memory_retrieval.py`
- Test: `tests/test_context_pack.py`

- [ ] **Step 1: Write failing budget tests**

Cases:

- `--max-memory-items 8` returns no more than 8 memory-derived items.
- `turn_boundary` remains present even under small budgets.
- Excluded items include reason codes: `budget`, `stale`, `conflicted`, `rejected`, `low_confidence`.
- Diagnostics are only included when requested.

- [ ] **Step 2: Add CLI option**

Add to `context build`:

```bash
--max-memory-items <int>
--include-memory-diagnostics
```

Default behavior remains compatible with current command.

- [ ] **Step 3: Run retrieval tests**

Run:

```bash
pytest tests/test_memory_retrieval.py tests/test_context_pack.py tests/test_agent_native_cli.py -v
```

Expected: all pass.

### Task 4.2: Add Local Export/Delete For Memory

**Files:**
- Modify: `dating_boost/cli.py`
- Modify: `dating_boost/core/memory/repositories.py`
- Modify: `dating_boost/core/production_store.py`
- Test: `tests/test_memory_cli.py`
- Test: `tests/test_production_data.py`

- [ ] **Step 1: Write failing export/delete tests**

Commands:

```bash
dating-boost memory export --data-dir <dir> --match-id <id>
dating-boost memory delete-match --data-dir <dir> --match-id <id> --confirm delete-match:<id>
```

Expected:

- Export includes projection, events, conflicts, and identity status.
- Export excludes raw screenshots by default.
- Delete removes or redacts match-local JSON documents, observations, projection, memory events, feedback events, and match index entry.
- If `dating_boost.sqlite3` exists, delete also removes mirrored `documents` and `audit_events` rows for the same match-local path prefix.
- Delete fails clearly if SQLite cleanup fails after JSON cleanup is planned but before it starts.
- Delete requires exact confirmation token.

- [ ] **Step 2: Add SQLite-aware removal helpers**

Add methods to `ProductionDataStore`:

- `delete_documents_with_prefix(prefix: str) -> int`
- `delete_audit_events_with_stream_prefix(prefix: str) -> int`

Rules:

- Only accept prefixes beginning with `matches/<match_id>/`.
- Do not allow empty prefix, `.`, `..`, `/`, or path traversal.
- Return deleted row counts for audit output.

- [ ] **Step 3: Implement commands**

Use existing storage paths and repository validation. Do not add destructive defaults.

Implementation rule:

- Prefer physical deletion when both JSON and SQLite cleanup can be completed consistently.
- If physical deletion cannot be made consistent, implement a tombstone projection and redacted export, but do not call the result a physical delete.

- [ ] **Step 4: Run production data tests**

Run:

```bash
pytest tests/test_memory_cli.py tests/test_production_data.py tests/test_storage.py -v
```

Expected: all pass.

### Task 4.3: Add Memory Regression Evals

**Files:**
- Create or modify: `tests/fixtures/evals/memory_cases.jsonl`
- Modify: `dating_boost/evals/runner.py`
- Test: `tests/test_evals.py`

- [ ] **Step 1: Add fixture cases**

Minimum 12 synthetic cases:

- stale weekend availability is excluded.
- corrected interest supersedes older interest.
- rejected photo inference is not used.
- identity conflict blocks managed-send confidence.
- active commitment is surfaced.
- resolved commitment is not treated as active.
- wrong assumption feedback suppresses a hook.
- mode-scoped `too_flirty` affects adaptive mode but not self mode.
- latest inbound outranks old summary.
- user boundary outranks recipient-optimized adaptation.
- opener uses profile hook without inventing user fact.
- stalled chat nudge uses low-investment repair memory.

- [ ] **Step 2: Extend eval runner**

Add a memory regression mode that builds context packs and checks expected labels/exclusions. Do not require live LLM calls.

- [ ] **Step 3: Run eval tests**

Run:

```bash
pytest tests/test_evals.py tests/test_memory_retrieval.py -v
```

Expected: all pass.

---

## Round 5: Optional Hardening

Only execute this round after Rounds 1-4 are stable.

### Task 5.1: All-Match Rebuild And Backfill Hardening

**Files:**
- Modify: `dating_boost/core/memory/repositories.py`
- Modify: `dating_boost/cli.py`
- Test: `tests/test_memory_cli.py`
- Test: `tests/test_production_reliability.py`

- [ ] **Step 1: Write failing rebuild tests**

Cases:

- `memory rebuild --all` rebuilds every match that has `observations.json`.
- One corrupt match reports an error for that match without deleting other successful projections.
- Existing `matches/index.json` remains valid.
- Rebuild is idempotent.

- [ ] **Step 2: Add command**

```bash
dating-boost memory rebuild --data-dir <dir> --match-id <id>
dating-boost memory rebuild --data-dir <dir> --all
```

The `--match-id` path already exists from Round 2. Round 5 adds only `--all` orchestration and stronger batch reporting.

- [ ] **Step 3: Run rebuild tests**

Run:

```bash
pytest tests/test_memory_cli.py tests/test_production_reliability.py -v
```

Expected: all pass.

### Task 5.2: Optional Semantic Hook Retrieval

**Files:**
- Create: `dating_boost/core/memory/semantic.py`
- Modify: `dating_boost/core/memory/retrieval.py`
- Test: `tests/test_memory_retrieval.py`

- [ ] **Step 1: Write tests that keep semantic retrieval subordinate**

Cases:

- Semantic hook retrieval never returns rejected/conflicted facts.
- Semantic hook retrieval never promotes photo cues to facts.
- Structured priority still outranks semantic similarity.

- [ ] **Step 2: Add interface only**

Define a provider interface and a no-op local implementation. Do not add a mandatory vector database dependency.

- [ ] **Step 3: Run retrieval tests**

Run:

```bash
pytest tests/test_memory_retrieval.py -v
```

Expected: all pass.

---

## Acceptance Criteria

The memory system is production-ready for dating-agent use when all of these are true:

- Existing agent-native and automation flows still pass.
- `memory ingest-observation` creates memory events and projection updates.
- Existing single-match observations can be rebuilt into projections with `memory rebuild --match-id`.
- `context build` uses projection plus latest observation.
- Latest inbound turn boundary always outranks older context.
- User hard facts and boundaries cannot be overwritten by match inferences.
- Photo cues and hook candidates remain hypotheses unless confirmed.
- Low-confidence or conflicted match identity cannot silently promote facts into managed-send context.
- Stale facts can be excluded by freshness.
- Conflicting facts are retained for audit but excluded from high-confidence context.
- User corrections produce explicit events and supersede old facts.
- `wrong_assumption` feedback downgrades or rejects referenced memory.
- Feedback learning is mode-scoped.
- Match identity low-confidence paths require confirmation before managed-send reliance.
- Export/delete commands are local, auditable, confirmation-gated, and consistent across JSON files and SQLite mirror when SQLite exists.
- No raw screenshots or original profile photos are stored by default.
- Memory events do not duplicate full chat transcripts.
- Memory regression evals cover at least 12 dating-specific cases.

## Local-Only Execution Rule

Do not push this work to a remote repository during these rounds.

Allowed local git actions during implementation:

- Create a local branch with prefix `codex/`.
- Commit after each task or round.
- Inspect diffs.

Disallowed unless the user explicitly asks:

- `git push`
- pull request creation
- destructive reset or checkout of user changes

## Recommended Round Gates

After each round, stop and ask for confirmation before continuing.

Round 1 gate:

- Memory domain tests pass.
- Repository and reducer tests pass.
- Identity trust gates are represented in projection.
- Fact conflict keys are explicit.
- No CLI behavior changed yet.

Round 2 gate:

- Existing CLI ingest/context behavior remains compatible.
- Single-match rebuild works for existing observations.
- Context quality improves by retaining older projection memory.
- CLI and automation use the same ingest/retrieval helpers.

Round 3 gate:

- User correction and feedback flows exist.
- Identity confirmation and conflicts are explicit.
- Identity merge preserves source event history and refuses unsafe confirmation.
- Capabilities and host workflow docs are aligned.

Round 4 gate:

- Context budget and diagnostics are available.
- Export/delete commands pass privacy tests and SQLite consistency tests.
- Memory regression evals pass.

Round 5 gate:

- All existing local matches can be rebuilt into projections with batch reporting.
- Optional semantic retrieval cannot override structured safety.

## Self-Review

- Spec coverage: The plan covers 3-5 rounds, local-only execution, production-grade dating-agent memory, framework-inspired provenance/time/conflict/retrieval patterns, and confirmation before implementation.
- Placeholder scan: No `TBD`, no deferred unspecified behavior, no open-ended “handle edge cases” steps.
- Type consistency: Model names, repository methods, reducer function, extraction function, and retrieval function are consistent across tasks.
- Risk check: The plan avoids making embeddings primary memory and keeps generated/inferred memory below explicit observations and user-confirmed facts.
