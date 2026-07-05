from tests.gui_harness_support import *


class GuiHarnessTashuoRuntimeTests(GuiHarnessTestCase):
    def test_tashuo_launch_dry_run_uses_tashu_search_term(self):
        runner = FakeRunner(ocr_text="今天 周五\n搜索\n电话\n微信\nChrome\n")
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner)

        payload = harness.launch(dry_run=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target"], "tashuo_app")
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            [
                "open_iphone_home_screen",
                "open_ios_spotlight",
                "type_app_name_verified",
                "tap_tashuo_search_result_icon",
            ],
        )
        self.assertEqual(payload["planned_steps"][2]["text"], "tashu")
        self.assertEqual(payload["planned_steps"][2]["expected_app_labels"], ["tashu", "她说", "TaShuo"])
        self.assertEqual(runner.commands, [])

    def test_tashuo_mac_ios_app_launch_dry_run_uses_local_bundle(self):
        runner = FakeRunner(ocr_text="推荐\n飞行\n消息\n我的\n", window_name="她说")
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.launch(dry_run=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(payload["target"], "tashuo_mac_ios_app")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            ["open_tashuo_mac_ios_app_bundle", "activate_tashuo_mac_ios_process"],
        )
        self.assertEqual(payload["bundle_id"], "com.intelcupid.tashuo")
        self.assertEqual(runner.commands, [])

    def test_tashuo_mac_ios_app_doctor_uses_runtime_specific_missing_window_reason(self):
        runner = FakeRunner(
            ocr_text="",
            window_info_stdout="missing value\n",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.doctor(capture=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(payload["reason"], "mac_ios_app_window_not_found")

    def test_tashuo_mac_ios_app_doctor_reports_host_appleevents_unavailable(self):
        class AppleEventsUnavailableRunner(FakeRunner):
            def run(self, command: list[str], *, input: str | None = None):
                if command and command[0] == "osascript" and any("System Events" in item for item in command):
                    return _result(
                        stderr=(
                            "Connection Invalid error for service com.apple.hiservices-xpcservice\n"
                            "execution error: 发生 \"-10827\" 类型错误. (-10827)\n"
                        ),
                        returncode=1,
                    )
                return super().run(command, input=input)

        runner = AppleEventsUnavailableRunner(ocr_text="")
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.doctor(capture=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(payload["reason"], "host_appleevents_unavailable")
        self.assertEqual(payload["diagnostic"]["category"], "host_appleevents_unavailable")
        self.assertIn("window_probe", payload)
        self.assertNotEqual(payload["reason"], "mac_ios_app_window_not_found")

    def test_tashuo_mac_ios_target_binding_window_failures_report_host_appleevents_unavailable(self):
        class AppleEventsUnavailableRunner(FakeRunner):
            def run(self, command: list[str], *, input: str | None = None):
                if command and command[0] == "osascript" and any("System Events" in item for item in command):
                    return _result(
                        stderr=(
                            "Connection Invalid error for service com.apple.hiservices-xpcservice\n"
                            "execution error: 发生 \"-10827\" 类型错误. (-10827)\n"
                        ),
                        returncode=1,
                    )
                return super().run(command, input=input)

        runner = AppleEventsUnavailableRunner(ocr_text="")
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")
        current_thread_binding = {
            "binding_type": "current_thread_visual_identity",
            "target_match_id": "match_tashuo",
            "candidate_key": "current_thread",
            "conversation_fingerprint": "conv-fingerprint",
            "thread_evidence": {
                "observation_id": "obs_1",
                "screen_state": "tashuo_conversation",
                "latest_inbound_fingerprint": "inbound-1",
                "visual_anchor_hash": "abcd",
            },
        }
        row_binding = {
            "binding_type": "chat_list_row_to_thread",
            "target_match_id": "match_tashuo",
            "candidate_key": "row_thread",
            "selection_evidence": {
                "row_index": 1,
                "source_state": "tashuo_chat_list",
                "opened_state": "tashuo_conversation",
                "target_scope": "ordinary_conversation",
                "open_action": "open-conversation",
            },
        }
        relocation_binding = {
            **current_thread_binding,
            "message_list_evidence": {
                "source_state": "tashuo_chat_list",
                "selection_method": "message_list_visual_anchor_scan",
                "visual_anchor_hash": "1234",
                "visual_anchor_region": {"x1": 0.1, "y1": 0.2, "x2": 0.9, "y2": 0.3},
                "visual_anchor_scan_region": {"x1": 0.0, "y1": 0.18, "x2": 1.0, "y2": 0.84},
                "tap_ratio": {"x": 0.45, "y": 0.34},
            },
        }

        current_result = tashuo_native._verify_tashuo_current_thread_visual_identity(
            harness,
            current_thread_binding,
        )
        row_result = tashuo_native._verify_tashuo_chat_list_row_target_binding(harness, row_binding)
        relocation_result = tashuo_native._recover_tashuo_current_thread_visual_identity_mismatch(
            harness,
            relocation_binding,
        )

        for result in (current_result, row_result, relocation_result):
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["reason"], "host_appleevents_unavailable")
            self.assertEqual(result["diagnostic"]["category"], "host_appleevents_unavailable")
            self.assertIn("window_probe", result)

    def test_tashuo_mac_ios_app_capture_defaults_to_visual_without_ocr(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=_tashuo_messages_bottom_nav_png(),
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac-ios-app")

        with tempfile.TemporaryDirectory() as temp_dir:
            screen = tashuo_native._capture_tashuo_window(
                harness,
                output=Path(temp_dir) / "capture.png",
            )

        self.assertEqual(screen["status"], "ok")
        self.assertEqual(screen["ocr_status"], "skipped")
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_app_launch_executes_open_bundle_and_verifies_foreground(self):
        runner = FakeRunner(
            ocr_text="推荐\nsmilewen 31\n1日内活跃\n推荐\n飞行\n消息\n我的\n",
            window_name="她说",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.launch(dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(
            [step["intent"] for step in payload["executed_steps"]],
            ["open_tashuo_mac_ios_app_bundle", "activate_tashuo_mac_ios_process"],
        )
        self.assertTrue(any(command[:3] == ["open", "-b", "com.intelcupid.tashuo"] for command in runner.commands))
        self.assertEqual(payload["verification"]["status"], "ok")
        self.assertEqual(payload["verification"]["screen"]["state"], "tashuo_recommend")

    def test_tashuo_mac_ios_app_activation_retries_runtime_process_name(self):
        class RetryActivationRunner(FakeRunner):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.frontmost_attempts = 0

            def run(self, command, *, input=None):
                if command and command[0] == "osascript" and any(
                    'set frontmost of process "tashuo"' in item for item in command
                ):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    self.frontmost_attempts += 1
                    if self.frontmost_attempts == 1:
                        return _result(stderr="process not ready", returncode=1)
                    return _result(stdout="")
                return super().run(command, input=input)

        runner = RetryActivationRunner(
            ocr_text="推荐\nsmilewen 31\n1日内活跃\n推荐\n飞行\n消息\n我的\n",
            window_name="她说",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.launch(dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertGreaterEqual(runner.frontmost_attempts, 2)
        self.assertEqual(payload["executed_steps"][1]["result"]["status"], "ok")

    def test_tashuo_mac_ios_app_doctor_reports_process_probe_when_window_missing(self):
        class NoWindowRunner(FakeRunner):
            def run(self, command, *, input=None):
                if command and command[0] == "osascript" and any(
                    "visible, count of windows" in item for item in command
                ):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    return _result(stdout="false, true, 0\n")
                return super().run(command, input=input)

        runner = NoWindowRunner(
            ocr_text="",
            window_info_stdout="missing value\n",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.doctor(capture=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "mac_ios_app_process_has_no_windows")
        process_probe = payload["window_probe"]["processes"][0]
        self.assertEqual(process_probe["process_name"], "tashuo")
        self.assertTrue(process_probe["process_exists"])
        self.assertTrue(process_probe["visible"])
        self.assertEqual(process_probe["window_count"], 0)

    def test_tashuo_mac_ios_app_click_blocks_when_loginwindow_frontmost(self):
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
        window = WindowInfo(frontmost=True, x=1093, y=111, width=288, height=541, name="她说", window_id=1713)

        payload = harness._click_ratio(window, {"x": 0.63, "y": 0.86})

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "mac_ios_app_gui_session_not_interactive")
        self.assertEqual(payload["input_backend"], "blocked_core_graphics")
        self.assertEqual(payload["point"], {"x": 1274, "y": 576})
        self.assertFalse(any("dating_boost_core_graphics_click" in " ".join(command) for command in runner.commands))

    def test_tashuo_mac_ios_app_launch_recovers_process_with_no_windows(self):
        class RecoverNoWindowRunner(FakeRunner):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.recovered = False

            def run(self, command, *, input=None):
                if command and command[0] == "osascript" and any(
                    "tell application id" in item and "to quit" in item for item in command
                ):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    self.recovered = True
                    return _result(stdout="")
                if command and command[0] == "osascript" and any(
                    "visible, count of windows" in item for item in command
                ):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    return _result(stdout="true, true, 0\n")
                if command and command[0] == "osascript" and any("get {frontmost" in item for item in command):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    if self.recovered:
                        return _result(stdout="true, 100, 50, 350, 760, 她说\n")
                    return _result(stdout="missing value\n")
                return super().run(command, input=input)

        runner = RecoverNoWindowRunner(
            ocr_text="推荐\nsmilewen 31\n1日内活跃\n推荐\n飞行\n消息\n我的\n",
            window_name="她说",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.launch(dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["verification"]["status"], "ok")
        self.assertEqual(payload["verification"]["screen"]["state"], "tashuo_recommend")
        self.assertEqual(
            [step["intent"] for step in payload["recovery_steps"]],
            [
                "quit_tashuo_mac_ios_app_without_windows",
                "reopen_tashuo_mac_ios_app_after_no_window",
                "reactivate_tashuo_mac_ios_app_after_no_window",
            ],
        )
        self.assertTrue(any(command[:3] == ["open", "-b", "com.intelcupid.tashuo"] for command in runner.commands))

    def test_tashuo_mac_ios_app_launch_force_recovers_stuck_process_with_no_windows(self):
        class ForceRecoverNoWindowRunner(FakeRunner):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.polite_recovered = False
                self.force_recovered = False

            def run(self, command, *, input=None):
                if command and command[0] == "osascript" and any(
                    "tell application id" in item and "to quit" in item for item in command
                ):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    self.polite_recovered = True
                    return _result(stdout="")
                if command[:2] == ["pkill", "-x"]:
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    self.force_recovered = True
                    return _result(stdout="")
                if command and command[0] == "osascript" and any(
                    "visible, count of windows" in item for item in command
                ):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    return _result(stdout="true, true, 0\n")
                if command and command[0] == "osascript" and any("get {frontmost" in item for item in command):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    if self.force_recovered:
                        return _result(stdout="true, 100, 50, 350, 760, 她说\n")
                    return _result(stdout="missing value\n")
                return super().run(command, input=input)

        runner = ForceRecoverNoWindowRunner(
            ocr_text="推荐\nsmilewen 31\n1日内活跃\n推荐\n飞行\n消息\n我的\n",
            window_name="她说",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.launch(dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["verification"]["screen"]["state"], "tashuo_recommend")
        self.assertEqual(payload["force_recovery_steps"][0]["intent"], "force_quit_tashuo_mac_ios_process_without_windows")
        self.assertTrue(any(command[:3] == ["pkill", "-x", "tashuo"] for command in runner.commands))

    def test_tashuo_mac_ios_app_observe_uses_local_runtime_capture_name(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=_tashuo_messages_bottom_nav_png(),
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.observe(output_dir=Path(temp_dir))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(payload["screen_state"], "tashuo_chat_list")
        self.assertTrue(payload["screen"]["path"].endswith("mac_ios_app.tashuo.observe.png"))
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_app_observe_marks_managed_live_send_supported_in_layout_hints(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=_tashuo_mac_ios_app_conversation_with_messages_png(),
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.observe()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(payload["screen_state"], "tashuo_conversation")
        self.assertTrue(payload["layout_hints"]["managed_live_send_supported"])
        self.assertTrue(payload["layout_hints"]["live_send_supported"])
        self.assertEqual(payload["layout_hints"]["live_send_status"], "supported")
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_launch_accepts_chinese_app_result_for_tashu_query(self):
        runner = FakeRunner(
            ocr_text=[
                "今天 周五\n搜索\n电话\n微信\nChrome\n",
                "她说\nApp\nSiri建议\n",
                "推荐\nsmilewen 31\n1日内活跃\n推荐\n飞行\n消息\n我的\n",
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner)

        payload = harness.launch(dry_run=False)

        self.assertEqual(payload["status"], "ok")
        type_step = next(step for step in payload["executed_steps"] if step["intent"] == "type_app_name_verified")
        self.assertFalse(type_step["result"]["retried_after_input_source_switch"])
        self.assertTrue(type_step["result"]["search_result_verified"])
        self.assertFalse(type_step["result"]["ime_commit_after_typing"])
        self.assertTrue(any('keystroke "tashu"' in " ".join(command) for command in runner.commands))
        self.assertFalse(any("key code 49" in " ".join(command) for command in runner.commands))

    def test_tashuo_thread_cues_capture_question_gate_skip_and_permanent_chat(self):
        skipped_text = "仿生人会爱上锅包肉吗\n她跳过了问答考验，快和她聊聊吧\nhey\n点击此处输入文字"
        permanent_text = (
            "小药丸儿\n你喜欢我资料里哪一点?\n白羊座，enfp，认为朋友很重要\n"
            "她开启了永久聊天\n继续聊聊问答中她感兴趣的话题\nHi，我们可以聊天啦!\n点击此处输入文字"
        )

        self.assertEqual(tashuo_thread_cues_from_text(skipped_text), ["tashuo_question_gate_skipped"])
        self.assertEqual(tashuo_thread_cues_from_text(permanent_text), ["tashuo_permanent_chat_enabled"])
        self.assertEqual(
            tashuo_layout_hints({"state": "tashuo_conversation", "text": skipped_text})["thread_cues"],
            ["tashuo_question_gate_skipped"],
        )

    def test_visual_tashuo_recommend_tolerates_window_id_black_margins(self):
        source_width, source_height, source_rows = _read_test_png_pixels(_tashuo_recommend_bottom_nav_png())
        canvas_width, canvas_height = 720, 1280
        offset_x, offset_y = 72, 70
        scale = 2
        pixels = [[(0, 0, 0, 255) for _ in range(canvas_width)] for _ in range(canvas_height)]
        for y, row in enumerate(source_rows):
            for x, pixel in enumerate(row):
                for dy in range(scale):
                    for dx in range(scale):
                        target_x = offset_x + x * scale + dx
                        target_y = offset_y + y * scale + dy
                        if 0 <= target_x < canvas_width and 0 <= target_y < canvas_height:
                            pixels[target_y][target_x] = pixel
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot_path = Path(temp_dir) / "tashuo-recommend-windowed.png"
            screenshot_path.write_bytes(_png_from_pixels(pixels, canvas_width, canvas_height))

            payload = classify_tashuo_screen_image(screenshot_path)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["state"], "tashuo_recommend")
        self.assertEqual(payload["active_tab"], "recommend")
        self.assertTrue(payload["bottom_nav_present"])
