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

class AutomationSessionSendGateTests(AutomationSessionTestCase):
    def test_session_step_processes_scan_batch_and_prevents_duplicate_sends(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "goal",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "goal_meet.json"),
            ])
            self._run([
                "automation",
                "availability",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "availability_weekend.json"),
            ])
            start_exit, start_payload, _ = self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])
            repeat_exit, repeat_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])

            self.assertEqual(start_exit, 0)
            self.assertEqual(start_payload["status"], "active")
            self.assertEqual(step_exit, 0)
            self.assertEqual(step_payload["status"], "ok")
            self.assertEqual(step_payload["scan_budget"], 5)
            self.assertEqual(step_payload["processed_entry_count"], 5)
            self.assertEqual(len(step_payload["action_requests"]), 1)
            action_request = step_payload["action_requests"][0]
            self.assertEqual(action_request["action"], "send_message")
            self.assertEqual(action_request["pre_action_observation_id"], "obs_ada_001")
            self.assertTrue(action_request["requires_post_action_verification"])
            self.assertIn("欠你一顿好吃的", action_request["payload_text"])
            self.assertIn("disclosure_source", action_request)
            self.assertIn("used_user_material_ids", action_request)
            self.assertIn("question_debt_after", action_request)
            self.assertIn("reciprocity_balance_after", action_request)
            self.assertIn("low_investment_repair_applied", action_request)
            self.assertEqual(len(step_payload["handoffs"]), 2)
            self.assertEqual(step_payload["handoffs"][0]["reason"], "appointment_details_requested")
            self.assertTrue(step_payload["handoffs"][1]["slot_conflict"])
            self.assertIn("row_cora", [item["candidate_key"] for item in step_payload["scan_requests"]])
            self.assertIn("row_faye", [item["candidate_key"] for item in step_payload["scheduled_actions"]])

            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])
            self.assertEqual(states_exit, 0)
            states_by_candidate = {
                state["candidate_key"]: state["state"]
                for state in states_payload["states"]
                if state.get("candidate_key")
            }
            self.assertEqual(states_by_candidate["row_ada"], "send_requested")
            self.assertEqual(states_by_candidate["row_cora"], "needs_thread_scan")
            self.assertEqual(states_by_candidate["row_bea"], "appointment_handoff")

            self.assertEqual(repeat_exit, 0)
            self.assertEqual(repeat_payload["action_requests"], [])
            self.assertIn("duplicate_send_request_suppressed", repeat_payload["warnings"])

            action_result = dict(json.loads((FIXTURE_DIR / "action_result_ada.json").read_text()))
            action_result["action_request_id"] = action_request["action_request_id"]
            action_result["target_match_id"] = action_request["match_id"]
            action_result["payload_hash"] = action_request["payload_hash"]
            action_result_path = Path(temp_dir) / "action_result.json"
            action_result_path.write_text(json.dumps(action_result, ensure_ascii=False), encoding="utf-8")
            result_exit, result_payload, _ = self._run([
                "action",
                "record-result",
                "--data-dir",
                str(data_dir),
                "--input",
                str(action_result_path),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])
            self.assertEqual(result_exit, 0)
            self.assertEqual(result_payload["action_request_id"], action_request["action_request_id"])
            state_by_match = {state["match_id"]: state for state in states_payload["states"]}
            self.assertEqual(state_by_match[action_request["match_id"]]["state"], "sent_waiting")

            post_result_repeat_exit, post_result_repeat_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])
            self.assertEqual(post_result_repeat_exit, 0)
            self.assertEqual(post_result_repeat_payload["action_requests"], [])
            self.assertIn("duplicate_send_request_suppressed", post_result_repeat_payload["warnings"])

    def test_session_step_stage_only_soft_accepts_standalone_reviewed_generation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "goal",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "goal_meet.json"),
            ])
            self._run([
                "automation",
                "availability",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "availability_weekend.json"),
            ])
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            ada = scan["thread_observations"][0]
            ada["draft"]["draft_self_review_summary"]["ai_or_weird_probability"] = 55
            ada["draft"]["draft_self_review_summary"]["status"] = "needs_revision"
            ada["standalone_draft_review"] = {
                "schema_version": 1,
                "allowed_for_stage": True,
                "allowed_for_live_send": False,
                "primary_reason": "soft_accept_stage_only",
            }
            scan_path = Path(temp_dir) / "scan_stage_soft_accept.json"
            self._write_json(scan_path, scan)

            start_exit, _, _ = self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])

        self.assertEqual(start_exit, 0)
        self.assertEqual(step_exit, 0)
        self.assertEqual(len(step_payload["action_requests"]), 1)
        action_request = step_payload["action_requests"][0]
        self.assertEqual(action_request["candidate_key"], "row_ada")
        self.assertEqual(action_request["action"], "send_message")
        self.assertEqual(action_request["draft_self_review_summary"]["ai_or_weird_probability"], 55)
        self.assertEqual(action_request["draft_self_review_summary"]["status"], "stage_only_soft_accepted")
        self.assertIn("stage_only_draft_self_review_soft_accepted", step_payload["warnings"])

    def test_session_step_stage_only_soft_accepts_standalone_reviewed_policy(self):
        review = DraftReviewDecision(
            schema_version=1,
            status="needs_revision",
            allowed_for_display=True,
            allowed_for_stage=True,
            allowed_for_managed_send=False,
            requires_user_confirmation=False,
            primary_reason="draft_strategy_delta_missing",
            summary={"stage": True, "managed_live": False},
            findings=[
                DraftReviewFinding(
                    code="draft_strategy_delta_missing",
                    category="strategy",
                    severity="medium",
                    message="needs stronger managed-live strategy",
                    revision_hint="add a concrete handle",
                    blocks_display=False,
                    blocks_stage=False,
                    blocks_managed_send=True,
                )
            ],
            revision_hints=["add a concrete handle"],
            payload_hash="review_payload_hash",
            payload_format="single",
            message_count=1,
            review_id="review_stage_only_policy",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "goal",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "goal_meet.json"),
            ])
            self._run([
                "automation",
                "availability",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "availability_weekend.json"),
            ])
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            ada = scan["thread_observations"][0]
            ada["standalone_draft_review"] = {
                "schema_version": 1,
                "allowed_for_stage": True,
                "allowed_for_managed_send": False,
                "primary_reason": "draft_strategy_delta_missing",
            }
            scan_path = Path(temp_dir) / "scan_stage_policy_soft_accept.json"
            self._write_json(scan_path, scan)

            start_exit, _, _ = self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            with patch("dating_boost.core.automation.review_draft", return_value=review):
                step_exit, step_payload, _ = self._run([
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(scan_path),
                ])

        self.assertEqual(start_exit, 0)
        self.assertEqual(step_exit, 0)
        self.assertEqual(len(step_payload["action_requests"]), 1)
        action_request = step_payload["action_requests"][0]
        self.assertEqual(action_request["policy"]["allowed"], True)
        self.assertEqual(action_request["policy"]["allowed_for_stage"], True)
        self.assertEqual(action_request["policy"]["allowed_for_managed_send"], False)
        self.assertEqual(action_request["policy"]["reason"], "stage_only_draft_review_soft_accepted")
        self.assertIn("stage_only_draft_review_soft_accepted", step_payload["warnings"])

    def test_session_step_live_send_does_not_use_stage_only_soft_accept(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "goal",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "goal_meet.json"),
            ])
            self._run([
                "automation",
                "availability",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "availability_weekend.json"),
            ])
            auth = json.loads((FIXTURE_DIR / "auth_send.json").read_text(encoding="utf-8"))
            auth["authorization_id"] = "auth_fixture_live_send"
            auth["live_send"] = True
            auth_path = Path(temp_dir) / "auth_live.json"
            self._write_json(auth_path, auth)
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            ada = scan["thread_observations"][0]
            ada["draft"]["draft_self_review_summary"]["ai_or_weird_probability"] = 55
            ada["draft"]["draft_self_review_summary"]["status"] = "needs_revision"
            ada["standalone_draft_review"] = {
                "schema_version": 1,
                "allowed_for_stage": True,
                "allowed_for_live_send": False,
                "primary_reason": "soft_accept_stage_only",
            }
            scan_path = Path(temp_dir) / "scan_live_blocks_soft_accept.json"
            self._write_json(scan_path, scan)

            start_exit, _, _ = self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(auth_path),
            ])
            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])

        self.assertEqual(start_exit, 0)
        self.assertEqual(step_exit, 0)
        self.assertEqual(step_payload["action_requests"], [])
        self.assertIn("draft_self_review_probability_high", step_payload["warnings"])
        self.assertIn("draft_generation_required", step_payload["warnings"])
        revision_requests = [
            item
            for item in step_payload["scan_requests"]
            if item.get("candidate_key") == "row_ada" and item.get("reason") == "draft_revision_required"
        ]
        self.assertEqual(len(revision_requests), 1)
        self.assertEqual(revision_requests[0]["draft_revision_reason"], "draft_self_review_probability_high")

    def test_session_step_live_send_does_not_use_stage_only_policy_soft_accept(self):
        review = DraftReviewDecision(
            schema_version=1,
            status="needs_revision",
            allowed_for_display=True,
            allowed_for_stage=True,
            allowed_for_managed_send=False,
            requires_user_confirmation=False,
            primary_reason="draft_strategy_delta_missing",
            summary={"stage": True, "managed_live": False},
            findings=[
                DraftReviewFinding(
                    code="draft_strategy_delta_missing",
                    category="strategy",
                    severity="medium",
                    message="needs stronger managed-live strategy",
                    revision_hint="add a concrete handle",
                    blocks_display=False,
                    blocks_stage=False,
                    blocks_managed_send=True,
                )
            ],
            revision_hints=["add a concrete handle"],
            payload_hash="review_payload_hash",
            payload_format="single",
            message_count=1,
            review_id="review_live_policy",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "goal",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "goal_meet.json"),
            ])
            self._run([
                "automation",
                "availability",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "availability_weekend.json"),
            ])
            auth = json.loads((FIXTURE_DIR / "auth_send.json").read_text(encoding="utf-8"))
            auth["authorization_id"] = "auth_fixture_live_send"
            auth["live_send"] = True
            auth_path = Path(temp_dir) / "auth_live.json"
            self._write_json(auth_path, auth)
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            ada = scan["thread_observations"][0]
            ada["standalone_draft_review"] = {
                "schema_version": 1,
                "allowed_for_stage": True,
                "allowed_for_managed_send": False,
                "primary_reason": "draft_strategy_delta_missing",
            }
            scan_path = Path(temp_dir) / "scan_live_policy_blocks_soft_accept.json"
            self._write_json(scan_path, scan)

            start_exit, _, _ = self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(auth_path),
            ])
            with patch("dating_boost.core.automation.review_draft", return_value=review):
                step_exit, step_payload, _ = self._run([
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(scan_path),
                ])

        self.assertEqual(start_exit, 0)
        self.assertEqual(step_exit, 0)
        self.assertEqual(step_payload["action_requests"], [])
        self.assertIn("draft_strategy_delta_missing", step_payload["warnings"])
        self.assertIn("draft_revision_required", step_payload["warnings"])

    def test_failed_send_result_allows_same_payload_retry_with_new_request_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "goal",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "goal_meet.json"),
            ])
            self._run([
                "automation",
                "availability",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "availability_weekend.json"),
            ])
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
            first_request = step_payload["action_requests"][0]

            failed_result = dict(json.loads((FIXTURE_DIR / "action_result_ada.json").read_text()))
            failed_result["action_request_id"] = first_request["action_request_id"]
            failed_result["target_match_id"] = first_request["match_id"]
            failed_result["payload_hash"] = first_request["payload_hash"]
            failed_result["result_status"] = "failed"
            failed_result["post_action_observation_id"] = None
            failed_result["evidence"] = {
                "failure_reason": "target_binding_visual_relocation_exhausted_before_stage"
            }
            failed_path = Path(temp_dir) / "failed_action_result.json"
            self._write_json(failed_path, failed_result)

            result_exit, _, _ = self._run([
                "action",
                "record-result",
                "--data-dir",
                str(data_dir),
                "--input",
                str(failed_path),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])
            retry_scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            retry_scan["captured_at"] = "2026-05-26T10:01:00Z"
            retry_scan["thread_observations"][0]["observation"]["observation_id"] = "obs_ada_002"
            retry_scan_path = Path(temp_dir) / "retry_scan_batch.json"
            self._write_json(retry_scan_path, retry_scan)
            retry_exit, retry_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(retry_scan_path),
            ])

        self.assertEqual(result_exit, 0)
        self.assertEqual(states_exit, 0)
        state_by_match = {state["match_id"]: state for state in states_payload["states"]}
        failed_state = state_by_match[first_request["match_id"]]
        self.assertEqual(failed_state["state"], "draft_ready")
        self.assertNotIn("last_outbound_payload_hash", failed_state)
        self.assertEqual(failed_state["last_failed_outbound_payload_hash"], first_request["payload_hash"])
        self.assertEqual(failed_state["send_retry_count"], 1)
        self.assertEqual(retry_exit, 0)
        self.assertEqual(len(retry_payload["action_requests"]), 1)
        retry_request = retry_payload["action_requests"][0]
        self.assertEqual(retry_request["payload_hash"], first_request["payload_hash"])
        self.assertNotEqual(retry_request["action_request_id"], first_request["action_request_id"])
        self.assertTrue(retry_request["action_request_id"].endswith("_retry1"))
        self.assertNotIn("duplicate_send_request_suppressed", retry_payload["warnings"])

    def test_stale_same_payload_hash_in_non_active_state_retries_instead_of_suppressing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "goal",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "goal_meet.json"),
            ])
            self._run([
                "automation",
                "availability",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "availability_weekend.json"),
            ])
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            _, first_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])
            first_request = first_payload["action_requests"][0]

            repo = AutomationRepository(data_dir)
            states = repo.load_states()
            for state in states:
                if state.get("match_id") == first_request["match_id"]:
                    state["state"] = "needs_thread_scan"
                    state["last_outbound_action_id"] = "action_result_failed_legacy"
                    state.pop("last_failed_outbound_payload_hash", None)
                    state.pop("last_failed_action_request_id", None)
                    state.pop("last_failed_action_result_event_id", None)
                    state.pop("send_retry_count", None)
            repo.save_states(states)

            retry_scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            retry_scan["captured_at"] = "2026-05-26T10:02:00Z"
            retry_scan["thread_observations"][0]["observation"]["observation_id"] = "obs_ada_legacy_retry"
            retry_scan_path = Path(temp_dir) / "retry_scan_batch.json"
            self._write_json(retry_scan_path, retry_scan)
            retry_exit, retry_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(retry_scan_path),
            ])
            retry_state = {
                state["match_id"]: state
                for state in AutomationRepository(data_dir).load_states()
            }[first_request["match_id"]]

        self.assertEqual(retry_exit, 0)
        self.assertEqual(len(retry_payload["action_requests"]), 1)
        retry_request = retry_payload["action_requests"][0]
        self.assertEqual(retry_request["payload_hash"], first_request["payload_hash"])
        self.assertNotEqual(retry_request["action_request_id"], first_request["action_request_id"])
        self.assertTrue(retry_request["action_request_id"].endswith("_retry1"))
        self.assertNotIn("duplicate_send_request_suppressed", retry_payload["warnings"])
        self.assertEqual(retry_state["state"], "send_requested")
        self.assertEqual(retry_state["send_retry_count"], 1)

    def test_session_step_blocks_send_when_target_profile_was_not_observed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "goal",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "goal_meet.json"),
            ])
            self._run([
                "automation",
                "availability",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "availability_weekend.json"),
            ])
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            scan["scan_budget"] = 1
            first_thread = scan["thread_observations"][0]
            scan["message_list_snapshot"]["entries"] = [scan["message_list_snapshot"]["entries"][0]]
            scan["thread_observations"] = [first_thread]
            first_thread["observation"]["profile_observation"] = {
                "profile_text": "",
                "photo_cues": [],
                "hook_candidates": [],
                "review_status": "missing",
                "evidence": "Profile was not opened before drafting.",
            }
            scan_path = root / "scan_missing_target_profile.json"
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
            self.assertEqual(step_payload["action_requests"], [])
            self.assertIn("target_profile_required", step_payload["warnings"])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])
            self.assertEqual(states_exit, 0)
            self.assertEqual(states_payload["states"][0]["state"], "needs_target_profile")

    def test_session_step_requeues_revision_when_content_policy_blocks_draft(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "goal",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "goal_meet.json"),
            ])
            self._run([
                "automation",
                "availability",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "availability_weekend.json"),
            ])
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            scan["scan_budget"] = 1
            scan["message_list_snapshot"]["entries"] = [scan["message_list_snapshot"]["entries"][0]]
            first_thread = scan["thread_observations"][0]
            scan["thread_observations"] = [first_thread]
            planner = first_thread["planner_assessment"]
            planner["recommended_stage"] = "soft_invite_probe"
            planner["recommended_move"] = "soft_invite_probe"
            planner["soft_invite_allowed"] = True
            planner["scores"]["logistics_readiness"] = 55
            planner["next_milestone"] = "轻量试探见面意愿，但不能直接敲定具体时间地点"
            draft = first_thread["draft"]
            draft["conversation_move"] = "soft_invite_probe"
            draft["best_reply"] = "那明天19:30我们去三里屯喝一杯，你看这样行吗"
            draft["safer_reply"] = "那明天19:30找个地方坐坐？"
            draft["bolder_reply"] = "那明晚三里屯见，感觉可以直接兑现奖励了"
            scan_path = root / "scan_policy_blocked_draft.json"
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
        self.assertEqual(step_payload["action_requests"], [])
        self.assertIn("draft_blocked", step_payload["warnings"])
        self.assertIn("draft_revision_required", step_payload["warnings"])
        self.assertEqual(len(step_payload["scan_requests"]), 1)
        revision_request = step_payload["scan_requests"][0]
        self.assertEqual(revision_request["candidate_key"], "row_ada")
        self.assertEqual(revision_request["reason"], "draft_revision_required")
        self.assertTrue(revision_request["requires_revised_draft"])
        self.assertEqual(revision_request["draft_revision_reason"], "content_managed_handoff_required")
        self.assertEqual(states_exit, 0)
        states_by_key = {state["candidate_key"]: state for state in states_payload["states"]}
        self.assertEqual(states_by_key["row_ada"]["state"], "needs_reply")
        self.assertTrue(states_by_key["row_ada"]["draft_revision_required"])
        self.assertEqual(states_by_key["row_ada"]["draft_revision_reason"], "content_managed_handoff_required")

    def test_non_nudge_send_cannot_bypass_latest_turn_by_declaring_nudge_draft_kind(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            first_thread = scan["thread_observations"][0]
            first_thread["observation"]["conversation_observation"]["visible_messages"] = [
                {"sender": "user", "text": "你猜猜会有什么奖励"},
                {"sender": "user", "text": "那我来定"},
            ]
            first_thread["draft"]["draft_kind"] = "nudge"
            observation = AppObservation.from_dict(first_thread["observation"])
            repo = AutomationRepository(data_dir)
            ingest = repo._store_observation(observation)
            action_requests: list[dict] = []
            scan_requests: list[dict] = []
            warnings: list[str] = []
            state = {
                "match_id": ingest["match_id"],
                "candidate_key": "row_ada",
                "state": "needs_reply",
            }

            repo._queue_send_request(
                action_requests=action_requests,
                scan_requests=scan_requests,
                warnings=warnings,
                state=state,
                match_id=ingest["match_id"],
                candidate_key="row_ada",
                observation=observation,
                draft_payload=first_thread["draft"],
                latest_fingerprint="ada:in:reward-choice",
                is_nudge=False,
                authorization=json.loads((FIXTURE_DIR / "auth_send.json").read_text(encoding="utf-8")),
            )

        self.assertEqual(action_requests, [])
        self.assertIn("latest_turn_required", warnings)
        self.assertIn("draft_evidence_required", warnings)
