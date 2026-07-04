from __future__ import annotations

import hashlib
from typing import Any

from dating_boost.apps.tashuo.standalone_common import (
    _is_synthetic_message_list_visible_name,
    _now_iso,
    _stable_text_hash,
    _visual_anchor_region_from_source,
)

__all__ = [
    "_conversation_confidence",
    "_identity_confidence",
    "_latest_inbound_messages",
    "_latest_user_message",
    "_looks_like_question",
    "_messages_fingerprint_payload",
    "_normalize_visible_messages",
    "_observation_id",
    "_planner_assessment_from_messages",
    "_profile_cues_from_cached_target",
    "_profile_observation_from_cached_target",
    "_sender_from_direction",
    "_target_binding",
    "_thread_cues",
    "_thread_observation_from_perception",
]

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
