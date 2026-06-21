from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from dating_boost.core.managed_session import ManagedSessionRepository
from dating_boost.core.operator import OperatorRepository
from dating_boost.core.standalone_actions import StandaloneActionExecutor
from dating_boost.core.standalone_observation import StandaloneObservationProvider


STANDALONE_RUNTIME_SCHEMA_VERSION = 1


class StandaloneAgentRuntime:
    def __init__(
        self,
        root: Path,
        *,
        observation_provider: StandaloneObservationProvider,
        harness_factory: Callable[..., Any] | None = None,
        action_executor: StandaloneActionExecutor | None = None,
        draft_planner: "StandaloneDraftPlanner | None" = None,
    ):
        self.root = root
        self.observation_provider = observation_provider
        self.action_executor = action_executor
        self.draft_planner = draft_planner
        self.managed = ManagedSessionRepository(root, harness_factory=harness_factory)
        self.operator = OperatorRepository(root)

    def tick(self) -> dict[str, Any]:
        managed_payload = self.managed.tick()
        if managed_payload.get("status") != "host_work_required":
            if managed_payload.get("status") == "no_work":
                continuation = self._consume_operator_continuation(managed_payload=managed_payload)
                if continuation is not None:
                    return continuation
            return {
                "schema_version": STANDALONE_RUNTIME_SCHEMA_VERSION,
                "status": str(managed_payload.get("status") or "unknown"),
                "managed_session": managed_payload,
            }

        work_item = managed_payload.get("work_item")
        if not isinstance(work_item, dict):
            return {
                "schema_version": STANDALONE_RUNTIME_SCHEMA_VERSION,
                "status": "blocked",
                "reason": "managed_session_missing_work_item",
            }
        return self.consume_work_item(work_item, managed_payload=managed_payload)

    def _consume_operator_continuation(self, *, managed_payload: dict[str, Any]) -> dict[str, Any] | None:
        state = self.operator.get_state_payload()
        operator_session = state.get("operator_session") if isinstance(state.get("operator_session"), dict) else {}
        if operator_session.get("status") != "active":
            return None
        has_continuation = (
            isinstance(operator_session.get("current_work_item"), dict)
            or isinstance(state.get("pending_scan_batch"), dict)
            or bool(state.get("work_queue"))
        )
        if not has_continuation:
            return None
        operator_payload = self.operator.next_work_item()
        work_item = operator_payload.get("work_item") if isinstance(operator_payload, dict) else None
        if not isinstance(work_item, dict):
            return None
        work_type = str(work_item.get("work_item_type") or "")
        if work_type in {"wait", "scheduled_wait"}:
            return None
        app_id = managed_payload.get("app_id") or operator_session.get("app_id")
        return self.consume_work_item(
            work_item,
            managed_payload={
                "schema_version": STANDALONE_RUNTIME_SCHEMA_VERSION,
                "status": "host_work_required",
                "app_id": app_id,
                "operator": operator_payload,
                "managed_session": managed_payload,
            },
        )

    def consume_work_item(self, work_item: dict[str, Any], *, managed_payload: dict[str, Any]) -> dict[str, Any]:
        app_id = managed_payload.get("app_id") or work_item.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            return _blocked("invalid_app_id", work_item=work_item)
        app_id = app_id.strip()
        work_type = str(work_item.get("work_item_type") or "")
        if work_type == "scan_message_list":
            scan_cursor = work_item.get("scan_cursor")
            if scan_cursor is None:
                scan_cursor = {}
            if not isinstance(scan_cursor, dict):
                return _blocked("invalid_scan_cursor", work_item=work_item, work_item_type=work_type)
            return self._consume_observation(
                work_type,
                work_item,
                self.observation_provider.observe_message_list,
                app_id=app_id,
                scan_cursor=scan_cursor,
            )

        if work_type == "open_thread":
            candidate_key = work_item.get("candidate_key")
            if not isinstance(candidate_key, str) or not candidate_key.strip():
                return _blocked("invalid_candidate_key", work_item=work_item, work_item_type=work_type)
            return self._consume_observation(
                work_type,
                work_item,
                self.observation_provider.observe_thread,
                app_id=app_id,
                candidate_key=candidate_key,
            )

        if work_type == "observe_current_thread":
            return self._consume_observation(
                work_type,
                work_item,
                self.observation_provider.observe_current_thread,
                app_id=app_id,
            )

        if work_type in {"wait", "scheduled_wait"}:
            return {
                "schema_version": STANDALONE_RUNTIME_SCHEMA_VERSION,
                "status": "no_work",
                "work_item_type": work_type,
                "work_item": work_item,
            }

        if work_type in {"blocked", "handoff"}:
            return {
                "schema_version": STANDALONE_RUNTIME_SCHEMA_VERSION,
                "status": work_type,
                "work_item_type": work_type,
                "work_item": work_item,
            }

        if work_type == "send_message":
            if self.action_executor is not None:
                try:
                    return self.action_executor.execute(work_item, app_id=app_id)
                except Exception as exc:  # noqa: BLE001 - injected executors must not crash the runtime loop.
                    return _blocked(
                        "action_executor_failed",
                        work_item=work_item,
                        work_item_type=work_type,
                        error_type=type(exc).__name__,
                    )
            return {
                "schema_version": STANDALONE_RUNTIME_SCHEMA_VERSION,
                "status": "needs_action_executor",
                "work_item_type": work_type,
                "work_item": work_item,
                "next_step": "configure_standalone_action_executor",
            }

        return {
            "schema_version": STANDALONE_RUNTIME_SCHEMA_VERSION,
            "status": "blocked",
            "reason": f"unsupported_work_item_type:{work_type}",
            "work_item": work_item,
        }

    def _consume_observation(
        self,
        work_type: str,
        work_item: dict[str, Any],
        observe: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            observation = observe(**kwargs)
            ingested = self.operator.ingest_observation(observation)
        except Exception as exc:  # noqa: BLE001 - standalone loop must return a structured wait point.
            return _blocked(
                "observation_ingest_failed",
                work_item=work_item,
                work_item_type=work_type,
                error_type=type(exc).__name__,
            )
        return _consumed(work_type, ingested, work_item)


def _consumed(work_type: str, ingested: dict[str, Any], work_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": STANDALONE_RUNTIME_SCHEMA_VERSION,
        "status": "work_consumed",
        "work_item_type": work_type,
        "work_item_id": work_item.get("work_item_id"),
        "ingested": ingested,
    }


def _blocked(reason: str, *, work_item: dict[str, Any], work_item_type: str | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": STANDALONE_RUNTIME_SCHEMA_VERSION,
        "status": "blocked",
        "reason": reason,
        "work_item_type": work_item_type or work_item.get("work_item_type"),
        "work_item": work_item,
        **extra,
    }


class StandaloneDraftPlanner:
    def __init__(self, root: Path, *, backend_config: dict[str, Any]):
        self.root = root
        self.backend_config = dict(backend_config)

    def draft_for_match(self, *, match_id: str, mode: str) -> dict[str, Any]:
        from dating_boost.core.draft_evidence import build_draft_evidence
        from dating_boost.core.draft_review_audit import DraftReviewAuditRepository
        from dating_boost.core.models import ReplyMode
        from dating_boost.core.repositories import ObservationRepository
        from dating_boost.intelligence.backend_factory import create_model_backend
        from dating_boost.intelligence.draft_generation import generate_reply_with_refinement
        from dating_boost.policy.draft_review import review_draft

        reply_mode = ReplyMode(mode)
        observation = ObservationRepository(self.root).load_latest_observation(match_id)
        evidence = build_draft_evidence(
            self.root,
            match_id,
            reply_mode=reply_mode,
            observation=observation,
            draft_kind="reply",
            user_reactivated=False,
            now=None,
            app_id=observation.app_id if observation else None,
            runtime=_observation_runtime(observation),
            require_user_profile_source=True,
        )
        if evidence.status != "ok":
            return {
                "schema_version": STANDALONE_RUNTIME_SCHEMA_VERSION,
                "status": "blocked",
                "reason": evidence.primary_reason,
                "draft_evidence": evidence.public_dict(),
            }

        try:
            generation = generate_reply_with_refinement(
                evidence,
                backend=create_model_backend(self.backend_config),
                audit_root=self.root,
            )
        except Exception as exc:  # noqa: BLE001 - standalone planner must stop with a structured wait point.
            return {
                "schema_version": STANDALONE_RUNTIME_SCHEMA_VERSION,
                "status": "blocked",
                "reason": "draft_generation_failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "draft_evidence": evidence.public_dict(),
            }
        if generation.status != "ok" or generation.draft_payload is None:
            return {
                "schema_version": STANDALONE_RUNTIME_SCHEMA_VERSION,
                "status": "blocked",
                "reason": generation.primary_reason,
                "draft_evidence": evidence.public_dict(),
                "draft_generation_summary": generation.summary(),
            }

        try:
            review = review_draft(
                generation.draft_payload,
                evidence.context_pack,
                mode="managed_live",
                observation=observation,
                planner_recommendation=evidence.planner_recommendation,
            )
        except Exception as exc:  # noqa: BLE001 - policy/review failures must not crash the standalone loop.
            return {
                "schema_version": STANDALONE_RUNTIME_SCHEMA_VERSION,
                "status": "blocked",
                "reason": "draft_review_failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "draft_evidence": evidence.public_dict(),
                "draft_generation_summary": generation.summary(),
            }
        DraftReviewAuditRepository(self.root).append_review(
            review,
            draft_payload=generation.draft_payload,
            context_pack=evidence.context_pack,
            mode="managed_live",
            target_match_id=match_id,
        )
        return {
            "schema_version": STANDALONE_RUNTIME_SCHEMA_VERSION,
            "status": "ok" if review.allowed_for_managed_send else "blocked",
            "reason": None if review.allowed_for_managed_send else review.primary_reason,
            "match_id": match_id,
            "mode": reply_mode.value,
            "draft_evidence": evidence.public_dict(),
            "draft": generation.draft_payload,
            "draft_generation_summary": generation.summary(),
            "draft_review": review.to_dict(),
        }


def _observation_runtime(observation: Any) -> str | None:
    if observation is None:
        return None
    provenance = observation.provenance if isinstance(observation.provenance, dict) else {}
    runtime = provenance.get("runtime") or provenance.get("harness_runtime")
    return str(runtime) if runtime else "default"
