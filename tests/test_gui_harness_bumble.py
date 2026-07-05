from tests.gui_harness_support import *


class GuiHarnessBumbleTests(GuiHarnessTestCase):
    def test_bumble_launch_dry_run_uses_home_search_without_send_support(self):
        runner = FakeRunner(ocr_text="今天 周五\n搜索\n电话\n微信\nChrome\n")
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.launch_bumble(dry_run=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target"], "bumble_app")
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            [
                "open_iphone_home_screen",
                "open_ios_spotlight",
                "type_app_name_verified",
                "tap_bumble_search_result_icon",
            ],
        )
        self.assertEqual(payload["planned_steps"][2]["text"], "Bumble")
        self.assertIn("send", payload["blocked_actions"])
        self.assertIn("superswipe", payload["blocked_actions"])
        self.assertEqual(runner.commands, [])
        self.assertFalse(any("keystroke" in " ".join(command) for command in runner.commands))

    def test_bumble_launch_retries_after_input_source_switch_when_first_search_is_not_english(self):
        runner = FakeRunner(
            ocr_text=[
                "今天 周五\n搜索\n电话\n微信\nChrome\n",
                "懂球帝\n搜索\n候选\n",
                "Bumble\nApp\n",
                "Bumble\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
            ],
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.launch_bumble(dry_run=False)

        self.assertEqual(payload["status"], "ok")
        type_step = next(step for step in payload["executed_steps"] if step["intent"] == "type_app_name_verified")
        self.assertTrue(type_step["result"]["retried_after_input_source_switch"])
        self.assertTrue(any("key code 49" in " ".join(command) and "control down" in " ".join(command) for command in runner.commands))
        self.assertFalse(
            any("key code 49" in " ".join(command) and "control down" not in " ".join(command) for command in runner.commands)
        )
        self.assertFalse(type_step["result"]["ime_commit_after_typing"])

    def test_bumble_launch_does_not_switch_input_source_when_first_search_has_app_result(self):
        runner = FakeRunner(
            ocr_text=[
                "今天 周五\n搜索\n电话\n微信\nChrome\n",
                "Bumble\nApp\n",
                "Bumble\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
            ],
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.launch_bumble(dry_run=False)

        self.assertEqual(payload["status"], "ok")
        type_step = next(step for step in payload["executed_steps"] if step["intent"] == "type_app_name_verified")
        self.assertFalse(type_step["result"]["retried_after_input_source_switch"])
        self.assertFalse(type_step["result"]["ime_commit_after_typing"])
        self.assertFalse(any("key code 49" in " ".join(command) and "control down" not in " ".join(command) for command in runner.commands))
        self.assertFalse(any("key code 49" in " ".join(command) and "control down" in " ".join(command) for command in runner.commands))

    def test_bumble_action_and_workflow_dry_runs_are_navigation_only(self):
        harness = create_adapter(app_id="bumble", platform="darwin", runner=FakeRunner(ocr_text="Bumble\n聊天\n"))

        action = harness.run_bumble_action("open-match", match_index=2, dry_run=True)
        workflow = harness.run_bumble_workflow("chat-read-match-profile", conversation_row=1, dry_run=True)

        self.assertEqual(action["status"], "ok")
        self.assertEqual(action["planned_steps"][0]["intent"], "tap_bumble_match_circle")
        self.assertEqual(action["planned_steps"][0]["tap_ratio"], {"x": 0.55, "y": 0.245})
        self.assertIn("send", action["blocked_actions"])
        self.assertEqual(workflow["status"], "ok")
        self.assertIn("capture_profile_read_step", [step["intent"] for step in workflow["planned_steps"]])
        self.assertTrue(all(step.get("risk") == "navigation_only" for step in workflow["planned_steps"]))

    def test_bumble_payloads_include_opening_move_role_policy(self):
        runner = FakeRunner(ocr_text="Bumble\n照片通过验证\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n")
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        observe = harness.observe_bumble_screen()
        action = harness.run_bumble_action("open-match", match_index=2, dry_run=True)
        workflow = harness.run_bumble_workflow("opening-move-open", match_index=2, dry_run=True)

        for payload in (observe, action, workflow):
            with self.subTest(target=payload.get("target") or payload.get("action") or payload.get("workflow")):
                policy = payload["opening_move_policy"]
                self.assertEqual(policy["scope"], "bumble_opening_move")
                self.assertEqual(policy["female_user"]["agent_decision_authority"], "none")
                self.assertIn("ask_user_to_decide", policy["female_user"]["agent_allowed_actions"])
                self.assertTrue(policy["male_user"]["agent_may_draft_reply"])
                self.assertTrue(policy["male_user"]["requires_user_confirmation_before_send"])
                self.assertTrue(policy["male_user"]["current_harness_send_supported"])
                self.assertFalse(policy["male_user"]["autonomous_opening_move_send_supported"])
                self.assertIn("opening_move_enable", payload["blocked_actions"])
                self.assertIn("opening_move_decide_reply_satisfaction", payload["blocked_actions"])
                self.assertIn("opening_move_send", payload["blocked_actions"])

    def test_bumble_send_message_verifies_target_staged_text_and_outbound_bubble(self):
        runner = FakeRunner(
            ocr_text=[
                "Ada\nHi!\nAa\nGIF\n",
                "Ada\nHi!\nAa\nGIF\n",
                "Ada\nHi!\nAa\nGIF\n",
                "Ada\nHi!\n今晚可以聊十分钟吗？\n发送\n",
                "Ada\nHi!\n今晚可以聊十分钟吗？\nAa\nGIF\n",
            ],
            screenshot_bytes=_bumble_conversation_png(outgoing_bubble=False),
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.send_bumble_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_bumble"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["action"], "send_message")
        self.assertTrue(payload["staged_text_verified"])
        self.assertTrue(payload["evidence"]["staged_text_verified"])
        self.assertTrue(payload["evidence"]["input_cleared_after_send"])
        self.assertTrue(payload["evidence"]["post_action_screen_captured"])
        self.assertTrue(payload["evidence"]["outbound_message_verified"])
        self.assertTrue(payload["post_action_observation_id"].startswith("gui_post_send_"))
        self.assertEqual(payload["current_thread_visual_anchor"]["status"], "ok")
        self.assertEqual(payload["current_thread_visual_anchor"]["screen_state"], "bumble_conversation")
        self.assertIn("visual_anchor_hash", payload["current_thread_visual_anchor"])
        self.assertEqual(payload["target_binding_verification"]["status"], "ok")
        self.assertTrue(any(command[:2] == ["xcrun", "swift"] for command in runner.commands))
        self.assertFalse(any('keystroke "v"' in " ".join(command) for command in runner.commands))

    def test_bumble_stage_draft_executes_without_send_and_records_stage_evidence(self):
        runner = FakeRunner(
            ocr_text=[
                "Ada\nHi!\nAa\nGIF\n",
                "Ada\nHi!\nAa\nGIF\n",
                "Ada\nHi!\n今晚可以聊十分钟吗？\n发送\n",
            ],
            screenshot_bytes=[
                _bumble_conversation_png(outgoing_bubble=False),
                _bumble_conversation_png(outgoing_bubble=False),
                _bumble_conversation_png(active_send_button=True, outgoing_bubble=False),
            ],
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

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
        self.assertFalse(any(step["intent"] == "tap_bumble_send_button" for step in payload["executed_steps"]))

    def test_bumble_stage_draft_blocks_when_input_is_already_occupied_before_clipboard_mutation(self):
        runner = FakeRunner(
            ocr_text=[
                "Ada\nHi!\nAa\nGIF\n",
                "Ada\nHi!\n未发送草稿\nAa\nGIF\n",
            ],
            screenshot_bytes=[
                _bumble_conversation_png(outgoing_bubble=False),
                _bumble_conversation_png(active_send_button=True, outgoing_bubble=False),
            ],
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.stage_draft("今晚可以聊十分钟吗？", dry_run=False, output_dir=Path(tempfile.mkdtemp()))

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "message_input_not_empty_before_staging")
        self.assertEqual(payload["next_host_action"], "clear_existing_message_input_before_stage")
        self.assertEqual(payload["pre_stage_input_guard"]["status"], "blocked")
        self.assertTrue(payload["pre_stage_input_guard"]["active_send_button_visual_visible"])
        self.assertFalse(any(command and command[0] == "pbpaste" for command in runner.commands))
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))
        self.assertFalse(any("dating_boost_core_graphics_command_v" in " ".join(command) for command in runner.commands))

    def test_bumble_stage_draft_relocates_current_thread_visual_identity_mismatch_before_staging(self):
        draft = "今晚可以聊十分钟吗？"
        visual_region = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65}
        target_conversation_png = _bumble_conversation_png(outgoing_bubble=False)
        wrong_conversation_png = _bumble_conversation_png(outgoing_bubble=True)
        old_list_png = _iphone_message_list_with_target_row_png(target_center_y=0.52)
        current_list_png = _iphone_message_list_with_target_row_png(target_center_y=0.68)
        row_region = {"x1": 0.05, "y1": 0.47, "x2": 0.95, "y2": 0.57}
        row_visual_hash = _png_average_hash(old_list_png, region=row_region)
        runner = FakeRunner(
            ocr_text=[
                "Ada\nHi!\nAa\nGIF\n",
                "Ada\nHi!\nAa\nGIF\n",
                "Ada\nHi!\nAa\nGIF\n",
                "Bumble\n聊天\n配对列表\n聊天（最近）\n",
                "Bumble\n聊天\n配对列表\n聊天（最近）\n",
                "Ada\nHi!\nAa\nGIF\n",
                "Ada\nHi!\nAa\nGIF\n",
                f"Ada\nHi!\n{draft}\n发送\n",
            ],
            screenshot_bytes=[
                wrong_conversation_png,
                wrong_conversation_png,
                wrong_conversation_png,
                current_list_png,
                current_list_png,
                target_conversation_png,
                target_conversation_png,
                _bumble_conversation_png(active_send_button=True, outgoing_bubble=False),
            ],
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.session.send_bumble_message(
            draft,
            dry_run=False,
            output_dir=Path(tempfile.mkdtemp()),
            stage_only=True,
            target_binding={
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_bumble_relocate",
                "candidate_key": "bumble_relocate",
                "conversation_fingerprint": "bumble-conversation-relocate",
                "thread_evidence": {
                    "observation_id": "obs_bumble_relocate",
                    "screen_state": "bumble_conversation",
                    "latest_inbound_fingerprint": "inbound-hi",
                    "visual_anchor_hash": _png_average_hash(target_conversation_png, region=visual_region),
                    "visual_anchor_region": visual_region,
                    "visual_anchor_max_hamming_distance": 0,
                },
                "message_list_evidence": {
                    "selection_method": "message_list_visual_anchor_scan",
                    "visual_anchor_hash": row_visual_hash,
                    "visual_anchor_region": row_region,
                    "tap_ratio": {"x": 0.43, "y": 0.52},
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
        self.assertFalse(any(step["intent"] == "tap_bumble_send_button" for step in payload["executed_steps"]))

    def test_bumble_send_message_is_idempotent_when_text_already_sent(self):
        draft = "今晚可以聊十分钟吗？"
        conversation_png = _bumble_conversation_png(outgoing_bubble=True)
        visual_region = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65}
        runner = FakeRunner(
            ocr_text=[
                "Ada\nHi!\nAa\nGIF\n",
                "Ada\nHi!\nAa\nGIF\n",
                f"Ada\nHi!\n{draft}\nAa\nGIF\n",
            ],
            screenshot_bytes=conversation_png,
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.send_bumble_message(
            draft,
            dry_run=False,
            target_binding={
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_bumble",
                "candidate_key": "bumble_current_ada",
                "conversation_fingerprint": "bumble-conversation-ada",
                "thread_evidence": {
                    "observation_id": "obs_bumble_current_ada",
                    "screen_state": "bumble_conversation",
                    "latest_inbound_fingerprint": "inbound-hi",
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
        self.assertEqual(payload["current_thread_visual_anchor"]["screen_state"], "bumble_conversation")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))
        self.assertFalse(any("dating_boost_core_graphics_command_v" in " ".join(command) for command in runner.commands))

    def test_bumble_send_message_accepts_chat_list_row_structural_binding_for_emoji_nickname(self):
        runner = FakeRunner(
            ocr_text=[
                "Hi!\nAa\nGIF\n",
                "Hi!\nAa\nGIF\n",
                "Hi!\nAa\nGIF\n",
                "Hi!\nhi\n发送\n",
                "Hi!\nhi\nAa\nGIF\n",
            ],
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.send_bumble_message(
            "hi",
            dry_run=False,
            target_binding={
                "binding_type": "chat_list_row_to_thread",
                "target_match_id": "match_bumble_row_5",
                "candidate_key": "bumble_chat_row_5_emoji",
                "selection_evidence": {
                    "source_state": "bumble_chat_list",
                    "opened_state": "bumble_conversation",
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
        self.assertEqual(payload["visual_verification_request"]["baseline_expected_text_occurrences"], 1)
        self.assertEqual(payload["visual_verification_request"]["observed_expected_text_occurrences"], 2)
        self.assertEqual(payload["target_binding_verification"]["status"], "ok")
        self.assertEqual(
            payload["target_binding_verification"]["verification_method"],
            "bumble_chat_list_row_to_thread_structural_binding",
        )
        self.assertTrue(payload["target_binding_verification"]["emoji_nickname_supported"])

    def test_bumble_current_thread_visual_identity_blocks_visual_mismatch(self):
        conversation_png = _bumble_conversation_png(outgoing_bubble=False)
        region = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65}
        runner = FakeRunner(
            ocr_text="GIF\n回复时间\nAa\n",
            screenshot_bytes=conversation_png,
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness._verify_bumble_target_binding(
            {
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_bumble_current",
                "candidate_key": "bumble_current",
                "conversation_fingerprint": "conversation-current",
                "thread_evidence": {
                    "observation_id": "obs_bumble_current",
                    "screen_state": "bumble_conversation",
                    "latest_inbound_fingerprint": "inbound-current",
                    "visual_anchor_hash": "0000000000000000",
                    "visual_anchor_region": region,
                    "visual_anchor_max_hamming_distance": 0,
                },
            }
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "target_binding_visual_anchor_mismatch")
        self.assertEqual(payload["verification_method"], "bumble_current_thread_visual_identity")
        self.assertEqual(payload["screen_state"], "bumble_conversation")
        self.assertIn("observed_visual_anchor_hash", payload)

    def test_bumble_send_message_commits_direct_type_ime_candidate_when_needed(self):
        runner = FakeRunner(
            ocr_text=[
                "Ada\nOpening Move\nAa\nGIF\n",
                "Ada\nOpening Move\nAa\nGIF\n",
                "Ada\nOpening Move\nAa\nGIF\n",
                "Ada\nOpening Move\nAa\nGIF\n",
                "Ada\nOpening Move\nAa\nGIF\n",
                "Ada\nOpening Move\nhi\n发送\n",
                "Ada\nOpening Move\nhi\nAa\nGIF\n",
            ],
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.send_bumble_message(
            "hi",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_bumble"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            [step["intent"] for step in payload["executed_steps"]],
            [
                "tap_bumble_message_input",
                "paste_clipboard_into_bumble_message_input",
                "type_bumble_message_input_if_paste_did_not_stage",
                "commit_bumble_message_input_ime_candidate_if_needed",
                "tap_bumble_send_button",
            ],
        )
        self.assertTrue(any('keystroke "hi"' in " ".join(command) for command in runner.commands))
        self.assertTrue(any("key code 49" in " ".join(command) and "control down" not in " ".join(command) for command in runner.commands))
        self.assertTrue(payload["staged_text_verified"])

    def test_bumble_send_message_blocks_direct_type_when_exact_text_not_ocr_verified(self):
        runner = FakeRunner(
            ocr_text=[
                "Ada\nOpening Move\nAa\nGIF\n",
                "Ada\nOpening Move\nAa\nGIF\n",
                "Ada\nOpening Move\nAa\nGIF\n",
                "Ada\nOpening Move\nAa\nGIF\n",
                "Ada\nOpening Move\nAah\nAa\nGIF\n",
                "Ada\nOpening Move\nAah\nAa\nGIF\n",
            ],
            screenshot_bytes=[
                _bumble_conversation_png(outgoing_bubble=False),
                _bumble_conversation_png(outgoing_bubble=False),
                _bumble_conversation_png(outgoing_bubble=False),
                _bumble_conversation_png(outgoing_bubble=False),
                _bumble_conversation_png(active_send_button=True, outgoing_bubble=False),
                _bumble_conversation_png(outgoing_bubble=True),
            ],
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.send_bumble_message(
            "hi",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_bumble"},
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "staged_text_not_verified")
        self.assertFalse(payload["staged_text_verification"]["exact_text_ocr_verified"])
        self.assertFalse(any(step["intent"] == "tap_bumble_send_button" for step in payload.get("executed_steps", [])))

    def test_bumble_send_message_blocks_generic_target_binding_markers_before_staging(self):
        runner = FakeRunner(
            ocr_text=[
                "Ada\nOpening Move\nAa\nGIF\n",
                "Ada\nOpening Move\nAa\nGIF\n",
                "Ada\nOpening Move\nAa\nGIF\n",
                "Ada\nOpening Move\nhi\n发送\n",
                "Ada\nOpening Move\nhi\nAa\nGIF\n",
            ],
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.send_bumble_message(
            "hi",
            dry_run=False,
            target_binding={"required_visible_text": ["Opening Move", "Aa"], "target_match_id": "match_bumble"},
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "target_binding_not_target_specific")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_bumble_open_conversation_dry_run_redacts_visible_name_locator(self):
        harness = create_adapter(app_id="bumble", platform="darwin", runner=FakeRunner(ocr_text="Bumble\n聊天\n"))

        payload = harness.run_bumble_action("open-conversation", dry_run=True, visible_name="Ada")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            ["locate_bumble_visible_conversation_name", "tap_bumble_visible_conversation_row"],
        )
        self.assertIn("target_marker_hash", payload["planned_steps"][0])
        self.assertNotIn("Ada", json.dumps(payload, ensure_ascii=False))

    def test_bumble_open_conversation_dry_run_uses_visual_anchor_plan(self):
        harness = create_adapter(app_id="bumble", platform="darwin", runner=FakeRunner(ocr_text="Bumble\n聊天\n"))

        payload = harness.run_bumble_action(
            "open-conversation",
            dry_run=True,
            message_list_evidence={
                "visual_anchor_hash": "ff07077f0101ffff",
                "visual_anchor_region": {"x1": 0.05, "y1": 0.47, "x2": 0.95, "y2": 0.57},
                "tap_ratio": {"x": 0.43, "y": 0.52},
            },
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            ["locate_bumble_conversation_row_visual_anchor", "tap_bumble_visible_conversation_row"],
        )
        self.assertEqual(payload["planned_steps"][0]["location_method"], "message_list_visual_anchor_scan")
        self.assertIn("visual_anchor_hash", payload["planned_steps"][0]["message_list_visual_anchor"])

    def test_bumble_open_conversation_dry_run_blocks_incomplete_visual_anchor_plan(self):
        harness = create_adapter(app_id="bumble", platform="darwin", runner=FakeRunner(ocr_text="Bumble\n聊天\n"))

        payload = harness.run_bumble_action(
            "open-conversation",
            dry_run=True,
            message_list_evidence={"visual_anchor_hash": "ff07077f0101ffff"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["planned_steps"][0]["intent"], "message_list_visual_anchor_evidence_incomplete")
        self.assertEqual(payload["planned_steps"][0]["reason"], "target_relocation_visual_anchor_evidence_incomplete")
        self.assertNotEqual(payload["planned_steps"][0]["intent"], "tap_conversation_row")

    def test_bumble_open_conversation_executes_visible_name_locator_and_verifies_target(self):
        runner = FakeRunner(
            ocr_text=[
                "Bumble\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n聊天（最近）\n",
                "Bumble\n聊天\n配对列表\n聊天（最近）\nAda\nIris\n",
                _ocr_tsv_for_line("Ada", top=330, height=28),
                "Ada\nHi\nAa\nGIF\n",
            ],
            screenshot_bytes=_bumble_conversation_png(outgoing_bubble=False),
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.run_bumble_action(
            "open-conversation",
            dry_run=False,
            visible_name="Ada",
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_bumble"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["open_mode"], "visible_name")
        self.assertEqual(payload["target_binding_verification"]["status"], "ok")
        self.assertEqual(payload["target_binding_verification"]["verification_method"], "bumble_open_conversation_visible_name")
        self.assertEqual(payload["executed_steps"][0]["intent"], "tap_bumble_visible_conversation_row")
        self.assertAlmostEqual(payload["executed_steps"][0]["tap_ratio"]["y"], 0.86)
        self.assertNotIn("Ada", json.dumps(payload, ensure_ascii=False))

    def test_bumble_open_conversation_relocates_visual_anchor_for_non_ocr_row(self):
        old_list_png = _iphone_message_list_with_target_row_png(target_center_y=0.52)
        current_list_png = _iphone_message_list_with_target_row_png(target_center_y=0.68)
        row_region = {"x1": 0.05, "y1": 0.47, "x2": 0.95, "y2": 0.57}
        row_visual_hash = _png_average_hash(old_list_png, region=row_region)
        runner = FakeRunner(
            ocr_text=[
                "Bumble\n聊天\n配对列表\n聊天（最近）\n",
                "Bumble\n聊天\n配对列表\n聊天（最近）\n",
                "GIF\n回复时间\nAa\n",
            ],
            screenshot_bytes=[
                current_list_png,
                current_list_png,
                _bumble_conversation_png(outgoing_bubble=False),
            ],
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.run_bumble_action(
            "open-conversation",
            dry_run=False,
            message_list_evidence={
                "selection_method": "message_list_visual_anchor_scan",
                "visual_anchor_hash": row_visual_hash,
                "visual_anchor_region": row_region,
                "tap_ratio": {"x": 0.43, "y": 0.52},
            },
            target_binding={
                "binding_type": "chat_list_row_to_thread",
                "target_match_id": "match_bumble_nonocr",
                "candidate_key": "bumble_row_nonocr",
                "selection_evidence": {
                    "source_state": "bumble_chat_list",
                    "opened_state": "bumble_conversation",
                    "row_index": 3,
                    "target_scope": "ordinary_conversation",
                    "open_action": "open-conversation",
                },
            },
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["open_mode"], "message_list_visual_anchor")
        location = payload["message_list_relocation"]["message_list_location"]
        self.assertEqual(location["location_method"], "message_list_visual_anchor_scan")
        self.assertFalse(location["uses_fixed_row_index"])
        self.assertAlmostEqual(location["tap_ratio"]["y"], 0.68, delta=0.02)
        self.assertEqual(payload["executed_steps"][0]["location_method"], "message_list_visual_anchor_scan")
        self.assertEqual(payload["target_binding_verification"]["status"], "ok")
        self.assertEqual(
            payload["target_binding_verification"]["verification_method"],
            "bumble_open_conversation_visual_anchor_structural_binding",
        )
        self.assertNotIn("Ada", json.dumps(payload, ensure_ascii=False))

    def test_bumble_send_message_blocks_on_opening_move_page_without_user_confirmation_path(self):
        runner = FakeRunner(ocr_text="旺仔的Opening Move\n旺仔预设了Opening Move。发送消息回复。\n回复\n")
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.send_bumble_message("That is a good question.", dry_run=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "bumble_opening_move_requires_user_confirmation")

    def test_bumble_bottom_tab_action_requires_complete_top_level_nav(self):
        runner = FakeRunner(
            ocr_text="Bumble\nPremium\n查看喜欢您的人\n",
            missing_commands={"xcrun"},
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.run_bumble_action("open-chats", dry_run=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "bumble_top_level_tab_bar_not_verified")
        self.assertNotIn("executed_steps", payload)

    def test_bumble_bottom_tab_action_allows_complete_top_level_nav(self):
        runner = FakeRunner(
            ocr_text=[
                "Bumble\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
                "Bumble\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
                "聊天\n配对列表 (2)\n你的Opening Moves\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
            ],
            missing_commands={"xcrun"},
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.run_bumble_action("open-chats", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["executed_steps"][0]["intent"], "tap_bumble_chats_tab")

    def test_bumble_prepare_message_page_opens_chats_and_returns_visual_plan_contract(self):
        runner = FakeRunner(
            ocr_text=[
                "Bumble\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
                "聊天\n配对列表 (2)\n你的Opening Moves\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
            ],
            missing_commands={"xcrun"},
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.run_bumble_action("prepare-message-page", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["screen_state"], "bumble_chat_list")
        self.assertEqual(payload["next_host_action"], "visual_plan_message_list")
        self.assertEqual(payload["executed_steps"][0]["intent"], "tap_bumble_chats_tab")
        contract = payload["message_list_planning_contract"]
        self.assertTrue(contract["use_visual_row_anchor_for_non_ocr_rows"])
        self.assertIn("chat_list_row_to_thread", contract["allowed_target_bindings"])
        self.assertTrue(contract["generic_ui_markers_are_not_target_binding"])

    def test_bumble_prepare_message_page_returns_from_current_thread_without_raw_text(self):
        runner = FakeRunner(
            ocr_text=[
                "Ada\nHi!\nAa\nGIF\n",
                "聊天\n配对列表 (2)\n你的Opening Moves\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
            ]
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.run_bumble_action("prepare-message-page", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["screen_state"], "bumble_chat_list")
        self.assertEqual(payload["executed_steps"][0]["intent"], "tap_bumble_back_to_chats")
        self.assertEqual(payload["next_host_action"], "visual_plan_message_list")
        self.assertNotIn("Ada", json.dumps(payload, ensure_ascii=False))

    def test_bumble_workflow_blocks_when_step_postcondition_is_not_verified(self):
        runner = FakeRunner(
            ocr_text=[
                "Bumble\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
                "Bumble\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
                "Bumble\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
            ],
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.run_bumble_workflow("chat-read-match-profile", dry_run=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "bumble_step_postcondition_not_verified")
        self.assertEqual(payload["postcondition"]["expected_bumble_states"], ["bumble_chat_list"])

    def test_bumble_opening_move_reply_requires_opening_move_page_before_tapping_reply(self):
        runner = FakeRunner(
            ocr_text=[
                "Bumble\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
                "Bumble\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
                "聊天\n配对列表 (2)\n你的Opening Moves\nJessie\nHi!\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
                "聊天\n配对列表 (2)\n你的Opening Moves\nJessie\nHi!\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
                "Jessie\nHi!\n您有8个小时的回复时间\nAa\nGIF\n",
                "Jessie\nHi!\n您有8个小时的回复时间\nAa\nGIF\n",
            ],
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.run_bumble_workflow("opening-move-reply-composer", dry_run=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "bumble_step_precondition_not_verified")
        self.assertEqual(payload["precondition"]["expected_bumble_states"], ["bumble_opening_move"])

    def test_classifies_bumble_screens_and_reply_deadlines(self):
        self.assertEqual(
            classify_bumble_screen_text("Bumble\n照片通过验证\n我们可以谈论的话题\n咖啡\n个人档案\n发现\n浏览用户\n为你心动\n聊天"),
            "bumble_browse",
        )
        self.assertEqual(
            classify_bumble_screen_text("聊天\n配对列表 (2)\n你的Opening Moves\nJessie\nHi!\n对话将在8小时后失效\n个人档案\n发现\n浏览用户\n为你心动\n聊天"),
            "bumble_chat_list",
        )
        self.assertEqual(
            classify_bumble_screen_text("Jessie\nHi!\n您有8个小时的回复时间\n该您给对方回复了\nAa\nGIF"),
            "bumble_conversation",
        )
        self.assertEqual(
            classify_bumble_screen_text("旺仔的Opening Move\n旺仔预设了Opening Move。发送消息回复。\n回复"),
            "bumble_opening_move",
        )

    def test_visual_bumble_browse_uses_bottom_nav_and_header_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = create_adapter(
                app_id="bumble",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="Bumble 25\n@® © = YG Oo\n",
                    screenshot_bytes=_bumble_browse_png(),
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "bumble-browse.png")

        self.assertEqual(payload["text_state"], "bumble_unknown")
        self.assertEqual(payload["visual_state"], "bumble_browse")
        self.assertEqual(payload["visual_active_tab"], "browse_users")
        self.assertTrue(payload["visual_bottom_nav_present"])
        self.assertEqual(payload["state"], "bumble_browse")

    def test_visual_bumble_browse_does_not_override_without_header_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = create_adapter(
                app_id="bumble",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="13:06\n@® © = YG Oo\n",
                    screenshot_bytes=_bumble_browse_png(),
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "bumble-browse-no-title.png")

        self.assertEqual(payload["text_state"], "unknown")
        self.assertEqual(payload["visual_state"], "bumble_browse")
        self.assertTrue(payload["visual_bottom_nav_present"])
        self.assertEqual(payload["state"], "unknown")

    def test_visual_bumble_chat_list_uses_active_chat_tab_and_list_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = create_adapter(
                app_id="bumble",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text=(
                        "18:28 8\nWIR Q\nBEIT FUR (2)\nIDX (Hi)\n{R&I Opening Moves\n"
                        "MAY R— MBS ITZ? >\nJessie\nHi!\nWIS EQ AT BAR\nPAR RM RAP Aah WR\n"
                    ),
                    screenshot_bytes=_bumble_chat_list_png(),
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "bumble-chat-list.png")

        self.assertEqual(payload["text_state"], "unknown")
        self.assertEqual(payload["visual_state"], "bumble_chat_list")
        self.assertEqual(payload["visual_active_tab"], "chats")
        self.assertTrue(payload["visual_bottom_nav_present"])
        self.assertEqual(payload["state"], "bumble_chat_list")

    def test_visual_bumble_chat_list_does_not_override_without_list_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = create_adapter(
                app_id="bumble",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="18:28\nWIR Q\nJessie\nHi!\n",
                    screenshot_bytes=_bumble_chat_list_png(),
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "bumble-chat-list-no-marker.png")

        self.assertEqual(payload["text_state"], "unknown")
        self.assertEqual(payload["visual_state"], "bumble_chat_list")
        self.assertTrue(payload["visual_bottom_nav_present"])
        self.assertEqual(payload["state"], "unknown")

    def test_visual_bumble_conversation_uses_header_input_and_thread_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = create_adapter(
                app_id="bumble",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="18:41\n{®RIOpening Move\nIHS R-PHASE ITA?\nREX\nHi!\n",
                    screenshot_bytes=_bumble_conversation_png(),
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "bumble-conversation.png")

        self.assertEqual(payload["text_state"], "unknown")
        self.assertEqual(payload["visual_state"], "bumble_conversation")
        self.assertFalse(payload["visual_bottom_nav_present"])
        self.assertEqual(payload["state"], "bumble_conversation")

    def test_visual_bumble_conversation_does_not_override_without_thread_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = create_adapter(
                app_id="bumble",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="18:41\n",
                    screenshot_bytes=_bumble_conversation_png(),
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "bumble-conversation-no-marker.png")

        self.assertEqual(payload["text_state"], "unknown")
        self.assertEqual(payload["visual_state"], "bumble_conversation")
        self.assertEqual(payload["state"], "unknown")

    def test_bumble_observe_conversation_reports_managed_live_send_support(self):
        runner = FakeRunner(
            ocr_text="Ada\nOpening Move\nAa\nGIF\n",
            screenshot_bytes=_bumble_conversation_png(),
        )
        harness = create_adapter(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.observe_bumble_screen()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["screen_state"], "bumble_conversation")
        self.assertTrue(payload["layout_hints"]["live_send_supported"])
        self.assertTrue(payload["layout_hints"]["draft_staging_supported"])
        self.assertFalse(payload["layout_hints"]["visual_only_exact_verification_allowed"])

    def test_bumble_top_level_page_uses_bottom_nav_and_header_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = create_adapter(
                app_id="bumble",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="Bumble\n照片通过验证\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
                    screenshot_bytes=_bumble_browse_png(),
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "bumble-browse-nav.png")

        self.assertEqual(payload["text_state"], "bumble_browse")
        self.assertEqual(payload["visual_state"], "bumble_browse")
        self.assertEqual(payload["state"], "bumble_browse")

    def test_cli_bumble_real_send_blocks_generic_target_binding_before_native_execution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            draft_text = "hi"
            payload_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
            draft_path = root / "bumble-draft.txt"
            auth_path = root / "auth.json"
            action_path = root / "action_request.json"
            draft_path.write_text(draft_text, encoding="utf-8")
            _write_json(auth_path, _live_send_auth("bumble", authorization_id="auth_bumble_live"))
            _write_json(action_path, {
                "schema_version": 1,
                "action_request_id": "act_bumble_send",
                "action": "send_message",
                "app_id": "bumble",
                "match_id": "match_bumble",
                "candidate_key": "bumble_ada",
                "payload_hash": payload_hash,
                "precondition_hash": "pre_hash",
                "autonomous_audit_binding": _autonomous_audit_binding(
                    authorization_id="auth_bumble_live",
                    target_match_id="match_bumble",
                    payload_hash=payload_hash,
                ),
                "requires_post_action_verification": True,
                "draft_review_id": "draft_review_fixture",
                "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                "target_binding": {
                    "required_visible_text": ["Opening Move", "Aa"],
                    "target_match_id": "match_bumble",
                    "candidate_key": "bumble_ada",
                },
            })

            with _patch_cli_adapter() as harness_class:
                harness_class.return_value.send_bumble_message.return_value = {
                    "schema_version": 1,
                    "status": "ok",
                    "app_id": "bumble",
                    "action": "send_message",
                }
                exit_code, payload = _run_cli_json([
                    "harness",
                    "bumble",
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
        self.assertEqual(payload["reason"], "action_request_target_binding_not_target_specific")
        harness_class.assert_not_called()
