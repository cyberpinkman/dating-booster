from __future__ import annotations

from enum import Enum

from dating_boost.core.models import ReplyMode


class FeedbackLabel(str, Enum):
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"
    TOO_LONG = "too_long"
    TOO_SHORT = "too_short"
    TOO_BORING = "too_boring"
    TOO_AGGRESSIVE = "too_aggressive"
    TOO_FLIRTY = "too_flirty"
    TOO_FORMAL = "too_formal"
    NOT_LIKE_ME = "not_like_me"
    GOOD_HOOK = "good_hook"
    BAD_HOOK = "bad_hook"
    WRONG_ASSUMPTION = "wrong_assumption"


def create_feedback_event(
    event_id: str,
    match_id: str,
    draft_id: str,
    mode: str | ReplyMode,
    label: FeedbackLabel | str,
    created_at: str,
    referenced_memory_ids: list[str] | None = None,
    conversation_move: str | None = None,
    hook_source: str | None = None,
    edited_text_ref: str | None = None,
    user_confirmed_style_promotion: bool | None = None,
) -> dict[str, object]:
    event: dict[str, object] = {
        "event_id": event_id,
        "match_id": match_id,
        "draft_id": draft_id,
        "mode": _mode_value(mode),
        "label": _label_value(label),
        "created_at": created_at,
    }
    if referenced_memory_ids:
        event["referenced_memory_ids"] = [str(item) for item in referenced_memory_ids]
    if conversation_move:
        event["conversation_move"] = str(conversation_move)
    if hook_source:
        event["hook_source"] = str(hook_source)
    if edited_text_ref:
        event["edited_text_ref"] = str(edited_text_ref)
    if user_confirmed_style_promotion is not None:
        event["user_confirmed_style_promotion"] = bool(user_confirmed_style_promotion)
    return event


def _label_value(label: FeedbackLabel | str) -> str:
    try:
        return FeedbackLabel(label).value
    except ValueError as exc:
        raise ValueError(f"invalid feedback label: {label!r}") from exc


def _mode_value(mode: str | ReplyMode) -> str:
    if isinstance(mode, ReplyMode):
        return mode.value
    return mode
