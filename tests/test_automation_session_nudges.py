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


class AutomationSessionNudgeTests(AutomationSessionTestCase):
    def test_mismatched_action_result_does_not_complete_pending_send(self):
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
            _, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])
            action_request = step_payload["action_requests"][0]
            action_result = dict(json.loads((FIXTURE_DIR / "action_result_ada.json").read_text()))
            action_result["action_request_id"] = action_request["action_request_id"]
            action_result["target_match_id"] = action_request["match_id"]
            action_result["payload_hash"] = "wrong_payload_hash"
            mismatch_path = Path(temp_dir) / "mismatch_result.json"
            self._write_json(mismatch_path, action_result)

            result_exit, _, _ = self._run([
                "action",
                "record-result",
                "--data-dir",
                str(data_dir),
                "--input",
                str(mismatch_path),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(result_exit, 0)
            self.assertEqual(states_exit, 0)
            state_by_match = {state["match_id"]: state for state in states_payload["states"]}
            state = state_by_match[action_request["match_id"]]
            self.assertEqual(state["state"], "send_requested")
            self.assertEqual(state["last_action_result_error"], "payload_hash_mismatch")

    def test_same_inbound_is_nudged_only_once(self):
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

            first_exit, first_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_nudge.json"),
            ])
            repeat_exit, repeat_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_nudge.json"),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(first_exit, 0)
            self.assertEqual(first_payload["state_updates"][0]["state"], "nudge_scheduled")
            self.assertEqual(first_payload["scheduled_actions"][0]["type"], "nudge_later")
            self.assertEqual(first_payload["scheduled_actions"][0]["candidate_key"], "row_gia")
            self.assertEqual(first_payload["action_requests"], [])
            self.assertEqual(repeat_exit, 0)
            self.assertEqual(repeat_payload["state_updates"][0]["state"], "nudge_scheduled")
            self.assertEqual(repeat_payload["scheduled_actions"], [])
            self.assertEqual(states_exit, 0)
            state = states_payload["states"][0]
            self.assertIsNone(state["last_nudged_inbound_fingerprint"])
            self.assertEqual(state["nudge_count_since_inbound"], 0)
            self.assertEqual(state["next_due_at"], "2026-05-26T00:30:00Z")

    def test_due_nudge_with_fresh_draft_generates_one_send_request(self):
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
            self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_nudge.json"),
            ])
            due_scan = json.loads((FIXTURE_DIR / "scan_batch_nudge.json").read_text(encoding="utf-8"))
            due_scan["captured_at"] = "2026-05-26T01:01:00Z"
            due_scan["thread_observations"][0]["draft"] = _nudge_draft()
            due_scan_path = Path(temp_dir) / "due_scan.json"
            self._write_json(due_scan_path, due_scan)

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T01:00:00Z"}):
                due_exit, due_payload, _ = self._run([
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(due_scan_path),
                ])
                repeat_exit, repeat_payload, _ = self._run([
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(due_scan_path),
                ])
                states_exit, states_payload, _ = self._run([
                    "automation",
                    "get-state",
                    "--data-dir",
                    str(data_dir),
                ])

        self.assertEqual(due_exit, 0)
        self.assertEqual(len(due_payload["action_requests"]), 1)
        self.assertIn("刚想起来", due_payload["action_requests"][0]["payload_text"])
        self.assertEqual(repeat_exit, 0)
        self.assertEqual(repeat_payload["action_requests"], [])
        self.assertIn("duplicate_send_request_suppressed", repeat_payload["warnings"])
        self.assertEqual(states_exit, 0)
        state = states_payload["states"][0]
        self.assertEqual(state["last_nudged_inbound_fingerprint"], "gia:in:absurd-comedy")
        self.assertEqual(state["nudge_count_since_inbound"], 1)

    def test_due_nudge_blocks_when_target_profile_was_not_observed(self):
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
            self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_nudge.json"),
            ])
            due_scan = json.loads((FIXTURE_DIR / "scan_batch_nudge.json").read_text(encoding="utf-8"))
            due_scan["captured_at"] = "2026-05-26T01:01:00Z"
            due_scan["thread_observations"][0]["draft"] = _nudge_draft()
            due_scan["thread_observations"][0]["observation"]["profile_observation"] = {
                "profile_text": "",
                "photo_cues": [],
                "hook_candidates": [],
                "review_status": "missing",
                "evidence": "Profile was not opened before a due nudge.",
            }
            due_scan_path = Path(temp_dir) / "due_scan_missing_profile.json"
            self._write_json(due_scan_path, due_scan)

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T01:00:00Z"}):
                due_exit, due_payload, _ = self._run([
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(due_scan_path),
                ])
                states_exit, states_payload, _ = self._run([
                    "automation",
                    "get-state",
                    "--data-dir",
                    str(data_dir),
                ])

        self.assertEqual(due_exit, 0)
        self.assertEqual(due_payload["action_requests"], [])
        self.assertIn("target_profile_required", due_payload["warnings"])
        self.assertEqual(states_exit, 0)
        self.assertEqual(states_payload["states"][0]["state"], "needs_target_profile")
