from __future__ import annotations

from typing import Any

from dating_boost.core.planner import validate_planner_assessment
from dating_boost.intelligence.reply_generator import parse_draft_response
from dating_boost.perception.observations import AppObservation


DRAFT_REQUIRED_FIELDS = [
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
]

ASSESSMENT_REQUIRED_FIELDS = [
    "schema_version",
    "latest_inbound_fingerprint",
    "reply_window_status",
    "continuation_opportunity",
    "appointment_stage",
    "recommended_next",
    "confidence",
    "evidence",
    "risk_flags",
]

OBSERVATION_REQUIRED_FIELDS = [
    "observation_id",
    "app_id",
    "captured_at",
    "page_type",
    "page_confidence",
    "match_identity_hints",
    "profile_observation",
    "conversation_observation",
]


def validate_thread_observation_contract(item: dict[str, Any], *, path: str, errors: list[str]) -> None:
    _validate_object_fields(item.get("assessment"), ASSESSMENT_REQUIRED_FIELDS, f"{path}.assessment", errors)

    observation_payload = item.get("observation")
    _validate_object_fields(observation_payload, OBSERVATION_REQUIRED_FIELDS, f"{path}.observation", errors)
    if isinstance(observation_payload, dict):
        try:
            AppObservation.from_dict(observation_payload)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{path}.observation is invalid: {exc}")

    if "draft" in item:
        draft_payload = item.get("draft")
        _validate_object_fields(draft_payload, DRAFT_REQUIRED_FIELDS, f"{path}.draft", errors)
        if isinstance(draft_payload, dict):
            try:
                parse_draft_response(draft_payload)
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{path}.draft is invalid: {exc}")

    if "planner_assessment" in item:
        result = validate_planner_assessment(item.get("planner_assessment"))
        for error in result["errors"]:
            errors.append(f"{path}.{error}")


def _validate_object_fields(value: Any, fields: list[str], path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return
    for field in fields:
        if field not in value:
            errors.append(f"{path}.{field} is required")
