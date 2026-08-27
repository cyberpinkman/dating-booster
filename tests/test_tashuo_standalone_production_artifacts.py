from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import pytest


pytestmark = pytest.mark.nightly_lab

from dating_boost.apps.tashuo.standalone_production_artifacts import (
    ArtifactViolation,
    build_child_environment,
    create_qualification_paths,
    import_user_model_snapshot,
    load_canonical_authorization,
    purge_sensitive_qualification_state,
    scrub_sensitive_sentinels,
    seal_canary_certificate,
    seal_qualification_bundle,
    store_encrypted_vault_payload,
    validate_production_artifact,
    verify_user_model_snapshot,
    write_immutable_artifact,
)
from dating_boost.apps.tashuo.standalone_production_contract import (
    QualificationBinding,
    SOAK_INTERVAL_NS,
    canonical_digest,
)
from dating_boost.apps.tashuo.standalone_production_ledger import ProductionQualificationLedger
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.storage import JsonStorage


@pytest.fixture(autouse=True)
def _local_test_key(monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    monkeypatch.setenv("DATING_BOOST_TEST_KEY", "production-artifact-test-key")


def _disclosure_profile():
    materials = []
    for index in range(5):
        moves = ["light_self_disclosure"]
        if index < 2:
            moves.append("low_investment_repair")
        material_type = "date_preference" if index == 4 else "life_detail"
        materials.append(
            {
                "material_id": f"mat_{index}",
                "type": material_type,
                "text": f"material {index}",
                "tags": ["date_preference"] if index == 4 else [],
                "risk_level": "low",
                "usable_moves": moves,
                "hard_fact_dependencies": [],
                "example_phrasings": [],
                "sensitivity": "low",
                "source": "user_interview",
            }
        )
    return {
        "schema_version": 1,
        "user_id": "user_local",
        "hard_facts": [],
        "persona_style": {"baseline": "direct", "allowed_modulations": ["warmer"]},
        "shareable_material": materials,
        "voice_samples": ["sample"],
        "boundaries": [],
        "simulation_policy": "free_simulation_soft",
        "source_completion": {"dating_profile": True, "interview": True},
        "updated_at": "2026-07-13T00:00:00Z",
    }


def _populate_source(source: Path) -> None:
    storage = JsonStorage(source)
    profile = {
        "schema_version": 1,
        "user_id": "user_local",
        "facts": [],
        "preferences": [],
        "boundaries": [],
        "style_examples": [],
        "goals": [],
        "persona_baseline": "direct",
        "persona_range": ["warmer"],
        "stance_range": [],
        "updated_at": "2026-07-13T00:00:00Z",
        "default_reply_mode": "adaptive",
    }
    disclosure = _disclosure_profile()
    storage.write_json(Path("user_profile.json"), profile)
    storage.write_json(Path("user/disclosure_profile.json"), disclosure)
    storage.write_json(
        Path("user/dating_profile_source.json"),
        {"schema_version": 1, "payload": {"source": "profile"}, "updated_at": "2026-07-13T00:00:00Z"},
    )
    storage.write_json(
        Path("user/self_interview_source.json"),
        {"schema_version": 1, "payload": {"source": "interview"}, "updated_at": "2026-07-13T00:00:00Z"},
    )
    storage.write_json(
        Path("user/user_memory_projection.json"),
        {
            "schema_version": 1,
            "user_id": "user_local",
            "profile": {"persona_baseline": "direct"},
            "disclosure_profile": disclosure,
            "profile_sources": [
                {"app_id": "tashuo", "runtime": "mac-ios-app", "last_observed_at": "2026-07-13T00:00:00Z"},
                {"app_id": "tinder", "runtime": "default", "last_observed_at": "2026-07-12T00:00:00Z"},
            ],
            "thread_disclosures": [{"match_id": "must_not_copy", "text": "secret"}],
            "matches": [{"match_id": "must_not_copy"}],
            "updated_at": "2026-07-13T00:00:00Z",
        },
    )
    storage.write_json(Path("matches/match_1/observations.json"), {"schema_version": 1, "observations": []})
    storage.write_json(Path("standalone/session.json"), {"schema_version": 1, "status": "active"})
    storage.append_jsonl(Path("audit/stage_results.jsonl"), {"event_id": "stage_secret", "text": "secret"})


def test_create_qualification_paths_owns_empty_isolated_tree(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    paths = create_qualification_paths(
        tmp_path / "qualification-root",
        source_data_dir=source,
        qualification_id="qual_test",
    )

    assert paths.qualification_id == "qual_test"
    assert paths.data_dir.is_dir()
    assert paths.work_dir.is_dir()
    assert paths.vault_dir.is_dir()
    assert paths.output_dir.is_dir()
    assert paths.runner_lock.is_file()
    assert paths.qualification_dir.parent == (tmp_path / "qualification-root").resolve()
    assert paths.data_dir != source.resolve()
    assert paths.ownership_digest
    assert paths.data_dir.stat().st_mode & 0o777 == 0o700
    assert paths.runner_lock.stat().st_mode & 0o777 == 0o600


def test_create_qualification_paths_rejects_source_overlap_and_existing_store(tmp_path):
    source = tmp_path / "source"
    _populate_source(source)
    with pytest.raises(ArtifactViolation, match="qualification_root_overlaps_source"):
        create_qualification_paths(source, source_data_dir=source, qualification_id="qual_test")

    root = tmp_path / "root"
    create_qualification_paths(root, source_data_dir=source, qualification_id="qual_test")
    with pytest.raises(ArtifactViolation, match="qualification_directory_exists"):
        create_qualification_paths(root, source_data_dir=source, qualification_id="qual_test")


def test_create_qualification_paths_rejects_symlink_escape(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ArtifactViolation, match="qualification_path_symlink"):
        create_qualification_paths(linked, source_data_dir=source, qualification_id="qual_test")


def test_snapshot_import_copies_only_allowlist_and_sanitizes_projection(tmp_path):
    source = tmp_path / "source"
    _populate_source(source)
    paths = create_qualification_paths(tmp_path / "root", source_data_dir=source, qualification_id="qual_test")

    result = import_user_model_snapshot(source, paths.data_dir, qualification_id="qual_test")

    assert result["status"] == "ok"
    assert result["readiness"]["ready"] is True
    assert "source" not in json.dumps(result).lower()
    projection = JsonStorage(paths.data_dir).read_json(
        Path("user/user_memory_projection.json"), expected_schema_version=1
    )
    assert projection["thread_disclosures"] == []
    assert "matches" not in projection
    assert projection["profile_sources"] == [
        {"app_id": "tashuo", "runtime": "mac-ios-app", "last_observed_at": "2026-07-13T00:00:00Z"}
    ]
    store = ProductionDataStore(paths.data_dir)
    copied_paths = {record["path"] for record in store.list_documents(prefix="")}
    assert "matches/match_1/observations.json" not in copied_paths
    assert "standalone/session.json" not in copied_paths
    assert not store.audit_stream_exists("audit/stage_results.jsonl")


def test_snapshot_digest_detects_source_drift_without_copying_new_state(tmp_path):
    source = tmp_path / "source"
    _populate_source(source)
    paths = create_qualification_paths(tmp_path / "root", source_data_dir=source, qualification_id="qual_test")
    imported = import_user_model_snapshot(source, paths.data_dir, qualification_id="qual_test")

    assert verify_user_model_snapshot(source, expected_digest=imported["snapshot_digest"])["status"] == "ok"
    profile = JsonStorage(source).read_json(Path("user_profile.json"), expected_schema_version=1)
    JsonStorage(source).write_json(Path("user_profile.json"), {**profile, "persona_baseline": "changed"})
    drift = verify_user_model_snapshot(source, expected_digest=imported["snapshot_digest"])
    assert drift == {"status": "blocked", "reason": "user_model_snapshot_drift"}


def test_snapshot_import_blocks_missing_tashuo_profile_source_and_unready_profile(tmp_path):
    source = tmp_path / "source"
    _populate_source(source)
    projection = JsonStorage(source).read_json(Path("user/user_memory_projection.json"), expected_schema_version=1)
    projection["profile_sources"] = []
    JsonStorage(source).write_json(Path("user/user_memory_projection.json"), projection)
    paths = create_qualification_paths(tmp_path / "root", source_data_dir=source, qualification_id="qual_test")

    with pytest.raises(ArtifactViolation, match="snapshot_tashuo_profile_source_missing"):
        import_user_model_snapshot(source, paths.data_dir, qualification_id="qual_test")


def test_authorization_is_canonicalized_into_encrypted_record_and_rechecked(tmp_path):
    now = "2026-07-13T00:00:00Z"
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "authorization_id": "auth_1",
                "app_id": "tashuo",
                "scope": "send_chat_messages",
                "allowed_actions": ["send_message"],
                "allowed_match_ids": [],
                "goal_ids": [],
                "autonomous_send": True,
                "autonomous_nudge": False,
                "live_send": False,
                "requires_post_action_verification": True,
                "quiet_hours": [],
                "created_at": "2026-07-01T00:00:00Z",
                "expires_at": "2099-01-01T00:00:00Z",
                "revoked_at": None,
            }
        ),
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"

    loaded = load_canonical_authorization(auth_path, data_dir=data_dir, now=now, qualification_id="qual_test")

    assert loaded["record_id"] == "authorization_auth_1"
    assert loaded["authorization_digest"]
    assert not (data_dir / "standalone_production/config/authorization_auth_1.json").exists()
    assert str(auth_path) not in json.dumps(loaded)

    payload = json.loads(auth_path.read_text(encoding="utf-8"))
    payload["revoked_at"] = "2026-07-13T00:01:00Z"
    auth_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ArtifactViolation, match="authorization_drift"):
        load_canonical_authorization(
            auth_path,
            data_dir=data_dir,
            now="2026-07-13T00:02:00Z",
            qualification_id="qual_test",
            expected_digest=loaded["authorization_digest"],
        )


def test_child_environment_routes_all_mutable_paths_under_qualification(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    paths = create_qualification_paths(tmp_path / "root", source_data_dir=source, qualification_id="qual_test")
    monkeypatch.setenv("MINIMAX_API_KEY", "secret-key")
    monkeypatch.setenv("SHOULD_NOT_PASS", "secret")

    env = build_child_environment(paths, credential_env_names=["MINIMAX_API_KEY"])

    assert env["MINIMAX_API_KEY"] == "secret-key"
    assert "SHOULD_NOT_PASS" not in env
    for name in ("TMPDIR", "PYTHONPYCACHEPREFIX", "XDG_CACHE_HOME", "DATING_BOOST_LOG_DIR"):
        assert Path(env[name]).resolve().is_relative_to(paths.qualification_dir)
    assert env["DATING_BOOST_QUALIFICATION_ID"] == "qual_test"


def test_immutable_artifact_replay_requires_identical_digest(tmp_path):
    path = tmp_path / "artifact.bin"
    first = write_immutable_artifact(path, b"first")
    replay = write_immutable_artifact(path, b"first")

    assert first["status"] == "written"
    assert replay["status"] == "replayed"
    assert replay["digest"] == first["digest"]
    with pytest.raises(ArtifactViolation, match="immutable_artifact_conflict"):
        write_immutable_artifact(path, b"different")


def _event_chain(data_dir, count, *, canary_count=10):
    ledger = ProductionQualificationLedger(data_dir)
    events = []
    for index in range(1, count + 1):
        binding = QualificationBinding(
            qualification_id="qual_test",
            phase="canary" if index <= canary_count else "soak",
            cycle_index=index if index <= canary_count else index - canary_count,
            attempt_id=f"attempt_{index}",
            local_fencing_token=1,
            runtime_fencing_token=1,
        )
        events.append(
            ledger.append_event(
                event_id=f"event_{index}",
                event_type="attempt_terminal_committed",
                binding=binding,
                reason_code=None,
                mutation_phase="attempt_terminal_committed",
                evidence_digest=f"evidence_{index}",
            )
        )
    return events


def _artifact_indexes(*, canary_count=10, soak_count=0):
    attempts = []
    cycles = []
    for global_index in range(1, canary_count + soak_count + 1):
        phase = "canary" if global_index <= canary_count else "soak"
        cycle_index = global_index if phase == "canary" else global_index - canary_count
        attempt_id = f"attempt_{global_index}"
        binding = QualificationBinding(
            qualification_id="qual_test",
            phase=phase,
            cycle_index=cycle_index,
            attempt_id=attempt_id,
            local_fencing_token=1,
            runtime_fencing_token=1,
        ).to_dict()
        outcome = {
            "schema_version": 1,
            "qualification_binding": binding,
            "attempt_id": attempt_id,
            "status": "succeeded",
            "reason_code": None,
            "mutation_phase": "attempt_terminal_committed",
            "terminal_evidence_digest": f"terminal_{attempt_id}",
        }
        receipt = {
            "schema_version": 1,
            "qualification_binding": binding,
            "attempt_id": attempt_id,
            "status": "succeeded",
            "mutation_phase": "attempt_terminal_committed",
            "worker_nonce": f"worker_{global_index}",
            "cleanup_digest": f"cleanup_{global_index}",
            "negative_send_digest": f"negative_{global_index}",
        }
        stage = {
            "qualification_binding": binding,
            "result_status": "succeeded",
            "stage_attempt_status": "completed",
            "staged_text_verified": True,
            "staged_text_verification_status": "verified",
            "target_verification_status": "ok",
            "stage_mode": True,
            "live_send_executed": False,
        }
        stage["certificate_digest"] = canonical_digest(stage)
        attempt = {
            "attempt_id": attempt_id,
            "qualification_binding": binding,
            "mutation_phase": "attempt_terminal_committed",
            "attempt_record_digest": f"record_{attempt_id}",
            "outcome": outcome,
            "outcome_digest": canonical_digest(outcome),
            "receipt": receipt,
            "receipt_digest": canonical_digest(receipt),
            "stage_result_certificates": [stage],
        }
        attempt["entry_digest"] = canonical_digest(attempt)
        attempts.append(attempt)
        mode = (
            "current-thread"
            if (phase == "canary" and cycle_index in {3, 8}) or (phase == "soak" and cycle_index % 5 == 0)
            else "message-list"
        )
        cycle = {
            "qualification_id": "qual_test",
            "phase": phase,
            "cycle_index": cycle_index,
            "planned_slot_id": f"slot_{phase}_{cycle_index}",
            "mode": mode,
            "state": "cycle_committed_success",
            "attempt_ids": [attempt_id],
            "final_attempt_id": attempt_id,
            "actual_start_ns": (cycle_index - 1) * SOAK_INTERVAL_NS if phase == "soak" else cycle_index,
            "commit_index": cycle_index,
            "predecessor": None,
        }
        cycle["cycle_digest"] = canonical_digest(cycle)
        cycles.append(cycle)
    return attempts, cycles


def _canary_metrics():
    return {
        "committed_cycles": 10,
        "successful_cycles": 10,
        "first_attempt_successes": 10,
        "retried_cycles": 0,
        "total_attempts": 10,
        "message_list_cycles": 8,
        "current_thread_cycles": 2,
        "safety_violations": 0,
        "terminal_audits": 10,
        "completed_stage_results": 10,
        "attempt_outcomes": 10,
        "receipts": 10,
        "phase_cleanup_ok": True,
        "support_bundle_ok": True,
        "hash_chain_ok": True,
        "sqlite_quick_check": "ok",
    }


def _soak_metrics():
    return {
        "committed_cycles": 100,
        "terminal_cycle_successes": 100,
        "first_attempt_successes": 100,
        "retried_cycles": 0,
        "total_attempts": 100,
        "message_list_cycles": 80,
        "current_thread_cycles": 20,
        "safety_violations": 0,
        "actual_start_ns": [index * SOAK_INTERVAL_NS for index in range(100)],
        "boot_session_unchanged": True,
        "environment_matches_canary": True,
        "phase_cleanup_ok": True,
        "support_bundles_ok": True,
        "artifacts_ok": True,
        "hash_chain_ok": True,
        "sqlite_quick_check": "ok",
    }


def test_canary_certificate_is_offline_valid_but_never_qualification_passed(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    support = output / "canary-support.zip"
    write_immutable_artifact(support, b"strict-support")
    events = _event_chain(tmp_path / "data", 10)
    attempts, cycles = _artifact_indexes()
    sealed = seal_canary_certificate(
        output_dir=output,
        qualification_id="qual_test",
        config_hash="config_hash",
        environment_fingerprint={"system": "pinned"},
        events=events,
        attempt_digest_index=attempts,
        cycle_digest_index=cycles,
        metrics=_canary_metrics(),
        support_bundle=support,
        support_session_id="support_canary",
        chain_range={"start": 1, "end": 10},
    )

    result = validate_production_artifact(Path(sealed["path"]))

    assert result["artifact_valid"] is True
    assert result["qualification_passed"] is False
    assert result["claim_code"] == "CANARY_PASSED_SOAK_NOT_RUN"
    assert "soak not run; qualification not passed" in result["claim_text"]


def test_validator_rejects_detached_digest_tampering_before_trusting_certificate(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    support = output / "canary-support.zip"
    write_immutable_artifact(support, b"strict-support")
    sealed = seal_canary_certificate(
        output_dir=output,
        qualification_id="qual_test",
        config_hash="config_hash",
        environment_fingerprint={"system": "pinned"},
        events=_event_chain(tmp_path / "data", 2),
        attempt_digest_index=[{"attempt_id": "attempt_1", "receipt_digest": "receipt_1"}],
        metrics=_canary_metrics(),
        support_bundle=support,
    )
    Path(sealed["digest_path"]).write_text("0" * 64 + "\n", encoding="ascii")

    result = validate_production_artifact(Path(sealed["path"]))

    assert result["artifact_valid"] is False
    assert result["reason"] == "artifact_detached_digest_mismatch"
    assert result["qualification_passed"] is False


def test_final_bundle_recomputes_both_phases_and_canary_chain_prefix(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    canary_support = output / "canary-support.zip"
    soak_support = output / "soak-support.zip"
    write_immutable_artifact(canary_support, b"canary support")
    write_immutable_artifact(soak_support, b"soak support")
    events = _event_chain(tmp_path / "data", 110)
    attempts, cycles = _artifact_indexes(canary_count=10, soak_count=100)
    canary = seal_canary_certificate(
        output_dir=output,
        qualification_id="qual_test",
        config_hash="config_hash",
        environment_fingerprint={"system": "pinned"},
        events=events[:10],
        attempt_digest_index=attempts[:10],
        cycle_digest_index=cycles[:10],
        metrics=_canary_metrics(),
        support_bundle=canary_support,
        support_session_id="support_canary",
        chain_range={"start": 1, "end": 10},
    )
    bundle = seal_qualification_bundle(
        output_dir=output,
        qualification_id="qual_test",
        outcome_state="soak_criteria_met",
        config_hash="config_hash",
        environment_fingerprint={"system": "pinned"},
        canary_certificate=Path(canary["path"]),
        events=events,
        receipt_digest_index=attempts,
        cycle_digest_index=cycles,
        evidence_certificates=[{"attempt_id": "attempt_1", "negative_send_digest": "negative_1"}],
        canary_metrics=_canary_metrics(),
        soak_metrics=_soak_metrics(),
        canary_support_bundle=canary_support,
        soak_support_bundle=soak_support,
        purge_result={"status": "purged", "verified": True},
        phase_bundle_metadata={
            "canary": {"support_session_id": "support_canary", "chain_range": {"start": 1, "end": 10}},
            "soak": {"support_session_id": "support_soak", "chain_range": {"start": 11, "end": 110}},
        },
    )

    result = validate_production_artifact(Path(bundle["path"]))

    assert result["artifact_valid"] is True
    assert result["qualification_passed"] is True
    assert result["claim_code"] == "PROTOCOL_PASSED_PINNED_ENVIRONMENT"
    assert result["manifest_digest"]


def test_final_bundle_missing_phase_support_or_broken_canary_prefix_is_invalid(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    support = output / "support.zip"
    write_immutable_artifact(support, b"support")
    events = _event_chain(tmp_path / "data", 4)
    canary = seal_canary_certificate(
        output_dir=output,
        qualification_id="qual_test",
        config_hash="config_hash",
        environment_fingerprint={"system": "pinned"},
        events=events[:2],
        attempt_digest_index=[{"attempt_id": "attempt_1", "receipt_digest": "receipt_1"}],
        metrics=_canary_metrics(),
        support_bundle=support,
    )
    bundle = seal_qualification_bundle(
        output_dir=output,
        qualification_id="qual_test",
        outcome_state="soak_criteria_met",
        config_hash="config_hash",
        environment_fingerprint={"system": "pinned"},
        canary_certificate=Path(canary["path"]),
        events=events[1:],
        receipt_digest_index=[{"attempt_id": "attempt_1", "receipt_digest": "receipt_1"}],
        evidence_certificates=[],
        canary_metrics=_canary_metrics(),
        soak_metrics=_soak_metrics(),
        canary_support_bundle=support,
        soak_support_bundle=None,
        purge_result={"status": "purged", "verified": True},
    )
    result = validate_production_artifact(Path(bundle["path"]))
    assert result["artifact_valid"] is False
    assert result["qualification_passed"] is False


def test_vault_payload_is_encrypted_and_sensitive_state_purge_is_verified(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    paths = create_qualification_paths(tmp_path / "root", source_data_dir=source, qualification_id="qual_test")
    sentinel = "HIGH_ENTROPY_PRIVATE_SENTINEL_7f301"
    stored = store_encrypted_vault_payload(paths, "capture-1", {"schema_version": 1, "raw_text": sentinel})
    encrypted_path = Path(stored["path"])

    assert encrypted_path.is_file()
    assert sentinel.encode("utf-8") not in encrypted_path.read_bytes()
    (paths.work_dir / "temporary.txt").write_text(sentinel, encoding="utf-8")
    result = purge_sensitive_qualification_state(paths)

    assert result == {"status": "purged", "verified": True}
    assert not paths.data_dir.exists()
    assert not paths.work_dir.exists()
    assert not paths.vault_dir.exists()
    assert paths.output_dir.exists()


def test_sensitive_sentinel_scan_deletes_plaintext_and_nested_archive_without_path_leak(tmp_path):
    source = tmp_path / "source-sentinel-scan"
    source.mkdir()
    paths = create_qualification_paths(
        tmp_path / "root-sentinel-scan",
        source_data_dir=source,
        qualification_id="qual_sentinel_scan",
    )
    sentinel = "HIGH_ENTROPY_PRIVATE_SENTINEL_8e1d44f3"
    encrypted = store_encrypted_vault_payload(
        paths,
        "encrypted-capture",
        {"schema_version": 1, "raw_text": sentinel},
    )
    plaintext = paths.work_dir / "cache" / "debug.log"
    plaintext.parent.mkdir(parents=True)
    plaintext.write_text(f"prefix {sentinel} suffix", encoding="utf-8")
    nested_buffer = io.BytesIO()
    with zipfile.ZipFile(nested_buffer, "w") as nested:
        nested.writestr("logs/debug.txt", sentinel)
    archive = paths.output_dir / "support.zip"
    with zipfile.ZipFile(archive, "w") as outer:
        outer.writestr("nested.zip", nested_buffer.getvalue())

    result = scrub_sensitive_sentinels(
        paths.qualification_dir,
        sentinels=[sentinel],
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "sensitive_sentinel_detected"
    assert len(result["matched_file_digests"]) == 2
    assert sentinel not in str(result)
    assert "debug.log" not in str(result)
    assert not plaintext.exists()
    assert not archive.exists()
    assert Path(encrypted["path"]).is_file()
