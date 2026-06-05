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
}
WECHAT_FOREGROUND_STATES = {"wechat_chat", "wechat_chat_list", "wechat_unknown"}
BUMBLE_FOREGROUND_STATES = {
    "bumble_browse",
    "bumble_chat_list",
    "bumble_conversation",
    "bumble_opening_move",
    "bumble_profile",
    "bumble_self_profile",
    "bumble_discover",
    "bumble_liked_you",
    "bumble_unknown",
}
BUMBLE_TOP_LEVEL_TAB_LABELS = ("个人档案", "发现", "浏览用户", "为你心动", "聊天")


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
    if _looks_like_tinder_subscription_paywall_text(normalized):
        return "tinder_subscription_paywall"
    if _looks_like_tinder_feedback_survey_text(normalized):
        return "tinder_feedback_survey"
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
    if "tinder" in normalized and any(
        marker in normalized for marker in ("siri", "建议", "搜索", "search", "json", "markdown", "icloud", "app")
    ):
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


def classify_bumble_screen_text(text: str) -> str:
    normalized = normalize_text(text)
    if not normalized:
        return "unknown"
    if "requesting to bypass" in normalized and "private window picker" in normalized:
        return "screen_permission_prompt"
    if "iphone mirroring is locked" in normalized or "enter password" in normalized or "touch id" in normalized:
        return "iphone_mirroring_locked"
    if "bumble" in normalized and any(
        marker in normalized for marker in ("siri", "建议", "搜索", "search", "app store")
    ):
        return "ios_search"
    top_level_state = _classify_bumble_top_level_text(normalized)
    if top_level_state is not None:
        return top_level_state
    if _looks_like_bumble_self_profile_text(normalized):
        return "bumble_self_profile"
    if _looks_like_bumble_chat_list_text(normalized):
        return "bumble_chat_list"
    if _looks_like_bumble_opening_move_text(normalized):
        return "bumble_opening_move"
    if _looks_like_bumble_conversation_text(normalized):
        return "bumble_conversation"
    if _looks_like_bumble_profile_text(normalized):
        return "bumble_profile"
    if _looks_like_bumble_liked_you_text(normalized):
        return "bumble_liked_you"
    if _looks_like_bumble_discover_text(normalized):
        return "bumble_discover"
    if _looks_like_bumble_browse_text(normalized):
        return "bumble_browse"
    if "bumble" in normalized:
        return "bumble_unknown"
    return "unknown"


def classify_screen_image(path: Path) -> dict[str, str]:
    try:
        pixels = _read_png_pixels(path)
    except (OSError, ValueError, zlib.error, struct.error):
        return {"status": "failed", "state": "unknown", "active_tab": "unknown"}
    bottom_nav = _tinder_bottom_nav_hint(pixels)
    if bottom_nav["present"]:
        active_tab = bottom_nav["active_tab"]
        state = {
            "home": "tinder_home",
            "explore": "tinder_home",
            "likes": "tinder_home",
            "chats": "tinder_messages",
            "profile": "tinder_self_profile",
        }.get(active_tab, "tinder_unknown")
        return {"status": "ok", "state": state, "active_tab": active_tab}
    if _looks_like_tinder_self_profile_top(pixels):
        return {"status": "ok", "state": "tinder_self_profile", "active_tab": "unknown"}
    return {"status": "ok", "state": "unknown", "active_tab": "unknown"}


def classify_bumble_screen_image(path: Path) -> dict[str, Any]:
    try:
        pixels = _read_png_pixels(path)
    except (OSError, ValueError, zlib.error, struct.error):
        return {"status": "failed", "state": "unknown", "active_tab": "unknown", "bottom_nav_present": False}
    bottom_nav = _bumble_bottom_nav_hint(pixels)
    bottom_nav_present = bool(bottom_nav["present"])
    if _looks_like_bumble_browse_visual(pixels):
        return {
            "status": "ok",
            "state": "bumble_browse",
            "active_tab": "browse_users",
            "bottom_nav_present": bottom_nav_present,
        }
    if _looks_like_bumble_conversation_visual(pixels):
        return {
            "status": "ok",
            "state": "bumble_conversation",
            "active_tab": "unknown",
            "bottom_nav_present": bottom_nav_present,
        }
    if _looks_like_bumble_chat_list_visual(pixels, bottom_nav=bottom_nav):
        return {
            "status": "ok",
            "state": "bumble_chat_list",
            "active_tab": "chats",
            "bottom_nav_present": bottom_nav_present,
        }
    return {
        "status": "ok",
        "state": "unknown",
        "active_tab": str(bottom_nav["active_tab"]),
        "bottom_nav_present": bottom_nav_present,
    }


def combine_screen_states(text_state: str, visual_state: str, text: str = "") -> str:
    if text_state in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return text_state
    if text_state not in {"unknown", "tinder_unknown"}:
        return text_state
    if visual_state in TINDER_FOREGROUND_STATES and _visual_tinder_foreground_override_allowed(text):
        return visual_state
    return text_state


def combine_bumble_screen_states(
    text_state: str,
    visual_state: str,
    text: str = "",
    *,
    visual_bottom_nav_present: bool = False,
) -> str:
    if text_state in {"iphone_mirroring_locked", "screen_permission_prompt", "ios_search"}:
        return text_state
    if text_state not in {"unknown", "bumble_unknown"}:
        return text_state
    normalized = normalize_text(text)
    if visual_bottom_nav_present:
        top_level_state = _classify_bumble_top_level_header_text(normalized)
        if top_level_state is not None:
            return top_level_state
    if (
        visual_state in BUMBLE_FOREGROUND_STATES
        and visual_bottom_nav_present
        and ("bumble" in normalized or _bumble_top_level_nav_text_present(normalized))
    ):
        return visual_state
    if (
        visual_state == "bumble_chat_list"
        and visual_bottom_nav_present
        and any(marker in normalized for marker in ("opening moves", "配对列表", "聊天（最近）", "轮到您了"))
    ):
        return visual_state
    if (
        visual_state == "bumble_conversation"
        and not visual_bottom_nav_present
        and any(marker in normalized for marker in ("opening move", "已发送", "回复时间", "hi", "aa", "gif"))
    ):
        return visual_state
    return text_state


def bumble_top_level_bottom_nav_present(screen: dict[str, Any]) -> bool:
    if screen.get("visual_bottom_nav_present") is True:
        return True
    normalized = normalize_text(str(screen.get("text") or ""))
    return _bumble_top_level_nav_text_present(normalized)


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
    visual_active_tab = str(screen.get("visual_active_tab") or "unknown")
    bottom_active_tab = (
        visual_active_tab
        if visual_active_tab in {"home", "explore", "likes", "chats", "profile"}
        else _bottom_active_tab_hint(state)
    )
    normalized = normalize_text(str(screen.get("text") or ""))
    page = {
        "tinder_home": "home",
        "tinder_messages": "chats",
        "tinder_conversation": "conversation",
        "tinder_self_profile": "self_profile",
        "tinder_profile": "profile",
        "tinder_unknown": "unknown_tinder",
        "tinder_subscription_paywall": "subscription_paywall",
        "tinder_feedback_survey": "feedback_survey",
    }.get(state, "unknown")
    return {
        "page": page,
        "bottom_active_tab": bottom_active_tab,
        "visual_bottom_active_tab": visual_active_tab,
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
        "subscription_paywall_visible": state == "tinder_subscription_paywall"
        or _looks_like_tinder_subscription_paywall_text(normalized),
        "feedback_survey_visible": state == "tinder_feedback_survey"
        or _looks_like_tinder_feedback_survey_text(normalized),
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


def bumble_layout_hints(screen: dict[str, Any]) -> dict[str, Any]:
    state = str(screen.get("state") or "unknown")
    normalized = normalize_text(str(screen.get("text") or ""))
    page = {
        "bumble_browse": "browse_users",
        "bumble_chat_list": "chats",
        "bumble_conversation": "conversation",
        "bumble_opening_move": "opening_move",
        "bumble_profile": "profile",
        "bumble_self_profile": "self_profile",
        "bumble_discover": "discover",
        "bumble_liked_you": "liked_you",
        "bumble_unknown": "unknown_bumble",
    }.get(state, "unknown")
    return {
        "page": page,
        "bottom_active_tab": _bumble_bottom_active_tab_hint(state),
        "top_level_bottom_nav_present": bumble_top_level_bottom_nav_present(screen),
        "browse_card_present": state == "bumble_browse"
        or _looks_like_bumble_browse_text(normalized),
        "self_profile_present": state == "bumble_self_profile"
        or any(marker in normalized for marker in ("个人档案", "完善我的个人档案", "付费方案")),
        "discover_present": state == "bumble_discover"
        or any(marker in normalized for marker in ("发现", "专属推荐", "每日更新")),
        "liked_you_present": state == "bumble_liked_you"
        or any(marker in normalized for marker in ("为你心动", "查看喜欢您的人", "开通premium")),
        "chat_list_present": state == "bumble_chat_list"
        or any(marker in normalized for marker in ("配对列表", "聊天（最近）", "opening moves")),
        "conversation_present": state == "bumble_conversation",
        "opening_move_present": state == "bumble_opening_move" or "opening move" in normalized,
        "reply_deadline_present": any(
            marker in normalized for marker in ("回复时间", "小时后失效", "轮到您了", "失效")
        ),
        "message_input_marker_present": _bumble_message_input_marker_present(normalized),
        "premium_gate_visible": any(
            marker in normalized for marker in ("premium", "查看喜欢您的人", "付费方案", "vip")
        ),
        "danger_menu_may_be_visible": any(marker in normalized for marker in ("解除匹配", "举报", "unmatch", "report")),
        "draft_staging_supported": state == "bumble_conversation",
        "live_send_supported": state == "bumble_conversation",
        "live_send_requires_harness_send_message": True,
        "visual_only_exact_verification_allowed": False,
    }


def _looks_like_tinder_chat_list_text(normalized_text: str) -> bool:
    has_chat_title = "聊天" in normalized_text or "messages" in normalized_text
    has_chat_sections = any(marker in normalized_text for marker in ("新的配对", "new matches", "消息", "messages"))
    return has_chat_title and has_chat_sections


def _looks_like_tinder_subscription_paywall_text(normalized_text: str) -> bool:
    product_marker = any(
        marker in normalized_text
        for marker in (
            "tinder gold",
            "tinder platinum",
            "tinder plus",
            "see who likes you",
            "查看谁喜欢你",
            "谁喜欢你",
        )
    )
    plan_marker = any(
        marker in normalized_text
        for marker in (
            "select a plan",
            "选择套餐",
            "选择计划",
            "订阅",
            "recurring billing",
            "continue -",
            "continue $",
            "1 week",
            "1 month",
            "/wk",
        )
    )
    purchase_marker = any(
        marker in normalized_text
        for marker in (
            "continue -",
            "recurring billing",
            "cancel anytime",
            "app store payment",
            "auto-renew",
            "自动续订",
        )
    )
    return product_marker and (plan_marker or purchase_marker)


def _looks_like_tinder_feedback_survey_text(normalized_text: str) -> bool:
    if "tinder" not in normalized_text:
        return False
    return any(marker in normalized_text for marker in ("体验", "experience", "rate tinder", "忽略")) or bool(
        re.search(r"\bw{4,}\b", normalized_text)
    )


def _visual_tinder_foreground_override_allowed(text: str) -> bool:
    normalized = normalize_text(text)
    negative = any(
        marker in normalized
        for marker in (
            "微信",
            "wechat",
            "通讯录",
            "发现",
            "mac 微信",
            "file transfer assistant",
            "synapseai",
            "app",
            "json",
            "markdown",
            "icloud",
            "搜索",
            "search",
        )
    )
    return not negative


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
    english_input = bool(re.search(r"\b(message|send|gif)\b", normalized_text))
    chinese_input = any(marker in normalized_text for marker in ("发送", "输入消息", "发消息", "说点什么", "键入信息"))
    return english_input or chinese_input


def _looks_like_bumble_self_profile_text(normalized_text: str) -> bool:
    return "个人档案" in normalized_text and any(
        marker in normalized_text for marker in ("完善我的个人档案", "付费方案", "照片洞察", "安全与健康")
    )


def _bumble_top_level_nav_text_present(normalized_text: str) -> bool:
    return all(marker in normalized_text for marker in BUMBLE_TOP_LEVEL_TAB_LABELS)


def _classify_bumble_top_level_text(normalized_text: str) -> str | None:
    if not _bumble_top_level_nav_text_present(normalized_text):
        return None
    return _classify_bumble_top_level_header_text(normalized_text)


def _classify_bumble_top_level_header_text(normalized_text: str) -> str | None:
    if normalized_text.count("个人档案") >= 2 or any(
        marker in normalized_text for marker in ("完善我的个人档案", "照片洞察", "安全与健康")
    ):
        return "bumble_self_profile"
    if normalized_text.count("发现") >= 2 or any(
        marker in normalized_text for marker in ("专属推荐", "每日更新", "共同之处")
    ):
        return "bumble_discover"
    if normalized_text.count("为你心动") >= 2 or any(
        marker in normalized_text for marker in ("查看喜欢您的人", "喜欢你", "premium")
    ):
        return "bumble_liked_you"
    if normalized_text.count("聊天") >= 2 or any(
        marker in normalized_text for marker in ("配对列表", "聊天（最近）", "opening moves")
    ):
        return "bumble_chat_list"
    if "bumble" in normalized_text or normalized_text.count("浏览用户") >= 2:
        return "bumble_browse"
    return None


def _looks_like_bumble_chat_list_text(normalized_text: str) -> bool:
    has_chat_title = "聊天" in normalized_text
    has_chat_sections = any(marker in normalized_text for marker in ("配对列表", "聊天（最近）", "opening moves"))
    return has_chat_title and has_chat_sections


def _looks_like_bumble_opening_move_text(normalized_text: str) -> bool:
    if "opening move" not in normalized_text:
        return False
    return any(marker in normalized_text for marker in ("回复", "发送消息回复", "预设了opening move"))


def _looks_like_bumble_conversation_text(normalized_text: str) -> bool:
    if _looks_like_bumble_chat_list_text(normalized_text) or _looks_like_bumble_profile_text(normalized_text):
        return False
    deadline_marker = any(marker in normalized_text for marker in ("回复时间", "小时后失效", "该您给对方回复了"))
    input_marker = _bumble_message_input_marker_present(normalized_text)
    return input_marker and (deadline_marker or "opening move" in normalized_text or "gif" in normalized_text)


def _looks_like_bumble_profile_text(normalized_text: str) -> bool:
    profile_sections = sum(
        1
        for marker in ("照片通过验证", "我的简介", "关于我", "我在寻找", "我的兴趣爱好", "about me")
        if marker in normalized_text
    )
    identity_header = bool(re.search(r"\b[a-z][a-z0-9_ .'-]{1,30}\s+\d{2}\b", normalized_text))
    return profile_sections >= 2 or (profile_sections >= 1 and identity_header)


def _looks_like_bumble_liked_you_text(normalized_text: str) -> bool:
    return "为你心动" in normalized_text and any(
        marker in normalized_text for marker in ("查看喜欢您的人", "喜欢你", "premium")
    )


def _looks_like_bumble_discover_text(normalized_text: str) -> bool:
    return "发现" in normalized_text and any(marker in normalized_text for marker in ("专属推荐", "每日更新", "共同之处"))


def _looks_like_bumble_browse_text(normalized_text: str) -> bool:
    if "bumble" not in normalized_text:
        return False
    return any(
        marker in normalized_text
        for marker in (
            "浏览用户",
            "照片通过验证",
            "我们可以谈论的话题",
            "个人档案",
            "为你心动",
            "聊天",
            "verified",
        )
    )


def _bumble_message_input_marker_present(normalized_text: str) -> bool:
    english_input = bool(re.search(r"\b(gif|aa)\b", normalized_text))
    chinese_input = any(marker in normalized_text for marker in ("发送", "发消息", "回复"))
    return english_input or chinese_input


def _bumble_bottom_active_tab_hint(state: str) -> str:
    return {
        "bumble_self_profile": "profile",
        "bumble_discover": "discover",
        "bumble_browse": "browse_users",
        "bumble_liked_you": "liked_you",
        "bumble_chat_list": "chats",
    }.get(state, "unknown")


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
    top_structure = (
        avatar["color_ratio"] > 0.04
        and edit_button["bright_ratio"] > 0.10
        and settings["dark_ratio"] > 0.60
        and settings["bright_ratio"] > 0.01
    )
    return top_structure


def _looks_like_bumble_browse_visual(pixels: dict[str, Any]) -> bool:
    top_title = _region_stats(pixels, 0.04, 0.08, 0.36, 0.15)
    profile_card = _region_stats(pixels, 0.04, 0.18, 0.96, 0.88)
    left_action = _region_stats(pixels, 0.06, 0.73, 0.20, 0.81)
    right_action = _region_stats(pixels, 0.76, 0.70, 0.96, 0.82)
    return (
        top_title["bright_ratio"] > 0.65
        and top_title["dark_ratio"] > 0.05
        and profile_card["color_ratio"] > 0.18
        and profile_card["mid_ratio"] > 0.25
        and left_action["color_ratio"] > 0.10
        and right_action["color_ratio"] > 0.16
        and _looks_like_bumble_top_level_bottom_nav_visual(pixels)
    )


def _looks_like_bumble_top_level_bottom_nav_visual(pixels: dict[str, Any]) -> bool:
    return bool(_bumble_bottom_nav_hint(pixels)["present"])


def _bumble_bottom_nav_hint(pixels: dict[str, Any]) -> dict[str, Any]:
    container = _region_stats(pixels, 0.04, 0.88, 0.96, 0.98)
    if container["bright_ratio"] < 0.70:
        return {"present": False, "active_tab": "unknown"}
    slots = (
        ("profile", 0.04, 0.18),
        ("discover", 0.18, 0.34),
        ("browse_users", 0.34, 0.58),
        ("liked_you", 0.58, 0.78),
        ("chats", 0.78, 0.96),
    )
    slot_results: list[dict[str, Any]] = []
    for name, x1, x2 in slots:
        icon_label = _region_stats(pixels, x1, 0.895, x2, 0.975)
        slot_signal = icon_label["dark_ratio"] + icon_label["mid_ratio"] + icon_label["color_ratio"]
        slot_results.append(
            {
                "name": name,
                "slot_signal": slot_signal,
                "active_signal": icon_label["dark_ratio"],
            }
        )
    present = sum(1 for slot in slot_results if slot["slot_signal"] > 0.018) >= 5
    if not present:
        return {"present": False, "active_tab": "unknown"}
    active_slots = [slot for slot in slot_results if slot["active_signal"] > 0.040]
    if not active_slots:
        return {"present": True, "active_tab": "unknown"}
    active = max(active_slots, key=lambda slot: slot["active_signal"])
    return {"present": True, "active_tab": str(active["name"])}


def _looks_like_bumble_chat_list_visual(pixels: dict[str, Any], *, bottom_nav: dict[str, Any]) -> bool:
    if not bottom_nav.get("present") or bottom_nav.get("active_tab") != "chats":
        return False
    header = _region_stats(pixels, 0.04, 0.10, 0.28, 0.16)
    match_carousel = _region_stats(pixels, 0.04, 0.19, 0.72, 0.33)
    opening_card = _region_stats(pixels, 0.04, 0.35, 0.96, 0.47)
    conversation_row = _region_stats(pixels, 0.04, 0.48, 0.96, 0.62)
    list_structure = (
        match_carousel["color_ratio"] > 0.025
        or opening_card["bright_ratio"] > 0.88
        and opening_card["dark_ratio"] + opening_card["mid_ratio"] > 0.010
        or conversation_row["color_ratio"] + conversation_row["mid_ratio"] > 0.040
    )
    return header["dark_ratio"] > 0.035 and header["bright_ratio"] > 0.70 and list_structure


def _looks_like_bumble_conversation_visual(pixels: dict[str, Any]) -> bool:
    if _bumble_bottom_nav_hint(pixels)["present"]:
        return False
    avatar = _region_stats(pixels, 0.14, 0.09, 0.24, 0.16)
    title = _region_stats(pixels, 0.25, 0.10, 0.45, 0.15)
    actions = _region_stats(pixels, 0.64, 0.09, 0.96, 0.16)
    input_bar = _region_stats(pixels, 0.10, 0.89, 0.88, 0.965)
    header_present = (
        avatar["color_ratio"] > 0.08
        and title["dark_ratio"] + title["mid_ratio"] > 0.025
        and actions["dark_ratio"] + actions["mid_ratio"] > 0.025
    )
    input_present = input_bar["bright_ratio"] > 0.88 and input_bar["mid_ratio"] + input_bar["color_ratio"] > 0.003
    return header_present and input_present


def _tinder_bottom_nav_hint(pixels: dict[str, Any]) -> dict[str, Any]:
    container = _region_stats(pixels, 0.05, 0.895, 0.95, 0.985)
    if container["dark_ratio"] < 0.62:
        return {"present": False, "active_tab": "unknown"}

    slots = (
        ("home", 0.07, 0.25),
        ("explore", 0.25, 0.41),
        ("likes", 0.41, 0.57),
        ("chats", 0.57, 0.74),
        ("profile", 0.74, 0.93),
    )
    slot_results: list[dict[str, Any]] = []
    for name, x1, x2 in slots:
        icon_label = _region_stats(pixels, x1, 0.925, x2, 0.960)
        label = _region_stats(pixels, x1, 0.955, x2, 0.985)
        slot_signal = (
            icon_label["bright_ratio"]
            + icon_label["mid_ratio"]
            + icon_label["color_ratio"]
            + min(label["mid_ratio"], 0.08)
        )
        active_signal = icon_label["bright_ratio"] + icon_label["mid_ratio"] + icon_label["color_ratio"]
        slot_results.append(
            {
                "name": name,
                "slot_signal": slot_signal,
                "active": icon_label["dark_ratio"] < 0.55 and active_signal > 0.12,
            }
        )

    if sum(1 for slot in slot_results if slot["slot_signal"] > 0.035) < 5:
        return {"present": False, "active_tab": "unknown"}
    active_slots = [slot for slot in slot_results if slot["active"]]
    if not active_slots:
        return {"present": False, "active_tab": "unknown"}
    active = max(active_slots, key=lambda slot: slot["slot_signal"])
    return {"present": True, "active_tab": active["name"]}


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
