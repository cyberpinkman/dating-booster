from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dating_boost.core.managed_gui_send_common import (
    MESSAGE_SEQUENCE_SECONDS_PER_MESSAGE, ManagedGuiSendError, _now_iso, _read_json,
    _safe_name, _write_json,
)
from dating_boost.core.managed_gui_send_evidence import _managed_gui_send_normalized_evidence


def _managed_sequence_progress_path(work_dir: Path, work_item: dict[str, Any]) -> Path:
    return work_dir / f"managed_sequence_progress.{_safe_name(str(work_item.get('work_item_id') or 'send'))}.json"


def _managed_sequence_visual_confirmation_path(work_dir: Path, work_item: dict[str, Any], message_index: int) -> Path:
    safe_work_id = _safe_name(str(work_item.get("work_item_id") or "send"))
    return work_dir / f"managed_sequence_visual_verification.{safe_work_id}.{int(message_index):02d}.json"


def _managed_sequence_pending_visual_result(message_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    for result in message_results:
        if isinstance(result, dict) and result.get("status") == "visual_verification_pending":
            return result
    return None


def _managed_sequence_message_by_index(messages: list[dict[str, Any]], message_index: int) -> dict[str, Any] | None:
    for message in messages:
        if int(message.get("index") or 0) == int(message_index):
            return message
    return None


def _managed_sequence_visual_confirmation_template(
    work_item: dict[str, Any],
    message: dict[str, Any],
    pending_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action_request_id": work_item.get("action_request_id"),
        "payload_hash": work_item.get("payload_hash"),
        "message_index": int(message.get("index") or 0),
        "message_hash": message.get("message_hash"),
        "post_action_observation_id": pending_result.get("post_action_observation_id") or "",
        "result_status": "unknown",
        "post_send_visible_text": "",
        "evidence": {
            "verification": "Set result_status to succeeded only after a fresh visual post-send observation confirms this exact outbound bubble and an empty input box.",
            "host_visual_outbound_exact_text_verified": False,
            "input_cleared_after_send": False,
            "post_action_screen_captured": False,
        },
    }


def _validate_managed_sequence_visual_confirmation(
    payload: dict[str, Any],
    work_item: dict[str, Any],
    message: dict[str, Any],
) -> str | None:
    if payload.get("action_request_id") != work_item.get("action_request_id"):
        return "managed_sequence_visual_confirmation_action_request_id_mismatch"
    if payload.get("payload_hash") != work_item.get("payload_hash"):
        return "managed_sequence_visual_confirmation_payload_hash_mismatch"
    if int(payload.get("message_index") or 0) != int(message.get("index") or 0):
        return "managed_sequence_visual_confirmation_message_index_mismatch"
    if payload.get("message_hash") != message.get("message_hash"):
        return "managed_sequence_visual_confirmation_message_hash_mismatch"
    if payload.get("result_status") != "succeeded":
        return "managed_sequence_visual_confirmation_not_succeeded"
    visible_text = payload.get("post_send_visible_text")
    if not isinstance(visible_text, str) or not visible_text.strip():
        return "managed_sequence_visual_confirmation_visible_text_missing"
    if visible_text != message.get("text"):
        return "managed_sequence_visual_confirmation_visible_text_mismatch"
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        return "managed_sequence_visual_confirmation_evidence_missing"
    outbound_verified = bool(
        evidence.get("outbound_exact_text_verified")
        or evidence.get("host_visual_outbound_exact_text_verified")
        or evidence.get("outbound_exact_text_visual_verified_by_host")
    )
    if not outbound_verified:
        return "managed_sequence_visual_confirmation_outbound_exact_text_missing"
    if evidence.get("input_cleared_after_send") is not True:
        return "managed_sequence_visual_confirmation_input_cleared_missing"
    if evidence.get("post_action_screen_captured") is not True:
        return "managed_sequence_visual_confirmation_post_screen_missing"
    return None


def _managed_sequence_visual_confirmation_evidence(
    confirmation: dict[str, Any],
    pending_result: dict[str, Any],
) -> dict[str, Any]:
    pending_evidence = pending_result.get("evidence") if isinstance(pending_result.get("evidence"), dict) else {}
    confirmation_evidence = confirmation.get("evidence") if isinstance(confirmation.get("evidence"), dict) else {}
    merged = {**pending_evidence, **confirmation_evidence}
    if (
        confirmation_evidence.get("host_visual_outbound_exact_text_verified")
        or confirmation_evidence.get("outbound_exact_text_visual_verified_by_host")
    ):
        merged["outbound_message_verified"] = True
        merged["outbound_exact_text_verified"] = True
    return _managed_gui_send_normalized_evidence(merged)


def _managed_sequence_window_seconds(message_count: int) -> int:
    return max(1, int(message_count or 1)) * MESSAGE_SEQUENCE_SECONDS_PER_MESSAGE


def _parse_iso_datetime_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _managed_sequence_elapsed_seconds(started_at: Any, *, now_iso: str | None = None) -> float | None:
    started = _parse_iso_datetime_utc(started_at)
    now = _parse_iso_datetime_utc(now_iso or _now_iso())
    if started is None or now is None:
        return None
    return max(0.0, (now - started).total_seconds())


def _managed_sequence_expiry(started_at: Any, *, window_seconds: int) -> dict[str, Any] | None:
    elapsed_seconds = _managed_sequence_elapsed_seconds(started_at)
    if elapsed_seconds is None or elapsed_seconds <= window_seconds:
        return None
    return {
        "message_sequence_started_at": started_at,
        "message_sequence_window_seconds": window_seconds,
        "message_sequence_elapsed_seconds": elapsed_seconds,
    }


def _managed_sequence_remaining_seconds(started_at: Any, *, window_seconds: int) -> float | None:
    elapsed_seconds = _managed_sequence_elapsed_seconds(started_at)
    if elapsed_seconds is None:
        return None
    return max(0.0, float(window_seconds) - elapsed_seconds)


def _managed_sequence_progress_load(path: Path, work_item: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = _read_json(path)
    except (OSError, json.JSONDecodeError, ManagedGuiSendError):
        return {}
    if payload.get("action_request_id") != work_item.get("action_request_id"):
        return {}
    if payload.get("payload_hash") != work_item.get("payload_hash"):
        return {}
    raw_results = payload.get("message_results")
    message_results = [result for result in raw_results if isinstance(result, dict)] if isinstance(raw_results, list) else []
    progress: dict[str, Any] = {"message_results": message_results}
    if isinstance(payload.get("sequence_started_at"), str):
        progress["sequence_started_at"] = payload["sequence_started_at"]
    if isinstance(payload.get("last_message_sent_at"), str):
        progress["last_message_sent_at"] = payload["last_message_sent_at"]
    if isinstance(payload.get("target_binding"), dict):
        progress["target_binding"] = payload["target_binding"]
    return progress


def _managed_sequence_progress_save(
    path: Path,
    work_item: dict[str, Any],
    *,
    message_results: list[dict[str, Any]],
    target_binding: dict[str, Any] | None,
    sequence_started_at: str | None,
    last_message_sent_at: str | None,
    message_sequence_window_seconds: int,
) -> None:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "action_request_id": work_item.get("action_request_id"),
        "work_item_id": work_item.get("work_item_id"),
        "payload_hash": work_item.get("payload_hash"),
        "completed_message_count": _completed_message_count(message_results),
        "sequence_started_at": sequence_started_at,
        "last_message_sent_at": last_message_sent_at,
        "message_sequence_window_seconds": message_sequence_window_seconds,
        "message_results": message_results,
    }
    if isinstance(target_binding, dict):
        payload["target_binding"] = target_binding
    _write_json(path, payload)


def _work_item_payload_messages(work_item: dict[str, Any]) -> list[dict[str, Any]]:
    raw_messages = work_item.get("payload_messages")
    if work_item.get("payload_format") == "message_sequence" and isinstance(raw_messages, list):
        messages = []
        for expected_index, item in enumerate(raw_messages, start=1):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            message_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            messages.append(
                {
                    "index": int(item.get("index") or expected_index),
                    "text": text,
                    "message_hash": str(item.get("message_hash") or message_hash),
                    "character_count": int(item.get("character_count") or len(text)),
                }
            )
        if messages:
            return messages
    text = str(work_item.get("payload_text") or "")
    return [
        {
            "index": 1,
            "text": text,
            "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "character_count": len(text),
        }
    ]


def _work_item_payload_text(work_item: dict[str, Any]) -> str:
    return "\n".join(message["text"] for message in _work_item_payload_messages(work_item))


def _single_message_work_item(work_item: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    text = str(message["text"])
    message_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    single = dict(work_item)
    single["action_request_id"] = f"{work_item.get('action_request_id')}.{int(message['index']):02d}"
    single["payload_text"] = text
    single["payload_hash"] = message_hash
    single["payload_format"] = "single_message"
    single["payload_messages"] = [
        {
            "index": 1,
            "text": text,
            "message_hash": message_hash,
            "character_count": len(text),
        }
    ]
    single["message_count"] = 1
    binding = single.get("autonomous_audit_binding")
    if isinstance(binding, dict):
        updated_binding = dict(binding)
        updated_binding["payload_hash"] = message_hash
        single["autonomous_audit_binding"] = updated_binding
    return single


def _completed_message_count(message_results: list[dict[str, Any]]) -> int:
    return sum(1 for result in message_results if result.get("status") == "ok")


def _validate_action_result(payload: dict[str, Any], work_item: dict[str, Any]) -> None:
    if payload.get("action_request_id") != work_item.get("action_request_id"):
        raise ManagedGuiSendError("action_result action_request_id mismatch")
    if payload.get("payload_hash") != work_item.get("payload_hash"):
        raise ManagedGuiSendError("action_result payload_hash mismatch")
    if payload.get("target_match_id") != work_item.get("match_id"):
        raise ManagedGuiSendError("action_result target_match_id mismatch")
