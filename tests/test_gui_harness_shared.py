from tests.gui_harness_support import (
    json, hashlib, re, struct,
    tempfile, unittest, zlib, contextmanager,
    redirect_stdout, StringIO, Path, patch,
    create_adapter, tashuo_native, SUPPORTED_NATIVE_HARNESS_APPS, main,
    classify_bumble_screen_text, classify_screen_text, classify_wechat_screen_text, classify_tashuo_capture,
    classify_tashuo_screen_image, classify_tashuo_screen_text, combine_tashuo_screen_states, tashuo_layout_hints,
    tashuo_thread_cues_from_text, core_graphics_command_v, core_graphics_drag, WindowInfo,
    FakeRunner, _result, _run_cli_json, _select_runtime_scope,
    _patch_cli_adapter, _ocr_tsv_for_line, _write_json, _write_draft_review_audit,
    _live_send_auth, _autonomous_audit_binding, _planner_evidence, _draft_generation_binding,
    GuiHarnessTestCase, _profile_top_structure_png, _profile_tab_active_png, _tinder_bottom_nav_png,
    _bumble_browse_png, _bumble_chat_list_png, _bumble_conversation_png, _iphone_message_list_with_target_row_png,
    _tashuo_conversation_toolbar_png, _tashuo_mac_ios_app_conversation_toolbar_png, _tashuo_mac_ios_app_conversation_with_title_chrome_png, _tashuo_mac_ios_app_conversation_with_messages_png,
    _tashuo_mac_ios_app_conversation_notification_prompt_png, _tashuo_mac_ios_app_message_list_with_target_row_png, _tashuo_mac_ios_app_profile_png, _tashuo_mac_ios_app_pending_question_list_png,
    _tashuo_mac_ios_app_profile_mid_png, _tashuo_mac_ios_app_profile_bottom_png, _tashuo_mac_ios_app_profile_closing_transition_png, _tashuo_recommend_bottom_nav_png,
    _tashuo_messages_bottom_nav_png, _tashuo_messages_top_anchor_png, _tashuo_liked_you_modal_png, _tashuo_recommend_content_with_messages_tab_png,
    _tashuo_top_level_bottom_nav_png, _spotlight_search_bottom_png, _tinder_conversation_send_button_png, _png_from_pixels,
    _png_chunk, _png_average_hash, _read_test_png_pixels,
)


class GuiHarnessSharedTests(GuiHarnessTestCase):
    def test_capabilities_expose_stage_gui_harness_and_opt_in_managed_wechat_send(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = StringIO()
            with redirect_stdout(output):
                exit_code = main(["capabilities", "--json", "--data-dir", temp_dir])

        payload = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["schema_versions"]["gui_harness"], 2)
        self.assertIn("harness doctor", payload["supported_commands"])
        self.assertIn("harness screenshot", payload["supported_commands"])
        self.assertIn("harness tinder launch", payload["supported_commands"])
        self.assertIn("harness tinder open-profile", payload["supported_commands"])
        self.assertIn("harness tinder observe", payload["supported_commands"])
        self.assertIn("harness tinder action", payload["supported_commands"])
        self.assertIn("harness tinder workflow", payload["supported_commands"])
        self.assertIn("harness tinder send-message", payload["supported_commands"])
        self.assertIn("harness bumble launch", payload["supported_commands"])
        self.assertIn("harness bumble observe", payload["supported_commands"])
        self.assertIn("harness bumble action", payload["supported_commands"])
        self.assertIn("harness bumble workflow", payload["supported_commands"])
        self.assertIn("harness bumble send-message", payload["supported_commands"])
        self.assertIn("harness tashuo launch", payload["supported_commands"])
        self.assertIn("harness tashuo observe", payload["supported_commands"])
        self.assertIn("harness tashuo action", payload["supported_commands"])
        self.assertIn("harness tashuo workflow", payload["supported_commands"])
        self.assertIn("harness tashuo stage-draft", payload["supported_commands"])
        self.assertIn("harness tashuo send-message", payload["supported_commands"])
        self.assertIn("harness wechat launch", payload["supported_commands"])
        self.assertIn("harness wechat observe", payload["supported_commands"])
        self.assertIn("harness wechat stage-draft", payload["supported_commands"])
        self.assertIn("harness wechat send-message", payload["supported_commands"])
        self.assertTrue(payload["agent_native_capabilities"]["iphone_mirroring_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["stage_gui_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["tinder_gui_launch"])
        self.assertTrue(payload["agent_native_capabilities"]["tinder_gui_navigation"])
        self.assertTrue(payload["agent_native_capabilities"]["tinder_profile_read_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["tinder_chat_navigation_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["tinder_live_send_harness"])
        self.assertIn("bumble", payload["agent_native_capabilities"]["supported_app_profiles"])
        self.assertIn("bumble", payload["agent_native_capabilities"]["host_loop_app_profiles"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_gui_launch"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_gui_navigation"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_profile_read_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_chat_navigation_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_opening_move_role_policy"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_opening_move_male_draft"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_opening_move_stage_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_opening_move_send_harness"])
        self.assertFalse(payload["agent_native_capabilities"]["bumble_opening_move_autonomous_send"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_live_send_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_host_loop"])
        self.assertIn("tashuo", payload["agent_native_capabilities"]["supported_app_profiles"])
        self.assertIn("tashuo", payload["agent_native_capabilities"]["host_loop_app_profiles"])
        self.assertTrue(payload["agent_native_capabilities"]["tashuo_gui_launch"])
        self.assertTrue(payload["agent_native_capabilities"]["tashuo_gui_navigation"])
        self.assertTrue(payload["agent_native_capabilities"]["tashuo_profile_read_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["tashuo_chat_navigation_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["tashuo_mac_ios_app_runtime"])
        self.assertTrue(payload["agent_native_capabilities"]["tashuo_mac_ios_app_stage_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["tashuo_mac_ios_app_live_send_harness"])
        self.assertEqual(
            payload["agent_native_capabilities"]["tashuo_mac_ios_app_live_send_status"],
            "supported",
        )
        self.assertEqual(
            payload["agent_native_capabilities"]["tashuo_mac_ios_app_live_send_block_reason"],
            "",
        )
        self.assertTrue(payload["agent_native_capabilities"]["tashuo_question_gate_role_policy"])
        self.assertTrue(payload["agent_native_capabilities"]["tashuo_question_gate_male_draft"])
        self.assertFalse(payload["agent_native_capabilities"]["tashuo_question_gate_stage_harness"])
        self.assertFalse(payload["agent_native_capabilities"]["tashuo_question_gate_send_harness"])
        self.assertFalse(payload["agent_native_capabilities"]["tashuo_question_gate_autonomous_send"])
        self.assertTrue(payload["agent_native_capabilities"]["tashuo_live_send_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["tashuo_host_loop"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_host_loop"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_macos_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_gui_launch"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_chat_observation_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_draft_stage_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["managed_gui_send"])
        self.assertFalse(payload["agent_native_capabilities"]["managed_gui_send_default"])
        self.assertFalse(payload["agent_native_capabilities"]["repo_computer_use_execution_backend"])
        self.assertFalse(payload["agent_native_capabilities"]["repo_computer_use_execution_backend_required"])
        self.assertEqual(
            payload["agent_native_capabilities"]["computer_use_execution_model"],
            "host_agent_capability_when_available_not_repo_backend",
        )
        self.assertTrue(payload["agent_native_capabilities"]["wechat_live_send_harness"])
        self.assertFalse(payload["agent_native_capabilities"]["live_gui_harness"])
        guidance = payload["managed_live_send_guidance"]
        self.assertIn(
            "do_not_use_host_tool_approval_as_send_authorization",
            guidance["forbidden_actions"],
        )
        self.assertIn(
            "do_not_direct_type_non_ascii_or_cjk_payload_text",
            guidance["forbidden_actions"],
        )
        self.assertEqual(
            guidance["host_tool_approval_scope"],
            "tool_execution_only_not_dating_booster_send_authorization",
        )
        self.assertEqual(
            guidance["payload_text_entry_policy"]["blocked_reason_for_cjk"],
            "cjk_direct_type_not_supported",
        )

    def test_direct_text_entry_blocks_cjk_before_osascript_keystroke(self):
        runner = FakeRunner(ocr_text="")
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness._type_text_into_frontmost_app("你好")

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "cjk_direct_type_not_supported")
        self.assertFalse(any("keystroke" in " ".join(command) for command in runner.commands))

    def test_direct_text_entry_allows_printable_ascii_fallback(self):
        runner = FakeRunner(ocr_text="")
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness._type_text_into_frontmost_app("hi")

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(any('keystroke "hi"' in " ".join(command) for command in runner.commands))

    def test_cli_generic_harness_blocks_unknown_app_before_native_execution(self):
        with _patch_cli_adapter() as harness_class:
            exit_code, payload = _run_cli_json([
                "harness",
                "doctor",
                "--app-id",
                "hinge",
                "--no-capture",
                "--json",
            ])

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "unsupported_native_harness_for_app")
        self.assertEqual(payload["app_id"], "hinge")
        self.assertEqual(payload["supported_native_harness_apps"], list(SUPPORTED_NATIVE_HARNESS_APPS))
        harness_class.assert_not_called()

    def test_iphone_stage_draft_blocks_current_thread_visual_mismatch_without_relocation_evidence(self):
        cases = (
            (
                "bumble",
                _bumble_conversation_png(outgoing_bubble=False),
                "GIF\n回复时间\nAa\n",
                "send_bumble_message",
                "bumble_conversation",
            ),
            (
                "tinder",
                _tinder_conversation_send_button_png(),
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "send_tinder_message",
                "tinder_conversation",
            ),
        )
        region = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65}
        for app_id, screenshot, ocr_text, method_name, screen_state in cases:
            with self.subTest(app_id=app_id):
                runner = FakeRunner(
                    ocr_text=[ocr_text, ocr_text],
                    screenshot_bytes=screenshot,
                )
                harness = create_adapter(app_id=app_id, platform="darwin", runner=runner)

                payload = getattr(harness.session, method_name)(
                    "今晚可以聊十分钟吗？",
                    dry_run=False,
                    output_dir=Path(tempfile.mkdtemp()),
                    stage_only=True,
                    target_binding={
                        "binding_type": "current_thread_visual_identity",
                        "target_match_id": f"match_{app_id}_missing_relocation",
                        "candidate_key": f"{app_id}_missing_relocation",
                        "conversation_fingerprint": f"{app_id}-conversation",
                        "thread_evidence": {
                            "observation_id": f"obs_{app_id}_missing_relocation",
                            "screen_state": screen_state,
                            "latest_inbound_fingerprint": "inbound-current",
                            "visual_anchor_hash": "0000000000000000",
                            "visual_anchor_region": region,
                            "visual_anchor_max_hamming_distance": 0,
                        },
                    },
                )

                self.assertEqual(payload["status"], "blocked")
                self.assertEqual(payload["reason"], "target_relocation_visual_evidence_required")
                self.assertEqual(payload["target_binding_relocation"]["status"], "blocked")
                self.assertTrue(payload["target_binding_relocation"]["requires_message_list_visual_evidence"])
                self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_input_backend_v2_reports_explicit_contract_for_drag_failures(self):
        class FailingRunner:
            def run(self, command, *, input=None):
                self.command = command
                return _result(stderr="permission denied", returncode=1)

        runner = FailingRunner()

        payload = core_graphics_drag(
            runner,
            start_x=10,
            start_y=20,
            end_x=30,
            end_y=40,
            duration_seconds=0.35,
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "core_graphics_drag_failed")
        self.assertEqual(payload["input_backend_contract_schema_version"], 2)
        self.assertIn("permission denied", payload["stderr"])
        self.assertEqual(runner.command[:2], ["xcrun", "swift"])

    def test_core_graphics_command_v_reports_explicit_contract_for_failures(self):
        class FailingRunner:
            def run(self, command, *, input=None):
                self.command = command
                return _result(stderr="keyboard denied", returncode=1)

        runner = FailingRunner()

        payload = core_graphics_command_v(runner)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "core_graphics_command_v_failed")
        self.assertEqual(payload["input_backend_contract_schema_version"], 2)
        self.assertIn("keyboard denied", payload["stderr"])
        self.assertEqual(runner.command[:2], ["xcrun", "swift"])

    def test_doctor_blocks_when_iphone_mirroring_is_locked(self):
        harness = create_adapter(
            app_id="tinder",
            platform="darwin",
            runner=FakeRunner(
                ocr_text=(
                    "iPhone Mirroring Is Locked\n"
                    "Touch ID or enter the Mac login for PINK to continue."
                )
            ),
        )

        payload = harness.doctor(capture=True)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "iphone_mirroring_locked")
        self.assertEqual(payload["screen"]["state"], "iphone_mirroring_locked")
        self.assertNotIn("Touch ID", json.dumps(payload, ensure_ascii=False))

    def test_doctor_blocks_when_iphone_mirroring_is_not_frontmost(self):
        harness = create_adapter(
            app_id="tinder",
            platform="darwin",
            runner=FakeRunner(ocr_text="Tinder\nMessages\n", frontmost=False),
        )

        payload = harness.doctor(capture=True)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "iphone_mirroring_not_frontmost")
        self.assertFalse(payload["window"]["frontmost"])
        self.assertFalse(any(command and command[0] == "screencapture" for command in harness.runner.commands))

    def test_window_info_skips_iphone_mirroring_floating_overlay(self):
        runner = FakeRunner(
            ocr_text="Tinder\n个人资料\n编辑个人资料\n",
            window_info_stdout=[
                "true, 1094, 776, 108, 28, \n",
                "true, 1067, 57, 348, 766, iPhone Mirroring\n",
            ],
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.doctor(capture=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["window"]["width"], 348)
        self.assertEqual(payload["window"]["height"], 766)

    def test_tashuo_mac_ios_app_doctor_uses_core_graphics_window_fallback(self):
        class CoreGraphicsWindowRunner(FakeRunner):
            def run(self, command, *, input=None):
                if command and command[0] == "osascript" and any("position of window" in item for item in command):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    return _result(stderr='Can’t get window 1 of process "tashuo". Invalid index.', returncode=1)
                if command and command[0] == "osascript" and any("to get unix id" in item for item in command):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    return _result(stdout="35218\n")
                if command[:3] == ["xcrun", "swift", "-e"] and "CGWindowListCopyWindowInfo" in command[-1]:
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    return _result(stdout="1093\t111\t288\t541\t1713\t她说\n")
                return super().run(command, input=input)

        runner = CoreGraphicsWindowRunner(ocr_text="", window_name="她说")
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.doctor(capture=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["window"]["name"], "她说")
        self.assertEqual(payload["window"]["x"], 1093)
        self.assertEqual(payload["window"]["y"], 111)
        self.assertEqual(payload["window"]["width"], 288)
        self.assertEqual(payload["window"]["height"], 541)
        self.assertEqual(payload["window"]["window_id"], 1713)
        swift_commands = [command for command in runner.commands if command[:3] == ["xcrun", "swift", "-e"]]
        self.assertTrue(swift_commands)
        self.assertIn('"她说"', swift_commands[-1][-1])

    def test_tashuo_mac_ios_app_doctor_blocks_when_loginwindow_frontmost(self):
        class LoginWindowFrontmostRunner(FakeRunner):
            def run(self, command, *, input=None):
                if command[:3] == ["xcrun", "swift", "-e"] and "NSWorkspace.shared.runningApplications" in command[-1]:
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    return _result(
                        stdout=(
                            "front\tloginwindow\tcom.apple.loginwindow\n"
                            "target\t她说\tcom.intelcupid.tashuo\t35218\tfalse\tfalse\tfalse\n"
                        )
                    )
                return super().run(command, input=input)

        runner = LoginWindowFrontmostRunner(ocr_text="", window_name="她说")
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.doctor(capture=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "mac_ios_app_gui_session_not_interactive")
        self.assertEqual(payload["activation"]["reason"], "mac_ios_app_gui_session_not_interactive")
        self.assertFalse(any("set frontmost of process" in " ".join(command) for command in runner.commands))

    def test_tashuo_mac_ios_app_doctor_retries_when_window_info_not_frontmost(self):
        runner = FakeRunner(
            ocr_text="",
            window_name="她说",
            window_info_stdout=[
                "false, 100, 50, 288, 541, 她说\n",
                "true, 100, 50, 288, 541, 她说\n",
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.doctor(capture=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["window"]["name"], "她说")
        self.assertTrue(payload["window"]["frontmost"])
        self.assertIn("frontmost_retry_activation", payload)
        self.assertIn("frontmost_retry_window", payload)
        self.assertTrue(any("set frontmost of process" in " ".join(command) for command in runner.commands))

    def test_tashuo_mac_ios_app_capture_uses_core_graphics_window_id(self):
        class CoreGraphicsWindowRunner(FakeRunner):
            def run(self, command, *, input=None):
                if command and command[0] == "osascript" and any("position of window" in item for item in command):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    return _result(stderr='Can’t get window 1 of process "tashuo". Invalid index.', returncode=1)
                if command and command[0] == "osascript" and any("to get unix id" in item for item in command):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    return _result(stdout="35218\n")
                if command[:3] == ["xcrun", "swift", "-e"] and "CGWindowListCopyWindowInfo" in command[-1]:
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    return _result(stdout="1093\t111\t288\t541\t1713\t她说\n")
                return super().run(command, input=input)

        runner = CoreGraphicsWindowRunner(
            ocr_text="推荐\nsmilewen 31\n1日内活跃\n推荐\n飞行\n消息\n我的\n",
            window_name="她说",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.capture_window(output=Path(temp_dir) / "capture.png")

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(any(command[:4] == ["screencapture", "-x", "-l", "1713"] for command in runner.commands))

    def test_tashuo_mac_ios_prepare_message_page_uses_core_graphics_window_id_capture(self):
        class CoreGraphicsWindowRunner(FakeRunner):
            def run(self, command, *, input=None):
                if command and command[0] == "osascript" and any("position of window" in item for item in command):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    return _result(stderr='Can’t get window 1 of process "tashuo". Invalid index.', returncode=1)
                if command and command[0] == "osascript" and any("to get unix id" in item for item in command):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    return _result(stdout="35218\n")
                if command[:3] == ["xcrun", "swift", "-e"] and "CGWindowListCopyWindowInfo" in command[-1]:
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    return _result(stdout="1093\t111\t288\t541\t1713\t她说\n")
                return super().run(command, input=input)

        runner = CoreGraphicsWindowRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                _tashuo_recommend_bottom_nav_png(),
                _tashuo_messages_bottom_nav_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_action("prepare-message-page", dry_run=False, output_dir=Path(temp_dir))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["preflight"]["window"]["window_id"], 1713)
        self.assertTrue(any(command[:4] == ["screencapture", "-x", "-l", "1713"] for command in runner.commands))
        self.assertFalse(any(command[:3] == ["screencapture", "-x", "-R"] for command in runner.commands))

    def test_open_profile_launch_if_needed_combines_launch_and_profile_navigation(self):
        runner = FakeRunner(ocr_text="周三\n03\n搜索\n电话\n微信\nChrome\n")
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.open_tinder_profile(dry_run=True, launch_if_needed=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            [
                "open_iphone_home_screen",
                "open_ios_spotlight",
                "type_app_name_verified",
                "tap_tinder_search_result_icon",
                "tap_tinder_profile_tab",
            ],
        )

    def test_visual_self_profile_does_not_override_ios_home_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = create_adapter(
                app_id="tinder",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="今天 周四 6月4日\n搜索\n电话\n微信\nChrome\n",
                    screenshot_bytes=_tinder_bottom_nav_png("profile"),
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "ios-home.png")

        self.assertEqual(payload["text_state"], "ios_home_screen")
        self.assertEqual(payload["state"], "ios_home_screen")

    def test_noisy_match_age_and_notification_prompt_do_not_identify_conversation_alone(self):
        self.assertEqual(classify_screen_text("您和Mooi已配对\n5个月前\n"), "unknown")
        self.assertEqual(classify_screen_text("查看Iris何时回复\n启用推送通知\n"), "unknown")

    def test_visual_profile_tab_active_state_supports_self_profile_detection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot = _tinder_bottom_nav_png("profile")
            harness = create_adapter(
                app_id="tinder",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="Tinder\nGold\nSuper Like\nBoost",
                    screenshot_bytes=screenshot,
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "profile-tab.png")

        self.assertEqual(payload["state"], "tinder_self_profile")
        self.assertEqual(payload["visual_state"], "tinder_self_profile")

    def test_self_profile_read_workflow_covers_preview_photos_full_read_expand_and_exit(self):
        harness = create_adapter(app_id="tinder", platform="darwin", runner=FakeRunner(ocr_text="编辑个人资料\n个人资料"))

        payload = harness.run_tinder_workflow("self-profile-read", dry_run=True, photo_steps=2, scroll_steps=2)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["workflow"], "self-profile-read")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            [
                "tap_self_profile_avatar",
                "tap_photo_next",
                "tap_photo_next",
                "tap_photo_previous",
                "tap_profile_up_arrow",
                "capture_profile_read_step",
                "wheel_profile_read_down",
                "capture_profile_read_step",
                "wheel_profile_read_down",
                "capture_profile_read_step",
                "safe_expand_visible_profile_section",
                "capture_profile_read_step",
                "tap_profile_down_arrow",
                "tap_preview_done",
            ],
        )
        self.assertTrue(all(step["risk"] == "navigation_only" for step in payload["planned_steps"]))

    def test_chat_read_match_profile_workflow_reads_existing_conversation_without_new_match_flow(self):
        harness = create_adapter(app_id="tinder", platform="darwin", runner=FakeRunner(ocr_text="Tinder\n聊天\n等你回应"))

        payload = harness.run_tinder_workflow(
            "chat-read-match-profile",
            dry_run=True,
            carousel_swipes=1,
            conversation_row=2,
            profile_scroll_steps=1,
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["workflow"], "chat-read-match-profile")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            [
                "tap_chats_tab",
                "tap_conversation_row",
                "tap_thread_profile_avatar",
                "tap_photo_next",
                "tap_profile_up_arrow",
                "capture_profile_read_step",
                "wheel_profile_read_down",
                "capture_profile_read_step",
                "safe_expand_visible_profile_section",
                "capture_profile_read_step",
                "tap_profile_down_arrow",
            ],
        )
        self.assertNotIn("tap_new_match_card", [step["intent"] for step in payload["planned_steps"]])
        self.assertNotIn("wheel_new_matches_left", [step["intent"] for step in payload["planned_steps"]])
        self.assertNotIn("tap_preview_done", [step["intent"] for step in payload["planned_steps"]])
        conversation_step = next(step for step in payload["planned_steps"] if step["intent"] == "tap_conversation_row")
        self.assertEqual(conversation_step["row_index"], 2)

    def test_new_match_open_workflow_opens_unstarted_match_and_stays_in_conversation(self):
        harness = create_adapter(app_id="tinder", platform="darwin", runner=FakeRunner(ocr_text="Tinder\n聊天\n新的配对"))

        payload = harness.run_tinder_workflow("new-match-open", dry_run=True, carousel_swipes=1, match_index=2)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["workflow"], "new-match-open")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            [
                "tap_chats_tab",
                "wheel_new_matches_left",
                "tap_new_match_card",
            ],
        )
        match_step = payload["planned_steps"][-1]
        self.assertEqual(match_step["match_index"], 2)
        self.assertNotIn("tap_conversation_row", [step["intent"] for step in payload["planned_steps"]])
        self.assertNotIn("tap_thread_back_to_chats", [step["intent"] for step in payload["planned_steps"]])

    def test_new_match_read_profile_workflow_reads_profile_without_existing_conversation_row(self):
        harness = create_adapter(app_id="tinder", platform="darwin", runner=FakeRunner(ocr_text="Tinder\n聊天\n新的配对"))

        payload = harness.run_tinder_workflow(
            "new-match-read-profile",
            dry_run=True,
            carousel_swipes=1,
            match_index=2,
            profile_scroll_steps=1,
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["workflow"], "new-match-read-profile")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            [
                "tap_chats_tab",
                "wheel_new_matches_left",
                "tap_new_match_card",
                "tap_thread_profile_avatar",
                "tap_photo_next",
                "tap_profile_up_arrow",
                "capture_profile_read_step",
                "wheel_profile_read_down",
                "capture_profile_read_step",
                "safe_expand_visible_profile_section",
                "capture_profile_read_step",
                "tap_profile_down_arrow",
            ],
        )
        match_step = next(step for step in payload["planned_steps"] if step["intent"] == "tap_new_match_card")
        self.assertEqual(match_step["match_index"], 2)
        self.assertNotIn("tap_conversation_row", [step["intent"] for step in payload["planned_steps"]])
        self.assertNotIn("tap_preview_done", [step["intent"] for step in payload["planned_steps"]])

    def test_execute_planned_steps_blocks_malformed_step_before_screen_guards(self):
        runner = FakeRunner(ocr_text="Tinder\nMessages\n")
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)
        payload = {
            **harness._base_payload("ok"),
            "action": "malformed-step",
            "mode": "execute",
            "planned_steps": ["not-a-step"],
            "blocked_actions": [],
        }

        result = harness._execute_planned_steps(payload)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "gui_step_not_mapping")
        self.assertEqual(result["step_index"], 1)
        self.assertEqual(result["step"], "not-a-step")

    def test_execute_planned_steps_reports_tinder_paywall_recovery_after_action(self):
        harness = create_adapter(app_id="tinder", platform="darwin", runner=FakeRunner(ocr_text="Tinder\nMessages\n"))
        session = harness.session
        payload = {
            **harness._base_payload("ok"),
            "action": "read-profile",
            "mode": "execute",
            "planned_steps": [],
            "blocked_actions": [],
        }
        doctor = {
            "status": "ok",
            "screen": {"state": "tinder_messages"},
            "window": {
                "frontmost": True,
                "x": 0,
                "y": 0,
                "width": 300,
                "height": 600,
                "name": "iPhone Mirroring",
            },
        }
        paywall_screen = {"status": "ok", "state": "tinder_subscription_paywall", "text": ""}
        recovery = {"status": "ok", "verification": {"state": "tinder_messages"}}

        with (
            patch.object(session, "doctor", return_value=doctor),
            patch.object(session, "capture_window", return_value=paywall_screen),
            patch.object(session, "_dismiss_tinder_subscription_paywall", return_value=recovery),
        ):
            try:
                result = session._execute_planned_steps(payload)
            except NameError as exc:
                self.fail(f"after-action paywall recovery raised NameError: {exc}")

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "tinder_subscription_paywall_dismissed")
        self.assertEqual(result["subscription_paywall_recovery"], recovery)
        self.assertEqual(result["next_host_action"], "navigate_to_verified_tinder_conversation_and_retry_send")

    def test_profile_read_workflow_reports_redacted_field_coverage_from_step_captures(self):
        runner = FakeRunner(
            ocr_text=[
                "编辑个人资料\n个人资料\n",
                "关于我\n关键信息\n兴趣\n我想要\n基本信息\n生活方式\n查看所有 7 项信息\n",
                "编辑个人资料\n个人资料\n",
            ]
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_tinder_workflow(
                "self-profile-read",
                dry_run=False,
                output_dir=Path(temp_dir),
                photo_steps=0,
                scroll_steps=1,
            )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            payload["field_coverage"],
            {
                "about_me": True,
                "key_info": True,
                "interests": True,
                "looking_for": True,
                "basic_info": True,
                "lifestyle": True,
            },
        )
        self.assertIn("profile_read_captures", payload)
        self.assertNotIn("关于我", json.dumps(payload, ensure_ascii=False))

    def test_profile_read_workflow_captures_full_profile_before_first_wheel(self):
        payload = create_adapter(
            app_id="tinder",
            platform="darwin",
            runner=FakeRunner(ocr_text="编辑个人资料\n个人资料"),
        ).run_tinder_workflow("self-profile-read", dry_run=True, photo_steps=0, scroll_steps=1)

        intents = [step["intent"] for step in payload["planned_steps"]]
        self.assertLess(
            intents.index("capture_profile_read_step"),
            intents.index("wheel_profile_read_down"),
        )

    def test_profile_read_workflow_skips_expand_when_danger_actions_are_visible(self):
        runner = FakeRunner(
            ocr_text=[
                "编辑个人资料\n个人资料\n",
                "Iris 27\n基本信息\n生活方式\n取消配对\n屏蔽Iris\n举报Iris\n",
                "Iris 27\n基本信息\n生活方式\n取消配对\n屏蔽Iris\n举报Iris\n",
                "编辑个人资料\n个人资料\n",
            ]
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_tinder_workflow(
                "self-profile-read",
                dry_run=False,
                output_dir=Path(temp_dir),
                photo_steps=0,
                scroll_steps=0,
            )

        expand_step = next(step for step in payload["executed_steps"] if step["intent"] == "safe_expand_visible_profile_section")
        self.assertEqual(expand_step["result"]["status"], "ok")
        self.assertTrue(expand_step["result"]["skipped"])
        self.assertEqual(expand_step["result"]["reason"], "dangerous_profile_action_visible")
        self.assertNotIn("取消配对", json.dumps(payload, ensure_ascii=False))

    def test_runtime_scope_data_dir_required_before_adapter_creation(self):
        with _patch_cli_adapter() as harness_class:
            exit_code, payload = _run_cli_json(["harness", "wechat", "observe", "--json"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "runtime_scope_data_dir_required")
        harness_class.assert_not_called()

    def test_runtime_scope_blocks_unrelated_harness_app_before_adapter_creation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            select_exit, select_payload = _run_cli_json([
                "runtime",
                "select",
                "--data-dir",
                temp_dir,
                "--app-id",
                "tashuo",
                "--runtime",
                "mac-ios-app",
                "--json",
            ])
            with _patch_cli_adapter() as harness_class:
                exit_code, payload = _run_cli_json([
                    "harness",
                    "wechat",
                    "observe",
                    "--data-dir",
                    temp_dir,
                    "--json",
                ])

        self.assertEqual(select_exit, 0)
        self.assertEqual(select_payload["status"], "selected")
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "runtime_scope_mismatch")
        self.assertEqual(payload["selected_app_id"], "tashuo")
        self.assertEqual(payload["selected_runtime"], "mac-ios-app")
        self.assertFalse(harness_class.called)

    def test_runtime_select_requires_clear_before_switching_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first_exit, first_payload = _run_cli_json([
                "runtime",
                "select",
                "--data-dir",
                temp_dir,
                "--app-id",
                "tashuo",
                "--runtime",
                "mac-ios-app",
                "--json",
            ])
            second_exit, second_payload = _run_cli_json([
                "runtime",
                "select",
                "--data-dir",
                temp_dir,
                "--app-id",
                "wechat",
                "--runtime",
                "default",
                "--json",
            ])
            clear_exit, clear_payload = _run_cli_json([
                "runtime",
                "clear",
                "--data-dir",
                temp_dir,
                "--reason",
                "user_requested_target_switch",
                "--json",
            ])
            third_exit, third_payload = _run_cli_json([
                "runtime",
                "select",
                "--data-dir",
                temp_dir,
                "--app-id",
                "wechat",
                "--runtime",
                "default",
                "--json",
            ])

        self.assertEqual(first_exit, 0)
        self.assertEqual(first_payload["status"], "selected")
        self.assertEqual(second_exit, 2)
        self.assertEqual(second_payload["status"], "blocked")
        self.assertEqual(second_payload["reason"], "runtime_scope_already_selected")
        self.assertEqual(second_payload["selected_app_id"], "tashuo")
        self.assertEqual(second_payload["requested_app_id"], "wechat")
        self.assertEqual(clear_exit, 0)
        self.assertEqual(clear_payload["status"], "cleared")
        self.assertEqual(third_exit, 0)
        self.assertEqual(third_payload["status"], "selected")
        self.assertEqual(third_payload["selected_app_id"], "wechat")

    def test_runtime_scope_is_required_for_data_dir_harness_before_adapter_creation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with _patch_cli_adapter() as harness_class:
                exit_code, payload = _run_cli_json([
                    "harness",
                    "wechat",
                    "observe",
                    "--data-dir",
                    temp_dir,
                    "--json",
                ])

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "runtime_scope_required")
        self.assertEqual(payload["requested_app_id"], "wechat")
        self.assertEqual(payload["requested_runtime"], "default")
        self.assertFalse(harness_class.called)

    def test_runtime_scope_blocks_implicit_default_runtime_before_adapter_creation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_cli_json([
                "runtime",
                "select",
                "--data-dir",
                temp_dir,
                "--app-id",
                "tashuo",
                "--runtime",
                "mac-ios-app",
                "--json",
            ])
            with _patch_cli_adapter() as harness_class:
                exit_code, payload = _run_cli_json([
                    "harness",
                    "tashuo",
                    "observe",
                    "--data-dir",
                    temp_dir,
                    "--json",
                ])

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "runtime_scope_mismatch")
        self.assertEqual(payload["requested_runtime"], "default")
        self.assertEqual(payload["selected_runtime"], "mac-ios-app")
        self.assertFalse(harness_class.called)

    def test_runtime_scope_allows_selected_harness_app_and_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            _run_cli_json([
                "runtime",
                "select",
                "--data-dir",
                temp_dir,
                "--app-id",
                "tashuo",
                "--runtime",
                "mac-ios-app",
                "--json",
            ])
            with _patch_cli_adapter() as harness_class:
                harness_class.return_value.observe_tashuo_screen.return_value = {
                    "schema_version": 2,
                    "status": "ok",
                    "app_id": "tashuo",
                    "harness_backend": "mac_ios_app",
                }
                exit_code, payload = _run_cli_json([
                    "harness",
                    "tashuo",
                    "observe",
                    "--data-dir",
                    temp_dir,
                    "--runtime",
                    "mac-ios-app",
                    "--json",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(harness_class.call_args.kwargs["runtime"], "mac-ios-app")

    def test_cli_exposes_iphone_dating_app_stage_draft(self):
        for app_id, method_name in (
            ("tinder", "stage_tinder_draft"),
            ("bumble", "stage_bumble_draft"),
        ):
            with self.subTest(app_id=app_id), tempfile.TemporaryDirectory() as temp_dir:
                data_dir = Path(temp_dir) / "data"
                _select_runtime_scope(data_dir, app_id)
                draft_path = Path(temp_dir) / "draft.txt"
                draft_text = "今晚聊得挺舒服的。"
                draft_path.write_text(draft_text, encoding="utf-8")
                with _patch_cli_adapter() as harness_class:
                    getattr(harness_class.return_value, method_name).return_value = {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": app_id,
                        "harness_backend": "iphone_mirroring_macos",
                        "action": "stage_draft",
                        "stage_attempt_status": "completed",
                        "staged_text_verified": True,
                    }

                    exit_code, payload = _run_cli_json([
                        "harness",
                        app_id,
                        "stage-draft",
                        "--data-dir",
                        str(data_dir),
                        "--text-file",
                        str(draft_path),
                        "--dry-run",
                        "--json",
                    ])

                self.assertEqual(exit_code, 0)
                self.assertEqual(payload["action"], "stage_draft")
                self.assertEqual(payload["app_id"], app_id)
                self.assertIsNone(harness_class.call_args.kwargs["runtime"])
                getattr(harness_class.return_value, method_name).assert_called_once_with(
                    draft_text,
                    dry_run=True,
                    output_dir=None,
                )

    def test_cli_real_send_accepts_valid_autonomous_audit_binding_for_supported_apps(self):
        for app_id, match_id, candidate_key, marker, command, method_name in (
            ("tinder", "match_ada", "tinder_ada", "Ada", ["harness", "tinder", "send-message"], "send_tinder_message"),
            ("wechat", "match_wechat", "wechat_ada", "Ada", ["harness", "wechat", "send-message"], "send_wechat_message"),
            ("bumble", "match_bumble", "bumble_ada", "Ada", ["harness", "bumble", "send-message"], "send_bumble_message"),
        ):
            with self.subTest(app_id=app_id):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    data_dir = root / "data"
                    draft_text = "今晚可以聊十分钟吗？"
                    payload_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
                    auth_id = f"auth_{app_id}_live"
                    draft_path = root / f"{app_id}-draft.txt"
                    auth_path = root / "auth.json"
                    action_path = root / "action_request.json"
                    draft_path.write_text(draft_text, encoding="utf-8")
                    _select_runtime_scope(data_dir, app_id)
                    _write_json(auth_path, _live_send_auth(app_id, authorization_id=auth_id, allowed_match_ids=[match_id]))
                    _write_json(action_path, {
                        "schema_version": 1,
                        "action_request_id": f"act_{app_id}_send",
                        "action": "send_message",
                        "app_id": app_id,
                        "match_id": match_id,
                        "candidate_key": candidate_key,
                        "payload_hash": payload_hash,
                        "precondition_hash": "pre_hash",
                        "autonomous_audit_binding": _autonomous_audit_binding(
                            authorization_id=auth_id,
                            target_match_id=match_id,
                            payload_hash=payload_hash,
                        ),
                        "requires_post_action_verification": True,
                        "draft_review_id": "draft_review_fixture",
                        **_draft_generation_binding(),
                        "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                        **_planner_evidence(),
                        "target_binding": {
                            "required_visible_text": [marker],
                            "target_match_id": match_id,
                            "candidate_key": candidate_key,
                        },
                    })
                    _write_draft_review_audit(data_dir, target_match_id=match_id, payload_hash=payload_hash)

                    with _patch_cli_adapter() as harness_class:
                        getattr(harness_class.return_value, method_name).return_value = {
                            "schema_version": 1,
                            "status": "ok",
                            "app_id": app_id,
                            "action": "send_message",
                        }
                        exit_code, payload = _run_cli_json([
                            *command,
                            "--text-file",
                            str(draft_path),
                            "--data-dir",
                            str(data_dir),
                            "--authorization",
                            str(auth_path),
                            "--action-request",
                            str(action_path),
                            "--json",
                        ])

                self.assertEqual(exit_code, 0)
                self.assertEqual(payload["status"], "ok")
                getattr(harness_class.return_value, method_name).assert_called_once()

    def test_cli_real_send_accepts_chat_list_row_structural_binding_for_iphone_dating_apps(self):
        cases = (
            ("tinder", "tinder_messages", "tinder_conversation", "send_tinder_message"),
            ("bumble", "bumble_chat_list", "bumble_conversation", "send_bumble_message"),
            ("tashuo", "tashuo_chat_list", "tashuo_conversation", "send_tashuo_message"),
        )
        for app_id, source_state, opened_state, method_name in cases:
            with self.subTest(app_id=app_id):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    data_dir = root / "data"
                    draft_text = "你好"
                    payload_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
                    match_id = f"match_{app_id}_row_5"
                    candidate_key = f"{app_id}_chat_row_5_emoji"
                    auth_id = f"auth_{app_id}_live"
                    draft_path = root / f"{app_id}-draft.txt"
                    auth_path = root / "auth.json"
                    action_path = root / "action_request.json"
                    draft_path.write_text(draft_text, encoding="utf-8")
                    _select_runtime_scope(data_dir, app_id)
                    _write_json(auth_path, _live_send_auth(app_id, authorization_id=auth_id, allowed_match_ids=[match_id]))
                    _write_json(action_path, {
                        "schema_version": 1,
                        "action_request_id": f"act_{app_id}_send",
                        "action": "send_message",
                        "app_id": app_id,
                        "match_id": match_id,
                        "candidate_key": candidate_key,
                        "payload_hash": payload_hash,
                        "precondition_hash": "pre_hash",
                        "autonomous_audit_binding": _autonomous_audit_binding(
                            authorization_id=auth_id,
                            target_match_id=match_id,
                            payload_hash=payload_hash,
                        ),
                        "requires_post_action_verification": True,
                        "draft_review_id": "draft_review_fixture",
                        **_draft_generation_binding(),
                        "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                        **_planner_evidence(),
                        "target_binding": {
                            "binding_type": "chat_list_row_to_thread",
                            "target_match_id": match_id,
                            "candidate_key": candidate_key,
                            "selection_evidence": {
                                "source_state": source_state,
                                "opened_state": opened_state,
                                "row_index": 5,
                                "target_scope": "ordinary_conversation",
                                "open_action": "open-conversation",
                            },
                        },
                    })
                    _write_draft_review_audit(data_dir, target_match_id=match_id, payload_hash=payload_hash)

                    with _patch_cli_adapter() as harness_class:
                        getattr(harness_class.return_value, method_name).return_value = {
                            "schema_version": 1,
                            "status": "ok",
                            "app_id": app_id,
                            "action": "send_message",
                        }
                        exit_code, payload = _run_cli_json([
                            "harness",
                            app_id,
                            "send-message",
                            "--text-file",
                            str(draft_path),
                            "--data-dir",
                            str(data_dir),
                            "--authorization",
                            str(auth_path),
                            "--action-request",
                            str(action_path),
                            "--json",
                        ])

                self.assertEqual(exit_code, 0)
                self.assertEqual(payload["status"], "ok")
                getattr(harness_class.return_value, method_name).assert_called_once()

    def test_wheel_action_blocks_cleanly_when_xcrun_missing(self):
        runner = FakeRunner(ocr_text="滑动\n探索\n赞\n聊天\n个人资料\n", missing_commands={"xcrun"})
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.run_tinder_action("profile-scroll-down", dry_run=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "missing_core_graphics_wheel_backend")
        self.assertEqual(payload["executed_steps"][0]["result"]["reason"], "missing_core_graphics_wheel_backend")
        self.assertFalse(any(command and command[0] == "xcrun" for command in runner.commands))

    def test_cli_exposes_new_match_workflows_with_match_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _select_runtime_scope(data_dir, "tinder")
            open_options_path = Path(temp_dir) / "open-options.json"
            read_options_path = Path(temp_dir) / "read-options.json"
            _write_json(open_options_path, {"carousel_swipes": 1, "match_index": 2})
            _write_json(read_options_path, {"carousel_swipes": 1, "match_index": 2, "profile_scroll_steps": 1})
            with patch.dict("os.environ", {"DATING_BOOST_ALLOW_REAL_GUI_TESTS": "1"}, clear=False):
                open_exit, open_payload = _run_cli_json([
                    "harness",
                    "tinder",
                    "workflow",
                    "new-match-open",
                    "--data-dir",
                    str(data_dir),
                    "--dry-run",
                    "--options-json",
                    str(open_options_path),
                    "--json",
                ])
                read_exit, read_payload = _run_cli_json([
                    "harness",
                    "tinder",
                    "workflow",
                    "new-match-read-profile",
                    "--data-dir",
                    str(data_dir),
                    "--dry-run",
                    "--options-json",
                    str(read_options_path),
                    "--json",
                ])

        self.assertEqual(open_exit, 0)
        self.assertEqual(open_payload["workflow"], "new-match-open")
        self.assertEqual(open_payload["planned_steps"][-1]["intent"], "tap_new_match_card")
        self.assertEqual(open_payload["planned_steps"][-1]["match_index"], 2)
        self.assertEqual(read_exit, 0)
        self.assertEqual(read_payload["workflow"], "new-match-read-profile")
        match_step = next(step for step in read_payload["planned_steps"] if step["intent"] == "tap_new_match_card")
        self.assertEqual(match_step["match_index"], 2)
        self.assertNotIn("tap_conversation_row", [step["intent"] for step in read_payload["planned_steps"]])
