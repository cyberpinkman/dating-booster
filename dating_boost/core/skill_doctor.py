from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dating_boost import __version__
from dating_boost.core.capabilities import build_capabilities


def run_skill_doctor(package_path: Path, data_dir: Path) -> dict[str, Any]:
    try:
        metadata = _read_json_object(package_path)
    except (OSError, ValueError) as exc:
        return {
            "schema_version": 1,
            "status": "error",
            "skill_version": None,
            "cli_found": True,
            "cli_version": __version__,
            "capabilities_ok": False,
            "missing_commands": [],
            "schema_mismatches": [],
            "data_dir": str(data_dir.resolve()),
            "warnings": [],
            "next_action": "stop",
            "reason": str(exc),
        }

    capabilities = build_capabilities(data_dir)
    missing_commands = _missing_commands(metadata, capabilities)
    schema_mismatches = _schema_mismatches(metadata, capabilities)
    warnings: list[str] = []

    tool_too_old = _version_tuple(capabilities["tool_version"]) < _version_tuple(
        str(metadata.get("dating_boost_min_version", "0.0.0"))
    )
    if tool_too_old:
        status = "needs_bootstrap"
        next_action = "bootstrap_cli"
    elif missing_commands or schema_mismatches:
        status = "incompatible"
        next_action = "stop"
    else:
        status = "ok"
        next_action = "ready"

    source_spec_commit = metadata.get("source_spec_commit")
    git_commit = capabilities.get("git_commit")
    if _looks_like_git_commit(source_spec_commit) and git_commit and source_spec_commit != git_commit:
        warnings.append(
            f"source_spec_commit {source_spec_commit} differs from current git_commit {git_commit}"
        )

    return {
        "schema_version": 1,
        "status": status,
        "skill_version": metadata.get("package_version"),
        "cli_found": True,
        "cli_version": capabilities["tool_version"],
        "capabilities_ok": status == "ok",
        "missing_commands": missing_commands,
        "schema_mismatches": schema_mismatches,
        "data_dir": str(data_dir.resolve()),
        "warnings": warnings,
        "next_action": next_action,
    }


def _missing_commands(metadata: dict[str, Any], capabilities: dict[str, Any]) -> list[str]:
    supported = set(capabilities.get("supported_commands") or [])
    return [
        str(command)
        for command in metadata.get("required_commands", [])
        if str(command) not in supported
    ]


def _schema_mismatches(metadata: dict[str, Any], capabilities: dict[str, Any]) -> list[dict[str, Any]]:
    actual = capabilities.get("schema_versions") or {}
    mismatches: list[dict[str, Any]] = []
    for schema_name, expected_version in (metadata.get("required_schema_versions") or {}).items():
        actual_version = actual.get(schema_name)
        if actual_version != expected_version:
            mismatches.append(
                {
                    "schema": schema_name,
                    "expected": expected_version,
                    "actual": actual_version,
                }
            )
    return mismatches


def _read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _version_tuple(version: str) -> tuple[int, ...]:
    values: list[int] = []
    for part in version.split("."):
        digits = "".join(character for character in part if character.isdigit())
        values.append(int(digits or "0"))
    return tuple(values)


def _looks_like_git_commit(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return 7 <= len(value) <= 40 and all(character in "0123456789abcdef" for character in value.lower())
