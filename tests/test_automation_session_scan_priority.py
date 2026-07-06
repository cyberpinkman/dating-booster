from tests.automation_session_support import (
    AppObservation,
    AutomationRepository,
    AutomationSessionTestCase,
    DraftReviewDecision,
    DraftReviewFinding,
    FIXTURE_DIR,
    IdentityTrustStatus,
    MatchMemoryProjection,
    MemoryRepository,
    Path,
    _contact_exchange_scan_batch,
    _next_priority_queue,
    _nudge_draft,
    _prioritize_entries,
    json,
    os,
    patch,
    tempfile,
)


class AutomationSessionScanPriorityTests(AutomationSessionTestCase):
    def test_thread_scan_merges_provisional_state_into_resolved_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            list_only_scan = {
                "schema_version": 1,
                "session_id": "session_fixture_merge",
                "app_id": "tinder",
                "captured_at": "2026-05-26T09:00:00Z",
                "scan_budget": 1,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_cora",
                            "visible_name": "Cora",
                            "latest_preview": "新匹配",
                            "latest_preview_hash": "preview_cora",
                            "timestamp_cue": "昨天",
                            "unread_cue": "absent",
                            "position": 1,
                        }
                    ]
                },
                "thread_observations": [],
            }
            thread_scan = dict(list_only_scan)
            thread_scan["thread_observations"] = [
                {
                    "candidate_key": "row_cora",
                    "assessment": {
                        "schema_version": 1,
                        "latest_match_message": "你好",
                        "latest_inbound_fingerprint": "cora:in:hello",
                        "reply_window_status": "open",
                        "continuation_opportunity": "yes",
                        "appointment_stage": "none",
                        "recommended_next": "wait",
                        "confidence": "high",
                        "evidence": "Thread opened for Cora.",
                        "risk_flags": [],
                    },
                    "observation": {
                        "observation_id": "obs_cora_001",
                        "source_type": "manual_fixture",
                        "app_id": "tinder",
                        "adapter_id": "codex.manual.v1",
                        "captured_at": "2026-05-26T09:01:00Z",
                        "page_type": "chat_thread",
                        "page_confidence": "high",
                        "match_identity_hints": {
                            "visible_name": "Cora",
                            "profile_cues": ["音乐"],
                            "conversation_fingerprint": "cora-new-match",
                            "evidence": "Visible chat thread for Cora.",
                        },
                        "profile_observation": {
                            "profile_text": "喜欢音乐。",
                            "photo_cues": [],
                            "hook_candidates": ["music"],
                        },
                        "conversation_observation": {
                            "visible_messages": [{"sender": "match", "text": "你好"}],
                            "input_state": "empty",
                            "thread_cues": [],
                        },
                        "element_observations": [],
                        "exception_state": "none",
                        "provenance": {
                            "evidence": "Fixture thread observation.",
                            "redaction_status": "redacted",
                        },
                        "raw_ref": None,
                    },
                }
            ]
            list_scan_path = Path(temp_dir) / "list_scan.json"
            thread_scan_path = Path(temp_dir) / "thread_scan.json"
            self._write_json(list_scan_path, list_only_scan)
            self._write_json(thread_scan_path, thread_scan)

            self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(list_scan_path),
            ])
            self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(thread_scan_path),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(states_exit, 0)
            self.assertEqual(len(states_payload["states"]), 1)
            state = states_payload["states"][0]
            self.assertEqual(state["candidate_key"], "row_cora")
            self.assertFalse(state["match_id"].startswith("provisional_"))
            self.assertEqual(state["state"], "sent_waiting")

    def test_scan_budget_prioritizes_new_candidates_before_known_continuations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            automation_dir = data_dir / "automation"
            automation_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(
                automation_dir / "states.json",
                {
                    "schema_version": 1,
                    "states": [
                        {
                            "schema_version": 1,
                            "match_id": f"match_old_{index}",
                            "candidate_key": f"row_old_{index}",
                            "state": "sent_waiting",
                            "candidate_type": "continuation_candidate",
                            "seen_before": True,
                            "last_session_id": "session_fixture_priority",
                        }
                        for index in range(1, 6)
                    ],
                },
            )
            priority_scan = {
                "schema_version": 1,
                "session_id": "session_fixture_priority",
                "app_id": "tinder",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 1,
                "message_list_snapshot": {
                    "entries": [
                        *[
                            {
                                "candidate_key": f"row_old_{index}",
                                "visible_name": f"Old {index}",
                                "latest_preview": "旧会话",
                                "latest_preview_hash": f"old_{index}",
                                "timestamp_cue": "昨天",
                                "unread_cue": "absent",
                                "position": index,
                            }
                            for index in range(1, 6)
                        ],
                        {
                            "candidate_key": "row_new",
                            "visible_name": "New",
                            "latest_preview": "新匹配",
                            "latest_preview_hash": "new_preview",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "present",
                            "position": 6,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "priority_scan.json"
            self._write_json(scan_path, priority_scan)

            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])

            self.assertEqual(step_exit, 0)
            self.assertEqual(step_payload["processed_entry_count"], 1)
            self.assertEqual(step_payload["scan_requests"][0]["candidate_key"], "row_new")
            self.assertNotIn(
                "row_new",
                [item.get("candidate_key") for item in step_payload["scheduled_actions"]],
            )

    def test_opportunity_priority_beats_new_unread_when_budget_is_tight(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            automation_dir = data_dir / "automation"
            automation_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(
                automation_dir / "states.json",
                {
                    "schema_version": 1,
                    "states": [
                        {
                            "schema_version": 1,
                            "match_id": "match_due",
                            "candidate_key": "row_due",
                            "state": "nudge_scheduled",
                            "candidate_type": "continuation_candidate",
                            "seen_before": True,
                            "latest_inbound_fingerprint": "due:fp",
                            "last_nudged_inbound_fingerprint": None,
                            "next_due_at": "2026-05-26T00:00:00Z",
                            "last_session_id": "session_priority_due",
                        }
                    ],
                },
            )
            priority_scan = {
                "schema_version": 1,
                "session_id": "session_priority_due",
                "app_id": "tinder",
                "captured_at": "2026-05-26T00:01:00Z",
                "scan_cursor": {"current": "page_1", "next": "page_2", "exhausted": False},
                "scan_budget": 1,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_new",
                            "visible_name": "New",
                            "latest_preview": "刚匹配",
                            "latest_preview_hash": "new_hash",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "present",
                            "position": 1,
                        },
                        {
                            "candidate_key": "row_due",
                            "visible_name": "Due",
                            "latest_preview": "上次聊到这",
                            "latest_preview_hash": "due_hash",
                            "timestamp_cue": "30分钟前",
                            "unread_cue": "absent",
                            "position": 2,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "priority_due_scan.json"
            self._write_json(scan_path, priority_scan)

            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])

        self.assertEqual(step_exit, 0)
        self.assertEqual(step_payload["scan_requests"][0]["candidate_key"], "row_due")
        self.assertEqual(step_payload["scheduled_actions"][0]["type"], "scan_later")
        self.assertEqual(step_payload["scheduled_actions"][0]["candidate_key"], "row_new")
        self.assertEqual(step_payload["scheduled_actions"][0]["scan_cursor"], priority_scan["scan_cursor"])

    def test_unread_known_continuation_beats_absent_unread_stale_new_candidate_when_budget_is_tight(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            automation_dir = data_dir / "automation"
            automation_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(
                automation_dir / "states.json",
                {
                    "schema_version": 1,
                    "states": [
                        {
                            "schema_version": 1,
                            "match_id": "match_xiaoyaowan",
                            "candidate_key": "row_xiaoyaowan",
                            "state": "needs_thread_scan",
                            "candidate_type": "continuation_candidate",
                            "seen_before": True,
                            "last_preview_hash": "same_waiting_reply_hash",
                            "last_session_id": "session_priority_unread_continuation",
                        }
                    ],
                },
            )
            priority_scan = {
                "schema_version": 1,
                "session_id": "session_priority_unread_continuation",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 1,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_stale_old",
                            "visible_name": "Old stale",
                            "latest_preview": "四个月前的旧反应",
                            "latest_preview_hash": "old_stale_hash",
                            "timestamp_cue": "",
                            "unread_cue": "absent",
                            "position": 1,
                        },
                        {
                            "candidate_key": "row_xiaoyaowan",
                            "visible_name": "小药丸儿",
                            "latest_preview": "我晚上上班呀",
                            "latest_preview_hash": "same_waiting_reply_hash",
                            "timestamp_cue": "",
                            "unread_cue": "present",
                            "position": 2,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "priority_unread_continuation_scan.json"
            self._write_json(scan_path, priority_scan)

            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])

        self.assertEqual(step_exit, 0)
        self.assertEqual(step_payload["processed_entry_count"], 1)
        self.assertEqual(step_payload["scan_requests"][0]["candidate_key"], "row_xiaoyaowan")
        self.assertEqual(step_payload["scheduled_actions"][0]["candidate_key"], "row_stale_old")

    def test_session_step_skips_non_chat_message_list_gates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            automation_dir = data_dir / "automation"
            automation_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(
                automation_dir / "states.json",
                {
                    "schema_version": 1,
                    "states": [
                        {
                            "schema_version": 1,
                            "match_id": "provisional_tashuo_liked_you_gate_29_active",
                            "candidate_key": "tashuo_liked_you_gate_29_active",
                            "state": "needs_thread_scan",
                            "candidate_type": "new_match_candidate",
                            "visible_name": "29人喜欢了你",
                            "latest_preview": "有人刚刚活跃，去打个招呼吧!",
                            "unread_cue": "present",
                            "last_session_id": "session_gate_filter",
                        },
                        {
                            "schema_version": 1,
                            "match_id": "provisional_tashuo_visual_8181c3ffffffff80",
                            "candidate_key": "tashuo_visual_8181c3ffffffff80",
                            "state": "needs_thread_scan",
                            "candidate_type": "new_match_candidate",
                            "visible_name": "Pending question avatar (illustration)",
                            "unread_cue": "present",
                            "last_session_id": "session_gate_filter",
                        },
                        {
                            "schema_version": 1,
                            "match_id": "provisional_tashuo_visual_000000ffffe7e7ef",
                            "candidate_key": "tashuo_visual_000000ffffe7e7ef",
                            "state": "needs_thread_scan",
                            "candidate_type": "new_match_candidate",
                            "visible_name": "Tab header: 消息 / 动态",
                            "unread_cue": None,
                            "last_session_id": "session_gate_filter",
                        },
                        {
                            "schema_version": 1,
                            "match_id": "provisional_tashuo_visual_0080c1ffffffffff",
                            "candidate_key": "tashuo_visual_0080c1ffffffffff",
                            "state": "needs_thread_scan",
                            "candidate_type": "new_match_candidate",
                            "visible_name": "匿名提问卡片",
                            "unread_cue": "present",
                            "last_session_id": "session_gate_filter",
                        }
                    ],
                },
            )
            scan = {
                "schema_version": 1,
                "session_id": "session_gate_filter",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 5,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "tashuo_liked_you_gate_29_active",
                            "candidate_type": "premium_or_liked_you_gate",
                            "visible_name": "29人喜欢了你",
                            "latest_preview": "有人刚刚活跃，去打个招呼吧!",
                            "latest_preview_hash": "liked_you_gate_hash",
                            "timestamp_cue": "",
                            "unread_cue": "present",
                            "position": 1,
                        },
                        {
                            "candidate_key": "tashuo_visual_8181c3ffffffff80",
                            "candidate_type": "new_match_candidate",
                            "visible_name": "Pending question avatar (illustration)",
                            "latest_preview": "Pending question row avatar",
                            "latest_preview_hash": "pending_question_hash",
                            "timestamp_cue": "",
                            "unread_cue": "present",
                            "position": 2,
                        },
                        {
                            "candidate_key": "tashuo_visual_000000ffffe7e7ef",
                            "candidate_type": "new_match_candidate",
                            "visible_name": "Tab header: 消息 / 动态",
                            "latest_preview": "Message tab header",
                            "latest_preview_hash": "tab_header_hash",
                            "timestamp_cue": "",
                            "unread_cue": "absent",
                            "position": 3,
                        },
                        {
                            "candidate_key": "tashuo_visual_0080c1ffffffffff",
                            "candidate_type": "new_match_candidate",
                            "visible_name": "匿名提问卡片",
                            "latest_preview": "待回答横向问题卡片",
                            "latest_preview_hash": "anonymous_question_card_hash",
                            "timestamp_cue": "",
                            "unread_cue": "present",
                            "position": 4,
                        },
                        {
                            "candidate_key": "row_ordinary",
                            "visible_name": "Ada",
                            "latest_preview": "刚刚问你今天忙不忙",
                            "latest_preview_hash": "ordinary_hash",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "present",
                            "position": 5,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "scan_with_gate.json"
            self._write_json(scan_path, scan)

            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])

        self.assertEqual(step_exit, 0)
        self.assertIn("non_chat_message_list_entry_skipped", step_payload["warnings"])
        self.assertEqual([item["candidate_key"] for item in step_payload["scan_requests"]], ["row_ordinary"])
        queued_keys = [item["candidate_key"] for item in step_payload["next_priority_queue"]]
        self.assertNotIn("tashuo_liked_you_gate_29_active", queued_keys)
        self.assertNotIn("tashuo_visual_8181c3ffffffff80", queued_keys)
        self.assertNotIn("tashuo_visual_000000ffffe7e7ef", queued_keys)
        self.assertNotIn("tashuo_visual_0080c1ffffffffff", queued_keys)
        self.assertIn("row_ordinary", queued_keys)

    def test_session_step_skips_tashuo_visual_rows_without_visible_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            scan = {
                "schema_version": 1,
                "session_id": "session_tashuo_empty_name_filter",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 2,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "tashuo_visual_0f3990839b0a",
                            "candidate_type": "continuation_candidate",
                            "latest_preview": "",
                            "latest_preview_hash": "empty_name_hash",
                            "position": 1,
                        },
                        {
                            "candidate_key": "row_ordinary",
                            "visible_name": "Ada",
                            "latest_preview": "刚刚问你忙不忙",
                            "latest_preview_hash": "ordinary_hash",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "present",
                            "position": 2,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "scan_with_empty_name_tashuo_visual_row.json"
            self._write_json(scan_path, scan)

            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])

        self.assertEqual(step_exit, 0)
        self.assertIn("non_chat_message_list_entry_skipped", step_payload["warnings"])
        self.assertEqual([item["candidate_key"] for item in step_payload["scan_requests"]], ["row_ordinary"])

    def test_session_step_queues_recent_open_chat_after_unread_continuation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            automation_dir = data_dir / "automation"
            automation_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(
                automation_dir / "states.json",
                {
                    "schema_version": 1,
                    "states": [
                        {
                            "schema_version": 1,
                            "match_id": "match_reply",
                            "candidate_key": "row_reply",
                            "state": "needs_thread_scan",
                            "candidate_type": "continuation_candidate",
                            "seen_before": True,
                            "last_preview_hash": "reply_old_hash",
                            "last_session_id": "session_open_chat_recent",
                        }
                    ],
                },
            )
            scan = {
                "schema_version": 1,
                "session_id": "session_open_chat_recent",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 2,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_open_chat",
                            "candidate_type": "open_chat_candidate",
                            "visible_name": "Newly Open",
                            "latest_preview": "你们已经可以进行会话了，开启聊天",
                            "latest_preview_hash": "open_chat_recent_hash",
                            "timestamp_cue": "2天前",
                            "unread_cue": "absent",
                            "position": 1,
                        },
                        {
                            "candidate_key": "row_reply",
                            "visible_name": "小药丸儿",
                            "latest_preview": "我晚上上班呀",
                            "latest_preview_hash": "reply_new_hash",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "present",
                            "position": 2,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "recent_open_chat_scan.json"
            self._write_json(scan_path, scan)

            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])

        self.assertEqual(step_exit, 0)
        self.assertEqual([item["candidate_key"] for item in step_payload["scan_requests"]], ["row_reply", "row_open_chat"])
        self.assertNotIn("message_list_history_cutoff_reached", step_payload["warnings"])
        self.assertEqual(states_exit, 0)
        states_by_key = {state["candidate_key"]: state for state in states_payload["states"]}
        self.assertEqual(states_by_key["row_open_chat"]["candidate_type"], "open_chat_candidate")
        self.assertEqual(states_by_key["row_open_chat"]["state"], "needs_thread_scan")

    def test_session_step_prioritizes_unseen_continuation_before_open_chat(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            scan = {
                "schema_version": 1,
                "session_id": "session_open_chat_after_continuation",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 3,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_open_chat",
                            "candidate_type": "open_chat_candidate",
                            "visible_name": "Newly Open",
                            "latest_preview": "你们已经可以进行会话了，开启聊天",
                            "latest_preview_hash": "open_chat_recent_hash",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "absent",
                            "position": 1,
                        },
                        {
                            "candidate_key": "row_continuation",
                            "candidate_type": "continuation_candidate",
                            "visible_name": "小药丸儿",
                            "latest_preview": "我晚上上班呀",
                            "latest_preview_hash": "reply_new_hash",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "absent",
                            "position": 2,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "open_chat_after_continuation_scan.json"
            self._write_json(scan_path, scan)

            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])

        self.assertEqual(step_exit, 0)
        self.assertEqual(
            [item["candidate_key"] for item in step_payload["scan_requests"]],
            ["row_continuation", "row_open_chat"],
        )

    def test_session_step_history_cutoff_skips_old_open_chat_and_lower_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            scan = {
                "schema_version": 1,
                "session_id": "session_history_cutoff",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_cursor": {"current": "page_1", "next": "page_2", "exhausted": False},
                "scan_budget": 5,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_recent_reply",
                            "visible_name": "Recent",
                            "latest_preview": "刚刚问你今天忙不忙",
                            "latest_preview_hash": "recent_hash",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "present",
                            "position": 1,
                        },
                        {
                            "candidate_key": "row_old_open_chat",
                            "candidate_type": "open_chat_candidate",
                            "visible_name": "Old Open",
                            "latest_preview": "你们已经可以进行会话了，开启聊天",
                            "latest_preview_hash": "old_open_chat_hash",
                            "timestamp_cue": "4个月前",
                            "unread_cue": "absent",
                            "position": 2,
                        },
                        {
                            "candidate_key": "row_below_old",
                            "visible_name": "Below Old",
                            "latest_preview": "更旧的一行",
                            "latest_preview_hash": "below_old_hash",
                            "timestamp_cue": "5个月前",
                            "unread_cue": "absent",
                            "position": 3,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "history_cutoff_scan.json"
            self._write_json(scan_path, scan)

            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])

        self.assertEqual(step_exit, 0)
        self.assertTrue(step_payload["history_cutoff_reached"])
        self.assertEqual(step_payload["historical_entry_count"], 2)
        self.assertIn("message_list_history_cutoff_reached", step_payload["warnings"])
        self.assertEqual([item["candidate_key"] for item in step_payload["scan_requests"]], ["row_recent_reply"])
        self.assertEqual(
            [item["candidate_key"] for item in step_payload["scheduled_actions"] if item["type"] == "historical_thread_skipped"],
            ["row_old_open_chat", "row_below_old"],
        )
        self.assertEqual(states_exit, 0)
        states_by_key = {state["candidate_key"]: state for state in states_payload["states"]}
        self.assertEqual(states_by_key["row_old_open_chat"]["state"], "historical_thread")
        self.assertEqual(states_by_key["row_below_old"]["state"], "historical_thread")
        queued_keys = [item["candidate_key"] for item in step_payload["next_priority_queue"]]
        self.assertNotIn("row_old_open_chat", queued_keys)
        self.assertNotIn("row_below_old", queued_keys)

    def test_session_step_history_cutoff_treats_reply_badge_below_old_row_as_historical(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            scan = {
                "schema_version": 1,
                "session_id": "session_history_cutoff_reply_badge",
                "app_id": "tashuo",
                "captured_at": "2026-06-17T08:52:19Z",
                "scan_cursor": {"current": "page_1", "next": None, "exhausted": True},
                "scan_budget": 5,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_old_open_chat",
                            "candidate_type": "open_chat_candidate",
                            "visible_name": "Old Open",
                            "latest_preview": "你们已经可以进行会话了，开启聊天",
                            "latest_preview_hash": "old_open_chat_hash",
                            "timestamp_cue": "4个月前",
                            "unread_cue": "absent",
                            "position": 1,
                        },
                        {
                            "candidate_key": "row_reply_below_old",
                            "candidate_type": "continuation_candidate",
                            "visible_name": "Reply Below Old",
                            "latest_preview": "我晚上上班呀",
                            "latest_preview_hash": "reply_below_old_hash",
                            "timestamp_cue": "去回复 badge",
                            "unread_cue": "reply_badge",
                            "position": 2,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "history_cutoff_reply_badge_scan.json"
            self._write_json(scan_path, scan)

            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])

        self.assertEqual(step_exit, 0)
        self.assertTrue(step_payload["history_cutoff_reached"])
        self.assertEqual(step_payload["historical_entry_count"], 2)
        self.assertEqual(step_payload["scan_requests"], [])
        self.assertEqual(
            [item["candidate_key"] for item in step_payload["scheduled_actions"] if item["type"] == "historical_thread_skipped"],
            ["row_old_open_chat", "row_reply_below_old"],
        )
        self.assertEqual(states_exit, 0)
        states_by_key = {state["candidate_key"]: state for state in states_payload["states"]}
        self.assertEqual(states_by_key["row_old_open_chat"]["state"], "historical_thread")
        self.assertEqual(states_by_key["row_reply_below_old"]["state"], "historical_thread")
        queued_keys = [item["candidate_key"] for item in step_payload["next_priority_queue"]]
        self.assertNotIn("row_reply_below_old", queued_keys)

    def test_session_step_keeps_stable_waiting_state_without_thread_scan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            automation_dir = data_dir / "automation"
            automation_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(
                automation_dir / "states.json",
                {
                    "schema_version": 1,
                    "states": [
                        {
                            "schema_version": 1,
                            "match_id": "match_waiting",
                            "candidate_key": "row_waiting",
                            "state": "waiting_for_match",
                            "candidate_type": "continuation_candidate",
                            "seen_before": True,
                            "visible_name": "Waiting",
                            "last_preview_hash": "sha256:same_outbound_preview",
                            "last_session_id": "session_stable_waiting",
                        }
                    ],
                },
            )
            scan = {
                "schema_version": 1,
                "session_id": "session_stable_waiting",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 1,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_waiting",
                            "visible_name": "Waiting",
                            "latest_preview": "哈哈好的!",
                            "latest_preview_hash": "sha256:same_outbound_preview",
                            "timestamp_cue": "",
                            "unread_cue": "absent",
                            "position": 1,
                        }
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "stable_waiting_scan.json"
            self._write_json(scan_path, scan)

            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])

        self.assertEqual(step_exit, 0)
        self.assertEqual(step_payload["scan_requests"], [])
        self.assertEqual(states_exit, 0)
        self.assertEqual(states_payload["states"][0]["state"], "waiting_for_match")
        self.assertEqual(step_payload["next_priority_queue"][0]["state"], "waiting_for_match")

    def test_session_step_ignores_residual_unread_after_successful_send_when_preview_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            automation_dir = data_dir / "automation"
            automation_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(
                automation_dir / "states.json",
                {
                    "schema_version": 1,
                    "states": [
                        {
                            "schema_version": 1,
                            "match_id": "match_sent",
                            "candidate_key": "row_sent",
                            "state": "sent_waiting",
                            "candidate_type": "continuation_candidate",
                            "seen_before": True,
                            "last_preview_hash": "sha256:same_preview",
                            "last_outbound_action_id": "action_result_success",
                            "last_session_id": "session_residual_unread",
                        }
                    ],
                },
            )
            scan = {
                "schema_version": 1,
                "session_id": "session_residual_unread",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 1,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_sent",
                            "visible_name": "Sent",
                            "latest_preview": "同一个预览",
                            "latest_preview_hash": "sha256:same_preview",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "present",
                            "position": 1,
                        }
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "residual_unread_scan.json"
            self._write_json(scan_path, scan)

            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])

        self.assertEqual(step_exit, 0)
        self.assertEqual(step_payload["scan_requests"], [])
        self.assertEqual(states_exit, 0)
        self.assertEqual(states_payload["states"][0]["state"], "sent_waiting")

    def test_handoff_opportunity_without_existing_state_beats_new_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            priority_scan = _contact_exchange_scan_batch()
            priority_scan["scan_budget"] = 1
            priority_scan["message_list_snapshot"]["entries"].insert(
                0,
                {
                    "candidate_key": "row_new",
                    "visible_name": "New",
                    "latest_preview": "刚匹配",
                    "latest_preview_hash": "new_hash",
                    "timestamp_cue": "刚刚",
                    "unread_cue": "present",
                    "position": 1,
                },
            )
            scan_path = Path(temp_dir) / "priority_handoff_scan.json"
            self._write_json(scan_path, priority_scan)

            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])

        self.assertEqual(step_exit, 0)
        self.assertEqual(step_payload["processed_entry_count"], 1)
        self.assertEqual(step_payload["handoffs"][0]["candidate_key"], "row_iris")
        self.assertEqual(step_payload["scheduled_actions"][0]["type"], "scan_later")
        self.assertEqual(step_payload["scheduled_actions"][0]["candidate_key"], "row_new")
