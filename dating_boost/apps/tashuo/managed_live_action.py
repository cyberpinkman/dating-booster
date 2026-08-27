from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from dating_boost.apps.tashuo.runtime_common import (
    _capture_tashuo_window,
    _is_mac_ios_app_session,
    _sleep_for_tashuo_post_action_observation,
    _tashuo_capture_prefix,
    _tashuo_message_input_tap_ratio,
    platform,
    target_binding_structural_evidence_present,
)
from dating_boost.apps.tashuo.send_input_ax import (
    _guarded_clear_tashuo_ax_text_area_if_exact,
    _guarded_set_tashuo_ax_text_area_if_empty,
    _tashuo_ax_conversation_snapshot,
    _tashuo_ax_static_text_values,
    _tashuo_ax_text_area_value,
)
from dating_boost.apps.tashuo.send_verification import _verify_tashuo_outbound_message
from dating_boost.apps.tashuo.targeting import _verify_tashuo_target_binding


def observe_tashuo_managed_inbound_revision(
    session: Any,
    *,
    target_binding: dict[str, Any],
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Bind a redacted AX conversation revision to a fresh target observation."""

    context = _observe_bound_target(
        session,
        action="observe_managed_inbound_revision",
        target_binding=target_binding,
        output_dir=output_dir,
    )
    if context.get("status") != "ok":
        return context
    revision = _observe_current_conversation_revision(session)
    if revision.get("status") != "ok":
        return {
            **context,
            "status": "blocked",
            "reason": revision.get("reason") or "managed_inbound_revision_unavailable",
            "inbound_revision_evidence": revision,
        }
    return {
        **context,
        "inbound_revision": revision["inbound_revision"],
        "inbound_revision_observation_id": revision["observation_id"],
        "inbound_revision_captured_at": revision["captured_at"],
        "inbound_revision_evidence": _public_revision_evidence(revision),
    }


def observe_tashuo_managed_composer(
    session: Any,
    *,
    target_binding: dict[str, Any],
    inbound_revision: str,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Observe a bound composer without staging or sending anything."""

    context = _observe_bound_conversation(
        session,
        action="observe_managed_composer",
        target_binding=target_binding,
        inbound_revision=inbound_revision,
        output_dir=output_dir,
    )
    if context.get("status") != "ok":
        return context
    composer = _tashuo_ax_text_area_value(session)
    if composer.get("status") != "ok":
        return _blocked(
            "managed_composer_exact_text_unavailable",
            action="observe_managed_composer",
            inbound_revision=inbound_revision,
            target_binding_hash=context["target_binding_hash"],
            composer_observation=composer,
        )
    captured_at = platform._now_iso()
    return {
        **context,
        "composer_text": str(composer.get("value") or ""),
        "composer_text_hash": platform._hash_text(str(composer.get("value") or "")),
        "composer_character_count": len(str(composer.get("value") or "")),
        "captured_at": captured_at,
        "observation_id": _observation_id("composer", captured_at),
    }


def stage_tashuo_managed_text(
    session: Any,
    draft_text: str,
    *,
    target_binding: dict[str, Any],
    inbound_revision: str,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Atomically set an empty AX composer and prove the exact resulting text."""

    if not draft_text:
        return _blocked("managed_stage_text_empty", action="stage_managed_text")
    context = _observe_bound_conversation(
        session,
        action="stage_managed_text",
        target_binding=target_binding,
        inbound_revision=inbound_revision,
        output_dir=output_dir,
    )
    if context.get("status") != "ok":
        return context

    staged = _guarded_set_tashuo_ax_text_area_if_empty(session, draft_text)
    if staged.get("status") != "ok":
        return {
            **context,
            "status": "blocked",
            "reason": staged.get("reason") or "managed_stage_failed",
            "staging": staged,
        }

    # The target check after staging protects against a manual/app navigation
    # race between the first visual binding check and the atomic AX write.  If
    # it fails, clear only our exact text and never leave it in an unknown chat.
    target_recheck = _verify_tashuo_target_binding(session, target_binding, output_dir=output_dir)
    if target_recheck.get("status") != "ok":
        cleanup = _guarded_clear_tashuo_ax_text_area_if_exact(session, draft_text)
        return {
            **context,
            "status": "blocked",
            "reason": target_recheck.get("reason") or "managed_target_binding_changed_during_stage",
            "target_binding_recheck": target_recheck,
            "exact_stage_cleanup": cleanup,
        }

    post_stage = _observe_matching_conversation_revision(
        session,
        action="stage_managed_text",
        target_binding=target_binding,
        inbound_revision=inbound_revision,
        expected_composer_text=draft_text,
    )
    if post_stage.get("status") != "ok" or post_stage.get("composer_exact_match") is not True:
        cleanup = _guarded_clear_tashuo_ax_text_area_if_exact(session, draft_text)
        return {
            **context,
            **post_stage,
            "status": "blocked",
            "reason": (
                str(post_stage.get("reason"))
                if post_stage.get("status") != "ok"
                else "managed_staged_text_exact_mismatch"
            ),
            "staging": staged,
            "target_binding_recheck": target_recheck,
            "exact_stage_cleanup": cleanup,
        }

    return {
        **context,
        **post_stage,
        "status": "ok",
        "staging": staged,
        "target_binding_recheck": target_recheck,
        "staged_text_verified": True,
        "staged_exact_text_ax_verified": True,
        "post_stage_inbound_revision_verified": True,
        "expected_payload_hash": platform._hash_text(draft_text),
        "expected_character_count": len(draft_text),
        "captured_at": post_stage["inbound_revision_captured_at"],
        "observation_id": _observation_id("stage", str(post_stage["inbound_revision_captured_at"])),
    }


def click_tashuo_managed_send_only(
    session: Any,
    expected_text: str,
    *,
    target_binding: dict[str, Any],
    inbound_revision: str,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Press Return only after fresh target and exact-composer verification.

    This boundary never writes or repairs composer text.  A mismatch blocks the
    irreversible action and leaves the current composer untouched.
    """

    if not expected_text:
        return _blocked("managed_click_expected_text_empty", action="click_managed_send_only")
    context = _observe_bound_conversation(
        session,
        action="click_managed_send_only",
        target_binding=target_binding,
        inbound_revision=inbound_revision,
        output_dir=output_dir,
        expected_text_for_occurrences=expected_text,
        expected_composer_text=expected_text,
    )
    if context.get("status") != "ok":
        return context
    if (
        context.get("composer_observation_status") != "ok"
        or context.get("composer_exact_match") is not True
    ):
        return {
            **context,
            "status": "blocked",
            "reason": "managed_pre_click_composer_exact_mismatch",
        }

    window = context["_window"]
    focus_result = session._click_ratio(window, _tashuo_message_input_tap_ratio(session, focused=True))
    if focus_result.get("status") != "ok":
        return {
            **context,
            "status": "blocked",
            "reason": focus_result.get("reason") or "managed_composer_focus_failed",
            "focus_result": focus_result,
        }
    after_focus = _tashuo_ax_text_area_value(session)
    if after_focus.get("status") != "ok" or str(after_focus.get("value") or "") != expected_text:
        return {
            **context,
            "status": "blocked",
            "reason": "managed_pre_click_composer_changed_after_focus",
            "composer_observation": after_focus,
        }
    prefix = _tashuo_capture_prefix(session)
    pre_click_screen = context["target_binding_verification"].get("screen")
    if not isinstance(pre_click_screen, dict) or not pre_click_screen.get("path"):
        pre_click_path = output_dir / f"{prefix}.managed.before_return.png" if output_dir is not None else None
        pre_click_screen = _capture_tashuo_window(
            session,
            output=pre_click_path,
            window=window,
            ocr=False,
        )
    if pre_click_screen.get("status") != "ok" or pre_click_screen.get("state") != "tashuo_conversation":
        return {
            **context,
            "status": "blocked",
            "reason": pre_click_screen.get("reason") or "managed_pre_click_screen_not_verified",
        }
    before_occurrences_raw = context.get("pre_click_expected_text_occurrences")
    if not isinstance(before_occurrences_raw, int) or before_occurrences_raw < 0:
        return {
            **context,
            "status": "blocked",
            "reason": "managed_pre_click_occurrence_baseline_missing",
        }
    before_occurrences = before_occurrences_raw

    send_result = session._press_return_key()
    if send_result.get("status") != "ok":
        return {
            **context,
            "status": "unknown",
            "reason": send_result.get("reason") or "managed_return_result_unknown",
            "send_result": send_result,
        }
    clicked_at = platform._now_iso()
    receipt_id = "tashuo_managed_click_" + uuid4().hex
    return {
        **context,
        "status": "ok",
        "action": "click_managed_send_only",
        "receipt_id": receipt_id,
        "clicked_at": clicked_at,
        "expected_payload_hash": platform._hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "pre_click_expected_text_occurrences": before_occurrences,
        "send_result": send_result,
        "_pre_click_screen": pre_click_screen,
    }


def observe_tashuo_managed_post_send(
    session: Any,
    expected_text: str,
    *,
    target_binding: dict[str, Any],
    inbound_revision: str,
    click_receipt: dict[str, Any],
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Capture fresh post-Return evidence without performing another action."""

    receipt_reason = _receipt_block_reason(click_receipt, expected_text, target_binding)
    if receipt_reason is not None:
        return _blocked(receipt_reason, action="observe_managed_post_send")
    if not _is_mac_ios_app_session(session):
        return _blocked("managed_tashuo_requires_mac_ios_app", action="observe_managed_post_send")

    _sleep_for_tashuo_post_action_observation(session, fallback=0.5)
    prefix = _tashuo_capture_prefix(session)
    pre_click_screen = click_receipt.get("_pre_click_screen")
    if not isinstance(pre_click_screen, dict):
        return _blocked("managed_click_receipt_evidence_missing", action="observe_managed_post_send")
    window = session._window_info()
    if window is None:
        return _blocked("managed_tashuo_window_not_found", action="observe_managed_post_send")
    post_path = output_dir / f"{prefix}.managed.after_return.png" if output_dir is not None else None
    post_screen = _capture_tashuo_window(session, output=post_path, window=window, ocr=False)
    post_static = _tashuo_ax_static_text_values(session)
    post_composer = _tashuo_ax_text_area_value(session)
    verification = _verify_tashuo_outbound_message(
        post_screen,
        expected_text,
        staged_screen=pre_click_screen,
        ax_static_text_values=post_static,
        ax_text_area_value=post_composer,
        staged_exact_text_verified=True,
        visual_commit_allowed=False,
        ocr_disabled_after_message_page=True,
    )
    before_occurrences = int(click_receipt.get("pre_click_expected_text_occurrences") or 0)
    after_occurrences = _expected_occurrences(post_static, expected_text)
    fresh_exact_text = after_occurrences > before_occurrences
    captured_at = platform._now_iso()
    clicked_at = str(click_receipt.get("clicked_at") or "")
    fresh_capture = _iso_strictly_after(captured_at, clicked_at)
    input_cleared = bool(verification.get("input_cleared_after_send"))
    exact_ax = bool(verification.get("exact_text_ax_verified"))
    if not (
        post_screen.get("status") == "ok"
        and post_screen.get("state") == "tashuo_conversation"
        and verification.get("status") == "ok"
        and input_cleared
        and exact_ax
        and fresh_exact_text
        and fresh_capture
    ):
        return {
            "schema_version": 1,
            "status": "unknown",
            "reason": _post_send_unknown_reason(
                post_screen=post_screen,
                verification=verification,
                fresh_exact_text=fresh_exact_text,
                fresh_capture=fresh_capture,
            ),
            "action": "observe_managed_post_send",
            "app_id": "tashuo",
            "runtime": "mac-ios-app",
            "receipt_id": click_receipt["receipt_id"],
            "target_binding_hash": _binding_hash(target_binding),
            "inbound_revision": inbound_revision,
            "captured_at": captured_at,
            "input_cleared": input_cleared,
            "outbound_exact_text_ax_verified": exact_ax,
            "fresh_outbound_occurrence_verified": fresh_exact_text,
            "pre_click_expected_text_occurrences": before_occurrences,
            "post_click_expected_text_occurrences": after_occurrences,
            "post_send_verification": verification,
        }
    observation_id = _observation_id("post_send", captured_at)
    return {
        "schema_version": 1,
        "status": "ok",
        "action": "observe_managed_post_send",
        "app_id": "tashuo",
        "runtime": "mac-ios-app",
        "receipt_id": click_receipt["receipt_id"],
        "target_binding_hash": _binding_hash(target_binding),
        "inbound_revision": inbound_revision,
        "captured_at": captured_at,
        "post_action_observation_id": observation_id,
        "input_cleared": True,
        "outbound_exact_text_ax_verified": True,
        "fresh_outbound_occurrence_verified": True,
        "pre_click_expected_text_occurrences": before_occurrences,
        "post_click_expected_text_occurrences": after_occurrences,
        "post_send_verification": verification,
        "expected_payload_hash": platform._hash_text(expected_text),
    }


def _observe_bound_conversation(
    session: Any,
    *,
    action: str,
    target_binding: dict[str, Any],
    inbound_revision: str,
    output_dir: Path | None,
    expected_text_for_occurrences: str | None = None,
    expected_composer_text: str | None = None,
) -> dict[str, Any]:
    if not inbound_revision:
        return _blocked("managed_inbound_revision_missing", action=action)
    bound_revision = _bound_managed_inbound_revision(target_binding)
    if not bound_revision:
        return _blocked("managed_inbound_revision_binding_missing", action=action)
    if bound_revision != inbound_revision:
        return _blocked("managed_inbound_revision_binding_mismatch", action=action)
    context = _observe_bound_target(
        session,
        action=action,
        target_binding=target_binding,
        output_dir=output_dir,
    )
    if context.get("status") != "ok":
        return context
    revision = _observe_matching_conversation_revision(
        session,
        action=action,
        target_binding=target_binding,
        inbound_revision=inbound_revision,
        expected_text_for_occurrences=expected_text_for_occurrences,
        expected_composer_text=expected_composer_text,
    )
    return {**context, **revision}


def _observe_matching_conversation_revision(
    session: Any,
    *,
    action: str,
    target_binding: dict[str, Any],
    inbound_revision: str,
    expected_text_for_occurrences: str | None = None,
    expected_composer_text: str | None = None,
) -> dict[str, Any]:
    revision = _observe_current_conversation_revision(
        session,
        expected_text_for_occurrences=expected_text_for_occurrences,
        expected_composer_text=expected_composer_text,
    )
    if revision.get("status") != "ok":
        return {
            "status": "blocked",
            "action": action,
            "reason": revision.get("reason") or "managed_inbound_revision_unavailable",
            "inbound_revision_evidence": revision,
        }
    observed_revision = str(revision.get("inbound_revision") or "")
    if observed_revision != inbound_revision:
        return {
            "status": "blocked",
            "action": action,
            "reason": "managed_inbound_revision_changed",
            "expected_inbound_revision": inbound_revision,
            "observed_inbound_revision": observed_revision,
            "inbound_revision_evidence": _public_revision_evidence(revision),
        }
    baseline_observation_id = _bound_managed_inbound_revision_observation_id(target_binding)
    if baseline_observation_id and revision.get("observation_id") == baseline_observation_id:
        return {
            "status": "blocked",
            "action": action,
            "reason": "managed_inbound_revision_observation_not_fresh",
        }
    result = {
        "status": "ok",
        "action": action,
        "inbound_revision": observed_revision,
        "inbound_revision_verified": True,
        "inbound_revision_observation_id": revision["observation_id"],
        "inbound_revision_captured_at": revision["captured_at"],
        "inbound_revision_evidence": _public_revision_evidence(revision),
    }
    if expected_text_for_occurrences is not None:
        result["pre_click_expected_text_occurrences"] = int(
            revision.get("expected_text_occurrences") or 0
        )
    if expected_composer_text is not None:
        result.update(
            {
                "composer_observation_status": revision.get("composer_observation_status"),
                "composer_exact_match": revision.get("composer_exact_match") is True,
                "composer_text_hash": revision.get("composer_text_hash"),
                "composer_character_count": revision.get("composer_character_count"),
            }
        )
    return result


def _observe_bound_target(
    session: Any,
    *,
    action: str,
    target_binding: dict[str, Any],
    output_dir: Path | None,
) -> dict[str, Any]:
    if not _is_mac_ios_app_session(session):
        return _blocked("managed_tashuo_requires_mac_ios_app", action=action)
    if not isinstance(target_binding, dict) or not target_binding_structural_evidence_present("tashuo", target_binding):
        return _blocked("target_binding_structural_evidence_required", action=action)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    window = session._window_info()
    if window is None:
        return _blocked("managed_tashuo_window_not_found", action=action)
    target_verification = _verify_tashuo_target_binding(session, target_binding, output_dir=output_dir)
    if target_verification.get("status") != "ok":
        return _blocked(
            target_verification.get("reason") or "managed_target_binding_not_verified",
            action=action,
            target_binding_verification=target_verification,
        )
    return {
        "schema_version": 1,
        "status": "ok",
        "action": action,
        "app_id": "tashuo",
        "runtime": "mac-ios-app",
        "target_binding_hash": _binding_hash(target_binding),
        "target_binding_verification": target_verification,
        "_window": window,
    }


def _observe_current_conversation_revision(
    session: Any,
    *,
    expected_text_for_occurrences: str | None = None,
    expected_composer_text: str | None = None,
) -> dict[str, Any]:
    observed = (
        _tashuo_ax_static_text_values(session)
        if expected_composer_text is None
        else _tashuo_ax_conversation_snapshot(session)
    )
    if observed.get("status") != "ok":
        return {
            "status": "blocked",
            "reason": observed.get("reason") or "managed_inbound_revision_ax_unavailable",
            "evidence_source": "macos_accessibility_static_text",
        }
    raw_values = observed.get("values")
    if not isinstance(raw_values, list):
        return {
            "status": "blocked",
            "reason": "managed_inbound_revision_ax_values_invalid",
            "evidence_source": "macos_accessibility_static_text",
        }
    values = [str(item).strip() for item in raw_values if str(item).strip()]
    if not values:
        return {
            "status": "blocked",
            "reason": "managed_inbound_revision_ax_values_empty",
            "evidence_source": "macos_accessibility_static_text",
        }
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    captured_at = platform._now_iso()
    result = {
        "status": "ok",
        "inbound_revision": "ax-static-v1:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "observation_id": _observation_id("inbound_revision", captured_at),
        "captured_at": captured_at,
        "value_count": len(values),
        "evidence_source": "macos_accessibility_static_text",
    }
    if expected_text_for_occurrences is not None:
        result["expected_text_occurrences"] = _expected_occurrences(
            observed,
            expected_text_for_occurrences,
        )
    if expected_composer_text is not None:
        composer_found = observed.get("composer_found") is True
        composer_value = str(observed.get("composer_value") or "") if composer_found else ""
        result.update(
            {
                "composer_observation_status": "ok" if composer_found else "blocked",
                "composer_exact_match": composer_found and composer_value == expected_composer_text,
                "composer_text_hash": platform._hash_text(composer_value) if composer_found else None,
                "composer_character_count": len(composer_value) if composer_found else None,
            }
        )
    return result


def _public_revision_evidence(revision: dict[str, Any]) -> dict[str, Any]:
    return {
        key: revision.get(key)
        for key in ("status", "observation_id", "captured_at", "value_count", "evidence_source")
        if revision.get(key) is not None
    }


def _bound_managed_inbound_revision(target_binding: dict[str, Any]) -> str:
    thread_evidence = target_binding.get("thread_evidence")
    if not isinstance(thread_evidence, dict):
        return ""
    return str(thread_evidence.get("managed_inbound_revision") or "").strip()


def _bound_managed_inbound_revision_observation_id(target_binding: dict[str, Any]) -> str:
    thread_evidence = target_binding.get("thread_evidence")
    if not isinstance(thread_evidence, dict):
        return ""
    return str(thread_evidence.get("managed_inbound_revision_observation_id") or "").strip()


def _receipt_block_reason(
    receipt: dict[str, Any],
    expected_text: str,
    target_binding: dict[str, Any],
) -> str | None:
    if not isinstance(receipt, dict) or receipt.get("status") != "ok":
        return "managed_click_receipt_invalid"
    if not str(receipt.get("receipt_id") or "") or not str(receipt.get("clicked_at") or ""):
        return "managed_click_receipt_incomplete"
    if receipt.get("expected_payload_hash") != platform._hash_text(expected_text):
        return "managed_click_receipt_payload_mismatch"
    if receipt.get("target_binding_hash") != _binding_hash(target_binding):
        return "managed_click_receipt_target_mismatch"
    return None


def _expected_occurrences(ax_static: dict[str, Any], expected_text: str) -> int:
    if ax_static.get("status") != "ok" or not isinstance(ax_static.get("values"), list):
        return 0
    observed = "\n".join(str(item) for item in ax_static["values"] if str(item).strip())
    return int(platform._expected_text_observation_stats(observed, expected_text)["expected_text_occurrences"])


def _post_send_unknown_reason(
    *,
    post_screen: dict[str, Any],
    verification: dict[str, Any],
    fresh_exact_text: bool,
    fresh_capture: bool,
) -> str:
    if post_screen.get("status") != "ok":
        return str(post_screen.get("reason") or "managed_post_send_screen_not_captured")
    if post_screen.get("state") != "tashuo_conversation":
        return "managed_post_send_conversation_not_verified"
    if not fresh_capture:
        return "managed_post_send_observation_not_fresh"
    if not verification.get("input_cleared_after_send"):
        return "managed_post_send_input_not_cleared"
    if not verification.get("exact_text_ax_verified"):
        return "managed_post_send_exact_text_not_verified"
    if not fresh_exact_text:
        return "managed_post_send_outbound_occurrence_not_new"
    return str(verification.get("reason") or "managed_post_send_not_verified")


def _binding_hash(target_binding: dict[str, Any]) -> str:
    encoded = json.dumps(target_binding, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _observation_id(kind: str, captured_at: str) -> str:
    source = f"{kind}:{captured_at}:{uuid4().hex}"
    return f"tashuo_managed_{kind}_" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]


def _iso_strictly_after(value: str, reference: str) -> bool:
    try:
        return platform._parse_iso(value) > platform._parse_iso(reference)
    except (AttributeError, TypeError, ValueError):
        # platform has no public time parser on some harness builds. ISO-8601
        # UTC strings emitted here are lexically ordered at equal precision.
        return bool(value and reference and value > reference)


def _blocked(reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "blocked",
        "reason": str(reason),
        "app_id": "tashuo",
        "runtime": "mac-ios-app",
        **extra,
    }


__all__ = [
    "click_tashuo_managed_send_only",
    "observe_tashuo_managed_composer",
    "observe_tashuo_managed_inbound_revision",
    "observe_tashuo_managed_post_send",
    "stage_tashuo_managed_text",
]
