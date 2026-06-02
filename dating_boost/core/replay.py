from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TIMELINE_PATH = Path("host_loop") / "timeline.jsonl"


def latest_replay_payload(data_dir: Path) -> dict[str, Any]:
    timeline_path = data_dir / TIMELINE_PATH
    timeline: list[dict[str, Any]] = []
    if timeline_path.exists():
        for line in timeline_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if isinstance(event, dict):
                timeline.append(event)
    report_path = data_dir / "automation" / "reports" / "machine_latest.json"
    report = None
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        "schema_version": 1,
        "status": "ok" if timeline or report else "not_found",
        "timeline_path": str(timeline_path),
        "event_count": len(timeline),
        "timeline": timeline,
        "machine_report_path": str(report_path) if report_path.exists() else None,
        "machine_report": report,
    }


def latest_replay_markdown(data_dir: Path) -> str:
    payload = latest_replay_payload(data_dir)
    if payload["status"] != "ok":
        return "# Dating Booster Replay\n\nNo replay timeline found."
    lines = [
        "# Dating Booster Replay",
        "",
        f"- Events: {payload['event_count']}",
        f"- Timeline: {payload['timeline_path']}",
    ]
    if payload.get("machine_report_path"):
        lines.append(f"- Machine report: {payload['machine_report_path']}")
    lines.extend(["", "## Timeline", ""])
    for event in payload["timeline"]:
        lines.append(
            f"- {event.get('created_at', '')} `{event.get('event_type')}` "
            f"{event.get('work_item_type') or event.get('status') or ''}".rstrip()
        )
    return "\n".join(lines)
