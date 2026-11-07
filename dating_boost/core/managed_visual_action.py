"""ManagedRun's visual conversation proof and fast, guarded composer IO.

The vision model interprets screenshots. Code owns sequencing, exact payload
comparison, freshness, checkpoints and authorization. AX is used for the input
control, never as a prerequisite for reading conversation bubbles.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from dating_boost.apps.tashuo.managed_send_evidence import ManagedSendEvidenceStore
from dating_boost.apps.tashuo.managed_visual_evidence import ManagedVisualVerifier, VisualFrame, VisualTransition, same_body
from dating_boost.apps.tashuo.managed_rendered_verification import (
    ManagedRenderedVerifier, accepted_rendered_verification, rendered_verification_applicable,
)
from dating_boost.core.managed_run import (
    ClickReceipt, ComposerObservation, ManagedActionError, ManagedClickBlocked,
    PostSendObservation, ThreadCandidate,
)
from dating_boost.core.safety import SafetyRepository


@dataclass
class _ThreadState:
    identity_digest: str
    bound_revision: str
    frame: VisualFrame
    staged_text: str = ""


@dataclass(frozen=True)
class _Receipt:
    candidate_key: str
    before: VisualFrame
    text: str
    clicked_at: str


class TaShuoVisualManagedActionPort:
    def __init__(
        self, root: Path, *, io: Any, verifier: ManagedVisualVerifier,
        sleeper: Callable[[float], None] = time.sleep,
        evidence_store: ManagedSendEvidenceStore | None = None,
        rendered_verifier: ManagedRenderedVerifier | None = None,
    ):
        self.io = io
        self.verifier = verifier
        self.safety = SafetyRepository(root)
        self.sleeper = sleeper
        self.evidence_store = evidence_store or ManagedSendEvidenceStore(root)
        self.rendered_verifier = rendered_verifier
        self._threads: dict[str, _ThreadState] = {}
        self._receipts: dict[str, _Receipt] = {}
        self._metrics: dict[str, float | int] = {}

    def bind_thread(self, binding: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
        """Reuse the exact immutable screenshot already interpreted for drafting."""
        key = raw.get("candidate_key")
        if not isinstance(key, str) or not key:
            raise ManagedActionError("managed_visual_candidate_missing")
        frame = self._frame(raw.get("managed_visual_frame"))
        revision = "visual-frame-v1:" + frame.file_digest
        self._threads[key] = _ThreadState(_identity_digest(binding), revision, frame)
        return {
            "status": "ok", "inbound_revision": revision,
            "inbound_revision_observation_id": frame.frame_id,
            "inbound_revision_captured_at": frame.captured_at,
            "evidence_source": "visible_conversation_screenshot",
        }

    def observe_composer(self, candidate: ThreadCandidate) -> ComposerObservation:
        state = self._state(candidate)
        fresh = self._unchanged(state.frame, self._capture())
        observed = self.io.read_composer()
        self._require_ok(observed, "managed_composer_observation_failed")
        state.frame = fresh
        return self._composer(candidate, str(observed.get("value") or ""), fresh)

    def restore_prepared(self, candidate: ThreadCandidate, text: str) -> ComposerObservation:
        """Rebind a durable single-message draft after fresh, read-only verification."""
        self._require_unpaused()
        observed = self.observe_composer(candidate)
        if text and observed.text == text:
            self._state(candidate).staged_text = text
        return observed

    def stage_text(self, candidate: ThreadCandidate, text: str) -> ComposerObservation:
        self._require_unpaused()
        state = self._state(candidate)
        # Focus may expand the composer, but never writes text. Verify the
        # resulting target and conversation once before the atomic write.
        self._require_ok(self.io.prepare_composer(), "managed_composer_prepare_failed")
        # Expanding an input can move the messages. Prove that transition once;
        # normal same-layout steps reuse their interpretation by exact pixels.
        focused = self._unchanged(state.frame, self._capture())
        attempted_stage = False
        try:
            attempted_stage = True
            result = self.io.stage_text(text)
            if isinstance(result, dict) and result.get("reason") == "candidate_composer_occupied":
                attempted_stage = False
            self._require_ok(result, "managed_stage_failed")
            if result.get("staged_exact_text_verified") is not True:
                raise ManagedActionError("managed_staged_exact_text_not_verified")
            # IO already performed the guarded write and exact AX readback.
            # Its completion time belongs to the composer proof; the earlier
            # immutable screenshot keeps its original capture time.
            staged_at = result.get("captured_at", focused.captured_at)
            try:
                if not isinstance(staged_at, str) or _instant(staged_at) < _instant(focused.captured_at):
                    raise ValueError
            except (TypeError, ValueError):
                raise ManagedActionError("managed_stage_observation_time_invalid") from None
        except Exception:
            if attempted_stage:
                self._pause_for_unresolved_draft()
            raise
        # A change after staging is checked against this baseline by the fresh
        # visual and exact-composer checks immediately before the sole Return.
        state.frame = focused
        state.staged_text = text
        return self._composer(candidate, text, focused, captured_at=staged_at)

    def click_send(self, candidate: ThreadCandidate) -> ClickReceipt:
        # Every exception in this preflight is known to precede Return. The
        # actual IO call below is outside this exception conversion boundary.
        try:
            self._require_unpaused()
            state = self._state(candidate)
            if not state.staged_text:
                raise ManagedActionError("managed_expected_composer_text_missing")
            self._require_ok(
                self.io.prepare_composer(expected_text=state.staged_text), "managed_composer_focus_failed",
            )
            before = self._unchanged(state.frame, self._capture())
            evidence_id = self._evidence_call(lambda: self.evidence_store.prepare(
                target_id=candidate.target_id, candidate_key=candidate.candidate_key,
                target_binding=candidate.target_binding, inbound_revision=str(candidate.inbound_revision),
                payload_hash=hashlib.sha256(state.staged_text.encode("utf-8")).hexdigest(), before=before,
            ))
        except Exception as exc:
            self._pause_for_unresolved_draft()
            code = exc.reason_code if isinstance(exc, ManagedActionError) else "managed_visual_pre_click_failed"
            raise ManagedClickBlocked(code) from exc
        result = self.io.click_return(
            state.staged_text, deadline_at=candidate.metadata.get("managed_burst_click_deadline_at"),
        )
        if isinstance(result, dict) and result.get("status") == "blocked":
            self._pause_for_unresolved_draft()
            raise ManagedClickBlocked(result.get("reason"), fallback_reason="managed_click_not_performed")
        receipt_id = result.get("receipt_id") if isinstance(result, dict) else None
        clicked_at = result.get("clicked_at") if isinstance(result, dict) else None
        if not isinstance(receipt_id, str) or not receipt_id or not isinstance(clicked_at, str) or not clicked_at:
            self._require_ok(result, "managed_return_result_unknown")
            raise ManagedActionError("managed_click_receipt_incomplete")
        self._evidence_call(lambda: self.evidence_store.record_click(
            evidence_id, receipt_id=receipt_id, clicked_at=clicked_at,
        ))
        self._require_ok(result, "managed_return_result_unknown")
        self._receipts[receipt_id] = _Receipt(candidate.candidate_key, before, state.staged_text, clicked_at)
        return ClickReceipt(receipt_id=receipt_id, clicked_at=clicked_at)

    def observe_post_send(self, candidate: ThreadCandidate, receipt: ClickReceipt) -> PostSendObservation:
        state = self._state(candidate)
        proof = self._receipts.get(receipt.receipt_id)
        if proof is None or proof.candidate_key != candidate.candidate_key or proof.clicked_at != receipt.clicked_at:
            raise ManagedActionError("managed_click_receipt_evidence_missing")
        after = self._capture()
        # Brief UI settlement is observation only: no model retry and no second
        # Return. Usually the first capture already contains the new bubble.
        for _ in range(3):
            if not self._same_body(proof.before, after):
                break
            self.sleeper(0.1)
            after = self._capture()
        if _instant(after.captured_at) <= _instant(proof.clicked_at):
            raise ManagedActionError("managed_post_send_capture_not_fresh")
        # Save source pixels before reading the composer or asking a model. A
        # timeout or mismatched transcription must not discard recoverable proof.
        self._evidence_call(lambda: self.evidence_store.record_after(receipt.receipt_id, after))
        composer = self.io.read_composer()
        self._evidence_call(lambda: self.evidence_store.record_after(
            receipt.receipt_id, after, composer=composer,
        ))
        self._require_changed_outbound_body(proof.before, after)
        transition = self._compare(proof.before, after)
        self._evidence_call(lambda: self.evidence_store.record_after(
            receipt.receipt_id, after, transition=transition,
        ))
        # A missing AX input after Return can be a collapsed composer. The same
        # post-send image can prove it is empty without requiring hidden AX UI.
        input_cleared = (
            composer.get("value") == "" if isinstance(composer, dict) and composer.get("status") == "ok"
            else transition.composer_state == "empty"
        )
        if not input_cleared or not self._outbound_verified(
            proof.text, proof.before, after, transition, receipt_id=receipt.receipt_id,
        ):
            raise ManagedActionError("managed_visual_outbound_not_verified")
        continuation = len(transition.added_bubbles) == 1
        state.frame = after
        state.staged_text = ""
        return PostSendObservation(
            observation_id=after.frame_id, receipt_id=receipt.receipt_id,
            target_id=candidate.target_id, target_binding=candidate.target_binding,
            captured_at=after.captured_at, input_cleared=True, outbound_text=proof.text,
            continuation_verified=continuation,
        )

    def recover_send(self, attempt: Mapping[str, Any]) -> PostSendObservation:
        """Verify saved evidence only; never reopen a thread, stage, or click."""
        proof = self._evidence_call(lambda: self.evidence_store.load_for_attempt(attempt))
        self._require_changed_outbound_body(proof.before, proof.after)
        transition = proof.transition or self._compare(proof.before, proof.after)
        if proof.transition is None:
            self._evidence_call(lambda: self.evidence_store.record_after(
                proof.receipt_id, proof.after, transition=transition,
            ))
        input_cleared = (
            proof.composer["input_cleared"] if proof.composer is not None and proof.composer["available"]
            else transition.composer_state == "empty"
        )
        text = attempt["exact_text"]
        if not input_cleared or not self._outbound_verified(
            text, proof.before, proof.after, transition, receipt_id=proof.receipt_id,
        ):
            raise ManagedActionError("managed_visual_outbound_not_verified")
        # Include any newly recorded interpretation or rendered-content proof
        # in the recovery digest; also recheck immutable source files after it.
        proof = self._evidence_call(lambda: self.evidence_store.load_for_attempt(attempt))
        return PostSendObservation(
            observation_id=proof.after.frame_id, receipt_id=proof.receipt_id,
            target_id=attempt["target_id"], target_binding=attempt["target_binding"],
            captured_at=proof.after.captured_at, input_cleared=True, outbound_text=text,
            continuation_verified=False, recovery_evidence_digest=proof.manifest_digest,
        )

    def _outbound_verified(
        self, text: str, before: VisualFrame, after: VisualFrame, transition: VisualTransition,
        *, receipt_id: str,
    ) -> bool:
        before.assert_unchanged()
        after.assert_unchanged()
        if transition.confirms_outbound(text):
            return True
        if not rendered_verification_applicable(text, transition):
            return False
        previous = self._evidence_call(lambda: self.evidence_store.begin_rendered_verification(receipt_id))
        if previous is not None:
            self._metrics["rendered_proof_reuses"] = int(self._metrics.get("rendered_proof_reuses", 0)) + 1
            return previous.get("status") == "complete" and accepted_rendered_verification(previous.get("result"))
        started = time.monotonic()
        self._metrics["rendered_visual_requests"] = int(self._metrics.get("rendered_visual_requests", 0)) + 1
        try:
            if self.rendered_verifier is None:
                self.rendered_verifier = ManagedRenderedVerifier(self.verifier.backend)
            result = self.rendered_verifier.compare(before, after)
        except Exception:
            self._evidence_call(lambda: self.evidence_store.finish_rendered_verification(
                receipt_id, None, error_code="managed_rendered_comparison_failed",
            ))
            raise ManagedActionError("managed_rendered_comparison_failed") from None
        finally:
            self._metrics["rendered_visual_ms"] = round(
                float(self._metrics.get("rendered_visual_ms", 0.0)) + (time.monotonic() - started) * 1000, 3,
            )
        self._evidence_call(lambda: self.evidence_store.finish_rendered_verification(receipt_id, result))
        before.assert_unchanged()
        after.assert_unchanged()
        return accepted_rendered_verification(result)

    @staticmethod
    def _evidence_call(operation: Callable[[], Any]) -> Any:
        try:
            return operation()
        except Exception as exc:
            raise ManagedActionError(
                str(exc) if isinstance(exc, ValueError) else None,
                fallback_reason="managed_send_evidence_persistence_failed",
            ) from exc

    def drain_metrics(self) -> dict[str, float | int]:
        result, self._metrics = self._metrics, {}
        return result

    def _unchanged(self, before: VisualFrame, after: VisualFrame) -> VisualFrame:
        if self._same_body(before, after):
            self._metrics["pixel_reuses"] = int(self._metrics.get("pixel_reuses", 0)) + 1
            return after
        transition = self._compare(before, after)
        if not transition.unchanged:
            raise ManagedActionError("managed_visual_conversation_changed")
        # A model response does not refresh the time of its input screenshot.
        # Recheck local pixels after model latency before permitting a mutation.
        current = self._capture()
        if not self._same_body(after, current):
            raise ManagedActionError("managed_visual_changed_during_verification")
        return current

    def _compare(self, before: VisualFrame, after: VisualFrame) -> Any:
        started = time.monotonic()
        self._metrics["visual_requests"] = int(self._metrics.get("visual_requests", 0)) + 1
        try:
            return self.verifier.compare(before, after)
        except Exception as exc:
            raise ManagedActionError("managed_visual_evidence_unavailable") from exc
        finally:
            self._metrics["visual_ms"] = round(float(self._metrics.get("visual_ms", 0.0)) + (time.monotonic() - started) * 1000, 3)

    def _require_changed_outbound_body(self, before: VisualFrame, after: VisualFrame) -> None:
        if self._same_body(before, after):
            raise ManagedActionError("managed_visual_outbound_not_verified")

    def _same_body(self, before: VisualFrame, after: VisualFrame) -> bool:
        try:
            return same_body(before, after)
        except ValueError as exc:
            raise ManagedActionError("managed_visual_frame_invalid") from exc

    def _capture(self) -> VisualFrame:
        self._metrics["captures"] = int(self._metrics.get("captures", 0)) + 1
        payload = self.io.capture()
        self._require_ok(payload, "managed_visual_capture_failed")
        return self._frame(payload)

    @staticmethod
    def _frame(payload: Any) -> VisualFrame:
        try:
            return VisualFrame.from_payload(payload)
        except Exception as exc:
            raise ManagedActionError("managed_visual_frame_invalid") from exc

    def _state(self, candidate: ThreadCandidate) -> _ThreadState:
        state = self._threads.get(candidate.candidate_key)
        binding = candidate.metadata.get("verified_target_binding")
        if state is None or not isinstance(binding, dict) or _identity_digest(binding) != state.identity_digest:
            raise ManagedActionError("managed_visual_target_evidence_missing")
        evidence = binding.get("thread_evidence")
        if not isinstance(evidence, dict) or evidence.get("managed_inbound_revision") != state.bound_revision:
            raise ManagedActionError("managed_visual_target_evidence_stale")
        if not candidate.inbound_revision or candidate.metadata.get("verified_inbound_revision") != candidate.inbound_revision:
            raise ManagedActionError("managed_authoritative_inbound_revision_missing")
        return state

    @staticmethod
    def _composer(
        candidate: ThreadCandidate, text: str, frame: VisualFrame, *, captured_at: str | None = None,
    ) -> ComposerObservation:
        return ComposerObservation(
            target_id=candidate.target_id, target_binding=candidate.target_binding,
            inbound_revision=str(candidate.inbound_revision), text=text, captured_at=captured_at or frame.captured_at,
        )

    @staticmethod
    def _require_ok(payload: Any, fallback: str) -> None:
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            raise ManagedActionError(payload.get("reason") if isinstance(payload, dict) else None, fallback_reason=fallback)

    def _require_unpaused(self) -> None:
        if self.safety.is_paused():
            raise ManagedActionError("global_safety_paused")

    def _pause_for_unresolved_draft(self) -> None:
        if self.safety.is_paused():
            return
        self.safety.pause(
            reason="managed_visual_staged_draft_requires_review",
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )


def _identity_digest(binding: dict[str, Any]) -> str:
    evidence = binding.get("thread_evidence")
    identity = {
        **binding,
        "thread_evidence": {k: v for k, v in evidence.items() if not k.startswith("managed_")} if isinstance(evidence, dict) else {},
    }
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("managed_visual_timestamp_invalid")
    return parsed
