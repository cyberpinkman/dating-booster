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


class GuiHarnessWechatTests(GuiHarnessTestCase):
    def test_classifies_macos_wechat_chat_screen(self):
        state = classify_wechat_screen_text("微信\nAda\n昨天 21:14\n在吗\n发送")

        self.assertEqual(state, "wechat_chat")

    def test_wechat_classifier_does_not_treat_send_word_alone_as_chat_input(self):
        state = classify_wechat_screen_text("微信\n通讯录\n群聊\n发送给朋友\n")

        self.assertEqual(state, "wechat_chat_list")

    def test_wechat_observe_uses_macos_window_and_redacts_raw_text(self):
        runner = FakeRunner(
            ocr_text="微信\nAda\n昨天 21:14\n今晚有空吗\n发送\n",
            window_name="WeChat",
        )
        harness = create_adapter(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

        payload = harness.observe_wechat_screen()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["app_id"], "wechat")
        self.assertEqual(payload["harness_backend"], "macos_wechat_desktop")
        self.assertEqual(payload["screen_state"], "wechat_chat")
        self.assertEqual(payload["layout_hints"]["page"], "conversation")
        self.assertTrue(payload["layout_hints"]["message_input_marker_present"])
        self.assertIn("text_fingerprint", payload["screen"])
        self.assertNotIn("今晚有空吗", json.dumps(payload, ensure_ascii=False))

    def test_wechat_stage_draft_dry_run_redacts_text_and_never_sends(self):
        runner = FakeRunner(ocr_text="微信\nAda\n发送\n", window_name="WeChat")
        harness = create_adapter(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

        payload = harness.stage_wechat_draft("今晚可以聊十分钟吗？", dry_run=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["action"], "stage_draft")
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["blocked_actions"], ["send", "payments", "calls", "contact_exchange_without_user"])
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            ["copy_draft_to_clipboard", "paste_clipboard_into_wechat_input"],
        )
        self.assertIn("draft_fingerprint", payload)
        self.assertEqual(payload["draft_character_count"], len("今晚可以聊十分钟吗？"))
        self.assertNotIn("今晚可以聊十分钟吗", json.dumps(payload, ensure_ascii=False))
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))
        self.assertFalse(any("key code 36" in " ".join(command) for command in runner.commands))

    def test_wechat_stage_draft_blocks_until_chat_input_is_verified(self):
        runner = FakeRunner(ocr_text="微信\n通讯录\n群聊\n", window_name="WeChat")
        harness = create_adapter(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

        payload = harness.stage_wechat_draft("今晚可以聊十分钟吗？", dry_run=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "wechat_chat_input_not_verified")
        self.assertEqual(payload["screen_state"], "wechat_chat_list")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_wechat_stage_draft_executes_clipboard_paste_without_send_and_requires_verification(self):
        runner = FakeRunner(
            ocr_text=[
                "微信\nAda\n昨天 21:14\n在吗\n发送\n",
                "微信\nAda\n昨天 21:14\n在吗\n发送\n",
            ],
            window_name="WeChat",
        )
        harness = create_adapter(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

        payload = harness.stage_wechat_draft("今晚可以聊十分钟吗？", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["next_host_action"], "verify_staged_text_before_send")
        self.assertEqual([step["intent"] for step in payload["executed_steps"]], [
            "copy_draft_to_clipboard",
            "paste_clipboard_into_wechat_input",
        ])
        self.assertTrue(any(command and command[0] == "pbcopy" for command in runner.commands))
        self.assertTrue(any('keystroke "v"' in " ".join(command) for command in runner.commands))
        self.assertFalse(any("key code 36" in " ".join(command) for command in runner.commands))
        self.assertTrue(payload["clipboard_restored"])
        self.assertEqual(runner.clipboard_text, "previous clipboard")
        self.assertEqual(
            payload["previous_clipboard_fingerprint"],
            hashlib.sha256("previous clipboard".encode("utf-8")).hexdigest(),
        )
        self.assertEqual(payload["previous_clipboard_character_count"], len("previous clipboard"))
        self.assertEqual(payload["draft_clipboard_fingerprint"], payload["draft_fingerprint"])
        pbcopy_inputs = [input_text for command, input_text in runner.command_inputs if command and command[0] == "pbcopy"]
        self.assertEqual(pbcopy_inputs, ["今晚可以聊十分钟吗？", "previous clipboard"])
        self.assertNotIn("previous clipboard", json.dumps(payload, ensure_ascii=False))

    def test_wechat_send_message_dry_run_is_explicit_live_send_plan(self):
        runner = FakeRunner(ocr_text="微信\nAda\n发送\n", window_name="WeChat")
        harness = create_adapter(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

        payload = harness.send_wechat_message("今晚可以聊十分钟吗？", dry_run=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["action"], "send_message")
        self.assertTrue(payload["live_send"])
        self.assertTrue(payload["requires_explicit_authorization"])
        self.assertNotIn("send", payload["blocked_actions"])
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            [
                "stage_draft_with_accessibility_verification",
                "press_return_to_send_wechat_message",
                "verify_input_cleared_and_capture_post_action_screen",
            ],
        )
        self.assertFalse(runner.commands)
        self.assertNotIn("今晚可以聊十分钟吗", json.dumps(payload, ensure_ascii=False))

    def test_wechat_send_message_verifies_staged_text_before_pressing_return(self):
        runner = FakeRunner(
            ocr_text=[
                "微信\nAda\n昨天 21:14\n在吗\n发送\n",
                "微信\nAda\n昨天 21:14\n在吗\n发送\n",
                "微信\nAda\n昨天 21:15\n今晚可以聊十分钟吗？\n发送\n",
            ],
            window_name="WeChat",
        )
        harness = create_adapter(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

        payload = harness.send_wechat_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["stage_status"], "ok")
        self.assertEqual(payload["target_binding_verification"]["status"], "ok")
        self.assertTrue(payload["staged_text_verification"]["expected_payload_hash"])
        self.assertTrue(payload["evidence"]["staged_text_verified"])
        self.assertTrue(payload["evidence"]["input_cleared_after_send"])
        self.assertTrue(payload["evidence"]["post_action_screen_captured"])
        self.assertTrue(payload["evidence"]["outbound_message_verified"])
        self.assertIn("post_action_observation_id", payload)
        self.assertTrue(any("key code 36" in " ".join(command) for command in runner.commands))
        self.assertEqual(runner.clipboard_text, "previous clipboard")
        self.assertEqual(
            payload["previous_clipboard_fingerprint"],
            hashlib.sha256("previous clipboard".encode("utf-8")).hexdigest(),
        )
        self.assertNotIn("今晚可以聊十分钟吗", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("previous clipboard", json.dumps(payload, ensure_ascii=False))

    def test_wechat_send_message_blocks_when_target_binding_mismatches_before_staging(self):
        runner = FakeRunner(
            ocr_text="微信\nZara\n昨天 21:14\n在吗\n发送\n",
            window_name="WeChat",
        )
        harness = create_adapter(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

        payload = harness.send_wechat_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "target_binding_mismatch")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))
        self.assertFalse(any("key code 36" in " ".join(command) for command in runner.commands))

    def test_wechat_send_message_needs_verification_when_outbound_bubble_is_not_seen(self):
        runner = FakeRunner(
            ocr_text=[
                "微信\nAda\n昨天 21:14\n在吗\n发送\n",
                "微信\nAda\n昨天 21:14\n在吗\n发送\n",
                "微信\nAda\n昨天 21:14\n在吗\n发送\n",
                "微信\nAda\n昨天 21:14\n在吗\n发送\n",
            ],
            window_name="WeChat",
        )
        harness = create_adapter(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

        payload = harness.send_wechat_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "needs_verification")
        self.assertEqual(payload["reason"], "outbound_message_not_verified")
        self.assertFalse(payload["evidence"]["outbound_message_verified"])

    def test_wechat_send_message_blocks_when_staged_text_mismatches(self):
        runner = FakeRunner(
            ocr_text=[
                "微信\nAda\n昨天 21:14\n在吗\n发送\n",
                "微信\nAda\n昨天 21:14\n在吗\n发送\n",
            ],
            window_name="WeChat",
            paste_focus_override="错误草稿",
        )
        harness = create_adapter(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

        payload = harness.send_wechat_message("今晚可以聊十分钟吗？", dry_run=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "staged_text_mismatch")
        self.assertFalse(any("key code 36" in " ".join(command) for command in runner.commands))

    def test_wechat_send_message_needs_verification_when_post_screen_capture_fails(self):
        runner = FakeRunner(
            ocr_text=[
                "微信\nAda\n昨天 21:14\n在吗\n发送\n",
                "微信\nAda\n昨天 21:14\n在吗\n发送\n",
            ],
            window_name="WeChat",
            screenshot_fail_at={3},
        )
        harness = create_adapter(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

        payload = harness.send_wechat_message("今晚可以聊十分钟吗？", dry_run=False)

        self.assertEqual(payload["status"], "needs_verification")
        self.assertEqual(payload["reason"], "post_action_screen_not_captured")
        self.assertFalse(payload["evidence"]["post_action_screen_captured"])

    def test_cli_exposes_wechat_observe_stage_draft_and_send_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            draft_path = Path(temp_dir) / "wechat-draft.txt"
            data_dir = Path(temp_dir) / "data"
            draft_path.write_text("今晚可以聊十分钟吗？", encoding="utf-8")
            _select_runtime_scope(data_dir, "wechat")
            with _patch_cli_adapter() as harness_class:
                harness_class.return_value.observe_wechat_screen.return_value = {
                    "schema_version": 1,
                    "status": "ok",
                    "app_id": "wechat",
                    "screen_state": "wechat_chat",
                    "layout_hints": {"page": "conversation"},
                }
                observe_exit, observe_payload = _run_cli_json([
                    "harness",
                    "wechat",
                    "observe",
                    "--data-dir",
                    str(data_dir),
                    "--json",
                ])

                harness_class.return_value.stage_wechat_draft.return_value = {
                    "schema_version": 1,
                    "status": "ok",
                    "app_id": "wechat",
                    "action": "stage_draft",
                    "mode": "dry_run",
                }
                stage_exit, stage_payload = _run_cli_json([
                    "harness",
                    "wechat",
                    "stage-draft",
                    "--text-file",
                    str(draft_path),
                    "--data-dir",
                    str(data_dir),
                    "--dry-run",
                    "--json",
                ])
                harness_class.return_value.send_wechat_message.return_value = {
                    "schema_version": 1,
                    "status": "ok",
                    "app_id": "wechat",
                    "action": "send_message",
                    "mode": "dry_run",
                }
                send_exit, send_payload = _run_cli_json([
                    "harness",
                    "wechat",
                    "send-message",
                    "--text-file",
                    str(draft_path),
                    "--data-dir",
                    str(data_dir),
                    "--dry-run",
                    "--json",
                ])

        self.assertEqual(observe_exit, 0)
        self.assertEqual(observe_payload["layout_hints"]["page"], "conversation")
        self.assertEqual(stage_exit, 0)
        self.assertEqual(stage_payload["action"], "stage_draft")
        self.assertEqual(send_exit, 0)
        self.assertEqual(send_payload["action"], "send_message")
        harness_class.return_value.observe_wechat_screen.assert_called_once()
        harness_class.return_value.stage_wechat_draft.assert_called_once_with(
            "今晚可以聊十分钟吗？",
            dry_run=True,
            output_dir=None,
        )
        harness_class.return_value.send_wechat_message.assert_called_once_with(
            "今晚可以聊十分钟吗？",
            dry_run=True,
            output_dir=None,
            target_binding=None,
        )

    def test_cli_wechat_real_stage_requires_data_dir_and_respects_safety_pause(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            draft_path = root / "wechat-draft.txt"
            data_dir = root / "data"
            draft_path.write_text("今晚可以聊十分钟吗？", encoding="utf-8")
            with _patch_cli_adapter() as harness_class:
                missing_data_exit, missing_data_payload = _run_cli_json([
                    "harness",
                    "wechat",
                    "stage-draft",
                    "--text-file",
                    str(draft_path),
                    "--json",
                ])
                pause_exit, _pause_payload = _run_cli_json([
                    "safety",
                    "pause",
                    "--data-dir",
                    str(data_dir),
                    "--reason",
                    "manual-stop",
                    "--json",
                ])
                paused_exit, paused_payload = _run_cli_json([
                    "harness",
                    "wechat",
                    "stage-draft",
                    "--text-file",
                    str(draft_path),
                    "--data-dir",
                    str(data_dir),
                    "--json",
                ])

        self.assertEqual(missing_data_exit, 2)
        self.assertEqual(missing_data_payload["reason"], "data_dir_required_for_safety_check")
        self.assertEqual(pause_exit, 0)
        self.assertEqual(paused_exit, 2)
        self.assertEqual(paused_payload["reason"], "safety_paused")
        harness_class.assert_not_called()

    def test_cli_wechat_real_send_requires_data_dir_authorization_and_safety_active(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            draft_path = root / "wechat-draft.txt"
            data_dir = root / "data"
            auth_path = root / "auth.json"
            draft_path.write_text("今晚可以聊十分钟吗？", encoding="utf-8")
            auth_path.write_text(json.dumps({
                "schema_version": 1,
                "authorization_id": "auth_wechat_live",
                "scope": "send_chat_messages",
                "app_id": "wechat",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            }), encoding="utf-8")
            with _patch_cli_adapter() as harness_class:
                missing_data_exit, missing_data_payload = _run_cli_json([
                    "harness",
                    "wechat",
                    "send-message",
                    "--text-file",
                    str(draft_path),
                    "--authorization",
                    str(auth_path),
                    "--json",
                ])
                missing_auth_exit, missing_auth_payload = _run_cli_json([
                    "harness",
                    "wechat",
                    "send-message",
                    "--text-file",
                    str(draft_path),
                    "--data-dir",
                    str(data_dir),
                    "--json",
                ])
                missing_action_exit, missing_action_payload = _run_cli_json([
                    "harness",
                    "wechat",
                    "send-message",
                    "--text-file",
                    str(draft_path),
                    "--data-dir",
                    str(data_dir),
                    "--authorization",
                    str(auth_path),
                    "--json",
                ])
                _run_cli_json([
                    "safety",
                    "pause",
                    "--data-dir",
                    str(data_dir),
                    "--reason",
                    "manual-stop",
                    "--json",
                ])
                paused_exit, paused_payload = _run_cli_json([
                    "harness",
                    "wechat",
                    "send-message",
                    "--text-file",
                    str(draft_path),
                    "--data-dir",
                    str(data_dir),
                    "--authorization",
                    str(auth_path),
                    "--json",
                ])

        self.assertEqual(missing_data_exit, 2)
        self.assertEqual(missing_data_payload["reason"], "data_dir_required_for_safety_check")
        self.assertEqual(missing_auth_exit, 2)
        self.assertEqual(missing_auth_payload["reason"], "authorization_required_for_live_send")
        self.assertEqual(missing_action_exit, 2)
        self.assertEqual(missing_action_payload["reason"], "action_request_required_for_live_send")
        self.assertEqual(missing_action_payload["next_host_action"], "use_operator_or_managed_session_work_item")
        self.assertIn("managed_live_send_guidance", missing_action_payload)
        self.assertIn("do_not_handcraft_action_request_json", missing_action_payload["forbidden_actions"])
        self.assertEqual(paused_exit, 2)
        self.assertEqual(paused_payload["reason"], "safety_paused")
        harness_class.assert_not_called()

    def test_cli_wechat_real_send_requires_policy_allowed_action_request(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            draft_path = root / "wechat-draft.txt"
            data_dir = root / "data"
            auth_path = root / "auth.json"
            action_path = root / "action_request.json"
            draft_text = "今晚可以聊十分钟吗？"
            draft_path.write_text(draft_text, encoding="utf-8")
            auth_path.write_text(json.dumps({
                "schema_version": 1,
                "authorization_id": "auth_wechat_live",
                "scope": "send_chat_messages",
                "app_id": "wechat",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            }), encoding="utf-8")
            action_path.write_text(json.dumps({
                "schema_version": 1,
                "action_request_id": "act_wechat_send",
                "action": "send_message",
                "match_id": "match_ada",
                "candidate_key": "wechat_ada",
                "payload_hash": "wrong_hash",
                "requires_post_action_verification": True,
                "draft_review_id": "draft_review_fixture",
                "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                "target_binding": {"required_visible_text": ["Ada"]},
            }), encoding="utf-8")
            with _patch_cli_adapter() as harness_class:
                exit_code, payload = _run_cli_json([
                    "harness",
                    "wechat",
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
        self.assertEqual(payload["reason"], "action_request_payload_hash_mismatch")
        harness_class.assert_not_called()

    def test_cli_wechat_doctor_and_screenshot_default_to_wechat_window_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _select_runtime_scope(data_dir, "wechat")
            output_path = Path(temp_dir) / "wechat.png"
            with _patch_cli_adapter() as harness_class:
                harness_class.return_value.doctor.return_value = {
                    "schema_version": 1,
                    "status": "ok",
                    "app_id": "wechat",
                }
                doctor_exit, _doctor_payload = _run_cli_json([
                    "harness",
                    "doctor",
                    "--app-id",
                    "wechat",
                    "--data-dir",
                    str(data_dir),
                    "--no-capture",
                    "--json",
                ])

                harness_class.return_value.capture_window.return_value = {
                    "schema_version": 1,
                    "status": "ok",
                    "app_id": "wechat",
                }
                screenshot_exit, _screenshot_payload = _run_cli_json([
                    "harness",
                    "screenshot",
                    "--app-id",
                    "wechat",
                    "--data-dir",
                    str(data_dir),
                    "--output",
                    str(output_path),
                    "--json",
                ])

        self.assertEqual(doctor_exit, 0)
        self.assertEqual(screenshot_exit, 0)
        self.assertEqual(harness_class.call_args_list[0].kwargs["window_title"], "WeChat")
        self.assertEqual(harness_class.call_args_list[1].kwargs["window_title"], "WeChat")
