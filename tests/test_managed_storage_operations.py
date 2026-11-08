from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
import threading
from unittest.mock import patch

import pytest

from dating_boost.core.encryption import DataKeyProvider
from dating_boost.core.managed_run import JsonManagedRunStore, ManagedRun
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.storage import _OPERATION_STORES
from test_managed_run import Clock, FixtureAction, FixtureDecision, FixtureObservation, _candidate, _config


pytestmark = pytest.mark.managed_critical


def _runtime(root, *, idle=False):
    clock, candidate = Clock(), _candidate()
    observation = FixtureObservation(clock, [] if idle else [candidate])
    decision, action = FixtureDecision(), FixtureAction(clock, candidate)
    runtime = ManagedRun(JsonManagedRunStore(root), observation, decision, action, now=clock)
    assert runtime.start(_config(), run_id="synthetic")["status"] == "active"
    return runtime, observation, decision, action


@contextmanager
def _mock_keychain(root):
    keys = {"key": DataKeyProvider(root).load_existing_key()}
    counts = Counter()

    def probe():
        counts["probe"] += 1
        return True

    def lookup(self):
        counts["lookup"] += 1
        return keys["key"]

    with patch.dict(os.environ):
        os.environ.pop("DATING_BOOST_KEY_PROVIDER", None)
        os.environ.pop("DATING_BOOST_TEST_KEY", None)
        with patch("dating_boost.core.encryption.platform.system", return_value="Darwin"), \
                patch("dating_boost.core.encryption._security_cli_available", probe), \
                patch.object(DataKeyProvider, "_load_keychain_key", lookup), \
                patch.object(DataKeyProvider, "_store_keychain_key", side_effect=lambda key: keys.update(key=key)):
            yield counts, keys


@pytest.mark.parametrize(("idle", "lookup_budget"), [(True, 8), (False, 16)])
def test_tick_bounds_keychain_work_by_short_database_operations(tmp_path, monkeypatch, idle, lookup_budget):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    runtime, _, _, action = _runtime(tmp_path, idle=idle)
    with _mock_keychain(tmp_path) as (counts, _):
        result = runtime.tick()
        assert result["status"] == ("no_work" if idle else "confirmed")
        assert action.click_count == (0 if idle else 1)
        assert counts["lookup"] <= lookup_budget, counts
        assert counts["probe"] <= lookup_budget + 2, counts


def test_gui_and_model_ports_never_inherit_database_operation_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    runtime, observation, decision, action = _runtime(tmp_path)
    for port, names in (
        (observation, ("scan_message_list", "open_thread", "observe_thread")),
        (decision, ("prioritize", "decide")),
        (action, ("observe_composer", "stage_text", "click_send", "observe_post_send")),
    ):
        for name in names:
            original = getattr(port, name)

            def checked(*args, _original=original, **kwargs):
                assert _OPERATION_STORES.get() is None, "database cache crossed a GUI/model boundary"
                return _original(*args, **kwargs)

            monkeypatch.setattr(port, name, checked)
    assert runtime.tick()["status"] == "confirmed"


def test_status_reuses_one_provider_per_snapshot_and_refreshes_next_call(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    runtime, _, _, _ = _runtime(tmp_path)
    with _mock_keychain(tmp_path) as (counts, _):
        assert runtime.status()["status"] == "active"
        assert counts == {"probe": 1, "lookup": 1}
        assert runtime.status()["status"] == "active"
        assert counts == {"probe": 2, "lookup": 2}


def test_rekey_completes_during_model_call_and_same_tick_uses_new_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    runtime, _, decision, action = _runtime(tmp_path)
    entered, release = threading.Event(), threading.Event()
    decide = decision.decide

    def slow_model(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return decide(*args, **kwargs)

    monkeypatch.setattr(decision, "decide", slow_model)
    with _mock_keychain(tmp_path) as (_, keys), ThreadPoolExecutor(max_workers=2) as pool:
        before = keys["key"]
        running = pool.submit(runtime.tick)
        assert entered.wait(3)
        try:
            rotated = pool.submit(ProductionDataStore(tmp_path).rekey)
            assert rotated.result(timeout=2)["status"] == "ok", "model call held the database write lock"
            assert keys["key"] != before
        finally:
            release.set()
        assert running.result(timeout=3)["status"] == "confirmed"
        assert action.click_count == 1
        assert runtime.status()["run"]["confirmed_send_count"] == 1


def test_short_operation_reuses_provider_but_rekey_and_restore_refresh_it(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    root, archive = tmp_path / "data", tmp_path / "snapshot.zip"
    runtime, _, _, _ = _runtime(root)
    store = runtime.store
    assert ProductionDataStore(root).backup(archive, recovery_passphrase="synthetic-passphrase")["status"] == "ok"
    with _mock_keychain(root) as (counts, keys):
        with store.database_operation():
            assert store.load("synthetic").run_id == "synthetic"
            assert store.current_run_id() == "synthetic"
            assert store.load("synthetic").run_id == "synthetic"
        assert counts["lookup"] == 1
        previous_key = keys["key"]
        assert ProductionDataStore(root).rekey()["status"] == "ok"
        assert keys["key"] != previous_key
        before = counts["lookup"]
        with store.database_operation():
            assert store.load("synthetic").status == "active"
        assert counts["lookup"] == before + 1
        assert ProductionDataStore(root).restore(
            archive, confirm="restore", recovery_passphrase="synthetic-passphrase",
        )["status"] == "ok"
        before = counts["lookup"]
        with store.database_operation():
            assert store.load("synthetic").status == "active"
        assert counts["lookup"] == before + 1
