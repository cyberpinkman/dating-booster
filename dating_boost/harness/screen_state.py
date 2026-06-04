from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path
from typing import Any
import zlib


TINDER_FOREGROUND_STATES = {
    "tinder_home",
    "tinder_messages",
    "tinder_conversation",
    "tinder_self_profile",
    "tinder_profile",
    "tinder_unknown",
}
WECHAT_FOREGROUND_STATES = {"wechat_chat", "wechat_chat_list", "wechat_unknown"}


def classify_screen_text(text: str) -> str:
    normalized = normalize_text(text)
    if not normalized:
        return "unknown"
    if "iphone mirroring is locked" in normalized or "enter password" in normalized or "touch id" in normalized:
        return "iphone_mirroring_locked"
    if "requesting to bypass" in normalized and "private window picker" in normalized:
        return "screen_permission_prompt"
    if any(marker in normalized for marker in ("edit profile", "编辑资料", "编辑个人资料", "edit info")):
        return "tinder_self_profile"
    if "个人资料" in normalized and any(marker in normalized for marker in ("完善个人资料", "添加一条", "设置")):
        return "tinder_self_profile"
    if _looks_like_tinder_chat_list_text(normalized):
        return "tinder_messages"
    if _looks_like_tinder_conversation_text(normalized):
        return "tinder_conversation"
    if _looks_like_tinder_profile_text(normalized):
        return "tinder_profile"
    if "等你回应" in normalized or ("配对" in normalized and any(marker in normalized for marker in ("消息", "聊天"))):
        return "tinder_messages"
    if all(marker in normalized for marker in ("滑动", "探索", "聊天", "个人资料")):
        return "tinder_home"
    if "tinder" in normalized and any(marker in normalized for marker in ("siri", "建议", "搜索", "search")):
        return "ios_search"
    if any(marker in normalized for marker in ("matches", "messages", "配对", "消息")) and "tinder" in normalized:
        return "tinder_messages"
    if "tinder" in normalized:
        return "tinder_unknown"
    if any(marker in normalized for marker in ("搜索", "search", "chrome", "phone", "电话", "微信")):
        return "ios_home_screen"
    return "unknown"


def classify_wechat_screen_text(text: str) -> str:
    normalized = normalize_text(text)
    if not normalized:
        return "unknown"
    if "requesting to bypass" in normalized and "private window picker" in normalized:
        return "screen_permission_prompt"
    wechat_marker = "wechat" in normalized or "微信" in normalized
    chat_input_marker = any(marker in normalized for marker in ("发送", "send", "按住说话", "enter"))
    chat_history_marker = any(marker in normalized for marker in ("昨天", "今天", "分钟前", ":", "am", "pm"))
    chat_list_marker = any(marker in normalized for marker in ("通讯录", "contacts", "订阅号", "群聊", "chats"))
    if wechat_marker and chat_list_marker:
        return "wechat_chat_list"
    if wechat_marker and chat_input_marker and chat_history_marker:
        return "wechat_chat"
    if chat_input_marker and chat_history_marker:
        return "wechat_chat"
    if wechat_marker:
        return "wechat_unknown"
    return "unknown"


def classify_screen_image(path: Path) -> dict[str, str]:
    try:
        pixels = _read_png_pixels(path)
    except (OSError, ValueError, zlib.error, struct.error):
        return {"status": "failed", "state": "unknown"}
    if _looks_like_tinder_self_profile_top(pixels):
        return {"status": "ok", "state": "tinder_self_profile"}
    return {"status": "ok", "state": "unknown"}


def combine_screen_states(text_state: str, visual_state: str) -> str:
    if text_state in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return text_state
    if text_state not in {"unknown", "tinder_unknown"}:
        return text_state
    if visual_state == "tinder_self_profile":
        return visual_state
    return text_state


def redacted_screen(screen: dict[str, Any]) -> dict[str, Any]:
    text = str(screen.get("text") or "")
    result = {key: value for key, value in screen.items() if key != "text"}
    if text:
        result["text_fingerprint"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        result["text_character_count"] = len(text)
    return result


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def tinder_profile_field_coverage(text: str) -> dict[str, bool]:
    normalized = normalize_text(text)
    return {
        "about_me": any(marker in normalized for marker in ("关于我", "about me")),
        "key_info": any(marker in normalized for marker in ("关键信息", "key info")),
        "interests": any(marker in normalized for marker in ("兴趣", "interests")),
        "looking_for": any(marker in normalized for marker in ("我想要", "looking for")),
        "basic_info": any(marker in normalized for marker in ("基本信息", "basic info")),
        "lifestyle": any(marker in normalized for marker in ("生活方式", "lifestyle")),
    }


def tinder_profile_expand_control_visible(text: str) -> bool:
    normalized = normalize_text(text)
    return any(marker in normalized for marker in ("查看所有", "查看更多", "show all", "show more"))


def tinder_profile_danger_action_visible(text: str) -> bool:
    normalized = normalize_text(text)
    return any(marker in normalized for marker in ("取消配对", "举报", "屏蔽", "unmatch", "report", "block"))


def tinder_layout_hints(screen: dict[str, Any]) -> dict[str, Any]:
    state = str(screen.get("state") or "unknown")
    normalized = normalize_text(str(screen.get("text") or ""))
    page = {
        "tinder_home": "home",
        "tinder_messages": "chats",
        "tinder_conversation": "conversation",
        "tinder_self_profile": "self_profile",
        "tinder_profile": "profile",
        "tinder_unknown": "unknown_tinder",
    }.get(state, "unknown")
    return {
        "page": page,
        "bottom_active_tab": _bottom_active_tab_hint(state),
        "self_profile_header_present": state == "tinder_self_profile"
        or any(marker in normalized for marker in ("edit profile", "编辑资料", "编辑个人资料")),
        "self_profile_edit_button_present": any(
            marker in normalized for marker in ("edit profile", "编辑资料", "编辑个人资料")
        ),
        "settings_marker_present": any(marker in normalized for marker in ("settings", "设置")),
        "new_matches_carousel_present": state == "tinder_messages"
        and any(marker in normalized for marker in ("matches", "match", "配对", "新的配对")),
        "conversation_list_present": state == "tinder_messages"
        and any(marker in normalized for marker in ("messages", "message", "消息", "聊天")),
        "reply_required_marker_present": any(marker in normalized for marker in ("等你回应", "your turn")),
        "profile_expand_control_marker_present": any(
            marker in normalized for marker in ("查看所有", "show all", "查看更多")
        ),
    }


def wechat_layout_hints(screen: dict[str, Any]) -> dict[str, Any]:
    state = str(screen.get("state") or "unknown")
    normalized = normalize_text(str(screen.get("text") or ""))
    page = {
        "wechat_chat": "conversation",
        "wechat_chat_list": "chat_list",
        "wechat_unknown": "unknown_wechat",
    }.get(state, "unknown")
    return {
        "page": page,
        "conversation_window_present": state == "wechat_chat",
        "chat_list_present": state == "wechat_chat_list"
        or any(marker in normalized for marker in ("通讯录", "contacts", "订阅号", "群聊", "chats")),
        "message_input_marker_present": any(marker in normalized for marker in ("发送", "send", "按住说话", "enter")),
        "unread_marker_present": any(marker in normalized for marker in ("未读", "new message", "unread")),
        "draft_staging_requires_user_verification": True,
    }


def _looks_like_tinder_chat_list_text(normalized_text: str) -> bool:
    has_chat_title = "聊天" in normalized_text or "messages" in normalized_text
    has_chat_sections = any(marker in normalized_text for marker in ("新的配对", "new matches", "消息", "messages"))
    return has_chat_title and has_chat_sections


def _looks_like_tinder_profile_text(normalized_text: str) -> bool:
    profile_sections = sum(
        1
        for marker in ("关于我", "关键信息", "兴趣", "我想要", "基本信息", "生活方式", "about me", "interests")
        if marker in normalized_text
    )
    has_identity_header = bool(re.search(r"\b[a-z][a-z0-9_ .'-]{1,30}\s+\d{2}\b", normalized_text)) or any(
        marker in normalized_text for marker in ("已认证", "verified")
    )
    return profile_sections >= 2 and not _tinder_message_input_marker_present(normalized_text) and (
        has_identity_header or profile_sections >= 3
    )


def _looks_like_tinder_conversation_text(normalized_text: str) -> bool:
    if _looks_like_tinder_chat_list_text(normalized_text):
        return False
    if _looks_like_tinder_profile_text(normalized_text):
        return False
    if not _tinder_message_input_marker_present(normalized_text):
        return False
    stable_thread_marker = any(marker in normalized_text for marker in ("gif", "send", "发送"))
    visible_name_marker = bool(re.search(r"\b[a-z][a-z0-9_ .'-]{1,30}\b", normalized_text))
    return stable_thread_marker or visible_name_marker


def _tinder_message_input_marker_present(normalized_text: str) -> bool:
    english_input = bool(re.search(r"\b(message|send)\b", normalized_text))
    chinese_input = any(marker in normalized_text for marker in ("发送", "输入消息", "发消息", "说点什么", "键入信息"))
    return english_input or chinese_input


def _bottom_active_tab_hint(state: str) -> str:
    if state == "tinder_self_profile":
        return "profile"
    if state == "tinder_messages":
        return "chats"
    if state == "tinder_home":
        return "home"
    return "unknown"


def _looks_like_tinder_self_profile_top(pixels: dict[str, Any]) -> bool:
    avatar = _region_stats(pixels, 0.04, 0.07, 0.22, 0.19)
    edit_button = _region_stats(pixels, 0.24, 0.11, 0.62, 0.21)
    settings = _region_stats(pixels, 0.82, 0.07, 0.97, 0.19)
    bottom_profile = _region_stats(pixels, 0.76, 0.88, 0.98, 0.99)
    top_structure = (
        avatar["dark_ratio"] > 0.35
        and avatar["color_ratio"] > 0.04
        and edit_button["bright_ratio"] > 0.10
        and settings["dark_ratio"] > 0.60
        and settings["bright_ratio"] > 0.01
    )
    profile_tab_active = bottom_profile["mid_ratio"] > 0.15 and bottom_profile["bright_ratio"] > 0.005
    return top_structure or profile_tab_active


def _region_stats(pixels: dict[str, Any], x1: float, y1: float, x2: float, y2: float) -> dict[str, float]:
    width = int(pixels["width"])
    height = int(pixels["height"])
    rows = pixels["rows"]
    channels = int(pixels["channels"])
    start_x = max(0, min(width - 1, int(x1 * width)))
    end_x = max(start_x + 1, min(width, int(x2 * width)))
    start_y = max(0, min(height - 1, int(y1 * height)))
    end_y = max(start_y + 1, min(height, int(y2 * height)))
    total = bright = dark = mid = color = 0
    for row in rows[start_y:end_y]:
        for x in range(start_x, end_x):
            r, g, b = row[x * channels : x * channels + 3]
            lum = (int(r) + int(g) + int(b)) / 3
            total += 1
            if lum > 210:
                bright += 1
            if lum < 45:
                dark += 1
            if 55 <= lum <= 150:
                mid += 1
            if max(r, g, b) - min(r, g, b) > 35 and lum > 45:
                color += 1
    return {
        "bright_ratio": bright / total,
        "dark_ratio": dark / total,
        "mid_ratio": mid / total,
        "color_ratio": color / total,
    }


def _read_png_pixels(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a png")
    pos = 8
    width = height = channels = color_type = bit_depth = None
    raw = b""
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        pos += 4
        chunk_type = data[pos : pos + 4]
        pos += 4
        chunk = data[pos : pos + length]
        pos += length + 4
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB",
                chunk,
            )
            if bit_depth != 8 or compression != 0 or filter_method != 0 or interlace != 0:
                raise ValueError("unsupported png format")
            channels = {2: 3, 6: 4}.get(color_type)
            if channels is None:
                raise ValueError("unsupported png color type")
        elif chunk_type == b"IDAT":
            raw += chunk
        elif chunk_type == b"IEND":
            break
    if width is None or height is None or channels is None:
        raise ValueError("missing png header")
    scanlines = zlib.decompress(raw)
    rows = []
    i = 0
    previous = [0] * (width * channels)
    for _ in range(height):
        filter_type = scanlines[i]
        i += 1
        row = list(scanlines[i : i + width * channels])
        i += width * channels
        decoded = _decode_png_scanline(row, previous, channels, filter_type)
        rows.append(decoded)
        previous = decoded
    return {"width": width, "height": height, "channels": channels, "rows": rows}


def _decode_png_scanline(row: list[int], previous: list[int], channels: int, filter_type: int) -> list[int]:
    decoded = [0] * len(row)
    for index, value in enumerate(row):
        left = decoded[index - channels] if index >= channels else 0
        up = previous[index]
        upper_left = previous[index - channels] if index >= channels else 0
        if filter_type == 0:
            predictor = 0
        elif filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        elif filter_type == 4:
            predictor = _paeth(left, up, upper_left)
        else:
            raise ValueError("unsupported png filter")
        decoded[index] = (value + predictor) & 0xFF
    return decoded


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    distances = ((abs(estimate - left), left), (abs(estimate - up), up), (abs(estimate - upper_left), upper_left))
    return min(distances, key=lambda item: item[0])[1]
