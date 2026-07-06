from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.core.managed_gui_send_common import (
    _now_iso, _read_json, _safe_name, _template_path,
    _write_json,
)
from dating_boost.core.managed_gui_send_evidence import (
    _managed_gui_send_message_evidence, _managed_gui_send_message_result, _managed_gui_send_normalized_evidence, _managed_gui_send_refreshed_target_binding,
    _managed_gui_send_required_evidence, _managed_gui_send_required_evidence_for_payload, _redacted_managed_send_payload,
)
from dating_boost.core.managed_gui_send_sequence import (
    _completed_message_count, _managed_sequence_elapsed_seconds, _managed_sequence_expiry, _managed_sequence_message_by_index,
    _managed_sequence_pending_visual_result, _managed_sequence_progress_load, _managed_sequence_progress_path, _managed_sequence_progress_save,
    _managed_sequence_remaining_seconds, _managed_sequence_visual_confirmation_evidence, _managed_sequence_visual_confirmation_path, _managed_sequence_visual_confirmation_template,
    _managed_sequence_window_seconds, _single_message_work_item, _validate_action_result, _validate_managed_sequence_visual_confirmation,
    _work_item_payload_messages,
)


def _run_managed_gui_send_sequence(
    host: Any,
    work_item: dict[str, Any],
    *,
    authorization_path: Path,
) -> dict[str, Any] | None:
    payload_messages = _work_item_payload_messages(work_item)
    sequence_timing_enabled = len(payload_messages) > 1
    message_sequence_window_seconds = _managed_sequence_window_seconds(len(payload_messages))
    progress_path = _managed_sequence_progress_path(host.work_dir, work_item)
    result_path = host._work_file(work_item, "action_result")
    if result_path.exists():
        return _record_existing_action_result(host, work_item, result_path=result_path, progress_path=progress_path)

    sequence_progress = _managed_sequence_progress_load(progress_path, work_item)
    harness_payloads: list[dict[str, Any]] = []
    message_results: list[dict[str, Any]] = list(sequence_progress.get("message_results") or [])
    sequence_started_at = str(sequence_progress.get("sequence_started_at") or "")
    sequence_last_sent_at = str(sequence_progress.get("last_message_sent_at") or "")
    completed_indices = _completed_message_indices(message_results)
    harness_runtime = str(getattr(host.args, "harness_runtime", "") or "").strip()
    required_evidence = _managed_gui_send_required_evidence(str(host.args.app_id), harness_runtime)
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
        completed_indices = _completed_message_indices(message_results)

    for message in payload_messages:
        if int(message["index"]) in completed_indices:
            continue
        send_result = _send_sequence_message(
            host,
            work_item,
            sequence_work_item,
            message,
            message_results,
            harness_payloads,
            authorization_path=authorization_path,
            harness_runtime=harness_runtime,
            required_evidence=required_evidence,
            sequence_timing_enabled=sequence_timing_enabled,
            sequence_started_at=sequence_started_at,
            sequence_last_sent_at=sequence_last_sent_at,
            message_sequence_window_seconds=message_sequence_window_seconds,
            progress_path=progress_path,
            result_path=result_path,
        )
        if isinstance(send_result, dict) and send_result.get("__return__") is True:
            return send_result.get("payload")
        if isinstance(send_result, dict):
            sequence_started_at = str(send_result.get("sequence_started_at") or sequence_started_at)
            sequence_last_sent_at = str(send_result.get("sequence_last_sent_at") or sequence_last_sent_at)
            completed_indices = _completed_message_indices(message_results)

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


def _record_existing_action_result(
    host: Any,
    work_item: dict[str, Any],
    *,
    result_path: Path,
    progress_path: Path,
) -> None:
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


def _completed_message_indices(message_results: list[dict[str, Any]]) -> set[int]:
    return {
        int(result.get("index") or 0)
        for result in message_results
        if isinstance(result, dict) and result.get("status") == "ok"
    }


def _send_sequence_message(
    host: Any,
    work_item: dict[str, Any],
    sequence_work_item: dict[str, Any],
    message: dict[str, Any],
    message_results: list[dict[str, Any]],
    harness_payloads: list[dict[str, Any]],
    *,
    authorization_path: Path,
    harness_runtime: str,
    required_evidence: tuple[str, ...],
    sequence_timing_enabled: bool,
    sequence_started_at: str,
    sequence_last_sent_at: str,
    message_sequence_window_seconds: int,
    progress_path: Path,
    result_path: Path,
) -> dict[str, Any] | None:
    if sequence_timing_enabled:
        timing_result = _prepare_sequence_message_timing(
            host,
            work_item,
            message,
            message_results,
            sequence_work_item=sequence_work_item,
            sequence_started_at=sequence_started_at,
            sequence_last_sent_at=sequence_last_sent_at,
            message_sequence_window_seconds=message_sequence_window_seconds,
            progress_path=progress_path,
        )
        if isinstance(timing_result, dict) and timing_result.get("__return__") is True:
            return timing_result
        if isinstance(timing_result, dict):
            sequence_started_at = str(timing_result.get("sequence_started_at") or sequence_started_at)
            sequence_last_sent_at = str(timing_result.get("sequence_last_sent_at") or sequence_last_sent_at)

    remaining_seconds = (
        _managed_sequence_remaining_seconds(sequence_started_at, window_seconds=message_sequence_window_seconds)
        if sequence_timing_enabled
        else None
    )
    if remaining_seconds is not None and remaining_seconds <= 0:
        return _sequence_window_expired_return(
            host,
            work_item,
            message,
            message_results,
            sequence_started_at=sequence_started_at,
            message_sequence_window_seconds=message_sequence_window_seconds,
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
    message_results.append(_managed_gui_send_message_result(message, harness_payload))
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
        return visual_wait
    if isinstance(visual_wait, dict):
        sequence_last_sent_at = str(visual_wait.get("sequence_last_sent_at") or sequence_last_sent_at)
    if harness_payload.get("status") == "needs_host_visual_verification":
        return {"sequence_started_at": sequence_started_at, "sequence_last_sent_at": sequence_last_sent_at}

    failure = _managed_gui_send_failure(
        host,
        work_item,
        message,
        message_results,
        harness_payload=harness_payload,
        harness_evidence=harness_evidence,
        required_evidence=required_evidence,
    )
    if failure is not None:
        return {"__return__": True, "payload": failure}

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
    return {"sequence_started_at": sequence_started_at, "sequence_last_sent_at": sequence_last_sent_at}


def _prepare_sequence_message_timing(
    host: Any,
    work_item: dict[str, Any],
    message: dict[str, Any],
    message_results: list[dict[str, Any]],
    *,
    sequence_work_item: dict[str, Any],
    sequence_started_at: str,
    sequence_last_sent_at: str,
    message_sequence_window_seconds: int,
    progress_path: Path,
) -> dict[str, Any] | None:
    completed_count = _completed_message_count(message_results)
    if completed_count and not sequence_started_at:
        return {
            "__return__": True,
            "payload": host._finish(
                "blocked",
                "message_sequence_window_unverifiable",
                current=work_item,
                extra={
                    "message_sequence_window_seconds": message_sequence_window_seconds,
                    "completed_message_count": completed_count,
                    "failed_message_index": message.get("index"),
                    "message_results": message_results,
                    "next_host_action": "observe_current_thread_and_replan_sequence",
                },
            ),
        }
    expired = _managed_sequence_expiry(
        sequence_started_at,
        window_seconds=message_sequence_window_seconds,
    )
    if expired is not None:
        return {
            "__return__": True,
            "payload": host._finish(
                "blocked",
                "message_sequence_window_expired",
                current=work_item,
                extra={
                    **expired,
                    "completed_message_count": completed_count,
                    "failed_message_index": message.get("index"),
                    "message_results": message_results,
                    "next_host_action": "observe_current_thread_and_replan_sequence",
                },
            ),
        }
    if sequence_started_at:
        return {"sequence_started_at": sequence_started_at, "sequence_last_sent_at": sequence_last_sent_at}

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
    return {"sequence_started_at": sequence_started_at, "sequence_last_sent_at": sequence_last_sent_at}


def _sequence_window_expired_return(
    host: Any,
    work_item: dict[str, Any],
    message: dict[str, Any],
    message_results: list[dict[str, Any]],
    *,
    sequence_started_at: str,
    message_sequence_window_seconds: int,
) -> dict[str, Any]:
    return {
        "__return__": True,
        "payload": host._finish(
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
        ),
    }


def _managed_gui_send_failure(
    host: Any,
    work_item: dict[str, Any],
    message: dict[str, Any],
    message_results: list[dict[str, Any]],
    *,
    harness_payload: dict[str, Any],
    harness_evidence: dict[str, Any],
    required_evidence: tuple[str, ...],
) -> dict[str, Any] | None:
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
    return None


def _handle_pending_visual_confirmation(
    host: Any,
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
    host: Any,
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
    host: Any,
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
    host: Any,
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
