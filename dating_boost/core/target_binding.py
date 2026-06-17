from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dating_boost.core.live_send_contract import target_binding_structural_evidence_present
from dating_boost.core.send_verification import hash_text


@dataclass(frozen=True)
class TargetBindingVerificationResult:
    verification_method: str
    target_match_id: Any
    candidate_key: Any
    status: str | None = None
    reason: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_binding(
        cls,
        *,
        verification_method: str,
        target_binding: dict[str, Any],
        fields: dict[str, Any] | None = None,
    ) -> "TargetBindingVerificationResult":
        return cls(
            verification_method=verification_method,
            target_match_id=target_binding.get("target_match_id"),
            candidate_key=target_binding.get("candidate_key"),
            fields=dict(fields or {}),
        )

    def with_status(self, status: str, reason: str | None = None) -> dict[str, Any]:
        payload = self.to_dict()
        payload["status"] = status
        if reason is not None:
            payload["reason"] = reason
        return payload

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "verification_method": self.verification_method,
            "target_match_id": self.target_match_id,
            "candidate_key": self.candidate_key,
            **self.fields,
        }
        if self.status is not None:
            payload["status"] = self.status
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


@dataclass(frozen=True)
class RowToThreadBindingSpec:
    app_id: str
    verification_method: str
    source_states: frozenset[str]
    conversation_state: str
    window_missing_reason: str
    blocked_state_reasons: dict[str, str] = field(default_factory=dict)
    visual_only_exact_verification_allowed: bool = False


def row_to_thread_base_result(
    target_binding: dict[str, Any],
    *,
    spec: RowToThreadBindingSpec,
) -> TargetBindingVerificationResult:
    selection_evidence = (
        target_binding.get("selection_evidence")
        if isinstance(target_binding.get("selection_evidence"), dict)
        else {}
    )
    return TargetBindingVerificationResult.from_binding(
        verification_method=spec.verification_method,
        target_binding=target_binding,
        fields={
            "binding_type": target_binding.get("binding_type"),
            "row_index": selection_evidence.get("row_index"),
            "source_state": selection_evidence.get("source_state"),
            "opened_state": selection_evidence.get("opened_state"),
            "target_scope": selection_evidence.get("target_scope"),
            "open_action": selection_evidence.get("open_action"),
            "requires_target_specific_marker": True,
            "requires_header_marker": False,
            "emoji_nickname_supported": True,
            "visual_only_exact_verification_allowed": spec.visual_only_exact_verification_allowed,
        },
    )


def validate_row_to_thread_structural_evidence(
    target_binding: dict[str, Any],
    *,
    spec: RowToThreadBindingSpec,
    base: TargetBindingVerificationResult | None = None,
) -> dict[str, Any] | None:
    result = base or row_to_thread_base_result(target_binding, spec=spec)
    selection_evidence = (
        target_binding.get("selection_evidence")
        if isinstance(target_binding.get("selection_evidence"), dict)
        else {}
    )
    if not target_binding_structural_evidence_present(spec.app_id, target_binding):
        return result.with_status("blocked", "target_binding_structural_evidence_required")
    if selection_evidence.get("source_state") not in spec.source_states:
        return result.with_status("blocked", "target_binding_source_state_mismatch")
    if selection_evidence.get("opened_state") != spec.conversation_state:
        return result.with_status("blocked", "target_binding_opened_state_mismatch")
    if selection_evidence.get("open_action") != "open-conversation":
        return result.with_status("blocked", "target_binding_open_action_mismatch")
    target_scope = selection_evidence.get("target_scope")
    if target_scope not in {None, "ordinary_conversation", "existing_conversation"}:
        return result.with_status("blocked", "target_binding_scope_not_ordinary_conversation")
    return None


def finish_row_to_thread_screen_verification(
    base: TargetBindingVerificationResult,
    *,
    screen: dict[str, Any],
    redacted_screen: dict[str, Any],
    observed_text: str,
    spec: RowToThreadBindingSpec,
) -> dict[str, Any]:
    result = TargetBindingVerificationResult(
        verification_method=base.verification_method,
        target_match_id=base.target_match_id,
        candidate_key=base.candidate_key,
        fields={
            **base.fields,
            "screen": redacted_screen,
            "screen_state": screen.get("state", "unknown"),
            "observed_text_hash": hash_text(observed_text) if observed_text else None,
        },
    )
    if screen.get("status") != "ok":
        return result.with_status("blocked", "target_binding_screen_capture_failed")
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return result.with_status("blocked", str(screen.get("state")))
    blocked_reason = spec.blocked_state_reasons.get(str(screen.get("state") or ""))
    if blocked_reason:
        return result.with_status("blocked", blocked_reason)
    if screen.get("state") != spec.conversation_state:
        return result.with_status("blocked", "target_binding_chat_not_verified")
    return result.with_status("ok")
