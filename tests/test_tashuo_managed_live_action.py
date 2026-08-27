from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from dating_boost.apps.tashuo.managed_live_action import (
    click_tashuo_managed_send_only,
    observe_tashuo_managed_composer,
    observe_tashuo_managed_inbound_revision,
    observe_tashuo_managed_post_send,
    stage_tashuo_managed_text,
)


pytestmark = pytest.mark.managed_critical


def _revision(values: list[str]) -> str:
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return "ax-static-v1:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _session() -> SimpleNamespace:
    return SimpleNamespace(
        harness_backend="mac_ios_app",
        doctor=Mock(
            return_value={
                "status": "ok",
                "window": {"x": 1, "y": 2, "width": 300, "height": 700},
                "screen": {"status": "ok", "state": "tashuo_conversation"},
            }
        ),
        _window_info=Mock(return_value=object()),
        _click_ratio=Mock(return_value={"status": "ok"}),
        _press_return_key=Mock(return_value={"status": "ok", "input_backend": "applescript_return"}),
    )


def _bound_context() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "ok",
        "action": "test",
        "app_id": "tashuo",
        "runtime": "mac-ios-app",
        "target_binding_hash": hashlib.sha256(
            json.dumps(_binding(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "target_binding_verification": {"status": "ok"},
        "inbound_revision": "inbound_7",
        "_window": object(),
    }


def _binding() -> dict[str, object]:
    return {
        "binding_type": "current_thread_visual_identity",
        "candidate_key": "row_ada",
        "conversation_fingerprint": "conversation_ada",
        "thread_evidence": {
            "observation_id": "thread_observation_ada",
            "screen_state": "tashuo_conversation",
            "latest_inbound_fingerprint": "latest_inbound_ada",
            "visual_anchor_hash": "thread-anchor",
            "managed_inbound_revision": _revision(["一条旧消息"]),
            "managed_inbound_revision_observation_id": "baseline_revision_observation",
        },
        "message_list_evidence": {"visual_anchor_hash": "list-anchor"},
    }


def test_initial_revision_observation_hashes_fresh_ax_conversation_without_returning_raw_text() -> None:
    session = _session()
    with patch(
        "dating_boost.apps.tashuo.managed_live_action._verify_tashuo_target_binding",
        return_value={"status": "ok"},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_static_text_values",
        return_value={"status": "ok", "values": ["一条旧消息", "另一条消息"], "value_count": 2},
    ):
        result = observe_tashuo_managed_inbound_revision(session, target_binding=_binding())

    assert result["status"] == "ok"
    assert result["inbound_revision"] == _revision(["一条旧消息", "另一条消息"])
    assert result["inbound_revision_observation_id"]
    assert result["inbound_revision_evidence"]["value_count"] == 2
    assert "一条旧消息" not in str(result["inbound_revision_evidence"])
    session._press_return_key.assert_not_called()


def test_composer_accepts_only_a_new_matching_ax_revision_observation() -> None:
    session = _session()
    expected = _revision(["一条旧消息"])
    with patch(
        "dating_boost.apps.tashuo.managed_live_action._verify_tashuo_target_binding",
        return_value={"status": "ok"},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_static_text_values",
        return_value={"status": "ok", "values": ["一条旧消息"], "value_count": 1},
    ) as revision_observation, patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_text_area_value",
        return_value={"status": "ok", "value": ""},
    ):
        result = observe_tashuo_managed_composer(
            session,
            target_binding=_binding(),
            inbound_revision=expected,
        )

    assert result["status"] == "ok"
    assert result["inbound_revision"] == expected
    assert result["inbound_revision_verified"] is True
    assert result["inbound_revision_observation_id"] != "baseline_revision_observation"
    revision_observation.assert_called_once_with(session)


def test_caller_cannot_self_echo_a_new_revision_over_the_bound_baseline() -> None:
    session = _session()
    self_echoed_revision = _revision(["一条旧消息", "新入站消息"])
    with patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_static_text_values"
    ) as revision_observation:
        result = observe_tashuo_managed_composer(
            session,
            target_binding=_binding(),
            inbound_revision=self_echoed_revision,
        )

    assert result["status"] == "blocked"
    assert result["reason"] == "managed_inbound_revision_binding_mismatch"
    revision_observation.assert_not_called()
    session._press_return_key.assert_not_called()


@pytest.mark.parametrize("boundary", ["composer", "stage", "click"])
def test_each_pre_send_boundary_recomputes_and_rejects_changed_conversation_revision(boundary: str) -> None:
    session = _session()
    expected = _revision(["一条旧消息"])
    binding = _binding()
    assert binding["thread_evidence"]["managed_inbound_revision"] == expected  # type: ignore[index]
    with patch(
        "dating_boost.apps.tashuo.managed_live_action._verify_tashuo_target_binding",
        return_value={"status": "ok"},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_static_text_values",
        return_value={"status": "ok", "values": ["一条旧消息", "新入站消息"], "value_count": 2},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_conversation_snapshot",
        return_value={
            "status": "ok",
            "values": ["一条旧消息", "新入站消息"],
            "value_count": 2,
            "composer_found": True,
            "composer_value": "准备发送的草稿",
        },
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_text_area_value"
    ) as composer, patch(
        "dating_boost.apps.tashuo.managed_live_action._guarded_set_tashuo_ax_text_area_if_empty"
    ) as stage:
        if boundary == "composer":
            result = observe_tashuo_managed_composer(
                session,
                target_binding=binding,
                inbound_revision=expected,
            )
        elif boundary == "stage":
            result = stage_tashuo_managed_text(
                session,
                "准备发送的草稿",
                target_binding=binding,
                inbound_revision=expected,
            )
        else:
            result = click_tashuo_managed_send_only(
                session,
                "准备发送的草稿",
                target_binding=binding,
                inbound_revision=expected,
            )

    assert result["status"] == "blocked"
    assert result["reason"] == "managed_inbound_revision_changed"
    composer.assert_not_called()
    stage.assert_not_called()
    session._press_return_key.assert_not_called()


def test_observe_composer_is_read_only_and_returns_exact_ax_value() -> None:
    session = _session()
    with patch(
        "dating_boost.apps.tashuo.managed_live_action._observe_bound_conversation",
        return_value=_bound_context(),
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_text_area_value",
        return_value={"status": "ok", "value": "草稿  \n"},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._guarded_set_tashuo_ax_text_area_if_empty"
    ) as stage:
        result = observe_tashuo_managed_composer(
            session,
            target_binding=_binding(),
            inbound_revision="inbound_7",
        )

    assert result["status"] == "ok"
    assert result["composer_text"] == "草稿  \n"
    assert result["captured_at"]
    stage.assert_not_called()
    session._press_return_key.assert_not_called()


def test_stage_uses_atomic_empty_guard_then_exact_ax_read_without_return() -> None:
    session = _session()
    exact = "你好  \n下一行"
    with patch(
        "dating_boost.apps.tashuo.managed_live_action._observe_bound_conversation",
        return_value=_bound_context(),
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._guarded_set_tashuo_ax_text_area_if_empty",
        return_value={"status": "ok", "input_backend": "guarded_macos_accessibility"},
    ) as atomic_stage, patch(
        "dating_boost.apps.tashuo.managed_live_action._verify_tashuo_target_binding",
        return_value={"status": "ok"},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_conversation_snapshot",
        return_value={
            "status": "ok",
            "values": ["一条旧消息"],
            "value_count": 1,
            "composer_found": True,
            "composer_value": exact,
        },
    ):
        result = stage_tashuo_managed_text(
            session,
            exact,
            target_binding=_binding(),
            inbound_revision=_revision(["一条旧消息"]),
        )

    assert result["status"] == "ok"
    assert result["staged_exact_text_ax_verified"] is True
    atomic_stage.assert_called_once_with(session, exact)
    session._press_return_key.assert_not_called()


def test_click_only_never_repairs_or_stages_a_mismatched_composer() -> None:
    session = _session()
    with patch(
        "dating_boost.apps.tashuo.managed_live_action._observe_bound_conversation",
        return_value=_bound_context(),
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_text_area_value",
        return_value={"status": "ok", "value": "someone else's text"},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._guarded_set_tashuo_ax_text_area_if_empty"
    ) as stage:
        result = click_tashuo_managed_send_only(
            session,
            "expected",
            target_binding=_binding(),
            inbound_revision="inbound_7",
        )

    assert result["status"] == "blocked"
    assert result["reason"] == "managed_pre_click_composer_exact_mismatch"
    stage.assert_not_called()
    session._press_return_key.assert_not_called()


def test_click_and_post_are_separate_and_require_a_fresh_exact_ax_occurrence() -> None:
    session = _session()
    expected = "可以，周日下午怎么样？"
    pre_screen = {"status": "ok", "state": "tashuo_conversation", "path": "/tmp/before.png"}
    post_screen = {"status": "ok", "state": "tashuo_conversation", "path": "/tmp/after.png"}
    with patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_text_area_value",
        side_effect=[
            {"status": "ok", "value": expected},
            {"status": "ok", "value": expected},
        ],
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._verify_tashuo_target_binding",
        return_value={"status": "ok"},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._capture_tashuo_window",
        return_value=pre_screen,
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_conversation_snapshot",
        return_value={
            "status": "ok",
            "values": ["一条旧消息"],
            "value_count": 1,
            "composer_found": True,
            "composer_value": expected,
        },
    ) as pre_click_snapshot, patch(
        "dating_boost.apps.tashuo.managed_live_action._guarded_set_tashuo_ax_text_area_if_empty"
    ) as stage:
        receipt = click_tashuo_managed_send_only(
            session,
            expected,
            target_binding=_binding(),
            inbound_revision=_revision(["一条旧消息"]),
        )

    assert receipt["status"] == "ok"
    pre_click_snapshot.assert_called_once_with(session)
    session._press_return_key.assert_called_once()
    stage.assert_not_called()

    with patch(
        "dating_boost.apps.tashuo.managed_live_action._capture_tashuo_window",
        return_value=post_screen,
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_static_text_values",
        return_value={"status": "ok", "values": ["一条旧消息", expected], "value_count": 2},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_text_area_value",
        return_value={"status": "ok", "value": ""},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._verify_tashuo_outbound_message",
        return_value={
            "status": "ok",
            "input_cleared_after_send": True,
            "exact_text_ax_verified": True,
        },
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._sleep_for_tashuo_post_action_observation"
    ):
        post = observe_tashuo_managed_post_send(
            session,
            expected,
            target_binding=_binding(),
            inbound_revision="inbound_7",
            click_receipt=receipt,
        )

    assert post["status"] == "ok"
    assert post["input_cleared"] is True
    assert post["outbound_exact_text_ax_verified"] is True
    assert post["fresh_outbound_occurrence_verified"] is True
    # Post observation is read-only and cannot accidentally send a second time.
    session._press_return_key.assert_called_once()


def test_post_observation_does_not_accept_an_old_identical_message() -> None:
    session = _session()
    expected = "same text"
    receipt = {
        "status": "ok",
        "receipt_id": "receipt_1",
        "clicked_at": "2020-01-01T00:00:00Z",
        "expected_payload_hash": hashlib.sha256(expected.encode()).hexdigest(),
        "target_binding_hash": hashlib.sha256(
            json.dumps(_binding(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "pre_click_expected_text_occurrences": 1,
        "_pre_click_screen": {"status": "ok", "state": "tashuo_conversation", "path": "/tmp/before.png"},
    }
    with patch(
        "dating_boost.apps.tashuo.managed_live_action._capture_tashuo_window",
        return_value={"status": "ok", "state": "tashuo_conversation", "path": "/tmp/after.png"},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_static_text_values",
        return_value={"status": "ok", "values": [expected], "value_count": 1},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_text_area_value",
        return_value={"status": "ok", "value": ""},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._verify_tashuo_outbound_message",
        return_value={
            "status": "ok",
            "input_cleared_after_send": True,
            "exact_text_ax_verified": True,
        },
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._sleep_for_tashuo_post_action_observation"
    ):
        result = observe_tashuo_managed_post_send(
            session,
            expected,
            target_binding=_binding(),
            inbound_revision="inbound_7",
            click_receipt=receipt,
        )

    assert result["status"] == "unknown"
    assert result["reason"] == "managed_post_send_outbound_occurrence_not_new"
    session._press_return_key.assert_not_called()
