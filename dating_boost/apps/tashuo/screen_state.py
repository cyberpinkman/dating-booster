from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Any
import zlib

from dating_boost.harness.screen_state import (
    _read_png_pixels,
    _region_stats,
    normalize_text,
)


TASHUO_FOREGROUND_STATES = {
    "tashuo_recommend",
    "tashuo_flight",
    "tashuo_chat_list",
    "tashuo_activity",
    "tashuo_search",
    "tashuo_conversation",
    "tashuo_question_gate",
    "tashuo_profile",
    "tashuo_self_profile",
    "tashuo_unknown",
}
TASHUO_TOP_LEVEL_TAB_LABELS = ("推荐", "飞行", "消息", "我的")


def classify_tashuo_screen_text(text: str) -> str:
    normalized = normalize_text(text)
    if not normalized:
        return "unknown"
    if "requesting to bypass" in normalized and "private window picker" in normalized:
        return "screen_permission_prompt"
    if "iphone mirroring is locked" in normalized or "enter password" in normalized or "touch id" in normalized:
        return "iphone_mirroring_locked"
    if any(marker in normalized for marker in ("她说", "tashu", "tashuo")) and any(
        marker in normalized for marker in ("siri", "建议", "搜索", "search", "app store", "app")
    ):
        return "ios_search"
    top_level_state = _classify_tashuo_top_level_text(normalized)
    if top_level_state is not None:
        return top_level_state
    if _looks_like_tashuo_flight_text(normalized):
        return "tashuo_flight"
    if _looks_like_tashuo_search_text(normalized):
        return "tashuo_search"
    if _looks_like_tashuo_question_gate_text(normalized):
        return "tashuo_question_gate"
    if _looks_like_tashuo_conversation_text(normalized):
        return "tashuo_conversation"
    if _looks_like_tashuo_profile_text(normalized):
        return "tashuo_profile"
    if "她说" in normalized or "tashu" in normalized or "tashuo" in normalized:
        return "tashuo_unknown"
    return "unknown"


def classify_tashuo_screen_image(path: Path) -> dict[str, Any]:
    try:
        pixels = _read_png_pixels(path)
    except (OSError, ValueError, zlib.error, struct.error):
        return {"status": "failed", "state": "unknown", "active_tab": "unknown", "bottom_nav_present": False}
    bottom_nav = _tashuo_bottom_nav_hint(pixels)
    bottom_nav_present = bool(bottom_nav["present"])
    conversation_toolbar = _tashuo_conversation_toolbar_hint(pixels)
    state = {
        "recommend": "tashuo_recommend",
        "flight": "tashuo_flight",
        "messages": "tashuo_chat_list",
        "mine": "tashuo_self_profile",
    }.get(str(bottom_nav["active_tab"]), "unknown")
    if state == "unknown" and not bottom_nav_present and conversation_toolbar["present"]:
        state = "tashuo_conversation"
    return {
        "status": "ok",
        "state": state,
        "active_tab": str(bottom_nav["active_tab"]),
        "bottom_nav_present": bottom_nav_present,
        "conversation_toolbar_present": conversation_toolbar["present"],
    }


def combine_tashuo_screen_states(
    text_state: str,
    visual_state: str,
    text: str = "",
    *,
    visual_bottom_nav_present: bool = False,
) -> str:
    if text_state in {"iphone_mirroring_locked", "screen_permission_prompt", "ios_search"}:
        return text_state
    if text_state not in {"unknown", "tashuo_unknown"}:
        return text_state
    normalized = normalize_text(text)
    if _looks_like_tashuo_flight_text(normalized):
        return "tashuo_flight"
    if (
        visual_state in {"tashuo_recommend", "tashuo_flight", "tashuo_chat_list", "tashuo_self_profile"}
        and visual_bottom_nav_present
    ):
        return visual_state
    if visual_bottom_nav_present:
        top_level_state = _classify_tashuo_top_level_header_text(normalized)
        if top_level_state is not None:
            return top_level_state
    if visual_state == "tashuo_conversation" and text_state in {"unknown", "tashuo_unknown"}:
        return "tashuo_conversation"
    return text_state


def classify_tashuo_capture(path: Path, text: str) -> dict[str, Any]:
    text_state = classify_tashuo_screen_text(text)
    visual = classify_tashuo_screen_image(path)
    state = combine_tashuo_screen_states(
        text_state,
        str(visual["state"]),
        text,
        visual_bottom_nav_present=bool(visual.get("bottom_nav_present")),
    )
    return {
        "state": state,
        "text_state": text_state,
        "visual_state": visual["state"],
        "visual_status": visual["status"],
        "visual_active_tab": visual.get("active_tab", "unknown"),
        "visual_bottom_nav_present": visual.get("bottom_nav_present", False),
    }


def tashuo_top_level_bottom_nav_present(screen: dict[str, Any]) -> bool:
    if screen.get("visual_bottom_nav_present") is True:
        return True
    normalized = normalize_text(str(screen.get("text") or ""))
    return _tashuo_top_level_nav_text_present(normalized)


def tashuo_layout_hints(screen: dict[str, Any]) -> dict[str, Any]:
    state = str(screen.get("state") or "unknown")
    normalized = normalize_text(str(screen.get("text") or ""))
    thread_cues = tashuo_thread_cues_from_text(normalized) if state == "tashuo_conversation" else []
    page = {
        "tashuo_recommend": "recommend",
        "tashuo_flight": "flight",
        "tashuo_chat_list": "messages",
        "tashuo_activity": "activity",
        "tashuo_search": "search",
        "tashuo_conversation": "conversation",
        "tashuo_question_gate": "question_gate",
        "tashuo_profile": "profile",
        "tashuo_self_profile": "self_profile",
        "tashuo_unknown": "unknown_tashuo",
    }.get(state, "unknown")
    return {
        "app": "tashuo",
        "page": page,
        "bottom_active_tab": _tashuo_bottom_active_tab_hint(state),
        "top_level_bottom_nav_present": tashuo_top_level_bottom_nav_present(screen),
        "recommend_card_present": state == "tashuo_recommend"
        or any(marker in normalized for marker in ("1日内活跃", "在线等你聊天")),
        "flight_map_present": state == "tashuo_flight"
        or any(marker in normalized for marker in ("背上行囊", "偶遇新的朋友", "马上开聊")),
        "chat_list_present": state == "tashuo_chat_list"
        or any(marker in normalized for marker in ("待回答", "全部消息")),
        "conversation_present": state == "tashuo_conversation",
        "question_gate_present": state == "tashuo_question_gate",
        "self_profile_present": state == "tashuo_self_profile"
        or any(marker in normalized for marker in ("编辑资料", "我的认证")),
        "profile_present": state == "tashuo_profile",
        "message_input_marker_present": _tashuo_message_input_marker_present(normalized),
        "thread_cues": thread_cues,
        "question_gate_reply_requires_user_confirmation": state == "tashuo_question_gate",
        "draft_staging_supported": state == "tashuo_conversation",
        "live_send_supported": state == "tashuo_conversation",
        "managed_live_send_supported": state == "tashuo_conversation",
        "live_send_status": "supported" if state == "tashuo_conversation" else "not_applicable",
        "live_send_block_reason": "",
        "dangerous_actions_blocked": ["like", "pass", "super_like", "flight_start_chat", "question_gate_send"],
        "visual_only_exact_verification_allowed": False,
    }


def tashuo_thread_cues_from_text(text: str) -> list[str]:
    normalized = normalize_text(text)
    cues: list[str] = []
    if "跳过了问答考验" in normalized:
        cues.append("tashuo_question_gate_skipped")
    if "开启了永久聊天" in normalized:
        cues.append("tashuo_permanent_chat_enabled")
    return cues


def _tashuo_top_level_nav_text_present(normalized_text: str) -> bool:
    return all(marker in normalized_text for marker in TASHUO_TOP_LEVEL_TAB_LABELS)


def _classify_tashuo_top_level_text(normalized_text: str) -> str | None:
    if not _tashuo_top_level_nav_text_present(normalized_text):
        return None
    return _classify_tashuo_top_level_header_text(normalized_text)


def _classify_tashuo_top_level_header_text(normalized_text: str) -> str | None:
    if any(marker in normalized_text for marker in ("编辑资料", "我的认证", "谁喜欢了我", "我喜欢的人", "发布动态")):
        return "tashuo_self_profile"
    if any(marker in normalized_text for marker in ("待回答", "全部消息", "开启聊天", "开启通知", "你们已经可以进行会话")):
        return "tashuo_chat_list"
    if any(marker in normalized_text for marker in ("背上行囊", "偶遇新的朋友", "轻触屏幕", "马上开聊")):
        return "tashuo_flight"
    if normalized_text.count("飞行") >= 2:
        return "tashuo_flight"
    if normalized_text.count("消息") >= 2:
        return "tashuo_chat_list"
    if normalized_text.count("我的") >= 2:
        return "tashuo_self_profile"
    if normalized_text.count("推荐") >= 2 or any(marker in normalized_text for marker in ("1日内活跃", "在线等你聊天")):
        return "tashuo_recommend"
    return None


def _looks_like_tashuo_question_gate_text(normalized_text: str) -> bool:
    if _tashuo_top_level_nav_text_present(normalized_text):
        return False
    if "提了一个问题" in normalized_text:
        return True
    question_markers = any(marker in normalized_text for marker in ("问题", "回答"))
    input_markers = _tashuo_message_input_marker_present(normalized_text)
    return question_markers and input_markers and "开启聊天" in normalized_text


def _looks_like_tashuo_flight_text(normalized_text: str) -> bool:
    return any(marker in normalized_text for marker in ("背上行囊", "偶遇新的朋友", "轻触屏幕", "马上开聊"))


def _looks_like_tashuo_search_text(normalized_text: str) -> bool:
    if "搜索" not in normalized_text:
        return False
    return any(marker in normalized_text for marker in ("取消", "上次聊天", "旧金山", "大学", "人喜欢"))


def _looks_like_tashuo_conversation_text(normalized_text: str) -> bool:
    if _tashuo_top_level_nav_text_present(normalized_text) or _looks_like_tashuo_profile_text(normalized_text):
        return False
    if _looks_like_tashuo_flight_text(normalized_text):
        return False
    if _looks_like_tashuo_question_gate_text(normalized_text):
        return False
    input_marker = _tashuo_message_input_marker_present(normalized_text)
    thread_marker = any(marker in normalized_text for marker in ("永久聊天", "可以聊天啦", "点击此处输入文字"))
    visible_name_marker = bool(re.search(r"\b[a-z][a-z0-9_ .'-]{1,30}\b", normalized_text))
    if input_marker and (thread_marker or visible_name_marker):
        return True
    return False


def _looks_like_tashuo_profile_text(normalized_text: str) -> bool:
    if _tashuo_top_level_nav_text_present(normalized_text):
        return False
    profile_sections = sum(
        1
        for marker in ("资料", "动态", "关于我", "我的日常", "我的愿望", "cm", "家乡", "星座")
        if marker in normalized_text
    )
    identity_header = bool(re.search(r"\b[a-z][a-z0-9_ .'-]{1,30}\s+\d{2}\b", normalized_text)) or bool(
        re.search(r"\d{2}\b", normalized_text)
    )
    return profile_sections >= 2 and identity_header


def _tashuo_message_input_marker_present(normalized_text: str) -> bool:
    english_input = bool(re.search(r"\bsend\b", normalized_text))
    chinese_input = any(marker in normalized_text for marker in ("点击此处输入文字", "输入文字", "发消息", "发送"))
    return english_input or chinese_input


def _tashuo_bottom_active_tab_hint(state: str) -> str:
    return {
        "tashuo_recommend": "recommend",
        "tashuo_flight": "flight",
        "tashuo_chat_list": "messages",
        "tashuo_activity": "messages",
        "tashuo_self_profile": "mine",
    }.get(state, "unknown")


def _tashuo_bottom_nav_hint(pixels: dict[str, Any]) -> dict[str, Any]:
    container = _region_stats(pixels, 0.04, 0.90, 0.96, 0.995)
    if container["bright_ratio"] < 0.70:
        return {"present": False, "active_tab": "unknown"}
    slots = (
        ("recommend", 0.06, 0.24),
        ("flight", 0.28, 0.46),
        ("messages", 0.50, 0.70),
        ("mine", 0.76, 0.94),
    )
    slot_results: list[dict[str, Any]] = []
    for name, x1, x2 in slots:
        icon_label = _region_stats(pixels, x1, 0.925, x2, 0.995)
        slot_signal = icon_label["dark_ratio"] + icon_label["mid_ratio"] + icon_label["color_ratio"]
        slot_results.append(
            {
                "name": name,
                "slot_signal": slot_signal,
                "active_signal": icon_label["color_ratio"],
            }
        )
    present = (
        sum(1 for slot in slot_results if slot["slot_signal"] > 0.0015) >= 4
        and max(slot["active_signal"] for slot in slot_results) > 0.035
    )
    if not present:
        return {"present": False, "active_tab": "unknown"}
    active_slots = [slot for slot in slot_results if slot["active_signal"] > 0.035]
    if not active_slots:
        return {"present": True, "active_tab": "unknown"}
    active = max(active_slots, key=lambda slot: slot["active_signal"])
    return {"present": True, "active_tab": str(active["name"])}


def _tashuo_conversation_toolbar_hint(pixels: dict[str, Any]) -> dict[str, Any]:
    input_pill_signal = _region_nonwhite_ratio(pixels, 0.03, 0.855, 0.97, 0.930, threshold=248)
    slots = (
        ("voice", 0.07, 0.20),
        ("image", 0.30, 0.43),
        ("emoji", 0.54, 0.67),
        ("extras", 0.78, 0.93),
    )
    slot_results = [
        {
            "name": name,
            "signal": _region_nonwhite_ratio(pixels, x1, 0.935, x2, 0.990, threshold=245),
        }
        for name, x1, x2 in slots
    ]
    visible_slots = sum(1 for slot in slot_results if slot["signal"] > 0.08)
    return {
        "present": input_pill_signal > 0.50 and visible_slots >= 4,
        "input_pill_signal": input_pill_signal,
        "visible_toolbar_slots": visible_slots,
    }


def _region_nonwhite_ratio(
    pixels: dict[str, Any],
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    threshold: int,
) -> float:
    width = int(pixels["width"])
    height = int(pixels["height"])
    rows = pixels["rows"]
    channels = int(pixels["channels"])
    start_x = max(0, min(width - 1, int(x1 * width)))
    end_x = max(start_x + 1, min(width, int(x2 * width)))
    start_y = max(0, min(height - 1, int(y1 * height)))
    end_y = max(start_y + 1, min(height, int(y2 * height)))
    total = nonwhite = 0
    for row in rows[start_y:end_y]:
        for x in range(start_x, end_x):
            r, g, b = row[x * channels : x * channels + 3]
            lum = (int(r) + int(g) + int(b)) / 3
            total += 1
            if lum < threshold:
                nonwhite += 1
    return nonwhite / total if total else 0.0
