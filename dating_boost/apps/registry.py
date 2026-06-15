from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dating_boost.apps.base import AppManifest
from dating_boost.apps.bumble import BumbleAdapter
from dating_boost.apps.tashuo import TaShuoAdapter
from dating_boost.apps.tinder import TinderAdapter
from dating_boost.apps.wechat import WeChatAdapter


PROFILE_DIR = Path(__file__).resolve().parents[2] / "app_profiles"


_ADAPTER_CLASSES = {
    "tinder": TinderAdapter,
    "wechat": WeChatAdapter,
    "bumble": BumbleAdapter,
    "tashuo": TaShuoAdapter,
}


def _load_profiles() -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for path in sorted(PROFILE_DIR.glob("*.json")):
        profile = json.loads(path.read_text(encoding="utf-8"))
        profiles[str(profile["app_id"])] = profile
    return profiles


def _profile_for(app_id: str) -> dict[str, Any]:
    profiles = _load_profiles()
    if app_id not in profiles:
        raise KeyError(app_id)
    return profiles[app_id]


def supported_app_ids() -> tuple[str, ...]:
    profiles = _load_profiles()
    return tuple(app_id for app_id in _ADAPTER_CLASSES if app_id in profiles)


def host_loop_app_ids() -> tuple[str, ...]:
    profiles = _load_profiles()
    return tuple(
        app_id
        for app_id in _ADAPTER_CLASSES
        if app_id in profiles and profiles[app_id].get("host_loop_supported") is True
    )


def app_profile(app_id: str) -> dict[str, Any]:
    return dict(_profile_for(app_id))


def manifest_for_app(app_id: str) -> AppManifest:
    profile = _profile_for(app_id)
    if app_id not in _ADAPTER_CLASSES:
        raise KeyError(app_id)
    return AppManifest.from_profile(profile)


def adapter_manifests() -> dict[str, AppManifest]:
    return {app_id: manifest_for_app(app_id) for app_id in supported_app_ids()}


def get_adapter(app_id: str):
    return create_adapter(app_id)


def create_adapter(
    app_id: str,
    *,
    platform: str | None = None,
    runner: Any | None = None,
    window_title: str | None = None,
    runtime: str | None = None,
):
    adapter_cls = _ADAPTER_CLASSES.get(app_id)
    if adapter_cls is None:
        raise KeyError(app_id)
    if _real_gui_adapter_disabled_for_tests(runner=runner):
        raise RuntimeError(
            "real_gui_adapter_disabled_in_tests: pass a fake runner/session or set "
            "DATING_BOOST_ALLOW_REAL_GUI_TESTS=1 for an explicit real-device test"
        )
    return adapter_cls(
        manifest=manifest_for_app(app_id),
        platform=platform,
        runner=runner,
        window_title=window_title,
        runtime=runtime,
    )


def _real_gui_adapter_disabled_for_tests(*, runner: Any | None) -> bool:
    if runner is not None:
        return False
    if os.environ.get("DATING_BOOST_ALLOW_REAL_GUI_TESTS") == "1":
        return False
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def target_binding_policy(app_id: str) -> dict[str, Any]:
    return dict(manifest_for_app(app_id).target_binding_policy)


def managed_session_policy(app_id: str) -> dict[str, Any]:
    return dict(manifest_for_app(app_id).managed_session_policy)


def capability_manifest() -> dict[str, Any]:
    all_profiles = _load_profiles()
    profiles = {app_id: all_profiles[app_id] for app_id in _ADAPTER_CLASSES if app_id in all_profiles}
    return {
        "supported_app_profiles": list(profiles),
        "host_loop_app_profiles": [
            app_id for app_id, profile in profiles.items() if profile.get("host_loop_supported") is True
        ],
        "apps": {
            app_id: {
                "support_level": profile.get("support_level"),
                "host_loop_supported": bool(profile.get("host_loop_supported")),
                "host_loop_send_modes": list(profile.get("host_loop_send_modes") or []),
                "adapter_module": (profile.get("adapter") or {}).get("module")
                if isinstance(profile.get("adapter"), dict)
                else None,
                "backend": (profile.get("adapter") or {}).get("backend")
                if isinstance(profile.get("adapter"), dict)
                else (profile.get("native_gui_harness") or {}).get("backend"),
                "supported_stage_actions": list(
                    profile.get("native_gui_harness", {}).get("supported_stage_actions") or []
                ),
                "supported_live_actions": list(profile.get("native_gui_harness", {}).get("supported_live_actions") or []),
                "supported_actions": list((profile.get("capabilities") or {}).get("actions") or []),
                "supported_workflows": list((profile.get("capabilities") or {}).get("workflows") or []),
                "alternate_runtimes": dict(
                    ((profile.get("native_gui_harness") or {}).get("alternate_runtimes") or {})
                    if isinstance((profile.get("native_gui_harness") or {}).get("alternate_runtimes"), dict)
                    else {}
                ),
                "target_binding": dict(profile.get("target_binding") or {}),
                "live_send_requirements": dict(profile.get("live_send_requirements") or {}),
                "cli_aliases": dict(profile.get("cli_aliases") or {}),
            }
            for app_id, profile in profiles.items()
        },
    }
