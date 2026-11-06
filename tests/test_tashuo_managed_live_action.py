from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
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
from dating_boost.apps.tashuo.targeting import _tashuo_visual_anchor_hash_for_pixels


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
            "managed_message_text_hashes": [hashlib.sha256("一条旧消息".encode()).hexdigest()],
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


@pytest.mark.parametrize("values", [["她说"], ["first"], ["second", "first"], ["first", "second", "first"]])
def test_revision_requires_exact_ordered_visible_message_coverage(values) -> None:
    session = _session()
    binding = _binding()
    binding["thread_evidence"]["managed_message_text_hashes"] = [
        hashlib.sha256(text.encode()).hexdigest() for text in ["first", "second"]
    ]
    with patch("dating_boost.apps.tashuo.managed_live_action._verify_tashuo_target_binding", return_value={"status": "ok"}), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_static_text_values",
        return_value={"status": "ok", "values": values, "value_count": len(values)},
    ):
        result = observe_tashuo_managed_inbound_revision(session, target_binding=binding)
    assert result["status"] == "blocked"
    assert result["reason"] == "managed_conversation_text_not_accessible"
    assert "inbound_revision" not in result
    session._press_return_key.assert_not_called()


@pytest.mark.parametrize("boundary", ["initial", "composer", "stage", "click"])
@pytest.mark.parametrize("coverage", [None, [], ["invalid"], "invalid", "title_only"])
def test_missing_or_unavailable_message_coverage_blocks_every_pre_send_boundary(boundary, coverage) -> None:
    session = _session()
    binding = _binding()
    values = ["一条旧消息"]
    if coverage == "title_only":
        values = ["她说"]
    elif coverage is None:
        binding["thread_evidence"].pop("managed_message_text_hashes")
    else:
        binding["thread_evidence"]["managed_message_text_hashes"] = coverage
    snapshot = {"status": "ok", "values": values, "value_count": len(values), "composer_found": True, "composer_value": "draft"}
    with patch("dating_boost.apps.tashuo.managed_live_action._verify_tashuo_target_binding", return_value={"status": "ok"}), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_static_text_values", return_value=snapshot,
    ), patch("dating_boost.apps.tashuo.managed_live_action._tashuo_ax_conversation_snapshot", return_value=snapshot), patch(
        "dating_boost.apps.tashuo.managed_live_action._guarded_set_tashuo_ax_text_area_if_empty",
    ) as stage:
        options = {"target_binding": binding, "inbound_revision": _revision(["一条旧消息"])}
        if boundary == "initial":
            result = observe_tashuo_managed_inbound_revision(session, target_binding=binding)
        elif boundary == "composer":
            result = observe_tashuo_managed_composer(session, **options)
        elif boundary == "stage":
            result = stage_tashuo_managed_text(session, "draft", **options)
        else:
            result = click_tashuo_managed_send_only(session, "draft", **options)
    assert result["status"] == "blocked"
    assert result["reason"] == "managed_conversation_text_not_accessible"
    stage.assert_not_called()
    session._press_return_key.assert_not_called()


def test_complete_visible_message_coverage_preserves_duplicates_and_ignores_unrelated_labels() -> None:
    session = _session()
    binding = _binding()
    messages = ["same", "same", "last"]
    binding["thread_evidence"]["managed_message_text_hashes"] = [hashlib.sha256(text.encode()).hexdigest() for text in messages]
    values = ["她说", "same", "timestamp", "same", "last", "toolbar"]
    with patch("dating_boost.apps.tashuo.managed_live_action._verify_tashuo_target_binding", return_value={"status": "ok"}), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_static_text_values",
        return_value={"status": "ok", "values": values, "value_count": len(values)},
    ):
        result = observe_tashuo_managed_inbound_revision(session, target_binding=binding)
    assert result["status"] == "ok"
    assert result["inbound_revision"] == _revision(values)
    assert result["inbound_revision_evidence"]["covered_message_count"] == 3
    assert result["inbound_revision_evidence"]["conversation_text_coverage_verified"] is True
    assert "same" not in str(result["inbound_revision_evidence"])


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


def _burst_click(before: list[str], expected: str, *, visual_hash="0" * 16, **kwargs):
    session = _session()
    binding = _binding()
    binding["thread_evidence"]["managed_inbound_revision"] = _revision(before)
    binding["thread_evidence"]["managed_message_text_hashes"] = [
        hashlib.sha256(text.encode()).hexdigest() for text in before if text != "toolbar"
    ]
    binding["thread_evidence"]["managed_inbound_revision_captured_at"] = "2026-09-20T00:00:00Z"
    binding["thread_evidence"]["visual_anchor_hash"] = visual_hash
    binding["thread_evidence"]["visual_anchor_region"] = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65}
    with patch(
        "dating_boost.apps.tashuo.managed_live_action._verify_tashuo_target_binding",
        return_value={"status": "ok", "screen": {"status": "ok", "state": "tashuo_conversation", "path": "/tmp/before.png"}},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_conversation_snapshot",
        return_value={"status": "ok", "values": before, "value_count": len(before), "composer_found": True, "composer_value": expected},
    ) as snapshot, patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_text_area_value",
        return_value={"status": "ok", "value": expected},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action.platform._now_iso",
        return_value="2026-09-20T00:00:01Z",
    ):
        receipt = click_tashuo_managed_send_only(
            session, expected, target_binding=binding, inbound_revision=_revision(before), **kwargs,
        )
    snapshot.assert_called_once_with(session)
    return session, binding, receipt


def _burst_post(session, binding, receipt, expected, after, *, value_count=None, anchor_result=None, image_pixels=None, real_anchor=False):
    with patch(
        "dating_boost.apps.tashuo.managed_live_action._capture_tashuo_window",
        return_value={"status": "ok", "state": "tashuo_conversation", "path": "/tmp/after.png"},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_static_text_values",
        return_value={"status": "ok", "values": after, "value_count": len(after) if value_count is None else value_count},
    ) as static, patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_text_area_value",
        return_value={"status": "ok", "value": ""},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._verify_tashuo_outbound_message",
        return_value={"status": "ok", "input_cleared_after_send": True, "exact_text_ax_verified": True},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action.platform._now_iso",
        return_value="2026-09-20T00:00:02Z",
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._read_png_pixels",
        side_effect=image_pixels if image_pixels is not None else [{"width": 300, "height": 700, "channels": 3}] * 2,
    ) as read_pixels, patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_visual_anchor_hash_for_pixels",
        return_value=anchor_result if anchor_result is not None else {"status": "ok", "visual_anchor_hash": "f" * 16},
        side_effect=_tashuo_visual_anchor_hash_for_pixels if real_anchor else None,
    ), patch("dating_boost.apps.tashuo.managed_live_action._sleep_for_tashuo_post_action_observation"):
        result = observe_tashuo_managed_post_send(
            session,
            expected,
            target_binding=binding,
            inbound_revision=binding["thread_evidence"]["managed_inbound_revision"],
            click_receipt=receipt,
        )
    static.assert_called_once_with(session)
    if result.get("continuation_verified"):
        assert read_pixels.call_args_list[0].args == (Path("/tmp/before.png"),)
        assert read_pixels.call_args_list[1].args == (Path("/tmp/after.png"),)
        assert read_pixels.call_count == 2
    return result


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (["old message"], ["old message", "expected reply"]),
        (["old message", "toolbar"], ["old message", "expected reply", "toolbar"]),
        (["expected reply", "old message"], ["expected reply", "old message", "expected reply"]),
        (["old message", "expected reply"], ["old message", "expected reply", "expected reply"]),
    ],
)
def test_continuation_requires_only_one_expected_entry_insertion(before, after) -> None:
    expected = "expected reply"
    session, binding, receipt = _burst_click(before, expected)
    assert receipt["status"] == "ok"
    assert receipt["_pre_click_static_text_hashes"] == tuple(hashlib.sha256(item.encode()).hexdigest() for item in before)
    result = _burst_post(session, binding, receipt, expected, after)
    assert result["status"] == "ok"
    assert result["continuation_verified"] is True
    assert result["continuation_inbound_revision"] == _revision(after)
    assert result["continuation_inbound_revision_observation_id"] == result["post_action_observation_id"]
    assert result["continuation_inbound_revision_captured_at"] == result["captured_at"]
    assert result["continuation_visual_anchor_hash"] == "f" * 16
    assert result["continuation_visual_anchor_region"] == binding["thread_evidence"]["visual_anchor_region"]
    assert "_pre_click_static_text_hashes" not in result
    assert "_pre_click_static_text_hashes" not in receipt["inbound_revision_evidence"]
    session._press_return_key.assert_called_once()


@pytest.mark.parametrize(
    "after",
    [
        ["old message", "second old message", "expected reply", "concurrent inbound"],
        ["old message", "concurrent inbound", "second old message", "expected reply"],
        ["second old message", "old message", "expected reply"],
        ["old message", "changed layout label", "expected reply"],
        ["second old message", "expected reply"],
        ["old message", "second old message", "expected reply", "expected reply"],
        ["old message", "second old message", "expected reply plus extra text"],
    ],
)
def test_confirmed_send_survives_but_continuation_stops_on_any_other_ax_change(after) -> None:
    session, binding, receipt = _burst_click(["old message", "second old message"], "expected reply")
    result = _burst_post(session, binding, receipt, "expected reply", after)
    assert result["status"] == "ok"
    assert result["continuation_verified"] is False
    assert "continuation_inbound_revision" not in result
    session._press_return_key.assert_called_once()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("_pre_click_static_text_hashes", None),
        ("_pre_click_static_text_hashes", ("malformed",)),
        ("_pre_click_static_text_hashes", ["0" * 64]),
        ("inbound_revision", "ax-static-v1:" + "0" * 64),
        ("inbound_revision_verified", False),
        ("inbound_revision_observation_id", "baseline_revision_observation"),
        ("inbound_revision_observation_id", ""),
        ("inbound_revision_captured_at", "not-a-timestamp"),
        ("inbound_revision_captured_at", "2026-09-20T00:00:01"),
        ("inbound_revision_captured_at", "2026-09-20T00:00:03Z"),
        ("inbound_revision_captured_at", "2026-09-19T00:00:00Z"),
    ],
)
def test_missing_malformed_or_stale_continuation_evidence_preserves_confirmed_single_send(field, value) -> None:
    session, binding, receipt = _burst_click(["old message"], "expected reply")
    receipt = deepcopy(receipt)
    receipt[field] = value
    result = _burst_post(session, binding, receipt, "expected reply", ["old message", "expected reply"])
    assert result["status"] == "ok"
    assert result["continuation_verified"] is False
    assert "continuation_inbound_revision" not in result


def test_post_static_count_mismatch_cannot_authorize_continuation() -> None:
    session, binding, receipt = _burst_click(["old message"], "expected reply")
    result = _burst_post(session, binding, receipt, "expected reply", ["old message", "expected reply"], value_count=3)
    assert result["status"] == "ok"
    assert result["continuation_verified"] is False


@pytest.mark.parametrize(
    ("deadline", "reason"),
    [
        ("2026-09-20T00:00:01Z", "managed_burst_continuation_expired"),
        ("2026-09-20T00:00:00Z", "managed_burst_continuation_expired"),
        ("invalid", "managed_burst_continuation_deadline_invalid"),
        ("2026-09-20T00:00:05", "managed_burst_continuation_deadline_invalid"),
        (123, "managed_burst_continuation_deadline_invalid"),
    ],
)
def test_click_deadline_is_checked_after_focus_before_return(deadline, reason) -> None:
    session, _, receipt = _burst_click(["old message"], "expected reply", click_deadline_at=deadline)
    assert receipt["status"] == "blocked"
    assert receipt["reason"] == reason
    session._click_ratio.assert_called_once()
    session._press_return_key.assert_not_called()


def test_click_with_time_remaining_keeps_existing_return_only_behavior() -> None:
    session, _, receipt = _burst_click(["old message"], "expected reply", click_deadline_at="2026-09-20T00:00:05Z")
    assert receipt["status"] == "ok"
    session._press_return_key.assert_called_once()


def test_adapter_forwards_burst_deadline_to_return_only_boundary() -> None:
    from dating_boost.apps.tashuo.adapter import TaShuoAdapter

    adapter = object.__new__(TaShuoAdapter)
    adapter.session = _session()
    adapter._runtime_lock_enabled = False
    binding = _binding()
    deadline = "2026-09-20T00:00:05Z"
    with patch(
        "dating_boost.apps.tashuo.adapter.tashuo_managed_live_action.click_tashuo_managed_send_only",
        return_value={"status": "blocked", "reason": "managed_burst_continuation_expired"},
    ) as click:
        result = adapter.click_managed_send_only(
            "expected reply", target_binding=binding, inbound_revision="revision", click_deadline_at=deadline,
        )
    assert result["status"] == "blocked"
    click.assert_called_once_with(
        adapter.session,
        "expected reply",
        target_binding=binding,
        inbound_revision="revision",
        output_dir=None,
        click_deadline_at=deadline,
    )
    adapter.session._press_return_key.assert_not_called()


@pytest.mark.parametrize("anchor_result", [{"status": "blocked"}, {"status": "ok", "visual_anchor_hash": "malformed"}])
def test_anchor_hash_failure_cannot_undo_confirmed_send_or_allow_continuation(anchor_result) -> None:
    session, binding, receipt = _burst_click(["old message"], "expected reply")
    result = _burst_post(session, binding, receipt, "expected reply", ["old message", "expected reply"], anchor_result=anchor_result)
    assert result["status"] == "ok"
    assert result["continuation_verified"] is False
    assert "continuation_inbound_revision" not in result
    assert "continuation_visual_anchor_hash" not in result


@pytest.mark.parametrize("failure", ["read", "dimensions"])
def test_unreadable_or_resized_post_image_disables_continuation(failure) -> None:
    session, binding, receipt = _burst_click(["old message"], "expected reply")
    pixels = [
        {"width": 300, "height": 700, "channels": 3},
        OSError("image unavailable") if failure == "read" else {"width": 600, "height": 700, "channels": 3},
    ]
    result = _burst_post(session, binding, receipt, "expected reply", ["old message", "expected reply"], image_pixels=pixels)
    assert result["status"] == "ok"
    assert result["continuation_verified"] is False
    assert "continuation_visual_anchor_hash" not in result


@pytest.mark.parametrize("change", ["list_binding", "missing_region", "invalid_region"])
def test_anchor_refresh_never_changes_binding_type_or_guesses_a_new_region(change) -> None:
    from dating_boost.apps.tashuo.managed_live_action import _continuation_visual_anchor

    binding = _binding()
    if change == "list_binding":
        binding["binding_type"] = "chat_list_row_to_thread"
    elif change == "invalid_region":
        binding["thread_evidence"]["visual_anchor_region"] = {"x1": 0, "x2": 2, "y1": 0, "y2": 1}
    with patch("dating_boost.apps.tashuo.managed_live_action._read_png_pixels") as read:
        assert _continuation_visual_anchor(binding, {"path": "before"}, {"path": "after"}) is None
    read.assert_not_called()


def test_proven_content_change_refreshes_anchor_for_the_next_stage() -> None:
    region = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65}
    before_pixels = {"width": 80, "height": 80, "channels": 3, "rows": [bytes([0] * 120 + [255] * 120)] * 80}
    after_pixels = {"width": 80, "height": 80, "channels": 3, "rows": [bytes([255] * 120 + [0] * 120)] * 80}
    before_hash = _tashuo_visual_anchor_hash_for_pixels(before_pixels, region=region)["visual_anchor_hash"]
    after_hash = _tashuo_visual_anchor_hash_for_pixels(after_pixels, region=region)["visual_anchor_hash"]
    assert (int(before_hash, 16) ^ int(after_hash, 16)).bit_count() == 64
    session, binding, receipt = _burst_click(["old message"], "expected reply", visual_hash=before_hash)
    values = ["old message", "expected reply"]
    post = _burst_post(
        session, binding, receipt, "expected reply", values,
        image_pixels=[before_pixels, after_pixels], real_anchor=True,
    )
    assert post["continuation_verified"] is True
    assert post["continuation_visual_anchor_hash"] == after_hash
    next_binding = deepcopy(binding)
    next_binding["thread_evidence"].update({
        "managed_inbound_revision": post["continuation_inbound_revision"],
        "managed_inbound_revision_observation_id": post["continuation_inbound_revision_observation_id"],
        "managed_inbound_revision_captured_at": post["continuation_inbound_revision_captured_at"],
        "visual_anchor_hash": post["continuation_visual_anchor_hash"],
        "visual_anchor_region": post["continuation_visual_anchor_region"],
    })
    stale_visual_binding = deepcopy(next_binding)
    stale_visual_binding["thread_evidence"]["visual_anchor_hash"] = before_hash
    with patch(
        "dating_boost.apps.tashuo.targeting._capture_tashuo_window",
        return_value={"status": "ok", "state": "tashuo_conversation", "path": "/tmp/after.png"},
    ), patch(
        "dating_boost.apps.tashuo.targeting._read_png_pixels", return_value=after_pixels,
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_static_text_values",
        return_value={"status": "ok", "values": values, "value_count": 2},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action._guarded_set_tashuo_ax_text_area_if_empty",
        return_value={"status": "ok"},
    ) as stage, patch(
        "dating_boost.apps.tashuo.managed_live_action._tashuo_ax_conversation_snapshot",
        return_value={"status": "ok", "values": values, "value_count": 2, "composer_found": True, "composer_value": "next reply"},
    ), patch(
        "dating_boost.apps.tashuo.managed_live_action.platform._now_iso", return_value="2026-09-20T00:00:03Z",
    ):
        stale = stage_tashuo_managed_text(
            session, "next reply", target_binding=stale_visual_binding, inbound_revision=post["continuation_inbound_revision"],
        )
        assert stale["reason"] == "target_binding_visual_anchor_mismatch"
        stage.assert_not_called()
        fresh = stage_tashuo_managed_text(
            session, "next reply", target_binding=next_binding, inbound_revision=post["continuation_inbound_revision"],
        )
    assert fresh["status"] == "ok"
    assert fresh["staged_exact_text_ax_verified"] is True
    stage.assert_called_once_with(session, "next reply")
    assert next_binding["conversation_fingerprint"] == binding["conversation_fingerprint"]
    assert next_binding["message_list_evidence"] == binding["message_list_evidence"]
