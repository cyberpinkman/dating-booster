from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from dating_boost.core.send_verification import hash_text, text_fingerprint_fields


@dataclass(frozen=True)
class SendAttemptContext:
    action: str
    target: str
    draft_text: str
    dry_run: bool
    planned_steps: tuple[dict[str, Any], ...]
    blocked_actions: tuple[str, ...]
    extra_fields: dict[str, Any] = field(default_factory=dict)
    live_send: bool = True
    requires_explicit_authorization: bool = True

    @property
    def mode(self) -> str:
        return "dry_run" if self.dry_run else "execute"

    @property
    def draft_fingerprint(self) -> str:
        return hash_text(self.draft_text)

    def initial_payload(self, base_payload: dict[str, Any]) -> dict[str, Any]:
        payload = {
            **base_payload,
            "action": self.action,
            "target": self.target,
            "mode": self.mode,
            "planned_steps": [dict(step) for step in self.planned_steps],
            "draft_fingerprint": self.draft_fingerprint,
            "draft_character_count": len(self.draft_text),
            **text_fingerprint_fields("draft_clipboard", self.draft_text),
            "blocked_actions": list(self.blocked_actions),
            "live_send": self.live_send,
            "requires_explicit_authorization": self.requires_explicit_authorization,
        }
        payload.update(copy.deepcopy(self.extra_fields))
        return payload


@dataclass(frozen=True)
class StagingResult:
    staged_text_verified: bool
    exact_text_verified: bool | None = None
    exact_text_ocr_verified: bool | None = None
    exact_text_ax_verified: bool | None = None
    exact_text_visual_verified: bool | None = None

    @classmethod
    def from_verification(
        cls,
        verification: dict[str, Any] | None,
        *,
        staged_text_verified: bool,
    ) -> "StagingResult":
        payload = verification if isinstance(verification, dict) else {}
        exact_text_verified = payload.get("exact_text_verified")
        exact_text_ocr_verified = payload.get("exact_text_ocr_verified")
        exact_text_ax_verified = payload.get("exact_text_ax_verified")
        exact_text_visual_verified = payload.get("exact_text_visual_verified")
        return cls(
            staged_text_verified=staged_text_verified,
            exact_text_verified=bool(exact_text_verified) if exact_text_verified is not None else None,
            exact_text_ocr_verified=bool(exact_text_ocr_verified) if exact_text_ocr_verified is not None else None,
            exact_text_ax_verified=bool(exact_text_ax_verified) if exact_text_ax_verified is not None else None,
            exact_text_visual_verified=bool(exact_text_visual_verified) if exact_text_visual_verified is not None else None,
        )


@dataclass(frozen=True)
class PostSendVerification:
    post_action_observation_id: str
    input_cleared_after_send: bool
    post_action_screen_captured: bool
    outbound_message_verified: bool


@dataclass(frozen=True)
class EvidencePayload:
    staging: StagingResult
    post_send: PostSendVerification
    send_input_backend: Any
    extra_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "staged_text_verified": self.staging.staged_text_verified,
            "send_input_backend": self.send_input_backend,
            "input_cleared_after_send": self.post_send.input_cleared_after_send,
            "post_action_screen_captured": self.post_send.post_action_screen_captured,
            "outbound_message_verified": self.post_send.outbound_message_verified,
        }
        if self.staging.exact_text_verified is not None:
            payload["staged_exact_text_verified"] = self.staging.exact_text_verified
        if self.staging.exact_text_ocr_verified is not None:
            payload["staged_exact_text_ocr_verified"] = self.staging.exact_text_ocr_verified
        if self.staging.exact_text_ax_verified is not None:
            payload["staged_exact_text_ax_verified"] = self.staging.exact_text_ax_verified
        if self.staging.exact_text_visual_verified is not None:
            payload["staged_exact_text_visual_verified"] = self.staging.exact_text_visual_verified
        payload.update(copy.deepcopy(self.extra_fields))
        payload["post_action_observation_id"] = self.post_send.post_action_observation_id
        return payload
