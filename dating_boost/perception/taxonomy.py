from __future__ import annotations

from enum import Enum


class SourceType(str, Enum):
    MANUAL_FIXTURE = "manual_fixture"
    SCREENSHOT_FIXTURE = "screenshot_fixture"
    LIVE_SCREENSHOT = "live_screenshot"
    USER_INPUT = "user_input"


class PageType(str, Enum):
    HOME_CARD = "home_card"
    CHAT_THREAD = "chat_thread"
    PROFILE = "profile"
    PROFILE_DETAIL = "profile_detail"
    MATCH_LIST = "match_list"
    NEW_MATCH = "new_match"
    PAYWALL = "paywall"
    PERMISSION = "permission"
    ERROR = "error"
    UNKNOWN = "unknown"


class ExceptionState(str, Enum):
    NONE = "none"
    PARTIAL_CAPTURE = "partial_capture"
    REDACTED = "redacted"
    PAYWALL = "paywall"
    PERMISSION_BLOCKED = "permission_blocked"
    NETWORK_ERROR = "network_error"
    LOGIN_REQUIRED = "login_required"
    UNKNOWN = "unknown"
