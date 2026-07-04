from __future__ import annotations

from .runtime_common import *
from .send_input_ax import *

def _verify_staged_tashuo_message_with_crop_ocr(
    session: Any,
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
    output_dir: Path | None = None,
    label: str = "tashuo.input_crop",
) -> dict[str, Any]:
    ax_value = _tashuo_ax_text_area_value(session) if _is_mac_ios_app_session(session) else None
    ocr_disabled_after_message_page = _is_mac_ios_app_session(session)
    result = _verify_staged_tashuo_message(
        screen,
        expected_text,
        baseline_screen=baseline_screen,
        trusted_direct_input=trusted_direct_input,
        ax_text_area_value=ax_value,
        ocr_disabled_after_message_page=ocr_disabled_after_message_page,
    )
    if result.get("status") == "ok" or screen.get("status") != "ok":
        return result
    if ocr_disabled_after_message_page:
        return {
            **result,
            "ocr_fallback_skipped": True,
            "ocr_fallback_skip_reason": "mac_ios_app_visual_first_after_message_page",
        }
    crop_ocr = _tashuo_input_crop_ocr(
        session,
        screen,
        expected_text=expected_text,
        output_dir=output_dir,
        label=label,
    )
    return _verify_staged_tashuo_message(
        screen,
        expected_text,
        baseline_screen=baseline_screen,
        trusted_direct_input=trusted_direct_input,
        input_crop_ocr=crop_ocr,
        ax_text_area_value=ax_value,
        ocr_disabled_after_message_page=False,
    )


def _verify_staged_tashuo_message(
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
    input_crop_ocr: dict[str, Any] | None = None,
    ax_text_area_value: dict[str, Any] | None = None,
    ocr_disabled_after_message_page: bool = False,
) -> dict[str, Any]:
    observed_text = "" if ocr_disabled_after_message_page else str(screen.get("text") or "")
    crop_text = (
        str(input_crop_ocr.get("text") or "")
        if not ocr_disabled_after_message_page
        and isinstance(input_crop_ocr, dict)
        and input_crop_ocr.get("status") == "ok"
        else ""
    )
    combined_text = "\n".join(item for item in (observed_text, crop_text) if item)
    observed_stats = platform._expected_text_observation_stats(combined_text or observed_text, expected_text)
    baseline_text = (
        ""
        if ocr_disabled_after_message_page
        else str(baseline_screen.get("text") or "") if isinstance(baseline_screen, dict) else ""
    )
    baseline_stats = platform._expected_text_observation_stats(baseline_text, expected_text) if baseline_text else None
    screen_exact = platform._message_text_matches(observed_text, expected_text)
    crop_exact = bool(crop_text) and platform._message_text_matches(crop_text, expected_text)
    ax_text = (
        str(ax_text_area_value.get("value") or "")
        if isinstance(ax_text_area_value, dict) and ax_text_area_value.get("status") == "ok"
        else ""
    )
    ax_exact = bool(ax_text) and platform._message_text_matches(ax_text, expected_text)
    result = platform._staged_text_ocr_evidence(
        verification_method=(
            "tashuo_staged_message_ax_then_host_visual_payload_text"
            if ocr_disabled_after_message_page
            else "tashuo_staged_message_ax_then_ocr_payload_text"
        ),
        observed_text=combined_text or observed_text,
        expected_text=expected_text,
        baseline_text=baseline_text,
        screen=screen,
        redact_screen=platform._redacted_screen,
        exact_text_ocr_verified=screen_exact or crop_exact,
        extra={
            "ocr_disabled_after_message_page": ocr_disabled_after_message_page,
            "send_action": "press_return",
            "exact_text_ax_verified": ax_exact,
            "ax_text_area_value_hash": platform._hash_text(ax_text) if ax_text else None,
            "ax_text_area_character_count": len(ax_text) if ax_text else 0,
            "screen_exact_text_ocr_verified": screen_exact,
            "input_crop_exact_text_ocr_verified": crop_exact,
        },
    )
    possible_append_to_existing = (
        bool(baseline_stats)
        and int(baseline_stats.get("expected_text_occurrences") or 0) > 0
        and int(observed_stats.get("text_character_count") or 0)
        > int(baseline_stats.get("text_character_count") or 0) + max(4, len(expected_text) // 3)
    )
    result["possible_append_to_existing_staged_text"] = possible_append_to_existing
    if ax_text_area_value is not None and ax_text_area_value.get("status") != "ok":
        result["ax_text_area_status"] = ax_text_area_value.get("status")
        result["ax_text_area_reason"] = ax_text_area_value.get("reason")
    if input_crop_ocr is not None and not ocr_disabled_after_message_page:
        result["input_crop_ocr"] = _redacted_tashuo_input_crop_ocr(input_crop_ocr, expected_text)
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "stage_screen_not_captured"}
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return {**result, "status": "blocked", "reason": screen.get("state")}
    if screen.get("state") == "tashuo_question_gate":
        return {**result, "status": "blocked", "reason": "tashuo_question_gate_requires_user_confirmation"}
    baseline_state = baseline_screen.get("state") if isinstance(baseline_screen, dict) else None
    if screen.get("state") != "tashuo_conversation" and baseline_state != "tashuo_conversation":
        return {**result, "status": "blocked", "reason": "tashuo_conversation_not_verified"}
    if not (result["exact_text_ocr_verified"] or result["exact_text_ax_verified"]):
        return {**result, "status": "needs_verification", "reason": "staged_text_not_verified"}
    if possible_append_to_existing and not trusted_direct_input and not result["exact_text_ax_verified"]:
        return {**result, "status": "needs_verification", "reason": "staged_text_may_have_been_appended"}
    if not result["exact_text_ax_verified"] and baseline_stats and observed_stats["expected_text_occurrences"] <= baseline_stats["expected_text_occurrences"]:
        if trusted_direct_input:
            return {**result, "status": "ok"}
        return {**result, "status": "needs_verification", "reason": "staged_text_not_newly_visible"}
    return {**result, "status": "ok"}


def _tashuo_input_crop_ocr(
    session: Any,
    screen: dict[str, Any],
    *,
    expected_text: str,
    output_dir: Path | None,
    label: str,
) -> dict[str, Any]:
    screen_path = str(screen.get("path") or "")
    if not screen_path:
        return {"status": "blocked", "reason": "input_crop_screen_path_missing"}
    source = Path(screen_path)
    try:
        pixels = _read_png_pixels(source)
        width = int(pixels["width"])
        height = int(pixels["height"])
    except Exception as exc:
        return {"status": "blocked", "reason": "input_crop_dimensions_unavailable", "error": str(exc)[:80]}
    region = dict(TASHUO_MAC_IOS_APP_INPUT_OCR_REGION)
    x = max(0, min(width - 1, int(region["x1"] * width)))
    y = max(0, min(height - 1, int(region["y1"] * height)))
    crop_width = max(1, min(width - x, int((region["x2"] - region["x1"]) * width)))
    crop_height = max(1, min(height - y, int((region["y2"] - region["y1"]) * height)))
    base_dir = output_dir if output_dir is not None else source.parent
    base_dir.mkdir(parents=True, exist_ok=True)
    crop_path = base_dir / f"{label}.png"
    resized_path = base_dir / f"{label}.2x.png"
    crop = session.runner.run(
        [
            "sips",
            "--cropToHeightWidth",
            str(crop_height),
            str(crop_width),
            "--cropOffset",
            str(y),
            str(x),
            str(source),
            "--out",
            str(crop_path),
        ]
    )
    if crop.returncode != 0:
        return {"status": "blocked", "reason": "input_crop_failed", "stderr": platform._short(crop.stderr)}
    resize = session.runner.run(
        [
            "sips",
            "--resampleWidth",
            str(crop_width * 2),
            str(crop_path),
            "--out",
            str(resized_path),
        ]
    )
    if resize.returncode != 0:
        return {"status": "blocked", "reason": "input_crop_resize_failed", "stderr": platform._short(resize.stderr)}
    best: dict[str, Any] | None = None
    for psm in ("6", "11"):
        ocr = session.runner.run(
            [
                "tesseract",
                str(resized_path),
                "stdout",
                "-l",
                "chi_sim+eng",
                "--psm",
                psm,
            ]
        )
        item = {
            "status": "ok" if ocr.returncode == 0 else "blocked",
            "reason": None if ocr.returncode == 0 else "input_crop_ocr_failed",
            "text": ocr.stdout if ocr.returncode == 0 else "",
            "stderr": platform._short(ocr.stderr) if ocr.returncode != 0 else None,
            "psm": psm,
            "path": str(crop_path),
            "resized_path": str(resized_path),
            "region": region,
        }
        best = item
        if item["status"] == "ok" and platform._message_text_matches(str(item.get("text") or ""), expected_text):
            return item
    return best or {"status": "blocked", "reason": "input_crop_ocr_not_run"}


def _redacted_tashuo_input_crop_ocr(payload: dict[str, Any], expected_text: str) -> dict[str, Any]:
    text = str(payload.get("text") or "")
    stats = platform._expected_text_observation_stats(text, expected_text) if text else {}
    return {
        "status": payload.get("status"),
        "reason": payload.get("reason"),
        "psm": payload.get("psm"),
        "path": payload.get("path"),
        "resized_path": payload.get("resized_path"),
        "region": payload.get("region"),
        "text_hash": stats.get("text_hash"),
        "text_character_count": stats.get("text_character_count"),
        "expected_text_occurrences": stats.get("expected_text_occurrences", 0),
        "exact_text_ocr_verified": bool(text) and platform._message_text_matches(text, expected_text),
        "stderr": payload.get("stderr"),
    }


def _tashuo_host_visual_staged_verification_available(
    screen: dict[str, Any],
    staged_verification: dict[str, Any],
    expected_text: str,
) -> bool:
    if screen.get("status") != "ok" or not screen.get("path"):
        return False
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt", "tashuo_question_gate"}:
        return False
    observed_text = str(screen.get("text") or "")
    if _tashuo_input_placeholder_visible(observed_text):
        return False
    if _tashuo_obvious_wrong_staged_text_visible(observed_text, expected_text):
        return False
    crop_ocr = staged_verification.get("input_crop_ocr")
    return not isinstance(crop_ocr, dict) or crop_ocr.get("status") in {None, "ok", "blocked"}


def _tashuo_obvious_wrong_staged_text_visible(observed_text: str, expected_text: str) -> bool:
    if platform._message_text_matches(observed_text, expected_text):
        return False
    normalized_lines = [line.strip().lower() for line in observed_text.splitlines() if line.strip()]
    if any(line in {"v", "发送v", "v发送"} for line in normalized_lines):
        return True
    comparable = platform._message_text_comparable(observed_text)
    expected = platform._message_text_comparable(expected_text)
    if expected and expected in comparable:
        return False
    return comparable.endswith("v发送") or comparable.endswith("vsend")


def _tashuo_visual_staged_verification_request(
    screen: dict[str, Any],
    staged_verification: dict[str, Any],
    expected_text: str,
) -> dict[str, Any]:
    crop_ocr = staged_verification.get("input_crop_ocr")
    crop = crop_ocr if isinstance(crop_ocr, dict) else {}
    return platform._staged_text_visual_verification_request(
        screen=screen,
        staged_verification=staged_verification,
        expected_text=expected_text,
        extra={
            "input_crop_path": crop.get("path"),
            "input_crop_resized_path": crop.get("resized_path"),
            "input_crop_region": crop.get("region") or TASHUO_MAC_IOS_APP_INPUT_OCR_REGION,
            "ocr_status": "skipped" if staged_verification.get("ocr_disabled_after_message_page") else crop.get("status"),
            "ocr_text_hash": None if staged_verification.get("ocr_disabled_after_message_page") else crop.get("text_hash"),
            "ocr_text_character_count": None
            if staged_verification.get("ocr_disabled_after_message_page")
            else crop.get("text_character_count"),
        },
        instructions="Use visual inspection of the screenshot to compare the staged input with the expected payload held by the current action request. Do not use OCR and do not press Return unless the visual comparison is exact.",
    )


def _tashuo_host_visual_outbound_verification_available(
    post_screen: dict[str, Any],
    outbound_verification: dict[str, Any],
    expected_text: str,
    *,
    staged_exact_text_verified: bool,
    input_cleared: bool,
) -> bool:
    if not expected_text.strip():
        return False
    if staged_exact_text_verified is not True or input_cleared is not True:
        return False
    if post_screen.get("status") != "ok" or not post_screen.get("path"):
        return False
    if post_screen.get("state") != "tashuo_conversation":
        return False
    if outbound_verification.get("exact_text_ax_verified") is True:
        return False
    return True


def _tashuo_visual_outbound_verification_request(
    staged_screen: dict[str, Any] | None,
    post_screen: dict[str, Any],
    outbound_verification: dict[str, Any],
    expected_text: str,
    *,
    post_action_observation_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "verification_type": "outbound_message_visual",
        "status": "needs_host_visual_verification",
        "expected_payload_hash": platform._hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "staged_screen_path": staged_screen.get("path") if isinstance(staged_screen, dict) else None,
        "post_screen_path": post_screen.get("path"),
        "screen_state": post_screen.get("state"),
        "post_action_observation_id": post_action_observation_id,
        "input_cleared_after_send": bool(outbound_verification.get("input_cleared_after_send")),
        "staged_exact_text_verified": bool(outbound_verification.get("staged_exact_text_verified")),
        "outbound_visual_region": dict(TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION),
        "ocr_status": "skipped",
        "next_host_action": "visually_verify_outbound_message_after_live_send",
        "instructions": "Use visual inspection of the post-send screenshot to confirm the latest outbound bubble exactly matches the current action request payload. Do not use OCR; if the screenshot does not visibly confirm the sent text, record unknown rather than succeeded.",
    }


def _stage_only_tashuo_verification(
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
    first_screen: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
    ax_text_area_value: dict[str, Any] | None = None,
) -> dict[str, Any]:
    low_level = _verify_staged_tashuo_message(
        screen,
        expected_text,
        baseline_screen=baseline_screen,
        trusted_direct_input=trusted_direct_input,
        ax_text_area_value=ax_text_area_value,
        ocr_disabled_after_message_page=bool(ax_text_area_value is not None),
    )
    observed_text = str(screen.get("text") or "")
    baseline_text = str(baseline_screen.get("text") or "") if isinstance(baseline_screen, dict) else ""
    first_text = str(first_screen.get("text") or "") if isinstance(first_screen, dict) else ""
    placeholder_visible = _tashuo_input_placeholder_visible(observed_text)
    baseline_placeholder_visible = _tashuo_input_placeholder_visible(baseline_text)
    first_placeholder_visible = _tashuo_input_placeholder_visible(first_text)
    evidence = {
        **low_level,
        "placeholder_visible": placeholder_visible,
        "baseline_placeholder_visible": baseline_placeholder_visible,
        "first_capture_placeholder_visible": first_placeholder_visible,
        "screen_text_character_count": len(observed_text),
        "baseline_text_character_count": len(baseline_text),
        "first_screen_text_character_count": len(first_text),
        "trusted_direct_input": trusted_direct_input,
    }
    if low_level.get("status") == "ok":
        return {**evidence, "status": "verified"}
    if low_level.get("status") == "blocked":
        return {**evidence, "status": "failed"}
    if placeholder_visible:
        return {**evidence, "status": "failed", "reason": low_level.get("reason") or "staged_text_not_visible"}
    if len(observed_text) > len(baseline_text) or (baseline_placeholder_visible and not placeholder_visible):
        return {
            **evidence,
            "status": "needs_user_verification",
            "reason": low_level.get("reason") or "cjk_exact_text_not_automatically_verified",
        }
    return {
        **evidence,
        "status": "needs_user_verification",
        "reason": low_level.get("reason") or "stage_result_ambiguous",
    }


def _verify_tashuo_outbound_message(
    screen: dict[str, Any],
    expected_text: str,
    *,
    staged_screen: dict[str, Any] | None = None,
    ax_static_text_values: dict[str, Any] | None = None,
    ax_text_area_value: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
    staged_exact_text_verified: bool = False,
    visual_commit_allowed: bool = False,
    ocr_disabled_after_message_page: bool = False,
) -> dict[str, Any]:
    result = (
        {
            "verification_method": "tashuo_post_send_ax_then_host_visual_payload_text",
            "expected_payload_hash": platform._hash_text(expected_text),
            "expected_character_count": len(expected_text),
            "observed_text_hash": platform._hash_text(""),
            "observed_character_count": 0,
            "status": "needs_verification",
            "reason": "post_send_requires_visual_verification",
        }
        if ocr_disabled_after_message_page
        else platform._verify_outbound_message(screen, expected_text)
    )
    observed_text = "" if ocr_disabled_after_message_page else str(screen.get("text") or "")
    staged_text = (
        ""
        if ocr_disabled_after_message_page
        else str(staged_screen.get("text") or "") if isinstance(staged_screen, dict) else ""
    )
    observed_stats = platform._expected_text_observation_stats(observed_text, expected_text)
    staged_stats = platform._expected_text_observation_stats(staged_text, expected_text) if staged_text else None
    ax_values = (
        [str(item) for item in ax_static_text_values.get("values", []) if str(item).strip()]
        if isinstance(ax_static_text_values, dict) and isinstance(ax_static_text_values.get("values"), list)
        else []
    )
    ax_text = "\n".join(ax_values)
    ax_stats = platform._expected_text_observation_stats(ax_text, expected_text) if ax_text else None
    ax_text_area = (
        str(ax_text_area_value.get("value") or "")
        if isinstance(ax_text_area_value, dict) and ax_text_area_value.get("status") == "ok"
        else None
    )
    input_cleared = (
        ax_text_area.strip() == ""
        if ax_text_area is not None
        else _tashuo_input_placeholder_visible(observed_text)
    )
    outgoing_bubble_visible = _tashuo_outgoing_bubble_visual_visible(screen)
    staged_outgoing_bubble_visible = (
        _tashuo_outgoing_bubble_visual_visible(staged_screen) if isinstance(staged_screen, dict) else False
    )
    exact_text_ocr_verified = False if ocr_disabled_after_message_page else result.get("status") == "ok"
    exact_text_ax_verified = bool(ax_text) and platform._message_text_matches(ax_text, expected_text)
    visual_commit = (
        _tashuo_outbound_visual_commit_verification(
            staged_screen,
            screen,
            input_cleared=input_cleared,
            staged_exact_text_verified=staged_exact_text_verified,
        )
        if visual_commit_allowed
        else {
            "status": "not_applicable",
            "reason": "visual_commit_not_allowed_for_runtime",
            "visual_only_exact_verification_allowed": False,
            "requires_ocr": True,
        }
    )
    exact_text_visual_verified = False
    exact_text_verified = exact_text_ocr_verified or exact_text_ax_verified
    extra = {
        "verification_method": (
            "tashuo_post_send_ax_then_host_visual_payload_text"
            if ocr_disabled_after_message_page
            else "tashuo_post_send_ax_static_text_then_ocr_payload_text"
            if ax_static_text_values is not None
            else "tashuo_post_send_ocr_payload_text_delta"
        ),
        "ocr_disabled_after_message_page": ocr_disabled_after_message_page,
        "observed_expected_text_occurrences": observed_stats["expected_text_occurrences"],
        "staged_expected_text_occurrences": staged_stats["expected_text_occurrences"] if staged_stats else None,
        "staged_text_hash": staged_stats["text_hash"] if staged_stats else None,
        "ax_static_text_status": ax_static_text_values.get("status") if isinstance(ax_static_text_values, dict) else None,
        "ax_static_text_count": ax_static_text_values.get("value_count") if isinstance(ax_static_text_values, dict) else None,
        "ax_expected_text_occurrences": ax_stats["expected_text_occurrences"] if ax_stats else None,
        "ax_text_hash": ax_stats["text_hash"] if ax_stats else None,
        "ax_text_area_status": ax_text_area_value.get("status") if isinstance(ax_text_area_value, dict) else None,
        "ax_text_area_value_hash": platform._hash_text(ax_text_area) if ax_text_area else None,
        "input_cleared_after_send": input_cleared,
        "outgoing_bubble_visual_visible": outgoing_bubble_visible,
        "staged_outgoing_bubble_visual_visible": staged_outgoing_bubble_visible,
        "visual_delta_diagnostics": visual_commit,
        "visual_commit_verification": visual_commit,
        "visual_commit_verified": False,
        "send_action": "press_return",
        "staged_exact_text_verified": staged_exact_text_verified,
        "exact_text_verified": exact_text_verified,
        "exact_text_ax_verified": exact_text_ax_verified,
        "exact_text_ocr_verified": exact_text_ocr_verified,
        "exact_text_visual_verified": exact_text_visual_verified,
        "visual_only_exact_verification_allowed": visual_commit_allowed,
    }
    if screen.get("state") != "tashuo_conversation":
        return {**result, **extra, "status": "needs_verification", "reason": "tashuo_conversation_not_verified"}
    if input_cleared is not True:
        return {**result, **extra, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    if exact_text_verified is not True:
        return {**result, **extra, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    return {**result, **extra, "status": "ok"}


def _tashuo_input_placeholder_visible(text: str) -> bool:
    normalized = platform._normalize_text(text)
    return "点击此处输入文字" in normalized or "输入文字" in normalized


def _cleanup_failed_tashuo_stage(
    session: Any,
    window: Any,
    input_step: dict[str, Any],
    *,
    expected_text: str,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    input_tap_ratio = _copy_tap_ratio(input_step["tap_ratio"])
    input_focus_state = str(input_step.get("focus_state") or "unknown")
    click_result = session._click_ratio(window, input_step["tap_ratio"])
    attempts.append({
        "intent": "refocus_tashuo_message_input_for_failed_stage_cleanup",
        "tap_ratio": input_tap_ratio,
        "focus_state": input_focus_state,
        "result": click_result,
    })
    if click_result.get("status") != "ok":
        return {
            "status": "blocked",
            "reason": click_result.get("reason") or "failed_stage_cleanup_refocus_failed",
            "input_tap_ratio": input_tap_ratio,
            "input_focus_state": input_focus_state,
            "attempts": attempts,
        }

    if _is_mac_ios_app_session(session):
        ax_clear_result = _clear_tashuo_ax_text_area(session)
        attempts.append({"intent": "clear_tashuo_text_area_for_failed_stage_cleanup", "result": ax_clear_result})
        if ax_clear_result.get("status") == "ok":
            time.sleep(0.2)
            output = output_dir / f"{_tashuo_capture_prefix(session)}.after_failed_stage_cleanup.png" if output_dir is not None else None
            screen = _capture_tashuo_window(session, output=output, window=window, ocr=not _is_mac_ios_app_session(session))
            ax_value = _tashuo_ax_text_area_value(session)
            ax_text = (
                str(ax_value.get("value") or "")
                if isinstance(ax_value, dict) and ax_value.get("status") == "ok"
                else ""
            )
            expected_still_visible = bool(ax_text) and platform._message_text_matches(ax_text, expected_text)
            input_placeholder_visible = ax_text.strip() == ""
            result = {
                "attempts": attempts,
                "input_tap_ratio": input_tap_ratio,
                "input_focus_state": input_focus_state,
                "screen": platform._redacted_screen(screen),
                "expected_payload_hash": platform._hash_text(expected_text),
                "expected_text_still_visible": expected_still_visible,
                "input_placeholder_visible": input_placeholder_visible,
                "cleanup_backend": "macos_accessibility",
                "ax_text_area_status": ax_value.get("status") if isinstance(ax_value, dict) else None,
                "ax_text_area_value_hash": platform._hash_text(ax_text) if ax_text else None,
            }
            if screen.get("status") != "ok":
                return {**result, "status": "needs_verification", "reason": "failed_stage_cleanup_screen_not_captured"}
            if not expected_still_visible and input_placeholder_visible:
                return {**result, "status": "ok"}

    escape_result = session._press_escape_key()
    attempts.append({"intent": "cancel_tashuo_input_candidate_for_failed_stage_cleanup", "result": escape_result})
    backspace_count = min(40, max(4, len(expected_text) + 4))
    for index in range(backspace_count):
        backspace_result = session._press_backspace_key()
        attempts.append({
            "intent": "backspace_tashuo_failed_stage_text",
            "index": index,
            "result": backspace_result,
        })
        if backspace_result.get("status") != "ok":
            return {
                "status": "blocked",
                "reason": backspace_result.get("reason") or "failed_stage_cleanup_backspace_failed",
                "attempts": attempts,
            }
    time.sleep(0.2)
    output = output_dir / f"{_tashuo_capture_prefix(session)}.after_failed_stage_cleanup.png" if output_dir is not None else None
    screen = _capture_tashuo_window(session, output=output, window=window, ocr=not _is_mac_ios_app_session(session))
    observed_text = str(screen.get("text") or "")
    expected_still_visible = platform._message_text_matches(observed_text, expected_text)
    input_placeholder_visible = _tashuo_input_placeholder_visible(observed_text)
    result = {
        "attempts": attempts,
        "input_tap_ratio": input_tap_ratio,
        "input_focus_state": input_focus_state,
        "screen": platform._redacted_screen(screen),
        "expected_payload_hash": platform._hash_text(expected_text),
        "expected_text_still_visible": expected_still_visible,
        "input_placeholder_visible": input_placeholder_visible,
    }
    if screen.get("status") != "ok":
        return {**result, "status": "needs_verification", "reason": "failed_stage_cleanup_screen_not_captured"}
    if expected_still_visible or not input_placeholder_visible:
        return {**result, "status": "needs_verification", "reason": "failed_stage_cleanup_not_verified"}
    return {**result, "status": "ok"}


def _tashuo_outgoing_bubble_visual_visible(screen: dict[str, Any] | None) -> bool:
    if not isinstance(screen, dict):
        return False
    region = TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION
    stats = platform._screen_region_stats(screen, region["x1"], region["y1"], region["x2"], region["y2"])
    if stats is None:
        return False
    return (
        stats["bright_ratio"] > 0.70
        and (
            stats["color_ratio"] > 0.030
            or (stats["color_ratio"] > 0.002 and stats["mid_ratio"] > 0.025)
        )
    )


def _tashuo_outbound_visual_commit_verification(
    staged_screen: dict[str, Any] | None,
    post_screen: dict[str, Any],
    *,
    input_cleared: bool,
    staged_exact_text_verified: bool,
) -> dict[str, Any]:
    base = {
        "verification_method": "tashuo_mac_ios_app_visual_commit_after_exact_stage",
        "staged_exact_text_verified": staged_exact_text_verified,
        "input_cleared_after_send": input_cleared,
        "visual_only_exact_verification_allowed": TASHUO_MAC_IOS_APP_VISUAL_EXACT_VERIFICATION_ALLOWED,
        "visual_region": dict(TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION),
        "requires_ocr": False,
    }
    if not staged_exact_text_verified:
        return {**base, "status": "needs_verification", "reason": "staged_exact_text_not_verified"}
    if input_cleared is not True:
        return {**base, "status": "needs_verification", "reason": "post_send_input_not_clear"}
    if post_screen.get("status") != "ok":
        return {**base, "status": "needs_verification", "reason": post_screen.get("reason") or "post_action_screen_not_captured"}
    if post_screen.get("state") != "tashuo_conversation":
        return {**base, "status": "needs_verification", "reason": "tashuo_conversation_not_verified"}
    if not _tashuo_outgoing_bubble_visual_visible(post_screen):
        return {**base, "status": "needs_verification", "reason": "outgoing_bubble_visual_not_visible"}

    delta = _tashuo_screen_region_visual_delta(
        staged_screen,
        post_screen,
        TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION,
    )
    if delta.get("status") != "ok":
        return {**base, **delta, "status": "needs_verification", "reason": delta.get("reason") or "visual_delta_unavailable"}
    changed_ratio = float(delta.get("changed_pixel_ratio") or 0.0)
    average_delta = float(delta.get("average_channel_delta") or 0.0)
    if (
        changed_ratio < TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_CHANGED_RATIO
        or average_delta < TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_AVERAGE_DELTA
    ):
        return {
            **base,
            **delta,
            "status": "needs_verification",
            "reason": "outgoing_bubble_visual_delta_too_small",
            "min_changed_pixel_ratio": TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_CHANGED_RATIO,
            "min_average_channel_delta": TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_AVERAGE_DELTA,
        }
    return {**base, **delta, "status": "ok"}


def _tashuo_screen_region_visual_delta(
    before_screen: dict[str, Any] | None,
    after_screen: dict[str, Any],
    region: dict[str, float],
) -> dict[str, Any]:
    if not isinstance(before_screen, dict):
        return {"status": "blocked", "reason": "before_screen_missing"}
    before_path = str(before_screen.get("path") or "")
    after_path = str(after_screen.get("path") or "")
    if not before_path or not after_path:
        return {"status": "blocked", "reason": "visual_delta_screen_path_missing"}
    try:
        before_pixels = _read_png_pixels(Path(before_path))
        after_pixels = _read_png_pixels(Path(after_path))
    except Exception as exc:
        return {"status": "blocked", "reason": "visual_delta_read_failed", "error": str(exc)[:80]}
    try:
        before_width = int(before_pixels["width"])
        before_height = int(before_pixels["height"])
        after_width = int(after_pixels["width"])
        after_height = int(after_pixels["height"])
        before_channels = int(before_pixels["channels"])
        after_channels = int(after_pixels["channels"])
        if before_width != after_width or before_height != after_height:
            return {
                "status": "blocked",
                "reason": "visual_delta_size_mismatch",
                "before_size": [before_width, before_height],
                "after_size": [after_width, after_height],
            }
        x1 = max(0, min(before_width - 1, int(float(region["x1"]) * before_width)))
        x2 = max(x1 + 1, min(before_width, int(float(region["x2"]) * before_width)))
        y1 = max(0, min(before_height - 1, int(float(region["y1"]) * before_height)))
        y2 = max(y1 + 1, min(before_height, int(float(region["y2"]) * before_height)))
        changed_pixels = 0
        total_pixels = 0
        total_delta = 0.0
        for y in range(y1, y2):
            before_row = before_pixels["rows"][y]
            after_row = after_pixels["rows"][y]
            for x in range(x1, x2):
                before_offset = x * before_channels
                after_offset = x * after_channels
                before_rgb = before_row[before_offset : before_offset + 3]
                after_rgb = after_row[after_offset : after_offset + 3]
                delta = sum(abs(int(after_rgb[index]) - int(before_rgb[index])) for index in range(3)) / 3.0
                total_delta += delta
                total_pixels += 1
                if delta >= 10.0:
                    changed_pixels += 1
        return {
            "status": "ok",
            "changed_pixel_ratio": changed_pixels / max(1, total_pixels),
            "average_channel_delta": total_delta / max(1, total_pixels),
            "visual_region": dict(region),
        }
    except Exception as exc:
        return {"status": "blocked", "reason": "visual_delta_failed", "error": str(exc)[:80]}


__all__ = [name for name in globals() if not name.startswith("__")]
