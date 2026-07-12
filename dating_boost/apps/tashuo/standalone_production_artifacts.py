from __future__ import annotations

import json
import hashlib
import io
import os
import secrets
import shutil
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from dating_boost.apps.tashuo.standalone_production_contract import (
    ContractViolation,
    MUTATION_PHASE_INDEX,
    PROTOCOL_VERSION,
    QualificationBinding,
    canonical_digest,
    derive_claim,
    canonicalize_authorization,
    validate_canary_metrics,
    validate_soak_metrics,
)
from dating_boost.apps.tashuo.standalone_production_ledger import ProductionQualificationLedger
from dating_boost.core.draft_evidence import UserMemoryRepository
from dating_boost.core.encryption import PayloadCipher
from dating_boost.core.production_store_common import PRODUCTION_DB_NAME
from dating_boost.core.storage import JsonStorage
from dating_boost.core.user_disclosure import UserDisclosureRepository, validate_disclosure_profile


OWNERSHIP_PATH = Path("standalone_production") / "ownership.json"
SNAPSHOT_METADATA_PATH = Path("standalone_production") / "config" / "user_model_snapshot.json"
MAX_SENTINEL_SCAN_ENTRY_BYTES = 8 * 1024 * 1024
MAX_SENTINEL_SCAN_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_SENTINEL_SCAN_DEPTH = 3
OUTPUT_IDENTITY_NAME = "qualification_identity.json"
FINALIZATION_CHECKPOINT_NAME = "finalization_checkpoint.json"
USER_MODEL_PATHS = (
    Path("user_profile.json"),
    Path("user") / "disclosure_profile.json",
    Path("user") / "dating_profile_source.json",
    Path("user") / "self_interview_source.json",
    Path("user") / "user_memory_projection.json",
)
REQUIRED_USER_MODEL_PATHS = frozenset(USER_MODEL_PATHS[1:])


class ArtifactViolation(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class QualificationPaths:
    qualification_id: str
    qualification_dir: Path
    data_dir: Path
    work_dir: Path
    vault_dir: Path
    output_dir: Path
    runner_lock: Path
    ownership_digest: str


def write_immutable_artifact(path: Path, content: bytes) -> dict[str, str]:
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _chmod(destination.parent, 0o700)
    digest = hashlib.sha256(content).hexdigest()
    if destination.exists():
        if _file_digest(destination) != digest:
            raise ArtifactViolation("immutable_artifact_conflict")
        return {"status": "replayed", "path": str(destination), "digest": digest}
    temp = destination.with_name(f".{destination.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, destination)
        except FileExistsError:
            if _file_digest(destination) != digest:
                raise ArtifactViolation("immutable_artifact_conflict") from None
            return {"status": "replayed", "path": str(destination), "digest": digest}
        _chmod(destination, 0o600)
        _fsync_directory(destination.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temp.exists():
            temp.unlink()
    return {"status": "written", "path": str(destination), "digest": digest}


def write_finalization_checkpoint(output_dir: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    destination = (output_dir / FINALIZATION_CHECKPOINT_NAME).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _chmod(destination.parent, 0o700)
    body = {"schema_version": 1, **dict(payload)}
    content = _json_bytes(body)
    temp = destination.with_name(f".{destination.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, destination)
        _chmod(destination, 0o600)
        _fsync_directory(destination.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temp.exists():
            temp.unlink()
    return {**body, "checkpoint_digest": hashlib.sha256(content).hexdigest()}


def read_finalization_checkpoint(output_dir: Path) -> dict[str, Any] | None:
    path = output_dir / FINALIZATION_CHECKPOINT_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactViolation("finalization_checkpoint_invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ArtifactViolation("finalization_checkpoint_invalid")
    return payload


def remove_finalization_checkpoint(output_dir: Path) -> None:
    path = output_dir / FINALIZATION_CHECKPOINT_NAME
    try:
        path.unlink()
    except FileNotFoundError:
        return
    _fsync_directory(output_dir)


def create_qualification_paths(
    root_dir: Path,
    *,
    source_data_dir: Path,
    qualification_id: str | None = None,
) -> QualificationPaths:
    source = source_data_dir.expanduser()
    if not source.exists() or not source.is_dir():
        raise ArtifactViolation("user_model_source_missing")
    _reject_symlink_components(source)
    _reject_symlink_components(root_dir.expanduser())
    source = source.resolve()
    root = root_dir.expanduser().resolve()
    if _paths_overlap(root, source):
        raise ArtifactViolation("qualification_root_overlaps_source")
    if (root / PRODUCTION_DB_NAME).exists():
        raise ArtifactViolation("qualification_root_is_data_store")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _chmod(root, 0o700)
    identifier = qualification_id or _new_qualification_id()
    if not _identifier(identifier):
        raise ArtifactViolation("qualification_id_invalid")
    qualification_dir = root / identifier
    try:
        qualification_dir.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ArtifactViolation("qualification_directory_exists") from exc
    data_dir = qualification_dir / "data"
    work_dir = qualification_dir / "work"
    vault_dir = qualification_dir / "vault"
    output_dir = qualification_dir / "output"
    for path in (data_dir, work_dir, vault_dir, output_dir):
        path.mkdir(mode=0o700)
        _chmod(path, 0o700)
    runner_lock = qualification_dir / "runner.lock"
    descriptor = os.open(runner_lock, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    _chmod(runner_lock, 0o600)
    marker = {
        "schema_version": 1,
        "record_type": "tashuo_standalone_production_qualification_ownership",
        "qualification_id": identifier,
        "app_id": "tashuo",
        "runtime": "mac-ios-app",
    }
    JsonStorage(data_dir).write_json(OWNERSHIP_PATH, marker)
    write_immutable_artifact(output_dir / OUTPUT_IDENTITY_NAME, _json_bytes(marker))
    return QualificationPaths(
        qualification_id=identifier,
        qualification_dir=qualification_dir.resolve(),
        data_dir=data_dir.resolve(),
        work_dir=work_dir.resolve(),
        vault_dir=vault_dir.resolve(),
        output_dir=output_dir.resolve(),
        runner_lock=runner_lock.resolve(),
        ownership_digest=canonical_digest(marker),
    )


def capture_user_model_snapshot(source_data_dir: Path) -> dict[str, Any]:
    source = source_data_dir.expanduser()
    if not source.exists() or not source.is_dir():
        raise ArtifactViolation("user_model_source_missing")
    _reject_symlink_components(source)
    source = source.resolve()
    storage = JsonStorage(source)
    records: dict[str, dict[str, Any]] = {}
    for path in USER_MODEL_PATHS:
        try:
            payload = storage.read_json(path, expected_schema_version=1)
        except FileNotFoundError:
            if path in REQUIRED_USER_MODEL_PATHS:
                raise ArtifactViolation("user_model_snapshot_missing") from None
            continue
        records[path.as_posix()] = payload
    projection_path = (Path("user") / "user_memory_projection.json").as_posix()
    projection = _sanitize_projection(records[projection_path])
    if not projection["profile_sources"]:
        raise ArtifactViolation("snapshot_tashuo_profile_source_missing")
    records[projection_path] = projection
    disclosure = records[(Path("user") / "disclosure_profile.json").as_posix()]
    if validate_disclosure_profile(disclosure):
        raise ArtifactViolation("user_model_snapshot_invalid")
    digest = canonical_digest({"schema_version": 1, "records": records})
    return {"records": records, "snapshot_digest": digest}


def import_user_model_snapshot(
    source_data_dir: Path,
    destination_data_dir: Path,
    *,
    qualification_id: str,
) -> dict[str, Any]:
    destination = destination_data_dir.resolve()
    storage = JsonStorage(destination)
    try:
        ownership = storage.read_json(OWNERSHIP_PATH, expected_schema_version=1)
    except FileNotFoundError as exc:
        raise ArtifactViolation("qualification_ownership_missing") from exc
    if ownership.get("qualification_id") != qualification_id:
        raise ArtifactViolation("qualification_ownership_mismatch")
    if storage.exists(SNAPSHOT_METADATA_PATH):
        raise ArtifactViolation("user_model_snapshot_already_imported")
    captured = capture_user_model_snapshot(source_data_dir)
    for relative_path, payload in captured["records"].items():
        storage.write_json(Path(relative_path), payload)
    readiness = UserDisclosureRepository(destination).readiness(mode="autonomous")
    if readiness.get("ready") is not True:
        raise ArtifactViolation("user_model_snapshot_not_autonomous_ready")
    if not UserMemoryRepository(destination).has_profile_source(app_id="tashuo", runtime="mac-ios-app"):
        raise ArtifactViolation("snapshot_tashuo_profile_source_missing")
    metadata = {
        "schema_version": 1,
        "qualification_id": qualification_id,
        "snapshot_digest": captured["snapshot_digest"],
        "record_paths": sorted(captured["records"]),
    }
    storage.write_json(SNAPSHOT_METADATA_PATH, metadata)
    return {
        "schema_version": 1,
        "status": "ok",
        "snapshot_digest": captured["snapshot_digest"],
        "record_count": len(captured["records"]),
        "readiness": readiness,
        "profile_scope": {"app_id": "tashuo", "runtime": "mac-ios-app"},
    }


def verify_user_model_snapshot(source_data_dir: Path, *, expected_digest: str) -> dict[str, str]:
    try:
        current = capture_user_model_snapshot(source_data_dir)
    except ArtifactViolation as exc:
        return {"status": "blocked", "reason": str(exc)}
    if current["snapshot_digest"] != expected_digest:
        return {"status": "blocked", "reason": "user_model_snapshot_drift"}
    return {"status": "ok", "reason": "user_model_snapshot_unchanged"}


def load_canonical_authorization(
    authorization_path: Path,
    *,
    data_dir: Path,
    now: str | datetime,
    qualification_id: str,
    expected_digest: str | None = None,
) -> dict[str, Any]:
    try:
        raw = json.loads(authorization_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactViolation("authorization_unreadable") from exc
    if not isinstance(raw, dict):
        raise ArtifactViolation("authorization_invalid")
    raw_digest = canonical_digest(raw)
    if expected_digest is not None and raw_digest != expected_digest:
        raise ArtifactViolation("authorization_drift")
    parsed_now = _parse_datetime(now)
    try:
        canonical = canonicalize_authorization(raw, now=parsed_now)
    except ContractViolation as exc:
        if expected_digest is not None:
            raise ArtifactViolation("authorization_drift") from exc
        raise ArtifactViolation(exc.reason) from exc
    if expected_digest is not None and canonical["digest"] != expected_digest:
        raise ArtifactViolation("authorization_drift")
    authorization_id = canonical["payload"]["authorization_id"]
    record_id = f"authorization_{authorization_id}"
    ledger = ProductionQualificationLedger(data_dir)
    record = {
        "schema_version": 1,
        "record_id": record_id,
        "qualification_id": qualification_id,
        "authorization_digest": canonical["digest"],
        "authorization": canonical["payload"],
    }
    try:
        ledger.insert_if_absent(f"standalone_production/config/{record_id}.json", record)
    except Exception as exc:
        if expected_digest is not None:
            raise ArtifactViolation("authorization_drift") from exc
        raise
    return {
        "schema_version": 1,
        "status": "ok",
        "record_id": record_id,
        "authorization_digest": canonical["digest"],
    }


def build_child_environment(
    paths: QualificationPaths,
    *,
    credential_env_names: Iterable[str],
    parent_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source = parent_environment if parent_environment is not None else os.environ
    environment: dict[str, str] = {}
    for name in ("PATH", "HOME", "LANG", "LC_ALL", "SHELL", "DATING_BOOST_KEY_PROVIDER"):
        value = source.get(name)
        if value:
            environment[name] = value
    for name in credential_env_names:
        if not _environment_name(name):
            raise ArtifactViolation("credential_environment_name_invalid")
        value = source.get(name)
        if value is None:
            raise ArtifactViolation("credential_environment_missing")
        environment[name] = value
    mutable_paths = {
        "TMPDIR": paths.work_dir / "tmp",
        "PYTHONPYCACHEPREFIX": paths.work_dir / "pycache",
        "XDG_CACHE_HOME": paths.work_dir / "cache",
        "DATING_BOOST_LOG_DIR": paths.work_dir / "logs",
    }
    for name, path in mutable_paths.items():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        _chmod(path, 0o700)
        if not path.resolve().is_relative_to(paths.qualification_dir):
            raise ArtifactViolation("child_environment_path_escape")
        environment[name] = str(path.resolve())
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "DATING_BOOST_QUALIFICATION_ID": paths.qualification_id,
            "DATING_BOOST_DATA_DIR": str(paths.data_dir),
            "DATING_BOOST_WORK_DIR": str(paths.work_dir),
            "DATING_BOOST_VAULT_DIR": str(paths.vault_dir),
            "DATING_BOOST_DISABLE_HTTP_BODY_LOGGING": "1",
        }
    )
    return environment


def snapshot_sentinel_candidates(data_dir: Path) -> list[str]:
    storage = JsonStorage(data_dir.resolve())
    values: set[str] = set()
    for path in USER_MODEL_PATHS:
        try:
            payload = storage.read_json(path, expected_schema_version=1)
        except FileNotFoundError:
            continue
        _collect_sensitive_strings(payload, values)
    return sorted(values)


def scrub_sensitive_sentinels(
    root: Path,
    *,
    sentinels: Iterable[str],
) -> dict[str, Any]:
    base = root.expanduser().resolve()
    tokens = sorted(
        {value.encode("utf-8") for value in sentinels if isinstance(value, str) and len(value) >= 8},
        key=len,
        reverse=True,
    )
    if not tokens or not base.exists():
        return {"schema_version": 1, "status": "ok", "matched_file_digests": []}
    matched: list[str] = []
    scan_failures: list[str] = []
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            scan_failures.append(canonical_digest({"relative_path": path.relative_to(base).as_posix()}))
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        if relative in {
            f"data/{PRODUCTION_DB_NAME}",
            f"data/{PRODUCTION_DB_NAME}-wal",
            f"data/{PRODUCTION_DB_NAME}-shm",
        }:
            continue
        location_digest = canonical_digest({"relative_path": relative})
        try:
            name_matches = any(token in relative.encode("utf-8") for token in tokens)
            content_matches = _file_contains_sentinel(path, tokens)
        except (OSError, zipfile.BadZipFile, RuntimeError):
            scan_failures.append(location_digest)
            continue
        if name_matches or content_matches:
            matched.append(location_digest)
            try:
                path.unlink()
            except OSError:
                scan_failures.append(location_digest)
    if matched or scan_failures:
        return {
            "schema_version": 1,
            "status": "blocked",
            "reason": "sensitive_sentinel_detected" if matched else "sensitive_sentinel_scan_failed",
            "matched_file_digests": sorted(set(matched)),
            "scan_failure_digests": sorted(set(scan_failures)),
        }
    return {"schema_version": 1, "status": "ok", "matched_file_digests": []}


def seal_canary_certificate(
    *,
    output_dir: Path,
    qualification_id: str,
    config_hash: str,
    environment_fingerprint: Mapping[str, Any],
    events: list[dict[str, Any]],
    attempt_digest_index: list[dict[str, Any]],
    cycle_digest_index: list[dict[str, Any]] | None = None,
    metrics: Mapping[str, Any],
    support_bundle: Path,
    support_session_id: str | None = None,
    chain_range: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    support_bytes = support_bundle.read_bytes()
    chain = _validate_exported_event_chain(events)
    predicate = validate_canary_metrics(metrics)
    body = {
        "schema_version": 1,
        "artifact_type": "tashuo_standalone_canary_certificate",
        "protocol_version": PROTOCOL_VERSION,
        "qualification_id": qualification_id,
        "config_hash": config_hash,
        "environment_fingerprint": dict(environment_fingerprint),
        "events": events,
        "canary_chain_root": chain.get("chain_root"),
        "attempt_digest_index": attempt_digest_index,
        "attempt_digest_index_digest": canonical_digest(attempt_digest_index),
        "cycle_digest_index": list(cycle_digest_index or []),
        "cycle_digest_index_digest": canonical_digest(list(cycle_digest_index or [])),
        "metrics": dict(metrics),
        "predicate_inputs_digest": canonical_digest(dict(metrics)),
        "support_bundle": {
            "entry": "support/canary-strict.zip",
            "digest": hashlib.sha256(support_bytes).hexdigest(),
            "support_session_id": support_session_id,
            "chain_range": dict(chain_range or {}),
        },
        "claim_code": "CANARY_PASSED_SOAK_NOT_RUN",
        "qualification_passed": False,
        "statistical_reliability_claim": False,
        "live_send_qualified": False,
        "chain_validation_at_seal": chain.get("valid") is True,
        "canary_predicate_at_seal": predicate.get("passed") is True,
    }
    body["certificate_content_digest"] = canonical_digest(body)
    entries = {
        "certificate.json": _json_bytes(body),
        "events.jsonl": _jsonl_bytes(events),
        "support/canary-strict.zip": support_bytes,
    }
    certificate_bytes = _zip_bytes(entries)
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = output_dir / "canary_certificate.zip"
    result = write_immutable_artifact(path, certificate_bytes)
    digest_path = path.with_suffix(path.suffix + ".sha256")
    write_immutable_artifact(digest_path, (result["digest"] + "\n").encode("ascii"))
    return {
        "status": "ok",
        "path": str(path.resolve()),
        "digest": result["digest"],
        "digest_path": str(digest_path.resolve()),
        "canary_chain_root": body["canary_chain_root"],
        "certificate_content_digest": body["certificate_content_digest"],
    }


def seal_qualification_evidence(
    *,
    output_dir: Path,
    qualification_id: str,
    outcome_state: str,
    config_hash: str,
    environment_fingerprint: Mapping[str, Any],
    canary_certificate: Path | None,
    events: list[dict[str, Any]],
    receipt_digest_index: list[dict[str, Any]],
    cycle_digest_index: list[dict[str, Any]] | None = None,
    evidence_certificates: list[dict[str, Any]],
    canary_metrics: Mapping[str, Any],
    soak_metrics: Mapping[str, Any] | None,
    canary_support_bundle: Path | None,
    soak_support_bundle: Path | None,
    phase_bundle_metadata: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    canary_bytes = canary_certificate.read_bytes() if canary_certificate and canary_certificate.is_file() else None
    canary_support_bytes = (
        canary_support_bundle.read_bytes() if canary_support_bundle and canary_support_bundle.is_file() else None
    )
    soak_support_bytes = soak_support_bundle.read_bytes() if soak_support_bundle and soak_support_bundle.is_file() else None
    metadata = phase_bundle_metadata or {}
    phase_index = {
        "canary": _phase_bundle_entry(
            "support/canary-strict.zip",
            canary_support_bytes,
            metadata=metadata.get("canary"),
        ),
        "soak": _phase_bundle_entry(
            "support/soak-strict.zip",
            soak_support_bytes,
            metadata=metadata.get("soak"),
        ),
    }
    evidence_index = {
        "schema_version": 1,
        "artifact_type": "tashuo_standalone_qualification_evidence",
        "protocol_version": PROTOCOL_VERSION,
        "qualification_id": qualification_id,
        "outcome_state": outcome_state,
        "config_hash": config_hash,
        "environment_fingerprint": dict(environment_fingerprint),
        "events": events,
        "event_chain": _validate_exported_event_chain(events),
        "receipt_digest_index": receipt_digest_index,
        "receipt_digest_index_digest": canonical_digest(receipt_digest_index),
        "cycle_digest_index": list(cycle_digest_index or []),
        "cycle_digest_index_digest": canonical_digest(list(cycle_digest_index or [])),
        "evidence_certificates": evidence_certificates,
        "evidence_certificates_digest": canonical_digest(evidence_certificates),
        "canary_metrics": dict(canary_metrics),
        "soak_metrics": dict(soak_metrics) if soak_metrics is not None else None,
        "phase_bundle_index": phase_index,
        "canary_certificate": (
            {"entry": "canary/canary_certificate.zip", "digest": hashlib.sha256(canary_bytes).hexdigest()}
            if canary_bytes is not None
            else {"status": "absent", "reason": "canary_not_passed"}
        ),
        "statistical_reliability_claim": False,
        "live_send_qualified": False,
    }
    evidence_entries: dict[str, bytes] = {
        "evidence_index.json": _json_bytes(evidence_index),
        "events.jsonl": _jsonl_bytes(events),
    }
    if canary_bytes is not None:
        evidence_entries["canary/canary_certificate.zip"] = canary_bytes
    if canary_support_bytes is not None:
        evidence_entries["support/canary-strict.zip"] = canary_support_bytes
    if soak_support_bytes is not None:
        evidence_entries["support/soak-strict.zip"] = soak_support_bytes
    evidence_content_root = canonical_digest(
        {name: hashlib.sha256(content).hexdigest() for name, content in sorted(evidence_entries.items())}
    )
    evidence_index["content_root"] = evidence_content_root
    evidence_entries["evidence_index.json"] = _json_bytes(evidence_index)
    evidence_bytes = _zip_bytes(evidence_entries)
    evidence_path = output_dir / "qualification_evidence.zip"
    evidence_result = write_immutable_artifact(evidence_path, evidence_bytes)
    digest_path = evidence_path.with_suffix(evidence_path.suffix + ".sha256")
    write_immutable_artifact(digest_path, (evidence_result["digest"] + "\n").encode("ascii"))
    validation = validate_qualification_evidence(evidence_path)
    return {
        "status": "ok" if validation.get("artifact_valid") is True else "sealed_invalid",
        "path": str(evidence_path.resolve()),
        "digest": evidence_result["digest"],
        "digest_path": str(digest_path.resolve()),
        "content_root": evidence_content_root,
        "validation": validation,
    }


def seal_qualification_bundle_from_evidence(
    *,
    output_dir: Path,
    qualification_evidence: Path,
    purge_result: Mapping[str, Any],
) -> dict[str, Any]:
    provisional = validate_qualification_evidence(qualification_evidence)
    if provisional.get("artifact_valid") is not True:
        raise ArtifactViolation("qualification_evidence_invalid")
    evidence_bytes = qualification_evidence.read_bytes()
    evidence_entries = _read_zip_entries(evidence_bytes)
    evidence_index = json.loads(evidence_entries["evidence_index.json"])
    if not isinstance(evidence_index, dict):
        raise ArtifactViolation("qualification_evidence_schema_invalid")
    qualification_id = str(evidence_index.get("qualification_id") or "")
    outcome_state = str(evidence_index.get("outcome_state") or "")
    config_hash = str(evidence_index.get("config_hash") or "")
    environment_fingerprint = evidence_index.get("environment_fingerprint")
    if not qualification_id or not config_hash or not isinstance(environment_fingerprint, dict):
        raise ArtifactViolation("qualification_evidence_schema_invalid")
    terminal_state = {
        "soak_criteria_met": "protocol_passed",
        "qualification_blocked": "blocked_finalized",
        "qualification_expired": "expired_finalized",
    }.get(outcome_state, "finalization_failed")
    claim_code = {
        "protocol_passed": "PROTOCOL_PASSED_PINNED_ENVIRONMENT",
        "blocked_finalized": "QUALIFICATION_BLOCKED",
        "expired_finalized": "QUALIFICATION_EXPIRED",
    }.get(terminal_state, "QUALIFICATION_BLOCKED")
    manifest = {
        "schema_version": 1,
        "artifact_type": "tashuo_standalone_terminal_manifest",
        "qualification_id": qualification_id,
        "outcome_state": outcome_state,
        "terminal_state": terminal_state,
        "claim_code": claim_code,
        "config_hash": config_hash,
        "environment_fingerprint": dict(environment_fingerprint),
        "canary_metrics": dict(evidence_index.get("canary_metrics") or {}),
        "soak_metrics": (
            dict(evidence_index["soak_metrics"])
            if isinstance(evidence_index.get("soak_metrics"), dict)
            else None
        ),
        "event_chain_root": evidence_index["event_chain"].get("chain_root"),
        "receipt_index_digest": evidence_index["receipt_digest_index_digest"],
        "phase_bundle_index": evidence_index["phase_bundle_index"],
        "qualification_evidence_digest": hashlib.sha256(evidence_bytes).hexdigest(),
        "qualification_evidence_content_root": evidence_index["content_root"],
        "purge_result": dict(purge_result),
        "finalization_state": "validated",
        "statistical_reliability_claim": False,
        "live_send_qualified": False,
    }
    manifest["manifest_content_digest"] = canonical_digest(manifest)
    bundle_entries = {
        "terminal_manifest.json": _json_bytes(manifest),
        "qualification_evidence.zip": evidence_bytes,
    }
    bundle_bytes = _zip_bytes(bundle_entries)
    bundle_path = output_dir / "qualification_bundle.zip"
    bundle_result = write_immutable_artifact(bundle_path, bundle_bytes)
    digest_path = bundle_path.with_suffix(bundle_path.suffix + ".sha256")
    write_immutable_artifact(digest_path, (bundle_result["digest"] + "\n").encode("ascii"))
    validation = validate_production_artifact(bundle_path)
    return {
        "status": "ok" if validation.get("artifact_valid") is True else "sealed_invalid",
        "path": str(bundle_path.resolve()),
        "digest": bundle_result["digest"],
        "digest_path": str(digest_path.resolve()),
        "evidence_path": str(qualification_evidence.resolve()),
        "evidence_digest": hashlib.sha256(evidence_bytes).hexdigest(),
        "manifest_digest": manifest["manifest_content_digest"],
        "manifest": manifest,
        "validation": validation,
    }


def publish_terminal_manifest(*, qualification_bundle: Path, output_dir: Path) -> dict[str, Any]:
    validation = validate_production_artifact(qualification_bundle)
    if validation.get("artifact_valid") is not True:
        raise ArtifactViolation("qualification_bundle_invalid")
    entries = _read_zip_entries(qualification_bundle.read_bytes())
    manifest_bytes = entries.get("terminal_manifest.json")
    if manifest_bytes is None:
        raise ArtifactViolation("terminal_manifest_missing")
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ArtifactViolation("terminal_manifest_schema_invalid")
    if manifest.get("finalization_state") != "validated":
        raise ArtifactViolation("terminal_manifest_not_publishable_exactly")
    result = write_immutable_artifact(output_dir / "terminal_manifest.json", manifest_bytes)
    return {
        "status": "published",
        "path": result["path"],
        "digest": result["digest"],
        "manifest_digest": manifest["manifest_content_digest"],
        "terminal_state": manifest["terminal_state"],
    }


def seal_qualification_bundle(
    *,
    output_dir: Path,
    qualification_id: str,
    outcome_state: str,
    config_hash: str,
    environment_fingerprint: Mapping[str, Any],
    canary_certificate: Path | None,
    events: list[dict[str, Any]],
    receipt_digest_index: list[dict[str, Any]],
    cycle_digest_index: list[dict[str, Any]] | None = None,
    evidence_certificates: list[dict[str, Any]],
    canary_metrics: Mapping[str, Any],
    soak_metrics: Mapping[str, Any] | None,
    canary_support_bundle: Path | None,
    soak_support_bundle: Path | None,
    purge_result: Mapping[str, Any],
    phase_bundle_metadata: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    evidence = seal_qualification_evidence(
        output_dir=output_dir,
        qualification_id=qualification_id,
        outcome_state=outcome_state,
        config_hash=config_hash,
        environment_fingerprint=environment_fingerprint,
        canary_certificate=canary_certificate,
        events=events,
        receipt_digest_index=receipt_digest_index,
        cycle_digest_index=cycle_digest_index,
        evidence_certificates=evidence_certificates,
        canary_metrics=canary_metrics,
        soak_metrics=soak_metrics,
        canary_support_bundle=canary_support_bundle,
        soak_support_bundle=soak_support_bundle,
        phase_bundle_metadata=phase_bundle_metadata,
    )
    if evidence["validation"].get("artifact_valid") is not True:
        return {
            "status": "sealed_invalid",
            "path": evidence["path"],
            "digest": evidence["digest"],
            "evidence_path": evidence["path"],
            "evidence_digest": evidence["digest"],
            "validation": evidence["validation"],
        }
    bundle = seal_qualification_bundle_from_evidence(
        output_dir=output_dir,
        qualification_evidence=Path(evidence["path"]),
        purge_result=purge_result,
    )
    if bundle["validation"].get("artifact_valid") is True:
        publish_terminal_manifest(qualification_bundle=Path(bundle["path"]), output_dir=output_dir)
    return bundle


def validate_qualification_evidence(path: Path) -> dict[str, Any]:
    artifact = path.resolve()
    try:
        content = artifact.read_bytes()
        expected_digest = artifact.with_suffix(artifact.suffix + ".sha256").read_text(encoding="ascii").strip()
    except OSError:
        return _artifact_invalid("qualification_evidence_unreadable")
    actual_digest = hashlib.sha256(content).hexdigest()
    if expected_digest != actual_digest:
        return _artifact_invalid("artifact_detached_digest_mismatch")
    try:
        evidence_entries = _read_zip_entries(content)
        evidence = json.loads(evidence_entries["evidence_index.json"])
        if not isinstance(evidence, dict):
            return _artifact_invalid("qualification_evidence_schema_invalid")
        outcome_state = str(evidence.get("outcome_state") or "")
        terminal_state = {
            "soak_criteria_met": "protocol_passed",
            "qualification_blocked": "blocked_finalized",
            "qualification_expired": "expired_finalized",
        }.get(outcome_state, "finalization_failed")
        claim_code = {
            "protocol_passed": "PROTOCOL_PASSED_PINNED_ENVIRONMENT",
            "blocked_finalized": "QUALIFICATION_BLOCKED",
            "expired_finalized": "QUALIFICATION_EXPIRED",
        }.get(terminal_state, "QUALIFICATION_BLOCKED")
        manifest = {
            "schema_version": 1,
            "artifact_type": "tashuo_standalone_terminal_manifest",
            "qualification_id": evidence.get("qualification_id"),
            "outcome_state": outcome_state,
            "terminal_state": terminal_state,
            "claim_code": claim_code,
            "config_hash": evidence.get("config_hash"),
            "environment_fingerprint": evidence.get("environment_fingerprint"),
            "canary_metrics": evidence.get("canary_metrics"),
            "soak_metrics": evidence.get("soak_metrics"),
            "event_chain_root": (evidence.get("event_chain") or {}).get("chain_root"),
            "receipt_index_digest": evidence.get("receipt_digest_index_digest"),
            "phase_bundle_index": evidence.get("phase_bundle_index"),
            "qualification_evidence_digest": actual_digest,
            "qualification_evidence_content_root": evidence.get("content_root"),
            "purge_result": {"status": "purged", "verified": True},
            "finalization_state": "validated",
            "statistical_reliability_claim": False,
            "live_send_qualified": False,
        }
        manifest["manifest_content_digest"] = canonical_digest(manifest)
        validated = _validate_qualification_entries(
            {
                "terminal_manifest.json": _json_bytes(manifest),
                "qualification_evidence.zip": content,
            },
            artifact_digest=actual_digest,
        )
    except (ArtifactViolation, KeyError, ValueError, json.JSONDecodeError):
        return _artifact_invalid("qualification_evidence_content_invalid")
    if validated.get("artifact_valid") is not True:
        return validated
    return {
        **validated,
        "qualification_passed": False,
        "provisional_outcome_eligible": validated.get("qualification_passed") is True,
        "artifact_type": "tashuo_standalone_qualification_evidence",
    }


def validate_production_artifact(path: Path) -> dict[str, Any]:
    artifact = path.resolve()
    try:
        content = artifact.read_bytes()
    except OSError:
        return _artifact_invalid("artifact_unreadable")
    detached = artifact.with_suffix(artifact.suffix + ".sha256")
    try:
        expected_digest = detached.read_text(encoding="ascii").strip()
    except OSError:
        return _artifact_invalid("artifact_detached_digest_missing")
    actual_digest = hashlib.sha256(content).hexdigest()
    if expected_digest != actual_digest:
        return _artifact_invalid("artifact_detached_digest_mismatch")
    try:
        entries = _read_zip_entries(content)
        if "certificate.json" in entries:
            return _validate_canary_entries(entries, artifact_digest=actual_digest)
        if "terminal_manifest.json" in entries and "qualification_evidence.zip" in entries:
            return _validate_qualification_entries(entries, artifact_digest=actual_digest)
    except (ArtifactViolation, ValueError, KeyError, json.JSONDecodeError):
        return _artifact_invalid("artifact_content_invalid")
    return _artifact_invalid("artifact_type_unsupported")


def store_encrypted_vault_payload(
    paths: QualificationPaths,
    name: str,
    payload: Mapping[str, Any],
) -> dict[str, str]:
    if not _identifier(name):
        raise ArtifactViolation("vault_evidence_name_invalid")
    encrypted = PayloadCipher(paths.data_dir).encrypt_json(
        dict(payload),
        associated_data=f"qualification-vault:{paths.qualification_id}:{name}",
    )
    destination = paths.vault_dir / f"{name}.enc"
    result = write_immutable_artifact(destination, (encrypted + "\n").encode("utf-8"))
    return {"status": result["status"], "path": result["path"], "digest": result["digest"]}


def purge_sensitive_qualification_state(paths: QualificationPaths) -> dict[str, Any]:
    for path in (paths.data_dir, paths.work_dir, paths.vault_dir):
        if path.exists():
            shutil.rmtree(path)
    _fsync_directory(paths.qualification_dir)
    verified = all(not path.exists() for path in (paths.data_dir, paths.work_dir, paths.vault_dir))
    if not verified:
        raise ArtifactViolation("sensitive_purge_verification_failed")
    return {"status": "purged", "verified": True}


def _collect_sensitive_strings(value: Any, result: set[str]) -> None:
    if isinstance(value, str):
        normalized = value.strip()
        structural_values = {
            "mac-ios-app",
            "tashuo",
            "user_local",
            "unknown",
            "not_provided",
        }
        if (
            len(normalized) >= 8
            and normalized not in structural_values
            and not _looks_like_iso_timestamp(normalized)
        ):
            result.add(normalized)
        return
    if isinstance(value, Mapping):
        for child in value.values():
            _collect_sensitive_strings(child, result)
        return
    if isinstance(value, list):
        for child in value:
            _collect_sensitive_strings(child, result)


def _looks_like_iso_timestamp(value: str) -> bool:
    if "T" not in value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _file_contains_sentinel(path: Path, tokens: list[bytes]) -> bool:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return _archive_contains_sentinel(archive, tokens=tokens, depth=1)
    overlap = max(len(token) for token in tokens) - 1
    previous = b""
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            combined = previous + chunk
            if any(token in combined for token in tokens):
                return True
            previous = combined[-overlap:] if overlap > 0 else b""
    return False


def _archive_contains_sentinel(
    archive: zipfile.ZipFile,
    *,
    tokens: list[bytes],
    depth: int,
) -> bool:
    total = 0
    for info in archive.infolist():
        encoded_name = info.filename.encode("utf-8", errors="replace")
        if any(token in encoded_name for token in tokens):
            return True
        if info.is_dir():
            continue
        if info.file_size > MAX_SENTINEL_SCAN_ENTRY_BYTES:
            raise RuntimeError("sensitive_sentinel_archive_entry_limit")
        total += info.file_size
        if total > MAX_SENTINEL_SCAN_ARCHIVE_BYTES:
            raise RuntimeError("sensitive_sentinel_archive_limit")
        content = archive.read(info)
        if any(token in content for token in tokens):
            return True
        if depth < MAX_SENTINEL_SCAN_DEPTH and content.startswith(b"PK\x03\x04"):
            with zipfile.ZipFile(io.BytesIO(content)) as nested:
                if _archive_contains_sentinel(nested, tokens=tokens, depth=depth + 1):
                    return True
    return False


def _sanitize_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for item in payload.get("profile_sources", []):
        if not isinstance(item, Mapping) or item.get("app_id") != "tashuo" or item.get("runtime") != "mac-ios-app":
            continue
        source = {"app_id": "tashuo", "runtime": "mac-ios-app"}
        for key in ("first_observed_at", "last_observed_at"):
            if isinstance(item.get(key), str):
                source[key] = item[key]
        sources.append(source)
    result = {
        "schema_version": 1,
        "user_id": str(payload.get("user_id") or "user_local"),
        "profile": dict(payload.get("profile") or {}),
        "profile_sources": sources,
        "thread_disclosures": [],
        "updated_at": str(payload.get("updated_at") or ""),
    }
    if isinstance(payload.get("disclosure_profile"), Mapping):
        result["disclosure_profile"] = dict(payload["disclosure_profile"])
    return result


def _reject_symlink_components(path: Path) -> None:
    expanded = path.expanduser()
    current = Path(expanded.anchor) if expanded.is_absolute() else Path.cwd()
    parts = expanded.parts[1:] if expanded.is_absolute() else expanded.parts
    for part in parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ArtifactViolation("qualification_path_symlink")


def _paths_overlap(one: Path, two: Path) -> bool:
    return one == two or one.is_relative_to(two) or two.is_relative_to(one)


def _new_qualification_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"qual_{timestamp}_{secrets.token_hex(6)}"


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "/" not in value and "\\" not in value and "\0" not in value


def _environment_name(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value.replace("_", "A").isalnum() and value.upper() == value


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ArtifactViolation("timestamp_invalid")
    if parsed.tzinfo is None:
        raise ArtifactViolation("timestamp_invalid")
    return parsed.astimezone(UTC)


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _validate_attempt_cycle_indexes(
    attempt_index: Any,
    cycle_index: Any,
    *,
    phase: str | None = None,
    require_complete: bool,
) -> dict[str, Any]:
    if not isinstance(attempt_index, list) or not isinstance(cycle_index, list):
        return {"valid": False, "reason": "qualification_attempt_or_cycle_index_missing"}
    attempts: dict[str, dict[str, Any]] = {}
    for entry in attempt_index:
        if not isinstance(entry, dict):
            return {"valid": False, "reason": "qualification_attempt_index_invalid"}
        stored_entry_digest = entry.get("entry_digest")
        entry_body = {key: value for key, value in entry.items() if key != "entry_digest"}
        if stored_entry_digest != canonical_digest(entry_body):
            return {"valid": False, "reason": "qualification_attempt_index_digest_mismatch"}
        attempt_id = str(entry.get("attempt_id") or "")
        if not attempt_id or attempt_id in attempts:
            return {"valid": False, "reason": "qualification_attempt_duplicate"}
        try:
            binding = QualificationBinding.from_dict(entry.get("qualification_binding") or {})
        except ValueError:
            return {"valid": False, "reason": "qualification_attempt_binding_invalid"}
        if binding.attempt_id != attempt_id or (phase is not None and binding.phase != phase):
            return {"valid": False, "reason": "qualification_attempt_binding_invalid"}
        outcome = entry.get("outcome")
        receipt = entry.get("receipt")
        if require_complete and (not isinstance(outcome, dict) or not isinstance(receipt, dict)):
            return {"valid": False, "reason": "qualification_attempt_terminal_missing"}
        for record, digest_key in ((outcome, "outcome_digest"), (receipt, "receipt_digest")):
            if record is None:
                if entry.get(digest_key) is not None:
                    return {"valid": False, "reason": "qualification_attempt_terminal_digest_invalid"}
                continue
            if not isinstance(record, dict) or entry.get(digest_key) != canonical_digest(record):
                return {"valid": False, "reason": "qualification_attempt_terminal_digest_invalid"}
            try:
                record_binding = QualificationBinding.from_dict(record.get("qualification_binding") or {})
            except ValueError:
                return {"valid": False, "reason": "qualification_attempt_binding_invalid"}
            if record_binding != binding:
                return {"valid": False, "reason": "qualification_attempt_binding_invalid"}
        if isinstance(outcome, dict) and isinstance(receipt, dict):
            if outcome.get("status") not in {"succeeded", "failed"} or receipt.get("status") != outcome.get("status"):
                return {"valid": False, "reason": "qualification_attempt_terminal_status_mismatch"}
        mutation_phase = (
            outcome.get("mutation_phase")
            if isinstance(outcome, dict)
            else entry.get("mutation_phase")
        )
        if mutation_phase not in MUTATION_PHASE_INDEX:
            return {"valid": False, "reason": "qualification_attempt_mutation_phase_invalid"}
        stages = entry.get("stage_result_certificates")
        if not isinstance(stages, list):
            return {"valid": False, "reason": "qualification_stage_index_invalid"}
        expected_stage_count = (
            1
            if MUTATION_PHASE_INDEX[mutation_phase] >= MUTATION_PHASE_INDEX["stage_mutation_intent"]
            else 0
        )
        if len(stages) != expected_stage_count:
            return {"valid": False, "reason": "qualification_stage_cardinality_invalid"}
        for stage in stages:
            if not isinstance(stage, dict):
                return {"valid": False, "reason": "qualification_stage_index_invalid"}
            digest = stage.get("certificate_digest")
            body = {key: value for key, value in stage.items() if key != "certificate_digest"}
            if digest != canonical_digest(body):
                return {"valid": False, "reason": "qualification_stage_certificate_digest_invalid"}
            try:
                stage_binding = QualificationBinding.from_dict(stage.get("qualification_binding") or {})
            except ValueError:
                return {"valid": False, "reason": "qualification_stage_binding_invalid"}
            if stage_binding != binding or stage.get("live_send_executed") is not False:
                return {"valid": False, "reason": "qualification_stage_binding_invalid"}
        if expected_stage_count == 1 and isinstance(outcome, dict) and isinstance(receipt, dict):
            stage = stages[0]
            expected_stage_status = "succeeded" if outcome.get("status") == "succeeded" else "failed"
            if stage.get("result_status") != expected_stage_status:
                return {"valid": False, "reason": "qualification_stage_outcome_mismatch"}
            if stage.get("stage_mode") is not True or stage.get("target_verification_status") != "ok":
                return {"valid": False, "reason": "qualification_stage_evidence_invalid"}
            if expected_stage_status == "succeeded" and (
                stage.get("stage_attempt_status") != "completed"
                or stage.get("staged_text_verified") is not True
                or stage.get("staged_text_verification_status") != "verified"
            ):
                return {"valid": False, "reason": "qualification_stage_evidence_invalid"}
            if expected_stage_status == "failed" and stage.get("stage_attempt_status") != "failed":
                return {"valid": False, "reason": "qualification_stage_evidence_invalid"}
            if not isinstance(receipt.get("cleanup_digest"), str) or not isinstance(
                receipt.get("negative_send_digest"), str
            ):
                return {"valid": False, "reason": "qualification_safe_cleanup_evidence_missing"}
        attempts[attempt_id] = entry
    cycles: dict[tuple[str, int], dict[str, Any]] = {}
    attempt_membership: list[str] = []
    commit_indexes: dict[str, list[int]] = {}
    for cycle in cycle_index:
        if not isinstance(cycle, dict):
            return {"valid": False, "reason": "qualification_cycle_index_invalid"}
        digest = cycle.get("cycle_digest")
        body = {key: value for key, value in cycle.items() if key != "cycle_digest"}
        if digest != canonical_digest(body):
            return {"valid": False, "reason": "qualification_cycle_digest_mismatch"}
        cycle_phase = str(cycle.get("phase") or "")
        cycle_number = cycle.get("cycle_index")
        if cycle_phase not in {"canary", "soak"} or not isinstance(cycle_number, int):
            return {"valid": False, "reason": "qualification_cycle_binding_invalid"}
        if phase is not None and cycle_phase != phase:
            return {"valid": False, "reason": "qualification_cycle_binding_invalid"}
        key = (cycle_phase, cycle_number)
        if key in cycles:
            return {"valid": False, "reason": "qualification_cycle_duplicate"}
        cycles[key] = cycle
        attempt_ids = [str(item) for item in cycle.get("attempt_ids") or []]
        if len(attempt_ids) != len(set(attempt_ids)):
            return {"valid": False, "reason": "qualification_cycle_attempt_duplicate"}
        attempt_membership.extend(attempt_ids)
        state = cycle.get("state")
        if require_complete and state not in {"cycle_committed_success", "cycle_committed_failure"}:
            return {"valid": False, "reason": "qualification_cycle_not_committed"}
        if state in {"cycle_committed_success", "cycle_committed_failure"}:
            if cycle.get("final_attempt_id") not in attempt_ids:
                return {"valid": False, "reason": "qualification_cycle_final_attempt_invalid"}
            final_entry = attempts.get(str(cycle.get("final_attempt_id") or ""))
            final_outcome = final_entry.get("outcome") if isinstance(final_entry, dict) else None
            expected_status = "succeeded" if state == "cycle_committed_success" else "failed"
            if not isinstance(final_outcome, dict) or final_outcome.get("status") != expected_status:
                return {"valid": False, "reason": "qualification_cycle_outcome_mismatch"}
            commit_index = cycle.get("commit_index")
            if not isinstance(commit_index, int) or commit_index < 1:
                return {"valid": False, "reason": "qualification_cycle_commit_index_invalid"}
            commit_indexes.setdefault(cycle_phase, []).append(commit_index)
    if sorted(attempt_membership) != sorted(attempts):
        return {"valid": False, "reason": "qualification_attempt_orphan_or_missing"}
    for indexes in commit_indexes.values():
        if sorted(indexes) != list(range(1, len(indexes) + 1)):
            return {"valid": False, "reason": "qualification_cycle_commit_order_invalid"}
    return {
        "valid": True,
        "reason": None,
        "attempt_count": len(attempts),
        "cycle_count": len(cycles),
        "cycles": list(cycles.values()),
    }


def _validate_canary_entries(entries: Mapping[str, bytes], *, artifact_digest: str) -> dict[str, Any]:
    required = {"certificate.json", "events.jsonl", "support/canary-strict.zip"}
    if not required.issubset(entries):
        return _artifact_invalid("canary_certificate_entry_missing")
    certificate = json.loads(entries["certificate.json"])
    if not isinstance(certificate, dict) or certificate.get("artifact_type") != "tashuo_standalone_canary_certificate":
        return _artifact_invalid("canary_certificate_schema_invalid")
    stored_content_digest = certificate.get("certificate_content_digest")
    body = {key: value for key, value in certificate.items() if key != "certificate_content_digest"}
    if stored_content_digest != canonical_digest(body):
        return _artifact_invalid("canary_certificate_content_digest_mismatch")
    events = _parse_jsonl(entries["events.jsonl"])
    if events != certificate.get("events"):
        return _artifact_invalid("canary_event_sequence_mismatch")
    chain = _validate_exported_event_chain(events)
    if chain.get("valid") is not True or chain.get("chain_root") != certificate.get("canary_chain_root"):
        return _artifact_invalid("canary_event_chain_invalid")
    support = certificate.get("support_bundle") if isinstance(certificate.get("support_bundle"), dict) else {}
    if support.get("digest") != hashlib.sha256(entries["support/canary-strict.zip"]).hexdigest():
        return _artifact_invalid("canary_support_bundle_digest_mismatch")
    chain_range = support.get("chain_range")
    if (
        not isinstance(support.get("support_session_id"), str)
        or not isinstance(chain_range, dict)
        or not isinstance(chain_range.get("start"), int)
        or not isinstance(chain_range.get("end"), int)
        or chain_range["start"] < 1
        or chain_range["end"] != len(events)
    ):
        return _artifact_invalid("canary_support_bundle_binding_invalid")
    attempt_index = certificate.get("attempt_digest_index")
    if not isinstance(attempt_index, list) or not attempt_index:
        return _artifact_invalid("canary_attempt_index_missing")
    if certificate.get("attempt_digest_index_digest") != canonical_digest(attempt_index):
        return _artifact_invalid("canary_attempt_index_digest_mismatch")
    cycle_index = certificate.get("cycle_digest_index")
    if certificate.get("cycle_digest_index_digest") != canonical_digest(cycle_index):
        return _artifact_invalid("canary_cycle_index_digest_mismatch")
    graph = _validate_attempt_cycle_indexes(
        attempt_index,
        cycle_index,
        phase="canary",
        require_complete=True,
    )
    if graph.get("valid") is not True:
        return _artifact_invalid(str(graph.get("reason") or "canary_attempt_graph_invalid"))
    metrics = certificate.get("metrics")
    if not isinstance(metrics, dict) or validate_canary_metrics(metrics).get("passed") is not True:
        return _artifact_invalid("canary_predicate_failed")
    cycles = graph["cycles"]
    if (
        graph.get("cycle_count") != metrics.get("committed_cycles")
        or graph.get("attempt_count") != metrics.get("total_attempts")
        or sum(1 for cycle in cycles if cycle.get("mode") == "message-list") != metrics.get("message_list_cycles")
        or sum(1 for cycle in cycles if cycle.get("mode") == "current-thread") != metrics.get("current_thread_cycles")
    ):
        return _artifact_invalid("canary_index_metric_mismatch")
    if certificate.get("qualification_passed") is not False or certificate.get("claim_code") != "CANARY_PASSED_SOAK_NOT_RUN":
        return _artifact_invalid("canary_claim_invalid")
    claim = derive_claim(
        "canary_passed",
        qualification_id=str(certificate.get("qualification_id") or ""),
        config_hash=str(certificate.get("config_hash") or ""),
        manifest_digest=str(stored_content_digest or ""),
    )
    return {
        "schema_version": 1,
        "artifact_valid": True,
        "qualification_passed": False,
        "claim_code": claim["claim_code"],
        "claim_text": claim["text"],
        "artifact_digest": artifact_digest,
        "manifest_digest": stored_content_digest,
        "qualification_id": certificate.get("qualification_id"),
        "config_hash": certificate.get("config_hash"),
        "chain_root": chain.get("chain_root"),
    }


def _validate_qualification_entries(entries: Mapping[str, bytes], *, artifact_digest: str) -> dict[str, Any]:
    manifest = json.loads(entries["terminal_manifest.json"])
    if not isinstance(manifest, dict) or manifest.get("artifact_type") != "tashuo_standalone_terminal_manifest":
        return _artifact_invalid("terminal_manifest_schema_invalid")
    stored_manifest_digest = manifest.get("manifest_content_digest")
    manifest_body = {key: value for key, value in manifest.items() if key != "manifest_content_digest"}
    if stored_manifest_digest != canonical_digest(manifest_body):
        return _artifact_invalid("terminal_manifest_digest_mismatch")
    evidence_bytes = entries["qualification_evidence.zip"]
    if manifest.get("qualification_evidence_digest") != hashlib.sha256(evidence_bytes).hexdigest():
        return _artifact_invalid("qualification_evidence_digest_mismatch")
    evidence_entries = _read_zip_entries(evidence_bytes)
    required = {"evidence_index.json", "events.jsonl"}
    if not required.issubset(evidence_entries):
        return _artifact_invalid("qualification_evidence_entry_missing")
    evidence = json.loads(evidence_entries["evidence_index.json"])
    if (
        not isinstance(evidence, dict)
        or evidence.get("artifact_type") != "tashuo_standalone_qualification_evidence"
        or evidence.get("qualification_id") != manifest.get("qualification_id")
        or evidence.get("outcome_state") != manifest.get("outcome_state")
        or evidence.get("config_hash") != manifest.get("config_hash")
        or evidence.get("environment_fingerprint") != manifest.get("environment_fingerprint")
    ):
        return _artifact_invalid("qualification_evidence_schema_invalid")
    root_entries = {
        name: content
        for name, content in evidence_entries.items()
        if name != "evidence_index.json"
    }
    evidence_without_root = dict(evidence)
    stored_root = evidence_without_root.pop("content_root", None)
    root_entries["evidence_index.json"] = _json_bytes(evidence_without_root)
    computed_root = canonical_digest(
        {name: hashlib.sha256(content).hexdigest() for name, content in sorted(root_entries.items())}
    )
    if stored_root != computed_root or manifest.get("qualification_evidence_content_root") != stored_root:
        return _artifact_invalid("qualification_evidence_content_root_mismatch")
    events = _parse_jsonl(evidence_entries["events.jsonl"])
    if events != evidence.get("events"):
        return _artifact_invalid("qualification_event_sequence_mismatch")
    chain = _validate_exported_event_chain(events)
    if chain.get("valid") is not True or chain.get("chain_root") != manifest.get("event_chain_root"):
        return _artifact_invalid("qualification_event_chain_invalid")
    outcome_state = manifest.get("outcome_state")
    if (
        manifest.get("finalization_state") != "validated"
        or manifest.get("statistical_reliability_claim") is not False
        or manifest.get("live_send_qualified") is not False
        or evidence.get("statistical_reliability_claim") is not False
        or evidence.get("live_send_qualified") is not False
    ):
        return _artifact_invalid("qualification_claim_scope_invalid")
    qualification_passed = outcome_state == "soak_criteria_met"
    receipts = evidence.get("receipt_digest_index")
    if not isinstance(receipts, list) or (qualification_passed and not receipts):
        return _artifact_invalid("qualification_receipt_index_missing")
    if evidence.get("receipt_digest_index_digest") != canonical_digest(receipts):
        return _artifact_invalid("qualification_receipt_index_digest_mismatch")
    cycles = evidence.get("cycle_digest_index")
    if evidence.get("cycle_digest_index_digest") != canonical_digest(cycles):
        return _artifact_invalid("qualification_cycle_index_digest_mismatch")
    graph = _validate_attempt_cycle_indexes(
        receipts,
        cycles,
        require_complete=qualification_passed,
    )
    if graph.get("valid") is not True:
        return _artifact_invalid(str(graph.get("reason") or "qualification_attempt_graph_invalid"))
    phase_index = evidence.get("phase_bundle_index") if isinstance(evidence.get("phase_bundle_index"), dict) else {}
    for phase in ("canary", "soak"):
        phase_entry = phase_index.get(phase) if isinstance(phase_index.get(phase), dict) else {}
        if phase_entry.get("status") == "present":
            entry_name = phase_entry.get("entry")
            if entry_name not in evidence_entries:
                return _artifact_invalid("qualification_support_bundle_missing")
            if phase_entry.get("digest") != hashlib.sha256(evidence_entries[entry_name]).hexdigest():
                return _artifact_invalid("qualification_support_bundle_digest_mismatch")
            chain_range = phase_entry.get("chain_range")
            if (
                not isinstance(phase_entry.get("support_session_id"), str)
                or not isinstance(chain_range, dict)
                or not isinstance(chain_range.get("start"), int)
                or not isinstance(chain_range.get("end"), int)
                or chain_range["start"] < 1
                or chain_range["end"] < chain_range["start"] - 1
                or chain_range["end"] > len(events)
            ):
                return _artifact_invalid("qualification_support_bundle_binding_invalid")
    if qualification_passed:
        if any((phase_index.get(phase) or {}).get("status") != "present" for phase in ("canary", "soak")):
            return _artifact_invalid("qualification_support_bundle_missing")
        canary_entry = evidence.get("canary_certificate") if isinstance(evidence.get("canary_certificate"), dict) else {}
        canary_name = canary_entry.get("entry")
        if canary_name not in evidence_entries:
            return _artifact_invalid("qualification_canary_certificate_missing")
        if canary_entry.get("digest") != hashlib.sha256(evidence_entries[canary_name]).hexdigest():
            return _artifact_invalid("qualification_canary_certificate_digest_mismatch")
        canary_validation = _validate_canary_entries(_read_zip_entries(evidence_entries[canary_name]), artifact_digest="embedded")
        if canary_validation.get("artifact_valid") is not True:
            return _artifact_invalid("qualification_canary_certificate_invalid")
        canary_entries = _read_zip_entries(evidence_entries[canary_name])
        canary_certificate = json.loads(canary_entries["certificate.json"])
        canary_events = canary_certificate.get("events") or []
        if events[: len(canary_events)] != canary_events:
            return _artifact_invalid("qualification_canary_chain_not_prefix")
        if (
            canary_certificate.get("config_hash") != evidence.get("config_hash")
            or canary_certificate.get("environment_fingerprint") != evidence.get("environment_fingerprint")
        ):
            return _artifact_invalid("qualification_canary_environment_mismatch")
        if validate_canary_metrics(evidence.get("canary_metrics") or {}).get("passed") is not True:
            return _artifact_invalid("qualification_canary_predicate_failed")
        if validate_soak_metrics(evidence.get("soak_metrics") or {}).get("passed") is not True:
            return _artifact_invalid("qualification_soak_predicate_failed")
        indexed_cycles = graph["cycles"]
        canary_cycles = [cycle for cycle in indexed_cycles if cycle.get("phase") == "canary"]
        soak_cycles = sorted(
            (cycle for cycle in indexed_cycles if cycle.get("phase") == "soak"),
            key=lambda cycle: int(cycle.get("commit_index") or 0),
        )
        if len(canary_cycles) != 10 or len(soak_cycles) != 100:
            return _artifact_invalid("qualification_cycle_count_mismatch")
        soak_metrics = evidence["soak_metrics"]
        if [cycle.get("actual_start_ns") for cycle in soak_cycles] != soak_metrics.get("actual_start_ns"):
            return _artifact_invalid("qualification_cycle_interval_index_mismatch")
        if (
            sum(1 for cycle in soak_cycles if cycle.get("mode") == "message-list") != 80
            or sum(1 for cycle in soak_cycles if cycle.get("mode") == "current-thread") != 20
        ):
            return _artifact_invalid("qualification_cycle_surface_index_mismatch")
        if not evidence.get("evidence_certificates"):
            return _artifact_invalid("qualification_evidence_certificates_missing")
        if manifest.get("purge_result") != {"status": "purged", "verified": True}:
            return _artifact_invalid("qualification_purge_not_verified")
        if manifest.get("claim_code") != "PROTOCOL_PASSED_PINNED_ENVIRONMENT":
            return _artifact_invalid("qualification_claim_invalid")
        claim_state = "protocol_passed"
    elif outcome_state == "qualification_expired":
        if manifest.get("claim_code") != "QUALIFICATION_EXPIRED":
            return _artifact_invalid("qualification_claim_invalid")
        claim_state = "qualification_expired"
    else:
        if manifest.get("claim_code") != "QUALIFICATION_BLOCKED":
            return _artifact_invalid("qualification_claim_invalid")
        claim_state = "qualification_blocked"
    claim = derive_claim(
        claim_state,
        qualification_id=str(manifest.get("qualification_id") or ""),
        config_hash=str(manifest.get("config_hash") or ""),
        manifest_digest=str(stored_manifest_digest or ""),
    )
    return {
        "schema_version": 1,
        "artifact_valid": True,
        "qualification_passed": qualification_passed,
        "claim_code": claim["claim_code"],
        "claim_text": claim["text"],
        "artifact_digest": artifact_digest,
        "manifest_digest": stored_manifest_digest,
        "qualification_id": manifest.get("qualification_id"),
        "config_hash": manifest.get("config_hash"),
        "chain_root": chain.get("chain_root"),
    }


def _validate_exported_event_chain(events: Any) -> dict[str, Any]:
    if not isinstance(events, list):
        return {"valid": False, "reason": "event_sequence_invalid", "chain_root": None}
    previous_hash = None
    for expected_sequence, event in enumerate(events, start=1):
        if not isinstance(event, dict) or event.get("sequence") != expected_sequence:
            return {"valid": False, "reason": "event_sequence_invalid", "chain_root": previous_hash}
        if event.get("previous_hash") != previous_hash:
            return {"valid": False, "reason": "event_previous_hash_mismatch", "chain_root": previous_hash}
        body = {key: value for key, value in event.items() if key not in {"previous_hash", "event_hash"}}
        expected_hash = canonical_digest({"previous_hash": previous_hash, "event_without_hash": body})
        if event.get("event_hash") != expected_hash:
            return {"valid": False, "reason": "event_hash_mismatch", "chain_root": previous_hash}
        previous_hash = expected_hash
    return {"valid": True, "reason": None, "chain_root": previous_hash, "event_count": len(events)}


def _phase_bundle_entry(
    entry: str,
    content: bytes | None,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if content is None:
        return {"status": "not_started", "entry": None, "digest": None, **dict(metadata or {})}
    return {
        "status": "present",
        "entry": entry,
        "digest": hashlib.sha256(content).hexdigest(),
        **dict(metadata or {}),
    }


def _zip_bytes(entries: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(entries.items()):
            if name.startswith("/") or ".." in Path(name).parts:
                raise ArtifactViolation("artifact_entry_path_invalid")
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def _read_zip_entries(content: bytes) -> dict[str, bytes]:
    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
        for info in archive.infolist():
            name = info.filename
            if name in entries or name.startswith("/") or ".." in Path(name).parts or info.is_dir():
                raise ArtifactViolation("artifact_entry_invalid")
            entries[name] = archive.read(info)
    return entries


def _parse_jsonl(content: bytes) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in content.decode("utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ArtifactViolation("artifact_jsonl_invalid")
        events.append(payload)
    return events


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _jsonl_bytes(payloads: list[dict[str, Any]]) -> bytes:
    return b"".join(_json_bytes(payload) for payload in payloads)


def _artifact_invalid(reason: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_valid": False,
        "qualification_passed": False,
        "reason": reason,
    }


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
