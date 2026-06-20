from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from dating_boost.apps.registry import host_loop_app_ids, manifest_for_app
from dating_boost.core.live_send_contract import validate_live_send_contract
from dating_boost.core.safety import SafetyRepository


MESSAGE_SEQUENCE_SECONDS_PER_MESSAGE = 20


class ManagedGuiSendError(RuntimeError):
    pass


class ManagedGuiSendArgsPort(Protocol):
    app_id: str
    harness_runtime: str | None


class ManagedGuiSendHostPort(Protocol):
    args: ManagedGuiSendArgsPort
    data_dir: Path
    work_dir: Path
    staged_verifications: list[dict[str, Any]]
    action_results_recorded: list[dict[str, Any]]

    def _finish(
        self,
        status: str,
        reason: str,
        *,
        current: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _runtime_live_send_block_reason(self) -> str | None:
        raise NotImplementedError

    def _target_profile_block_reason(self, work_item: dict[str, Any]) -> str | None:
        raise NotImplementedError

    def _authorization_path(self) -> Path:
        raise NotImplementedError

    def _live_send_action_request(self, work_item: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def _run_cli_json(
        self,
        *args: str,
        allow_error: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _append_timeline(
        self,
        event_type: str,
        work_item: dict[str, Any] | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        raise NotImplementedError

    def _work_file(self, work_item: dict[str, Any], kind: str) -> Path:
        raise NotImplementedError

    def _clear_host_work_item(self, work_item: dict[str, Any], *, consume: bool = False) -> None:
        raise NotImplementedError


class ManagedGuiSendRunner:
    """Host-loop managed live-send transaction runner.

    The host object supplies orchestration side effects: finish states, CLI
    invocation, timeline writes, work-file paths, and action-result recording.
    This keeps app/session transaction logic out of host_loop.py without
    creating a separate generic sender that hides app-specific harness behavior.
    """

    def __init__(self, host: ManagedGuiSendHostPort):
        self.host = host

    def handle(self, work_item: dict[str, Any]) -> dict[str, Any] | None:
        host = self.host
        app_id = str(host.args.app_id)
        if app_id not in set(host_loop_app_ids()):
            return host._finish("blocked", f"managed_gui_send_not_supported_for_app:{app_id}", current=work_item)
        runtime_block = host._runtime_live_send_block_reason()
        if runtime_block is not None:
            return host._finish("blocked", runtime_block, current=work_item)
        target_profile_block = host._target_profile_block_reason(work_item)
        if target_profile_block is not None:
            return host._finish(
                "blocked",
                target_profile_block,
                current=work_item,
                extra={"next_host_action": "open_target_profile_and_ingest_memory"},
            )
        if SafetyRepository(host.data_dir).is_paused():
            return host._finish("blocked", "safety_paused", current=work_item)

        authorization_path = host._authorization_path()
        authorization = _read_json(authorization_path)
        action_request = host._live_send_action_request(work_item)
        contract_reason = validate_live_send_contract(
            authorization,
            action_request,
            app_id=app_id,
            draft_text=_work_item_payload_text(work_item),
            data_dir=host.data_dir,
        )
        if contract_reason is not None:
            return host._finish("blocked", contract_reason, current=work_item)

        payload_messages = _work_item_payload_messages(work_item)
        sequence_timing_enabled = len(payload_messages) > 1
        message_sequence_window_seconds = _managed_sequence_window_seconds(len(payload_messages))
        progress_path = _managed_sequence_progress_path(host.work_dir, work_item)
        result_path = host._work_file(work_item, "action_result")
        if result_path.exists():
            result = _read_json(result_path)
            _validate_action_result(result, work_item)
            recorded = host._run_cli_json(
                "operator",
                "record-action-result",
                "--data-dir",
                str(host.data_dir),
                "--input",
                str(result_path),
            )
            host.action_results_recorded.append(recorded)
            host._append_timeline("action_result", work_item, {"path": str(result_path), "recorded": recorded})
            if progress_path.exists():
                progress_path.unlink()
            host._clear_host_work_item(work_item, consume=True)
            return None

        sequence_progress = _managed_sequence_progress_load(progress_path, work_item)
        harness_payloads: list[dict[str, Any]] = []
        message_results: list[dict[str, Any]] = list(sequence_progress.get("message_results") or [])
        sequence_started_at = str(sequence_progress.get("sequence_started_at") or "")
        sequence_last_sent_at = str(sequence_progress.get("last_message_sent_at") or "")
        completed_indices = {
            int(result.get("index") or 0)
            for result in message_results
            if isinstance(result, dict) and result.get("status") == "ok"
        }
        harness_runtime = str(getattr(host.args, "harness_runtime", "") or "").strip()
        required_evidence = _managed_gui_send_required_evidence(app_id, harness_runtime)
        sequence_work_item = dict(work_item)
        if isinstance(sequence_progress.get("target_binding"), dict):
            sequence_work_item["target_binding"] = sequence_progress["target_binding"]

        pending_result = _handle_pending_visual_confirmation(
            host,
            work_item,
            payload_messages,
            message_results,
            sequence_work_item=sequence_work_item,
            sequence_timing_enabled=sequence_timing_enabled,
            sequence_started_at=sequence_started_at,
            sequence_last_sent_at=sequence_last_sent_at,
            message_sequence_window_seconds=message_sequence_window_seconds,
            progress_path=progress_path,
        )
        if isinstance(pending_result, dict) and pending_result.get("__return__") is True:
            return pending_result.get("payload")
        if isinstance(pending_result, dict):
            sequence_started_at = str(pending_result.get("sequence_started_at") or sequence_started_at)
            sequence_last_sent_at = str(pending_result.get("sequence_last_sent_at") or sequence_last_sent_at)

        completed_indices = {
            int(result.get("index") or 0)
            for result in message_results
            if isinstance(result, dict) and result.get("status") == "ok"
        }
        for message in payload_messages:
            if int(message["index"]) in completed_indices:
                continue
            if sequence_timing_enabled and completed_indices and not sequence_started_at:
                return host._finish(
                    "blocked",
                    "message_sequence_window_unverifiable",
                    current=work_item,
                    extra={
                        "message_sequence_window_seconds": message_sequence_window_seconds,
                        "completed_message_count": _completed_message_count(message_results),
                        "failed_message_index": message.get("index"),
                        "message_results": message_results,
                        "next_host_action": "observe_current_thread_and_replan_sequence",
                    },
                )
            if sequence_timing_enabled:
                expired = _managed_sequence_expiry(
                    sequence_started_at,
                    window_seconds=message_sequence_window_seconds,
                )
                if expired is not None:
                    return host._finish(
                        "blocked",
                        "message_sequence_window_expired",
                        current=work_item,
                        extra={
                            **expired,
                            "completed_message_count": _completed_message_count(message_results),
                            "failed_message_index": message.get("index"),
                            "message_results": message_results,
                            "next_host_action": "observe_current_thread_and_replan_sequence",
                        },
                    )
            if sequence_timing_enabled and not sequence_started_at:
                sequence_started_at = _now_iso()
                _managed_sequence_progress_save(
                    progress_path,
                    work_item,
                    message_results=message_results,
                    target_binding=sequence_work_item.get("target_binding")
                    if isinstance(sequence_work_item.get("target_binding"), dict)
                    else None,
                    sequence_started_at=sequence_started_at,
                    last_message_sent_at=sequence_last_sent_at or None,
                    message_sequence_window_seconds=message_sequence_window_seconds,
                )
            remaining_seconds = None
            if sequence_timing_enabled:
                remaining_seconds = _managed_sequence_remaining_seconds(
                    sequence_started_at,
                    window_seconds=message_sequence_window_seconds,
                )
                if remaining_seconds is not None and remaining_seconds <= 0:
                    return host._finish(
                        "blocked",
                        "message_sequence_window_expired",
                        current=work_item,
                        extra={
                            "message_sequence_started_at": sequence_started_at,
                            "message_sequence_window_seconds": message_sequence_window_seconds,
                            "message_sequence_elapsed_seconds": message_sequence_window_seconds,
                            "completed_message_count": _completed_message_count(message_results),
                            "failed_message_index": message.get("index"),
                            "message_results": message_results,
                            "next_host_action": "observe_current_thread_and_replan_sequence",
                        },
                    )

            harness_payload = _send_single_message_via_harness(
                host,
                work_item,
                sequence_work_item,
                message,
                authorization_path=authorization_path,
                harness_runtime=harness_runtime,
                remaining_seconds=remaining_seconds,
            )
            harness_payloads.append(harness_payload)
            message_work_item = _single_message_work_item(sequence_work_item, message)
            message_result = _managed_gui_send_message_result(message, harness_payload)
            message_results.append(message_result)
            host._append_timeline(
                "managed_gui_send",
                message_work_item,
                {"harness": _redacted_managed_send_payload(harness_payload)},
            )
            harness_evidence = _managed_gui_send_normalized_evidence(
                harness_payload.get("evidence") if isinstance(harness_payload.get("evidence"), dict) else {}
            )
            visual_wait = _handle_harness_visual_wait(
                host,
                work_item,
                message,
                message_results,
                sequence_work_item=sequence_work_item,
                harness_payload=harness_payload,
                harness_evidence=harness_evidence,
                sequence_timing_enabled=sequence_timing_enabled,
                sequence_started_at=sequence_started_at,
                sequence_last_sent_at=sequence_last_sent_at,
                message_sequence_window_seconds=message_sequence_window_seconds,
                progress_path=progress_path,
                result_path=result_path,
            )
            if isinstance(visual_wait, dict) and visual_wait.get("__return__") is True:
                return visual_wait.get("payload")
            if isinstance(visual_wait, dict):
                sequence_last_sent_at = str(visual_wait.get("sequence_last_sent_at") or sequence_last_sent_at)
            if harness_payload.get("status") == "needs_host_visual_verification":
                continue
            if harness_payload.get("status") != "ok":
                return host._finish(
                    "blocked",
                    str(harness_payload.get("reason") or "managed_gui_send_failed"),
                    current=work_item,
                    extra={
                        "managed_gui_send": _redacted_managed_send_payload(harness_payload),
                        "completed_message_count": max(len(message_results) - 1, 0),
                        "failed_message_index": message.get("index"),
                        "message_results": message_results,
                    },
                )
            if not harness_payload.get("post_action_observation_id"):
                return host._finish(
                    "blocked",
                    "post_action_observation_required",
                    current=work_item,
                    extra={
                        "managed_gui_send": _redacted_managed_send_payload(harness_payload),
                        "completed_message_count": max(len(message_results) - 1, 0),
                        "failed_message_index": message.get("index"),
                        "message_results": message_results,
                    },
                )
            required_for_payload = _managed_gui_send_required_evidence_for_payload(required_evidence, harness_payload)
            if any(harness_evidence.get(key) is not True for key in required_for_payload):
                return host._finish(
                    "blocked",
                    "managed_gui_send_verification_incomplete",
                    current=work_item,
                    extra={
                        "managed_gui_send": _redacted_managed_send_payload(harness_payload),
                        "completed_message_count": max(len(message_results) - 1, 0),
                        "failed_message_index": message.get("index"),
                        "message_results": message_results,
                    },
                )
            sent_at = _now_iso()
            sequence_last_sent_at = sent_at
            message_results[-1]["evidence"] = _managed_gui_send_message_evidence(harness_evidence)
            message_results[-1]["sent_at"] = sent_at
            sequence_work_item["target_binding"] = _managed_gui_send_refreshed_target_binding(
                sequence_work_item.get("target_binding")
                if isinstance(sequence_work_item.get("target_binding"), dict)
                else None,
                harness_payload,
            )
            _managed_sequence_progress_save(
                progress_path,
                work_item,
                message_results=message_results,
                target_binding=sequence_work_item.get("target_binding")
                if isinstance(sequence_work_item.get("target_binding"), dict)
                else None,
                sequence_started_at=sequence_started_at,
                last_message_sent_at=sequence_last_sent_at,
                message_sequence_window_seconds=message_sequence_window_seconds,
            )

        return _finish_successful_managed_gui_send(
            host,
            work_item,
            payload_messages=payload_messages,
            message_results=message_results,
            harness_payloads=harness_payloads,
            sequence_started_at=sequence_started_at,
            sequence_last_sent_at=sequence_last_sent_at,
            message_sequence_window_seconds=message_sequence_window_seconds,
            progress_path=progress_path,
        )


def _handle_pending_visual_confirmation(
    host: ManagedGuiSendHostPort,
    work_item: dict[str, Any],
    payload_messages: list[dict[str, Any]],
    message_results: list[dict[str, Any]],
    *,
    sequence_work_item: dict[str, Any],
    sequence_timing_enabled: bool,
    sequence_started_at: str,
    sequence_last_sent_at: str,
    message_sequence_window_seconds: int,
    progress_path: Path,
) -> dict[str, Any] | None:
    pending_visual_result = _managed_sequence_pending_visual_result(message_results)
    if pending_visual_result is None:
        return None
    pending_message = _managed_sequence_message_by_index(
        payload_messages,
        int(pending_visual_result.get("index") or 0),
    )
    if pending_message is None:
        return {
            "__return__": True,
            "payload": host._finish(
                "blocked",
                "message_sequence_pending_visual_message_missing",
                current=work_item,
                extra={
                    "completed_message_count": _completed_message_count(message_results),
                    "message_results": message_results,
                    "next_host_action": "observe_current_thread_and_replan_sequence",
                },
            ),
        }
    visual_confirmation_path = _managed_sequence_visual_confirmation_path(
        host.work_dir,
        work_item,
        int(pending_message["index"]),
    )
    if sequence_timing_enabled:
        expired = _managed_sequence_expiry(
            sequence_started_at,
            window_seconds=message_sequence_window_seconds,
        )
        if expired is not None and not visual_confirmation_path.exists():
            return {
                "__return__": True,
                "payload": host._finish(
                    "blocked",
                    "message_sequence_window_expired",
                    current=work_item,
                    extra={
                        **expired,
                        "completed_message_count": _completed_message_count(message_results),
                        "failed_message_index": pending_message.get("index"),
                        "message_results": message_results,
                        "next_host_action": "observe_current_thread_and_replan_sequence",
                    },
                ),
            }
    if not visual_confirmation_path.exists():
        _write_json(
            _template_path(visual_confirmation_path),
            _managed_sequence_visual_confirmation_template(work_item, pending_message, pending_visual_result),
        )
        return {
            "__return__": True,
            "payload": host._finish(
                "waiting_for_host",
                "outbound_message_requires_visual_verification",
                current=work_item,
                extra={
                    "expected_input": str(visual_confirmation_path),
                    "next_host_action": "visually_verify_sequence_outbound_message_and_resume",
                    "completed_message_count": _completed_message_count(message_results),
                    "pending_message_index": pending_message.get("index"),
                    "message_results": message_results,
                },
            ),
        }
    visual_confirmation = _read_json(visual_confirmation_path)
    validation_reason = _validate_managed_sequence_visual_confirmation(
        visual_confirmation,
        work_item,
        pending_message,
    )
    if validation_reason is not None:
        return {
            "__return__": True,
            "payload": host._finish(
                "blocked",
                validation_reason,
                current=work_item,
                extra={
                    "expected_input": str(visual_confirmation_path),
                    "completed_message_count": _completed_message_count(message_results),
                    "failed_message_index": pending_message.get("index"),
                    "message_results": message_results,
                },
            ),
        }
    confirmation_evidence = _managed_sequence_visual_confirmation_evidence(
        visual_confirmation,
        pending_visual_result,
    )
    pending_visual_result["status"] = "ok"
    pending_visual_result["post_action_observation_id"] = (
        visual_confirmation.get("post_action_observation_id")
        or pending_visual_result.get("post_action_observation_id")
    )
    pending_visual_result["evidence"] = _managed_gui_send_message_evidence(confirmation_evidence)
    pending_visual_result["sent_at"] = str(
        pending_visual_result.get("sent_at")
        or visual_confirmation.get("confirmed_at")
        or _now_iso()
    )
    pending_visual_result["host_visual_verification"] = {
        "status": "ok",
        "path": str(visual_confirmation_path),
    }
    sequence_last_sent_at = str(pending_visual_result.get("sent_at") or sequence_last_sent_at or "")
    if visual_confirmation_path.exists():
        visual_confirmation_path.unlink()
    _managed_sequence_progress_save(
        progress_path,
        work_item,
        message_results=message_results,
        target_binding=sequence_work_item.get("target_binding")
        if isinstance(sequence_work_item.get("target_binding"), dict)
        else None,
        sequence_started_at=sequence_started_at,
        last_message_sent_at=sequence_last_sent_at or None,
        message_sequence_window_seconds=message_sequence_window_seconds,
    )
    return {
        "sequence_started_at": sequence_started_at,
        "sequence_last_sent_at": sequence_last_sent_at,
    }


def _send_single_message_via_harness(
    host: ManagedGuiSendHostPort,
    work_item: dict[str, Any],
    sequence_work_item: dict[str, Any],
    message: dict[str, Any],
    *,
    authorization_path: Path,
    harness_runtime: str,
    remaining_seconds: float | None,
) -> dict[str, Any]:
    message_work_item = _single_message_work_item(sequence_work_item, message)
    message_action_request = host._live_send_action_request(message_work_item)
    draft_path = host.work_dir / (
        f"managed_payload.{_safe_name(str(work_item.get('work_item_id') or 'send'))}."
        f"{int(message['index']):02d}.txt"
    )
    action_request_path = host.work_dir / (
        f"managed_action_request.{_safe_name(str(work_item.get('work_item_id') or 'send'))}."
        f"{int(message['index']):02d}.json"
    )
    draft_path.write_text(str(message["text"]), encoding="utf-8")
    _write_json(action_request_path, message_action_request)
    command_args = [
        "harness",
        host.args.app_id,
        "send-message",
        "--data-dir",
        str(host.data_dir),
        "--authorization",
        str(authorization_path),
        "--text-file",
        str(draft_path),
        "--action-request",
        str(action_request_path),
        "--output-dir",
        str(host.work_dir / "harness"),
        "--json",
    ]
    if harness_runtime:
        command_args[3:3] = ["--runtime", harness_runtime]
    try:
        harness_payload = host._run_cli_json(
            *command_args,
            allow_error=True,
            timeout_seconds=remaining_seconds,
        )
    finally:
        if draft_path.exists():
            draft_path.unlink()
        if action_request_path.exists():
            action_request_path.unlink()

    harness_payload["message_sequence_index"] = message["index"]
    harness_payload["message_sequence_count"] = len(_work_item_payload_messages(work_item))
    return harness_payload


def _handle_harness_visual_wait(
    host: ManagedGuiSendHostPort,
    work_item: dict[str, Any],
    message: dict[str, Any],
    message_results: list[dict[str, Any]],
    *,
    sequence_work_item: dict[str, Any],
    harness_payload: dict[str, Any],
    harness_evidence: dict[str, Any],
    sequence_timing_enabled: bool,
    sequence_started_at: str,
    sequence_last_sent_at: str,
    message_sequence_window_seconds: int,
    progress_path: Path,
    result_path: Path,
) -> dict[str, Any] | None:
    if harness_payload.get("status") != "needs_host_visual_verification":
        return None
    reason = str(harness_payload.get("reason") or "visual_verification_required")
    if reason == "outbound_message_requires_visual_verification" and sequence_timing_enabled:
        sent_at = _now_iso()
        message_results[-1]["status"] = "visual_verification_pending"
        message_results[-1]["sent_at"] = sent_at
        message_results[-1]["evidence"] = _managed_gui_send_message_evidence(harness_evidence)
        if isinstance(harness_payload.get("visual_verification_request"), dict):
            message_results[-1]["visual_verification_request"] = harness_payload.get("visual_verification_request")
        sequence_last_sent_at = sent_at
        sequence_work_item["target_binding"] = _managed_gui_send_refreshed_target_binding(
            sequence_work_item.get("target_binding")
            if isinstance(sequence_work_item.get("target_binding"), dict)
            else None,
            harness_payload,
        )
        visual_confirmation_path = _managed_sequence_visual_confirmation_path(
            host.work_dir,
            work_item,
            int(message["index"]),
        )
        _write_json(
            _template_path(visual_confirmation_path),
            _managed_sequence_visual_confirmation_template(work_item, message, message_results[-1]),
        )
        _managed_sequence_progress_save(
            progress_path,
            work_item,
            message_results=message_results,
            target_binding=sequence_work_item.get("target_binding")
            if isinstance(sequence_work_item.get("target_binding"), dict)
            else None,
            sequence_started_at=sequence_started_at,
            last_message_sent_at=sequence_last_sent_at,
            message_sequence_window_seconds=message_sequence_window_seconds,
        )
        return {
            "__return__": True,
            "payload": host._finish(
                "waiting_for_host",
                reason,
                current=work_item,
                extra={
                    "expected_input": str(visual_confirmation_path),
                    "next_host_action": "visually_verify_sequence_outbound_message_and_resume",
                    "managed_gui_send": _redacted_managed_send_payload(harness_payload),
                    "completed_message_count": _completed_message_count(message_results),
                    "pending_message_index": message.get("index"),
                    "message_results": message_results,
                },
            ),
        }
    return {
        "__return__": True,
        "payload": host._finish(
            "waiting_for_host",
            reason,
            current=work_item,
            extra={
                "expected_input": str(result_path) if reason == "outbound_message_requires_visual_verification" else None,
                "managed_gui_send": _redacted_managed_send_payload(harness_payload),
                "completed_message_count": max(len(message_results) - 1, 0),
                "failed_message_index": message.get("index"),
                "message_results": message_results,
            },
        ),
    }


def _finish_successful_managed_gui_send(
    host: ManagedGuiSendHostPort,
    work_item: dict[str, Any],
    *,
    payload_messages: list[dict[str, Any]],
    message_results: list[dict[str, Any]],
    harness_payloads: list[dict[str, Any]],
    sequence_started_at: str,
    sequence_last_sent_at: str,
    message_sequence_window_seconds: int,
    progress_path: Path,
) -> dict[str, Any] | None:
    if not message_results:
        return host._finish("blocked", "managed_gui_send_no_message_results", current=work_item)
    final_harness_payload = harness_payloads[-1] if harness_payloads else {}
    final_evidence = _managed_gui_send_normalized_evidence(
        final_harness_payload.get("evidence") if isinstance(final_harness_payload.get("evidence"), dict) else {}
    )
    if not final_evidence:
        final_evidence = {
            key: bool(value)
            for key, value in (
                message_results[-1].get("evidence") if isinstance(message_results[-1].get("evidence"), dict) else {}
            ).items()
        }
    sequence_elapsed_seconds = _managed_sequence_elapsed_seconds(
        sequence_started_at,
        now_iso=sequence_last_sent_at or _now_iso(),
    )
    verification = {
        "status": "ok",
        "action_request_id": work_item.get("action_request_id"),
        "payload_hash": work_item.get("payload_hash"),
        "verification_method": f"managed_{host.args.app_id}_gui_send",
    }
    host.staged_verifications.append(verification)
    result_payload = {
        "action_request_id": work_item.get("action_request_id"),
        "action": "send_message",
        "target_match_id": work_item.get("match_id"),
        "payload_hash": work_item.get("payload_hash"),
        "precondition_hash": work_item.get("precondition_hash"),
        "autonomous_audit_binding": work_item.get("autonomous_audit_binding"),
        "pre_action_observation_id": work_item.get("pre_action_observation_id"),
        "post_action_observation_id": message_results[-1].get("post_action_observation_id"),
        "result_status": "succeeded",
        "message_count": len(payload_messages),
        "payload_format": "message_sequence" if len(payload_messages) > 1 else "single_message",
        "message_sequence_started_at": sequence_started_at or None,
        "message_sequence_last_sent_at": sequence_last_sent_at or None,
        "message_sequence_window_seconds": message_sequence_window_seconds,
        "message_sequence_elapsed_seconds": sequence_elapsed_seconds,
        "message_results": message_results,
        "evidence": {
            "managed_gui_send": True,
            "message_sequence_send": len(payload_messages) > 1,
            "message_sequence_within_window": (
                sequence_elapsed_seconds is None
                or sequence_elapsed_seconds <= message_sequence_window_seconds
            ),
            **final_evidence,
        },
    }
    result_path = host._work_file(work_item, "action_result")
    _write_json(result_path, result_payload)
    recorded = host._run_cli_json(
        "operator",
        "record-action-result",
        "--data-dir",
        str(host.data_dir),
        "--input",
        str(result_path),
    )
    host.action_results_recorded.append(recorded)
    host._append_timeline("action_result", work_item, {"path": str(result_path), "recorded": recorded})
    if progress_path.exists():
        progress_path.unlink()
    host._clear_host_work_item(work_item, consume=True)
    return None


def _redacted_managed_send_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "status",
        "reason",
        "app_id",
        "action",
        "mode",
        "draft_fingerprint",
        "draft_character_count",
        "staged_text_verification",
        "post_send_verification",
        "post_action_observation_id",
        "evidence",
        "clipboard_restored",
        "next_host_action",
        "visual_verification_request",
        "current_thread_visual_anchor",
        "message_sequence_index",
        "message_sequence_count",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _managed_gui_send_normalized_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(evidence)
    normalized["staged_exact_text_verified"] = bool(
        evidence.get("staged_exact_text_verified")
        or evidence.get("staged_exact_text_ax_verified")
        or evidence.get("staged_exact_text_ocr_verified")
    )
    normalized["outbound_exact_text_verified"] = bool(
        evidence.get("outbound_exact_text_verified")
        or evidence.get("outbound_exact_text_ax_verified")
        or evidence.get("outbound_exact_text_ocr_verified")
    )
    return normalized


def _managed_gui_send_message_evidence(evidence: dict[str, Any]) -> dict[str, bool]:
    return {
        "staged_text_verified": bool(evidence.get("staged_text_verified")),
        "staged_exact_text_verified": bool(evidence.get("staged_exact_text_verified")),
        "input_cleared_after_send": bool(evidence.get("input_cleared_after_send")),
        "post_action_screen_captured": bool(evidence.get("post_action_screen_captured")),
        "outbound_message_verified": bool(evidence.get("outbound_message_verified")),
        "outbound_exact_text_verified": bool(evidence.get("outbound_exact_text_verified")),
    }


def _managed_gui_send_message_result(message: dict[str, Any], harness_payload: dict[str, Any]) -> dict[str, Any]:
    evidence = _managed_gui_send_normalized_evidence(
        harness_payload.get("evidence") if isinstance(harness_payload.get("evidence"), dict) else {}
    )
    result = {
        "index": int(message.get("index") or 0),
        "message_hash": str(message.get("message_hash") or ""),
        "character_count": int(message.get("character_count") or 0),
        "post_action_observation_id": harness_payload.get("post_action_observation_id"),
        "status": harness_payload.get("status"),
        "evidence": _managed_gui_send_message_evidence(evidence),
    }
    if harness_payload.get("already_sent") is True:
        result["already_sent"] = True
    if harness_payload.get("reason"):
        result["reason"] = harness_payload.get("reason")
    return result


def _managed_gui_send_required_evidence_for_payload(
    required_evidence: tuple[str, ...],
    harness_payload: dict[str, Any],
) -> tuple[str, ...]:
    if harness_payload.get("already_sent") is not True:
        return required_evidence
    return tuple(
        key
        for key in required_evidence
        if key not in {"staged_text_verified", "staged_exact_text_verified", "staged_exact_text_ocr_verified"}
    )


def _managed_gui_send_refreshed_target_binding(
    target_binding: dict[str, Any] | None,
    harness_payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(target_binding, dict):
        return target_binding
    anchor = harness_payload.get("current_thread_visual_anchor")
    if not isinstance(anchor, dict) or anchor.get("status") != "ok":
        return target_binding
    visual_hash = str(anchor.get("visual_anchor_hash") or "").strip()
    if not visual_hash:
        return target_binding

    refreshed = dict(target_binding)
    thread_evidence = (
        dict(refreshed.get("thread_evidence"))
        if isinstance(refreshed.get("thread_evidence"), dict)
        else {}
    )
    thread_evidence["visual_anchor_hash"] = visual_hash
    if isinstance(anchor.get("visual_anchor_region"), dict):
        thread_evidence["visual_anchor_region"] = anchor.get("visual_anchor_region")
    thread_evidence["screen_state"] = str(anchor.get("screen_state") or thread_evidence.get("screen_state") or "tashuo_conversation")
    if harness_payload.get("post_action_observation_id"):
        thread_evidence["observation_id"] = harness_payload.get("post_action_observation_id")
    refreshed["thread_evidence"] = thread_evidence
    return refreshed


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


def _managed_gui_send_required_evidence(app_id: str, runtime: str | None = None) -> tuple[str, ...]:
    manifest = manifest_for_app(app_id)
    runtime_key = _normalized_harness_runtime(str(runtime or ""))
    if runtime_key and runtime_key != "default":
        runtime_profile = manifest.runtime_profiles.get(runtime_key)
        requirements = (
            runtime_profile.get("live_send_requirements")
            if isinstance(runtime_profile, dict) and isinstance(runtime_profile.get("live_send_requirements"), dict)
            else {}
        )
        evidence = requirements.get("required_evidence")
        if isinstance(evidence, list) and evidence:
            return tuple(str(item) for item in evidence)
    return manifest.required_send_evidence


def _completed_message_count(message_results: list[dict[str, Any]]) -> int:
    return sum(1 for result in message_results if result.get("status") == "ok")


def _validate_action_result(payload: dict[str, Any], work_item: dict[str, Any]) -> None:
    if payload.get("action_request_id") != work_item.get("action_request_id"):
        raise ManagedGuiSendError("action_result action_request_id mismatch")
    if payload.get("payload_hash") != work_item.get("payload_hash"):
        raise ManagedGuiSendError("action_result payload_hash mismatch")
    if payload.get("target_match_id") != work_item.get("match_id"):
        raise ManagedGuiSendError("action_result target_match_id mismatch")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManagedGuiSendError(f"invalid JSON in {path}") from exc
    if not isinstance(data, dict):
        raise ManagedGuiSendError(f"expected JSON object in {path}")
    return data


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _template_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.template{path.suffix}")


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value).strip("_") or "unknown"


def _now_iso() -> str:
    if os.environ.get("DATING_BOOST_NOW"):
        return str(os.environ["DATING_BOOST_NOW"])
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _normalized_harness_runtime(value: str) -> str:
    return value.strip().replace("-", "_")
