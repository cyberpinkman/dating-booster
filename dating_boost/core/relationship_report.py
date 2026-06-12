from __future__ import annotations

from pathlib import Path
from typing import Any


RELATIONSHIP_PROGRESS_REPORT_SCHEMA_VERSION = 1
RELATIONSHIP_PROGRESS_NEXT_ACTION = "present_relationship_progress_report"


def build_relationship_progress_report(
    *,
    data_dir: Path,
    human_report_path: Path | str,
    machine_report_path: Path | str | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    human_path = _resolve_report_path(data_dir, human_report_path)
    machine_path = _resolve_report_path(data_dir, machine_report_path) if machine_report_path is not None else None
    return {
        "schema_version": RELATIONSHIP_PROGRESS_REPORT_SCHEMA_VERSION,
        "report_type": "relationship_progress",
        "format": "markdown",
        "markdown": human_path.read_text(encoding="utf-8") if human_path.exists() else "",
        "human_report_path": str(human_path),
        "machine_report_path": str(machine_path) if machine_path is not None else None,
        "summary": dict(summary or {}),
        "next_host_action": RELATIONSHIP_PROGRESS_NEXT_ACTION,
    }


def _resolve_report_path(data_dir: Path, path: Path | str) -> Path:
    report_path = Path(path)
    if report_path.is_absolute():
        return report_path
    return (data_dir / report_path).resolve()
