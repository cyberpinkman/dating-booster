from tests.operator_host_loop_support import (
    AppObservation,
    FIXTURE_DIR,
    HostLoopCommandError,
    HostLoopError,
    HostLoopSupervisor,
    OperatorHostLoopTestCase,
    OperatorRepository,
    Path,
    _action_result_for_work_item,
    _audit_binding,
    _bumble_conversation_png,
    _iphone_current_thread_target_binding,
    _target_binding_for_work_item,
    _tashuo_mac_ios_app_conversation_with_messages_png,
    _thread_template,
    _tinder_conversation_send_button_png,
    _validate_managed_sequence_visual_confirmation,
    _wechat_managed_work_item,
    _write_draft_review_audit,
    argparse,
    hashlib,
    json,
    os,
    patch,
    shutil,
    subprocess,
    sys,
    tempfile,
)
from dating_boost.core.storage import JsonStorage


def _audit_events(data_dir: Path, filename: str) -> list[dict]:
    return JsonStorage(data_dir).read_jsonl(Path("audit") / filename)


class OperatorHostLoopCoreTests(OperatorHostLoopTestCase):
    def test_capabilities_expose_tinder_host_loop_without_live_gui_harness(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, payload = self._run_cli([
                "capabilities",
                "--json",
                "--data-dir",
                str(Path(temp_dir) / "data"),
            ])

            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["agent_native_capabilities"]["host_loop_supervisor"])
            self.assertTrue(payload["agent_native_capabilities"]["tinder_host_loop"])
            self.assertTrue(payload["agent_native_capabilities"]["bumble_host_loop"])
            self.assertTrue(payload["agent_native_capabilities"]["tashuo_host_loop"])
            self.assertIn("bumble", payload["agent_native_capabilities"]["host_loop_app_profiles"])
            self.assertIn("tashuo", payload["agent_native_capabilities"]["host_loop_app_profiles"])
            self.assertEqual(payload["agent_native_capabilities"]["host_loop_command"], "dating-boost-host-loop")
            self.assertFalse(payload["agent_native_capabilities"]["live_gui_harness"])

    def test_wechat_host_loop_init_writes_wechat_authorization_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"

            payload = self._run_script(
                "init",
                "--app-id",
                "wechat",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )

            auth_template = json.loads((data_dir / "automation" / "auth.template.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(auth_template["app_id"], "wechat")
            self.assertTrue((work_dir / "current_work_item.json").exists())

    def test_host_loop_rejects_user_supplied_max_pages_per_cycle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"

            payload = self._run_script(
                "run",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--max-pages-per-cycle",
                "2",
                "--json",
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "message_list_scan_boundary_framework_controlled")
        self.assertEqual(
            payload["message_list_scan_boundary"],
            {"type": "first_historical_row", "history_cutoff_days": 7},
        )

    def test_thread_observation_template_uses_valid_source_type(self):
        template = _thread_template(
            {"candidate_key": "row_ada"},
            {"app_id": "tashuo", "display_name": "她说", "native_gui_harness": {"backend": "mac_ios_app"}},
        )
        observation = template["observation"]
        observation["observation_id"] = "obs_template_001"
        observation["captured_at"] = "2026-06-11T12:00:00Z"
        observation["page_confidence"] = "high"
        observation["match_identity_hints"]["visible_name"] = "Ada"
        observation["match_identity_hints"]["conversation_fingerprint"] = "ada-latest"
        observation["conversation_observation"]["visible_messages"] = [
            {"sender": "match", "text": "你好"}
        ]

        parsed = AppObservation.from_dict(observation)

        self.assertEqual(parsed.source_type.value, "live_screenshot")

    def test_cli_thread_observation_template_uses_valid_source_type(self):
        exit_code, payload = self._run_cli([
            "observation",
            "template",
            "--type",
            "thread",
            "--app-id",
            "tashuo",
            "--json",
        ])
        observation = payload["observation"]
        observation["observation_id"] = "obs_template_cli_001"
        observation["captured_at"] = "2026-06-11T12:00:00Z"
        observation["page_confidence"] = "high"
        observation["match_identity_hints"]["visible_name"] = "Ada"
        observation["match_identity_hints"]["conversation_fingerprint"] = "ada-latest"
        observation["conversation_observation"]["visible_messages"] = [
            {"sender": "match", "text": "你好"}
        ]

        parsed = AppObservation.from_dict(observation)

        self.assertEqual(exit_code, 0)
        self.assertEqual(parsed.source_type.value, "live_screenshot")

    def test_managed_sequence_visual_confirmation_requires_exact_visible_text(self):
        work_item = {"action_request_id": "act_1", "payload_hash": "payload_hash_1"}
        message = {"index": 1, "message_hash": "message_hash_1", "text": "第一句"}
        payload = {
            "schema_version": 1,
            "action_request_id": "act_1",
            "payload_hash": "payload_hash_1",
            "message_index": 1,
            "message_hash": "message_hash_1",
            "result_status": "succeeded",
            "evidence": {
                "host_visual_outbound_exact_text_verified": True,
                "input_cleared_after_send": True,
                "post_action_screen_captured": True,
            },
        }

        reason = _validate_managed_sequence_visual_confirmation(payload, work_item, message)

        self.assertEqual(reason, "managed_sequence_visual_confirmation_visible_text_missing")

    def test_operator_prioritizes_open_thread_queue_by_relationship_priority(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            operator_dir = data_dir / "operator"
            automation_dir = data_dir / "automation"
            operator_dir.mkdir(parents=True, exist_ok=True)
            automation_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(
                operator_dir / "session.json",
                {
                    "schema_version": 1,
                    "session_id": "session_priority_queue",
                    "authorization_id": "auth_priority_queue",
                    "status": "active",
                    "current_work_item": None,
                    "management_mode": "high-throughput",
                    "max_threads_per_cycle": 12,
                    "max_pages_per_cycle": 3,
                    "cycle_send_limit": 3,
                    "cycle_send_count": 0,
                },
            )
            self._write_json(
                operator_dir / "work_queue.json",
                {
                    "schema_version": 1,
                    "work_items": [
                        {
                            "schema_version": 1,
                            "work_item_id": "work_open_thread_sherry",
                            "work_item_type": "open_thread",
                            "candidate_key": "row_sherry",
                        },
                        {
                            "schema_version": 1,
                            "work_item_id": "work_open_thread_xiaoyaowan",
                            "work_item_type": "open_thread",
                            "candidate_key": "row_xiaoyaowan",
                        },
                    ],
                },
            )
            self._write_json(
                automation_dir / "states.json",
                {
                    "schema_version": 1,
                    "states": [
                        {
                            "schema_version": 1,
                            "match_id": "match_sherry",
                            "candidate_key": "row_sherry",
                            "state": "needs_thread_scan",
                            "candidate_type": "new_match_candidate",
                            "unread_cue": "absent",
                        },
                        {
                            "schema_version": 1,
                            "match_id": "match_xiaoyaowan",
                            "candidate_key": "row_xiaoyaowan",
                            "state": "needs_thread_scan",
                            "candidate_type": "continuation_candidate",
                            "unread_cue": "present",
                        },
                    ],
                },
            )

            payload = OperatorRepository(data_dir).next_work_item()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["work_item"]["candidate_key"], "row_xiaoyaowan")

    def test_unsupported_app_blocks_host_loop_doctor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/operator_host_loop.py",
                    "doctor",
                    "--app-id",
                    "hinge",
                    "--data-dir",
                    str(Path(temp_dir) / "data"),
                    "--work-dir",
                    str(Path(temp_dir) / "work"),
                    "--json",
                ],
                cwd=Path.cwd(),
                env=self._env,
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["next_host_action"], "choose_supported_host_loop_app")
            self.assertEqual(payload["reason"], "unsupported app profile: hinge")

    def test_wechat_waiting_template_uses_wechat_desktop_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            auth_path = Path(temp_dir) / "wechat_auth.json"
            auth = json.loads((FIXTURE_DIR / "auth.json").read_text(encoding="utf-8"))
            auth["app_id"] = "wechat"
            self._write_json(auth_path, auth)
            self._bootstrap_data_dir(data_dir)

            payload = self._run_script(
                "run",
                "--app-id",
                "wechat",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(auth_path),
                "--goal",
                str(FIXTURE_DIR / "goal.json"),
                "--availability",
                str(FIXTURE_DIR / "availability.json"),
                "--work-dir",
                str(work_dir),
                "--initial-surface",
                "message-list",
                "--once",
                "--json",
            )
            work_item_id = payload["current_work_item"]["work_item_id"]
            template = json.loads(
                (work_dir / f"message_list_observation.{work_item_id}.template.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(payload["status"], "waiting_for_host")
            self.assertIn("send", payload["app_profile"]["native_blocked_actions"])
            self.assertEqual(template["app_id"], "wechat")
            self.assertIn("WeChat chat list", template["provenance"]["evidence"])
            self.assertNotIn("Tinder", json.dumps(template, ensure_ascii=False))

    def test_wechat_target_binding_falls_back_to_message_list_identity_hints(self):
        binding = _target_binding_for_work_item(
            {"match_id": "match_wechat", "candidate_key": "wechat_ada"},
            {
                "schema_version": 1,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "wechat_ada",
                            "visible_name": "Ada",
                            "match_identity_hints": {
                                "visible_name": "Ada",
                                "conversation_fingerprint": "Ada dinner thread",
                            },
                        }
                    ]
                },
                "thread_observations": [
                    {
                        "candidate_key": "wechat_ada",
                        "observation": {"match_identity_hints": {}},
                    }
                ],
            },
        )

        self.assertEqual(binding["target_match_id"], "match_wechat")
        self.assertEqual(binding["candidate_key"], "wechat_ada")
        self.assertEqual(binding["visible_name"], "Ada")
        self.assertEqual(binding["required_visible_text"], ["Ada"])
        self.assertEqual(binding["conversation_fingerprint"], "Ada dinner thread")

    def test_tashuo_target_binding_carries_message_list_visual_relocation_evidence(self):
        binding = _target_binding_for_work_item(
            {
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_xiaoyaowan",
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_xiaoyaowan",
                    "conversation_fingerprint": "xiaoyaowan-slow-warm",
                    "thread_evidence": {
                        "observation_id": "obs_thread",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "xiaoyaowan:slow-warm",
                        "visual_anchor_hash": "0123456789abcdef",
                    },
                },
            },
            {
                "schema_version": 1,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "tashuo_xiaoyaowan",
                            "visible_name": "小药丸儿",
                            "message_list_evidence": {
                                "source_state": "tashuo_chat_list",
                                "selection_method": "message_list_visual_anchor_scan",
                                "visual_anchor_hash": "fedcba9876543210",
                                "visual_anchor_region": {"x1": 0.05, "y1": 0.29, "x2": 0.95, "y2": 0.39},
                                "tap_ratio": {"x": 0.45, "y": 0.34},
                            },
                        }
                    ]
                },
                "thread_observations": [],
            },
        )

        self.assertEqual(binding["binding_type"], "current_thread_visual_identity")
        self.assertEqual(binding["message_list_evidence"]["selection_method"], "message_list_visual_anchor_scan")
        self.assertEqual(binding["message_list_evidence"]["visual_anchor_hash"], "fedcba9876543210")
        self.assertEqual(binding["message_list_evidence"]["tap_ratio"], {"x": 0.45, "y": 0.34})

    def test_tashuo_target_binding_derives_current_thread_visual_identity_from_thread_screenshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot_path = Path(temp_dir) / "tashuo_thread.png"
            screenshot_path.write_bytes(_tashuo_mac_ios_app_conversation_with_messages_png())

            binding = _target_binding_for_work_item(
                {"match_id": "match_tashuo", "candidate_key": "tashuo_haidian"},
                {
                    "schema_version": 1,
                    "message_list_snapshot": {"entries": []},
                    "thread_observations": [
                        {
                            "candidate_key": "tashuo_haidian",
                            "screenshot_ref": str(screenshot_path),
                            "assessment": {
                                "latest_inbound_fingerprint": "sha256:latest",
                            },
                            "observation": {
                                "observation_id": "obs_haidian",
                                "app_id": "tashuo",
                                "match_identity_hints": {
                                    "visible_name": "海淀大橙子",
                                    "conversation_fingerprint": "tashuo_haidian",
                                },
                            },
                        }
                    ],
                },
            )

        self.assertEqual(binding["binding_type"], "current_thread_visual_identity")
        self.assertEqual(binding["visible_name"], "海淀大橙子")
        self.assertEqual(binding["conversation_fingerprint"], "tashuo_haidian")
        self.assertEqual(binding["required_visible_text"], ["海淀大橙子"])
        self.assertEqual(binding["thread_evidence"]["observation_id"], "obs_haidian")
        self.assertEqual(binding["thread_evidence"]["screen_state"], "tashuo_conversation")
        self.assertEqual(binding["thread_evidence"]["latest_inbound_fingerprint"], "sha256:latest")
        self.assertTrue(binding["thread_evidence"]["visual_anchor_hash"])

    def test_iphone_mirroring_target_binding_derives_current_thread_visual_identity_from_thread_screenshot(self):
        fixtures = (
            ("tinder", _tinder_conversation_send_button_png(), "tinder_conversation"),
            ("bumble", _bumble_conversation_png(outgoing_bubble=False), "bumble_conversation"),
        )
        for app_id, screenshot_bytes, screen_state in fixtures:
            with self.subTest(app_id=app_id), tempfile.TemporaryDirectory() as temp_dir:
                screenshot_path = Path(temp_dir) / f"{app_id}_thread.png"
                screenshot_path.write_bytes(screenshot_bytes)

                binding = _target_binding_for_work_item(
                    {"match_id": f"match_{app_id}", "candidate_key": f"{app_id}_thread"},
                    {
                        "schema_version": 1,
                        "message_list_snapshot": {"entries": []},
                        "thread_observations": [
                            {
                                "candidate_key": f"{app_id}_thread",
                                "screenshot_ref": str(screenshot_path),
                                "assessment": {
                                    "latest_inbound_fingerprint": f"sha256:{app_id}:latest",
                                },
                                "observation": {
                                    "observation_id": f"obs_{app_id}",
                                    "app_id": app_id,
                                    "match_identity_hints": {
                                        "conversation_fingerprint": f"{app_id}:thread:fingerprint",
                                    },
                                },
                            }
                        ],
                    },
                )

                self.assertEqual(binding["binding_type"], "current_thread_visual_identity")
                self.assertNotIn("visible_name", binding)
                self.assertEqual(binding["conversation_fingerprint"], f"{app_id}:thread:fingerprint")
                self.assertEqual(binding["required_visible_text"], [])
                self.assertEqual(binding["thread_evidence"]["observation_id"], f"obs_{app_id}")
                self.assertEqual(binding["thread_evidence"]["screen_state"], screen_state)
                self.assertEqual(binding["thread_evidence"]["latest_inbound_fingerprint"], f"sha256:{app_id}:latest")
                self.assertTrue(binding["thread_evidence"]["visual_anchor_hash"])

    def test_fixture_host_loop_stage_mode_stages_message_without_recording_send_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"

            payload = self._run_script(
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )

            self.assertEqual(payload["status"], "staged_waiting_user_confirmation")
            self.assertEqual(payload["send_mode"], "stage")
            self.assertTrue((work_dir / "current_work_item.json").exists())
            work_item_id = payload["current_work_item"]["work_item_id"]
            self.assertTrue((work_dir / f"staged_verification.{work_item_id}.json").exists())
            self.assertTrue(_audit_events(data_dir, "stage_results.jsonl"))
            self.assertFalse(_audit_events(data_dir, "action_results.jsonl"))
            self.assertTrue(payload["stage_results_recorded"])
            stage_events = _audit_events(data_dir, "stage_results.jsonl")
            self.assertEqual(stage_events[0]["result_status"], "succeeded")
            self.assertIn("without recording send result", payload["stop_reason"])

    def test_tashuo_mac_ios_stage_mode_runs_harness_stage_draft_and_preserves_stage_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "是，感觉你这作息已经是夜间型选手了哈哈"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_stage",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="stage",
                    managed_gui_send=False,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=True,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                    initial_surface="message-list",
                    management_mode="conservative",
                    max_threads_per_cycle=1,
                    max_pages_per_cycle=None,
                    cycle_send_limit=1,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.update({
                "work_item_id": "work_tashuo_stage",
                "action_request_id": "act_tashuo_stage",
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_xiaoyaowan",
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_tashuo_stage",
                    target_match_id="match_tashuo",
                    payload_hash=payload_hash,
                ),
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_xiaoyaowan",
                    "visible_name": "小药丸儿",
                    "visual_anchor_hash": "0123456789abcdef",
                    "uses_header_ocr": False,
                },
            })
            recorded_result: dict[str, object] = {}
            stage_commands: list[tuple[str, ...]] = []

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if args[:3] == ("harness", "tashuo", "stage-draft"):
                    stage_commands.append(args)
                    self.assertIn("--runtime", args)
                    self.assertEqual(args[args.index("--runtime") + 1], "mac-ios-app")
                    text_path = Path(args[args.index("--text-file") + 1])
                    self.assertEqual(text_path.read_text(encoding="utf-8"), payload_text)
                    self.assertIn("--data-dir", args)
                    return {
                        "schema_version": 2,
                        "status": "ok",
                        "action": "stage_draft",
                        "app_id": "tashuo",
                        "harness_backend": "mac_ios_app",
                        "stage_attempt_status": "completed",
                        "staged_text_verified": True,
                        "staged_text_verification": {
                            "status": "verified",
                            "expected_payload_hash": payload_hash,
                            "expected_character_count": len(payload_text),
                            "screen_exact_text_ocr_verified": True,
                            "exact_text_ocr_verified": True,
                            "exact_text_ax_verified": False,
                            "screen": {
                                "path": str(work_dir / "harness" / "mac_ios_app.tashuo.after_stage_draft.delayed.png"),
                                "state": "tashuo_conversation",
                                "status": "ok",
                            },
                        },
                    }
                if args[:2] == ("operator", "record-stage-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "event_id": "stage_result_test",
                        "action_request_id": recorded_result["action_request_id"],
                        "result_status": recorded_result["result_status"],
                        "path": "audit/stage_results.jsonl",
                    }
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                result = supervisor._handle_send_message(work_item)

        self.assertEqual(result["status"], "staged_waiting_user_confirmation")
        self.assertEqual(len(stage_commands), 1)
        self.assertEqual(recorded_result["result_status"], "succeeded")
        self.assertEqual(recorded_result["stage_attempt_status"], "completed")
        self.assertEqual(recorded_result["staged_text_verification"]["status"], "verified")
        self.assertTrue(recorded_result["staged_text_verification"]["screen_exact_text_ocr_verified"])
        self.assertIn("screenshot_ref", recorded_result)
        self.assertFalse(recorded_result["evidence"]["sent"])
        self.assertFalse(_audit_events(data_dir, "action_results.jsonl"))

    def test_iphone_dating_stage_mode_runs_harness_stage_draft_without_runtime_override(self):
        for app_id, auth_id, match_id, candidate_key in (
            ("tinder", "auth_tinder_stage", "match_tinder", "tinder_ada"),
            ("bumble", "auth_bumble_stage", "match_bumble", "bumble_ada"),
        ):
            with self.subTest(app_id=app_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                data_dir = root / "data"
                work_dir = root / "work"
                auth_path = root / f"{app_id}_auth.json"
                payload_text = "今晚聊得挺舒服的。"
                payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
                self._write_json(auth_path, {
                    "schema_version": 1,
                    "authorization_id": auth_id,
                    "scope": "send_chat_messages",
                    "app_id": app_id,
                    "expires_at": "2099-01-01T00:00:00Z",
                    "allowed_actions": ["send_message"],
                    "autonomous_send": True,
                    "requires_post_action_verification": True,
                    "revoked_at": None,
                })
                supervisor = HostLoopSupervisor(
                    argparse.Namespace(
                        data_dir=data_dir,
                        authorization=auth_path,
                        goal=None,
                        availability=None,
                        app_id=app_id,
                        send_mode="stage",
                        managed_gui_send=False,
                        harness_runtime=None,
                        work_dir=work_dir,
                        max_steps=1,
                        once=True,
                        json=True,
                        fixture_host=None,
                        wait_timeout=None,
                        poll_interval=1.0,
                        adapter_package=None,
                        skill_package=None,
                        initial_surface="message-list",
                        management_mode="conservative",
                        max_threads_per_cycle=1,
                        max_pages_per_cycle=None,
                        cycle_send_limit=1,
                    )
                )
                work_dir.mkdir(parents=True, exist_ok=True)
                work_item = _wechat_managed_work_item(payload_text, payload_hash)
                work_item.update({
                    "work_item_id": f"work_{app_id}_stage",
                    "action_request_id": f"act_{app_id}_stage",
                    "match_id": match_id,
                    "candidate_key": candidate_key,
                    "autonomous_audit_binding": _audit_binding(
                        authorization_id=auth_id,
                        target_match_id=match_id,
                        payload_hash=payload_hash,
                    ),
                    "target_binding": _iphone_current_thread_target_binding(app_id, match_id, candidate_key),
                })
                recorded_result: dict[str, object] = {}
                stage_commands: list[tuple[str, ...]] = []

                def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                    if args[:3] == ("harness", app_id, "stage-draft"):
                        stage_commands.append(args)
                        self.assertNotIn("--runtime", args)
                        text_path = Path(args[args.index("--text-file") + 1])
                        self.assertEqual(text_path.read_text(encoding="utf-8"), payload_text)
                        self.assertIn("--data-dir", args)
                        return {
                            "schema_version": 1,
                            "status": "ok",
                            "action": "stage_draft",
                            "app_id": app_id,
                            "harness_backend": "iphone_mirroring_macos",
                            "stage_attempt_status": "completed",
                            "staged_text_verified": True,
                            "staged_text_verification": {
                                "status": "ok",
                                "expected_payload_hash": payload_hash,
                                "expected_character_count": len(payload_text),
                                "screen_exact_text_ocr_verified": True,
                                "exact_text_ocr_verified": True,
                                "screen": {
                                    "path": str(work_dir / "harness" / f"iphone_mirroring.{app_id}.after_stage_message.png"),
                                    "state": f"{app_id}_conversation",
                                    "status": "ok",
                                },
                            },
                        }
                    if args[:2] == ("operator", "record-stage-result"):
                        result_path = Path(args[args.index("--input") + 1])
                        recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                        return {
                            "schema_version": 1,
                            "status": "ok",
                            "event_id": f"stage_result_{app_id}",
                            "action_request_id": recorded_result["action_request_id"],
                            "result_status": recorded_result["result_status"],
                            "path": "audit/stage_results.jsonl",
                        }
                    raise AssertionError(args)

                with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                    result = supervisor._handle_send_message(work_item)

                self.assertEqual(result["status"], "staged_waiting_user_confirmation")
                self.assertEqual(len(stage_commands), 1)
                self.assertEqual(recorded_result["result_status"], "succeeded")
                self.assertEqual(recorded_result["stage_attempt_status"], "completed")
                self.assertEqual(recorded_result["staged_text_verification"]["status"], "ok")
                self.assertIn("iphone_mirroring_macos stage-draft", recorded_result["evidence"]["verification"])
                self.assertFalse(recorded_result["evidence"]["sent"])
                self.assertFalse(_audit_events(data_dir, "action_results.jsonl"))

    def test_host_loop_preflight_blocks_selected_runtime_scope_mismatch_before_cli_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            (data_dir / "runtime").mkdir(parents=True, exist_ok=True)
            self._write_json(data_dir / "runtime" / "session_scope.json", {
                "schema_version": 1,
                "status": "selected",
                "selected_app_id": "tashuo",
                "selected_runtime": "mac-ios-app",
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=None,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="stage",
                    managed_gui_send=False,
                    harness_runtime=None,
                    work_dir=work_dir,
                    max_steps=1,
                    once=True,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                    initial_surface="message-list",
                    management_mode="conservative",
                    max_threads_per_cycle=1,
                    max_pages_per_cycle=None,
                    cycle_send_limit=1,
                )
            )
            cli_calls = []

            def fake_run_cli_json(*args: str, **kwargs: object) -> dict[str, object]:
                cli_calls.append(args)
                return {"schema_version": 1, "status": "ok"}

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                with self.assertRaises(HostLoopError) as raised:
                    supervisor._preflight()

        self.assertIn("runtime_scope_mismatch", str(raised.exception))
        self.assertEqual(cli_calls, [])

    def test_tashuo_host_loop_preflight_requires_runtime_choice_before_cli_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=None,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="stage",
                    managed_gui_send=False,
                    harness_runtime=None,
                    work_dir=work_dir,
                    max_steps=1,
                    once=True,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                    initial_surface="message-list",
                    management_mode="conservative",
                    max_threads_per_cycle=1,
                    max_pages_per_cycle=None,
                    cycle_send_limit=1,
                )
            )
            cli_calls = []

            def fake_run_cli_json(*args: str, **kwargs: object) -> dict[str, object]:
                cli_calls.append(args)
                return {"schema_version": 1, "status": "ok"}

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                with self.assertRaises(HostLoopError) as raised:
                    supervisor._preflight()

        self.assertIn("runtime_scope_required", str(raised.exception))
        self.assertEqual(cli_calls, [])

    def test_fixture_message_list_initial_surface_does_not_call_real_harness_observe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            fixture_dir = root / "fixture"
            fixture_dir.mkdir()
            self._write_json(fixture_dir / "message_list_observation.json", {"schema_version": 1})
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=None,
                    goal=None,
                    availability=None,
                    app_id="tinder",
                    send_mode="stage",
                    managed_gui_send=False,
                    harness_runtime=None,
                    work_dir=work_dir,
                    max_steps=1,
                    once=True,
                    json=True,
                    fixture_host=fixture_dir,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                    initial_surface="auto",
                    management_mode="conservative",
                    max_threads_per_cycle=1,
                    max_pages_per_cycle=None,
                    cycle_send_limit=1,
                )
            )

            with patch.object(supervisor, "_run_cli_json", side_effect=AssertionError("real harness observe must not run")):
                surface = supervisor._initial_surface()

        self.assertEqual(surface, "message-list")

    def test_resume_send_work_item_starts_operator_session_before_handling(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "auth.json"
            self._write_json(auth_path, {"schema_version": 1, "authorization_id": "auth_resume"})
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item("hello", hashlib.sha256("hello".encode("utf-8")).hexdigest())
            work_item["work_item_id"] = "work_resume_send"
            self._write_json(work_dir / "current_work_item.json", work_item)
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="stage",
                    managed_gui_send=False,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=True,
                    json=True,
                    fixture_host=None,
                    wait_timeout=0,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                    initial_surface="current-thread",
                    management_mode="conservative",
                    max_threads_per_cycle=1,
                    max_pages_per_cycle=None,
                    cycle_send_limit=1,
                )
            )
            calls: list[object] = []

            def fake_start() -> dict[str, object]:
                calls.append("start")
                return {"schema_version": 1, "status": "active", "session_id": "session_resume"}

            def fake_handle(current: dict[str, object]) -> dict[str, object]:
                calls.append(("handle", supervisor.operator_session_active, current.get("work_item_id")))
                return supervisor._finish("staged_waiting_user_confirmation", "stage_resume_test", current=current)

            with (
                patch.object(supervisor, "_preflight", lambda: None),
                patch.object(supervisor, "_operator_session_status", return_value=None),
                patch.object(supervisor, "_start_operator_session", side_effect=fake_start),
                patch.object(supervisor, "_handle_send_message", side_effect=fake_handle),
            ):
                payload, exit_code = supervisor.run(resume=True)

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "staged_waiting_user_confirmation")
        self.assertEqual(calls, ["start", ("handle", True, "work_resume_send")])

    def test_run_reuses_active_operator_session_instead_of_restarting_wait_point(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "auth.json"
            self._write_json(auth_path, {"schema_version": 1, "authorization_id": "auth_active"})
            work_item = _wechat_managed_work_item("hello", hashlib.sha256("hello".encode("utf-8")).hexdigest())
            work_item["work_item_id"] = "work_active_send"
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="stage",
                    managed_gui_send=False,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=True,
                    json=True,
                    fixture_host=None,
                    wait_timeout=0,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                    initial_surface="current-thread",
                    management_mode="conservative",
                    max_threads_per_cycle=1,
                    max_pages_per_cycle=None,
                    cycle_send_limit=1,
                )
            )
            calls: list[object] = []

            def fake_run_cli_json(*args: str, **kwargs: object) -> dict[str, object]:
                calls.append(args)
                if args[:2] == ("operator", "next"):
                    return {"schema_version": 1, "status": "host_work_required", "work_item": work_item}
                raise AssertionError(f"unexpected cli call: {args}")

            def fail_start() -> dict[str, object]:
                raise AssertionError("host-loop run must not restart an active operator session")

            def fake_handle(current: dict[str, object]) -> dict[str, object]:
                return supervisor._finish("staged_waiting_user_confirmation", "stage_active_test", current=current)

            with (
                patch.object(supervisor, "_preflight", lambda: None),
                patch.object(supervisor, "_operator_session_status", return_value="active"),
                patch.object(supervisor, "_start_operator_session", side_effect=fail_start),
                patch.object(supervisor, "_run_cli_json", side_effect=fake_run_cli_json),
                patch.object(supervisor, "_handle_send_message", side_effect=fake_handle),
            ):
                payload, exit_code = supervisor.run()

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "staged_waiting_user_confirmation")
        self.assertEqual(payload["current_work_item"]["work_item_id"], "work_active_send")
        self.assertEqual(calls, [("operator", "next", "--data-dir", str(data_dir.resolve()))])

    def test_fixture_host_loop_current_thread_start_does_not_return_to_message_list_before_staging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            fixture_dir = root / "fixture"
            shutil.copytree(FIXTURE_DIR, fixture_dir)
            shutil.copyfile(
                fixture_dir / "threads" / "ada_1_preview_ada.json",
                fixture_dir / "current_thread_observation.json",
            )

            payload = self._run_script(
                "--fixture-host",
                str(fixture_dir),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )

            step_types = [step["work_item_type"] for step in payload["steps"]]
            self.assertEqual(payload["status"], "staged_waiting_user_confirmation")
            self.assertEqual(step_types[0], "observe_current_thread")
            self.assertNotIn("scan_message_list", step_types)
            self.assertNotIn("open_thread", step_types)
            self.assertIn("send_message", step_types)
            self.assertTrue(_audit_events(data_dir, "stage_results.jsonl"))
            self.assertFalse(_audit_events(data_dir, "action_results.jsonl"))

    def test_fixture_host_loop_blocks_with_target_profile_required_when_thread_profile_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            fixture_dir = root / "fixture"
            shutil.copytree(FIXTURE_DIR, fixture_dir)
            thread_path = fixture_dir / "threads" / "ada_1_preview_ada.json"
            thread_payload = json.loads(thread_path.read_text(encoding="utf-8"))
            thread_payload["observation"]["profile_observation"] = {
                "profile_text": "",
                "photo_cues": [],
                "hook_candidates": [],
                "review_status": "missing",
                "evidence": "Profile was not opened before drafting.",
            }
            self._write_json(thread_path, thread_payload)

            payload = self._run_script(
                "--fixture-host",
                str(fixture_dir),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["stop_reason"], "target_profile_required")
        self.assertEqual(payload["next_host_action"], "open_target_profile_and_ingest_memory")

    def test_confirm_staged_cancel_clears_pending_send_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            staged_payload = self._run_script(
                "run",
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )
            work_item_id = staged_payload["current_work_item"]["work_item_id"]

            cancel_payload = self._run_script(
                "confirm-staged",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--cancel",
                "--json",
            )
            status_payload = self._run_script(
                "status",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )

            self.assertEqual(cancel_payload["status"], "staged_cancelled")
            self.assertEqual(status_payload["status"], "idle")
            self.assertFalse((work_dir / "current_work_item.json").exists())
            self.assertFalse((data_dir / "operator" / "current_work_item.json").exists())
            self.assertFalse((work_dir / f"staged_verification.{work_item_id}.json").exists())

    def test_confirm_staged_action_result_is_idempotent_and_clears_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            staged_payload = self._run_script(
                "run",
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )
            work_item = staged_payload["current_work_item"]
            action_result_path = Path(temp_dir) / "action_result.json"
            self._write_json(action_result_path, _action_result_for_work_item(work_item))

            first_confirm = self._run_script(
                "confirm-staged",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--action-result",
                str(action_result_path),
                "--json",
            )
            status_payload = self._run_script(
                "status",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )
            second_confirm = self._run_script(
                "confirm-staged",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--action-result",
                str(action_result_path),
                "--json",
            )
            audit_events = _audit_events(data_dir, "action_results.jsonl")

            self.assertEqual(first_confirm["status"], "confirmed")
            self.assertEqual(status_payload["status"], "idle")
            self.assertEqual(second_confirm["status"], "blocked")
            self.assertEqual(second_confirm["stop_reason"], "no_staged_send_work_item")
            self.assertEqual(len(audit_events), 1)
            self.assertFalse((work_dir / "current_work_item.json").exists())
            self.assertFalse((data_dir / "operator" / "current_work_item.json").exists())

    def test_confirm_staged_requires_valid_staged_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            staged_payload = self._run_script(
                "run",
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )
            work_item = staged_payload["current_work_item"]
            staged_path = work_dir / f"staged_verification.{work_item['work_item_id']}.json"
            staged_path.unlink()

            missing_payload = self._run_script(
                "confirm-staged",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )
            bad_staged = {
                "schema_version": 1,
                "verification_type": "staged_text",
                "action_request_id": work_item["action_request_id"],
                "match_id": work_item["match_id"],
                "candidate_key": work_item["candidate_key"],
                "expected_payload_hash": work_item["payload_hash"],
                "expected_payload_text": work_item["payload_text"],
                "result_status": "failed",
                "staged_text": work_item["payload_text"],
            }
            self._write_json(staged_path, bad_staged)
            failed_payload = self._run_script(
                "confirm-staged",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )

            self.assertEqual(missing_payload["status"], "blocked")
            self.assertEqual(missing_payload["stop_reason"], "staged_verification_required_before_confirmation")
            self.assertEqual(failed_payload["status"], "blocked")
            self.assertEqual(failed_payload["stop_reason"], "staged text was not verified as succeeded")
            self.assertFalse(_audit_events(data_dir, "action_results.jsonl"))

    def test_fixture_host_loop_live_mode_requires_staged_verification_before_recording_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"

            payload = self._run_script(
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "live",
                "--max-steps",
                "8",
                "--json",
            )

            self.assertIn(payload["status"], {"completed", "waiting", "wait"})
            events = _audit_events(data_dir, "action_results.jsonl")
            self.assertTrue(events)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["result_status"], "succeeded")
            self.assertTrue(payload["staged_verifications"])
            self.assertTrue(payload["action_results_recorded"])
            self.assertFalse(any(path.name.startswith("staged_verification.") for path in work_dir.glob("*.json")))
            self.assertTrue(any("staged_verification" in path.name for path in (work_dir / "consumed").iterdir()))
            self.assertIn("machine_report_path", payload)
            self.assertTrue(JsonStorage(data_dir).exists(Path("automation") / "reports" / "machine_latest.json"))
            self.assertIn("human_report_path", payload)
            self.assertTrue(JsonStorage(data_dir).exists(Path("automation") / "reports" / "human_latest.md"))
            self.assertEqual(payload["next_host_action"], "present_relationship_progress_report")
            report = payload["relationship_progress_report"]
            self.assertEqual(report["format"], "markdown")
            self.assertEqual(report["human_report_path"], payload["human_report_path"])
            self.assertIn("Conversation Plans", report["markdown"])
            self.assertIn("Next Priority Queue", report["markdown"])

    def test_live_mode_blocks_when_safety_is_paused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            self._run_cli(["safety", "pause", "--data-dir", str(data_dir), "--reason", "manual-stop", "--json"])

            payload = self._run_script(
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "live",
                "--max-steps",
                "8",
                "--json",
            )

            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["stop_reason"], "safety_paused")
            self.assertFalse(_audit_events(data_dir, "action_results.jsonl"))

    def test_live_mode_requires_explicit_live_send_authorization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            auth_path = Path(temp_dir) / "auth_without_live.json"
            auth = json.loads((FIXTURE_DIR / "auth.json").read_text(encoding="utf-8"))
            auth.pop("live_send", None)
            self._write_json(auth_path, auth)

            payload = self._run_script(
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(auth_path),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "live",
                "--max-steps",
                "8",
                "--json",
            )

            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["stop_reason"], "live_send_authorization_required")
            self.assertFalse(_audit_events(data_dir, "action_results.jsonl"))

    def test_live_mode_blocks_authorization_match_mismatch_before_action_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            auth_path = Path(temp_dir) / "auth_wrong_match.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tinder_live",
                "scope": "send_chat_messages",
                "app_id": "tinder",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_match_ids": ["match_bea"],
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tinder",
                    send_mode="live",
                    managed_gui_send=False,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = {
                "schema_version": 1,
                "work_item_id": "work_tinder_send",
                "work_item_type": "send_message",
                "action_request_id": "act_tinder_send",
                "match_id": "match_ada",
                "candidate_key": "tinder_ada",
                "payload_text": payload_text,
                "payload_hash": payload_hash,
                "precondition_hash": "pre_hash",
                "autonomous_audit_binding": {
                    "schema_version": 1,
                    "binding_type": "autonomous_authorization",
                    "authorization_id": "auth_tinder_live",
                    "action": "send_message",
                    "target_match_id": "match_ada",
                    "payload_hash": payload_hash,
                    "precondition_hash": "pre_hash",
                },
                "pre_action_observation_id": "obs_before",
                "target_profile_observation": {
                    "review_status": "observed",
                    "profile_text": "喜欢日料，周末常去看展。",
                    "photo_cues": [],
                    "hook_candidates": ["日料", "看展"],
                    "evidence": "Profile was reviewed before drafting.",
                },
                "requires_post_action_verification": True,
                "draft_review_id": "draft_review_fixture",
                "draft_evidence_id": "draft_evidence_fixture",
                "draft_generation_id": "draft_generation_fixture",
                "latest_turn_id": "latest_turn_fixture",
                "conversation_thread_revision": 1,
                "draft_self_review_summary": {
                    "schema_version": 1,
                    "status": "ok",
                    "ai_or_weird_probability": 20,
                    "attempts": 1,
                    "source": "unit_fixture",
                },
                "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
            }
            staged_path = supervisor._work_file(work_item, "staged_verification")
            self._write_json(staged_path, {
                "schema_version": 1,
                "verification_type": "staged_text",
                "action_request_id": work_item["action_request_id"],
                "match_id": work_item["match_id"],
                "candidate_key": work_item["candidate_key"],
                "expected_payload_hash": payload_hash,
                "expected_payload_text": payload_text,
                "result_status": "succeeded",
                "staged_text": payload_text,
                "evidence": {"verification": "Input box text was checked before send."},
            })

            _write_draft_review_audit(data_dir, work_item)

            payload = supervisor._handle_send_message(work_item)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["stop_reason"], "authorization_match_not_allowed")
        self.assertFalse(any(path.name.startswith("action_result.") for path in work_dir.glob("*.json")))
