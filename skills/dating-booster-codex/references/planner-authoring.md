# Goal-Oriented Planner Authoring

Use this reference when authoring `planner_assessment` for an opened thread.
The goal is not to label the match permanently. The goal is to capture the
current conversation state so Dating Booster can keep moving toward
`meet_in_person` without looping on stale topics or jumping too fast.

## Scores

Use integer scores from 0 to 100:

- `engagement`: reply effort, specificity, and whether the match gives material
  the user can actually respond to.
- `warmth`: playfulness, friendliness, laughter, softness, or positive affect.
- `curiosity`: whether the match asks about the user or pulls the user further
  into the thread.
- `comfort`: willingness to share personal but low-risk details.
- `momentum`: whether the thread has a natural next step without forcing an
  interview question.
- `topic_saturation`: how close the current topic is to becoming repetitive.
- `logistics_readiness`: whether the thread has enough shared interest, city,
  timing, or activity context to softly probe meeting.
- `risk`: refusal, discomfort, ambiguity, contact exchange, exact appointment
  details, stale identity, or anything requiring user judgment.

Use `0-30` for low, `31-60` for medium, and `61-100` for high.

## Topic Lifecycle

Set `topic_state` to:

- `new`: the topic just appeared.
- `active`: the topic is still producing new information.
- `saturating`: the match answered but did not expand much; continuing the same
  shallow line risks尬聊.
- `exhausted`: the topic has stopped producing useful movement.

When `topic_saturation` is high, prefer `bridge_topic` or `reset_thread`. Use
`deepen_current` only when the match actively expanded the topic and there is a
clear new unknown detail to ask about.

## Stage And Move

Choose the stage that describes the long-term path:

- `opening`: first contact or weak thread.
- `warmup`: establish easy back-and-forth.
- `personal_texture`: learn how the match lives, rests, thinks, or chooses.
- `mutual_thread`: both sides are contributing, joking, or self-disclosing.
- `soft_invite_probe`: gently test whether this would work better offline.
- `appointment_handoff`: exact date, time, place, route, contact, or commitment.
- `paused`: wait; do not push.
- `closed`: stop.

Choose one move:

- `answer_or_riff`: answer or play with the latest inbound first.
- `take_the_lead`: accept a delegation such as “你定”.
- `deepen_current`: ask a specific unknown detail inside the current topic.
- `bridge_topic`: move from the topic to the person or a nearby life context.
- `light_self_disclosure`: add a small personal detail without stealing the turn.
- `reset_thread`: deliberately open a fresh low-pressure thread.
- `soft_invite_probe`: low-pressure offline probe, no exact logistics.
- `nudge_later`: one delayed reopening attempt.
- `wait`: no useful automatic move yet.
- `handoff`: user must take over.

## Soft Invite

Set `soft_invite_allowed` to true only when warmth, comfort, and momentum are
not low, risk is low, and logistics readiness is at least medium. A soft invite
can say the topic feels suitable for meeting in person, but it must not decide
the exact date, time, place, store, route, or contact channel.
