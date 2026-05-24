from __future__ import annotations

from enum import Enum


class SourceType(str, Enum):
    MANUAL_FIXTURE = "manual_fixture"
    SCREENSHOT_FIXTURE = "screenshot_fixture"
    LIVE_SCREENSHOT = "live_screenshot"
    USER_INPUT = "user_input"


class PageType(str, Enum):
    CHAT_THREAD = "chat_thread"
    PROFILE = "profile"
    MATCH_LIST = "match_list"
    UNKNOWN = "unknown"


class ExceptionState(str, Enum):
    NONE = "none"
    PARTIAL_CAPTURE = "partial_capture"
    REDACTED = "redacted"
    UNKNOWN = "unknown"
