from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STAGE_RESULTS_PATH = Path("audit") / "stage_results.jsonl"
EXPECTED_SMOKE_REASON = "tashuo_standalone_stage_smoke_complete"


def evaluate_alpha_gate(smoke_payload: dict[str, Any], *, data_dir: Path) -> dict[str, Any]:
    smoke_check = _smoke_completion_check(smoke_payload)
    if smoke_check is not None:
        return smoke_check

    final_tick = _final_tick_step(smoke_payload)
    binding = _stage_binding_from_final_tick(final_tick)
    if binding is None:
        return _blocked("alpha_gate_final_tick_stage_binding_missing")

    stage_results = _stage_results(data_dir)
    if not stage_results:
        return _blocked("alpha_gate_stage_result_missing", data_dir=data_dir)
    stage_result = _find_bound_stage_result(stage_results, binding)
    if stage_result is None:
        return _blocked(
            "alpha_gate_stage_result_not_bound_to_final_tick",
            expected_stage_binding=binding,
            latest_stage_result=_stage_result_summary(stage_results[-1]),
            audit_path=str(data_dir / STAGE_RESULTS_PATH),
        )

    stage_check = _stage_result_check(stage_result)
    if stage_check is not None:
        return stage_check

    return {
        "schema_version": 1,
        "status": "ok",
        "reason": "tashuo_standalone_alpha_gate_passed",
        "checks": {
            "smoke_completed": True,
            "final_tick_stage_recorded": True,
            "stage_result_recorded": True,
            "stage_only": True,
            "live_send_not_executed": True,
            "stage_attempt_completed": True,
            "staged_text_verified": True,
            "target_verified": True,
        },
        "stage_binding": binding,
        "stage_result": _stage_result_summary(stage_result),
        "audit_path": str(data_dir / STAGE_RESULTS_PATH),
    }


def _smoke_completion_check(smoke_payload: dict[str, Any]) -> dict[str, Any] | None:
    if smoke_payload.get("status") != "ok":
        return _blocked(
            "alpha_gate_smoke_not_ok",
            smoke_status=smoke_payload.get("status"),
            smoke_reason=smoke_payload.get("reason"),
        )
    if smoke_payload.get("reason") != EXPECTED_SMOKE_REASON:
        return _blocked(
            "alpha_gate_smoke_reason_mismatch",
            smoke_reason=smoke_payload.get("reason"),
            expected_reason=EXPECTED_SMOKE_REASON,
        )
    final_tick = _final_tick_step(smoke_payload)
    if final_tick is None or final_tick.get("status") != "stage_recorded":
        return _blocked(
            "alpha_gate_final_tick_not_stage_recorded",
            final_tick_status=final_tick.get("status") if isinstance(final_tick, dict) else None,
        )
    return None


def _stage_result_check(stage_result: dict[str, Any]) -> dict[str, Any] | None:
    evidence = stage_result.get("evidence") if isinstance(stage_result.get("evidence"), dict) else {}
    staged_text_verification = (
        stage_result.get("staged_text_verification")
        if isinstance(stage_result.get("staged_text_verification"), dict)
        else {}
    )
    target_verification = (
        stage_result.get("target_verification")
        if isinstance(stage_result.get("target_verification"), dict)
        else {}
    )

    if stage_result.get("result_status") != "succeeded":
        return _blocked("alpha_gate_stage_result_not_succeeded", stage_result=_stage_result_summary(stage_result))
    if evidence.get("stage_mode") is not True:
        return _blocked("alpha_gate_stage_mode_not_recorded", stage_result=_stage_result_summary(stage_result))
    if evidence.get("live_send_executed") is not False:
        return _blocked("alpha_gate_live_send_executed", stage_result=_stage_result_summary(stage_result))
    if stage_result.get("stage_attempt_status") != "completed":
        return _blocked("alpha_gate_stage_attempt_not_completed", stage_result=_stage_result_summary(stage_result))
    if stage_result.get("staged_text_verified") is not True or staged_text_verification.get("status") != "verified":
        return _blocked("alpha_gate_staged_text_not_verified", stage_result=_stage_result_summary(stage_result))
    if target_verification.get("status") != "ok":
        return _blocked("alpha_gate_target_not_verified", stage_result=_stage_result_summary(stage_result))
    if not _non_empty(stage_result.get("action_request_id")):
        return _blocked("alpha_gate_action_request_id_missing", stage_result=_stage_result_summary(stage_result))
    if not _non_empty(stage_result.get("target_match_id")):
        return _blocked("alpha_gate_target_match_id_missing", stage_result=_stage_result_summary(stage_result))
    if not _non_empty(stage_result.get("payload_hash")):
        return _blocked("alpha_gate_payload_hash_missing", stage_result=_stage_result_summary(stage_result))
    if not _non_empty(stage_result.get("pre_action_observation_id")):
        return _blocked("alpha_gate_pre_action_observation_missing", stage_result=_stage_result_summary(stage_result))
    return None


def _stage_results(data_dir: Path) -> list[dict[str, Any]]:
    path = data_dir / STAGE_RESULTS_PATH
    if not path.is_file():
        return []
    results: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            results.append(parsed)
    return results


def _find_bound_stage_result(stage_results: list[dict[str, Any]], binding: dict[str, str]) -> dict[str, Any] | None:
    event_id = binding.get("event_id")
    if event_id:
        for stage_result in reversed(stage_results):
            if stage_result.get("event_id") == event_id:
                return stage_result
        return None
    for stage_result in reversed(stage_results):
        if all(stage_result.get(key) == value for key, value in binding.items()):
            return stage_result
    return None


def _final_tick_step(smoke_payload: dict[str, Any]) -> dict[str, Any] | None:
    steps = smoke_payload.get("steps")
    if not isinstance(steps, list):
        return None
    for step in reversed(steps):
        if not isinstance(step, dict):
            continue
        cmd = step.get("cmd")
        if isinstance(cmd, list) and cmd[:2] == ["standalone-session", "tick"]:
            return step
    return None


def _stage_binding_from_final_tick(final_tick: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(final_tick, dict):
        return None
    recorded = final_tick.get("recorded") if isinstance(final_tick.get("recorded"), dict) else {}
    source = recorded if recorded else final_tick
    binding = {
        key: str(source.get(key) or "").strip()
        for key in ("event_id", "action_request_id", "target_match_id", "payload_hash")
        if str(source.get(key) or "").strip()
    }
    if binding.get("event_id"):
        return binding
    required = {"action_request_id", "target_match_id", "payload_hash"}
    if required.issubset(binding):
        return {key: binding[key] for key in ("action_request_id", "target_match_id", "payload_hash")}
    return None


def _stage_result_summary(stage_result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: stage_result.get(key)
        for key in (
            "event_id",
            "action_request_id",
            "target_match_id",
            "payload_hash",
            "pre_action_observation_id",
            "result_status",
            "stage_attempt_status",
            "staged_text_verified",
            "staged_text_verification",
            "target_verification",
            "evidence",
        )
        if key in stage_result
    }


def _blocked(reason: str, **extras: Any) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "status": "blocked",
        "reason": reason,
    }
    payload.update(_json_safe(extras))
    return payload


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
