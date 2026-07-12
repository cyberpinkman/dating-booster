from __future__ import annotations

import json
from pathlib import Path

import pytest

import dating_boost.apps.tashuo.standalone_production_runner as runner_module
from dating_boost.apps.tashuo.standalone_production_artifacts import create_qualification_paths
from dating_boost.apps.tashuo.standalone_production_runner import (
    DefaultProductionPreflight,
    _mac_ui_environment_probe,
    _tashuo_bundle_fingerprint,
)
from dating_boost.apps.tashuo.standalone_production_runtime import _provider_identity_matches


@pytest.fixture(autouse=True)
def _local_test_key(monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    monkeypatch.setenv("DATING_BOOST_TEST_KEY", "production-preflight-test-key")
    monkeypatch.setenv("MINIMAX_API_KEY", "provider-preflight-key")


def _paths(tmp_path: Path, suffix: str = "one"):
    source = tmp_path / f"source-{suffix}"
    source.mkdir()
    return create_qualification_paths(
        tmp_path / f"root-{suffix}",
        source_data_dir=source,
        qualification_id=f"qual_preflight_{suffix}",
    )


def _ui_environment(*, accessibility: bool = True, screen_recording: bool = True):
    return {
        "display": {
            "logical_bounds": [0, 0, 1440, 900],
            "pixel_bounds": [0, 0, 2880, 1800],
            "scale_factor": 2,
            "appearance": "dark",
            "locale": "zh_CN",
        },
        "permissions": {
            "accessibility": accessibility,
            "screen_recording": screen_recording,
        },
    }


def _provider(_config, _credential):
    return {
        "status": "ok",
        "response_model_identifier": "MiniMax-M3",
        "revision_identifier": "revision-1",
        "stable_provider_identifier": "revision-1",
    }


def _patch_host_checks(monkeypatch, *, clean: bool = True):
    monkeypatch.setattr(runner_module, "release_doctor", lambda: {"status": "ok"})
    monkeypatch.setattr(
        runner_module,
        "run_codex_adapter_doctor",
        lambda _data_dir: {"status": "ok"},
    )
    monkeypatch.setattr(
        runner_module,
        "build_capabilities",
        lambda _data_dir: {
            "managed_live_send_guidance": {
                "direct_harness_scope": "executor_internal_only"
            },
            "storage_capabilities": {
                "storage_backend": "sqlite",
                "encrypted_default": True,
            },
            "schema_versions": {"standalone_production_qualification": 1},
            "agent_native_capabilities": {
                "tashuo_standalone_production_qualification": True,
                "tashuo_standalone_production_qualification_runtime": "mac-ios-app",
                "tashuo_standalone_production_qualification_send_mode": "stage",
                "tashuo_standalone_production_qualification_live_send_qualified": False,
            },
        },
    )
    monkeypatch.setattr(
        runner_module,
        "_source_execution_fingerprint",
        lambda _root: {
            "mode": "source_checkout",
            "git_commit": "commit-1",
            "tree_digest": "tree-1",
            "clean": clean,
        },
    )
    monkeypatch.setattr(runner_module, "_dependency_digest", lambda: "dependency-digest")
    monkeypatch.setattr(
        runner_module,
        "_system_fingerprint",
        lambda: {
            "product_version": "15.5",
            "build_version": "24F74",
            "architecture": "arm64",
            "boot_session_id": "boot-1",
        },
    )
    monkeypatch.setattr(
        runner_module,
        "_tashuo_bundle_fingerprint",
        lambda: {
            "bundle_id": "com.intelcupid.tashuo",
            "short_version": "5.70.1",
            "build_version": "0",
            "executable_digest": "tashuo-executable-digest",
            "bundle_layout": "mac_ios_wrapped",
        },
    )


def _run(preflight: DefaultProductionPreflight, paths):
    return preflight.run(
        paths=paths,
        snapshot_digest="snapshot-digest",
        authorization_digest="authorization-digest",
        qualification_salt="qualification-salt",
        expected_environment_fingerprint=None,
    )


def test_default_preflight_pins_non_gui_environment_and_runtime_scope(tmp_path, monkeypatch):
    _patch_host_checks(monkeypatch)
    paths = _paths(tmp_path)
    preflight = DefaultProductionPreflight(
        source_checkout=Path.cwd(),
        provider_probe=_provider,
        ui_environment_probe=_ui_environment,
    )

    result = _run(preflight, paths)

    assert result["status"] == "ok", result
    assert result["checks"]["runtime_scope"] == "tashuo/mac-ios-app"
    assert result["checks"]["direct_harness_scope"] == "executor_internal_only"
    assert result["environment_fingerprint"]["execution"]["clean"] is True
    assert result["environment_fingerprint"]["model"]["response_model_identifier"] == "MiniMax-M3"
    assert result["environment_fingerprint"]["credential_fingerprint"] != "provider-preflight-key"


@pytest.mark.parametrize(
    ("clean", "accessibility", "screen_recording", "reason"),
    [
        (False, True, True, "environment_dirty_source_checkout"),
        (True, False, True, "environment_permission_missing"),
        (True, True, False, "environment_permission_missing"),
    ],
)
def test_default_preflight_blocks_dirty_source_or_missing_permissions(
    tmp_path,
    monkeypatch,
    clean,
    accessibility,
    screen_recording,
    reason,
):
    _patch_host_checks(monkeypatch, clean=clean)
    paths = _paths(tmp_path, suffix=reason + str(accessibility) + str(screen_recording))
    preflight = DefaultProductionPreflight(
        source_checkout=Path.cwd(),
        provider_probe=_provider,
        ui_environment_probe=lambda: _ui_environment(
            accessibility=accessibility,
            screen_recording=screen_recording,
        ),
    )

    result = _run(preflight, paths)

    assert result == {"status": "blocked", "reason": reason}


def test_action_recheck_detects_credential_hmac_drift_without_second_provider_call(
    tmp_path,
    monkeypatch,
):
    _patch_host_checks(monkeypatch)
    paths = _paths(tmp_path)
    calls = {"provider": 0}

    def provider(config, credential):
        calls["provider"] += 1
        return _provider(config, credential)

    preflight = DefaultProductionPreflight(
        source_checkout=Path.cwd(),
        provider_probe=provider,
        ui_environment_probe=_ui_environment,
    )
    initial = _run(preflight, paths)
    monkeypatch.setenv("MINIMAX_API_KEY", "different-provider-key")

    result = preflight.recheck_action(
        snapshot_digest="snapshot-digest",
        authorization_digest="authorization-digest",
        qualification_salt="qualification-salt",
        expected_environment_fingerprint=initial["environment_fingerprint"],
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "environment_drift"
    assert "credential_fingerprint" in result["drift_fields"]
    assert calls["provider"] == 1


@pytest.mark.parametrize(
    ("capabilities", "reason"),
    [
        (
            {
                "managed_live_send_guidance": {
                    "direct_harness_scope": "executor_internal_only"
                },
                "storage_capabilities": {
                    "storage_backend": "json",
                    "encrypted_default": True,
                },
            },
            "encrypted_sqlite_storage_required",
        ),
        (
            {
                "managed_live_send_guidance": {
                    "direct_harness_scope": "executor_internal_only"
                },
                "storage_capabilities": {
                    "storage_backend": "sqlite",
                    "encrypted_default": True,
                },
                "schema_versions": {"standalone_production_qualification": 1},
                "agent_native_capabilities": {
                    "tashuo_standalone_production_qualification": True,
                    "tashuo_standalone_production_qualification_runtime": "mac-ios-app",
                    "tashuo_standalone_production_qualification_send_mode": "live",
                    "tashuo_standalone_production_qualification_live_send_qualified": False,
                },
            },
            "production_qualification_capability_invalid",
        ),
    ],
)
def test_preflight_rejects_non_sqlite_or_non_stage_gate_capabilities(
    tmp_path,
    monkeypatch,
    capabilities,
    reason,
):
    _patch_host_checks(monkeypatch)
    monkeypatch.setattr(runner_module, "build_capabilities", lambda _data_dir: capabilities)
    preflight = DefaultProductionPreflight(
        source_checkout=Path.cwd(),
        provider_probe=_provider,
        ui_environment_probe=_ui_environment,
    )

    result = _run(preflight, _paths(tmp_path, suffix=reason))

    assert result == {"status": "blocked", "reason": reason}


def test_provider_response_model_and_revision_must_match_preflight_identity():
    expected = {
        "response_model_identifier": "MiniMax-M3",
        "provider_identifier": "revision-1",
    }

    assert _provider_identity_matches(
        expected,
        {
            "response_model_identifier": "MiniMax-M3",
            "stable_provider_identifier": "revision-1",
        },
    ) is True
    assert _provider_identity_matches(
        expected,
        {
            "response_model_identifier": "MiniMax-M3-new",
            "stable_provider_identifier": "revision-1",
        },
    ) is False
    assert _provider_identity_matches(
        expected,
        {
            "response_model_identifier": "MiniMax-M3",
            "stable_provider_identifier": "revision-2",
        },
    ) is False


def test_environment_probe_overrides_are_structured_and_do_not_open_apps(monkeypatch):
    ui = _ui_environment()
    bundle = {
        "bundle_id": "com.intelcupid.tashuo",
        "short_version": "5.70.1",
        "build_version": "0",
        "executable_digest": "digest",
        "bundle_layout": "mac_ios_wrapped",
    }
    monkeypatch.setenv("DATING_BOOST_MAC_UI_ENVIRONMENT_JSON", json.dumps(ui))
    monkeypatch.setenv(
        "DATING_BOOST_TASHUO_BUNDLE_FINGERPRINT_JSON",
        json.dumps(bundle),
    )

    assert _mac_ui_environment_probe() == ui
    assert _tashuo_bundle_fingerprint() == bundle
