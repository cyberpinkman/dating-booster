from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from dating_boost.apps.registry import create_adapter
from dating_boost.apps.tashuo.message_list_grounding import ground_message_list_rows
from dating_boost.apps.tashuo.message_list_anchor_selection import _same_image, resolve_native_anchor_misses
from dating_boost.apps.tashuo.perception import analyze_tashuo_conversation
from dating_boost.apps.tashuo.standalone_common import (
    TARGET_CACHE_PATH, TARGET_CACHE_MAX_AGE_SECONDS, TARGET_VISUAL_ANCHOR_CACHE_MAX_AGE_SECONDS, SYNTHETIC_MESSAGE_LIST_VISIBLE_NAME_PREFIX,
    _blocked, _identity_text_key, _is_cjk_character, _is_synthetic_message_list_visible_name,
    _latest_preview_corroborates_thread, _normalized_visible_name, _now_iso, _stable_text_hash,
    _visible_name_identity_conflict, _visual_anchor_region_from_source,
)
from dating_boost.apps.tashuo.standalone_message_list import (
    _attach_tashuo_message_list_perceptual_anchors,
    _candidate_type_from_visual_row, _dedupe_tashuo_message_list_rows,
    _looks_like_tashuo_action_artifact, _looks_like_tashuo_non_chat_gate, _message_list_entry_from_visual_row,
    _open_conversation_target_options, _redacted_skipped_visual_row, _redacted_step_result,
    _screen_path_from_observation, _tashuo_message_list_duplicate_key,
    _tashuo_message_list_visual_row_skip_reason,
)
from dating_boost.apps.tashuo.standalone_stage_rules import (
    _current_latest_inbound_fingerprint, _current_thread_binding_evidence_mismatch, _current_thread_visible_name_continuity_allowed, _is_current_thread_candidate_key,
    _message_list_evidence_from_target, _stage_candidate_key, _stage_evidence, _stage_expected_visible_name,
    _stage_target_blocked, _stage_target_identity_mismatch, _stage_work_item_block_reason, _staged_text_verified,
    _target_age_seconds, _target_cache_max_age_seconds, _target_freshness_block_reason, _target_has_relocatable_visual_anchor,
)
from dating_boost.apps.tashuo.standalone_target_cache import TaShuoStandaloneTargetCache
from dating_boost.apps.tashuo.standalone_thread import (
    _conversation_confidence, _identity_confidence, _latest_inbound_messages, _latest_user_message,
    _looks_like_question, _messages_fingerprint_payload, _normalize_visible_messages, _observation_id,
    _planner_assessment_from_messages, _profile_cues_from_cached_target, _profile_observation_from_cached_target, _sender_from_direction,
    _target_binding, _thread_cues, _thread_observation_from_perception,
)
from dating_boost.apps.tashuo.standalone_vision import (
    _analyze_tashuo_conversation_with_retry,
    _analyze_tashuo_message_list_with_retry,
    _analyze_tashuo_vision_with_retry,
    _is_retryable_vision_timeout,
)
from dating_boost.core.safety import SafetyRepository
from dating_boost.core.standalone_actions import StageOnlyActionExecutor
from dating_boost.intelligence.vision_backends import VisionBackend


@dataclass(frozen=True)
class TaShuoObservationCapture:
    """Captured pixels and navigation context; analysis performs no GUI work."""

    app_id: str
    observed: dict[str, Any]
    image_digest: str | None
    scan_cursor: dict[str, Any] | None = None
    candidate_key: str = "current_thread"
    cached_target: dict[str, Any] | None = None
    frame: dict[str, Any] | None = None


def _capture_image_digest(observed: dict[str, Any]) -> str | None:
    path = _screen_path_from_observation(observed)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path is not None else None


def _capture_image_unchanged(capture: TaShuoObservationCapture) -> bool:
    path = _screen_path_from_observation(capture.observed)
    return capture.image_digest is None or (path is not None and _same_image(path, capture.image_digest))


class TaShuoMacIosStandaloneObservationProvider:
    def __init__(
        self,
        *,
        root: Path,
        output_dir: Path,
        vision_backend: VisionBackend,
        adapter_factory: Callable[[], Any] | None = None,
        thread_capture: Callable[[], dict[str, Any]] | None = None,
    ):
        self.root = root
        self.output_dir = output_dir
        self.vision_backend = vision_backend
        self.adapter_factory = adapter_factory or (lambda: create_adapter("tashuo", runtime="mac-ios-app"))
        self.thread_capture = thread_capture
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
        capture = self.capture_message_list(app_id=app_id, scan_cursor=scan_cursor)
        return self.publish_message_list(self.analyze_message_list(capture))

    def capture_message_list(self, *, app_id: str, scan_cursor: dict[str, Any]) -> TaShuoObservationCapture:
        if app_id != "tashuo":
            precheck = _blocked("unsupported_app_for_tashuo_provider", app_id=app_id, observation_type="message_list")
        else:
            precheck = self.precheck_payload(app_id=app_id)
        try:
            image_digest = _capture_image_digest(precheck) if precheck.get("status") == "ok" else None
        except OSError:
            precheck = _blocked("tashuo_message_list_image_unavailable", app_id=app_id, observation_type="message_list")
            image_digest = None
        return TaShuoObservationCapture(app_id, precheck, image_digest, scan_cursor=dict(scan_cursor))

    def analyze_message_list(self, capture: TaShuoObservationCapture) -> dict[str, Any]:
        app_id, precheck = capture.app_id, capture.observed
        if precheck.get("status") != "ok":
            return {**precheck, "observation_type": "message_list"}
        if not _capture_image_unchanged(capture):
            return _blocked("tashuo_message_list_image_changed", app_id=app_id, observation_type="message_list")
        screen_path = _screen_path_from_observation(precheck)
        image_digest = capture.image_digest
        perceived = _analyze_tashuo_message_list_with_retry(precheck, backend=self.vision_backend)
        if perceived.get("status") != "ok":
            return {**perceived, "observation_type": "message_list", "app_id": app_id, "runtime": "mac-ios-app"}
        # OCR only grounds identities already extracted by vision, once for the
        # same saved screenshot. It never discovers or reads conversations.
        session = getattr(self.adapter_factory(), "session", None)
        ocr_tsv = getattr(session, "_ocr_tsv", None)
        native_ocr_tsv = getattr(session, "_native_ocr_tsv", None)
        native_ocr_available = callable(native_ocr_tsv)
        native_payload: dict[str, Any] | None = None

        def read_native_once(path: Path) -> dict[str, Any]:
            nonlocal native_payload
            if not callable(native_ocr_tsv):
                return {"status": "unavailable", "backend": "apple_vision"}
            native_payload = native_ocr_tsv(path)
            return native_payload

        grounding = ground_message_list_rows(
            perceived["rows"],
            screen_path=screen_path,
            ocr_tsv=read_native_once if native_ocr_available else (
                (lambda path: ocr_tsv(path, segmentation_mode=6, allow_language_fallback=False)) if callable(ocr_tsv) else None
            ),
            sparse_ocr_tsv=(lambda path: ocr_tsv(path, segmentation_mode=11, allow_language_fallback=False)) if callable(ocr_tsv) and not native_ocr_available else None,
        )
        if native_ocr_available:
            grounding = resolve_native_anchor_misses(
                grounding, original_rows=perceived["rows"], screen_path=screen_path,
                native_payload=native_payload, backend=self.vision_backend,
                image_digest=image_digest,
            )
        rows = _attach_tashuo_message_list_perceptual_anchors(
            grounding.rows,
            screen_path=screen_path,
        )
        # The app writes successive captures to the same path. Only publish
        # anchors when the final pixels also belong to the initial visual read.
        if screen_path is not None and image_digest is not None and not _same_image(screen_path, image_digest):
            return _blocked("tashuo_message_list_image_changed", app_id=app_id, observation_type="message_list")
        rows, duplicate_rows = _dedupe_tashuo_message_list_rows(rows)
        candidates = []
        entries = []
        skipped_rows = [*grounding.skipped, *duplicate_rows]
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
            candidates.append(row)
            entries.append(_message_list_entry_from_visual_row(row, position=index))
        result = {
            "schema_version": 1,
            "status": "ok",
            "observation_type": "message_list",
            "app_id": app_id,
            "runtime": "mac-ios-app",
            "scan_cursor": dict(capture.scan_cursor or {}),
            "message_list_snapshot": {"entries": entries},
            "candidates": candidates,
            "provenance": {"app_id": app_id, "runtime": "mac-ios-app", "source": "standalone_live_gui"},
            "message_list_grounding": {**grounding.summary, "backend": "apple_vision"} if native_ocr_available else grounding.summary,
        }
        if skipped_rows:
            if provider_skipped_row:
                warnings.append("tashuo_message_list_visual_row_skipped")
            if duplicate_rows:
                warnings.append("tashuo_message_list_duplicate_visual_row_skipped")
            if grounding.skipped:
                warnings.append("tashuo_message_list_ambiguous_name_location_skipped")
            result["warnings"] = list(dict.fromkeys(warnings))
            result["skipped_candidates"] = skipped_rows
        elif warnings:
            result["warnings"] = list(dict.fromkeys(warnings))
        return result

    def publish_message_list(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Publish only after the owning ManagedRun accepts its lifecycle revision."""
        if payload.get("status") == "ok":
            for row in payload["candidates"]:
                self.targets.put(row)
        return payload

    def observe_thread(self, *, app_id: str, candidate_key: str) -> dict[str, Any]:
        return self.analyze_thread(self.capture_thread(app_id=app_id, candidate_key=candidate_key))

    def capture_thread(self, *, app_id: str, candidate_key: str) -> TaShuoObservationCapture:
        target = self.targets.get(candidate_key)
        if target is None:
            if _is_current_thread_candidate_key(candidate_key):
                return self._capture_current_thread(app_id=app_id, candidate_key=candidate_key, cached_target=None)
            blocked = _blocked(
                "tashuo_standalone_target_not_found",
                app_id=app_id,
                observation_type="thread",
                candidate_key=candidate_key,
            )
            return TaShuoObservationCapture(app_id, blocked, None, candidate_key=candidate_key)
        freshness_reason = _target_freshness_block_reason(target)
        if freshness_reason:
            max_age_seconds = _target_cache_max_age_seconds(target)
            blocked = _blocked(
                freshness_reason,
                app_id=app_id,
                observation_type="thread",
                candidate_key=candidate_key,
                observed_at=target.get("observed_at"),
                max_age_seconds=max_age_seconds,
            )
            return TaShuoObservationCapture(app_id, blocked, None, candidate_key=candidate_key)
        adapter = self.adapter_factory()
        opened = adapter.run_action(
            "open-conversation",
            dry_run=False,
            output_dir=self.output_dir,
            **_open_conversation_target_options(target),
        )
        if opened.get("status") != "ok":
            blocked = _blocked(
                str(opened.get("reason") or "open_thread_failed"),
                app_id=app_id,
                observation_type="thread",
                candidate_key=candidate_key,
            )
            return TaShuoObservationCapture(app_id, blocked, None, candidate_key=candidate_key)
        return self._capture_current_thread(app_id=app_id, candidate_key=candidate_key, cached_target=target)

    def observe_current_thread(
        self,
        *,
        app_id: str,
        candidate_key: str = "current_thread",
        cached_target: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.analyze_thread(self._capture_current_thread(
            app_id=app_id, candidate_key=candidate_key, cached_target=cached_target,
        ))

    def _capture_current_thread(
        self, *, app_id: str, candidate_key: str, cached_target: dict[str, Any] | None,
    ) -> TaShuoObservationCapture:
        frame = self.thread_capture() if self.thread_capture is not None else None
        if frame is not None:
            observed = {
                **frame,
                "screen": {"status": frame.get("status"), "path": frame.get("path"), "state": frame.get("state")},
            }
        else:
            observed = self.adapter_factory().observe(output_dir=self.output_dir)
        try:
            image_digest = _capture_image_digest(observed) if observed.get("status") == "ok" else None
        except OSError:
            observed = _blocked("tashuo_thread_image_unavailable", app_id=app_id, observation_type="thread")
            image_digest = None
        return TaShuoObservationCapture(
            app_id, observed, image_digest, candidate_key=candidate_key, cached_target=cached_target, frame=frame,
        )

    def analyze_thread(self, capture: TaShuoObservationCapture) -> dict[str, Any]:
        app_id, candidate_key = capture.app_id, capture.candidate_key
        observed, cached_target, frame = capture.observed, capture.cached_target, capture.frame
        if observed.get("status") != "ok":
            return _blocked(
                str(observed.get("reason") or "observe_thread_failed"),
                app_id=app_id,
                observation_type="thread",
                candidate_key=candidate_key,
            )
        if not _capture_image_unchanged(capture):
            return _blocked("tashuo_thread_image_changed", app_id=app_id, observation_type="thread", candidate_key=candidate_key)
        perceived = _analyze_tashuo_conversation_with_retry(observed, backend=self.vision_backend)
        if not _capture_image_unchanged(capture):
            return _blocked("tashuo_thread_image_changed", app_id=app_id, observation_type="thread", candidate_key=candidate_key)
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
        result = _thread_observation_from_perception(
            app_id=app_id,
            candidate_key=candidate_key,
            identity=identity,
            visible_messages=perceived["visible_messages"],
            cached_target=cached_target,
        )
        if frame is not None:
            result["managed_visual_frame"] = frame
        return result

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
