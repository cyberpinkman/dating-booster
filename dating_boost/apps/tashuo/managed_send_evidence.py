"""Durable, receipt-bound evidence for read-only managed send recovery."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from dating_boost.apps.tashuo.managed_rendered_verification import _validated_payload
from dating_boost.apps.tashuo.managed_visual_evidence import (
    VisualFrame, VisualTransition, _capture_time, _transition_from_payload, _validate_pair,
)
from dating_boost.core.storage import JsonStorage
from dating_boost.core.managed_run import JsonManagedRunStore


_ROOT = Path("managed_run") / "send_evidence"
_IDENTITY_FIELDS = ("target_id", "candidate_key", "target_binding", "inbound_revision", "payload_hash")


class _EncryptedEvidenceStorage(JsonStorage):
    def read_json(self, relative_path: Path, *, expected_schema_version: int) -> dict[str, Any]:
        path = self._resolve_path(relative_path)
        store = self._sqlite_store()
        if store is None:
            if path.exists():
                raise ValueError("managed_send_evidence_requires_encrypted_store")
            raise FileNotFoundError(path)
        data = store.get_document(relative_path.as_posix(), require_encrypted=True)
        if data is None:
            raise FileNotFoundError(path)
        if data.get("schema_version") != expected_schema_version:
            raise ValueError("managed_send_evidence_schema_invalid")
        return data

    def _sqlite_store_for_write(self) -> Any:
        store = super()._sqlite_store_for_write()
        # JsonStorage intentionally supports legacy plaintext repositories.
        # New raw conversation evidence must never use that compatibility path.
        if store is None:
            raise ValueError("managed_send_evidence_requires_encrypted_store")
        return store


@dataclass(frozen=True)
class SavedSendEvidence:
    before: VisualFrame
    after: VisualFrame
    receipt_id: str
    clicked_at: str
    composer: dict[str, Any] | None
    transition: VisualTransition | None
    manifest_digest: str
    rendered_verification: dict[str, Any] | None = None


class ManagedSendEvidenceStore:
    """Use the same encrypted document store as ManagedRun; never infer orphan frames."""

    def __init__(self, root: Path):
        self.storage = _EncryptedEvidenceStorage(root)
        self._leases = JsonManagedRunStore(root)

    def prepare(
        self, *, target_id: str, candidate_key: str, target_binding: str,
        inbound_revision: str, payload_hash: str, before: VisualFrame,
        provenance: Mapping[str, Any] | None = None,
    ) -> str:
        identity = {
            "target_id": target_id, "candidate_key": candidate_key,
            "target_binding": target_binding, "inbound_revision": inbound_revision,
            "payload_hash": payload_hash,
        }
        if any(not isinstance(value, str) or not value for value in identity.values()) or not _digest_valid(payload_hash):
            raise ValueError("managed_send_evidence_identity_invalid")
        source = dict(provenance or {"source": "captured_at_send_boundary"})
        if set(source) - {"source", "reviewed_at"} or source.get("source") not in {
            "captured_at_send_boundary", "host_reviewed_legacy_capture",
        }:
            raise ValueError("managed_send_evidence_provenance_invalid")
        if source["source"] == "host_reviewed_legacy_capture":
            _capture_time(source.get("reviewed_at"))
        elif "reviewed_at" in source:
            raise ValueError("managed_send_evidence_provenance_invalid")
        evidence_id = uuid4().hex
        self.storage.write_json(self._preflight_path(evidence_id), {
            "schema_version": 1, "evidence_id": evidence_id, **identity,
            "before": _frame_payload(before), "provenance": source,
            "prepared_at": _now(),
        })
        return evidence_id

    def record_click(self, evidence_id: str, *, receipt_id: str, clicked_at: str) -> None:
        preflight = self.storage.read_json(self._preflight_path(evidence_id), expected_schema_version=1)
        before = _restore_frame(preflight.get("before"))
        if _capture_time(clicked_at) <= _capture_time(before.captured_at):
            raise ValueError("managed_send_evidence_click_not_fresh")
        path = self._receipt_path(receipt_id)
        if self.storage.exists(path):
            raise ValueError("managed_send_evidence_receipt_already_recorded")
        self.storage.write_json(path, {
            **preflight, "receipt_id": receipt_id, "clicked_at": clicked_at,
            "preflight_digest": _digest(preflight), "click_recorded_at": _now(),
        })

    def record_after(
        self, receipt_id: str, after: VisualFrame, *,
        composer: Mapping[str, Any] | None = None,
        transition: VisualTransition | None = None,
    ) -> None:
        manifest = self._read_receipt(receipt_id)
        before = _restore_frame(manifest.get("before"))
        _validate_pair(before, after)
        if _capture_time(after.captured_at) <= _capture_time(manifest["clicked_at"]):
            raise ValueError("managed_post_send_capture_not_fresh")
        after_payload = _frame_payload(after)
        if "after" in manifest and manifest["after"] != after_payload:
            raise ValueError("managed_send_evidence_after_frame_changed")
        manifest["after"] = after_payload
        if composer is not None:
            # Preserve evidence of the AX read, never the potentially private
            # residual composer value. A failed read is not proof of emptiness.
            reading = {
                "available": composer.get("status") == "ok" and isinstance(composer.get("value"), str),
                "input_cleared": composer.get("status") == "ok" and composer.get("value") == "",
            }
            if "composer" in manifest and manifest["composer"] != reading:
                raise ValueError("managed_send_evidence_composer_changed")
            manifest["composer"] = reading
        if transition is not None:
            typed = _transition_payload(transition)
            if "transition" in manifest and manifest["transition"] != typed:
                raise ValueError("managed_send_evidence_transition_changed")
            manifest["transition"] = typed
        manifest["after_recorded_at"] = _now()
        self.storage.write_json(self._receipt_path(receipt_id), manifest)

    def load_for_attempt(self, attempt: Mapping[str, Any]) -> SavedSendEvidence:
        """Read existing receipt evidence and reject any mismatched original binding."""
        receipt_id = attempt.get("receipt_id")
        if not isinstance(receipt_id, str) or not receipt_id:
            raise ValueError("managed_send_evidence_receipt_missing")
        manifest = self._read_receipt(receipt_id)
        if any(manifest.get(key) != attempt.get(key) for key in _IDENTITY_FIELDS):
            raise ValueError("managed_send_evidence_attempt_mismatch")
        text = attempt.get("exact_text")
        if not isinstance(text, str) or not text or hashlib.sha256(text.encode("utf-8")).hexdigest() != manifest.get("payload_hash"):
            raise ValueError("managed_send_evidence_payload_mismatch")
        if manifest.get("clicked_at") != attempt.get("clicked_at"):
            raise ValueError("managed_send_evidence_receipt_mismatch")
        before, after = _restore_frame(manifest.get("before")), _restore_frame(manifest.get("after"))
        _validate_pair(before, after)
        if not _capture_time(before.captured_at) < _capture_time(manifest["clicked_at"]) < _capture_time(after.captured_at):
            raise ValueError("managed_send_evidence_times_invalid")
        composer = manifest.get("composer")
        if composer is not None and (
            not isinstance(composer, dict) or set(composer) != {"available", "input_cleared"}
            or any(type(value) is not bool for value in composer.values())
            or (composer["input_cleared"] and not composer["available"])
        ):
            raise ValueError("managed_send_evidence_composer_invalid")
        transition = _transition_from_payload(manifest["transition"]) if "transition" in manifest else None
        rendered = _rendered_state(manifest.get("rendered_verification"))
        return SavedSendEvidence(
            before=before, after=after, receipt_id=receipt_id, clicked_at=manifest["clicked_at"],
            composer=composer, transition=transition, manifest_digest=_digest(manifest),
            rendered_verification=rendered,
        )

    def begin_rendered_verification(self, receipt_id: str) -> dict[str, Any] | None:
        """Durably consume the one optional rendered comparison before calling it."""
        path = self._receipt_path(receipt_id)
        with self._leases.state_lease("send_evidence_" + path.stem):
            manifest = self._read_receipt(receipt_id)
            existing = _rendered_state(manifest.get("rendered_verification"))
            if existing is not None:
                return existing
            _restore_frame(manifest.get("after"))
            manifest["rendered_verification"] = {"status": "started", "started_at": _now()}
            self.storage.write_json(path, manifest)
        return None

    def finish_rendered_verification(
        self, receipt_id: str, result: dict[str, Any] | None, *, error_code: str | None = None,
    ) -> None:
        if result is not None:
            if error_code is not None:
                raise ValueError("managed_rendered_result_invalid")
            completion = {"status": "complete", "result": _validated_payload(result)}
        else:
            error_code = error_code or "managed_rendered_comparison_failed"
            if not isinstance(error_code, str) or len(error_code) > 96 or not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", error_code):
                raise ValueError("managed_rendered_error_code_invalid")
            completion = {"status": "failed", "error_code": error_code}
        path = self._receipt_path(receipt_id)
        with self._leases.state_lease("send_evidence_" + path.stem):
            manifest = self._read_receipt(receipt_id)
            existing = _rendered_state(manifest.get("rendered_verification"))
            if existing is None or existing["status"] != "started":
                raise ValueError("managed_rendered_attempt_not_pending")
            manifest["rendered_verification"] = {
                **existing, **completion, "finished_at": _now(),
            }
            self.storage.write_json(path, manifest)

    def _read_receipt(self, receipt_id: Any) -> dict[str, Any]:
        try:
            manifest = self.storage.read_json(self._receipt_path(receipt_id), expected_schema_version=1)
        except FileNotFoundError:
            raise ValueError("managed_send_evidence_missing") from None
        if manifest.get("receipt_id") != receipt_id:
            raise ValueError("managed_send_evidence_receipt_mismatch")
        try:
            preflight = self.storage.read_json(self._preflight_path(manifest.get("evidence_id")), expected_schema_version=1)
        except FileNotFoundError:
            raise ValueError("managed_send_evidence_preflight_missing") from None
        if manifest.get("preflight_digest") != _digest(preflight) or any(
            manifest.get(key) != value for key, value in preflight.items()
        ):
            raise ValueError("managed_send_evidence_preflight_mismatch")
        return manifest

    @staticmethod
    def _preflight_path(evidence_id: Any) -> Path:
        if not isinstance(evidence_id, str) or not re.fullmatch(r"[0-9a-f]{32}", evidence_id):
            raise ValueError("managed_send_evidence_id_invalid")
        return _ROOT / "preflight" / f"{evidence_id}.json"

    @staticmethod
    def _receipt_path(receipt_id: Any) -> Path:
        if not isinstance(receipt_id, str) or not receipt_id:
            raise ValueError("managed_send_evidence_receipt_missing")
        return _ROOT / "receipts" / f"{hashlib.sha256(receipt_id.encode('utf-8')).hexdigest()}.json"


def _frame_payload(frame: VisualFrame) -> dict[str, Any]:
    frame.assert_unchanged()
    return {**asdict(frame), "path": str(frame.path)}


def _restore_frame(payload: Any) -> VisualFrame:
    if not isinstance(payload, dict):
        raise ValueError("managed_send_evidence_frame_missing")
    try:
        frame = VisualFrame.from_payload({**payload, "status": "ok"})
        if _frame_payload(frame) != payload:
            raise ValueError
    except Exception:
        raise ValueError("managed_send_evidence_frame_changed") from None
    return frame


def _transition_payload(transition: VisualTransition) -> dict[str, Any]:
    if not isinstance(transition, VisualTransition):
        raise ValueError("managed_send_evidence_transition_invalid")
    payload = {**asdict(transition), "added_bubbles": [asdict(bubble) for bubble in transition.added_bubbles]}
    _transition_from_payload(payload)
    return payload


def _rendered_state(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("status") not in {"started", "complete", "failed"}:
        raise ValueError("managed_rendered_state_invalid")
    status = value["status"]
    fields = {"status", "started_at"}
    if status != "started":
        fields.update({"finished_at", "result" if status == "complete" else "error_code"})
    if set(value) != fields:
        raise ValueError("managed_rendered_state_invalid")
    _capture_time(value["started_at"])
    if status != "started":
        _capture_time(value["finished_at"])
    if status == "complete":
        return {**value, "result": _validated_payload(value["result"])}
    if status == "failed" and (
        not isinstance(value["error_code"], str) or len(value["error_code"]) > 96
        or not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", value["error_code"])
    ):
        raise ValueError("managed_rendered_state_invalid")
    return dict(value)


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _digest_valid(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
