from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from dating_boost.core.live_send_contract import live_send_authorization_quiet_hours_block_reason
from dating_boost.core.managed_run import (
    ClickReceipt,
    ComposerObservation,
    DraftDecision,
    JsonManagedRunStore,
    ManagedRun,
    ManagedRunConfig,
    MessageListSnapshot,
    OpenThreadObservation,
    PostSendObservation,
    ThreadCandidate,
    ThreadObservation,
)
from dating_boost.core.standalone_observation import FixtureObservationProvider
from dating_boost.core.standalone_runtime import StandaloneDraftPlanner
from dating_boost.core.user_disclosure import UserDisclosureRepository


MANAGED_RUN_FIXTURE_DIR_ENV = "DATING_BOOST_MANAGED_RUN_FIXTURE_DIR"
MANAGED_RUN_SCRIPTED_BACKEND_ENV = "DATING_BOOST_MANAGED_RUN_SCRIPTED_BACKEND_OUTPUT"
MANAGED_RUN_TASHUO_CONFIG_ENV = "DATING_BOOST_MANAGED_RUN_TASHUO_CONFIG"

# The legacy all-in-one send_message remains for host-loop compatibility.
# ManagedRun uses the separate adapter seam below so its durable
# prepared_to_click checkpoint always precedes the Return-only boundary.
MANAGED_LIVE_ACTION_PORT_STATUS = "managed_live_action_port_not_available"
MANAGED_LIVE_ACTION_REQUIRED_SEAM = (
    "observe_composer",
    "stage_and_verify_exact_text",
    "click_send_only",
    "observe_fresh_post_send",
)


class ManagedRunProviderRuntime:
    """Lifecycle-safe facade around a configured or unconfigured ManagedRun.

    The CLI rebuilds this object for every command.  Status/pause/resume/stop
    therefore remain available without provider environment variables, while
    start/tick/run fail before creating or mutating an unusable run.
    """

    def __init__(
        self,
        runtime: ManagedRun,
        *,
        provider_kind: str,
        runnable: bool,
        unavailable_reason: str = "managed_run_runtime_not_configured",
        start_precondition: Callable[[], dict[str, Any] | None] | None = None,
    ):
        self.runtime = runtime
        self.store = runtime.store
        self.provider_kind = provider_kind
        self.runnable = runnable
        self.unavailable_reason = unavailable_reason
        self.start_precondition = start_precondition

    def current_run_id(self) -> str | None:
        return self.runtime.current_run_id()

    def start(self, config: ManagedRunConfig | Mapping[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
        if not isinstance(config, ManagedRunConfig):
            config = ManagedRunConfig.from_dict(config)
        quiet_hours_reason = live_send_authorization_quiet_hours_block_reason(config.authorization.quiet_hours)
        if quiet_hours_reason is not None:
            return _blocked(quiet_hours_reason, provider_kind=self.provider_kind)
        if not self.runnable:
            return _blocked(self.unavailable_reason, provider_kind=self.provider_kind)
        if self.start_precondition is not None:
            precondition = self.start_precondition()
            if precondition is not None:
                return precondition
        return self.runtime.start(config, run_id=run_id)

    def tick(self, run_id: str | None = None) -> dict[str, Any]:
        if not self.runnable:
            return _blocked(self.unavailable_reason, provider_kind=self.provider_kind, run_id=run_id)
        return self.runtime.tick(run_id)

    def run(
        self,
        run_id: str | None = None,
        *,
        max_steps: int = 50,
        wait: bool = False,
        poll_interval_seconds: float = 1.0,
    ) -> dict[str, Any]:
        if not self.runnable:
            return _blocked(self.unavailable_reason, provider_kind=self.provider_kind, run_id=run_id)
        return self.runtime.run(
            run_id,
            max_steps=max_steps,
            wait=wait,
            poll_interval_seconds=poll_interval_seconds,
        )

    def status(self, run_id: str | None = None) -> dict[str, Any]:
        return self.runtime.status(run_id)

    def pause(self, run_id: str | None = None, *, reason: str = "manual_pause") -> dict[str, Any]:
        return self.runtime.pause(run_id, reason=reason)

    def resume(self, run_id: str | None = None) -> dict[str, Any]:
        return self.runtime.resume(run_id)

    def stop(self, run_id: str | None = None, *, reason: str = "manual_stop") -> dict[str, Any]:
        return self.runtime.stop(run_id, reason=reason)


class UnconfiguredManagedRunPort:
    """Never used for runnable operations; present for durable lifecycle calls."""

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(f"managed_run_runtime_not_configured:{name}")


@dataclass
class _CachedThread:
    raw: dict[str, Any]
    target_id: str
    target_binding: str
    inbound_revision: str
    captured_at: str
    match_id: str | None = None


class StandaloneObservationManagedRunPort:
    """Maps the existing standalone observation contract into ManagedRun ports.

    Fixture mode allows deterministic fixture bindings.  Live mode only accepts
    a message-list visual anchor that is corroborated by the thread provider's
    structured target binding; it never turns a visible name into target proof.
    """

    def __init__(
        self,
        root: Path,
        provider: Any,
        *,
        fixture_mode: bool,
        live_inbound_revision_observer: Callable[[dict[str, Any]], Mapping[str, Any]] | None = None,
    ):
        self.root = root
        self.provider = provider
        self.fixture_mode = fixture_mode
        self.live_inbound_revision_observer = live_inbound_revision_observer
        self._app_id = ""
        self._candidates: dict[str, ThreadCandidate] = {}
        self._opened: dict[str, _CachedThread] = {}

    def scan_message_list(
        self,
        *,
        run_id: str,
        app_id: str,
        runtime: str,
        cursor: dict[str, Any],
    ) -> MessageListSnapshot:
        del run_id
        self._app_id = app_id
        payload = self.provider.observe_message_list(app_id=app_id, scan_cursor=dict(cursor))
        _require_ok_observation(payload, "message_list")
        payload_runtime = str(payload.get("runtime") or runtime)
        if payload_runtime != runtime:
            raise ValueError("managed_observation_runtime_mismatch")
        captured_at = _captured_at(payload)
        entries = _message_list_entries(payload)
        candidates: list[ThreadCandidate] = []
        for position, entry in enumerate(entries, start=1):
            candidate = self._candidate_from_entry(entry, position=position)
            if candidate is None:
                continue
            self._candidates[candidate.candidate_key] = candidate
            candidates.append(candidate)
        return MessageListSnapshot(
            candidates=tuple(candidates),
            captured_at=captured_at,
            next_cursor=_next_cursor(payload),
        )

    def open_thread(self, candidate: ThreadCandidate) -> OpenThreadObservation:
        known = self._candidates.get(candidate.candidate_key)
        if known != candidate:
            raise ValueError("managed_candidate_not_from_latest_scan")
        raw = self.provider.observe_thread(app_id=str(candidate.metadata["app_id"]), candidate_key=candidate.candidate_key)
        _require_ok_observation(raw, "thread")
        cached = self._map_thread(candidate, raw)
        self._opened[candidate.candidate_key] = cached
        return OpenThreadObservation(
            target_id=cached.target_id,
            target_binding=cached.target_binding,
            captured_at=cached.captured_at,
        )

    def observe_thread(self, candidate: ThreadCandidate) -> ThreadObservation:
        cached = self._opened.pop(candidate.candidate_key, None)
        if cached is None:
            raw = self.provider.observe_thread(app_id=str(candidate.metadata["app_id"]), candidate_key=candidate.candidate_key)
            _require_ok_observation(raw, "thread")
            cached = self._map_thread(candidate, raw)
        match_id = self._ingest_for_planner(cached.raw)
        context = {
            "standalone_thread_observation": cached.raw,
            "managed_provider_kind": "fixture" if self.fixture_mode else "tashuo_mac_ios_observation_only",
        }
        if match_id:
            context["match_id"] = match_id
        return ThreadObservation(
            target_id=cached.target_id,
            target_binding=cached.target_binding,
            inbound_revision=cached.inbound_revision,
            captured_at=cached.captured_at,
            context=context,
        )

    def _candidate_from_entry(self, entry: dict[str, Any], *, position: int) -> ThreadCandidate | None:
        candidate_key = _first_string(entry, "candidate_key")
        if not candidate_key:
            return None
        app_id = _first_string(entry, "app_id") or _first_string(entry.get("provenance"), "app_id") or self._app_id
        target_id = _first_string(entry, "target_id", "match_id") or candidate_key
        discovery_revision = _first_string(
            entry,
            "inbound_revision",
            "latest_inbound_fingerprint",
            "latest_preview_hash",
        )
        if not discovery_revision:
            hints = entry.get("match_identity_hints")
            discovery_revision = _first_string(hints, "conversation_fingerprint")
        if not discovery_revision:
            return None

        target_binding: str
        if self.fixture_mode:
            target_binding = _fixture_target_binding(entry, candidate_key=candidate_key)
        else:
            live_target_binding = _live_list_target_binding(entry, candidate_key=candidate_key)
            if live_target_binding is None:
                return None
            target_binding = live_target_binding
        unread = str(entry.get("unread_cue") or "").strip().lower()
        priority = int(entry.get("priority") or (0 if unread in {"present", "true", "unread"} else position))
        return ThreadCandidate(
            candidate_key=candidate_key,
            target_id=target_id,
            target_binding=target_binding,
            discovery_revision=discovery_revision,
            priority=priority,
            metadata={"app_id": app_id, "position": position, "source_entry": dict(entry)},
        )

    def _map_thread(self, candidate: ThreadCandidate, raw: dict[str, Any]) -> _CachedThread:
        raw_candidate_key = _first_string(raw, "candidate_key")
        if raw_candidate_key and raw_candidate_key != candidate.candidate_key:
            raise ValueError("managed_thread_candidate_key_mismatch")
        raw_target_id = _first_string(raw, "target_id", "match_id")
        if raw_target_id and raw_target_id != candidate.target_id:
            raise ValueError("managed_thread_target_id_mismatch")
        if self.fixture_mode:
            raw_binding = raw.get("target_binding")
            if raw_binding is not None and _canonical_binding(raw_binding) != candidate.target_binding:
                raise ValueError("managed_thread_target_binding_mismatch")
        else:
            raw_binding = raw.get("target_binding")
            if not _live_thread_binding_corroborates(candidate, raw_binding):
                raise ValueError("managed_thread_structural_binding_not_corroborated")
            # `ThreadCandidate` is immutable, but its metadata is an intentional
            # run-local evidence cache.  The live action port only accepts the
            # original structured binding after this list-to-thread
            # corroboration succeeds; it never reconstructs evidence from the
            # canonical hash stored in candidate.target_binding.
            verified_binding = json.loads(json.dumps(raw_binding, ensure_ascii=False))
            if self.live_inbound_revision_observer is not None:
                revision_payload = dict(self.live_inbound_revision_observer(verified_binding))
                if revision_payload.get("status") != "ok":
                    raise ValueError(
                        str(revision_payload.get("reason") or "managed_inbound_revision_observation_failed")
                    )
                managed_revision = str(revision_payload.get("inbound_revision") or "").strip()
                revision_observation_id = str(
                    revision_payload.get("inbound_revision_observation_id") or ""
                ).strip()
                if not managed_revision or not revision_observation_id:
                    raise ValueError("managed_inbound_revision_evidence_incomplete")
                thread_evidence = verified_binding.get("thread_evidence")
                if not isinstance(thread_evidence, dict):
                    raise ValueError("managed_thread_evidence_missing")
                thread_evidence["managed_inbound_revision"] = managed_revision
                thread_evidence["managed_inbound_revision_observation_id"] = revision_observation_id
                thread_evidence["managed_inbound_revision_captured_at"] = revision_payload.get(
                    "inbound_revision_captured_at"
                )
                thread_evidence["managed_inbound_revision_source"] = "macos_accessibility_static_text"
                candidate.metadata["managed_inbound_revision"] = managed_revision
            candidate.metadata["verified_target_binding"] = verified_binding

        inbound_revision = _thread_inbound_revision(raw)
        if not inbound_revision:
            raise ValueError("managed_thread_inbound_revision_missing")
        candidate.metadata["verified_inbound_revision"] = inbound_revision
        return _CachedThread(
            raw=dict(raw),
            target_id=candidate.target_id,
            target_binding=candidate.target_binding,
            inbound_revision=inbound_revision,
            captured_at=_captured_at(raw),
        )

    def _ingest_for_planner(self, raw: dict[str, Any]) -> str | None:
        observation = raw.get("observation")
        if not isinstance(observation, dict):
            return None
        from dating_boost.core.memory.ingest import store_observation_with_memory
        from dating_boost.perception.observations import AppObservation

        app_observation = AppObservation.from_dict(observation)
        result = store_observation_with_memory(self.root, app_observation)
        match_id = result.get("match_id")
        return str(match_id) if match_id else None


class StandalonePlannerManagedDecisionPort:
    def __init__(self, planner: StandaloneDraftPlanner, *, action_available: bool = True):
        self.planner = planner
        self.action_available = action_available

    def prioritize(
        self,
        candidates: Sequence[ThreadCandidate],
        *,
        thread_states: Mapping[str, dict[str, Any]],
    ) -> ThreadCandidate | None:
        del thread_states
        return min(candidates, key=lambda item: (item.priority, item.candidate_key)) if candidates else None

    def decide(self, observation: ThreadObservation, *, config: ManagedRunConfig) -> DraftDecision:
        raw = observation.context.get("standalone_thread_observation")
        assessment_value = raw.get("assessment") if isinstance(raw, dict) else None
        assessment: dict[str, Any] = dict(assessment_value) if isinstance(assessment_value, dict) else {}
        recommended = str(assessment.get("recommended_next") or "reply").strip()
        if recommended == "nudge_later":
            nudge_reason = _nudge_wait_reason(assessment, config=config)
            if nudge_reason is not None:
                return DraftDecision(
                    decision_id=_decision_id(observation, "wait"),
                    outcome="wait",
                    target_id=observation.target_id,
                    inbound_revision=observation.inbound_revision,
                    reason_codes=(nudge_reason,),
                )
        if recommended not in {"reply", "nudge_later"}:
            outcome = "handoff" if recommended == "handoff" else "wait"
            return DraftDecision(
                decision_id=_decision_id(observation, outcome),
                outcome=outcome,
                target_id=observation.target_id,
                inbound_revision=observation.inbound_revision,
                reason_codes=(f"standalone_assessment:{recommended or 'wait'}",),
            )
        match_id = str(observation.context.get("match_id") or "").strip()
        if not match_id:
            return DraftDecision(
                decision_id=_decision_id(observation, "handoff"),
                outcome="handoff",
                target_id=observation.target_id,
                inbound_revision=observation.inbound_revision,
                reason_codes=("managed_thread_memory_match_missing",),
            )
        result = self.planner.draft_for_match(match_id=match_id, mode="adaptive")
        if result.get("status") != "ok" or not isinstance(result.get("draft"), dict):
            return DraftDecision(
                decision_id=_decision_id(observation, "handoff"),
                outcome="handoff",
                target_id=observation.target_id,
                inbound_revision=observation.inbound_revision,
                reason_codes=(str(result.get("reason") or "managed_draft_not_available"),),
            )
        draft = result["draft"]
        text = str(draft.get("best_reply") or "").strip()
        if not text:
            return DraftDecision(
                decision_id=_decision_id(observation, "handoff"),
                outcome="handoff",
                target_id=observation.target_id,
                inbound_revision=observation.inbound_revision,
                reason_codes=("managed_draft_text_missing",),
            )
        if not self.action_available:
            return DraftDecision(
                decision_id=_decision_id(observation, text),
                outcome="handoff",
                target_id=observation.target_id,
                inbound_revision=observation.inbound_revision,
                text=text,
                reason_codes=(MANAGED_LIVE_ACTION_PORT_STATUS,),
            )
        return DraftDecision.send(
            decision_id=_decision_id(observation, text),
            target_id=observation.target_id,
            inbound_revision=observation.inbound_revision,
            text=text,
        )


class DevelopmentFixtureActionPort:
    """In-memory stage/click/verify simulator activated only by fixture env vars."""

    def __init__(self) -> None:
        self._composer: dict[str, str] = {}
        self._clicked: dict[str, tuple[str, str]] = {}
        self._clock = datetime.now(timezone.utc)
        self.calls: list[str] = []

    def observe_composer(self, candidate: ThreadCandidate) -> ComposerObservation:
        self.calls.append("observe_composer")
        inbound_revision = _authoritative_candidate_revision(candidate)
        return ComposerObservation(
            target_id=candidate.target_id,
            target_binding=candidate.target_binding,
            inbound_revision=inbound_revision,
            text=self._composer.get(candidate.candidate_key, ""),
            captured_at=self._tick(),
        )

    def stage_text(self, candidate: ThreadCandidate, text: str) -> ComposerObservation:
        self.calls.append("stage_text")
        inbound_revision = _authoritative_candidate_revision(candidate)
        if not text:
            raise ValueError("fixture_stage_text_empty")
        if self._composer.get(candidate.candidate_key, ""):
            raise ValueError("fixture_composer_occupied")
        self._composer[candidate.candidate_key] = text
        return ComposerObservation(
            target_id=candidate.target_id,
            target_binding=candidate.target_binding,
            inbound_revision=inbound_revision,
            text=text,
            captured_at=self._tick(),
        )

    def click_send(self, candidate: ThreadCandidate) -> ClickReceipt:
        self.calls.append("click_send")
        text = self._composer.get(candidate.candidate_key, "")
        if not text:
            raise ValueError("fixture_composer_not_staged")
        receipt_id = f"fixture_receipt_{uuid.uuid4().hex}"
        clicked_at = self._tick()
        self._clicked[receipt_id] = (candidate.candidate_key, text)
        self._composer[candidate.candidate_key] = ""
        return ClickReceipt(receipt_id=receipt_id, clicked_at=clicked_at)

    def observe_post_send(self, candidate: ThreadCandidate, receipt: ClickReceipt) -> PostSendObservation:
        self.calls.append("observe_post_send")
        committed = self._clicked.get(receipt.receipt_id)
        if committed is None or committed[0] != candidate.candidate_key:
            raise ValueError("fixture_click_receipt_mismatch")
        return PostSendObservation(
            observation_id=f"fixture_post_{uuid.uuid4().hex}",
            receipt_id=receipt.receipt_id,
            target_id=candidate.target_id,
            target_binding=candidate.target_binding,
            captured_at=self._tick(),
            input_cleared=self._composer.get(candidate.candidate_key, "") == "",
            outbound_text=committed[1],
        )

    def _tick(self) -> str:
        self._clock += timedelta(milliseconds=1)
        return self._clock.isoformat().replace("+00:00", "Z")


class TaShuoMacIosManagedActionPort:
    """Real TaShuo action port backed by the split mac-ios-app adapter seam."""

    def __init__(self, root: Path, *, output_dir: Path, adapter_factory: Any):
        from dating_boost.core.safety import SafetyRepository

        self.root = root
        self.output_dir = output_dir
        self.adapter_factory = adapter_factory
        self.safety = SafetyRepository(root)
        self._adapter: Any | None = None
        self._last_composer: dict[str, str] = {}
        self._receipts: dict[str, dict[str, Any]] = {}

    @property
    def adapter(self) -> Any:
        if self._adapter is None:
            self._adapter = self.adapter_factory()
        return self._adapter

    def observe_composer(self, candidate: ThreadCandidate) -> ComposerObservation:
        binding = self._verified_binding(candidate)
        inbound_revision = _authoritative_candidate_revision(candidate)
        managed_inbound_revision = self._managed_inbound_revision(binding)
        payload = self.adapter.observe_managed_composer(
            target_binding=binding,
            inbound_revision=managed_inbound_revision,
            output_dir=self.output_dir,
        )
        _require_action_ok(payload, "managed_composer_observation_failed")
        text = str(payload.get("composer_text") or "")
        self._last_composer[candidate.candidate_key] = text
        return ComposerObservation(
            target_id=candidate.target_id,
            target_binding=candidate.target_binding,
            inbound_revision=inbound_revision,
            text=text,
            captured_at=str(payload["captured_at"]),
        )

    def stage_text(self, candidate: ThreadCandidate, text: str) -> ComposerObservation:
        self._require_mutation_allowed()
        binding = self._verified_binding(candidate)
        inbound_revision = _authoritative_candidate_revision(candidate)
        managed_inbound_revision = self._managed_inbound_revision(binding)
        payload = self.adapter.stage_managed_text(
            text,
            target_binding=binding,
            inbound_revision=managed_inbound_revision,
            output_dir=self.output_dir,
        )
        _require_action_ok(payload, "managed_stage_failed")
        if payload.get("staged_exact_text_ax_verified") is not True:
            raise RuntimeError("managed_staged_exact_text_not_verified")
        if payload.get("post_stage_inbound_revision_verified") is not True:
            raise RuntimeError("managed_post_stage_inbound_revision_not_verified")
        captured_at = str(payload.get("captured_at") or "")
        if not captured_at:
            raise RuntimeError("managed_stage_observation_incomplete")
        self._last_composer[candidate.candidate_key] = text
        return ComposerObservation(
            target_id=candidate.target_id,
            target_binding=candidate.target_binding,
            inbound_revision=inbound_revision,
            text=text,
            captured_at=captured_at,
        )

    def click_send(self, candidate: ThreadCandidate) -> ClickReceipt:
        self._require_mutation_allowed()
        binding = self._verified_binding(candidate)
        managed_inbound_revision = self._managed_inbound_revision(binding)
        expected_text = self._last_composer.get(candidate.candidate_key, "")
        if not expected_text:
            raise RuntimeError("managed_expected_composer_text_missing")
        payload = self.adapter.click_managed_send_only(
            expected_text,
            target_binding=binding,
            inbound_revision=managed_inbound_revision,
            output_dir=self.output_dir,
        )
        _require_action_ok(payload, "managed_click_result_unknown")
        receipt_id = str(payload.get("receipt_id") or "")
        clicked_at = str(payload.get("clicked_at") or "")
        if not receipt_id or not clicked_at:
            raise RuntimeError("managed_click_receipt_incomplete")
        self._receipts[receipt_id] = dict(payload)
        return ClickReceipt(receipt_id=receipt_id, clicked_at=clicked_at)

    def observe_post_send(self, candidate: ThreadCandidate, receipt: ClickReceipt) -> PostSendObservation:
        binding = self._verified_binding(candidate)
        managed_inbound_revision = self._managed_inbound_revision(binding)
        expected_text = self._last_composer.get(candidate.candidate_key, "")
        click_payload = self._receipts.get(receipt.receipt_id)
        if not expected_text or click_payload is None:
            # Recovery without the process-local pre-click capture is unknown,
            # never a reason to repeat the irreversible Return action.
            raise RuntimeError("managed_click_receipt_evidence_missing")
        payload = self.adapter.observe_managed_post_send(
            expected_text,
            target_binding=binding,
            inbound_revision=managed_inbound_revision,
            click_receipt=click_payload,
            output_dir=self.output_dir,
        )
        _require_action_ok(payload, "managed_post_send_not_verified")
        if not (
            payload.get("input_cleared") is True
            and payload.get("outbound_exact_text_ax_verified") is True
            and payload.get("fresh_outbound_occurrence_verified") is True
        ):
            raise RuntimeError("managed_post_send_exact_freshness_not_verified")
        return PostSendObservation(
            observation_id=str(payload["post_action_observation_id"]),
            receipt_id=receipt.receipt_id,
            target_id=candidate.target_id,
            target_binding=candidate.target_binding,
            captured_at=str(payload["captured_at"]),
            input_cleared=True,
            outbound_text=expected_text,
        )

    def _verified_binding(self, candidate: ThreadCandidate) -> dict[str, Any]:
        binding = candidate.metadata.get("verified_target_binding")
        revision = str(candidate.metadata.get("verified_inbound_revision") or "")
        if not isinstance(binding, dict):
            raise RuntimeError("managed_structured_target_binding_missing")
        if revision != _authoritative_candidate_revision(candidate):
            raise RuntimeError("managed_structured_target_binding_stale")
        return binding

    @staticmethod
    def _managed_inbound_revision(binding: dict[str, Any]) -> str:
        thread_evidence = binding.get("thread_evidence")
        revision = (
            str(thread_evidence.get("managed_inbound_revision") or "").strip()
            if isinstance(thread_evidence, dict)
            else ""
        )
        if not revision:
            raise RuntimeError("managed_inbound_revision_binding_missing")
        return revision

    def _require_mutation_allowed(self) -> None:
        if self.safety.is_paused():
            raise RuntimeError("global_safety_paused")


def build_managed_run_runtime(
    data_dir: Path,
    *,
    requested_config: ManagedRunConfig | Mapping[str, Any] | None = None,
    require_ports: bool = True,
) -> ManagedRunProviderRuntime:
    """Build the product-default TaShuo runtime, a development fixture, or a lifecycle facade.

    Fixture and TaShuo live execution remain disjoint so a simulated action
    port cannot be mistaken for the real GUI seam.
    """

    fixture_dir_raw = str(os.environ.get(MANAGED_RUN_FIXTURE_DIR_ENV) or "").strip()
    scripted_output_raw = str(os.environ.get(MANAGED_RUN_SCRIPTED_BACKEND_ENV) or "").strip()
    tashuo_config_raw = str(os.environ.get(MANAGED_RUN_TASHUO_CONFIG_ENV) or "").strip()
    store = JsonManagedRunStore(data_dir)
    if not require_ports:
        port = UnconfiguredManagedRunPort()
        return ManagedRunProviderRuntime(
            ManagedRun(store, port, port, port),
            provider_kind="lifecycle_only",
            runnable=False,
        )
    if tashuo_config_raw and (fixture_dir_raw or scripted_output_raw):
        port = UnconfiguredManagedRunPort()
        return ManagedRunProviderRuntime(
            ManagedRun(store, port, port, port),
            provider_kind="conflicting_configuration",
            runnable=False,
            unavailable_reason="managed_run_provider_configuration_conflict",
        )
    if tashuo_config_raw:
        return _build_tashuo_managed_run_runtime(data_dir, Path(tashuo_config_raw), store=store)
    if not fixture_dir_raw and not scripted_output_raw:
        live_config = _default_tashuo_live_config(requested_config, data_dir=data_dir, store=store)
        if live_config is not None:
            return _build_tashuo_managed_run_from_config(data_dir, live_config, store=store)
        port = UnconfiguredManagedRunPort()
        return ManagedRunProviderRuntime(
            ManagedRun(store, port, port, port),
            provider_kind="unconfigured",
            runnable=False,
        )
    if not fixture_dir_raw or not scripted_output_raw:
        port = UnconfiguredManagedRunPort()
        return ManagedRunProviderRuntime(
            ManagedRun(store, port, port, port),
            provider_kind="fixture",
            runnable=False,
            unavailable_reason="managed_run_fixture_configuration_incomplete",
        )

    fixture_dir = Path(fixture_dir_raw).expanduser().resolve()
    scripted_output = Path(scripted_output_raw).expanduser().resolve()
    if not fixture_dir.is_dir():
        raise FileNotFoundError("managed_run_fixture_dir_not_found")
    if not scripted_output.is_file():
        raise FileNotFoundError("managed_run_scripted_backend_output_not_found")
    provider = FixtureObservationProvider(fixture_dir)
    observation = StandaloneObservationManagedRunPort(data_dir, provider, fixture_mode=True)
    decision = StandalonePlannerManagedDecisionPort(
        StandaloneDraftPlanner(
            data_dir,
            backend_config={"type": "scripted", "model": "scripted", "path": str(scripted_output)},
        )
    )
    action = DevelopmentFixtureActionPort()
    return ManagedRunProviderRuntime(
        ManagedRun(store, observation, decision, action),
        provider_kind="development_fixture",
        runnable=True,
    )


def _build_tashuo_managed_run_runtime(
    data_dir: Path,
    config_path: Path,
    *,
    store: JsonManagedRunStore,
) -> ManagedRunProviderRuntime:
    port = UnconfiguredManagedRunPort()
    resolved_config_path = config_path.expanduser().resolve()
    if not resolved_config_path.is_file():
        return ManagedRunProviderRuntime(
            ManagedRun(store, port, port, port),
            provider_kind="tashuo_mac_ios_live",
            runnable=False,
            unavailable_reason="managed_run_tashuo_config_not_found",
        )
    try:
        config = json.loads(resolved_config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        config = None
    if not isinstance(config, dict):
        return ManagedRunProviderRuntime(
            ManagedRun(store, port, port, port),
            provider_kind="tashuo_mac_ios_live",
            runnable=False,
            unavailable_reason="managed_run_tashuo_config_invalid",
        )
    return _build_tashuo_managed_run_from_config(data_dir, config, store=store)


def _build_tashuo_managed_run_from_config(
    data_dir: Path,
    config: Mapping[str, Any],
    *,
    store: JsonManagedRunStore,
) -> ManagedRunProviderRuntime:
    port = UnconfiguredManagedRunPort()
    if str(config.get("app_id") or "") != "tashuo" or str(config.get("runtime") or "") != "mac-ios-app":
        return ManagedRunProviderRuntime(
            ManagedRun(store, port, port, port),
            provider_kind="tashuo_mac_ios_live",
            runnable=False,
            unavailable_reason="managed_run_tashuo_config_scope_invalid",
        )
    vision_config = config.get("vision_backend")
    backend_config = config.get("backend")
    if not isinstance(vision_config, dict) or not vision_config or not isinstance(backend_config, dict) or not backend_config:
        return ManagedRunProviderRuntime(
            ManagedRun(store, port, port, port),
            provider_kind="tashuo_mac_ios_live",
            runnable=False,
            unavailable_reason="managed_run_tashuo_model_configuration_required",
        )

    from dating_boost.apps.registry import create_adapter
    from dating_boost.core.runtime_scope import RuntimeScopeRepository
    from dating_boost.intelligence.vision_backend_factory import create_vision_backend

    scope_block = RuntimeScopeRepository(data_dir).validate(
        app_id="tashuo",
        runtime="mac-ios-app",
        require_selected=True,
    )
    if scope_block is not None:
        return ManagedRunProviderRuntime(
            ManagedRun(store, port, port, port),
            provider_kind="tashuo_mac_ios_live",
            runnable=False,
            unavailable_reason=str(scope_block.get("reason") or "runtime_scope_required"),
        )
    try:
        vision_backend = create_vision_backend(dict(vision_config))
    except (FileNotFoundError, RuntimeError, ValueError):
        return ManagedRunProviderRuntime(
            ManagedRun(store, port, port, port),
            provider_kind="tashuo_mac_ios_live",
            runnable=False,
            unavailable_reason="managed_run_tashuo_vision_backend_unavailable",
        )
    output_dir = Path(config.get("output_dir") or data_dir / "managed_harness").expanduser().resolve()

    def adapter_factory() -> Any:
        return create_adapter("tashuo", runtime="mac-ios-app")

    from dating_boost.apps.tashuo.standalone import TaShuoMacIosStandaloneObservationProvider

    provider = TaShuoMacIosStandaloneObservationProvider(
        root=data_dir,
        output_dir=output_dir,
        vision_backend=vision_backend,
        adapter_factory=adapter_factory,
    )

    def observe_live_inbound_revision(target_binding: dict[str, Any]) -> Mapping[str, Any]:
        return adapter_factory().observe_managed_inbound_revision(
            target_binding=target_binding,
            output_dir=output_dir,
        )

    observation = StandaloneObservationManagedRunPort(
        data_dir,
        provider,
        fixture_mode=False,
        live_inbound_revision_observer=observe_live_inbound_revision,
    )
    decision = StandalonePlannerManagedDecisionPort(
        StandaloneDraftPlanner(data_dir, backend_config=dict(backend_config)),
        action_available=True,
    )
    action = TaShuoMacIosManagedActionPort(
        data_dir,
        output_dir=output_dir,
        adapter_factory=adapter_factory,
    )
    return ManagedRunProviderRuntime(
        ManagedRun(store, observation, decision, action),
        provider_kind="tashuo_mac_ios_live",
        runnable=True,
        start_precondition=lambda: managed_run_start_readiness(data_dir),
    )


def managed_run_start_readiness(data_dir: Path) -> dict[str, Any] | None:
    """Return the shared product precondition for autonomous managed sending."""

    readiness = UserDisclosureRepository(data_dir).readiness(mode="autonomous")
    if readiness.get("ready") is True:
        return None
    return {
        "schema_version": 1,
        "status": "needs_user_profile",
        "reason": "autonomous_requires_user_profile",
        "user_profile_readiness": readiness,
        "next_host_action": "complete_user_self_model",
    }


def _default_tashuo_live_config(
    requested_config: ManagedRunConfig | Mapping[str, Any] | None,
    *,
    data_dir: Path,
    store: JsonManagedRunStore,
) -> dict[str, Any] | None:
    candidate: ManagedRunConfig | None
    if isinstance(requested_config, ManagedRunConfig):
        candidate = requested_config
    elif isinstance(requested_config, Mapping):
        try:
            candidate = ManagedRunConfig.from_dict(requested_config)
        except (TypeError, ValueError):
            candidate = None
    else:
        current_id = store.current_run_id()
        current = store.load(current_id) if current_id else None
        candidate = current.config if current is not None else None
    if candidate is None or candidate.app_id != "tashuo" or candidate.runtime != "mac-ios-app":
        return None
    # MiniMax is already the standalone TaShuo default. Reusing that default
    # removes a user-facing provider JSON file; missing SDK/key still produces
    # a structured blocked result before any GUI observation.
    return {
        "app_id": "tashuo",
        "runtime": "mac-ios-app",
        "output_dir": str(data_dir / "managed_harness"),
        "vision_backend": {"type": "minimax"},
        "backend": {"type": "minimax"},
    }


def build_tashuo_observation_only_ports(
    data_dir: Path,
    *,
    output_dir: Path,
    vision_backend: Any,
    backend_config: dict[str, Any],
) -> tuple[StandaloneObservationManagedRunPort, StandalonePlannerManagedDecisionPort]:
    """Reuse TaShuo observation/planning without claiming live action support."""

    from dating_boost.apps.tashuo.standalone import TaShuoMacIosStandaloneObservationProvider

    provider = TaShuoMacIosStandaloneObservationProvider(
        root=data_dir,
        output_dir=output_dir,
        vision_backend=vision_backend,
    )
    observation = StandaloneObservationManagedRunPort(data_dir, provider, fixture_mode=False)
    decision = StandalonePlannerManagedDecisionPort(
        StandaloneDraftPlanner(data_dir, backend_config=backend_config),
        action_available=False,
    )
    return observation, decision


def _nudge_wait_reason(assessment: dict[str, Any], *, config: ManagedRunConfig) -> str | None:
    # CLI construction intersects `--nudge` with authorization.autonomous_nudge
    # before ManagedRunConfig is created.  Providers still fail closed for
    # direct callers and for assessments without explicit due evidence.
    if not config.nudge_enabled or not config.authorization.autonomous_nudge:
        return "managed_nudge_disabled"
    if assessment.get("nudge_due") is True:
        return None
    due_at = str(assessment.get("nudge_due_at") or assessment.get("due_at") or "").strip()
    if not due_at:
        return "managed_nudge_not_due"
    try:
        due = datetime.fromisoformat(due_at.replace("Z", "+00:00"))
    except ValueError:
        return "managed_nudge_due_at_invalid"
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return None if due.astimezone(timezone.utc) <= datetime.now(timezone.utc) else "managed_nudge_not_due"


def _require_action_ok(payload: Any, fallback_reason: str) -> None:
    if not isinstance(payload, dict):
        raise RuntimeError(fallback_reason)
    if payload.get("status") != "ok":
        raise RuntimeError(str(payload.get("reason") or fallback_reason))


def _message_list_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = payload.get("message_list_snapshot")
    entries = snapshot.get("entries") if isinstance(snapshot, dict) else None
    if isinstance(entries, list):
        return [dict(item) for item in entries if isinstance(item, dict)]
    candidates = payload.get("candidates")
    return [dict(item) for item in candidates or [] if isinstance(item, dict)]


def _next_cursor(payload: dict[str, Any]) -> dict[str, Any]:
    cursor = payload.get("scan_cursor")
    if isinstance(cursor, dict):
        next_value = cursor.get("next")
        if isinstance(next_value, dict):
            return dict(next_value)
        return dict(cursor)
    return {}


def _fixture_target_binding(entry: dict[str, Any], *, candidate_key: str) -> str:
    explicit = entry.get("target_binding")
    if explicit is not None:
        return _canonical_binding(explicit)
    identity_value = entry.get("match_identity_hints")
    identity: dict[str, Any] = dict(identity_value) if isinstance(identity_value, dict) else {}
    evidence = {
        "development_fixture": True,
        "candidate_key": candidate_key,
        "conversation_fingerprint": identity.get("conversation_fingerprint"),
        "latest_preview_hash": entry.get("latest_preview_hash"),
    }
    return "fixture:" + _digest(evidence)


def _live_list_target_binding(entry: dict[str, Any], *, candidate_key: str) -> str | None:
    evidence = entry.get("message_list_evidence")
    if not isinstance(evidence, dict):
        evidence = entry
    anchor = str(evidence.get("visual_anchor_hash") or "").strip()
    region = evidence.get("visual_anchor_region")
    if not anchor or not isinstance(region, dict):
        return None
    return "tashuo-list-anchor:" + _digest(
        {"candidate_key": candidate_key, "visual_anchor_hash": anchor, "visual_anchor_region": region}
    )


def _live_thread_binding_corroborates(candidate: ThreadCandidate, raw_binding: Any) -> bool:
    if not isinstance(raw_binding, dict):
        return False
    source_entry = candidate.metadata.get("source_entry")
    if not isinstance(source_entry, dict):
        return False
    source_evidence = source_entry.get("message_list_evidence")
    if not isinstance(source_evidence, dict):
        source_evidence = source_entry
    expected_anchor = str(source_evidence.get("visual_anchor_hash") or "").strip()
    list_evidence = raw_binding.get("message_list_evidence")
    if not expected_anchor or not isinstance(list_evidence, dict):
        return False
    actual_anchor = str(list_evidence.get("visual_anchor_hash") or "").strip()
    raw_candidate_key = str(raw_binding.get("candidate_key") or "").strip()
    return actual_anchor == expected_anchor and raw_candidate_key == candidate.candidate_key


def _thread_inbound_revision(raw: dict[str, Any]) -> str:
    direct = _first_string(raw, "inbound_revision", "latest_inbound_fingerprint")
    if direct:
        return direct
    assessment = raw.get("assessment")
    direct = _first_string(assessment, "latest_inbound_fingerprint")
    if direct:
        return direct
    observation = raw.get("observation")
    return _first_string(observation, "observation_id")


def _authoritative_candidate_revision(candidate: ThreadCandidate) -> str:
    revision = str(candidate.inbound_revision or "").strip()
    if not revision:
        raise RuntimeError("managed_authoritative_inbound_revision_missing")
    return revision


def _captured_at(payload: dict[str, Any]) -> str:
    direct = _first_string(payload, "captured_at")
    if direct:
        return direct
    observation = payload.get("observation")
    direct = _first_string(observation, "captured_at")
    if direct:
        return direct
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_ok_observation(payload: Any, expected_type: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError("managed_observation_must_be_object")
    if payload.get("status") == "blocked":
        raise ValueError(str(payload.get("reason") or "managed_observation_blocked"))
    observation_type = str(payload.get("observation_type") or expected_type)
    if observation_type != expected_type:
        raise ValueError("managed_observation_type_mismatch")


def _canonical_binding(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ValueError("managed_target_binding_empty")
        return normalized
    if isinstance(value, dict):
        return "binding:" + _digest(value)
    raise ValueError("managed_target_binding_invalid")


def _first_string(payload: Any, *keys: str) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _decision_id(observation: ThreadObservation, value: str) -> str:
    return "managed_decision_" + _digest(
        {
            "target_id": observation.target_id,
            "inbound_revision": observation.inbound_revision,
            "value": value,
        }
    )[:20]


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _blocked(reason: str, **extra: Any) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason, **extra}
