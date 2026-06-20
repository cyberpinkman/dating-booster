from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from dating_boost.core.managed_session import ManagedSessionRepository
from dating_boost.core.operator import OperatorRepository
from dating_boost.core.standalone_observation import StandaloneObservationProvider


STANDALONE_RUNTIME_SCHEMA_VERSION = 1


class StandaloneAgentRuntime:
    def __init__(
        self,
        root: Path,
        *,
        observation_provider: StandaloneObservationProvider,
        harness_factory: Callable[..., Any] | None = None,
    ):
        self.root = root
        self.observation_provider = observation_provider
        self.managed = ManagedSessionRepository(root, harness_factory=harness_factory)
        self.operator = OperatorRepository(root)

    def tick(self) -> dict[str, Any]:
        managed_payload = self.managed.tick()
        if managed_payload.get("status") != "host_work_required":
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
