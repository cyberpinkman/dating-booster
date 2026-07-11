from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.apps.tashuo.stage_alpha_utils import _read_json_file

FORBIDDEN_COMMAND_TOKENS = {
    "--managed-gui-send",
    "send-message",
    "send_message",
    "like",
    "super-like",
    "super_like",
    "pass",
    "unmatch",
    "report",
    "profile-edit",
    "edit-profile",
    "profile_edit",
    "edit_profile",
    "premium-purchase",
    "premium_purchase",
    "call",
    "payment",
    "flight-start-chat",
    "flight_start_chat",
    "question-gate-send",
    "question_gate_send",
    "question-gate-enable",
    "question_gate_enable",
    "question-gate-skip",
    "question_gate_skip",
    "question-gate-decide-reply-satisfaction",
    "question_gate_decide_reply_satisfaction",
}
LIVE_SEND_COMMAND_TOKENS = {"--managed-gui-send", "send-message", "send_message"}

__all__ = [
    "FORBIDDEN_COMMAND_TOKENS",
    "LIVE_SEND_COMMAND_TOKENS",
    "_any_command_violation",
    "_bundle_smokes_command_violation",
    "_bundle_smokes_zero_live_send_execution",
    "_command_violation",
    "_live_send_command_violation",
    "_normalize_command_token",
    "_payload_command_violation",
    "_payload_live_send_violation",
    "_run_command_violation",
    "_run_live_send_violation",
    "_steps_command_violation",
    "_steps_live_send_violation",
    "_zero_live_send_execution",
]

def _payload_command_violation(payload: dict[str, Any]) -> str | None:
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return "smoke_steps_missing"
    for step in steps:
        if not isinstance(step, dict):
            continue
        violation = _command_violation(step.get("cmd"))
        if violation is not None:
            return violation
    command = payload.get("_smoke_command")
    violation = _command_violation(command)
    if violation is not None:
        return violation
    return None


def _steps_command_violation(steps: list[dict[str, Any]]) -> str | None:
    for step in steps:
        violation = _command_violation(step.get("cmd"))
        if violation is not None:
            return violation
    return None


def _any_command_violation(steps: list[dict[str, Any]], smoke_runs: list[dict[str, Any]]) -> str | None:
    violation = _steps_command_violation(steps)
    if violation is not None:
        return violation
    for run in smoke_runs:
        violation = _run_command_violation(run)
        if violation is not None:
            return violation
    return None


def _bundle_smokes_command_violation(bundle_smokes: dict[int, dict[str, Any]]) -> str | None:
    for run_number, payload in sorted(bundle_smokes.items()):
        violation = _payload_command_violation(payload)
        if violation is not None:
            return f"run_{run_number:02d}:{violation}"
    return None


def _run_command_violation(run: dict[str, Any]) -> str | None:
    smoke_json = run.get("smoke_json")
    if not isinstance(smoke_json, str):
        return None
    payload = _read_json_file(Path(smoke_json))
    if payload is None:
        return None
    return _payload_command_violation(payload)


def _zero_live_send_execution(steps: list[dict[str, Any]], smoke_runs: list[dict[str, Any]]) -> bool:
    if _steps_live_send_violation(steps) is not None:
        return False
    for run in smoke_runs:
        if _run_live_send_violation(run) is not None:
            return False
        alpha_gate = run.get("alpha_release_gate") if isinstance(run.get("alpha_release_gate"), dict) else {}
        checks = alpha_gate.get("checks") if isinstance(alpha_gate.get("checks"), dict) else {}
        if checks.get("live_send_not_executed") is False:
            return False
    return True


def _bundle_smokes_zero_live_send_execution(bundle_smokes: dict[int, dict[str, Any]]) -> bool:
    for payload in bundle_smokes.values():
        if _payload_live_send_violation(payload) is not None:
            return False
    return True


def _steps_live_send_violation(steps: list[dict[str, Any]]) -> str | None:
    for step in steps:
        violation = _live_send_command_violation(step.get("cmd"))
        if violation is not None:
            return violation
    return None


def _run_live_send_violation(run: dict[str, Any]) -> str | None:
    smoke_json = run.get("smoke_json")
    if not isinstance(smoke_json, str):
        return None
    payload = _read_json_file(Path(smoke_json))
    if payload is None:
        return None
    return _payload_live_send_violation(payload)


def _payload_live_send_violation(payload: dict[str, Any]) -> str | None:
    steps = payload.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            violation = _live_send_command_violation(step.get("cmd"))
            if violation is not None:
                return violation
    violation = _live_send_command_violation(payload.get("_smoke_command"))
    if violation is not None:
        return violation
    gate = payload.get("alpha_release_gate") if isinstance(payload.get("alpha_release_gate"), dict) else {}
    checks = gate.get("checks") if isinstance(gate.get("checks"), dict) else {}
    if checks.get("live_send_not_executed") is False:
        return "live_send_executed_by_alpha_gate"
    stage_result = gate.get("stage_result") if isinstance(gate.get("stage_result"), dict) else {}
    evidence = stage_result.get("evidence") if isinstance(stage_result.get("evidence"), dict) else {}
    if evidence.get("live_send_executed") is True:
        return "live_send_executed_by_stage_result"
    return None


def _live_send_command_violation(command: Any) -> str | None:
    if not isinstance(command, list):
        return None
    tokens = [str(item) for item in command]
    normalized_tokens = {_normalize_command_token(token) for token in tokens}
    for token in tokens:
        if token in LIVE_SEND_COMMAND_TOKENS or _normalize_command_token(token) in {
            _normalize_command_token(forbidden) for forbidden in LIVE_SEND_COMMAND_TOKENS
        }:
            return f"live_send_command_present:{token}"
    if normalized_tokens.intersection({"live"}):
        return "live_send_mode_token_present"
    if "--send-mode" in tokens:
        index = tokens.index("--send-mode")
        if index + 1 < len(tokens) and tokens[index + 1] != "stage":
            return "non_stage_send_mode_present"
    return None


def _command_violation(command: Any) -> str | None:
    if not isinstance(command, list):
        return None
    tokens = [str(item) for item in command]
    forbidden_normalized = {_normalize_command_token(token) for token in FORBIDDEN_COMMAND_TOKENS}
    for token in tokens:
        if token in FORBIDDEN_COMMAND_TOKENS or _normalize_command_token(token) in forbidden_normalized:
            return f"forbidden_command_present:{token}"
    if "--send-mode" in tokens:
        index = tokens.index("--send-mode")
        if index + 1 < len(tokens) and tokens[index + 1] != "stage":
            return "non_stage_send_mode_present"
    return None


def _normalize_command_token(token: str) -> str:
    return token.strip().lower().replace("_", "-")
