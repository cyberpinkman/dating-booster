from __future__ import annotations

from dating_boost.apps.iphone_targeting_common import (
    annotations, hashlib, _platform, copy,
    csv, datetime, timezone, io,
    re, struct, sys, tempfile,
    time, zlib, Path, Any,
    uuid4, SubprocessRunner, WindowInfo, _parse_window_info,
    _short, _window_from_payload, _click_iphone_mirroring_view_menu_item_backend, _core_graphics_click_backend,
    _core_graphics_command_v_backend, _core_graphics_drag_backend, _core_graphics_wheel_backend, BUMBLE_FOREGROUND_STATES,
    TINDER_FOREGROUND_STATES, WECHAT_FOREGROUND_STATES, _bumble_layout_hints, _bumble_top_level_bottom_nav_present,
    classify_bumble_screen_text, classify_bumble_screen_image, classify_screen_image, classify_screen_text,
    classify_wechat_screen_text, _combine_bumble_screen_states, _combine_screen_states, _read_png_pixels_for_send_button,
    _region_stats_for_send_button, _redacted_screen, _tinder_layout_hints, _tinder_profile_danger_action_visible,
    _tinder_profile_expand_control_visible, _tinder_profile_field_coverage, _wechat_layout_hints, bumble_target_binding_specific_marker_present,
    target_binding_structural_evidence_present, _expected_text_observation_stats, _hash_text, _message_text_comparable,
    _message_text_matches, _normalize_text, _outbound_text_ocr_evidence, _staged_text_ocr_evidence,
    _staged_text_visual_verification_request, _text_fingerprint_fields, _harness_step_validation_reason, GUI_HARNESS_SCHEMA_VERSION,
    IPHONE_MIRRORING_HARNESS_BACKEND, MAC_IOS_APP_HARNESS_BACKEND, WECHAT_HARNESS_BACKEND, HARNESS_BACKEND,
    _contains_cjk_text, direct_text_entry_block_reason, NativeGuiHarness, _applescript_string_literal,
    _ensure_ascii_input_source, _switch_ascii_input_source, _read_current_input_source, _input_source_id_is_ascii,
    _app_search_result_visible, _default_screenshot_path, _now_iso, _parse_mac_ios_process_probe,
    _parse_core_graphics_window_info, _parse_mac_ios_active_application_probe, _swift_string_literal, _mac_ios_running_application_lookup_script,
    _mac_ios_core_graphics_window_lookup_script, _mac_ios_window_failure_reason, mac_ios_window_failure_payload, _contains_host_appleevents_unavailable_error,
    _host_appleevents_unavailable_diagnostic, _looks_like_iphone_mirroring_window, _looks_like_mac_ios_app_window, EvidencePayload,
    PostSendVerification, SendAttemptContext, StagingResult, BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
    IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE, TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION, _bumble_action_steps, _bumble_profile_field_coverage,
    _bumble_tap_step, _bumble_workflow_steps, _copy_tap_ratio, _has_bumble_step_postcondition,
    _has_bumble_step_precondition, _int_in_range, _launch_app_steps, _launch_tinder_steps,
    _message_list_visual_anchor_evidence_from_options, _normalized_visual_anchor_region, _redacted_iphone_prepare_message_page_payload, _redacted_message_list_visual_anchor_evidence,
    _redacted_target_binding, _target_binding_primary_visible_name, _target_binding_required_markers, _tap_ratio_option,
    _tap_step, _tinder_feedback_survey_dismiss_step, _tinder_action_steps, _tinder_subscription_paywall_dismiss_step,
    _tinder_workflow_steps, _verify_bumble_step_state, _visual_anchor_hamming_distance, harness_step_validation_reason,
    RowToThreadBindingSpec, finish_row_to_thread_screen_verification, row_to_thread_base_result, validate_row_to_thread_structural_evidence,
    target_binding_specific_marker_present, BLOCKED_GUI_ACTIONS, WECHAT_BLOCKED_GUI_ACTIONS, BUMBLE_BLOCKED_GUI_ACTIONS,
    BUMBLE_SEND_BLOCKED_GUI_ACTIONS, BUMBLE_OPENING_MOVE_POLICY, TINDER_SUBSCRIPTION_PAYWALL_STATE, TINDER_FEEDBACK_SURVEY_STATE,
    DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS, IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO, IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y, IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
    IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE, IPHONE_TARGET_RELOCATION_MAX_ATTEMPTS,
)


def _visible_text_contains_marker(observed_text: str, marker: str) -> bool:
    marker = marker.strip()
    if not marker:
        return False
    return _normalize_text(marker) in _normalize_text(observed_text) or _message_text_comparable(marker) in _message_text_comparable(observed_text)

def _recover_iphone_current_thread_visual_identity_mismatch(
    self,
    *,
    app_id: str,
    target_binding: dict[str, Any],
    target_verification: dict[str, Any] | None,
    output_dir: Path | None,
    chat_list_state: str,
    conversation_state: str,
    foreground_states: set[str],
    open_chats_step: dict[str, Any],
    return_to_chats_step: dict[str, Any],
    secondary_close_steps: dict[str, dict[str, Any]],
    guardrails: dict[str, Any],
    layout_hints_fn: Any,
    message_list_visual_anchor_scan_region: dict[str, float],
    blocked_state_reasons: dict[str, str],
    tap_intent: str,
    tap_x: float,
    tap_y_min: float,
    tap_y_max: float,
    output_prefix: str,
    verify_target_binding: Any,
    max_attempts: int = IPHONE_TARGET_RELOCATION_MAX_ATTEMPTS,
) -> dict[str, Any]:
    preflight = _iphone_visual_identity_relocation_preflight(
        app_id=app_id,
        target_binding=target_binding,
        target_verification=target_verification,
        message_list_visual_anchor_scan_region=message_list_visual_anchor_scan_region,
        max_attempts=max_attempts,
    )
    base = preflight["base"]
    if preflight.get("return_payload") is not None:
        return preflight["return_payload"]
    evidence = preflight["evidence"]

    return _run_iphone_visual_identity_relocation_attempts(
        self,
        base=base,
        evidence=evidence,
        context={
            "app_id": app_id,
            "target_binding": target_binding,
            "output_dir": output_dir,
            "chat_list_state": chat_list_state,
            "conversation_state": conversation_state,
            "foreground_states": foreground_states,
            "open_chats_step": open_chats_step,
            "return_to_chats_step": return_to_chats_step,
            "secondary_close_steps": secondary_close_steps,
            "guardrails": guardrails,
            "layout_hints_fn": layout_hints_fn,
            "message_list_visual_anchor_scan_region": message_list_visual_anchor_scan_region,
            "tap_intent": tap_intent,
            "tap_x": tap_x,
            "tap_y_min": tap_y_min,
            "tap_y_max": tap_y_max,
            "output_prefix": output_prefix,
            "verify_target_binding": verify_target_binding,
            "max_attempts": max_attempts,
        },
    )


def _iphone_visual_identity_relocation_preflight(
    *,
    app_id: str,
    target_binding: dict[str, Any],
    target_verification: dict[str, Any] | None,
    message_list_visual_anchor_scan_region: dict[str, float],
    max_attempts: int,
) -> dict[str, Any]:
    base = {
        "recovery_method": f"{app_id}_iphone_mirroring_message_list_visual_relocation",
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "attempt_limit": max_attempts,
        "requires_message_list_visual_evidence": True,
        "uses_fixed_row_index": False,
        "uses_header_ocr": False,
    }
    if target_binding.get("binding_type") != "current_thread_visual_identity":
        return {
            "base": base,
            "return_payload": {
                **base,
                "status": "blocked",
                "reason": (target_verification or {}).get("reason") or "target_binding_visual_identity_required",
                "recovery_skipped": True,
            },
        }
    if (target_verification or {}).get("reason") != "target_binding_visual_anchor_mismatch":
        return {
            "base": base,
            "return_payload": {
                **base,
                "status": "blocked",
                "reason": (target_verification or {}).get("reason") or "target_binding_mismatch",
                "recovery_skipped": True,
            },
        }

    evidence = _message_list_visual_anchor_evidence_from_options(
        {},
        target_binding=target_binding,
        default_scan_region=message_list_visual_anchor_scan_region,
        default_max_distance=IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE,
    )
    if evidence.get("status") != "ok":
        return {
            "base": base,
            "return_payload": {
                **base,
                **evidence,
                "status": "blocked",
                "reason": evidence.get("reason") or "target_relocation_visual_evidence_required",
            },
        }
    return {"base": base, "evidence": evidence}


def _run_iphone_visual_identity_relocation_attempts(
    self,
    *,
    base: dict[str, Any],
    evidence: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    max_attempts = int(context["max_attempts"])
    for attempt_index in range(1, max_attempts + 1):
        attempt_result = _run_iphone_visual_identity_relocation_attempt(
            self,
            attempt_index=attempt_index,
            app_id=context["app_id"],
            target_binding=context["target_binding"],
            output_dir=context["output_dir"],
            chat_list_state=context["chat_list_state"],
            conversation_state=context["conversation_state"],
            foreground_states=context["foreground_states"],
            open_chats_step=context["open_chats_step"],
            return_to_chats_step=context["return_to_chats_step"],
            secondary_close_steps=context["secondary_close_steps"],
            guardrails=context["guardrails"],
            layout_hints_fn=context["layout_hints_fn"],
            message_list_visual_anchor_scan_region=context["message_list_visual_anchor_scan_region"],
            tap_intent=context["tap_intent"],
            tap_x=context["tap_x"],
            tap_y_min=context["tap_y_min"],
            tap_y_max=context["tap_y_max"],
            output_prefix=context["output_prefix"],
            evidence=evidence,
            verify_target_binding=context["verify_target_binding"],
        )
        attempts.append(attempt_result["attempt"])
        blocked = _iphone_visual_identity_relocation_attempt_blocked_payload(
            base,
            attempt_result,
            attempts=attempts,
        )
        if blocked is not None:
            return blocked
        if attempt_result.get("retry"):
            if attempt_index < max_attempts:
                time.sleep(0.25)
                continue
            break
        verification = attempt_result["verification"]
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
    return _iphone_visual_identity_relocation_exhausted_payload(base, attempts)


def _iphone_visual_identity_relocation_attempt_blocked_payload(
    base: dict[str, Any],
    attempt_result: dict[str, Any],
    *,
    attempts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if attempt_result.get("retry"):
        return None
    if attempt_result.get("status") == "window_missing":
        return {**base, "status": "blocked", "reason": "iphone_mirroring_window_not_found", "attempts": attempts}
    if attempt_result.get("status") == "prepare_failed":
        prepare_payload = attempt_result["prepare_payload"]
        return {
            **base,
            "status": "blocked",
            "reason": prepare_payload.get("reason") or "target_relocation_message_list_not_verified",
            "attempts": attempts,
        }
    if attempt_result.get("status") == "tap_ratio_missing":
        return {
            **base,
            "status": "blocked",
            "reason": "target_relocation_tap_ratio_unavailable",
            "attempts": attempts,
        }
    if attempt_result.get("status") == "click_failed":
        click_result = attempt_result["click_result"]
        return {
            **base,
            "status": "blocked",
            "reason": click_result.get("reason") or "target_relocation_open_click_failed",
            "attempts": attempts,
        }
    return None


def _iphone_visual_identity_relocation_exhausted_payload(
    base: dict[str, Any],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        **base,
        "status": "blocked",
        "reason": "target_binding_visual_relocation_exhausted",
        "last_reason": (
            attempts[-1].get("target_binding_verification", {}).get("reason")
            if attempts and isinstance(attempts[-1].get("target_binding_verification"), dict)
            else attempts[-1].get("message_list_location", {}).get("reason")
            if attempts and isinstance(attempts[-1].get("message_list_location"), dict)
            else None
        ),
        "attempts": attempts,
    }


def _run_iphone_visual_identity_relocation_attempt(
    self,
    *,
    attempt_index: int,
    app_id: str,
    target_binding: dict[str, Any],
    output_dir: Path | None,
    chat_list_state: str,
    conversation_state: str,
    foreground_states: set[str],
    open_chats_step: dict[str, Any],
    return_to_chats_step: dict[str, Any],
    secondary_close_steps: dict[str, dict[str, Any]],
    guardrails: dict[str, Any],
    layout_hints_fn: Any,
    message_list_visual_anchor_scan_region: dict[str, float],
    tap_intent: str,
    tap_x: float,
    tap_y_min: float,
    tap_y_max: float,
    output_prefix: str,
    evidence: dict[str, Any],
    verify_target_binding: Any,
) -> dict[str, Any]:
    prepare_payload = self._prepare_iphone_message_page(
        {
            **self._base_payload("ok"),
            "action": "recover-target-binding",
            "mode": "execute",
            "attempt_index": attempt_index,
            **guardrails,
        },
        app_id=app_id,
        output_dir=output_dir,
        output_prefix=output_prefix,
        chat_list_state=chat_list_state,
        returnable_states={conversation_state},
        foreground_states=foreground_states,
        open_chats_step=open_chats_step,
        return_to_chats_step=return_to_chats_step,
        secondary_close_steps=secondary_close_steps,
        guardrails=guardrails,
        layout_hints_fn=layout_hints_fn,
        message_list_visual_anchor_scan_region=message_list_visual_anchor_scan_region,
    )
    attempt: dict[str, Any] = {
        "attempt_index": attempt_index,
        "message_list_recovery": _redacted_iphone_prepare_message_page_payload(prepare_payload),
    }
    if prepare_payload.get("status") != "ok":
        return {"status": "prepare_failed", "attempt": attempt, "prepare_payload": prepare_payload}

    window = self._window_info()
    if window is None:
        return {"status": "window_missing", "attempt": attempt}

    location = _locate_iphone_visual_identity_relocation_target(
        self,
        window=window,
        output_dir=output_dir,
        output_prefix=output_prefix,
        attempt_index=attempt_index,
        evidence=evidence,
        chat_list_state=chat_list_state,
        tap_x=tap_x,
        tap_y_min=tap_y_min,
        tap_y_max=tap_y_max,
    )
    attempt["message_list_location"] = location
    if location.get("status") != "ok":
        return {"status": "location_failed", "retry": True, "attempt": attempt}

    tap_step_result = _iphone_relocation_open_target_tap_step(
        app_id,
        location,
        tap_intent=tap_intent,
        chat_list_state=chat_list_state,
        conversation_state=conversation_state,
    )
    if tap_step_result.get("status") != "ok":
        return {"status": "tap_ratio_missing", "attempt": attempt}
    tap_step = tap_step_result["tap_step"]
    click_result = self._execute_step(window, tap_step)
    attempt["open_target_click"] = {**tap_step, "result": click_result}
    if click_result.get("status") != "ok":
        return {"status": "click_failed", "attempt": attempt, "click_result": click_result}
    time.sleep(float(tap_step.get("wait_after_seconds", 0.2)))

    verification = verify_target_binding(target_binding, output_dir=output_dir)
    attempt["target_binding_verification"] = verification
    return {"status": "verified" if verification.get("status") == "ok" else "verification_failed", "attempt": attempt, "verification": verification}


def _locate_iphone_visual_identity_relocation_target(
    self,
    *,
    window: Any,
    output_dir: Path | None,
    output_prefix: str,
    attempt_index: int,
    evidence: dict[str, Any],
    chat_list_state: str,
    tap_x: float,
    tap_y_min: float,
    tap_y_max: float,
) -> dict[str, Any]:
    list_output = output_dir / f"{output_prefix}.target_relocation_{attempt_index:02d}.message_list.png" if output_dir is not None else None
    list_screen = self.capture_window(output=list_output, window=window)
    return _locate_iphone_message_list_visual_anchor_target(
        list_screen,
        evidence,
        chat_list_state=chat_list_state,
        tap_x=tap_x,
        tap_y_min=tap_y_min,
        tap_y_max=tap_y_max,
    )


def _iphone_relocation_open_target_tap_step(
    app_id: str,
    location: dict[str, Any],
    *,
    tap_intent: str,
    chat_list_state: str,
    conversation_state: str,
) -> dict[str, Any]:
    tap_ratio = location.get("tap_ratio") if isinstance(location.get("tap_ratio"), dict) else None
    if tap_ratio is None:
        return {"status": "blocked", "reason": "target_relocation_tap_ratio_unavailable"}
    if app_id == "bumble":
        tap_step = {
            **_bumble_tap_step(
                tap_intent,
                x=float(tap_ratio["x"]),
                y=float(tap_ratio["y"]),
                requires_states=chat_list_state,
                expected_states=conversation_state,
            ),
            "location_method": location.get("location_method"),
            "message_list_location": location,
        }
    else:
        tap_step = {
            **_tap_step(tap_intent, x=float(tap_ratio["x"]), y=float(tap_ratio["y"])),
            "location_method": location.get("location_method"),
            "message_list_location": location,
        }
    return {"status": "ok", "tap_step": tap_step}


def _verify_iphone_current_thread_visual_identity(
    self,
    *,
    app_id: str,
    target_binding: dict[str, Any],
    output_dir: Path | None,
    conversation_state: str,
    blocked_state_reasons: dict[str, str],
    output_name: str,
    verification_method: str,
) -> dict[str, Any]:
    thread_evidence = (
        target_binding.get("thread_evidence")
        if isinstance(target_binding.get("thread_evidence"), dict)
        else {}
    )
    expected_visual_hash = str(thread_evidence.get("visual_anchor_hash") or "").strip()
    visual_region = _normalized_visual_anchor_region(
        thread_evidence.get("visual_anchor_region"),
        fallback=IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
    ) or dict(IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION)
    max_distance = _int_in_range(
        thread_evidence.get("visual_anchor_max_hamming_distance"),
        default=IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE,
        minimum=0,
        maximum=32,
    )
    base = {
        "verification_method": verification_method,
        "binding_type": target_binding.get("binding_type"),
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "conversation_fingerprint_hash": _hash_text(str(target_binding.get("conversation_fingerprint") or "")),
        "pre_action_observation_id": thread_evidence.get("observation_id"),
        "latest_inbound_fingerprint_hash": _hash_text(str(thread_evidence.get("latest_inbound_fingerprint") or "")),
        "expected_visual_anchor_hash": expected_visual_hash or None,
        "visual_anchor_region": visual_region,
        "visual_anchor_max_hamming_distance": max_distance,
        "requires_visual_anchor": True,
        "requires_header_marker": False,
        "requires_fresh_conversation_screen": True,
        "uses_header_ocr": False,
        "visual_only_exact_verification_allowed": False,
    }
    if not target_binding_structural_evidence_present(app_id, target_binding):
        return {**base, "status": "blocked", "reason": "target_binding_structural_evidence_required"}
    window = self._window_info()
    if window is None:
        return {**base, "status": "blocked", "reason": "iphone_mirroring_window_not_found"}
    output = output_dir / output_name if output_dir is not None else None
    screen = self.capture_window(output=output, window=window)
    screen_path = str(screen.get("path") or "")
    if screen_path:
        try:
            visual_hash_result = _iphone_visual_anchor_hash_for_pixels(
                _read_png_pixels_for_send_button(Path(screen_path)),
                region=visual_region,
            )
        except Exception as exc:
            visual_hash_result = {
                "status": "blocked",
                "reason": "target_binding_visual_anchor_read_failed",
                "error": str(exc)[:80],
            }
    else:
        visual_hash_result = {"status": "blocked", "reason": "target_binding_screen_path_missing"}
    observed_visual_hash = str(visual_hash_result.get("visual_anchor_hash") or "")
    visual_distance = (
        _visual_anchor_hamming_distance(expected_visual_hash, observed_visual_hash)
        if expected_visual_hash and observed_visual_hash
        else None
    )
    result = {
        **base,
        "screen": _redacted_screen(screen),
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
    blocked_reason = blocked_state_reasons.get(str(screen.get("state") or ""))
    if blocked_reason:
        return {**result, "status": "blocked", "reason": blocked_reason}
    if screen.get("state") != conversation_state:
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


def _verify_chat_list_row_target_binding(
    self,
    *,
    app_id: str,
    target_binding: dict[str, Any],
    output_dir: Path | None,
    source_states: set[str],
    conversation_state: str,
    blocked_state_reasons: dict[str, str],
    output_name: str,
    verification_method: str,
) -> dict[str, Any]:
    spec = RowToThreadBindingSpec(
        app_id=app_id,
        verification_method=verification_method,
        source_states=frozenset(source_states),
        conversation_state=conversation_state,
        window_missing_reason="iphone_mirroring_window_not_found",
        blocked_state_reasons=dict(blocked_state_reasons),
    )
    base = row_to_thread_base_result(target_binding, spec=spec)
    structural_block = validate_row_to_thread_structural_evidence(target_binding, spec=spec, base=base)
    if structural_block is not None:
        return structural_block
    window = self._window_info()
    if window is None:
        return base.with_status("blocked", spec.window_missing_reason)
    output = output_dir / output_name if output_dir is not None else None
    screen = self.capture_window(output=output, window=window)
    observed_text = str(screen.get("text") or "")
    return finish_row_to_thread_screen_verification(
        base,
        screen=screen,
        redacted_screen=_redacted_screen(screen),
        observed_text=observed_text,
        spec=spec,
    )


def _locate_iphone_message_list_visual_anchor_target(
    list_screen: dict[str, Any],
    evidence: dict[str, Any],
    *,
    chat_list_state: str,
    tap_x: float,
    tap_y_min: float,
    tap_y_max: float,
) -> dict[str, Any]:
    setup = _iphone_message_list_visual_anchor_scan_setup(
        list_screen,
        evidence,
        chat_list_state=chat_list_state,
    )
    if setup.get("status") != "ok":
        return setup
    scan_result = _scan_iphone_message_list_visual_anchor_candidates(setup)
    best = scan_result["best"]
    candidate_count = scan_result["candidate_count"]
    if best is None:
        return {
            "status": "blocked",
            "reason": "target_relocation_visual_anchor_unavailable",
            "candidate_count": candidate_count,
        }
    max_distance = setup["max_distance"]
    expected_hash = setup["expected_hash"]
    if int(best["visual_anchor_hamming_distance"]) > max_distance:
        return {
            **best,
            "status": "blocked",
            "reason": "target_relocation_visual_anchor_not_found",
            "expected_visual_anchor_hash": expected_hash,
            "visual_anchor_max_hamming_distance": max_distance,
            "candidate_count": candidate_count,
        }
    return _finish_iphone_message_list_visual_anchor_location(
        best,
        setup,
        tap_x=tap_x,
        tap_y_min=tap_y_min,
        tap_y_max=tap_y_max,
        candidate_count=candidate_count,
    )


def _iphone_message_list_visual_anchor_scan_setup(
    list_screen: dict[str, Any],
    evidence: dict[str, Any],
    *,
    chat_list_state: str,
) -> dict[str, Any]:
    if list_screen.get("status") != "ok":
        return {"status": "blocked", "reason": list_screen.get("reason") or "target_relocation_message_list_not_captured"}
    if list_screen.get("state") != chat_list_state:
        return {
            "status": "blocked",
            "reason": "target_relocation_message_list_not_verified",
            "screen_state": list_screen.get("state", "unknown"),
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
        screen_pixels = _read_png_pixels_for_send_button(Path(path))
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": "target_binding_visual_anchor_read_failed",
            "error": str(exc)[:80],
        }

    row_height = max(0.03, min(0.28, float(source_region["y2"]) - float(source_region["y1"])))
    row_width = max(0.05, min(1.0, float(source_region["x2"]) - float(source_region["x1"])))
    tap_ratio = evidence.get("tap_ratio") if isinstance(evidence.get("tap_ratio"), dict) else None
    tap_y_offset = 0.5
    prior_tap_y: float | None = None
    if tap_ratio is not None:
        tap_y_offset = (float(tap_ratio["y"]) - float(source_region["y1"])) / row_height
        prior_tap_y = max(0.0, min(1.0, float(tap_ratio["y"])))
    return {
        "status": "ok",
        "screen_pixels": screen_pixels,
        "expected_hash": expected_hash,
        "row_height": row_height,
        "row_width": row_width,
        "scan_y1": max(0.0, min(1.0 - row_height, float(scan_region["y1"]))),
        "scan_y2": max(max(0.0, min(1.0 - row_height, float(scan_region["y1"]))) + row_height, min(1.0, float(scan_region["y2"]))),
        "source_x1": max(0.0, min(1.0 - row_width, float(source_region["x1"]))),
        "tap_ratio": tap_ratio,
        "tap_y_offset": max(0.05, min(0.95, tap_y_offset)),
        "prior_tap_y": prior_tap_y,
        "max_distance": int(evidence.get("visual_anchor_max_hamming_distance") or IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE),
    }


def _scan_iphone_message_list_visual_anchor_candidates(setup: dict[str, Any]) -> dict[str, Any]:
    screen_pixels = setup["screen_pixels"]
    expected_hash = setup["expected_hash"]
    row_height = setup["row_height"]
    source_x1 = setup["source_x1"]
    source_x2 = source_x1 + setup["row_width"]
    scan_y1 = setup["scan_y1"]
    scan_y2 = setup["scan_y2"]
    tap_y_offset = setup["tap_y_offset"]
    prior_tap_y = setup["prior_tap_y"]
    step_y = max(0.004, min(0.012, row_height / 12.0))
    best: dict[str, Any] | None = None
    candidate_count = 0
    y = scan_y1
    while y <= scan_y2 - row_height + 0.0001:
        region = {"x1": source_x1, "y1": y, "x2": source_x2, "y2": y + row_height}
        hash_result = _iphone_visual_anchor_hash_for_pixels(screen_pixels, region=region)
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
    return {"best": best, "candidate_count": candidate_count}


def _finish_iphone_message_list_visual_anchor_location(
    best: dict[str, Any],
    setup: dict[str, Any],
    *,
    tap_x: float,
    tap_y_min: float,
    tap_y_max: float,
    candidate_count: int,
) -> dict[str, Any]:
    row_height = setup["row_height"]
    tap_y_offset = setup["tap_y_offset"]
    tap_ratio = setup["tap_ratio"]
    matched_region = best["visual_anchor_region"]
    raw_tap_ratio = {
        "x": max(0.0, min(1.0, float(tap_ratio["x"]) if tap_ratio is not None else tap_x)),
        "y": max(0.0, min(1.0, float(matched_region["y1"]) + row_height * tap_y_offset)),
    }
    safe_tap = _safe_iphone_message_list_visual_anchor_tap_ratio(
        raw_tap_ratio,
        matched_region=matched_region,
        tap_y_min=tap_y_min,
        tap_y_max=tap_y_max,
    )
    return {
        **best,
        "status": "ok",
        "location_method": "message_list_visual_anchor_scan",
        "expected_visual_anchor_hash": setup["expected_hash"],
        "visual_anchor_max_hamming_distance": setup["max_distance"],
        "candidate_count": candidate_count,
        "tap_ratio": safe_tap["tap_ratio"],
        "raw_tap_ratio": raw_tap_ratio,
        "tap_adjustment": safe_tap["tap_adjustment"],
        "uses_fixed_row_index": False,
        "visual_anchor_scanned": True,
    }


def _safe_iphone_message_list_visual_anchor_tap_ratio(
    tap_ratio: dict[str, float],
    *,
    matched_region: dict[str, Any],
    tap_y_min: float,
    tap_y_max: float,
) -> dict[str, Any]:
    tap_y = max(0.0, min(1.0, float(tap_ratio["y"])))
    try:
        region_y1 = float(matched_region["y1"])
        region_y2 = float(matched_region["y2"])
    except (KeyError, TypeError, ValueError):
        region_y1 = tap_y
        region_y2 = tap_y
    reasons: list[str] = []
    bottom_row = region_y2 >= IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO or tap_y >= tap_y_max
    if bottom_row:
        safe_y = min(tap_y, tap_y_max, IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y)
        if safe_y < tap_y:
            tap_y = safe_y
            reasons.append("bottom_row_safe_tap_guard")
    else:
        tap_y = max(tap_y_min, min(tap_y_max, tap_y))
    if tap_y >= IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO:
        safe_y = min(tap_y, IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y)
        if safe_y < tap_y:
            tap_y = safe_y
            reasons.append("bottom_nav_overlap_guard")
    if tap_y < tap_y_min:
        tap_y = tap_y_min
        reasons.append("row_top_safe_tap_guard")
    return {
        "tap_ratio": {
            "x": max(0.0, min(1.0, float(tap_ratio["x"]))),
            "y": round(tap_y, 4),
        },
        "tap_adjustment": {
            "adjusted": bool(reasons),
            "reason": "+".join(reasons) if reasons else None,
            "bottom_nav_top_ratio": IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO,
            "bottom_row_safe_tap_y": IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y,
            "bottom_row_detected": bottom_row,
            "matched_region_y2": region_y2,
        },
    }


def _iphone_visual_anchor_hash_for_pixels(
    pixels: dict[str, Any],
    *,
    region: dict[str, float],
    grid_size: int = 8,
) -> dict[str, Any]:
    try:
        width = int(pixels["width"])
        height = int(pixels["height"])
        channels = int(pixels["channels"])
        rows = pixels["rows"]
        x1 = max(0, min(width - 1, int(float(region["x1"]) * width)))
        x2 = max(x1 + 1, min(width, int(float(region["x2"]) * width)))
        y1 = max(0, min(height - 1, int(float(region["y1"]) * height)))
        y2 = max(y1 + 1, min(height, int(float(region["y2"]) * height)))
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


def _iphone_visual_anchor_hash_for_path(
    path: Path,
    *,
    region: dict[str, float],
    grid_size: int = 8,
) -> dict[str, Any]:
    try:
        pixels = _read_png_pixels_for_send_button(path)
    except Exception as exc:
        return {"status": "blocked", "reason": "target_binding_visual_anchor_read_failed", "error": str(exc)[:80]}
    return _iphone_visual_anchor_hash_for_pixels(pixels, region=region, grid_size=grid_size)


def _iphone_current_thread_visual_anchor(
    screen: dict[str, Any],
    *,
    conversation_state: str,
    region: dict[str, float] | None = None,
) -> dict[str, Any]:
    anchor_region = region or dict(IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION)
    base = {
        "screen_state": screen.get("state", "unknown"),
        "visual_state": screen.get("visual_state", "unknown"),
        "visual_anchor_region": anchor_region,
        "uses_header_ocr": False,
    }
    if screen.get("status") != "ok":
        return {**base, "status": "blocked", "reason": screen.get("reason") or "screen_not_captured"}
    if screen.get("state") != conversation_state:
        return {**base, "status": "blocked", "reason": f"{conversation_state}_not_verified"}
    screen_path = str(screen.get("path") or "")
    if not screen_path:
        return {**base, "status": "blocked", "reason": "target_binding_screen_path_missing"}
    return {
        **base,
        **_iphone_visual_anchor_hash_for_path(Path(screen_path), region=anchor_region),
    }


def _verify_open_conversation_target_binding_against_screen(
    app_id: str,
    target_binding: dict[str, Any] | None,
    screen: dict[str, Any],
    *,
    fallback_marker: str,
    verification_method: str,
    conversation_state: str,
    source_states: set[str],
    blocked_state_reasons: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(target_binding, dict):
        return {
            "verification_method": verification_method,
            "status": "blocked",
            "reason": "target_binding_required",
            "screen": _redacted_screen(screen),
            "screen_state": screen.get("state", "unknown"),
        }
    if target_binding.get("binding_type") == "chat_list_row_to_thread":
        spec = RowToThreadBindingSpec(
            app_id=app_id,
            verification_method=f"{verification_method}_structural_binding",
            source_states=frozenset(source_states),
            conversation_state=conversation_state,
            window_missing_reason="iphone_mirroring_window_not_found",
            blocked_state_reasons=dict(blocked_state_reasons),
        )
        base = row_to_thread_base_result(target_binding, spec=spec)
        structural_block = validate_row_to_thread_structural_evidence(target_binding, spec=spec, base=base)
        if structural_block is not None:
            return structural_block
        return finish_row_to_thread_screen_verification(
            base,
            screen=screen,
            redacted_screen=_redacted_screen(screen),
            observed_text=str(screen.get("text") or ""),
            spec=spec,
        )
    return _verify_target_binding_against_screen(
        target_binding,
        screen,
        fallback_marker=fallback_marker,
        verification_method=verification_method,
        conversation_state=conversation_state,
        blocked_state_reasons=blocked_state_reasons,
    )


def _verify_target_binding_against_screen(
    target_binding: dict[str, Any] | None,
    screen: dict[str, Any],
    *,
    fallback_marker: str,
    verification_method: str,
    conversation_state: str = "tinder_conversation",
    blocked_state_reasons: dict[str, str] | None = None,
) -> dict[str, Any]:
    markers = _target_binding_required_markers(target_binding or {})
    if not markers and fallback_marker.strip():
        markers = [fallback_marker.strip()]
    observed_text = str(screen.get("text") or "")
    matched = [marker for marker in markers if _visible_text_contains_marker(observed_text, marker)]
    result = {
        "verification_method": verification_method,
        "target_match_id": target_binding.get("target_match_id") if isinstance(target_binding, dict) else None,
        "candidate_key": target_binding.get("candidate_key") if isinstance(target_binding, dict) else None,
        "required_marker_hashes": [_hash_text(marker) for marker in markers],
        "matched_marker_hashes": [_hash_text(marker) for marker in matched],
        "screen": _redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "observed_text_hash": _hash_text(observed_text) if observed_text else None,
    }
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "target_binding_screen_capture_failed"}
    blocked_reason = (blocked_state_reasons or {}).get(str(screen.get("state") or ""))
    if blocked_reason:
        return {**result, "status": "blocked", "reason": blocked_reason}
    if screen.get("state") != conversation_state:
        return {**result, "status": "blocked", "reason": "target_binding_chat_not_verified"}
    if not markers:
        return {**result, "status": "blocked", "reason": "target_binding_required"}
    if len(matched) != len(markers):
        return {**result, "status": "blocked", "reason": "target_binding_mismatch"}
    return {**result, "status": "ok"}


__all__ = [
    'annotations', 'hashlib', '_platform', 'copy',
    'csv', 'datetime', 'timezone', 'io',
    're', 'struct', 'sys', 'tempfile',
    'time', 'zlib', 'Path', 'Any',
    'uuid4', 'SubprocessRunner', 'WindowInfo', '_parse_window_info',
    '_short', '_window_from_payload', '_click_iphone_mirroring_view_menu_item_backend', '_core_graphics_click_backend',
    '_core_graphics_command_v_backend', '_core_graphics_drag_backend', '_core_graphics_wheel_backend', 'BUMBLE_FOREGROUND_STATES',
    'TINDER_FOREGROUND_STATES', 'WECHAT_FOREGROUND_STATES', '_bumble_layout_hints', '_bumble_top_level_bottom_nav_present',
    'classify_bumble_screen_text', 'classify_bumble_screen_image', 'classify_screen_image', 'classify_screen_text',
    'classify_wechat_screen_text', '_combine_bumble_screen_states', '_combine_screen_states', '_read_png_pixels_for_send_button',
    '_region_stats_for_send_button', '_redacted_screen', '_tinder_layout_hints', '_tinder_profile_danger_action_visible',
    '_tinder_profile_expand_control_visible', '_tinder_profile_field_coverage', '_wechat_layout_hints', 'bumble_target_binding_specific_marker_present',
    'target_binding_structural_evidence_present', '_expected_text_observation_stats', '_hash_text', '_message_text_comparable',
    '_message_text_matches', '_normalize_text', '_outbound_text_ocr_evidence', '_staged_text_ocr_evidence',
    '_staged_text_visual_verification_request', '_text_fingerprint_fields', '_harness_step_validation_reason', 'GUI_HARNESS_SCHEMA_VERSION',
    'IPHONE_MIRRORING_HARNESS_BACKEND', 'MAC_IOS_APP_HARNESS_BACKEND', 'WECHAT_HARNESS_BACKEND', 'HARNESS_BACKEND',
    '_contains_cjk_text', 'direct_text_entry_block_reason', 'NativeGuiHarness', '_applescript_string_literal',
    '_ensure_ascii_input_source', '_switch_ascii_input_source', '_read_current_input_source', '_input_source_id_is_ascii',
    '_app_search_result_visible', '_default_screenshot_path', '_now_iso', '_parse_mac_ios_process_probe',
    '_parse_core_graphics_window_info', '_parse_mac_ios_active_application_probe', '_swift_string_literal', '_mac_ios_running_application_lookup_script',
    '_mac_ios_core_graphics_window_lookup_script', '_mac_ios_window_failure_reason', 'mac_ios_window_failure_payload', '_contains_host_appleevents_unavailable_error',
    '_host_appleevents_unavailable_diagnostic', '_looks_like_iphone_mirroring_window', '_looks_like_mac_ios_app_window', 'EvidencePayload',
    'PostSendVerification', 'SendAttemptContext', 'StagingResult', 'BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION',
    'IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE', 'TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION', '_bumble_action_steps', '_bumble_profile_field_coverage',
    '_bumble_tap_step', '_bumble_workflow_steps', '_copy_tap_ratio', '_has_bumble_step_postcondition',
    '_has_bumble_step_precondition', '_int_in_range', '_launch_app_steps', '_launch_tinder_steps',
    '_message_list_visual_anchor_evidence_from_options', '_normalized_visual_anchor_region', '_redacted_iphone_prepare_message_page_payload', '_redacted_message_list_visual_anchor_evidence',
    '_redacted_target_binding', '_target_binding_primary_visible_name', '_target_binding_required_markers', '_tap_ratio_option',
    '_tap_step', '_tinder_feedback_survey_dismiss_step', '_tinder_action_steps', '_tinder_subscription_paywall_dismiss_step',
    '_tinder_workflow_steps', '_verify_bumble_step_state', '_visual_anchor_hamming_distance', 'harness_step_validation_reason',
    'RowToThreadBindingSpec', 'finish_row_to_thread_screen_verification', 'row_to_thread_base_result', 'validate_row_to_thread_structural_evidence',
    'target_binding_specific_marker_present', 'BLOCKED_GUI_ACTIONS', 'WECHAT_BLOCKED_GUI_ACTIONS', 'BUMBLE_BLOCKED_GUI_ACTIONS',
    'BUMBLE_SEND_BLOCKED_GUI_ACTIONS', 'BUMBLE_OPENING_MOVE_POLICY', 'TINDER_SUBSCRIPTION_PAYWALL_STATE', 'TINDER_FEEDBACK_SURVEY_STATE',
    'DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS', 'IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO', 'IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y', 'IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION',
    'IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE', 'IPHONE_TARGET_RELOCATION_MAX_ATTEMPTS', '_visible_text_contains_marker', '_recover_iphone_current_thread_visual_identity_mismatch',
    '_iphone_visual_identity_relocation_preflight', '_run_iphone_visual_identity_relocation_attempts', '_iphone_visual_identity_relocation_attempt_blocked_payload', '_iphone_visual_identity_relocation_exhausted_payload',
    '_run_iphone_visual_identity_relocation_attempt', '_locate_iphone_visual_identity_relocation_target', '_iphone_relocation_open_target_tap_step', '_verify_iphone_current_thread_visual_identity',
    '_verify_chat_list_row_target_binding', '_locate_iphone_message_list_visual_anchor_target', '_iphone_message_list_visual_anchor_scan_setup', '_scan_iphone_message_list_visual_anchor_candidates',
    '_finish_iphone_message_list_visual_anchor_location', '_safe_iphone_message_list_visual_anchor_tap_ratio', '_iphone_visual_anchor_hash_for_pixels', '_iphone_visual_anchor_hash_for_path',
    '_iphone_current_thread_visual_anchor', '_verify_open_conversation_target_binding_against_screen', '_verify_target_binding_against_screen',
]
