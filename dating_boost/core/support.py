from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from dating_boost.core.production_store import ProductionDataStore, payload_digest


SUPPORT_LOG_SCHEMA_VERSION = 1
SUPPORT_EVIDENCE_SCHEMA_VERSION = 1
SUPPORT_BUNDLE_SCHEMA_VERSION = 1
ACTIVE_SESSION_PATH = "support/active_session.json"
SENSITIVE_KEYS = {
    "best_reply",
    "safer_reply",
    "bolder_reply",
    "why_this_works",
    "situation_read",
    "naturalness_notes",
    "followup_if_match_replies",
    "mode_notes",
    "draft_text",
    "message_text",
    "payload_text",
    "preference_text",
    "profile_bio_text",
    "raw_text",
    "screenshot_text",
    "staged_text",
    "outbound_text",
    "visible_text",
    "clipboard_text",
    "conversation_text",
    "profile_text",
    "ocr_text",
    "text",
}
COMMAND_VALUE_REDACT_FLAGS = {
    "--data-dir",
    "--input",
    "--context",
    "--goal",
    "--text-file",
    "--authorization",
    "--availability",
    "--action-request",
    "--adapter-package",
    "--candidate-key",
    "--fixture-host",
    "--match-id",
    "--package",
    "--target-binding",
    "--target",
    "--payload-json",
    "--precondition-json",
    "--output",
    "--output-dir",
    "--recovery-passphrase-file",
    "--skill-package",
    "--visible-name",
    "--window-title",
    "--work-dir",
}
HOSTS = {"codex", "claude-code", "openclaw", "hermes"}
REDACTIONS = {"strict", "standard", "full-with-consent"}
SAFE_STRING_KEYS = {
    "action",
    "app_id",
    "bundle_type",
    "candidate_key",
    "clipboard_restore_status",
    "command",
    "created_at",
    "default_bundle_redaction",
    "event_id",
    "event_type",
    "expires_at",
    "evidence_id",
    "harness_backend",
    "host_agent",
    "input_backend",
    "intent",
    "kind",
    "location_method",
    "mode",
    "next_host_action",
    "page",
    "phase",
    "reason",
    "redaction",
    "risk",
    "screen_state",
    "source_event_type",
    "started_at",
    "status",
    "stopped_at",
    "stored_at",
    "support_session_id",
    "target",
    "target_match_id",
    "verification_method",
}
SAFE_STRING_LIST_KEYS = {
    "argv_redacted",
    "files",
    "missing",
    "required_marker_hashes",
    "supported_hosts",
    "supported_redactions",
    "topic_labels",
}
SAFE_STRING_SUFFIXES = (
    "_fingerprint",
    "_hash",
    "_id",
    "_status",
    "_type",
)


@dataclass(frozen=True)
class SupportCommandEvent:
    session_id: str
    event_id: str


class SupportLogRepository:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.store = ProductionDataStore(self.root)

    def start_session(
        self,
        *,
        host: str,
        app_id: str,
        owner: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if host not in HOSTS:
            return _blocked("unsupported_host_agent", supported_hosts=sorted(HOSTS))
        try:
            support_owner = _normalize_support_owner(owner)
        except ValueError:
            return _blocked("support_session_owner_invalid")
        ready = self._ensure_ready()
        if ready.get("status") != "ok":
            return ready
        now = _now_iso()
        session_id = "support_" + _digest({"host": host, "app_id": app_id, "at": now, "nonce": uuid4().hex})[:16]
        session = {
            "schema_version": SUPPORT_LOG_SCHEMA_VERSION,
            "session_id": session_id,
            "host_agent": host,
            "app_id": app_id,
            "status": "active",
            "started_at": now,
            "stopped_at": None,
            "sensitive_evidence_vault": "encrypted_sqlite",
            "default_bundle_redaction": "strict",
            "support_owner": support_owner,
        }
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = _tx_read_document(conn, self.store, ACTIVE_SESSION_PATH)
            if active and active.get("status") == "active":
                if (
                    active.get("support_owner") == support_owner
                    and active.get("host_agent") == host
                    and active.get("app_id") == app_id
                ):
                    return {**active, "status": "active", "reused": True}
                return _blocked("support_session_owner_conflict")
            _tx_write_document(conn, self.store, _session_path(session_id), session)
            _tx_write_document(conn, self.store, ACTIVE_SESSION_PATH, session)
        self._append_event(
            session_id,
            event_type="support_session_started",
            payload={
                "host_agent": host,
                "app_id": app_id,
                "sensitive_evidence_vault": "encrypted_sqlite",
                "support_owner": support_owner,
            },
        )
        return {**session, "status": "active"}

    def stop_session(
        self,
        *,
        session_id: str,
        owner: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        ready = self._ensure_ready()
        if ready.get("status") != "ok":
            return ready
        try:
            requested_owner = _normalize_support_owner(owner)
        except ValueError:
            return _blocked("support_session_owner_invalid")
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            session = _tx_read_document(conn, self.store, _session_path(session_id))
            if not session:
                return _blocked("support_session_not_found", session_id=session_id)
            stored_owner = session.get("support_owner")
            if stored_owner is not None and requested_owner is None:
                return _blocked("support_session_owner_required")
            if stored_owner != requested_owner:
                return _blocked("support_session_owner_mismatch")
            active = _tx_read_document(conn, self.store, ACTIVE_SESSION_PATH)
            if active and active.get("status") == "active" and active.get("session_id") != session_id:
                return _blocked("support_session_owner_conflict")
            now = _now_iso()
            stopped = {**session, "status": "stopped", "stopped_at": now}
            _tx_write_document(conn, self.store, _session_path(session_id), stopped)
            if active and active.get("session_id") == session_id:
                _tx_write_document(conn, self.store, ACTIVE_SESSION_PATH, stopped)
        self._append_event(session_id, event_type="support_session_stopped", payload={"stopped_at": now})
        return stopped

    def active_session(self) -> dict[str, Any] | None:
        if not self.store.db_path.exists():
            return None
        try:
            active = self.store.get_document(ACTIVE_SESSION_PATH)
        except Exception:  # noqa: BLE001 - support logging must never break primary commands.
            return None
        if not active or active.get("status") != "active":
            return None
        return active

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        if not isinstance(session_id, str) or not session_id.strip():
            return None
        try:
            session = self.store.get_document(_session_path(session_id))
        except Exception:  # noqa: BLE001 - support reads must fail closed at the caller.
            return None
        return dict(session) if isinstance(session, dict) else None

    def record_event(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        sensitive: dict[str, Any] | None = None,
        sensitive_kind: str | None = None,
    ) -> dict[str, Any]:
        if sensitive is not None:
            ready = self._ensure_ready()
            if ready.get("status") != "ok":
                return ready
        if not self.store.get_document(_session_path(session_id)):
            return _blocked("support_session_not_found", session_id=session_id)
        evidence_summary = None
        if sensitive is not None:
            evidence_summary = self._store_sensitive_evidence(
                session_id=session_id,
                kind=sensitive_kind or event_type,
                payload=sensitive,
                source_event_type=event_type,
            )
        event = self._append_event(
            session_id,
            event_type=event_type,
            payload=payload,
            sensitive_evidence=evidence_summary,
        )
        return {
            "schema_version": SUPPORT_LOG_SCHEMA_VERSION,
            "status": "ok",
            "session_id": session_id,
            "event_id": event["event_id"],
            "event_type": event_type,
            "sensitive_evidence": evidence_summary,
        }

    def bundle(
        self,
        *,
        session_id: str,
        output: Path,
        redaction: str = "strict",
        include_sensitive: list[str] | None = None,
        confirm: str | None = None,
    ) -> dict[str, Any]:
        if redaction not in REDACTIONS:
            return _blocked("unsupported_redaction", supported_redactions=sorted(REDACTIONS))
        ready = self._ensure_ready()
        if ready.get("status") != "ok":
            return ready
        session = self.store.get_document(_session_path(session_id))
        if not session:
            return _blocked("support_session_not_found", session_id=session_id)
        include_sensitive = include_sensitive or []
        if redaction == "full-with-consent":
            expected = sensitive_export_confirm_token(session_id)
            if confirm != expected:
                return _blocked(
                    "confirm_token_mismatch",
                    required_confirm_token=expected,
                    session_id=session_id,
                )
        elif include_sensitive:
            return _blocked("sensitive_export_requires_full_consent", session_id=session_id)
        events = [
            _redact_sensitive_keys(item["payload"])
            for item in self.store.list_audit_events(stream=_events_stream(session_id))
        ]
        evidence_docs = self.store.list_documents(prefix=f"support/{session_id}/evidence/")
        evidence_manifest = [
            _redact_sensitive_keys(dict(doc["payload"].get("summary") or {}))
            for doc in evidence_docs
            if isinstance(doc.get("payload"), dict)
        ]
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": SUPPORT_BUNDLE_SCHEMA_VERSION,
            "status": "ok",
            "bundle_type": "dating_boost_support",
            "session_id": session_id,
            "created_at": _now_iso(),
            "redaction": redaction,
            "contains_sensitive_text": redaction == "full-with-consent" and bool(include_sensitive),
            "contains_screenshots": False,
            "files": [],
        }
        payloads: dict[str, Any] = {
            "manifest.json": manifest,
            "support/session.redacted.json": _redact_sensitive_keys(session),
            "support/events.redacted.jsonl": events,
            "support/evidence_manifest.redacted.json": evidence_manifest,
        }
        if redaction == "full-with-consent":
            sensitive_by_kind: dict[str, list[dict[str, Any]]] = {}
            for doc in evidence_docs:
                payload = doc.get("payload")
                if not isinstance(payload, dict):
                    continue
                kind = str(payload.get("kind") or "")
                if kind not in include_sensitive:
                    continue
                sensitive_by_kind.setdefault(kind, []).append(payload)
            for kind, entries in sensitive_by_kind.items():
                payloads[f"support/sensitive/{kind}.json"] = entries[0] if len(entries) == 1 else entries
        manifest["files"] = sorted(payloads)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in payloads.items():
                if name.endswith(".jsonl"):
                    archive.writestr(
                        name,
                        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in payload),
                    )
                else:
                    archive.writestr(name, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return {
            "schema_version": SUPPORT_BUNDLE_SCHEMA_VERSION,
            "status": "ok",
            "session_id": session_id,
            "output": str(output),
            "redaction": redaction,
            "files": sorted(payloads),
            "contains_sensitive_text": manifest["contains_sensitive_text"],
        }

    def record_command_started(
        self,
        argv: list[str],
        *,
        context: dict[str, Any] | None = None,
    ) -> SupportCommandEvent | None:
        active = self._session_for_command_context(context)
        if not active:
            return None
        context_payload = _command_context_payload(context)
        event = self._append_event(
            str(active["session_id"]),
            event_type="command_started",
            payload={
                "argv_redacted": redact_argv(argv),
                "command": _command_name(argv),
                **context_payload,
            },
        )
        return SupportCommandEvent(session_id=str(active["session_id"]), event_id=str(event["event_id"]))

    def record_command_finished(
        self,
        command_event: SupportCommandEvent | None,
        *,
        argv: list[str],
        exit_code: int,
        duration_ms: int,
    ) -> None:
        if command_event is None:
            return
        try:
            self._append_event(
                command_event.session_id,
                event_type="command_finished",
                payload={
                    "argv_redacted": redact_argv(argv),
                    "command": _command_name(argv),
                    "started_event_id": command_event.event_id,
                    "exit_code": exit_code,
                    "duration_ms": duration_ms,
                },
            )
        except Exception:
            return

    def record_command_interrupted(
        self,
        command_event: SupportCommandEvent | None,
        *,
        argv: list[str],
        reason: str,
    ) -> None:
        if command_event is None:
            return
        try:
            self._append_event(
                command_event.session_id,
                event_type="command_interrupted",
                payload={
                    "argv_redacted": redact_argv(argv),
                    "command": _command_name(argv),
                    "started_event_id": command_event.event_id,
                    "reason": reason,
                },
            )
        except Exception:
            return

    def validate_command_coverage(
        self,
        *,
        session_id: str,
        required_context_ids: list[str],
    ) -> dict[str, Any]:
        events = [
            item["payload"]
            for item in self.store.list_audit_events(stream=_events_stream(session_id))
            if isinstance(item.get("payload"), dict)
        ]
        starts: dict[str, list[str]] = {}
        terminals: dict[str, int] = {}
        for event in events:
            if event.get("event_type") == "command_started":
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                context_id = str(payload.get("attempt_id") or payload.get("probe_id") or "")
                if context_id:
                    starts.setdefault(context_id, []).append(str(event.get("event_id") or ""))
            elif event.get("event_type") in {"command_finished", "command_interrupted"}:
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                started_event_id = str(payload.get("started_event_id") or "")
                if started_event_id:
                    terminals[started_event_id] = terminals.get(started_event_id, 0) + 1
        missing: list[str] = []
        for context_id in sorted(set(required_context_ids) | set(starts)):
            event_ids = starts.get(context_id, [])
            if len(event_ids) != 1 or terminals.get(event_ids[0], 0) != 1:
                missing.append(context_id)
        return {
            "schema_version": SUPPORT_LOG_SCHEMA_VERSION,
            "valid": not missing,
            "reason": None if not missing else "support_command_coverage_incomplete",
            "missing_context_ids": missing,
        }

    def reconcile_interrupted_context(
        self,
        *,
        session_id: str,
        context_id: str,
        reason: str,
    ) -> dict[str, Any]:
        events = [
            item["payload"]
            for item in self.store.list_audit_events(stream=_events_stream(session_id))
            if isinstance(item.get("payload"), dict)
        ]
        starts: list[dict[str, Any]] = []
        terminal_started_ids: set[str] = set()
        for event in events:
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if event.get("event_type") == "command_started":
                current_id = str(payload.get("attempt_id") or payload.get("probe_id") or "")
                if current_id == context_id:
                    starts.append(event)
            elif event.get("event_type") in {"command_finished", "command_interrupted"}:
                started_event_id = str(payload.get("started_event_id") or "")
                if started_event_id:
                    terminal_started_ids.add(started_event_id)
        unresolved = [event for event in starts if str(event.get("event_id") or "") not in terminal_started_ids]
        if len(unresolved) > 1:
            return _blocked("support_command_coverage_ambiguous", context_id=context_id)
        if not unresolved:
            return {"schema_version": SUPPORT_LOG_SCHEMA_VERSION, "status": "ok", "reconciled": False}
        started = unresolved[0]
        self._append_event(
            session_id,
            event_type="command_interrupted",
            payload={
                "argv_redacted": ["qualification", "recovery"],
                "command": "qualification",
                "started_event_id": started.get("event_id"),
                "reason": reason,
            },
        )
        return {
            "schema_version": SUPPORT_LOG_SCHEMA_VERSION,
            "status": "ok",
            "reconciled": True,
            "started_event_id": started.get("event_id"),
        }

    def _session_for_command_context(self, context: dict[str, Any] | None) -> dict[str, Any] | None:
        if context is None:
            return self.active_session()
        session_id = context.get("support_session_id")
        if not isinstance(session_id, str) or not session_id:
            return None
        session = self.store.get_document(_session_path(session_id))
        if not session or session.get("status") != "active":
            return None
        owner = session.get("support_owner")
        if not isinstance(owner, dict):
            return None
        if owner.get("qualification_id") != context.get("qualification_id") or owner.get("phase") != context.get("phase"):
            return None
        attempt_id = context.get("attempt_id")
        probe_id = context.get("probe_id")
        if bool(attempt_id) == bool(probe_id):
            return None
        return session

    def _ensure_ready(self) -> dict[str, Any]:
        doctor = self.store.doctor()
        if doctor.get("status") == "ok":
            return {"schema_version": SUPPORT_LOG_SCHEMA_VERSION, "status": "ok"}
        if (
            doctor.get("status") == "needs_migration"
            and doctor.get("storage_backend") == "sqlite"
            and (int(doctor.get("document_count") or 0) > 0 or int(doctor.get("audit_event_count") or 0) > 0)
        ):
            return {
                "schema_version": SUPPORT_LOG_SCHEMA_VERSION,
                "status": "blocked",
                "reason": "data_migration_required_before_support_logging",
                "data_doctor": doctor,
            }
        migration = self.store.migrate()
        if migration.get("status") != "ok":
            return {
                "schema_version": SUPPORT_LOG_SCHEMA_VERSION,
                "status": "blocked",
                "reason": migration.get("reason") or "support_log_store_not_ready",
                "migration": migration,
            }
        return {"schema_version": SUPPORT_LOG_SCHEMA_VERSION, "status": "ok"}

    def _append_event(
        self,
        session_id: str,
        *,
        event_type: str,
        payload: dict[str, Any],
        sensitive_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _now_iso()
        event_base = {
            "schema_version": SUPPORT_LOG_SCHEMA_VERSION,
            "support_session_id": session_id,
            "event_type": event_type,
            "payload": _redact_sensitive_keys(payload),
            "topic_labels": sorted(set(classify_payload_topics(payload))),
            "payload_hash": payload_digest(_redact_sensitive_keys(payload)),
            "created_at": now,
        }
        if sensitive_evidence is not None:
            event_base["sensitive_evidence"] = _redact_sensitive_keys(sensitive_evidence)
            event_base["topic_labels"] = sorted(
                set(event_base["topic_labels"]) | set(sensitive_evidence.get("topic_labels") or [])
            )
        event = {
            "event_id": "support_event_" + _digest({**event_base, "nonce": uuid4().hex})[:16],
            **event_base,
        }
        self.store.append_audit_event(_events_stream(session_id), event)
        return event

    def _store_sensitive_evidence(
        self,
        *,
        session_id: str,
        kind: str,
        payload: dict[str, Any],
        source_event_type: str,
    ) -> dict[str, Any]:
        now = _now_iso()
        evidence_id = "support_evidence_" + _digest(
            {
                "session_id": session_id,
                "kind": kind,
                "payload_hash": payload_digest(payload),
                "at": now,
                "nonce": uuid4().hex,
            }
        )[:16]
        text_stats = text_fingerprints(payload)
        summary = {
            "schema_version": SUPPORT_EVIDENCE_SCHEMA_VERSION,
            "evidence_id": evidence_id,
            "kind": kind,
            "source_event_type": source_event_type,
            "payload_hash": payload_digest(payload),
            "topic_labels": classify_payload_topics(payload),
            "text_fingerprints": text_stats,
            "stored_at": now,
            "redaction": "encrypted_local_only",
            "sensitive": True,
        }
        document = {
            "schema_version": SUPPORT_EVIDENCE_SCHEMA_VERSION,
            "evidence_id": evidence_id,
            "support_session_id": session_id,
            "kind": kind,
            "source_event_type": source_event_type,
            "created_at": now,
            "summary": summary,
            "payload": payload,
        }
        self.store.upsert_document(f"support/{session_id}/evidence/{evidence_id}.json", document)
        return summary


def sensitive_export_confirm_token(session_id: str) -> str:
    return f"export-sensitive:{session_id}"


def redact_argv(argv: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for token in argv:
        if redact_next:
            redacted.append("[redacted]")
            redact_next = False
            continue
        matching_inline_flag = next(
            (flag for flag in COMMAND_VALUE_REDACT_FLAGS if token.startswith(f"{flag}=")),
            None,
        )
        if matching_inline_flag is not None:
            redacted.append(f"{matching_inline_flag}=[redacted]")
            continue
        redacted.append(token)
        if token in COMMAND_VALUE_REDACT_FLAGS:
            redact_next = True
    return redacted


def text_fingerprints(payload: Any) -> list[dict[str, Any]]:
    texts: list[tuple[str, str]] = []
    _collect_texts(payload, path="$", result=texts)
    stats = []
    for path, text in texts:
        if not text:
            continue
        stats.append(
            {
                "path": path,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "character_count": len(text),
                "topic_labels": classify_text_topics(text),
            }
        )
    return stats


def classify_payload_topics(payload: Any) -> list[str]:
    topics: set[str] = set()
    for _path, text in _all_strings(payload):
        topics.update(classify_text_topics(text))
    if isinstance(payload, dict):
        declared = payload.get("allowed_topics") or payload.get("topic_labels")
        if isinstance(declared, list):
            topics.update(str(item) for item in declared if str(item).strip())
    return sorted(topics)


def classify_text_topics(text: str) -> list[str]:
    normalized = text.lower()
    labels: set[str] = set()
    if any(marker in normalized for marker in ("dog", "puppy", "pet", "小狗", "狗", "宠物")):
        labels.add("dogs")
    if any(marker in normalized for marker in ("work", "job", "career", "company", "office")) or any(
        marker in text for marker in ("工作", "公司", "项目", "职业", "上班", "业务", "同事", "内测")
    ):
        labels.add("work")
    if any(marker in text for marker in ("微信", "wechat")):
        labels.add("wechat")
    if "tinder" in normalized:
        labels.add("tinder")
    return sorted(labels)


def context_source_manifest(context_pack: dict[str, Any]) -> dict[str, Any]:
    items = context_pack.get("items")
    if not isinstance(items, list):
        items = []
    sources = []
    topic_labels: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        redacted = _redact_sensitive_keys(item)
        topic_labels.update(classify_payload_topics(item))
        sources.append(
            {
                "index": index,
                "kind": item.get("kind"),
                "source_id": item.get("source_id") or item.get("id"),
                "payload_hash": payload_digest(redacted),
                "topic_labels": classify_payload_topics(item),
            }
        )
    return {
        "source_count": len(sources),
        "sources": sources,
        "topic_labels": sorted(topic_labels),
        "manifest_hash": payload_digest(sources),
    }


def _session_path(session_id: str) -> str:
    return f"support/{session_id}/session.json"


def _events_stream(session_id: str) -> str:
    return f"support/{session_id}/events.jsonl"


def _now_iso() -> str:
    import os

    return os.environ.get("DATING_BOOST_NOW") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _blocked(reason: str, **extra: Any) -> dict[str, Any]:
    return {"schema_version": SUPPORT_LOG_SCHEMA_VERSION, "status": "blocked", "reason": reason, **extra}


def _redact_sensitive_keys(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for item_key, item in value.items():
            if item_key in SENSITIVE_KEYS:
                if isinstance(item, str):
                    result.update(_redacted_string_fields(item_key, item))
                else:
                    result[f"{item_key}_hash"] = payload_digest(item)
                continue
            if isinstance(item, str) and not _string_is_safe(item_key, item):
                result.update(_redacted_string_fields(item_key, item))
                continue
            result[item_key] = _redact_sensitive_keys(item, key=item_key)
        return result
    if isinstance(value, list):
        if key in SAFE_STRING_LIST_KEYS or (key is not None and key.endswith("_topic_labels")):
            return [item if isinstance(item, str) else _redact_sensitive_keys(item, key=key) for item in value]
        return [_redact_sensitive_keys(item, key=key) for item in value]
    if isinstance(value, str) and not _string_is_safe(key, value):
        return {
            "value_hash": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "value_character_count": len(value),
            "value_topic_labels": classify_text_topics(value),
        }
    return value


def _redacted_string_fields(key: str, value: str) -> dict[str, Any]:
    return {
        f"{key}_hash": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        f"{key}_character_count": len(value),
        f"{key}_topic_labels": classify_text_topics(value),
    }


def _string_is_safe(key: str | None, value: str) -> bool:
    if key in SAFE_STRING_KEYS:
        return True
    if key == "path" and value.startswith("$"):
        return True
    if key and key.endswith(SAFE_STRING_SUFFIXES):
        return True
    return False


def _collect_texts(value: Any, *, path: str, result: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _collect_texts(item, path=f"{path}.{key}", result=result)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _collect_texts(item, path=f"{path}[{index}]", result=result)
        return
    if isinstance(value, str):
        result.append((path, value))


def _all_strings(value: Any) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    _collect_texts(value, path="$", result=result)
    return result


def _digest(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _command_name(argv: list[str]) -> str:
    if not argv:
        return ""
    command = []
    for token in argv:
        if token.startswith("-"):
            break
        command.append(token)
        if len(command) >= 3:
            break
    return " ".join(command)


def _normalize_support_owner(owner: dict[str, str] | None) -> dict[str, str] | None:
    if owner is None:
        return None
    if not isinstance(owner, dict):
        raise ValueError("support owner must be an object")
    qualification_id = owner.get("qualification_id")
    phase = owner.get("phase")
    if not isinstance(qualification_id, str) or not qualification_id.strip() or phase not in {"canary", "soak"}:
        raise ValueError("support owner invalid")
    return {"qualification_id": qualification_id, "phase": phase}


def _command_context_payload(context: dict[str, Any] | None) -> dict[str, Any]:
    if context is None:
        return {}
    return {
        key: context[key]
        for key in ("qualification_id", "phase", "attempt_id", "probe_id")
        if key in context
    }


def _tx_read_document(
    conn: sqlite3.Connection,
    store: ProductionDataStore,
    path: str,
) -> dict[str, Any] | None:
    row = conn.execute("SELECT payload_json FROM documents WHERE path = ?", (path,)).fetchone()
    if row is None:
        return None
    payload = store._decode_document(path, row["payload_json"])
    return payload if isinstance(payload, dict) else None


def _tx_write_document(
    conn: sqlite3.Connection,
    store: ProductionDataStore,
    path: str,
    payload: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO documents (path, schema_version, payload_json, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            schema_version = excluded.schema_version,
            payload_json = excluded.payload_json,
            updated_at = excluded.updated_at
        """,
        (
            path,
            payload.get("schema_version"),
            store._encode_document(path, payload),
            _now_iso(),
        ),
    )
