from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dating_boost.core.storage import JsonStorage
from dating_boost.perception.observations import AppObservation


PLANNER_ASSESSMENT_SCHEMA_VERSION = 1
GOAL_PLAN_SCHEMA_VERSION = 1
PLANNER_RECOMMENDATION_SCHEMA_VERSION = 1

CONVERSATION_STAGES = {
    "opening",
    "warmup",
    "personal_texture",
    "mutual_thread",
    "soft_invite_probe",
    "appointment_handoff",
    "paused",
    "closed",
}

CONVERSATION_MOVES = {
    "answer_or_riff",
    "take_the_lead",
    "deepen_current",
    "bridge_topic",
    "light_self_disclosure",
    "reciprocal_disclosure",
    "low_investment_repair",
    "reset_thread",
    "soft_invite_probe",
    "nudge_later",
    "slow_down_wait",
    "wait",
    "handoff",
}

HANDOFF_REASONS = {
    "appointment_details_requested",
    "contact_exchange",
    "risk",
    "user_takeover",
}

SCORE_FIELDS = (
    "engagement",
    "warmth",
    "curiosity",
    "comfort",
    "momentum",
    "topic_saturation",
    "logistics_readiness",
    "risk",
)

PLANNER_ASSESSMENT_REQUIRED_FIELDS = (
    "schema_version",
    "latest_turn_summary",
    "latest_turn_type",
    "inbound_intent",
    "topic",
    "scores",
    "recommended_stage",
    "recommended_move",
    "next_milestone",
    "avoid_next",
    "soft_invite_allowed",
    "confidence",
    "evidence",
)


@dataclass(frozen=True)
class PlannerUpdate:
    goal_plan: dict[str, Any]
    recommendation: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": "ok",
            "goal_plan": self.goal_plan,
            "recommendation": self.recommendation,
        }


class PlannerRepository:
    def __init__(self, root: Path):
        self.root = root
        self._storage = JsonStorage(root)

    def update_plan(
        self,
        *,
        match_id: str,
        goal_id: str,
        observation: AppObservation,
        assessment: dict[str, Any],
        now: str,
    ) -> dict[str, Any]:
        _validate_storage_id(match_id, "match_id")
        _validate_storage_id(goal_id, "goal_id")
        errors = validate_planner_assessment(assessment)["errors"]
        if errors:
            raise ValueError("; ".join(errors))

        existing = self.load_plan(match_id)
        topic = dict(assessment["topic"])
        scores = _scores_from_assessment(assessment)
        stage = str(assessment["recommended_stage"])
        move = str(assessment["recommended_move"])
        reciprocity = _reciprocity_from_assessment(
            assessment,
            existing=existing,
            scores=scores,
        )
        handoff_reason = _handoff_reason(stage, move, assessment)
        if handoff_reason:
            stage = "appointment_handoff"
            move = "handoff"

        revision = int(existing.get("plan_revision", 0)) + 1 if existing else 1
        topic_history = _updated_topic_history(
            existing.get("topic_history", []) if existing else [],
            current_topic=str(topic["current_topic"]),
            topic_state=str(topic["topic_state"]),
            observation_id=observation.observation_id,
        )
        latest_inbound_present = bool(observation.conversation_observation.latest_inbound_messages)

        goal_plan = {
            "schema_version": GOAL_PLAN_SCHEMA_VERSION,
            "match_id": match_id,
            "goal_id": goal_id,
            "goal_type": "meet_in_person",
            "stage": stage,
            "strategy_summary": str(
                assessment.get("strategy_summary")
                or (existing or {}).get("strategy_summary")
                or _default_strategy_summary(stage, move)
            ),
            "current_topic": str(topic["current_topic"]),
            "topic_state": str(topic["topic_state"]),
            "topic_history": topic_history,
            "scores": scores,
            "reciprocity": reciprocity,
            "question_debt": reciprocity["question_debt"],
            "self_disclosure_debt": reciprocity["self_disclosure_debt"],
            "reciprocity_balance": reciprocity["reciprocity_balance"],
            "low_investment_streak": reciprocity["low_investment_streak"],
            "match_curiosity_about_user": reciprocity["match_curiosity_about_user"],
            "topic_exit_pressure": reciprocity["topic_exit_pressure"],
            "last_user_turn_type": reciprocity["last_user_turn_type"],
            "next_milestone": str(assessment["next_milestone"]),
            "recommended_move": move,
            "avoid_next": [str(item) for item in assessment.get("avoid_next", [])],
            "soft_invite_allowed": bool(assessment.get("soft_invite_allowed")),
            "handoff_reason": handoff_reason,
            "last_observation_id": observation.observation_id,
            "latest_inbound_present": latest_inbound_present,
            "planner_confidence": str(assessment["confidence"]),
            "planner_evidence": str(assessment["evidence"]),
            "last_planner_assessment": dict(assessment),
            "plan_revision": revision,
            "updated_at": now,
        }
        recommendation = build_planner_recommendation(goal_plan)
        self._storage.write_json(_goal_plan_path(match_id), goal_plan)
        self._storage.append_jsonl(
            _planner_events_path(match_id),
            {
                "schema_version": 1,
                "event_type": "planner_update",
                "match_id": match_id,
                "goal_id": goal_id,
                "planner_revision": revision,
                "observation_id": observation.observation_id,
                "stage": goal_plan["stage"],
                "recommended_move": goal_plan["recommended_move"],
                "recommendation": recommendation,
                "created_at": now,
            },
        )
        return PlannerUpdate(goal_plan=goal_plan, recommendation=recommendation).to_dict()

    def load_plan(self, match_id: str) -> dict[str, Any] | None:
        _validate_storage_id(match_id, "match_id")
        try:
            return self._storage.read_json(_goal_plan_path(match_id), expected_schema_version=GOAL_PLAN_SCHEMA_VERSION)
        except FileNotFoundError:
            return None

    def get_plan_payload(self, match_id: str) -> dict[str, Any]:
        plan = self.load_plan(match_id)
        if plan is None:
            return {"schema_version": 1, "status": "not_found", "match_id": match_id}
        return {"schema_version": 1, "status": "ok", "goal_plan": plan}

    def recommend(self, match_id: str) -> dict[str, Any]:
        plan = self.load_plan(match_id)
        if plan is None:
            return {"schema_version": 1, "status": "not_found", "match_id": match_id}
        return {
            "schema_version": 1,
            "status": "ok",
            "match_id": match_id,
            "recommendation": build_planner_recommendation(plan),
        }

    def event_log(self, match_id: str) -> list[dict[str, Any]]:
        _validate_storage_id(match_id, "match_id")
        return self._storage.read_jsonl(_planner_events_path(match_id))

    def event_log_payload(self, match_id: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": "ok",
            "match_id": match_id,
            "events": self.event_log(match_id),
        }


def validate_planner_assessment(assessment: Any) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(assessment, dict):
        return {
            "schema_version": 1,
            "status": "error",
            "errors": ["planner_assessment must be an object"],
        }
    for field in PLANNER_ASSESSMENT_REQUIRED_FIELDS:
        if field not in assessment:
            errors.append(f"planner_assessment.{field} is required")
    if assessment.get("schema_version") != PLANNER_ASSESSMENT_SCHEMA_VERSION:
        errors.append("planner_assessment.schema_version must equal 1")

    stage = assessment.get("recommended_stage")
    if stage not in CONVERSATION_STAGES:
        errors.append(f"planner_assessment.recommended_stage must be one of {sorted(CONVERSATION_STAGES)}")
    move = assessment.get("recommended_move")
    if move not in CONVERSATION_MOVES:
        errors.append(f"planner_assessment.recommended_move must be one of {sorted(CONVERSATION_MOVES)}")
    if assessment.get("confidence") not in {"high", "medium", "low"}:
        errors.append("planner_assessment.confidence must be high, medium, or low")

    topic = assessment.get("topic")
    if not isinstance(topic, dict):
        errors.append("planner_assessment.topic must be an object")
    else:
        for field in ("current_topic", "topic_state", "new_information", "stale_hooks"):
            if field not in topic:
                errors.append(f"planner_assessment.topic.{field} is required")
        if "new_information" in topic and not isinstance(topic.get("new_information"), list):
            errors.append("planner_assessment.topic.new_information must be a list")
        if "stale_hooks" in topic and not isinstance(topic.get("stale_hooks"), list):
            errors.append("planner_assessment.topic.stale_hooks must be a list")

    scores = assessment.get("scores")
    if not isinstance(scores, dict):
        errors.append("planner_assessment.scores must be an object")
    else:
        for field in SCORE_FIELDS:
            value = scores.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 100:
                errors.append(f"planner_assessment.scores.{field} must be an integer from 0 to 100")

    if "avoid_next" in assessment and not isinstance(assessment.get("avoid_next"), list):
        errors.append("planner_assessment.avoid_next must be a list")
    if "soft_invite_allowed" in assessment and not isinstance(assessment.get("soft_invite_allowed"), bool):
        errors.append("planner_assessment.soft_invite_allowed must be a boolean")
    if "handoff_reason" in assessment and assessment.get("handoff_reason") not in HANDOFF_REASONS:
        errors.append(f"planner_assessment.handoff_reason must be one of {sorted(HANDOFF_REASONS)}")
    reciprocity = assessment.get("reciprocity")
    if reciprocity is not None:
        if not isinstance(reciprocity, dict):
            errors.append("planner_assessment.reciprocity must be an object")
        else:
            for field in ("question_debt", "self_disclosure_debt", "low_investment_streak"):
                value = reciprocity.get(field)
                if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                    errors.append(f"planner_assessment.reciprocity.{field} must be a non-negative integer")

    return {
        "schema_version": 1,
        "status": "ok" if not errors else "error",
        "errors": errors,
    }


def build_planner_recommendation(goal_plan: dict[str, Any]) -> dict[str, Any]:
    scores = dict(goal_plan.get("scores", {}))
    stage = str(goal_plan.get("stage", "warmup"))
    move = str(goal_plan.get("recommended_move", "wait"))
    evidence = str(goal_plan.get("planner_evidence", ""))
    block_reasons: list[str] = []
    requires_handoff = stage == "appointment_handoff" or move == "handoff"
    handoff_reason = goal_plan.get("handoff_reason") if requires_handoff else None
    if requires_handoff and not handoff_reason:
        handoff_reason = "appointment_details_requested"

    if goal_plan.get("planner_confidence") == "low":
        block_reasons.append("planner_low_confidence")
    if not goal_plan.get("latest_inbound_present", True) and move != "nudge_later":
        block_reasons.append("no_latest_inbound_messages")
    if int(scores.get("topic_saturation", 0)) >= 70 and not _saturated_topic_move_allowed(move, evidence):
        block_reasons.append("topic_saturation_requires_bridge")
    if move == "soft_invite_probe":
        if not goal_plan.get("soft_invite_allowed") or int(scores.get("logistics_readiness", 0)) < 40:
            block_reasons.append("soft_invite_not_ready")
    if move in {"wait", "slow_down_wait"}:
        block_reasons.append("planner_wait")
    if (
        int(goal_plan.get("low_investment_streak") or 0) >= 2
        and int(goal_plan.get("question_debt") or 0) >= 2
        and move in {"deepen_current", "soft_invite_probe"}
    ):
        block_reasons.append("low_investment_question_debt")
    if int(scores.get("risk", 0)) >= 70:
        block_reasons.append("risk_too_high")

    return {
        "schema_version": PLANNER_RECOMMENDATION_SCHEMA_VERSION,
        "status": "ok",
        "match_id": goal_plan.get("match_id"),
        "goal_id": goal_plan.get("goal_id"),
        "planner_revision": goal_plan.get("plan_revision"),
        "conversation_stage": stage,
        "recommended_move": move,
        "next_milestone": goal_plan.get("next_milestone"),
        "avoid_next": list(goal_plan.get("avoid_next", [])),
        "conversation_scores": scores,
        "reciprocity": dict(goal_plan.get("reciprocity") or {}),
        "question_debt": int(goal_plan.get("question_debt") or 0),
        "self_disclosure_debt": int(goal_plan.get("self_disclosure_debt") or 0),
        "reciprocity_balance": str(goal_plan.get("reciprocity_balance") or "unknown"),
        "low_investment_streak": int(goal_plan.get("low_investment_streak") or 0),
        "match_curiosity_about_user": str(goal_plan.get("match_curiosity_about_user") or "unknown"),
        "topic_lifecycle": {
            "current_topic": goal_plan.get("current_topic"),
            "topic_state": goal_plan.get("topic_state"),
            "topic_history": list(goal_plan.get("topic_history", [])),
        },
        "soft_invite_allowed": bool(goal_plan.get("soft_invite_allowed")),
        "requires_handoff": requires_handoff,
        "handoff_reason": handoff_reason,
        "auto_send_allowed": not requires_handoff and not block_reasons,
        "block_reasons": block_reasons,
    }


def planner_context_items(goal_plan: dict[str, Any] | None) -> dict[str, Any]:
    if not goal_plan:
        return {}
    recommendation = build_planner_recommendation(goal_plan)
    return {
        "goal_plan": goal_plan,
        "planner_recommendation": recommendation,
        "conversation_scores": recommendation["conversation_scores"],
        "topic_lifecycle": recommendation["topic_lifecycle"],
        "reciprocity": recommendation["reciprocity"],
        "avoid_next": recommendation["avoid_next"],
    }


def _scores_from_assessment(assessment: dict[str, Any]) -> dict[str, int]:
    scores = dict(assessment["scores"])
    return {field: int(scores[field]) for field in SCORE_FIELDS}


def _reciprocity_from_assessment(
    assessment: dict[str, Any],
    *,
    existing: dict[str, Any] | None,
    scores: dict[str, int],
) -> dict[str, Any]:
    supplied = assessment.get("reciprocity")
    if isinstance(supplied, dict):
        return {
            "question_debt": _bounded_int(supplied.get("question_debt"), 0, 99),
            "self_disclosure_debt": _bounded_int(supplied.get("self_disclosure_debt"), 0, 99),
            "reciprocity_balance": str(supplied.get("reciprocity_balance") or "unknown"),
            "low_investment_streak": _bounded_int(supplied.get("low_investment_streak"), 0, 99),
            "match_curiosity_about_user": str(supplied.get("match_curiosity_about_user") or "unknown"),
            "topic_exit_pressure": str(supplied.get("topic_exit_pressure") or _topic_exit_pressure(scores)),
            "last_user_turn_type": str(supplied.get("last_user_turn_type") or "unknown"),
        }

    existing_reciprocity = dict((existing or {}).get("reciprocity") or {})
    latest_turn_type = str(assessment.get("latest_turn_type") or "")
    low_investment = (
        latest_turn_type in {"short_answer", "short_acknowledgement", "low_investment"}
        or (scores.get("engagement", 0) <= 30 and scores.get("curiosity", 0) <= 30)
    )
    observed_last_user_turn_type = str(assessment.get("last_user_turn_type") or "")
    last_user_turn_type = str(observed_last_user_turn_type or existing_reciprocity.get("last_user_turn_type") or "unknown")
    prior_question_debt = int(existing_reciprocity.get("question_debt") or 0)
    prior_disclosure_debt = int(existing_reciprocity.get("self_disclosure_debt") or 0)
    if observed_last_user_turn_type in {"question", "followup_question", "interview"}:
        question_debt = prior_question_debt + 1
        self_disclosure_debt = prior_disclosure_debt + 1
    elif observed_last_user_turn_type in {"disclosure", "riff", "answer_or_riff", "reciprocal_disclosure"}:
        question_debt = 0
        self_disclosure_debt = 0
    elif observed_last_user_turn_type in {"statement", "invite", "nudge"}:
        question_debt = 0
        self_disclosure_debt = prior_disclosure_debt
    else:
        question_debt = prior_question_debt
        self_disclosure_debt = prior_disclosure_debt
    low_streak = int(existing_reciprocity.get("low_investment_streak") or 0) + 1 if low_investment else 0
    match_curiosity = "yes" if scores.get("curiosity", 0) >= 45 else "no" if scores.get("curiosity", 0) <= 25 else "mixed"
    if question_debt > self_disclosure_debt + 1:
        balance = "user_over_asking"
    elif self_disclosure_debt > question_debt + 1:
        balance = "user_under_disclosing"
    else:
        balance = "balanced"
    return {
        "question_debt": question_debt,
        "self_disclosure_debt": self_disclosure_debt,
        "reciprocity_balance": balance,
        "low_investment_streak": low_streak,
        "match_curiosity_about_user": match_curiosity,
        "topic_exit_pressure": _topic_exit_pressure(scores),
        "last_user_turn_type": last_user_turn_type,
    }


def _topic_exit_pressure(scores: dict[str, int]) -> str:
    saturation = scores.get("topic_saturation", 0)
    if saturation >= 80:
        return "high"
    if saturation >= 60:
        return "medium"
    return "low"


def _bounded_int(value: Any, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return minimum
    return max(minimum, min(maximum, value))


def _updated_topic_history(
    history: list[Any],
    *,
    current_topic: str,
    topic_state: str,
    observation_id: str,
) -> list[dict[str, Any]]:
    items = [dict(item) for item in history if isinstance(item, dict)]
    if items and items[-1].get("topic") == current_topic:
        items[-1]["turn_count"] = int(items[-1].get("turn_count") or 0) + 1
        items[-1]["outcome"] = topic_state
        items[-1]["last_observation_id"] = observation_id
        return items
    items.append(
        {
            "topic": current_topic,
            "started_at": observation_id,
            "last_observation_id": observation_id,
            "turn_count": 1,
            "outcome": topic_state,
        }
    )
    return items


def _saturated_topic_move_allowed(move: str, evidence: str) -> bool:
    if move in {
        "bridge_topic",
        "reset_thread",
        "light_self_disclosure",
        "reciprocal_disclosure",
        "low_investment_repair",
        "slow_down_wait",
        "wait",
    }:
        return True
    if move == "deepen_current":
        evidence_lower = evidence.casefold()
        return "主动扩展" in evidence_lower or "active expansion" in evidence_lower
    return False


def _handoff_reason(stage: str, move: str, assessment: dict[str, Any]) -> str | None:
    if stage == "appointment_handoff" or move == "handoff":
        reason = assessment.get("handoff_reason")
        if reason in HANDOFF_REASONS:
            return str(reason)
        return "appointment_details_requested"
    return None


def _default_strategy_summary(stage: str, move: str) -> str:
    if stage == "soft_invite_probe" or move == "soft_invite_probe":
        return "Use a low-pressure soft invite without committing to exact appointment details."
    if stage == "appointment_handoff" or move == "handoff":
        return "Pause automation and ask the user to decide concrete appointment details."
    return "Advance the conversation toward meeting by building comfort and avoiding stale topic loops."


def _goal_plan_path(match_id: str) -> Path:
    return Path("matches") / match_id / "goal_plan.json"


def _planner_events_path(match_id: str) -> Path:
    return Path("matches") / match_id / "planner_events.jsonl"


def _validate_storage_id(value: str, label: str) -> None:
    if value in {"", ".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"invalid {label}: {value!r}")
