from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TARGET_CACHE_PATH = Path("standalone_session") / "tashuo_targets.json"
TARGET_CACHE_MAX_AGE_SECONDS = 120
TARGET_VISUAL_ANCHOR_CACHE_MAX_AGE_SECONDS = 600
SYNTHETIC_MESSAGE_LIST_VISIBLE_NAME_PREFIX = "TaShuo visible chat row"

__all__ = [
    "TARGET_CACHE_PATH",
    "TARGET_CACHE_MAX_AGE_SECONDS",
    "TARGET_VISUAL_ANCHOR_CACHE_MAX_AGE_SECONDS",
    "SYNTHETIC_MESSAGE_LIST_VISIBLE_NAME_PREFIX",
    "_blocked",
    "_identity_text_key",
    "_is_cjk_character",
    "_is_synthetic_message_list_visible_name",
    "_latest_preview_corroborates_thread",
    "_normalized_visible_name",
    "_now_iso",
    "_stable_text_hash",
    "_visible_name_identity_conflict",
    "_visual_anchor_region_from_source",
]

def _visual_anchor_region_from_source(source: dict[str, Any]) -> dict[str, float] | None:
    region = source.get("visual_anchor_region") if isinstance(source.get("visual_anchor_region"), dict) else None
    if region is None:
        return None
    try:
        x1 = float(region["x1"])
        y1 = float(region["y1"])
        x2 = float(region["x2"])
        y2 = float(region["y2"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        return None
    return {"x1": round(x1, 4), "y1": round(y1, 4), "x2": round(x2, 4), "y2": round(y2, 4)}

def _messages_fingerprint_payload(messages: list[dict[str, str]]) -> str:
    return "|".join(f"{message.get('sender')}:{message.get('text')}" for message in messages)


def _stable_text_hash(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"

def _normalized_visible_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text)
    notification_match = re.search(r"不要让(.{1,40}?)等太久", compact)
    if notification_match:
        candidate = notification_match.group(1).strip("，。,.!！?？：:、|")
        if candidate and "喜欢你的人" not in candidate:
            return candidate
    return text


def _visible_name_identity_conflict(
    expected: Any,
    perceived: Any,
    *,
    cached_target: dict[str, Any] | None = None,
    visible_messages: Any = None,
) -> bool:
    expected_name = _normalized_visible_name(expected)
    perceived_name = _normalized_visible_name(perceived)
    if not expected_name or not perceived_name:
        return False
    if _is_synthetic_message_list_visible_name(expected_name) or _is_synthetic_message_list_visible_name(perceived_name):
        return False
    if expected_name == perceived_name:
        return False
    if _cjk_visible_name_ocr_near_match(expected_name, perceived_name):
        return False
    if cached_target and _latest_preview_corroborates_thread(cached_target, visible_messages):
        return False
    return True


def _is_synthetic_message_list_visible_name(value: Any) -> bool:
    text = str(value or "").strip()
    return text.startswith(SYNTHETIC_MESSAGE_LIST_VISIBLE_NAME_PREFIX)


def _cjk_visible_name_ocr_near_match(expected: str, perceived: str) -> bool:
    if len(expected) != len(perceived) or len(expected) < 3:
        return False
    if not all(_is_cjk_character(char) for char in f"{expected}{perceived}"):
        return False
    mismatches = sum(1 for left, right in zip(expected, perceived, strict=True) if left != right)
    if mismatches != 1:
        return False
    return expected[0] == perceived[0] and expected[-1] == perceived[-1]


def _is_cjk_character(value: str) -> bool:
    if len(value) != 1:
        return False
    codepoint = ord(value)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )


def _latest_preview_corroborates_thread(cached_target: dict[str, Any], visible_messages: Any) -> bool:
    preview = _identity_text_key(cached_target.get("latest_preview"))
    if len(preview) < 8:
        return False
    if not isinstance(visible_messages, list):
        return False
    for message in visible_messages:
        if not isinstance(message, dict):
            continue
        text = _identity_text_key(message.get("text"))
        if len(text) < 8:
            continue
        if preview in text or text in preview:
            return True
    return False


def _identity_text_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    for token in ("[草稿]", "【草稿】", "草稿", "...", "…"):
        text = text.replace(token, "")
    return "".join(char for char in text if not char.isspace() and char not in "，。！？、,.!?;；:：")


def _blocked(reason: str, *, app_id: str, **extra: Any) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason, "app_id": app_id, "runtime": "mac-ios-app", **extra}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
