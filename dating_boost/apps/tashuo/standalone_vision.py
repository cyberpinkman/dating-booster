from __future__ import annotations

from typing import Any, Callable

from dating_boost.apps.tashuo.perception import analyze_tashuo_conversation, analyze_tashuo_message_list
from dating_boost.intelligence.vision_backends import VisionBackend

__all__ = [
    "_analyze_tashuo_conversation_with_retry",
    "_analyze_tashuo_message_list_with_retry",
    "_analyze_tashuo_vision_with_retry",
    "_is_retryable_vision_timeout",
]

def _analyze_tashuo_message_list_with_retry(observation: dict[str, Any], *, backend: VisionBackend) -> dict[str, Any]:
    return _analyze_tashuo_vision_with_retry(
        lambda: analyze_tashuo_message_list(observation, backend=backend),
        timeout_reason="tashuo_message_list_vision_timeout",
    )


def _analyze_tashuo_conversation_with_retry(observation: dict[str, Any], *, backend: VisionBackend) -> dict[str, Any]:
    return _analyze_tashuo_vision_with_retry(
        lambda: analyze_tashuo_conversation(observation, backend=backend),
        timeout_reason="tashuo_conversation_vision_timeout",
    )


def _analyze_tashuo_vision_with_retry(analyze: Callable[[], dict[str, Any]], *, timeout_reason: str) -> dict[str, Any]:
    last_timeout: Exception | None = None
    for _attempt in range(2):
        try:
            return analyze()
        except Exception as exc:  # noqa: BLE001 - transient model timeouts should not crash the runtime loop.
            if not _is_retryable_vision_timeout(exc):
                raise
            last_timeout = exc
    return {
        "schema_version": 1,
        "status": "blocked",
        "reason": timeout_reason,
        "error_type": type(last_timeout).__name__ if last_timeout is not None else "TimeoutError",
    }


def _is_retryable_vision_timeout(exc: Exception) -> bool:
    error_type = type(exc).__name__.lower()
    message = str(exc).lower()
    return "timeout" in error_type or "timed out" in message or "request timed out" in message
