from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.core.storage import JsonStorage


TIMELINE_PATH = Path("host_loop") / "timeline.jsonl"


def latest_replay_payload(data_dir: Path) -> dict[str, Any]:
    storage = JsonStorage(data_dir)
    timeline_path = data_dir / TIMELINE_PATH
    timeline = storage.read_jsonl(TIMELINE_PATH)
    report_relative_path = Path("automation") / "reports" / "machine_latest.json"
    report_path = data_dir / report_relative_path
    try:
        report = storage.read_json(report_relative_path, expected_schema_version=1)
    except FileNotFoundError:
        report = None
    return {
        "schema_version": 1,
        "status": "ok" if timeline or report else "not_found",
        "timeline_path": str(timeline_path),
        "event_count": len(timeline),
        "timeline": timeline,
        "machine_report_path": str(report_path) if report is not None else None,
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
