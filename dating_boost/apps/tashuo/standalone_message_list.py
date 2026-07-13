from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from dating_boost.apps.tashuo.native import _tashuo_visual_anchor_hash_for_path
from dating_boost.apps.tashuo.standalone_common import (
    SYNTHETIC_MESSAGE_LIST_VISIBLE_NAME_PREFIX,
    _normalized_visible_name,
    _stable_text_hash,
    _visual_anchor_region_from_source,
)

__all__ = [
    "_align_visual_anchor_region_to_tap_y",
    "_all_messages_open_tap_x",
    "_all_messages_start_y",
    "_attach_tashuo_message_list_perceptual_anchors",
    "_candidate_type_from_visual_row",
    "_correct_tashuo_message_list_tap_ratios",
    "_dedupe_tashuo_message_list_rows",
    "_fallback_first_chat_row_y",
    "_fallback_message_list_avatar_region",
    "_fallback_message_list_row_ys",
    "_first_all_messages_row_index",
    "_infer_first_visible_chat_row_grid_start",
    "_looks_like_tashuo_action_artifact",
    "_looks_like_tashuo_non_chat_gate",
    "_message_list_entry_from_visual_row",
    "_message_list_evidence_from_target",
    "_open_conversation_target_options",
    "_precheck_has_tashuo_message_list_anchor",
    "_redacted_skipped_visual_row",
    "_redacted_step_result",
    "_screen_path_from_observation",
    "_tap_y",
    "_tashuo_message_list_duplicate_key",
    "_tashuo_message_list_grid_fallback_rows",
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
    entry = {
        "candidate_key": str(row.get("candidate_key") or f"tashuo_visual_{anchor}").strip(),
        "visible_name": visible_name or None,
        "latest_preview": latest_preview,
        "latest_preview_hash": _stable_text_hash(latest_preview or anchor),
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
    anchor = str(row.get("visual_anchor_hash") or row.get("candidate_key") or "").strip()
    region = _visual_anchor_region_from_source(row)
    if not anchor and region is None:
        return "missing_visual_anchor"
    return None


def _dedupe_tashuo_message_list_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    seen: set[tuple[str, str]] = set()
    kept: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for position, row in enumerate(rows, start=1):
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


def _correct_tashuo_message_list_tap_ratios(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(rows) < 2:
        return rows
    first_index = _first_all_messages_row_index(rows)
    if first_index is None:
        inferred = _infer_first_visible_chat_row_grid_start(rows)
        if inferred is None:
            return rows
        first_index, start_y = inferred
    else:
        start_y = _all_messages_start_y(rows[first_index])
        if start_y is None:
            return rows
    corrected: list[dict[str, Any]] = []
    row_step = 0.122
    grid_offset = 0
    for index, row in enumerate(rows):
        item = dict(row)
        tap_ratio = item.get("tap_ratio") if isinstance(item.get("tap_ratio"), dict) else {}
        if index >= first_index:
            y = round(min(0.965, start_y + grid_offset * row_step), 4)
            item["tap_ratio"] = {**tap_ratio, "x": _all_messages_open_tap_x(item), "y": y}
            item["tap_ratio_source"] = "corrected_all_messages_row_action"
            item = _align_visual_anchor_region_to_tap_y(item, tap_y=y)
            if not _looks_like_tashuo_action_artifact(item):
                grid_offset += 1
        corrected.append(item)
    return corrected


def _infer_first_visible_chat_row_grid_start(rows: list[dict[str, Any]]) -> tuple[int, float] | None:
    for index, row in enumerate(rows):
        if _candidate_type_from_visual_row(row) == "non_chat_gate":
            continue
        if not _normalized_visible_name(row.get("visible_name")):
            continue
        y = _tap_y(row)
        region = _visual_anchor_region_from_source(row)
        if y is None:
            continue
        region_y1 = float(region["y1"]) if isinstance(region, dict) else y - 0.06
        if 0.52 <= y <= 0.66 and region_y1 <= 0.62:
            return index, 0.577
        return None
    return None


def _all_messages_open_tap_x(row: dict[str, Any]) -> float:
    visible_name = str(row.get("visible_name") or "").strip()
    latest_preview = str(row.get("latest_preview") or "").strip()
    anchor = str(row.get("visual_anchor_hash") or row.get("candidate_key") or "").strip().lower()
    combined = f"{visible_name} {latest_preview} {anchor}".lower()
    if _looks_like_tashuo_non_chat_gate(combined, visible_name=visible_name, latest_preview=latest_preview):
        return 0.5
    return 0.87


def _align_visual_anchor_region_to_tap_y(row: dict[str, Any], *, tap_y: float) -> dict[str, Any]:
    region = _visual_anchor_region_from_source(row)
    if region is None:
        return row
    if float(region["y1"]) <= tap_y <= float(region["y2"]):
        return row
    height = max(0.03, min(0.28, float(region["y2"]) - float(region["y1"])))
    y1 = max(0.0, min(1.0 - height, tap_y - height / 2.0))
    aligned = {
        **region,
        "y1": round(y1, 4),
        "y2": round(y1 + height, 4),
    }
    return {**row, "visual_anchor_region": aligned}


def _tashuo_message_list_grid_fallback_rows(
    *,
    precheck: dict[str, Any],
    rows: list[dict[str, Any]],
    screen_path: Path | None,
) -> list[dict[str, Any]]:
    if screen_path is None or not _precheck_has_tashuo_message_list_anchor(precheck):
        return []
    start_y = _fallback_first_chat_row_y(rows)
    if start_y is None:
        return []
    fallback_rows = []
    for offset, y in enumerate(_fallback_message_list_row_ys(start_y), start=1):
        row = {
            "tap_ratio": {"x": 0.87, "y": y},
            "tap_ratio_source": "synthetic_all_messages_row_action",
            "visible_name": f"{SYNTHETIC_MESSAGE_LIST_VISIBLE_NAME_PREFIX} {offset}",
            "latest_preview": "",
            "visual_anchor_hash": f"synthetic_grid_row_{offset}_{int(y * 10000)}",
            "visual_anchor_region": _fallback_message_list_avatar_region(y),
            "visual_anchor_region_source": "synthetic_message_list_grid",
            "confidence": "low",
            "selection_method": "standalone_visual_message_list_grid_fallback",
        }
        fallback_rows.append(row)
    enriched = _attach_tashuo_message_list_perceptual_anchors(fallback_rows, screen_path=screen_path)
    normalized = []
    for row in enriched:
        item = dict(row)
        anchor = str(item.get("visual_anchor_hash") or item.get("visual_anchor_label") or "").strip()
        if not anchor:
            anchor = hashlib.sha256(
                f"{item.get('visible_name')}|{item.get('tap_ratio')}|{item.get('visual_anchor_region')}".encode("utf-8")
            ).hexdigest()[:16]
        item["candidate_key"] = f"tashuo_visual_{anchor}"
        normalized.append(item)
    return normalized


def _precheck_has_tashuo_message_list_anchor(precheck: dict[str, Any]) -> bool:
    if precheck.get("screen_state") != "tashuo_chat_list":
        return False
    if precheck.get("message_list_top_anchor_present") is True:
        return True
    screen = precheck.get("screen") if isinstance(precheck.get("screen"), dict) else {}
    if screen.get("message_list_top_anchor_present") is True:
        return True
    layout = precheck.get("layout_hints") if isinstance(precheck.get("layout_hints"), dict) else {}
    return bool(layout.get("message_list_top_anchor_present") or layout.get("chat_list_visual_present"))


def _fallback_first_chat_row_y(rows: list[dict[str, Any]]) -> float | None:
    first_index = _first_all_messages_row_index(rows)
    if first_index is not None:
        start_y = _all_messages_start_y(rows[first_index])
        if start_y is not None:
            return round(start_y + 0.122, 4)
    if rows and any(_candidate_type_from_visual_row(row) == "non_chat_gate" for row in rows):
        return 0.577
    return None


def _fallback_message_list_row_ys(start_y: float) -> list[float]:
    values = []
    for index in range(3):
        y = round(start_y + index * 0.122, 4)
        if 0.52 <= y <= 0.86:
            values.append(y)
    return values


def _fallback_message_list_avatar_region(y: float) -> dict[str, float]:
    height = 0.101
    y1 = max(0.0, y - height / 2.0)
    y2 = min(1.0, y + height / 2.0)
    return {"x1": 0.041, "y1": round(y1, 4), "x2": 0.37, "y2": round(y2, 4)}


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
    screen = observation.get("screen") if isinstance(observation.get("screen"), dict) else {}
    path = screen.get("path") if isinstance(screen.get("path"), str) else None
    if not path:
        return None
    return Path(path)


def _first_all_messages_row_index(rows: list[dict[str, Any]]) -> int | None:
    for index, row in enumerate(rows):
        visible_name = str(row.get("visible_name") or "")
        latest_preview = str(row.get("latest_preview") or "")
        anchor = str(row.get("visual_anchor_hash") or row.get("candidate_key") or "").lower()
        if any(token in visible_name for token in ("有个优秀的女生想认识你", "查看谁喜欢了我", "喜欢了你")):
            return index
        if any(token in anchor for token in ("new_promo", "new_badge", "liked_you", "likes_you", "liked_", "likes_")):
            return index
        if latest_preview.startswith("你们已经可以进行会话") and _tap_y(row) and _tap_y(row) > 0.72:
            return index
    return None


def _all_messages_start_y(first_row: dict[str, Any]) -> float | None:
    visible_name = str(first_row.get("visible_name") or "")
    anchor = str(first_row.get("visual_anchor_hash") or first_row.get("candidate_key") or "").lower()
    if (
        "查看谁喜欢了我" in visible_name
        or "喜欢了你" in visible_name
        or any(token in anchor for token in ("liked_you", "likes_you", "liked_", "likes_"))
    ):
        return 0.455
    if "有个优秀的女生想认识你" in visible_name or any(token in anchor for token in ("new_promo", "new_badge")):
        return 0.525
    if str(first_row.get("latest_preview") or "").startswith("你们已经可以进行会话"):
        return 0.635
    return None


def _tap_y(row: dict[str, Any]) -> float | None:
    tap_ratio = row.get("tap_ratio") if isinstance(row.get("tap_ratio"), dict) else {}
    try:
        return float(tap_ratio.get("y"))
    except (TypeError, ValueError):
        return None
