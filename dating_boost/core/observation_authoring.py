from __future__ import annotations

import hashlib
from typing import Any


OBSERVATION_AUTHORING_SCHEMA_VERSION = 1
IDENTITY_CONFIDENCE_VALUES = {"low", "medium", "high"}


def observation_template(observation_type: str = "thread", app_id: str = "tinder") -> dict[str, Any]:
    if observation_type == "message_list":
        return {
            "schema_version": OBSERVATION_AUTHORING_SCHEMA_VERSION,
            "observation_type": "message_list",
            "session_id": "TODO_SESSION_ID",
            "app_id": app_id,
            "captured_at": "TODO_ISO_TIMESTAMP",
            "scan_cursor": None,
            "scan_budget": 5,
            "screenshot_ref": "",
            "provenance": {"author": "host_agent", "evidence": "TODO"},
            "message_list_snapshot": {
                "entries": [
                    {
                        "candidate_key": "visible_name_row_1_latest_preview_hash",
                        "visible_name": "TODO",
                        "latest_preview": "TODO",
                        "latest_preview_hash": "TODO_STABLE_HASH",
                        "timestamp_cue": "TODO",
                        "unread_cue": "present|absent",
                        "position": 1,
                        "identity_confidence": "medium",
                        "identity_evidence": "Visible list row and stable position.",
                        "match_identity_hints": {
                            "visible_name": "TODO",
                            "profile_cues": [],
                            "conversation_fingerprint": "TODO",
                        },
                        "evidence": "Visible app message-list row.",
                    }
                ]
            },
        }
    if observation_type == "thread":
        return {
            "schema_version": OBSERVATION_AUTHORING_SCHEMA_VERSION,
            "observation_type": "thread",
            "candidate_key": "TODO_CANDIDATE_KEY",
            "identity_confidence": "medium",
            "identity_evidence": "Visible chat header and conversation cues match the list row.",
            "turn_boundary_evidence": {
                "latest_user_outbound_text": "",
                "latest_user_outbound_index": None,
                "latest_inbound_after_user": [],
            },
            "screenshot_ref": "",
            "assessment": {},
            "planner_assessment": None,
            "observation": {
                "observation_id": "TODO_OBSERVATION_ID",
                "source_type": "manual_host_loop",
                "app_id": app_id,
                "captured_at": "TODO_ISO_TIMESTAMP",
                "page_type": "chat_thread",
                "page_confidence": "high",
                "match_identity_hints": {
                    "visible_name": "TODO",
                    "profile_cues": [],
                    "conversation_fingerprint": "TODO",
                    "evidence": "TODO",
                },
                "profile_observation": {
                    "profile_text": "",
                    "photo_cues": [],
                    "hook_candidates": [],
                },
                "conversation_observation": {
                    "visible_messages": [],
                    "latest_inbound_messages": [
                        {
                            "sender": "match",
                            "text": "TODO",
                            "is_after_latest_outbound": True,
                        }
                    ],
                    "input_state": "empty",
                    "thread_cues": [],
                },
                "element_observations": [],
                "exception_state": "none",
                "provenance": {"evidence": "Host-agent screen read."},
                "raw_ref": None,
            },
            "draft": None,
        }
    raise ValueError("observation_type must be message_list or thread")


def normalize_observation(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.setdefault("schema_version", OBSERVATION_AUTHORING_SCHEMA_VERSION)
    normalized.setdefault("screenshot_ref", "")
    if normalized.get("observation_type") == "message_list":
        snapshot = dict(normalized.get("message_list_snapshot") or {})
        entries: list[dict[str, Any]] = []
        for entry in _objects(snapshot.get("entries")):
            item = dict(entry)
            item.setdefault("identity_confidence", "medium")
            item.setdefault("identity_evidence", item.get("evidence") or "Visible message-list row.")
            if not item.get("latest_preview_hash") and isinstance(item.get("latest_preview"), str):
                item["latest_preview_hash"] = _stable_hash(item["latest_preview"])
            entries.append(item)
        snapshot["entries"] = entries
        normalized["message_list_snapshot"] = snapshot
    elif normalized.get("observation_type") == "thread":
        normalized.setdefault("identity_confidence", "medium")
        normalized.setdefault("identity_evidence", "Visible chat header and thread cues.")
    return normalized


def validate_observation(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        errors.append("observation payload must be an object")
        return _validation_payload(errors)
    if payload.get("schema_version") != OBSERVATION_AUTHORING_SCHEMA_VERSION:
        errors.append("schema_version must equal 1")
    observation_type = payload.get("observation_type")
    if observation_type == "message_list":
        _validate_message_list(payload, errors)
    elif observation_type == "thread":
        _validate_thread(payload, errors)
    else:
        errors.append("observation_type must be message_list or thread")
    return _validation_payload(errors)


def _validate_message_list(payload: dict[str, Any], errors: list[str]) -> None:
    if not isinstance(payload.get("screenshot_ref"), str):
        errors.append("screenshot_ref is required and may be an empty string")
    snapshot = payload.get("message_list_snapshot")
    if not isinstance(snapshot, dict):
        errors.append("message_list_snapshot must be an object")
        return
    entries = snapshot.get("entries")
    if not isinstance(entries, list):
        errors.append("message_list_snapshot.entries must be a list")
        return
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            errors.append(f"message_list_snapshot.entries[{index}] must be an object")
            continue
        _require_non_empty_string(entry, "candidate_key", errors, f"message_list_snapshot.entries[{index}]")
        confidence = entry.get("identity_confidence")
        if confidence not in IDENTITY_CONFIDENCE_VALUES:
            errors.append(f"message_list_snapshot.entries[{index}].identity_confidence must be low, medium, or high")
        _require_non_empty_string(entry, "identity_evidence", errors, f"message_list_snapshot.entries[{index}]")


def _validate_thread(payload: dict[str, Any], errors: list[str]) -> None:
    _require_non_empty_string(payload, "candidate_key", errors, "thread")
    confidence = payload.get("identity_confidence")
    if confidence not in IDENTITY_CONFIDENCE_VALUES:
        errors.append("thread.identity_confidence must be low, medium, or high")
    _require_non_empty_string(payload, "identity_evidence", errors, "thread")
    if not isinstance(payload.get("screenshot_ref"), str):
        errors.append("thread.screenshot_ref is required and may be an empty string")
    if not isinstance(payload.get("turn_boundary_evidence"), dict):
        errors.append("thread.turn_boundary_evidence is required")
    observation = payload.get("observation")
    if not isinstance(observation, dict):
        errors.append("thread.observation must be an object")
        return
    conversation = observation.get("conversation_observation")
    if not isinstance(conversation, dict):
        errors.append("thread.observation.conversation_observation must be an object")
        return
    latest = conversation.get("latest_inbound_messages")
    if not isinstance(latest, list):
        errors.append("thread.observation.conversation_observation.latest_inbound_messages must be a list")
        return
    for index, message in enumerate(latest, start=1):
        if not isinstance(message, dict):
            errors.append(f"latest_inbound_messages[{index}] must be an object")
            continue
        if message.get("sender") != "match":
            errors.append(f"latest_inbound_messages[{index}] must have sender=match")
        if message.get("is_after_latest_outbound") is not True:
            errors.append(
                f"latest_inbound_messages[{index}] must be marked is_after_latest_outbound=true; old visible messages belong in background"
            )


def _validation_payload(errors: list[str]) -> dict[str, Any]:
    return {
        "schema_version": OBSERVATION_AUTHORING_SCHEMA_VERSION,
        "status": "error" if errors else "ok",
        "error_count": len(errors),
        "errors": errors,
    }


def _require_non_empty_string(payload: dict[str, Any], key: str, errors: list[str], prefix: str) -> None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{prefix}.{key} is required")


def _objects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _stable_hash(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"
