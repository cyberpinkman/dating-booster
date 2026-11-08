from __future__ import annotations

import hashlib
import stat
import threading
from datetime import datetime, timedelta, timezone
from dataclasses import replace
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
    ManagedActionError,
    ManagedClickBlocked,
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
            inbound_revision=self.thread_revision or candidate.discovery_revision,
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


class FailingScanObservation(FixtureObservation):
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
        raise RuntimeError("fixture scan failure")


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


class FailingPrioritizationDecision(FixtureDecision):
    def prioritize(
        self,
        candidates: Sequence[ThreadCandidate],
        *,
        thread_states: Mapping[str, dict[str, Any]],
    ) -> ThreadCandidate | None:
        del candidates, thread_states
        raise RuntimeError("fixture prioritization failure")


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


class FailingEventStore(InMemoryManagedRunStore):
    def append_event(self, event: dict[str, Any]) -> None:
        del event
        raise RuntimeError("fixture diagnostic event failure")


class SimulatedProcessCrash(RuntimeError):
    pass


class SimulatedHardCrash(BaseException):
    pass


def _candidate() -> ThreadCandidate:
    return ThreadCandidate(
        candidate_key="row_1",
        target_id="match_alice",
        target_binding="visual-anchor:alice-v1",
        discovery_revision="inbound_7",
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


@pytest.mark.parametrize("boundary,reason", [
    ("scan_message_list", "message_list_observation_failed"),
    ("open_thread", "open_thread_failed"),
    ("observe_thread", "thread_observation_failed"),
])
@pytest.mark.parametrize("error,action_reason", [
    (ManagedActionError("managed_conversation_text_not_accessible"), "managed_conversation_text_not_accessible"),
    (ManagedActionError("private raw error text"), "managed_action_failed"),
    (RuntimeError("managed_conversation_text_not_accessible private raw error text"), None),
])
def test_observation_failures_preserve_only_controlled_reasons_without_decision_or_send(boundary, reason, error, action_reason) -> None:
    runtime, store, observation, decision, action, clock = _runtime()

    def inaccessible(*args, **kwargs):
        raise error

    setattr(observation, boundary, inaccessible)
    runtime.start(_config(), run_id="coverage")
    result = runtime.tick()
    assert result["status"] == "paused"
    assert result["reason"] == reason
    assert result["error_type"] == type(error).__name__
    saved = store.load("coverage")
    assert saved.status == "paused" and saved.pause_reason == reason
    assert result.get("action_reason") == saved.last_result.get("action_reason") == action_reason
    events = store.events("coverage")
    if action_reason:
        assert any(event.get("action_reason") == action_reason for event in events)
    else:
        assert "action_reason" not in result and "action_reason" not in saved.last_result
    assert "private raw error text" not in str((result, saved.to_dict(), events))
    assert "decide" not in decision.calls
    assert action.calls == []


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
        "tick_profile",
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


def test_unknown_send_blocks_start_after_stop_without_resetting_budget_or_history() -> None:
    clock = Clock()
    candidate = _candidate()
    store = InMemoryManagedRunStore()
    observation = FixtureObservation(clock, [candidate])
    action = FixtureAction(clock, candidate, outbound_text_override="无法确认的其他文本")
    first_runtime = ManagedRun(store, observation, FixtureDecision(), action, now=clock)
    first_runtime.start(_config(), run_id="run_unknown_first")

    assert first_runtime.tick()["status"] == "unknown_after_click"
    assert first_runtime.stop(reason="operator_reconciled_later")["status"] == "stopped"
    before_restart = store.load("run_unknown_first").to_dict()

    second_runtime = ManagedRun(store, observation, FixtureDecision(), action, now=clock)
    started = second_runtime.start(_config(), run_id="run_unknown_second")
    result = second_runtime.tick()

    assert started["status"] == "blocked"
    assert started["reason"] == "unknown_after_click_requires_reconciliation"
    assert result["status"] == "stopped"
    assert action.click_count == 1
    assert store.load("run_unknown_second") is None
    assert store.current_run_id() == "run_unknown_first"
    assert store.load("run_unknown_first").to_dict() == before_restart
    assert second_runtime.status()["relationship_progress_snapshot"]["unknown_sends"] == 1


class RecoveryAction(FixtureAction):
    def __init__(self, clock: Clock, candidate: ThreadCandidate):
        super().__init__(clock, candidate, outbound_text_override="different observed text")
        self.recover_calls: list[dict[str, Any]] = []
        self.transform: Callable[[PostSendObservation], Any] = lambda post: post

    def recover_send(self, attempt: dict[str, Any]) -> PostSendObservation:
        self.recover_calls.append(attempt)
        return self.transform(PostSendObservation(
            observation_id="recovered_post", receipt_id=attempt["receipt_id"],
            target_id=attempt["target_id"], target_binding=attempt["target_binding"],
            captured_at=self.clock.tick(), input_cleared=True,
            outbound_text=attempt["exact_text"], recovery_evidence_digest="a" * 64,
        ))


def _recovery_runtime(store=None):
    clock = Clock()
    action = RecoveryAction(clock, _candidate())
    runtime, store, observation, decision, _, _ = _runtime(store=store, action=action)
    runtime.start(_config(max_sends_per_run=3), run_id="run_recovery")
    assert runtime.tick()["status"] == "unknown_after_click"
    return runtime, store, observation, decision, action


def test_reconcile_supports_run_id_that_matches_the_start_lease() -> None:
    action = RecoveryAction(Clock(), _candidate())
    runtime, *_ = _runtime(action=action)
    runtime.start(_config(), run_id="__managed_run_start__")
    assert runtime.tick()["status"] == "unknown_after_click"
    assert runtime.reconcile()["status"] == "reconciled"
    assert runtime.reconcile()["already_reconciled"] is True
    assert len(action.recover_calls) == 1


@pytest.mark.parametrize("lineage", ["verified", "binding_changed", "cycle", "second_unknown"])
def test_reconciliation_of_original_attempt_resolves_only_its_legacy_lineage(lineage) -> None:
    runtime, store, _, _, action = _recovery_runtime()
    runtime.stop()
    source = store.load("run_recovery")
    target_id, source_state = next(iter(source.thread_states.items()))
    # Older versions allowed starting additional runs after an unknown send.
    # They copied the original identity and pointed at the immediately prior run.
    previous = source
    for run_id in ("legacy_1", "legacy_2"):
        inherited = {**source_state, "inherited_from_run_id": previous.run_id}
        previous = replace(
            previous, run_id=run_id, send_attempts={}, send_reconciliations={},
            thread_states={target_id: inherited}, attempted_send_count=0,
        )
        store.create(previous)

    first = store.load("legacy_1")
    if lineage == "binding_changed":
        first.thread_states[target_id]["target_binding"] = "a different thread"
    if lineage == "cycle":
        first.thread_states[target_id]["inherited_from_run_id"] = "legacy_2"
    if lineage == "second_unknown":
        first.send_attempts["other_decision"] = {"status": "unknown_after_click", "target_id": target_id}
    store.save(first)
    assert runtime.start(_config())["reason"] == "unknown_after_click_requires_reconciliation"
    assert runtime.reconcile(source.run_id)["status"] == "reconciled"
    expected_unknown = 0 if lineage == "verified" else 1
    assert runtime.status()["relationship_progress_snapshot"]["unknown_sends"] == expected_unknown
    result = runtime.start(_config(), run_id="new_run")
    if lineage == "verified":
        assert result["status"] == "active"
        assert result["relationship_progress_snapshot"]["unknown_sends"] == 0
    else:
        assert result["reason"] == "unknown_after_click_requires_reconciliation"
    assert store.load("legacy_2") == previous
    assert store.load(source.run_id).confirmed_send_count == action.click_count == 1


@pytest.mark.parametrize("stopped", [False, True])
def test_reconcile_preserves_attempt_budget_lifecycle_and_cancelled_tail_and_is_idempotent(stopped) -> None:
    runtime, store, observation, decision, action = _recovery_runtime()
    if stopped:
        runtime.stop()
    before = store.load("run_recovery")
    key = next(iter(before.send_attempts))
    before.send_bursts["cancelled_burst"] = {"status": "cancelled", "messages": ["first", "cancelled tail"]}
    store.save(before)
    observed_calls, decision_calls, action_calls = list(observation.calls), list(decision.calls), list(action.calls)

    result = runtime.reconcile()
    committed = store.load(before.run_id)
    again = runtime.reconcile(decision_key=key)

    assert result["status"] == again["status"] == "reconciled"
    assert again["already_reconciled"] is True
    assert result["reconciliation_id"] == again["reconciliation_id"]
    assert committed.status == before.status
    assert committed.send_attempts == before.send_attempts
    assert committed.send_bursts == before.send_bursts
    assert committed.thread_states == before.thread_states
    assert committed.attempted_send_count == before.attempted_send_count == 1
    assert committed.confirmed_send_count == store.load(before.run_id).confirmed_send_count == 1
    assert result["relationship_progress_snapshot"]["unknown_sends"] == 0
    assert result["relationship_progress_snapshot"]["reconciled_sends"] == 1
    assert len(action.recover_calls) == 1
    assert action.recover_calls[0]["run_id"] == before.run_id
    assert (observation.calls, decision.calls, action.calls) == (observed_calls, decision_calls, action_calls)
    assert ManagedRunRecord.from_dict(committed.to_dict()).send_reconciliations == committed.send_reconciliations
    if stopped:
        assert runtime.start(_config(), run_id="replacement")["status"] == "active"
    else:
        assert runtime.resume()["status"] == "active"
        assert runtime.tick()["status"] == "no_work"
    assert action.click_count == 1
    assert len(action.recover_calls) == 1


@pytest.mark.parametrize("changes,reason", [
    ({"recovery_evidence_digest": None}, "managed_recovery_evidence_missing"),
    ({"recovery_evidence_digest": "a" * 63}, "managed_recovery_evidence_missing"),
    ({"observation_id": ""}, "post_send_observation_id_missing"),
    ({"receipt_id": "another_receipt"}, "post_send_receipt_mismatch"),
    ({"target_id": "another_target"}, "managed_recovery_target_mismatch"),
    ({"target_binding": "another_binding"}, "managed_recovery_target_mismatch"),
    ({"captured_at": "2020-01-01T00:00:00Z"}, "managed_recovery_observation_not_fresh"),
    ({"captured_at": "2026-08-27T04:01:00"}, "managed_recovery_observation_not_fresh"),
    ({"input_cleared": 1}, "composer_not_cleared_after_click"),
    ({"outbound_text": "different exact text"}, "outbound_text_not_exact"),
])
def test_reconcile_rejects_incomplete_or_mismatched_proof_without_mutation(changes, reason) -> None:
    runtime, store, _, _, action = _recovery_runtime()
    before = store.load("run_recovery").to_dict()
    action.transform = lambda post: replace(post, **changes)
    result = runtime.reconcile()
    assert result["status"] == "blocked"
    assert result["reason"] == reason
    assert store.load("run_recovery").to_dict() == before
    assert action.stage_count == action.click_count == 1


@pytest.mark.parametrize("field,value,reason", [
    ("receipt_id", "", "managed_recovery_attempt_incomplete"),
    ("decision_key", "other", "managed_recovery_attempt_mismatch"),
    ("payload_hash", "f" * 64, "managed_recovery_payload_hash_mismatch"),
    ("clicked_at", "bad", "managed_recovery_click_time_invalid"),
])
def test_reconcile_checks_stored_attempt_before_recovery_port(field, value, reason) -> None:
    runtime, store, _, _, action = _recovery_runtime()
    record = store.load("run_recovery")
    key = next(iter(record.send_attempts))
    record.send_attempts[key][field] = value
    store.save(record)
    before = record.to_dict()
    assert runtime.reconcile()["reason"] == reason
    assert action.recover_calls == []
    assert store.load(record.run_id).to_dict() == before


def test_reconcile_does_not_accept_success_mapping_or_mutated_attempt_and_sanitizes_errors() -> None:
    runtime, store, _, _, action = _recovery_runtime()
    before = store.load("run_recovery").to_dict()
    action.transform = lambda post: {"success": True, "expected_text": "untrusted"}
    assert runtime.reconcile()["reason"] == "managed_recovery_observation_invalid"

    def failing_recovery(attempt):
        attempt["exact_text"] = "modified by recovery port"
        raise RuntimeError("private raw text")

    action.recover_send = failing_recovery
    result = runtime.reconcile()
    assert result["reason"] == "managed_recovery_failed"
    assert "private raw text" not in str(result)
    assert store.load("run_recovery").to_dict() == before


def test_reconcile_rechecks_attempt_after_observation_and_rejects_equal_capture_time() -> None:
    runtime, store, _, _, action = _recovery_runtime()
    record = store.load("run_recovery")
    key = next(iter(record.send_attempts))
    action.transform = lambda post: replace(post, captured_at=record.send_attempts[key]["clicked_at"])
    assert runtime.reconcile()["reason"] == "managed_recovery_observation_not_fresh"
    assert store.load(record.run_id).to_dict() == record.to_dict()

    def changed_during_observation(post):
        changed = store.load(record.run_id)
        changed.send_attempts[key]["receipt_id"] = "different_receipt"
        store.save(changed)
        return post

    action.transform = changed_during_observation
    assert runtime.reconcile()["reason"] == "managed_reconciliation_attempt_changed"
    assert store.load(record.run_id).send_reconciliations == {}
    assert store.load(record.run_id).confirmed_send_count == 0


def test_reconcile_requires_unknown_attempt_and_optional_recovery_capability() -> None:
    runtime, store, _, _, action = _recovery_runtime()
    record = store.load("run_recovery")
    assert runtime.reconcile(decision_key="nonexistent")["reason"] == "managed_reconciliation_attempt_not_unknown"
    runtime.action = FixtureAction(action.clock, _candidate())
    assert runtime.reconcile()["reason"] == "managed_recovery_unavailable"
    assert store.load(record.run_id).to_dict() == record.to_dict()
    assert action.recover_calls == []


@pytest.mark.parametrize("source", ["second_attempt", "orphan_state", "corrupted_reconciliation"])
def test_reconcile_cannot_clear_other_unknown_or_unbound_state(source) -> None:
    runtime, store, observation, _, action = _recovery_runtime()
    record = store.load("run_recovery")
    key = next(iter(record.send_attempts))
    if source == "second_attempt":
        record.send_attempts["another"] = {**record.send_attempts[key], "decision_key": "another", "receipt_id": "other"}
        store.save(record)
        assert runtime.reconcile()["reason"] == "managed_reconciliation_attempt_required"
        assert action.recover_calls == []
    elif source == "orphan_state":
        record.thread_states["orphan"] = {"last_outcome": "unknown_after_click"}
        store.save(record)
    assert runtime.reconcile(decision_key=key)["status"] == "reconciled"
    if source == "corrupted_reconciliation":
        record = store.load(record.run_id)
        record.send_reconciliations[key]["receipt_id"] = "other"
        store.save(record)
        assert runtime.reconcile(decision_key=key)["reason"] == "managed_reconciliation_conflict"
    assert runtime.resume()["reason"] == "unknown_after_click_requires_reconciliation"
    calls = list(observation.calls)
    record = store.load(record.run_id)
    record.status = "active"  # An older caller must not bypass the shared gate.
    store.save(record)
    assert runtime.tick()["status"] == "paused"
    assert observation.calls == calls
    runtime.stop()
    assert runtime.start(_config(), run_id="replacement")["reason"] == "unknown_after_click_requires_reconciliation"
    assert action.click_count == 1


@pytest.mark.parametrize("failure", ["before_save", "after_save", "event"])
def test_reconciliation_commit_survives_crash_and_diagnostic_failures(failure, monkeypatch) -> None:
    runtime, store, _, _, action = _recovery_runtime()
    before = store.load("run_recovery").to_dict()
    original_save = store.save

    def save(record):
        if failure == "before_save":
            raise RuntimeError("write failed")
        original_save(record)
        if failure == "after_save":
            raise SimulatedHardCrash

    monkeypatch.setattr(store, "save", save)
    if failure == "event":
        monkeypatch.setattr(store, "append_event", lambda event: (_ for _ in ()).throw(RuntimeError("event failed")))
    if failure == "after_save":
        with pytest.raises(SimulatedHardCrash):
            runtime.reconcile()
        result = runtime.reconcile()
    else:
        result = runtime.reconcile()
    saved = store.load("run_recovery")
    if failure == "before_save":
        assert result["reason"] == "managed_reconciliation_save_failed"
        assert saved.to_dict() == before
    else:
        assert result["status"] == "reconciled"
        assert saved.confirmed_send_count == 1
        assert len(saved.send_reconciliations) == 1
    assert len(action.recover_calls) == 1


def test_reconciliation_excludes_tick_start_and_parallel_recovery_and_preserves_concurrent_stop() -> None:
    runtime, store, _, _, action = _recovery_runtime()
    entered, release = threading.Event(), threading.Event()

    def blocked(post):
        entered.set()
        assert release.wait(timeout=5)
        return post

    action.transform = blocked
    results = []
    worker = threading.Thread(target=lambda: results.append(runtime.reconcile()))
    worker.start()
    assert entered.wait(timeout=5)
    try:
        assert runtime.tick()["reason"] == "managed_run_busy"
        assert runtime.reconcile()["reason"] == "managed_run_busy"
        assert runtime.start(_config(), run_id="replacement")["reason"] == "managed_run_busy"
        assert runtime.stop()["status"] == "stopped"
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert results[0]["status"] == "reconciled"
    assert store.load("run_recovery").status == "stopped"
    assert len(action.recover_calls) == 1
    assert action.click_count == 1


def test_reconciliation_survives_new_store_and_runtime(tmp_path) -> None:
    runtime, store, observation, decision, action = _recovery_runtime(JsonManagedRunStore(tmp_path))
    assert runtime.reconcile()["status"] == "reconciled"
    fresh = ManagedRun(JsonManagedRunStore(tmp_path), observation, decision, action, now=action.clock)
    assert fresh.reconcile()["already_reconciled"] is True
    assert len(action.recover_calls) == 1
    assert fresh.status()["relationship_progress_snapshot"]["verified_sends"] == 1


@pytest.mark.parametrize("send_budget", [1, 3])
def test_unknown_send_blocks_resume_independently_of_remaining_budget(send_budget: int) -> None:
    clock = Clock()
    first = _candidate()
    second = ThreadCandidate(
        candidate_key="row_2",
        target_id="match_bob",
        target_binding="visual-anchor:bob-v1",
        discovery_revision="inbound_3",
        priority=2,
    )
    store = InMemoryManagedRunStore()
    observation = FixtureObservation(clock, [first, second])
    action = FixtureAction(clock, first, outbound_text_override="无法确认的其他文本")
    runtime = ManagedRun(store, observation, FixtureDecision(), action, now=clock)
    config = _config(max_sends_per_run=send_budget)
    config = replace(config, authorization=replace(
        config.authorization, allowed_target_ids=(first.target_id, second.target_id),
    ))
    runtime.start(config, run_id="run_unknown_budget")

    first_result = runtime.run(max_steps=5)
    resumed = runtime.resume()
    second_result = runtime.tick()

    assert first_result["status"] == "unknown_after_click"
    assert len(first_result["steps"]) == 1
    assert resumed["status"] == "blocked"
    assert resumed["reason"] == "unknown_after_click_requires_reconciliation"
    assert second_result["status"] == "paused"
    assert second_result["reason"] == "unknown_after_click"
    assert runtime.status()["relationship_progress_snapshot"]["unknown_sends"] == 1
    assert observation.calls == ["scan", "open", "observe"]
    assert action.click_count == 1
    record = store.load("run_unknown_budget")
    assert record is not None
    assert record.status == "paused"
    assert record.attempted_send_count == 1


@pytest.mark.parametrize("unknown_source", ["attempt", "inherited_thread_state"])
@pytest.mark.parametrize("operation", ["start", "resume", "tick"])
def test_unknown_barrier_blocks_legacy_active_records_before_observation(
    unknown_source: str, operation: str,
) -> None:
    runtime, store, observation, decision, action, _ = _runtime()
    runtime.start(_config(), run_id="run_legacy_unknown")
    record = store.load("run_legacy_unknown")
    assert record is not None
    if unknown_source == "attempt":
        record.send_attempts["previous_decision"] = {
            "status": "unknown_after_click", "target_id": "old_visual_candidate_key",
            "inbound_revision": "old_revision",
        }
        record.attempted_send_count = 1
    else:
        record.thread_states["old_visual_candidate_key"] = {
            "last_outcome": "unknown_after_click", "last_inbound_revision": "old_revision",
            "inherited_from_run_id": "previous_run",
        }
    # The visible fixture has a different target/key/revision. No identity guess
    # may allow an unresolved click to be bypassed, even in an older active run.
    store.save(record)

    result = (
        runtime.start(_config(), run_id="replacement_run")
        if operation == "start" else getattr(runtime, operation)()
    )

    assert result["status"] == ("paused" if operation == "tick" else "blocked")
    assert result["reason"] == (
        "unknown_after_click" if operation == "tick"
        else "unknown_after_click_requires_reconciliation"
    )
    if operation != "start":
        assert store.load(record.run_id).status == "paused"
    assert observation.calls == []
    assert decision.calls == []
    assert action.calls == []
    assert store.current_run_id() == record.run_id
    saved = store.load(record.run_id)
    assert saved.send_attempts == record.send_attempts
    assert saved.thread_states == record.thread_states
    assert saved.attempted_send_count == record.attempted_send_count


@pytest.mark.parametrize("error_type", [ManagedClickBlocked, ManagedActionError, RuntimeError])
def test_click_failure_releases_only_proven_unused_budget_and_keeps_unknown_reserved(error_type) -> None:
    runtime, store, observation, _, action, _ = _runtime()
    second = replace(
        _candidate(), candidate_key="row_2", target_id="match_bob",
        target_binding="visual-anchor:bob-v1", discovery_revision="inbound_8",
    )
    config = _config(max_sends_per_run=2)
    config = replace(config, authorization=replace(
        config.authorization, allowed_target_ids=(_candidate().target_id, second.target_id),
    ))
    runtime.start(config, run_id="run_click_boundary_budget")
    assert runtime.tick()["status"] == "confirmed"
    observation.candidates = (second,)
    boundary_calls = []

    def fail_at_click_boundary(candidate):
        record = store.load("run_click_boundary_budget")
        assert record.attempted_send_count == 2
        assert any(
            attempt["target_id"] == candidate.target_id and attempt["status"] == "click_started"
            for attempt in record.send_attempts.values()
        )
        boundary_calls.append(candidate.target_id)
        raise error_type("managed_target_binding_changed")

    action.click_send = fail_at_click_boundary
    result = runtime.tick()
    record = store.load("run_click_boundary_budget")
    attempt = next(attempt for attempt in record.send_attempts.values() if attempt["target_id"] == second.target_id)
    proven_no_return = error_type is ManagedClickBlocked
    expected_status = "failed_before_click" if proven_no_return else "unknown_after_click"

    assert result["status"] == attempt["status"] == expected_status
    assert result["reason"] == ("click_not_performed" if proven_no_return else "click_result_unknown")
    assert record.attempted_send_count == (1 if proven_no_return else 2)
    assert record.confirmed_send_count == 1
    assert record.status == ("active" if proven_no_return else "paused")
    progress = runtime.status()["relationship_progress_snapshot"]
    assert progress["send_budget_remaining"] == (1 if proven_no_return else 0)
    assert progress["unknown_sends"] == (0 if proven_no_return else 1)
    assert action.click_count == action.post_count == 1
    assert boundary_calls == [second.target_id]
    if proven_no_return:
        assert result["action_reason"] == attempt["action_reason"] == "managed_target_binding_changed"
    else:
        assert runtime.tick()["status"] == "paused"
        assert boundary_calls == [second.target_id]


def test_release_of_unused_click_budget_commits_outcome_in_same_checkpoint(monkeypatch) -> None:
    runtime, store, _, _, action, _ = _runtime()
    runtime.start(_config(), run_id="refund")
    save = store.save

    def crash_after_refund(record):
        previous = store.load(record.run_id)
        save(record)
        if record.attempted_send_count < previous.attempted_send_count:
            raise SimulatedHardCrash

    def blocked_before_return(candidate):
        raise ManagedClickBlocked("target_changed")

    monkeypatch.setattr(store, "save", crash_after_refund)
    monkeypatch.setattr(action, "click_send", blocked_before_return)
    with pytest.raises(SimulatedHardCrash):
        runtime.tick()

    persisted = store.load("refund")
    assert persisted.attempted_send_count == 0
    assert [attempt["status"] for attempt in persisted.send_attempts.values()] == ["failed_before_click"]
    restarted, *_ = _runtime(store=store)
    assert restarted.start(_config())["reason"] == "managed_run_already_active"
    assert action.click_count == 0


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


def test_wait_run_persists_a_pause_when_a_port_failure_ends_the_runner() -> None:
    clock = Clock()
    candidate = _candidate()
    store = InMemoryManagedRunStore()
    observation = FailingScanObservation(clock, [candidate])
    sleep_calls: list[float] = []
    runtime = ManagedRun(
        store,
        observation,
        FixtureDecision(),
        FixtureAction(clock, candidate),
        now=clock,
        sleeper=sleep_calls.append,
    )
    runtime.start(_config(), run_id="run_wait_port_failure")

    result = runtime.run(wait=True, poll_interval_seconds=3.0)

    assert result["status"] == "paused"
    assert result["reason"] == "message_list_observation_failed"
    assert result["error_type"] == "RuntimeError"
    assert sleep_calls == []
    durable = store.load("run_wait_port_failure")
    assert durable is not None
    assert durable.status == "paused"
    assert durable.pause_reason == "message_list_observation_failed"
    assert durable.last_result == {
        "schema_version": 1,
        "status": "paused",
        "reason": "message_list_observation_failed",
        "run_id": "run_wait_port_failure",
        "error_type": "RuntimeError",
    }


@pytest.mark.parametrize(
    ("failure", "expected_reason"),
    (
        (RuntimeError("fixture sleeper failure"), "managed_run_wait_sleep_failed"),
        (KeyboardInterrupt(), "managed_run_interrupted"),
    ),
)
def test_wait_run_pauses_when_polling_is_interrupted(
    failure: BaseException,
    expected_reason: str,
) -> None:
    clock = Clock()
    candidate = _candidate()
    store = InMemoryManagedRunStore()

    def interrupted_sleep(seconds: float) -> None:
        del seconds
        raise failure

    runtime = ManagedRun(
        store,
        FixtureObservation(clock, []),
        FixtureDecision(),
        FixtureAction(clock, candidate),
        now=clock,
        sleeper=interrupted_sleep,
    )
    runtime.start(_config(), run_id="run_wait_interrupted")

    result = runtime.run(wait=True, poll_interval_seconds=3.0)

    assert result["status"] == "paused"
    assert result["reason"] == expected_reason
    assert runtime.status()["status"] == "paused"


def test_prioritization_failure_pauses_instead_of_leaving_an_active_run() -> None:
    clock = Clock()
    candidate = _candidate()
    store = InMemoryManagedRunStore()
    runtime = ManagedRun(
        store,
        FixtureObservation(clock, [candidate]),
        FailingPrioritizationDecision(),
        FixtureAction(clock, candidate),
        now=clock,
    )
    runtime.start(_config(), run_id="run_prioritization_failure")

    result = runtime.tick()

    assert result["status"] == "paused"
    assert result["reason"] == "candidate_prioritization_failed"
    assert runtime.status()["status"] == "paused"


def test_diagnostic_event_failure_does_not_interrupt_managed_send() -> None:
    clock = Clock()
    candidate = _candidate()
    store = FailingEventStore()
    runtime = ManagedRun(
        store,
        FixtureObservation(clock, [candidate]),
        FixtureDecision(),
        FixtureAction(clock, candidate),
        now=clock,
    )

    assert runtime.start(_config(), run_id="run_event_failure")["status"] == "active"
    result = runtime.tick()

    assert result["status"] == "confirmed"
    assert runtime.status()["status"] == "active"


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


def _batch_fixture(*, decision: FixtureDecision | None = None, sleeper=None, batch_max_age: float = 120.0):
    clock = Clock()
    candidates = tuple(
        replace(_candidate(), candidate_key=f"row_{index}", target_id=f"match_{index}", priority=index)
        for index in range(3)
    )
    store = InMemoryManagedRunStore()
    observation = FixtureObservation(clock, candidates)
    action = FixtureAction(clock, candidates[0])
    runtime = ManagedRun(
        store, observation, decision or FixtureDecision(), action,
        now=clock, sleeper=sleeper,
        scan_batch_max_age_seconds=batch_max_age,
        monotonic=lambda: clock.value.timestamp(),
    )
    config = _config(max_sends_per_run=3)
    runtime.start(replace(config, authorization=replace(config.authorization, allow_all_targets=True)), run_id="run_batch")
    return runtime, store, observation, action, clock


def test_discovery_batch_reuses_one_scan_but_freshly_observes_each_target() -> None:
    runtime, store, observation, action, _ = _batch_fixture()

    results = [runtime.tick() for _ in range(3)]

    assert [result["status"] for result in results] == ["confirmed"] * 3
    assert observation.calls.count("scan") == 1
    assert observation.calls.count("open") == observation.calls.count("observe") == 3
    assert action.click_count == action.post_count == 3
    assert store.load("run_batch").cycle_count == 1


def test_discovery_batch_wait_does_not_delay_other_pending_targets() -> None:
    sleeps: list[float] = []
    runtime, _, observation, action, _ = _batch_fixture(
        decision=MaturingNudgeDecision(), sleeper=sleeps.append,
    )
    # Two replies exhaust the budget after one candidate elects to wait.
    record = runtime.store.load("run_batch")
    record.config = replace(record.config, max_sends_per_run=2)
    runtime.store.save(record)

    result = runtime.run(wait=True, poll_interval_seconds=30)

    assert result["status"] == "stopped"
    assert sleeps == []
    assert observation.calls.count("scan") == 1
    assert action.click_count == 2


def test_discovery_batch_is_opt_in_for_other_providers() -> None:
    runtime, _, observation, _, _ = _batch_fixture(batch_max_age=0.0)

    runtime.run(max_steps=3)

    assert observation.calls.count("scan") == 3


@pytest.mark.parametrize("outcome", ["wait", "handoff"])
def test_finite_run_consumes_other_candidates_after_a_non_send(outcome: str) -> None:
    class FirstNonSend(FixtureDecision):
        def decide(self, observation, *, config):
            if observation.target_id == "match_0":
                return DraftDecision(
                    decision_id="deferred", outcome=outcome,
                    target_id=observation.target_id, inbound_revision=observation.inbound_revision,
                    reason_codes=("user_attention_required",),
                )
            return super().decide(observation, config=config)

    runtime, _, observation, action, _ = _batch_fixture(decision=FirstNonSend())

    result = runtime.run(max_steps=3)

    assert [step["status"] for step in result["steps"]] == [outcome, "confirmed", "confirmed"]
    assert observation.calls.count("scan") == 1
    assert action.click_count == 2


@pytest.mark.parametrize("change", ["expiry", "external_lifecycle", "configuration", "cursor", "thread_state", "local_lifecycle", "restart"])
def test_discovery_batch_invalidates_after_state_changes(change: str) -> None:
    runtime, store, observation, action, clock = _batch_fixture()
    assert runtime.tick()["status"] == "confirmed"
    if change == "expiry":
        clock.value += timedelta(seconds=120)
    elif change in {"external_lifecycle", "local_lifecycle"}:
        controller = runtime if change == "local_lifecycle" else ManagedRun(store, observation, FixtureDecision(), action, now=clock)
        # Deliberately do not advance time: timestamps cannot detect this cycle.
        controller.pause()
        controller.resume()
    elif change == "restart":
        runtime = ManagedRun(
            store, observation, FixtureDecision(), action, now=clock,
            scan_batch_max_age_seconds=120.0, monotonic=lambda: clock.value.timestamp(),
        )
    else:
        record = store.load("run_batch")
        if change == "configuration":
            record.config = replace(record.config, max_sends_per_run=4)
        elif change == "cursor":
            record.scan_cursor = {"position": "external_reset"}
        else:
            record.thread_states["unrelated"] = {"last_outcome": "handoff"}
        store.save(record)

    assert runtime.tick()["status"] == "confirmed"
    assert observation.calls.count("scan") == 2
    assert action.click_count == 2


def test_discovery_batch_expiry_is_measured_from_original_scan() -> None:
    runtime, _, observation, _, clock = _batch_fixture(batch_max_age=20.0)
    assert runtime.tick()["status"] == "confirmed"
    clock.value += timedelta(seconds=8)
    assert runtime.tick()["status"] == "confirmed"
    clock.value += timedelta(seconds=1)

    assert runtime.tick()["status"] == "confirmed"
    assert observation.calls.count("scan") == 2


@pytest.mark.parametrize("gate", ["target", "inbound_revision", "staged_text"])
def test_discovery_batch_preserves_fresh_target_and_send_gates(gate: str) -> None:
    runtime, _, observation, action, _ = _batch_fixture()
    assert runtime.tick()["status"] == "confirmed"
    if gate == "target":
        observation.opened_target_id = "wrong_target"
    elif gate == "inbound_revision":
        action.composer_revision = "different_fresh_inbound"
    else:
        action.staged_text_override = "not the approved draft"

    result = runtime.tick()

    assert result["status"] == "failed_before_click"
    assert observation.calls.count("scan") == 1
    assert observation.calls.count("open") == 2
    assert action.click_count == 1


def test_discovery_batch_uses_fresh_thread_revision_for_drafting() -> None:
    runtime, store, observation, action, _ = _batch_fixture()
    assert runtime.tick()["status"] == "confirmed"
    observation.thread_revision = "new_inbound_after_discovery"

    result = runtime.tick()

    assert result["status"] == "confirmed"
    assert observation.calls.count("scan") == 1
    assert action.click_count == 2
    assert store.load("run_batch").thread_states["match_1"]["last_inbound_revision"] == "new_inbound_after_discovery"


def test_discovery_batch_still_suppresses_an_authoritative_duplicate() -> None:
    runtime, store, observation, action, _ = _batch_fixture()
    record = store.load("run_batch")
    record.thread_states["match_1"] = {
        "last_discovery_revision": "old_preview",
        "last_inbound_revision": "inbound_7",
        "last_outcome": "confirmed",
    }
    store.save(record)

    result = runtime.run(max_steps=3)

    assert [step["status"] for step in result["steps"]] == ["confirmed", "no_work", "confirmed"]
    assert result["steps"][1]["reason"] == "inbound_revision_already_processed"
    assert observation.calls.count("scan") == 1
    assert observation.calls.count("observe") == 3
    assert action.click_count == 2


def test_discovery_batch_unknown_blocks_resume_and_remaining_candidates() -> None:
    runtime, store, observation, action, _ = _batch_fixture()
    assert runtime.tick()["status"] == "confirmed"
    action.outbound_text_override = "verification failed"
    assert runtime.tick()["status"] == "unknown_after_click"
    assert runtime.tick()["status"] == "paused"
    assert action.click_count == 2
    assert runtime.resume()["status"] == "blocked"
    action.outbound_text_override = None

    result = runtime.tick()

    assert result["status"] == "paused"
    assert observation.calls.count("scan") == 1
    assert action.click_count == 2
    assert store.load("run_batch").thread_states["match_1"]["last_outcome"] == "unknown_after_click"


def test_discovery_batch_profile_reports_stages_without_model_text() -> None:
    decision = FixtureDecision()
    decision.last_triage_metrics = {
        "route": "draft", "reason": "PRIVATE_MODEL_TEXT", "model": "PRIVATE_MODEL_TEXT",
        "duration_ms": 1.25, "input_tokens": 10, "output_tokens": 3, "request_count": 1,
        "prompt": "PRIVATE_MODEL_TEXT", "text": "PRIVATE_MODEL_TEXT",
    }
    runtime, store, _, _, _ = _batch_fixture(decision=decision)
    runtime.tick()
    runtime.tick()

    profiles = [event for event in store.events("run_batch") if event["event_type"] == "tick_profile"]

    assert [event["scan_reused"] for event in profiles] == [False, True]
    assert profiles[0]["stage_ms"]["scan"] == 1000.0
    assert profiles[1]["stage_ms"]["scan"] == 0.0
    assert set(profiles[0]["stage_ms"]) == {"scan", "open_thread", "observe_thread", "decide", "send"}
    assert profiles[0]["triage"] == {"route": "draft", "duration_ms": 1.25, "input_tokens": 10, "output_tokens": 3, "request_count": 1}
    assert "PRIVATE_MODEL_TEXT" not in str(profiles)


def test_discovery_batch_is_bounded_and_reobserves_excess_candidates() -> None:
    runtime, store, observation, action, _ = _batch_fixture(batch_max_age=3600)
    observation.candidates = tuple(
        replace(_candidate(), candidate_key=f"row_{index}", target_id=f"match_{index}", priority=index)
        for index in range(101)
    )
    record = store.load("run_batch")
    record.config = replace(record.config, max_sends_per_run=101)
    store.save(record)

    result = runtime.run(max_steps=101)

    assert result["processed_count"] == 101
    assert observation.calls.count("scan") == 2
    assert action.click_count == 101


def test_discovery_batch_is_invalidated_by_a_lifecycle_change_during_decision() -> None:
    holder: dict[str, ManagedRun] = {}

    class InterleavedLifecycle(FixtureDecision):
        changed = False

        def decide(self, observation, *, config):
            if observation.target_id == "match_0" and not self.changed:
                self.changed = True
                holder["controller"].pause()
                holder["controller"].resume()
            return super().decide(observation, config=config)

    runtime, store, observation, action, clock = _batch_fixture(decision=InterleavedLifecycle())
    holder["controller"] = ManagedRun(store, observation, FixtureDecision(), action, now=clock)

    assert runtime.tick()["reason"] == "managed_run_lifecycle_changed"
    assert action.click_count == 0
    assert runtime.tick()["status"] == "confirmed"
    assert observation.calls.count("scan") == 2


def test_discovery_batch_empty_or_consumed_work_returns_to_normal_polling() -> None:
    sleeps: list[float] = []
    holder: dict[str, ManagedRun] = {}

    def stop_after_idle(seconds: float) -> None:
        sleeps.append(seconds)
        holder["runtime"].stop()

    runtime, _, observation, action, _ = _batch_fixture(sleeper=stop_after_idle)
    holder["runtime"] = runtime
    observation.candidates = ()

    result = runtime.run(wait=True, poll_interval_seconds=30)

    assert result["status"] == "stopped"
    assert sleeps == [30]
    assert observation.calls == ["scan"]
    assert action.click_count == 0


def test_discovery_batch_quiet_hours_invalidate_without_gui_work() -> None:
    runtime, store, observation, action, clock = _batch_fixture(batch_max_age=3600)
    record = store.load("run_batch")
    start = (clock.value + timedelta(minutes=1)).astimezone().strftime("%H:%M")
    end = (clock.value + timedelta(minutes=2)).astimezone().strftime("%H:%M")
    record.config = replace(record.config, authorization=replace(record.config.authorization, quiet_hours=(f"{start}-{end}",)))
    store.save(record)
    assert runtime.tick()["status"] == "confirmed"
    clock.value = clock.value.replace(minute=1, second=0)

    quiet = runtime.tick()

    assert quiet["reason"] == "authorization_quiet_hours"
    assert observation.calls.count("scan") == 1
    assert action.click_count == 1
    clock.value = clock.value.replace(minute=2, second=1)
    assert runtime.tick()["status"] == "confirmed"
    assert observation.calls.count("scan") == 2


def test_discovery_batch_port_failure_pauses_and_invalidates() -> None:
    runtime, store, observation, action, _ = _batch_fixture()
    assert runtime.tick()["status"] == "confirmed"
    runtime.decision = FailingPrioritizationDecision()

    assert runtime.tick()["status"] == "paused"
    assert action.click_count == 1
    runtime.decision = FixtureDecision()
    runtime.resume()
    assert runtime.tick()["status"] == "confirmed"
    assert observation.calls.count("scan") == 2


def test_optional_triage_telemetry_failure_cannot_block_a_send() -> None:
    class BrokenTelemetryDecision(FixtureDecision):
        @property
        def last_triage_metrics(self):
            raise RuntimeError("telemetry unavailable")

    runtime, _, _, action, _ = _batch_fixture(decision=BrokenTelemetryDecision())

    assert runtime.tick()["status"] == "confirmed"
    assert action.click_count == 1


class BurstDecision(FixtureDecision):
    def __init__(self, clock: Clock, messages: tuple[str, ...], *, planning_seconds: float = 0.0):
        super().__init__("\n".join(messages))
        self.clock = clock
        self.messages = messages
        self.planning_seconds = planning_seconds

    def decide(self, observation, *, config):
        self.calls.append("decide")
        self.clock.value += timedelta(seconds=self.planning_seconds)
        return DraftDecision.send(
            decision_id="reviewed_burst", target_id=observation.target_id,
            inbound_revision=observation.inbound_revision,
            text=self.text, message_sequence=self.messages,
        )


class BurstAction(FixtureAction):
    def __init__(self, clock: Clock, candidate: ThreadCandidate):
        super().__init__(clock, candidate)
        self.continuation_verified = True
        self.stage_delays: list[float] = []
        self.sent_texts: list[str] = []
        self.clicked_at: list[str] = []
        self.after_post: Callable[[], None] | None = None
        self.before_stage: Callable[[], None] | None = None

    def stage_text(self, candidate, text):
        if self.before_stage is not None:
            self.before_stage()
        if self.stage_count < len(self.stage_delays):
            self.clock.value += timedelta(seconds=self.stage_delays[self.stage_count])
        return super().stage_text(candidate, text)

    def click_send(self, candidate):
        receipt = super().click_send(candidate)
        self.sent_texts.append(self.last_clicked_text)
        self.clicked_at.append(receipt.clicked_at)
        return receipt

    def observe_post_send(self, candidate, receipt):
        post = replace(super().observe_post_send(candidate, receipt), continuation_verified=self.continuation_verified)
        if self.after_post is not None:
            self.after_post()
        return post


def _burst_fixture(
    *, messages: tuple[str, ...] = ("第一条完整内容", "第二条完整内容", "第三条完整内容"),
    planning_seconds: float = 0.0, budget: int = 10, store=None,
):
    clock = Clock()
    candidate = _candidate()
    store = store or InMemoryManagedRunStore()
    observation = FixtureObservation(clock, [candidate])
    decision = BurstDecision(clock, messages, planning_seconds=planning_seconds)
    action = BurstAction(clock, candidate)
    runtime = ManagedRun(
        store, observation, decision, action, now=clock,
        scan_batch_max_age_seconds=120.0, monotonic=lambda: clock.value.timestamp(),
        sleeper=lambda _: pytest.fail("a burst must not poll between bubbles"),
    )
    runtime.start(_config(max_sends_per_run=budget), run_id="run_burst")
    return runtime, store, observation, decision, action, clock


@pytest.mark.parametrize("messages", [("第一条", "第二条"), ("第一条", "第二条", "第三条"), ("一样", "一样", "一样")])
def test_burst_sends_all_reviewed_bubbles_in_one_tick(messages: tuple[str, ...]) -> None:
    runtime, store, observation, decision, action, _ = _burst_fixture(messages=messages)

    def plan_is_durable_before_staging() -> None:
        plan = next(iter(store.load("run_burst").send_bursts.values()))
        assert plan["messages"] == list(messages)

    action.before_stage = plan_is_durable_before_staging
    result = runtime.tick()

    assert result["status"] == "confirmed"
    assert result["completed_message_count"] == len(messages)
    assert result["cancelled_message_count"] == result["unknown_message_count"] == 0
    assert observation.calls == ["scan", "open", "observe"]
    assert decision.calls == ["prioritize", "decide"]
    assert action.calls == ["stage", "click", "verify"] * len(messages)
    assert action.sent_texts == list(messages)
    record = store.load("run_burst")
    assert record.attempted_send_count == record.confirmed_send_count == len(messages)
    assert len(record.send_attempts) == len(messages)
    assert sorted(attempt["message_index"] for attempt in record.send_attempts.values()) == list(range(1, len(messages) + 1))
    assert next(iter(record.send_bursts.values()))["status"] == "completed"
    assert runtime.tick()["status"] == "no_work"
    assert action.click_count == len(messages)


def test_burst_window_excludes_planning_and_first_stage() -> None:
    runtime, _, observation, decision, action, _ = _burst_fixture(planning_seconds=180)
    action.stage_delays = [180, 0, 0]

    result = runtime.tick()

    assert result["status"] == "confirmed"
    assert action.click_count == 3
    clicks = [datetime.fromisoformat(stamp.replace("Z", "+00:00")) for stamp in action.clicked_at]
    assert [(later - earlier).total_seconds() for earlier, later in zip(clicks, clicks[1:])] == [3, 3]
    assert observation.calls.count("scan") == decision.calls.count("decide") == 1


def test_burst_slow_later_stage_rechecks_deadline_before_click_and_pauses() -> None:
    runtime, store, _, _, action, _ = _burst_fixture()
    action.stage_delays = [0, 21, 0]

    result = runtime.tick()

    assert result["status"] == "paused"
    assert result["reason"] == "message_burst_gap_expired"
    assert result["completed_message_count"] == 1
    assert result["cancelled_message_count"] == 2
    assert action.stage_count == 2 and action.click_count == 1
    assert action.composer_text == "第二条完整内容"
    runtime.resume()
    assert runtime.tick()["status"] == "no_work"
    assert action.click_count == 1
    assert next(iter(store.load("run_burst").send_bursts.values()))["status"] == "cancelled"


def test_burst_post_verification_delay_counts_against_next_click_gap() -> None:
    runtime, _, _, _, action, clock = _burst_fixture()
    action.after_post = lambda: setattr(clock, "value", clock.value + timedelta(seconds=21))

    result = runtime.tick()

    assert result["reason"] == "message_burst_gap_expired"
    assert result["status"] == "failed_before_click"
    assert result["completed_message_count"] == 1
    assert action.stage_count == action.click_count == 1
    assert action.composer_text == ""


def test_burst_new_inbound_cancels_tail_without_pausing_other_threads() -> None:
    runtime, store, observation, _, action, _ = _burst_fixture()
    action.continuation_verified = False

    result = runtime.tick()

    assert result["status"] == "handoff"
    assert result["reason"] == "message_burst_continuation_unverified"
    assert result["completed_message_count"] == 1 and result["cancelled_message_count"] == 2
    assert runtime.status()["status"] == "active"
    assert runtime.tick()["status"] == "no_work"
    assert action.click_count == 1
    observation.candidates = (replace(_candidate(), discovery_revision="new-preview"),)
    observation.thread_revision = "new-authoritative-inbound"
    action.continuation_verified = True
    assert runtime.tick()["status"] == "confirmed"
    assert action.click_count == 4
    assert len(store.load("run_burst").send_bursts) == 2


@pytest.mark.parametrize("interruption", ["budget", "pause", "lifecycle", "unknown"])
def test_burst_obeys_each_message_budget_lifecycle_and_unknown_gates(interruption: str) -> None:
    runtime, store, _, _, action, _ = _burst_fixture(budget=1 if interruption == "budget" else 10)

    def interrupt_after_first() -> None:
        if action.post_count != 1:
            return
        if interruption == "pause":
            runtime.pause()
        elif interruption == "lifecycle":
            runtime.pause()
            runtime.resume()
        elif interruption == "unknown":
            action.outbound_text_override = "not the sent text"

    action.after_post = interrupt_after_first
    result = runtime.tick()

    expected = {"budget": "stopped", "pause": "paused", "lifecycle": "blocked", "unknown": "unknown_after_click"}
    assert result["status"] == expected[interruption]
    assert result["completed_message_count"] == 1
    assert result["unknown_message_count"] == (1 if interruption == "unknown" else 0)
    assert result["cancelled_message_count"] == (1 if interruption == "unknown" else 2)
    assert action.click_count == (2 if interruption == "unknown" else 1)
    assert store.load("run_burst").attempted_send_count == action.click_count


def test_active_legacy_unknown_burst_pauses_during_the_same_recovery_tick() -> None:
    runtime, store, observation, decision, action, _ = _burst_fixture()
    action.outbound_text_override = "cannot verify"
    assert runtime.tick()["status"] == "unknown_after_click"
    record = store.load("run_burst")
    record.status = "active"
    record.pause_reason = None
    next(iter(record.send_bursts.values()))["status"] = "active"
    store.save(record)
    calls_before = (list(observation.calls), list(decision.calls), list(action.calls))

    result = runtime.tick()

    assert result["status"] == "unknown_after_click"
    saved = store.load("run_burst")
    assert saved.status == "paused"
    assert saved.pause_reason == "unknown_after_click"
    assert saved.attempted_send_count == 1
    assert (observation.calls, decision.calls, action.calls) == calls_before


@pytest.mark.parametrize("boundary", ["confirmed", "prepared", "click_started"])
def test_burst_restart_reconciles_progress_and_never_replays_tail(boundary: str) -> None:
    store = (
        CrashAfterConfirmedStore() if boundary == "confirmed"
        else CrashAfterPreparedStore() if boundary == "prepared"
        else CrashBeforeClickCommittedSaveStore()
    )
    if boundary == "prepared":
        store.crash_armed = False
    runtime, store, observation, decision, action, clock = _burst_fixture(store=store)
    if boundary == "prepared":
        action.after_post = lambda: setattr(store, "crash_armed", True)
    with pytest.raises(SimulatedProcessCrash):
        runtime.tick()
    calls_before_restart = list(observation.calls)
    decision_before_restart = list(decision.calls)
    clicks_before_restart = action.click_count
    recovered = ManagedRun(store, observation, decision, action, now=clock)

    result = recovered.tick()

    assert result["status"] == {"confirmed": "handoff", "prepared": "paused", "click_started": "unknown_after_click"}[boundary]
    assert result["completed_message_count"] == (0 if boundary == "click_started" else 1)
    assert result["unknown_message_count"] == (1 if boundary == "click_started" else 0)
    assert result["cancelled_message_count"] == 2
    assert observation.calls == calls_before_restart
    assert decision.calls == decision_before_restart
    assert action.click_count == clicks_before_restart
    recovered.resume()
    assert recovered.tick()["status"] == ("paused" if boundary == "click_started" else "no_work")
    assert action.click_count == clicks_before_restart
    assert next(iter(store.load("run_burst").send_bursts.values()))["status"] == "abandoned"


def test_burst_audit_contains_no_full_message_content() -> None:
    messages = ("private full bubble alpha", "private full bubble beta")
    runtime, store, _, _, _, _ = _burst_fixture(messages=messages)

    result = runtime.tick()

    audit_and_result = str(store.events("run_burst")) + str(result)
    assert not any(message in audit_and_result for message in messages)
    assert next(iter(store.load("run_burst").send_bursts.values()))["messages"] == list(messages)


@pytest.mark.parametrize("messages,text,reason", [
    (("a", "b", "c", "d"), "a\nb\nc\nd", "message_sequence_count_invalid"),
    (("a", ""), "a\n", "message_sequence_text_invalid"),
    (("a", "b"), "truncated", "message_sequence_text_mismatch"),
])
def test_burst_decision_rejects_invalid_sequences_without_truncation(messages, text, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        DraftDecision.send(decision_id="decision", target_id="target", inbound_revision="revision", text=text, message_sequence=messages)


@pytest.mark.parametrize("burst", [False, True])
def test_adapter_stage_reason_survives_transaction_and_burst_summary(burst: bool) -> None:
    from dating_boost.core.managed_run_provider import _require_action_ok

    if burst:
        runtime, store, _, _, action, _ = _burst_fixture()
        run_id = "run_burst"
    else:
        runtime, store, _, _, action, _ = _runtime()
        run_id = "run_action_diagnostic"
        runtime.start(_config(), run_id=run_id)

    def blocked_stage(candidate, text):
        _require_action_ok({"status": "blocked", "reason": "managed_inbound_revision_changed"}, "managed_stage_failed")

    action.stage_text = blocked_stage
    result = runtime.tick()

    assert result["status"] == "failed_before_click"
    assert result["reason"] == "staging_failed"
    assert result["action_reason"] == "managed_inbound_revision_changed"
    attempt = next(iter(store.load(run_id).send_attempts.values()))
    assert attempt["action_reason"] == result["action_reason"]
    assert action.click_count == 0
    if burst:
        assert next(iter(store.load(run_id).send_bursts.values()))["action_reason"] == result["action_reason"]


@pytest.mark.parametrize("seam", ["stage_text", "click_send", "observe_post_send"])
@pytest.mark.parametrize("typed", [False, True])
def test_action_diagnostics_preserve_codes_without_exception_text_and_keep_safety(seam: str, typed: bool) -> None:
    runtime, store, _, _, action, _ = _runtime()
    runtime.start(_config(), run_id="run_safe_action_error")

    def fail(*args):
        error = ManagedActionError("managed_target_binding_changed") if typed else RuntimeError("PRIVATE chat body and key")
        if not typed:
            error.reason_code = "untrusted_dynamic_code"
        raise error

    setattr(action, seam, fail)
    result = runtime.tick()

    reasons = {
        "stage_text": "staging_failed",
        "click_send": "click_result_unknown",
        "observe_post_send": "post_send_observation_failed",
    }
    assert result["reason"] == reasons[seam]
    assert result["status"] == ("failed_before_click" if seam == "stage_text" else "unknown_after_click")
    assert runtime.status()["status"] == ("active" if seam == "stage_text" else "paused")
    attempt = next(iter(store.load("run_safe_action_error").send_attempts.values()))
    if typed:
        assert result["action_reason"] == attempt["action_reason"] == "managed_target_binding_changed"
        assert any(event.get("action_reason") == result["action_reason"] for event in store.events("run_safe_action_error"))
    else:
        assert "action_reason" not in result and "action_reason" not in attempt
    serialized = str(result) + str(attempt) + str(store.events("run_safe_action_error"))
    assert "PRIVATE" not in serialized
    assert "untrusted_dynamic_code" not in serialized


def test_prepared_composer_diagnostic_uses_the_same_safe_action_error_boundary() -> None:
    store = CrashAfterPreparedStore()
    runtime, store, _, _, action, _ = _runtime(store=store)
    runtime.start(_config(), run_id="run_prepared_action_error")
    with pytest.raises(SimulatedProcessCrash):
        runtime.tick()

    def failed_observation(candidate):
        raise ManagedActionError("managed_composer_exact_text_unavailable")

    action.observe_composer = failed_observation
    result = runtime.tick()

    assert result["reason"] == "prepared_checkpoint_composer_unknown"
    assert result["action_reason"] == "managed_composer_exact_text_unavailable"
    assert next(iter(store.load("run_prepared_action_error").send_attempts.values()))["action_reason"] == result["action_reason"]
    assert action.click_count == 0
