from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from dating_boost import __version__


CAPABILITIES_SCHEMA_VERSION = 1

SCHEMA_VERSIONS: dict[str, int] = {
    "capabilities": 1,
    "user_profile": 1,
    "app_observation": 1,
    "match_index": 1,
    "context_pack": 1,
    "content_policy": 1,
    "action_policy": 1,
    "feedback_event": 1,
    "action_result": 1,
    "reply_draft": 2,
    "workflow_result": 1,
    "scan_batch": 1,
    "automation_authorization": 1,
    "automation_state": 1,
    "automation_session": 1,
    "appointment_ledger": 1,
    "progress_report": 1,
    "skill_package": 1,
}

SUPPORTED_COMMANDS: list[str] = [
    "capabilities",
    "init-profile",
    "import-observation",
    "observe-screenshot",
    "draft",
    "feedback",
    "authorize",
    "memory ingest-observation",
    "memory get-match",
    "context build",
    "policy check-draft",
    "policy check-action",
    "action record-result",
    "feedback record",
    "workflow draft",
    "automation session start",
    "automation session step",
    "automation session stop",
    "automation report latest",
    "automation get-state",
    "automation pause",
    "automation resume",
    "automation record-authorization",
    "automation availability set",
    "automation goal set",
]


def build_capabilities(data_dir: Path | None = None) -> dict[str, Any]:
    return {
        "schema_version": CAPABILITIES_SCHEMA_VERSION,
        "tool_version": __version__,
        "git_commit": _git_commit(),
        "schema_versions": dict(SCHEMA_VERSIONS),
        "supported_commands": list(SUPPORTED_COMMANDS),
        "data_dir": str(data_dir.resolve()) if data_dir is not None else None,
        "policy_capabilities": {
            "action_authorization": True,
            "draft_content_check": True,
            "blocked_draft_redaction": True,
            "high_risk_autonomous_switch": True,
        },
        "memory_capabilities": {
            "user_profile": True,
            "match_identity_index": True,
            "observation_ingest": True,
            "context_pack_build": True,
            "feedback_events": True,
        },
        "agent_native_capabilities": {
            "host_executed_action_audit": True,
            "workflow_draft_runner": True,
            "automation_session": True,
            "automation_dry_run_default": True,
            "automation_external_scheduler": True,
            "appointment_ledger": True,
            "progress_report": True,
            "post_action_verification_required": True,
            "llm_owned_by_host_agent": True,
            "live_gui_harness": False,
            "mcp_adapter": False,
        },
        "warnings": [
            "Agent-native mode can expose visible dating app content to the host agent.",
            "High-risk actions remain disabled unless the user explicitly enables autonomous handling.",
        ],
    }


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"
