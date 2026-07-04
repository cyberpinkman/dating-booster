"""Context-pack extraction for draft review."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from dating_boost.perception.observations import AppObservation
from dating_boost.policy.draft_review_utils import _digest

__all__ = [
    "_captured_at_from_send_time",
    "_context_label_content",
    "_context_message_list",
    "_context_string_list",
    "_disclosure_profile_from_context_pack",
    "_observation_from_context_pack",
    "_planner_recommendation",
]

def _planner_recommendation(context_pack: Mapping[str, Any]) -> Mapping[str, Any]:
    direct = context_pack.get("planner_recommendation")
    if isinstance(direct, Mapping):
        return direct
    for item in context_pack.get("items", []):
        if isinstance(item, Mapping) and item.get("label") == "planner_recommendation":
            content = item.get("content")
            if isinstance(content, Mapping):
                return content
    return {}


def _disclosure_profile_from_context_pack(context_pack: Mapping[str, Any]) -> Mapping[str, Any] | None:
    content = _context_label_content(context_pack, "user_disclosure_profile")
    return content if isinstance(content, Mapping) else None


def _observation_from_context_pack(context_pack: Mapping[str, Any]) -> AppObservation | None:
    latest_inbound = _context_message_list(_context_label_content(context_pack, "latest_inbound_messages"))
    recent_messages = _context_message_list(_context_label_content(context_pack, "recent_messages"))
    latest_message = _context_message_list(_context_label_content(context_pack, "latest_message"))
    visible_messages = [*recent_messages, *latest_message, *latest_inbound]
    hooks = _context_string_list(_context_label_content(context_pack, "match_hooks"))
    thread_cues = _context_string_list(_context_label_content(context_pack, "open_threads"))
    send_time = _context_label_content(context_pack, "send_time_context")
    if not latest_inbound and not visible_messages and not hooks and not isinstance(send_time, Mapping):
        return None
    captured_at = _captured_at_from_send_time(send_time)
    profile_text = "\n".join(hooks)
    return AppObservation.from_dict(
        {
            "observation_id": "ctx_obs_" + _digest(
                {
                    "latest_inbound": latest_inbound,
                    "visible_messages": visible_messages,
                    "hooks": hooks,
                    "captured_at": captured_at,
                }
            )[:16],
            "source_type": "user_input",
            "app_id": str(context_pack.get("app_id") or "context"),
            "adapter_id": "draft_review.context.v1",
            "captured_at": captured_at,
            "page_type": "chat_thread",
            "page_confidence": "low",
            "match_identity_hints": {
                "visible_name": None,
                "profile_cues": hooks,
                "conversation_fingerprint": None,
                "evidence": "context_pack",
            },
            "profile_observation": {
                "profile_text": profile_text,
                "photo_cues": [],
                "hook_candidates": hooks,
                "review_status": "observed" if hooks else "missing",
                "evidence": "context_pack",
            },
            "conversation_observation": {
                "visible_messages": visible_messages,
                "input_state": "",
                "thread_cues": thread_cues,
                "latest_inbound_messages": latest_inbound,
            },
            "element_observations": [],
            "exception_state": "none",
            "provenance": {"source": "context_pack"},
            "raw_ref": None,
        }
    )


def _context_label_content(context_pack: Mapping[str, Any], label: str) -> Any:
    direct = context_pack.get(label)
    if direct is not None:
        return direct
    items = context_pack.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if item.get("label") == label:
            return item.get("content")
    return None


def _context_message_list(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    messages: list[dict[str, str]] = []
    for item in raw_items:
        if isinstance(item, Mapping):
            text = str(item.get("text") or item.get("content") or "").strip()
            if not text:
                continue
            message = {
                "sender": str(item.get("sender") or "match"),
                "text": text,
            }
            timestamp = str(item.get("timestamp") or item.get("created_at") or "").strip()
            if timestamp:
                message["timestamp"] = timestamp
            messages.append(message)
        else:
            text = str(item).strip()
            if text:
                messages.append({"sender": "match", "text": text})
    return messages


def _context_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    strings: list[str] = []
    for item in raw_items:
        if isinstance(item, Mapping):
            text = str(item.get("text") or item.get("content") or item.get("label") or "").strip()
        else:
            text = str(item).strip()
        if text:
            strings.append(text)
    return strings


def _captured_at_from_send_time(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("current_utc", "current_local", "captured_at"):
            raw = str(value.get(key) or "").strip()
            if raw:
                return raw
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
