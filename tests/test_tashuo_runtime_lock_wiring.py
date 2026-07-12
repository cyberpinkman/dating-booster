from __future__ import annotations

import json
from unittest.mock import patch

from dating_boost.apps.registry import create_adapter
from dating_boost.core.gui_runtime_lock import GuiRuntimeLock
from tests.gui_harness_support import FakeRunner


def _adapter(monkeypatch, tmp_path):
    monkeypatch.setenv("DATING_BOOST_ENFORCE_RUNTIME_LOCK_FOR_TESTS", "1")
    monkeypatch.setenv("DATING_BOOST_RUNTIME_LOCK_ROOT", str(tmp_path / "runtime"))
    return create_adapter(
        "tashuo",
        platform="darwin",
        runner=FakeRunner(ocr_text="", window_name="她说"),
        runtime="mac_ios_app",
    )


def test_tashuo_mac_ios_adapter_blocks_when_shared_runtime_is_owned_elsewhere(monkeypatch, tmp_path):
    external = GuiRuntimeLock(state_root=tmp_path / "runtime").acquire(
        owner_id="external_owner", owner_nonce="external_nonce"
    )
    try:
        adapter = _adapter(monkeypatch, tmp_path)
        with patch("dating_boost.apps.tashuo.adapter.tashuo_native.observe_tashuo_screen") as observe:
            payload = adapter.observe()
        assert payload["status"] == "blocked"
        assert payload["reason"] == "runtime_os_lock_held"
        observe.assert_not_called()
    finally:
        external.release()


def test_tashuo_mac_ios_adapter_honors_runtime_safety_pause(monkeypatch, tmp_path):
    lock = GuiRuntimeLock(state_root=tmp_path / "runtime")
    lock.pause(reason="composer_state_unknown")
    adapter = _adapter(monkeypatch, tmp_path)

    with patch("dating_boost.apps.tashuo.adapter.tashuo_native.observe_tashuo_screen") as observe:
        payload = adapter.observe()

    assert payload["status"] == "blocked"
    assert payload["reason"] == "runtime_safety_paused"
    observe.assert_not_called()


def test_tashuo_mac_ios_adapter_accepts_valid_delegated_capability_without_reacquiring(monkeypatch, tmp_path):
    lock = GuiRuntimeLock(state_root=tmp_path / "runtime")
    parent = lock.acquire(owner_id="qualification_owner", owner_nonce="qualification_nonce")
    monkeypatch.setenv("DATING_BOOST_GUI_RUNTIME_CAPABILITY", json.dumps(parent.delegated_capability()))
    try:
        adapter = _adapter(monkeypatch, tmp_path)
        expected = {"schema_version": 1, "status": "ok", "screen_state": "tashuo_conversation"}
        with patch(
            "dating_boost.apps.tashuo.adapter.tashuo_native.observe_tashuo_screen",
            return_value=expected,
        ) as observe:
            payload = adapter.observe()
        assert payload == expected
        observe.assert_called_once()
        assert lock.status()["lease"]["owner_id"] == "qualification_owner"
    finally:
        parent.release()


def test_unmanaged_tashuo_mac_ios_call_acquires_and_releases_transient_lock(monkeypatch, tmp_path):
    adapter = _adapter(monkeypatch, tmp_path)
    expected = {"schema_version": 1, "status": "ok"}

    with patch(
        "dating_boost.apps.tashuo.adapter.tashuo_native.observe_tashuo_screen",
        return_value=expected,
    ):
        assert adapter.observe() == expected
        first_token = GuiRuntimeLock(state_root=tmp_path / "runtime").status()["lease"]["fencing_token"]
        assert adapter.observe() == expected
        status = GuiRuntimeLock(state_root=tmp_path / "runtime").status()

    assert status["lease"]["status"] == "released"
    assert status["lease"]["fencing_token"] > first_token
