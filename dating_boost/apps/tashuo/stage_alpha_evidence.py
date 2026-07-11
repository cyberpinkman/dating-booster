from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from dating_boost.apps.tashuo.stage_alpha_safety import (
    _any_command_violation, _bundle_smokes_command_violation, _bundle_smokes_zero_live_send_execution, _payload_command_violation,
    _zero_live_send_execution,
)
from dating_boost.apps.tashuo.stage_alpha_utils import _read_json_file

__all__ = [
    "EVIDENCE_BUNDLE_REDACT_KEYS",
    "_archive_entry_is_visual_artifact",
    "_bundle_run_number",
    "_bundle_smokes_ok",
    "_collect_redaction_violations",
    "_dict_or_empty",
    "_is_redaction_marker",
    "_load_release_evidence",
    "_looks_like_visual_artifact_path",
    "_redact_for_evidence_bundle",
    "_redaction_marker",
    "_redaction_violations",
    "_release_evidence_checks",
    "_release_run_summary_ok",
    "_run_summary_from_payload",
    "_runtime_scope_from_payload",
    "_validate_smoke_payload",
    "payload_digest_for_compare",
]

def _validate_smoke_payload(smoke_payload: dict[str, Any]) -> dict[str, str]:
    violation = _payload_command_violation(smoke_payload)
    if violation is not None:
        return {"status": "blocked", "reason": violation}
    if smoke_payload.get("status") != "ok":
        return {"status": "blocked", "reason": str(smoke_payload.get("reason") or "standalone_smoke_failed")}
    if smoke_payload.get("reason") != "tashuo_standalone_stage_smoke_complete":
        return {"status": "blocked", "reason": "standalone_smoke_incomplete"}
    final_input = smoke_payload.get("final_input_verification")
    if not isinstance(final_input, dict) or final_input.get("status") != "ok":
        return {"status": "blocked", "reason": "final_input_not_verified_empty"}
    try:
        final_count = int(final_input.get("final_input_character_count"))
    except (TypeError, ValueError):
        final_count = -1
    if final_input.get("input_cleared") is not True or final_count != 0:
        return {"status": "blocked", "reason": "final_input_not_empty"}
    gate = smoke_payload.get("alpha_release_gate")
    if not isinstance(gate, dict) or gate.get("status") != "ok":
        return {"status": "blocked", "reason": str((gate or {}).get("reason") or "alpha_release_gate_failed")}
    checks = gate.get("checks") if isinstance(gate.get("checks"), dict) else {}
    for key in ("stage_only", "live_send_not_executed", "staged_text_verified", "target_verified", "final_input_empty"):
        if checks.get(key) is not True:
            return {"status": "blocked", "reason": f"alpha_gate_check_failed:{key}"}
    stage_result = gate.get("stage_result") if isinstance(gate.get("stage_result"), dict) else {}
    evidence = stage_result.get("evidence") if isinstance(stage_result.get("evidence"), dict) else {}
    if evidence.get("live_send_executed") is not False:
        return {"status": "blocked", "reason": "live_send_execution_not_ruled_out"}
    return {"status": "ok", "reason": "tashuo_stage_alpha_run_passed"}

EVIDENCE_BUNDLE_REDACT_KEYS = {
    "best_reply",
    "bolder_reply",
    "conversation_observation",
    "draft_text",
    "input_text",
    "latest_match_message",
    "latest_user_message",
    "payload_text",
    "photo_cues",
    "profile_observation",
    "profile_text",
    "raw_chat",
    "raw_conversation",
    "raw_draft",
    "raw_profile",
    "raw_ref",
    "safer_reply",
    "screen",
    "screenshot",
    "text",
    "visible_messages",
    "visible_name",
}


def _run_summary_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "runs_required": payload.get("runs_required"),
        "runs_completed": payload.get("runs_completed"),
        "runs_passed": payload.get("runs_passed"),
        "pass_rate": payload.get("pass_rate"),
    }


def _runtime_scope_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "selected"
        if payload.get("app_id") == "tashuo" and payload.get("harness_runtime") == "mac-ios-app"
        else "unknown",
        "selected_app_id": payload.get("app_id"),
        "selected_runtime": payload.get("harness_runtime"),
        "send_mode": payload.get("send_mode"),
    }


def _redact_for_evidence_bundle(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in EVIDENCE_BUNDLE_REDACT_KEYS:
                redacted[key_text] = _redaction_marker(item)
                continue
            if key_text == "path" and _looks_like_visual_artifact_path(item):
                redacted[key_text] = "[redacted_visual_artifact_path]"
                continue
            redacted[key_text] = _redact_for_evidence_bundle(item)
        return redacted
    if isinstance(value, list):
        return [_redact_for_evidence_bundle(item) for item in value]
    if _looks_like_visual_artifact_path(value):
        return "[redacted_visual_artifact_path]"
    return value


def _redaction_marker(value: Any) -> dict[str, Any]:
    marker = {"redacted": True}
    if isinstance(value, str):
        marker["character_count"] = len(value)
    elif isinstance(value, list):
        marker["item_count"] = len(value)
    elif isinstance(value, dict):
        marker["field_count"] = len(value)
    return marker


def _looks_like_visual_artifact_path(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    return any(ext in lowered for ext in (".png", ".jpg", ".jpeg", ".heic", ".webp", ".tiff"))


def _load_release_evidence(
    *,
    evidence_json: Path | None,
    evidence_bundle: Path | None,
) -> tuple[dict[str, Any], dict[int, dict[str, Any]], dict[str, Any]]:
    if evidence_json is None and evidence_bundle is None:
        raise ValueError("one of --validate-evidence-json or --validate-evidence-bundle is required")
    bundle_smokes: dict[int, dict[str, Any]] = {}
    bundle_summary: dict[str, Any] = {"provided": evidence_bundle is not None}
    if evidence_bundle is not None:
        with zipfile.ZipFile(evidence_bundle) as archive:
            names = set(archive.namelist())
            redaction_violations: list[str] = []
            bundle_summary = {
                "provided": True,
                "path": str(evidence_bundle),
                "entry_count": len(names),
                "has_alpha_release_evidence": "alpha_release_evidence.json" in names,
                "has_support_bundle": "support/dating-boost-support-strict.zip" in names,
                "has_visual_artifact_entries": any(_archive_entry_is_visual_artifact(name) for name in names),
            }
            if "alpha_release_evidence.json" not in names:
                raise ValueError("bundle missing alpha_release_evidence.json")
            payload = json.loads(archive.read("alpha_release_evidence.json").decode("utf-8"))
            if isinstance(payload, dict):
                redaction_violations.extend(_redaction_violations(payload, path="alpha_release_evidence.json"))
            for name in sorted(names):
                if name.endswith(".json") and name != "alpha_release_evidence.json":
                    parsed_for_redaction = json.loads(archive.read(name).decode("utf-8"))
                    redaction_violations.extend(_redaction_violations(parsed_for_redaction, path=name))
                if not name.startswith("runs/run_") or not name.endswith("_smoke.json"):
                    continue
                run_number = _bundle_run_number(name)
                if run_number is None:
                    continue
                parsed = json.loads(archive.read(name).decode("utf-8"))
                if isinstance(parsed, dict):
                    bundle_smokes[run_number] = parsed
            bundle_summary["redaction_violations"] = redaction_violations
    else:
        payload = json.loads(evidence_json.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("release evidence JSON must be an object")
    if evidence_json is not None and evidence_bundle is not None:
        file_payload = json.loads(evidence_json.read_text(encoding="utf-8"))
        if (
            isinstance(file_payload, dict)
            and payload_digest_for_compare(_redact_for_evidence_bundle(file_payload)) != payload_digest_for_compare(payload)
        ):
            bundle_summary["json_mismatch"] = True
    return payload, bundle_smokes, bundle_summary


def payload_digest_for_compare(payload: dict[str, Any]) -> str:
    comparable = dict(payload)
    comparable.pop("evidence_json", None)
    comparable.pop("evidence_bundle", None)
    return json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _bundle_run_number(name: str) -> int | None:
    stem = Path(name).name
    if not stem.startswith("run_"):
        return None
    try:
        return int(stem.split("_", 2)[1])
    except (IndexError, ValueError):
        return None


def _release_evidence_checks(
    payload: dict[str, Any],
    *,
    bundle_smokes: dict[int, dict[str, Any]],
    bundle_summary: dict[str, Any],
) -> dict[str, Any]:
    failures: list[str] = []
    smoke_runs = payload.get("smoke_runs") if isinstance(payload.get("smoke_runs"), list) else []
    top_checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    support_stop = _dict_or_empty(payload.get("support_session_stop"))
    support_bundle = _dict_or_empty(payload.get("support_bundle"))
    required_top_checks = {
        "twenty_of_twenty_passed",
        "required_run_count_passed",
        "zero_live_send_execution",
        "zero_high_risk_action",
        "strict_support_bundle",
        "support_bundle_required",
        "evidence_bundle_written",
    }
    checks = {
        "source_status_ok": payload.get("status") == "ok",
        "source_reason_ok": payload.get("reason") == "tashuo_stage_alpha_release_gate_passed",
        "app_runtime_stage": payload.get("app_id") == "tashuo"
        and payload.get("harness_runtime") == "mac-ios-app"
        and payload.get("send_mode") == "stage",
        "runs_required_20": payload.get("runs_required") == 20,
        "runs_completed_20": payload.get("runs_completed") == 20,
        "runs_passed_20": payload.get("runs_passed") == 20,
        "smoke_run_count_20": len(smoke_runs) == 20,
        "top_checks_all_true": all(top_checks.get(key) is True for key in required_top_checks),
        "zero_live_send_execution": _zero_live_send_execution(payload.get("steps") if isinstance(payload.get("steps"), list) else [], smoke_runs)
        and _bundle_smokes_zero_live_send_execution(bundle_smokes),
        "zero_high_risk_action": _any_command_violation(
            payload.get("steps") if isinstance(payload.get("steps"), list) else [],
            smoke_runs,
        )
        is None
        and _bundle_smokes_command_violation(bundle_smokes) is None,
        "support_session_stopped": support_stop.get("status") in {"ok", "stopped"},
        "support_bundle_strict": support_bundle.get("status") == "ok"
        and support_bundle.get("redaction") == "strict",
        "bundle_provided": bundle_summary.get("provided") is True,
        "bundle_has_alpha_release_evidence": not bundle_summary.get("provided")
        or bundle_summary.get("has_alpha_release_evidence") is True,
        "bundle_has_support_bundle": not bundle_summary.get("provided")
        or bundle_summary.get("has_support_bundle") is True,
        "bundle_json_matches_file": bundle_summary.get("json_mismatch") is not True,
        "bundle_redacted": bundle_summary.get("provided") is not True
        or (
            bundle_summary.get("has_visual_artifact_entries") is not True
            and not bundle_summary.get("redaction_violations")
        ),
    }
    checks["every_run_summary_ok"] = all(_release_run_summary_ok(run) for run in smoke_runs)
    checks["every_bundle_smoke_ok"] = _bundle_smokes_ok(payload, bundle_smokes, bundle_summary, failures)
    checks["all_release_checks_true"] = all(checks.values())
    for key, value in checks.items():
        if value is not True and key != "all_release_checks_true":
            failures.append(f"release_evidence_check_failed:{key}")
    return {"checks": checks, "failures": failures}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _archive_entry_is_visual_artifact(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith((".png", ".jpg", ".jpeg", ".heic", ".webp", ".tiff"))


def _redaction_violations(value: Any, *, path: str) -> list[str]:
    violations: list[str] = []
    _collect_redaction_violations(value, path=path, violations=violations)
    return violations


def _collect_redaction_violations(value: Any, *, path: str, violations: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            key_text = str(key)
            if key_text in EVIDENCE_BUNDLE_REDACT_KEYS and not _is_redaction_marker(item):
                violations.append(f"unredacted_sensitive_field:{child_path}")
            if key_text == "path" and _looks_like_visual_artifact_path(item):
                violations.append(f"unredacted_visual_path:{child_path}")
            _collect_redaction_violations(item, path=child_path, violations=violations)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _collect_redaction_violations(item, path=f"{path}[{index}]", violations=violations)
        return
    if _looks_like_visual_artifact_path(value):
        violations.append(f"unredacted_visual_path:{path}")


def _is_redaction_marker(value: Any) -> bool:
    return isinstance(value, dict) and value.get("redacted") is True


def _release_run_summary_ok(run: Any) -> bool:
    if not isinstance(run, dict):
        return False
    if run.get("status") != "ok" or run.get("reason") != "tashuo_stage_alpha_run_passed":
        return False
    gate = run.get("alpha_release_gate") if isinstance(run.get("alpha_release_gate"), dict) else {}
    if gate.get("status") != "ok":
        return False
    checks = gate.get("checks") if isinstance(gate.get("checks"), dict) else {}
    for key in ("stage_only", "live_send_not_executed", "staged_text_verified", "target_verified", "final_input_empty"):
        if checks.get(key) is not True:
            return False
    return bool(run.get("stage_binding"))


def _bundle_smokes_ok(
    payload: dict[str, Any],
    bundle_smokes: dict[int, dict[str, Any]],
    bundle_summary: dict[str, Any],
    failures: list[str],
) -> bool:
    if not bundle_summary.get("provided"):
        return True
    try:
        runs_required = int(payload.get("runs_required"))
    except (TypeError, ValueError):
        runs_required = 0
    if runs_required != 20:
        return False
    ok = True
    for run_number in range(1, runs_required + 1):
        smoke = bundle_smokes.get(run_number)
        if not isinstance(smoke, dict):
            failures.append(f"release_evidence_bundle_smoke_missing:run_{run_number:02d}")
            ok = False
            continue
        validation = _validate_smoke_payload(smoke)
        if validation.get("status") != "ok":
            failures.append(f"release_evidence_bundle_smoke_invalid:run_{run_number:02d}:{validation.get('reason')}")
            ok = False
    return ok
