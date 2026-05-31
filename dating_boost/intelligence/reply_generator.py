"""Structured reply generation contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from dating_boost.core.models import Divergence, ReplyMode
from dating_boost.intelligence.backends import ModelBackend
from dating_boost.intelligence.prompts import REPLY_SCHEMA


@dataclass(frozen=True)
class DraftResponse:
    best_reply: str
    safer_reply: str
    bolder_reply: str
    why_this_works: str
    situation_read: str
    conversation_move: str
    hook_source: str
    naturalness_notes: list[str]
    followup_if_match_replies: str
    risk_flags: list[str]
    missing_info: list[str]
    mode_notes: str
    persona_divergence: Divergence
    stance_divergence: Divergence


def generate_reply(context_pack: Mapping[str, Any], reply_mode: ReplyMode, backend: ModelBackend) -> DraftResponse:
    """Generate structured reply drafts from a context pack."""

    payload = backend.generate_structured(
        system_prompt=_build_system_prompt(),
        user_prompt=_build_user_prompt(context_pack, reply_mode),
        schema=REPLY_SCHEMA,
    )
    return parse_draft_response(payload)


def _build_system_prompt() -> str:
    return (
        "You generate dating-app reply drafts as structured JSON. "
        "Return only fields required by the provided schema. "
        "Use situation_read to summarize recipient investment, the latest message, current friction, and whether the "
        "user has already sent too much. "
        "Use conversation_move for one clear move such as answer_or_riff, take_the_lead, deepen_hook, "
        "bridge_from_latest, light_self_disclosure, reset_thread, or soft_invite_probe. "
        "Use hook_source to name the strongest source: latest_message, profile_unknown_detail, shared_overlap, or "
        "conversation_thread. "
        "Use naturalness_notes to self-check whether the draft sounds like a real person in Chinese private chat. "
        "Use followup_if_match_replies to suggest the next step if the match responds. "
        "For Chinese replies, question is optional: one short question is the maximum, not a requirement. "
        "If the match already asked a question, teased, or showed surprise, answer or riff first and do not force a "
        "question just to continue the thread. "
        "If the match delegates the choice with wording like 'you decide', 'up to you', or '听你的', take_the_lead "
        "with one light concrete decision and do not ask them to decide again. "
        "When asking, prefer unknown details behind profile hooks, and avoid multi-option survey wording, tag "
        "stacking, abstract planning nouns, and repeating known facts as if they were new hooks. "
        "Respect safety constraints, respect hard facts, and do not invent identity, location, education, work, "
        "relationship intent, or other hard facts."
    )


def _build_user_prompt(context_pack: Mapping[str, Any], reply_mode: ReplyMode) -> str:
    context_json = json.dumps(context_pack, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "\n".join(
        [
            f"reply_mode: {reply_mode.value}",
            "context_pack_json:",
            context_json,
        ]
    )


def parse_draft_response(payload: Mapping[str, object]) -> DraftResponse:
    required = tuple(REPLY_SCHEMA["required"])
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Reply generation output missing required field(s): {', '.join(missing)}")

    return DraftResponse(
        best_reply=_require_string(payload, "best_reply"),
        safer_reply=_require_string(payload, "safer_reply"),
        bolder_reply=_require_string(payload, "bolder_reply"),
        why_this_works=_require_string(payload, "why_this_works"),
        situation_read=_require_string(payload, "situation_read"),
        conversation_move=_require_string(payload, "conversation_move"),
        hook_source=_require_string(payload, "hook_source"),
        naturalness_notes=_require_string_list(payload, "naturalness_notes"),
        followup_if_match_replies=_require_string(payload, "followup_if_match_replies"),
        risk_flags=_require_string_list(payload, "risk_flags"),
        missing_info=_require_string_list(payload, "missing_info"),
        mode_notes=_require_string(payload, "mode_notes"),
        persona_divergence=_require_divergence(payload, "persona_divergence"),
        stance_divergence=_require_divergence(payload, "stance_divergence"),
    )


def _require_string(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError(f"Reply generation field '{key}' must be a string.")
    return value


def _require_string_list(payload: Mapping[str, object], key: str) -> list[str]:
    value = payload[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Reply generation field '{key}' must be a list of strings.")
    return list(value)


def _require_divergence(payload: Mapping[str, object], key: str) -> Divergence:
    value = _require_string(payload, key)
    try:
        return Divergence(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in Divergence)
        raise ValueError(f"Reply generation field '{key}' must be one of: {allowed}.") from exc


_parse_draft_response = parse_draft_response
