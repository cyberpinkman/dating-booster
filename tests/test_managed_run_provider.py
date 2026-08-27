from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from dating_boost.core.managed_run import (
    JsonManagedRunStore,
    ManagedAuthorization,
    ManagedRun,
    ManagedRunConfig,
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
)
from dating_boost.core.runtime_scope import RuntimeScopeRepository


pytestmark = pytest.mark.managed_critical


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


def test_live_observation_caches_only_corroborated_structured_binding_for_action_port(tmp_path: Path) -> None:
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
            }

    managed_revision = "ax-static-v1:managed-revision"
    port = StandaloneObservationManagedRunPort(
        tmp_path,
        Provider(),
        fixture_mode=False,
        live_inbound_revision_observer=lambda _binding: {
            "status": "ok",
            "inbound_revision": managed_revision,
            "inbound_revision_observation_id": "managed_revision_obs_1",
            "inbound_revision_captured_at": "2026-08-27T04:00:01.500000Z",
        },
    )
    snapshot = port.scan_message_list(
        run_id="run_1",
        app_id="tashuo",
        runtime="mac-ios-app",
        cursor={},
    )
    candidate = snapshot.candidates[0]

    port.open_thread(candidate)
    port.observe_thread(candidate)

    verified_binding = candidate.metadata["verified_target_binding"]
    assert verified_binding["thread_evidence"]["managed_inbound_revision"] == managed_revision
    assert (
        verified_binding["thread_evidence"]["managed_inbound_revision_observation_id"]
        == "managed_revision_obs_1"
    )
    assert candidate.metadata["verified_inbound_revision"] == "inbound_7"


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
    assert isinstance(runtime.runtime.action, TaShuoMacIosManagedActionPort)


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
