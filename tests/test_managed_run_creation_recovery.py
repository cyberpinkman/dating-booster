"""A committed active run must remain indexed when post-write cleanup fails."""

import pytest

from dating_boost.core.managed_run import JsonManagedRunStore
from tests.test_managed_run import _config, _runtime


pytestmark = pytest.mark.managed_critical


@pytest.mark.parametrize("backend", ["sqlite", "legacy"])
@pytest.mark.parametrize("failure", ["before_commit", "after_commit", "after_commit_probe_failed"])
def test_create_rollback_requires_proof_that_the_new_run_is_absent(tmp_path, monkeypatch, backend, failure):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    if backend == "legacy":
        (tmp_path / "matches").mkdir()
        (tmp_path / "matches/index.json").write_text('{"schema_version": 1, "matches": []}')
    store = JsonManagedRunStore(tmp_path)
    runtime, _, _, _, _, _ = _runtime(store=store)
    runtime.start(_config(), run_id="previous")
    runtime.stop()
    run_path = store._run_path("new-run")

    if failure == "before_commit":
        write_json = store._storage.write_json

        def fail_write(path, payload):
            if path == run_path:
                raise OSError("synthetic new-run write failed")
            return write_json(path, payload)

        monkeypatch.setattr(store._storage, "write_json", fail_write)
    else:
        if backend == "sqlite":
            # A remaining legacy file triggers cleanup after the SQLite commit.
            legacy_path = tmp_path / run_path
            legacy_path.parent.mkdir(parents=True, exist_ok=True)
            legacy_path.write_text("{}")
        fsync_directory = store._storage._fsync_directory
        exists = store._storage.exists
        failed = False

        def fail_fsync(path):
            nonlocal failed
            if path == tmp_path / "managed_run/runs":
                failed = True
                raise OSError("synthetic new-run write failed")
            return fsync_directory(path)

        def fail_probe(path):
            if failed and path == run_path:
                raise OSError("synthetic outcome probe unavailable")
            return exists(path)

        monkeypatch.setattr(store._storage, "_fsync_directory", fail_fsync)
        if failure == "after_commit_probe_failed":
            monkeypatch.setattr(store._storage, "exists", fail_probe)

    with pytest.raises(OSError, match="synthetic new-run write failed"):
        runtime.start(_config(), run_id="new-run")

    # A fresh store has neither fault injection nor in-process state to rely on.
    recovered = JsonManagedRunStore(tmp_path)
    restarted, _, _, _, action, _ = _runtime(store=recovered)
    if failure == "before_commit":
        assert recovered.load("new-run") is None
        assert recovered.current_run_id() == "previous"
        assert restarted.start(_config(), run_id="replacement")["status"] == "active"
    else:
        assert recovered.load("new-run").status == "active"
        assert recovered.current_run_id() == "new-run"
        result = restarted.start(_config(), run_id="replacement")
        assert result["reason"] == "managed_run_already_active"
        assert recovered.load("replacement") is None
        assert restarted.tick()["status"] == "confirmed"
        assert action.click_count == 1
