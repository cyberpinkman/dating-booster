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


class GuiHarnessTashuoScreenStateTests(GuiHarnessTestCase):
    def test_tashuo_current_thread_visual_anchor_distance_uses_calibrated_floor(self):
        self.assertEqual(tashuo_native._tashuo_visual_anchor_max_distance({}), 12)
        self.assertEqual(
            tashuo_native._tashuo_visual_anchor_max_distance({"visual_anchor_max_hamming_distance": 6}),
            12,
        )
        self.assertEqual(
            tashuo_native._tashuo_visual_anchor_max_distance({"visual_anchor_max_hamming_distance": 15}),
            15,
        )

    def test_tashuo_open_chats_accepts_visual_top_level_state_when_ocr_is_unknown(self):
        runner = FakeRunner(
            ocr_text="她说\n谁喜欢了我\n",
            window_name="她说",
            screenshot_bytes=[
                _tashuo_recommend_bottom_nav_png(),
                _tashuo_messages_bottom_nav_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.run_action("open-chats", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["executed_steps"][-1]["postcondition"]["screen_state"], "tashuo_chat_list")
        self.assertIn("tap_tashuo_messages_tab", [step["intent"] for step in payload["executed_steps"]])

    def test_tashuo_message_list_relocation_prefers_prior_tap_when_visual_anchor_is_ambiguous(self):
        width, height = 288, 541
        ambiguous_png = _png_from_pixels(
            [[(255, 255, 255, 255) for _x in range(width)] for _y in range(height)],
            width,
            height,
        )
        row_region = {"x1": 0.02, "y1": 0.7815, "x2": 0.98, "y2": 0.8605}
        row_visual_hash = _png_average_hash(ambiguous_png, region=row_region)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ambiguous-list.png"
            path.write_bytes(ambiguous_png)

            location = tashuo_native._locate_tashuo_message_list_visual_target(
                {"status": "ok", "state": "tashuo_chat_list", "path": str(path)},
                {
                    "status": "ok",
                    "evidence_type": "message_list_visual_anchor",
                    "visual_anchor_hash": row_visual_hash,
                    "visual_anchor_region": row_region,
                    "visual_anchor_scan_region": {"x1": 0.0, "y1": 0.16, "x2": 1.0, "y2": 0.95},
                    "visual_anchor_max_hamming_distance": 0,
                    "tap_ratio": {"x": 0.87, "y": 0.821},
                },
            )

        self.assertEqual(location["status"], "ok")
        self.assertEqual(location["location_method"], "message_list_visual_anchor_scan")
        self.assertLess(location["visual_anchor_tap_y_delta"], 0.01)
        self.assertAlmostEqual(location["raw_tap_ratio"]["y"], 0.821, delta=0.01)
        self.assertAlmostEqual(location["tap_ratio"]["x"], 0.87, delta=0.001)
        self.assertGreater(location["tap_ratio"]["y"], row_region["y1"])
        self.assertLess(location["tap_ratio"]["y"], row_region["y2"])

    def test_tashuo_default_runtime_does_not_accept_visual_commit_without_text_verification(self):
        runner = FakeRunner(
            ocr_text=[
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n今晚可以聊十分钟吗？\n",
                "Yasmine\n不理解\nOCR没有读到新气泡\n点击此处输入文字\n",
            ],
            screenshot_bytes=[
                _tashuo_mac_ios_app_conversation_with_messages_png(outgoing_bubble=False),
                _tashuo_mac_ios_app_conversation_with_messages_png(outgoing_bubble=False),
                _tashuo_mac_ios_app_conversation_with_messages_png(outgoing_bubble=False),
                _tashuo_mac_ios_app_conversation_with_messages_png(outgoing_bubble=False),
                _tashuo_mac_ios_app_conversation_with_messages_png(outgoing_bubble=True),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner)

        payload = harness.send_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Yasmine"], "target_match_id": "match_tashuo"},
        )

        self.assertEqual(payload["status"], "needs_verification")
        self.assertEqual(payload["reason"], "outbound_message_not_verified")
        self.assertFalse(payload["evidence"]["outbound_exact_text_verified"])
        self.assertFalse(payload["evidence"]["outbound_exact_text_visual_verified"])
        self.assertFalse(payload["evidence"]["outbound_visual_commit_verified"])
        self.assertFalse(payload["evidence"]["visual_only_exact_verification_allowed"])
        self.assertEqual(
            payload["outbound_message_verification"]["visual_commit_verification"]["status"],
            "not_applicable",
        )

    def test_tashuo_mac_ios_app_inconclusive_stage_waits_for_host_visual_verification(self):
        runner = FakeRunner(
            ocr_text=[
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\nv\n发送\n",
                "Yasmine\n不理解\n点击此处输入文字\n",
            ],
            window_name="她说",
            screenshot_bytes=_tashuo_mac_ios_app_conversation_with_messages_png(),
            paste_focus_override="v",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(
            "你好",
            dry_run=False,
            target_binding={
                "binding_type": "chat_list_row_to_thread",
                "target_match_id": "match_tashuo",
                "candidate_key": "tashuo_row_1",
                "selection_evidence": {
                    "source_state": "tashuo_chat_list",
                    "opened_state": "tashuo_conversation",
                    "row_index": 1,
                    "target_scope": "ordinary_conversation",
                    "open_action": "open-conversation",
                },
            },
        )

        self.assertEqual(payload["status"], "needs_host_visual_verification")
        self.assertEqual(payload["reason"], "staged_text_requires_visual_verification")
        self.assertEqual(payload["next_host_action"], "visually_verify_staged_text_before_live_send")
        self.assertNotIn("failed_stage_cleanup", payload)
        self.assertEqual(payload["visual_verification_request"]["ocr_status"], "skipped")
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_classifies_tashuo_screens_and_question_gate(self):
        self.assertEqual(
            classify_tashuo_screen_text("推荐\nsmilewen 31\n1日内活跃\n推荐\n飞行\n消息\n我的"),
            "tashuo_recommend",
        )
        self.assertEqual(
            classify_tashuo_screen_text("飞行\n背上行囊 偶遇新的朋友\n轻触屏幕 马上开聊\n推荐\n飞行\n消息\n我的"),
            "tashuo_flight",
        )
        self.assertEqual(
            classify_tashuo_screen_text("搜索\n取消\n小药丸儿\n上次聊天\n旧金山\n大学"),
            "tashuo_search",
        )
        self.assertEqual(
            classify_tashuo_screen_text("消息\n待回答 (0)\n全部消息\nYasmine\n不理解\n推荐\n飞行\n消息\n我的"),
            "tashuo_chat_list",
        )
        self.assertEqual(
            classify_tashuo_screen_text(
                "消息\n动态\n开启通知，不要让喜欢你的人等太久！\n"
                "待回答 (0)\n等待中\n全部消息\nMM豆\nhi\n小药丸儿\n哈喽呀\n推荐\n飞行\n消息\n我的"
            ),
            "tashuo_chat_list",
        )
        self.assertEqual(
            classify_tashuo_screen_text("Pink\n编辑资料\n我的认证\n谁喜欢了我\n我喜欢的人\n推荐\n飞行\n消息\n我的"),
            "tashuo_self_profile",
        )
        self.assertEqual(
            classify_tashuo_screen_text("小药丸儿 25\n资料\n关于我\n星座\n家乡\n我的日常"),
            "tashuo_profile",
        )
        self.assertEqual(
            classify_tashuo_screen_text("朵朵 31\n某厂 · 运营\n长春理工大学\n162cm\n天蝎座\n家乡 · 长春"),
            "tashuo_profile",
        )
        self.assertEqual(
            classify_tashuo_screen_text("更多信息\n有健身习惯\n不饮酒\n不吸烟\n我的恋爱三观\n我的心灵测试\n关于人生阶段"),
            "tashuo_profile",
        )
        self.assertEqual(
            classify_tashuo_screen_text("近期动态\n我在哪里\n北京市 朝阳区\n分享给好友"),
            "tashuo_profile",
        )
        self.assertEqual(
            combine_tashuo_screen_states(
                "unknown",
                "tashuo_conversation",
                "近期动态\n我在哪里\n北京市 朝阳区\n分享给好友",
            ),
            "tashuo_profile",
        )
        self.assertEqual(
            classify_tashuo_screen_text("Yasmine\n不理解\n点击此处输入文字\n"),
            "tashuo_conversation",
        )
        self.assertEqual(
            classify_tashuo_screen_text("Yasmine\n不理解\n今晚聊得挺舒服的。\n发送\n"),
            "tashuo_conversation",
        )
        self.assertEqual(
            classify_tashuo_screen_text(
                "小药丸儿\n你喜欢我资料里哪一点?\n白羊座，enfp，认为朋友很重要\n"
                "她开启了永久聊天\n继续聊聊问答中她感兴趣的话题\nHi，我们可以聊天啦!\n"
                "昨天 22:10\n哈喽\n00:21\n哈喽呀\n点击此处输入文字"
            ),
            "tashuo_conversation",
        )
        self.assertEqual(
            classify_tashuo_screen_text("待回答\n她向你提了一个问题\n回答后即可开启聊天\n"),
            "tashuo_question_gate",
        )
        self.assertEqual(
            classify_tashuo_screen_text("Yasmine\n她向你提了一个问题\n点击此处输入文字\n发送\n"),
            "tashuo_question_gate",
        )
        self.assertEqual(
            classify_tashuo_screen_text("Yasmine\n待回答\n点击此处输入文字\n发送\n"),
            "tashuo_conversation",
        )
        self.assertEqual(
            classify_tashuo_screen_text("Yasmine\n回答后\n点击此处输入文字\n发送\n"),
            "tashuo_conversation",
        )
        self.assertEqual(
            combine_tashuo_screen_states(
                "unknown",
                "tashuo_conversation",
                "飞行\n背上行囊 偶遇新的朋友\n轻触屏幕 马上开聊\n",
            ),
            "tashuo_flight",
        )
        flight_hints = tashuo_layout_hints(
            {"state": "tashuo_flight", "text": "飞行\n背上行囊 偶遇新的朋友\n马上开聊"}
        )
        self.assertFalse(flight_hints["conversation_present"])
        self.assertFalse(flight_hints["draft_staging_supported"])

    def test_visual_tashuo_mac_ios_app_conversation_uses_lower_input_toolbar(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot_path = Path(temp_dir) / "tashuo-mac-ios-conversation.png"
            screenshot_path.write_bytes(_tashuo_mac_ios_app_conversation_toolbar_png())

            payload = classify_tashuo_screen_image(screenshot_path)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["state"], "tashuo_conversation")
        self.assertFalse(payload["bottom_nav_present"])
        self.assertTrue(payload["conversation_toolbar_present"])

    def test_visual_tashuo_notification_prompt_is_recoverable_not_stageable_conversation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot_path = Path(temp_dir) / "tashuo-notification-prompt.png"
            screenshot_path.write_bytes(_tashuo_mac_ios_app_conversation_notification_prompt_png())

            payload = classify_tashuo_screen_image(screenshot_path)
            capture = classify_tashuo_capture(screenshot_path, "")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["state"], "tashuo_conversation_notification_prompt")
        self.assertTrue(payload["conversation_notification_prompt_present"])
        self.assertFalse(payload["conversation_toolbar_present"])
        self.assertEqual(capture["state"], "tashuo_conversation_notification_prompt")
        self.assertFalse(tashuo_layout_hints(capture)["draft_staging_supported"])

    def test_visual_tashuo_recommend_uses_bottom_nav_active_color(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot_path = Path(temp_dir) / "tashuo-recommend-bottom-nav.png"
            screenshot_path.write_bytes(_tashuo_recommend_bottom_nav_png())

            payload = classify_tashuo_screen_image(screenshot_path)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["state"], "tashuo_recommend")
        self.assertEqual(payload["active_tab"], "recommend")
        self.assertTrue(payload["bottom_nav_present"])
        self.assertFalse(payload["conversation_toolbar_present"])

    def test_visual_tashuo_liked_you_modal_is_not_classified_as_conversation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot_path = Path(temp_dir) / "tashuo-liked-you-modal.png"
            screenshot_path.write_bytes(_tashuo_liked_you_modal_png())

            payload = classify_tashuo_screen_image(screenshot_path)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["state"], "tashuo_liked_you_modal")
        self.assertTrue(payload["liked_you_modal_present"])
        self.assertFalse(payload["bottom_nav_present"])

    def test_visual_tashuo_conversation_uses_persistent_input_toolbar(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = create_adapter(
                app_id="tashuo",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="EB vasmine eee\nget $2!)\nRRM RaRRS\nARTA Zhe\n",
                    screenshot_bytes=_tashuo_conversation_toolbar_png(),
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "tashuo-conversation.png")

        self.assertEqual(payload["text_state"], "unknown")
        self.assertEqual(payload["visual_state"], "tashuo_conversation")
        self.assertFalse(payload["visual_bottom_nav_present"])
        self.assertEqual(payload["state"], "tashuo_conversation")

    def test_visual_tashuo_mac_ios_conversation_toolbar_tolerates_title_chrome_offset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = create_adapter(
                app_id="tashuo",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="昨天 17:33\nhi\n昨天 17:54\n你好啊\n",
                    screenshot_bytes=_tashuo_mac_ios_app_conversation_with_title_chrome_png(),
                    window_name="她说",
                ),
                runtime="mac_ios_app",
            )

            payload = harness.capture_window(output=Path(temp_dir) / "tashuo-mac-ios-conversation-title.png")

        self.assertEqual(payload["text_state"], "unknown")
        self.assertEqual(payload["visual_state"], "tashuo_conversation")
        self.assertFalse(payload["visual_bottom_nav_present"])
        self.assertEqual(payload["state"], "tashuo_conversation")

    def test_visual_tashuo_conversation_toolbar_does_not_override_question_gate_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = create_adapter(
                app_id="tashuo",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="Yasmine\n她向你提了一个问题\n回答后即可开启聊天\n",
                    screenshot_bytes=_tashuo_conversation_toolbar_png(),
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "tashuo-question-gate.png")

        self.assertEqual(payload["text_state"], "tashuo_question_gate")
        self.assertEqual(payload["visual_state"], "tashuo_conversation")
        self.assertEqual(payload["state"], "tashuo_question_gate")
