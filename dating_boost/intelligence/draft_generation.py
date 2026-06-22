from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dating_boost.core.draft_evidence import DraftEvidencePack
from dating_boost.core.draft_generation_audit import DraftGenerationAuditRepository
from dating_boost.intelligence.backends import ModelBackend
from dating_boost.intelligence.draft_prompt import DraftGenerationPrompt, build_draft_generation_prompt
from dating_boost.intelligence.prompts import REPLY_SCHEMA
from dating_boost.intelligence.reply_generator import DraftResponse, normalize_draft_payload, parse_draft_response


DRAFT_SELF_REVIEW_SCHEMA_VERSION = 1
DRAFT_SELF_REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "ai_or_weird_probability",
        "reason",
        "supplemental_prompt",
    ],
    "properties": {
        "ai_or_weird_probability": {"type": "integer", "minimum": 0, "maximum": 100},
        "reason": {"type": "string"},
        "supplemental_prompt": {"type": "string"},
    },
}


@dataclass(frozen=True)
class DraftGenerationResult:
    schema_version: int
    status: str
    generation_id: str
    evidence_id: str
    primary_reason: str | None
    draft: DraftResponse | None
    draft_payload: dict[str, Any] | None
    prompt: DraftGenerationPrompt
    attempt_count: int
    self_review_attempts: list[dict[str, Any]]
    audit_event: dict[str, Any] | None

    def summary(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "generation_id": self.generation_id,
            "evidence_id": self.evidence_id,
            "primary_reason": self.primary_reason,
            "attempt_count": self.attempt_count,
            "prompt_id": self.prompt.prompt_id,
            "prompt_hash": _digest(self.prompt.user_prompt),
            "draft_hash": _digest(self.draft_payload) if self.draft_payload else None,
            "self_review_attempts": [
                {
                    "ai_or_weird_probability": item["ai_or_weird_probability"],
                    "reason": item["reason"],
                    "supplemental_prompt_hash": item.get("supplemental_prompt_hash"),
                }
                for item in self.self_review_attempts
            ],
        }


def generate_reply_with_refinement(
    evidence_pack: DraftEvidencePack,
    *,
    backend: ModelBackend,
    audit_root: Path | None,
    supplemental_prompts: list[str] | None = None,
    threshold: int = 40,
    max_attempts: int = 3,
) -> DraftGenerationResult:
    if evidence_pack.status != "ok":
        prompt = build_draft_generation_prompt(evidence_pack, supplemental_prompts=supplemental_prompts)
        return _result(
            evidence_pack=evidence_pack,
            prompt=prompt,
            status="blocked",
            reason=evidence_pack.primary_reason or "draft_evidence_blocked",
            draft=None,
            draft_payload=None,
            attempts=[],
            audit_root=audit_root,
        )

    active_supplemental_prompts: list[str] = [str(item) for item in (supplemental_prompts or []) if str(item).strip()]
    attempts: list[dict[str, Any]] = []
    last_prompt = build_draft_generation_prompt(evidence_pack)
    last_draft: DraftResponse | None = None
    last_payload: dict[str, Any] | None = None

    for _attempt_index in range(1, max_attempts + 1):
        last_prompt = build_draft_generation_prompt(
            evidence_pack,
            supplemental_prompts=active_supplemental_prompts,
        )
        last_payload = backend.generate_structured(
            system_prompt=last_prompt.system_prompt,
            user_prompt=last_prompt.user_prompt,
            schema=REPLY_SCHEMA,
        )
        last_payload = normalize_draft_payload(last_payload)
        last_draft = parse_draft_response(last_payload)
        self_review = _parse_self_review(
            backend.generate_structured(
                system_prompt=_self_review_system_prompt(),
                user_prompt=_self_review_user_prompt(
                    evidence_pack=evidence_pack,
                    prompt=last_prompt,
                    draft_payload=last_payload,
                ),
                schema=DRAFT_SELF_REVIEW_SCHEMA,
            )
        )
        attempts.append(self_review)
        if self_review["ai_or_weird_probability"] <= threshold:
            return _result(
                evidence_pack=evidence_pack,
                prompt=last_prompt,
                status="ok",
                reason=None,
                draft=last_draft,
                draft_payload=dict(last_payload),
                attempts=attempts,
                audit_root=audit_root,
            )
        supplemental = str(self_review.get("supplemental_prompt") or "").strip()
        active_supplemental_prompts.append(
            supplemental
            or "Rewrite to sound like a real private-chat message: shorter, more grounded in the latest inbound turn, and less like a summary."
        )

    return _result(
        evidence_pack=evidence_pack,
        prompt=last_prompt,
        status="blocked",
        reason="draft_refinement_exhausted",
        draft=None,
        draft_payload=None,
        attempts=attempts,
        audit_root=audit_root,
    )


def _result(
    *,
    evidence_pack: DraftEvidencePack,
    prompt: DraftGenerationPrompt,
    status: str,
    reason: str | None,
    draft: DraftResponse | None,
    draft_payload: dict[str, Any] | None,
    attempts: list[dict[str, Any]],
    audit_root: Path | None,
) -> DraftGenerationResult:
    generation_id = f"draft_generation_{_digest({'evidence_id': evidence_pack.evidence_id, 'prompt_id': prompt.prompt_id, 'status': status, 'attempts': attempts})[:16]}"
    audit_event = None
    if audit_root is not None:
        audit_event = DraftGenerationAuditRepository(audit_root).append_generation(
            generation_id=generation_id,
            evidence_id=evidence_pack.evidence_id,
            prompt_id=prompt.prompt_id,
            status=status,
            primary_reason=reason,
            prompt_hash=_digest(prompt.user_prompt),
            context_hash=_digest(evidence_pack.context_pack),
            draft_hash=_digest(draft_payload) if draft_payload is not None else None,
            attempt_count=len(attempts),
            self_review_attempts=attempts,
            created_at=_now_iso(),
        )
    return DraftGenerationResult(
        schema_version=1,
        status=status,
        generation_id=generation_id,
        evidence_id=evidence_pack.evidence_id,
        primary_reason=reason,
        draft=draft,
        draft_payload=draft_payload,
        prompt=prompt,
        attempt_count=len(attempts),
        self_review_attempts=attempts,
        audit_event=audit_event,
    )


def _parse_self_review(payload: dict[str, Any]) -> dict[str, Any]:
    raw_probability = payload.get("ai_or_weird_probability")
    if not isinstance(raw_probability, int) or isinstance(raw_probability, bool):
        raise ValueError("self review ai_or_weird_probability must be an integer from 0 to 100")
    if raw_probability < 0 or raw_probability > 100:
        raise ValueError("self review ai_or_weird_probability must be from 0 to 100")
    supplemental = str(payload.get("supplemental_prompt") or "")
    return {
        "ai_or_weird_probability": raw_probability,
        "reason": str(payload.get("reason") or ""),
        "supplemental_prompt": supplemental,
        "supplemental_prompt_hash": _digest(supplemental) if supplemental else None,
    }


def _self_review_system_prompt() -> str:
    return (
        "You review one draft for whether it would feel AI-generated or strange to a human recipient. "
        "Return a probability from 0 to 100. If probability is above 40, provide a concrete supplemental prompt "
        "for rewriting. Do not apply deterministic safety policy here."
    )


def _self_review_user_prompt(
    *,
    evidence_pack: DraftEvidencePack,
    prompt: DraftGenerationPrompt,
    draft_payload: dict[str, Any],
) -> str:
    return "\n\n".join(
        [
            "evidence_manifest_json:",
            json.dumps(evidence_pack.evidence_manifest, sort_keys=True, ensure_ascii=False),
            "generation_prompt_hash:",
            _digest(prompt.user_prompt),
            "draft_payload_json:",
            json.dumps(draft_payload, sort_keys=True, ensure_ascii=False),
        ]
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
