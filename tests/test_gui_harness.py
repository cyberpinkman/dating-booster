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


class FakeRunner:
    def __init__(
        self,
        *,
        ocr_text: str | list[str],
        frontmost: bool = True,
        screenshot_bytes: bytes | None = None,
        missing_commands: set[str] | None = None,
        window_name: str = "iPhone Mirroring",
    ):
        self.ocr_texts = list(ocr_text) if isinstance(ocr_text, list) else [ocr_text]
        self.frontmost = frontmost
        self.screenshot_bytes = screenshot_bytes
        self.missing_commands = missing_commands or set()
        self.window_name = window_name
        self.commands: list[list[str]] = []

    def run(self, command: list[str], *, input: str | None = None):
        self.commands.append(command)
        if command[:2] == ["command", "-v"]:
            if command[2] in self.missing_commands:
                return _result(returncode=1)
            return _result(stdout=f"/usr/bin/{command[2]}\n")
        if command and command[0] == "osascript" and any("get {frontmost" in item for item in command):
            frontmost = "true" if self.frontmost else "false"
            return _result(stdout=f"{frontmost}, 100, 50, 350, 760, {self.window_name}\n")
        if command and command[0] == "osascript":
            return _result(stdout="")
        if command and command[0] == "screencapture":
            output = Path(command[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(self.screenshot_bytes or b"fake png")
            return _result(stdout="")
        if command and command[0] == "tesseract":
            if len(self.ocr_texts) > 1:
                return _result(stdout=self.ocr_texts.pop(0))
            return _result(stdout=self.ocr_texts[0])
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
    def test_capabilities_expose_stage_gui_harness_without_live_send_harness(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = StringIO()
            with redirect_stdout(output):
                exit_code = main(["capabilities", "--json", "--data-dir", temp_dir])

        payload = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["schema_versions"]["gui_harness"], 1)
        self.assertIn("harness doctor", payload["supported_commands"])
        self.assertIn("harness screenshot", payload["supported_commands"])
        self.assertIn("harness tinder launch", payload["supported_commands"])
        self.assertIn("harness tinder open-profile", payload["supported_commands"])
        self.assertIn("harness tinder observe", payload["supported_commands"])
        self.assertIn("harness tinder action", payload["supported_commands"])
        self.assertIn("harness tinder workflow", payload["supported_commands"])
        self.assertIn("harness wechat launch", payload["supported_commands"])
        self.assertIn("harness wechat observe", payload["supported_commands"])
        self.assertIn("harness wechat stage-draft", payload["supported_commands"])
        self.assertTrue(payload["agent_native_capabilities"]["iphone_mirroring_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["stage_gui_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["tinder_gui_launch"])
        self.assertTrue(payload["agent_native_capabilities"]["tinder_gui_navigation"])
        self.assertTrue(payload["agent_native_capabilities"]["tinder_profile_read_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["tinder_chat_navigation_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_host_loop"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_macos_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_gui_launch"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_chat_observation_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_draft_stage_harness"])
        self.assertFalse(payload["agent_native_capabilities"]["live_gui_harness"])

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

    def test_tinder_launch_dry_run_uses_ios_search_from_home_screen(self):
        runner = FakeRunner(ocr_text="周三\n03\n搜索\n电话\n微信\nChrome\n")
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.launch_tinder(dry_run=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target"], "tinder_app")
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            ["tap_ios_search", "tap_tinder_suggestion_icon", "type_app_name", "press_return"],
        )
        self.assertEqual(payload["planned_steps"][0]["tap_ratio"], {"x": 0.5, "y": 0.84})
        self.assertFalse(any("keystroke" in " ".join(command) for command in runner.commands))

    def test_tinder_launch_executes_suggestion_tap_before_keyboard_fallback(self):
        runner = FakeRunner(
            ocr_text=[
                "周三\n03\n搜索\n电话\n微信\nChrome\n",
                "Siri 建议\nTinder\n搜索",
                "Tinder\n滑动\n探索\n赞\n聊天\n个人资料",
            ]
        )
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.launch_tinder(dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual([step["intent"] for step in payload["executed_steps"]], ["tap_ios_search", "tap_tinder_suggestion_icon"])
        self.assertFalse(any("keystroke" in " ".join(command) for command in runner.commands))

    def test_open_profile_launch_if_needed_combines_launch_and_profile_navigation(self):
        runner = FakeRunner(ocr_text="周三\n03\n搜索\n电话\n微信\nChrome\n")
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.open_tinder_profile(dry_run=True, launch_if_needed=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            ["tap_ios_search", "tap_tinder_suggestion_icon", "type_app_name", "press_return", "tap_tinder_profile_tab"],
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
                "swipe_profile_read_down",
                "swipe_profile_read_down",
                "tap_expand_visible_profile_section",
                "tap_profile_down_arrow",
                "tap_preview_done",
            ],
        )
        self.assertTrue(all(step["risk"] == "navigation_only" for step in payload["planned_steps"]))

    def test_chat_read_match_profile_workflow_covers_matches_messages_thread_and_profile_reading(self):
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
                "swipe_new_matches_left",
                "tap_new_match_card",
                "tap_chats_tab",
                "tap_conversation_row",
                "tap_thread_profile_avatar",
                "tap_photo_next",
                "tap_profile_up_arrow",
                "swipe_profile_read_down",
                "tap_expand_visible_profile_section",
                "tap_profile_down_arrow",
                "tap_preview_done",
            ],
        )
        conversation_step = next(step for step in payload["planned_steps"] if step["intent"] == "tap_conversation_row")
        self.assertEqual(conversation_step["row_index"], 2)

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
        ]
        payloads = [harness.run_tinder_action(name, dry_run=True) for name in action_names]

        self.assertTrue(all(payload["status"] == "ok" for payload in payloads))
        self.assertTrue(all(payload["blocked_actions"] == ["send", "like", "super_like", "unmatch", "report", "profile_edit"] for payload in payloads))
        self.assertIn("swipe", payloads[1]["planned_steps"][0])

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

    def test_cli_exposes_wechat_observe_and_stage_draft(self):
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
                "--text",
                "今晚可以聊十分钟吗？",
                "--dry-run",
                "--json",
            ])

        self.assertEqual(observe_exit, 0)
        self.assertEqual(observe_payload["layout_hints"]["page"], "conversation")
        self.assertEqual(stage_exit, 0)
        self.assertEqual(stage_payload["action"], "stage_draft")
        harness_class.return_value.observe_wechat_screen.assert_called_once()
        harness_class.return_value.stage_wechat_draft.assert_called_once_with(
            "今晚可以聊十分钟吗？",
            dry_run=True,
            output_dir=None,
        )

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

    def test_swipe_action_blocks_cleanly_when_xcrun_missing(self):
        runner = FakeRunner(ocr_text="Tinder\n聊天", missing_commands={"xcrun"})
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.run_tinder_action("profile-scroll-down", dry_run=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "missing_core_graphics_swipe_backend")
        self.assertEqual(payload["executed_steps"][0]["result"]["reason"], "missing_core_graphics_swipe_backend")
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
