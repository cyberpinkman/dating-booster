# Dating Booster Intelligence Layer Design

Status: accepted draft
Date: 2026-05-25

## Purpose

Dating Booster needs stronger reply quality than a generic chat prompt can provide. The intelligence layer will build structured memory about the user, each matched person, and each conversation, then use that memory to draft replies in a controllable mode.

This design covers memory, profile analysis, context assembly, and reply generation modes. It does not implement GUI automation, iPhone Mirroring control, MCP adapters, or autonomous sending.

## Product Principles

1. The agent should improve dating conversations by using real context, not generic pickup lines.
2. The agent must distinguish facts from guesses.
3. Profile photos may produce observable cues and conversation hooks, but not unsupported claims about personality, protected traits, income, politics, religion, mental state, or sexual orientation.
4. The agent must not invent or rewrite hard facts, past experiences, already-sent messages, or consent.
5. Hard facts and historical events are constraints. Interests, value framing, future availability, future intent, future commitments, and conversational persona are controllable variables unless the user sets them as boundaries.
6. The default mode should be useful and authentic rather than maximally persuasive.

## Core Data Model

### User Profile

The user profile stores durable information about the user.

Fields:

- `facts`: stable facts the user has confirmed.
- `preferences`: dating preferences, communication preferences, and desired relationship style.
- `boundaries`: non-negotiable topics, behaviors, facts, or commitments the agent must avoid or preserve.
- `style_examples`: user-written messages or approved drafts used to learn tone.
- `goals`: current dating goals, such as casual dating, serious relationship, or practice.
- `persona_baseline`: the user's normal conversational style.
- `persona_range`: user-approved style range, such as more direct, warmer, more playful, or more outgoing.
- `stance_range`: user-approved flexibility around interests, value framing, availability, intent, and future commitments.
- `updated_at`: last user-confirmed update time.

Facts and boundaries override all generation modes.

### Match Profile

Each matched person gets one structured profile.

Fields:

- `match_id`: local stable identifier.
- `display_name`: visible name when available.
- `profile_text_summary`: structured summary of profile text.
- `observed_photo_cues`: factual visual observations from profile photos.
- `possible_interests`: low to high confidence interest hypotheses with evidence.
- `conversation_hooks`: safe topics to ask about.
- `avoid_assumptions`: claims the agent must not make.
- `confidence_notes`: uncertainty and weak evidence.
- `sources`: timestamps and screen contexts used to build the profile.
- `updated_at`: last refresh time.

The system should store structured analysis by default, not raw profile text or original photos. A later encrypted raw vault can be added for local debugging if needed.

### Match Identity and Merge Rules

`match_id` is a local identifier assigned by Dating Booster, not an identifier from the target app.

The identity resolver should use multiple signals:

- visible display name.
- profile text summary.
- stable profile cues, such as age, city, school, job, interests, and recurring photo cues when visible.
- conversation fingerprint, such as the latest visible messages and open threads.
- source screen context and refresh time.

Identity confidence levels:

- `high`: one existing match strongly agrees across name, profile cues, and conversation fingerprint.
- `medium`: one existing match agrees on name and either profile cues or conversation fingerprint.
- `low`: name-only match, conflicting cues, or multiple plausible candidates.

Rules:

1. Low-confidence identity resolution must ask the user to confirm before writing memory.
2. Conflicting evidence must create a conflict note rather than overwriting existing memory.
3. Automatic merge is allowed only for high-confidence matches.
4. Medium-confidence merge can update non-destructive fields but must preserve prior values and sources.
5. Manual merge and manual split commands should exist before broad automatic refresh is enabled.
6. Unmatched, hidden, or deleted matches should be archived, not immediately deleted.

### Conversation Memory

Each match has conversation memory.

Fields:

- `recent_messages`: recent extracted messages with speaker, timestamp when visible, and source screen.
- `running_summary`: concise summary of the full conversation.
- `open_threads`: unanswered questions, pending topics, and callbacks.
- `commitments`: anything the user or match has agreed to, proposed, or already said.
- `sensitive_context`: topics requiring caution.
- `stage`: relationship stage such as new match, icebreaker, light rapport, deeper rapport, ready to invite, scheduled, cooled, or stop.
- `last_refreshed_at`: last extraction time.

The running summary must preserve concrete details such as names, places, plans, and what each side has already said or promised. It should not compress away facts needed for future replies.

### Strategy State

Strategy state is derived from user profile, match profile, and conversation memory.

Fields:

- `current_goal`: what the next message should achieve.
- `recommended_tone`: concise style guidance for the current reply.
- `risk_flags`: reasons to avoid a draft or ask the user for confirmation.
- `missing_info`: user facts needed before the agent can safely answer.

### Memory Provenance

Every durable memory item should carry provenance metadata. This applies to user profile entries, match profile entries, conversation summaries, and strategy state.

Fields:

- `id`: local stable item identifier.
- `kind`: fact, preference, boundary, inference, summary, hook, commitment, risk, or feedback.
- `content`: structured content.
- `source_type`: user_input, profile_text_analysis, photo_analysis, conversation_extraction, model_summary, user_feedback, or system_event.
- `evidence`: short evidence summary, not raw screenshot data by default.
- `confidence`: high, medium, low, or user_confirmed.
- `created_at`: creation time.
- `last_seen_at`: latest time supporting evidence was observed.
- `supersedes`: optional item ids replaced by this item.
- `status`: active, conflicted, archived, or rejected.

Generation must treat `user_confirmed` facts and boundaries as stronger than extracted or inferred memory. Low-confidence inferences can be used as conversation hooks, but not as factual claims.

## Context Pack

Every draft request builds a context pack.

Inputs:

1. User profile facts, preferences, boundaries, and style examples.
2. Match profile summary, visual cues, interests, hooks, and uncertainty.
3. Conversation memory, including recent messages and running summary.
4. Strategy state.
5. Reply mode.
6. Safety constraints.

The context pack is the only input the conversation agent should need. GUI screenshots and raw OCR output remain in the perception layer unless the system is refreshing memory.

When context is too large, include items in this priority order:

1. User boundaries and hard facts.
2. The match's latest visible message and the user's pending reply context.
3. Open questions, historical commitments, and scheduled plans.
4. Recent messages.
5. Conversation running summary.
6. High-confidence match interests and conversation hooks.
7. User style examples relevant to the selected mode.
8. Low-confidence hypotheses, only if clearly labeled.

The context pack should preserve provenance and confidence labels for any fact or inference that may affect a draft.

## Persona and Stance Modulation Boundary

The agent may adjust conversational persona and strategic stance. This is part of the product's value: a user who is normally quiet, awkward, overly cautious, undecided, or under-expressive may ask the agent to write in a more outgoing, playful, warm, confident, flexible, or committed style.

Hard constraints that must not be changed:

- factual identity, such as education, nationality, location, job, age, and relationship status.
- historical facts, such as past experiences, places lived, travel history, social circle, and messages already sent.
- already-made commitments as historical facts. The agent may help renegotiate them, but it must not pretend they were never made.
- consent, safety boundaries, and user-declared non-negotiables.
- user boundaries and topics the user has rejected.

Soft variables that may be adjusted:

- extroversion in the message.
- warmth, confidence, directness, teasing, flirtation, and humor.
- message length and rhythm.
- initiative level, such as asking a question or suggesting a next step.
- emotional expressiveness.
- interests to emphasize, explore, or express curiosity about, as long as the draft does not claim established experience the user lacks.
- value framing and relationship framing.
- future availability, future intent, and future commitments.
- willingness to change course, clarify, or renegotiate prior statements.

If a draft is far from the user's baseline style or previous stance, the output should mark `persona_divergence` or `stance_divergence` as medium or high and explain the tradeoff in `mode_notes`.

## Reply Modes

### Self Mode

Self Mode optimizes for authenticity.

Rules:

- Strongly preserve the user's tone and known preferences.
- Use user-confirmed facts, prior messages, and stated boundaries as strong constraints.
- Avoid over-optimizing for what the match wants.
- Best for users who want the agent to sound like them.

### Adaptive Mode

Adaptive Mode is the default.

Rules:

- Preserve user facts, boundaries, and general voice.
- Adapt topic, length, warmth, humor, and directness to the match and current conversation.
- Use match interests as hooks, and allow the user to express curiosity or openness even when the interest is not part of their baseline.
- Best for quality improvement while staying grounded.

### Recipient-Optimized Mode

Recipient-Optimized Mode corresponds to the earlier user-described "no-self" mode, but with hard factual constraints and flexible conversational persona and stance.

Rules:

- Optimize for the match's likely reception while preserving factual truth.
- Still obey hard facts, prior-message history, user boundaries, and consent constraints.
- It may simulate a more outgoing, playful, confident, or socially fluent conversational persona when useful.
- It may adjust expressed interests, value framing, future availability, future intent, and future commitments when useful.
- Do not fabricate credentials, location, relationship status, past experiences, established hobbies, or messages already sent.
- If changing a previously stated availability, intent, or commitment, acknowledge the shift or ask the user to confirm before drafting it as settled.
- Mark drafts that may be less like the user's usual style with `persona_divergence`.
- Best for exploring stronger alternatives, not for default autopilot.

## Draft Output Contract

Reply generation should return structured output.

Fields:

- `best_reply`: recommended reply.
- `safer_reply`: lower-risk version.
- `bolder_reply`: more playful, direct, or higher-variance version.
- `why_this_works`: short explanation tied to context.
- `risk_flags`: potential issues or unsupported assumptions.
- `missing_info`: questions the agent needs the user to answer.
- `mode_notes`: how the selected mode shaped the result.
- `persona_divergence`: none, low, medium, or high compared with the user's baseline.
- `stance_divergence`: none, low, medium, or high compared with prior expressed interests, values, availability, intent, or commitments.

The UI or CLI can display all three drafts and let the user choose one to paste.

## User Feedback Loop

The system should treat user choices as training signals for local memory.

Feedback events:

- `accepted`: user used a draft with no material edits.
- `edited`: user edited a draft before sending or saving.
- `rejected`: user rejected all drafts.
- `too_long`, `too_short`, `too_boring`, `too_aggressive`, `too_flirty`, `too_formal`, `not_like_me`: explicit quality labels.
- `good_hook`, `bad_hook`, `wrong_assumption`: context-quality labels.

Rules:

1. Accepted and edited drafts can become style examples after user confirmation or a clear local setting.
2. Rejections should not immediately rewrite the user profile; they should accumulate as feedback events.
3. `wrong_assumption` should downgrade or reject the underlying memory item.
4. `not_like_me` should update persona range, stance range, or mode preferences, not hard facts.
5. Feedback should be scoped by mode. A draft rejected in Self Mode may still be acceptable in Recipient-Optimized Mode.

## Profile Refresh Workflow

Manual refresh comes first.

Commands to support later:

- `dating-boost update-match-profile`
- `dating-boost refresh-conversation`
- `dating-boost draft --mode adaptive`

Daily refresh can be added after the manual flow is reliable. It must report failure clearly when iPhone Mirroring is unavailable, the app is not on the expected screen, text extraction fails, or the state cannot be verified.

## Safety Rules

1. Do not treat photo inferences as facts.
2. Do not infer protected traits or sensitive traits from images.
3. Do not invent hard facts, past experiences, already-sent messages, or consent.
4. Do not draft manipulative pressure, harassment, or deceptive claims.
5. Do not silently overwrite match memory when evidence conflicts. Keep both the new observation and the conflict note.
6. If the context pack lacks enough information to answer safely, ask the user or return `missing_info`.
7. Do not present persona modulation as factual identity change.
8. Do not present stance modulation as a past fact or already-held belief unless the user confirmed it.
9. Do not infer or target protected or sensitive traits from photos or profile cues.

## Storage

Initial storage can use local JSON files under a user data directory. The schema should be versioned from the start.

Recommended layout:

```text
schema_version.json
user_profile.json
matches/
  <match_id>/
    match_profile.json
    conversation_memory.json
    strategy_state.json
    feedback_events.jsonl
```

The storage layer should be abstracted behind repository interfaces so local SQLite or encrypted storage can replace JSON later.

## Privacy and Retention

Default storage should be local, minimal, and auditable.

Rules:

1. Do not save raw screenshots or original profile photos by default.
2. Store structured summaries, evidence summaries, and confidence labels by default.
3. If raw screenshot storage is later added, it must be opt-in and local-only by default.
4. Logs must avoid full conversation dumps unless debug mode is explicitly enabled.
5. Provide delete commands for user profile, a specific match, all archived matches, and all local data.
6. Provide export commands so the user can inspect what the system knows.
7. Before sending data to an LLM provider, build the smallest context pack that can support the requested draft.
8. Local files should live in a user data directory, not the repository checkout.
9. Later encrypted storage should preserve the same repository interface.

## Evaluation

The first useful eval is not GUI success. It is reply quality with memory.

Eval set:

- consented or synthetic match profiles.
- consented or synthetic conversation histories.
- fixed user profiles with style examples.
- expected properties for each reply mode.

Metrics:

- groundedness: no invented user facts.
- context use: reply references relevant match or conversation details.
- voice match: Self Mode resembles user examples.
- adaptability: Adaptive Mode adjusts tone without losing truthfulness.
- safety: risky assumptions are flagged.
- usefulness: human reviewer preference compared with a baseline generic LLM reply.

Rubric:

- `5`: excellent; grounded, context-aware, mode-appropriate, and immediately usable.
- `4`: good; minor wording edits may improve it, but no factual or safety issue.
- `3`: acceptable; usable after noticeable edits or missing some useful context.
- `2`: weak; generic, awkward, or poorly matched to the selected mode.
- `1`: fail; invents facts, misses crucial context, violates a boundary, or creates a risky assumption.

Pass criteria for the first implementation:

- groundedness average at least 4.7, with no score below 4 on hard-fact samples.
- safety average at least 4.7, with no score below 4 on boundary samples.
- context use average at least 4.0.
- Self Mode voice match average at least 4.0.
- Adaptive Mode usefulness average at least 4.0.
- Recipient-Optimized Mode must have no hard-fact violations and must mark high persona or stance divergence when applicable.
- At least 20 fixture cases before connecting perception outputs.

## Non-Goals

- No raw Tinder API use.
- No private API reverse engineering.
- No anti-detection or rate-limit evasion.
- No autonomous sending in this design.
- No claim that target apps permit automation.

## Implementation Sequence

1. Define schemas and repository interfaces.
2. Implement memory provenance and match identity resolution.
3. Implement context pack builder with budget priority.
4. Implement profile analysis prompt contract.
5. Implement conversation summarization contract.
6. Implement reply generation contract and three modes.
7. Implement user feedback events.
8. Add CLI commands for local, non-GUI test fixtures.
9. Add eval fixtures, rubric scoring, and regression tests.
10. Connect perception outputs after the manual fixture path works.
