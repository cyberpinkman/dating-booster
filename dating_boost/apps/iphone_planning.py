from __future__ import annotations

from typing import Any

from dating_boost.core.harness_steps import (
    marker_step as _harness_marker_step,
    swipe_step as _harness_swipe_step,
    tap_step as _harness_tap_step,
    wheel_step as _harness_wheel_step,
)
from dating_boost.core.send_verification import hash_text as _hash_text
from dating_boost.core.send_verification import normalize_text as _normalize_text


TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION = {"x1": 0.0, "y1": 0.32, "x2": 1.0, "y2": 0.89}
BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION = {"x1": 0.0, "y1": 0.34, "x2": 1.0, "y2": 0.89}
IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE = 8


def _target_binding_required_markers(target_binding: dict[str, Any]) -> list[str]:
    markers: list[str] = []
    value = target_binding.get("required_visible_text")
    if isinstance(value, list):
        markers.extend(str(item).strip() for item in value if str(item).strip())
    visible_name = target_binding.get("visible_name")
    if isinstance(visible_name, str) and visible_name.strip():
        markers.append(visible_name.strip())
    unique: list[str] = []
    for marker in markers:
        if marker not in unique:
            unique.append(marker)
    return unique


def _target_binding_primary_visible_name(target_binding: dict[str, Any]) -> str | None:
    markers = _target_binding_required_markers(target_binding)
    if markers:
        return markers[0]
    return None


def _redacted_target_binding(target_binding: dict[str, Any] | None) -> dict[str, Any] | None:
    if target_binding is None:
        return None
    selection_evidence = (
        target_binding.get("selection_evidence")
        if isinstance(target_binding.get("selection_evidence"), dict)
        else {}
    )
    redacted_selection = None
    if selection_evidence:
        redacted_selection = {
            "row_index": selection_evidence.get("row_index"),
            "source_state": selection_evidence.get("source_state"),
            "opened_state": selection_evidence.get("opened_state"),
            "target_scope": selection_evidence.get("target_scope"),
            "open_action": selection_evidence.get("open_action"),
        }
        visual = _redacted_message_list_visual_anchor_evidence(selection_evidence)
        if visual.get("has_visual_anchor"):
            redacted_selection["message_list_visual_anchor"] = visual
    return {
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "binding_type": target_binding.get("binding_type"),
        "selection_evidence": redacted_selection,
        "required_marker_hashes": [_hash_text(marker) for marker in _target_binding_required_markers(target_binding)],
    }


def _redacted_iphone_prepare_message_page_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "status",
        "reason",
        "action",
        "mode",
        "screen_state",
        "next_host_action",
        "message_list_planning_contract",
        "layout_hints",
        "executed_steps",
        "recoveries",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _message_list_visual_anchor_evidence_from_options(
    options: dict[str, Any],
    *,
    target_binding: dict[str, Any] | None,
    default_scan_region: dict[str, float],
    default_max_distance: int,
) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for key in ("message_list_evidence", "selection_evidence", "target_selection_evidence"):
        value = options.get(key)
        if isinstance(value, dict):
            sources.append(value)
    if isinstance(target_binding, dict):
        for key in ("message_list_evidence", "selection_evidence", "target_selection_evidence"):
            value = target_binding.get(key)
            if isinstance(value, dict):
                sources.append(value)
    flat = {
        key: options.get(key)
        for key in (
            "visual_anchor_hash",
            "row_visual_anchor_hash",
            "message_list_visual_anchor_hash",
            "visual_anchor_region",
            "row_visual_anchor_region",
            "message_list_visual_anchor_region",
            "visual_anchor_scan_region",
            "visual_anchor_max_hamming_distance",
            "row_visual_anchor_max_hamming_distance",
            "tap_ratio",
            "visual_tap_ratio",
            "target_tap_ratio",
            "tap_ratio_source",
            "selection_method",
            "source_state",
        )
        if options.get(key) is not None
    }
    if flat:
        sources.append(flat)
    requested = False
    blocked: dict[str, Any] | None = None
    for source in sources:
        if _message_list_visual_anchor_requested(source):
            requested = True
        evidence = _normalize_iphone_message_list_visual_anchor_evidence(
            source,
            default_scan_region=default_scan_region,
            default_max_distance=default_max_distance,
        )
        if evidence.get("status") == "ok":
            return evidence
        if evidence.get("status") == "blocked":
            blocked = evidence
    if requested:
        return blocked or {"status": "blocked", "reason": "target_relocation_visual_evidence_required"}
    return {"status": "not_requested"}


def _message_list_visual_anchor_requested(source: dict[str, Any]) -> bool:
    return any(
        source.get(key) is not None
        for key in (
            "visual_anchor_hash",
            "row_visual_anchor_hash",
            "message_list_visual_anchor_hash",
            "visual_anchor_region",
            "row_visual_anchor_region",
            "message_list_visual_anchor_region",
            "message_list_evidence",
        )
    )


def _normalize_iphone_message_list_visual_anchor_evidence(
    source: dict[str, Any],
    *,
    default_scan_region: dict[str, float],
    default_max_distance: int,
) -> dict[str, Any]:
    visual_hash = str(
        source.get("visual_anchor_hash")
        or source.get("row_visual_anchor_hash")
        or source.get("message_list_visual_anchor_hash")
        or ""
    ).strip()
    region = _normalized_visual_anchor_region(
        source.get("visual_anchor_region")
        or source.get("row_visual_anchor_region")
        or source.get("message_list_visual_anchor_region"),
        fallback=None,
    )
    if not visual_hash and region is None:
        return {"status": "not_requested"}
    if not visual_hash or region is None:
        return {"status": "blocked", "reason": "target_relocation_visual_anchor_evidence_incomplete"}
    max_distance = _int_in_range(
        source.get("visual_anchor_max_hamming_distance") or source.get("row_visual_anchor_max_hamming_distance"),
        default=default_max_distance,
        minimum=0,
        maximum=32,
    )
    scan_region = _normalized_visual_anchor_region(
        source.get("visual_anchor_scan_region") or source.get("scan_region"),
        fallback=default_scan_region,
    )
    if scan_region is None:
        return {"status": "blocked", "reason": "target_relocation_visual_anchor_scan_region_invalid"}
    return {
        "status": "ok",
        "evidence_type": "message_list_visual_anchor",
        "visual_anchor_hash": visual_hash,
        "visual_anchor_region": region,
        "visual_anchor_scan_region": scan_region,
        "visual_anchor_max_hamming_distance": max_distance,
        "tap_ratio": _tap_ratio_option(
            source.get("tap_ratio") or source.get("visual_tap_ratio") or source.get("target_tap_ratio")
        ),
        "tap_ratio_source": source.get("tap_ratio_source"),
        "source_state": source.get("source_state"),
        "selection_method": source.get("selection_method") or "message_list_visual_anchor_scan",
    }


def _redacted_message_list_visual_anchor_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    visual_hash = str(
        evidence.get("visual_anchor_hash")
        or evidence.get("row_visual_anchor_hash")
        or evidence.get("message_list_visual_anchor_hash")
        or ""
    ).strip()
    raw_region = (
        evidence.get("visual_anchor_region")
        or evidence.get("row_visual_anchor_region")
        or evidence.get("message_list_visual_anchor_region")
    )
    region = raw_region if isinstance(raw_region, dict) else None
    raw_scan_region = evidence.get("visual_anchor_scan_region") or evidence.get("scan_region")
    scan_region = raw_scan_region if isinstance(raw_scan_region, dict) else None
    return {
        "has_visual_anchor": bool(visual_hash and region),
        "visual_anchor_hash": visual_hash or None,
        "visual_anchor_region": dict(region) if region is not None else None,
        "visual_anchor_scan_region": dict(scan_region) if scan_region is not None else None,
        "visual_anchor_max_hamming_distance": evidence.get("visual_anchor_max_hamming_distance")
        or evidence.get("row_visual_anchor_max_hamming_distance"),
        "tap_ratio": _copy_tap_ratio(evidence.get("tap_ratio")) if isinstance(evidence.get("tap_ratio"), dict) else None,
        "selection_method": evidence.get("selection_method"),
        "source_state": evidence.get("source_state"),
    }


def _visual_anchor_hamming_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        return max(len(left), len(right)) * 4
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return max(len(left), len(right)) * 4


def _normalized_visual_anchor_region(
    raw: Any,
    *,
    fallback: dict[str, float] | None,
) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return dict(fallback) if fallback is not None else None
    fallback_values = fallback or {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}
    region: dict[str, float] = {}
    for key, default in fallback_values.items():
        value = raw.get(key)
        try:
            region[key] = float(value)
        except (TypeError, ValueError):
            if fallback is None:
                return None
            region[key] = default
    if region["x2"] <= region["x1"] or region["y2"] <= region["y1"]:
        return dict(fallback) if fallback is not None else None
    return {
        "x1": max(0.0, min(0.99, region["x1"])),
        "y1": max(0.0, min(0.99, region["y1"])),
        "x2": max(0.01, min(1.0, region["x2"])),
        "y2": max(0.01, min(1.0, region["y2"])),
    }


def _tap_ratio_option(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    try:
        return {
            "x": max(0.0, min(1.0, float(raw["x"]))),
            "y": max(0.0, min(1.0, float(raw["y"]))),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _copy_tap_ratio(raw: Any) -> dict[str, float] | None:
    return _tap_ratio_option(raw)


def _int_in_range(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _has_bumble_step_precondition(step: dict[str, Any]) -> bool:
    return bool(step.get("requires_bumble_top_level_tab_bar") or step.get("requires_bumble_states"))


def _has_bumble_step_postcondition(step: dict[str, Any]) -> bool:
    return bool(step.get("expected_bumble_states"))


def _verify_bumble_step_state(screen: dict[str, Any], step: dict[str, Any], *, key: str) -> dict[str, Any]:
    expected = step.get(key)
    if not expected:
        return {"status": "ok"}
    expected_states = [str(expected)] if isinstance(expected, str) else [str(state) for state in expected]
    actual = str(screen.get("state") or "unknown")
    if actual in expected_states:
        return {"status": "ok"}
    return {
        "status": "blocked",
        "expected_bumble_states": expected_states,
        "actual_bumble_state": actual,
    }


def _tap_step(intent: str, *, x: float, y: float) -> dict[str, Any]:
    return _harness_tap_step(intent, x=x, y=y, requires_verified_tinder_screen=True)


def _tinder_subscription_paywall_dismiss_step() -> dict[str, Any]:
    return _harness_tap_step(
        "tap_tinder_subscription_paywall_close",
        x=0.09,
        y=0.14,
        risk="subscription_paywall_recovery",
        requires_tinder_subscription_paywall=True,
        subscription_purchase_executed=False,
    )


def _tinder_feedback_survey_dismiss_step() -> dict[str, Any]:
    return _harness_tap_step(
        "tap_tinder_feedback_survey_ignore",
        x=0.50,
        y=0.64,
        risk="feedback_survey_recovery",
        requires_tinder_feedback_survey=True,
        rating_submitted=False,
    )


def _swipe_step(intent: str, *, from_x: float, from_y: float, to_x: float, to_y: float, duration_ms: int = 350) -> dict[str, Any]:
    return _harness_swipe_step(
        intent,
        from_x=from_x,
        from_y=from_y,
        to_x=to_x,
        to_y=to_y,
        duration_ms=duration_ms,
        requires_verified_tinder_screen=True,
    )


def _wheel_step(
    intent: str,
    *,
    x: float,
    y: float,
    delta_y: int = 0,
    delta_x: int = 0,
    repeats: int = 18,
) -> dict[str, Any]:
    return _harness_wheel_step(
        intent,
        x=x,
        y=y,
        delta_y=delta_y,
        delta_x=delta_x,
        repeats=repeats,
        requires_verified_tinder_screen=True,
    )


def _capture_profile_read_step(*, app_id: str = "tinder") -> dict[str, Any]:
    if app_id == "bumble":
        requires_key = "requires_verified_bumble_screen"
    else:
        requires_key = "requires_verified_tinder_screen"
    step = _harness_marker_step("capture_profile_read_step", **{requires_key: True}, wait_after_seconds=0.0)
    if app_id == "bumble":
        step["requires_bumble_states"] = ["bumble_browse", "bumble_profile", "bumble_self_profile"]
    return step


def _safe_expand_step() -> dict[str, Any]:
    return _harness_tap_step(
        "safe_expand_visible_profile_section",
        x=0.50,
        y=0.76,
        requires_verified_tinder_screen=True,
    )


def _tinder_action_steps(action: str, **options: Any) -> list[dict[str, Any]]:
    row_index = int(options.get("row_index") or options.get("conversation_row") or 1)
    match_index = int(options.get("match_index") or 1)
    row_y = min(0.86, 0.30 + (max(row_index, 1) - 1) * 0.12)
    if options.get("y_ratio") is not None:
        row_y = max(0.12, min(0.88, float(options["y_ratio"])))
    match_x = min(0.86, 0.42 + (max(match_index, 1) - 1) * 0.24)
    target = str(options.get("target") or "row")
    conversation_x = 0.14 if target == "avatar" else 0.50
    visible_name = str(options.get("visible_name") or "").strip()
    target_binding = options.get("target_binding")
    visual_evidence = _message_list_visual_anchor_evidence_from_options(
        options,
        target_binding=target_binding if isinstance(target_binding, dict) else None,
        default_scan_region=TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
        default_max_distance=IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE,
    )
    if action == "open-conversation" and visual_evidence.get("status") == "ok":
        visual = _redacted_message_list_visual_anchor_evidence(visual_evidence)
        return [
            {
                "intent": "locate_conversation_row_visual_anchor",
                "requires_verified_tinder_screen": True,
                "risk": "navigation_only",
                "location_method": "message_list_visual_anchor_scan",
                "message_list_visual_anchor": visual,
            },
            {
                "intent": "tap_visible_conversation_row",
                "requires_verified_tinder_screen": True,
                "risk": "navigation_only",
                "location_method": "message_list_visual_anchor_scan",
                "message_list_visual_anchor": visual,
            },
        ]
    if action == "open-conversation" and visual_evidence.get("status") == "blocked":
        return [
            {
                "intent": "message_list_visual_anchor_evidence_incomplete",
                "requires_verified_tinder_screen": True,
                "risk": "navigation_only",
                "location_method": "message_list_visual_anchor_scan",
                "evidence_status": "blocked",
                "reason": visual_evidence.get("reason") or "target_relocation_visual_evidence_required",
            }
        ]
    if not visible_name and isinstance(target_binding, dict):
        visible_name = _target_binding_primary_visible_name(target_binding) or ""
    if action == "open-conversation" and visible_name:
        marker_hash = _hash_text(visible_name)
        return [
            {
                "intent": "locate_visible_conversation_name",
                "target_marker_hash": marker_hash,
                "requires_verified_tinder_screen": True,
                "risk": "navigation_only",
                "location_method": "ocr_tsv_visible_text",
            },
            {
                "intent": "tap_visible_conversation_row",
                "target_marker_hash": marker_hash,
                "requires_verified_tinder_screen": True,
                "risk": "navigation_only",
                "location_method": "ocr_tsv_visible_text",
            },
        ]
    actions: dict[str, list[dict[str, Any]]] = {
        "prepare-message-page": [
            {
                **_tap_step("tap_thread_back_to_chats_if_in_thread", x=0.09, y=0.13),
                "conditional": "when_current_state_is_tinder_conversation",
            },
            {
                **_tap_step("tap_chats_tab_if_needed", x=0.66, y=0.94),
                "conditional": "when_current_state_is_tinder_foreground_not_messages",
            },
        ],
        "open-chats": [_tap_step("tap_chats_tab", x=0.66, y=0.94)],
        "matches-carousel-next": [_wheel_step("wheel_new_matches_left", x=0.56, y=0.30, delta_x=-20, repeats=18)],
        "matches-carousel-previous": [_wheel_step("wheel_new_matches_right", x=0.56, y=0.30, delta_x=20, repeats=18)],
        "conversation-list-scroll-down": [
            _wheel_step("wheel_conversation_list_down", x=0.50, y=0.78, delta_y=-20, repeats=14)
        ],
        "conversation-list-scroll-up": [
            _wheel_step("wheel_conversation_list_up", x=0.50, y=0.46, delta_y=20, repeats=14)
        ],
        "open-new-match": [{**_tap_step("tap_new_match_card", x=match_x, y=0.30), "match_index": match_index}],
        "open-conversation": [
            {**_tap_step("tap_conversation_row", x=conversation_x, y=row_y), "row_index": row_index, "target": target}
        ],
        "open-thread-profile": [_tap_step("tap_thread_profile_avatar", x=0.50, y=0.14)],
        "open-self-profile-preview": [_tap_step("tap_self_profile_avatar", x=0.14, y=0.13)],
        "profile-photo-next": [_tap_step("tap_photo_next", x=0.86, y=0.45)],
        "profile-photo-previous": [_tap_step("tap_photo_previous", x=0.14, y=0.45)],
        "open-full-profile": [_tap_step("tap_profile_up_arrow", x=0.90, y=0.82)],
        "profile-scroll-down": [_wheel_step("wheel_profile_read_down", x=0.50, y=0.86, delta_y=-20, repeats=18)],
        "profile-scroll-up": [_wheel_step("wheel_profile_read_up", x=0.50, y=0.46, delta_y=20, repeats=18)],
        "expand-visible-profile-section": [_safe_expand_step()],
        "close-full-profile": [_tap_step("tap_profile_down_arrow", x=0.90, y=0.08)],
        "close-preview": [_tap_step("tap_preview_done", x=0.90, y=0.08)],
        "return-to-chats": [_tap_step("tap_thread_back_to_chats", x=0.09, y=0.13)],
        "dismiss-subscription-paywall": [_tinder_subscription_paywall_dismiss_step()],
        "dismiss-feedback-survey": [_tinder_feedback_survey_dismiss_step()],
    }
    if action not in actions:
        raise KeyError(action)
    return actions[action]


def _tinder_workflow_steps(workflow: str, **options: Any) -> list[dict[str, Any]]:
    if workflow == "self-profile-read":
        photo_steps = max(0, int(options.get("photo_steps", 1)))
        scroll_steps = max(0, int(options.get("scroll_steps", 1)))
        steps: list[dict[str, Any]] = []
        steps.extend(_tinder_action_steps("open-self-profile-preview"))
        for _ in range(photo_steps):
            steps.extend(_tinder_action_steps("profile-photo-next"))
        steps.extend(_tinder_action_steps("profile-photo-previous"))
        steps.extend(_tinder_action_steps("open-full-profile"))
        steps.append(_capture_profile_read_step())
        for _ in range(scroll_steps):
            steps.extend(_tinder_action_steps("profile-scroll-down"))
            steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("expand-visible-profile-section"))
        steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("close-full-profile"))
        steps.extend(_tinder_action_steps("close-preview"))
        return steps
    if workflow == "chat-read-match-profile":
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps", 1)))
        conversation_row = int(options.get("conversation_row", 1))
        steps = []
        steps.extend(_tinder_action_steps("open-chats"))
        steps.extend(_tinder_action_steps("open-conversation", row_index=conversation_row))
        steps.extend(_tinder_action_steps("open-thread-profile"))
        steps.extend(_tinder_action_steps("profile-photo-next"))
        steps.extend(_tinder_action_steps("open-full-profile"))
        steps.append(_capture_profile_read_step())
        for _ in range(profile_scroll_steps):
            steps.extend(_tinder_action_steps("profile-scroll-down"))
            steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("expand-visible-profile-section"))
        steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("close-full-profile"))
        return steps
    if workflow == "new-match-open":
        carousel_swipes = max(0, int(options.get("carousel_swipes", 0)))
        match_index = int(options.get("match_index", 1))
        steps = []
        steps.extend(_tinder_action_steps("open-chats"))
        for _ in range(carousel_swipes):
            steps.extend(_tinder_action_steps("matches-carousel-next"))
        steps.extend(_tinder_action_steps("open-new-match", match_index=match_index))
        return steps
    if workflow == "new-match-read-profile":
        carousel_swipes = max(0, int(options.get("carousel_swipes", 0)))
        match_index = int(options.get("match_index", 1))
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps", 1)))
        steps = []
        steps.extend(_tinder_action_steps("open-chats"))
        for _ in range(carousel_swipes):
            steps.extend(_tinder_action_steps("matches-carousel-next"))
        steps.extend(_tinder_action_steps("open-new-match", match_index=match_index))
        steps.extend(_tinder_action_steps("open-thread-profile"))
        steps.extend(_tinder_action_steps("profile-photo-next"))
        steps.extend(_tinder_action_steps("open-full-profile"))
        steps.append(_capture_profile_read_step())
        for _ in range(profile_scroll_steps):
            steps.extend(_tinder_action_steps("profile-scroll-down"))
            steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("expand-visible-profile-section"))
        steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("close-full-profile"))
        return steps
    raise KeyError(workflow)


def _bumble_tap_step(
    intent: str,
    *,
    x: float,
    y: float,
    requires_states: list[str] | str | None = None,
    expected_states: list[str] | str | None = None,
) -> dict[str, Any]:
    step = _harness_tap_step(intent, x=x, y=y, requires_verified_bumble_screen=True)
    if requires_states is not None:
        step["requires_bumble_states"] = requires_states
    if expected_states is not None:
        step["expected_bumble_states"] = expected_states
    return step


def _bumble_bottom_tab_step(intent: str, *, x: float, y: float, expected_state: str) -> dict[str, Any]:
    return _harness_tap_step(
        intent,
        x=x,
        y=y,
        requires_verified_bumble_screen=True,
        requires_bumble_top_level_tab_bar=True,
        expected_bumble_states=[expected_state],
    )


def _bumble_wheel_step(
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
        requires_verified_bumble_screen=True,
    )
    if requires_states is not None:
        step["requires_bumble_states"] = requires_states
    if expected_states is not None:
        step["expected_bumble_states"] = expected_states
    return step


def _bumble_action_steps(action: str, **options: Any) -> list[dict[str, Any]]:
    row_index = int(options.get("row_index") or options.get("conversation_row") or 1)
    match_index = int(options.get("match_index") or 1)
    row_y = min(0.86, 0.53 + (max(row_index, 1) - 1) * 0.12)
    if options.get("y_ratio") is not None:
        row_y = max(0.16, min(0.88, float(options["y_ratio"])))
    match_x = min(0.84, 0.34 + (max(match_index, 1) - 1) * 0.21)
    profile_read_states = ["bumble_browse", "bumble_profile", "bumble_self_profile"]
    visible_name = str(options.get("visible_name") or "").strip()
    target_binding = options.get("target_binding")
    visual_evidence = _message_list_visual_anchor_evidence_from_options(
        options,
        target_binding=target_binding if isinstance(target_binding, dict) else None,
        default_scan_region=BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
        default_max_distance=IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE,
    )
    if action == "open-conversation" and visual_evidence.get("status") == "ok":
        visual = _redacted_message_list_visual_anchor_evidence(visual_evidence)
        return [
            {
                "intent": "locate_bumble_conversation_row_visual_anchor",
                "requires_verified_bumble_screen": True,
                "requires_bumble_states": "bumble_chat_list",
                "risk": "navigation_only",
                "location_method": "message_list_visual_anchor_scan",
                "message_list_visual_anchor": visual,
            },
            {
                "intent": "tap_bumble_visible_conversation_row",
                "requires_verified_bumble_screen": True,
                "requires_bumble_states": "bumble_chat_list",
                "expected_bumble_states": "bumble_conversation",
                "risk": "navigation_only",
                "location_method": "message_list_visual_anchor_scan",
                "message_list_visual_anchor": visual,
            },
        ]
    if action == "open-conversation" and visual_evidence.get("status") == "blocked":
        return [
            {
                "intent": "message_list_visual_anchor_evidence_incomplete",
                "requires_verified_bumble_screen": True,
                "requires_bumble_states": "bumble_chat_list",
                "risk": "navigation_only",
                "location_method": "message_list_visual_anchor_scan",
                "evidence_status": "blocked",
                "reason": visual_evidence.get("reason") or "target_relocation_visual_evidence_required",
            }
        ]
    if not visible_name and isinstance(target_binding, dict):
        visible_name = _target_binding_primary_visible_name(target_binding) or ""
    if action == "open-conversation" and visible_name:
        marker_hash = _hash_text(visible_name)
        return [
            {
                "intent": "locate_bumble_visible_conversation_name",
                "target_marker_hash": marker_hash,
                "requires_verified_bumble_screen": True,
                "requires_bumble_states": "bumble_chat_list",
                "risk": "navigation_only",
                "location_method": "ocr_tsv_visible_text",
            },
            {
                "intent": "tap_bumble_visible_conversation_row",
                "target_marker_hash": marker_hash,
                "requires_verified_bumble_screen": True,
                "requires_bumble_states": "bumble_chat_list",
                "expected_bumble_states": "bumble_conversation",
                "risk": "navigation_only",
                "location_method": "ocr_tsv_visible_text",
            },
        ]
    actions: dict[str, list[dict[str, Any]]] = {
        "prepare-message-page": [
            {
                **_bumble_tap_step(
                    "tap_bumble_back_to_chats_if_in_thread",
                    x=0.09,
                    y=0.13,
                    requires_states=["bumble_conversation", "bumble_opening_move"],
                    expected_states="bumble_chat_list",
                ),
                "conditional": "when_current_state_is_bumble_thread_or_opening_move",
            },
            {
                **_bumble_bottom_tab_step("tap_bumble_chats_tab_if_needed", x=0.89, y=0.93, expected_state="bumble_chat_list"),
                "conditional": "when_current_state_is_bumble_top_level_not_chat_list",
            },
        ],
        "open-profile-tab": [_bumble_bottom_tab_step("tap_bumble_profile_tab", x=0.11, y=0.93, expected_state="bumble_self_profile")],
        "open-discover": [_bumble_bottom_tab_step("tap_bumble_discover_tab", x=0.31, y=0.93, expected_state="bumble_discover")],
        "open-browse": [_bumble_bottom_tab_step("tap_bumble_browse_tab", x=0.50, y=0.93, expected_state="bumble_browse")],
        "open-liked-you": [_bumble_bottom_tab_step("tap_bumble_liked_you_tab", x=0.70, y=0.93, expected_state="bumble_liked_you")],
        "open-chats": [_bumble_bottom_tab_step("tap_bumble_chats_tab", x=0.89, y=0.93, expected_state="bumble_chat_list")],
        "conversation-list-scroll-down": [
            _bumble_wheel_step(
                "wheel_bumble_conversation_list_down",
                x=0.50,
                y=0.78,
                delta_y=-18,
                repeats=14,
                requires_states="bumble_chat_list",
                expected_states="bumble_chat_list",
            )
        ],
        "conversation-list-scroll-up": [
            _bumble_wheel_step(
                "wheel_bumble_conversation_list_up",
                x=0.50,
                y=0.46,
                delta_y=18,
                repeats=14,
                requires_states="bumble_chat_list",
                expected_states="bumble_chat_list",
            )
        ],
        "open-conversation": [
            {
                **_bumble_tap_step(
                    "tap_bumble_conversation_row",
                    x=0.43,
                    y=row_y,
                    requires_states="bumble_chat_list",
                    expected_states="bumble_conversation",
                ),
                "row_index": row_index,
            }
        ],
        "open-match": [
            {
                **_bumble_tap_step(
                    "tap_bumble_match_circle",
                    x=match_x,
                    y=0.245,
                    requires_states="bumble_chat_list",
                    expected_states=["bumble_opening_move", "bumble_conversation"],
                ),
                "match_index": match_index,
            }
        ],
        "open-thread-profile": [
            _bumble_tap_step(
                "tap_bumble_thread_name",
                x=0.32,
                y=0.13,
                requires_states="bumble_conversation",
                expected_states="bumble_profile",
            )
        ],
        "open-opening-move-reply": [
            _bumble_tap_step(
                "tap_bumble_opening_move_reply",
                x=0.24,
                y=0.735,
                requires_states="bumble_opening_move",
                expected_states="bumble_conversation",
            )
        ],
        "profile-scroll-down": [
            _bumble_wheel_step(
                "wheel_bumble_profile_read_down",
                x=0.50,
                y=0.78,
                delta_y=-18,
                repeats=18,
                requires_states=profile_read_states,
                expected_states=profile_read_states,
            )
        ],
        "profile-scroll-up": [
            _bumble_wheel_step(
                "wheel_bumble_profile_read_up",
                x=0.50,
                y=0.46,
                delta_y=18,
                repeats=18,
                requires_states=profile_read_states,
                expected_states=profile_read_states,
            )
        ],
        "close-profile": [
            _bumble_tap_step(
                "tap_bumble_profile_close",
                x=0.09,
                y=0.13,
                requires_states="bumble_profile",
                expected_states="bumble_conversation",
            )
        ],
        "return-to-chats": [
            _bumble_tap_step(
                "tap_bumble_back_to_chats",
                x=0.09,
                y=0.13,
                requires_states=["bumble_conversation", "bumble_opening_move"],
                expected_states="bumble_chat_list",
            )
        ],
    }
    if action not in actions:
        raise KeyError(action)
    return actions[action]


def _bumble_workflow_steps(workflow: str, **options: Any) -> list[dict[str, Any]]:
    if workflow == "browse-profile-read":
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps") or options.get("scroll_steps") or 2))
        steps = []
        steps.extend(_bumble_action_steps("open-browse"))
        steps.append(_capture_profile_read_step(app_id="bumble"))
        for _ in range(profile_scroll_steps):
            steps.extend(_bumble_action_steps("profile-scroll-down"))
            steps.append(_capture_profile_read_step(app_id="bumble"))
        return steps
    if workflow == "chat-read-match-profile":
        conversation_row = int(options.get("conversation_row") or 1)
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps") or 2))
        steps = []
        steps.extend(_bumble_action_steps("open-chats"))
        steps.extend(_bumble_action_steps("open-conversation", row_index=conversation_row))
        steps.extend(_bumble_action_steps("open-thread-profile"))
        steps.append(_capture_profile_read_step(app_id="bumble"))
        for _ in range(profile_scroll_steps):
            steps.extend(_bumble_action_steps("profile-scroll-down"))
            steps.append(_capture_profile_read_step(app_id="bumble"))
        steps.extend(_bumble_action_steps("close-profile"))
        return steps
    if workflow == "opening-move-open":
        match_index = int(options.get("match_index") or 1)
        steps = []
        steps.extend(_bumble_action_steps("open-chats"))
        steps.extend(_bumble_action_steps("open-match", match_index=match_index))
        return steps
    if workflow == "opening-move-reply-composer":
        match_index = int(options.get("match_index") or 1)
        steps = []
        steps.extend(_bumble_action_steps("open-chats"))
        steps.extend(_bumble_action_steps("open-match", match_index=match_index))
        steps.extend(_bumble_action_steps("open-opening-move-reply"))
        return steps
    raise KeyError(workflow)


def _launch_tinder_steps() -> list[dict[str, Any]]:
    return _launch_app_steps(app_name="Tinder", search_result_intent="tap_tinder_search_result_icon")


def _launch_app_steps(
    *,
    app_name: str,
    search_result_intent: str,
    expected_app_labels: list[str] | None = None,
) -> list[dict[str, Any]]:
    type_step = _harness_marker_step("type_app_name_verified", text=app_name, wait_after_seconds=0.2)
    if expected_app_labels is not None:
        type_step["expected_app_labels"] = list(expected_app_labels)
    return [
        _harness_marker_step("open_iphone_home_screen", wait_after_seconds=0.8),
        _harness_marker_step("open_ios_spotlight", wait_after_seconds=0.4),
        type_step,
        _harness_tap_step(search_result_intent, x=0.18, y=0.20, wait_after_seconds=2.5),
    ]


def _bumble_profile_field_coverage(text: str) -> dict[str, bool]:
    normalized = _normalize_text(text)
    return {
        "about_me": any(marker in normalized for marker in ("我的简介", "about me")),
        "basic_info": any(marker in normalized for marker in ("关于我", "cm", "身高")),
        "looking_for": any(marker in normalized for marker in ("我在寻找", "长期恋爱关系", "终身伴侣")),
        "interests": any(marker in normalized for marker in ("我的兴趣爱好", "兴趣")),
        "opening_move": "opening move" in normalized,
        "reply_deadline": any(marker in normalized for marker in ("回复时间", "小时后失效", "失效")),
    }
