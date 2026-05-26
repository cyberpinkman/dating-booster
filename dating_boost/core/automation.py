from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dating_boost.core.context_pack import build_context_pack
from dating_boost.core.identity import resolve_match_identity
from dating_boost.core.models import Divergence, ReplyMode
from dating_boost.core.repositories import JsonMemoryRepository, MatchRepository, ObservationRepository
from dating_boost.core.storage import JsonStorage
from dating_boost.intelligence.reply_generator import DraftResponse
from dating_boost.perception.observations import AppObservation
from dating_boost.policy.content import evaluate_draft_content


ACTIVE_SLOT_STATUSES = {"soft_mentioned", "handoff_pending", "user_confirmed"}


class AutomationRepository:
    def __init__(self, root: Path):
        self.root = root
        self._storage = JsonStorage(root)

    def _now(self) -> str:
        return _now_iso()

    def save_goal(self, payload: dict[str, Any]) -> dict[str, Any]:
        goal_id = _non_empty(payload.get("goal_id"), "goal_id")
        document = self._load_collection(Path("automation") / "goals.json", "goals")
        items = {item["goal_id"]: dict(item) for item in document["goals"]}
        items[goal_id] = dict(payload)
        document["goals"] = sorted(items.values(), key=lambda item: str(item["goal_id"]))
        self._storage.write_json(Path("automation") / "goals.json", document)
        return {"schema_version": 1, "status": "ok", "goal_id": goal_id}

    def save_availability(self, payload: dict[str, Any]) -> dict[str, Any]:
        items = list(payload.get("availability", []))
        self._storage.write_json(
            Path("automation") / "availability.json",
            {"schema_version": 1, "availability": items},
        )
        return {"schema_version": 1, "status": "ok", "availability_count": len(items)}

    def save_authorization(self, payload: dict[str, Any]) -> dict[str, Any]:
        authorization_id = _non_empty(payload.get("authorization_id"), "authorization_id")
        self._storage.write_json(
            Path("automation") / "authorization.json",
            dict(payload),
        )
        return {
            "schema_version": 1,
            "status": "ok",
            "authorization_id": authorization_id,
            "autonomous_send": bool(payload.get("autonomous_send")),
            "revoked": bool(payload.get("revoked_at")),
        }

    def load_authorization(self) -> dict[str, Any] | None:
        try:
            return self._storage.read_json(Path("automation") / "authorization.json", expected_schema_version=1)
        except FileNotFoundError:
            return None

    def start_session(self, authorization: dict[str, Any]) -> dict[str, Any]:
        auth_result = self.save_authorization(authorization)
        latest_report_path = self._latest_machine_report_path()
        session_id = f"session_{auth_result['authorization_id']}_{_digest(authorization)[:8]}"
        now = self._now()
        session = {
            "schema_version": 1,
            "session_id": session_id,
            "authorization_id": auth_result["authorization_id"],
            "status": "active",
            "started_at": now,
            "stopped_at": None,
            "step_count": 0,
            "last_scan_cursor": None,
            "resumed_from_report": str(latest_report_path) if latest_report_path else None,
        }
        self._storage.write_json(Path("automation") / "session.json", session)
        return {
            "schema_version": 1,
            "status": "active",
            "session_id": session_id,
            "authorization_id": auth_result["authorization_id"],
            "resumed_from_report": session["resumed_from_report"],
        }

    def stop_session(self) -> dict[str, Any]:
        session = self._load_session()
        states = self.load_states()
        ledger = self.load_ledger()
        summary = _build_summary(states, ledger)
        now = self._now()
        machine_path = Path("automation") / "reports" / "machine_latest.json"
        human_path = Path("automation") / "reports" / "human_latest.md"
        machine_report = {
            "schema_version": 1,
            "session_id": session["session_id"],
            "authorization_id": session.get("authorization_id"),
            "started_at": session.get("started_at"),
            "stopped_at": now,
            "summary": summary,
            "states": states,
            "appointment_ledger": ledger,
            "next_priority_queue": _next_priority_queue(states),
        }
        self._storage.write_json(machine_path, machine_report)
        self._write_text(human_path, _human_report(machine_report))
        session["status"] = "stopped"
        session["stopped_at"] = now
        self._storage.write_json(Path("automation") / "session.json", session)
        return {
            "schema_version": 1,
            "status": "stopped",
            "session_id": session["session_id"],
            "machine_report_path": str(machine_path),
            "human_report_path": str(human_path),
            "summary": summary,
        }

    def latest_report(self) -> dict[str, Any]:
        path = self._latest_machine_report_path()
        if path is None:
            return {"schema_version": 1, "status": "not_found"}
        report = self._storage.read_json(path, expected_schema_version=1)
        return {
            "schema_version": 1,
            "status": "ok",
            "machine_report_path": str(path),
            "machine_report": report,
        }

    def load_states(self) -> list[dict[str, Any]]:
        return list(self._load_collection(Path("automation") / "states.json", "states")["states"])

    def save_states(self, states: list[dict[str, Any]]) -> None:
        self._storage.write_json(
            Path("automation") / "states.json",
            {"schema_version": 1, "states": sorted(states, key=lambda item: str(item["match_id"]))},
        )

    def get_state_payload(self) -> dict[str, Any]:
        return {"schema_version": 1, "status": "ok", "states": self.load_states()}

    def pause_session(self) -> dict[str, Any]:
        session = self._load_session()
        session["status"] = "paused"
        session["paused_at"] = self._now()
        self._storage.write_json(Path("automation") / "session.json", session)
        return {
            "schema_version": 1,
            "status": "ok",
            "session_id": session["session_id"],
            "paused": True,
        }

    def resume_session(self) -> dict[str, Any]:
        session = self._load_session()
        session["status"] = "active"
        session["resumed_at"] = self._now()
        self._storage.write_json(Path("automation") / "session.json", session)
        return {
            "schema_version": 1,
            "status": "ok",
            "session_id": session["session_id"],
            "paused": False,
        }

    def load_ledger(self) -> list[dict[str, Any]]:
        return list(self._load_collection(Path("automation") / "appointment_ledger.json", "slots")["slots"])

    def save_ledger(self, slots: list[dict[str, Any]]) -> None:
        self._storage.write_json(
            Path("automation") / "appointment_ledger.json",
            {"schema_version": 1, "slots": sorted(slots, key=lambda item: str(item["slot_id"]))},
        )

    def apply_action_result(self, event: dict[str, Any]) -> None:
        action_request_id = event.get("action_request_id")
        if not action_request_id:
            return
        now = self._now()
        states = self.load_states()
        changed = False
        for state in states:
            if state.get("last_action_request_id") != action_request_id:
                continue
            mismatch = _action_result_mismatch(event, state)
            if mismatch:
                state["last_action_result_event_id"] = event["event_id"]
                state["last_action_result_error"] = mismatch
                state["updated_at"] = event.get("created_at", now)
                changed = True
                continue
            state["last_outbound_action_id"] = event["event_id"]
            state.pop("last_action_result_error", None)
            if event.get("result_status") == "succeeded":
                state["state"] = "sent_waiting"
            elif event.get("result_status") == "failed":
                state["state"] = "draft_ready"
            state["updated_at"] = event.get("created_at", now)
            changed = True
        if changed:
            self.save_states(states)

    def step(self, scan_batch: dict[str, Any]) -> dict[str, Any]:
        session = self._load_session()
        now = self._now()
        authorization = self.load_authorization() or {}
        if session.get("status") != "active":
            status = str(session.get("status") or "unknown")
            reason = "session_paused" if status == "paused" else "session_stopped" if status == "stopped" else "session_not_active"
            return {
                "schema_version": 1,
                "status": "blocked",
                "reason": reason,
                "action_requests": [],
                "handoffs": [],
                "scan_requests": [],
                "scheduled_actions": [],
                "warnings": [reason],
                "machine_report_ref": str(Path("automation") / "reports" / "machine_latest.json"),
            }
        if _authorization_revoked_or_expired(authorization, now):
            return {
                "schema_version": 1,
                "status": "blocked",
                "reason": "authorization_expired_or_revoked",
                "action_requests": [],
                "handoffs": [],
                "scan_requests": [],
                "scheduled_actions": [],
                "warnings": ["authorization_expired_or_revoked"],
                "machine_report_ref": None,
            }

        states = self.load_states()
        states_by_match = {state["match_id"]: dict(state) for state in states}
        states_by_candidate = {
            state.get("candidate_key"): dict(state)
            for state in states
            if state.get("candidate_key")
        }
        ledger = self.load_ledger()
        thread_items = {
            item.get("candidate_key"): dict(item)
            for item in scan_batch.get("thread_observations", [])
            if item.get("candidate_key")
        }
        entries = _prioritize_entries(
            list(scan_batch.get("message_list_snapshot", {}).get("entries", [])),
            states_by_candidate=states_by_candidate,
            thread_items=thread_items,
        )
        budget = int(scan_batch.get("scan_budget") or 5)
        processed_entries = entries[:budget]
        over_budget_entries = entries[budget:]

        action_requests: list[dict[str, Any]] = []
        handoffs: list[dict[str, Any]] = []
        scan_requests: list[dict[str, Any]] = []
        scheduled_actions: list[dict[str, Any]] = []
        state_updates: list[dict[str, Any]] = []
        warnings: list[str] = []
        processed_match_count = 0

        for entry in processed_entries:
            candidate_key = _non_empty(entry.get("candidate_key"), "candidate_key")
            thread_item = thread_items.get(candidate_key)
            if thread_item is None:
                provisional_id = _provisional_match_id(entry)
                state = states_by_match.get(provisional_id) or states_by_candidate.get(candidate_key) or _new_state(
                    match_id=provisional_id,
                    candidate_key=candidate_key,
                    session_id=session["session_id"],
                    timestamp=now,
                )
                state["state"] = "needs_thread_scan"
                state["candidate_type"] = "continuation_candidate" if state.get("seen_before") else "new_match_candidate"
                state["visible_name"] = entry.get("visible_name")
                state["last_preview_hash"] = entry.get("latest_preview_hash")
                state["updated_at"] = scan_batch.get("captured_at", now)
                states_by_match[state["match_id"]] = state
                scan_requests.append(
                    {
                        "candidate_key": candidate_key,
                        "reason": "thread_observation_required",
                        "visible_name": entry.get("visible_name"),
                    }
                )
                state_updates.append(_state_update(state))
                continue

            processed_match_count += 1
            observation = AppObservation.from_dict(thread_item["observation"])
            ingest = self._store_observation(observation)
            match_id = ingest["match_id"]
            assessment = dict(thread_item.get("assessment", {}))
            latest_fingerprint = assessment.get("latest_inbound_fingerprint")
            state = states_by_match.get(match_id)
            if state is None:
                state = states_by_candidate.get(candidate_key)
                if state is not None:
                    previous_match_id = state["match_id"]
                    if previous_match_id != match_id:
                        states_by_match.pop(previous_match_id, None)
                        if str(previous_match_id).startswith("provisional_"):
                            state["previous_provisional_match_id"] = previous_match_id
                        state["match_id"] = match_id
                else:
                    state = _new_state(
                        match_id=match_id,
                        candidate_key=candidate_key,
                        session_id=session["session_id"],
                        timestamp=now,
                    )
            state["candidate_key"] = candidate_key
            state["visible_name"] = entry.get("visible_name") or observation.match_identity_hints.visible_name
            state["last_session_id"] = session["session_id"]
            state["last_inbound_observation_id"] = observation.observation_id
            state["latest_inbound_fingerprint"] = latest_fingerprint
            state["last_preview_hash"] = entry.get("latest_preview_hash")
            state["last_assessment"] = assessment
            state["updated_at"] = scan_batch.get("captured_at", observation.captured_at)
            state["candidate_type"] = "new_match_candidate" if not state.get("seen_before") else "continuation_candidate"
            state["seen_before"] = True

            if _is_handoff_assessment(assessment):
                slot_conflict = False
                if thread_item.get("appointment_slot"):
                    slot, slot_conflict = _reserve_slot(
                        ledger,
                        match_id=match_id,
                        candidate_key=candidate_key,
                        slot_payload=dict(thread_item["appointment_slot"]),
                        timestamp=now,
                    )
                    state["appointment_slot_id"] = slot["slot_id"]
                state["state"] = "appointment_handoff"
                state["handoff_reason"] = "appointment_details_requested"
                handoffs.append(
                    {
                        "match_id": match_id,
                        "candidate_key": candidate_key,
                        "reason": "appointment_details_requested",
                        "slot_conflict": slot_conflict,
                        "assessment": assessment,
                    }
                )
                states_by_match[match_id] = state
                state_updates.append(_state_update(state))
                continue

            draft_payload = thread_item.get("draft")
            if _can_request_send(authorization, ingest, assessment, state, draft_payload):
                draft = _draft_from_dict(dict(draft_payload))
                context_pack = self._context_pack(match_id, observation)
                policy = evaluate_draft_content(draft, context_pack)
                if policy.allowed:
                    payload_hash = _text_hash(draft.best_reply)
                    if state.get("last_outbound_payload_hash") == payload_hash:
                        warnings.append("duplicate_send_request_suppressed")
                    else:
                        action_request_id = f"action_request_{match_id}_{payload_hash[:12]}"
                        request = {
                            "schema_version": 1,
                            "action_request_id": action_request_id,
                            "match_id": match_id,
                            "candidate_key": candidate_key,
                            "action": "send_message",
                            "payload_text": draft.best_reply,
                            "payload_hash": payload_hash,
                            "pre_action_observation_id": observation.observation_id,
                            "requires_post_action_verification": True,
                            "policy": {
                                "allowed": policy.allowed,
                                "severity": policy.severity,
                                "reason": policy.reason,
                                "requires_user_confirmation": policy.requires_user_confirmation,
                            },
                        }
                        action_requests.append(request)
                        state["state"] = "send_requested"
                        state["last_action"] = "send_message"
                        state["last_action_request_id"] = action_request_id
                        state["last_outbound_payload_hash"] = payload_hash
                        state["last_pre_action_observation_id"] = observation.observation_id
                        state["last_draft_id"] = f"draft_{payload_hash[:12]}"
                else:
                    state["state"] = "draft_ready"
                    state["handoff_reason"] = "draft_blocked"
                    warnings.append("draft_blocked")
            elif assessment.get("recommended_next") == "reply":
                state["state"] = "needs_reply"
            elif assessment.get("recommended_next") == "nudge_later":
                if state.get("last_nudged_inbound_fingerprint") == latest_fingerprint:
                    state["state"] = "waiting_for_match"
                else:
                    state["state"] = "nudge_scheduled"
                    state["last_nudged_inbound_fingerprint"] = latest_fingerprint
                    state["nudge_count_since_inbound"] = int(state.get("nudge_count_since_inbound") or 0) + 1
                    scheduled_actions.append(
                        {
                            "type": "nudge_later",
                            "match_id": match_id,
                            "candidate_key": candidate_key,
                            "latest_inbound_fingerprint": latest_fingerprint,
                            "reason": "host_assessed_continuation_opportunity",
                        }
                    )
            else:
                state["state"] = "sent_waiting"

            states_by_match[match_id] = state
            state_updates.append(_state_update(state))

        for entry in over_budget_entries:
            scheduled_actions.append(
                {
                    "type": "scan_later",
                    "candidate_key": entry.get("candidate_key"),
                    "visible_name": entry.get("visible_name"),
                    "reason": "scan_budget_exceeded",
                }
            )

        self.save_states(list(states_by_match.values()))
        self.save_ledger(ledger)
        session["step_count"] = int(session.get("step_count") or 0) + 1
        session["last_scan_cursor"] = scan_batch.get("scan_cursor")
        self._storage.write_json(Path("automation") / "session.json", session)

        return {
            "schema_version": 1,
            "status": "ok",
            "session_id": session["session_id"],
            "scan_budget": budget,
            "processed_entry_count": len(processed_entries),
            "processed_match_count": processed_match_count,
            "state_updates": state_updates,
            "action_requests": action_requests,
            "handoffs": handoffs,
            "scan_requests": scan_requests,
            "scheduled_actions": scheduled_actions,
            "warnings": _unique_strings(warnings),
            "machine_report_ref": str(Path("automation") / "reports" / "machine_latest.json"),
        }

    def _load_session(self) -> dict[str, Any]:
        try:
            return self._storage.read_json(Path("automation") / "session.json", expected_schema_version=1)
        except FileNotFoundError:
            session = {
                "schema_version": 1,
                "session_id": "session_implicit",
                "authorization_id": None,
                "status": "active",
                "started_at": self._now(),
                "stopped_at": None,
                "step_count": 0,
                "last_scan_cursor": None,
                "resumed_from_report": None,
            }
            self._storage.write_json(Path("automation") / "session.json", session)
            return session

    def _load_collection(self, path: Path, key: str) -> dict[str, Any]:
        try:
            return self._storage.read_json(path, expected_schema_version=1)
        except FileNotFoundError:
            return {"schema_version": 1, key: []}

    def _latest_machine_report_path(self) -> Path | None:
        path = Path("automation") / "reports" / "machine_latest.json"
        absolute = (self._storage.root / path).resolve()
        return path if absolute.exists() else None

    def _write_text(self, relative_path: Path, text: str) -> None:
        path = (self._storage.root / relative_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _store_observation(self, observation: AppObservation) -> dict[str, Any]:
        match_repo = MatchRepository(self.root)
        identity = resolve_match_identity(observation, existing_matches=match_repo.list_match_candidates())
        ObservationRepository(self.root).save_observation(identity.match_id, observation)
        match_repo.upsert_match_from_observation(
            match_id=identity.match_id,
            observation=observation,
            confidence=identity.confidence.value,
            requires_user_confirmation=identity.requires_user_confirmation,
        )
        return {
            "match_id": identity.match_id,
            "confidence": identity.confidence.value,
            "requires_user_confirmation": identity.requires_user_confirmation,
            "observation_id": observation.observation_id,
        }

    def _context_pack(self, match_id: str, observation: AppObservation) -> dict[str, Any]:
        profile = JsonMemoryRepository(self.root).load_user_profile()
        user_profile = {
            "facts": [item.to_dict() for item in profile.facts],
            "preferences": [item.to_dict() for item in profile.preferences],
            "boundaries": [item.to_dict() for item in profile.boundaries],
            "style_examples": list(profile.style_examples),
            "goals": list(profile.goals),
            "persona_baseline": profile.persona_baseline,
            "persona_range": list(profile.persona_range),
            "stance_range": list(profile.stance_range),
        }
        match_profile = {
            "match_id": match_id,
            "display_name": observation.match_identity_hints.visible_name,
            "profile_text": observation.profile_observation.profile_text,
            "conversation_hooks": list(observation.profile_observation.hook_candidates),
            "possible_interests": [
                {"name": cue, "confidence": "medium"}
                for cue in [
                    *observation.profile_observation.photo_cues,
                    *observation.profile_observation.hook_candidates,
                ]
            ],
        }
        messages = [dict(message) for message in observation.conversation_observation.visible_messages]
        conversation_memory = {
            "recent_messages": messages,
            "open_threads": list(observation.conversation_observation.thread_cues),
            "commitments": [],
            "running_summary": " ".join(message.get("text", "") for message in messages).strip(),
        }
        return build_context_pack(
            user_profile=user_profile,
            match_profile=match_profile,
            conversation_memory=conversation_memory,
            reply_mode=ReplyMode.ADAPTIVE,
            max_items=None,
        )


def _draft_from_dict(data: dict[str, Any]) -> DraftResponse:
    return DraftResponse(
        best_reply=str(data["best_reply"]),
        safer_reply=str(data["safer_reply"]),
        bolder_reply=str(data["bolder_reply"]),
        why_this_works=str(data["why_this_works"]),
        situation_read=str(data["situation_read"]),
        conversation_move=str(data["conversation_move"]),
        hook_source=str(data["hook_source"]),
        naturalness_notes=[str(item) for item in data["naturalness_notes"]],
        followup_if_match_replies=str(data["followup_if_match_replies"]),
        risk_flags=[str(item) for item in data["risk_flags"]],
        missing_info=[str(item) for item in data["missing_info"]],
        mode_notes=str(data["mode_notes"]),
        persona_divergence=Divergence(str(data["persona_divergence"])),
        stance_divergence=Divergence(str(data["stance_divergence"])),
    )


def _can_request_send(
    authorization: dict[str, Any],
    ingest: dict[str, Any],
    assessment: dict[str, Any],
    state: dict[str, Any],
    draft_payload: Any,
) -> bool:
    if not draft_payload:
        return False
    if state.get("state") == "appointment_handoff":
        return False
    if not authorization.get("autonomous_send"):
        return False
    if "send_message" not in authorization.get("allowed_actions", []):
        return False
    if ingest.get("confidence") == "low" or ingest.get("requires_user_confirmation"):
        return False
    return (
        assessment.get("recommended_next") == "reply"
        and assessment.get("continuation_opportunity") == "yes"
        and assessment.get("reply_window_status") == "open"
        and assessment.get("confidence") in {"high", "medium"}
    )


def _authorization_revoked_or_expired(authorization: dict[str, Any], now: str) -> bool:
    if not authorization:
        return True
    if authorization.get("revoked_at"):
        return True
    expires_at = authorization.get("expires_at")
    if isinstance(expires_at, str):
        try:
            return _parse_iso_utc(expires_at) <= _parse_iso_utc(now)
        except ValueError:
            return True
    return False


def _action_result_mismatch(event: dict[str, Any], state: dict[str, Any]) -> str | None:
    if event.get("action") != state.get("last_action"):
        return "action_mismatch"
    if event.get("target_match_id") != state.get("match_id"):
        return "target_match_id_mismatch"
    if event.get("payload_hash") != state.get("last_outbound_payload_hash"):
        return "payload_hash_mismatch"
    if event.get("pre_action_observation_id") != state.get("last_pre_action_observation_id"):
        return "pre_action_observation_id_mismatch"
    return None


def _prioritize_entries(
    entries: list[dict[str, Any]],
    *,
    states_by_candidate: dict[str | None, dict[str, Any]],
    thread_items: dict[str | None, dict[str, Any]],
) -> list[dict[str, Any]]:
    indexed_entries = list(enumerate(entries))
    return [
        entry
        for _, entry in sorted(
            indexed_entries,
            key=lambda item: (
                _entry_priority(
                    item[1],
                    states_by_candidate.get(item[1].get("candidate_key")),
                    thread_items.get(item[1].get("candidate_key")),
                ),
                item[0],
            ),
        )
    ]


def _entry_priority(
    entry: dict[str, Any],
    state: dict[str, Any] | None,
    thread_item: dict[str, Any] | None,
) -> int:
    if state is None:
        return 0
    assessment = dict(thread_item.get("assessment", {})) if thread_item else {}
    latest_fingerprint = assessment.get("latest_inbound_fingerprint")
    if latest_fingerprint and latest_fingerprint != state.get("latest_inbound_fingerprint"):
        return 1
    latest_preview_hash = entry.get("latest_preview_hash")
    if entry.get("unread_cue") == "present" and latest_preview_hash != state.get("last_preview_hash"):
        return 1
    if state.get("state") == "appointment_handoff" or _is_handoff_assessment(assessment):
        return 2
    if state.get("state") == "nudge_scheduled" or assessment.get("recommended_next") == "nudge_later":
        return 3
    return 4


def _is_handoff_assessment(assessment: dict[str, Any]) -> bool:
    return (
        assessment.get("appointment_stage") in {"details_requested", "scheduled"}
        or assessment.get("recommended_next") == "handoff"
        or "appointment_details" in assessment.get("risk_flags", [])
    )


def _reserve_slot(
    ledger: list[dict[str, Any]],
    *,
    match_id: str,
    candidate_key: str,
    slot_payload: dict[str, Any],
    timestamp: str,
) -> tuple[dict[str, Any], bool]:
    slot_id = f"slot_{slot_payload.get('date')}_{slot_payload.get('time_window')}"
    conflict = any(
        slot.get("slot_id") == slot_id
        and slot.get("status") in ACTIVE_SLOT_STATUSES
        and slot.get("match_id") != match_id
        for slot in ledger
    )
    existing = [
        slot
        for slot in ledger
        if slot.get("slot_id") == slot_id and slot.get("match_id") == match_id
    ]
    if existing:
        existing[0]["conflict"] = bool(existing[0].get("conflict") or conflict)
        return existing[0], conflict
    slot = {
        "schema_version": 1,
        "slot_id": slot_id,
        "match_id": match_id,
        "candidate_key": candidate_key,
        "date": slot_payload.get("date"),
        "time_window": slot_payload.get("time_window"),
        "area": slot_payload.get("area"),
        "status": "handoff_pending",
        "conflict": conflict,
        "created_at": timestamp,
    }
    ledger.append(slot)
    return slot, conflict


def _new_state(*, match_id: str, candidate_key: str, session_id: str, timestamp: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "match_id": match_id,
        "candidate_key": candidate_key,
        "state": "new_match",
        "stage": "new_match",
        "goal_id": None,
        "latest_inbound_fingerprint": None,
        "last_inbound_observation_id": None,
        "last_outbound_payload_hash": None,
        "last_nudged_inbound_fingerprint": None,
        "nudge_count_since_inbound": 0,
        "next_due_at": None,
        "last_action": None,
        "last_action_request_id": None,
        "last_pre_action_observation_id": None,
        "handoff_reason": None,
        "last_session_id": session_id,
        "updated_at": timestamp,
        "seen_before": False,
    }


def _state_update(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "match_id": state["match_id"],
        "candidate_key": state.get("candidate_key"),
        "state": state["state"],
        "latest_inbound_fingerprint": state.get("latest_inbound_fingerprint"),
        "handoff_reason": state.get("handoff_reason"),
    }


def _build_summary(states: list[dict[str, Any]], ledger: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "match_count": len(states),
        "new_match_count": sum(1 for state in states if state.get("candidate_type") == "new_match_candidate"),
        "action_request_count": sum(1 for state in states if state.get("state") == "send_requested"),
        "waiting_count": sum(1 for state in states if state.get("state") in {"sent_waiting", "waiting_for_match"}),
        "nudge_count": sum(1 for state in states if state.get("state") == "nudge_scheduled"),
        "handoff_count": sum(1 for state in states if state.get("state") == "appointment_handoff"),
        "slot_count": len(ledger),
        "slot_conflict_count": sum(1 for slot in ledger if slot.get("conflict")),
    }


def _next_priority_queue(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = {
        "appointment_handoff": 0,
        "needs_reply": 1,
        "needs_thread_scan": 2,
        "nudge_scheduled": 3,
        "sent_waiting": 4,
    }
    items = [
        {
            "match_id": state["match_id"],
            "candidate_key": state.get("candidate_key"),
            "state": state.get("state"),
            "priority": priority.get(str(state.get("state")), 9),
        }
        for state in states
        if state.get("state") not in {"closed", "paused"}
    ]
    return sorted(items, key=lambda item: (item["priority"], str(item["match_id"])))


def _human_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    return "\n".join(
        [
            "# Dating Booster Session Report",
            "",
            f"- Session: {report['session_id']}",
            f"- Matches tracked: {summary['match_count']}",
            f"- New matches: {summary['new_match_count']}",
            f"- Send requests pending: {summary['action_request_count']}",
            f"- Waiting: {summary['waiting_count']}",
            f"- Handoffs: {summary['handoff_count']}",
            f"- Slot conflicts: {summary['slot_conflict_count']}",
            "",
        ]
    )


def _provisional_match_id(entry: dict[str, Any]) -> str:
    key = entry.get("candidate_key") or entry.get("visible_name") or "unknown"
    return f"provisional_{_safe_id(str(key))}"


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value.lower()).strip("_") or "unknown"


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _non_empty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _now_iso() -> str:
    override = os.environ.get("DATING_BOOST_NOW")
    if override:
        return override
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
