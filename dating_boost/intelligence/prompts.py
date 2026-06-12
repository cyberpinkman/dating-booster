"""Prompt contracts for intelligence generation features."""

from __future__ import annotations


DIVERGENCE_VALUES = ["none", "low", "medium", "high"]

REPLY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "best_reply",
        "safer_reply",
        "bolder_reply",
        "why_this_works",
        "situation_read",
        "conversation_move",
        "hook_source",
        "naturalness_notes",
        "followup_if_match_replies",
        "risk_flags",
        "missing_info",
        "mode_notes",
        "persona_divergence",
        "stance_divergence",
    ],
    "properties": {
        "best_reply": {"type": "string"},
        "safer_reply": {"type": "string"},
        "bolder_reply": {"type": "string"},
        "why_this_works": {"type": "string"},
        "situation_read": {"type": "string"},
        "conversation_move": {"type": "string"},
        "hook_source": {"type": "string"},
        "naturalness_notes": {"type": "array", "items": {"type": "string"}},
        "followup_if_match_replies": {"type": "string"},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "missing_info": {"type": "array", "items": {"type": "string"}},
        "mode_notes": {"type": "string"},
        "persona_divergence": {"type": "string", "enum": DIVERGENCE_VALUES},
        "stance_divergence": {"type": "string", "enum": DIVERGENCE_VALUES},
        "message_sequence": {"type": "array", "items": {"type": "string"}},
        "strategic_delta": {"type": "string"},
        "selected_hook": {"type": "string"},
        "meeting_path": {"type": "string"},
        "why_not_ask_question": {"type": "string"},
        "why_not_invite_now": {"type": "string"},
    },
}
