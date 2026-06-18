from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.core.storage import JsonStorage


DRAFT_GENERATION_AUDIT_SCHEMA_VERSION = 1


class DraftGenerationAuditRepository:
    def __init__(self, root: Path):
        self._storage = JsonStorage(root)

    def append_generation(
        self,
        *,
        generation_id: str,
        evidence_id: str,
        prompt_id: str,
        status: str,
        primary_reason: str | None,
        prompt_hash: str,
        context_hash: str,
        draft_hash: str | None,
        attempt_count: int,
        self_review_attempts: list[dict[str, Any]],
        created_at: str,
    ) -> dict[str, Any]:
        event = {
            "schema_version": DRAFT_GENERATION_AUDIT_SCHEMA_VERSION,
            "generation_id": generation_id,
            "evidence_id": evidence_id,
            "prompt_id": prompt_id,
            "status": status,
            "primary_reason": primary_reason,
            "prompt_hash": prompt_hash,
            "context_hash": context_hash,
            "draft_hash": draft_hash,
            "attempt_count": attempt_count,
            "self_review_attempts": [
                {
                    "ai_or_weird_probability": int(item.get("ai_or_weird_probability") or 0),
                    "reason": str(item.get("reason") or ""),
                    "supplemental_prompt_hash": str(item.get("supplemental_prompt_hash") or ""),
                }
                for item in self_review_attempts
            ],
            "created_at": created_at,
        }
        self._storage.append_jsonl(Path("audit") / "draft_generations.jsonl", event)
        return event

    def generation_block_reason(self, generation_id: str, *, evidence_id: str | None = None) -> str | None:
        events = self._storage.read_jsonl(Path("audit") / "draft_generations.jsonl")
        matched = None
        for event in events:
            if event.get("generation_id") == generation_id:
                matched = event
        if matched is None:
            return "draft_generation_audit_not_found"
        if evidence_id is not None and matched.get("evidence_id") != evidence_id:
            return "draft_generation_evidence_mismatch"
        if matched.get("status") != "ok":
            return "draft_generation_not_allowed"
        return None
