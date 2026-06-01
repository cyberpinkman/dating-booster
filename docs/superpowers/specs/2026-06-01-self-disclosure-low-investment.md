# Self-Disclosure And Low-Investment Repair Spec

## Summary

Autonomous dating conversations cannot rely on interviewing the match. The
system needs a user-side disclosure model and reciprocity controls so managed
sessions can give, riff, bridge, or wait instead of repeatedly asking questions.

Full managed automation must not start until the user has provided enough
dating profile and interview material for safe self-disclosure.

## User Disclosure Profile

`UserDisclosureProfile` stores:

- `hard_facts`
- `persona_style`
- `shareable_material`
- `voice_samples`
- `boundaries`
- `simulation_policy`

Hard facts include identity, location, education, work, age, relationship
status, and other stable factual claims. The agent must not invent or contradict
hard facts.

`simulation_policy` controls soft expression:

- `free_simulation_soft`: the agent may simulate low-risk tone, attitude, and
  small lifestyle texture while respecting hard facts and boundaries.
- `material_only`: self-disclosure must come from user material.
- `user_confirmed_only`: autonomous sending must stop before self-disclosure.

## Readiness

`dating-boost user readiness --mode autonomous --json` must pass before
operator or automation sessions can automatically send ordinary conversation
messages. If readiness returns `needs_user_profile`, the skill may continue
single-turn drafting with confirmation, but not managed autonomous sending.

## Reciprocity Controls

Per-match planner state tracks:

- `question_debt`
- `self_disclosure_debt`
- `reciprocity_balance`
- `low_investment_streak`
- `match_curiosity_about_user`
- `topic_exit_pressure`
- `last_user_turn_type`

Rules:

- If `low_investment_streak >= 2` and `question_debt >= 2`, direct questions are
  blocked.
- A low-investment repair should prefer `low_investment_repair`,
  `light_self_disclosure`, `reset_thread`, or `slow_down_wait`.
- If repair does not increase reciprocity, the match should move toward
  `slow_down_wait`, `paused`, or `waiting_for_match`.
- Self-disclosure moves must set `disclosure_source` and, when using user
  material, list `used_user_material_ids`.

## Drafting Requirements

Every managed draft should choose one of: give, ask, respond, bridge, or wait.
Questioning is optional and must not be the default. Low-investment repair
should normally use zero questions. Self-disclosure should support the current
milestone rather than becoming a monologue.
