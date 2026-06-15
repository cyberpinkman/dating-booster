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
      {"sender": "user", "text": "I may go to a small show tonight."},
      {"sender": "match", "text": "What are you up to this weekend?"}
    ],
    "latest_inbound_messages": [
      {"sender": "match", "text": "What are you up to this weekend?"}
    ],
    "input_state": "empty",
    "thread_cues": ["weekend plans"]
  }
}
```

`latest_inbound_messages` is the live turn boundary: it contains match messages
after the user's latest outbound. If it is missing, the CLI derives it from
`visible_messages`; host agents should still author it explicitly when possible
so stale visible bubbles do not become the primary reply hook.

## Doctor Output

Use this shape from `dating-boost skill doctor --package skills/dating-booster-codex/skill-package.json --data-dir .local/dating-boost --json`.

```json
{
  "schema_version": 1,
  "status": "ok",
  "skill_version": "1.0.0-rc.2.dev0",
  "cli_found": true,
  "cli_version": "1.0.0-rc.2.dev0",
  "capabilities_ok": true,
  "missing_commands": [],
  "schema_mismatches": [],
  "data_dir": "/abs/path/.local/dating-boost",
  "warnings": [],
  "next_action": "ready"
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

## User Disclosure Profile

Use this shape through `dating-boost user ingest-profile`,
`dating-boost user ingest-interview`, `dating-boost user disclosure-profile`,
and `dating-boost user readiness`.

```json
{
  "schema_version": 1,
  "user_id": "user_local",
  "hard_facts": [
    {"fact_id": "fact_city", "field": "city", "value": "北京", "source": "dating_profile"}
  ],
  "persona_style": {
    "baseline": "有点慢热",
    "allowed_modulations": ["warmer", "more outgoing", "more playful"]
  },
  "shareable_material": [
    {
      "material_id": "mat_home_rhythm",
      "type": "life_detail",
      "text": "我在家待久了会突然想出去透气",
      "tags": ["home", "low_investment_repair"],
      "sensitivity": "low",
      "source": "user_interview"
    }
  ],
  "voice_samples": ["短一点，先接梗再补一句自己的状态"],
  "boundaries": [{"boundary_id": "no_fake_hard_fact", "text": "不编城市、学历、工作、年龄"}],
  "simulation_policy": "free_simulation_soft",
  "source_completion": {"dating_profile": true, "interview": true}
}
```

For autonomous mode, `user readiness` must return `ready: true`; otherwise the
operator/session start returns `needs_user_profile`. Readiness counts only
usable material: non-empty `text` and low/medium `sensitivity`. Empty interview
template rows do not unlock autonomous sending.

`simulation_policy` controls send-time behavior:

- `free_simulation_soft`: may use `simulated_soft` for low-risk persona,
  attitude, or生活感; hard facts remain locked.
- `material_only`: disclosure drafts must use `user_material` and list
  `used_user_material_ids`.
- `user_confirmed_only`: autonomous sending must stop before disclosure.

## Draft Input

Use this shape with `dating-boost policy check-draft`.

```json
{
  "best_reply": "That sounds fun. Any venue you have been wanting to try?",
  "safer_reply": "Nice. Any fun plans already?",
  "bolder_reply": "If there is live music involved, I am listening.",
  "why_this_works": "It follows the open weekend thread and asks an easy question.",
  "situation_read": "The match gave a short positive reply; the user should not over-explain.",
  "conversation_move": "deepen_current",
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
  "selected_hook": "live music",
  "strategic_delta": "Moves from generic weekend talk to a concrete music handle.",
  "meeting_path": "If they engage, later bridge to a low-pressure show or cafe nearby.",
  "why_not_ask_question": "",
  "why_not_invite_now": "Logistics readiness is still low.",
  "persona_divergence": "low",
  "stance_divergence": "low"
}
```

When one reply is more natural as several chat bubbles, include
`message_sequence`. `best_reply` should be the same content joined with newlines;
Dating Booster binds the whole sequence as one payload and host-loop sends each
ordinary chat message in order.
For managed live send, the sequence continuity window is 20 seconds per message
and starts before the first message send attempt. A 3-message sequence therefore
has a 60-second window. If a partial sequence exceeds the window, append audit
evidence/correction as needed, re-observe, and replan instead of sending the
remaining messages later.

```json
{
  "best_reply": "慢热联盟可以成立\n狼人杀这种局我一般也先观察一会儿\n熟了再开麦会比较自然",
  "message_sequence": [
    "慢热联盟可以成立",
    "狼人杀这种局我一般也先观察一会儿",
    "熟了再开麦会比较自然"
  ],
  "strategic_delta": "从慢热共识切到狼人杀局内观察场景，给下一轮自然接点。",
  "selected_hook": "狼人杀"
}
```

## Stage Result Input

Use this shape with `dating-boost operator record-stage-result` when a draft was
placed into the app input box but not sent. Stage-only audit is separate from
live-send action audit and must not be written through `action record-result`.

```json
{
  "action_request_id": "action_request_match_alex_123",
  "target_match_id": "match_alex",
  "payload_hash": "sha256:example",
  "pre_action_observation_id": "obs_before_stage",
  "result_status": "succeeded",
  "stage_attempt_status": "completed",
  "staged_text_verification": {
    "status": "needs_user_verification",
    "evidence": {
      "placeholder_disappeared": true,
      "character_count": 18
    }
  },
  "evidence": {
    "stage_mode": true,
    "user_must_review_before_send": true
  }
}
```

Allowed `result_status` values are `succeeded`, `failed`, and `unknown`. For
stage-only, `succeeded` means the staging operation completed and the draft is
pending user review; it does not mean the message was sent.

## Action Result Input

Use this shape with `dating-boost action record-result`.

```json
{
  "action_request_id": "action_request_match_alex_123",
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

## Action Correction Input

Use this shape with `dating-boost action record-correction` to append a
correction for a previously recorded action or stage event. Never rewrite audit
history in place.

```json
{
  "corrects_event_id": "action_result_123",
  "corrected_status": "unknown",
  "reason": "Earlier audit treated a staged draft as a sent message.",
  "evidence": {
    "source": "fresh review",
    "replacement_event": "stage_result_456"
  }
}
```

## Automation Scan Batch Input

Use `dating-boost automation scan template`, `dating-boost automation scan assemble`,
`dating-boost automation scan normalize`, and `dating-boost automation scan validate`
before passing a `scan_batch` to `dating-boost automation session step`.

`message_list_snapshot` and `thread_observations` can be authored separately:

```json
{
  "entries": [
    {
      "candidate_key": "row_1",
      "visible_name": "Alex",
      "latest_preview": "你定",
      "timestamp_cue": "昨天",
      "unread_cue": "present"
    }
  ]
}
```

```json
{
  "thread_observations": []
}
```

Assemble them with:

```bash
dating-boost automation scan assemble --message-list list.json --threads threads.json --session-id session_123 --captured-at 2026-05-26T10:00:00Z --json
```

The assembled `scan_batch` shape is:

```json
{
  "schema_version": 1,
  "session_id": "session_123",
  "app_id": "tinder",
  "captured_at": "2026-05-26T10:00:00Z",
  "scan_cursor": {
    "current": "page_1",
    "next": "page_2",
    "exhausted": false
  },
  "page_index": 1,
  "visible_range": {"start": 1, "end": 5},
  "entries_observed_count": 5,
  "scan_budget": 5,
  "message_list_snapshot": {
    "entries": [
      {
        "candidate_key": "row_1",
        "visible_name": "Alex",
        "latest_preview": "你定",
        "latest_preview_hash": "sha256:preview",
        "timestamp_cue": "昨天",
        "unread_cue": "present",
        "match_identity_hints": {
          "visible_name": "Alex",
          "profile_cues": ["coffee"],
          "conversation_fingerprint": "alex-coffee"
        },
        "evidence": "Visible message list row."
      }
    ]
  },
  "thread_observations": [
    {
      "candidate_key": "row_1",
      "assessment": {
        "schema_version": 1,
        "latest_match_message": "你定",
        "latest_inbound_fingerprint": "alex:in:you-pick",
        "reply_window_status": "open",
        "continuation_opportunity": "yes",
        "appointment_stage": "none",
        "recommended_next": "reply",
        "confidence": "high",
        "evidence": "The match delegated the choice.",
        "risk_flags": []
      },
      "planner_assessment": {
        "schema_version": 1,
        "latest_turn_summary": "The match delegated the choice.",
        "latest_turn_type": "handoff",
        "inbound_intent": "delegate",
        "topic": {
          "current_topic": "reward",
          "topic_state": "active",
          "new_information": ["match said 你定"],
          "stale_hooks": []
        },
        "scores": {
          "engagement": 62,
          "warmth": 55,
          "curiosity": 35,
          "comfort": 50,
          "momentum": 61,
          "topic_saturation": 20,
          "logistics_readiness": 25,
          "risk": 10
        },
        "recommended_stage": "warmup",
        "recommended_move": "take_the_lead",
        "next_milestone": "Accept the handoff with one light decision.",
        "avoid_next": ["do not ask her to decide again"],
        "soft_invite_allowed": false,
        "reciprocity": {
          "question_debt": 1,
          "self_disclosure_debt": 1,
          "reciprocity_balance": "balanced",
          "low_investment_streak": 0,
          "match_curiosity_about_user": "mixed",
          "topic_exit_pressure": "low",
          "last_user_turn_type": "question"
        },
        "confidence": "high",
        "evidence": "The latest inbound delegates the choice."
      },
      "observation": {
        "observation_id": "obs_alex_001",
        "source_type": "manual_fixture",
        "app_id": "tinder",
        "captured_at": "2026-05-26T10:00:00Z",
        "page_type": "chat_thread",
        "page_confidence": "high",
        "match_identity_hints": {
          "visible_name": "Alex",
          "profile_cues": ["coffee"],
          "conversation_fingerprint": "alex-coffee",
          "evidence": "Visible chat header and messages."
        },
        "profile_observation": {
          "profile_text": "Mentions coffee.",
          "photo_cues": [],
          "hook_candidates": ["coffee"]
        },
        "conversation_observation": {
          "visible_messages": [
            {"sender": "user", "text": "你猜猜会有什么奖励"},
            {"sender": "match", "text": "你定"}
          ],
          "latest_inbound_messages": [{"sender": "match", "text": "你定"}],
          "input_state": "empty",
          "thread_cues": []
        },
        "element_observations": [],
        "exception_state": "none",
        "provenance": {"evidence": "Host-agent screen read."},
        "raw_ref": null
      },
      "draft": {
        "best_reply": "那先欠你一杯咖啡",
        "safer_reply": "那我先记一笔",
        "bolder_reply": "那先欠你一顿好吃的",
        "why_this_works": "It takes the lead.",
        "situation_read": "The match delegated the choice.",
        "conversation_move": "take_the_lead",
        "hook_source": "latest_message",
        "naturalness_notes": ["short"],
        "followup_if_match_replies": "Continue lightly.",
        "risk_flags": [],
        "missing_info": [],
        "mode_notes": "Adaptive mode.",
        "strategic_delta": "Takes the lead without asking them to decide again.",
        "selected_hook": "latest_message",
        "disclosure_source": "none",
        "used_user_material_ids": [],
        "question_count": 0,
        "reply_shape": "statement",
        "persona_divergence": "low",
        "stance_divergence": "low"
      }
    }
  ]
}
```

## Automation Session Step Output

```json
{
  "schema_version": 1,
  "status": "ok",
  "session_id": "session_123",
  "state_updates": [],
  "action_requests": [
    {
      "action_request_id": "action_request_match_alex_123",
      "match_id": "match_alex",
      "action": "send_message",
      "payload_text": "那先欠你一杯咖啡",
      "payload_hash": "sha256:example",
      "pre_action_observation_id": "obs_alex_001",
      "requires_post_action_verification": true,
      "planner_revision": 1,
      "conversation_stage": "warmup",
      "conversation_move": "take_the_lead",
      "planner_alignment": "ok",
      "next_milestone": "Accept the handoff with one light decision.",
      "disclosure_source": "none",
      "used_user_material_ids": [],
      "question_debt_after": 1,
      "reciprocity_balance_after": "balanced",
      "low_investment_repair_applied": false
    }
  ],
  "handoffs": [],
  "scan_requests": [],
  "scheduled_actions": [],
  "warnings": [],
  "machine_report_ref": "automation/reports/machine_latest.json"
}
```

## Planner Contracts

`goal_plan` is persisted per match and summarizes the long-term strategy:

```json
{
  "schema_version": 1,
  "match_id": "match_alex",
  "goal_id": "goal_meet",
  "goal_type": "meet_in_person",
  "stage": "warmup",
  "current_topic": "reward",
  "topic_state": "active",
  "scores": {
    "engagement": 62,
    "warmth": 55,
    "curiosity": 35,
    "comfort": 50,
    "momentum": 61,
    "topic_saturation": 20,
    "logistics_readiness": 25,
    "risk": 10
  },
  "reciprocity": {
    "question_debt": 1,
    "self_disclosure_debt": 1,
    "reciprocity_balance": "balanced",
    "low_investment_streak": 0,
    "match_curiosity_about_user": "mixed",
    "topic_exit_pressure": "low",
    "last_user_turn_type": "question"
  },
  "recommended_move": "take_the_lead",
  "next_milestone": "Accept the handoff with one light decision.",
  "soft_invite_allowed": false,
  "plan_revision": 1
}
```

`planner_recommendation` is the send-time constraint. It exposes
`conversation_scores`, `topic_lifecycle`, `avoid_next`, `auto_send_allowed`,
`requires_handoff`, and `block_reasons`.

## Automation Machine Report

```json
{
  "schema_version": 1,
  "session_id": "session_123",
  "summary": {
    "new_match_count": 1,
    "action_request_count": 1,
    "handoff_count": 0,
    "slot_conflict_count": 0
  },
  "states": [],
  "appointment_ledger": [],
  "next_priority_queue": [
    {
      "match_id": "match_123",
      "candidate_key": "row_1",
      "state": "nudge_scheduled",
      "priority": 1,
      "next_due_at": "2026-05-26T10:30:00Z"
    }
  ]
}
```

## Automation Human Report

Use `dating-boost automation report latest --data-dir .local/dating-boost --format md`
to show a user-facing Markdown report. It must keep match identifiers visible
enough for the user to know who was handled, including match id and candidate key
when available. It includes Summary, Match States, Conversation Plans, Handoffs,
Appointment Ledger, and Next Priority Queue. It should not hide who the agent
talked to by default, but it also should not dump full chat transcripts unless
the user explicitly asks for a transcript-style audit.

## Tinder Host Loop Work Dir

`dating-boost-host-loop` writes `current_work_item.json` plus one
template file. The host fills the matching non-template file. Phase C scopes
all active files by `work_item_id` to prevent stale-file pollution.

```text
message_list_observation.<work_item_id>.template.json -> message_list_observation.<work_item_id>.json
thread_observation.<work_item_id>.template.json -> thread_observation.<work_item_id>.json
staged_verification.<work_item_id>.template.json -> staged_verification.<work_item_id>.json
action_result.<work_item_id>.template.json -> action_result.<work_item_id>.json
```

Older examples may mention `staged_verification.json` or `action_result.json`;
host-loop recovery uses the scoped names. The old
`message_list_observation.template.json` style is no longer the active file
contract.

`staged_verification.<work_item_id>.json` confirms paste/stage before send:

```json
{
  "schema_version": 1,
  "verification_type": "staged_text",
  "action_request_id": "action_request_match_123",
  "match_id": "match_123",
  "candidate_key": "ada_1_preview",
  "expected_payload_hash": "sha256:example",
  "expected_payload_text": "那先欠你一顿好吃的",
  "result_status": "succeeded",
  "staged_text": "那先欠你一顿好吃的",
  "evidence": {
    "verification": "Tinder input box text matched the payload before send.",
    "input_method": "paste"
  }
}
```

In `--send-mode stage`, the host must not click send after this file is written.
In `--send-mode live`, write `action_result.<work_item_id>.json` only after a fresh
post-action observation confirms the sent bubble.

## Observation Authoring

Before ingestion, host-authored observations should pass:

```bash
dating-boost observation validate --input OBSERVATION.json --json
```

Thread observation quality fields:

```json
{
  "schema_version": 1,
  "observation_type": "thread",
  "candidate_key": "ada_1_preview_ada",
  "identity_confidence": "high",
  "identity_evidence": "Visible chat header matches the list row.",
  "turn_boundary_evidence": {
    "latest_user_outbound_text": "你猜猜会有什么奖励",
    "latest_user_outbound_index": 0,
    "latest_inbound_after_user": ["你定"]
  },
  "screenshot_ref": "",
  "observation": {
    "conversation_observation": {
      "visible_messages": [],
      "latest_inbound_messages": [
        {
          "sender": "match",
          "text": "你定",
          "is_after_latest_outbound": true
        }
      ]
    }
  }
}
```

`latest_inbound_messages` must only contain messages after the user's latest
outbound. Old visible messages are background context.

## Replay And Eval

`dating-boost replay latest --data-dir .local/dating-boost --format json`
returns:

```json
{
  "schema_version": 1,
  "status": "ok",
  "event_count": 3,
  "timeline": [
    {"event_type": "work_item", "work_item_type": "scan_message_list"},
    {"event_type": "observation", "work_item_type": "open_thread"},
    {"event_type": "staged_verification", "work_item_type": "send_message"}
  ]
}
```

`dating-boost eval run --suite conversation --json` returns deterministic
fixture pass/fail results for planner decisions and does not call an external
LLM.
