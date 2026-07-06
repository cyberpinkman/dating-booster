from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dating_boost.apps.tashuo.standalone_common import (
    TARGET_CACHE_MAX_AGE_SECONDS, TARGET_VISUAL_ANCHOR_CACHE_MAX_AGE_SECONDS, _is_synthetic_message_list_visible_name, _latest_preview_corroborates_thread,
    _normalized_visible_name, _stable_text_hash, _visible_name_identity_conflict, _visual_anchor_region_from_source,
)
from dating_boost.apps.tashuo.standalone_message_list import _message_list_evidence_from_target
from dating_boost.apps.tashuo.standalone_thread import _latest_inbound_messages, _normalize_visible_messages

__all__ = [
    "_current_latest_inbound_fingerprint",
    "_current_thread_binding_evidence_mismatch",
    "_current_thread_visible_name_continuity_allowed",
    "_is_current_thread_candidate_key",
    "_message_list_evidence_from_target",
    "_stage_candidate_key",
    "_stage_evidence",
    "_stage_expected_visible_name",
    "_stage_target_blocked",
    "_stage_target_identity_mismatch",
    "_stage_work_item_block_reason",
    "_staged_text_verified",
    "_target_age_seconds",
    "_target_cache_max_age_seconds",
    "_target_freshness_block_reason",
    "_target_has_relocatable_visual_anchor",
]

def _stage_work_item_block_reason(work_item: dict[str, Any]) -> str | None:
    if not str(work_item.get("action_request_id") or "").strip():
        return "invalid_send_work_item:action_request_id"
    if not str(work_item.get("target_match_id") or work_item.get("match_id") or "").strip():
        return "invalid_send_work_item:target_match_id"
    if not str(work_item.get("payload_text") or "").strip():
        return "invalid_send_work_item:payload_text"
    return None


def _stage_candidate_key(work_item: dict[str, Any]) -> str | None:
    direct = str(work_item.get("candidate_key") or "").strip()
    if direct:
        return direct
    binding = work_item.get("target_binding") if isinstance(work_item.get("target_binding"), dict) else {}
    value = str(binding.get("candidate_key") or "").strip()
    return value or None


def _is_current_thread_candidate_key(candidate_key: Any) -> bool:
    value = str(candidate_key or "").strip()
    return value == "current_thread" or value.startswith("current_thread_")


def _stage_target_blocked(reason: str, *, candidate_key: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "blocked",
        "reason": reason,
        "candidate_key": candidate_key,
        **extra,
    }


def _stage_expected_visible_name(target: dict[str, Any], work_item: dict[str, Any]) -> str | None:
    binding = work_item.get("target_binding") if isinstance(work_item.get("target_binding"), dict) else {}
    for value in (binding.get("visible_name"), target.get("visible_name")):
        normalized = _normalized_visible_name(value)
        if normalized and not _is_synthetic_message_list_visible_name(normalized):
            return normalized
    return None


def _stage_target_identity_mismatch(
    identity: dict[str, Any],
    *,
    target: dict[str, Any],
    work_item: dict[str, Any],
    visible_messages: Any = None,
) -> str | None:
    expected_name = _stage_expected_visible_name(target, work_item)
    perceived_name = _normalized_visible_name(identity.get("visible_name"))
    if _visible_name_identity_conflict(
        expected_name,
        perceived_name,
        cached_target=target,
        visible_messages=visible_messages,
    ):
        return "current_thread_visual_identity_mismatch"
    if _current_thread_binding_evidence_mismatch(
        identity,
        work_item=work_item,
        visible_messages=visible_messages,
        target=target,
    ):
        return "current_thread_binding_evidence_mismatch"
    return None


def _current_thread_binding_evidence_mismatch(
    identity: dict[str, Any],
    *,
    work_item: dict[str, Any],
    visible_messages: Any,
    target: dict[str, Any] | None = None,
) -> bool:
    binding = work_item.get("target_binding") if isinstance(work_item.get("target_binding"), dict) else {}
    thread_evidence = binding.get("thread_evidence") if isinstance(binding.get("thread_evidence"), dict) else {}
    expected_anchor = str(thread_evidence.get("visual_anchor_hash") or "").strip()
    expected_latest = str(thread_evidence.get("latest_inbound_fingerprint") or "").strip()
    if not expected_anchor and not expected_latest:
        return False

    current_anchor = str(identity.get("visual_anchor_hash") or "").strip()
    current_latest = _current_latest_inbound_fingerprint(visible_messages)
    anchor_matches = bool(expected_anchor and current_anchor and expected_anchor == current_anchor)
    latest_matches = bool(expected_latest and current_latest and expected_latest == current_latest)
    preview_matches = bool(target and _latest_preview_corroborates_thread(target, visible_messages))
    visible_name_continuity = _current_thread_visible_name_continuity_allowed(
        identity,
        work_item=work_item,
        target=target,
        expected_latest=expected_latest,
        current_latest=current_latest,
    )
    return not (anchor_matches or latest_matches or preview_matches or visible_name_continuity)


def _current_thread_visible_name_continuity_allowed(
    identity: dict[str, Any],
    *,
    work_item: dict[str, Any],
    target: dict[str, Any] | None,
    expected_latest: str,
    current_latest: str | None,
) -> bool:
    candidate_key = _stage_candidate_key(work_item) or ""
    if not _is_current_thread_candidate_key(candidate_key):
        return False
    if expected_latest and current_latest and expected_latest != current_latest:
        return False
    expected_name = _stage_expected_visible_name(target or {}, work_item)
    perceived_name = _normalized_visible_name(identity.get("visible_name"))
    if not expected_name or not perceived_name:
        return False
    return not _visible_name_identity_conflict(expected_name, perceived_name)


def _current_latest_inbound_fingerprint(visible_messages: Any) -> str | None:
    if not isinstance(visible_messages, list):
        return None
    normalized = _normalize_visible_messages(visible_messages)
    latest_inbound = _latest_inbound_messages(normalized)
    latest_text = str(latest_inbound[-1].get("text") or "").strip() if latest_inbound else ""
    return _stable_text_hash(latest_text) if latest_text else None


def _message_list_evidence_from_target(target: dict[str, Any]) -> dict[str, Any]:
    tap_ratio = target.get("tap_ratio") if isinstance(target.get("tap_ratio"), dict) else None
    region = _visual_anchor_region_from_source(target)
    return {
        "evidence_type": "message_list_visual_anchor",
        "visual_anchor_hash": str(target.get("visual_anchor_hash") or "").strip() or None,
        "visual_anchor_region": region,
        "tap_ratio": dict(tap_ratio) if tap_ratio else None,
        "tap_ratio_source": target.get("tap_ratio_source"),
        "selection_method": target.get("selection_method") or "standalone_vision_message_list_row",
    }


def _open_conversation_target_options(target: dict[str, Any]) -> dict[str, Any]:
    evidence = _message_list_evidence_from_target(target)
    return {
        "tap_ratio": target.get("tap_ratio"),
        "visual_target_label": target.get("visible_name"),
        "visual_target_preview": target.get("latest_preview"),
        "visual_anchor_hash": evidence.get("visual_anchor_hash"),
        "visual_anchor_region": evidence.get("visual_anchor_region"),
        "message_list_evidence": evidence,
    }

def _staged_text_verified(staged: dict[str, Any]) -> bool:
    if staged.get("staged_text_verified") is True:
        return True
    verification = staged.get("staged_text_verification")
    if not isinstance(verification, dict):
        return False
    return str(verification.get("status") or "") in {"ok", "verified"}


def _stage_evidence(staged: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in staged.items()
        if key
        in {
            "schema_version",
            "status",
            "stage_attempt_status",
            "staged_text_verified",
            "staged_text_verification",
        }
    }


def _target_freshness_block_reason(target: dict[str, Any]) -> str | None:
    age_seconds = _target_age_seconds(target)
    if age_seconds is None or age_seconds > _target_cache_max_age_seconds(target):
        return "tashuo_standalone_target_stale"
    return None


def _target_cache_max_age_seconds(target: dict[str, Any]) -> int:
    if _target_has_relocatable_visual_anchor(target):
        return TARGET_VISUAL_ANCHOR_CACHE_MAX_AGE_SECONDS
    return TARGET_CACHE_MAX_AGE_SECONDS


def _target_has_relocatable_visual_anchor(target: dict[str, Any]) -> bool:
    return bool(str(target.get("visual_anchor_hash") or "").strip() and _visual_anchor_region_from_source(target))


def _target_age_seconds(target: dict[str, Any]) -> float | None:
    observed_at = str(target.get("observed_at") or "").strip()
    if not observed_at:
        return None
    try:
        parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
