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


class GuiHarnessTashuoMessagePageTests(GuiHarnessTestCase):
    def test_tashuo_mac_ios_prepare_message_page_uses_ax_radio_button_before_tap_fallback_without_ocr(self):
        runner = FakeRunner(
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
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(payload["initial_visual_state"], "tashuo_recommend")
        self.assertEqual(payload["initial_active_tab"], "recommend")
        self.assertEqual(payload["screen_state"], "tashuo_chat_list")
        self.assertEqual(payload["next_host_action"], "visual_plan_message_list")
        self.assertFalse(payload["ocr_used"])
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))
        self.assertIn("click_tashuo_messages_tab_accessibility", [step["intent"] for step in payload["executed_steps"]])
        self.assertNotIn("tap_tashuo_messages_tab_fallback", [step["intent"] for step in payload["executed_steps"]])
        self.assertTrue(any("radio button 3" in " ".join(command) for command in runner.commands))
        self.assertNotIn("tap_tashuo_conversation_row", [step["intent"] for step in payload["executed_steps"]])

    def test_tashuo_mac_ios_prepare_message_page_retries_frontmost_when_open_probe_not_active(self):
        class DelayedActiveRunner(FakeRunner):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.active_probe_calls = 0

            def run(self, command, *, input=None):
                if (
                    command[:3] == ["xcrun", "swift", "-e"]
                    and "NSWorkspace.shared.frontmostApplication" in command[-1]
                ):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    self.active_probe_calls += 1
                    if self.active_probe_calls <= 2:
                        return _result(
                            stdout=(
                                "front\tFinder\tcom.apple.finder\n"
                                "target\t她说\tcom.intelcupid.tashuo\t123\tfalse\tfalse\tfalse\n"
                            )
                        )
                    return _result(
                        stdout=(
                            "front\t她说\tcom.intelcupid.tashuo\n"
                            "target\t她说\tcom.intelcupid.tashuo\t123\ttrue\tfalse\tfalse\n"
                        )
                    )
                return super().run(command, input=input)

        runner = DelayedActiveRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[_tashuo_messages_bottom_nav_png()],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_action("prepare-message-page", dry_run=False, output_dir=Path(temp_dir))

        self.assertEqual(payload["status"], "ok")
        self.assertGreaterEqual(runner.active_probe_calls, 3)
        activate_step = next(step for step in payload["executed_steps"] if step["intent"] == "activate_tashuo_mac_ios_process")
        attempts = activate_step["result"]["attempts"]
        self.assertIn("defer_blocked_active_probe_to_frontmost_retry", [attempt["method"] for attempt in attempts])
        self.assertIn("retry_after_frontmost_active_probe_blocked", [attempt["method"] for attempt in attempts])
        self.assertIn("set_process_frontmost", [attempt["method"] for attempt in attempts])
        self.assertEqual(payload["screen_state"], "tashuo_chat_list")

    def test_tashuo_mac_ios_prepare_message_page_fallback_taps_real_messages_tab_when_ax_missing(self):
        class AxMissingRunner(FakeRunner):
            def run(self, command, *, input=None):
                if command and command[0] == "osascript" and any("radio button" in item for item in command):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    return _result(stderr='System Events got an error: Can’t get radio button 3.', returncode=1)
                return super().run(command, input=input)

        runner = AxMissingRunner(
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
        fallback = next(step for step in payload["executed_steps"] if step["intent"] == "tap_tashuo_messages_tab_fallback")
        self.assertAlmostEqual(fallback["tap_ratio"]["x"], 0.67)
        self.assertAlmostEqual(fallback["tap_ratio"]["y"], 0.96)
        self.assertEqual(payload["screen_state"], "tashuo_chat_list")

    def test_tashuo_mac_ios_prepare_message_page_waits_for_message_list_after_tab_highlight(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                _tashuo_recommend_bottom_nav_png(),
                _tashuo_recommend_content_with_messages_tab_png(),
                _tashuo_messages_bottom_nav_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_action("prepare-message-page", dry_run=False, output_dir=Path(temp_dir))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["screen_state"], "tashuo_chat_list")
        self.assertEqual(payload["message_page_settle"]["status"], "ok")
        self.assertEqual(payload["message_page_settle"]["attempt_count"], 2)
        self.assertFalse(payload["message_page_settle"]["attempts"][0]["ready"])
        self.assertTrue(payload["message_page_settle"]["attempts"][1]["ready"])
        self.assertEqual(
            payload["message_page_settle"]["attempts"][0]["screen"]["visual_active_tab"],
            "messages",
        )
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_prepare_message_page_returns_from_conversation_with_ax_navback(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_messages_bottom_nav_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_action("prepare-message-page", dry_run=False, output_dir=Path(temp_dir))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["initial_visual_state"], "tashuo_conversation")
        self.assertEqual(payload["post_navback_visual_state"], "tashuo_chat_list")
        self.assertEqual(payload["post_navback_active_tab"], "messages")
        self.assertEqual(payload["screen_state"], "tashuo_chat_list")
        self.assertEqual(payload["next_host_action"], "visual_plan_message_list")
        self.assertFalse(payload["ocr_used"])
        self.assertEqual(runner.ax_navback_clicks, 1)
        self.assertIn("click_tashuo_conversation_navback_accessibility", [step["intent"] for step in payload["executed_steps"]])
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_prepare_message_page_falls_back_when_ax_navback_missing(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_messages_bottom_nav_png(),
            ],
            ax_navback_stdout="not_found",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_action("prepare-message-page", dry_run=False, output_dir=Path(temp_dir))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["initial_visual_state"], "tashuo_conversation")
        self.assertEqual(payload["post_navback_visual_state"], "tashuo_chat_list")
        self.assertEqual(payload["post_navback_active_tab"], "messages")
        self.assertEqual(runner.ax_navback_clicks, 1)
        intents = [step["intent"] for step in payload["executed_steps"]]
        self.assertIn("click_tashuo_conversation_navback_accessibility", intents)
        self.assertIn("tap_tashuo_conversation_navback_visual_fallback", intents)
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_prepare_message_page_returns_from_secondary_profile_page(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                _tashuo_mac_ios_app_profile_png(),
                _tashuo_messages_bottom_nav_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_action("prepare-message-page", dry_run=False, output_dir=Path(temp_dir))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["initial_visual_state"], "tashuo_profile")
        self.assertEqual(payload["post_secondary_navback_visual_state"], "tashuo_chat_list")
        self.assertEqual(payload["screen_state"], "tashuo_chat_list")
        intents = [step["intent"] for step in payload["executed_steps"]]
        self.assertIn("tap_tashuo_secondary_page_navback_visual", intents)
        self.assertIn("handoff_to_visual_message_list_planning", intents)
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_prepare_message_page_returns_from_pending_question_list(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                _tashuo_mac_ios_app_pending_question_list_png(),
                _tashuo_messages_bottom_nav_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_action("prepare-message-page", dry_run=False, output_dir=Path(temp_dir))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["initial_visual_state"], "tashuo_pending_question_list")
        self.assertEqual(payload["post_secondary_navback_visual_state"], "tashuo_chat_list")
        self.assertEqual(payload["screen_state"], "tashuo_chat_list")
        intents = [step["intent"] for step in payload["executed_steps"]]
        self.assertIn("tap_tashuo_secondary_page_navback_visual", intents)
        self.assertIn("handoff_to_visual_message_list_planning", intents)
        self.assertNotIn("question_gate_send", intents)
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_prepare_message_page_dismisses_liked_you_modal(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                _tashuo_liked_you_modal_png(),
                _tashuo_messages_bottom_nav_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_action("prepare-message-page", dry_run=False, output_dir=Path(temp_dir))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["initial_visual_state"], "tashuo_liked_you_modal")
        self.assertEqual(payload["initial_screen"]["state"], "tashuo_liked_you_modal")
        self.assertTrue(payload["liked_you_modal_dismissed"])
        self.assertEqual(payload["post_liked_you_modal_visual_state"], "tashuo_chat_list")
        self.assertEqual(payload["after_liked_you_modal_screen"]["state"], "tashuo_chat_list")
        self.assertEqual(payload["screen_state"], "tashuo_chat_list")
        self.assertEqual(payload["next_host_action"], "visual_plan_message_list")
        intents = [step["intent"] for step in payload["executed_steps"]]
        self.assertIn("dismiss_tashuo_liked_you_modal_later", intents)
        self.assertNotIn("click_tashuo_conversation_navback_accessibility", intents)
        self.assertNotIn("tap_tashuo_conversation_navback_visual_fallback", intents)
        dismiss_step = next(step for step in payload["executed_steps"] if step["intent"] == "dismiss_tashuo_liked_you_modal_later")
        self.assertEqual(dismiss_step["result"]["status"], "ok")
        self.assertTrue(dismiss_step["result"]["does_not_purchase"])
        self.assertEqual(dismiss_step["result"]["method"], "visual_cancel_tap")
        self.assertAlmostEqual(dismiss_step["result"]["tap_ratio"]["x"], 0.50)
        self.assertAlmostEqual(dismiss_step["result"]["tap_ratio"]["y"], 0.79)
        self.assertIn("refresh_tashuo_mac_ios_window_after_liked_you_modal", intents)
        self.assertTrue(any("DATING_BOOST_TASHUO_DISMISS_LIKED_YOU_MODAL" in " ".join(command) for command in runner.commands))
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_conversation_list_scroll_action_skips_all_ocr_captures(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                _tashuo_messages_bottom_nav_png(),
                _tashuo_messages_bottom_nav_png(),
                _tashuo_messages_bottom_nav_png(),
                _tashuo_messages_bottom_nav_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_action(
                "conversation-list-scroll-down",
                dry_run=False,
                output_dir=Path(temp_dir),
            )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(payload["preflight"]["screen"]["ocr_status"], "skipped")
        self.assertEqual(payload["executed_steps"][0]["postcondition"]["screen"]["ocr_status"], "skipped")
        self.assertEqual(payload["verification"]["ocr_status"], "skipped")
        self.assertIn("mac_ios_app.before_action.png", payload["preflight"]["screen"]["path"])
        self.assertIn("mac_ios_app.after_action.png", payload["verification"]["path"])
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_app_open_conversation_accepts_visual_tap_ratio_without_row_index(self):
        runner = FakeRunner(ocr_text="消息\n全部消息\n朵朵\n你好啊\n推荐\n飞行\n消息\n我的\n")
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac-ios-app")

        action = harness.run_action(
            "open-conversation",
            dry_run=True,
            tap_ratio={"x": 0.50, "y": 0.82},
            visual_target_label="朵朵",
            visual_target_preview="你好啊",
        )

        self.assertEqual(action["status"], "ok")
        step = action["planned_steps"][0]
        self.assertEqual(step["intent"], "tap_tashuo_visual_conversation_target")
        self.assertEqual(step["tap_ratio"], {"x": 0.5, "y": 0.82})
        self.assertEqual(step["visual_target_label"], "朵朵")
        self.assertEqual(step["visual_target_preview"], "你好啊")
        self.assertEqual(step["selection_method"], "host_visual_tap_ratio")
        self.assertNotIn("row_index", step)

    def test_tashuo_mac_ios_app_open_conversation_relocates_visual_anchor_before_tapping(self):
        old_list_png = _tashuo_mac_ios_app_message_list_with_target_row_png(target_center_y=0.34)
        current_list_png = _tashuo_mac_ios_app_message_list_with_target_row_png(target_center_y=0.62)
        row_region = {"x1": 0.05, "y1": 0.29, "x2": 0.95, "y2": 0.39}
        row_visual_hash = _png_average_hash(old_list_png, region=row_region)
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                current_list_png,
                current_list_png,
                current_list_png,
                _tashuo_mac_ios_app_conversation_with_messages_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac-ios-app")

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("dating_boost.apps.native_gui_session.time.sleep", return_value=None),
            patch("dating_boost.apps.tashuo.native.time.sleep", return_value=None),
        ):
            payload = harness.run_action(
                "open-conversation",
                dry_run=False,
                output_dir=Path(temp_dir),
                tap_ratio={"x": 0.45, "y": 0.34},
                visual_target_label="小药丸儿",
                visual_target_preview="我也比较慢热",
                message_list_evidence={
                    "source_state": "tashuo_chat_list",
                    "selection_method": "message_list_visual_anchor_scan",
                    "visual_anchor_hash": row_visual_hash,
                    "visual_anchor_region": row_region,
                    "visual_anchor_scan_region": {"x1": 0.0, "y1": 0.18, "x2": 1.0, "y2": 0.84},
                    "tap_ratio": {"x": 0.45, "y": 0.34},
                    "visual_anchor_max_hamming_distance": 0,
                },
            )

        self.assertEqual(payload["status"], "ok")
        relocation = payload["message_list_relocation"]["message_list_location"]
        self.assertEqual(relocation["location_method"], "message_list_visual_anchor_scan")
        self.assertAlmostEqual(relocation["tap_ratio"]["y"], 0.60, delta=0.04)
        self.assertAlmostEqual(payload["executed_steps"][0]["tap_ratio"]["y"], 0.60, delta=0.04)
        self.assertEqual(payload["executed_steps"][0]["selection_method"], "message_list_visual_anchor_scan")
        self.assertEqual(relocation["tap_adjustment"]["reason"], "row_upper_band_guard")

    def test_tashuo_mac_ios_app_open_conversation_relocates_bottom_visible_visual_anchor(self):
        old_list_png = _tashuo_mac_ios_app_message_list_with_target_row_png(target_center_y=0.85)
        current_list_png = _tashuo_mac_ios_app_message_list_with_target_row_png(target_center_y=0.85)
        row_region = {"x1": 0.05, "y1": 0.80, "x2": 0.95, "y2": 0.90}
        row_visual_hash = _png_average_hash(old_list_png, region=row_region)
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                current_list_png,
                current_list_png,
                current_list_png,
                _tashuo_mac_ios_app_conversation_with_messages_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac-ios-app")

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("dating_boost.apps.native_gui_session.time.sleep", return_value=None),
            patch("dating_boost.apps.tashuo.native.time.sleep", return_value=None),
        ):
            payload = harness.run_action(
                "open-conversation",
                dry_run=False,
                output_dir=Path(temp_dir),
                tap_ratio={"x": 0.45, "y": 0.85},
                visual_target_label="如是徧是",
                visual_target_preview="确实，端午就该给自己开个省电…",
                message_list_evidence={
                    "source_state": "tashuo_chat_list",
                    "selection_method": "message_list_visual_anchor_scan",
                    "visual_anchor_hash": row_visual_hash,
                    "visual_anchor_region": row_region,
                    "tap_ratio": {"x": 0.45, "y": 0.85},
                    "visual_anchor_max_hamming_distance": 0,
                },
            )

        self.assertEqual(payload["status"], "ok")
        relocation = payload["message_list_relocation"]["message_list_location"]
        self.assertEqual(relocation["location_method"], "message_list_visual_anchor_scan")
        self.assertAlmostEqual(relocation["tap_ratio"]["y"], 0.85, delta=0.02)
        self.assertAlmostEqual(payload["executed_steps"][0]["tap_ratio"]["y"], 0.85, delta=0.02)
        self.assertFalse(relocation["tap_adjustment"]["adjusted"])
        self.assertIsNone(relocation["tap_adjustment"]["reason"])
        self.assertTrue(relocation["tap_adjustment"]["bottom_row_detected"])

    def test_tashuo_mac_ios_app_open_conversation_clamps_noisy_bottom_anchor_tap_above_tab_bar(self):
        old_list_png = _tashuo_mac_ios_app_message_list_with_target_row_png(target_center_y=0.85)
        current_list_png = _tashuo_mac_ios_app_message_list_with_target_row_png(target_center_y=0.85)
        row_region = {"x1": 0.05, "y1": 0.83, "x2": 0.95, "y2": 0.95}
        row_visual_hash = _png_average_hash(old_list_png, region=row_region)
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                current_list_png,
                current_list_png,
                current_list_png,
                _tashuo_mac_ios_app_conversation_with_messages_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac-ios-app")

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("dating_boost.apps.native_gui_session.time.sleep", return_value=None),
            patch("dating_boost.apps.tashuo.native.time.sleep", return_value=None),
        ):
            payload = harness.run_action(
                "open-conversation",
                dry_run=False,
                output_dir=Path(temp_dir),
                tap_ratio={"x": 0.45, "y": 0.891},
                visual_target_label="如是徧是",
                visual_target_preview="确实，端午就该给自己开个省电…",
                message_list_evidence={
                    "source_state": "tashuo_chat_list",
                    "selection_method": "message_list_visual_anchor_scan",
                    "visual_anchor_hash": row_visual_hash,
                    "visual_anchor_region": row_region,
                    "tap_ratio": {"x": 0.45, "y": 0.891},
                    "visual_anchor_max_hamming_distance": 0,
                },
            )

        self.assertEqual(payload["status"], "ok")
        relocation = payload["message_list_relocation"]["message_list_location"]
        self.assertEqual(relocation["location_method"], "message_list_visual_anchor_scan")
        self.assertGreater(relocation["raw_tap_ratio"]["y"], relocation["tap_ratio"]["y"])
        self.assertLessEqual(relocation["tap_ratio"]["y"], 0.86)
        self.assertTrue(relocation["tap_adjustment"]["adjusted"])
        self.assertEqual(relocation["tap_adjustment"]["reason"], "bottom_row_safe_tap_guard")
        self.assertTrue(relocation["tap_adjustment"]["bottom_row_detected"])
        self.assertEqual(payload["executed_steps"][0]["tap_ratio"], relocation["tap_ratio"])

    def test_tashuo_mac_ios_app_open_conversation_short_circuits_when_thread_already_open(self):
        runner = FakeRunner(
            ocr_text="朵朵\n她跳过了问答考验，快和她聊聊吧\nhi\n你好啊\n点击此处输入文字\n",
            screenshot_bytes=_tashuo_mac_ios_app_conversation_with_messages_png(),
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac-ios-app")

        payload = harness.run_action(
            "open-conversation",
            dry_run=False,
            tap_ratio={"x": 0.50, "y": 0.82},
            visual_target_label="朵朵",
            visual_target_preview="你好啊",
        )

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["already_at_expected_state"])
        self.assertEqual(payload["screen_state"], "tashuo_conversation")
        self.assertEqual(payload["next_host_action"], "observe_current_thread")
        self.assertNotIn("executed_steps", payload)

    def test_tashuo_mac_ios_app_open_conversation_relocates_from_existing_thread_when_target_evidence_present(self):
        old_thread_png = _tashuo_mac_ios_app_conversation_with_messages_png(accent=(92, 168, 126, 255))
        target_thread_png = _tashuo_mac_ios_app_conversation_with_messages_png(accent=(168, 92, 126, 255))
        old_list_png = _tashuo_mac_ios_app_message_list_with_target_row_png(target_center_y=0.34)
        list_png = _tashuo_mac_ios_app_message_list_with_target_row_png(target_center_y=0.62)
        row_region = {"x1": 0.05, "y1": 0.29, "x2": 0.95, "y2": 0.39}
        row_visual_hash = _png_average_hash(old_list_png, region=row_region)
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                old_thread_png,
                list_png,
                list_png,
                list_png,
                target_thread_png,
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac-ios-app")

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("dating_boost.apps.native_gui_session.time.sleep", return_value=None),
            patch("dating_boost.apps.tashuo.native.time.sleep", return_value=None),
        ):
            payload = harness.run_action(
                "open-conversation",
                dry_run=False,
                output_dir=Path(temp_dir),
                tap_ratio={"x": 0.45, "y": 0.34},
                visual_target_label="小药丸儿",
                visual_target_preview="我也比较慢热",
                message_list_evidence={
                    "source_state": "tashuo_chat_list",
                    "selection_method": "message_list_visual_anchor_scan",
                    "visual_anchor_hash": row_visual_hash,
                    "visual_anchor_region": row_region,
                    "visual_anchor_scan_region": {"x1": 0.0, "y1": 0.18, "x2": 1.0, "y2": 0.84},
                    "tap_ratio": {"x": 0.45, "y": 0.34},
                    "visual_anchor_max_hamming_distance": 0,
                },
            )

        self.assertEqual(payload["status"], "ok")
        self.assertNotIn("already_at_expected_state", payload)
        recovery = payload["message_list_relocation"]["message_list_recovery"]
        self.assertEqual(recovery["screen_state"], "tashuo_conversation")
        self.assertEqual(recovery["return_to_chats"]["intent"], "tap_tashuo_back_to_chats")
        self.assertEqual(payload["executed_steps"][0]["selection_method"], "message_list_visual_anchor_scan")

    def test_tashuo_mac_ios_app_open_conversation_retries_body_tap_when_action_tap_does_not_open(self):
        list_png = _tashuo_mac_ios_app_message_list_with_target_row_png(target_center_y=0.82)
        target_thread_png = _tashuo_mac_ios_app_conversation_with_messages_png(accent=(168, 92, 126, 255))
        row_region = {"x1": 0.04, "y1": 0.77, "x2": 0.96, "y2": 0.87}
        row_visual_hash = _png_average_hash(list_png, region=row_region)
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                list_png,
                list_png,
                list_png,
                list_png,
                list_png,
                list_png,
                target_thread_png,
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac-ios-app")

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("dating_boost.apps.native_gui_session.time.sleep", return_value=None),
            patch("dating_boost.apps.tashuo.native.time.sleep", return_value=None),
        ):
            payload = harness.run_action(
                "open-conversation",
                dry_run=False,
                output_dir=Path(temp_dir),
                tap_ratio={"x": 0.87, "y": 0.821},
                visual_target_label="小药丸儿",
                visual_target_preview="我也比较慢热",
                message_list_evidence={
                    "source_state": "tashuo_chat_list",
                    "selection_method": "message_list_visual_anchor_scan",
                    "visual_anchor_hash": row_visual_hash,
                    "visual_anchor_region": row_region,
                    "visual_anchor_scan_region": {"x1": 0.0, "y1": 0.18, "x2": 1.0, "y2": 0.90},
                    "tap_ratio": {"x": 0.87, "y": 0.821},
                    "tap_ratio_source": "corrected_all_messages_row_action",
                    "visual_anchor_max_hamming_distance": 0,
                },
            )

        self.assertEqual(payload["status"], "ok")
        attempts = payload["message_list_open_fallback_attempts"]
        self.assertEqual(attempts[0]["selection_method"], "message_list_visual_anchor_body_fallback_tap")
        self.assertEqual(attempts[0]["result"]["status"], "ok")
        self.assertEqual(payload["message_list_open_initial_result"]["reason"], "tashuo_step_postcondition_not_verified")
        self.assertEqual(payload["executed_steps"][0]["selection_method"], "message_list_visual_anchor_body_fallback_tap")
        self.assertEqual(payload["executed_steps"][0]["message_list_open_fallback"]["attempt_index"], 1)

    def test_tashuo_mac_ios_app_open_conversation_waits_before_postcondition_capture(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                _tashuo_messages_bottom_nav_png(),
                _tashuo_messages_bottom_nav_png(),
                _tashuo_messages_bottom_nav_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac-ios-app")
        sleeps: list[float] = []

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("dating_boost.apps.native_gui_session.time.sleep", side_effect=lambda seconds: sleeps.append(seconds)),
        ):
            payload = harness.run_action(
                "open-conversation",
                dry_run=False,
                output_dir=Path(temp_dir),
                tap_ratio={"x": 0.86, "y": 0.47},
                visual_target_label="仿生人会爱上锅包肉吗",
                visual_target_preview="哈哈哈哈哈",
            )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["executed_steps"][0]["postcondition"]["screen_state"], "tashuo_conversation")
        self.assertIn(2.0, sleeps)
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_open_conversation_dismisses_notification_prompt_before_postcondition(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                _tashuo_messages_bottom_nav_png(),
                _tashuo_messages_bottom_nav_png(),
                _tashuo_messages_bottom_nav_png(),
                _tashuo_mac_ios_app_conversation_notification_prompt_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac-ios-app")

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("dating_boost.apps.native_gui_session.time.sleep", return_value=None),
            patch("dating_boost.apps.tashuo.native.time.sleep", return_value=None),
        ):
            payload = harness.run_action(
                "open-conversation",
                dry_run=False,
                output_dir=Path(temp_dir),
                tap_ratio={"x": 0.86, "y": 0.47},
                visual_target_label="小药丸儿",
                visual_target_preview="我也比较慢热",
            )

        self.assertEqual(payload["status"], "ok")
        postcondition = payload["executed_steps"][0]["postcondition"]
        self.assertEqual(postcondition["screen_state"], "tashuo_conversation")
        self.assertTrue(postcondition["dismissed_tashuo_notification_prompt"])
        self.assertEqual(postcondition["first_screen_state"], "tashuo_conversation_notification_prompt")
        self.assertTrue(
            any(
                command
                and command[0] == "osascript"
                and "DATING_BOOST_TASHUO_DISMISS_NOTIFICATION_PROMPT" in " ".join(command)
                for command in runner.commands
            )
        )

    def test_tashuo_mac_ios_conversation_list_scroll_to_top_requires_top_anchor(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                _tashuo_messages_bottom_nav_png(),
                _tashuo_messages_top_anchor_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac-ios-app")
        sleeps: list[float] = []

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("dating_boost.apps.tashuo.native.time.sleep", side_effect=lambda seconds: sleeps.append(seconds)),
        ):
            payload = harness.run_action(
                "conversation-list-scroll-to-top",
                dry_run=False,
                output_dir=Path(temp_dir),
                max_scrolls=3,
            )

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["top_anchor_verified"])
        self.assertEqual([attempt["top_anchor_verified"] for attempt in payload["attempts"]], [False, True])
        self.assertEqual(len(payload["executed_steps"]), 1)
        self.assertIn(2.0, sleeps)
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))
