from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.core.standalone_actions import StageOnlyActionExecutor, StandaloneManagedGuiSendExecutor
from dating_boost.core.standalone_observation import FixtureObservationProvider, fixture_harness_factory
from dating_boost.intelligence.vision_backend_factory import create_vision_backend


def build_standalone_runtime_ports(root: Path, session: dict[str, Any]) -> dict[str, Any]:
    source = session.get("observation_source") if isinstance(session.get("observation_source"), dict) else {}
    source_type = str(source.get("type") or "").strip()
    send_mode = str(session.get("send_mode") or "stage")

    if source_type == "fixture_dir":
        source_path = source.get("path")
        if not isinstance(source_path, str) or not source_path.strip():
            return _blocked("standalone_observation_fixture_dir_required")
        fixture_dir = Path(source_path).expanduser().resolve()
        if not fixture_dir.is_dir():
            return _blocked("observation_fixture_dir_not_found")
        provider = FixtureObservationProvider(fixture_dir)
        return {
            "schema_version": 1,
            "status": "ok",
            "observation_source_type": "fixture_dir",
            "observation_provider": provider,
            "harness_factory": fixture_harness_factory(provider),
            "action_executor": StageOnlyActionExecutor(root, send_mode=send_mode),
        }

    if source_type == "live_gui":
        app_id = str(source.get("app_id") or session.get("app_id") or "").strip()
        runtime = str(source.get("runtime") or session.get("runtime") or "").strip()
        if app_id != "tashuo" or runtime != "mac-ios-app":
            return _blocked("unsupported_live_gui_observation_source")
        vision_config = session.get("vision_backend") if isinstance(session.get("vision_backend"), dict) else {}
        if not vision_config:
            return _blocked("vision_backend_required_for_live_gui_source")

        output_dir = Path(source.get("output_dir") or root / "standalone_harness").expanduser()
        try:
            create_vision_backend(dict(vision_config))
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            return _blocked(str(exc))
        provider = _PendingTaShuoLiveGuiProvider()

        def _harness_factory(factory_app_id: str, runtime: str | None = None) -> _PendingTaShuoLiveGuiHarness:
            return _PendingTaShuoLiveGuiHarness(app_id=factory_app_id, runtime=runtime)

        return {
            "schema_version": 1,
            "status": "ok",
            "observation_source_type": "live_gui",
            "observation_provider": provider,
            "harness_factory": _harness_factory,
            "action_executor": StandaloneManagedGuiSendExecutor(root)
            if send_mode == "live"
            else StageOnlyActionExecutor(root, send_mode=send_mode),
            "output_dir": str(output_dir),
        }

    return _blocked("unsupported_standalone_observation_source")


class _PendingTaShuoLiveGuiProvider:
    def observe_message_list(self, *, app_id: str, scan_cursor: dict[str, Any]) -> dict[str, Any]:
        return _pending_tashuo_provider_payload(app_id=app_id, observation_type="message_list")

    def observe_thread(self, *, app_id: str, candidate_key: str) -> dict[str, Any]:
        return _pending_tashuo_provider_payload(
            app_id=app_id,
            observation_type="thread",
            candidate_key=candidate_key,
        )

    def observe_current_thread(self, *, app_id: str) -> dict[str, Any]:
        return _pending_tashuo_provider_payload(app_id=app_id, observation_type="thread", candidate_key="current_thread")

    def precheck_payload(self, *, app_id: str) -> dict[str, Any]:
        return _pending_tashuo_provider_payload(app_id=app_id, observation_type="precheck")


class _PendingTaShuoLiveGuiHarness:
    def __init__(self, *, app_id: str, runtime: str | None):
        self.app_id = app_id
        self.runtime = runtime

    def observe(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": "blocked",
            "reason": "tashuo_standalone_provider_not_ready",
            "app_id": self.app_id,
            "runtime": self.runtime or "mac-ios-app",
        }


def _pending_tashuo_provider_payload(*, app_id: str, observation_type: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "blocked",
        "reason": "tashuo_standalone_provider_not_ready",
        "app_id": app_id,
        "runtime": "mac-ios-app",
        "observation_type": observation_type,
        **extra,
    }


def _blocked(reason: str) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason}
