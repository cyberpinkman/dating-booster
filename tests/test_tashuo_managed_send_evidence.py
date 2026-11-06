from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
import zlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from dating_boost.core.encryption import EncryptionError
from dating_boost.apps.tashuo.managed_send_evidence import ManagedSendEvidenceStore
from dating_boost.apps.tashuo.managed_visual_evidence import VisualFrame


def _frame(tmp_path, index):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    path = tmp_path / f"frame-{index}.png"
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\x00" + bytes([index] * 6)) * 2))
        + chunk(b"IEND", b"")
    )
    return VisualFrame.from_payload({
        "status": "ok", "path": str(path), "frame_id": f"frame-{index}",
        "state": "tashuo_conversation", "captured_at": f"2026-09-20T10:00:0{index}Z",
    })


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    store = ManagedSendEvidenceStore(tmp_path / "data")
    evidence_id = store.prepare(
        target_id="synthetic-target", candidate_key="synthetic-candidate",
        target_binding="synthetic-binding", inbound_revision="synthetic-revision",
        payload_hash=hashlib.sha256(b"synthetic").hexdigest(), before=_frame(tmp_path, 1),
    )
    store.record_click(evidence_id, receipt_id="receipt", clicked_at="2026-09-20T10:00:02Z")
    store.record_after("receipt", _frame(tmp_path, 3))
    return store


def test_recovery_cannot_accept_plain_json_in_place_of_encrypted_receipt_evidence(evidence, tmp_path):
    receipt_path = evidence._receipt_path("receipt")
    manifest = evidence.storage.read_json(receipt_path, expected_schema_version=1)
    attempt = {**manifest, "exact_text": "synthetic"}
    # Both plaintext manifests have valid matching digests and refer to real fixture PNGs.
    raw = ManagedSendEvidenceStore(tmp_path / "plaintext")
    for path in (receipt_path, evidence._preflight_path(manifest["evidence_id"])):
        destination = raw.storage.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(evidence.storage.read_json(path, expected_schema_version=1)))
    with pytest.raises(ValueError, match="managed_send_evidence_requires_encrypted_store"):
        raw.load_for_attempt(attempt)


def test_recovery_requires_an_encrypted_sqlite_payload_even_with_valid_plaintext_contents(evidence):
    receipt_path = evidence._receipt_path("receipt")
    manifest = evidence.storage.read_json(receipt_path, expected_schema_version=1)
    production = evidence.storage._sqlite_store()
    with sqlite3.connect(production.db_path) as conn:
        conn.execute("UPDATE documents SET payload_json = ? WHERE path = ?", (json.dumps(manifest), receipt_path.as_posix()))
    assert production.get_document(receipt_path.as_posix()) == manifest  # Existing legacy readers still work.
    with pytest.raises(EncryptionError, match="document_encryption_required"):
        evidence.load_for_attempt({**manifest, "exact_text": "synthetic"})


def _result(comparison="identical"):
    return {
        "comparison": comparison, "confidence": "high",
        "before_composer_readable": True, "after_new_outbound_readable": True,
    }


@pytest.mark.parametrize("outcome", ["identical", "different", "uncertain", "failed", "interrupted"])
def test_rendered_attempt_is_durable_once_including_negative_failed_and_interrupted(evidence, outcome):
    assert evidence.begin_rendered_verification("receipt") is None
    started = evidence.begin_rendered_verification("receipt")
    assert started["status"] == "started"
    if outcome == "failed":
        evidence.finish_rendered_verification("receipt", None, error_code="managed_rendered_comparison_failed")
    elif outcome != "interrupted":
        evidence.finish_rendered_verification("receipt", _result(outcome))
    restarted = ManagedSendEvidenceStore(evidence.storage.root)
    saved = restarted.begin_rendered_verification("receipt")
    assert saved["status"] == ("started" if outcome == "interrupted" else "failed" if outcome == "failed" else "complete")
    if saved["status"] == "complete":
        assert saved["result"] == _result(outcome)
        saved["result"]["comparison"] = "different"  # The returned state is not a mutable alias.
        assert restarted.begin_rendered_verification("receipt")["result"] == _result(outcome)
    if outcome != "interrupted":
        with pytest.raises(ValueError, match="^managed_rendered_attempt_not_pending$"):
            restarted.finish_rendered_verification("receipt", _result())


def test_concurrent_begin_only_grants_one_rendered_attempt(evidence):
    other = ManagedSendEvidenceStore(evidence.storage.root)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda store: store.begin_rendered_verification("receipt"), (evidence, other)))
    assert sum(result is None for result in results) == 1
    assert [result["status"] for result in results if result is not None] == ["started"]


@pytest.mark.parametrize("malformation", ["extra_text", "boolean_number", "bad_enum", "unsafe_error"])
def test_cache_accepts_only_fixed_structured_fields(evidence, malformation):
    evidence.begin_rendered_verification("receipt")
    result = _result()
    if malformation == "extra_text":
        result["text"] = "synthetic private text"
    elif malformation == "boolean_number":
        result["before_composer_readable"] = 1
    elif malformation == "bad_enum":
        result["confidence"] = "absolutely"
    with pytest.raises(ValueError, match="^managed_rendered_(result_invalid|error_code_invalid)$"):
        if malformation == "unsafe_error":
            evidence.finish_rendered_verification("receipt", None, error_code="private exception text")
        else:
            evidence.finish_rendered_verification("receipt", result)
    assert evidence.begin_rendered_verification("receipt")["status"] == "started"
