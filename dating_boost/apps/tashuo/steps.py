from __future__ import annotations

from typing import Any

from dating_boost.apps import native_gui_session as platform
from dating_boost.core.harness_steps import (
    marker_step as _harness_marker_step,
    tap_step as _harness_tap_step,
    wheel_step as _harness_wheel_step,
)


TASHUO_MESSAGES_TAB_TAP_RATIO = {"x": 0.67, "y": 0.96}
TASHUO_MINE_TAB_TAP_RATIO = {"x": 0.86, "y": 0.96}


def _tap_ratio_option(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = max(0.0, min(1.0, float(value["x"])))
        y = max(0.0, min(1.0, float(value["y"])))
    except (KeyError, TypeError, ValueError):
        return None
    return {"x": x, "y": y}


def _has_tashuo_step_precondition(step: dict[str, Any]) -> bool:
    return bool(step.get("requires_tashuo_top_level_tab_bar") or step.get("requires_tashuo_states"))


def _has_tashuo_step_postcondition(step: dict[str, Any]) -> bool:
    return bool(step.get("expected_tashuo_states"))


def _verify_tashuo_step_state(screen: dict[str, Any], step: dict[str, Any], *, key: str) -> dict[str, Any]:
    expected = step.get(key)
    if not expected:
        return {"status": "ok"}
    expected_states = [str(expected)] if isinstance(expected, str) else [str(state) for state in expected]
    actual = str(screen.get("state") or "unknown")
    if actual in expected_states:
        return {"status": "ok"}
    return {
        "status": "blocked",
        "expected_tashuo_states": expected_states,
        "actual_tashuo_state": actual,
    }


def _tashuo_step_expects_state(step: dict[str, Any], state: str) -> bool:
    expected = step.get("expected_tashuo_states")
    if not expected:
        return False
    expected_states = [str(expected)] if isinstance(expected, str) else [str(value) for value in expected]
    return state in expected_states


def _capture_tashuo_profile_read_step() -> dict[str, Any]:
    return _harness_marker_step(
        "capture_profile_read_step",
        requires_verified_tashuo_screen=True,
        requires_tashuo_states=["tashuo_recommend", "tashuo_profile", "tashuo_self_profile"],
        wait_after_seconds=0.0,
    )


def _tashuo_tap_step(
    intent: str,
    *,
    x: float,
    y: float,
    requires_states: list[str] | str | None = None,
    expected_states: list[str] | str | None = None,
) -> dict[str, Any]:
    step = _harness_tap_step(intent, x=x, y=y, requires_verified_tashuo_screen=True)
    if requires_states is not None:
        step["requires_tashuo_states"] = requires_states
    if expected_states is not None:
        step["expected_tashuo_states"] = expected_states
    return step


def _tashuo_bottom_tab_step(intent: str, *, x: float, y: float, expected_state: str) -> dict[str, Any]:
    return _harness_tap_step(
        intent,
        x=x,
        y=y,
        requires_verified_tashuo_screen=True,
        requires_tashuo_top_level_tab_bar=True,
        expected_tashuo_states=[expected_state],
    )


def _tashuo_wheel_step(
    intent: str,
    *,
    x: float,
    y: float,
    delta_y: int = 0,
    delta_x: int = 0,
    repeats: int = 18,
    requires_states: list[str] | str | None = None,
    expected_states: list[str] | str | None = None,
) -> dict[str, Any]:
    step = _harness_wheel_step(
        intent,
        x=x,
        y=y,
        delta_y=delta_y,
        delta_x=delta_x,
        repeats=repeats,
        requires_verified_tashuo_screen=True,
    )
    if requires_states is not None:
        step["requires_tashuo_states"] = requires_states
    if expected_states is not None:
        step["expected_tashuo_states"] = expected_states
    return step


def _tashuo_action_steps(action: str, **options: Any) -> list[dict[str, Any]]:
    row_index = int(options.get("row_index") or options.get("conversation_row") or 1)
    gate_index = int(options.get("gate_index") or options.get("match_index") or 1)
    row_y = min(0.86, 0.52 + (max(row_index, 1) - 1) * 0.12)
    if options.get("y_ratio") is not None:
        row_y = max(0.16, min(0.88, float(options["y_ratio"])))
    visual_tap_ratio = _tap_ratio_option(options.get("tap_ratio"))
    visual_target_label = str(options.get("visual_target_label") or "").strip()
    visual_target_preview = str(options.get("visual_target_preview") or "").strip()
    gate_x = min(0.84, 0.15 + (max(gate_index, 1) - 1) * 0.22)
    profile_read_states = ["tashuo_profile", "tashuo_self_profile", "tashuo_recommend"]
    open_conversation_steps = [
        {
            **_tashuo_tap_step(
                "tap_tashuo_visual_conversation_target",
                x=visual_tap_ratio["x"],
                y=visual_tap_ratio["y"],
                requires_states="tashuo_chat_list",
                expected_states=["tashuo_conversation", "tashuo_question_gate"],
            ),
            "selection_method": "host_visual_tap_ratio",
            **({"visual_target_label": visual_target_label} if visual_target_label else {}),
            **({"visual_target_preview": visual_target_preview} if visual_target_preview else {}),
        }
    ] if visual_tap_ratio is not None else [
        {
            **_tashuo_tap_step(
                "tap_tashuo_conversation_row",
                x=0.45,
                y=row_y,
                requires_states="tashuo_chat_list",
                expected_states=["tashuo_conversation", "tashuo_question_gate"],
            ),
            "row_index": row_index,
        }
    ]
    actions: dict[str, list[dict[str, Any]]] = {
        "open-recommend": [
            _tashuo_bottom_tab_step("tap_tashuo_recommend_tab", x=0.14, y=0.92, expected_state="tashuo_recommend")
        ],
        "open-flight": [
            _tashuo_bottom_tab_step("tap_tashuo_flight_tab", x=0.38, y=0.92, expected_state="tashuo_flight")
        ],
        "open-chats": [
            _tashuo_bottom_tab_step(
                "tap_tashuo_messages_tab",
                x=TASHUO_MESSAGES_TAB_TAP_RATIO["x"],
                y=TASHUO_MESSAGES_TAB_TAP_RATIO["y"],
                expected_state="tashuo_chat_list",
            )
        ],
        "open-profile-tab": [
            _tashuo_bottom_tab_step("tap_tashuo_mine_tab", x=0.86, y=0.92, expected_state="tashuo_self_profile")
        ],
        "conversation-list-scroll-down": [
            _tashuo_wheel_step(
                "wheel_tashuo_conversation_list_down",
                x=0.50,
                y=0.78,
                delta_y=-18,
                repeats=14,
                requires_states="tashuo_chat_list",
                expected_states="tashuo_chat_list",
            )
        ],
        "conversation-list-scroll-up": [
            _tashuo_wheel_step(
                "wheel_tashuo_conversation_list_up",
                x=0.50,
                y=0.46,
                delta_y=18,
                repeats=14,
                requires_states="tashuo_chat_list",
                expected_states="tashuo_chat_list",
            )
        ],
        "open-conversation": open_conversation_steps,
        "open-question-gate": [
            {
                **_tashuo_tap_step(
                    "tap_tashuo_waiting_question_card",
                    x=gate_x,
                    y=0.30,
                    requires_states="tashuo_chat_list",
                    expected_states=["tashuo_question_gate", "tashuo_conversation"],
                ),
                "gate_index": gate_index,
            }
        ],
        "open-thread-profile": [
            _tashuo_tap_step(
                "tap_tashuo_thread_name",
                x=0.50,
                y=0.13,
                requires_states="tashuo_conversation",
                expected_states="tashuo_profile",
            )
        ],
        "profile-scroll-down": [
            _tashuo_wheel_step(
                "wheel_tashuo_profile_read_down",
                x=0.50,
                y=0.78,
                delta_y=-18,
                repeats=18,
                requires_states=profile_read_states,
                expected_states=profile_read_states,
            )
        ],
        "profile-scroll-up": [
            _tashuo_wheel_step(
                "wheel_tashuo_profile_read_up",
                x=0.50,
                y=0.46,
                delta_y=18,
                repeats=18,
                requires_states=profile_read_states,
                expected_states=profile_read_states,
            )
        ],
        "close-profile": [
            {
                **_tashuo_tap_step(
                    "tap_tashuo_profile_back",
                    x=0.09,
                    y=0.13,
                    requires_states="tashuo_profile",
                    expected_states="tashuo_conversation",
                ),
                "postcondition_retry_after_seconds": 0.8,
            }
        ],
        "return-to-chats": [
            _tashuo_tap_step(
                "tap_tashuo_back_to_chats",
                x=0.09,
                y=0.13,
                requires_states=["tashuo_conversation", "tashuo_question_gate"],
                expected_states="tashuo_chat_list",
            )
        ],
    }
    if action not in actions:
        raise KeyError(action)
    return actions[action]


def _tashuo_workflow_steps(workflow: str, **options: Any) -> list[dict[str, Any]]:
    if workflow == "self-profile-read":
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps") or options.get("scroll_steps") or 2))
        steps = []
        steps.extend(_tashuo_action_steps("open-profile-tab"))
        steps.append(_capture_tashuo_profile_read_step())
        for _ in range(profile_scroll_steps):
            steps.extend(_tashuo_action_steps("profile-scroll-down"))
            steps.append(_capture_tashuo_profile_read_step())
        return steps
    if workflow == "recommend-profile-read":
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps") or options.get("scroll_steps") or 2))
        steps = []
        steps.extend(_tashuo_action_steps("open-recommend"))
        steps.append(_capture_tashuo_profile_read_step())
        for _ in range(profile_scroll_steps):
            steps.extend(_tashuo_action_steps("profile-scroll-down"))
            steps.append(_capture_tashuo_profile_read_step())
        return steps
    if workflow == "chat-read-match-profile":
        conversation_row = int(options.get("conversation_row") or 1)
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps") or 2))
        steps = []
        steps.extend(_tashuo_action_steps("open-chats"))
        steps.extend(_tashuo_action_steps("open-conversation", row_index=conversation_row))
        steps.extend(_tashuo_action_steps("open-thread-profile"))
        steps.append(_capture_tashuo_profile_read_step())
        for _ in range(profile_scroll_steps):
            steps.extend(_tashuo_action_steps("profile-scroll-down"))
            steps.append(_capture_tashuo_profile_read_step())
        steps.extend(_tashuo_action_steps("close-profile"))
        return steps
    if workflow == "question-gate-open":
        gate_index = int(options.get("gate_index") or options.get("match_index") or 1)
        steps = []
        steps.extend(_tashuo_action_steps("open-chats"))
        steps.extend(_tashuo_action_steps("open-question-gate", gate_index=gate_index))
        return steps
    if workflow == "question-gate-reply-composer":
        gate_index = int(options.get("gate_index") or options.get("match_index") or 1)
        steps = []
        steps.extend(_tashuo_action_steps("open-chats"))
        steps.extend(_tashuo_action_steps("open-question-gate", gate_index=gate_index))
        return steps
    raise KeyError(workflow)


def _tashuo_profile_field_coverage(text: str) -> dict[str, bool]:
    normalized = platform._normalize_text(text)
    return {
        "about_me": any(marker in normalized for marker in ("关于我", "自我介绍")),
        "daily_life": any(marker in normalized for marker in ("我的日常", "日常")),
        "wishes": any(marker in normalized for marker in ("我的愿望", "愿望")),
        "basic_info": any(marker in normalized for marker in ("资料", "身高", "星座", "家乡")),
        "activity": "动态" in normalized,
    }
