from __future__ import annotations

from .runtime_common import *

def _tashuo_open_conversation_requires_visual_relocation(options: dict[str, Any]) -> bool:
    evidence = _tashuo_message_list_relocation_evidence(
        {
            "message_list_evidence": options.get("message_list_evidence"),
            "selection_evidence": options.get("selection_evidence"),
            "target_selection_evidence": options.get("target_selection_evidence"),
            "visual_anchor_hash": options.get("visual_anchor_hash"),
            "visual_anchor_region": options.get("visual_anchor_region"),
            "visual_anchor_scan_region": options.get("visual_anchor_scan_region"),
            "visual_anchor_max_hamming_distance": options.get("visual_anchor_max_hamming_distance"),
            "tap_ratio": options.get("tap_ratio"),
            "selection_method": options.get("selection_method"),
        }
    )
    return evidence.get("status") == "ok" and evidence.get("evidence_type") == "message_list_visual_anchor"

def _try_tashuo_open_conversation_visual_relocation(
    session: Any,
    payload: dict[str, Any],
    *,
    options: dict[str, Any],
    output_dir: Path | None,
) -> dict[str, Any] | None:
    evidence = _tashuo_message_list_relocation_evidence(
        {
            "message_list_evidence": options.get("message_list_evidence"),
            "selection_evidence": options.get("selection_evidence"),
            "target_selection_evidence": options.get("target_selection_evidence"),
            "visual_anchor_hash": options.get("visual_anchor_hash"),
            "visual_anchor_region": options.get("visual_anchor_region"),
            "visual_anchor_scan_region": options.get("visual_anchor_scan_region"),
            "visual_anchor_max_hamming_distance": options.get("visual_anchor_max_hamming_distance"),
            "tap_ratio": options.get("tap_ratio"),
            "selection_method": options.get("selection_method"),
        }
    )
    if evidence.get("status") != "ok" or evidence.get("evidence_type") != "message_list_visual_anchor":
        return None
    window = session._window_info()
    if window is None:
        return {
            **payload,
            "status": "blocked",
            "reason": "target_relocation_window_missing",
            **_tashuo_window_missing_payload(session),
        }
    list_result = _ensure_tashuo_message_list_for_relocation(
        session,
        window,
        output_dir=output_dir,
        attempt_index=1,
    )
    relocation: dict[str, Any] = {
        "status": list_result.get("status"),
        "message_list_recovery": list_result,
    }
    if list_result.get("status") != "ok":
        relocation["reason"] = list_result.get("reason") or "target_relocation_message_list_not_verified"
        return {
            **payload,
            "status": "blocked",
            "reason": relocation["reason"],
            "message_list_relocation": relocation,
        }
    list_screen = list_result.get("screen_payload") if isinstance(list_result.get("screen_payload"), dict) else {}
    location = _locate_tashuo_message_list_visual_target(list_screen, evidence)
    relocation["message_list_location"] = location
    if location.get("status") != "ok":
        relocation["status"] = "blocked"
        relocation["reason"] = location.get("reason") or "target_relocation_visual_anchor_not_found"
        return {
            **payload,
            "status": "blocked",
            "reason": relocation["reason"],
            "message_list_relocation": relocation,
        }
    tap_ratio = location.get("tap_ratio") if isinstance(location.get("tap_ratio"), dict) else None
    if tap_ratio is None:
        relocation["status"] = "blocked"
        relocation["reason"] = "target_relocation_tap_ratio_unavailable"
        return {
            **payload,
            "status": "blocked",
            "reason": relocation["reason"],
            "message_list_relocation": relocation,
        }
    relocation["status"] = "ok"
    relocated_steps = list(payload.get("planned_steps") or [])
    if relocated_steps:
        relocated_steps[0] = {
            **relocated_steps[0],
            "tap_ratio": _copy_tap_ratio(tap_ratio),
            "selection_method": "message_list_visual_anchor_scan",
            "message_list_location": location,
        }
    result = session._execute_planned_steps(
        {
            **payload,
            "planned_steps": relocated_steps,
            "message_list_relocation": relocation,
        },
        output_dir=output_dir,
    )
    fallback = _retry_tashuo_message_list_open_after_postcondition_failure(
        session,
        payload=payload,
        relocated_steps=relocated_steps,
        location=location,
        first_result=result,
        output_dir=output_dir,
    )
    if fallback is not None:
        result = fallback
    result["message_list_relocation"] = relocation
    return result

def _retry_tashuo_message_list_open_after_postcondition_failure(
    session: Any,
    *,
    payload: dict[str, Any],
    relocated_steps: list[dict[str, Any]],
    location: dict[str, Any],
    first_result: dict[str, Any],
    output_dir: Path | None,
) -> dict[str, Any] | None:
    if first_result.get("status") != "blocked":
        return None
    if first_result.get("reason") != "tashuo_step_postcondition_not_verified":
        return None
    first_step = {}
    steps = first_result.get("executed_steps")
    if isinstance(steps, list) and steps and isinstance(steps[0], dict):
        first_step = steps[0]
    postcondition = first_step.get("postcondition") if isinstance(first_step.get("postcondition"), dict) else {}
    if postcondition.get("screen_state") != "tashuo_chat_list":
        return None
    if not relocated_steps:
        return None

    attempts: list[dict[str, Any]] = []
    for attempt_index, fallback_tap in enumerate(_tashuo_message_list_open_fallback_taps(location), start=1):
        retry_steps = list(relocated_steps)
        retry_steps[0] = {
            **retry_steps[0],
            "tap_ratio": fallback_tap["tap_ratio"],
            "selection_method": fallback_tap["selection_method"],
            "message_list_open_fallback": {
                "attempt_index": attempt_index,
                "reason": "action_tap_postcondition_not_verified",
                "first_postcondition_screen_state": postcondition.get("screen_state"),
            },
        }
        retry_result = session._execute_planned_steps(
            {
                **payload,
                "planned_steps": retry_steps,
                "message_list_open_fallback_attempt": attempt_index,
            },
            output_dir=output_dir,
        )
        attempts.append(
            {
                "attempt_index": attempt_index,
                "tap_ratio": fallback_tap["tap_ratio"],
                "selection_method": fallback_tap["selection_method"],
                "result": {
                    "status": retry_result.get("status"),
                    "reason": retry_result.get("reason"),
                    "screen_state": retry_result.get("screen_state"),
                },
            }
        )
        if retry_result.get("status") == "ok":
            retry_result["message_list_open_initial_result"] = {
                "status": first_result.get("status"),
                "reason": first_result.get("reason"),
                "postcondition_screen_state": postcondition.get("screen_state"),
            }
            retry_result["message_list_open_fallback_attempts"] = attempts
            return retry_result
        if retry_result.get("reason") != "tashuo_step_postcondition_not_verified":
            break

    return {
        **first_result,
        "message_list_open_fallback_attempts": attempts,
    }

def _tashuo_message_list_open_fallback_taps(location: dict[str, Any]) -> list[dict[str, Any]]:
    raw = location.get("raw_tap_ratio") if isinstance(location.get("raw_tap_ratio"), dict) else {}
    tap = location.get("tap_ratio") if isinstance(location.get("tap_ratio"), dict) else {}
    region = location.get("visual_anchor_region") if isinstance(location.get("visual_anchor_region"), dict) else {}
    try:
        y = float(tap.get("y") if "y" in tap else raw.get("y"))
    except (TypeError, ValueError):
        y = 0.5
    y = max(0.0, min(TASHUO_CHAT_LIST_BOTTOM_ROW_SAFE_TAP_Y, y))
    taps = [
        {
            "selection_method": "message_list_visual_anchor_body_fallback_tap",
            "tap_ratio": {"x": 0.50, "y": round(y, 4)},
        }
    ]
    try:
        avatar_x = max(0.10, min(0.28, (float(region["x1"]) + float(region["x2"])) / 2.0))
    except (KeyError, TypeError, ValueError):
        avatar_x = 0.16
    taps.append(
        {
            "selection_method": "message_list_visual_anchor_avatar_fallback_tap",
            "tap_ratio": {"x": round(avatar_x, 4), "y": round(y, 4)},
        }
    )
    return taps

def _tashuo_already_at_open_conversation_target(
    session: Any,
    planned_steps: list[dict[str, Any]],
    *,
    output_dir: Path | None = None,
) -> dict[str, Any] | None:
    if not planned_steps:
        return None
    expected_states = planned_steps[0].get("expected_tashuo_states")
    expected = set(expected_states if isinstance(expected_states, list) else [expected_states])
    expected.discard(None)
    if not expected:
        return None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    before = output_dir / f"{_tashuo_capture_prefix(session)}.before_action.png" if output_dir is not None else None
    doctor = session.doctor(capture=True, output=before, ocr=not _is_mac_ios_app_session(session))
    if doctor.get("status") == "blocked":
        return {
            "preflight": doctor,
            "status": "blocked",
            "reason": doctor.get("reason") or "tashuo_preflight_not_verified",
        }
    screen_state = doctor.get("screen", {}).get("state")
    if screen_state not in expected:
        return None
    return {
        "preflight": doctor,
        "screen_state": screen_state,
        "already_at_expected_state": True,
        "target_binding_created": False,
        "next_host_action": "observe_current_thread",
    }

def _verify_tashuo_target_binding(
    session: Any,
    target_binding: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    if target_binding.get("binding_type") == "chat_list_row_to_thread":
        return _verify_tashuo_chat_list_row_target_binding(session, target_binding, output_dir=output_dir)
    if target_binding.get("binding_type") == "current_thread_visual_identity":
        return _verify_tashuo_current_thread_visual_identity(session, target_binding, output_dir=output_dir)
    if _is_mac_ios_app_session(session):
        return {
            "verification_method": "tashuo_mac_ios_app_structural_binding_required",
            "target_match_id": target_binding.get("target_match_id"),
            "candidate_key": target_binding.get("candidate_key"),
            "requires_header_marker": False,
            "requires_structural_binding": True,
            "status": "blocked",
            "reason": "target_binding_structural_evidence_required",
        }

    markers = platform._target_binding_required_markers(target_binding)
    base = {
        "verification_method": "tashuo_screen_ocr_required_visible_text",
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "required_marker_hashes": [platform._hash_text(marker) for marker in markers],
        "requires_target_specific_marker": True,
        "requires_header_marker": True,
    }
    if not markers:
        return {**base, "status": "blocked", "reason": "target_binding_required"}
    if not target_binding_specific_marker_present("tashuo", target_binding):
        return {**base, "status": "blocked", "reason": "target_binding_not_target_specific"}
    window = session._window_info()
    if window is None:
        return {**base, "status": "blocked", **_tashuo_window_missing_payload(session)}
    output = output_dir / f"{_tashuo_capture_prefix(session)}.target_binding.png" if output_dir is not None else None
    screen = _capture_tashuo_window(session, output=output, window=window)
    observed_text = str(screen.get("text") or "")
    header_text = _tashuo_header_text(observed_text)
    matched = [marker for marker in markers if _tashuo_marker_matches_text(observed_text, marker)]
    header_matched = [marker for marker in markers if _tashuo_marker_matches_text(header_text, marker)]
    result = {
        **base,
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "observed_text_hash": platform._hash_text(observed_text) if observed_text else None,
        "matched_marker_hashes": [platform._hash_text(marker) for marker in matched],
        "header_marker_hashes": [platform._hash_text(marker) for marker in header_matched],
        "header_text_hash": platform._hash_text(header_text) if header_text else None,
    }
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": "target_binding_screen_capture_failed"}
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return {**result, "status": "blocked", "reason": screen.get("state")}
    if screen.get("state") == "tashuo_question_gate":
        return {**result, "status": "blocked", "reason": "tashuo_question_gate_requires_user_confirmation"}
    if screen.get("state") != "tashuo_conversation":
        return {**result, "status": "blocked", "reason": "target_binding_chat_not_verified"}
    if len(matched) != len(markers):
        return {**result, "status": "blocked", "reason": "target_binding_mismatch"}
    if not header_matched:
        return {**result, "status": "blocked", "reason": "target_binding_header_mismatch"}
    return {**result, "status": "ok"}

def _tashuo_current_thread_visual_anchor(
    screen: dict[str, Any],
    *,
    region: dict[str, float] | None = None,
) -> dict[str, Any]:
    anchor_region = region or dict(TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION)
    base = {
        "screen_state": screen.get("state", "unknown"),
        "visual_state": screen.get("visual_state", "unknown"),
        "visual_anchor_region": anchor_region,
        "uses_header_ocr": False,
    }
    if screen.get("status") != "ok":
        return {**base, "status": "blocked", "reason": screen.get("reason") or "screen_not_captured"}
    if screen.get("state") != "tashuo_conversation":
        return {**base, "status": "blocked", "reason": "tashuo_conversation_not_verified"}
    screen_path = str(screen.get("path") or "")
    if not screen_path:
        return {**base, "status": "blocked", "reason": "target_binding_screen_path_missing"}
    return {
        **base,
        **_tashuo_visual_anchor_hash_for_path(Path(screen_path), region=anchor_region),
    }

def _verify_tashuo_current_thread_visual_identity(
    session: Any,
    target_binding: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    thread_evidence = (
        target_binding.get("thread_evidence") if isinstance(target_binding.get("thread_evidence"), dict) else {}
    )
    expected_visual_hash = str(thread_evidence.get("visual_anchor_hash") or "").strip()
    visual_region = _tashuo_visual_anchor_region(thread_evidence)
    max_distance = _tashuo_visual_anchor_max_distance(thread_evidence)
    base = {
        "verification_method": "tashuo_current_thread_visual_identity",
        "binding_type": target_binding.get("binding_type"),
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "conversation_fingerprint_hash": platform._hash_text(str(target_binding.get("conversation_fingerprint") or "")),
        "pre_action_observation_id": thread_evidence.get("observation_id"),
        "latest_inbound_fingerprint_hash": platform._hash_text(str(thread_evidence.get("latest_inbound_fingerprint") or "")),
        "expected_visual_anchor_hash": expected_visual_hash or None,
        "visual_anchor_region": visual_region,
        "visual_anchor_max_hamming_distance": max_distance,
        "requires_visual_anchor": True,
        "requires_header_marker": False,
        "requires_fresh_conversation_screen": True,
        "uses_header_ocr": False,
        "visual_only_exact_verification_allowed": _is_mac_ios_app_session(session),
    }
    if not target_binding_structural_evidence_present("tashuo", target_binding):
        return {**base, "status": "blocked", "reason": "target_binding_structural_evidence_required"}
    window = session._window_info()
    if window is None:
        return {**base, "status": "blocked", **_tashuo_window_missing_payload(session)}
    output = output_dir / f"{_tashuo_capture_prefix(session)}.target_binding.png" if output_dir is not None else None
    screen = _capture_tashuo_window(session, output=output, window=window)
    screen_path = str(screen.get("path") or "")
    visual_hash_result = _tashuo_visual_anchor_hash_for_path(Path(screen_path), region=visual_region) if screen_path else {
        "status": "blocked",
        "reason": "target_binding_screen_path_missing",
    }
    observed_visual_hash = str(visual_hash_result.get("visual_anchor_hash") or "")
    visual_distance = (
        _visual_anchor_hamming_distance(expected_visual_hash, observed_visual_hash)
        if expected_visual_hash and observed_visual_hash
        else None
    )
    result = {
        **base,
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "visual_state": screen.get("visual_state", "unknown"),
        "visual_anchor_hash_status": visual_hash_result.get("status"),
        "observed_visual_anchor_hash": observed_visual_hash or None,
        "visual_anchor_hamming_distance": visual_distance,
    }
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": "target_binding_screen_capture_failed"}
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return {**result, "status": "blocked", "reason": screen.get("state")}
    if screen.get("state") == "tashuo_question_gate":
        return {**result, "status": "blocked", "reason": "tashuo_question_gate_requires_user_confirmation"}
    if screen.get("state") != "tashuo_conversation":
        return {**result, "status": "blocked", "reason": "target_binding_chat_not_verified"}
    if visual_hash_result.get("status") != "ok":
        return {
            **result,
            "status": "blocked",
            "reason": visual_hash_result.get("reason") or "target_binding_visual_anchor_unavailable",
        }
    if visual_distance is None or visual_distance > max_distance:
        return {**result, "status": "blocked", "reason": "target_binding_visual_anchor_mismatch"}
    return {**result, "status": "ok"}

def _recover_tashuo_current_thread_visual_identity_mismatch(
    session: Any,
    target_binding: dict[str, Any],
    *,
    output_dir: Path | None = None,
    max_attempts: int = TASHUO_MAC_IOS_APP_TARGET_RELOCATION_MAX_ATTEMPTS,
) -> dict[str, Any]:
    evidence = _tashuo_message_list_relocation_evidence(target_binding)
    base = {
        "recovery_method": "tashuo_mac_ios_app_message_list_visual_relocation",
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "attempt_limit": max_attempts,
        "requires_message_list_visual_evidence": True,
        "uses_fixed_row_index": False,
        "uses_header_ocr": False,
    }
    if evidence.get("status") != "ok":
        return {**base, **evidence, "status": "blocked"}
    window = session._window_info()
    if window is None:
        return {**base, "status": "blocked", **_tashuo_window_missing_payload(session)}

    attempts: list[dict[str, Any]] = []
    for attempt_index in range(1, max_attempts + 1):
        list_screen_result = _ensure_tashuo_message_list_for_relocation(
            session,
            window,
            output_dir=output_dir,
            attempt_index=attempt_index,
        )
        attempt: dict[str, Any] = {
            "attempt_index": attempt_index,
            "message_list_recovery": list_screen_result,
        }
        if list_screen_result.get("status") != "ok":
            attempts.append(attempt)
            return {
                **base,
                "status": "blocked",
                "reason": list_screen_result.get("reason") or "target_relocation_message_list_not_verified",
                "attempts": attempts,
            }

        list_screen = list_screen_result.get("screen_payload") if isinstance(list_screen_result.get("screen_payload"), dict) else {}
        location = _locate_tashuo_message_list_visual_target(list_screen, evidence)
        attempt["message_list_location"] = location
        if location.get("status") != "ok":
            attempts.append(attempt)
            if attempt_index < max_attempts:
                time.sleep(0.25)
                continue
            break

        tap_ratio = location.get("tap_ratio") if isinstance(location.get("tap_ratio"), dict) else None
        if tap_ratio is None:
            attempts.append(attempt)
            return {
                **base,
                "status": "blocked",
                "reason": "target_relocation_tap_ratio_unavailable",
                "attempts": attempts,
            }
        click_result = session._click_ratio(window, tap_ratio)
        attempt["open_target_click"] = {
            "intent": "tap_tashuo_relocated_visual_conversation_target",
            "tap_ratio": _copy_tap_ratio(tap_ratio),
            "result": click_result,
        }
        if click_result.get("status") != "ok":
            attempts.append(attempt)
            return {
                **base,
                "status": "blocked",
                "reason": click_result.get("reason") or "target_relocation_open_click_failed",
                "attempts": attempts,
            }
        _sleep_for_tashuo_post_action_observation(session, fallback=0.45)

        verification = _verify_tashuo_current_thread_visual_identity(session, target_binding, output_dir=output_dir)
        attempt["target_binding_verification"] = verification
        attempts.append(attempt)
        if verification.get("status") == "ok":
            return {
                **base,
                "status": "ok",
                "attempt_count": attempt_index,
                "attempts": attempts,
                "target_binding_verification": {
                    **verification,
                    "recovered_by": "message_list_visual_relocation",
                    "relocation_attempt_count": attempt_index,
                },
            }
        if verification.get("reason") != "target_binding_visual_anchor_mismatch":
            return {
                **base,
                "status": "blocked",
                "reason": verification.get("reason") or "target_relocation_target_verification_failed",
                "attempts": attempts,
            }

    return {
        **base,
        "status": "blocked",
        "reason": "target_binding_visual_relocation_exhausted",
        "last_reason": (
            attempts[-1].get("target_binding_verification", {}).get("reason")
            if isinstance(attempts[-1].get("target_binding_verification"), dict)
            else attempts[-1].get("message_list_location", {}).get("reason")
            if isinstance(attempts[-1].get("message_list_location"), dict)
            else None
        ) if attempts else None,
        "attempts": attempts,
    }

def _ensure_tashuo_message_list_for_relocation(
    session: Any,
    window: Any,
    *,
    output_dir: Path | None,
    attempt_index: int,
) -> dict[str, Any]:
    prefix = _tashuo_capture_prefix(session)
    current_output = (
        output_dir / f"{prefix}.target_relocation_{attempt_index:02d}.current.png"
        if output_dir is not None
        else None
    )
    current = _capture_tashuo_window(session, output=current_output, window=window, ocr=not _is_mac_ios_app_session(session))
    result: dict[str, Any] = {
        "status": current.get("status", "blocked"),
        "screen": platform._redacted_screen(current),
        "screen_state": current.get("state", "unknown"),
    }
    if result["status"] != "ok":
        return {**result, "reason": current.get("reason") or "target_relocation_current_screen_not_captured"}
    if current.get("state") == "tashuo_chat_list":
        return {**result, "screen_payload": current}
    if current.get("state") not in {"tashuo_conversation", "tashuo_question_gate"}:
        return {**result, "status": "blocked", "reason": "target_relocation_requires_thread_or_message_list"}

    return_step = _tashuo_action_steps("return-to-chats")[0]
    click_result = session._click_ratio(window, return_step["tap_ratio"])
    result["return_to_chats"] = {
        "intent": return_step["intent"],
        "tap_ratio": _copy_tap_ratio(return_step["tap_ratio"]),
        "result": click_result,
    }
    if click_result.get("status") != "ok":
        return {**result, "status": "blocked", "reason": click_result.get("reason") or "target_relocation_back_failed"}
    _sleep_for_tashuo_post_action_observation(session, fallback=0.45)

    list_output = (
        output_dir / f"{prefix}.target_relocation_{attempt_index:02d}.message_list.png"
        if output_dir is not None
        else None
    )
    list_screen = _capture_tashuo_window(session, output=list_output, window=window, ocr=not _is_mac_ios_app_session(session))
    result["message_list_screen"] = platform._redacted_screen(list_screen)
    result["message_list_screen_state"] = list_screen.get("state", "unknown")
    if list_screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": list_screen.get("reason") or "target_relocation_message_list_not_captured"}
    if list_screen.get("state") != "tashuo_chat_list":
        return {**result, "status": "blocked", "reason": "target_relocation_message_list_not_verified"}
    return {**result, "status": "ok", "screen_payload": list_screen}

def _tashuo_message_list_relocation_evidence(target_binding: dict[str, Any]) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for key in ("message_list_evidence", "selection_evidence", "target_selection_evidence"):
        value = target_binding.get(key)
        if isinstance(value, dict):
            sources.append(value)
    sources.append(target_binding)
    for source in sources:
        evidence = _normalize_tashuo_message_list_relocation_evidence(source)
        if evidence.get("status") == "ok":
            return evidence
    return {
        "status": "blocked",
        "reason": "target_relocation_visual_evidence_required",
        "accepted_evidence": [
            "message_list_evidence.visual_anchor_hash + visual_anchor_region",
            "selection_evidence.visual_anchor_hash + visual_anchor_region",
            "selection_evidence.tap_ratio as fallback only",
        ],
    }

def _normalize_tashuo_message_list_relocation_evidence(source: dict[str, Any]) -> dict[str, Any]:
    tap_ratio = _tap_ratio_option(
        source.get("tap_ratio")
        or source.get("visual_tap_ratio")
        or source.get("target_tap_ratio")
    )
    visual_hash = str(
        source.get("visual_anchor_hash")
        or source.get("row_visual_anchor_hash")
        or source.get("message_list_visual_anchor_hash")
        or ""
    ).strip()
    region = _tashuo_normalized_region(
        source.get("visual_anchor_region")
        or source.get("row_visual_anchor_region")
        or source.get("message_list_visual_anchor_region"),
        fallback=None,
    )
    if visual_hash and region is not None:
        max_distance = _tashuo_int_in_range(
            source.get("visual_anchor_max_hamming_distance")
            or source.get("row_visual_anchor_max_hamming_distance"),
            default=TASHUO_CHAT_LIST_VISUAL_ANCHOR_MAX_DISTANCE,
            minimum=0,
            maximum=32,
        )
        scan_region = _tashuo_normalized_region(
            source.get("visual_anchor_scan_region") or source.get("scan_region"),
            fallback=TASHUO_CHAT_LIST_VISUAL_ANCHOR_SCAN_REGION,
        )
        return {
            "status": "ok",
            "evidence_type": "message_list_visual_anchor",
            "visual_anchor_hash": visual_hash,
            "visual_anchor_region": region,
            "visual_anchor_max_hamming_distance": max_distance,
            "visual_anchor_scan_region": scan_region,
            "tap_ratio": tap_ratio,
            "tap_ratio_source": source.get("tap_ratio_source"),
            "source_state": source.get("source_state"),
            "selection_method": source.get("selection_method") or "message_list_visual_anchor_scan",
        }
    if tap_ratio is not None:
        return {
            "status": "ok",
            "evidence_type": "visual_tap_ratio_fallback",
            "tap_ratio": tap_ratio,
            "selection_method": source.get("selection_method") or "host_visual_tap_ratio",
            "visual_anchor_hash": None,
        }
    return {"status": "blocked", "reason": "target_relocation_visual_evidence_required"}

def _locate_tashuo_message_list_visual_target(
    list_screen: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if list_screen.get("status") != "ok":
        return {"status": "blocked", "reason": "target_relocation_message_list_not_captured"}
    if list_screen.get("state") != "tashuo_chat_list":
        return {"status": "blocked", "reason": "target_relocation_message_list_not_verified"}
    if evidence.get("evidence_type") == "visual_tap_ratio_fallback":
        tap_ratio = evidence.get("tap_ratio") if isinstance(evidence.get("tap_ratio"), dict) else None
        if tap_ratio is None:
            return {"status": "blocked", "reason": "target_relocation_tap_ratio_unavailable"}
        return {
            "status": "ok",
            "location_method": "visual_tap_ratio_fallback",
            "tap_ratio": _copy_tap_ratio(tap_ratio),
            "uses_fixed_row_index": False,
            "visual_anchor_scanned": False,
        }
    expected_hash = str(evidence.get("visual_anchor_hash") or "").strip()
    source_region = evidence.get("visual_anchor_region") if isinstance(evidence.get("visual_anchor_region"), dict) else None
    scan_region = evidence.get("visual_anchor_scan_region") if isinstance(evidence.get("visual_anchor_scan_region"), dict) else None
    if not expected_hash or source_region is None or scan_region is None:
        return {"status": "blocked", "reason": "target_relocation_visual_anchor_evidence_incomplete"}
    path = str(list_screen.get("path") or "")
    if not path:
        return {"status": "blocked", "reason": "target_relocation_message_list_screen_path_missing"}
    try:
        screen_pixels = _read_png_pixels(Path(path))
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": "target_binding_visual_anchor_read_failed",
            "error": str(exc)[:80],
        }

    row_height = max(0.03, min(0.28, float(source_region["y2"]) - float(source_region["y1"])))
    row_width = max(0.05, min(1.0, float(source_region["x2"]) - float(source_region["x1"])))
    scan_y1 = max(0.0, min(1.0 - row_height, float(scan_region["y1"])))
    scan_y2 = max(scan_y1 + row_height, min(1.0, float(scan_region["y2"])))
    source_x1 = max(0.0, min(1.0 - row_width, float(source_region["x1"])))
    source_x2 = source_x1 + row_width
    tap_ratio = evidence.get("tap_ratio") if isinstance(evidence.get("tap_ratio"), dict) else None
    tap_y_offset = 0.5
    prior_tap_y: float | None = None
    if tap_ratio is not None:
        tap_y_offset = (float(tap_ratio["y"]) - float(source_region["y1"])) / row_height
        prior_tap_y = max(0.0, min(1.0, float(tap_ratio["y"])))
    tap_y_offset = max(0.05, min(0.95, tap_y_offset))
    tap_x = float(tap_ratio["x"]) if tap_ratio is not None else (source_x1 + source_x2) / 2.0
    max_distance = int(evidence.get("visual_anchor_max_hamming_distance") or TASHUO_CHAT_LIST_VISUAL_ANCHOR_MAX_DISTANCE)
    preserve_action_tap = _tashuo_message_list_relocation_preserves_action_tap(evidence)
    if tap_ratio is not None and preserve_action_tap:
        source_hash = _tashuo_visual_anchor_hash_for_pixels(screen_pixels, region=source_region)
        observed_source_hash = str(source_hash.get("visual_anchor_hash") or "")
        source_distance = (
            _visual_anchor_hamming_distance(expected_hash, observed_source_hash)
            if source_hash.get("status") == "ok" and observed_source_hash
            else None
        )
        if source_distance is not None and source_distance <= max_distance:
            safe_tap = _safe_tashuo_message_list_visual_anchor_tap_ratio(
                _copy_tap_ratio(tap_ratio),
                matched_region=source_region,
                row_height=row_height,
                preserve_action_tap=True,
            )
            return {
                "status": "ok",
                "location_method": "message_list_visual_anchor_current_region_tap",
                "expected_visual_anchor_hash": expected_hash,
                "observed_visual_anchor_hash": observed_source_hash or None,
                "visual_anchor_hamming_distance": source_distance,
                "visual_anchor_max_hamming_distance": max_distance,
                "visual_anchor_region": source_region,
                "tap_ratio": safe_tap["tap_ratio"],
                "raw_tap_ratio": _copy_tap_ratio(tap_ratio),
                "tap_adjustment": safe_tap["tap_adjustment"],
                "tap_ratio_source": evidence.get("tap_ratio_source"),
                "uses_fixed_row_index": False,
                "visual_anchor_scanned": False,
                "current_region_verified": True,
            }
    step_y = max(0.004, min(0.012, row_height / 12.0))
    best: dict[str, Any] | None = None
    candidate_count = 0
    y = scan_y1
    while y <= scan_y2 - row_height + 0.0001:
        region = {"x1": source_x1, "y1": y, "x2": source_x2, "y2": y + row_height}
        hash_result = _tashuo_visual_anchor_hash_for_pixels(screen_pixels, region=region)
        candidate_count += 1
        observed_hash = str(hash_result.get("visual_anchor_hash") or "")
        distance = (
            _visual_anchor_hamming_distance(expected_hash, observed_hash)
            if hash_result.get("status") == "ok" and observed_hash
            else None
        )
        candidate = {
            "status": hash_result.get("status"),
            "visual_anchor_region": region,
            "observed_visual_anchor_hash": observed_hash or None,
            "visual_anchor_hamming_distance": distance,
            "visual_anchor_tap_y_delta": (
                abs(max(0.0, min(1.0, y + row_height * tap_y_offset)) - prior_tap_y)
                if prior_tap_y is not None
                else None
            ),
        }
        if distance is not None and (
            best is None
            or distance < int(best["visual_anchor_hamming_distance"])
            or (
                distance == int(best["visual_anchor_hamming_distance"])
                and candidate["visual_anchor_tap_y_delta"] is not None
                and (
                    best.get("visual_anchor_tap_y_delta") is None
                    or float(candidate["visual_anchor_tap_y_delta"]) < float(best["visual_anchor_tap_y_delta"])
                )
            )
        ):
            best = candidate
        y += step_y

    if best is None:
        return {
            "status": "blocked",
            "reason": "target_relocation_visual_anchor_unavailable",
            "candidate_count": candidate_count,
        }
    if int(best["visual_anchor_hamming_distance"]) > max_distance:
        return {
            **best,
            "status": "blocked",
            "reason": "target_relocation_visual_anchor_not_found",
            "expected_visual_anchor_hash": expected_hash,
            "visual_anchor_max_hamming_distance": max_distance,
            "candidate_count": candidate_count,
        }
    matched_region = best["visual_anchor_region"]
    raw_tap_ratio = {
        "x": max(0.0, min(1.0, tap_x)),
        "y": max(0.0, min(1.0, float(matched_region["y1"]) + row_height * tap_y_offset)),
    }
    safe_tap = _safe_tashuo_message_list_visual_anchor_tap_ratio(
        raw_tap_ratio,
        matched_region=matched_region,
        row_height=row_height,
        preserve_action_tap=preserve_action_tap,
    )
    return {
        **best,
        "status": "ok",
        "location_method": "message_list_visual_anchor_scan",
        "expected_visual_anchor_hash": expected_hash,
        "visual_anchor_max_hamming_distance": max_distance,
        "candidate_count": candidate_count,
        "tap_ratio": safe_tap["tap_ratio"],
        "raw_tap_ratio": raw_tap_ratio,
        "tap_adjustment": safe_tap["tap_adjustment"],
        "tap_ratio_source": evidence.get("tap_ratio_source"),
        "uses_fixed_row_index": False,
        "visual_anchor_scanned": True,
    }

def _tashuo_message_list_relocation_preserves_action_tap(evidence: dict[str, Any]) -> bool:
    source = str(evidence.get("tap_ratio_source") or "").strip().lower()
    return source in {"corrected_all_messages_row_action"}

def _safe_tashuo_message_list_visual_anchor_tap_ratio(
    tap_ratio: dict[str, float],
    *,
    matched_region: dict[str, Any],
    row_height: float,
    preserve_action_tap: bool = False,
) -> dict[str, Any]:
    tap_y = max(0.0, min(1.0, float(tap_ratio["y"])))
    adjusted = False
    reason = None
    try:
        region_y1 = float(matched_region["y1"])
        region_y2 = float(matched_region["y2"])
    except (KeyError, TypeError, ValueError):
        region_y1 = tap_y - row_height / 2.0
        region_y2 = tap_y + row_height / 2.0

    reasons: list[str] = []
    bottom_row = (
        region_y1 >= TASHUO_CHAT_LIST_BOTTOM_ROW_TOP_THRESHOLD
        or region_y2 >= TASHUO_CHAT_LIST_BOTTOM_ROW_REGION_THRESHOLD
        or tap_y >= TASHUO_CHAT_LIST_BOTTOM_ROW_SAFE_TAP_Y
    )
    if preserve_action_tap:
        if tap_y >= TASHUO_CHAT_LIST_BOTTOM_NAV_TOP_RATIO:
            safe_y = min(tap_y, TASHUO_CHAT_LIST_BOTTOM_ROW_SAFE_TAP_Y)
            if safe_y < tap_y:
                tap_y = safe_y
                adjusted = True
                reasons.append("bottom_nav_overlap_guard")
    elif bottom_row:
        safe_y = max(0.0, min(1.0, min(tap_y, TASHUO_CHAT_LIST_BOTTOM_ROW_SAFE_TAP_Y)))
        if safe_y < tap_y:
            tap_y = safe_y
            adjusted = True
            reasons.append("bottom_row_safe_tap_guard")
    else:
        top_band_y = region_y1 + max(
            TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MIN,
            min(TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MAX, row_height * TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_FRACTION),
        )
        if top_band_y < tap_y:
            tap_y = max(0.0, min(1.0, top_band_y))
            adjusted = True
            reasons.append("row_upper_band_guard")

        if tap_y >= TASHUO_CHAT_LIST_BOTTOM_NAV_TOP_RATIO:
            safe_y = min(tap_y, TASHUO_CHAT_LIST_BOTTOM_ROW_SAFE_TAP_Y)
            if safe_y < tap_y:
                tap_y = safe_y
                adjusted = True
                reasons.append("bottom_nav_overlap_guard")
    reason = "+".join(reasons) if reasons else None

    return {
        "tap_ratio": {
            "x": max(0.0, min(1.0, float(tap_ratio["x"]))),
            "y": tap_y,
        },
        "tap_adjustment": {
            "adjusted": adjusted,
            "reason": reason,
            "bottom_nav_top_ratio": TASHUO_CHAT_LIST_BOTTOM_NAV_TOP_RATIO,
            "bottom_row_safe_tap_y": TASHUO_CHAT_LIST_BOTTOM_ROW_SAFE_TAP_Y,
            "bottom_row_detected": bottom_row,
            "matched_region_y2": region_y2,
        },
    }

def _tashuo_visual_anchor_region(thread_evidence: dict[str, Any]) -> dict[str, float]:
    raw = thread_evidence.get("visual_anchor_region")
    return _tashuo_normalized_region(raw, fallback=TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION) or dict(
        TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION
    )

def _tashuo_normalized_region(
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

def _tashuo_int_in_range(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))

def _tashuo_visual_anchor_max_distance(thread_evidence: dict[str, Any]) -> int:
    try:
        value = int(thread_evidence.get("visual_anchor_max_hamming_distance"))
    except (TypeError, ValueError):
        return TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE
    return max(TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE, min(16, value))

def _tashuo_visual_anchor_hash_for_path(
    path: Path,
    *,
    region: dict[str, float] | None = None,
    grid_size: int = 8,
) -> dict[str, Any]:
    try:
        pixels = _read_png_pixels(path)
    except Exception as exc:
        return {"status": "blocked", "reason": "target_binding_visual_anchor_read_failed", "error": str(exc)[:80]}
    return _tashuo_visual_anchor_hash_for_pixels(pixels, region=region, grid_size=grid_size)

def _tashuo_visual_anchor_hash_for_pixels(
    pixels: dict[str, Any],
    *,
    region: dict[str, float] | None = None,
    grid_size: int = 8,
) -> dict[str, Any]:
    try:
        width = int(pixels["width"])
        height = int(pixels["height"])
        channels = int(pixels["channels"])
        rows = pixels["rows"]
        anchor_region = region or TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION
        x1 = max(0, min(width - 1, int(float(anchor_region["x1"]) * width)))
        x2 = max(x1 + 1, min(width, int(float(anchor_region["x2"]) * width)))
        y1 = max(0, min(height - 1, int(float(anchor_region["y1"]) * height)))
        y2 = max(y1 + 1, min(height, int(float(anchor_region["y2"]) * height)))
        values: list[float] = []
        for cell_y in range(grid_size):
            start_y = y1 + int((y2 - y1) * cell_y / grid_size)
            end_y = y1 + int((y2 - y1) * (cell_y + 1) / grid_size)
            for cell_x in range(grid_size):
                start_x = x1 + int((x2 - x1) * cell_x / grid_size)
                end_x = x1 + int((x2 - x1) * (cell_x + 1) / grid_size)
                total = 0.0
                count = 0
                for y in range(start_y, max(start_y + 1, end_y)):
                    row = rows[y]
                    for x in range(start_x, max(start_x + 1, end_x)):
                        offset = x * channels
                        r, g, b = row[offset : offset + 3]
                        total += (0.299 * int(r)) + (0.587 * int(g)) + (0.114 * int(b))
                        count += 1
                values.append(total / max(1, count))
        average = sum(values) / len(values)
        bits = "".join("1" if value >= average else "0" for value in values)
        return {
            "status": "ok",
            "visual_anchor_hash": f"{int(bits, 2):0{grid_size * grid_size // 4}x}",
            "grid_size": grid_size,
        }
    except Exception as exc:
        return {"status": "blocked", "reason": "target_binding_visual_anchor_hash_failed", "error": str(exc)[:80]}

def _visual_anchor_hamming_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        return max(len(left), len(right)) * 4
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return max(len(left), len(right)) * 4

def _verify_tashuo_chat_list_row_target_binding(
    session: Any,
    target_binding: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    spec = RowToThreadBindingSpec(
        app_id="tashuo",
        verification_method="tashuo_chat_list_row_to_thread_structural_binding",
        source_states=frozenset({"tashuo_chat_list"}),
        conversation_state="tashuo_conversation",
        window_missing_reason="mac_ios_app_window_not_found"
        if _is_mac_ios_app_session(session)
        else "iphone_mirroring_window_not_found",
        blocked_state_reasons={"tashuo_question_gate": "tashuo_question_gate_requires_user_confirmation"},
        visual_only_exact_verification_allowed=_is_mac_ios_app_session(session),
    )
    base = row_to_thread_base_result(target_binding, spec=spec)
    structural_block = validate_row_to_thread_structural_evidence(target_binding, spec=spec, base=base)
    if structural_block is not None:
        return structural_block
    window = session._window_info()
    if window is None:
        return {**base.to_dict(), "status": "blocked", **_tashuo_window_missing_payload(session)}
    output = output_dir / f"{_tashuo_capture_prefix(session)}.target_binding.png" if output_dir is not None else None
    screen = _capture_tashuo_window(session, output=output, window=window, ocr=not _is_mac_ios_app_session(session))
    observed_text = str(screen.get("text") or "")
    return finish_row_to_thread_screen_verification(
        base,
        screen=screen,
        redacted_screen=platform._redacted_screen(screen),
        observed_text=observed_text,
        spec=spec,
    )

def _tashuo_header_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    filtered: list[str] = []
    for line in lines[:5]:
        if any(marker in line for marker in ("开启通知", "点击此处输入文字", "发送")):
            continue
        filtered.append(line)
        if len(filtered) >= 2:
            break
    return "\n".join(filtered)

def _tashuo_marker_matches_text(text: str, marker: str) -> bool:
    normalized_marker = platform._normalize_text(marker)
    normalized_text = platform._normalize_text(text)
    if normalized_marker and normalized_marker in normalized_text:
        return True
    return _tashuo_cjk_marker_fuzzy_match(text, marker)

def _tashuo_cjk_marker_fuzzy_match(text: str, marker: str) -> bool:
    marker_key = platform._message_text_comparable(marker)
    text_key = platform._message_text_comparable(text)
    if not marker_key or not text_key:
        return False
    cjk_count = sum(1 for char in marker_key if "\u4e00" <= char <= "\u9fff")
    if len(marker_key) < 6 or cjk_count < 4 or cjk_count * 2 < len(marker_key):
        return False
    if len(text_key) + 2 < len(marker_key):
        return False
    if not any(marker_key[index : index + 3] in text_key for index in range(max(len(marker_key) - 2, 0))):
        return False

    max_distance = 1 if len(marker_key) < 9 else 2
    min_window = max(1, len(marker_key) - max_distance)
    max_window = len(marker_key) + max_distance
    for width in range(min_window, max_window + 1):
        if width > len(text_key):
            continue
        for start in range(0, len(text_key) - width + 1):
            if _bounded_edit_distance(marker_key, text_key[start : start + width], max_distance) <= max_distance:
                return True
    return False

def _bounded_edit_distance(left: str, right: str, limit: int) -> int:
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        row_min = current[0]
        for right_index, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            value = min(
                previous[right_index] + 1,
                current[right_index - 1] + 1,
                previous[right_index - 1] + cost,
            )
            current.append(value)
            row_min = min(row_min, value)
        if row_min > limit:
            return limit + 1
        previous = current
    return previous[-1]

__all__ = [name for name in globals() if not name.startswith("__")]
