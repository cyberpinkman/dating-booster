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
4. The agent must not invent user facts, user experiences, promises, availability, or values.
5. The default mode should be useful and authentic rather than maximally persuasive.

## Core Data Model

### User Profile

The user profile stores durable information about the user.

Fields:

- `facts`: stable facts the user has confirmed.
- `preferences`: dating preferences, communication preferences, and desired relationship style.
- `boundaries`: topics, behaviors, and commitments the agent must avoid.
- `style_examples`: user-written messages or approved drafts used to learn tone.
- `goals`: current dating goals, such as casual dating, serious relationship, or practice.
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

### Conversation Memory

Each match has conversation memory.

Fields:

- `recent_messages`: recent extracted messages with speaker, timestamp when visible, and source screen.
- `running_summary`: concise summary of the full conversation.
- `open_threads`: unanswered questions, pending topics, and callbacks.
- `commitments`: anything the user or match has agreed to or proposed.
- `sensitive_context`: topics requiring caution.
- `stage`: relationship stage such as new match, icebreaker, light rapport, deeper rapport, ready to invite, scheduled, cooled, or stop.
- `last_refreshed_at`: last extraction time.

The running summary must preserve concrete details such as names, places, plans, and commitments. It should not compress away facts needed for future replies.

### Strategy State

Strategy state is derived from user profile, match profile, and conversation memory.

Fields:

- `current_goal`: what the next message should achieve.
- `recommended_tone`: concise style guidance for the current reply.
- `risk_flags`: reasons to avoid a draft or ask the user for confirmation.
- `missing_info`: user facts needed before the agent can safely answer.

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

## Reply Modes

### Self Mode

Self Mode optimizes for authenticity.

Rules:

- Strongly preserve the user's tone and known preferences.
- Use only user-confirmed facts and commitments.
- Avoid over-optimizing for what the match wants.
- Best for users who want the agent to sound like them.

### Adaptive Mode

Adaptive Mode is the default.

Rules:

- Preserve user facts, boundaries, and general voice.
- Adapt topic, length, warmth, humor, and directness to the match and current conversation.
- Use match interests as hooks, but do not pretend the user has interests they have not confirmed.
- Best for quality improvement while staying grounded.

### Recipient-Optimized Mode

Recipient-Optimized Mode corresponds to the earlier "no-self" idea, but with stronger truth constraints.

Rules:

- Optimize for the match's likely reception.
- Still obey user facts, boundaries, and commitments.
- Do not fabricate shared interests, lifestyle, values, availability, or intent.
- Mark drafts that may be less like the user's usual style.
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

The UI or CLI can display all three drafts and let the user choose one to paste.

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
3. Do not invent user experience, availability, intent, or consent.
4. Do not draft manipulative pressure, harassment, or deceptive claims.
5. Do not silently overwrite match memory when evidence conflicts. Keep both the new observation and the conflict note.
6. If the context pack lacks enough information to answer safely, ask the user or return `missing_info`.

## Storage

Initial storage can use local JSON files under a user data directory. The schema should be versioned from the start.

Recommended layout:

```text
user_profile.json
matches/
  <match_id>/
    match_profile.json
    conversation_memory.json
    strategy_state.json
```

The storage layer should be abstracted behind repository interfaces so local SQLite or encrypted storage can replace JSON later.

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

## Non-Goals

- No raw Tinder API use.
- No private API reverse engineering.
- No anti-detection or rate-limit evasion.
- No autonomous sending in this design.
- No claim that target apps permit automation.

## Implementation Sequence

1. Define schemas and repository interfaces.
2. Implement context pack builder.
3. Implement profile analysis prompt contract.
4. Implement conversation summarization contract.
5. Implement reply generation contract and three modes.
6. Add CLI commands for local, non-GUI test fixtures.
7. Add eval fixtures and regression tests.
8. Connect perception outputs after the manual fixture path works.
