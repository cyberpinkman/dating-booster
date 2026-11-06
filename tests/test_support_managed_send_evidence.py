import hashlib
import sqlite3
import struct
import zipfile
import zlib

import pytest

from dating_boost.apps.tashuo.managed_send_evidence import ManagedSendEvidenceStore
from dating_boost.apps.tashuo.managed_visual_evidence import VisualBubble, VisualFrame, VisualTransition
from dating_boost.core.encryption import payload_is_encrypted
from dating_boost.core.support import SupportLogRepository


def _frame(tmp_path, index):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    path = tmp_path / f"private-capture-location-{index}.png"
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


def _prepare(store, before):
    return store.prepare(
        target_id="synthetic-target", candidate_key="synthetic-candidate",
        target_binding="synthetic-binding", inbound_revision="synthetic-revision",
        payload_hash=hashlib.sha256(b"synthetic-private-message-raw").hexdigest(), before=before,
    )


@pytest.mark.parametrize("copy_manifest_to_support_event", [False, True])
def test_managed_send_evidence_is_encrypted_and_excluded_from_strict_support_bundle(
    tmp_path, monkeypatch, copy_manifest_to_support_event,
):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    data = tmp_path / "data"
    store = ManagedSendEvidenceStore(data)
    before, after = _frame(tmp_path, 1), _frame(tmp_path, 3)
    evidence_id = _prepare(store, before)
    store.record_click(evidence_id, receipt_id="receipt", clicked_at="2026-09-20T10:00:02Z")
    store.record_after("receipt", after, transition=VisualTransition(
        same_conversation=True, baseline_messages_preserved=True,
        added_bubbles=(VisualBubble("outbound", "synthetic-private-message-raw", "text"),),
        other_conversation_change=False, composer_state="empty", composer_text="", confidence="high",
    ))
    manifest = store._read_receipt("receipt")
    assert manifest["transition"]["added_bubbles"][0]["text"] == "synthetic-private-message-raw"
    with sqlite3.connect(data / "dating_boost.sqlite3") as connection:
        payloads = [row[0] for row in connection.execute(
            "SELECT payload_json FROM documents WHERE path LIKE 'managed_run/send_evidence/%'",
        )]
    assert len(payloads) == 2
    assert all(payload_is_encrypted(payload) for payload in payloads)
    assert not list((data / "managed_run" / "send_evidence").rglob("*.json"))

    support = SupportLogRepository(data)
    session = support.start_session(host="codex", app_id="tashuo")
    assert session["status"] == "active"
    if copy_manifest_to_support_event:
        support.record_event(session_id=session["session_id"], event_type="synthetic_send_evidence", payload=manifest)
    support.stop_session(session_id=session["session_id"])
    output = tmp_path / "strict.zip"
    result = support.bundle(session_id=session["session_id"], output=output, redaction="strict")
    assert result["status"] == "ok"
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        contents = b"\n".join(archive.read(name) for name in names)
    assert len(names) == 4
    assert not any(name.endswith(".png") or "send_evidence" in name for name in names)
    for secret in ("synthetic-private-message-raw", str(before.path), str(after.path), "private-capture-location"):
        assert secret.encode("utf-8") not in contents
        assert secret not in "\n".join(payloads)


def test_new_managed_send_evidence_refuses_legacy_plaintext_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    data = tmp_path / "legacy"
    data.mkdir()
    legacy_profile = data / "user_profile.json"
    legacy_profile.write_text('{"schema_version": 1, "legacy": true}')
    store = ManagedSendEvidenceStore(data)
    with pytest.raises(ValueError, match="^managed_send_evidence_requires_encrypted_store$"):
        _prepare(store, _frame(tmp_path, 1))
    assert not list((data / "managed_run" / "send_evidence").rglob("*.json"))
    assert not (data / "dating_boost.sqlite3").exists()
    assert legacy_profile.read_text() == '{"schema_version": 1, "legacy": true}'
