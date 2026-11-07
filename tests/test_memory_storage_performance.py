import json
import multiprocessing
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from dating_boost.cli_sessions import _record_feedback
from dating_boost.core.encryption import DataKeyProvider
from dating_boost.core.memory.ingest import store_observation_with_memory
from dating_boost.core.memory.models import MemoryEvent, MemoryEventType, MemoryScope
from dating_boost.core.memory.repositories import MemoryRepository
from dating_boost.core.models import ReplyMode
from dating_boost.core.repositories import JsonMemoryRepository
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.production_store_schema import ProductionStoreSchemaMixin
from dating_boost.core.storage import JsonStorage, storage_operation, storage_write_lock
from dating_boost.perception.fixture_loader import load_observation


def _event(event_id, value="first"):
    return MemoryEvent(event_id, MemoryEventType.FEEDBACK_RECORDED, "match_test", MemoryScope.FEEDBACK_PREFERENCE,
                       "2026-11-07T00:00:00Z", {"mode": "adaptive", "label": "accepted", "value": value})


def _seed(root, backend):
    if backend == "empty":
        return
    index = {"schema_version": 1, "matches": [{"match_id": "match_test", "app_id": "tinder"}]}
    if backend == "legacy":
        (root / "matches").mkdir()
        (root / "matches/index.json").write_text(json.dumps(index), encoding="utf-8")
    else:
        JsonStorage(root).write_json(Path("matches/index.json"), index)


def test_existing_wal_store_reads_without_waiting_for_writer(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    store = ProductionDataStore(tmp_path)
    store.upsert_document("sample.json", {"schema_version": 1})
    store.append_audit_event("events.jsonl", {"event_id": "one"})
    writer = sqlite3.connect(store.db_path)
    writer.execute("BEGIN IMMEDIATE")

    def read_all():
        with patch.object(store, "_set_metadata", side_effect=AssertionError("a read wrote schema metadata")):
            assert store.get_document("sample.json") == {"schema_version": 1}
            assert store.document_exists("sample.json")
            assert len(store.list_documents(prefix="sample")) == 1
            assert len(store.list_audit_events(stream="events.jsonl")) == 1
            assert store.audit_stream_exists("events.jsonl")

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(read_all)
            try:
                future.result(timeout=0.5)
            finally:
                writer.rollback()
    finally:
        writer.close()


@pytest.mark.parametrize("backend", ["sqlite", "legacy"])
def test_memory_batch_is_atomic_and_first_write_wins(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    _seed(tmp_path, backend)
    repo = MemoryRepository(tmp_path)
    repo.append_events("match_test", [_event("one"), _event("one", "duplicate"), _event("two")])
    repo.append_events("match_test", [_event("one", "retry")])
    before = [event.to_dict() for event in repo.load_events("match_test")]
    assert [event["event_id"] for event in before] == ["one", "two"]
    assert before[0]["payload"]["value"] == "first"
    with pytest.raises(TypeError):
        repo.append_events("match_test", [_event("three"), _event("four", object())])
    assert [event.to_dict() for event in repo.load_events("match_test")] == before
    with pytest.raises(ValueError, match="match_id"):
        repo.append_events("match_test", [_event("three"), replace(_event("four"), match_id="another")])
    assert [event.to_dict() for event in repo.load_events("match_test")] == before


def _append_in_process(root, value, ready, go):
    ready.put(value)
    assert go.wait(10)
    MemoryRepository(root).append_events("match_test", [_event("shared", value), _event(value)])


@pytest.mark.parametrize("backend", ["sqlite", "legacy", "empty"])
def test_memory_batch_parallel_processes_preserve_first_writer(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    _seed(tmp_path, backend)
    ctx = multiprocessing.get_context("spawn")
    ready, go = ctx.Queue(), ctx.Event()
    workers = [ctx.Process(target=_append_in_process, args=(tmp_path, value, ready, go)) for value in ("one", "two")]
    try:
        for worker in workers:
            worker.start()
        assert {ready.get(timeout=10), ready.get(timeout=10)} == {"one", "two"}
        go.set()
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
        repo = MemoryRepository(tmp_path)
        events = repo.load_events("match_test")
        assert {event.event_id for event in events} == {"shared", "one", "two"}
        winner = next(event.payload["value"] for event in events if event.event_id == "shared")
        repo.append_events("match_test", [_event("shared", "retry")])
        assert next(event.payload["value"] for event in repo.load_events("match_test") if event.event_id == "shared") == winner
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(2)
        ready.close()


@pytest.mark.parametrize("backend", ["sqlite", "legacy"])
def test_rebuild_cannot_replace_concurrently_appended_feedback(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    _seed(tmp_path, backend)
    observation = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))
    match_id = store_observation_with_memory(tmp_path, observation)["match_id"]
    repo = MemoryRepository(tmp_path)
    loaded, release, writer_started = threading.Event(), threading.Event(), threading.Event()
    original = repo.load_events

    def pause_snapshot(*args):
        result = original(*args)
        if not loaded.is_set():
            loaded.set()
            assert release.wait(10)
        return result

    def append_feedback():
        writer_started.set()
        other = MemoryRepository(tmp_path)
        other.append_event(match_id, replace(_event("new_feedback"), match_id=match_id))
        other.rebuild_projection(match_id)

    with ThreadPoolExecutor(max_workers=2) as pool, patch.object(repo, "load_events", side_effect=pause_snapshot):
        rebuild = pool.submit(repo.rebuild_projection_from_observations, match_id, [observation])
        assert loaded.wait(10)
        writer = pool.submit(append_feedback)
        assert writer_started.wait(10)
        try:
            with pytest.raises(TimeoutError):
                writer.result(timeout=0.2)
        finally:
            release.set()
        rebuild.result(timeout=10)
        writer.result(timeout=10)
    assert "new_feedback" in {event.event_id for event in repo.load_events(match_id)}
    assert repo.load_projection(match_id).feedback_preferences["adaptive"]["labels"]["accepted"] == 1


def test_ingest_reads_history_once_and_reuses_only_operation_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    observation = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))
    match_id = store_observation_with_memory(tmp_path, observation)["match_id"]
    key = DataKeyProvider(tmp_path).load_existing_key()
    initial_count = len(MemoryRepository(tmp_path).load_events(match_id))
    original = ProductionStoreSchemaMixin._decode_audit_event
    decoded = []

    def count_decode(self, stream, event_id, stored):
        decoded.append(event_id)
        return original(self, stream, event_id, stored)

    with patch.object(DataKeyProvider, "_provider_name", return_value="keychain"), \
            patch.object(DataKeyProvider, "_load_keychain_key", return_value=key) as lookup, \
            patch.object(ProductionStoreSchemaMixin, "_decode_audit_event", count_decode):
        first = store_observation_with_memory(tmp_path, replace(observation, observation_id="second"))
        assert len(decoded) == initial_count
        assert lookup.call_count == 1
        decoded.clear()
        store_observation_with_memory(tmp_path, replace(observation, observation_id="third"))
        assert len(decoded) == first["memory_event_count"]
        assert lookup.call_count == 2


def test_operation_provider_is_refreshed_after_rekey_and_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    storage = JsonStorage(tmp_path)
    storage.write_json(Path("sample.json"), {"schema_version": 1, "value": "before"})
    keys = {"key": DataKeyProvider(tmp_path).load_existing_key()}
    with patch.object(DataKeyProvider, "_provider_name", return_value="keychain"), \
            patch.object(DataKeyProvider, "_load_keychain_key", side_effect=lambda: keys["key"]) as lookup, \
            patch.object(DataKeyProvider, "_store_keychain_key", side_effect=lambda key: keys.update(key=key)):
        with storage_operation():
            assert storage.read_json(Path("sample.json"), expected_schema_version=1)["value"] == "before"
            storage.read_json(Path("sample.json"), expected_schema_version=1)
            assert lookup.call_count == 1
        before_key = keys["key"]
        assert ProductionDataStore(tmp_path).rekey()["status"] == "ok"
        assert keys["key"] != before_key
        before_reads = lookup.call_count
        with storage_operation():
            assert storage.read_json(Path("sample.json"), expected_schema_version=1)["value"] == "before"
        assert lookup.call_count == before_reads + 1
        assert ProductionDataStore(tmp_path).delete(scope="all", match_id=None, confirm="delete:all")["status"] == "ok"
        with storage_operation():
            assert not storage.exists(Path("sample.json"))
            storage.write_json(Path("sample.json"), {"schema_version": 1, "value": "after"})
            assert storage.read_json(Path("sample.json"), expected_schema_version=1)["value"] == "after"


def test_feedback_first_write_is_shared_across_its_two_streams(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    loaded, release, second_started = threading.Event(), threading.Event(), threading.Event()
    original = JsonMemoryRepository.load_feedback_events

    def pause_first_read(self, match_id):
        result = original(self, match_id)
        if not loaded.is_set():
            loaded.set()
            assert release.wait(10)
        return result

    def record(value):
        if value == "second":
            second_started.set()
        return _record_feedback(data_dir=tmp_path, match_id="match_test", draft_id="draft",
                                mode=ReplyMode.ADAPTIVE, label="accepted", conversation_move=value)

    with ThreadPoolExecutor(max_workers=2) as pool, patch.object(JsonMemoryRepository, "load_feedback_events", pause_first_read):
        first = pool.submit(record, "first")
        assert loaded.wait(10)
        second = pool.submit(record, "second")
        assert second_started.wait(10)
        try:
            with pytest.raises(TimeoutError):
                second.result(timeout=0.2)
        finally:
            release.set()
        first.result(timeout=10)
        second.result(timeout=10)
    feedback = JsonMemoryRepository(tmp_path).load_feedback_events("match_test")
    events = MemoryRepository(tmp_path).load_events("match_test")
    assert len(feedback) == len(events) == 1
    assert feedback[0] == events[0].payload
    assert feedback[0]["conversation_move"] == "first"
    assert MemoryRepository(tmp_path).load_projection("match_test").feedback_preferences["adaptive"]["labels"]["accepted"] == 1


def test_rekey_waits_for_operation_using_cached_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    storage = JsonStorage(tmp_path)
    storage.write_json(Path("before.json"), {"schema_version": 1, "value": "before"})
    keys = {"key": DataKeyProvider(tmp_path).load_existing_key()}
    started = threading.Event()

    def rekey():
        started.set()
        return ProductionDataStore(tmp_path).rekey()

    with patch.object(DataKeyProvider, "_provider_name", return_value="keychain"), \
            patch.object(DataKeyProvider, "_load_keychain_key", side_effect=lambda: keys["key"]), \
            patch.object(DataKeyProvider, "_store_keychain_key", side_effect=lambda key: keys.update(key=key)), \
            ThreadPoolExecutor(max_workers=1) as pool:
        with storage_operation(), storage_write_lock(tmp_path):
            assert storage.read_json(Path("before.json"), expected_schema_version=1)["value"] == "before"
            rotated = pool.submit(rekey)
            assert started.wait(10)
            try:
                with pytest.raises(TimeoutError):
                    rotated.result(timeout=0.2)
            finally:
                storage.write_json(Path("after.json"), {"schema_version": 1, "value": "after"})
        assert rotated.result(timeout=10)["status"] == "ok"
        # A fresh operation must decrypt both the old and the concurrently written row.
        with storage_operation():
            assert storage.read_json(Path("before.json"), expected_schema_version=1)["value"] == "before"
            assert storage.read_json(Path("after.json"), expected_schema_version=1)["value"] == "after"
