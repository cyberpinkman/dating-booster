from tests.gui_harness_support import *


class GuiHarnessTinderSendTests(GuiHarnessTestCase):
    def test_tinder_send_message_verifies_target_staged_text_and_outbound_bubble(self):
        runner = FakeRunner(
            ocr_text=[
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\n今晚可以聊十分钟吗？\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\n今晚可以聊十分钟吗？\nGIF\n",
            ],
            screenshot_bytes=_tinder_conversation_send_button_png(),
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target_binding_verification"]["status"], "ok")
        self.assertTrue(payload["evidence"]["staged_text_verified"])
        self.assertTrue(payload["evidence"]["post_action_screen_captured"])
        self.assertTrue(payload["evidence"]["input_cleared_after_send"])
        self.assertTrue(payload["evidence"]["outbound_message_verified"])
        self.assertIn("post_action_observation_id", payload)
        self.assertEqual(payload["current_thread_visual_anchor"]["status"], "ok")
        self.assertEqual(payload["current_thread_visual_anchor"]["screen_state"], "tinder_conversation")
        self.assertIn("visual_anchor_hash", payload["current_thread_visual_anchor"])
        self.assertTrue(any(command and command[0] == "pbcopy" for command in runner.commands))
        self.assertTrue(any('keystroke "v"' in " ".join(command) for command in runner.commands))
        self.assertEqual(
            payload["previous_clipboard_fingerprint"],
            hashlib.sha256("previous clipboard".encode("utf-8")).hexdigest(),
        )
        self.assertEqual(payload["previous_clipboard_character_count"], len("previous clipboard"))
        self.assertEqual(payload["draft_clipboard_fingerprint"], payload["draft_fingerprint"])
        self.assertNotIn("今晚可以聊十分钟吗", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("previous clipboard", json.dumps(payload, ensure_ascii=False))

    def test_tinder_stage_draft_executes_without_send_and_records_stage_evidence(self):
        runner = FakeRunner(
            ocr_text=[
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\n今晚可以聊十分钟吗？\nSend\n",
            ],
            screenshot_bytes=_tinder_conversation_send_button_png(),
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.stage_draft("今晚可以聊十分钟吗？", dry_run=False, output_dir=Path(tempfile.mkdtemp()))

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["action"], "stage_draft")
        self.assertEqual(payload["stage_attempt_status"], "completed")
        self.assertTrue(payload["staged_text_verified"])
        self.assertEqual(payload["staged_text_verification"]["status"], "ok")
        self.assertEqual(payload["next_host_action"], "verify_staged_text_before_send")
        self.assertFalse(payload["send_action_executed"])
        self.assertTrue(payload["evidence"]["stage_mode"])
        self.assertFalse(payload["evidence"]["live_send_executed"])
        self.assertFalse(any(step["intent"] == "tap_tinder_send_button" for step in payload["executed_steps"]))

    def test_tinder_stage_draft_blocks_when_input_is_already_occupied_before_clipboard_mutation(self):
        runner = FakeRunner(
            ocr_text=[
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\n未发送草稿\nSend\n",
            ],
            screenshot_bytes=_tinder_conversation_send_button_png(),
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.stage_draft("今晚可以聊十分钟吗？", dry_run=False, output_dir=Path(tempfile.mkdtemp()))

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "message_input_not_empty_before_staging")
        self.assertEqual(payload["next_host_action"], "clear_existing_message_input_before_stage")
        self.assertEqual(payload["pre_stage_input_guard"]["status"], "blocked")
        self.assertTrue(payload["pre_stage_input_guard"]["send_button_visual_visible"])
        self.assertTrue(payload["pre_stage_input_guard"]["send_marker_visible"])
        self.assertFalse(payload["pre_stage_input_guard"]["message_input_placeholder_visible"])
        self.assertFalse(any(command and command[0] == "pbpaste" for command in runner.commands))
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))
        self.assertFalse(any('keystroke "v"' in " ".join(command) for command in runner.commands))

    def test_tinder_stage_draft_relocates_current_thread_visual_identity_mismatch_before_staging(self):
        draft = "今晚可以聊十分钟吗？"
        visual_region = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65}
        target_conversation_png = _tinder_conversation_send_button_png()
        wrong_conversation_png = _bumble_conversation_png(outgoing_bubble=True)
        old_list_png = _iphone_message_list_with_target_row_png(target_center_y=0.42)
        current_list_png = _iphone_message_list_with_target_row_png(target_center_y=0.64)
        row_region = {"x1": 0.05, "y1": 0.37, "x2": 0.95, "y2": 0.47}
        row_visual_hash = _png_average_hash(old_list_png, region=row_region)
        runner = FakeRunner(
            ocr_text=[
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\n新的配对\n消息\nAda\n等你回应\n",
                "Tinder\n新的配对\n消息\nAda\n等你回应\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                f"Tinder\nAda\n昨天 21:14\n在吗\n{draft}\nSend\n",
            ],
            screenshot_bytes=[
                wrong_conversation_png,
                wrong_conversation_png,
                wrong_conversation_png,
                current_list_png,
                current_list_png,
                target_conversation_png,
                target_conversation_png,
                target_conversation_png,
            ],
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.session.send_tinder_message(
            draft,
            dry_run=False,
            output_dir=Path(tempfile.mkdtemp()),
            stage_only=True,
            target_binding={
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_tinder_relocate",
                "candidate_key": "tinder_relocate",
                "conversation_fingerprint": "tinder-conversation-relocate",
                "thread_evidence": {
                    "observation_id": "obs_tinder_relocate",
                    "screen_state": "tinder_conversation",
                    "latest_inbound_fingerprint": "inbound-zai-ma",
                    "visual_anchor_hash": _png_average_hash(target_conversation_png, region=visual_region),
                    "visual_anchor_region": visual_region,
                    "visual_anchor_max_hamming_distance": 0,
                },
                "message_list_evidence": {
                    "selection_method": "message_list_visual_anchor_scan",
                    "visual_anchor_hash": row_visual_hash,
                    "visual_anchor_region": row_region,
                    "tap_ratio": {"x": 0.50, "y": 0.42},
                },
            },
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["action"], "stage_draft")
        self.assertEqual(payload["target_binding_relocation"]["status"], "ok")
        self.assertEqual(payload["target_binding_relocation"]["attempt_count"], 1)
        self.assertEqual(
            payload["target_binding_verification"]["recovered_by"],
            "message_list_visual_relocation",
        )
        location = payload["target_binding_relocation"]["attempts"][0]["message_list_location"]
        self.assertEqual(location["location_method"], "message_list_visual_anchor_scan")
        self.assertFalse(location["uses_fixed_row_index"])
        self.assertEqual(payload["stage_attempt_status"], "completed")
        self.assertFalse(payload["send_action_executed"])
        self.assertFalse(any(step["intent"] == "tap_tinder_send_button" for step in payload["executed_steps"]))

    def test_tinder_send_message_is_idempotent_when_text_already_sent(self):
        draft = "今晚可以聊十分钟吗？"
        conversation_png = _tinder_conversation_send_button_png()
        visual_region = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65}
        runner = FakeRunner(
            ocr_text=[
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                f"Tinder\nAda\n昨天 21:14\n在吗\n{draft}\nGIF\n",
            ],
            screenshot_bytes=conversation_png,
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            draft,
            dry_run=False,
            target_binding={
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_ada",
                "candidate_key": "tinder_current_ada",
                "conversation_fingerprint": "tinder-conversation-ada",
                "thread_evidence": {
                    "observation_id": "obs_tinder_current_ada",
                    "screen_state": "tinder_conversation",
                    "latest_inbound_fingerprint": "inbound-zai-ma",
                    "visual_anchor_hash": _png_average_hash(conversation_png, region=visual_region),
                    "visual_anchor_region": visual_region,
                    "visual_anchor_max_hamming_distance": 0,
                },
            },
        )

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["already_sent"])
        self.assertFalse(payload["evidence"]["staged_text_verified"])
        self.assertTrue(payload["evidence"]["outbound_exact_text_ocr_verified"])
        self.assertTrue(payload["evidence"]["input_cleared_after_send"])
        self.assertEqual(payload["current_thread_visual_anchor"]["status"], "ok")
        self.assertEqual(payload["current_thread_visual_anchor"]["screen_state"], "tinder_conversation")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))
        self.assertFalse(any('keystroke "v"' in " ".join(command) for command in runner.commands))

    def test_tinder_send_message_accepts_chat_list_row_structural_binding_for_emoji_nickname(self):
        runner = FakeRunner(
            ocr_text=[
                "Tinder\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\n昨天 21:14\n在吗\nhi\nSend\n",
                "Tinder\n昨天 21:14\n在吗\nhi\n",
            ]
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "hi",
            dry_run=False,
            target_binding={
                "binding_type": "chat_list_row_to_thread",
                "target_match_id": "match_tinder_row_5",
                "candidate_key": "tinder_chat_row_5_emoji",
                "selection_evidence": {
                    "source_state": "tinder_messages",
                    "opened_state": "tinder_conversation",
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
            "tinder_chat_list_row_to_thread_structural_binding",
        )
        self.assertTrue(payload["target_binding_verification"]["emoji_nickname_supported"])

    def test_tinder_send_message_accepts_ocr_punctuation_noise_for_staged_text(self):
        runner = FakeRunner(
            ocr_text=[
                "Iris\nlriss613\nGIF\n",
                "Iris\nlriss613\nGIF\n",
                "Iris\nlriss613\nGIF\n",
                "Iris\nlriss613\nGIF Testing send path, please ignore] 1)\n",
                "Iris\nlriss613\nTesting send path, please ignore] 1)\n",
            ]
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "Testing send path, please ignore.",
            dry_run=False,
            target_binding={"required_visible_text": ["Iris"], "target_match_id": "match_iris"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["staged_text_verification"]["status"], "ok")
        self.assertEqual(payload["outbound_message_verification"]["status"], "ok")

    def test_tinder_send_message_reused_existing_staged_text_waits_for_host_visual_verification(self):
        runner = FakeRunner(
            ocr_text=[
                "Iris\nlriss613\nGIF Testing send path, please ignore] 1)\n",
                "Iris\nlriss613\nGIF Testing send path, please ignore] 1)\n",
                "Iris\nlriss613\nGIF Testing send path, please ignore] 1)\n",
                "Iris\nlriss613\nTesting send path, please ignore] 1)\n",
            ],
            screenshot_bytes=_tinder_conversation_send_button_png(),
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "Testing send path, please ignore.",
            dry_run=False,
            target_binding={"required_visible_text": ["Iris"], "target_match_id": "match_iris"},
        )

        self.assertEqual(payload["status"], "needs_host_visual_verification")
        self.assertEqual(payload["reason"], "staged_text_requires_visual_verification")
        self.assertEqual(payload["next_host_action"], "visually_verify_staged_text_before_live_send")
        self.assertTrue(payload["staged_text_verification"]["reused_existing_staged_text"])
        self.assertEqual(payload["visual_verification_request"]["verification_type"], "staged_text_visual")
        self.assertEqual(payload["visual_verification_request"]["expected_character_count"], len("Testing send path, please ignore."))
        self.assertEqual(payload["executed_steps"], [])
        self.assertNotIn("evidence", payload)
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))
        self.assertFalse(any('keystroke "v"' in " ".join(command) for command in runner.commands))
        self.assertFalse(any("tap_tinder_send_button" == step.get("intent") for step in payload["executed_steps"]))

    def test_tinder_send_message_reused_short_row_binding_text_waits_for_host_visual_verification(self):
        runner = FakeRunner(
            ocr_text=[
                "Tinder\n昨天 21:14\nhi\nMessage\nSend\n",
                "Tinder\n昨天 21:14\nhi\nMessage\nSend\n",
                "Tinder\n昨天 21:14\nhi\nMessage\nSend\n",
            ],
            screenshot_bytes=_tinder_conversation_send_button_png(),
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "hi",
            dry_run=False,
            target_binding={
                "binding_type": "chat_list_row_to_thread",
                "target_match_id": "match_tinder_row_5",
                "candidate_key": "tinder_chat_row_5_emoji",
                "selection_evidence": {
                    "source_state": "tinder_messages",
                    "opened_state": "tinder_conversation",
                    "row_index": 5,
                    "target_scope": "ordinary_conversation",
                    "open_action": "open-conversation",
                },
            },
        )

        self.assertEqual(payload["status"], "needs_host_visual_verification")
        self.assertEqual(payload["reason"], "staged_text_requires_visual_verification")
        self.assertEqual(payload["next_host_action"], "visually_verify_staged_text_before_live_send")
        self.assertEqual(payload["visual_verification_request"]["verification_type"], "staged_text_visual")
        self.assertEqual(payload["visual_verification_request"]["expected_character_count"], 2)
        self.assertTrue(payload["visual_verification_request"]["reused_existing_staged_text"])
        self.assertEqual(payload["executed_steps"], [])
        self.assertNotIn("evidence", payload)

    def test_tinder_send_message_dismisses_feedback_survey_before_post_send_verification(self):
        runner = FakeRunner(
            ocr_text=[
                "Iris\nlriss613\nGIF\n",
                "Iris\nlriss613\nGIF\n",
                "Iris\nlriss613\nGIF\n",
                "Iris\nlriss613\nGIF Testing send path, please ignore] 1)\n",
                "tinder\nRAY Tinder 3h2 (0)?\nWWWWW\nAng\n",
                "Iris\nlriss613\nGIF Testing send path, please ignore] 1)\n",
                "Iris\nlriss613\nTesting send path, please ignore] 1)\n",
            ]
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "Testing send path, please ignore.",
            dry_run=False,
            target_binding={"required_visible_text": ["Iris"], "target_match_id": "match_iris"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["feedback_survey_recovery"]["status"], "ok")
        self.assertFalse(payload["feedback_survey_recovery"]["rating_submitted"])
        self.assertEqual(payload["outbound_message_verification"]["status"], "ok")

    def test_tinder_send_message_blocks_when_target_marker_visible_but_screen_is_not_conversation(self):
        runner = FakeRunner(ocr_text="Iris\n查看Iris何时回复\n启用推送通知\n")
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "Hi Iris",
            dry_run=False,
            target_binding={"required_visible_text": ["Iris"], "target_match_id": "match_iris"},
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "target_binding_chat_not_verified")
        self.assertEqual(payload["target_binding_verification"]["matched_marker_hashes"], [
            "65003c7a186430e894caa11372a179dbdcac2cbf99724dacc1455efe1c2582a9"
        ])
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_tinder_send_message_auto_dismisses_subscription_paywall_renavigates_and_retries(self):
        runner = FakeRunner(
            ocr_text=[
                "TINDER GOLD\n"
                "See Who Likes You and match with them instantly with Tinder Gold™\n"
                "Select a plan\n"
                "Continue - $18.99 total\n",
                "Tinder\n聊天\n新的配对\n消息\nAda\n等你回应\n",
                "Tinder\n聊天\n新的配对\n消息\nAda\n等你回应\n",
                "Tinder\n聊天\n新的配对\n消息\nAda\n等你回应\n",
                _ocr_tsv_for_line("Ada", top=235, height=28),
                "Ada\nGIF\n",
                "Ada\nGIF\n",
                "Ada\nGIF\n",
                "Ada\nGIF\n",
                "Ada\nGIF\n今晚可以聊十分钟吗？\nSend\n",
                "Ada\n今晚可以聊十分钟吗？\n",
            ],
            screenshot_bytes=_tinder_bottom_nav_png("chats"),
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["paywall_recovered_and_retried"])
        self.assertEqual(payload["subscription_paywall_recovery"]["status"], "ok")
        self.assertEqual(payload["post_paywall_navigation"]["status"], "ok")
        self.assertEqual(payload["outbound_message_verification"]["status"], "ok")
        self.assertTrue(any(command and command[0] == "pbcopy" for command in runner.commands))
        self.assertTrue(any('keystroke "v"' in " ".join(command) for command in runner.commands))
        self.assertNotIn("18.99", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("今晚可以聊十分钟吗", json.dumps(payload, ensure_ascii=False))

    def test_tinder_stage_draft_paywall_recovery_retries_without_send(self):
        runner = FakeRunner(
            ocr_text=[
                "TINDER GOLD\n"
                "See Who Likes You and match with them instantly with Tinder Gold™\n"
                "Select a plan\n"
                "Continue - $18.99 total\n",
                "Tinder\n聊天\n新的配对\n消息\nAda\n等你回应\n",
                "Tinder\n聊天\n新的配对\n消息\nAda\n等你回应\n",
                "Tinder\n聊天\n新的配对\n消息\nAda\n等你回应\n",
                _ocr_tsv_for_line("Ada", top=235, height=28),
                "Ada\nGIF\n",
                "Ada\nGIF\n",
                "Ada\nGIF\n",
                "Ada\nGIF\n",
                "Ada\nGIF\n今晚可以聊十分钟吗？\nSend\n",
            ],
            screenshot_bytes=_tinder_bottom_nav_png("chats"),
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.session.send_tinder_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
            stage_only=True,
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["action"], "stage_draft")
        self.assertTrue(payload["paywall_recovered_and_retried"])
        self.assertEqual(payload["subscription_paywall_recovery"]["status"], "ok")
        self.assertEqual(payload["stage_attempt_status"], "completed")
        self.assertFalse(payload["send_action_executed"])
        self.assertFalse(any(step["intent"] == "tap_tinder_send_button" for step in payload["executed_steps"]))
        self.assertNotIn("outbound_message_verification", payload)
        self.assertNotIn("18.99", json.dumps(payload, ensure_ascii=False))

    def test_tinder_send_message_blocks_when_iphone_mirroring_is_not_frontmost(self):
        runner = FakeRunner(
            ocr_text="Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
            frontmost=False,
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "iphone_mirroring_not_frontmost")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))
        self.assertFalse(any('keystroke "v"' in " ".join(command) for command in runner.commands))

    def test_tinder_send_message_blocks_when_target_is_only_visible_in_chat_list(self):
        runner = FakeRunner(ocr_text="Tinder\n新的配对\n消息\nAda\n等你回应\n")
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "target_binding_chat_not_verified")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_tinder_send_message_needs_verification_when_post_send_screen_matches_staged_screen(self):
        runner = FakeRunner(
            ocr_text=[
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\n今晚可以聊十分钟吗？\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\n今晚可以聊十分钟吗？\nSend\n",
            ]
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "needs_verification")
        self.assertEqual(payload["reason"], "post_send_input_not_verified_clear")
        self.assertFalse(payload["evidence"]["input_cleared_after_send"])
        self.assertFalse(payload["evidence"]["outbound_message_verified"])
        self.assertTrue(payload["evidence"]["staged_exact_text_ocr_verified"])
        self.assertTrue(payload["evidence"]["outbound_exact_text_ocr_verified"])

    def test_tinder_send_message_needs_verification_when_send_marker_remains_after_post_change(self):
        runner = FakeRunner(
            ocr_text=[
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\n今晚可以聊十分钟吗？\nSend\n",
                "Tinder\nAda\n刚刚\n在吗\n今晚可以聊十分钟吗？\nSend\n",
            ]
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "needs_verification")
        self.assertEqual(payload["reason"], "post_send_input_not_verified_clear")
        self.assertFalse(payload["evidence"]["input_cleared_after_send"])
        self.assertFalse(payload["evidence"]["outbound_message_verified"])
        self.assertTrue(payload["evidence"]["staged_exact_text_ocr_verified"])
        self.assertTrue(payload["evidence"]["outbound_exact_text_ocr_verified"])

    def test_tinder_send_message_allows_send_word_inside_sent_message_body(self):
        runner = FakeRunner(
            ocr_text=[
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nsend me your plan\nSend\n",
                "Tinder\nAda\n刚刚\n在吗\nsend me your plan\n",
            ]
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "send me your plan",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["evidence"]["input_cleared_after_send"])
        self.assertTrue(payload["evidence"]["outbound_message_verified"])
        self.assertTrue(payload["evidence"]["staged_exact_text_ocr_verified"])
        self.assertTrue(payload["evidence"]["outbound_exact_text_ocr_verified"])

    def test_tinder_send_message_blocks_when_target_binding_mismatches_before_staging(self):
        runner = FakeRunner(ocr_text="Tinder\nZara\n昨天 21:14\n在吗\nMessage\nSend\n")
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "target_binding_mismatch")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_tinder_send_message_blocks_generic_target_binding_markers_before_staging(self):
        runner = FakeRunner(ocr_text="Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n")
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "hi",
            dry_run=False,
            target_binding={"required_visible_text": ["Message", "Send"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "target_binding_not_target_specific")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_tinder_send_message_commits_direct_type_ime_candidate_when_paste_does_not_stage(self):
        runner = FakeRunner(
            ocr_text=[
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nhi\nSend\n",
                "Tinder\nAda\n刚刚\n在吗\nhi\n",
            ],
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "hi",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            [step["intent"] for step in payload["executed_steps"]],
            [
                "tap_tinder_message_input",
                "paste_clipboard_into_tinder_message_input",
                "type_tinder_message_input_if_paste_did_not_stage",
                "commit_tinder_message_input_ime_candidate_if_needed",
                "tap_tinder_send_button",
            ],
        )
        self.assertTrue(any('keystroke "hi"' in " ".join(command) for command in runner.commands))
        self.assertTrue(
            any("key code 49" in " ".join(command) and "control down" not in " ".join(command) for command in runner.commands)
        )
        self.assertTrue(payload["staged_text_verified"])
        self.assertTrue(payload["evidence"]["outbound_message_verified"])

    def test_cli_tinder_real_send_requires_policy_allowed_action_request(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            draft_path = root / "tinder-draft.txt"
            data_dir = root / "data"
            auth_path = root / "auth.json"
            action_path = root / "action_request.json"
            draft_text = "今晚可以聊十分钟吗？"
            draft_path.write_text(draft_text, encoding="utf-8")
            auth_path.write_text(json.dumps({
                "schema_version": 1,
                "authorization_id": "auth_tinder_live",
                "scope": "send_chat_messages",
                "app_id": "tinder",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            }), encoding="utf-8")
            action_path.write_text(json.dumps({
                "schema_version": 1,
                "action_request_id": "act_tinder_send",
                "action": "send_message",
                "match_id": "match_ada",
                "candidate_key": "tinder_ada",
                "payload_hash": "wrong_hash",
                "requires_post_action_verification": True,
                "draft_review_id": "draft_review_fixture",
                "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                "target_binding": {"required_visible_text": ["Ada"]},
            }), encoding="utf-8")
            with _patch_cli_adapter() as harness_class:
                exit_code, payload = _run_cli_json([
                    "harness",
                    "tinder",
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

    def test_cli_tinder_real_send_blocks_authorization_match_mismatch_before_native_execution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            draft_path = root / "tinder-draft.txt"
            data_dir = root / "data"
            auth_path = root / "auth.json"
            action_path = root / "action_request.json"
            draft_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
            draft_path.write_text(draft_text, encoding="utf-8")
            auth_path.write_text(json.dumps({
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
            }), encoding="utf-8")
            action_path.write_text(json.dumps({
                "schema_version": 1,
                "action_request_id": "act_tinder_send",
                "action": "send_message",
                "match_id": "match_ada",
                "candidate_key": "tinder_ada",
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
                "requires_post_action_verification": True,
                "draft_review_id": "draft_review_fixture",
                "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
            }), encoding="utf-8")
            with _patch_cli_adapter() as harness_class:
                exit_code, payload = _run_cli_json([
                    "harness",
                    "tinder",
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
        self.assertEqual(payload["reason"], "authorization_match_not_allowed")
        harness_class.assert_not_called()

    def test_cli_tinder_real_send_requires_confirmation_or_autonomous_audit_binding(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            draft_path = root / "tinder-draft.txt"
            data_dir = root / "data"
            auth_path = root / "auth.json"
            action_path = root / "action_request.json"
            draft_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
            draft_path.write_text(draft_text, encoding="utf-8")
            auth_path.write_text(json.dumps({
                "schema_version": 1,
                "authorization_id": "auth_tinder_live",
                "scope": "send_chat_messages",
                "app_id": "tinder",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_match_ids": ["match_ada"],
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            }), encoding="utf-8")
            action_path.write_text(json.dumps({
                "schema_version": 1,
                "action_request_id": "act_tinder_send",
                "action": "send_message",
                "match_id": "match_ada",
                "candidate_key": "tinder_ada",
                "payload_hash": payload_hash,
                "requires_post_action_verification": True,
                "draft_review_id": "draft_review_fixture",
                "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
            }), encoding="utf-8")
            with _patch_cli_adapter() as harness_class:
                exit_code, payload = _run_cli_json([
                    "harness",
                    "tinder",
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
        self.assertEqual(payload["reason"], "confirmation_contract_required")
        self.assertEqual(payload["next_host_action"], "use_operator_or_managed_session_work_item")
        self.assertIn("managed_live_send_guidance", payload)
        self.assertIn("do_not_handcraft_action_request_json", payload["forbidden_actions"])
        harness_class.assert_not_called()

    def test_cli_tinder_real_send_blocks_target_binding_match_mismatch_before_native_execution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            draft_path = root / "tinder-draft.txt"
            data_dir = root / "data"
            auth_path = root / "auth.json"
            action_path = root / "action_request.json"
            draft_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
            draft_path.write_text(draft_text, encoding="utf-8")
            auth_path.write_text(json.dumps({
                "schema_version": 1,
                "authorization_id": "auth_tinder_live",
                "scope": "send_chat_messages",
                "app_id": "tinder",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_match_ids": ["match_ada"],
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            }), encoding="utf-8")
            action_path.write_text(json.dumps({
                "schema_version": 1,
                "action_request_id": "act_tinder_send",
                "action": "send_message",
                "match_id": "match_ada",
                "candidate_key": "tinder_ada",
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
                "requires_post_action_verification": True,
                "draft_review_id": "draft_review_fixture",
                "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_bea"},
            }), encoding="utf-8")
            with _patch_cli_adapter() as harness_class:
                exit_code, payload = _run_cli_json([
                    "harness",
                    "tinder",
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
        self.assertEqual(payload["reason"], "action_request_target_binding_mismatch")
        harness_class.assert_not_called()

    def test_cli_tinder_real_send_requires_explicit_confirmation_hashes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            draft_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
            draft_path = root / "tinder-draft.txt"
            auth_path = root / "auth.json"
            action_path = root / "action_request.json"
            draft_path.write_text(draft_text, encoding="utf-8")
            _write_json(auth_path, _live_send_auth("tinder", authorization_id="auth_tinder_live"))
            _write_json(action_path, {
                "schema_version": 1,
                "action_request_id": "act_tinder_send",
                "action": "send_message",
                "match_id": "match_ada",
                "candidate_key": "tinder_ada",
                "payload_hash": payload_hash,
                "confirmation_id": "confirmation_ada",
                "requires_post_action_verification": True,
                "draft_review_id": "draft_review_fixture",
                "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
            })

            with _patch_cli_adapter() as harness_class:
                exit_code, payload = _run_cli_json([
                    "harness",
                    "tinder",
                    "send-message",
                    "--text-file",
                    str(draft_path),
                    "--data-dir",
                    str(root / "data"),
                    "--authorization",
                    str(auth_path),
                    "--action-request",
                    str(action_path),
                    "--json",
                ])

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["reason"], "confirmation_hashes_required")
        self.assertEqual(payload["next_host_action"], "use_confirmation_validate_hashes_or_operator_work_item")
        self.assertIn("confirmation_validate", payload["managed_live_send_guidance"]["canonical_commands"])
        self.assertIn("do_not_add_confirmation_id_without_confirmation_hashes", payload["forbidden_actions"])
        harness_class.assert_not_called()

    def test_cli_tinder_real_send_accepts_confirmed_confirmation_hash_binding(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            draft_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
            draft_path = root / "tinder-draft.txt"
            auth_path = root / "auth.json"
            action_path = root / "action_request.json"
            payload_path = root / "confirmation_payload.json"
            precondition_path = root / "confirmation_precondition.json"
            draft_path.write_text(draft_text, encoding="utf-8")
            _write_json(auth_path, _live_send_auth("tinder", authorization_id="auth_tinder_live"))
            _write_json(payload_path, {"text": draft_text})
            _write_json(precondition_path, {"observation_id": "obs_before", "fingerprint": "ada:1"})
            _select_runtime_scope(data_dir, "tinder")

            create_exit, create_payload = _run_cli_json([
                "confirmation",
                "create",
                "--data-dir",
                str(data_dir),
                "--action",
                "send_message",
                "--target-match-id",
                "match_ada",
                "--payload-json",
                str(payload_path),
                "--precondition-json",
                str(precondition_path),
                "--expires-at",
                "2099-01-01T00:00:00Z",
                "--json",
            ])
            confirm_exit, confirm_payload = _run_cli_json([
                "confirmation",
                "confirm",
                "--data-dir",
                str(data_dir),
                "--confirmation-id",
                create_payload["confirmation_id"],
                "--json",
            ])
            _write_json(action_path, {
                "schema_version": 1,
                "action_request_id": "act_tinder_send",
                "action": "send_message",
                "match_id": "match_ada",
                "candidate_key": "tinder_ada",
                "payload_hash": payload_hash,
                "confirmation_id": create_payload["confirmation_id"],
                "confirmation_payload_hash": create_payload["payload_hash"],
                "confirmation_precondition_hash": create_payload["precondition_hash"],
                "requires_post_action_verification": True,
                "draft_review_id": "draft_review_fixture",
                **_draft_generation_binding(),
                "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                **_planner_evidence(),
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
            })
            _write_draft_review_audit(data_dir, target_match_id="match_ada", payload_hash=payload_hash)

            with _patch_cli_adapter() as harness_class:
                harness_class.return_value.send_tinder_message.return_value = {
                    "schema_version": 1,
                    "status": "ok",
                    "app_id": "tinder",
                    "action": "send_message",
                }
                send_exit, send_payload = _run_cli_json([
                    "harness",
                    "tinder",
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

        self.assertEqual(create_exit, 0)
        self.assertEqual(confirm_exit, 0)
        self.assertEqual(confirm_payload["status"], "confirmed")
        self.assertEqual(send_exit, 0)
        self.assertEqual(send_payload["status"], "ok")
        harness_class.return_value.send_tinder_message.assert_called_once()
