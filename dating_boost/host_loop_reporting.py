from __future__ import annotations

from dating_boost.host_loop_common import *

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


__all__ = [name for name in globals() if not name.startswith("__")]
