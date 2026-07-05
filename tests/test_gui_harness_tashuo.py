from tests.gui_harness_support import *


class GuiHarnessTashuoOtherTests(GuiHarnessTestCase):
    def test_tashuo_mac_ios_app_post_action_delay_uses_two_seconds(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=_tashuo_messages_bottom_nav_png(),
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac-ios-app")

        delay = tashuo_native._tashuo_post_action_observation_delay_seconds(harness, fallback=0.45)

        self.assertEqual(delay, 2.0)

    def test_tashuo_mac_ios_app_open_bundle_failure_recovers_when_app_already_active(self):
        class OpenFailRunner:
            def __init__(self):
                self.commands = []

            def run(self, command, *, input=None):
                self.commands.append(command)
                if command[:2] == ["open", "-b"]:
                    return _result(returncode=1, stderr="_LSOpenURLsWithCompletionHandler() failed with error -1712.")
                return _result()

        class Session:
            def __init__(self):
                self.runner = OpenFailRunner()

            def _mac_ios_active_application_probe(self):
                return {
                    "status": "ok",
                    "frontmost_application": {"name": "她说", "bundle_id": "com.intelcupid.tashuo"},
                    "target_application": {"name": "她说", "bundle_id": "com.intelcupid.tashuo", "active": True},
                }

        payload = tashuo_native._open_tashuo_mac_ios_app_bundle(Session(), "com.intelcupid.tashuo")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["recovered_by"], "active_probe_after_failed_open")
        self.assertEqual(payload["active_probe_after_failed_open"]["status"], "ok")

    def test_tashuo_mac_ios_app_open_bundle_retries_transient_failed_active_probe(self):
        class OpenFailRunner:
            def __init__(self):
                self.commands = []

            def run(self, command, *, input=None):
                self.commands.append(command)
                if command[:2] == ["open", "-b"]:
                    return _result(returncode=1, stderr="_LSOpenURLsWithCompletionHandler() failed with error -1712.")
                return _result()

        class Session:
            def __init__(self):
                self.runner = OpenFailRunner()
                self.probes = 0

            def _mac_ios_active_application_probe(self):
                self.probes += 1
                if self.probes == 1:
                    return {"status": "blocked", "reason": "frontmost_application_not_target"}
                return {
                    "status": "ok",
                    "frontmost_application": {"name": "她说", "bundle_id": "com.intelcupid.tashuo"},
                    "target_application": {"name": "她说", "bundle_id": "com.intelcupid.tashuo", "active": True},
                }

        session = Session()
        payload = tashuo_native._open_tashuo_mac_ios_app_bundle(session, "com.intelcupid.tashuo")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["recovered_by"], "active_probe_after_failed_open")
        self.assertEqual(session.probes, 2)
        self.assertEqual(len(payload["attempts"]), 2)
        self.assertEqual(session.runner.commands.count(["open", "-b", "com.intelcupid.tashuo"]), 2)

    def test_tashuo_mac_ios_app_already_sent_treats_ax_missing_value_as_empty_input(self):
        draft = "你好啊，接上了"
        runner = FakeRunner(
            ocr_text=[
                f"朵朵\n你好啊\n{draft}\n点击此处输入文字\n",
                f"朵朵\n你好啊\n{draft}\n点击此处输入文字\n",
            ],
            screenshot_bytes=[
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
            ],
            window_name="她说",
            ax_text_area_value="missing value",
            ax_static_text_values=["朵朵", "你好啊", draft, "点击此处输入文字"],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(draft, dry_run=False, output_dir=Path(tempfile.mkdtemp()))

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["already_sent"])
        self.assertTrue(payload["evidence"]["input_cleared_after_send"])
        self.assertTrue(payload["evidence"]["outbound_exact_text_verified"])
        self.assertTrue(payload["evidence"]["outbound_exact_text_ax_verified"])
        self.assertFalse(payload["evidence"]["outbound_exact_text_ocr_verified"])
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_tashuo_action_and_workflow_dry_runs_are_navigation_only(self):
        runner = FakeRunner(ocr_text="消息\n待回答 (0)\n全部消息\n推荐\n飞行\n消息\n我的\n")
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner)

        action = harness.run_action("open-conversation", conversation_row=2, dry_run=True)
        workflow = harness.run_workflow("chat-read-match-profile", conversation_row=1, dry_run=True)
        scroll = harness.run_action("conversation-list-scroll-down", dry_run=True)

        self.assertEqual(action["status"], "ok")
        self.assertEqual(action["planned_steps"][0]["intent"], "tap_tashuo_conversation_row")
        self.assertEqual(action["planned_steps"][0]["tap_ratio"], {"x": 0.45, "y": 0.64})
        self.assertIn("question_gate_send", action["blocked_actions"])
        self.assertEqual(workflow["status"], "ok")
        self.assertIn("capture_profile_read_step", [step["intent"] for step in workflow["planned_steps"]])
        self.assertTrue(all(step.get("risk") == "navigation_only" for step in workflow["planned_steps"]))
        self.assertEqual(scroll["status"], "ok")
        self.assertEqual(
            scroll["planned_steps"][0]["wheel"],
            {"x": 0.5, "y": 0.78, "delta_y": -18, "delta_x": 0, "repeats": 14, "interval_us": 18000},
        )
        self.assertEqual(scroll["planned_steps"][0]["risk"], "navigation_only")

    def test_tashuo_message_list_relocation_preserves_corrected_action_tap_when_current_region_matches(self):
        width, height = 288, 541
        current_png = _png_from_pixels(
            [[(255, 255, 255, 255) for _x in range(width)] for _y in range(height)],
            width,
            height,
        )
        row_region = {"x1": 0.03, "y1": 0.497, "x2": 0.22, "y2": 0.657}
        row_visual_hash = _png_average_hash(current_png, region=row_region)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "current-list.png"
            path.write_bytes(current_png)

            location = tashuo_native._locate_tashuo_message_list_visual_target(
                {"status": "ok", "state": "tashuo_chat_list", "path": str(path)},
                {
                    "status": "ok",
                    "evidence_type": "message_list_visual_anchor",
                    "visual_anchor_hash": row_visual_hash,
                    "visual_anchor_region": row_region,
                    "visual_anchor_scan_region": {"x1": 0.0, "y1": 0.16, "x2": 1.0, "y2": 0.95},
                    "visual_anchor_max_hamming_distance": 0,
                    "tap_ratio": {"x": 0.87, "y": 0.577},
                    "tap_ratio_source": "corrected_all_messages_row_action",
                },
            )

        self.assertEqual(location["status"], "ok")
        self.assertEqual(location["location_method"], "message_list_visual_anchor_current_region_tap")
        self.assertTrue(location["current_region_verified"])
        self.assertFalse(location["visual_anchor_scanned"])
        self.assertEqual(location["tap_ratio_source"], "corrected_all_messages_row_action")
        self.assertAlmostEqual(location["tap_ratio"]["x"], 0.87, delta=0.001)
        self.assertAlmostEqual(location["tap_ratio"]["y"], 0.577, delta=0.001)
        self.assertFalse(location["tap_adjustment"]["adjusted"])

    def test_tashuo_bottom_tab_action_requires_complete_top_level_nav(self):
        runner = FakeRunner(
            ocr_text="她说\nVIP\n谁喜欢了我\n",
            missing_commands={"xcrun"},
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner)

        payload = harness.run_action("open-chats", dry_run=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "tashuo_top_level_tab_bar_not_verified")
        self.assertNotIn("executed_steps", payload)

    def test_tashuo_question_gate_policy_is_in_payloads(self):
        runner = FakeRunner(ocr_text="消息\n待回答 (1)\n全部消息\n推荐\n飞行\n消息\n我的\n")
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner)

        observe = harness.observe()
        action = harness.run_action("open-question-gate", dry_run=True)
        workflow = harness.run_workflow("question-gate-open", dry_run=True)

        for payload in (observe, action, workflow):
            with self.subTest(target=payload.get("target") or payload.get("action") or payload.get("workflow")):
                policy = payload["question_gate_policy"]
                self.assertEqual(policy["scope"], "tashuo_question_gate")
                self.assertEqual(policy["female_user"]["agent_decision_authority"], "none")
                self.assertIn("ask_user_to_decide", policy["female_user"]["agent_allowed_actions"])
                self.assertTrue(policy["male_user"]["agent_may_draft_reply"])
                self.assertTrue(policy["male_user"]["requires_user_confirmation_before_send"])
                self.assertFalse(policy["male_user"]["current_harness_stage_supported"])
                self.assertFalse(policy["male_user"]["current_harness_send_supported"])
                self.assertFalse(policy["male_user"]["autonomous_question_gate_send_supported"])
                self.assertIn("question_gate_skip", payload["blocked_actions"])
                self.assertIn("question_gate_decide_reply_satisfaction", payload["blocked_actions"])
                self.assertIn("question_gate_send", payload["blocked_actions"])

    def test_cli_passes_explicit_runtime_to_tashuo_adapter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _select_runtime_scope(data_dir, "tashuo", "mac-ios-app")
            with _patch_cli_adapter() as harness_class:
                harness_class.return_value.launch_tashuo.return_value = {
                    "schema_version": 2,
                    "status": "ok",
                    "app_id": "tashuo",
                    "harness_backend": "mac_ios_app",
                }

                exit_code, payload = _run_cli_json([
                    "harness",
                    "tashuo",
                    "launch",
                    "--runtime",
                    "mac-ios-app",
                    "--data-dir",
                    str(data_dir),
                    "--dry-run",
                    "--json",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(harness_class.call_args.kwargs["runtime"], "mac-ios-app")
