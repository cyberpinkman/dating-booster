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
from dating_boost.core.storage import JsonStorage

class AutomationSessionLifecycleTests(AutomationSessionTestCase):
    def test_automation_context_uses_projection_plus_latest_observation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            repo = AutomationRepository(data_dir)
            first_payload = json.loads(Path("tests/fixtures/intelligence/app_observation_chat.json").read_text(encoding="utf-8"))
            first_observation = AppObservation.from_dict(first_payload)
            first_ingest = repo._store_observation(first_observation)
            match_id = first_ingest["match_id"]

            second_payload = dict(first_payload)
            second_payload["observation_id"] = "obs_chat_002"
            second_payload["captured_at"] = "2026-05-26T00:00:00Z"
            second_payload["profile_observation"] = {
                "profile_text": "",
                "photo_cues": [],
                "hook_candidates": [],
            }
            second_payload["conversation_observation"] = {
                "visible_messages": [
                    {"sender": "user", "text": "哈哈这个我记得"},
                    {"sender": "match", "text": "那你周末一般会去听现场吗"},
                ],
                "input_state": "empty",
                "thread_cues": ["weekend live music question"],
            }
            second_observation = AppObservation.from_dict(second_payload)
            repo._store_observation(second_observation)

            context_pack = repo._context_pack(match_id, second_observation)

            items = {item["label"]: item["content"] for item in context_pack["items"]}
            self.assertIn("match_hooks", items)
            self.assertIn("Ask about live music", items["match_hooks"])
            self.assertEqual(
                items["latest_inbound_messages"][-1]["text"],
                "那你周末一般会去听现场吗",
            )

    def test_automation_context_exposes_only_identity_diagnostic_for_untrusted_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            repo = AutomationRepository(data_dir)
            match_id = "match_untrusted"
            payload = json.loads(Path("tests/fixtures/intelligence/app_observation_chat.json").read_text(encoding="utf-8"))
            observation = AppObservation.from_dict(payload)
            MemoryRepository(data_dir).save_projection(
                match_id,
                MatchMemoryProjection(
                    match_id=match_id,
                    identity_status=IdentityTrustStatus.NEEDS_CONFIRMATION,
                    trusted_for_context=False,
                    trusted_for_managed_send=False,
                    updated_at="2026-06-06T00:00:00Z",
                ),
            )

            context_pack = repo._context_pack(match_id, observation)
            encoded_context = json.dumps(context_pack, ensure_ascii=False)
            items = {item["label"]: item["content"] for item in context_pack["items"]}

            self.assertIn("identity_trust", items)
            self.assertNotIn("latest_inbound_messages", items)
            self.assertNotIn("recent_messages", items)
            self.assertNotIn("It was. What are you up to this weekend?", encoded_context)

    def test_session_stop_report_and_resume(self):
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
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])
            stop_exit, stop_payload, _ = self._run([
                "automation",
                "session",
                "stop",
                "--data-dir",
                str(data_dir),
            ])
            latest_exit, latest_payload, _ = self._run([
                "automation",
                "report",
                "latest",
                "--data-dir",
                str(data_dir),
            ])
            latest_md_exit, latest_md_text = self._run_text([
                "automation",
                "report",
                "latest",
                "--data-dir",
                str(data_dir),
                "--format",
                "md",
            ])
            restart_exit, restart_payload, _ = self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            if restart_exit != 0 and restart_payload.get("status") == "needs_memory_review":
                from dating_boost.core.memory.review_queue import ReviewQueueRepository
                review_repo = ReviewQueueRepository(data_dir)
                pending = review_repo.load_items(status="pending")
                session_id = pending[0].session_id if pending else ""
                confirm_token = f"memory-review:{session_id}"
                reject_ids = [item.review_item_id for item in pending]
                if reject_ids:
                    self._run([
                        "memory", "review", "decide",
                        "--data-dir", str(data_dir),
                        "--confirm", confirm_token,
                        "--reject", *reject_ids,
                    ])
                restart_exit, restart_payload, _ = self._run([
                    "automation",
                    "session",
                    "start",
                    "--data-dir",
                    str(data_dir),
                    "--authorization",
                    str(FIXTURE_DIR / "auth_send.json"),
                ])

            self.assertEqual(stop_exit, 0)
            self.assertEqual(stop_payload["status"], "stopped")
            storage = JsonStorage(data_dir)
            self.assertTrue(storage.exists(Path(stop_payload["machine_report_path"])))
            self.assertTrue(storage.exists(Path(stop_payload["human_report_path"])))
            self.assertGreaterEqual(stop_payload["summary"]["new_match_count"], 3)
            self.assertEqual(stop_payload["summary"]["action_request_count"], 1)
            self.assertGreaterEqual(stop_payload["summary"]["handoff_count"], 2)
            self.assertEqual(latest_exit, 0)
            self.assertEqual(latest_payload["status"], "ok")
            self.assertEqual(latest_payload["machine_report"]["session_id"], stop_payload["session_id"])
            self.assertEqual(latest_md_exit, 0)
            self.assertIn("Next Priority Queue", latest_md_text)
            self.assertIn("Handoffs", latest_md_text)
            self.assertNotIn("欠你一顿好吃的", latest_md_text)
            self.assertEqual(restart_exit, 0)
            self.assertEqual(restart_payload["resumed_from_report"], stop_payload["machine_report_path"])

    def test_pause_and_resume_gate_session_steps(self):
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
            pause_exit, pause_payload, _ = self._run([
                "automation",
                "pause",
                "--data-dir",
                str(data_dir),
            ])
            blocked_exit, blocked_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])
            resume_exit, resume_payload, _ = self._run([
                "automation",
                "resume",
                "--data-dir",
                str(data_dir),
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

            self.assertEqual(pause_exit, 0)
            self.assertTrue(pause_payload["paused"])
            self.assertEqual(blocked_exit, 0)
            self.assertEqual(blocked_payload["status"], "blocked")
            self.assertEqual(blocked_payload["reason"], "session_paused")
            self.assertEqual(resume_exit, 0)
            self.assertFalse(resume_payload["paused"])
            self.assertEqual(step_exit, 0)
            self.assertEqual(step_payload["status"], "ok")

    def test_stopped_session_blocks_step_until_restarted(self):
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
                "stop",
                "--data-dir",
                str(data_dir),
            ])

            blocked_exit, blocked_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
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
            resumed_exit, resumed_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])

            self.assertEqual(blocked_exit, 0)
            self.assertEqual(blocked_payload["status"], "blocked")
            self.assertEqual(blocked_payload["reason"], "session_stopped")
            self.assertEqual(blocked_payload["action_requests"], [])
            self.assertEqual(resumed_exit, 0)
            self.assertEqual(resumed_payload["status"], "ok")

    def test_revoked_or_expired_authorization_blocks_automatic_send(self):
        for auth_file in ("auth_revoked.json", "auth_expired.json"):
            with self.subTest(auth_file=auth_file):
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
                        str(FIXTURE_DIR / auth_file),
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

                    self.assertEqual(step_exit, 0)
                    self.assertEqual(step_payload["status"], "blocked")
                    self.assertEqual(step_payload["reason"], "authorization_expired_or_revoked")
                    self.assertEqual(step_payload["action_requests"], [])
                    self.assertIn("authorization_expired_or_revoked", step_payload["warnings"])

    def test_authorization_scope_app_allowlist_quiet_hours_and_verification_gate_send(self):
        cases = [
            ("draft_only_scope", {"scope": "draft_only"}, "authorization_scope_not_send_chat_messages"),
            ("wrong_app", {"app_id": "wechat"}, "authorization_app_mismatch"),
            (
                "match_not_allowed",
                {"allowed_match_ids": ["match_not_ada"]},
                "authorization_match_not_allowed",
            ),
            (
                "quiet_hours",
                {"quiet_hours": [{"start": "00:00", "end": "23:59"}]},
                "authorization_quiet_hours",
            ),
            (
                "missing_post_action_verification",
                {"requires_post_action_verification": False},
                "authorization_requires_post_action_verification",
            ),
        ]
        for name, overrides, warning in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    data_dir = Path(temp_dir) / "data"
                    auth_path = Path(temp_dir) / f"{name}.json"
                    auth_payload = json.loads((FIXTURE_DIR / "auth_send.json").read_text(encoding="utf-8"))
                    auth_payload.update(overrides)
                    self._write_json(auth_path, auth_payload)
                    self._init_profile(data_dir)
                    self._run([
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
                        str(FIXTURE_DIR / "scan_batch_initial.json"),
                    ])

                    self.assertEqual(step_exit, 0)
                    self.assertEqual(step_payload["action_requests"], [])
                    self.assertIn(warning, step_payload["warnings"])

    def test_contact_exchange_handoff_has_specific_reason(self):
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
            scan_path = Path(temp_dir) / "contact_exchange_scan.json"
            self._write_json(scan_path, _contact_exchange_scan_batch())

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
            self.assertEqual(step_payload["handoffs"][0]["reason"], "contact_exchange")
            self.assertEqual(states_exit, 0)
            self.assertEqual(states_payload["states"][0]["handoff_reason"], "contact_exchange")

    def test_authorization_expiration_uses_current_clock(self):
        with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-28T00:00:00Z"}):
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

                step_exit, step_payload, _ = self._run([
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(FIXTURE_DIR / "scan_batch_initial.json"),
                ])

                self.assertEqual(step_exit, 0)
                self.assertEqual(step_payload["status"], "blocked")
                self.assertEqual(step_payload["reason"], "authorization_expired_or_revoked")
