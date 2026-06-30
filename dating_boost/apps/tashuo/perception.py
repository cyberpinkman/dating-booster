from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from dating_boost.apps.tashuo.native import (
    TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
    _tashuo_visual_anchor_hash_for_path,
)
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
                    "visual_anchor_region": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["x1", "y1", "x2", "y2"],
                        "properties": {
                            "x1": {"type": "number"},
                            "y1": {"type": "number"},
                            "x2": {"type": "number"},
                            "y2": {"type": "number"},
                        },
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
    result = _analyze_image_structured_with_retry(
        backend=backend,
        system_prompt="Analyze the TaShuo message list screenshot. Return visible message-list rows with precise tap ratios and row visual anchor regions. Include promotional, Likes You, VIP/paywall, question-gate, and pending-answer rows when they are visible so row positions remain auditable; the host will filter unsafe non-chat rows.",
        user_prompt="Extract visible message-list rows in top-to-bottom order. Include ordinary chat rows and visible non-chat gate/promo rows such as '有人/女生喜欢了你', '查看谁喜欢我', VIP/paywall prompts, and pending-answer/question-gate items. Include visual_anchor_region as normalized x1/y1/x2/y2 bounds for each visible row anchor. Do not infer hidden rows. If no clear visible row exists, return an empty rows array.",
        screen_path=screen_path,
        schema=MESSAGE_LIST_SCHEMA,
        failure_reason="tashuo_message_list_structured_json_invalid",
    )
    if result.get("status") == "blocked":
        return _blocked(str(result.get("reason") or "tashuo_message_list_perception_blocked"))
    rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    raw_rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    for index, raw in enumerate(raw_rows, start=1):
        row = _normalize_row(raw, screen_path=screen_path)
        if row.get("status") == "blocked":
            skipped_rows.append(_redacted_skipped_perception_row(raw, reason=str(row.get("reason") or "invalid_row"), position=index))
            continue
        rows.append(row)
    if not rows:
        first_reason = str(skipped_rows[0].get("reason") or "").strip() if skipped_rows else ""
        result = _blocked(first_reason or "tashuo_message_list_no_visible_rows")
        if skipped_rows:
            result["skipped_rows"] = skipped_rows
        return result
    payload: dict[str, Any] = {"schema_version": 1, "status": "ok", "rows": rows}
    if skipped_rows:
        payload["warnings"] = ["tashuo_message_list_perception_row_skipped"]
        payload["skipped_rows"] = skipped_rows
    return payload


def analyze_tashuo_conversation(observation: dict[str, Any], *, backend: VisionBackend) -> dict[str, Any]:
    screen_path = _screen_path(observation)
    if screen_path is None:
        return _blocked("screen_path_required_for_tashuo_conversation_perception")
    result = _analyze_image_structured_with_retry(
        backend=backend,
        system_prompt="Analyze the TaShuo conversation screenshot. Return visible identity evidence and visible messages.",
        user_prompt="Extract only visible messages. Preserve direction and text. Do not invent missing context.",
        screen_path=screen_path,
        schema=CONVERSATION_SCHEMA,
        failure_reason="tashuo_conversation_structured_json_invalid",
    )
    if result.get("status") == "blocked":
        return _blocked(str(result.get("reason") or "tashuo_conversation_perception_blocked"))
    anchor = _conversation_visual_anchor(screen_path, model_anchor=str(result.get("visual_anchor_hash") or "").strip())
    if anchor.get("status") != "ok":
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
            "visual_anchor_hash": anchor["visual_anchor_hash"],
            "visual_anchor_region": anchor.get("visual_anchor_region"),
            "visual_anchor_source": anchor.get("source"),
            "visual_anchor_grid_size": anchor.get("grid_size"),
            "visible_name": str(result.get("visible_name") or "").strip() or None,
        },
        "visible_messages": messages,
    }


def _conversation_visual_anchor(screen_path: Path, *, model_anchor: str) -> dict[str, Any]:
    hash_result = _tashuo_visual_anchor_hash_for_path(
        screen_path,
        region=dict(TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION),
    )
    local_anchor = str(hash_result.get("visual_anchor_hash") or "").strip()
    if hash_result.get("status") == "ok" and local_anchor:
        return {
            "status": "ok",
            "visual_anchor_hash": local_anchor,
            "visual_anchor_region": dict(TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION),
            "source": "local_perceptual_thread_anchor",
            "grid_size": hash_result.get("grid_size"),
        }
    if model_anchor:
        return {
            "status": "ok",
            "visual_anchor_hash": model_anchor,
            "source": "vision_model_conversation",
        }
    return _blocked(str(hash_result.get("reason") or "thread_visual_anchor_unavailable"))


def _normalize_row(raw: Any, *, screen_path: Path) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return _blocked("tashuo_message_row_must_be_object")
    region = None
    region_source = None
    if "visual_anchor_region" in raw:
        region, region_source = _normalize_visual_anchor_region_with_source(raw.get("visual_anchor_region"))
        if region is not None and _visual_anchor_region_too_small(region):
            region = None
            region_source = "tiny_vision_region"

    tap_ratio = raw.get("tap_ratio")
    tap_ratio_source = "vision_tap_ratio"
    if isinstance(tap_ratio, dict) and "x" in tap_ratio and "y" in tap_ratio:
        ratio = _normalize_tap_ratio(tap_ratio)
        if ratio is None:
            if region is None:
                return _blocked("tashuo_message_row_tap_ratio_invalid")
            ratio = _tap_ratio_from_region(region)
            tap_ratio_source = "derived_from_visual_anchor_region_after_invalid_tap_ratio"
    elif region is not None:
        ratio = _tap_ratio_from_region(region)
        tap_ratio_source = "derived_from_visual_anchor_region"
    else:
        return _blocked("tashuo_message_row_tap_ratio_required")

    if "visual_anchor_region" in raw and region is None:
        region = _fallback_visual_anchor_region(ratio)
        region_source = (
            "derived_from_tap_ratio_after_tiny_vision_region"
            if region_source == "tiny_vision_region"
            else "derived_from_tap_ratio_after_invalid_vision_region"
        )
    elif "visual_anchor_region" not in raw:
        region = _fallback_visual_anchor_region(ratio)
        region_source = "derived_from_tap_ratio_missing_vision_region"

    anchor = _local_visual_anchor_hash(screen_path, region) if region is not None else ""
    anchor_source = "local_screen_region" if anchor else None
    if not anchor:
        anchor = str(raw.get("visual_anchor_hash") or "").strip()
        anchor_source = "vision_model" if anchor else None
    if not anchor:
        anchor = _row_hash(raw)
        anchor_source = "row_text_hash"
    row = {
        "candidate_key": f"tashuo_visual_{anchor}",
        "tap_ratio": ratio,
        "visible_name": str(raw.get("visible_name") or "").strip() or None,
        "latest_preview": str(raw.get("latest_preview") or "").strip() or None,
        "visual_anchor_hash": anchor,
        "confidence": str(raw.get("confidence") or "medium"),
    }
    if anchor_source is not None:
        row["visual_anchor_hash_source"] = anchor_source
    if tap_ratio_source != "vision_tap_ratio":
        row["tap_ratio_source"] = tap_ratio_source
    if region is not None:
        row["visual_anchor_region"] = region
        row["visual_anchor_region_source"] = region_source
    return row


def _normalize_tap_ratio(tap_ratio: dict[str, Any]) -> dict[str, float] | None:
    try:
        x = float(tap_ratio["x"])
        y = float(tap_ratio["y"])
    except (TypeError, ValueError):
        return None
    if not (0 <= x <= 1 and 0 <= y <= 1):
        return None
    return {"x": round(x, 4), "y": round(y, 4)}


def _tap_ratio_from_region(region: dict[str, float]) -> dict[str, float]:
    return {
        "x": round((float(region["x1"]) + float(region["x2"])) / 2.0, 4),
        "y": round((float(region["y1"]) + float(region["y2"])) / 2.0, 4),
    }


def _normalize_visual_anchor_region(raw: Any) -> dict[str, float] | None:
    region, _source = _normalize_visual_anchor_region_with_source(raw)
    return region


def _normalize_visual_anchor_region_with_source(raw: Any) -> tuple[dict[str, float] | None, str | None]:
    if not isinstance(raw, dict):
        return None, None
    try:
        x1 = float(raw["x1"])
        y1 = float(raw["y1"])
        x2 = float(raw["x2"])
        y2 = float(raw["y2"])
    except (KeyError, TypeError, ValueError):
        return None, None
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        values = (x1, y1, x2, y2)
        if 0 <= x1 < x2 <= 100 and 0 <= y1 < y2 <= 100 and any(value > 1 for value in values):
            mixed_scale = any(value <= 1 for value in values)
            x1, y1, x2, y2 = (_normalize_visual_anchor_coordinate(value) for value in values)
            if 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1:
                return (
                    {"x1": round(x1, 4), "y1": round(y1, 4), "x2": round(x2, 4), "y2": round(y2, 4)},
                    "vision_mixed_percent_normalized" if mixed_scale else "vision_percent_normalized",
                )
        return None, None
    return (
        {"x1": round(x1, 4), "y1": round(y1, 4), "x2": round(x2, 4), "y2": round(y2, 4)},
        "vision_unit_normalized",
    )


def _normalize_visual_anchor_coordinate(value: float) -> float:
    return value / 100.0 if value > 1 else value


def _visual_anchor_region_too_small(region: dict[str, float]) -> bool:
    width = float(region["x2"]) - float(region["x1"])
    height = float(region["y2"]) - float(region["y1"])
    return width < 0.03 or height < 0.025


def _local_visual_anchor_hash(screen_path: Path, region: dict[str, float]) -> str:
    result = _tashuo_visual_anchor_hash_for_path(screen_path, region=region)
    if result.get("status") != "ok":
        return ""
    return str(result.get("visual_anchor_hash") or "").strip()


def _fallback_visual_anchor_region(tap_ratio: dict[str, float]) -> dict[str, float]:
    height = 0.12
    y = float(tap_ratio["y"])
    y1 = max(0.0, min(1.0 - height, y - height / 2.0))
    return {"x1": 0.04, "y1": round(y1, 4), "x2": 0.96, "y2": round(y1 + height, 4)}


def _redacted_skipped_perception_row(raw: Any, *, reason: str, position: int) -> dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    return {
        "position": position,
        "reason": reason,
        "has_visible_name": bool(str(row.get("visible_name") or "").strip()),
        "has_latest_preview": bool(str(row.get("latest_preview") or "").strip()),
        "has_tap_ratio": isinstance(row.get("tap_ratio"), dict),
        "has_visual_anchor": bool(str(row.get("visual_anchor_hash") or "").strip())
        or isinstance(row.get("visual_anchor_region"), dict),
    }


def _screen_path(observation: dict[str, Any]) -> Path | None:
    screen = observation.get("screen") if isinstance(observation.get("screen"), dict) else {}
    value = screen.get("path")
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value)


def _analyze_image_structured_with_retry(
    *,
    backend: VisionBackend,
    system_prompt: str,
    user_prompt: str,
    screen_path: Path,
    schema: Mapping[str, object],
    failure_reason: str,
) -> dict[str, Any]:
    try:
        return backend.analyze_image_structured(system_prompt, user_prompt, screen_path, schema)
    except RuntimeError as exc:
        if not _is_structured_json_error(exc):
            raise

    retry_prompt = (
        f"{user_prompt}\n\n"
        "Return exactly one JSON object matching the provided schema. "
        "Do not include prose, markdown, code fences, or explanations. "
        "Include every required schema field even when status is blocked."
    )
    try:
        return backend.analyze_image_structured(system_prompt, retry_prompt, screen_path, schema)
    except RuntimeError as exc:
        if _is_structured_json_error(exc):
            return _blocked(failure_reason)
        raise


def _is_structured_json_error(exc: RuntimeError) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "not valid json",
            "valid structured payload",
            "not a json object",
            "could not be parsed",
        )
    )


def _row_hash(raw: dict[str, Any]) -> str:
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def _blocked(reason: str) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason}
