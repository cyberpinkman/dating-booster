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

class AutomationSessionPriorityTests(AutomationSessionTestCase):
    def test_capabilities_expose_automation_session_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, payload, _ = self._run([
                "capabilities",
                "--json",
                "--data-dir",
                str(Path(temp_dir) / "data"),
            ])

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["schema_versions"]["scan_batch"], 1)
            self.assertEqual(payload["schema_versions"]["automation_state"], 1)
            self.assertEqual(payload["schema_versions"]["appointment_ledger"], 1)
            self.assertEqual(payload["schema_versions"]["progress_report"], 1)
            self.assertIn("automation session start", payload["supported_commands"])
            self.assertIn("automation session step", payload["supported_commands"])
            self.assertIn("automation report latest", payload["supported_commands"])
            self.assertTrue(payload["agent_native_capabilities"]["automation_session"])
            self.assertTrue(payload["agent_native_capabilities"]["appointment_ledger"])

    def test_entry_priority_keeps_needs_reply_ahead_of_sent_waiting(self):
        sent_entry = {"candidate_key": "row_sent", "unread_cue": "unknown"}
        reply_entry = {"candidate_key": "row_reply", "unread_cue": "unknown"}
        ordered = _prioritize_entries(
            [sent_entry, reply_entry],
            states_by_candidate={
                "row_sent": {"state": "sent_waiting"},
                "row_reply": {"state": "needs_reply"},
            },
            thread_items={
                "row_reply": {
                    "assessment": {
                        "recommended_next": "reply",
                        "continuation_opportunity": "yes",
                    }
                }
            },
        )

        self.assertEqual([entry["candidate_key"] for entry in ordered], ["row_reply", "row_sent"])

    def test_entry_priority_keeps_draft_ready_reply_badge_ahead_of_unsignaled_scan(self):
        draft_ready_entry = {"candidate_key": "row_draft_ready", "unread_cue": "reply_badge"}
        unsignaled_entry = {"candidate_key": "row_unsignaled", "unread_cue": "absent"}
        ordered = _prioritize_entries(
            [unsignaled_entry, draft_ready_entry],
            states_by_candidate={
                "row_draft_ready": {
                    "state": "draft_ready",
                    "candidate_type": "continuation_candidate",
                },
                "row_unsignaled": {
                    "state": "needs_thread_scan",
                    "candidate_type": "continuation_candidate",
                },
            },
            thread_items={},
        )

        self.assertEqual([entry["candidate_key"] for entry in ordered], ["row_draft_ready", "row_unsignaled"])

    def test_entry_priority_demotes_stale_waiting_thread_observation(self):
        sent_entry = {"candidate_key": "row_sent", "unread_cue": "unknown"}
        scan_later_entry = {"candidate_key": "row_scan_later", "unread_cue": "unknown"}
        ordered = _prioritize_entries(
            [sent_entry, scan_later_entry],
            states_by_candidate={
                "row_sent": {
                    "state": "sent_waiting",
                    "latest_inbound_fingerprint": "same_inbound",
                },
                "row_scan_later": {"state": "scan_later"},
            },
            thread_items={
                "row_sent": {
                    "assessment": {
                        "recommended_next": "reply",
                        "continuation_opportunity": "yes",
                        "latest_inbound_fingerprint": "same_inbound",
                    }
                },
                "row_scan_later": {
                    "assessment": {
                        "recommended_next": "reply",
                        "continuation_opportunity": "yes",
                    }
                },
            },
        )

        self.assertEqual([entry["candidate_key"] for entry in ordered], ["row_scan_later", "row_sent"])

    def test_next_priority_queue_excludes_stale_activation_candidate_without_unread(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "match_old",
                    "candidate_key": "row_old",
                    "state": "draft_ready",
                    "updated_at": "2026-05-01T00:00:00Z",
                    "unread_cue": "absent",
                },
                {
                    "match_id": "match_unread_old",
                    "candidate_key": "row_unread_old",
                    "state": "needs_thread_scan",
                    "updated_at": "2026-05-01T00:00:00Z",
                    "unread_cue": "present",
                    "candidate_type": "continuation_candidate",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_unread_old"])

    def test_next_priority_queue_excludes_tashuo_pending_question_gate_state(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "provisional_tashuo_visual_8181c3ffffffff80",
                    "candidate_key": "tashuo_visual_8181c3ffffffff80",
                    "state": "needs_thread_scan",
                    "candidate_type": "new_match_candidate",
                    "visible_name": "Pending question avatar (illustration)",
                    "updated_at": "2026-06-29T17:34:33Z",
                },
                {
                    "match_id": "match_ordinary",
                    "candidate_key": "row_ordinary",
                    "state": "needs_thread_scan",
                    "candidate_type": "continuation_candidate",
                    "visible_name": "Ada",
                    "unread_cue": "present",
                    "updated_at": "2026-06-29T17:34:33Z",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_ordinary"])

    def test_next_priority_queue_excludes_tashuo_structural_tab_header_state(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "provisional_tashuo_visual_000000ffffe7e7ef",
                    "candidate_key": "tashuo_visual_000000ffffe7e7ef",
                    "state": "needs_thread_scan",
                    "candidate_type": "new_match_candidate",
                    "visible_name": "Tab header: 消息 / 动态",
                    "updated_at": "2026-06-29T17:59:32Z",
                },
                {
                    "match_id": "match_ordinary",
                    "candidate_key": "row_ordinary",
                    "state": "needs_thread_scan",
                    "candidate_type": "continuation_candidate",
                    "visible_name": "Ada",
                    "unread_cue": "present",
                    "updated_at": "2026-06-29T17:59:32Z",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_ordinary"])

    def test_next_priority_queue_excludes_tashuo_anonymous_question_card_state(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "provisional_tashuo_visual_0080c1ffffffffff",
                    "candidate_key": "tashuo_visual_0080c1ffffffffff",
                    "state": "needs_thread_scan",
                    "candidate_type": "new_match_candidate",
                    "visible_name": "匿名提问卡片",
                    "updated_at": "2026-06-29T18:08:28Z",
                },
                {
                    "match_id": "match_ordinary",
                    "candidate_key": "row_ordinary",
                    "state": "needs_thread_scan",
                    "candidate_type": "continuation_candidate",
                    "visible_name": "Ada",
                    "unread_cue": "present",
                    "updated_at": "2026-06-29T18:08:28Z",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_ordinary"])

    def test_next_priority_queue_promotes_recent_scan_later_continuation_with_inbound(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "match_opening",
                    "candidate_key": "row_opening",
                    "state": "needs_thread_scan",
                    "candidate_type": "new_match_candidate",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
                {
                    "match_id": "match_reply",
                    "candidate_key": "row_reply",
                    "state": "scan_later",
                    "candidate_type": "continuation_candidate",
                    "latest_inbound_fingerprint": "reply:fresh",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_reply", "row_opening"])

    def test_next_priority_queue_demotes_open_chat_behind_unseen_continuation(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "match_a_open",
                    "candidate_key": "row_open_chat",
                    "state": "needs_thread_scan",
                    "candidate_type": "open_chat_candidate",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
                {
                    "match_id": "match_z_continuation",
                    "candidate_key": "row_continuation",
                    "state": "needs_thread_scan",
                    "candidate_type": "continuation_candidate",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_continuation", "row_open_chat"])
        self.assertEqual(queue[0]["priority"], 4)
        self.assertEqual(queue[1]["priority"], 5)

    def test_next_priority_queue_promotes_pending_send_request(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "match_scan",
                    "candidate_key": "row_scan",
                    "state": "needs_thread_scan",
                    "candidate_type": "continuation_candidate",
                    "unread_cue": "present",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
                {
                    "match_id": "match_send",
                    "candidate_key": "row_send",
                    "state": "send_requested",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_send", "row_scan"])
        self.assertEqual(queue[0]["priority"], 1)

    def test_next_priority_queue_promotes_draft_ready_reply_badge(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "match_opening",
                    "candidate_key": "row_opening",
                    "state": "needs_thread_scan",
                    "candidate_type": "new_match_candidate",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
                {
                    "match_id": "match_reply",
                    "candidate_key": "row_reply",
                    "state": "draft_ready",
                    "candidate_type": "continuation_candidate",
                    "unread_cue": "reply_badge",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_reply", "row_opening"])
        self.assertEqual(queue[0]["priority"], 2)
