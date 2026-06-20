from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from dating_boost.core.action_audit import ActionAuditRepository
from dating_boost.core.operator import OperatorRepository


class StandaloneActionExecutor(Protocol):
    def execute(self, work_item: dict[str, Any], *, app_id: str) -> dict[str, Any]:
        raise NotImplementedError


class StageOnlyActionExecutor:
    def __init__(self, root: Path, *, send_mode: str = "stage"):
        self.root = root
        self.send_mode = send_mode

    def execute(self, work_item: dict[str, Any], *, app_id: str) -> dict[str, Any]:
        if self.send_mode not in {"stage", "live"}:
            return {
                "schema_version": 1,
                "status": "blocked",
                "reason": "unsupported_send_mode",
                "send_mode": self.send_mode,
            }
        block_reason = _send_work_item_block_reason(work_item)
        if block_reason:
            return {
                "schema_version": 1,
                "status": "blocked",
                "reason": block_reason,
                "action_request_id": work_item.get("action_request_id"),
            }
        if self.send_mode == "live":
            return {
                "schema_version": 1,
                "status": "needs_live_executor",
                "action_request_id": work_item.get("action_request_id"),
                "next_host_action": "enable_managed_gui_send_or_switch_to_stage",
            }
        try:
            payload = _stage_payload(work_item, app_id=app_id)
            operator_recorded = _record_with_operator_if_active(self.root, payload)
            if operator_recorded is None:
                event = ActionAuditRepository(self.root).append_stage_result(payload, created_at=_now_iso())
                operator_recorded = {"status": "skipped", "reason": "operator_session_not_active"}
            else:
                event = operator_recorded
        except Exception as exc:  # noqa: BLE001 - action execution must return a structured wait point.
            return {
                "schema_version": 1,
                "status": "blocked",
                "reason": "stage_result_failed",
                "error_type": type(exc).__name__,
                "action_request_id": work_item.get("action_request_id"),
            }
        return {
            "schema_version": 1,
            "status": "stage_recorded",
            "action_request_id": payload["action_request_id"],
            "result_status": payload["result_status"],
            "recorded": event,
            "operator_recorded": operator_recorded,
        }


class StandaloneManagedGuiSendExecutor:
    def __init__(self, root: Path):
        self.root = root

    def execute(self, work_item: dict[str, Any], *, app_id: str) -> dict[str, Any]:
        block_reason = _send_work_item_block_reason(work_item)
        if block_reason:
            return {
                "schema_version": 1,
                "status": "blocked",
                "reason": block_reason,
                "action_request_id": work_item.get("action_request_id"),
            }
        return {
            "schema_version": 1,
            "status": "blocked",
            "reason": "standalone_live_gui_send_not_enabled",
            "action_request_id": work_item.get("action_request_id"),
            "app_id": app_id,
            "next_host_action": "use_host_loop_live_send_or_stage_mode",
        }


def _stage_payload(work_item: dict[str, Any], *, app_id: str) -> dict[str, Any]:
    text = str(work_item.get("payload_text") or "")
    action_request_id = _required_str(work_item.get("action_request_id"))
    target_match_id = _required_str(work_item.get("target_match_id") or work_item.get("match_id"))
    payload_hash = _required_str(work_item.get("payload_hash")) or _sha256(text)
    return {
        "schema_version": 1,
        "action": "send_message",
        "app_id": app_id,
        "action_request_id": action_request_id,
        "target_match_id": target_match_id,
        "payload_hash": payload_hash,
        "pre_action_observation_id": work_item.get("pre_action_observation_id"),
        "result_status": "succeeded",
        "evidence": {
            "stage_mode": True,
            "draft_text_hash": _sha256(text),
            "live_send_executed": False,
        },
    }


def _send_work_item_block_reason(work_item: dict[str, Any]) -> str | None:
    if not _required_str(work_item.get("action_request_id")):
        return "invalid_send_work_item:action_request_id"
    if not _required_str(work_item.get("target_match_id") or work_item.get("match_id")):
        return "invalid_send_work_item:target_match_id"
    if not _required_str(work_item.get("payload_hash")) and not _required_str(work_item.get("payload_text")):
        return "invalid_send_work_item:payload"
    return None


def _required_str(value: Any) -> str:
    return str(value or "").strip()


def _record_with_operator_if_active(root: Path, payload: dict[str, Any]) -> dict[str, Any] | None:
    operator = OperatorRepository(root)
    state = operator.get_state_payload()
    session = state.get("operator_session") if isinstance(state.get("operator_session"), dict) else None
    if not isinstance(session, dict) or session.get("status") != "active":
        return None
    return operator.record_stage_result(payload)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
