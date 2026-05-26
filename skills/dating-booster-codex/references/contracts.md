# Dating Booster Agent-Native Contracts

These examples show the minimum practical JSON shapes a host agent needs when
calling the Phase A CLI. The source of truth remains the core code and specs.

## Observation Input

Use this shape with `dating-boost memory ingest-observation`.

```json
{
  "schema_version": 1,
  "observation_id": "obs_chat_001",
  "app_id": "tinder",
  "captured_at": "2026-05-25T00:00:00Z",
  "page_type": "chat_thread",
  "page_confidence": "medium",
  "match_identity_hints": {
    "visible_name": "Alex",
    "profile_cues": ["live music", "weekend plans"],
    "conversation_fingerprint": "alex-live-music-weekend",
    "evidence": "Visible profile and latest chat messages."
  },
  "profile_observation": {
    "profile_text": "Live music and small venues.",
    "photo_cues": ["concert photo"],
    "hook_candidates": ["Ask about recent shows"]
  },
  "conversation_observation": {
    "visible_messages": [
      {"sender": "match", "text": "What are you up to this weekend?"}
    ],
    "input_state": "empty",
    "thread_cues": ["weekend plans"]
  }
}
```

## Context Output

Use this shape from `dating-boost context build` as host-agent input.

```json
{
  "schema_version": 1,
  "status": "ok",
  "match_id": "match_alex",
  "mode": "adaptive",
  "context_pack": {
    "schema_version": 1,
    "reply_mode": "adaptive",
    "items": []
  }
}
```

## Draft Input

Use this shape with `dating-boost policy check-draft`.

```json
{
  "best_reply": "That sounds fun. Any venue you have been wanting to try?",
  "safer_reply": "Nice. Any fun plans already?",
  "bolder_reply": "If there is live music involved, I am listening.",
  "why_this_works": "It follows the open weekend thread and asks an easy question.",
  "situation_read": "The match gave a short positive reply; the user should not over-explain.",
  "conversation_move": "deepen_hook",
  "hook_source": "profile_unknown_detail",
  "naturalness_notes": [
    "one short question",
    "asks for an unknown detail instead of repeating known tags",
    "avoids three-option list wording"
  ],
  "followup_if_match_replies": "If they name a genre or venue, ask one concrete follow-up.",
  "risk_flags": [],
  "missing_info": [],
  "mode_notes": "Adaptive mode.",
  "persona_divergence": "low",
  "stance_divergence": "low"
}
```

## Action Result Input

Use this shape with `dating-boost action record-result`.

```json
{
  "action": "send_message",
  "target_match_id": "match_alex",
  "payload_hash": "sha256:example",
  "pre_action_observation_id": "obs_before_send",
  "post_action_observation_id": "obs_after_send",
  "result_status": "unknown",
  "evidence": {
    "verification": "Post-action screenshot did not conclusively show a sent bubble."
  }
}
```

Allowed `result_status` values are `succeeded`, `failed`, and `unknown`. Only use
`succeeded` when post-action evidence confirms the expected state.
