"""Append-only audit log for draft review decisions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from dating_boost.core.production_store import payload_digest
from dating_boost.core.support import classify_text_topics, context_source_manifest
from dating_boost.policy.draft_review import DraftReviewDecision


DRAFT_REVIEW_AUDIT_SCHEMA_VERSION = 1
DRAFT_REVIEW_AUDIT_PATH = Path("audit") / "draft_reviews.jsonl"


class DraftReviewAuditRepository:
    def __init__(self, root: Path):
        self.root = root

    def append_review(
        self,
        review: DraftReviewDecision,
        *,
        draft_payload: Mapping[str, Any],
        context_pack: Mapping[str, Any],
        mode: str,
        target_match_id: str | None = None,
    ) -> dict[str, Any]:
        path = self.root / DRAFT_REVIEW_AUDIT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        text = str(draft_payload.get("best_reply") or "")
        record = {
            "schema_version": DRAFT_REVIEW_AUDIT_SCHEMA_VERSION,
            "review_id": review.review_id,
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "mode": mode,
            "target_match_id": target_match_id or _target_from_context(context_pack),
            "payload_hash": review.payload_hash,
            "payload_format": review.payload_format,
            "message_count": review.message_count,
            "status": review.status,
            "allowed_for_display": review.allowed_for_display,
            "allowed_for_stage": review.allowed_for_stage,
            "allowed_for_managed_send": review.allowed_for_managed_send,
            "requires_user_confirmation": review.requires_user_confirmation,
            "primary_reason": review.primary_reason,
            "finding_codes": [finding.code for finding in review.findings],
            "findings": [finding.to_dict() for finding in review.findings],
            "revision_hint_count": len(review.revision_hints),
            "context_manifest": context_source_manifest(dict(context_pack)),
            "draft_payload_hash": payload_digest(dict(draft_payload)),
            "context_pack_hash": payload_digest(dict(context_pack)),
            "draft_topic_labels": classify_text_topics(text),
            "draft_character_count": len(text),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def find_review(self, review_id: str) -> dict[str, Any] | None:
        path = self.root / DRAFT_REVIEW_AUDIT_PATH
        if not path.exists():
            return None
        found: dict[str, Any] | None = None
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and record.get("review_id") == review_id:
                    found = record
        return found

    def managed_send_block_reason(
        self,
        review_id: str,
        *,
        payload_hash: str,
        target_match_id: str,
    ) -> str | None:
        record = self.find_review(review_id)
        if record is None:
            return "draft_review_audit_not_found"
        if record.get("mode") != "managed_live":
            return "draft_review_audit_not_managed_live"
        if record.get("allowed_for_managed_send") is not True:
            return "draft_review_audit_not_allowed"
        if record.get("payload_hash") != payload_hash:
            return "draft_review_audit_payload_hash_mismatch"
        recorded_target = str(record.get("target_match_id") or "").strip()
        if not recorded_target:
            return "draft_review_audit_target_missing"
        if recorded_target != target_match_id:
            return "draft_review_audit_target_mismatch"
        return None


def _target_from_context(context_pack: Mapping[str, Any]) -> str | None:
    value = context_pack.get("match_id")
    return str(value) if value else None
