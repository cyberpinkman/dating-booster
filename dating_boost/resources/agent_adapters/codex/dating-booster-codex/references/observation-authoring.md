# Observation Authoring Guide

Use this guide when a host agent converts a visible dating-app screen,
screenshot, OCR output, or manual user-provided text into an `AppObservation`
JSON object. Prefer what is visible. Do not infer hard facts from weak cues.

## Data Minimization

- Redact phone numbers, handles, exact locations, workplace names, and other
  sensitive details unless the user explicitly asks to preserve them.
- Keep only visible dating-app content needed for the next workflow step.
- Use synthetic or shortened evidence phrases when possible.
- Do not infer protected or intimate traits from photos.

## Page Type

Set `page_type` from the visible screen:

- `home_card`: swipe/card stack with one profile shown.
- `profile_detail`: expanded profile with bio, prompts, interests, or photos.
- `match_list`: list/grid of existing matches or messages.
- `chat_thread`: one conversation thread with messages and an input box.
- `new_match`: modal or screen announcing a new match.
- `paywall`: subscription, boost, super-like, or upsell screen.
- `permission`: OS/app permission prompt or blocked device capability.
- `error`: app error, network issue, unavailable profile, or failed action.
- `unknown`: use when the page cannot be identified confidently.

Set `page_confidence` to `high` when the page type is obvious, `medium` when
partially visible, and `low` when OCR/VLM evidence is weak or ambiguous.

## Match Identity Hints

Fill `match_identity_hints` with stable visible cues:

- `visible_name`: the displayed name if visible; otherwise `null`.
- `profile_cues`: short cues such as prompts, interests, school/city text, or
  distinctive but non-sensitive visible details.
- `conversation_fingerprint`: a short stable phrase from the latest visible
  thread, such as `alex-weekend-question`.
- `evidence`: one sentence explaining why these hints identify the match.

If identity is uncertain, keep evidence explicit and avoid merging assumptions.

## Profile Observation

Fill `profile_observation` from visible profile content:

- `profile_text`: visible bio/prompts/interests summarized or copied in short
  form.
- `photo_cues`: neutral visual cues such as `concert photo`, `dog photo`,
  `hiking trail`, or `coffee shop`. Do not infer personality, income, religion,
  ethnicity, health, or intent from images.
- `hook_candidates`: possible conversation hooks grounded in visible content.

## Facts, Cues, And Inferences

Keep source types separate:

- `visible fact`: text directly visible in the app, such as profile prompts,
  interests, education, city, stated intent, and visible chat messages.
- `photo cue`: neutral visual content, such as `winter coat selfie`, `dog
  photo`, `restaurant table`, or `concert stage`.
- `inference`: a tentative reading derived from visible facts or photo cues,
  such as a possible conversation hook or low-confidence vibe.

Rules:

- A photo cue must not be promoted to fact. Seeing a dog in a photo can support
  `dog photo`; it cannot prove dog ownership unless text says so.
- An inference must not be promoted to fact. If it is useful as a hook, mark it
  with `low_confidence` in the hook text or evidence.
- Put directly visible profile/chat text in `profile_text` or
  `visible_messages`; put neutral image descriptions in `photo_cues`; put
  possible conversation openings in `hook_candidates`.
- Do not infer protected traits, health, income, sexuality, religion, or intent
  from photos. Use `unknown` when unsure.

## Conversation Observation

Fill `conversation_observation` from visible messages:

- `visible_messages`: ordered oldest-to-newest for the visible window. Use
  `sender: "user"` for the user's messages, `sender: "match"` for the other
  person, and `sender: "system"` for app notices.
- `latest_inbound_messages`: match messages after the user's latest outbound.
  This is the turn boundary for drafting. Old visible messages are background
  only and must not become the primary reply hook.
- `input_state`: use `empty`, `draft_present`, `keyboard_open`, `disabled`, or
  `unknown`.
- `thread_cues`: unresolved questions, open topics, commitments, or emotional
  tone visible in the thread.
  For TaShuo, record `tashuo_question_gate_skipped` when the visible system
  notice says `她跳过了问答考验`, and record `tashuo_permanent_chat_enabled`
  when the visible system notice says `她开启了永久聊天`; inherited question/answer
  text remains visible thread context, not low-investment evidence by itself.

If message order is unclear, record only the messages whose order is visible and
use `unknown` in evidence/provenance.

When a visible thread contains older match messages above the user's latest
reply, do not treat those older bubbles as the live question. If
`latest_inbound_messages` is empty, either wait for a new inbound message or use
a deliberate reset/nudge workflow instead of pretending the old visible text is
fresh.

## Elements And Exceptions

Use `element_observations` for actionable screen elements only when needed:

- input box location
- send button state
- back button
- popover dismiss button
- paywall or modal buttons

Set `exception_state` to `none` unless a blocking condition is visible. Use
`paywall`, `permission_blocked`, `network_error`, `login_required`, or `unknown`
when the app state prevents the intended workflow.

## Provenance

Use `provenance` to say where the observation came from:

```json
{
  "evidence": "Host-agent screen read from iPhone Mirroring.",
  "redaction_status": "redacted",
  "author": "host_agent"
}
```

Use `raw_ref` for a screenshot path or other local reference only when the user
intends to keep that artifact.

## Minimum Example

```json
{
  "observation_id": "obs_manual_001",
  "source_type": "manual_fixture",
  "app_id": "tinder",
  "adapter_id": "codex.manual.v1",
  "captured_at": "2026-05-26T00:00:00Z",
  "page_type": "chat_thread",
  "page_confidence": "medium",
  "match_identity_hints": {
    "visible_name": "Alex",
    "profile_cues": ["live music"],
    "conversation_fingerprint": "alex-weekend-question",
    "evidence": "Visible chat header and latest message."
  },
  "profile_observation": {
    "profile_text": "Mentions live music.",
    "photo_cues": ["concert photo"],
    "hook_candidates": ["Ask about recent shows"]
  },
  "conversation_observation": {
    "visible_messages": [
      {"sender": "match", "text": "What are you up to this weekend?"}
    ],
    "latest_inbound_messages": [
      {"sender": "match", "text": "What are you up to this weekend?"}
    ],
    "input_state": "empty",
    "thread_cues": ["weekend plans"]
  },
  "element_observations": [],
  "exception_state": "none",
  "provenance": {
    "evidence": "Manual redacted observation.",
    "redaction_status": "redacted"
  },
  "raw_ref": null
}
```
