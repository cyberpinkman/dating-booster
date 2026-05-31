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

Use this shape from `python3 scripts/doctor.py --json --data-dir .local/dating-boost`
or `dating-boost skill doctor`.

```json
{
  "schema_version": 1,
  "status": "ok",
  "skill_version": "0.1.7",
  "cli_found": true,
  "cli_version": "0.1.7",
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

## Workflow Draft Output

Use this shape from `dating-boost workflow draft` as the preferred host-agent
result contract. The command returns `status: "blocked"` and omits `draft` when
policy blocks the draft.

```json
{
  "schema_version": 1,
  "workflow": "draft",
  "status": "ok",
  "match_id": "match_alex",
  "observation_id": "obs_chat_001",
  "mode": "adaptive",
  "steps": {
    "capabilities": "ok",
    "ingest_observation": "ok",
    "context_build": "ok",
    "policy_check_draft": "ok",
    "feedback_record": "skipped"
  },
  "context_pack": {
    "reply_mode": "adaptive",
    "items": []
  },
  "policy": {
    "allowed": true,
    "severity": "low",
    "reason": "Draft content passed MVP policy checks.",
    "requires_user_confirmation": false
  },
  "draft": {
    "best_reply": "That sounds fun."
  },
  "feedback": null
}
```

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
  "scan_cursor": "page_1",
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
      "next_milestone": "Accept the handoff with one light decision."
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
  "next_priority_queue": []
}
```

## Automation Human Report

Use `dating-boost automation report latest --data-dir .local/dating-boost --format md`
to show a redacted Markdown report. It includes Summary, Match States,
Handoffs, Appointment Ledger, and Next Priority Queue without dumping full chat
message text.
