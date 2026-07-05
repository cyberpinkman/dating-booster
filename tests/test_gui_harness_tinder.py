from tests.gui_harness_support import *


class GuiHarnessTinderOtherTests(GuiHarnessTestCase):
    def test_tinder_open_profile_dry_run_uses_safe_navigation_only(self):
        runner = FakeRunner(ocr_text="Tinder\nMatches\nMessages\n")
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.open_tinder_profile(dry_run=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target"], "self_profile")
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["planned_steps"][0]["intent"], "tap_tinder_profile_tab")
        self.assertEqual(payload["planned_steps"][0]["tap_ratio"], {"x": 0.88, "y": 0.94})
        self.assertEqual(payload["blocked_actions"], ["send", "like", "super_like", "unmatch", "report", "profile_edit"])
        self.assertFalse(any("click at" in " ".join(command) for command in runner.commands))

    def test_tinder_launch_dry_run_forces_home_and_search_when_not_in_tinder(self):
        runner = FakeRunner(ocr_text="今天 周四 6月4日\n搜索\n电话\n微信\nChrome\n")
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.launch_tinder(dry_run=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target"], "tinder_app")
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            [
                "open_iphone_home_screen",
                "open_ios_spotlight",
                "type_app_name_verified",
                "tap_tinder_search_result_icon",
            ],
        )
        self.assertEqual(payload["planned_steps"][-1]["tap_ratio"], {"x": 0.18, "y": 0.20})
        self.assertEqual(runner.commands, [])
        self.assertFalse(any("keystroke" in " ".join(command) for command in runner.commands))

    def test_tinder_launch_executes_home_search_and_taps_app_result(self):
        runner = FakeRunner(
            ocr_text=[
                "今天 周四 6月4日\n搜索\n电话\n微信\nChrome\n",
                "Tinder\n滑动\n探索\n赞\n聊天\n个人资料",
            ]
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.launch_tinder(dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            [step["intent"] for step in payload["executed_steps"]],
            [
                "open_iphone_home_screen",
                "open_ios_spotlight",
                "type_app_name_verified",
                "tap_tinder_search_result_icon",
            ],
        )
        self.assertTrue(any('keystroke "Tinder"' in " ".join(command) for command in runner.commands))
        self.assertEqual(payload["executed_steps"][-1]["tap_ratio"], {"x": 0.18, "y": 0.20})

    def test_classifies_chinese_tinder_profile_screen(self):
        state = classify_screen_text("ray\n编辑个人资料\n完善个人资料，让更多的人看到你！\ntinder GOLD\n个人资料")

        self.assertEqual(state, "tinder_self_profile")

    def test_classifies_noisy_tinder_profile_ocr(self):
        state = classify_screen_text("@tinder\nSMI RR Gold\nHi Super Like\nBoost")

        self.assertEqual(state, "tinder_unknown")

    def test_classifies_ios_spotlight_tinder_search_results_as_not_tinder_foreground(self):
        state = classify_screen_text(
            "20:25 Hoe 39\n"
            "Tinder\n"
            "3) Tinder A\n"
            "xt App FRR O\n"
            "tinder\n"
            "JSON - 5KB\n"
            "2026-06-01-tinder-host-loop\n"
            "Markdown - 2 KB\n"
            "iCloud\n"
        )

        self.assertEqual(state, "ios_search")

    def test_classifies_tinder_subscription_paywall_as_recoverable_exception(self):
        state = classify_screen_text(
            "TINDER GOLD\n"
            "See Who Likes You and match with them instantly with Tinder Gold™\n"
            "Select a plan\n"
            "Popular\n"
            "1 Week\n"
            "Unlimited Likes\n"
            "Recurring billing. Cancel anytime.\n"
            "Continue - $18.99 total\n"
        )

        self.assertEqual(state, "tinder_subscription_paywall")

    def test_classifies_tinder_feedback_survey_as_recoverable_overlay(self):
        state = classify_screen_text("cea nee 5\ntinder\nRAY Tinder 3h2 (0)?\nWWWWW\nAng\n")

        self.assertEqual(state, "tinder_feedback_survey")

    def test_classifies_chinese_tinder_messages_without_tinder_word(self):
        state = classify_screen_text("新的配对\n消息\nAda\n等你回应\n")

        self.assertEqual(state, "tinder_messages")

    def test_visual_self_profile_does_not_override_non_tinder_app_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = create_adapter(
                app_id="tinder",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="Mac #iaEER\nSynapseAI\nFOR A Hermes\n",
                    screenshot_bytes=_tinder_bottom_nav_png("profile"),
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "wechat-like.png")

        self.assertEqual(payload["text_state"], "unknown")
        self.assertEqual(payload["visual_state"], "tinder_self_profile")
        self.assertEqual(payload["state"], "unknown")

    def test_visual_self_profile_does_not_override_ios_spotlight_tinder_search_results(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = create_adapter(
                app_id="tinder",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text=(
                        "20:25 Hoe 39\n"
                        "Tinder\n"
                        "3) Tinder A\n"
                        "xt App FRR O\n"
                        "tinder\n"
                        "JSON - 5KB\n"
                        "2026-06-01-tinder-host-loop\n"
                        "Markdown - 2 KB\n"
                        "iCloud\n"
                    ),
                    screenshot_bytes=_spotlight_search_bottom_png(),
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "ios-spotlight.png")

        self.assertEqual(payload["text_state"], "ios_search")
        self.assertEqual(payload["visual_state"], "unknown")
        self.assertEqual(payload["state"], "ios_search")

    def test_visual_tinder_bottom_nav_identifies_stable_pages_without_content_ocr(self):
        cases = [
            ("home", "tinder_home"),
            ("explore", "tinder_home"),
            ("likes", "tinder_home"),
            ("chats", "tinder_messages"),
            ("profile", "tinder_self_profile"),
        ]
        for active_tab, expected_state in cases:
            with self.subTest(active_tab=active_tab):
                with tempfile.TemporaryDirectory() as temp_dir:
                    harness = create_adapter(
                        app_id="tinder",
                        platform="darwin",
                        runner=FakeRunner(
                            ocr_text="20:29 RO 37\n",
                            screenshot_bytes=_tinder_bottom_nav_png(active_tab),
                        ),
                    )

                    payload = harness.capture_window(output=Path(temp_dir) / f"{active_tab}.png")

                self.assertEqual(payload["text_state"], "unknown")
                self.assertEqual(payload["visual_state"], expected_state)
                self.assertEqual(payload["visual_active_tab"], active_tab)
                self.assertEqual(payload["state"], expected_state)

    def test_tinder_observe_preserves_visual_bottom_active_tab_for_home_surfaces(self):
        runner = FakeRunner(ocr_text="20:29 RO 37\n", screenshot_bytes=_tinder_bottom_nav_png("likes"))
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.observe_tinder_screen()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["screen_state"], "tinder_home")
        self.assertEqual(payload["layout_hints"]["page"], "home")
        self.assertEqual(payload["layout_hints"]["bottom_active_tab"], "likes")
        self.assertEqual(payload["layout_hints"]["visual_bottom_active_tab"], "likes")

    def test_spotlight_bottom_search_candidate_bar_is_not_tinder_bottom_nav(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = create_adapter(
                app_id="tinder",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="Tinder\nJSON\nMarkdown\niCloud\n",
                    screenshot_bytes=_spotlight_search_bottom_png(),
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "spotlight.png")

        self.assertEqual(payload["visual_state"], "unknown")
        self.assertEqual(payload["state"], "ios_search")

    def test_classifies_stable_chinese_tinder_surfaces_without_noisy_markers(self):
        self.assertEqual(classify_screen_text("滑动\n探索\n赞\n聊天\n个人资料\n"), "tinder_home")
        self.assertEqual(classify_screen_text("聊天\n新的配对\n消息\nMooi\nIris\n"), "tinder_messages")
        self.assertEqual(classify_screen_text("Iris\n怕你认不出我\nIriss613\n键入信息\nGIF\n"), "tinder_conversation")
        self.assertEqual(classify_screen_text("20:40 Ae 36\nIris @\nSis as x\nlriss613\nGIF\n"), "tinder_conversation")
        self.assertEqual(classify_screen_text("Mooi 36\n关于我\n关键信息\n兴趣\n"), "tinder_profile")

    def test_visual_top_structure_identifies_tinder_self_profile_without_subscription_heuristic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot = _profile_top_structure_png()
            harness = create_adapter(
                app_id="tinder",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="@tinder\nSMI RR Gold\nHi Super Like\nBoost",
                    screenshot_bytes=screenshot,
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "profile.png")

        self.assertEqual(payload["state"], "tinder_self_profile")
        self.assertEqual(payload["visual_state"], "tinder_self_profile")

    def test_tinder_atomic_actions_expose_safe_tap_and_swipe_contracts(self):
        harness = create_adapter(app_id="tinder", platform="darwin", runner=FakeRunner(ocr_text="Tinder\n聊天"))

        action_names = [
            "prepare-message-page",
            "open-chats",
            "matches-carousel-next",
            "conversation-list-scroll-down",
            "conversation-list-scroll-up",
            "open-new-match",
            "open-conversation",
            "open-thread-profile",
            "profile-photo-next",
            "profile-photo-previous",
            "open-full-profile",
            "profile-scroll-down",
            "expand-visible-profile-section",
            "close-full-profile",
            "close-preview",
            "return-to-chats",
            "dismiss-feedback-survey",
        ]
        payloads = [harness.run_tinder_action(name, dry_run=True) for name in action_names]

        self.assertTrue(all(payload["status"] == "ok" for payload in payloads))
        self.assertTrue(all(payload["blocked_actions"] == ["send", "like", "super_like", "unmatch", "report", "profile_edit"] for payload in payloads))
        self.assertIn("wheel", payloads[2]["planned_steps"][0])
        self.assertIn("wheel", payloads[3]["planned_steps"][0])
        self.assertIn("wheel", payloads[4]["planned_steps"][0])
        self.assertIn("wheel", payloads[11]["planned_steps"][0])
        self.assertEqual(payloads[0]["planned_steps"][-1]["intent"], "tap_chats_tab_if_needed")
        thread_profile_step = payloads[7]["planned_steps"][0]
        self.assertEqual(thread_profile_step["tap_ratio"], {"x": 0.5, "y": 0.14})
        return_to_chats_step = payloads[-2]["planned_steps"][0]
        self.assertEqual(return_to_chats_step["intent"], "tap_thread_back_to_chats")
        feedback_survey_step = payloads[-1]["planned_steps"][0]
        self.assertEqual(feedback_survey_step["intent"], "tap_tinder_feedback_survey_ignore")

    def test_tinder_prepare_message_page_opens_chats_and_returns_visual_plan_contract(self):
        runner = FakeRunner(
            ocr_text=[
                "滑动\n探索\n聊天\n个人资料\n",
                "Tinder\nMatches\nMessages\n配对\n消息\n等你回应\n",
            ]
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.run_tinder_action("prepare-message-page", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["screen_state"], "tinder_messages")
        self.assertEqual(payload["next_host_action"], "visual_plan_message_list")
        self.assertEqual(payload["executed_steps"][0]["intent"], "tap_chats_tab")
        contract = payload["message_list_planning_contract"]
        self.assertTrue(contract["use_visual_row_anchor_for_non_ocr_rows"])
        self.assertIn("chat_list_row_to_thread", contract["allowed_target_bindings"])
        self.assertEqual(
            contract["message_list_visual_anchor_scan_region"],
            {"x1": 0.0, "y1": 0.32, "x2": 1.0, "y2": 0.89},
        )

    def test_tinder_prepare_message_page_returns_from_current_thread_without_raw_text(self):
        runner = FakeRunner(
            ocr_text=[
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nMatches\nMessages\n配对\n消息\n等你回应\n",
            ]
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.run_tinder_action("prepare-message-page", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["screen_state"], "tinder_messages")
        self.assertEqual(payload["executed_steps"][0]["intent"], "tap_thread_back_to_chats")
        self.assertEqual(payload["next_host_action"], "visual_plan_message_list")
        self.assertNotIn("Ada", json.dumps(payload, ensure_ascii=False))

    def test_tinder_open_conversation_can_target_visible_row_y_ratio_after_scroll(self):
        harness = create_adapter(app_id="tinder", platform="darwin", runner=FakeRunner(ocr_text="Tinder\n聊天"))

        payload = harness.run_tinder_action("open-conversation", dry_run=True, y_ratio=0.71)

        self.assertEqual(payload["status"], "ok")
        step = payload["planned_steps"][0]
        self.assertEqual(step["intent"], "tap_conversation_row")
        self.assertEqual(step["tap_ratio"], {"x": 0.5, "y": 0.71})

    def test_tinder_open_conversation_can_target_visible_name_without_raw_text_in_plan(self):
        harness = create_adapter(app_id="tinder", platform="darwin", runner=FakeRunner(ocr_text="Tinder\n聊天"))

        payload = harness.run_tinder_action("open-conversation", dry_run=True, visible_name="Iris")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            ["locate_visible_conversation_name", "tap_visible_conversation_row"],
        )
        self.assertIn("target_marker_hash", payload["planned_steps"][0])
        self.assertNotIn("Iris", json.dumps(payload, ensure_ascii=False))

    def test_tinder_open_conversation_executes_visible_name_locator_and_verifies_target(self):
        runner = FakeRunner(
            ocr_text=[
                "聊天\n新的配对\n消息\n",
                "聊天\n新的配对\n消息\nIris\nAda\n",
                _ocr_tsv_for_line("Iris", top=235, height=28),
                "Iris\nGIF\n",
            ],
            screenshot_bytes=_tinder_bottom_nav_png("chats"),
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.run_tinder_action(
            "open-conversation",
            dry_run=False,
            visible_name="Iris",
            target_binding={"required_visible_text": ["Iris"], "target_match_id": "match_iris"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["open_mode"], "visible_name")
        self.assertEqual(payload["target_binding_verification"]["status"], "ok")
        self.assertEqual(payload["executed_steps"][0]["intent"], "tap_visible_conversation_row")
        self.assertAlmostEqual(payload["executed_steps"][0]["tap_ratio"]["y"], 0.6225)
        self.assertNotIn("Iris", json.dumps(payload, ensure_ascii=False))

    def test_tinder_open_conversation_relocates_visual_anchor_from_existing_thread(self):
        old_list_png = _iphone_message_list_with_target_row_png(target_center_y=0.42)
        current_list_png = _iphone_message_list_with_target_row_png(target_center_y=0.64)
        row_region = {"x1": 0.05, "y1": 0.37, "x2": 0.95, "y2": 0.47}
        row_visual_hash = _png_average_hash(old_list_png, region=row_region)
        runner = FakeRunner(
            ocr_text=[
                "GIF\nMessage\n",
                "聊天\n新的配对\n消息\n",
                "GIF\nMessage\n",
            ],
            screenshot_bytes=[
                _tinder_conversation_send_button_png(),
                current_list_png,
                _tinder_conversation_send_button_png(),
            ],
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.run_tinder_action(
            "open-conversation",
            dry_run=False,
            message_list_evidence={
                "selection_method": "message_list_visual_anchor_scan",
                "visual_anchor_hash": row_visual_hash,
                "visual_anchor_region": row_region,
                "tap_ratio": {"x": 0.50, "y": 0.42},
            },
            target_binding={
                "binding_type": "chat_list_row_to_thread",
                "target_match_id": "match_tinder_nonocr",
                "candidate_key": "tinder_row_nonocr",
                "selection_evidence": {
                    "source_state": "tinder_messages",
                    "opened_state": "tinder_conversation",
                    "row_index": 4,
                    "target_scope": "ordinary_conversation",
                    "open_action": "open-conversation",
                },
            },
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["open_mode"], "message_list_visual_anchor")
        self.assertEqual(payload["executed_steps"][0]["intent"], "tap_thread_back_to_chats")
        self.assertEqual(payload["executed_steps"][1]["intent"], "tap_visible_conversation_row")
        location = payload["message_list_relocation"]["message_list_location"]
        self.assertEqual(location["location_method"], "message_list_visual_anchor_scan")
        self.assertFalse(location["uses_fixed_row_index"])
        self.assertAlmostEqual(location["tap_ratio"]["y"], 0.64, delta=0.02)
        self.assertEqual(
            payload["target_binding_verification"]["verification_method"],
            "tinder_open_conversation_visual_anchor_structural_binding",
        )
        self.assertEqual(payload["target_binding_verification"]["status"], "ok")
        self.assertNotIn("Iris", json.dumps(payload, ensure_ascii=False))

    def test_tinder_observe_distinguishes_chat_regions_and_redacts_raw_text(self):
        runner = FakeRunner(ocr_text="Tinder\n新的配对\n消息\nAda\n等你回应\n")
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.observe_tinder_screen()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["screen_state"], "tinder_messages")
        self.assertEqual(payload["layout_hints"]["page"], "chats")
        self.assertTrue(payload["layout_hints"]["new_matches_carousel_present"])
        self.assertTrue(payload["layout_hints"]["conversation_list_present"])
        self.assertTrue(payload["layout_hints"]["reply_required_marker_present"])
        self.assertIn("text_fingerprint", payload["screen"])
        self.assertNotIn("等你回应", json.dumps(payload, ensure_ascii=False))

    def test_tinder_observe_marks_subscription_paywall_for_agent_recovery(self):
        runner = FakeRunner(
            ocr_text=(
                "TINDER GOLD\n"
                "See Who Likes You and match with them instantly with Tinder Gold™\n"
                "Select a plan\n"
                "Continue - $18.99 total\n"
            )
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.observe_tinder_screen()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["screen_state"], "tinder_subscription_paywall")
        self.assertEqual(payload["layout_hints"]["page"], "subscription_paywall")
        self.assertTrue(payload["layout_hints"]["subscription_paywall_visible"])
        self.assertEqual(payload["next_host_action"], "dismiss_subscription_paywall_and_renavigate")
        self.assertNotIn("18.99", json.dumps(payload, ensure_ascii=False))

    def test_tinder_current_thread_visual_identity_verifies_current_screen(self):
        conversation_png = _tinder_conversation_send_button_png()
        region = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65}
        visual_hash = _png_average_hash(conversation_png, region=region)
        runner = FakeRunner(
            ocr_text="GIF\nMessage\n",
            screenshot_bytes=conversation_png,
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness._verify_tinder_target_binding(
            {
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_tinder_current",
                "candidate_key": "tinder_current",
                "conversation_fingerprint": "conversation-current",
                "thread_evidence": {
                    "observation_id": "obs_tinder_current",
                    "screen_state": "tinder_conversation",
                    "latest_inbound_fingerprint": "inbound-current",
                    "visual_anchor_hash": visual_hash,
                    "visual_anchor_region": region,
                },
            }
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["verification_method"], "tinder_current_thread_visual_identity")
        self.assertEqual(payload["visual_anchor_hamming_distance"], 0)
        self.assertNotIn("matched_marker_hashes", payload)

    def test_tinder_action_dismisses_subscription_paywall_without_purchase_path(self):
        runner = FakeRunner(
            ocr_text=[
                "TINDER GOLD\nSelect a plan\nContinue - $18.99 total\n",
                "Tinder\n聊天\n新的配对\n消息\n",
            ]
        )
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.run_tinder_action("dismiss-subscription-paywall", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["executed_steps"][0]["intent"], "tap_tinder_subscription_paywall_close")
        self.assertEqual(payload["verification"]["state"], "tinder_messages")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_cli_exposes_tinder_observe_with_redacted_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _select_runtime_scope(data_dir, "tinder")
            with _patch_cli_adapter() as harness_class:
                harness_class.return_value.observe_tinder_screen.return_value = {
                    "schema_version": 1,
                    "status": "ok",
                    "app_id": "tinder",
                    "screen_state": "tinder_messages",
                    "layout_hints": {"page": "chats"},
                }

                exit_code, payload = _run_cli_json([
                    "harness",
                    "tinder",
                    "observe",
                    "--data-dir",
                    str(data_dir),
                    "--json",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["layout_hints"]["page"], "chats")
        harness_class.return_value.observe_tinder_screen.assert_called_once()

    def test_tinder_action_execution_blocks_when_tinder_foreground_not_verified(self):
        runner = FakeRunner(ocr_text="周三\n03\n搜索\n电话\n微信\nChrome\n")
        harness = create_adapter(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.run_tinder_action("profile-photo-next", dry_run=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "tinder_foreground_not_verified")
        self.assertEqual(payload["screen_state"], "ios_home_screen")
        self.assertFalse(any(command and command[0] == "xcrun" for command in runner.commands))
        self.assertFalse(any("click at" in " ".join(command) for command in runner.commands))

    def test_cli_exposes_tinder_action_and_workflow_dry_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _select_runtime_scope(data_dir, "tinder")
            options_path = Path(temp_dir) / "workflow-options.json"
            _write_json(options_path, {"photo_steps": 1, "scroll_steps": 1})
            with patch.dict("os.environ", {"DATING_BOOST_ALLOW_REAL_GUI_TESTS": "1"}, clear=False):
                action_exit, action_payload = _run_cli_json([
                    "harness",
                    "tinder",
                    "action",
                    "profile-photo-next",
                    "--data-dir",
                    str(data_dir),
                    "--dry-run",
                    "--json",
                ])
                workflow_exit, workflow_payload = _run_cli_json([
                    "harness",
                    "tinder",
                    "workflow",
                    "self-profile-read",
                    "--data-dir",
                    str(data_dir),
                    "--dry-run",
                    "--options-json",
                    str(options_path),
                    "--json",
                ])

        self.assertEqual(action_exit, 0)
        self.assertEqual(action_payload["action"], "profile-photo-next")
        self.assertEqual(action_payload["planned_steps"][0]["intent"], "tap_photo_next")
        self.assertEqual(workflow_exit, 0)
        self.assertEqual(workflow_payload["workflow"], "self-profile-read")
        self.assertIn("tap_profile_up_arrow", [step["intent"] for step in workflow_payload["planned_steps"]])

    def test_cli_tinder_action_accepts_visible_name_and_target_binding_for_conversation_open(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _select_runtime_scope(data_dir, "tinder")
            binding_path = Path(temp_dir) / "target-binding.json"
            _write_json(
                binding_path,
                {"required_visible_text": ["Iris"], "target_match_id": "match_iris", "candidate_key": "tinder_iris"},
            )
            with _patch_cli_adapter() as harness_class:
                harness_class.return_value.run_tinder_action.return_value = {
                    "schema_version": 2,
                    "status": "ok",
                    "action": "open-conversation",
                }
                options_path = Path(temp_dir) / "options.json"
                _write_json(
                    options_path,
                    {
                        "visible_name": "Iris",
                        "target_binding": {
                            "required_visible_text": ["Iris"],
                            "target_match_id": "match_iris",
                            "candidate_key": "tinder_iris",
                        },
                    },
                )
                exit_code, payload = _run_cli_json([
                    "harness",
                    "tinder",
                    "action",
                    "open-conversation",
                    "--data-dir",
                    str(data_dir),
                    "--options-json",
                    str(options_path),
                    "--json",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        harness_class.return_value.run_tinder_action.assert_called_once()
        self.assertEqual(harness_class.return_value.run_tinder_action.call_args.kwargs["visible_name"], "Iris")
        self.assertEqual(
            harness_class.return_value.run_tinder_action.call_args.kwargs["target_binding"]["target_match_id"],
            "match_iris",
        )
