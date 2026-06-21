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
            vision_backend = create_vision_backend(dict(vision_config))
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            return _blocked(str(exc))
        from dating_boost.apps.tashuo.standalone import (
            TaShuoMacIosStageExecutor,
            TaShuoMacIosStandaloneObservationProvider,
            TaShuoStandalonePrecheckHarness,
        )

        provider = TaShuoMacIosStandaloneObservationProvider(
            root=root,
            output_dir=output_dir,
            vision_backend=vision_backend,
        )

        def _harness_factory(factory_app_id: str, runtime: str | None = None) -> TaShuoStandalonePrecheckHarness:
            return TaShuoStandalonePrecheckHarness(provider, app_id=factory_app_id, runtime=runtime)

        return {
            "schema_version": 1,
            "status": "ok",
            "observation_source_type": "live_gui",
            "observation_provider": provider,
            "harness_factory": _harness_factory,
            "action_executor": StandaloneManagedGuiSendExecutor(root)
            if send_mode == "live"
            else TaShuoMacIosStageExecutor(root=root, output_dir=output_dir),
            "output_dir": str(output_dir),
        }

    return _blocked("unsupported_standalone_observation_source")


def _blocked(reason: str) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason}
