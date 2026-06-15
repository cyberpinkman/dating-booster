from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dating_boost.apps.registry import manifest_for_app, supported_app_ids
from dating_boost.core.storage import JsonStorage


RUNTIME_SCOPE_SCHEMA_VERSION = 1
RUNTIME_SCOPE_PATH = Path("runtime") / "session_scope.json"


def normalize_runtime(value: Any) -> str:
    text = str(value or "").strip().replace("-", "_")
    if not text or text in {"default", "app_default"}:
        return "default"
    if text in {"iphone_mirroring", "iphone_mirroring_macos"}:
        return "iphone_mirroring_macos"
    if text in {"mac_ios_app", "macos_ios_app"}:
        return "mac_ios_app"
    if text in {"macos_wechat", "macos_wechat_desktop"}:
        return "macos_wechat_desktop"
    return text


def runtime_display(value: Any) -> str:
    runtime = normalize_runtime(value)
    if runtime == "default":
        return "default"
    return runtime.replace("_", "-")


class RuntimeScopeRepository:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self._storage = JsonStorage(self.root)

    def read(self) -> dict[str, Any] | None:
        path = self.root / RUNTIME_SCOPE_PATH
        if not path.exists():
            return None
        return self._storage.read_json(RUNTIME_SCOPE_PATH, expected_schema_version=RUNTIME_SCOPE_SCHEMA_VERSION)

    def select(self, *, app_id: str, runtime: str | None, source: str = "manual") -> dict[str, Any]:
        app_id = _validate_app_id(app_id)
        runtime_key = normalize_runtime(runtime)
        existing = self.read()
        if existing is not None:
            selected_app_id = str(existing.get("selected_app_id") or "")
            selected_runtime_key = normalize_runtime(existing.get("selected_runtime_key") or existing.get("selected_runtime"))
            if selected_app_id == app_id and selected_runtime_key == runtime_key:
                return {
                    **existing,
                    "status": "selected",
                    "already_selected": True,
                }
            return _runtime_scope_already_selected_payload(
                selected_app_id=selected_app_id,
                selected_runtime=selected_runtime_key,
                requested_app_id=app_id,
                requested_runtime=runtime_key,
            )
        payload = {
            "schema_version": RUNTIME_SCOPE_SCHEMA_VERSION,
            "status": "selected",
            "selected_app_id": app_id,
            "selected_runtime": runtime_display(runtime_key),
            "selected_runtime_key": runtime_key,
            "source": source,
            "selected_at": _now_iso(),
        }
        self._storage.write_json(RUNTIME_SCOPE_PATH, payload)
        return payload

    def clear(self, *, reason: str = "manual_clear") -> dict[str, Any]:
        path = self.root / RUNTIME_SCOPE_PATH
        existed = path.exists()
        if existed:
            path.unlink()
        return {
            "schema_version": RUNTIME_SCOPE_SCHEMA_VERSION,
            "status": "cleared" if existed else "not_found",
            "reason": reason,
            "cleared_at": _now_iso(),
        }

    def validate(self, *, app_id: str, runtime: str | None, require_selected: bool = False) -> dict[str, Any] | None:
        scope = self.read()
        requested_app_id = _validate_app_id(app_id)
        requested_runtime_key = normalize_runtime(runtime)
        if scope is None:
            if require_selected:
                return _runtime_scope_required_payload(
                    requested_app_id=requested_app_id,
                    requested_runtime=requested_runtime_key,
                )
            return None
        selected_app_id = str(scope.get("selected_app_id") or "")
        selected_runtime_key = normalize_runtime(scope.get("selected_runtime_key") or scope.get("selected_runtime"))
        if selected_app_id == requested_app_id and selected_runtime_key == requested_runtime_key:
            return None
        return _runtime_scope_mismatch_payload(
            selected_app_id=selected_app_id,
            selected_runtime=selected_runtime_key,
            requested_app_id=requested_app_id,
            requested_runtime=requested_runtime_key,
        )

    def ensure_selected(
        self,
        *,
        app_id: str,
        runtime: str | None,
        source: str,
        require_explicit_runtime_choice: bool = False,
    ) -> dict[str, Any]:
        block = self.validate(app_id=app_id, runtime=runtime)
        if block is not None:
            return block
        existing = self.read()
        if existing is not None:
            return existing
        requested_app_id = _validate_app_id(app_id)
        requested_runtime_key = normalize_runtime(runtime)
        if (
            require_explicit_runtime_choice
            and requested_runtime_key == "default"
            and _app_has_alternate_runtimes(requested_app_id)
        ):
            return _runtime_scope_required_payload(
                requested_app_id=requested_app_id,
                requested_runtime=requested_runtime_key,
            )
        return self.select(app_id=app_id, runtime=runtime, source=source)


def _runtime_scope_mismatch_payload(
    *,
    selected_app_id: str,
    selected_runtime: str,
    requested_app_id: str,
    requested_runtime: str,
) -> dict[str, Any]:
    return {
        "schema_version": RUNTIME_SCOPE_SCHEMA_VERSION,
        "status": "blocked",
        "reason": "runtime_scope_mismatch",
        "selected_app_id": selected_app_id,
        "selected_runtime": runtime_display(selected_runtime),
        "requested_app_id": requested_app_id,
        "requested_runtime": runtime_display(requested_runtime),
        "next_host_action": "restart_with_matching_target_app_runtime_or_clear_runtime_scope",
    }


def _runtime_scope_already_selected_payload(
    *,
    selected_app_id: str,
    selected_runtime: str,
    requested_app_id: str,
    requested_runtime: str,
) -> dict[str, Any]:
    return {
        "schema_version": RUNTIME_SCOPE_SCHEMA_VERSION,
        "status": "blocked",
        "reason": "runtime_scope_already_selected",
        "selected_app_id": selected_app_id,
        "selected_runtime": runtime_display(selected_runtime),
        "requested_app_id": requested_app_id,
        "requested_runtime": runtime_display(requested_runtime),
        "next_host_action": "runtime_clear_before_switching_target",
        "recovery_commands": [
            "dating-boost runtime clear --data-dir <data_dir> --reason user_requested_target_switch --json",
            (
                "dating-boost runtime select --data-dir <data_dir> "
                f"--app-id {requested_app_id} --runtime {runtime_display(requested_runtime)} --json"
            ),
        ],
    }


def _runtime_scope_required_payload(*, requested_app_id: str, requested_runtime: str) -> dict[str, Any]:
    return {
        "schema_version": RUNTIME_SCOPE_SCHEMA_VERSION,
        "status": "blocked",
        "reason": "runtime_scope_required",
        "requested_app_id": requested_app_id,
        "requested_runtime": runtime_display(requested_runtime),
        "next_host_action": "run_runtime_select_before_gui_work",
    }


def _validate_app_id(app_id: str) -> str:
    value = str(app_id or "").strip()
    if value not in set(supported_app_ids()):
        raise ValueError(f"unsupported app_id: {app_id}")
    return value


def _app_has_alternate_runtimes(app_id: str) -> bool:
    try:
        return bool(manifest_for_app(app_id).runtime_profiles)
    except KeyError:
        return False


def _now_iso() -> str:
    return os.environ.get("DATING_BOOST_NOW") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
