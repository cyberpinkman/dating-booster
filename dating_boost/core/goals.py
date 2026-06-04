from __future__ import annotations

from dataclasses import dataclass


DEFAULT_GOAL_TYPE = "meet_in_person"
BASE_CONVERSATION_MOVES = (
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
)
BASE_HANDOFF_RULES = ("contact_exchange", "risk", "user_takeover")
BASE_POLICY_CONSTRAINTS = (
    "no_unverified_claims",
    "no_contact_exchange_without_user",
    "no_concrete_appointment_commitment_without_user",
)


@dataclass(frozen=True)
class GoalTypeDefinition:
    goal_type: str
    milestones: tuple[str, ...]
    allowed_moves: tuple[str, ...]
    handoff_rules: tuple[str, ...]
    required_user_context: tuple[str, ...]
    policy_constraints: tuple[str, ...]
    success_evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "goal_type": self.goal_type,
            "milestones": list(self.milestones),
            "allowed_moves": list(self.allowed_moves),
            "handoff_rules": list(self.handoff_rules),
            "required_user_context": list(self.required_user_context),
            "policy_constraints": list(self.policy_constraints),
            "success_evidence": list(self.success_evidence),
        }


GOAL_TYPE_REGISTRY: dict[str, GoalTypeDefinition] = {
    "meet_in_person": GoalTypeDefinition(
        goal_type="meet_in_person",
        milestones=(
            "opening",
            "warmup",
            "personal_texture",
            "mutual_thread",
            "soft_invite_probe",
            "appointment_handoff",
        ),
        allowed_moves=BASE_CONVERSATION_MOVES,
        handoff_rules=("appointment_details_requested", *BASE_HANDOFF_RULES),
        required_user_context=(
            "low_risk_shareable_materials",
            "low_investment_repair_materials",
            "date_or_meeting_preferences",
        ),
        policy_constraints=BASE_POLICY_CONSTRAINTS,
        success_evidence=(
            "mutual_interest",
            "logistics_readiness",
            "soft_invite_accepted_or_user_handoff_needed",
        ),
    ),
    "build_rapport": GoalTypeDefinition(
        goal_type="build_rapport",
        milestones=("opening", "warmup", "personal_texture", "mutual_thread"),
        allowed_moves=tuple(move for move in BASE_CONVERSATION_MOVES if move != "soft_invite_probe"),
        handoff_rules=BASE_HANDOFF_RULES,
        required_user_context=("low_risk_shareable_materials", "tone_preferences"),
        policy_constraints=BASE_POLICY_CONSTRAINTS,
        success_evidence=("sustained_engagement", "mutual_curiosity", "natural_topic_continuity"),
    ),
    "screen_compatibility": GoalTypeDefinition(
        goal_type="screen_compatibility",
        milestones=("opening", "warmup", "values_probe", "compatibility_signal", "user_handoff"),
        allowed_moves=tuple(move for move in BASE_CONVERSATION_MOVES if move != "soft_invite_probe"),
        handoff_rules=BASE_HANDOFF_RULES,
        required_user_context=("dating_preferences", "dealbreakers", "low_risk_shareable_materials"),
        policy_constraints=BASE_POLICY_CONSTRAINTS,
        success_evidence=("preference_signal", "values_alignment_signal", "clear_mismatch_or_user_handoff_needed"),
    ),
    "revive_stalled_chat": GoalTypeDefinition(
        goal_type="revive_stalled_chat",
        milestones=("stalled_context_review", "low_pressure_reopen", "response_recovery", "new_thread"),
        allowed_moves=(
            "answer_or_riff",
            "take_the_lead",
            "bridge_topic",
            "light_self_disclosure",
            "low_investment_repair",
            "reset_thread",
            "nudge_later",
            "slow_down_wait",
            "wait",
            "handoff",
        ),
        handoff_rules=BASE_HANDOFF_RULES,
        required_user_context=("low_investment_repair_materials", "tone_preferences"),
        policy_constraints=BASE_POLICY_CONSTRAINTS,
        success_evidence=("reply_recovered", "new_topic_started", "no_reply_after_low_pressure_attempt"),
    ),
    "maintain_connection": GoalTypeDefinition(
        goal_type="maintain_connection",
        milestones=("check_in", "shared_context", "light_continuity", "user_handoff"),
        allowed_moves=(
            "answer_or_riff",
            "deepen_current",
            "bridge_topic",
            "light_self_disclosure",
            "reciprocal_disclosure",
            "nudge_later",
            "slow_down_wait",
            "wait",
            "handoff",
        ),
        handoff_rules=BASE_HANDOFF_RULES,
        required_user_context=("tone_preferences", "known_shared_threads"),
        policy_constraints=BASE_POLICY_CONSTRAINTS,
        success_evidence=("connection_maintained", "mutual_check_in", "clear_wait_needed"),
    ),
}


def get_goal_type_definition(goal_type: str = DEFAULT_GOAL_TYPE) -> GoalTypeDefinition:
    try:
        return GOAL_TYPE_REGISTRY[goal_type]
    except KeyError as exc:
        raise ValueError(f"unsupported goal_type: {goal_type}") from exc
