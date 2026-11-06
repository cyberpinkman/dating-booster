"""Exercise independent repository processes against both storage backends."""
import json
import multiprocessing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.repositories import MatchRepository, ObservationRepository
from dating_boost.core.storage import JsonStorage
from dating_boost.perception.fixture_loader import load_observation


def _mutate(root, kind, key, rendezvous):
    observation = replace(load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json")), observation_id=key)
    if kind == "index":
        repo = MatchRepository(root)
        method = "_load_index"
    elif kind == "delete":
        repo = ProductionDataStore(root)
        method = "_decode_document"
    else:
        repo = ObservationRepository(root)
        method = "_load_document"
    read = getattr(repo, method)
    paused = False

    def pause_first_snapshot(*args):
        nonlocal paused
        document = read(*args)
        if not paused and (kind != "delete" or args[0] == "matches/index.json"):
            paused = True
            rendezvous.send("read")
            if not rendezvous.poll(15):
                raise TimeoutError("test did not release snapshot")
            rendezvous.recv()
        return document

    with patch.object(repo, method, pause_first_snapshot):
        rendezvous.send("ready")
        rendezvous.recv()
        if kind == "index":
            repo.upsert_match_from_observation(match_id=key, observation=observation,
                                               confidence="high", requires_user_confirmation=False)
        elif kind == "delete":
            result = repo.delete(scope="match", match_id=key, confirm=f"delete:match:{key}")
            assert result["status"] == "ok"
        else:
            repo.save_observation("match_existing", observation)


def _overlap_writes(root, operations):
    ctx = multiprocessing.get_context("spawn")
    workers = []
    channels = []
    try:
        for kind, key in operations:
            parent, child = ctx.Pipe()
            worker = ctx.Process(target=_mutate, args=(root, kind, key, child))
            worker.start()
            child.close()
            workers.append(worker)
            channels.append(parent)
        for channel in channels:
            assert channel.poll(15) and channel.recv() == "ready"
        first, second = channels
        first.send("start")
        assert first.poll(15) and first.recv() == "read"
        second.send("start")
        # Before atomic updates both can reach this point with the same snapshot.
        # With serialization the second snapshot can only arrive after the first commits.
        if second.poll(0.3):
            assert second.recv() == "read"
            second.send("write")
            workers[1].join(15)
            assert workers[1].exitcode == 0
            first.send("write")
        else:
            first.send("write")
            assert second.poll(15) and second.recv() == "read"
            second.send("write")
        for worker in workers:
            worker.join(15)
            assert worker.exitcode == 0
    finally:
        for channel in channels:
            channel.close()
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(5)


@pytest.mark.parametrize("backend", ["sqlite", "legacy"])
@pytest.mark.parametrize("kind", ["index", "observations"])
def test_concurrent_repository_processes_preserve_both_updates(tmp_path, monkeypatch, backend, kind):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    index = {"schema_version": 1, "matches": [{"match_id": "match_existing", "app_id": "tinder"}]}
    path = Path("matches/index.json")
    if backend == "legacy":
        (tmp_path / path).parent.mkdir()
        (tmp_path / path).write_text(json.dumps(index))
    else:
        JsonStorage(tmp_path).write_json(path, index)

    _overlap_writes(tmp_path, [(kind, "update_one"), (kind, "update_two")])

    if kind == "index":
        actual = {item["match_id"] for item in MatchRepository(tmp_path).list_match_candidates()}
        assert actual == {"match_existing", "update_one", "update_two"}
    else:
        actual = {item.observation_id for item in ObservationRepository(tmp_path).load_observations("match_existing")}
        assert actual == {"update_one", "update_two"}


def test_sqlite_match_cleanup_and_concurrent_unrelated_upsert_preserve_both_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    JsonStorage(tmp_path).write_json(Path("matches/index.json"), {
        "schema_version": 1, "matches": [{"match_id": "remove_me", "app_id": "tinder"}],
    })
    _overlap_writes(tmp_path, [("delete", "remove_me"), ("index", "keep_me")])
    assert [record["match_id"] for record in MatchRepository(tmp_path).list_match_candidates()] == ["keep_me"]
