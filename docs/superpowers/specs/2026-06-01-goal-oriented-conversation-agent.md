# Goal-Oriented Conversation Agent Spec

## Summary

Dating Booster should move beyond single-turn drafting into a persistent
goal-oriented conversation planner. The first supported goal is
`meet_in_person`.

The planner is not a replacement for the host LLM. The host agent reads the
visible conversation and authors structured assessments. The CLI validates,
persists, constrains, and reports the plan so a later run can continue without
depending on host-agent memory.

## Planner State

Each match stores a `MatchGoalPlan` with:

- `match_id`
- `goal_id`
- `goal_type`
- `stage`
- `strategy_summary`
- `current_topic`
- `topic_state`
- `topic_history`
- `scores`
- `next_milestone`
- `recommended_move`
- `avoid_next`
- `soft_invite_allowed`
- `handoff_reason`
- `last_observation_id`
- `plan_revision`
- `updated_at`

Supported stages:

- `opening`
- `warmup`
- `personal_texture`
- `mutual_thread`
- `soft_invite_probe`
- `appointment_handoff`
- `paused`
- `closed`

Supported moves:

- `answer_or_riff`
- `take_the_lead`
- `deepen_current`
- `bridge_topic`
- `light_self_disclosure`
- `reciprocal_disclosure`
- `low_investment_repair`
- `reset_thread`
- `soft_invite_probe`
- `nudge_later`
- `slow_down_wait`
- `wait`
- `handoff`

Scores are integer values from `0` to `100`:

- `engagement`
- `warmth`
- `curiosity`
- `comfort`
- `momentum`
- `topic_saturation`
- `logistics_readiness`
- `risk`

## Rules

- A draft move must align with the planner recommendation before automatic send.
- `planner_assessment.confidence == low` blocks automatic sending.
- Empty `latest_inbound_messages` must not be treated as a new reply.
- `topic_saturation >= 70` blocks more shallow questioning unless the match
  actively expanded the topic and the planner recommends `deepen_current`.
- `soft_invite_probe` may be automatic only when it is broad and
  non-committal.
- Exact date, time, venue, route, contact exchange, or other commitment details
  move the match into `appointment_handoff`.

## Skill Requirements

The Codex skill must instruct the host agent to author `planner_assessment`
before draft generation in managed sessions. The skill must also tell the host
to stop automatic sending when planner state is low-confidence, misaligned,
saturated, or in handoff.
