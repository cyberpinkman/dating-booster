from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from dating_boost.core.managed_run import (
    DraftDecision,
    InMemoryManagedRunStore,
    JsonManagedRunStore,
    ManagedAuthorization,
    ManagedActionError,
    ManagedDecisionError,
    ManagedRun,
    ManagedRunConfig,
    MessageListSnapshot,
    OpenThreadObservation,
    ThreadCandidate,
    ThreadObservation,
)
from dating_boost.core.managed_run_provider import (
    MANAGED_LIVE_ACTION_PORT_STATUS,
    MANAGED_RUN_FIXTURE_DIR_ENV,
    MANAGED_RUN_SCRIPTED_BACKEND_ENV,
    MANAGED_RUN_TASHUO_CONFIG_ENV,
    DevelopmentFixtureActionPort,
    ManagedRunProviderRuntime,
    StandalonePlannerManagedDecisionPort,
    StandaloneObservationManagedRunPort,
    TaShuoMacIosManagedActionPort,
    build_managed_run_runtime,
    _require_action_ok,
    _require_ok_observation,
)
from dating_boost.core.runtime_scope import RuntimeScopeRepository


pytestmark = pytest.mark.managed_critical


@pytest.mark.parametrize("runnable", [True, False])
def test_reconciliation_facade_requires_provider_and_forwards_only_recovery(runnable):
    runtime = Mock()
    runtime.reconcile.return_value = {"status": "reconciled"}
    facade = ManagedRunProviderRuntime(runtime, provider_kind="test", runnable=runnable)

    result = facade.reconcile("old-run", decision_key="old-attempt")

    if runnable:
        assert result == {"status": "reconciled"}
        runtime.reconcile.assert_called_once_with("old-run", decision_key="old-attempt")
    else:
        assert result["status"] == "blocked"
        runtime.reconcile.assert_not_called()
    runtime.start.assert_not_called()
    runtime.run.assert_not_called()


@pytest.mark.parametrize("reason", [None, "", "PRIVATE chat and key", "UPPER_CASE", "bad-code", "bad__code", "bad_code_", "a" * 97, {"private": "text"}])
def test_action_adapter_error_rejects_raw_or_unbounded_reason_payloads(reason) -> None:
    with pytest.raises(ManagedActionError) as caught:
        _require_action_ok({"status": "blocked", "reason": reason}, "managed_stage_failed")
    assert caught.value.reason_code == "managed_stage_failed"
    assert str(caught.value) == "managed_stage_failed"


def test_action_adapter_error_keeps_only_a_bounded_machine_code() -> None:
    with pytest.raises(ManagedActionError) as caught:
        _require_action_ok({"status": "blocked", "reason": "managed_inbound_revision_changed", "error": "PRIVATE chat"}, "managed_stage_failed")
    assert caught.value.reason_code == "managed_inbound_revision_changed"
    assert "PRIVATE" not in str(caught.value)
    assert ManagedActionError("PRIVATE chat", fallback_reason="PRIVATE key").reason_code == "managed_action_failed"
    assert ManagedActionError("a" * 96).reason_code == "a" * 96


def test_observation_adapter_error_preserves_the_safe_machine_code() -> None:
    with pytest.raises(ManagedActionError) as caught:
        _require_ok_observation({
            "status": "blocked", "observation_type": "thread",
            "reason": "tashuo_conversation_not_verified", "error": "PRIVATE diagnostic text",
        }, "thread")
    assert caught.value.reason_code == "tashuo_conversation_not_verified"
    assert str(caught.value) == "tashuo_conversation_not_verified"


@pytest.mark.parametrize("reason", [None, "", "PRIVATE chat and key", "UPPER_CASE", "bad-code", "bad__code", "bad_code_", "a" * 97, {"private": "text"}, True])
def test_observation_adapter_error_sanitizes_invalid_reasons(reason) -> None:
    with pytest.raises(ManagedActionError) as caught:
        _require_ok_observation({"status": "blocked", "reason": reason}, "thread")
    assert caught.value.reason_code == "managed_observation_blocked"
    assert str(caught.value) == "managed_observation_blocked"


@pytest.mark.parametrize("payload", [None, [], "PRIVATE raw payload", True, 1])
def test_observation_adapter_error_requires_an_object(payload) -> None:
    with pytest.raises(ManagedActionError) as caught:
        _require_ok_observation(payload, "message_list")
    assert caught.value.reason_code == "managed_observation_must_be_object"


@pytest.mark.parametrize("status", [None, "", "blocked", "failed", "needs_verification", "unknown", True, 1, [], {}])
def test_observation_adapter_error_rejects_explicit_non_ok_status(status) -> None:
    payload = {"observation_type": "thread", "status": status}
    with pytest.raises(ManagedActionError) as caught:
        _require_ok_observation(payload, "thread")
    assert caught.value.reason_code == "managed_observation_blocked"


@pytest.mark.parametrize("observation_type", ["message_list", "PRIVATE type", True, 1, ["wrong"], {"private": "type"}])
def test_observation_adapter_error_keeps_existing_observation_type_mismatch_check(observation_type) -> None:
    payload = {"status": "ok", "observation_type": observation_type}
    with pytest.raises(ManagedActionError) as caught:
        _require_ok_observation(payload, "thread")
    assert caught.value.reason_code == "managed_observation_type_mismatch"


@pytest.mark.parametrize("expected_type", ["message_list", "thread"])
def test_observation_adapter_accepts_explicit_ok_and_matching_type(expected_type) -> None:
    assert _require_ok_observation({"status": "ok", "observation_type": expected_type}, expected_type) is None


@pytest.mark.parametrize("payload", [{}, {"status": "ok"}, {"observation_type": "thread"}, {"status": "ok", "observation_type": None}])
def test_observation_adapter_preserves_legacy_omitted_status_and_default_type(payload) -> None:
    assert _require_ok_observation(payload, "thread") is None


@pytest.mark.parametrize(
    ("fixture_mode", "raw", "reason"),
    [
        (True, {"candidate_key": "wrong"}, "managed_thread_candidate_key_mismatch"),
        (True, {"target_id": "wrong"}, "managed_thread_target_id_mismatch"),
        (True, {"target_binding": "wrong"}, "managed_thread_target_binding_mismatch"),
        (False, {}, "managed_thread_structural_binding_not_corroborated"),
        (True, {}, "managed_thread_inbound_revision_missing"),
    ],
)
def test_thread_mapping_keeps_known_failure_codes_at_observation_boundary(tmp_path, fixture_mode, raw, reason) -> None:
    port = StandaloneObservationManagedRunPort(tmp_path, Mock(), fixture_mode=fixture_mode)
    candidate = ThreadCandidate(
        candidate_key="row", target_id="target", target_binding="fixture:target", discovery_revision="preview",
    )
    with pytest.raises(ManagedActionError) as caught:
        port._map_thread(candidate, raw)
    assert caught.value.reason_code == reason
    assert str(caught.value) == reason


@pytest.fixture(autouse=True)
def _local_key_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")


class _UnusedPort:
    pass


class _Planner:
    def draft_for_match(self, *, match_id: str, mode: str) -> dict[str, object]:
        assert match_id
        assert mode == "adaptive"
        return {"status": "ok", "draft": {"best_reply": "可以，周日下午怎么样？"}}


@pytest.mark.parametrize("reason,error_type", [
    ("draft_generation_failed", "APITimeoutError"),
    ("draft_review_failed", "RuntimeError"),
])
def test_planner_execution_failure_pauses_without_consuming_incoming_and_resumes_fresh(tmp_path, reason, error_type):
    from tests.test_managed_run import Clock, FixtureAction, FixtureObservation, _candidate, _config

    clock = Clock()
    candidate = _candidate()
    observation = FixtureObservation(clock, [candidate], thread_context={"match_id": candidate.target_id})
    action = FixtureAction(clock, candidate)
    planner = Mock()
    planner.draft_for_match.return_value = {
        "status": "blocked", "reason": reason, "error_type": error_type,
        "error": "PRIVATE raw backend diagnostic",
    }
    store = JsonManagedRunStore(tmp_path)
    runtime = ManagedRun(store, observation, StandalonePlannerManagedDecisionPort(planner), action, now=clock)
    runtime.start(_config(), run_id="recoverable_decision")

    result = runtime.tick()

    assert result["status"] == "paused"
    assert result["reason"] == "draft_decision_failed"
    assert result["decision_reason"] == reason
    assert result["error_type"] == error_type
    saved = store.load("recoverable_decision")
    assert saved.status == "paused"
    assert saved.thread_states == saved.send_attempts == {}
    assert saved.attempted_send_count == saved.confirmed_send_count == 0
    assert saved.last_result == result
    events = store.events("recoverable_decision")
    assert any(event.get("decision_reason") == reason and event.get("error_type") == error_type for event in events)
    assert "PRIVATE" not in str((result, saved.to_dict(), events))
    assert action.calls == []
    assert runtime.tick()["status"] == "paused"
    assert planner.draft_for_match.call_count == 1
    assert observation.calls == ["scan", "open", "observe"]

    # Rebuild the runtime as a new CLI invocation would; resume is explicit and
    # neither the old thread observation nor a failed draft is reused.
    planner.draft_for_match.return_value = {"status": "ok", "draft": {"best_reply": "听起来挺有趣的"}}
    restored = ManagedRun(JsonManagedRunStore(tmp_path), observation, StandalonePlannerManagedDecisionPort(planner), action, now=clock)
    assert restored.resume()["status"] == "active"
    assert restored.tick()["status"] == "confirmed"
    assert observation.calls == ["scan", "open", "observe"] * 2
    assert planner.draft_for_match.call_count == 2
    assert action.click_count == 1
    assert restored.tick()["status"] == "no_work"
    assert action.click_count == 1


@pytest.mark.parametrize("lifecycle", ["pause", "stop"])
def test_planner_failure_preserves_concurrent_lifecycle_transition(lifecycle):
    from tests.test_managed_run import Clock, FixtureObservation, _candidate, _config, _runtime

    observation = FixtureObservation(Clock(), [_candidate()], thread_context={"match_id": "match_alice"})
    planner = Mock()
    runtime, store, _, _, action, _ = _runtime(
        observation=observation, decision=StandalonePlannerManagedDecisionPort(planner),
    )

    def fail_after_lifecycle_change(**kwargs):
        getattr(runtime, lifecycle)(reason="user_request")
        return {"status": "blocked", "reason": "draft_generation_failed", "error_type": "APITimeoutError"}

    planner.draft_for_match.side_effect = fail_after_lifecycle_change
    runtime.start(_config(), run_id="lifecycle")
    result = runtime.tick()

    assert result["status"] == ("paused" if lifecycle == "pause" else "stopped")
    assert result["reason"] == "user_request"
    assert result["decision_reason"] == "draft_generation_failed"
    saved = store.load("lifecycle")
    assert saved.status == result["status"]
    assert saved.thread_states == saved.send_attempts == {}
    assert action.calls == []


@pytest.mark.parametrize("reason,error_type,expected_reason,expected_type", [
    ("draft_generation_failed", "APITimeoutError", "draft_generation_failed", "APITimeoutError"),
    ("PRIVATE raw diagnostic", "PRIVATE raw error", "managed_draft_not_available", "ManagedDecisionError"),
    (None, {"private": "raw diagnostic"}, "managed_draft_not_available", "ManagedDecisionError"),
])
def test_planner_execution_error_exposes_only_bounded_diagnostics(reason, error_type, expected_reason, expected_type):
    planner = Mock()
    planner.draft_for_match.return_value = {
        "status": "blocked", "reason": reason, "error_type": error_type, "error": "PRIVATE raw backend diagnostic",
    }
    with pytest.raises(ManagedDecisionError) as caught:
        StandalonePlannerManagedDecisionPort(planner).decide(ThreadObservation(
            target_id="target", target_binding="binding", inbound_revision="inbound",
            captured_at="2026-09-20T04:00:00Z", context={"match_id": "match"},
        ), config=_config())
    assert caught.value.reason_code == expected_reason
    assert caught.value.error_type == expected_type
    assert "PRIVATE" not in str(caught.value)


def test_planner_business_handoff_still_consumes_the_incoming():
    from tests.test_managed_run import Clock, FixtureObservation, _candidate, _config, _runtime

    observation = FixtureObservation(Clock(), [_candidate()], thread_context={"match_id": "match_alice"})
    planner = Mock()
    planner.draft_for_match.return_value = {
        "status": "blocked", "reason": "requires_user_confirmation",
        "draft_review": {"requires_user_confirmation": True},
    }
    runtime, store, _, _, action, _ = _runtime(
        observation=observation, decision=StandalonePlannerManagedDecisionPort(planner),
    )
    runtime.start(_config(), run_id="business_handoff")

    result = runtime.tick()

    assert result["status"] == "handoff"
    assert result["reason"] == "requires_user_confirmation"
    assert store.load("business_handoff").status == "active"
    assert runtime.tick()["status"] == "no_work"
    assert planner.draft_for_match.call_count == 1
    assert action.calls == []


@pytest.mark.parametrize("messages", [[], ["哈哈，是有点"], ["哈哈，是有点", "你后来怎么处理的？"], ["哈哈", "这个画面感", "你后来怎么处理的？"]])
def test_decision_preserves_complete_authored_bubble_sequence(messages: list[str]) -> None:
    planner = Mock()
    planner.draft_for_match.return_value = {
        "status": "ok", "draft": {"best_reply": "单条备用回复", "message_sequence": messages},
    }
    port = StandalonePlannerManagedDecisionPort(planner)
    decision = port.decide(ThreadObservation(
        target_id="target", target_binding="binding", inbound_revision="inbound",
        captured_at="2026-09-20T04:00:00Z", context={"match_id": "match"},
    ), config=_config())
    assert decision.outcome == "send"
    assert decision.text == ("\n".join(messages) if messages else "单条备用回复")
    assert tuple(decision.message_sequence or (decision.text,)) == tuple(messages or ["单条备用回复"])
    planner.draft_for_match.assert_called_once_with(match_id="match", mode="adaptive")


@pytest.mark.parametrize("messages", [["一", "二", "三", "四"], ["一", ""], ["一", 2], "一二"])
def test_invalid_sequence_is_not_silently_truncated_or_cast(messages: object) -> None:
    planner = Mock()
    planner.draft_for_match.return_value = {
        "status": "ok", "draft": {"best_reply": "备用回复", "message_sequence": messages},
    }
    decision = StandalonePlannerManagedDecisionPort(planner).decide(ThreadObservation(
        target_id="target", target_binding="binding", inbound_revision="inbound",
        captured_at="2026-09-20T04:00:00Z", context={"match_id": "match"},
    ), config=_config())
    assert decision.outcome == "handoff"
    assert decision.reason_codes == ("managed_draft_message_sequence_invalid",)


def _config() -> ManagedRunConfig:
    return ManagedRunConfig(
        app_id="tinder",
        runtime="default",
        authorization=ManagedAuthorization(
            authorization_id="auth_fixture_live",
            app_id="tinder",
            runtime="default",
            allow_all_targets=True,
            live_send=True,
        ),
        max_sends_per_run=3,
    )


def test_unconfigured_factory_preserves_durable_lifecycle_without_starting_an_unusable_run(tmp_path: Path) -> None:
    port = _UnusedPort()
    seed = ManagedRun(JsonManagedRunStore(tmp_path), port, port, port)
    assert seed.start(_config(), run_id="run_existing")["status"] == "active"

    with patch.dict(
        "os.environ",
        {MANAGED_RUN_FIXTURE_DIR_ENV: "", MANAGED_RUN_SCRIPTED_BACKEND_ENV: ""},
    ):
        runtime = build_managed_run_runtime(tmp_path)
        status = runtime.status()
        paused = runtime.pause(reason="user_break")
        blocked_start = runtime.start(_config(), run_id="run_must_not_exist")

    assert status["status"] == "active"
    assert paused["status"] == "paused"
    assert blocked_start == {
        "schema_version": 1,
        "status": "blocked",
        "reason": "managed_run_runtime_not_configured",
        "provider_kind": "unconfigured",
    }
    assert JsonManagedRunStore(tmp_path).load("run_must_not_exist") is None


def test_fixture_provider_runs_observe_plan_stage_checkpoint_click_and_fresh_verify(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    scripted_output = tmp_path / "scripted.json"
    scripted_output.write_text(json.dumps({"best_reply": "unused by patched planner"}), encoding="utf-8")
    (fixture_dir / "message_list.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "ok",
                "observation_type": "message_list",
                "app_id": "tinder",
                "captured_at": "2026-08-27T04:00:00Z",
                "scan_cursor": {"next": None, "exhausted": True},
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_ada",
                            "target_id": "match_ada",
                            "target_binding": "fixture-binding:ada-v1",
                            "inbound_revision": "inbound_7",
                            "unread_cue": "present",
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (fixture_dir / "thread_row_ada.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "ok",
                "observation_type": "thread",
                "app_id": "tinder",
                "candidate_key": "row_ada",
                "target_id": "match_ada",
                "target_binding": "fixture-binding:ada-v1",
                "inbound_revision": "inbound_7",
                "assessment": {
                    "recommended_next": "reply",
                    "latest_inbound_fingerprint": "inbound_7",
                },
                "observation": _app_observation(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with patch.dict(
        "os.environ",
        {
            MANAGED_RUN_FIXTURE_DIR_ENV: str(fixture_dir),
            MANAGED_RUN_SCRIPTED_BACKEND_ENV: str(scripted_output),
        },
    ), patch(
        "dating_boost.core.standalone_runtime.StandaloneDraftPlanner.draft_for_match",
        _Planner().draft_for_match,
    ):
        runtime = build_managed_run_runtime(tmp_path / "data")
        started = runtime.start(_config(), run_id="run_fixture")
        result = runtime.tick("run_fixture")

    assert started["status"] == "active"
    assert runtime.provider_kind == "development_fixture"
    assert result["status"] == "confirmed"
    assert result["reason"] == "fresh_outbound_exact_text_verified"
    action = runtime.runtime.action
    assert isinstance(action, DevelopmentFixtureActionPort)
    assert action.calls == [
        "stage_text",
        "click_send",
        "observe_post_send",
    ]
    record = JsonManagedRunStore(tmp_path / "data").load("run_fixture")
    assert record is not None
    assert record.confirmed_send_count == 1
    assert {attempt["status"] for attempt in record.send_attempts.values()} == {"confirmed"}
    assert runtime.runtime.decision.planner.backend_config["path"] == str(scripted_output.resolve())


def test_fixture_registration_requires_both_explicit_environment_paths(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    with patch.dict(
        "os.environ",
        {MANAGED_RUN_FIXTURE_DIR_ENV: str(fixture_dir), MANAGED_RUN_SCRIPTED_BACKEND_ENV: ""},
    ):
        runtime = build_managed_run_runtime(tmp_path / "data")

    assert runtime.runnable is False
    assert runtime.tick("run_missing") == {
        "schema_version": 1,
        "status": "blocked",
        "reason": "managed_run_fixture_configuration_incomplete",
        "provider_kind": "fixture",
        "run_id": "run_missing",
    }


def test_provider_runtime_forwards_continuous_scheduler_options() -> None:
    runtime = Mock()
    runtime.store = object()
    runtime.run.return_value = {"status": "stopped"}
    facade = ManagedRunProviderRuntime(runtime, provider_kind="test", runnable=True)

    result = facade.run("run_1", max_steps=7, wait=True, poll_interval_seconds=0.25)

    assert result == {"status": "stopped"}
    runtime.run.assert_called_once_with(
        "run_1",
        max_steps=7,
        wait=True,
        poll_interval_seconds=0.25,
    )


@pytest.mark.parametrize(
    "quiet_hours",
    [
        "23:00-08:00",
        {"start": "23:00", "end": "08:00"},
        ({"start": "23:00"},),
        ({"start": "24:00", "end": "08:00"},),
        ({"start": "08:00", "end": "08:00"},),
        (object(),),
    ],
)
def test_provider_start_rejects_malformed_managed_authorization_quiet_hours(quiet_hours: object) -> None:
    runtime = Mock()
    runtime.store = object()
    facade = ManagedRunProviderRuntime(runtime, provider_kind="test", runnable=True)
    config = ManagedRunConfig(
        app_id="tinder",
        runtime="default",
        authorization=ManagedAuthorization(
            authorization_id="auth_bad_quiet_hours",
            app_id="tinder",
            runtime="default",
            allow_all_targets=True,
            live_send=True,
            quiet_hours=quiet_hours,
        ),
    )

    result = facade.start(config, run_id="run_must_not_start")

    assert result == {
        "schema_version": 1,
        "status": "blocked",
        "reason": "authorization_quiet_hours_invalid",
        "provider_kind": "test",
    }
    runtime.start.assert_not_called()


@pytest.mark.parametrize(
    "quiet_hours",
    [
        (),
        ({"start": "23:00", "end": "08:00"},),
        ("23:00-08:00",),
    ],
)
def test_provider_start_accepts_well_formed_managed_authorization_quiet_hours(quiet_hours: tuple[object, ...]) -> None:
    runtime = Mock()
    runtime.store = object()
    runtime.start.return_value = {"schema_version": 1, "status": "active", "run_id": "run_valid"}
    facade = ManagedRunProviderRuntime(runtime, provider_kind="test", runnable=True)
    config = ManagedRunConfig(
        app_id="tinder",
        runtime="default",
        authorization=ManagedAuthorization(
            authorization_id="auth_valid_quiet_hours",
            app_id="tinder",
            runtime="default",
            allow_all_targets=True,
            live_send=True,
            quiet_hours=quiet_hours,
        ),
    )

    result = facade.start(config, run_id="run_valid")

    assert result["status"] == "active"
    runtime.start.assert_called_once_with(config, run_id="run_valid")


def test_tashuo_observation_only_decision_handoffs_instead_of_claiming_live_send() -> None:
    decision = StandalonePlannerManagedDecisionPort(_Planner(), action_available=False)
    observation = ThreadObservation(
        target_id="match_ada",
        target_binding="tashuo-list-anchor:verified",
        inbound_revision="inbound_7",
        captured_at="2026-08-27T04:00:00Z",
        context={
            "match_id": "memory_match_ada",
            "standalone_thread_observation": {"assessment": {"recommended_next": "reply"}},
        },
    )

    result = decision.decide(observation, config=_config())

    assert result.outcome == "handoff"
    assert result.reason_codes == (MANAGED_LIVE_ACTION_PORT_STATUS,)
    assert result.text == "可以，周日下午怎么样？"


@pytest.mark.parametrize(
    ("nudge_enabled", "assessment", "expected_reason"),
    [
        (False, {"recommended_next": "nudge_later", "nudge_due": True}, "managed_nudge_disabled"),
        (True, {"recommended_next": "nudge_later"}, "managed_nudge_not_due"),
        (
            True,
            {"recommended_next": "nudge_later", "nudge_due_at": "2099-01-01T00:00:00Z"},
            "managed_nudge_not_due",
        ),
    ],
)
def test_nudge_later_waits_without_both_authorized_config_and_due_evidence(
    nudge_enabled: bool,
    assessment: dict[str, object],
    expected_reason: str,
) -> None:
    decision = StandalonePlannerManagedDecisionPort(_Planner())
    config = ManagedRunConfig(
        app_id="tinder",
        runtime="default",
        authorization=ManagedAuthorization(
            authorization_id="auth_nudge",
            app_id="tinder",
            runtime="default",
            autonomous_nudge=True,
            allow_all_targets=True,
        ),
        nudge_enabled=nudge_enabled,
    )
    observation = ThreadObservation(
        target_id="match_ada",
        target_binding="binding",
        inbound_revision="inbound_7",
        captured_at="2026-08-27T04:00:00Z",
        context={
            "match_id": "memory_match_ada",
            "standalone_thread_observation": {"assessment": assessment},
        },
    )

    result = decision.decide(observation, config=config)

    assert result.outcome == "wait"
    assert result.reason_codes == (expected_reason,)


@pytest.mark.parametrize("accessible", [True, False])
@pytest.mark.parametrize("visual", [True, False])
def test_live_observation_caches_only_corroborated_structured_binding_for_action_port(tmp_path: Path, accessible: bool, visual: bool) -> None:
    binding = {
        "binding_type": "current_thread_visual_identity",
        "candidate_key": "row_ada",
        "thread_evidence": {
            "observation_id": "obs_thread_ada",
            "screen_state": "tashuo_conversation",
            "latest_inbound_fingerprint": "inbound_7",
            "visual_anchor_hash": "thread-anchor",
            "visual_anchor_region": {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.84},
        },
        "message_list_evidence": {
            "visual_anchor_hash": "list-anchor",
            "visual_anchor_region": {"x1": 0.05, "y1": 0.2, "x2": 0.95, "y2": 0.3},
        },
    }

    class Provider:
        def observe_message_list(self, *, app_id: str, scan_cursor: dict[str, object]) -> dict[str, object]:
            return {
                "status": "ok",
                "observation_type": "message_list",
                "runtime": "mac-ios-app",
                "captured_at": "2026-08-27T04:00:00Z",
                "message_list_snapshot": {
                    "entries": [
                        {
                            "app_id": app_id,
                            "candidate_key": "row_ada",
                            "target_id": "match_ada",
                            "inbound_revision": "inbound_7",
                            "message_list_evidence": dict(binding["message_list_evidence"]),
                        }
                    ]
                },
                "scan_cursor": scan_cursor,
            }

        def observe_thread(self, *, app_id: str, candidate_key: str) -> dict[str, object]:
            return {
                "status": "ok",
                "observation_type": "thread",
                "app_id": app_id,
                "candidate_key": candidate_key,
                "target_id": "match_ada",
                "inbound_revision": "inbound_7",
                "captured_at": "2026-08-27T04:00:01Z",
                "target_binding": binding,
                "assessment": {"recommended_next": "wait"},
                "observation": _app_observation(),
            }

    managed_revision = ("visual-frame-v1:" if visual else "ax-static-v1:") + "managed-revision"
    revision_payload = {
        "status": "ok" if accessible else "blocked",
        "reason": "managed_conversation_text_not_accessible",
        "inbound_revision": managed_revision,
        "inbound_revision_observation_id": "managed_revision_obs_1",
        "inbound_revision_captured_at": "2026-08-27T04:00:01.500000Z",
        "evidence_source": "visible_conversation_screenshot" if visual else "macos_accessibility_static_text",
    }
    ax_observer = Mock(return_value=revision_payload)
    binder = Mock(return_value=revision_payload)
    port = StandaloneObservationManagedRunPort(
        tmp_path,
        Provider(),
        fixture_mode=False,
        live_inbound_revision_observer=ax_observer,
        live_thread_binder=binder if visual else None,
    )
    snapshot = port.scan_message_list(
        run_id="run_1",
        app_id="tashuo",
        runtime="mac-ios-app",
        cursor={},
    )
    candidate = snapshot.candidates[0]

    if not accessible:
        with pytest.raises(ManagedActionError) as caught:
            port.open_thread(candidate)
        assert caught.value.reason_code == "managed_conversation_text_not_accessible"
        assert "verified_target_binding" not in candidate.metadata
        return
    port.open_thread(candidate)
    port.observe_thread(candidate)

    verified_binding = candidate.metadata["verified_target_binding"]
    assert verified_binding["thread_evidence"]["managed_inbound_revision"] == managed_revision
    assert (
        verified_binding["thread_evidence"]["managed_inbound_revision_observation_id"]
        == "managed_revision_obs_1"
    )
    assert candidate.metadata["verified_inbound_revision"] == "inbound_7"
    if visual:
        ax_observer.assert_not_called()
        binder.assert_called_once()
        assert "managed_message_text_hashes" not in verified_binding["thread_evidence"]
        assert verified_binding["thread_evidence"]["managed_inbound_revision_source"] == "visible_conversation_screenshot"
    else:
        assert verified_binding["thread_evidence"]["managed_message_text_hashes"] == [
            hashlib.sha256(text.encode()).hexdigest() for text in ["周末有空", "那你定呀"]
        ]


@pytest.mark.parametrize("messages", [None, [], [{"sender": "system", "text": "system only"}], [{"sender": "match", "text": ""}], [None]])
def test_visible_message_coverage_expectations_fail_closed_when_missing(messages) -> None:
    from dating_boost.core.managed_run_provider import _visible_message_text_hashes

    raw = {"observation": {"conversation_observation": {"visible_messages": messages}}}
    with pytest.raises(ManagedActionError) as caught:
        _visible_message_text_hashes(raw)
    assert caught.value.reason_code == "managed_conversation_text_not_accessible"


def test_visible_message_coverage_uses_only_ordered_non_system_body_hashes() -> None:
    from dating_boost.core.managed_run_provider import _visible_message_text_hashes

    messages = [{"sender": "system", "text": "system"}] + [{"sender": sender, "text": "repeat"} for sender in ["match", "user"]]
    assert _visible_message_text_hashes({"observation": {"conversation_observation": {"visible_messages": messages}}}) == [hashlib.sha256(b"repeat").hexdigest()] * 2


class _ManagedActionAdapter:
    def __init__(self) -> None:
        self.text = ""
        self.calls: list[str] = []
        self.inbound_revisions: list[str] = []

    def _record_revision(self, kwargs: dict[str, object]) -> None:
        self.inbound_revisions.append(str(kwargs.get("inbound_revision") or ""))

    def observe_managed_composer(self, **kwargs: object) -> dict[str, object]:
        self.calls.append("observe")
        self._record_revision(kwargs)
        return {"status": "ok", "composer_text": self.text, "captured_at": "2026-08-27T04:00:02Z"}

    def stage_managed_text(self, text: str, **kwargs: object) -> dict[str, object]:
        self.calls.append("stage")
        self._record_revision(kwargs)
        self.text = text
        return {
            "status": "ok",
            "staged_exact_text_ax_verified": True,
            "post_stage_inbound_revision_verified": True,
            "captured_at": "2026-08-27T04:00:02Z",
        }

    def click_managed_send_only(self, text: str, **kwargs: object) -> dict[str, object]:
        self.calls.append("click")
        self._record_revision(kwargs)
        assert text == self.text
        return {
            "status": "ok",
            "receipt_id": "receipt_ada",
            "clicked_at": "2026-08-27T04:00:03Z",
            "_pre_click_screen": {"status": "ok"},
        }

    def observe_managed_post_send(self, text: str, **kwargs: object) -> dict[str, object]:
        self.calls.append("post")
        self._record_revision(kwargs)
        return {
            "status": "ok",
            "post_action_observation_id": "post_ada",
            "captured_at": "2026-08-27T04:00:04Z",
            "input_cleared": True,
            "outbound_exact_text_ax_verified": True,
            "fresh_outbound_occurrence_verified": True,
        }


def test_truncated_list_preview_defers_to_full_thread_revision_for_send_and_dedup(tmp_path: Path) -> None:
    truncated_previews = [
        "我工作时间没办法哈哈哈 但我也喜…",
        "我工作时间没办法哈哈哈 但我也喜欢…",
    ]
    full_inbound = "我工作时间没办法哈哈哈 但我也喜欢周末出去走走"
    preview_revisions = [hashlib.sha256(value.encode("utf-8")).hexdigest() for value in truncated_previews]
    authoritative_revision = hashlib.sha256(full_inbound.encode("utf-8")).hexdigest()
    assert authoritative_revision not in preview_revisions

    binding = {
        "binding_type": "current_thread_visual_identity",
        "candidate_key": "row_ada",
        "thread_evidence": {
            "observation_id": "obs_thread_ada",
            "screen_state": "tashuo_conversation",
            "latest_inbound_fingerprint": authoritative_revision,
            "visual_anchor_hash": "thread-anchor",
            "visual_anchor_region": {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.84},
        },
        "message_list_evidence": {
            "visual_anchor_hash": "list-anchor",
            "visual_anchor_region": {"x1": 0.05, "y1": 0.2, "x2": 0.95, "y2": 0.3},
        },
    }

    class Provider:
        scan_count = 0
        thread_count = 0

        def observe_message_list(self, *, app_id: str, scan_cursor: dict[str, object]) -> dict[str, object]:
            revision = preview_revisions[min(self.scan_count, len(preview_revisions) - 1)]
            self.scan_count += 1
            return {
                "status": "ok",
                "observation_type": "message_list",
                "runtime": "mac-ios-app",
                "captured_at": "2026-08-27T04:00:00Z",
                "message_list_snapshot": {
                    "entries": [
                        {
                            "app_id": app_id,
                            "candidate_key": "row_ada",
                            "target_id": "match_ada",
                            "latest_preview_hash": revision,
                            "message_list_evidence": dict(binding["message_list_evidence"]),
                        }
                    ]
                },
                "scan_cursor": scan_cursor,
            }

        def observe_thread(self, *, app_id: str, candidate_key: str) -> dict[str, object]:
            self.thread_count += 1
            return {
                "status": "ok",
                "observation_type": "thread",
                "app_id": app_id,
                "candidate_key": candidate_key,
                "target_id": "match_ada",
                "latest_inbound_fingerprint": authoritative_revision,
                "captured_at": "2026-08-27T04:00:01Z",
                "target_binding": binding,
                "assessment": {"recommended_next": "reply"},
                "observation": {**_app_observation(), "conversation_observation": {
                    "visible_messages": [{"sender": "match", "text": full_inbound}],
                }},
            }

    class Decision:
        def __init__(self) -> None:
            self.revisions: list[str] = []

        def prioritize(
            self,
            candidates: list[ThreadCandidate] | tuple[ThreadCandidate, ...],
            *,
            thread_states: object,
        ) -> ThreadCandidate | None:
            del thread_states
            return candidates[0] if candidates else None

        def decide(self, observation: ThreadObservation, *, config: ManagedRunConfig) -> DraftDecision:
            del config
            self.revisions.append(observation.inbound_revision)
            return DraftDecision.send(
                decision_id="decision_full_inbound",
                target_id=observation.target_id,
                inbound_revision=observation.inbound_revision,
                text="听起来周末派更适合你哈哈",
            )

    data_dir = tmp_path / "data"
    provider = Provider()
    observation = StandaloneObservationManagedRunPort(
        data_dir,
        provider,
        fixture_mode=False,
        live_inbound_revision_observer=lambda _binding: {
            "status": "ok",
            "inbound_revision": "ax-static-v1:managed-revision",
            "inbound_revision_observation_id": "managed_revision_obs_1",
            "inbound_revision_captured_at": "2026-08-27T04:00:01.500000Z",
        },
    )
    decision = Decision()
    adapter = _ManagedActionAdapter()
    action = TaShuoMacIosManagedActionPort(
        data_dir,
        output_dir=tmp_path / "harness",
        adapter_factory=lambda: adapter,
    )
    runtime = ManagedRun(JsonManagedRunStore(data_dir), observation, decision, action)
    config = ManagedRunConfig(
        app_id="tashuo",
        runtime="mac-ios-app",
        authorization=ManagedAuthorization(
            authorization_id="auth_truncated_preview",
            app_id="tashuo",
            runtime="mac-ios-app",
            allow_all_targets=True,
        ),
    )

    runtime.start(config, run_id="run_truncated_preview")
    run_result = runtime.run(max_steps=3)
    first, second, third = run_result["steps"]

    assert run_result["processed_count"] == 1
    assert first["status"] == "confirmed"
    assert second["status"] == "no_work"
    assert second["reason"] == "inbound_revision_already_processed"
    assert third["status"] == "no_work"
    assert third["reason"] == "no_eligible_thread"
    assert provider.thread_count == 2
    assert decision.revisions == [authoritative_revision]
    assert adapter.calls == ["stage", "click", "post"]
    record = JsonManagedRunStore(data_dir).load("run_truncated_preview")
    assert record is not None
    assert record.thread_states["match_ada"]["last_inbound_revision"] == authoritative_revision
    assert record.thread_states["match_ada"]["last_discovery_revision"] == preview_revisions[-1]
    attempt = next(iter(record.send_attempts.values()))
    assert attempt["inbound_revision"] == authoritative_revision
    assert attempt["discovery_revision"] == preview_revisions[0]


def test_tashuo_action_port_uses_split_adapter_boundaries_without_all_in_one_send(tmp_path: Path) -> None:
    adapter = _ManagedActionAdapter()
    port = TaShuoMacIosManagedActionPort(
        tmp_path,
        output_dir=tmp_path / "harness",
        adapter_factory=lambda: adapter,
    )
    candidate = ThreadCandidate(
        candidate_key="row_ada",
        target_id="match_ada",
        target_binding="tashuo-list-anchor:verified",
        discovery_revision="preview_ada_7",
        inbound_revision="inbound_7",
        metadata={
            "verified_target_binding": {
                "binding_type": "current_thread_visual_identity",
                "thread_evidence": {
                    "managed_inbound_revision": "ax-static-v1:managed-revision",
                    "managed_inbound_revision_observation_id": "managed_revision_obs_1",
                },
            },
            "verified_inbound_revision": "inbound_7",
        },
    )

    staged = port.stage_text(candidate, "可以，周日下午怎么样？")
    receipt = port.click_send(candidate)
    post = port.observe_post_send(candidate, receipt)

    assert staged.text == "可以，周日下午怎么样？"
    assert post.outbound_text == staged.text
    assert adapter.calls == ["stage", "click", "post"]
    assert adapter.inbound_revisions == ["ax-static-v1:managed-revision"] * 3
    assert not hasattr(adapter, "send_message")


@pytest.mark.parametrize("proof", ["valid", "absent", "wrong_revision", "stale_observation", "wrong_time", "missing_anchor", "wrong_region"])
def test_live_burst_continuation_advances_only_proven_ax_baseline(tmp_path: Path, proof: str) -> None:
    adapter = _ManagedActionAdapter()
    original_post = adapter.observe_managed_post_send
    next_revision = "ax-static-v1:" + "a" * 64

    def post(text: str, **kwargs: object) -> dict[str, object]:
        payload = original_post(text, **kwargs)
        payload.update({
            "continuation_verified": proof != "absent",
            "continuation_inbound_revision": next_revision if proof != "wrong_revision" else "arbitrary",
            "continuation_inbound_revision_observation_id": "post_ada" if proof != "stale_observation" else "baseline",
            "continuation_inbound_revision_captured_at": payload["captured_at"] if proof != "wrong_time" else "stale",
            "continuation_visual_anchor_hash": "ffffffffffffffff" if proof != "missing_anchor" else None,
            "continuation_visual_anchor_region": {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65 if proof != "wrong_region" else 0.66},
        })
        return payload

    adapter.observe_managed_post_send = post
    port = TaShuoMacIosManagedActionPort(tmp_path, output_dir=tmp_path / "harness", adapter_factory=lambda: adapter)
    original_binding = {
        "binding_type": "current_thread_visual_identity",
        "thread_evidence": {
            "visual_anchor_hash": "retained-anchor",
            "managed_inbound_revision": "ax-static-v1:baseline",
            "managed_inbound_revision_observation_id": "baseline",
            "managed_message_text_hashes": [hashlib.sha256(b"old message").hexdigest()],
        },
    }
    candidate = ThreadCandidate(
        candidate_key="row", target_id="target", target_binding="binding",
        discovery_revision="preview", inbound_revision="original-inbound",
        metadata={"verified_target_binding": original_binding, "verified_inbound_revision": "original-inbound"},
    )
    port.stage_text(candidate, "第一条")
    receipt = port.click_send(candidate)
    observed = port.observe_post_send(candidate, receipt)
    assert observed.outbound_text == "第一条"  # Confirmation does not depend on permission to continue.
    assert observed.continuation_verified is (proof == "valid")
    binding = candidate.metadata["verified_target_binding"]
    expected_revision = next_revision if proof == "valid" else "ax-static-v1:baseline"
    assert binding["thread_evidence"]["managed_inbound_revision"] == expected_revision
    assert binding["thread_evidence"]["visual_anchor_hash"] == ("ffffffffffffffff" if proof == "valid" else "retained-anchor")
    assert candidate.metadata["verified_inbound_revision"] == "original-inbound"
    assert original_binding["thread_evidence"]["managed_inbound_revision"] == "ax-static-v1:baseline"
    expected_messages = [hashlib.sha256(b"old message").hexdigest()]
    if proof == "valid":
        expected_messages.append(hashlib.sha256("第一条".encode()).hexdigest())
    assert binding["thread_evidence"]["managed_message_text_hashes"] == expected_messages
    if proof == "valid":
        staged = port.stage_text(candidate, "第二条")
        assert staged.inbound_revision == "original-inbound"
        assert adapter.inbound_revisions[-1] == next_revision


def test_live_port_forwards_burst_deadline_to_irreversible_boundary(tmp_path: Path) -> None:
    adapter = _ManagedActionAdapter()
    adapter.click_managed_send_only = Mock(wraps=adapter.click_managed_send_only)
    port = TaShuoMacIosManagedActionPort(tmp_path, output_dir=tmp_path / "harness", adapter_factory=lambda: adapter)
    candidate = ThreadCandidate(
        candidate_key="row", target_id="target", target_binding="binding",
        discovery_revision="preview", inbound_revision="inbound",
        metadata={
            "verified_inbound_revision": "inbound",
            "verified_target_binding": {"thread_evidence": {"managed_inbound_revision": "ax-static-v1:baseline"}},
            "managed_burst_click_deadline_at": "2026-09-20T04:00:20Z",
        },
    )
    port.stage_text(candidate, "第二条")
    port.click_send(candidate)
    assert adapter.click_managed_send_only.call_args.kwargs["click_deadline_at"] == "2026-09-20T04:00:20Z"


@pytest.mark.parametrize("message_count", [2, 3])
def test_managed_runtime_burst_uses_each_fresh_ax_binding_without_replanning(tmp_path: Path, message_count: int) -> None:
    now = [datetime(2026, 9, 20, 4, tzinfo=timezone.utc)]

    def timestamp() -> str:
        now[0] += timedelta(seconds=1)
        return now[0].isoformat()

    class Adapter(_ManagedActionAdapter):
        revision = "ax-static-v1:" + "a" * 64
        anchor = "0000000000000000"
        sends = 0

        def _record_revision(self, kwargs):
            super()._record_revision(kwargs)
            assert kwargs["inbound_revision"] == self.revision
            assert kwargs["target_binding"]["thread_evidence"]["managed_inbound_revision"] == self.revision
            assert kwargs["target_binding"]["thread_evidence"]["visual_anchor_hash"] == self.anchor

        def stage_managed_text(self, text, **kwargs):
            assert self.text == ""
            payload = super().stage_managed_text(text, **kwargs)
            return {**payload, "captured_at": timestamp()}

        def click_managed_send_only(self, text, **kwargs):
            payload = super().click_managed_send_only(text, **kwargs)
            assert ("click_deadline_at" in kwargs) is (self.sends > 0)
            self.sends += 1
            return {**payload, "receipt_id": f"receipt_{self.sends}", "clicked_at": timestamp()}

        def observe_managed_post_send(self, text, **kwargs):
            payload = super().observe_managed_post_send(text, **kwargs)
            self.text = ""
            self.revision = "ax-static-v1:" + hashlib.sha256((self.revision + text).encode()).hexdigest()
            self.anchor = f"{self.sends:016x}"
            captured_at = timestamp()
            observation_id = f"post_{self.sends}"
            return {
                **payload, "captured_at": captured_at, "post_action_observation_id": observation_id,
                "continuation_verified": True, "continuation_inbound_revision": self.revision,
                "continuation_inbound_revision_observation_id": observation_id,
                "continuation_inbound_revision_captured_at": captured_at,
                "continuation_visual_anchor_hash": self.anchor,
                "continuation_visual_anchor_region": {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65},
            }

    adapter = Adapter()
    candidate = ThreadCandidate(
        candidate_key="row", target_id="target", target_binding="binding",
        discovery_revision="preview", inbound_revision="inbound",
        metadata={
            "verified_inbound_revision": "inbound",
            "verified_target_binding": {
                "binding_type": "current_thread_visual_identity",
                "thread_evidence": {
                    "managed_inbound_revision": adapter.revision,
                    "visual_anchor_hash": adapter.anchor,
                    "managed_message_text_hashes": [hashlib.sha256(b"old message").hexdigest()],
                },
            },
        },
    )
    observation = Mock()
    observation.scan_message_list.return_value = MessageListSnapshot((candidate,), timestamp())
    observation.open_thread.return_value = OpenThreadObservation("target", "binding", timestamp())
    observation.observe_thread.return_value = ThreadObservation(
        "target", "binding", "inbound", timestamp(), {"match_id": "match"},
    )
    planner = Mock()
    planner.draft_for_match.return_value = {
        "status": "ok", "draft": {"best_reply": "备用", "message_sequence": ["哈哈", "有画面了", "后来呢？"][:message_count]},
    }
    store = InMemoryManagedRunStore()
    runtime = ManagedRun(
        store, observation, StandalonePlannerManagedDecisionPort(planner),
        TaShuoMacIosManagedActionPort(tmp_path, output_dir=tmp_path / "harness", adapter_factory=lambda: adapter),
        now=lambda: now[0],
    )
    config = ManagedRunConfig(
        app_id="tashuo", runtime="mac-ios-app", max_sends_per_run=3,
        authorization=ManagedAuthorization(
            authorization_id="auth_burst", app_id="tashuo", runtime="mac-ios-app", allow_all_targets=True,
        ),
    )
    runtime.start(config, run_id="burst")
    result = runtime.tick()
    assert result["status"] == "confirmed"
    assert result["completed_message_count"] == message_count
    assert adapter.calls == ["stage", "click", "post"] * message_count
    planner.draft_for_match.assert_called_once()
    observation.scan_message_list.assert_called_once()
    assert store.load("burst").confirmed_send_count == message_count


def test_tashuo_live_factory_is_runnable_only_with_explicit_config_and_runtime_scope(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    RuntimeScopeRepository(data_dir).select(app_id="tashuo", runtime="mac-ios-app")
    config_path = tmp_path / "tashuo-managed.json"
    config_path.write_text(
        json.dumps(
            {
                "app_id": "tashuo",
                "runtime": "mac-ios-app",
                "output_dir": str(tmp_path / "harness"),
                "vision_backend": {"type": "scripted", "path": str(tmp_path / "vision.json")},
                "backend": {"type": "scripted", "path": str(tmp_path / "draft.json")},
            }
        ),
        encoding="utf-8",
    )
    with patch.dict(
        "os.environ",
        {
            MANAGED_RUN_FIXTURE_DIR_ENV: "",
            MANAGED_RUN_SCRIPTED_BACKEND_ENV: "",
            MANAGED_RUN_TASHUO_CONFIG_ENV: str(config_path),
        },
    ), patch(
        "dating_boost.intelligence.vision_backend_factory.create_vision_backend",
        return_value=object(),
    ):
        runtime = build_managed_run_runtime(data_dir)

    assert runtime.runnable is True
    assert runtime.provider_kind == "tashuo_mac_ios_live"
    from dating_boost.core.managed_visual_action import TaShuoVisualManagedActionPort
    assert isinstance(runtime.runtime.action, TaShuoVisualManagedActionPort)
    assert runtime.runtime.observation.live_inbound_revision_observer is None
    assert runtime.runtime.observation.live_thread_binder == runtime.runtime.action.bind_thread
    assert runtime.runtime.observation.provider.thread_capture == runtime.runtime.action.io.capture_initial_thread


def test_tashuo_product_start_uses_existing_minimax_defaults_without_provider_json(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    RuntimeScopeRepository(data_dir).select(app_id="tashuo", runtime="mac-ios-app")
    config = ManagedRunConfig(
        app_id="tashuo",
        runtime="mac-ios-app",
        authorization=ManagedAuthorization(
            authorization_id="auth_tashuo_default",
            app_id="tashuo",
            runtime="mac-ios-app",
            allow_all_targets=True,
            autonomous_send=True,
            live_send=True,
            requires_post_action_verification=True,
        ),
    )

    with patch.dict(
        "os.environ",
        {
            MANAGED_RUN_FIXTURE_DIR_ENV: "",
            MANAGED_RUN_SCRIPTED_BACKEND_ENV: "",
            MANAGED_RUN_TASHUO_CONFIG_ENV: "",
        },
    ), patch(
        "dating_boost.intelligence.vision_backend_factory.create_vision_backend",
        return_value=object(),
    ) as create_vision:
        runtime = build_managed_run_runtime(data_dir, requested_config=config)

    assert runtime.runnable is True
    assert runtime.provider_kind == "tashuo_mac_ios_live"
    assert runtime.runtime.decision.planner.backend_config == {"type": "minimax"}
    assert runtime.runtime.observation.provider.thread_capture == runtime.runtime.action.io.capture_initial_thread
    create_vision.assert_called_once_with({"type": "minimax"})


def test_tashuo_product_runtime_cannot_start_without_autonomous_user_readiness(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    RuntimeScopeRepository(data_dir).select(app_id="tashuo", runtime="mac-ios-app")
    config = ManagedRunConfig(
        app_id="tashuo",
        runtime="mac-ios-app",
        authorization=ManagedAuthorization(
            authorization_id="auth_tashuo_missing_profile",
            app_id="tashuo",
            runtime="mac-ios-app",
            allow_all_targets=True,
            autonomous_send=True,
            live_send=True,
            requires_post_action_verification=True,
        ),
    )

    with patch.dict(
        "os.environ",
        {
            MANAGED_RUN_FIXTURE_DIR_ENV: "",
            MANAGED_RUN_SCRIPTED_BACKEND_ENV: "",
            MANAGED_RUN_TASHUO_CONFIG_ENV: "",
        },
    ), patch(
        "dating_boost.intelligence.vision_backend_factory.create_vision_backend",
        return_value=object(),
    ):
        runtime = build_managed_run_runtime(data_dir, requested_config=config)
        payload = runtime.start(config, run_id="run_missing_profile")

    assert payload["status"] == "needs_user_profile"
    assert payload["reason"] == "autonomous_requires_user_profile"
    assert payload["user_profile_readiness"]["ready"] is False
    assert JsonManagedRunStore(data_dir).current_run_id() is None


def test_new_scan_invalidates_candidates_from_previous_discovery_generation(tmp_path: Path) -> None:
    provider = Mock()
    first = {
        "status": "ok", "observation_type": "message_list", "captured_at": "2026-09-20T04:00:00Z",
        "message_list_snapshot": {"entries": [{
            "candidate_key": "old-row", "target_id": "old-target", "inbound_revision": "old-preview",
            "target_binding": "fixture:old",
        }]},
    }
    provider.observe_message_list.side_effect = [first, {**first, "message_list_snapshot": {"entries": []}}]
    port = StandaloneObservationManagedRunPort(tmp_path, provider, fixture_mode=True)
    original = port.scan_message_list(run_id="r", app_id="tinder", runtime="default", cursor={})
    port.scan_message_list(run_id="r", app_id="tinder", runtime="default", cursor={})

    with pytest.raises(ValueError, match="managed_candidate_not_from_latest_scan"):
        port.open_thread(original.candidates[0])
    provider.observe_thread.assert_not_called()


def _app_observation() -> dict[str, object]:
    return {
        "observation_id": "obs_fixture_ada_7",
        "source_type": "manual_fixture",
        "app_id": "tinder",
        "adapter_id": "managed.fixture.v1",
        "captured_at": "2026-08-27T04:00:01Z",
        "page_type": "chat_thread",
        "page_confidence": "high",
        "match_identity_hints": {
            "visible_name": "Ada",
            "profile_cues": [],
            "conversation_fingerprint": "fixture-ada-conversation",
            "evidence": "ManagedRun development fixture.",
        },
        "profile_observation": {
            "profile_text": "",
            "photo_cues": [],
            "hook_candidates": [],
            "review_status": "missing",
            "evidence": "",
        },
        "conversation_observation": {
            "visible_messages": [
                {"sender": "user", "text": "周末有空"},
                {"sender": "match", "text": "那你定呀"},
            ],
            "latest_inbound_messages": [{"sender": "match", "text": "那你定呀"}],
            "input_state": "empty",
            "thread_cues": ["match delegated choice"],
        },
        "element_observations": [],
        "exception_state": "none",
        "provenance": {"runtime": "default", "source": "managed_fixture"},
        "raw_ref": None,
    }
