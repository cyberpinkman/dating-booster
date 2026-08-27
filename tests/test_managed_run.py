from __future__ import annotations

import hashlib
import stat
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pytest

from dating_boost.core.managed_run import (
    ClickReceipt,
    ComposerObservation,
    DraftDecision,
    InMemoryManagedRunStore,
    JsonManagedRunStore,
    ManagedActionPort,
    ManagedAuthorization,
    ManagedDecisionPort,
    ManagedObservationPort,
    ManagedRun,
    ManagedRunConfig,
    ManagedRunRecord,
    MessageListSnapshot,
    OpenThreadObservation,
    PostSendObservation,
    ThreadCandidate,
    ThreadObservation,
)


pytestmark = pytest.mark.managed_critical


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 27, 4, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def tick(self) -> str:
        self.value += timedelta(seconds=1)
        return self.value.isoformat().replace("+00:00", "Z")


class FixtureObservation(ManagedObservationPort):
    def __init__(
        self,
        clock: Clock,
        candidates: Sequence[ThreadCandidate],
        *,
        opened_target_id: str | None = None,
        opened_binding: str | None = None,
        thread_revision: str | None = None,
        next_cursor: dict[str, Any] | None = None,
        thread_context: dict[str, Any] | None = None,
    ):
        self.clock = clock
        self.candidates = tuple(candidates)
        self.opened_target_id = opened_target_id
        self.opened_binding = opened_binding
        self.thread_revision = thread_revision
        self.next_cursor = dict(next_cursor or {})
        self.thread_context = dict(thread_context or {"latest_inbound": "周末要不要喝咖啡？"})
        self.calls: list[str] = []

    def scan_message_list(
        self,
        *,
        run_id: str,
        app_id: str,
        runtime: str,
        cursor: dict[str, Any],
    ) -> MessageListSnapshot:
        del run_id, app_id, runtime, cursor
        self.calls.append("scan")
        return MessageListSnapshot(
            candidates=self.candidates,
            captured_at=self.clock.tick(),
            next_cursor=dict(self.next_cursor),
        )

    def open_thread(self, candidate: ThreadCandidate) -> OpenThreadObservation:
        self.calls.append("open")
        return OpenThreadObservation(
            target_id=self.opened_target_id or candidate.target_id,
            target_binding=self.opened_binding or candidate.target_binding,
            captured_at=self.clock.tick(),
        )

    def observe_thread(self, candidate: ThreadCandidate) -> ThreadObservation:
        self.calls.append("observe")
        return ThreadObservation(
            target_id=candidate.target_id,
            target_binding=candidate.target_binding,
            inbound_revision=self.thread_revision or candidate.inbound_revision,
            captured_at=self.clock.tick(),
            context=dict(self.thread_context),
        )


class BlockingOnceObservation(FixtureObservation):
    def __init__(self, clock: Clock, candidates: Sequence[ThreadCandidate]):
        super().__init__(clock, candidates)
        self.entered = threading.Event()
        self.release = threading.Event()

    def scan_message_list(
        self,
        *,
        run_id: str,
        app_id: str,
        runtime: str,
        cursor: dict[str, Any],
    ) -> MessageListSnapshot:
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test did not release the execution lease")
        return super().scan_message_list(
            run_id=run_id,
            app_id=app_id,
            runtime=runtime,
            cursor=cursor,
        )


class SequencedObservation(FixtureObservation):
    def __init__(self, clock: Clock, candidate_batches: Sequence[Sequence[ThreadCandidate]]):
        batches = [tuple(batch) for batch in candidate_batches]
        super().__init__(clock, batches[0] if batches else ())
        self.candidate_batches = batches
        self.scan_count = 0

    def scan_message_list(
        self,
        *,
        run_id: str,
        app_id: str,
        runtime: str,
        cursor: dict[str, Any],
    ) -> MessageListSnapshot:
        index = min(self.scan_count, len(self.candidate_batches) - 1)
        self.candidates = self.candidate_batches[index] if index >= 0 else ()
        self.scan_count += 1
        return super().scan_message_list(
            run_id=run_id,
            app_id=app_id,
            runtime=runtime,
            cursor=cursor,
        )


class FixtureDecision(ManagedDecisionPort):
    def __init__(self, text: str = "可以，周日下午怎么样？"):
        self.text = text
        self.calls: list[str] = []

    def prioritize(
        self,
        candidates: Sequence[ThreadCandidate],
        *,
        thread_states: Mapping[str, dict[str, Any]],
    ) -> ThreadCandidate | None:
        del thread_states
        self.calls.append("prioritize")
        return min(candidates, key=lambda item: item.priority) if candidates else None

    def decide(self, observation: ThreadObservation, *, config: ManagedRunConfig) -> DraftDecision:
        del config
        self.calls.append("decide")
        return DraftDecision.send(
            decision_id=f"decision_{observation.target_id}_{observation.inbound_revision}",
            target_id=observation.target_id,
            inbound_revision=observation.inbound_revision,
            text=self.text,
        )


class MaturingNudgeDecision(FixtureDecision):
    def __init__(self) -> None:
        super().__init__("跟进一下")
        self.decision_count = 0

    def decide(self, observation: ThreadObservation, *, config: ManagedRunConfig) -> DraftDecision:
        self.decision_count += 1
        if self.decision_count == 1:
            self.calls.append("decide")
            return DraftDecision(
                decision_id="decision_nudge_wait",
                outcome="wait",
                target_id=observation.target_id,
                inbound_revision=observation.inbound_revision,
                reason_codes=("managed_nudge_not_due",),
            )
        return super().decide(observation, config=config)


class FixtureAction(ManagedActionPort):
    def __init__(
        self,
        clock: Clock,
        candidate: ThreadCandidate,
        *,
        staged_text_override: str | None = None,
        composer_revision: str | None = None,
        outbound_text_override: str | None = None,
        post_receipt_override: str | None = None,
        composer_captured_at_override: str | None = None,
        post_captured_at_override: str | None = None,
        after_stage: Callable[[], None] | None = None,
    ):
        self.clock = clock
        self.candidate = candidate
        self.staged_text_override = staged_text_override
        self.composer_revision = composer_revision
        self.outbound_text_override = outbound_text_override
        self.post_receipt_override = post_receipt_override
        self.composer_captured_at_override = composer_captured_at_override
        self.post_captured_at_override = post_captured_at_override
        self.after_stage = after_stage
        self.composer_text = ""
        self.last_clicked_text: str | None = None
        self.stage_count = 0
        self.click_count = 0
        self.post_count = 0
        self.composer_observe_count = 0
        self.calls: list[str] = []

    def observe_composer(self, candidate: ThreadCandidate) -> ComposerObservation:
        self.calls.append("observe_composer")
        self.composer_observe_count += 1
        captured_at = self.clock.tick()
        return ComposerObservation(
            target_id=candidate.target_id,
            target_binding=candidate.target_binding,
            inbound_revision=self.composer_revision or candidate.inbound_revision,
            text=self.composer_text,
            captured_at=self.composer_captured_at_override or captured_at,
        )

    def stage_text(self, candidate: ThreadCandidate, text: str) -> ComposerObservation:
        self.calls.append("stage")
        self.stage_count += 1
        if self.composer_text:
            raise ValueError("fixture_composer_occupied")
        self.composer_text = self.staged_text_override if self.staged_text_override is not None else text
        if self.after_stage is not None:
            self.after_stage()
        return ComposerObservation(
            target_id=candidate.target_id,
            target_binding=candidate.target_binding,
            inbound_revision=self.composer_revision or candidate.inbound_revision,
            text=self.composer_text,
            captured_at=self.composer_captured_at_override or self.clock.tick(),
        )

    def click_send(self, candidate: ThreadCandidate) -> ClickReceipt:
        del candidate
        self.calls.append("click")
        self.click_count += 1
        self.last_clicked_text = self.composer_text
        self.composer_text = ""
        return ClickReceipt(receipt_id=f"receipt_{self.click_count}", clicked_at=self.clock.tick())

    def observe_post_send(
        self,
        candidate: ThreadCandidate,
        receipt: ClickReceipt,
    ) -> PostSendObservation:
        self.calls.append("verify")
        self.post_count += 1
        outbound = self.outbound_text_override if self.outbound_text_override is not None else self.last_clicked_text
        return PostSendObservation(
            observation_id=f"post_{self.post_count}",
            receipt_id=self.post_receipt_override or receipt.receipt_id,
            target_id=candidate.target_id,
            target_binding=candidate.target_binding,
            captured_at=self.post_captured_at_override or self.clock.tick(),
            input_cleared=self.composer_text == "",
            outbound_text=outbound,
        )


class BlockingClickAction(FixtureAction):
    def __init__(self, clock: Clock, candidate: ThreadCandidate):
        super().__init__(clock, candidate)
        self.click_entered = threading.Event()
        self.release_click = threading.Event()
        self.order: list[str] = []

    def click_send(self, candidate: ThreadCandidate) -> ClickReceipt:
        self.click_entered.set()
        if not self.release_click.wait(timeout=5):
            raise TimeoutError("test did not release click")
        receipt = super().click_send(candidate)
        self.order.append("click_finished")
        return receipt


class CrashAfterPreparedStore(InMemoryManagedRunStore):
    def __init__(self) -> None:
        super().__init__()
        self.crash_armed = True

    def save(self, record: ManagedRunRecord) -> None:
        super().save(record)
        if self.crash_armed and any(
            attempt.get("status") == "prepared_to_click" for attempt in record.send_attempts.values()
        ):
            self.crash_armed = False
            raise SimulatedProcessCrash


class CrashBeforeClickCommittedSaveStore(InMemoryManagedRunStore):
    def __init__(self) -> None:
        super().__init__()
        self.crash_armed = True

    def save(self, record: ManagedRunRecord) -> None:
        if self.crash_armed and any(
            attempt.get("status") == "click_committed" for attempt in record.send_attempts.values()
        ):
            self.crash_armed = False
            raise SimulatedProcessCrash
        super().save(record)


class CrashAfterConfirmedStore(InMemoryManagedRunStore):
    def __init__(self) -> None:
        super().__init__()
        self.crash_armed = True

    def save(self, record: ManagedRunRecord) -> None:
        super().save(record)
        if self.crash_armed and any(
            attempt.get("status") == "confirmed" for attempt in record.send_attempts.values()
        ):
            self.crash_armed = False
            raise SimulatedProcessCrash


class BlockingCreateStore(InMemoryManagedRunStore):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def create(self, record: ManagedRunRecord) -> None:
        super().create(record)
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test did not release start lease")


class SimulatedProcessCrash(RuntimeError):
    pass


class SimulatedHardCrash(BaseException):
    pass


def _candidate() -> ThreadCandidate:
    return ThreadCandidate(
        candidate_key="row_1",
        target_id="match_alice",
        target_binding="visual-anchor:alice-v1",
        inbound_revision="inbound_7",
        priority=1,
    )


def _config(
    *,
    allow_target: bool = True,
    duration_minutes: int = 120,
    max_sends_per_run: int = 100,
    quiet_hours: tuple[Any, ...] = (),
    nudge_enabled: bool = False,
) -> ManagedRunConfig:
    candidate = _candidate()
    return ManagedRunConfig(
        app_id="tashuo",
        runtime="mac-ios-app",
        authorization=ManagedAuthorization(
            authorization_id="auth_live_1",
            app_id="tashuo",
            runtime="mac-ios-app",
            allowed_actions=("send_message",),
            allowed_target_ids=(candidate.target_id,) if allow_target else ("match_bob",),
            autonomous_nudge=nudge_enabled,
            live_send=True,
            quiet_hours=quiet_hours,
        ),
        duration_minutes=duration_minutes,
        nudge_enabled=nudge_enabled,
        max_sends_per_run=max_sends_per_run,
    )


def _runtime(
    *,
    store: InMemoryManagedRunStore | None = None,
    observation: FixtureObservation | None = None,
    decision: FixtureDecision | None = None,
    action: FixtureAction | None = None,
) -> tuple[ManagedRun, InMemoryManagedRunStore, FixtureObservation, FixtureDecision, FixtureAction, Clock]:
    clock = observation.clock if observation is not None else action.clock if action is not None else Clock()
    candidate = _candidate()
    normalized_store = store or InMemoryManagedRunStore()
    normalized_observation = observation or FixtureObservation(clock, [candidate])
    normalized_decision = decision or FixtureDecision()
    normalized_action = action or FixtureAction(clock, candidate)
    return (
        ManagedRun(normalized_store, normalized_observation, normalized_decision, normalized_action, now=clock),
        normalized_store,
        normalized_observation,
        normalized_decision,
        normalized_action,
        clock,
    )


def test_tick_executes_complete_full_managed_chain_and_persists_confirmation() -> None:
    clock = Clock()
    observation = FixtureObservation(clock, [_candidate()], next_cursor={"page": 2})
    runtime, store, observation, decision, action, _ = _runtime(observation=observation)
    started = runtime.start(_config(), run_id="run_normal")

    result = runtime.tick(started["run_id"])

    assert result["status"] == "confirmed"
    assert observation.calls == ["scan", "open", "observe"]
    assert decision.calls == ["prioritize", "decide"]
    assert action.calls == ["stage", "click", "verify"]
    assert action.click_count == 1
    record = store.load("run_normal")
    assert record is not None
    assert record.attempted_send_count == 1
    assert record.confirmed_send_count == 1
    assert record.cycle_count == 1
    assert record.scan_cursor == {"page": 2}
    assert record.thread_states["match_alice"]["last_outcome"] == "confirmed"
    assert next(iter(record.send_attempts.values()))["status"] == "confirmed"
    assert [event["event_type"] for event in store.events("run_normal")] == [
        "run_started",
        "send_transaction_finished",
    ]


def test_wrong_opened_target_fails_before_drafting_or_clicking() -> None:
    clock = Clock()
    candidate = _candidate()
    observation = FixtureObservation(clock, [candidate], opened_target_id="match_bob")
    action = FixtureAction(clock, candidate)
    runtime, _, _, decision, _, _ = _runtime(observation=observation, action=action)
    runtime.start(_config(), run_id="run_wrong_target")

    result = runtime.tick()

    assert result["status"] == "failed_before_click"
    assert result["reason"] == "target_id_mismatch"
    assert decision.calls == ["prioritize"]
    assert action.stage_count == 0
    assert action.click_count == 0


def test_staged_text_must_exactly_match_decision() -> None:
    clock = Clock()
    candidate = _candidate()
    observation = FixtureObservation(clock, [candidate])
    action = FixtureAction(clock, candidate, staged_text_override="被截断的错误内容")
    runtime, store, _, _, _, _ = _runtime(observation=observation, action=action)
    runtime.start(_config(), run_id="run_wrong_text")

    result = runtime.tick()

    assert result["status"] == "failed_before_click"
    assert result["reason"] == "staged_text_mismatch"
    assert action.click_count == 0
    record = store.load("run_wrong_text")
    assert record is not None
    assert next(iter(record.send_attempts.values()))["status"] == "failed_before_click"


def test_atomic_stage_blocks_an_occupied_composer_without_clicking() -> None:
    clock = Clock()
    candidate = _candidate()
    observation = FixtureObservation(clock, [candidate])
    action = FixtureAction(clock, candidate)
    action.composer_text = "user draft already present"
    runtime, _, _, _, _, _ = _runtime(observation=observation, action=action)
    runtime.start(_config(), run_id="run_occupied_composer")

    result = runtime.tick()

    assert result["status"] == "failed_before_click"
    assert result["reason"] == "staging_failed"
    assert action.composer_text == "user draft already present"
    assert action.click_count == 0


def test_inbound_revision_drift_blocks_before_click() -> None:
    clock = Clock()
    candidate = _candidate()
    observation = FixtureObservation(clock, [candidate])
    action = FixtureAction(clock, candidate, composer_revision="inbound_8")
    runtime, _, _, _, _, _ = _runtime(observation=observation, action=action)
    runtime.start(_config(), run_id="run_revision_drift")

    result = runtime.tick()

    assert result["status"] == "failed_before_click"
    assert result["reason"] == "inbound_revision_changed"
    assert action.stage_count == 1
    assert action.click_count == 0


def test_pause_after_staging_is_rechecked_before_click() -> None:
    clock = Clock()
    candidate = _candidate()
    store = InMemoryManagedRunStore()
    observation = FixtureObservation(clock, [candidate])
    decision = FixtureDecision()
    holder: dict[str, ManagedRun] = {}

    def pause_after_stage() -> None:
        holder["runtime"].pause(reason="user_pressed_pause")

    action = FixtureAction(clock, candidate, after_stage=pause_after_stage)
    runtime = ManagedRun(store, observation, decision, action, now=clock)
    holder["runtime"] = runtime
    runtime.start(_config(), run_id="run_pause")

    result = runtime.tick()

    assert result["status"] == "paused"
    assert result["reason"] == "user_pressed_pause"
    assert action.click_count == 0
    assert runtime.status()["status"] == "paused"
    paused = store.load("run_pause")
    assert paused is not None
    assert next(iter(paused.send_attempts.values()))["status"] == "prepared_to_click"

    runtime.resume()
    resumed = runtime.tick()

    assert resumed["status"] == "confirmed"
    assert action.stage_count == 1
    assert action.click_count == 1


def test_stop_returns_only_after_an_inflight_click_boundary_finishes() -> None:
    clock = Clock()
    candidate = _candidate()
    store = InMemoryManagedRunStore()
    observation = FixtureObservation(clock, [candidate])
    action = BlockingClickAction(clock, candidate)
    runtime = ManagedRun(store, observation, FixtureDecision(), action, now=clock)
    runtime.start(_config(), run_id="run_stop_during_click")
    tick_results: list[dict[str, Any]] = []
    stop_results: list[dict[str, Any]] = []

    tick_worker = threading.Thread(target=lambda: tick_results.append(runtime.tick()), daemon=True)
    tick_worker.start()
    assert action.click_entered.wait(timeout=5)

    def stop_run() -> None:
        stop_results.append(runtime.stop(reason="user_stopped_during_click"))
        action.order.append("stop_returned")

    stop_worker = threading.Thread(target=stop_run, daemon=True)
    stop_worker.start()
    stop_worker.join(timeout=0.05)
    assert stop_worker.is_alive()

    action.release_click.set()
    tick_worker.join(timeout=5)
    stop_worker.join(timeout=5)

    assert not tick_worker.is_alive()
    assert not stop_worker.is_alive()
    assert action.order == ["click_finished", "stop_returned"]
    assert tick_results[0]["status"] == "confirmed"
    assert stop_results[0]["status"] == "stopped"
    record = store.load("run_stop_during_click")
    assert record is not None
    assert record.status == "stopped"
    assert record.confirmed_send_count == 1


def test_unknown_after_click_is_never_automatically_retried() -> None:
    clock = Clock()
    candidate = _candidate()
    observation = FixtureObservation(clock, [candidate])
    action = FixtureAction(clock, candidate, outbound_text_override="无法确认的其他文本")
    runtime, store, _, _, _, _ = _runtime(observation=observation, action=action)
    runtime.start(_config(), run_id="run_unknown")

    first = runtime.tick()
    restarted = ManagedRun(store, observation, FixtureDecision(), action, now=clock)
    second = restarted.tick()

    assert first["status"] == "unknown_after_click"
    assert first["reason"] == "outbound_text_not_exact"
    assert second["status"] == "paused"
    assert restarted.status()["run"]["pause_reason"] == "unknown_after_click"
    assert action.stage_count == 1
    assert action.click_count == 1


def test_unknown_thread_is_suppressed_in_a_later_managed_run() -> None:
    clock = Clock()
    candidate = _candidate()
    store = InMemoryManagedRunStore()
    observation = FixtureObservation(clock, [candidate])
    action = FixtureAction(clock, candidate, outbound_text_override="无法确认的其他文本")
    first_runtime = ManagedRun(store, observation, FixtureDecision(), action, now=clock)
    first_runtime.start(_config(), run_id="run_unknown_first")

    assert first_runtime.tick()["status"] == "unknown_after_click"
    assert first_runtime.stop(reason="operator_reconciled_later")["status"] == "stopped"

    second_runtime = ManagedRun(store, observation, FixtureDecision(), action, now=clock)
    started = second_runtime.start(_config(), run_id="run_unknown_second")
    result = second_runtime.tick()

    assert started["status"] == "active"
    assert result["status"] == "no_work"
    assert result["reason"] == "no_eligible_thread"
    assert action.click_count == 1
    record = store.load("run_unknown_second")
    assert record is not None
    assert record.thread_states[candidate.target_id]["last_outcome"] == "unknown_after_click"
    assert record.thread_states[candidate.target_id]["inherited_from_run_id"] == "run_unknown_first"
    assert second_runtime.status()["relationship_progress_snapshot"]["unknown_sends"] == 1


def test_unknown_click_uses_budget_and_blocks_clicking_a_second_target_after_resume() -> None:
    clock = Clock()
    first = _candidate()
    second = ThreadCandidate(
        candidate_key="row_2",
        target_id="match_bob",
        target_binding="visual-anchor:bob-v1",
        inbound_revision="inbound_3",
        priority=2,
    )
    store = InMemoryManagedRunStore()
    observation = FixtureObservation(clock, [first, second])
    action = FixtureAction(clock, first, outbound_text_override="无法确认的其他文本")
    runtime = ManagedRun(store, observation, FixtureDecision(), action, now=clock)
    runtime.start(_config(max_sends_per_run=1), run_id="run_unknown_budget")

    first_result = runtime.run(max_steps=5)
    runtime.resume()
    second_result = runtime.tick()

    assert first_result["status"] == "unknown_after_click"
    assert len(first_result["steps"]) == 1
    assert second_result["status"] == "stopped"
    assert second_result["reason"] == "send_budget_exhausted"
    assert second_result["relationship_progress_report"]["unknown_sends"] == 1
    assert action.click_count == 1
    record = store.load("run_unknown_budget")
    assert record is not None
    assert record.status == "stopped"
    assert record.attempted_send_count == 1


def test_pre_click_checkpoint_survives_crash_and_resumes_without_restaging() -> None:
    clock = Clock()
    candidate = _candidate()
    store = CrashAfterPreparedStore()
    observation = FixtureObservation(clock, [candidate])
    action = FixtureAction(clock, candidate)
    original_decision = FixtureDecision("原始的精确草稿")
    runtime = ManagedRun(store, observation, original_decision, action, now=clock)
    runtime.start(_config(), run_id="run_crash")

    with pytest.raises(SimulatedProcessCrash):
        runtime.tick()

    crashed = store.load("run_crash")
    assert crashed is not None
    assert next(iter(crashed.send_attempts.values()))["status"] == "prepared_to_click"
    assert action.stage_count == 1
    assert action.click_count == 0

    replacement_decision = FixtureDecision("重启后模型生成的不同草稿")
    restarted = ManagedRun(store, observation, replacement_decision, action, now=clock)
    result = restarted.tick()

    assert result["status"] == "confirmed"
    assert action.stage_count == 1
    assert action.click_count == 1
    assert action.last_clicked_text == "原始的精确草稿"
    assert replacement_decision.calls == ["prioritize"]


def test_crash_saving_click_receipt_recovers_as_unknown_without_second_click() -> None:
    clock = Clock()
    candidate = _candidate()
    store = CrashBeforeClickCommittedSaveStore()
    observation = FixtureObservation(clock, [candidate])
    action = FixtureAction(clock, candidate)
    runtime = ManagedRun(store, observation, FixtureDecision(), action, now=clock)
    runtime.start(_config(), run_id="run_click_save_crash")

    with pytest.raises(SimulatedProcessCrash):
        runtime.tick()

    crashed = store.load("run_click_save_crash")
    assert crashed is not None
    assert next(iter(crashed.send_attempts.values()))["status"] == "click_started"
    assert crashed.attempted_send_count == 1
    assert action.click_count == 1

    # A successful click may remove the unread row from the next scan. Recovery
    # must reconcile the durable click checkpoint before relying on candidates.
    observation.candidates = ()
    restarted = ManagedRun(store, observation, FixtureDecision(), action, now=clock)
    result = restarted.tick()

    assert result["status"] == "unknown_after_click"
    assert restarted.status()["status"] == "paused"
    assert action.click_count == 1


def test_confirmed_attempt_and_thread_state_survive_a_crash_without_duplicate_click() -> None:
    clock = Clock()
    candidate = _candidate()
    store = CrashAfterConfirmedStore()
    observation = FixtureObservation(clock, [candidate])
    action = FixtureAction(clock, candidate)
    runtime = ManagedRun(store, observation, FixtureDecision(), action, now=clock)
    runtime.start(_config(), run_id="run_confirmed_crash")

    with pytest.raises(SimulatedProcessCrash):
        runtime.tick()

    crashed = store.load("run_confirmed_crash")
    assert crashed is not None
    assert crashed.confirmed_send_count == 1
    assert next(iter(crashed.send_attempts.values()))["status"] == "confirmed"
    assert crashed.thread_states[candidate.target_id]["last_outcome"] == "confirmed"

    restarted = ManagedRun(store, observation, FixtureDecision("不同的新草稿"), action, now=clock)
    result = restarted.tick()

    assert result["status"] == "no_work"
    assert result["reason"] == "no_eligible_thread"
    assert action.click_count == 1
    recovered = store.load("run_confirmed_crash")
    assert recovered is not None
    assert recovered.confirmed_send_count == 1


def test_concurrent_start_creates_only_one_active_run() -> None:
    clock = Clock()
    store = BlockingCreateStore()
    candidate = _candidate()
    observation = FixtureObservation(clock, [candidate])
    action = FixtureAction(clock, candidate)
    first_runtime = ManagedRun(store, observation, FixtureDecision(), action, now=clock)
    second_runtime = ManagedRun(store, observation, FixtureDecision(), action, now=clock)
    first_result: list[dict[str, Any]] = []

    thread = threading.Thread(target=lambda: first_result.append(first_runtime.start(_config(), run_id="run_first")))
    thread.start()
    assert store.entered.wait(timeout=5)

    second_result = second_runtime.start(_config(), run_id="run_second")
    store.release.set()
    thread.join(timeout=5)

    assert first_result[0]["status"] == "active"
    assert second_result == {"schema_version": 1, "status": "blocked", "reason": "managed_run_busy"}
    assert store.current_run_id() == "run_first"
    assert store.load("run_second") is None


def test_authorization_contract_and_quiet_hours_block_before_gui_observation() -> None:
    runtime, _, observation, _, action, _ = _runtime()
    invalid_payload = _config().to_dict()
    invalid_payload["authorization"]["scope"] = "draft_only"

    invalid = runtime.start(ManagedRunConfig.from_dict(invalid_payload), run_id="run_invalid_scope")

    assert invalid["status"] == "blocked"
    assert invalid["reason"] == "authorization_scope_not_send_chat_messages"
    assert observation.calls == []
    assert action.calls == []

    quiet_runtime, _, quiet_observation, _, quiet_action, _ = _runtime()
    quiet_runtime.start(
        _config(quiet_hours=({"start": "00:00", "end": "23:59"},)),
        run_id="run_quiet",
    )

    quiet = quiet_runtime.tick()

    assert quiet["status"] == "no_work"
    assert quiet["reason"] == "authorization_quiet_hours"
    assert quiet_observation.calls == []
    assert quiet_action.calls == []


def test_invalid_quiet_hours_fail_closed_at_direct_core_start() -> None:
    runtime, _, observation, _, action, _ = _runtime()

    result = runtime.start(
        _config(quiet_hours=({"start": "not-a-time", "end": "08:00"},)),
        run_id="run_invalid_quiet_hours",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "authorization_quiet_hours_invalid"
    assert observation.calls == []
    assert action.calls == []


def test_managed_run_config_defaults_nudge_to_disabled() -> None:
    payload = _config(nudge_enabled=True).to_dict()
    payload.pop("nudge_enabled")

    restored = ManagedRunConfig.from_dict(payload)

    assert restored.nudge_enabled is False


def test_duration_is_rechecked_after_staging_before_click() -> None:
    clock = Clock()
    candidate = _candidate()
    observation = FixtureObservation(clock, [candidate])

    def expire_run_after_stage() -> None:
        clock.value += timedelta(minutes=2)

    action = FixtureAction(clock, candidate, after_stage=expire_run_after_stage)
    runtime, store, _, _, _, _ = _runtime(observation=observation, action=action)
    runtime.start(_config(duration_minutes=1), run_id="run_expired_after_stage")

    result = runtime.tick()

    assert result["status"] == "stopped"
    assert result["reason"] == "managed_run_duration_elapsed"
    assert action.stage_count == 1
    assert action.click_count == 0
    record = store.load("run_expired_after_stage")
    assert record is not None
    assert record.status == "stopped"
    assert next(iter(record.send_attempts.values()))["status"] == "prepared_to_click"


def test_stale_composer_and_post_send_observations_are_rejected() -> None:
    clock = Clock()
    candidate = _candidate()
    stale = "2026-08-27T03:00:00Z"
    observation = FixtureObservation(clock, [candidate])
    stale_composer_action = FixtureAction(clock, candidate, composer_captured_at_override=stale)
    composer_runtime, _, _, _, _, _ = _runtime(observation=observation, action=stale_composer_action)
    composer_runtime.start(_config(), run_id="run_stale_composer")

    composer_result = composer_runtime.tick()

    assert composer_result["status"] == "failed_before_click"
    assert composer_result["reason"] == "composer_observation_not_fresh"
    assert stale_composer_action.stage_count == 1

    post_clock = Clock()
    post_observation = FixtureObservation(post_clock, [candidate])
    stale_post_action = FixtureAction(post_clock, candidate, post_captured_at_override=stale)
    post_runtime, _, _, _, _, _ = _runtime(observation=post_observation, action=stale_post_action)
    post_runtime.start(_config(), run_id="run_stale_post")

    post_result = post_runtime.tick()

    assert post_result["status"] == "unknown_after_click"
    assert post_result["reason"] == "post_send_observation_not_fresh"
    assert post_runtime.status()["status"] == "paused"


def test_unauthorized_target_never_reaches_composer() -> None:
    runtime, _, _, _, action, _ = _runtime()
    runtime.start(_config(allow_target=False), run_id="run_unauthorized")

    result = runtime.tick()

    assert result["status"] == "failed_before_click"
    assert result["reason"] == "target_not_authorized"
    assert action.calls == []


def test_pause_resume_stop_and_duration_are_durable_run_state() -> None:
    runtime, _, _, _, action, clock = _runtime()
    runtime.start(_config(duration_minutes=1), run_id="run_lifecycle")

    assert runtime.pause(reason="taking_over")["status"] == "paused"
    assert runtime.status()["relationship_progress_snapshot"]["send_budget_remaining"] == 100
    assert runtime.tick()["status"] == "paused"
    assert runtime.resume()["status"] == "active"
    clock.value += timedelta(minutes=2)
    assert runtime.tick()["status"] == "stopped"
    assert runtime.status()["run"]["stop_reason"] == "managed_run_duration_elapsed"
    assert action.click_count == 0


def test_stop_returns_compact_relationship_progress_report() -> None:
    runtime, _, _, _, _, _ = _runtime()
    runtime.start(_config(), run_id="run_report")
    assert runtime.tick()["status"] == "confirmed"

    stopped = runtime.stop(reason="user_finished")

    report = stopped["relationship_progress_report"]
    assert report["checked_threads"] == 1
    assert report["verified_sends"] == 1
    assert report["unknown_sends"] == 0
    assert "验证发送 1 条" in report["summary"]


def test_json_store_recovers_current_run_and_send_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    clock = Clock()
    candidate = _candidate()
    observation = FixtureObservation(clock, [candidate])
    action = FixtureAction(clock, candidate)
    first_store = JsonManagedRunStore(tmp_path)
    first_runtime = ManagedRun(first_store, observation, FixtureDecision(), action, now=clock)
    first_runtime.start(_config(), run_id="run_json")
    assert first_runtime.tick()["status"] == "confirmed"

    reopened_store = JsonManagedRunStore(tmp_path)
    reopened_runtime = ManagedRun(reopened_store, observation, FixtureDecision(), action, now=clock)
    status = reopened_runtime.status()

    assert reopened_store.current_run_id() == "run_json"
    assert status["status"] == "active"
    assert status["run"]["attempted_send_count"] == 1
    assert status["run"]["confirmed_send_count"] == 1
    assert next(iter(status["run"]["send_attempts"].values()))["status"] == "confirmed"


def test_json_start_recovers_when_a_hard_crash_leaves_index_pointing_to_no_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    clock = Clock()
    candidate = _candidate()
    observation = FixtureObservation(clock, [candidate])
    action = FixtureAction(clock, candidate)
    crashed_store = JsonManagedRunStore(tmp_path)
    crashed_runtime = ManagedRun(crashed_store, observation, FixtureDecision(), action, now=clock)
    original_write_json = crashed_store._storage.write_json
    crashed_run_path = crashed_store._run_path("run_orphaned_index")

    def hard_crash_before_run_document(relative_path: Path, payload: dict[str, Any]) -> None:
        if relative_path == crashed_run_path:
            raise SimulatedHardCrash
        original_write_json(relative_path, payload)

    monkeypatch.setattr(crashed_store._storage, "write_json", hard_crash_before_run_document)

    with pytest.raises(SimulatedHardCrash):
        crashed_runtime.start(_config(), run_id="run_orphaned_index")

    assert crashed_store.current_run_id() == "run_orphaned_index"
    assert crashed_store.load("run_orphaned_index") is None

    recovered_store = JsonManagedRunStore(tmp_path)
    recovered_runtime = ManagedRun(recovered_store, observation, FixtureDecision(), action, now=clock)
    recovered = recovered_runtime.start(_config(), run_id="run_after_orphan")

    assert recovered["status"] == "active"
    assert recovered_store.current_run_id() == "run_after_orphan"
    assert recovered_store.load("run_after_orphan") is not None


def test_two_runners_on_one_run_have_one_nonblocking_execution_lease_and_one_click() -> None:
    clock = Clock()
    candidate = _candidate()
    store = InMemoryManagedRunStore()
    observation = BlockingOnceObservation(clock, [candidate])
    decision = FixtureDecision()
    action = FixtureAction(clock, candidate)
    first = ManagedRun(store, observation, decision, action, now=clock)
    second = ManagedRun(store, observation, decision, action, now=clock)
    first.start(_config(), run_id="run_concurrent")
    first_results: list[dict[str, Any]] = []

    worker = threading.Thread(target=lambda: first_results.append(first.tick()), daemon=True)
    worker.start()
    assert observation.entered.wait(timeout=2)

    before = store.load("run_concurrent")
    before_events = store.events("run_concurrent")
    busy = second.tick()
    after_busy = store.load("run_concurrent")
    after_busy_events = store.events("run_concurrent")

    assert busy == {
        "schema_version": 1,
        "status": "blocked",
        "reason": "managed_run_busy",
        "run_id": "run_concurrent",
    }
    assert before is not None and after_busy is not None
    assert after_busy.to_dict() == before.to_dict()
    assert after_busy_events == before_events
    assert action.click_count == 0

    observation.release.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert first_results[0]["status"] == "confirmed"
    assert action.click_count == 1


def test_json_execution_lease_is_shared_by_store_instances_and_private(tmp_path: Path) -> None:
    first = JsonManagedRunStore(tmp_path)
    second = JsonManagedRunStore(tmp_path)
    run_id = "run_json_lease"

    with first.execution_lease(run_id) as first_acquired:
        with second.execution_lease(run_id) as second_acquired:
            assert first_acquired is True
            assert second_acquired is False

    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
    lock_path = tmp_path / "managed_run" / "locks" / f"{digest}.lock"
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600


def test_run_processes_one_full_chain_then_becomes_idle() -> None:
    runtime, _, _, _, action, _ = _runtime()
    runtime.start(_config(), run_id="run_until_idle")

    result = runtime.run(max_steps=5)

    assert result["status"] == "no_work"
    assert result["processed_count"] == 1
    assert [step["status"] for step in result["steps"]] == ["confirmed", "no_work"]
    assert action.click_count == 1


def test_wait_run_sleeps_after_idle_then_continues_same_run_until_budget() -> None:
    clock = Clock()
    candidate = _candidate()
    store = InMemoryManagedRunStore()
    observation = SequencedObservation(clock, [(), (candidate,)])
    action = FixtureAction(clock, candidate)
    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        clock.value += timedelta(seconds=seconds)

    runtime = ManagedRun(
        store,
        observation,
        FixtureDecision(),
        action,
        now=clock,
        sleeper=fake_sleep,
    )
    runtime.start(_config(max_sends_per_run=1), run_id="run_wait")

    result = runtime.run(
        max_steps=1,
        wait=True,
        poll_interval_seconds=2.5,
    )

    assert result["status"] == "stopped"
    assert result["reason"] == "send_budget_exhausted"
    assert result["poll_count"] == 1
    assert result["wait"] is True
    assert [step["status"] for step in result["steps"]] == ["no_work", "confirmed", "stopped"]
    assert result["relationship_progress_report"]["verified_sends"] == 1
    assert sleep_calls == [2.5]
    assert action.click_count == 1
    assert runtime.current_run_id() == "run_wait"
    assert runtime.status()["status"] == "stopped"


def test_wait_run_sleeps_after_an_early_candidate_failure_instead_of_spinning() -> None:
    clock = Clock()
    candidate = _candidate()
    store = InMemoryManagedRunStore()
    observation = FixtureObservation(clock, [candidate], opened_target_id="wrong_target")
    action = FixtureAction(clock, candidate)
    holder: dict[str, ManagedRun] = {}
    sleep_calls: list[float] = []

    def stop_after_idle(seconds: float) -> None:
        sleep_calls.append(seconds)
        holder["runtime"].stop(reason="test_finished_after_idle")

    runtime = ManagedRun(
        store,
        observation,
        FixtureDecision(),
        action,
        now=clock,
        sleeper=stop_after_idle,
    )
    holder["runtime"] = runtime
    runtime.start(_config(), run_id="run_failed_candidate_wait")

    result = runtime.run(wait=True, poll_interval_seconds=0.5)

    assert result["status"] == "stopped"
    assert result["reason"] == "test_finished_after_idle"
    assert [step["status"] for step in result["steps"]] == [
        "failed_before_click",
        "no_work",
        "stopped",
    ]
    assert result["processed_count"] == 1
    assert result["poll_count"] == 1
    assert sleep_calls == [0.5]
    assert observation.calls.count("scan") == 2
    assert observation.calls.count("open") == 1
    assert action.click_count == 0


def test_wait_run_rechecks_a_deferred_nudge_after_sleep_and_then_sends() -> None:
    clock = Clock()
    candidate = _candidate()
    store = InMemoryManagedRunStore()
    due_at = (clock.value + timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
    observation = FixtureObservation(
        clock,
        [candidate],
        thread_context={
            "standalone_thread_observation": {
                "assessment": {
                    "recommended_next": "nudge_later",
                    "nudge_due_at": due_at,
                }
            }
        },
    )
    decision = MaturingNudgeDecision()
    action = FixtureAction(clock, candidate)
    sleep_calls: list[float] = []

    def advance_time(seconds: float) -> None:
        sleep_calls.append(seconds)
        clock.value += timedelta(seconds=seconds)

    runtime = ManagedRun(
        store,
        observation,
        decision,
        action,
        now=clock,
        sleeper=advance_time,
    )
    runtime.start(
        _config(nudge_enabled=True, max_sends_per_run=1),
        run_id="run_maturing_nudge",
    )

    result = runtime.run(wait=True, poll_interval_seconds=30.0)

    assert result["status"] == "stopped"
    assert result["reason"] == "send_budget_exhausted"
    assert [step["status"] for step in result["steps"]] == [
        "wait",
        "no_work",
        "confirmed",
        "stopped",
    ]
    assert result["poll_count"] == 2
    assert sleep_calls == [30.0, 30.0]
    assert decision.decision_count == 2
    assert observation.calls.count("scan") == 3
    assert observation.calls.count("open") == 2
    assert observation.calls.count("observe") == 2
    assert action.click_count == 1


def test_wait_run_exits_paused_without_sleeping_again_and_resume_continues_same_run() -> None:
    clock = Clock()
    candidate = _candidate()
    store = InMemoryManagedRunStore()
    observation = SequencedObservation(clock, [(), (candidate,)])
    action = FixtureAction(clock, candidate)
    holder: dict[str, ManagedRun] = {}
    sleep_calls: list[float] = []

    def pause_instead_of_real_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        holder["runtime"].pause(reason="user_pause_during_wait")

    runtime = ManagedRun(
        store,
        observation,
        FixtureDecision(),
        action,
        now=clock,
        sleeper=pause_instead_of_real_sleep,
    )
    holder["runtime"] = runtime
    runtime.start(_config(max_sends_per_run=1), run_id="run_wait_pause")

    paused = runtime.run(wait=True, poll_interval_seconds=3.0)

    assert paused["status"] == "paused"
    assert paused["reason"] == "user_pause_during_wait"
    assert paused["poll_count"] == 1
    assert sleep_calls == [3.0]
    assert action.click_count == 0

    runtime.resume()
    resumed = runtime.run(max_steps=5)

    assert resumed["reason"] == "send_budget_exhausted"
    assert action.click_count == 1
    assert runtime.current_run_id() == "run_wait_pause"


def test_wait_run_uses_injected_sleep_to_reach_duration_stop() -> None:
    clock = Clock()
    candidate = _candidate()
    observation = SequencedObservation(clock, [()])
    sleep_calls: list[float] = []

    def advance_past_duration(seconds: float) -> None:
        sleep_calls.append(seconds)
        clock.value += timedelta(seconds=61)

    runtime = ManagedRun(
        InMemoryManagedRunStore(),
        observation,
        FixtureDecision(),
        FixtureAction(clock, candidate),
        now=clock,
        sleeper=advance_past_duration,
    )
    runtime.start(_config(duration_minutes=1), run_id="run_wait_duration")

    result = runtime.run(wait=True, poll_interval_seconds=0.25)

    assert result["status"] == "stopped"
    assert result["reason"] == "managed_run_duration_elapsed"
    assert result["poll_count"] == 1
    assert sleep_calls == [0.25]
