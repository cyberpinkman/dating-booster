from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from dating_boost.core.managed_run import ManagedAuthorization, ManagedRunConfig, ThreadObservation
from dating_boost.core.managed_run_provider import (
    MANAGED_RUN_JEV_ENV,
    StandalonePlannerManagedDecisionPort,
    _build_managed_triage,
    build_managed_run_runtime,
)
from dating_boost.core.runtime_scope import RuntimeScopeRepository
from dating_boost.intelligence.managed_triage import JevManagedTriage, TRIAGE_QUESTIONS
from dating_boost.intelligence.typesafe import ChoiceAnswer, TypeSafeError


pytestmark = pytest.mark.managed_critical


def _raw() -> dict:
    return {
        "assessment": {"recommended_next": "reply"},
        "observation": {
            "page_type": "chat_thread",
            "page_confidence": "high",
            "match_identity_hints": {"visible_name": "Private name"},
            "raw_ref": "/private/screenshot.png",
            "conversation_observation": {
                "visible_messages": [
                    {"sender": "user", "text": "先忙你的，晚点聊"},
                    {"sender": "match", "text": "好呀，晚点聊"},
                ],
            },
        },
    }


def _answer(question: str, choice: str, confidence: float = 0.96) -> ChoiceAnswer:
    options = TRIAGE_QUESTIONS[question]["criteria"]
    return ChoiceAnswer(
        choice=choice,
        confidence=confidence,
        probabilities={key: 0.98 if key == choice else 0.02 / (len(options) - 1) for key in options},
    )


def _client(boundary: str = "ordinary_chat", need: str = "wait", *, confidence: float = 0.96) -> Mock:
    client = Mock()
    client.evaluate.return_value = SimpleNamespace(
        answers={
            "boundary": _answer("boundary", boundary, confidence),
            "response_need": _answer("response_need", need, confidence),
        },
        model="jev-test",
        duration_ms=40.0,
        input_tokens=100,
        output_tokens=30,
    )
    return client


@pytest.mark.parametrize(
    ("boundary", "need", "confidence", "expected"),
    [
        ("ordinary_chat", "wait", 0.96, "wait"),
        ("ordinary_chat", "reply", 0.96, "draft"),
        ("user_handoff", "uncertain", 0.96, "handoff"),
        ("ordinary_chat", "uncertain", 0.96, "fallback"),
        ("uncertain", "wait", 0.96, "fallback"),
        ("ordinary_chat", "wait", 0.50, "fallback"),
    ],
)
def test_independent_routing_questions_share_one_request(boundary, need, confidence, expected) -> None:
    client = _client(boundary, need, confidence=confidence)
    result = JevManagedTriage(client).evaluate(_raw())
    assert result.route == expected
    client.evaluate.assert_called_once()
    request = client.evaluate.call_args.kwargs
    assert set(request["questions"]) == {"boundary", "response_need"}
    assert set(request["state"]) == {"conversation"}
    assert "Private name" not in str(request)
    assert "/private/screenshot.png" not in str(request)
    assert result.metrics["request_count"] == 1
    assert "晚点聊" not in str(result.metrics)


def test_handoff_does_not_depend_on_uncertainty_in_unused_reply_question() -> None:
    client = _client("user_handoff", "uncertain")
    client.evaluate.return_value.answers["response_need"] = _answer("response_need", "uncertain", 0.01)
    assert JevManagedTriage(client).evaluate(_raw()).route == "handoff"


def test_concentrated_confidence_does_not_replace_option_probability() -> None:
    client = _client()
    client.evaluate.return_value.answers["boundary"] = ChoiceAnswer(
        choice="ordinary_chat", confidence=0.99,
        probabilities={"ordinary_chat": 0.6, "user_handoff": 0.2, "uncertain": 0.2},
    )
    assert JevManagedTriage(client).evaluate(_raw()).route == "fallback"


@pytest.mark.parametrize("condition", ["low_confidence", "too_large", "no_inbound", "wrong_page", "missing"])
def test_incomplete_observation_does_not_become_a_semantic_shortcut(condition) -> None:
    raw = _raw()
    messages = raw["observation"]["conversation_observation"]["visible_messages"]
    if condition == "low_confidence":
        messages[1]["confidence"] = "low"
    elif condition == "too_large":
        messages[0]["text"] = "x" * 12001
    elif condition == "no_inbound":
        messages.reverse()
    elif condition == "wrong_page":
        raw["observation"]["page_type"] = "question_gate"
    else:
        raw = {}
    client = _client()
    assert JevManagedTriage(client).evaluate(raw).route == "fallback"
    client.evaluate.assert_not_called()


def test_service_failure_falls_back_without_retrying_each_thread() -> None:
    now = [10.0]
    client = _client()
    client.evaluate.side_effect = TypeSafeError("typesafe_timeout")
    triage = JevManagedTriage(client, monotonic=lambda: now[0])
    first = triage.evaluate(_raw())
    second = triage.evaluate(_raw())
    assert first.route == second.route == "fallback"
    assert first.reason == "typesafe_timeout"
    assert second.reason == "typesafe_service_cooldown"
    assert client.evaluate.call_count == 1
    now[0] = 41
    triage.evaluate(_raw())
    assert client.evaluate.call_count == 2


def _config() -> ManagedRunConfig:
    return ManagedRunConfig(
        app_id="tashuo", runtime="mac-ios-app",
        authorization=ManagedAuthorization(
            authorization_id="test-auth", app_id="tashuo", runtime="mac-ios-app",
            allow_all_targets=True, live_send=True,
        ),
    )


def _observation(raw: dict) -> ThreadObservation:
    return ThreadObservation(
        target_id="test-target", target_binding="binding", inbound_revision="fresh-inbound",
        captured_at="2026-09-20T04:00:00Z",
        context={"match_id": "test-match", "standalone_thread_observation": raw},
    )


@pytest.mark.parametrize(("boundary", "need", "outcome", "drafts"), [
    ("ordinary_chat", "wait", "wait", 0),
    ("user_handoff", "reply", "handoff", 0),
    ("ordinary_chat", "reply", "send", 1),
    ("uncertain", "reply", "send", 1),
])
def test_route_avoids_only_unnecessary_drafting(boundary, need, outcome, drafts) -> None:
    planner = Mock()
    planner.draft_for_match.return_value = {"status": "ok", "draft": {"best_reply": "工作忙完啦"}}
    decision = StandalonePlannerManagedDecisionPort(planner, triage=JevManagedTriage(_client(boundary, need)))
    result = decision.decide(_observation(_raw()), config=_config())
    assert result.outcome == outcome
    assert result.inbound_revision == "fresh-inbound"
    assert result.target_id == "test-target"
    assert planner.draft_for_match.call_count == drafts


def test_jev_reply_cannot_override_existing_policy_rejection_or_nudge_gate() -> None:
    planner = Mock()
    planner.draft_for_match.return_value = {"status": "blocked", "reason": "policy_rejected"}
    client = _client(need="reply")
    decision = StandalonePlannerManagedDecisionPort(planner, triage=JevManagedTriage(client))
    assert decision.decide(_observation(_raw()), config=_config()).reason_codes == ("policy_rejected",)
    raw = _raw()
    raw["assessment"] = {"recommended_next": "nudge_later", "nudge_due": True}
    result = decision.decide(_observation(raw), config=_config())
    assert result.reason_codes == ("managed_nudge_disabled",)
    assert client.evaluate.call_count == planner.draft_for_match.call_count == 1
    assert decision.last_triage_metrics == {}


def test_api_failure_preserves_existing_draft_path() -> None:
    planner = Mock()
    planner.draft_for_match.return_value = {"status": "ok", "draft": {"best_reply": "工作忙完啦"}}
    client = _client()
    client.evaluate.side_effect = TypeSafeError("typesafe_timeout")
    decision = StandalonePlannerManagedDecisionPort(planner, triage=JevManagedTriage(client))
    assert decision.decide(_observation(_raw()), config=_config()).outcome == "send"
    planner.draft_for_match.assert_called_once_with(match_id="test-match", mode="adaptive")
    assert decision.last_triage_metrics["route"] == "fallback"


def test_key_presence_does_not_implicitly_enable_external_service(monkeypatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    monkeypatch.delenv(MANAGED_RUN_JEV_ENV, raising=False)
    assert _build_managed_triage({}) is None
    monkeypatch.setenv(MANAGED_RUN_JEV_ENV, "1")
    assert isinstance(_build_managed_triage({}), JevManagedTriage)
    assert _build_managed_triage({"semantic_router": {"type": "disabled"}}) is None


def test_explicit_jev_without_key_blocks_before_gui_or_model_setup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    for name in ("DATING_BOOST_MANAGED_RUN_FIXTURE_DIR", "DATING_BOOST_MANAGED_RUN_SCRIPTED_BACKEND_OUTPUT",
                 "DATING_BOOST_MANAGED_RUN_TASHUO_CONFIG", "TYPESAFE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(MANAGED_RUN_JEV_ENV, "1")
    RuntimeScopeRepository(tmp_path).select(app_id="tashuo", runtime="mac-ios-app")
    with patch("dating_boost.intelligence.vision_backend_factory.create_vision_backend") as vision:
        runtime = build_managed_run_runtime(tmp_path, requested_config=_config())
    assert runtime.runnable is False
    assert "key" in runtime.unavailable_reason
    vision.assert_not_called()


@pytest.mark.parametrize("threshold", [False, 0, -1, 1.1, float("nan"), float("inf"), "0.8"])
def test_thresholds_must_be_finite_probabilities(threshold) -> None:
    with pytest.raises(ValueError):
        JevManagedTriage(_client(), confidence_threshold=threshold)
