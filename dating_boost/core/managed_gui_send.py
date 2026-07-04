from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from dating_boost.apps.registry import host_loop_app_ids
from dating_boost.core.managed_gui_send_common import (
    MESSAGE_SEQUENCE_SECONDS_PER_MESSAGE,
    ManagedGuiSendError,
    _normalized_harness_runtime,
    _now_iso,
    _read_json,
    _safe_name,
    _template_path,
    _write_json,
)
from dating_boost.core.managed_gui_send_evidence import (
    _managed_gui_send_message_evidence,
    _managed_gui_send_message_result,
    _managed_gui_send_normalized_evidence,
    _managed_gui_send_refreshed_target_binding,
    _managed_gui_send_required_evidence,
    _managed_gui_send_required_evidence_for_payload,
    _redacted_managed_send_payload,
)
from dating_boost.core.managed_gui_send_harness import (
    _finish_successful_managed_gui_send,
    _handle_harness_visual_wait,
    _handle_pending_visual_confirmation,
    _run_managed_gui_send_sequence,
    _send_single_message_via_harness,
)
from dating_boost.core.managed_gui_send_sequence import (
    _completed_message_count,
    _managed_sequence_elapsed_seconds,
    _managed_sequence_expiry,
    _managed_sequence_message_by_index,
    _managed_sequence_pending_visual_result,
    _managed_sequence_progress_load,
    _managed_sequence_progress_path,
    _managed_sequence_progress_save,
    _managed_sequence_remaining_seconds,
    _managed_sequence_visual_confirmation_evidence,
    _managed_sequence_visual_confirmation_path,
    _managed_sequence_visual_confirmation_template,
    _managed_sequence_window_seconds,
    _parse_iso_datetime_utc,
    _single_message_work_item,
    _validate_action_result,
    _validate_managed_sequence_visual_confirmation,
    _work_item_payload_messages,
    _work_item_payload_text,
)
from dating_boost.core.safety import SafetyRepository


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

    def _live_send_contract_block_reason(self, work_item: dict[str, Any], authorization: dict[str, Any]) -> str | None:
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
        contract_reason = host._live_send_contract_block_reason(work_item, authorization)
        if contract_reason is not None:
            return host._finish("blocked", contract_reason, current=work_item)

        return _run_managed_gui_send_sequence(
            host,
            work_item,
            authorization_path=authorization_path,
        )
