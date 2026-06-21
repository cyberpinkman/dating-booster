from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from dating_boost.intelligence.vision_backends import VisionBackend


MESSAGE_LIST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "rows"],
    "properties": {
        "status": {"type": "string", "enum": ["ok", "blocked"]},
        "reason": {"type": "string"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["tap_ratio", "visual_anchor_hash", "confidence"],
                "properties": {
                    "tap_ratio": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["x", "y"],
                        "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                    },
                    "visible_name": {"type": "string"},
                    "latest_preview": {"type": "string"},
                    "visual_anchor_hash": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
            },
        },
    },
}

CONVERSATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "visual_anchor_hash", "visible_messages"],
    "properties": {
        "status": {"type": "string", "enum": ["ok", "blocked"]},
        "reason": {"type": "string"},
        "visible_name": {"type": "string"},
        "visual_anchor_hash": {"type": "string"},
        "visible_messages": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["direction", "text", "confidence"],
                "properties": {
                    "direction": {"type": "string", "enum": ["inbound", "outbound", "system", "unknown"]},
                    "text": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
            },
        },
    },
}


def analyze_tashuo_message_list(observation: dict[str, Any], *, backend: VisionBackend) -> dict[str, Any]:
    screen_path = _screen_path(observation)
    if screen_path is None:
        return _blocked("screen_path_required_for_tashuo_message_list_perception")
    result = backend.analyze_image_structured(
        "Analyze the TaShuo message list screenshot. Return only visible chat rows with precise tap ratios.",
        "Extract candidate rows. Do not infer hidden rows. If no clear row exists, return an empty rows array.",
        screen_path,
        MESSAGE_LIST_SCHEMA,
    )
    if result.get("status") == "blocked":
        return _blocked(str(result.get("reason") or "tashuo_message_list_perception_blocked"))
    rows: list[dict[str, Any]] = []
    raw_rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    for raw in raw_rows:
        row = _normalize_row(raw)
        if row.get("status") == "blocked":
            return row
        rows.append(row)
    if not rows:
        return _blocked("tashuo_message_list_no_visible_rows")
    return {"schema_version": 1, "status": "ok", "rows": rows}


def analyze_tashuo_conversation(observation: dict[str, Any], *, backend: VisionBackend) -> dict[str, Any]:
    screen_path = _screen_path(observation)
    if screen_path is None:
        return _blocked("screen_path_required_for_tashuo_conversation_perception")
    result = backend.analyze_image_structured(
        "Analyze the TaShuo conversation screenshot. Return visible identity evidence and visible messages.",
        "Extract only visible messages. Preserve direction and text. Do not invent missing context.",
        screen_path,
        CONVERSATION_SCHEMA,
    )
    if result.get("status") == "blocked":
        return _blocked(str(result.get("reason") or "tashuo_conversation_perception_blocked"))
    anchor = str(result.get("visual_anchor_hash") or "").strip()
    if not anchor:
        return _blocked("current_thread_visual_identity_not_verified")
    messages = [
        item
        for item in result.get("visible_messages", [])
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    return {
        "schema_version": 1,
        "status": "ok",
        "identity": {
            "binding_type": "current_thread_visual_identity",
            "visual_anchor_hash": anchor,
            "visible_name": str(result.get("visible_name") or "").strip() or None,
        },
        "visible_messages": messages,
    }


def _normalize_row(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return _blocked("tashuo_message_row_must_be_object")
    tap_ratio = raw.get("tap_ratio")
    if not isinstance(tap_ratio, dict) or "x" not in tap_ratio or "y" not in tap_ratio:
        return _blocked("tashuo_message_row_tap_ratio_required")
    ratio = _normalize_tap_ratio(tap_ratio)
    if ratio is None:
        return _blocked("tashuo_message_row_tap_ratio_invalid")
    anchor = str(raw.get("visual_anchor_hash") or "").strip()
    if not anchor:
        anchor = _row_hash(raw)
    return {
        "candidate_key": f"tashuo_visual_{anchor}",
        "tap_ratio": ratio,
        "visible_name": str(raw.get("visible_name") or "").strip() or None,
        "latest_preview": str(raw.get("latest_preview") or "").strip() or None,
        "visual_anchor_hash": anchor,
        "confidence": str(raw.get("confidence") or "medium"),
    }


def _normalize_tap_ratio(tap_ratio: dict[str, Any]) -> dict[str, float] | None:
    try:
        x = float(tap_ratio["x"])
        y = float(tap_ratio["y"])
    except (TypeError, ValueError):
        return None
    if not (0 <= x <= 1 and 0 <= y <= 1):
        return None
    return {"x": round(x, 4), "y": round(y, 4)}


def _screen_path(observation: dict[str, Any]) -> Path | None:
    screen = observation.get("screen") if isinstance(observation.get("screen"), dict) else {}
    value = screen.get("path")
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value)


def _row_hash(raw: dict[str, Any]) -> str:
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def _blocked(reason: str) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason}
