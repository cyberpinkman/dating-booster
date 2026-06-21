from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dating_boost.apps.registry import create_adapter
from dating_boost.apps.tashuo.perception import analyze_tashuo_conversation, analyze_tashuo_message_list
from dating_boost.core.standalone_actions import StageOnlyActionExecutor
from dating_boost.core.storage import JsonStorage
from dating_boost.intelligence.vision_backends import VisionBackend


TARGET_CACHE_PATH = Path("standalone_session") / "tashuo_targets.json"


class TaShuoStandaloneTargetCache:
    def __init__(self, root: Path):
        self._storage = JsonStorage(root)

    def put(self, target: dict[str, Any]) -> None:
        current = self._read()
        candidate_key = str(target.get("candidate_key") or "").strip()
        if not candidate_key:
            raise ValueError("candidate_key_required")
        current[candidate_key] = {**target, "observed_at": _now_iso()}
        self._storage.write_json(TARGET_CACHE_PATH, {"schema_version": 1, "targets": current})

    def get(self, candidate_key: str) -> dict[str, Any] | None:
        return self._read().get(candidate_key)

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            payload = self._storage.read_json(TARGET_CACHE_PATH, expected_schema_version=1)
        except FileNotFoundError:
            return {}
        targets = payload.get("targets") if isinstance(payload.get("targets"), dict) else {}
        return {str(key): value for key, value in targets.items() if isinstance(value, dict)}


class TaShuoMacIosStandaloneObservationProvider:
    def __init__(
        self,
        *,
        root: Path,
        output_dir: Path,
        vision_backend: VisionBackend,
        adapter_factory: Callable[[], Any] | None = None,
    ):
        self.root = root
        self.output_dir = output_dir
        self.vision_backend = vision_backend
        self.adapter_factory = adapter_factory or (lambda: create_adapter("tashuo", runtime="mac-ios-app"))
        self.targets = TaShuoStandaloneTargetCache(root)

    def precheck_payload(self, *, app_id: str) -> dict[str, Any]:
        if app_id != "tashuo":
            return _blocked("unsupported_app_for_tashuo_provider", app_id=app_id)
        adapter = self.adapter_factory()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        prepared = adapter.run_action("prepare-message-page", dry_run=False, output_dir=self.output_dir)
        if prepared.get("status") != "ok":
            return _blocked(str(prepared.get("reason") or "prepare_message_page_failed"), app_id=app_id)
        observed = adapter.observe(output_dir=self.output_dir)
        return observed if observed.get("status") == "ok" else _blocked(
            str(observed.get("reason") or "observe_failed"),
            app_id=app_id,
        )

    def observe_message_list(self, *, app_id: str, scan_cursor: dict[str, Any]) -> dict[str, Any]:
        if app_id != "tashuo":
            return _blocked("unsupported_app_for_tashuo_provider", app_id=app_id, observation_type="message_list")
        precheck = self.precheck_payload(app_id=app_id)
        if precheck.get("status") != "ok":
            return {**precheck, "observation_type": "message_list"}
        perceived = analyze_tashuo_message_list(precheck, backend=self.vision_backend)
        if perceived.get("status") != "ok":
            return {**perceived, "observation_type": "message_list", "app_id": app_id, "runtime": "mac-ios-app"}
        candidates = []
        for row in perceived["rows"]:
            self.targets.put(row)
            candidates.append(row)
        return {
            "schema_version": 1,
            "status": "ok",
            "observation_type": "message_list",
            "app_id": app_id,
            "runtime": "mac-ios-app",
            "scan_cursor": dict(scan_cursor),
            "candidates": candidates,
            "provenance": {"app_id": app_id, "runtime": "mac-ios-app", "source": "standalone_live_gui"},
        }

    def observe_thread(self, *, app_id: str, candidate_key: str) -> dict[str, Any]:
        target = self.targets.get(candidate_key)
        if target is None:
            return _blocked(
                "tashuo_standalone_target_not_found",
                app_id=app_id,
                observation_type="thread",
                candidate_key=candidate_key,
            )
        adapter = self.adapter_factory()
        opened = adapter.run_action(
            "open-conversation",
            dry_run=False,
            output_dir=self.output_dir,
            tap_ratio=target["tap_ratio"],
            visual_target_label=target.get("visible_name"),
            visual_target_preview=target.get("latest_preview"),
        )
        if opened.get("status") != "ok":
            return _blocked(
                str(opened.get("reason") or "open_thread_failed"),
                app_id=app_id,
                observation_type="thread",
                candidate_key=candidate_key,
            )
        return self.observe_current_thread(app_id=app_id, candidate_key=candidate_key, cached_target=target)

    def observe_current_thread(
        self,
        *,
        app_id: str,
        candidate_key: str = "current_thread",
        cached_target: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        adapter = self.adapter_factory()
        observed = adapter.observe(output_dir=self.output_dir)
        if observed.get("status") != "ok":
            return _blocked(
                str(observed.get("reason") or "observe_thread_failed"),
                app_id=app_id,
                observation_type="thread",
                candidate_key=candidate_key,
            )
        perceived = analyze_tashuo_conversation(observed, backend=self.vision_backend)
        if perceived.get("status") != "ok":
            return {**perceived, "observation_type": "thread", "app_id": app_id, "runtime": "mac-ios-app", "candidate_key": candidate_key}
        identity = dict(perceived["identity"])
        if cached_target and cached_target.get("visible_name") and not identity.get("visible_name"):
            identity["visible_name"] = cached_target.get("visible_name")
        return {
            "schema_version": 1,
            "status": "ok",
            "observation_type": "thread",
            "app_id": app_id,
            "runtime": "mac-ios-app",
            "candidate_key": candidate_key,
            "match_identity_hints": identity,
            "conversation_observation": {"visible_messages": perceived["visible_messages"]},
            "provenance": {"app_id": app_id, "runtime": "mac-ios-app", "source": "standalone_live_gui"},
        }


class TaShuoStandalonePrecheckHarness:
    def __init__(self, provider: TaShuoMacIosStandaloneObservationProvider, *, app_id: str, runtime: str | None):
        self.provider = provider
        self.app_id = app_id
        self.runtime = runtime

    def observe(self) -> dict[str, Any]:
        payload = self.provider.precheck_payload(app_id=self.app_id)
        payload["runtime"] = self.runtime or "mac-ios-app"
        return payload


class TaShuoMacIosStageExecutor(StageOnlyActionExecutor):
    def __init__(self, *, root: Path, output_dir: Path, adapter_factory: Callable[[], Any] | None = None):
        super().__init__(root, send_mode="stage")
        self.output_dir = output_dir
        self.adapter_factory = adapter_factory or (lambda: create_adapter("tashuo", runtime="mac-ios-app"))

    def execute(self, work_item: dict[str, Any], *, app_id: str) -> dict[str, Any]:
        block_reason = _stage_work_item_block_reason(work_item)
        if block_reason:
            return {
                "schema_version": 1,
                "status": "blocked",
                "reason": block_reason,
                "action_request_id": work_item.get("action_request_id"),
            }
        text = str(work_item.get("payload_text") or "").strip()
        adapter = self.adapter_factory()
        staged = adapter.stage_draft(text, dry_run=False, output_dir=self.output_dir)
        if staged.get("status") != "ok":
            return {
                "schema_version": 1,
                "status": "blocked",
                "reason": str(staged.get("reason") or "tashuo_stage_draft_failed"),
                "action_request_id": work_item.get("action_request_id"),
            }
        if not _staged_text_verified(staged):
            return {
                "schema_version": 1,
                "status": "blocked",
                "reason": "exact_staged_text_not_verified",
                "action_request_id": work_item.get("action_request_id"),
                "gui_stage": _stage_evidence(staged),
            }
        result = super().execute(work_item, app_id=app_id)
        result["gui_stage"] = _stage_evidence(staged)
        return result


def _stage_work_item_block_reason(work_item: dict[str, Any]) -> str | None:
    if not str(work_item.get("action_request_id") or "").strip():
        return "invalid_send_work_item:action_request_id"
    if not str(work_item.get("target_match_id") or work_item.get("match_id") or "").strip():
        return "invalid_send_work_item:target_match_id"
    if not str(work_item.get("payload_text") or "").strip():
        return "invalid_send_work_item:payload_text"
    return None


def _staged_text_verified(staged: dict[str, Any]) -> bool:
    if staged.get("staged_text_verified") is True:
        return True
    verification = staged.get("staged_text_verification")
    if not isinstance(verification, dict):
        return False
    return str(verification.get("status") or "") in {"ok", "verified"}


def _stage_evidence(staged: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in staged.items()
        if key
        in {
            "schema_version",
            "status",
            "stage_attempt_status",
            "staged_text_verified",
            "staged_text_verification",
        }
    }


def _blocked(reason: str, *, app_id: str, **extra: Any) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason, "app_id": app_id, "runtime": "mac-ios-app", **extra}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
