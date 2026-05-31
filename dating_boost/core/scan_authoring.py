from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timezone
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


def scan_template() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "session_id": "session_example",
        "app_id": "tinder",
        "captured_at": _now_iso(),
        "scan_cursor": None,
        "scan_budget": 5,
        "provenance": {
            "author": "host_agent",
            "evidence": "Host-agent screen read from iPhone Mirroring.",
        },
        "message_list_snapshot": {
            "entries": [
                {
                    "candidate_key": "row_1",
                    "visible_name": "Example",
                    "latest_preview": "你好",
                    "latest_preview_hash": "sha256:example",
                    "timestamp_cue": "刚刚",
                    "unread_cue": "present",
                    "position": 1,
                    "evidence": "Visible message list row.",
                }
            ]
        },
        "thread_observations": [],
    }


def normalize_scan_batch(scan_batch: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(scan_batch)
    normalized.setdefault("schema_version", 1)
    normalized.setdefault("app_id", "tinder")
    normalized.setdefault("scan_budget", 5)
    provenance = normalized.setdefault("provenance", {})
    if isinstance(provenance, dict):
        provenance.setdefault("author", "host_agent")
    message_list = normalized.setdefault("message_list_snapshot", {})
    if isinstance(message_list, dict):
        entries = message_list.setdefault("entries", [])
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if entry.get("latest_preview") and not entry.get("latest_preview_hash"):
                    entry["latest_preview_hash"] = _preview_hash(entry)
    normalized.setdefault("thread_observations", [])
    return normalized


def validate_scan_batch(scan_batch: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if scan_batch.get("schema_version") != 1:
        errors.append("schema_version must equal 1")
    _require_string(scan_batch, "session_id", "scan_batch", errors)
    _require_string(scan_batch, "app_id", "scan_batch", errors)
    _require_string(scan_batch, "captured_at", "scan_batch", errors)

    message_list = scan_batch.get("message_list_snapshot")
    if not isinstance(message_list, dict):
        errors.append("message_list_snapshot must be an object")
        entries: list[Any] = []
    else:
        entries = message_list.get("entries")
        if not isinstance(entries, list):
            errors.append("message_list_snapshot.entries must be a list")
            entries = []

    entry_keys: set[str] = set()
    for index, entry in enumerate(entries):
        path = f"message_list_snapshot.entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{path} must be an object")
            continue
        candidate_key = entry.get("candidate_key")
        if not isinstance(candidate_key, str) or not candidate_key.strip():
            errors.append(f"{path}.candidate_key must be a non-empty string")
        else:
            entry_keys.add(candidate_key)

    thread_observations = scan_batch.get("thread_observations")
    if not isinstance(thread_observations, list):
        errors.append("thread_observations must be a list")
        thread_observations = []

    for index, item in enumerate(thread_observations):
        path = f"thread_observations[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        candidate_key = item.get("candidate_key")
        if not isinstance(candidate_key, str) or not candidate_key.strip():
            errors.append(f"{path}.candidate_key must be a non-empty string")
        elif entry_keys and candidate_key not in entry_keys:
            warnings.append(f"{path}.candidate_key is not present in message_list_snapshot")
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

    return {
        "schema_version": 1,
        "status": "ok" if not errors else "error",
        "error_count": len(errors),
        "errors": errors,
        "warnings": warnings,
    }


def assemble_scan_batch(
    *,
    message_list: dict[str, Any],
    threads: dict[str, Any] | list[Any],
    session_id: str,
    captured_at: str,
    app_id: str = "tinder",
    scan_budget: int = 5,
) -> dict[str, Any]:
    if "message_list_snapshot" in message_list:
        message_list_snapshot = message_list["message_list_snapshot"]
    else:
        message_list_snapshot = message_list
    if isinstance(threads, dict):
        thread_observations = threads.get("thread_observations", [])
    else:
        thread_observations = threads
    return normalize_scan_batch(
        {
            "schema_version": 1,
            "session_id": session_id,
            "app_id": app_id,
            "captured_at": captured_at,
            "scan_budget": scan_budget,
            "provenance": {
                "author": "host_agent",
                "evidence": "Host-agent assembled scan batch.",
            },
            "message_list_snapshot": message_list_snapshot,
            "thread_observations": thread_observations,
        }
    )


def _validate_object_fields(value: Any, fields: list[str], path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return
    for field in fields:
        if field not in value:
            errors.append(f"{path}.{field} is required")


def _require_string(value: dict[str, Any], key: str, path: str, errors: list[str]) -> None:
    if not isinstance(value.get(key), str) or not value.get(key).strip():
        errors.append(f"{path}.{key} must be a non-empty string")


def _preview_hash(entry: dict[str, Any]) -> str:
    payload = "|".join(
        str(entry.get(key) or "")
        for key in ("candidate_key", "visible_name", "latest_preview", "timestamp_cue")
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
