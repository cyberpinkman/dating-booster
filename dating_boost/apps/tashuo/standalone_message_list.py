from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from dating_boost.apps.tashuo.native import _tashuo_visual_anchor_hash_for_path
from dating_boost.apps.tashuo.standalone_common import (
    _normalized_visible_name,
    _stable_text_hash,
    _visual_anchor_region_from_source,
)

__all__ = [
    "_attach_tashuo_message_list_perceptual_anchors",
    "_candidate_type_from_visual_row",
    "_dedupe_tashuo_message_list_rows",
    "_looks_like_tashuo_action_artifact",
    "_looks_like_tashuo_non_chat_gate",
    "_message_list_entry_from_visual_row",
    "_message_list_evidence_from_target",
    "_open_conversation_target_options",
    "_redacted_skipped_visual_row",
    "_redacted_step_result",
    "_screen_path_from_observation",
    "_tashuo_message_list_duplicate_key",
    "_tashuo_message_list_visual_row_skip_reason",
]

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


def _redacted_step_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in ("schema_version", "status", "reason", "screen_state", "action", "target", "next_host_action")
        if key in payload
    }


def _message_list_entry_from_visual_row(row: dict[str, Any], *, position: int) -> dict[str, Any]:
    visible_name = str(row.get("visible_name") or "").strip()
    latest_preview = str(row.get("latest_preview") or "").strip()
    anchor = str(row.get("visual_anchor_hash") or row.get("candidate_key") or "").strip()
    tap_ratio = row.get("tap_ratio") if isinstance(row.get("tap_ratio"), dict) else None
    region = _visual_anchor_region_from_source(row)
    selection_method = str(row.get("selection_method") or "standalone_vision_message_list_row")
    timestamp_cue = row.get("timestamp_cue")
    unread_cue = str(row.get("unread_cue") or "unknown").strip().lower()
    entry = {
        "candidate_key": str(row.get("candidate_key") or f"tashuo_visual_{anchor}").strip(),
        "visible_name": visible_name or None,
        "latest_preview": latest_preview,
        "latest_preview_hash": _stable_text_hash(latest_preview or anchor),
        "timestamp_cue": timestamp_cue.strip() if isinstance(timestamp_cue, str) else "",
        "unread_cue": unread_cue if unread_cue in {"present", "absent", "reply_badge", "unknown"} else "unknown",
        "candidate_type": _candidate_type_from_visual_row(row),
        "position": position,
        "identity_confidence": row.get("confidence") if row.get("confidence") in {"low", "medium", "high"} else "medium",
        "identity_evidence": "TaShuo mac-ios-app message-list visual row.",
        "evidence": "Visible TaShuo message-list row selected by standalone observation provider.",
        "match_identity_hints": {
            "visible_name": visible_name,
            "profile_cues": [],
            "conversation_fingerprint": anchor or _stable_text_hash(latest_preview),
            "evidence": "Visible TaShuo message-list row visual anchor.",
        },
        "message_list_evidence": {
            "evidence_type": "message_list_visual_anchor",
            "visual_anchor_hash": anchor,
            "visual_anchor_region": region,
            "tap_ratio": dict(tap_ratio) if tap_ratio else None,
            "selection_method": selection_method,
        },
    }
    return {key: value for key, value in entry.items() if value is not None}


def _tashuo_message_list_visual_row_skip_reason(row: dict[str, Any]) -> str | None:
    visible_name = _normalized_visible_name(row.get("visible_name"))
    if not visible_name:
        return "missing_visible_name"
    if _candidate_type_from_visual_row(row) == "non_chat_gate":
        return "non_chat_gate"
    tap_ratio = row.get("tap_ratio") if isinstance(row.get("tap_ratio"), dict) else None
    if not tap_ratio:
        return "missing_tap_ratio"
    if any(type(tap_ratio.get(key)) not in (int, float) or not math.isfinite(tap_ratio[key])
           or not 0 <= tap_ratio[key] <= 1 for key in ("x", "y")):
        return "invalid_tap_ratio"
    anchor = str(row.get("visual_anchor_hash") or row.get("candidate_key") or "").strip()
    region = _visual_anchor_region_from_source(row)
    if region is None or str(row.get("visual_anchor_region_source") or "").startswith("derived_from_tap_ratio"):
        return "missing_visual_anchor_region"
    if not anchor:
        return "missing_visual_anchor"
    return None


def _dedupe_tashuo_message_list_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # Two distinct visual rows can land on the same OCR box or hash. Neither
    # may own that cache key, even if its competing row occurs later.
    owners: dict[str, tuple[str, str] | None] = {}
    ambiguous: set[str] = set()
    for row in rows:
        candidate_key = str(row.get("candidate_key") or "").strip()
        if not candidate_key:
            continue
        identity = _tashuo_message_list_duplicate_key(row)
        if candidate_key in owners and (identity is None or owners[candidate_key] != identity):
            ambiguous.add(candidate_key)
        owners[candidate_key] = identity

    seen: set[tuple[str, str]] = set()
    kept: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for position, row in enumerate(rows, start=1):
        if str(row.get("candidate_key") or "").strip() in ambiguous:
            skipped.append(_redacted_skipped_visual_row(row, reason="ambiguous_candidate_key", position=position))
            continue
        key = _tashuo_message_list_duplicate_key(row)
        if key is not None and key in seen:
            skipped.append(_redacted_skipped_visual_row(row, reason="duplicate_visual_row", position=position))
            continue
        if key is not None:
            seen.add(key)
        kept.append(row)
    return kept, skipped


def _tashuo_message_list_duplicate_key(row: dict[str, Any]) -> tuple[str, str] | None:
    visible_name = _normalized_visible_name(row.get("visible_name"))
    latest_preview = str(row.get("latest_preview") or "").strip()
    if not visible_name or not latest_preview:
        return None
    return (visible_name, _stable_text_hash(latest_preview))


def _redacted_skipped_visual_row(row: dict[str, Any], *, reason: str, position: int) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "candidate_key": row.get("candidate_key"),
            "reason": reason,
            "position": position,
            "candidate_type": _candidate_type_from_visual_row(row),
            "has_latest_preview": bool(str(row.get("latest_preview") or "").strip()),
            "has_tap_ratio": isinstance(row.get("tap_ratio"), dict),
            "has_visual_anchor": bool(str(row.get("visual_anchor_hash") or "").strip())
            or _visual_anchor_region_from_source(row) is not None,
        }.items()
        if value is not None
    }


def _candidate_type_from_visual_row(row: dict[str, Any]) -> str:
    visible_name = str(row.get("visible_name") or "").strip()
    latest_preview = str(row.get("latest_preview") or "").strip()
    anchor = str(row.get("visual_anchor_hash") or row.get("candidate_key") or "").strip().lower()
    combined = f"{visible_name} {latest_preview} {anchor}".lower()
    if _looks_like_tashuo_non_chat_gate(combined, visible_name=visible_name, latest_preview=latest_preview):
        return "non_chat_gate"
    if "开启聊天" in latest_preview or "可以进行会话" in latest_preview:
        return "open_chat_candidate"
    return "continuation_candidate"


def _looks_like_tashuo_action_artifact(row: dict[str, Any]) -> bool:
    visible_name = str(row.get("visible_name") or "").strip()
    latest_preview = str(row.get("latest_preview") or "").strip()
    preview_lower = latest_preview.lower()
    if any(token in visible_name for token in ("去回复", "开启聊天按钮", "去回复按钮", "按钮")):
        return True
    if latest_preview in {"去回复", "开启聊天"}:
        return True
    if any(token in latest_preview for token in ("去回复", "开启聊天")) and any(
        token in preview_lower for token in ("action", "button", "按钮")
    ):
        return True
    return False


def _looks_like_tashuo_non_chat_gate(combined: str, *, visible_name: str, latest_preview: str) -> bool:
    if _looks_like_tashuo_action_artifact({"visible_name": visible_name, "latest_preview": latest_preview}):
        return True
    visible_name_lower = visible_name.strip().lower()
    if visible_name_lower in {"全部消息", "all messages"}:
        return True
    if visible_name_lower.startswith("tab header"):
        return True
    if "消息" in visible_name and "动态" in visible_name and len(visible_name.strip()) <= 24:
        return True
    if "开启通知" in combined or "接收通知" in combined:
        return True
    if any(
        token in combined
        for token in (
            "liked_you",
            "premium",
            "paywall",
            "new_badge",
            "pending_clock",
            "clock_placeholder",
            "photo_avatar",
            "portrait_oval",
            "blurred_avatar",
            "orange_avatar_blur",
            "answer_pending",
            "pending question",
            "pending_question",
            "question gate",
            "question_gate",
            "question row avatar",
            "anonymous question",
            "anonymous_question",
            "no visible name",
            "unnamed",
            "tab header",
            "message tab header",
            "notification banner",
            "search icon",
            "filter icon",
            "list icon",
        )
    ):
        return True
    if any(
        token in visible_name
        for token in (
            "优秀的女生想认识你",
            "抢手的女生喜欢了你",
            "查看谁喜欢了我",
            "查看谁喜欢我",
            "喜欢你的人",
            "喜欢了你",
            "去回复",
            "开启聊天",
            "按钮",
            "等待中",
            "待回答",
            "匿名提问",
            "提问卡片",
            "问题卡片",
            "未命名",
        )
    ):
        return True
    if latest_preview in {"等待中", "待回答", "待回答 (1)"} or "待回答" in latest_preview:
        return True
    if "受欢迎" in latest_preview and ("女生" in visible_name or "喜欢" in visible_name):
        return True
    if "她毕业于知名院校" in latest_preview and "优秀的女生" in visible_name:
        return True
    if "开通黑金vip" in latest_preview.lower():
        return True
    return False


def _attach_tashuo_message_list_perceptual_anchors(
    rows: list[dict[str, Any]],
    *,
    screen_path: Path | None,
) -> list[dict[str, Any]]:
    if screen_path is None:
        return rows
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        region = _visual_anchor_region_from_source(item)
        semantic_anchor = str(item.get("visual_anchor_hash") or "").strip()
        if region is not None:
            hash_result = _tashuo_visual_anchor_hash_for_path(screen_path, region=region)
            perceptual_hash = str(hash_result.get("visual_anchor_hash") or "").strip()
            if hash_result.get("status") == "ok" and perceptual_hash:
                if semantic_anchor:
                    item["visual_anchor_label"] = semantic_anchor
                item["visual_anchor_hash"] = perceptual_hash
                item["visual_anchor_grid_size"] = hash_result.get("grid_size")
        enriched.append(item)
    return enriched


def _screen_path_from_observation(observation: dict[str, Any]) -> Path | None:
    screen = observation.get("screen")
    if not isinstance(screen, dict):
        return None
    path = screen.get("path") if isinstance(screen.get("path"), str) else None
    if not path:
        return None
    return Path(path)
