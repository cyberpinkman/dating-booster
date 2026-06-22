"""Prompt contracts for intelligence generation features."""

from __future__ import annotations


DIVERGENCE_VALUES = ["none", "low", "medium", "high"]
CONVERSATION_MOVE_VALUES = [
    "answer_or_riff",
    "take_the_lead",
    "deepen_current",
    "bridge_topic",
    "light_self_disclosure",
    "reciprocal_disclosure",
    "low_investment_repair",
    "reset_thread",
    "soft_invite_probe",
    "nudge_later",
    "slow_down_wait",
    "wait",
    "handoff",
]

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
        "conversation_move": {"type": "string", "enum": CONVERSATION_MOVE_VALUES},
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
        "question_count": {"type": "integer", "minimum": 0},
        "reply_shape": {"type": "string"},
        "disclosure_source": {"type": "string"},
        "used_user_material_ids": {"type": "array", "items": {"type": "string"}},
        "meeting_path": {"type": "string"},
        "why_not_ask_question": {"type": "string"},
        "why_not_invite_now": {"type": "string"},
    },
}
