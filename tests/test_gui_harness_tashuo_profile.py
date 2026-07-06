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


class GuiHarnessTashuoProfileTests(GuiHarnessTestCase):
    def test_tashuo_mac_ios_prepare_self_profile_page_uses_ax_radio_button_without_ocr(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                _tashuo_recommend_bottom_nav_png(),
                _tashuo_messages_bottom_nav_png(),
                _tashuo_top_level_bottom_nav_png("mine"),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_action("prepare-self-profile-page", dry_run=False, output_dir=Path(temp_dir))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(payload["screen_state"], "tashuo_self_profile")
        self.assertEqual(payload["next_host_action"], "extract_visible_self_profile_facts")
        self.assertFalse(payload["ocr_used"])
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))
        self.assertIn(
            "prepare_tashuo_message_page_as_safe_top_level_anchor",
            [step["intent"] for step in payload["executed_steps"]],
        )
        self.assertIn("click_tashuo_mine_tab_accessibility", [step["intent"] for step in payload["executed_steps"]])
        self.assertTrue(any("radio button 4" in " ".join(command) for command in runner.commands))
        self.assertNotIn("tap_tashuo_conversation_row", [step["intent"] for step in payload["executed_steps"]])

    def test_tashuo_mac_ios_prepare_self_profile_page_fallback_taps_real_mine_tab_when_ax_missing(self):
        class MineAxMissingRunner(FakeRunner):
            def run(self, command, *, input=None):
                if command and command[0] == "osascript" and any("radio button 4" in item for item in command):
                    self.commands.append(command)
                    self.command_inputs.append((command, input))
                    return _result(stderr='System Events got an error: Can’t get radio button 4.', returncode=1)
                return super().run(command, input=input)

        runner = MineAxMissingRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                _tashuo_recommend_bottom_nav_png(),
                _tashuo_messages_bottom_nav_png(),
                _tashuo_top_level_bottom_nav_png("mine"),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_action("prepare-self-profile-page", dry_run=False, output_dir=Path(temp_dir))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["screen_state"], "tashuo_self_profile")
        fallback = next(step for step in payload["executed_steps"] if step["intent"] == "tap_tashuo_mine_tab_fallback")
        self.assertAlmostEqual(fallback["tap_ratio"]["x"], 0.86)
        self.assertAlmostEqual(fallback["tap_ratio"]["y"], 0.96)

    def test_tashuo_mac_ios_open_self_profile_detail_taps_avatar_read_only(self):
        runner = FakeRunner(
            ocr_text="OCR should not be used",
            window_name="她说",
            screenshot_bytes=[
                _tashuo_recommend_bottom_nav_png(),
                _tashuo_messages_bottom_nav_png(),
                _tashuo_top_level_bottom_nav_png("mine"),
                _tashuo_mac_ios_app_profile_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_action("open-self-profile-detail", dry_run=False, output_dir=Path(temp_dir))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(payload["screen_state"], "tashuo_profile")
        self.assertEqual(payload["next_host_action"], "extract_visible_self_profile_detail_facts")
        self.assertFalse(payload["ocr_used"])
        self.assertTrue(any(command and command[0] == "tesseract" for command in runner.commands))
        intents = [step["intent"] for step in payload["executed_steps"]]
        self.assertIn("prepare_tashuo_self_profile_page_top", intents)
        self.assertIn("tap_tashuo_self_profile_avatar", intents)
        self.assertNotIn("tap_tashuo_conversation_row", intents)
        avatar_tap = next(step for step in payload["executed_steps"] if step["intent"] == "tap_tashuo_self_profile_avatar")
        self.assertTrue(avatar_tap["does_not_tap_edit_profile"])
        self.assertAlmostEqual(avatar_tap["tap_ratio"]["x"], 0.50)
        self.assertAlmostEqual(avatar_tap["tap_ratio"]["y"], 0.27)

    def test_tashuo_mac_ios_profile_scroll_to_bottom_stops_on_share_anchor(self):
        runner = FakeRunner(
            ocr_text=[
                "我的资料\nVibe Coding\n健身\n补觉\n",
                "我的资料\n我的MBTI\nENFP创造家\n小狗\n",
                "我的资料\n近期动态\n我在哪里\n北京市 朝阳区\n分享给好友\n",
            ],
            window_name="她说",
            screenshot_bytes=[
                _tashuo_mac_ios_app_profile_mid_png(),
                _tashuo_mac_ios_app_profile_mid_png(),
                _tashuo_mac_ios_app_profile_bottom_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_action("profile-scroll-to-bottom", dry_run=False, output_dir=Path(temp_dir), max_scrolls=3)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["reason"], "tashuo_profile_bottom_anchor_verified")
        self.assertTrue(payload["bottom_anchor_verified"])
        self.assertEqual(payload["attempt_count"], 3)
        self.assertEqual(len(payload["executed_steps"]), 2)
        self.assertTrue(all(step["intent"] == "wheel_tashuo_profile_read_down" for step in payload["executed_steps"]))
        self.assertEqual(payload["next_host_action"], "extract_visible_self_profile_detail_facts")

    def test_tashuo_mac_ios_profile_scroll_to_bottom_continues_through_mid_profile_without_title(self):
        runner = FakeRunner(
            ocr_text=[
                "Vibe Coding\n健身\n补觉\n",
                "更多信息\n有健身习惯\n不饮酒\n不吸烟\n我的恋爱三观\n我的心灵测试\n关于人生阶段\n",
                "近期动态\n我在哪里\n北京市 朝阳区\n分享给好友\n",
            ],
            window_name="她说",
            screenshot_bytes=[
                _tashuo_mac_ios_app_profile_mid_png(),
                _tashuo_mac_ios_app_profile_bottom_png(),
                _tashuo_mac_ios_app_profile_bottom_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_action("profile-scroll-to-bottom", dry_run=False, output_dir=Path(temp_dir), max_scrolls=3)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["reason"], "tashuo_profile_bottom_anchor_verified")
        self.assertTrue(payload["bottom_anchor_verified"])
        self.assertEqual(payload["attempt_count"], 3)
        self.assertEqual(len(payload["executed_steps"]), 2)

    def test_tashuo_close_profile_retries_postcondition_after_transition_frame(self):
        runner = FakeRunner(
            ocr_text=[
                "",
                "",
                "",
                "",
                "",
            ],
            screenshot_bytes=[
                _tashuo_mac_ios_app_profile_png(),
                _tashuo_mac_ios_app_profile_png(),
                _tashuo_mac_ios_app_profile_closing_transition_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac-ios-app")

        payload = harness.run_action("close-profile", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["executed_steps"][0]["postcondition"]["screen_state"], "tashuo_conversation")
        self.assertTrue(payload["executed_steps"][0]["postcondition"]["retried_after_transition"])

    def test_visual_tashuo_mac_ios_app_profile_uses_media_and_info_card_layout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot_path = Path(temp_dir) / "tashuo-mac-ios-profile.png"
            screenshot_path.write_bytes(_tashuo_mac_ios_app_profile_png())

            payload = classify_tashuo_screen_image(screenshot_path)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["state"], "tashuo_profile")
        self.assertFalse(payload["bottom_nav_present"])
        self.assertFalse(payload["conversation_toolbar_present"])

    def test_tashuo_capture_accepts_visual_profile_when_ocr_is_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot_path = Path(temp_dir) / "tashuo-mac-ios-profile.png"
            screenshot_path.write_bytes(_tashuo_mac_ios_app_profile_png())

            payload = classify_tashuo_capture(screenshot_path, "")

        self.assertEqual(payload["text_state"], "unknown")
        self.assertEqual(payload["visual_state"], "tashuo_profile")
        self.assertEqual(payload["state"], "tashuo_profile")
