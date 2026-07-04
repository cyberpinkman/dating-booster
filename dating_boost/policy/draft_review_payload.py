"""Draft payload normalization and message hashing."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any, Mapping

from dating_boost.core.models import Divergence
from dating_boost.intelligence.reply_generator import DraftResponse
from dating_boost.policy.draft_review_models import DRAFT_REVIEW_MODES
from dating_boost.policy.draft_review_utils import _digest, text_hash

__all__ = [
    "_divergence_value",
    "_draft_from_payload",
    "_draft_payload_dict",
    "_normalize_mode",
    "draft_messages_payload_hash",
    "draft_payload_messages",
    "draft_question_count",
    "looks_like_direct_question",
    "text_hash",
]

def draft_payload_messages(draft_payload: Mapping[str, Any], fallback_text: str) -> list[dict[str, Any]]:
    raw_messages = draft_payload.get("message_sequence")
    if isinstance(raw_messages, list):
        texts = [str(item).strip() for item in raw_messages if str(item).strip()]
    else:
        texts = [str(fallback_text).strip()]
    if not texts:
        texts = [str(fallback_text)]
    return [
        {
            "index": index,
            "text": text,
            "message_hash": text_hash(text),
            "character_count": len(text),
        }
        for index, text in enumerate(texts, start=1)
    ]


def draft_messages_payload_hash(messages: list[dict[str, Any]]) -> str:
    texts = [str(message.get("text") or "") for message in messages]
    if len(texts) == 1:
        return text_hash(texts[0])
    return _digest({"payload_format": "message_sequence", "messages": texts})


def draft_question_count(raw_draft: Mapping[str, Any], best_reply: str) -> int:
    explicit = raw_draft.get("question_count")
    if isinstance(explicit, int) and not isinstance(explicit, bool) and explicit >= 0:
        return explicit
    reply_shape = str(raw_draft.get("reply_shape") or "")
    if reply_shape in {"question", "contains_question"}:
        return 1
    texts = [str(message.get("text") or "") for message in draft_payload_messages(raw_draft, best_reply)]
    return sum(1 for text in texts if looks_like_direct_question(text))


def looks_like_direct_question(text: str) -> bool:
    stripped = text.strip()
    if "?" in stripped or "？" in stripped:
        return True
    question_phrases = ("是不是", "有没有", "会不会", "要不要", "能不能", "为什么", "怎么")
    if any(marker in stripped for marker in question_phrases):
        return True
    return bool(re.search(r"(吗|嘛|么|呢)[。！!…]*$", stripped))

def _normalize_mode(mode: str) -> str:
    normalized = str(mode).strip().replace("-", "_")
    if normalized not in DRAFT_REVIEW_MODES:
        raise ValueError(f"unsupported draft review mode: {mode}")
    return normalized


def _draft_payload_dict(draft_payload: Mapping[str, Any] | DraftResponse) -> dict[str, Any]:
    if isinstance(draft_payload, DraftResponse):
        data = asdict(draft_payload)
        data["persona_divergence"] = draft_payload.persona_divergence.value
        data["stance_divergence"] = draft_payload.stance_divergence.value
        return data
    return dict(draft_payload)


def _draft_from_payload(data: Mapping[str, Any]) -> DraftResponse:
    return DraftResponse(
        best_reply=str(data.get("best_reply") or ""),
        safer_reply=str(data.get("safer_reply") or data.get("best_reply") or ""),
        bolder_reply=str(data.get("bolder_reply") or data.get("best_reply") or ""),
        why_this_works=str(data.get("why_this_works") or ""),
        situation_read=str(data.get("situation_read") or ""),
        conversation_move=str(data.get("conversation_move") or ""),
        hook_source=str(data.get("hook_source") or ""),
        naturalness_notes=[str(item) for item in data.get("naturalness_notes", [])] if isinstance(data.get("naturalness_notes", []), list) else [],
        followup_if_match_replies=str(data.get("followup_if_match_replies") or ""),
        risk_flags=[str(item) for item in data.get("risk_flags", [])] if isinstance(data.get("risk_flags", []), list) else [],
        missing_info=[str(item) for item in data.get("missing_info", [])] if isinstance(data.get("missing_info", []), list) else [],
        mode_notes=str(data.get("mode_notes") or ""),
        persona_divergence=_divergence_value(data.get("persona_divergence")),
        stance_divergence=_divergence_value(data.get("stance_divergence")),
    )


def _divergence_value(value: Any) -> Divergence:
    try:
        if isinstance(value, Divergence):
            return value
        return Divergence(str(value or Divergence.LOW.value))
    except ValueError:
        return Divergence.HIGH
