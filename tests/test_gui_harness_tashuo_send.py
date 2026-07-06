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


class GuiHarnessTashuoSendTests(GuiHarnessTestCase):
    def test_tashuo_mac_ios_app_stage_draft_dry_run_is_stage_only(self):
        runner = FakeRunner(ocr_text="Yasmine\n点击此处输入文字\n", window_name="她说")
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.stage_draft("今晚聊得挺舒服的。", dry_run=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(payload["action"], "stage_draft")
        self.assertEqual(payload["target"], "tashuo_message_input")
        self.assertTrue(payload["requires_user_confirmation_before_send"])
        self.assertTrue(all(step.get("risk") == "draft_staging_only" for step in payload["planned_steps"]))
        self.assertTrue(all(step.get("does_not_send", True) for step in payload["planned_steps"]))
        self.assertIn("send", payload["blocked_actions"])
        self.assertEqual(
            payload["input_coordinate_model"],
            {
                "runtime": "mac_ios_app",
                "coordinate_shift_after_focus": True,
                "unfocused_input_tap_ratio": {"x": 0.32, "y": 0.91},
                "focused_input_tap_ratio": {"x": 0.32, "y": 0.9},
            },
        )
        self.assertEqual(payload["planned_steps"][0]["focus_state"], "unfocused")
        self.assertEqual(payload["planned_steps"][0]["tap_ratio"], {"x": 0.32, "y": 0.91})

    def test_tashuo_mac_ios_app_send_message_dry_run_is_authorized_live_send_plan(self):
        runner = FakeRunner(ocr_text="Yasmine\n点击此处输入文字\n", window_name="她说")
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message("今晚聊得挺舒服的。", dry_run=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(payload["action"], "send_message")
        self.assertTrue(payload["live_send"])
        self.assertTrue(payload["requires_explicit_authorization"])
        self.assertIn(
            "press_return_to_send_tashuo_message",
            [step["intent"] for step in payload["planned_steps"]],
        )
        self.assertNotIn("tap_tashuo_send_button", [step["intent"] for step in payload["planned_steps"]])
        return_step = next(step for step in payload["planned_steps"] if step["intent"] == "press_return_to_send_tashuo_message")
        self.assertEqual(return_step["risk"], "live_send")
        self.assertTrue(return_step["requires_explicit_authorization"])

    def test_tashuo_mac_ios_app_send_message_requires_structural_binding_not_header_ocr(self):
        runner = FakeRunner(
            ocr_text=[
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n今晚可以聊十分钟吗？\n发送\n",
                "Yasmine\n不理解\n今晚可以聊十分钟吗？\n点击此处输入文字\n",
            ],
            window_name="她说",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            payload = harness.send_message(
                "今晚可以聊十分钟吗？",
                dry_run=False,
                output_dir=output_dir,
                target_binding={"required_visible_text": ["Yasmine"], "target_match_id": "match_tashuo"},
            )
            captured_names = {path.name for path in output_dir.iterdir()}

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(payload["reason"], "target_binding_structural_evidence_required")
        self.assertNotIn("mac_ios_app.tashuo.before_send_message.png", captured_names)
        self.assertNotIn("mac_ios_app.tashuo.after_send_message.png", captured_names)

    def test_tashuo_mac_ios_app_send_message_rejects_fuzzy_header_ocr_binding(self):
        runner = FakeRunner(
            ocr_text=[
                "仿生人会爱上锅包肉吗\nhey\n点击此处输入文字\n",
                "< Q) 仿生人会受上锅包内吗。\nhey\n点击此处输入文字\n",
                "仿生人会爱上锅包肉吗\nhey\n点击此处输入文字\n",
                "仿生人会爱上锅包肉吗\nhey\n你好\n发送\n",
                "仿生人会爱上锅包肉吗\nhey\n你好\n点击此处输入文字\n",
            ],
            window_name="她说",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(
            "你好",
            dry_run=False,
            target_binding={
                "required_visible_text": ["仿生人会爱上锅包肉吗"],
                "target_match_id": "match_tashuo",
            },
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "target_binding_structural_evidence_required")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_tashuo_mac_ios_app_send_message_accepts_current_thread_visual_identity_without_row_index_or_header_ocr(self):
        conversation_png = _tashuo_mac_ios_app_conversation_with_messages_png()
        visual_region = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.84}
        visual_hash = _png_average_hash(conversation_png, region=visual_region)
        runner = FakeRunner(
            ocr_text=[
                "小药丸儿\n我也比较慢热\n点击此处输入文字\n",
                "另一个人\n别的消息\n点击此处输入文字\n",
                "小药丸儿\n我也比较慢热\n点击此处输入文字\n",
                "小药丸儿\n我也比较慢热\n那我们俩算慢热同盟了\n",
                "小药丸儿\n我也比较慢热\n那我们俩算慢热同盟了\n点击此处输入文字\n",
            ],
            screenshot_bytes=[
                conversation_png,
                conversation_png,
                conversation_png,
                conversation_png,
                conversation_png,
            ],
            window_name="她说",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(
            "那我们俩算慢热同盟了",
            dry_run=False,
            target_binding={
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_xiaoyaowan",
                "candidate_key": "xiaoyaowan_current_thread",
                "visible_name": "小药丸儿",
                "conversation_fingerprint": "xiaoyaowan-slow-warm-20260611",
                "thread_evidence": {
                    "observation_id": "obs_xiaoyaowan_current_thread",
                    "screen_state": "tashuo_conversation",
                    "latest_inbound_fingerprint": "xiaoyaowan:in:slow-warm",
                    "visual_anchor_hash": visual_hash,
                    "visual_anchor_region": visual_region,
                },
            },
        )

        self.assertEqual(payload["status"], "needs_host_visual_verification")
        self.assertEqual(payload["reason"], "staged_text_requires_visual_verification")
        self.assertEqual(payload["target_binding_verification"]["status"], "ok")
        self.assertEqual(
            payload["target_binding_verification"]["verification_method"],
            "tashuo_current_thread_visual_identity",
        )
        self.assertFalse(payload["staged_text_verified"])
        self.assertEqual(payload["visual_verification_request"]["verification_type"], "staged_text_visual")
        self.assertEqual(payload["target_binding_verification"]["visual_anchor_hamming_distance"], 0)
        self.assertNotIn("matched_marker_hashes", payload["target_binding_verification"])

    def test_tashuo_mac_ios_app_send_message_relocates_current_thread_visual_identity_mismatch_before_staging(self):
        wrong_conversation_png = _tashuo_mac_ios_app_conversation_with_title_chrome_png()
        target_conversation_png = _tashuo_mac_ios_app_conversation_with_messages_png(accent=(92, 168, 126, 255))
        old_list_png = _tashuo_mac_ios_app_message_list_with_target_row_png(target_center_y=0.34)
        current_list_png = _tashuo_mac_ios_app_message_list_with_target_row_png(target_center_y=0.62)
        visual_region = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.84}
        target_visual_hash = _png_average_hash(target_conversation_png, region=visual_region)
        row_region = {"x1": 0.05, "y1": 0.29, "x2": 0.95, "y2": 0.39}
        row_visual_hash = _png_average_hash(old_list_png, region=row_region)
        draft = "那我们俩算慢热同盟了"
        runner = FakeRunner(
            ocr_text=[
                "小药丸儿\n我也比较慢热\n点击此处输入文字\n",
                "别的人\n刚发来的消息\n点击此处输入文字\n",
                "别的人\n刚发来的消息\n点击此处输入文字\n",
                "消息\n全部消息\n小药丸儿\n我也比较慢热\n推荐\n飞行\n消息\n我的\n",
                "小药丸儿\n我也比较慢热\n点击此处输入文字\n",
                "小药丸儿\n我也比较慢热\n点击此处输入文字\n",
                f"小药丸儿\n我也比较慢热\n{draft}\n点击此处输入文字\n",
                f"小药丸儿\n我也比较慢热\n{draft}\n点击此处输入文字\n",
            ],
            screenshot_bytes=[
                wrong_conversation_png,
                wrong_conversation_png,
                wrong_conversation_png,
                current_list_png,
                target_conversation_png,
                target_conversation_png,
                target_conversation_png,
                target_conversation_png,
            ],
            window_name="她说",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(
            draft,
            dry_run=False,
            target_binding={
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_xiaoyaowan",
                "candidate_key": "xiaoyaowan_current_thread",
                "visible_name": "小药丸儿",
                "conversation_fingerprint": "xiaoyaowan-slow-warm-20260611",
                "thread_evidence": {
                    "observation_id": "obs_xiaoyaowan_current_thread",
                    "screen_state": "tashuo_conversation",
                    "latest_inbound_fingerprint": "xiaoyaowan:in:slow-warm",
                    "visual_anchor_hash": target_visual_hash,
                    "visual_anchor_region": visual_region,
                    "visual_anchor_max_hamming_distance": 0,
                },
                "message_list_evidence": {
                    "source_state": "tashuo_chat_list",
                    "selection_method": "message_list_visual_anchor_scan",
                    "visual_anchor_hash": row_visual_hash,
                    "visual_anchor_region": row_region,
                    "visual_anchor_scan_region": {"x1": 0.0, "y1": 0.18, "x2": 1.0, "y2": 0.84},
                    "tap_ratio": {"x": 0.45, "y": 0.34},
                },
            },
        )

        self.assertEqual(payload["status"], "needs_host_visual_verification")
        self.assertEqual(payload["reason"], "staged_text_requires_visual_verification")
        self.assertEqual(payload["target_binding_relocation"]["status"], "ok")
        self.assertEqual(payload["target_binding_relocation"]["attempt_count"], 1)
        self.assertEqual(payload["target_binding_verification"]["status"], "ok")
        self.assertEqual(payload["target_binding_verification"]["recovered_by"], "message_list_visual_relocation")
        location = payload["target_binding_relocation"]["attempts"][0]["message_list_location"]
        self.assertEqual(location["location_method"], "message_list_visual_anchor_scan")
        self.assertAlmostEqual(location["tap_ratio"]["y"], 0.62, delta=0.04)
        self.assertFalse(payload["staged_text_verified"])
        self.assertTrue(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_tashuo_mac_ios_app_send_message_blocks_current_thread_visual_identity_mismatch_without_visual_relocation_evidence(self):
        conversation_png = _tashuo_mac_ios_app_conversation_with_messages_png()
        visual_region = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.84}
        runner = FakeRunner(
            ocr_text=[
                "小药丸儿\n我也比较慢热\n点击此处输入文字\n",
                "小药丸儿\n我也比较慢热\n点击此处输入文字\n",
            ],
            screenshot_bytes=[
                conversation_png,
                conversation_png,
            ],
            window_name="她说",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(
            "那我们俩算慢热同盟了",
            dry_run=False,
            target_binding={
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_xiaoyaowan",
                "candidate_key": "xiaoyaowan_current_thread",
                "conversation_fingerprint": "xiaoyaowan-slow-warm-20260611",
                "thread_evidence": {
                    "observation_id": "obs_xiaoyaowan_current_thread",
                    "screen_state": "tashuo_conversation",
                    "latest_inbound_fingerprint": "xiaoyaowan:in:slow-warm",
                    "visual_anchor_hash": "0000000000000000",
                    "visual_anchor_region": visual_region,
                },
            },
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "target_relocation_visual_evidence_required")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_tashuo_mac_ios_app_send_message_retries_visual_relocation_before_exhausting(self):
        wrong_conversation_png = _tashuo_mac_ios_app_conversation_with_title_chrome_png()
        target_conversation_png = _tashuo_mac_ios_app_conversation_with_messages_png(accent=(92, 168, 126, 255))
        list_png = _tashuo_mac_ios_app_message_list_with_target_row_png(target_center_y=0.62)
        visual_region = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.84}
        target_visual_hash = _png_average_hash(target_conversation_png, region=visual_region)
        row_region = {"x1": 0.05, "y1": 0.29, "x2": 0.95, "y2": 0.39}
        runner = FakeRunner(
            ocr_text=[
                "小药丸儿\n我也比较慢热\n点击此处输入文字\n",
                "别的人\n刚发来的消息\n点击此处输入文字\n",
                "别的人\n刚发来的消息\n点击此处输入文字\n",
                "消息\n全部消息\n其他人\n刚发来的消息\n推荐\n飞行\n消息\n我的\n",
                "消息\n全部消息\n其他人\n刚发来的消息\n推荐\n飞行\n消息\n我的\n",
                "消息\n全部消息\n其他人\n刚发来的消息\n推荐\n飞行\n消息\n我的\n",
            ],
            screenshot_bytes=[
                wrong_conversation_png,
                wrong_conversation_png,
                wrong_conversation_png,
                list_png,
                list_png,
                list_png,
            ],
            window_name="她说",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(
            "那我们俩算慢热同盟了",
            dry_run=False,
            target_binding={
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_xiaoyaowan",
                "candidate_key": "xiaoyaowan_current_thread",
                "visible_name": "小药丸儿",
                "conversation_fingerprint": "xiaoyaowan-slow-warm-20260611",
                "thread_evidence": {
                    "observation_id": "obs_xiaoyaowan_current_thread",
                    "screen_state": "tashuo_conversation",
                    "latest_inbound_fingerprint": "xiaoyaowan:in:slow-warm",
                    "visual_anchor_hash": target_visual_hash,
                    "visual_anchor_region": visual_region,
                    "visual_anchor_max_hamming_distance": 0,
                },
                "message_list_evidence": {
                    "source_state": "tashuo_chat_list",
                    "selection_method": "message_list_visual_anchor_scan",
                    "visual_anchor_hash": "0000000000000000",
                    "visual_anchor_region": row_region,
                    "visual_anchor_scan_region": {"x1": 0.0, "y1": 0.18, "x2": 1.0, "y2": 0.84},
                    "tap_ratio": {"x": 0.45, "y": 0.34},
                    "visual_anchor_max_hamming_distance": 0,
                },
            },
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "target_binding_visual_relocation_exhausted")
        self.assertEqual(len(payload["target_binding_relocation"]["attempts"]), 3)
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_tashuo_mac_ios_app_send_message_skips_input_crop_ocr_for_staged_text_verification(self):
        draft = "那我们俩算慢热同盟了，我也是刚开始话少一点，熟了会自然很多"
        runner = FakeRunner(
            ocr_text=[
                "小药丸儿\n我也比较慢热\n点击此处输入文字\n",
                "小药丸儿\n我也比较慢热\n点击此处输入文字\n",
                "那我们俩算慢热同盟了，我也是刚开始话少一\nR, RT SERRE\n",
                f"{draft}\n",
                f"小药丸儿\n我也比较慢热\n{draft}\n点击此处输入文字\n",
            ],
            screenshot_bytes=[
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
            ],
            window_name="她说",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(draft, dry_run=False, output_dir=Path(tempfile.mkdtemp()))

        self.assertEqual(payload["status"], "needs_host_visual_verification")
        self.assertEqual(payload["reason"], "staged_text_requires_visual_verification")
        self.assertTrue(payload["staged_text_verification"]["ocr_fallback_skipped"])
        self.assertEqual(
            payload["staged_text_verification"]["ocr_fallback_skip_reason"],
            "mac_ios_app_visual_first_after_message_page",
        )
        self.assertFalse(any(command and command[0] == "sips" for command in runner.commands))
        self.assertFalse(any("key code 36" in " ".join(command) for command in runner.commands))

    def test_tashuo_mac_ios_app_send_message_accepts_ax_exact_staged_text_verification(self):
        draft = "你好啊，接上了"
        runner = FakeRunner(
            ocr_text=[
                "朵朵\n你好啊\n点击此处输入文字\n",
                "朵朵\n你好啊\n点击此处输入文字\n",
                "乱码\n",
                f"朵朵\n你好啊\n{draft}\n点击此处输入文字\n",
            ],
            screenshot_bytes=[
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
            ],
            window_name="她说",
            ax_text_area_value=draft,
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(draft, dry_run=False, output_dir=Path(tempfile.mkdtemp()))

        self.assertEqual(payload["status"], "needs_host_visual_verification")
        self.assertEqual(payload["reason"], "outbound_message_requires_visual_verification")
        self.assertTrue(payload["staged_text_verified"])
        self.assertTrue(payload["staged_text_verification"]["exact_text_ax_verified"])
        self.assertFalse(payload["staged_text_verification"]["exact_text_ocr_verified"])
        self.assertTrue(payload["evidence"]["staged_exact_text_verified"])
        self.assertTrue(payload["evidence"]["staged_exact_text_ax_verified"])
        self.assertEqual(payload["visual_verification_request"]["verification_type"], "outbound_message_visual")
        self.assertEqual(payload["visual_verification_request"]["verification_type"], "outbound_message_visual")

    def test_tashuo_mac_ios_app_send_message_accepts_ax_exact_outbound_text_verification(self):
        draft = "你好啊，接上了"
        runner = FakeRunner(
            ocr_text=[
                "朵朵\n你好啊\n点击此处输入文字\n",
                "朵朵\n你好啊\n点击此处输入文字\n",
                "乱码\n",
                "朵朵\n你好啊\n点击此处输入文字\n",
            ],
            screenshot_bytes=[
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
            ],
            window_name="她说",
            ax_text_area_value=draft,
            ax_static_text_values=["朵朵", "你好啊", draft, "点击此处输入文字"],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(draft, dry_run=False, output_dir=Path(tempfile.mkdtemp()))

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["evidence"]["staged_exact_text_ax_verified"])
        self.assertTrue(payload["evidence"]["outbound_exact_text_verified"])
        self.assertTrue(payload["evidence"]["outbound_exact_text_ax_verified"])
        self.assertFalse(payload["evidence"]["outbound_exact_text_ocr_verified"])
        self.assertEqual(
            payload["outbound_message_verification"]["verification_method"],
            "tashuo_post_send_ax_then_host_visual_payload_text",
        )
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_app_send_message_waits_for_outbound_visual_verification_when_ax_is_inconclusive(self):
        draft = "你好啊，接上了"
        runner = FakeRunner(
            ocr_text=[
                "朵朵\n你好啊\n点击此处输入文字\n",
                "朵朵\n你好啊\n点击此处输入文字\n",
                "乱码\n",
                "乱码\n",
                "OCR没有读到新气泡\n",
            ],
            screenshot_bytes=[
                _tashuo_mac_ios_app_conversation_with_messages_png(outgoing_bubble=False),
                _tashuo_mac_ios_app_conversation_with_messages_png(outgoing_bubble=False),
                _tashuo_mac_ios_app_conversation_with_messages_png(outgoing_bubble=False),
                _tashuo_mac_ios_app_conversation_with_messages_png(outgoing_bubble=False),
                _tashuo_mac_ios_app_conversation_with_messages_png(outgoing_bubble=True),
            ],
            window_name="她说",
            ax_text_area_value="",
            ax_static_text_values=[],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(draft, dry_run=False, output_dir=Path(tempfile.mkdtemp()))

        self.assertEqual(payload["status"], "needs_host_visual_verification")
        self.assertEqual(payload["reason"], "outbound_message_requires_visual_verification")
        self.assertEqual(payload["next_host_action"], "visually_verify_outbound_message_after_live_send")
        self.assertTrue(payload["evidence"]["staged_exact_text_ax_verified"])
        self.assertTrue(payload["evidence"]["input_cleared_after_send"])
        self.assertFalse(payload["evidence"]["outbound_exact_text_ax_verified"])
        self.assertFalse(payload["evidence"]["outbound_exact_text_ocr_verified"])
        self.assertFalse(payload["evidence"]["outbound_exact_text_visual_verified"])
        self.assertFalse(payload["evidence"]["outbound_visual_commit_verified"])
        self.assertFalse(payload["evidence"]["outbound_exact_text_verified"])
        self.assertEqual(payload["visual_verification_request"]["verification_type"], "outbound_message_visual")
        self.assertEqual(payload["visual_verification_request"]["ocr_status"], "skipped")
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_app_send_message_does_not_use_low_saturation_color_as_success(self):
        draft = "你好啊，接上了"
        runner = FakeRunner(
            ocr_text=[
                "海淀大橙子\n哇，那很酷\n点击此处输入文字\n",
                "海淀大橙子\n哇，那很酷\n点击此处输入文字\n",
                "乱码\n",
                "乱码\n",
                "OCR没有读到新气泡\n",
            ],
            screenshot_bytes=[
                _tashuo_mac_ios_app_conversation_with_messages_png(outgoing_bubble=False),
                _tashuo_mac_ios_app_conversation_with_messages_png(outgoing_bubble=False),
                _tashuo_mac_ios_app_conversation_with_messages_png(outgoing_bubble=False),
                _tashuo_mac_ios_app_conversation_with_messages_png(outgoing_bubble=False),
                _tashuo_mac_ios_app_conversation_with_messages_png(
                    outgoing_bubble=True,
                    outgoing_color=(205, 242, 255, 255),
                ),
            ],
            window_name="她说",
            ax_text_area_value="",
            ax_static_text_values=[],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(draft, dry_run=False, output_dir=Path(tempfile.mkdtemp()))

        self.assertEqual(payload["status"], "needs_host_visual_verification")
        self.assertEqual(payload["reason"], "outbound_message_requires_visual_verification")
        self.assertTrue(payload["evidence"]["staged_exact_text_ax_verified"])
        self.assertTrue(payload["evidence"]["input_cleared_after_send"])
        self.assertFalse(payload["evidence"]["outbound_exact_text_visual_verified"])
        self.assertFalse(payload["evidence"]["outbound_visual_commit_verified"])
        self.assertFalse(payload["evidence"]["outbound_exact_text_verified"])
        self.assertEqual(payload["visual_verification_request"]["ocr_status"], "skipped")
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_app_send_message_waits_for_host_visual_verification_without_post_send_delta(self):
        draft = "你好啊，接上了"
        unchanged = _tashuo_mac_ios_app_conversation_with_messages_png(outgoing_bubble=False)
        runner = FakeRunner(
            ocr_text=[
                "朵朵\n你好啊\n点击此处输入文字\n",
                "朵朵\n你好啊\n点击此处输入文字\n",
                "乱码\n",
                "乱码\n",
                "OCR没有读到新气泡\n",
            ],
            screenshot_bytes=[unchanged, unchanged, unchanged, unchanged, unchanged],
            window_name="她说",
            ax_text_area_value="",
            ax_static_text_values=[],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(draft, dry_run=False, output_dir=Path(tempfile.mkdtemp()))

        self.assertEqual(payload["status"], "needs_host_visual_verification")
        self.assertEqual(payload["reason"], "outbound_message_requires_visual_verification")
        self.assertFalse(payload["evidence"]["outbound_exact_text_visual_verified"])
        self.assertFalse(payload["evidence"]["outbound_visual_commit_verified"])
        self.assertEqual(payload["visual_verification_request"]["ocr_status"], "skipped")
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_app_send_message_is_idempotent_when_text_already_sent(self):
        draft = "你好啊，接上了"
        runner = FakeRunner(
            ocr_text=[
                "朵朵\n你好啊\n点击此处输入文字\n",
                "朵朵\n你好啊\n点击此处输入文字\n",
            ],
            screenshot_bytes=[
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
            ],
            window_name="她说",
            ax_text_area_value="",
            ax_static_text_values=["朵朵", "你好啊", draft, "点击此处输入文字"],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(draft, dry_run=False, output_dir=Path(tempfile.mkdtemp()))

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["already_sent"])
        self.assertTrue(payload["evidence"]["outbound_exact_text_verified"])
        self.assertTrue(payload["evidence"]["outbound_exact_text_ax_verified"])
        self.assertTrue(payload["evidence"]["input_cleared_after_send"])
        self.assertEqual(payload["current_thread_visual_anchor"]["status"], "ok")
        self.assertEqual(payload["current_thread_visual_anchor"]["screen_state"], "tashuo_conversation")
        self.assertIn("visual_anchor_hash", payload["current_thread_visual_anchor"])
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))
        self.assertFalse(any("keystroke \"v\"" in " ".join(command) for command in runner.commands))
        self.assertFalse(any("key code 36" in " ".join(command) for command in runner.commands))

    def test_tashuo_mac_ios_app_send_message_falls_back_to_ax_set_when_paste_does_not_stage(self):
        draft = "看你是做运营的，我有点好奇"
        baseline = "朵朵\n你好啊\n你好啊，接上了\n点击此处输入文字\n"
        runner = FakeRunner(
            ocr_text=[
                baseline,
                baseline,
                baseline,
                "点击此处输入文字\n",
                f"朵朵\n你好啊\n你好啊，接上了\n{draft}\n点击此处输入文字\n",
                f"朵朵\n你好啊\n你好啊，接上了\n{draft}\n点击此处输入文字\n",
            ],
            screenshot_bytes=_tashuo_mac_ios_app_conversation_with_messages_png(),
            window_name="她说",
            paste_focus_override="没有成功写入草稿",
            ax_text_area_value="",
            ax_static_text_values=[],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(draft, dry_run=False, output_dir=Path(tempfile.mkdtemp()))

        self.assertEqual(payload["status"], "needs_host_visual_verification")
        self.assertEqual(payload["reason"], "outbound_message_requires_visual_verification")
        self.assertEqual(payload["ax_set_text_area_result"]["status"], "ok")
        self.assertEqual(payload["ax_set_text_verification"]["status"], "ok")
        self.assertTrue(payload["evidence"]["staged_exact_text_verified"])
        self.assertTrue(payload["evidence"]["staged_exact_text_ax_verified"])
        self.assertFalse(payload["evidence"]["outbound_exact_text_verified"])
        self.assertEqual(payload["visual_verification_request"]["verification_type"], "outbound_message_visual")
        self.assertTrue(any("DATING_BOOST_AX_SET_TEXT_AREA_VALUE" in " ".join(command) for command in runner.commands))
        self.assertIn(
            "focus_tashuo_message_input_after_accessibility_set",
            [step["intent"] for step in payload["executed_steps"]],
        )
        self.assertTrue(any("key code 36" in " ".join(command) for command in runner.commands))

    def test_tashuo_mac_ios_app_send_message_waits_for_host_visual_verification_when_text_ocr_is_inconclusive(self):
        draft = "那我们俩算慢热同盟了，我也是刚开始话少一点，熟了会自然很多"
        runner = FakeRunner(
            ocr_text=[
                "小药丸儿\n我也比较慢热\n点击此处输入文字\n",
                "小药丸儿\n我也比较慢热\n点击此处输入文字\n",
                "小药丸儿\n我也比较慢热\n乱码\n",
                "乱码\n",
            ],
            screenshot_bytes=[
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
                _tashuo_mac_ios_app_conversation_with_messages_png(),
            ],
            window_name="她说",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.send_message(draft, dry_run=False, output_dir=Path(tempfile.mkdtemp()))

        self.assertEqual(payload["status"], "needs_host_visual_verification")
        self.assertEqual(payload["reason"], "staged_text_requires_visual_verification")
        self.assertEqual(payload["next_host_action"], "visually_verify_staged_text_before_live_send")
        self.assertFalse(payload["staged_text_verified"])
        self.assertEqual(payload["visual_verification_request"]["expected_payload_hash"], payload["draft_fingerprint"])
        self.assertNotIn("expected_text", payload["visual_verification_request"])
        self.assertFalse(any("key code 36" in " ".join(command) for command in runner.commands))
        self.assertNotIn("failed_stage_cleanup", payload)

    def test_tashuo_mac_ios_app_stage_draft_executes_without_return_key_and_restores_clipboard(self):
        runner = FakeRunner(
            ocr_text=[
                "Yasmine\n你好\n点击此处输入文字\n发送\n",
                "Yasmine\n你好\n点击此处输入文字\n发送\n",
                "Yasmine\n你好\n今晚聊得挺舒服的。\n发送\n",
                "Yasmine\n你好\n今晚聊得挺舒服的。\n发送\n",
            ],
            window_name="她说",
            screenshot_bytes=_tashuo_mac_ios_app_conversation_with_messages_png(),
            ax_text_area_value="",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.stage_draft("今晚聊得挺舒服的。", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(payload["stage_attempt_status"], "completed")
        self.assertEqual(payload["staged_text_verification"]["status"], "verified")
        self.assertTrue(payload["staged_text_verified"])
        self.assertEqual(payload["next_host_action"], "verify_staged_text_before_send")
        self.assertTrue(payload["clipboard_restored"])
        self.assertEqual(runner.clipboard_text, "previous clipboard")
        self.assertTrue(any(command and command[0] == "pbcopy" for command in runner.commands))
        self.assertTrue(any(command[:2] == ["xcrun", "swift"] for command in runner.commands))
        self.assertFalse(any("key code 36" in " ".join(command) for command in runner.commands))
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_app_stage_draft_uses_ax_set_when_paste_does_not_stage(self):
        runner = FakeRunner(
            ocr_text=[
                "Yasmine\n你好\n点击此处输入文字\n发送\n",
                "Yasmine\n你好\n点击此处输入文字\n发送\n",
                "Yasmine\n你好\n点击此处输入文字\n发送\n",
                "Yasmine\n你好\n点击此处输入文字\n发送\n",
                "Yasmine\n你好\n点击此处输入文字\n发送\n",
            ],
            window_name="她说",
            screenshot_bytes=_tashuo_mac_ios_app_conversation_with_messages_png(),
            ax_text_area_value="",
            paste_focus_override="",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.stage_draft("今晚聊得挺舒服的。", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["ax_set_text_area_result"]["status"], "ok")
        self.assertEqual(payload["staging_input_backend"], "macos_accessibility")
        self.assertEqual(payload["staged_text_verification"]["status"], "verified")
        self.assertTrue(payload["staged_text_verified"])
        self.assertEqual(runner.ax_text_area_value, "今晚聊得挺舒服的。")
        self.assertTrue(
            any(
                command and command[0] == "osascript" and any("DATING_BOOST_AX_SET_TEXT_AREA_VALUE" in item for item in command)
                for command in runner.commands
            )
        )
        self.assertFalse(any("key code 36" in " ".join(command) for command in runner.commands))

    def test_tashuo_mac_ios_app_stage_draft_reactivates_before_click_when_focus_moves(self):
        class FocusMovesBeforeClickRunner(FakeRunner):
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
                    if self.active_probe_calls == 2:
                        return _result(
                            stdout=(
                                "front\tCodex\tcom.openai.codex\n"
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

        runner = FocusMovesBeforeClickRunner(
            ocr_text=[
                "Yasmine\n你好\n点击此处输入文字\n发送\n",
                "Yasmine\n你好\n点击此处输入文字\n发送\n",
                "Yasmine\n你好\n今晚聊得挺舒服的。\n发送\n",
                "Yasmine\n你好\n今晚聊得挺舒服的。\n发送\n",
            ],
            window_name="她说",
            screenshot_bytes=_tashuo_mac_ios_app_conversation_with_messages_png(),
            ax_text_area_value="",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.stage_draft("今晚聊得挺舒服的。", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["staged_text_verified"])
        self.assertGreaterEqual(runner.active_probe_calls, 4)
        self.assertGreaterEqual(sum(1 for command in runner.commands if command[:2] == ["open", "-b"]), 2)
        self.assertFalse(any("key code 36" in " ".join(command) for command in runner.commands))

    def test_tashuo_mac_ios_app_stage_draft_clears_existing_input_before_paste(self):
        runner = FakeRunner(
            ocr_text=[
                "Yasmine\n你好\n旧草稿\n发送\n",
                "Yasmine\n你好\n旧草稿\n发送\n",
                "Yasmine\n你好\n今晚聊得挺舒服的。\n发送\n",
                "Yasmine\n你好\n今晚聊得挺舒服的。\n发送\n",
            ],
            window_name="她说",
            screenshot_bytes=_tashuo_mac_ios_app_conversation_with_messages_png(),
            ax_text_area_value="旧草稿",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.stage_draft("今晚聊得挺舒服的。", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["pre_stage_clear_result"]["status"], "ok")
        self.assertEqual(payload["staged_text_verification"]["status"], "verified")
        self.assertTrue(payload["staged_text_verified"])
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))
        clear_index = next(
            index
            for index, command in enumerate(runner.commands)
            if command and command[0] == "osascript" and any("DATING_BOOST_AX_CLEAR_TEXT_AREA" in item for item in command)
        )
        copy_index = next(
            index
            for index, command in enumerate(runner.commands)
            if command and command[0] == "pbcopy"
        )
        self.assertLess(clear_index, copy_index)

    def test_tashuo_mac_ios_app_clear_message_input_verifies_empty_without_send(self):
        runner = FakeRunner(
            ocr_text="Yasmine\n你好\n旧草稿\n发送\n",
            window_name="她说",
            screenshot_bytes=_tashuo_mac_ios_app_conversation_with_messages_png(),
            ax_text_area_value="旧草稿",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = harness.run_action("clear-message-input", dry_run=False, output_dir=Path(temp_dir))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["action"], "clear-message-input")
        self.assertTrue(payload["input_cleared"])
        self.assertEqual(payload["final_input_character_count"], 0)
        self.assertEqual(payload["final_input_verification"]["status"], "ok")
        self.assertEqual(payload["final_input_verification"]["final_input_character_count"], 0)
        self.assertFalse(payload["send_action_executed"])
        self.assertEqual(runner.ax_text_area_value, "")
        self.assertTrue(
            any(
                command and command[0] == "osascript" and any("DATING_BOOST_AX_CLEAR_TEXT_AREA" in item for item in command)
                for command in runner.commands
            )
        )
        self.assertFalse(any("key code 36" in " ".join(command) for command in runner.commands))

    def test_tashuo_mac_ios_app_stage_draft_duplicate_append_needs_user_verification(self):
        runner = FakeRunner(
            ocr_text=[
                "Yasmine\n你好\n今晚聊得挺舒服的。\n发送\n",
                "Yasmine\n你好\n今晚聊得挺舒服的。\n发送\n",
                "Yasmine\n你好\n今晚聊得挺舒服的。\n今晚聊得挺舒服的。\n发送\n",
                "Yasmine\n你好\n今晚聊得挺舒服的。\n今晚聊得挺舒服的。\n发送\n",
            ],
            window_name="她说",
            screenshot_bytes=_tashuo_mac_ios_app_conversation_with_messages_png(),
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.stage_draft("今晚聊得挺舒服的。", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["pre_stage_clear_result"]["status"], "blocked")
        self.assertEqual(payload["staged_text_verification"]["status"], "needs_user_verification")
        self.assertEqual(payload["staged_text_verification"]["reason"], "staged_text_not_verified")
        self.assertFalse(payload["staged_text_verified"])
        self.assertFalse(payload["staged_text_verification"]["possible_append_to_existing_staged_text"])
        self.assertTrue(payload["staged_text_verification"]["ocr_disabled_after_message_page"])
        self.assertFalse(any(command and command[0] == "tesseract" for command in runner.commands))

    def test_tashuo_mac_ios_app_stage_draft_cjk_ambiguous_ocr_needs_user_verification_not_failed(self):
        runner = FakeRunner(
            ocr_text=[
                "Yasmine\n你好\n点击此处输入文字\n发送\n",
                "Yasmine\n你好\n点击此处输入文字\n发送\n",
                "Yasmine\n你好\n发送\n",
                "Yasmine\n你好\n发送\n",
            ],
            window_name="她说",
            screenshot_bytes=_tashuo_mac_ios_app_conversation_with_messages_png(),
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac_ios_app")

        payload = harness.stage_draft("今晚聊得挺舒服的。", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["stage_attempt_status"], "completed")
        self.assertEqual(payload["staged_text_verification"]["status"], "needs_user_verification")
        self.assertEqual(payload["staged_text_verification"]["reason"], "staged_text_not_verified")
        self.assertFalse(payload["staged_text_verified"])
        self.assertNotEqual(payload["staged_text_verification"]["status"], "failed")

    def test_tashuo_failed_stage_cleanup_uses_ax_text_area_clear(self):
        runner = FakeRunner(
            ocr_text="朵朵\n你好啊\n点击此处输入文字\n",
            screenshot_bytes=_tashuo_mac_ios_app_conversation_with_messages_png(),
            window_name="她说",
            ax_text_area_value="你好啊，接上了",
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner, runtime="mac-ios-app")

        result = tashuo_native._cleanup_failed_tashuo_stage(
            harness.session,
            type("Window", (), {"x": 100, "y": 50, "width": 350, "height": 760})(),
            {"tap_ratio": {"x": 0.32, "y": 0.85}, "focus_state": "focused"},
            expected_text="你好啊，接上了",
            output_dir=Path(tempfile.mkdtemp()),
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["cleanup_backend"], "macos_accessibility")
        self.assertEqual(runner.ax_text_area_value, "")

    def test_tashuo_send_message_blocks_on_question_gate_page_without_user_confirmation_path(self):
        runner = FakeRunner(ocr_text="待回答\n她向你提了一个问题\n回答后即可开启聊天\n点击此处输入文字\n")
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner)

        payload = harness.send_message("这个问题我会认真回答。", dry_run=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "tashuo_question_gate_requires_user_confirmation")

    def test_tashuo_send_message_blocks_generic_target_binding_markers_before_staging(self):
        runner = FakeRunner(
            ocr_text=[
                "Yasmine\n点击此处输入文字\n发送\n",
                "Yasmine\n点击此处输入文字\n发送\n",
                "Yasmine\n点击此处输入文字\n发送\n",
                "Yasmine\nhi\n发送\n",
                "Yasmine\nhi\n点击此处输入文字\n",
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner)

        payload = harness.send_message(
            "hi",
            dry_run=False,
            target_binding={"required_visible_text": ["点击此处输入文字", "发送"], "target_match_id": "match_tashuo"},
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "target_binding_not_target_specific")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_tashuo_send_message_verifies_target_staged_text_and_outbound_bubble(self):
        runner = FakeRunner(
            ocr_text=[
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n今晚可以聊十分钟吗？\n",
                "Yasmine\n不理解\n今晚可以聊十分钟吗？\n点击此处输入文字\n",
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner)

        payload = harness.send_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Yasmine"], "target_match_id": "match_tashuo"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["staged_text_verified"])
        self.assertTrue(payload["evidence"]["staged_text_verified"])
        self.assertTrue(payload["evidence"]["staged_exact_text_ocr_verified"])
        self.assertTrue(payload["evidence"]["input_cleared_after_send"])
        self.assertTrue(payload["evidence"]["outbound_message_verified"])
        self.assertEqual(payload["target_binding_verification"]["status"], "ok")
        intents = [step["intent"] for step in payload["executed_steps"]]
        self.assertIn("press_return_to_send_tashuo_message", intents)
        self.assertNotIn("tap_tashuo_send_button", intents)
        self.assertTrue(any("key code 36" in " ".join(command) for command in runner.commands))

    def test_tashuo_send_message_accepts_chat_list_row_structural_binding_for_emoji_nickname(self):
        runner = FakeRunner(
            ocr_text=[
                "点击此处输入文字\n",
                "点击此处输入文字\n",
                "点击此处输入文字\n",
                "你好\n",
                "你好\n点击此处输入文字\n",
            ],
            screenshot_bytes=[
                _tashuo_conversation_toolbar_png(),
                _tashuo_conversation_toolbar_png(),
                _tashuo_conversation_toolbar_png(),
                _tashuo_conversation_toolbar_png(),
                _tashuo_conversation_toolbar_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner)

        payload = harness.send_message(
            "你好",
            dry_run=False,
            target_binding={
                "binding_type": "chat_list_row_to_thread",
                "target_match_id": "match_tashuo_row_5",
                "candidate_key": "tashuo_chat_row_5_emoji",
                "selection_evidence": {
                    "source_state": "tashuo_chat_list",
                    "opened_state": "tashuo_conversation",
                    "row_index": 5,
                    "target_scope": "ordinary_conversation",
                    "open_action": "open-conversation",
                },
            },
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target_binding_verification"]["status"], "ok")
        self.assertEqual(
            payload["target_binding_verification"]["verification_method"],
            "tashuo_chat_list_row_to_thread_structural_binding",
        )
        self.assertTrue(payload["target_binding_verification"]["emoji_nickname_supported"])
        self.assertFalse(payload["target_binding_verification"]["requires_header_marker"])
        self.assertTrue(payload["staged_text_verified"])

    def test_tashuo_send_message_blocks_structural_binding_for_non_conversation_target(self):
        runner = FakeRunner(
            ocr_text=[
                "点击此处输入文字\n",
                "点击此处输入文字\n",
                "点击此处输入文字\n",
            ],
            screenshot_bytes=[
                _tashuo_conversation_toolbar_png(),
                _tashuo_conversation_toolbar_png(),
                _tashuo_conversation_toolbar_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner)

        payload = harness.send_message(
            "你好",
            dry_run=False,
            target_binding={
                "binding_type": "chat_list_row_to_thread",
                "target_match_id": "match_tashuo_row_5",
                "candidate_key": "tashuo_chat_row_5_emoji",
                "selection_evidence": {
                    "source_state": "tashuo_chat_list",
                    "opened_state": "tashuo_question_gate",
                    "row_index": 5,
                    "target_scope": "question_gate",
                    "open_action": "open-conversation",
                },
            },
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "target_binding_opened_state_mismatch")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_tashuo_send_message_blocks_when_target_marker_is_not_in_thread_header(self):
        runner = FakeRunner(
            ocr_text=[
                "Ada\n不理解\nYasmine 昨天说过\n点击此处输入文字\n",
                "Ada\n不理解\nYasmine 昨天说过\n点击此处输入文字\n",
                "Ada\n不理解\nYasmine 昨天说过\n点击此处输入文字\n",
                "Ada\n不理解\nYasmine 昨天说过\nhi\n发送\n",
                "Ada\n不理解\nYasmine 昨天说过\nhi\n点击此处输入文字\n",
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner)

        payload = harness.send_message(
            "hi",
            dry_run=False,
            target_binding={"required_visible_text": ["Yasmine"], "target_match_id": "match_tashuo"},
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "target_binding_header_mismatch")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_tashuo_send_message_blocks_cjk_direct_type_fallback(self):
        runner = FakeRunner(
            ocr_text=[
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n点击此处输入文字\n发送\n",
                "Yasmine\n不理解\n你好\n发送\n",
                "Yasmine\n不理解\n你好\n点击此处输入文字\n",
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner)

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

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "cjk_direct_type_not_supported")
        intents = [step["intent"] for step in payload["executed_steps"]]
        self.assertNotIn("type_tashuo_message_input_if_paste_did_not_stage", intents)
        self.assertNotIn("commit_tashuo_message_input_ime_candidate_if_needed", intents)
        self.assertNotIn("tap_tashuo_send_button", intents)
        self.assertNotIn("press_return_to_send_tashuo_message", intents)

    def test_tashuo_send_message_cleans_failed_paste_without_sending(self):
        runner = FakeRunner(
            ocr_text=[
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\n点击此处输入文字\n",
                "Yasmine\n不理解\nv\n发送\n",
                "Yasmine\n不理解\n点击此处输入文字\n",
            ],
            screenshot_bytes=[
                _tashuo_conversation_toolbar_png(),
                _tashuo_conversation_toolbar_png(),
                _tashuo_conversation_toolbar_png(),
                _tashuo_conversation_toolbar_png(),
                _tashuo_conversation_toolbar_png(),
            ],
        )
        harness = create_adapter(app_id="tashuo", platform="darwin", runner=runner)

        payload = harness.send_message(
            "你好",
            dry_run=False,
            target_binding={"required_visible_text": ["Yasmine"], "target_match_id": "match_tashuo"},
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "staged_text_not_verified")
        self.assertEqual(payload["failed_stage_cleanup"]["status"], "ok")
        intents = [step["intent"] for step in payload["executed_steps"]]
        self.assertNotIn("type_tashuo_message_input_if_paste_did_not_stage", intents)
        self.assertNotIn("tap_tashuo_send_button", intents)
        self.assertNotIn("press_return_to_send_tashuo_message", intents)
        joined_commands = [" ".join(command) for command in runner.commands]
        self.assertTrue(any("key code 53" in command for command in joined_commands))
        self.assertTrue(any("ASCII character 8" in command for command in joined_commands))

    def test_cli_passes_explicit_runtime_to_tashuo_stage_draft(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _select_runtime_scope(data_dir, "tashuo", "mac-ios-app")
            draft_path = Path(temp_dir) / "draft.txt"
            draft_path.write_text("今晚聊得挺舒服的。", encoding="utf-8")
            with _patch_cli_adapter() as harness_class:
                harness_class.return_value.stage_tashuo_draft.return_value = {
                    "schema_version": 2,
                    "status": "ok",
                    "app_id": "tashuo",
                    "harness_backend": "mac_ios_app",
                    "action": "stage_draft",
                }

                exit_code, payload = _run_cli_json([
                    "harness",
                    "tashuo",
                    "stage-draft",
                    "--data-dir",
                    str(data_dir),
                    "--runtime",
                    "mac-ios-app",
                    "--text-file",
                    str(draft_path),
                    "--dry-run",
                    "--json",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertEqual(harness_class.call_args.kwargs["runtime"], "mac-ios-app")
        harness_class.return_value.stage_tashuo_draft.assert_called_once()

    def test_cli_passes_explicit_runtime_to_tashuo_send_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _select_runtime_scope(data_dir, "tashuo", "mac-ios-app")
            draft_path = Path(temp_dir) / "draft.txt"
            draft_path.write_text("今晚聊得挺舒服的。", encoding="utf-8")
            with _patch_cli_adapter() as harness_class:
                harness_class.return_value.send_tashuo_message.return_value = {
                    "schema_version": 2,
                    "status": "ok",
                    "app_id": "tashuo",
                    "harness_backend": "mac_ios_app",
                    "action": "send_message",
                    "live_send": True,
                    "requires_explicit_authorization": True,
                }

                exit_code, payload = _run_cli_json([
                    "harness",
                    "tashuo",
                    "send-message",
                    "--data-dir",
                    str(data_dir),
                    "--runtime",
                    "mac-ios-app",
                    "--text-file",
                    str(draft_path),
                    "--dry-run",
                    "--json",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["harness_backend"], "mac_ios_app")
        self.assertTrue(payload["live_send"])
        self.assertEqual(harness_class.call_args.kwargs["runtime"], "mac-ios-app")
        harness_class.return_value.send_tashuo_message.assert_called_once()

    def test_cli_tashuo_real_send_blocks_structural_binding_without_row_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            draft_text = "你好"
            payload_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
            draft_path = root / "tashuo-draft.txt"
            auth_path = root / "auth.json"
            action_path = root / "action_request.json"
            draft_path.write_text(draft_text, encoding="utf-8")
            _write_json(auth_path, _live_send_auth("tashuo", authorization_id="auth_tashuo_live"))
            _write_json(action_path, {
                "schema_version": 1,
                "action_request_id": "act_tashuo_send",
                "action": "send_message",
                "app_id": "tashuo",
                "match_id": "match_tashuo_row_5",
                "candidate_key": "tashuo_chat_row_5_emoji",
                "payload_hash": payload_hash,
                "precondition_hash": "pre_hash",
                "autonomous_audit_binding": _autonomous_audit_binding(
                    authorization_id="auth_tashuo_live",
                    target_match_id="match_tashuo_row_5",
                    payload_hash=payload_hash,
                ),
                "requires_post_action_verification": True,
                "draft_review_id": "draft_review_fixture",
                "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                "target_binding": {
                    "binding_type": "chat_list_row_to_thread",
                    "target_match_id": "match_tashuo_row_5",
                    "candidate_key": "tashuo_chat_row_5_emoji",
                    "selection_evidence": {
                        "source_state": "tashuo_chat_list",
                        "opened_state": "tashuo_conversation",
                        "target_scope": "ordinary_conversation",
                        "open_action": "open-conversation",
                    },
                },
            })

            with _patch_cli_adapter() as harness_class:
                exit_code, payload = _run_cli_json([
                    "harness",
                    "tashuo",
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

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["reason"], "action_request_target_binding_required")
        harness_class.assert_not_called()
