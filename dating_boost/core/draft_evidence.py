from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dating_boost.core.context_pack import build_context_pack
from dating_boost.core.memory.repositories import MemoryRepository, _validate_match_id
from dating_boost.core.models import ReplyMode, UserProfile
from dating_boost.core.planner import PlannerRepository, build_planner_recommendation, planner_context_items
from dating_boost.core.repositories import JsonMemoryRepository
from dating_boost.core.storage import JsonStorage
from dating_boost.perception.observations import AppObservation


DRAFT_EVIDENCE_SCHEMA_VERSION = 1
CONVERSATION_THREAD_SCHEMA_VERSION = 1
LATEST_TURN_SCHEMA_VERSION = 1
USER_MEMORY_SCHEMA_VERSION = 1

PROFILE_REFRESH_AFTER_DAYS = 14


@dataclass(frozen=True)
class DraftEvidencePack:
    schema_version: int
    status: str
    evidence_id: str
    match_id: str
    reply_mode: str
    draft_kind: str
    primary_reason: str | None
    missing_blocks: list[str]
    evidence_manifest: dict[str, Any]
    latest_turn: dict[str, Any]
    conversation_thread: dict[str, Any]
    planner_recommendation: dict[str, Any]
    match_memory: dict[str, Any]
    user_memory: dict[str, Any]
    context_pack: dict[str, Any]

    @property
    def latest_turn_id(self) -> str | None:
        value = self.latest_turn.get("latest_turn_id")
        return str(value) if value else None

    @property
    def conversation_thread_revision(self) -> int | None:
        value = self.conversation_thread.get("revision")
        return int(value) if isinstance(value, int) else None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "evidence_id": self.evidence_id,
            "match_id": self.match_id,
            "reply_mode": self.reply_mode,
            "draft_kind": self.draft_kind,
            "primary_reason": self.primary_reason,
            "missing_blocks": list(self.missing_blocks),
            "latest_turn_id": self.latest_turn_id,
            "conversation_thread_revision": self.conversation_thread_revision,
            "evidence_manifest": dict(self.evidence_manifest),
        }


class ConversationThreadRepository:
    def __init__(self, root: Path):
        self._storage = JsonStorage(root)

    def load(self, match_id: str) -> dict[str, Any] | None:
        _validate_match_id(match_id)
        try:
            return self._storage.read_json(self._path(match_id), expected_schema_version=CONVERSATION_THREAD_SCHEMA_VERSION)
        except FileNotFoundError:
            return None

    def empty_document(self, match_id: str) -> dict[str, Any]:
        _validate_match_id(match_id)
        return {
            "schema_version": CONVERSATION_THREAD_SCHEMA_VERSION,
            "match_id": match_id,
            "revision": 0,
            "messages": [],
            "message_count": 0,
            "last_activity_at": None,
            "updated_at": None,
        }

    def overwrite_from_observation(self, match_id: str, observation: AppObservation) -> dict[str, Any]:
        _validate_match_id(match_id)
        existing = self.load(match_id)
        revision = int((existing or {}).get("revision") or 0) + 1
        existing_messages = [
            dict(item)
            for item in (existing or {}).get("messages", [])
            if isinstance(item, dict)
        ]
        observed_messages = _normalized_messages(
            observation.conversation_observation.visible_messages,
            observed_at=observation.captured_at,
            source_observation_id=observation.observation_id,
        )
        messages = _merge_messages(existing_messages, observed_messages)
        document = {
            "schema_version": CONVERSATION_THREAD_SCHEMA_VERSION,
            "match_id": match_id,
            "revision": revision,
            "messages": messages,
            "message_count": len(messages),
            "last_activity_at": messages[-1]["observed_at"] if messages else None,
            "updated_at": observation.captured_at,
            "source_observation_id": observation.observation_id,
        }
        self._storage.write_json(self._path(match_id), document)
        return document

    def append_confirmed_outbound_turn(
        self,
        match_id: str,
        *,
        latest_turn: dict[str, Any] | None,
        payload_messages: list[dict[str, Any]],
        action_request_id: str,
        created_at: str,
    ) -> dict[str, Any]:
        _validate_match_id(match_id)
        existing = self.load(match_id) or self.empty_document(match_id)
        messages = [dict(item) for item in existing.get("messages", []) if isinstance(item, dict)]
        if latest_turn and latest_turn.get("status") != "cleared":
            for item in latest_turn.get("messages", []):
                if isinstance(item, dict):
                    candidate = _message_entry(
                        item,
                        index=len(messages) + 1,
                        observed_at=created_at,
                        source_observation_id=latest_turn.get("source_observation_id"),
                    )
                    if not _message_seen(messages, candidate):
                        messages.append(candidate)
        for item in payload_messages:
            if isinstance(item, dict):
                message = _message_entry(
                    {"sender": "user", "text": str(item.get("text") or "")},
                    index=len(messages) + 1,
                    observed_at=created_at,
                    source_observation_id=action_request_id,
                )
                message["direction"] = "outbound"
                message["action_request_id"] = action_request_id
                messages.append(message)
        document = {
            "schema_version": CONVERSATION_THREAD_SCHEMA_VERSION,
            "match_id": match_id,
            "revision": int(existing.get("revision") or 0) + 1,
            "messages": messages,
            "message_count": len(messages),
            "last_activity_at": created_at if messages else existing.get("last_activity_at"),
            "updated_at": created_at,
        }
        self._storage.write_json(self._path(match_id), document)
        return document

    def _path(self, match_id: str) -> Path:
        _validate_match_id(match_id)
        return Path("matches") / match_id / "conversation_thread.json"


class LatestTurnRepository:
    def __init__(self, root: Path):
        self._storage = JsonStorage(root)

    def load(self, match_id: str) -> dict[str, Any] | None:
        _validate_match_id(match_id)
        try:
            return self._storage.read_json(self._path(match_id), expected_schema_version=LATEST_TURN_SCHEMA_VERSION)
        except FileNotFoundError:
            return None

    def overwrite_from_observation(self, match_id: str, observation: AppObservation) -> dict[str, Any]:
        _validate_match_id(match_id)
        messages = _normalized_messages(
            observation.conversation_observation.latest_inbound_messages,
            observed_at=observation.captured_at,
            source_observation_id=observation.observation_id,
        )
        turn_hash = _digest(
            {
                "match_id": match_id,
                "observation_id": observation.observation_id,
                "messages": messages,
            }
        )
        document = {
            "schema_version": LATEST_TURN_SCHEMA_VERSION,
            "status": "ok" if messages else "empty",
            "match_id": match_id,
            "latest_turn_id": f"latest_turn_{turn_hash[:16]}",
            "source_observation_id": observation.observation_id,
            "messages": messages,
            "message_count": len(messages),
            "captured_at": observation.captured_at,
            "updated_at": observation.captured_at,
            "payload_hash": turn_hash,
        }
        self._storage.write_json(self._path(match_id), document)
        return document

    def clear(self, match_id: str, *, reason: str, cleared_at: str) -> dict[str, Any]:
        _validate_match_id(match_id)
        existing = self.load(match_id) or {}
        document = {
            "schema_version": LATEST_TURN_SCHEMA_VERSION,
            "status": "cleared",
            "match_id": match_id,
            "latest_turn_id": existing.get("latest_turn_id"),
            "source_observation_id": existing.get("source_observation_id"),
            "messages": [],
            "message_count": 0,
            "cleared_reason": reason,
            "cleared_at": cleared_at,
            "updated_at": cleared_at,
            "previous_payload_hash": existing.get("payload_hash"),
        }
        self._storage.write_json(self._path(match_id), document)
        return document

    def _path(self, match_id: str) -> Path:
        _validate_match_id(match_id)
        return Path("matches") / match_id / "latest_turn.json"


class UserMemoryRepository:
    def __init__(self, root: Path):
        self.root = root
        self._storage = JsonStorage(root)

    def load_projection(self) -> dict[str, Any]:
        try:
            return self._storage.read_json(self._path(), expected_schema_version=USER_MEMORY_SCHEMA_VERSION)
        except FileNotFoundError:
            profile = JsonMemoryRepository(self.root).load_user_profile()
            projection = self._projection_from_profile(profile, profile_sources=[])
            self._storage.write_json(self._path(), projection)
            return projection

    def load_projection_or_none(self) -> dict[str, Any] | None:
        try:
            return self.load_projection()
        except FileNotFoundError:
            return None

    def ensure_profile_source(self, *, app_id: str, runtime: str, observed_at: str) -> dict[str, Any]:
        projection = self.load_projection()
        sources = [dict(item) for item in projection.get("profile_sources", []) if isinstance(item, dict)]
        key = (app_id, runtime)
        if not any((item.get("app_id"), item.get("runtime")) == key for item in sources):
            sources.append(
                {
                    "app_id": app_id,
                    "runtime": runtime,
                    "first_observed_at": observed_at,
                    "last_observed_at": observed_at,
                }
            )
        else:
            for item in sources:
                if (item.get("app_id"), item.get("runtime")) == key:
                    item["last_observed_at"] = observed_at
        projection["profile_sources"] = sources
        projection["updated_at"] = observed_at
        self._storage.write_json(self._path(), projection)
        return projection

    def has_profile_source(self, *, app_id: str, runtime: str) -> bool:
        projection = self.load_projection()
        return any(
            isinstance(item, dict)
            and item.get("app_id") == app_id
            and item.get("runtime") == runtime
            for item in projection.get("profile_sources", [])
        )

    def _projection_from_profile(self, profile: UserProfile, *, profile_sources: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "schema_version": USER_MEMORY_SCHEMA_VERSION,
            "user_id": profile.user_id,
            "profile": {
                "facts": [item.to_dict() for item in profile.facts],
                "preferences": [item.to_dict() for item in profile.preferences],
                "boundaries": [item.to_dict() for item in profile.boundaries],
                "style_examples": list(profile.style_examples),
                "goals": list(profile.goals),
                "persona_baseline": profile.persona_baseline,
                "persona_range": list(profile.persona_range),
                "stance_range": list(profile.stance_range),
                "default_reply_mode": profile.default_reply_mode.value,
            },
            "profile_sources": profile_sources,
            "thread_disclosures": [],
            "updated_at": profile.updated_at,
        }

    def _path(self) -> Path:
        return Path("user") / "user_memory_projection.json"


def build_draft_evidence(
    root: Path,
    match_id: str,
    *,
    reply_mode: ReplyMode | str,
    observation: AppObservation | None = None,
    draft_kind: str = "reply",
    user_reactivated: bool = False,
    now: str | None = None,
    app_id: str | None = None,
    runtime: str | None = None,
    max_memory_items: int | None = None,
    require_user_profile_source: bool = False,
) -> DraftEvidencePack:
    _validate_match_id(match_id)
    reply_mode_value = _reply_mode_value(reply_mode)
    observation_now = observation.captured_at if observation is not None else None
    created_at = now or observation_now or _now_iso()

    memory_repo = MemoryRepository(root)
    match_projection = memory_repo.load_projection(match_id)
    if match_projection is None:
        return _blocked_pack(
            match_id=match_id,
            reply_mode=reply_mode_value,
            draft_kind=draft_kind,
            reason="match_memory_required",
            missing_blocks=["match_memory"],
        )

    user_projection = UserMemoryRepository(root).load_projection_or_none()
    if user_projection is None:
        return _blocked_pack(
            match_id=match_id,
            reply_mode=reply_mode_value,
            draft_kind=draft_kind,
            reason="user_memory_required",
            missing_blocks=["user_memory"],
            match_memory=match_projection.to_dict(),
        )

    user_memory_repo = UserMemoryRepository(root)
    if app_id and runtime:
        if require_user_profile_source and not user_memory_repo.has_profile_source(app_id=app_id, runtime=runtime):
            return _blocked_pack(
                match_id=match_id,
                reply_mode=reply_mode_value,
                draft_kind=draft_kind,
                reason="user_profile_source_required",
                missing_blocks=["user_profile_source"],
                match_memory=match_projection.to_dict(),
                user_memory=user_projection,
            )
        user_projection = user_memory_repo.ensure_profile_source(
            app_id=app_id,
            runtime=runtime,
            observed_at=created_at,
        )

    if user_reactivated and _older_than_days(
        match_projection.profile_last_observed_at,
        created_at,
        PROFILE_REFRESH_AFTER_DAYS,
    ):
        return _blocked_pack(
            match_id=match_id,
            reply_mode=reply_mode_value,
            draft_kind=draft_kind,
            reason="profile_refresh_required",
            missing_blocks=["fresh_match_profile"],
            match_memory=match_projection.to_dict(),
            user_memory=user_projection,
        )

    latest_repo = LatestTurnRepository(root)
    latest_turn = latest_repo.overwrite_from_observation(match_id, observation) if observation else latest_repo.load(match_id)
    thread_repo = ConversationThreadRepository(root)
    conversation_thread = thread_repo.load(match_id)

    if conversation_thread is None:
        if draft_kind == "opener" and _observation_has_no_thread(observation):
            conversation_thread = thread_repo.empty_document(match_id)
        else:
            return _blocked_pack(
                match_id=match_id,
                reply_mode=reply_mode_value,
                draft_kind=draft_kind,
                reason="conversation_thread_required",
                missing_blocks=["conversation_thread"],
                latest_turn=latest_turn or {},
                match_memory=match_projection.to_dict(),
                user_memory=user_projection,
            )

    if draft_kind not in {"opener", "nudge"} and (latest_turn is None or int(latest_turn.get("message_count") or 0) < 1):
        return _blocked_pack(
            match_id=match_id,
            reply_mode=reply_mode_value,
            draft_kind=draft_kind,
            reason="latest_turn_required",
            missing_blocks=["latest_inbound_turn"],
            latest_turn=latest_turn or {},
            conversation_thread=conversation_thread,
            match_memory=match_projection.to_dict(),
            user_memory=user_projection,
        )

    goal_plan = PlannerRepository(root).load_plan(match_id)
    if goal_plan is None:
        goal_plan = _baseline_goal_plan(
            match_id,
            draft_kind=draft_kind,
            latest_turn=latest_turn or {},
            created_at=created_at,
        )
    planner_recommendation = build_planner_recommendation(goal_plan)
    match_memory = match_projection.to_dict()
    user_memory = user_projection
    context_pack = _build_context_pack_from_evidence(
        match_id=match_id,
        reply_mode=reply_mode_value,
        user_memory=user_memory,
        match_memory=match_memory,
        conversation_thread=conversation_thread,
        latest_turn=latest_turn or {},
        goal_plan=goal_plan,
        planner_recommendation=planner_recommendation,
        current_time_iso=created_at,
        max_memory_items=max_memory_items,
    )
    manifest = _evidence_manifest(
        latest_turn=latest_turn or {},
        conversation_thread=conversation_thread,
        planner_recommendation=planner_recommendation,
        match_memory=match_memory,
        user_memory=user_memory,
    )
    evidence_id = f"draft_evidence_{_digest({'match_id': match_id, 'manifest': manifest})[:16]}"
    return DraftEvidencePack(
        schema_version=DRAFT_EVIDENCE_SCHEMA_VERSION,
        status="ok",
        evidence_id=evidence_id,
        match_id=match_id,
        reply_mode=reply_mode_value,
        draft_kind=draft_kind,
        primary_reason=None,
        missing_blocks=[],
        evidence_manifest=manifest,
        latest_turn=latest_turn or {},
        conversation_thread=conversation_thread,
        planner_recommendation=planner_recommendation,
        match_memory=match_memory,
        user_memory=user_memory,
        context_pack=context_pack,
    )


def _build_context_pack_from_evidence(
    *,
    match_id: str,
    reply_mode: str,
    user_memory: dict[str, Any],
    match_memory: dict[str, Any],
    conversation_thread: dict[str, Any],
    latest_turn: dict[str, Any],
    goal_plan: dict[str, Any],
    planner_recommendation: dict[str, Any],
    current_time_iso: str,
    max_memory_items: int | None,
) -> dict[str, Any]:
    messages = [dict(item) for item in conversation_thread.get("messages", []) if isinstance(item, dict)]
    latest_messages = [dict(item) for item in latest_turn.get("messages", []) if isinstance(item, dict)]
    conversation_memory = {
        "recent_messages": messages,
        "latest_inbound_messages": latest_messages,
        "running_summary": {
            "message_count": int(conversation_thread.get("message_count") or 0),
            "revision": conversation_thread.get("revision"),
        },
        "memory_items": [
            {"label": "match_memory_projection", "content": match_memory},
            {"label": "user_memory_projection", "content": user_memory},
        ],
    }
    conversation_memory.update(planner_context_items(goal_plan))
    conversation_memory["planner_recommendation"] = planner_recommendation
    user_profile = dict(user_memory.get("profile") or {})
    match_profile = {
        "conversation_hooks": _match_conversation_hooks(match_memory),
        "possible_interests": [],
    }
    context_pack = build_context_pack(
        user_profile=user_profile,
        match_profile=match_profile,
        conversation_memory=conversation_memory,
        reply_mode=reply_mode,
        max_items=max_memory_items,
        current_time_iso=current_time_iso,
    )
    context_pack["match_id"] = match_id
    return context_pack


def _baseline_goal_plan(
    match_id: str,
    *,
    draft_kind: str,
    latest_turn: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    has_latest = int(latest_turn.get("message_count") or 0) > 0
    stage = "opening" if draft_kind == "opener" else "warmup"
    move = "bridge_topic" if draft_kind == "opener" else "deepen_current"
    return {
        "schema_version": 1,
        "match_id": match_id,
        "goal_id": f"goal_{match_id}",
        "goal_type": "first_meeting",
        "stage": stage,
        "strategy_summary": "Build mutual context and move toward a low-pressure meeting only when ready.",
        "current_topic": "latest_inbound" if has_latest else "profile",
        "topic_state": "active" if has_latest else "opening",
        "topic_history": [],
        "scores": {
            "engagement": 50,
            "warmth": 50,
            "curiosity": 50,
            "comfort": 50,
            "momentum": 50,
            "topic_saturation": 20,
            "logistics_readiness": 10,
            "risk": 0,
        },
        "reciprocity": {
            "question_debt": 0,
            "self_disclosure_debt": 0,
            "reciprocity_balance": "unknown",
            "low_investment_streak": 0,
            "match_curiosity_about_user": "unknown",
            "topic_exit_pressure": "low",
            "last_user_turn_type": "unknown",
        },
        "question_debt": 0,
        "self_disclosure_debt": 0,
        "reciprocity_balance": "unknown",
        "low_investment_streak": 0,
        "match_curiosity_about_user": "unknown",
        "topic_exit_pressure": "low",
        "last_user_turn_type": "unknown",
        "next_milestone": "Create a concrete conversational handle before any invite.",
        "recommended_move": move,
        "avoid_next": [],
        "soft_invite_allowed": False,
        "handoff_reason": None,
        "latest_inbound_present": has_latest,
        "planner_confidence": "medium",
        "planner_evidence": "Baseline plan created because no persisted strategy existed.",
        "last_planner_assessment": None,
        "plan_revision": 0,
        "updated_at": created_at,
    }


def _blocked_pack(
    *,
    match_id: str,
    reply_mode: str,
    draft_kind: str,
    reason: str,
    missing_blocks: list[str],
    latest_turn: dict[str, Any] | None = None,
    conversation_thread: dict[str, Any] | None = None,
    planner_recommendation: dict[str, Any] | None = None,
    match_memory: dict[str, Any] | None = None,
    user_memory: dict[str, Any] | None = None,
) -> DraftEvidencePack:
    manifest = _evidence_manifest(
        latest_turn=latest_turn or {},
        conversation_thread=conversation_thread or {},
        planner_recommendation=planner_recommendation or {},
        match_memory=match_memory or {},
        user_memory=user_memory or {},
    )
    evidence_id = f"draft_evidence_{_digest({'match_id': match_id, 'reason': reason, 'missing': missing_blocks})[:16]}"
    return DraftEvidencePack(
        schema_version=DRAFT_EVIDENCE_SCHEMA_VERSION,
        status="blocked",
        evidence_id=evidence_id,
        match_id=match_id,
        reply_mode=reply_mode,
        draft_kind=draft_kind,
        primary_reason=reason,
        missing_blocks=list(missing_blocks),
        evidence_manifest=manifest,
        latest_turn=latest_turn or {},
        conversation_thread=conversation_thread or {},
        planner_recommendation=planner_recommendation or {},
        match_memory=match_memory or {},
        user_memory=user_memory or {},
        context_pack={"match_id": match_id, "items": []},
    )


def _evidence_manifest(
    *,
    latest_turn: dict[str, Any],
    conversation_thread: dict[str, Any],
    planner_recommendation: dict[str, Any],
    match_memory: dict[str, Any],
    user_memory: dict[str, Any],
) -> dict[str, Any]:
    return {
        "latest_turn_hash": _digest(latest_turn) if latest_turn else None,
        "latest_turn_message_count": int(latest_turn.get("message_count") or 0),
        "conversation_thread_hash": _digest(conversation_thread) if conversation_thread else None,
        "conversation_thread_revision": conversation_thread.get("revision"),
        "conversation_thread_message_count": int(conversation_thread.get("message_count") or 0),
        "planner_recommendation_hash": _digest(planner_recommendation) if planner_recommendation else None,
        "match_memory_hash": _digest(match_memory) if match_memory else None,
        "user_memory_hash": _digest(user_memory) if user_memory else None,
    }


def _normalized_messages(
    messages: list[dict[str, Any]],
    *,
    observed_at: str,
    source_observation_id: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, message in enumerate(messages, start=1):
        normalized.append(
            _message_entry(
                message,
                index=index,
                observed_at=str(message.get("observed_at") or observed_at),
                source_observation_id=str(message.get("source_observation_id") or source_observation_id),
            )
        )
    return normalized


def _message_entry(
    message: dict[str, Any],
    *,
    index: int,
    observed_at: str,
    source_observation_id: Any,
) -> dict[str, Any]:
    sender = str(message.get("sender") or message.get("role") or "").strip()
    text = str(message.get("text") or "").strip()
    entry = {
        "index": index,
        "sender": sender,
        "text": text,
        "observed_at": observed_at,
        "source_observation_id": str(source_observation_id or ""),
        "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "direction": "inbound" if sender == "match" else "outbound" if sender == "user" else "unknown",
    }
    for key in ("timestamp", "timestamp_cue", "message_id"):
        if message.get(key):
            entry[key] = message[key]
    return entry


def _merge_messages(existing: list[dict[str, Any]], observed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages = [dict(item) for item in existing]
    for item in observed:
        if not _message_seen(messages, item):
            merged = dict(item)
            merged["index"] = len(messages) + 1
            messages.append(merged)
    return messages


def _message_seen(messages: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
    candidate_key = _message_dedupe_key(candidate)
    return any(_message_dedupe_key(item) == candidate_key for item in messages)


def _message_dedupe_key(message: dict[str, Any]) -> tuple[str, str, str]:
    message_id = str(message.get("message_id") or "").strip()
    if message_id:
        return ("message_id", message_id, "")
    return (
        str(message.get("sender") or ""),
        str(message.get("message_hash") or ""),
        str(message.get("text") or "").strip(),
    )


def _match_conversation_hooks(match_memory: dict[str, Any]) -> list[str]:
    hooks: list[str] = []
    for fact in match_memory.get("facts", []):
        if not isinstance(fact, dict):
            continue
        value = fact.get("value")
        if isinstance(value, str) and value.strip():
            hooks.append(value.strip())
    for key in ("conversation_threads", "inferences"):
        for item in match_memory.get(key, []):
            if isinstance(item, dict):
                text = item.get("summary") or item.get("value") or item.get("text")
                if isinstance(text, str) and text.strip():
                    hooks.append(text.strip())
    return hooks


def _observation_has_no_thread(observation: AppObservation | None) -> bool:
    if observation is None:
        return True
    return not observation.conversation_observation.visible_messages


def _older_than_days(value: str | None, now: str, days: int) -> bool:
    if not value:
        return True
    try:
        then_dt = _parse_iso(value)
        now_dt = _parse_iso(now)
    except ValueError:
        return True
    return (now_dt - then_dt).total_seconds() > days * 24 * 60 * 60


def _parse_iso(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _reply_mode_value(reply_mode: ReplyMode | str) -> str:
    return reply_mode.value if isinstance(reply_mode, ReplyMode) else str(reply_mode)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
