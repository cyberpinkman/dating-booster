from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from dating_boost.core.storage import JsonStorage
from dating_boost.policy import Action


ACTION_RESULT_SCHEMA_VERSION = 1
ACTION_RESULTS_PATH = Path("audit") / "action_results.jsonl"
RESULT_STATUSES = {"succeeded", "failed", "unknown"}
REQUIRED_ACTION_RESULT_FIELDS = (
    "action",
    "target_match_id",
    "payload_hash",
    "pre_action_observation_id",
    "post_action_observation_id",
    "result_status",
    "evidence",
)
VERIFIABLE_SUCCESS_ACTIONS = {Action.SEND_MESSAGE.value}


class ActionAuditRepository:
    def __init__(self, root: Path):
        self._storage = JsonStorage(root)

    def append_action_result(self, payload: dict[str, Any], *, created_at: str) -> dict[str, Any]:
        event = validate_action_result(payload, created_at=created_at)
        self._storage.append_jsonl(ACTION_RESULTS_PATH, event)
        return event


def validate_action_result(payload: dict[str, Any], *, created_at: str) -> dict[str, Any]:
    missing = [field for field in REQUIRED_ACTION_RESULT_FIELDS if field not in payload]
    if missing:
        raise ValueError(f"action result missing required field(s): {', '.join(missing)}")

    action = _require_action(payload["action"])
    target_match_id = _require_non_empty_string(payload["target_match_id"], "target_match_id")
    payload_hash = _require_non_empty_string(payload["payload_hash"], "payload_hash")
    pre_observation_id = _require_nullable_string(
        payload["pre_action_observation_id"],
        "pre_action_observation_id",
    )
    post_observation_id = _require_nullable_string(
        payload["post_action_observation_id"],
        "post_action_observation_id",
    )
    result_status = _require_result_status(payload["result_status"])
    evidence = _require_evidence(payload["evidence"])
    raw_action_request_id = payload.get("action_request_id")
    if action in VERIFIABLE_SUCCESS_ACTIONS:
        action_request_id = _require_non_empty_string(raw_action_request_id, "action_request_id")
    elif raw_action_request_id is None:
        action_request_id = None
    else:
        action_request_id = _require_non_empty_string(raw_action_request_id, "action_request_id")

    if result_status == "succeeded" and action in VERIFIABLE_SUCCESS_ACTIONS and not post_observation_id:
        raise ValueError("succeeded send_message results require post_action_observation_id evidence")

    base_event = {
        "schema_version": ACTION_RESULT_SCHEMA_VERSION,
        "action": action,
        "target_match_id": target_match_id,
        "action_request_id": action_request_id,
        "payload_hash": payload_hash,
        "pre_action_observation_id": pre_observation_id,
        "post_action_observation_id": post_observation_id,
        "result_status": result_status,
        "evidence": evidence,
        "created_at": created_at,
    }
    return {
        "event_id": f"action_result_{_event_digest(base_event)}",
        **base_event,
    }


def _require_action(value: Any) -> str:
    action = _require_non_empty_string(value, "action")
    try:
        return Action(action).value
    except ValueError as exc:
        allowed = ", ".join(item.value for item in Action)
        raise ValueError(f"action must be one of: {allowed}") from exc


def _require_result_status(value: Any) -> str:
    status = _require_non_empty_string(value, "result_status")
    if status not in RESULT_STATUSES:
        raise ValueError("result_status must be one of: succeeded, failed, unknown")
    return status


def _require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    if label == "target_match_id" and (value in {"", ".", ".."} or "/" in value or "\\" in value):
        raise ValueError(f"invalid target_match_id: {value!r}")
    return value


def _require_nullable_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string or null")
    return value


def _require_evidence(value: Any) -> Any:
    if isinstance(value, str):
        if not value.strip():
            raise ValueError("evidence must be non-empty")
        return value
    if isinstance(value, list):
        if not value:
            raise ValueError("evidence must be non-empty")
        return value
    if isinstance(value, dict):
        if not value:
            raise ValueError("evidence must be non-empty")
        return value
    raise ValueError("evidence must be a non-empty string, object, or array")


def _event_digest(event: dict[str, Any]) -> str:
    canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
