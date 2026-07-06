from __future__ import annotations

from dating_boost.host_loop_common import (
    annotations, argparse, hashlib, json,
    os, shutil, subprocess, sys,
    time, Path, Any, supported_app_ids,
    UserMemoryRepository, target_binding_structural_evidence_present, validate_live_send_contract, ManagedGuiSendError,
    ManagedGuiSendRunner, _managed_gui_send_required_evidence, _validate_managed_sequence_visual_confirmation, _work_item_payload_text,
    DEFAULT_MESSAGE_LIST_SCAN_BOUNDARY, OperatorRepository, ProductionDataStore, RELATIONSHIP_PROGRESS_NEXT_ACTION,
    build_relationship_progress_report, RuntimeScopeRepository, SafetyRepository, SupportLogRepository,
    ProfileObservation, ROOT, DEFAULT_DATA_DIR, DEFAULT_FIXTURE_NOW,
    REPORT_FINAL_STATUSES, MESSAGE_SEQUENCE_SECONDS_PER_MESSAGE, IPHONE_MIRRORING_STRUCTURAL_BINDING_APP_IDS, HostLoopError,
    HostLoopCommandError,
)

def _data_dir_path(data_dir: Path, value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str(data_dir / path)


def _host_loop_relationship_report_paths(data_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(report)
    normalized["human_report_path"] = _data_dir_path(data_dir, normalized.get("human_report_path"))
    normalized["machine_report_path"] = _data_dir_path(data_dir, normalized.get("machine_report_path"))
    return normalized


def _digest(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return os.environ.get("DATING_BOOST_NOW") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _print_human(payload: dict[str, Any]) -> None:
    print(f"status: {payload.get('status')}")
    print(f"reason: {payload.get('stop_reason')}")
    print(f"work_dir: {payload.get('work_dir')}")
    if payload.get("current_work_item"):
        print(f"current_work_item: {payload['current_work_item'].get('work_item_type')}")


__all__ = [
    'annotations', 'argparse', 'hashlib', 'json',
    'os', 'shutil', 'subprocess', 'sys',
    'time', 'Path', 'Any', 'supported_app_ids',
    'UserMemoryRepository', 'target_binding_structural_evidence_present', 'validate_live_send_contract', 'ManagedGuiSendError',
    'ManagedGuiSendRunner', '_managed_gui_send_required_evidence', '_validate_managed_sequence_visual_confirmation', '_work_item_payload_text',
    'DEFAULT_MESSAGE_LIST_SCAN_BOUNDARY', 'OperatorRepository', 'ProductionDataStore', 'RELATIONSHIP_PROGRESS_NEXT_ACTION',
    'build_relationship_progress_report', 'RuntimeScopeRepository', 'SafetyRepository', 'SupportLogRepository',
    'ProfileObservation', 'ROOT', 'DEFAULT_DATA_DIR', 'DEFAULT_FIXTURE_NOW',
    'REPORT_FINAL_STATUSES', 'MESSAGE_SEQUENCE_SECONDS_PER_MESSAGE', 'IPHONE_MIRRORING_STRUCTURAL_BINDING_APP_IDS', 'HostLoopError',
    'HostLoopCommandError', '_data_dir_path', '_host_loop_relationship_report_paths', '_digest',
    '_now_iso', '_write_json', '_print_human',
]
