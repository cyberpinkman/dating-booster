from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dating_boost.apps.registry import create_adapter
from dating_boost.apps.tashuo.native import _tashuo_visual_anchor_hash_for_path
from dating_boost.apps.tashuo.perception import analyze_tashuo_conversation, analyze_tashuo_message_list
from dating_boost.core.safety import SafetyRepository
from dating_boost.core.standalone_actions import StageOnlyActionExecutor
from dating_boost.core.storage import JsonStorage
from dating_boost.intelligence.vision_backends import VisionBackend


TARGET_CACHE_PATH = Path("standalone_session") / "tashuo_targets.json"
TARGET_CACHE_MAX_AGE_SECONDS = 120
TARGET_VISUAL_ANCHOR_CACHE_MAX_AGE_SECONDS = 600
SYNTHETIC_MESSAGE_LIST_VISIBLE_NAME_PREFIX = "TaShuo visible chat row"


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

    def app_precheck_payload(self, *, app_id: str) -> dict[str, Any]:
        if app_id != "tashuo":
            return _blocked("unsupported_app_for_tashuo_provider", app_id=app_id)
        adapter = self.adapter_factory()
        self.output_dir.mkdir(parents=True, exist_ok=True)
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
        perceived = _analyze_tashuo_message_list_with_retry(precheck, backend=self.vision_backend)
        if perceived.get("status") != "ok":
            return {**perceived, "observation_type": "message_list", "app_id": app_id, "runtime": "mac-ios-app"}
        screen_path = _screen_path_from_observation(precheck)
        rows = _attach_tashuo_message_list_perceptual_anchors(
            _correct_tashuo_message_list_tap_ratios(perceived["rows"]),
            screen_path=screen_path,
        )
        rows, duplicate_rows = _dedupe_tashuo_message_list_rows(rows)
        candidates = []
        entries = []
        skipped_rows = list(duplicate_rows)
        provider_skipped_row = False
        warnings = [str(item) for item in perceived.get("warnings", []) if str(item).strip()] if isinstance(perceived.get("warnings"), list) else []
        if isinstance(perceived.get("skipped_rows"), list):
            skipped_rows.extend(item for item in perceived["skipped_rows"] if isinstance(item, dict))
        for index, row in enumerate(rows, start=1):
            skip_reason = _tashuo_message_list_visual_row_skip_reason(row)
            if skip_reason:
                provider_skipped_row = True
                skipped_rows.append(_redacted_skipped_visual_row(row, reason=skip_reason, position=index))
                continue
            self.targets.put(row)
            candidates.append(row)
            entries.append(_message_list_entry_from_visual_row(row, position=index))
        if not entries:
            fallback_rows = _tashuo_message_list_grid_fallback_rows(
                precheck=precheck,
                rows=rows,
                screen_path=screen_path,
            )
            if fallback_rows:
                warnings.append("tashuo_message_list_grid_fallback_used")
                for fallback_position, row in enumerate(fallback_rows, start=1):
                    self.targets.put(row)
                    candidates.append(row)
                    entries.append(_message_list_entry_from_visual_row(row, position=fallback_position))
        result = {
            "schema_version": 1,
            "status": "ok",
            "observation_type": "message_list",
            "app_id": app_id,
            "runtime": "mac-ios-app",
            "scan_cursor": dict(scan_cursor),
            "message_list_snapshot": {"entries": entries},
            "candidates": candidates,
            "provenance": {"app_id": app_id, "runtime": "mac-ios-app", "source": "standalone_live_gui"},
        }
        if skipped_rows:
            if provider_skipped_row:
                warnings.append("tashuo_message_list_visual_row_skipped")
            if duplicate_rows:
                warnings.append("tashuo_message_list_duplicate_visual_row_skipped")
            result["warnings"] = list(dict.fromkeys(warnings))
            result["skipped_candidates"] = skipped_rows
        elif warnings:
            result["warnings"] = list(dict.fromkeys(warnings))
        return result

    def observe_thread(self, *, app_id: str, candidate_key: str) -> dict[str, Any]:
        target = self.targets.get(candidate_key)
        if target is None:
            if _is_current_thread_candidate_key(candidate_key):
                return self.observe_current_thread(app_id=app_id, candidate_key=candidate_key, cached_target=None)
            return _blocked(
                "tashuo_standalone_target_not_found",
                app_id=app_id,
                observation_type="thread",
                candidate_key=candidate_key,
            )
        freshness_reason = _target_freshness_block_reason(target)
        if freshness_reason:
            max_age_seconds = _target_cache_max_age_seconds(target)
            return _blocked(
                freshness_reason,
                app_id=app_id,
                observation_type="thread",
                candidate_key=candidate_key,
                observed_at=target.get("observed_at"),
                max_age_seconds=max_age_seconds,
            )
        adapter = self.adapter_factory()
        opened = adapter.run_action(
            "open-conversation",
            dry_run=False,
            output_dir=self.output_dir,
            **_open_conversation_target_options(target),
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
        perceived = _analyze_tashuo_conversation_with_retry(observed, backend=self.vision_backend)
        if perceived.get("status") != "ok":
            return {**perceived, "observation_type": "thread", "app_id": app_id, "runtime": "mac-ios-app", "candidate_key": candidate_key}
        identity = dict(perceived["identity"])
        normalized_identity_name = _normalized_visible_name(identity.get("visible_name"))
        if normalized_identity_name:
            identity["visible_name"] = normalized_identity_name
        if cached_target:
            cached_name = _normalized_visible_name(cached_target.get("visible_name"))
            perceived_name = _normalized_visible_name(identity.get("visible_name"))
            if _visible_name_identity_conflict(
                cached_name,
                perceived_name,
                cached_target=cached_target,
                visible_messages=perceived.get("visible_messages"),
            ):
                return _blocked(
                    "current_thread_visual_identity_mismatch",
                    app_id=app_id,
                    observation_type="thread",
                    candidate_key=candidate_key,
                    cached_visible_name=cached_name,
                    perceived_visible_name=perceived_name,
                )
        if (
            cached_target
            and cached_target.get("visible_name")
            and not _is_synthetic_message_list_visible_name(cached_target.get("visible_name"))
            and not identity.get("visible_name")
        ):
            identity["visible_name"] = cached_target.get("visible_name")
        return _thread_observation_from_perception(
            app_id=app_id,
            candidate_key=candidate_key,
            identity=identity,
            visible_messages=perceived["visible_messages"],
            cached_target=cached_target,
        )


def _analyze_tashuo_message_list_with_retry(observation: dict[str, Any], *, backend: VisionBackend) -> dict[str, Any]:
    return _analyze_tashuo_vision_with_retry(
        lambda: analyze_tashuo_message_list(observation, backend=backend),
        timeout_reason="tashuo_message_list_vision_timeout",
    )


def _analyze_tashuo_conversation_with_retry(observation: dict[str, Any], *, backend: VisionBackend) -> dict[str, Any]:
    return _analyze_tashuo_vision_with_retry(
        lambda: analyze_tashuo_conversation(observation, backend=backend),
        timeout_reason="tashuo_conversation_vision_timeout",
    )


def _analyze_tashuo_vision_with_retry(analyze: Callable[[], dict[str, Any]], *, timeout_reason: str) -> dict[str, Any]:
    last_timeout: Exception | None = None
    for _attempt in range(2):
        try:
            return analyze()
        except Exception as exc:  # noqa: BLE001 - transient model timeouts should not crash the runtime loop.
            if not _is_retryable_vision_timeout(exc):
                raise
            last_timeout = exc
    return {
        "schema_version": 1,
        "status": "blocked",
        "reason": timeout_reason,
        "error_type": type(last_timeout).__name__ if last_timeout is not None else "TimeoutError",
    }


def _is_retryable_vision_timeout(exc: Exception) -> bool:
    error_type = type(exc).__name__.lower()
    message = str(exc).lower()
    return "timeout" in error_type or "timed out" in message or "request timed out" in message


class TaShuoStandalonePrecheckHarness:
    def __init__(self, provider: TaShuoMacIosStandaloneObservationProvider, *, app_id: str, runtime: str | None):
        self.provider = provider
        self.app_id = app_id
        self.runtime = runtime

    def observe(self) -> dict[str, Any]:
        payload = self.provider.app_precheck_payload(app_id=self.app_id)
        payload["runtime"] = self.runtime or "mac-ios-app"
        return payload


class TaShuoMacIosStageExecutor(StageOnlyActionExecutor):
    def __init__(
        self,
        *,
        root: Path,
        output_dir: Path,
        vision_backend: VisionBackend | None = None,
        adapter_factory: Callable[[], Any] | None = None,
    ):
        super().__init__(root, send_mode="stage")
        self.root = root
        self.output_dir = output_dir
        self.vision_backend = vision_backend
        self.adapter_factory = adapter_factory or (lambda: create_adapter("tashuo", runtime="mac-ios-app"))
        self.targets = TaShuoStandaloneTargetCache(root)

    def execute(self, work_item: dict[str, Any], *, app_id: str) -> dict[str, Any]:
        block_reason = _stage_work_item_block_reason(work_item)
        if block_reason:
            return {
                "schema_version": 1,
                "status": "blocked",
                "reason": block_reason,
                "action_request_id": work_item.get("action_request_id"),
            }
        if SafetyRepository(self.root).is_paused():
            return {
                "schema_version": 1,
                "status": "blocked",
                "reason": "safety_paused",
                "action_request_id": work_item.get("action_request_id"),
                "next_host_action": "resume_safety_before_staging",
            }
        text = str(work_item.get("payload_text") or "").strip()
        adapter = self.adapter_factory()
        target_verification = self._verify_stage_target(adapter, work_item=work_item, app_id=app_id)
        if target_verification.get("status") == "blocked":
            return {
                "schema_version": 1,
                "status": "blocked",
                "reason": str(target_verification.get("reason") or "tashuo_stage_target_not_verified"),
                "action_request_id": work_item.get("action_request_id"),
                "target_verification": target_verification,
            }
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
                "target_verification": target_verification,
            }
        stage_evidence = _stage_evidence(staged)
        if target_verification.get("status") == "ok":
            stage_evidence["target_verification"] = target_verification
        result = self._execute_stage(work_item, app_id=app_id, stage_evidence=stage_evidence)
        result["gui_stage"] = stage_evidence
        if target_verification.get("status") == "ok":
            result["target_verification"] = target_verification
        return result

    def _verify_stage_target(self, adapter: Any, *, work_item: dict[str, Any], app_id: str) -> dict[str, Any]:
        candidate_key = _stage_candidate_key(work_item)
        if not candidate_key:
            return _stage_target_blocked("tashuo_stage_target_candidate_key_absent", candidate_key="")
        target = self.targets.get(candidate_key)
        in_place: dict[str, Any] | None = None
        if self.vision_backend is not None:
            in_place = self._verify_current_stage_target(
                adapter,
                work_item=work_item,
                app_id=app_id,
                target=target or {},
            )
            if in_place.get("status") == "ok":
                return in_place
        if target is None:
            return _stage_target_blocked(
                "tashuo_standalone_target_not_found",
                candidate_key=candidate_key,
                in_place_result=in_place,
            )
        return self._reopen_stage_target(
            adapter,
            work_item=work_item,
            app_id=app_id,
            target=target,
            in_place_result=in_place,
        )

    def _verify_current_stage_target(
        self,
        adapter: Any,
        *,
        work_item: dict[str, Any],
        app_id: str,
        target: dict[str, Any],
    ) -> dict[str, Any]:
        candidate_key = _stage_candidate_key(work_item) or ""
        observed = adapter.observe(output_dir=self.output_dir)
        if observed.get("status") != "ok":
            return _stage_target_blocked(
                str(observed.get("reason") or "observe_current_thread_failed_before_stage"),
                candidate_key=candidate_key,
            )
        screen_state = str(observed.get("screen_state") or "").strip()
        if screen_state and screen_state != "tashuo_conversation":
            return _stage_target_blocked(
                "tashuo_current_screen_not_conversation",
                candidate_key=candidate_key,
                screen_state=screen_state,
            )
        perceived = analyze_tashuo_conversation(observed, backend=self.vision_backend)  # type: ignore[arg-type]
        if perceived.get("status") != "ok":
            return _stage_target_blocked(
                str(perceived.get("reason") or "tashuo_current_thread_identity_not_verified"),
                candidate_key=candidate_key,
                screen_state=screen_state or None,
            )
        identity = perceived.get("identity") if isinstance(perceived.get("identity"), dict) else {}
        identity_mismatch = _stage_target_identity_mismatch(
            identity,
            target=target,
            work_item=work_item,
            visible_messages=perceived.get("visible_messages"),
        )
        if identity_mismatch:
            return _stage_target_blocked(
                identity_mismatch,
                candidate_key=candidate_key,
                screen_state=screen_state or None,
                expected_visible_name=_stage_expected_visible_name(target, work_item),
                perceived_visible_name=_normalized_visible_name(identity.get("visible_name")),
            )
        return {
            "schema_version": 1,
            "status": "ok",
            "verification_method": "tashuo_stage_target_in_place_vision_identity_check",
            "app_id": app_id,
            "candidate_key": candidate_key,
            "visible_name": _stage_expected_visible_name(target, work_item),
            "thread_visual_anchor_hash": identity.get("visual_anchor_hash"),
            "message_list_evidence": _message_list_evidence_from_target(target) if target else None,
            "screen_state": screen_state or None,
        }

    def _reopen_stage_target(
        self,
        adapter: Any,
        *,
        work_item: dict[str, Any],
        app_id: str,
        target: dict[str, Any],
        in_place_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        candidate_key = _stage_candidate_key(work_item) or str(target.get("candidate_key") or "")
        freshness_reason = _target_freshness_block_reason(target)
        if freshness_reason:
            return _stage_target_blocked(freshness_reason, candidate_key=candidate_key, in_place_result=in_place_result)
        tap_ratio = target.get("tap_ratio") if isinstance(target.get("tap_ratio"), dict) else None
        if not tap_ratio:
            return _stage_target_blocked(
                "tashuo_stage_target_tap_ratio_missing",
                candidate_key=candidate_key,
                in_place_result=in_place_result,
            )

        prepared = adapter.run_action("prepare-message-page", dry_run=False, output_dir=self.output_dir)
        if prepared.get("status") != "ok":
            return _stage_target_blocked(
                str(prepared.get("reason") or "prepare_message_page_failed_before_stage"),
                candidate_key=candidate_key,
                in_place_result=in_place_result,
                prepare_result=_redacted_step_result(prepared),
            )
        opened = adapter.run_action(
            "open-conversation",
            dry_run=False,
            output_dir=self.output_dir,
            **_open_conversation_target_options(target),
        )
        if opened.get("status") != "ok":
            return _stage_target_blocked(
                str(opened.get("reason") or "open_thread_failed_before_stage"),
                candidate_key=candidate_key,
                in_place_result=in_place_result,
                prepare_result=_redacted_step_result(prepared),
                open_result=_redacted_step_result(opened),
            )
        if self.vision_backend is None:
            return {
                "schema_version": 1,
                "status": "ok",
                "verification_method": "tashuo_stage_target_reopened_without_vision_recheck",
                "candidate_key": candidate_key,
                "message_list_evidence": _message_list_evidence_from_target(target),
                "in_place_result": in_place_result,
                "prepare_result": _redacted_step_result(prepared),
                "open_result": _redacted_step_result(opened),
            }
        observed = adapter.observe(output_dir=self.output_dir)
        if observed.get("status") != "ok":
            return _stage_target_blocked(
                str(observed.get("reason") or "observe_thread_failed_before_stage"),
                candidate_key=candidate_key,
                in_place_result=in_place_result,
                prepare_result=_redacted_step_result(prepared),
                open_result=_redacted_step_result(opened),
            )
        perceived = analyze_tashuo_conversation(observed, backend=self.vision_backend)
        if perceived.get("status") != "ok":
            return _stage_target_blocked(
                str(perceived.get("reason") or "tashuo_stage_target_identity_not_verified"),
                candidate_key=candidate_key,
                in_place_result=in_place_result,
                prepare_result=_redacted_step_result(prepared),
                open_result=_redacted_step_result(opened),
            )
        identity = perceived.get("identity") if isinstance(perceived.get("identity"), dict) else {}
        identity_mismatch = _stage_target_identity_mismatch(
            identity,
            target=target,
            work_item=work_item,
            visible_messages=perceived.get("visible_messages"),
        )
        if identity_mismatch:
            return _stage_target_blocked(
                identity_mismatch,
                candidate_key=candidate_key,
                in_place_result=in_place_result,
                prepare_result=_redacted_step_result(prepared),
                open_result=_redacted_step_result(opened),
                expected_visible_name=_stage_expected_visible_name(target, work_item),
                perceived_visible_name=_normalized_visible_name(identity.get("visible_name")),
            )
        return {
            "schema_version": 1,
            "status": "ok",
            "verification_method": "tashuo_stage_target_reopen_and_vision_identity_check",
            "app_id": app_id,
            "candidate_key": candidate_key,
            "visible_name": _stage_expected_visible_name(target, work_item),
            "thread_visual_anchor_hash": identity.get("visual_anchor_hash"),
            "message_list_evidence": _message_list_evidence_from_target(target),
            "in_place_result": in_place_result,
            "prepare_result": _redacted_step_result(prepared),
            "open_result": _redacted_step_result(opened),
        }


def _stage_work_item_block_reason(work_item: dict[str, Any]) -> str | None:
    if not str(work_item.get("action_request_id") or "").strip():
        return "invalid_send_work_item:action_request_id"
    if not str(work_item.get("target_match_id") or work_item.get("match_id") or "").strip():
        return "invalid_send_work_item:target_match_id"
    if not str(work_item.get("payload_text") or "").strip():
        return "invalid_send_work_item:payload_text"
    return None


def _stage_candidate_key(work_item: dict[str, Any]) -> str | None:
    direct = str(work_item.get("candidate_key") or "").strip()
    if direct:
        return direct
    binding = work_item.get("target_binding") if isinstance(work_item.get("target_binding"), dict) else {}
    value = str(binding.get("candidate_key") or "").strip()
    return value or None


def _is_current_thread_candidate_key(candidate_key: Any) -> bool:
    value = str(candidate_key or "").strip()
    return value == "current_thread" or value.startswith("current_thread_")


def _stage_target_blocked(reason: str, *, candidate_key: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "blocked",
        "reason": reason,
        "candidate_key": candidate_key,
        **extra,
    }


def _stage_expected_visible_name(target: dict[str, Any], work_item: dict[str, Any]) -> str | None:
    binding = work_item.get("target_binding") if isinstance(work_item.get("target_binding"), dict) else {}
    for value in (binding.get("visible_name"), target.get("visible_name")):
        normalized = _normalized_visible_name(value)
        if normalized and not _is_synthetic_message_list_visible_name(normalized):
            return normalized
    return None


def _stage_target_identity_mismatch(
    identity: dict[str, Any],
    *,
    target: dict[str, Any],
    work_item: dict[str, Any],
    visible_messages: Any = None,
) -> str | None:
    expected_name = _stage_expected_visible_name(target, work_item)
    perceived_name = _normalized_visible_name(identity.get("visible_name"))
    if _visible_name_identity_conflict(
        expected_name,
        perceived_name,
        cached_target=target,
        visible_messages=visible_messages,
    ):
        return "current_thread_visual_identity_mismatch"
    if _current_thread_binding_evidence_mismatch(
        identity,
        work_item=work_item,
        visible_messages=visible_messages,
        target=target,
    ):
        return "current_thread_binding_evidence_mismatch"
    return None


def _current_thread_binding_evidence_mismatch(
    identity: dict[str, Any],
    *,
    work_item: dict[str, Any],
    visible_messages: Any,
    target: dict[str, Any] | None = None,
) -> bool:
    binding = work_item.get("target_binding") if isinstance(work_item.get("target_binding"), dict) else {}
    thread_evidence = binding.get("thread_evidence") if isinstance(binding.get("thread_evidence"), dict) else {}
    expected_anchor = str(thread_evidence.get("visual_anchor_hash") or "").strip()
    expected_latest = str(thread_evidence.get("latest_inbound_fingerprint") or "").strip()
    if not expected_anchor and not expected_latest:
        return False

    current_anchor = str(identity.get("visual_anchor_hash") or "").strip()
    current_latest = _current_latest_inbound_fingerprint(visible_messages)
    anchor_matches = bool(expected_anchor and current_anchor and expected_anchor == current_anchor)
    latest_matches = bool(expected_latest and current_latest and expected_latest == current_latest)
    preview_matches = bool(target and _latest_preview_corroborates_thread(target, visible_messages))
    visible_name_continuity = _current_thread_visible_name_continuity_allowed(
        identity,
        work_item=work_item,
        target=target,
        expected_latest=expected_latest,
        current_latest=current_latest,
    )
    return not (anchor_matches or latest_matches or preview_matches or visible_name_continuity)


def _current_thread_visible_name_continuity_allowed(
    identity: dict[str, Any],
    *,
    work_item: dict[str, Any],
    target: dict[str, Any] | None,
    expected_latest: str,
    current_latest: str | None,
) -> bool:
    candidate_key = _stage_candidate_key(work_item) or ""
    if not _is_current_thread_candidate_key(candidate_key):
        return False
    if expected_latest and current_latest and expected_latest != current_latest:
        return False
    expected_name = _stage_expected_visible_name(target or {}, work_item)
    perceived_name = _normalized_visible_name(identity.get("visible_name"))
    if not expected_name or not perceived_name:
        return False
    return not _visible_name_identity_conflict(expected_name, perceived_name)


def _current_latest_inbound_fingerprint(visible_messages: Any) -> str | None:
    if not isinstance(visible_messages, list):
        return None
    normalized = _normalize_visible_messages(visible_messages)
    latest_inbound = _latest_inbound_messages(normalized)
    latest_text = str(latest_inbound[-1].get("text") or "").strip() if latest_inbound else ""
    return _stable_text_hash(latest_text) if latest_text else None


def _message_list_evidence_from_target(target: dict[str, Any]) -> dict[str, Any]:
    tap_ratio = target.get("tap_ratio") if isinstance(target.get("tap_ratio"), dict) else None
    region = _visual_anchor_region_from_source(target)
    return {
        "evidence_type": "message_list_visual_anchor",
        "visual_anchor_hash": str(target.get("visual_anchor_hash") or "").strip() or None,
        "visual_anchor_region": region,
        "tap_ratio": dict(tap_ratio) if tap_ratio else None,
        "tap_ratio_source": target.get("tap_ratio_source"),
        "selection_method": target.get("selection_method") or "standalone_vision_message_list_row",
    }


def _open_conversation_target_options(target: dict[str, Any]) -> dict[str, Any]:
    evidence = _message_list_evidence_from_target(target)
    return {
        "tap_ratio": target.get("tap_ratio"),
        "visual_target_label": target.get("visible_name"),
        "visual_target_preview": target.get("latest_preview"),
        "visual_anchor_hash": evidence.get("visual_anchor_hash"),
        "visual_anchor_region": evidence.get("visual_anchor_region"),
        "message_list_evidence": evidence,
    }


def _redacted_step_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in ("schema_version", "status", "reason", "screen_state", "action", "target", "next_host_action")
        if key in payload
    }


def _message_list_entry_from_visual_row(row: dict[str, Any], *, position: int) -> dict[str, Any]:
    visible_name = str(row.get("visible_name") or "").strip()
    latest_preview = str(row.get("latest_preview") or "").strip()
    anchor = str(row.get("visual_anchor_hash") or row.get("candidate_key") or "").strip()
    tap_ratio = row.get("tap_ratio") if isinstance(row.get("tap_ratio"), dict) else None
    region = _visual_anchor_region_from_source(row)
    selection_method = str(row.get("selection_method") or "standalone_vision_message_list_row")
    entry = {
        "candidate_key": str(row.get("candidate_key") or f"tashuo_visual_{anchor}").strip(),
        "visible_name": visible_name or None,
        "latest_preview": latest_preview,
        "latest_preview_hash": _stable_text_hash(latest_preview or anchor),
        "candidate_type": _candidate_type_from_visual_row(row),
        "position": position,
        "identity_confidence": row.get("confidence") if row.get("confidence") in {"low", "medium", "high"} else "medium",
        "identity_evidence": "TaShuo mac-ios-app message-list visual row.",
        "evidence": "Visible TaShuo message-list row selected by standalone observation provider.",
        "match_identity_hints": {
            "visible_name": visible_name,
            "profile_cues": [],
            "conversation_fingerprint": anchor or _stable_text_hash(latest_preview),
            "evidence": "Visible TaShuo message-list row visual anchor.",
        },
        "message_list_evidence": {
            "evidence_type": "message_list_visual_anchor",
            "visual_anchor_hash": anchor,
            "visual_anchor_region": region,
            "tap_ratio": dict(tap_ratio) if tap_ratio else None,
            "selection_method": selection_method,
        },
    }
    return {key: value for key, value in entry.items() if value is not None}


def _tashuo_message_list_visual_row_skip_reason(row: dict[str, Any]) -> str | None:
    visible_name = _normalized_visible_name(row.get("visible_name"))
    if not visible_name:
        return "missing_visible_name"
    if _candidate_type_from_visual_row(row) == "non_chat_gate":
        return "non_chat_gate"
    tap_ratio = row.get("tap_ratio") if isinstance(row.get("tap_ratio"), dict) else None
    if not tap_ratio:
        return "missing_tap_ratio"
    anchor = str(row.get("visual_anchor_hash") or row.get("candidate_key") or "").strip()
    region = _visual_anchor_region_from_source(row)
    if not anchor and region is None:
        return "missing_visual_anchor"
    return None


def _dedupe_tashuo_message_list_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    seen: set[tuple[str, str]] = set()
    kept: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for position, row in enumerate(rows, start=1):
        key = _tashuo_message_list_duplicate_key(row)
        if key is not None and key in seen:
            skipped.append(_redacted_skipped_visual_row(row, reason="duplicate_visual_row", position=position))
            continue
        if key is not None:
            seen.add(key)
        kept.append(row)
    return kept, skipped


def _tashuo_message_list_duplicate_key(row: dict[str, Any]) -> tuple[str, str] | None:
    visible_name = _normalized_visible_name(row.get("visible_name"))
    latest_preview = str(row.get("latest_preview") or "").strip()
    if not visible_name or not latest_preview:
        return None
    return (visible_name, _stable_text_hash(latest_preview))


def _redacted_skipped_visual_row(row: dict[str, Any], *, reason: str, position: int) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "candidate_key": row.get("candidate_key"),
            "reason": reason,
            "position": position,
            "candidate_type": _candidate_type_from_visual_row(row),
            "has_latest_preview": bool(str(row.get("latest_preview") or "").strip()),
            "has_tap_ratio": isinstance(row.get("tap_ratio"), dict),
            "has_visual_anchor": bool(str(row.get("visual_anchor_hash") or "").strip())
            or _visual_anchor_region_from_source(row) is not None,
        }.items()
        if value is not None
    }


def _candidate_type_from_visual_row(row: dict[str, Any]) -> str:
    visible_name = str(row.get("visible_name") or "").strip()
    latest_preview = str(row.get("latest_preview") or "").strip()
    anchor = str(row.get("visual_anchor_hash") or row.get("candidate_key") or "").strip().lower()
    combined = f"{visible_name} {latest_preview} {anchor}".lower()
    if _looks_like_tashuo_non_chat_gate(combined, visible_name=visible_name, latest_preview=latest_preview):
        return "non_chat_gate"
    if "开启聊天" in latest_preview or "可以进行会话" in latest_preview:
        return "open_chat_candidate"
    return "continuation_candidate"


def _looks_like_tashuo_action_artifact(row: dict[str, Any]) -> bool:
    visible_name = str(row.get("visible_name") or "").strip()
    latest_preview = str(row.get("latest_preview") or "").strip()
    preview_lower = latest_preview.lower()
    if any(token in visible_name for token in ("去回复", "开启聊天按钮", "去回复按钮", "按钮")):
        return True
    if latest_preview in {"去回复", "开启聊天"}:
        return True
    if any(token in latest_preview for token in ("去回复", "开启聊天")) and any(
        token in preview_lower for token in ("action", "button", "按钮")
    ):
        return True
    return False


def _looks_like_tashuo_non_chat_gate(combined: str, *, visible_name: str, latest_preview: str) -> bool:
    if _looks_like_tashuo_action_artifact({"visible_name": visible_name, "latest_preview": latest_preview}):
        return True
    visible_name_lower = visible_name.strip().lower()
    if visible_name_lower.startswith("tab header"):
        return True
    if "消息" in visible_name and "动态" in visible_name and len(visible_name.strip()) <= 24:
        return True
    if "开启通知" in combined or "接收通知" in combined:
        return True
    if any(
        token in combined
        for token in (
            "liked_you",
            "premium",
            "paywall",
            "new_badge",
            "pending_clock",
            "clock_placeholder",
            "photo_avatar",
            "portrait_oval",
            "blurred_avatar",
            "orange_avatar_blur",
            "answer_pending",
            "pending question",
            "pending_question",
            "question gate",
            "question_gate",
            "question row avatar",
            "anonymous question",
            "anonymous_question",
            "no visible name",
            "unnamed",
            "tab header",
            "message tab header",
            "notification banner",
            "search icon",
            "filter icon",
            "list icon",
        )
    ):
        return True
    if any(
        token in visible_name
        for token in (
            "优秀的女生想认识你",
            "抢手的女生喜欢了你",
            "查看谁喜欢了我",
            "查看谁喜欢我",
            "喜欢你的人",
            "喜欢了你",
            "去回复",
            "开启聊天",
            "按钮",
            "等待中",
            "待回答",
            "匿名提问",
            "提问卡片",
            "问题卡片",
            "未命名",
        )
    ):
        return True
    if latest_preview in {"等待中", "待回答", "待回答 (1)"} or "待回答" in latest_preview:
        return True
    if "受欢迎" in latest_preview and ("女生" in visible_name or "喜欢" in visible_name):
        return True
    if "她毕业于知名院校" in latest_preview and "优秀的女生" in visible_name:
        return True
    if "开通黑金vip" in latest_preview.lower():
        return True
    return False


def _correct_tashuo_message_list_tap_ratios(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(rows) < 2:
        return rows
    first_index = _first_all_messages_row_index(rows)
    if first_index is None:
        inferred = _infer_first_visible_chat_row_grid_start(rows)
        if inferred is None:
            return rows
        first_index, start_y = inferred
    else:
        start_y = _all_messages_start_y(rows[first_index])
        if start_y is None:
            return rows
    corrected: list[dict[str, Any]] = []
    row_step = 0.122
    grid_offset = 0
    for index, row in enumerate(rows):
        item = dict(row)
        tap_ratio = item.get("tap_ratio") if isinstance(item.get("tap_ratio"), dict) else {}
        if index >= first_index:
            y = round(min(0.965, start_y + grid_offset * row_step), 4)
            item["tap_ratio"] = {**tap_ratio, "x": _all_messages_open_tap_x(item), "y": y}
            item["tap_ratio_source"] = "corrected_all_messages_row_action"
            item = _align_visual_anchor_region_to_tap_y(item, tap_y=y)
            if not _looks_like_tashuo_action_artifact(item):
                grid_offset += 1
        corrected.append(item)
    return corrected


def _infer_first_visible_chat_row_grid_start(rows: list[dict[str, Any]]) -> tuple[int, float] | None:
    for index, row in enumerate(rows):
        if _candidate_type_from_visual_row(row) == "non_chat_gate":
            continue
        if not _normalized_visible_name(row.get("visible_name")):
            continue
        y = _tap_y(row)
        region = _visual_anchor_region_from_source(row)
        if y is None:
            continue
        region_y1 = float(region["y1"]) if isinstance(region, dict) else y - 0.06
        if 0.52 <= y <= 0.66 and region_y1 <= 0.62:
            return index, 0.577
        return None
    return None


def _all_messages_open_tap_x(row: dict[str, Any]) -> float:
    visible_name = str(row.get("visible_name") or "").strip()
    latest_preview = str(row.get("latest_preview") or "").strip()
    anchor = str(row.get("visual_anchor_hash") or row.get("candidate_key") or "").strip().lower()
    combined = f"{visible_name} {latest_preview} {anchor}".lower()
    if _looks_like_tashuo_non_chat_gate(combined, visible_name=visible_name, latest_preview=latest_preview):
        return 0.5
    return 0.87


def _align_visual_anchor_region_to_tap_y(row: dict[str, Any], *, tap_y: float) -> dict[str, Any]:
    region = _visual_anchor_region_from_source(row)
    if region is None:
        return row
    if float(region["y1"]) <= tap_y <= float(region["y2"]):
        return row
    height = max(0.03, min(0.28, float(region["y2"]) - float(region["y1"])))
    y1 = max(0.0, min(1.0 - height, tap_y - height / 2.0))
    aligned = {
        **region,
        "y1": round(y1, 4),
        "y2": round(y1 + height, 4),
    }
    return {**row, "visual_anchor_region": aligned}


def _tashuo_message_list_grid_fallback_rows(
    *,
    precheck: dict[str, Any],
    rows: list[dict[str, Any]],
    screen_path: Path | None,
) -> list[dict[str, Any]]:
    if screen_path is None or not _precheck_has_tashuo_message_list_anchor(precheck):
        return []
    start_y = _fallback_first_chat_row_y(rows)
    if start_y is None:
        return []
    fallback_rows = []
    for offset, y in enumerate(_fallback_message_list_row_ys(start_y), start=1):
        row = {
            "tap_ratio": {"x": 0.87, "y": y},
            "tap_ratio_source": "synthetic_all_messages_row_action",
            "visible_name": f"{SYNTHETIC_MESSAGE_LIST_VISIBLE_NAME_PREFIX} {offset}",
            "latest_preview": "",
            "visual_anchor_hash": f"synthetic_grid_row_{offset}_{int(y * 10000)}",
            "visual_anchor_region": _fallback_message_list_avatar_region(y),
            "visual_anchor_region_source": "synthetic_message_list_grid",
            "confidence": "low",
            "selection_method": "standalone_visual_message_list_grid_fallback",
        }
        fallback_rows.append(row)
    enriched = _attach_tashuo_message_list_perceptual_anchors(fallback_rows, screen_path=screen_path)
    normalized = []
    for row in enriched:
        item = dict(row)
        anchor = str(item.get("visual_anchor_hash") or item.get("visual_anchor_label") or "").strip()
        if not anchor:
            anchor = hashlib.sha256(
                f"{item.get('visible_name')}|{item.get('tap_ratio')}|{item.get('visual_anchor_region')}".encode("utf-8")
            ).hexdigest()[:16]
        item["candidate_key"] = f"tashuo_visual_{anchor}"
        normalized.append(item)
    return normalized


def _precheck_has_tashuo_message_list_anchor(precheck: dict[str, Any]) -> bool:
    if precheck.get("screen_state") != "tashuo_chat_list":
        return False
    if precheck.get("message_list_top_anchor_present") is True:
        return True
    screen = precheck.get("screen") if isinstance(precheck.get("screen"), dict) else {}
    if screen.get("message_list_top_anchor_present") is True:
        return True
    layout = precheck.get("layout_hints") if isinstance(precheck.get("layout_hints"), dict) else {}
    return bool(layout.get("message_list_top_anchor_present") or layout.get("chat_list_visual_present"))


def _fallback_first_chat_row_y(rows: list[dict[str, Any]]) -> float | None:
    first_index = _first_all_messages_row_index(rows)
    if first_index is not None:
        start_y = _all_messages_start_y(rows[first_index])
        if start_y is not None:
            return round(start_y + 0.122, 4)
    if rows and any(_candidate_type_from_visual_row(row) == "non_chat_gate" for row in rows):
        return 0.577
    return None


def _fallback_message_list_row_ys(start_y: float) -> list[float]:
    values = []
    for index in range(3):
        y = round(start_y + index * 0.122, 4)
        if 0.52 <= y <= 0.86:
            values.append(y)
    return values


def _fallback_message_list_avatar_region(y: float) -> dict[str, float]:
    height = 0.101
    y1 = max(0.0, y - height / 2.0)
    y2 = min(1.0, y + height / 2.0)
    return {"x1": 0.041, "y1": round(y1, 4), "x2": 0.37, "y2": round(y2, 4)}


def _attach_tashuo_message_list_perceptual_anchors(
    rows: list[dict[str, Any]],
    *,
    screen_path: Path | None,
) -> list[dict[str, Any]]:
    if screen_path is None:
        return rows
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        region = _visual_anchor_region_from_source(item)
        semantic_anchor = str(item.get("visual_anchor_hash") or "").strip()
        if region is not None:
            hash_result = _tashuo_visual_anchor_hash_for_path(screen_path, region=region)
            perceptual_hash = str(hash_result.get("visual_anchor_hash") or "").strip()
            if hash_result.get("status") == "ok" and perceptual_hash:
                if semantic_anchor:
                    item["visual_anchor_label"] = semantic_anchor
                item["visual_anchor_hash"] = perceptual_hash
                item["visual_anchor_grid_size"] = hash_result.get("grid_size")
        enriched.append(item)
    return enriched


def _screen_path_from_observation(observation: dict[str, Any]) -> Path | None:
    screen = observation.get("screen") if isinstance(observation.get("screen"), dict) else {}
    path = screen.get("path") if isinstance(screen.get("path"), str) else None
    if not path:
        return None
    return Path(path)


def _first_all_messages_row_index(rows: list[dict[str, Any]]) -> int | None:
    for index, row in enumerate(rows):
        visible_name = str(row.get("visible_name") or "")
        latest_preview = str(row.get("latest_preview") or "")
        anchor = str(row.get("visual_anchor_hash") or row.get("candidate_key") or "").lower()
        if any(token in visible_name for token in ("有个优秀的女生想认识你", "查看谁喜欢了我", "喜欢了你")):
            return index
        if any(token in anchor for token in ("new_promo", "new_badge", "liked_you", "likes_you", "liked_", "likes_")):
            return index
        if latest_preview.startswith("你们已经可以进行会话") and _tap_y(row) and _tap_y(row) > 0.72:
            return index
    return None


def _all_messages_start_y(first_row: dict[str, Any]) -> float | None:
    visible_name = str(first_row.get("visible_name") or "")
    anchor = str(first_row.get("visual_anchor_hash") or first_row.get("candidate_key") or "").lower()
    if (
        "查看谁喜欢了我" in visible_name
        or "喜欢了你" in visible_name
        or any(token in anchor for token in ("liked_you", "likes_you", "liked_", "likes_"))
    ):
        return 0.455
    if "有个优秀的女生想认识你" in visible_name or any(token in anchor for token in ("new_promo", "new_badge")):
        return 0.525
    if str(first_row.get("latest_preview") or "").startswith("你们已经可以进行会话"):
        return 0.635
    return None


def _tap_y(row: dict[str, Any]) -> float | None:
    tap_ratio = row.get("tap_ratio") if isinstance(row.get("tap_ratio"), dict) else {}
    try:
        return float(tap_ratio.get("y"))
    except (TypeError, ValueError):
        return None


def _thread_observation_from_perception(
    *,
    app_id: str,
    candidate_key: str,
    identity: dict[str, Any],
    visible_messages: list[dict[str, Any]],
    cached_target: dict[str, Any] | None,
) -> dict[str, Any]:
    now = _now_iso()
    normalized_messages = _normalize_visible_messages(visible_messages)
    latest_inbound = _latest_inbound_messages(normalized_messages)
    latest_inbound_text = str(latest_inbound[-1].get("text") or "").strip() if latest_inbound else ""
    anchor = str(identity.get("visual_anchor_hash") or "").strip()
    cached_anchor = str((cached_target or {}).get("visual_anchor_hash") or "").strip()
    visible_name = str(identity.get("visible_name") or (cached_target or {}).get("visible_name") or "").strip()
    conversation_fingerprint = anchor or cached_anchor or _stable_text_hash(_messages_fingerprint_payload(normalized_messages))
    observation_id = _observation_id(app_id=app_id, candidate_key=candidate_key, fingerprint=conversation_fingerprint)
    latest_inbound_fingerprint = _stable_text_hash(latest_inbound_text or conversation_fingerprint)
    observation = {
        "observation_id": observation_id,
        "source_type": "live_screenshot",
        "app_id": app_id,
        "adapter_id": "tashuo.mac-ios-app.standalone.v1",
        "captured_at": now,
        "page_type": "chat_thread",
        "page_confidence": _conversation_confidence(visible_messages),
        "match_identity_hints": {
            "visible_name": visible_name or None,
            "profile_cues": _profile_cues_from_cached_target(cached_target),
            "conversation_fingerprint": conversation_fingerprint,
            "evidence": "TaShuo mac-ios-app current thread visual identity.",
        },
        "profile_observation": _profile_observation_from_cached_target(cached_target, visible_name=visible_name),
        "conversation_observation": {
            "visible_messages": normalized_messages,
            "input_state": "empty",
            "thread_cues": _thread_cues(normalized_messages),
            "latest_inbound_messages": latest_inbound,
        },
        "element_observations": [],
        "exception_state": "none",
        "provenance": {
            "app_id": app_id,
            "runtime": "mac-ios-app",
            "source": "standalone_live_gui",
            "evidence": "TaShuo mac-ios-app conversation screenshot analyzed by standalone vision backend.",
            "redaction_status": "structured_no_raw_screenshot",
        },
        "raw_ref": None,
    }
    has_latest_inbound = bool(latest_inbound_text)
    thread_item = {
        "schema_version": 1,
        "status": "ok",
        "observation_type": "thread",
        "app_id": app_id,
        "runtime": "mac-ios-app",
        "candidate_key": candidate_key,
        "assessment": {
            "schema_version": 1,
            "latest_match_message": latest_inbound_text,
            "latest_user_message": _latest_user_message(normalized_messages),
            "latest_inbound_fingerprint": latest_inbound_fingerprint,
            "reply_window_status": "open" if has_latest_inbound else "closed",
            "continuation_opportunity": "yes" if has_latest_inbound else "no",
            "appointment_stage": "none",
            "recommended_next": "reply" if has_latest_inbound else "wait",
            "confidence": "medium" if has_latest_inbound else "low",
            "evidence": "Latest visible TaShuo inbound message supports a conservative reply."
            if has_latest_inbound
            else "No visible inbound message was available for a reply.",
            "risk_flags": [],
        },
        "planner_assessment": _planner_assessment_from_messages(normalized_messages, latest_inbound_text=latest_inbound_text),
        "observation": observation,
        "identity_confidence": _identity_confidence(identity, cached_target),
        "identity_evidence": "Current thread visual identity was compared with cached message-list target.",
        "target_binding": _target_binding(
            identity=identity,
            cached_target=cached_target,
            candidate_key=candidate_key,
            observation_id=observation_id,
            conversation_fingerprint=conversation_fingerprint,
            latest_inbound_fingerprint=latest_inbound_fingerprint,
        ),
    }
    return thread_item


def _normalize_visible_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        text = str(message.get("text") or "").strip()
        if not text:
            continue
        sender = _sender_from_direction(message.get("direction") or message.get("sender"))
        if sender is None:
            continue
        item = {"sender": sender, "text": text}
        confidence = str(message.get("confidence") or "").strip()
        if confidence in {"low", "medium", "high"}:
            item["confidence"] = confidence
        normalized.append(item)
    return normalized


def _sender_from_direction(value: Any) -> str | None:
    direction = str(value or "").strip()
    if direction in {"inbound", "match"}:
        return "match"
    if direction in {"outbound", "user"}:
        return "user"
    if direction in {"system", "unknown"}:
        return "system"
    return None


def _latest_inbound_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    latest_user_index = -1
    for index, message in enumerate(messages):
        if message.get("sender") == "user":
            latest_user_index = index
    return [
        {"sender": "match", "text": str(message.get("text") or "")}
        for message in messages[latest_user_index + 1 :]
        if message.get("sender") == "match" and str(message.get("text") or "").strip()
    ]


def _latest_user_message(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("sender") == "user" and str(message.get("text") or "").strip():
            return str(message["text"])
    return ""


def _planner_assessment_from_messages(
    messages: list[dict[str, str]],
    *,
    latest_inbound_text: str,
) -> dict[str, Any]:
    has_latest_inbound = bool(latest_inbound_text.strip())
    current_topic = "latest visible TaShuo turn" if has_latest_inbound else "no visible inbound turn"
    return {
        "schema_version": 1,
        "latest_turn_summary": latest_inbound_text[:80] if has_latest_inbound else "没有可见的最新对方消息",
        "latest_turn_type": "message" if has_latest_inbound else "none",
        "inbound_intent": "continue_chat" if has_latest_inbound else "none",
        "topic": {
            "current_topic": current_topic,
            "topic_state": "active" if has_latest_inbound else "stale",
            "new_information": [latest_inbound_text] if has_latest_inbound else [],
            "stale_hooks": [],
        },
        "scores": {
            "engagement": 55 if has_latest_inbound else 10,
            "warmth": 50 if has_latest_inbound else 10,
            "curiosity": 45 if _looks_like_question(latest_inbound_text) else 30,
            "comfort": 50 if has_latest_inbound else 10,
            "momentum": 55 if has_latest_inbound else 10,
            "topic_saturation": 20 if has_latest_inbound else 80,
            "logistics_readiness": 10,
            "risk": 10 if has_latest_inbound else 20,
        },
        "recommended_stage": "warmup",
        "recommended_move": "answer_or_riff" if has_latest_inbound else "wait",
        "next_milestone": "接住对方最新一句，保持轻松自然，不推进邀约或交换联系方式。"
        if has_latest_inbound
        else "等待新的对方消息或重新观察线程。",
        "avoid_next": ["直接邀约", "索要联系方式", "提及系统或自动化"],
        "soft_invite_allowed": False,
        "confidence": "medium" if has_latest_inbound else "low",
        "evidence": f"Visible thread has {len(messages)} normalized message(s).",
        "reciprocity": {
            "question_debt": 0,
            "self_disclosure_debt": 0,
            "reciprocity_balance": "unknown",
            "low_investment_streak": 0,
            "match_curiosity_about_user": "mixed" if has_latest_inbound else "unknown",
            "topic_exit_pressure": "low" if has_latest_inbound else "high",
            "last_user_turn_type": "unknown",
        },
    }


def _target_binding(
    *,
    identity: dict[str, Any],
    cached_target: dict[str, Any] | None,
    candidate_key: str,
    observation_id: str,
    conversation_fingerprint: str,
    latest_inbound_fingerprint: str,
) -> dict[str, Any]:
    cached_target = cached_target or {}
    tap_ratio = cached_target.get("tap_ratio") if isinstance(cached_target.get("tap_ratio"), dict) else None
    region = _visual_anchor_region_from_source(cached_target)
    list_anchor = str(cached_target.get("visual_anchor_hash") or "").strip()
    thread_anchor = str(identity.get("visual_anchor_hash") or "").strip()
    thread_region = _visual_anchor_region_from_source(identity)
    binding = {
        "schema_version": 1,
        "binding_type": "current_thread_visual_identity",
        "candidate_key": candidate_key,
        "visible_name": identity.get("visible_name") or cached_target.get("visible_name"),
        "conversation_fingerprint": conversation_fingerprint,
        "thread_evidence": {
            "observation_id": observation_id,
            "screen_state": "tashuo_conversation",
            "latest_inbound_fingerprint": latest_inbound_fingerprint,
            "visual_anchor_hash": thread_anchor,
            "visual_anchor_region": thread_region,
            "visual_anchor_grid_size": identity.get("visual_anchor_grid_size"),
            "source": identity.get("visual_anchor_source") or "standalone_vision_conversation",
        },
        "message_list_evidence": {
            "evidence_type": "message_list_visual_anchor",
            "visual_anchor_hash": list_anchor,
            "visual_anchor_region": region,
            "tap_ratio": dict(tap_ratio) if tap_ratio else None,
            "selection_method": "standalone_vision_message_list_row",
        },
    }
    return binding


def _visual_anchor_region_from_source(source: dict[str, Any]) -> dict[str, float] | None:
    region = source.get("visual_anchor_region") if isinstance(source.get("visual_anchor_region"), dict) else None
    if region is None:
        return None
    try:
        x1 = float(region["x1"])
        y1 = float(region["y1"])
        x2 = float(region["x2"])
        y2 = float(region["y2"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        return None
    return {"x1": round(x1, 4), "y1": round(y1, 4), "x2": round(x2, 4), "y2": round(y2, 4)}


def _profile_observation_from_cached_target(cached_target: dict[str, Any] | None, *, visible_name: str) -> dict[str, Any]:
    latest_preview = str((cached_target or {}).get("latest_preview") or "").strip()
    display_name = "" if _is_synthetic_message_list_visible_name(visible_name) else visible_name
    profile_text = (
        f"TaShuo visible thread/list context for {display_name}: latest preview {latest_preview}"
        if latest_preview
        else f"TaShuo visible thread/list context for {display_name or 'current thread'}."
    )
    return {
        "profile_text": profile_text,
        "photo_cues": [],
        "hook_candidates": [latest_preview] if latest_preview else [],
        "review_status": "observed",
        "evidence": "No profile page was opened; this is limited visible thread/list context for target readiness.",
    }


def _profile_cues_from_cached_target(cached_target: dict[str, Any] | None) -> list[str]:
    latest_preview = str((cached_target or {}).get("latest_preview") or "").strip()
    return [latest_preview] if latest_preview else []


def _thread_cues(messages: list[dict[str, str]]) -> list[str]:
    cues: list[str] = []
    if any(message.get("sender") == "match" for message in messages):
        cues.append("visible inbound message")
    if any(_looks_like_question(str(message.get("text") or "")) for message in messages if message.get("sender") == "match"):
        cues.append("match asked a question")
    return cues


def _looks_like_question(text: str) -> bool:
    value = text.strip()
    return bool(value.endswith("?") or value.endswith("？") or any(token in value for token in ("吗", "呢", "么", "什么", "怎么", "哪")))


def _conversation_confidence(messages: list[dict[str, Any]]) -> str:
    confidences = [str(message.get("confidence") or "") for message in messages if isinstance(message, dict)]
    if confidences and all(item == "high" for item in confidences):
        return "high"
    if any(item in {"high", "medium"} for item in confidences):
        return "medium"
    return "low"


def _identity_confidence(identity: dict[str, Any], cached_target: dict[str, Any] | None) -> str:
    if cached_target and identity.get("visible_name"):
        return "high"
    if identity.get("visible_name") or cached_target:
        return "medium"
    return "low"


def _observation_id(*, app_id: str, candidate_key: str, fingerprint: str) -> str:
    digest = hashlib.sha256(f"{app_id}|{candidate_key}|{fingerprint}".encode("utf-8")).hexdigest()[:16]
    return f"obs_{app_id}_standalone_{digest}"


def _messages_fingerprint_payload(messages: list[dict[str, str]]) -> str:
    return "|".join(f"{message.get('sender')}:{message.get('text')}" for message in messages)


def _stable_text_hash(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


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


def _target_freshness_block_reason(target: dict[str, Any]) -> str | None:
    age_seconds = _target_age_seconds(target)
    if age_seconds is None or age_seconds > _target_cache_max_age_seconds(target):
        return "tashuo_standalone_target_stale"
    return None


def _target_cache_max_age_seconds(target: dict[str, Any]) -> int:
    if _target_has_relocatable_visual_anchor(target):
        return TARGET_VISUAL_ANCHOR_CACHE_MAX_AGE_SECONDS
    return TARGET_CACHE_MAX_AGE_SECONDS


def _target_has_relocatable_visual_anchor(target: dict[str, Any]) -> bool:
    return bool(str(target.get("visual_anchor_hash") or "").strip() and _visual_anchor_region_from_source(target))


def _target_age_seconds(target: dict[str, Any]) -> float | None:
    observed_at = str(target.get("observed_at") or "").strip()
    if not observed_at:
        return None
    try:
        parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()


def _normalized_visible_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text)
    notification_match = re.search(r"不要让(.{1,40}?)等太久", compact)
    if notification_match:
        candidate = notification_match.group(1).strip("，。,.!！?？：:、|")
        if candidate and "喜欢你的人" not in candidate:
            return candidate
    return text


def _visible_name_identity_conflict(
    expected: Any,
    perceived: Any,
    *,
    cached_target: dict[str, Any] | None = None,
    visible_messages: Any = None,
) -> bool:
    expected_name = _normalized_visible_name(expected)
    perceived_name = _normalized_visible_name(perceived)
    if not expected_name or not perceived_name:
        return False
    if _is_synthetic_message_list_visible_name(expected_name) or _is_synthetic_message_list_visible_name(perceived_name):
        return False
    if expected_name == perceived_name:
        return False
    if _cjk_visible_name_ocr_near_match(expected_name, perceived_name):
        return False
    if cached_target and _latest_preview_corroborates_thread(cached_target, visible_messages):
        return False
    return True


def _is_synthetic_message_list_visible_name(value: Any) -> bool:
    text = str(value or "").strip()
    return text.startswith(SYNTHETIC_MESSAGE_LIST_VISIBLE_NAME_PREFIX)


def _cjk_visible_name_ocr_near_match(expected: str, perceived: str) -> bool:
    if len(expected) != len(perceived) or len(expected) < 3:
        return False
    if not all(_is_cjk_character(char) for char in f"{expected}{perceived}"):
        return False
    mismatches = sum(1 for left, right in zip(expected, perceived, strict=True) if left != right)
    if mismatches != 1:
        return False
    return expected[0] == perceived[0] and expected[-1] == perceived[-1]


def _is_cjk_character(value: str) -> bool:
    if len(value) != 1:
        return False
    codepoint = ord(value)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )


def _latest_preview_corroborates_thread(cached_target: dict[str, Any], visible_messages: Any) -> bool:
    preview = _identity_text_key(cached_target.get("latest_preview"))
    if len(preview) < 8:
        return False
    if not isinstance(visible_messages, list):
        return False
    for message in visible_messages:
        if not isinstance(message, dict):
            continue
        text = _identity_text_key(message.get("text"))
        if len(text) < 8:
            continue
        if preview in text or text in preview:
            return True
    return False


def _identity_text_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    for token in ("[草稿]", "【草稿】", "草稿", "...", "…"):
        text = text.replace(token, "")
    return "".join(char for char in text if not char.isspace() and char not in "，。！？、,.!?;；:：")


def _blocked(reason: str, *, app_id: str, **extra: Any) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason, "app_id": app_id, "runtime": "mac-ios-app", **extra}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
