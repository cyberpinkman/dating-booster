import json
import struct
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.core.gui_harness import NativeGuiHarness, classify_screen_text, classify_wechat_screen_text
from dating_boost.harness.input_backends import core_graphics_drag


class FakeRunner:
    def __init__(
        self,
        *,
        ocr_text: str | list[str],
        frontmost: bool = True,
        screenshot_bytes: bytes | None = None,
        missing_commands: set[str] | None = None,
        window_name: str = "iPhone Mirroring",
        paste_focus_override: str | None = None,
        return_key_clears_focus: bool = True,
        screenshot_fail_at: set[int] | None = None,
    ):
        self.ocr_texts = list(ocr_text) if isinstance(ocr_text, list) else [ocr_text]
        self.frontmost = frontmost
        self.screenshot_bytes = screenshot_bytes
        self.missing_commands = missing_commands or set()
        self.window_name = window_name
        self.commands: list[list[str]] = []
        self.command_inputs: list[tuple[list[str], str | None]] = []
        self.clipboard_text = "previous clipboard"
        self.focused_text = ""
        self.paste_focus_override = paste_focus_override
        self.return_key_clears_focus = return_key_clears_focus
        self.screenshot_fail_at = screenshot_fail_at or set()
        self.screenshot_calls = 0

    def run(self, command: list[str], *, input: str | None = None):
        self.commands.append(command)
        self.command_inputs.append((command, input))
        if command[:2] == ["command", "-v"]:
            if command[2] in self.missing_commands:
                return _result(returncode=1)
            return _result(stdout=f"/usr/bin/{command[2]}\n")
        if command and command[0] == "osascript" and any("get {frontmost" in item for item in command):
            frontmost = "true" if self.frontmost else "false"
            return _result(stdout=f"{frontmost}, 100, 50, 350, 760, {self.window_name}\n")
        if command and command[0] == "osascript" and any("focused UI element" in item for item in command):
            return _result(stdout=f"{self.focused_text}\n")
        if command and command[0] == "osascript" and any('keystroke "v"' in item for item in command):
            self.focused_text = self.clipboard_text if self.paste_focus_override is None else self.paste_focus_override
            return _result(stdout="")
        if command and command[0] == "osascript" and any("key code 36" in item for item in command):
            if self.return_key_clears_focus:
                self.focused_text = ""
            return _result(stdout="")
        if command and command[0] == "osascript":
            return _result(stdout="")
        if command and command[0] == "screencapture":
            self.screenshot_calls += 1
            if self.screenshot_calls in self.screenshot_fail_at:
                return _result(stderr="screen permission denied", returncode=1)
            output = Path(command[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(self.screenshot_bytes or b"fake png")
            return _result(stdout="")
        if command and command[0] == "tesseract":
            if len(self.ocr_texts) > 1:
                return _result(stdout=self.ocr_texts.pop(0))
            return _result(stdout=self.ocr_texts[0])
        if command and command[0] == "pbpaste":
            return _result(stdout=self.clipboard_text)
        if command and command[0] == "pbcopy":
            self.clipboard_text = input or ""
            return _result(stdout="")
        return _result(stdout="")


def _result(*, stdout: str = "", stderr: str = "", returncode: int = 0):
    return type(
        "FakeCompletedProcess",
        (),
        {"stdout": stdout, "stderr": stderr, "returncode": returncode},
    )()


def _run_cli_json(argv: list[str]) -> tuple[int, dict[str, object]]:
    output = StringIO()
    with redirect_stdout(output):
        exit_code = main(argv)
    return exit_code, json.loads(output.getvalue())


class GuiHarnessTests(unittest.TestCase):
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
        self.assertTrue(payload["agent_native_capabilities"]["wechat_host_loop"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_macos_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_gui_launch"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_chat_observation_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_draft_stage_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["managed_gui_send"])
        self.assertFalse(payload["agent_native_capabilities"]["managed_gui_send_default"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_live_send_harness"])
        self.assertFalse(payload["agent_native_capabilities"]["live_gui_harness"])

    def test_cli_generic_harness_blocks_unsupported_app_before_native_execution(self):
        with patch("dating_boost.cli.NativeGuiHarness") as harness_class:
            exit_code, payload = _run_cli_json([
                "harness",
                "doctor",
                "--app-id",
                "bumble",
                "--no-capture",
                "--json",
            ])

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "unsupported_native_harness_for_app")
        self.assertEqual(payload["app_id"], "bumble")
        self.assertEqual(payload["supported_native_harness_apps"], ["tinder", "wechat"])
        harness_class.assert_not_called()

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

    def test_doctor_blocks_when_iphone_mirroring_is_locked(self):
        harness = NativeGuiHarness(
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
        harness = NativeGuiHarness(
            app_id="tinder",
            platform="darwin",
            runner=FakeRunner(ocr_text="Tinder\nMessages\n", frontmost=False),
        )

        payload = harness.doctor(capture=True)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "iphone_mirroring_not_frontmost")
        self.assertFalse(payload["window"]["frontmost"])
        self.assertFalse(any(command and command[0] == "screencapture" for command in harness.runner.commands))

    def test_tinder_open_profile_dry_run_uses_safe_navigation_only(self):
        runner = FakeRunner(ocr_text="Tinder\nMatches\nMessages\n")
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

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
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.launch_tinder(dry_run=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target"], "tinder_app")
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            ["open_iphone_home_screen", "open_ios_spotlight", "type_app_name", "press_return"],
        )
        self.assertFalse(any(step["intent"] == "tap_tinder_suggestion_icon" for step in payload["planned_steps"]))
        self.assertFalse(any("keystroke" in " ".join(command) for command in runner.commands))

    def test_tinder_launch_executes_home_search_and_keyboard_without_siri_suggestion(self):
        runner = FakeRunner(
            ocr_text=[
                "今天 周四 6月4日\n搜索\n电话\n微信\nChrome\n",
                "Tinder\n滑动\n探索\n赞\n聊天\n个人资料",
            ]
        )
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.launch_tinder(dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            [step["intent"] for step in payload["executed_steps"]],
            ["open_iphone_home_screen", "open_ios_spotlight", "type_app_name", "press_return"],
        )
        self.assertTrue(any('keystroke "Tinder"' in " ".join(command) for command in runner.commands))
        self.assertFalse(any(step["intent"] == "tap_tinder_suggestion_icon" for step in payload["executed_steps"]))

    def test_open_profile_launch_if_needed_combines_launch_and_profile_navigation(self):
        runner = FakeRunner(ocr_text="周三\n03\n搜索\n电话\n微信\nChrome\n")
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.open_tinder_profile(dry_run=True, launch_if_needed=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            ["open_iphone_home_screen", "open_ios_spotlight", "type_app_name", "press_return", "tap_tinder_profile_tab"],
        )

    def test_classifies_chinese_tinder_profile_screen(self):
        state = classify_screen_text("ray\n编辑个人资料\n完善个人资料，让更多的人看到你！\ntinder GOLD\n个人资料")

        self.assertEqual(state, "tinder_self_profile")

    def test_classifies_noisy_tinder_profile_ocr(self):
        state = classify_screen_text("@tinder\nSMI RR Gold\nHi Super Like\nBoost")

        self.assertEqual(state, "tinder_unknown")

    def test_classifies_chinese_tinder_messages_without_tinder_word(self):
        state = classify_screen_text("新的配对\n消息\nAda\n等你回应\n")

        self.assertEqual(state, "tinder_messages")

    def test_visual_self_profile_does_not_override_ios_home_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = NativeGuiHarness(
                app_id="tinder",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="今天 周四 6月4日\n搜索\n电话\n微信\nChrome\n",
                    screenshot_bytes=_profile_tab_active_png(),
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "ios-home.png")

        self.assertEqual(payload["text_state"], "ios_home_screen")
        self.assertEqual(payload["state"], "ios_home_screen")

    def test_classifies_stable_chinese_tinder_surfaces_without_noisy_markers(self):
        self.assertEqual(classify_screen_text("滑动\n探索\n赞\n聊天\n个人资料\n"), "tinder_home")
        self.assertEqual(classify_screen_text("聊天\n新的配对\n消息\nMooi\nIris\n"), "tinder_messages")
        self.assertEqual(classify_screen_text("Iris\n怕你认不出我\nIriss613\n键入信息\nGIF\n"), "tinder_conversation")
        self.assertEqual(classify_screen_text("Mooi 36\n关于我\n关键信息\n兴趣\n"), "tinder_profile")

    def test_noisy_match_age_and_notification_prompt_do_not_identify_conversation_alone(self):
        self.assertEqual(classify_screen_text("您和Mooi已配对\n5个月前\n"), "unknown")
        self.assertEqual(classify_screen_text("查看Iris何时回复\n启用推送通知\n"), "unknown")

    def test_classifies_macos_wechat_chat_screen(self):
        state = classify_wechat_screen_text("微信\nAda\n昨天 21:14\n在吗\n发送")

        self.assertEqual(state, "wechat_chat")

    def test_wechat_classifier_does_not_treat_send_word_alone_as_chat_input(self):
        state = classify_wechat_screen_text("微信\n通讯录\n群聊\n发送给朋友\n")

        self.assertEqual(state, "wechat_chat_list")

    def test_visual_top_structure_identifies_tinder_self_profile_without_subscription_heuristic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot = _profile_top_structure_png()
            harness = NativeGuiHarness(
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

    def test_visual_profile_tab_active_state_supports_self_profile_detection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot = _profile_tab_active_png()
            harness = NativeGuiHarness(
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
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=FakeRunner(ocr_text="编辑个人资料\n个人资料"))

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
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=FakeRunner(ocr_text="Tinder\n聊天\n等你回应"))

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
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=FakeRunner(ocr_text="Tinder\n聊天\n新的配对"))

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
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=FakeRunner(ocr_text="Tinder\n聊天\n新的配对"))

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

    def test_tinder_atomic_actions_expose_safe_tap_and_swipe_contracts(self):
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=FakeRunner(ocr_text="Tinder\n聊天"))

        action_names = [
            "open-chats",
            "matches-carousel-next",
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
        ]
        payloads = [harness.run_tinder_action(name, dry_run=True) for name in action_names]

        self.assertTrue(all(payload["status"] == "ok" for payload in payloads))
        self.assertTrue(all(payload["blocked_actions"] == ["send", "like", "super_like", "unmatch", "report", "profile_edit"] for payload in payloads))
        self.assertIn("wheel", payloads[1]["planned_steps"][0])
        self.assertIn("wheel", payloads[8]["planned_steps"][0])
        thread_profile_step = payloads[4]["planned_steps"][0]
        self.assertEqual(thread_profile_step["tap_ratio"], {"x": 0.5, "y": 0.14})
        return_to_chats_step = payloads[-1]["planned_steps"][0]
        self.assertEqual(return_to_chats_step["intent"], "tap_thread_back_to_chats")

    def test_tinder_observe_distinguishes_chat_regions_and_redacts_raw_text(self):
        runner = FakeRunner(ocr_text="Tinder\n新的配对\n消息\nAda\n等你回应\n")
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.observe_tinder_screen()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["screen_state"], "tinder_messages")
        self.assertEqual(payload["layout_hints"]["page"], "chats")
        self.assertTrue(payload["layout_hints"]["new_matches_carousel_present"])
        self.assertTrue(payload["layout_hints"]["conversation_list_present"])
        self.assertTrue(payload["layout_hints"]["reply_required_marker_present"])
        self.assertIn("text_fingerprint", payload["screen"])
        self.assertNotIn("等你回应", json.dumps(payload, ensure_ascii=False))

    def test_profile_read_workflow_reports_redacted_field_coverage_from_step_captures(self):
        runner = FakeRunner(
            ocr_text=[
                "编辑个人资料\n个人资料\n",
                "关于我\n关键信息\n兴趣\n我想要\n基本信息\n生活方式\n查看所有 7 项信息\n",
                "编辑个人资料\n个人资料\n",
            ]
        )
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

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
        payload = NativeGuiHarness(
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
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

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

    def test_tinder_send_message_verifies_target_staged_text_and_outbound_bubble(self):
        runner = FakeRunner(
            ocr_text=[
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\n今晚可以聊十分钟吗？\nSend\n",
                "Tinder\nAda\n昨天 21:14\n在吗\n今晚可以聊十分钟吗？\n",
            ]
        )
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target_binding_verification"]["status"], "ok")
        self.assertTrue(payload["evidence"]["staged_text_verified"])
        self.assertTrue(payload["evidence"]["post_action_screen_captured"])
        self.assertTrue(payload["evidence"]["outbound_message_verified"])
        self.assertIn("post_action_observation_id", payload)
        self.assertTrue(any(command and command[0] == "pbcopy" for command in runner.commands))
        self.assertTrue(any('keystroke "v"' in " ".join(command) for command in runner.commands))
        self.assertNotIn("今晚可以聊十分钟吗", json.dumps(payload, ensure_ascii=False))

    def test_tinder_send_message_blocks_when_target_marker_visible_but_screen_is_not_conversation(self):
        runner = FakeRunner(ocr_text="Iris\n查看Iris何时回复\n启用推送通知\n")
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

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

    def test_tinder_send_message_blocks_when_iphone_mirroring_is_not_frontmost(self):
        runner = FakeRunner(
            ocr_text="Tinder\nAda\n昨天 21:14\n在吗\nMessage\nSend\n",
            frontmost=False,
        )
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

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
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

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
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "needs_verification")
        self.assertEqual(payload["reason"], "outbound_message_not_verified")
        self.assertFalse(payload["evidence"]["outbound_message_verified"])

    def test_tinder_send_message_blocks_when_target_binding_mismatches_before_staging(self):
        runner = FakeRunner(ocr_text="Tinder\nZara\n昨天 21:14\n在吗\nMessage\nSend\n")
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "target_binding_mismatch")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_cli_exposes_tinder_observe_with_redacted_payload(self):
        with patch("dating_boost.cli.NativeGuiHarness") as harness_class:
            harness_class.return_value.observe_tinder_screen.return_value = {
                "schema_version": 1,
                "status": "ok",
                "app_id": "tinder",
                "screen_state": "tinder_messages",
                "layout_hints": {"page": "chats"},
            }

            exit_code, payload = _run_cli_json(["harness", "tinder", "observe", "--json"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["layout_hints"]["page"], "chats")
        harness_class.return_value.observe_tinder_screen.assert_called_once()

    def test_wechat_observe_uses_macos_window_and_redacts_raw_text(self):
        runner = FakeRunner(
            ocr_text="微信\nAda\n昨天 21:14\n今晚有空吗\n发送\n",
            window_name="WeChat",
        )
        harness = NativeGuiHarness(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

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
        harness = NativeGuiHarness(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

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
        harness = NativeGuiHarness(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

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
        harness = NativeGuiHarness(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

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
        pbcopy_inputs = [input_text for command, input_text in runner.command_inputs if command and command[0] == "pbcopy"]
        self.assertEqual(pbcopy_inputs, ["今晚可以聊十分钟吗？", "previous clipboard"])

    def test_wechat_send_message_dry_run_is_explicit_live_send_plan(self):
        runner = FakeRunner(ocr_text="微信\nAda\n发送\n", window_name="WeChat")
        harness = NativeGuiHarness(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

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
        harness = NativeGuiHarness(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

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
        self.assertNotIn("今晚可以聊十分钟吗", json.dumps(payload, ensure_ascii=False))

    def test_wechat_send_message_blocks_when_target_binding_mismatches_before_staging(self):
        runner = FakeRunner(
            ocr_text="微信\nZara\n昨天 21:14\n在吗\n发送\n",
            window_name="WeChat",
        )
        harness = NativeGuiHarness(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

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
        harness = NativeGuiHarness(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

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
        harness = NativeGuiHarness(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

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
        harness = NativeGuiHarness(app_id="wechat", platform="darwin", runner=runner, window_title="WeChat")

        payload = harness.send_wechat_message("今晚可以聊十分钟吗？", dry_run=False)

        self.assertEqual(payload["status"], "needs_verification")
        self.assertEqual(payload["reason"], "post_action_screen_not_captured")
        self.assertFalse(payload["evidence"]["post_action_screen_captured"])

    def test_cli_exposes_wechat_observe_stage_draft_and_send_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            draft_path = Path(temp_dir) / "wechat-draft.txt"
            draft_path.write_text("今晚可以聊十分钟吗？", encoding="utf-8")
            with patch("dating_boost.cli.NativeGuiHarness") as harness_class:
                harness_class.return_value.observe_wechat_screen.return_value = {
                    "schema_version": 1,
                    "status": "ok",
                    "app_id": "wechat",
                    "screen_state": "wechat_chat",
                    "layout_hints": {"page": "conversation"},
                }
                observe_exit, observe_payload = _run_cli_json(["harness", "wechat", "observe", "--json"])

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
            with patch("dating_boost.cli.NativeGuiHarness") as harness_class:
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
                "expires_at": "2026-06-05T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            }), encoding="utf-8")
            with patch("dating_boost.cli.NativeGuiHarness") as harness_class:
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
                "expires_at": "2026-06-05T00:00:00Z",
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
                "policy": {"allowed": True},
                "target_binding": {"required_visible_text": ["Ada"]},
            }), encoding="utf-8")
            with patch("dating_boost.cli.NativeGuiHarness") as harness_class:
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
                "expires_at": "2026-06-05T00:00:00Z",
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
                "policy": {"allowed": True},
                "target_binding": {"required_visible_text": ["Ada"]},
            }), encoding="utf-8")
            with patch("dating_boost.cli.NativeGuiHarness") as harness_class:
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

    def test_cli_wechat_doctor_and_screenshot_default_to_wechat_window_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "wechat.png"
            with patch("dating_boost.cli.NativeGuiHarness") as harness_class:
                harness_class.return_value.doctor_wechat.return_value = {
                    "schema_version": 1,
                    "status": "ok",
                    "app_id": "wechat",
                }
                doctor_exit, _doctor_payload = _run_cli_json([
                    "harness",
                    "doctor",
                    "--app-id",
                    "wechat",
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
                    "--output",
                    str(output_path),
                    "--json",
                ])

        self.assertEqual(doctor_exit, 0)
        self.assertEqual(screenshot_exit, 0)
        self.assertEqual(harness_class.call_args_list[0].kwargs["window_title"], "WeChat")
        self.assertEqual(harness_class.call_args_list[1].kwargs["window_title"], "WeChat")

    def test_tinder_action_execution_blocks_when_tinder_foreground_not_verified(self):
        runner = FakeRunner(ocr_text="周三\n03\n搜索\n电话\n微信\nChrome\n")
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.run_tinder_action("profile-photo-next", dry_run=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "tinder_foreground_not_verified")
        self.assertEqual(payload["screen_state"], "ios_home_screen")
        self.assertFalse(any(command and command[0] == "xcrun" for command in runner.commands))
        self.assertFalse(any("click at" in " ".join(command) for command in runner.commands))

    def test_wheel_action_blocks_cleanly_when_xcrun_missing(self):
        runner = FakeRunner(ocr_text="Tinder\n聊天", missing_commands={"xcrun"})
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.run_tinder_action("profile-scroll-down", dry_run=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "missing_core_graphics_wheel_backend")
        self.assertEqual(payload["executed_steps"][0]["result"]["reason"], "missing_core_graphics_wheel_backend")
        self.assertFalse(any(command and command[0] == "xcrun" for command in runner.commands))

    def test_cli_exposes_tinder_action_and_workflow_dry_runs(self):
        action_exit, action_payload = _run_cli_json([
            "harness",
            "tinder",
            "action",
            "profile-photo-next",
            "--dry-run",
            "--json",
        ])
        workflow_exit, workflow_payload = _run_cli_json([
            "harness",
            "tinder",
            "workflow",
            "self-profile-read",
            "--dry-run",
            "--photo-steps",
            "1",
            "--scroll-steps",
            "1",
            "--json",
        ])

        self.assertEqual(action_exit, 0)
        self.assertEqual(action_payload["action"], "profile-photo-next")
        self.assertEqual(action_payload["planned_steps"][0]["intent"], "tap_photo_next")
        self.assertEqual(workflow_exit, 0)
        self.assertEqual(workflow_payload["workflow"], "self-profile-read")
        self.assertIn("tap_profile_up_arrow", [step["intent"] for step in workflow_payload["planned_steps"]])

    def test_cli_exposes_new_match_workflows_with_match_index(self):
        open_exit, open_payload = _run_cli_json([
            "harness",
            "tinder",
            "workflow",
            "new-match-open",
            "--dry-run",
            "--carousel-swipes",
            "1",
            "--match-index",
            "2",
            "--json",
        ])
        read_exit, read_payload = _run_cli_json([
            "harness",
            "tinder",
            "workflow",
            "new-match-read-profile",
            "--dry-run",
            "--carousel-swipes",
            "1",
            "--match-index",
            "2",
            "--profile-scroll-steps",
            "1",
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


def _profile_top_structure_png() -> bytes:
    width, height = 200, 400
    pixels = [[(0, 0, 0, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.05, 0.08, 0.20, 0.18, (190, 120, 80, 255))
    fill(0.25, 0.13, 0.58, 0.19, (245, 245, 245, 255))
    fill(0.84, 0.10, 0.94, 0.18, (20, 20, 20, 255))
    fill(0.88, 0.13, 0.91, 0.15, (245, 245, 245, 255))
    fill(0.78, 0.89, 0.96, 0.97, (80, 80, 80, 255))
    fill(0.87, 0.91, 0.89, 0.95, (245, 245, 245, 255))

    raw_rows = []
    for row in pixels:
        raw_rows.append(b"\x00" + b"".join(bytes(pixel) for pixel in row))
    raw = b"".join(raw_rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", ihdr),
            _png_chunk(b"IDAT", zlib.compress(raw)),
            _png_chunk(b"IEND", b""),
        ]
    )


def _profile_tab_active_png() -> bytes:
    width, height = 200, 400
    pixels = [[(0, 0, 0, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.03, 0.89, 0.97, 0.98, (18, 18, 18, 255))
    fill(0.78, 0.90, 0.96, 0.97, (82, 82, 82, 255))
    fill(0.86, 0.91, 0.90, 0.96, (246, 246, 246, 255))
    raw_rows = [b"\x00" + b"".join(bytes(pixel) for pixel in row) for row in pixels]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", ihdr),
            _png_chunk(b"IDAT", zlib.compress(b"".join(raw_rows))),
            _png_chunk(b"IEND", b""),
        ]
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


if __name__ == "__main__":
    unittest.main()
