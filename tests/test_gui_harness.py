import json
import hashlib
import struct
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.core.gui_harness import (
    NativeGuiHarness,
    classify_bumble_screen_text,
    classify_screen_text,
    classify_wechat_screen_text,
)
from dating_boost.harness.input_backends import core_graphics_command_v, core_graphics_drag


class FakeRunner:
    def __init__(
        self,
        *,
        ocr_text: str | list[str],
        frontmost: bool = True,
        screenshot_bytes: bytes | list[bytes] | None = None,
        missing_commands: set[str] | None = None,
        window_name: str = "iPhone Mirroring",
        paste_focus_override: str | None = None,
        return_key_clears_focus: bool = True,
        screenshot_fail_at: set[int] | None = None,
        window_info_stdout: str | list[str] | None = None,
    ):
        self.ocr_texts = list(ocr_text) if isinstance(ocr_text, list) else [ocr_text]
        self.frontmost = frontmost
        if isinstance(screenshot_bytes, list):
            self.screenshot_bytes = None
            self.screenshot_byte_outputs = list(screenshot_bytes)
        else:
            self.screenshot_bytes = screenshot_bytes
            self.screenshot_byte_outputs = []
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
        if isinstance(window_info_stdout, list):
            self.window_info_outputs = list(window_info_stdout)
        elif isinstance(window_info_stdout, str):
            self.window_info_outputs = [window_info_stdout]
        else:
            self.window_info_outputs = []

    def run(self, command: list[str], *, input: str | None = None):
        self.commands.append(command)
        self.command_inputs.append((command, input))
        if command[:2] == ["command", "-v"]:
            if command[2] in self.missing_commands:
                return _result(returncode=1)
            return _result(stdout=f"/usr/bin/{command[2]}\n")
        if command and command[0] == "osascript" and any("get {frontmost" in item for item in command):
            if self.window_info_outputs:
                if len(self.window_info_outputs) > 1:
                    return _result(stdout=self.window_info_outputs.pop(0))
                return _result(stdout=self.window_info_outputs[0])
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
            if self.screenshot_byte_outputs:
                if len(self.screenshot_byte_outputs) > 1:
                    screenshot_bytes = self.screenshot_byte_outputs.pop(0)
                else:
                    screenshot_bytes = self.screenshot_byte_outputs[0]
            else:
                screenshot_bytes = self.screenshot_bytes or b"fake png"
            output.write_bytes(screenshot_bytes)
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


def _ocr_tsv_for_line(text: str, *, top: int = 235, height: int = 28, left: int = 80, width: int = 60) -> str:
    return "\n".join(
        [
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
            f"5\t1\t1\t1\t1\t1\t{left}\t{top}\t{width}\t{height}\t93\t{text}",
            "",
        ]
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _live_send_auth(app_id: str, *, authorization_id: str, allowed_match_ids: list[str] | None = None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "authorization_id": authorization_id,
        "scope": "send_chat_messages",
        "app_id": app_id,
        "expires_at": "2099-01-01T00:00:00Z",
        "allowed_match_ids": allowed_match_ids or [],
        "allowed_actions": ["send_message"],
        "autonomous_send": True,
        "live_send": True,
        "requires_post_action_verification": True,
        "revoked_at": None,
    }


def _autonomous_audit_binding(
    *,
    authorization_id: str,
    target_match_id: str,
    payload_hash: str,
    precondition_hash: str = "pre_hash",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "binding_type": "autonomous_authorization",
        "authorization_id": authorization_id,
        "action": "send_message",
        "target_match_id": target_match_id,
        "payload_hash": payload_hash,
        "precondition_hash": precondition_hash,
    }


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
        self.assertIn("harness bumble launch", payload["supported_commands"])
        self.assertIn("harness bumble observe", payload["supported_commands"])
        self.assertIn("harness bumble action", payload["supported_commands"])
        self.assertIn("harness bumble workflow", payload["supported_commands"])
        self.assertIn("harness bumble send-message", payload["supported_commands"])
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
        self.assertIn("bumble", payload["agent_native_capabilities"]["supported_app_profiles"])
        self.assertIn("bumble", payload["agent_native_capabilities"]["host_loop_app_profiles"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_gui_launch"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_gui_navigation"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_profile_read_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_chat_navigation_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_opening_move_role_policy"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_opening_move_male_draft"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_opening_move_stage_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_opening_move_send_harness"])
        self.assertFalse(payload["agent_native_capabilities"]["bumble_opening_move_autonomous_send"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_live_send_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["bumble_host_loop"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_host_loop"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_macos_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_gui_launch"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_chat_observation_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_draft_stage_harness"])
        self.assertTrue(payload["agent_native_capabilities"]["managed_gui_send"])
        self.assertFalse(payload["agent_native_capabilities"]["managed_gui_send_default"])
        self.assertTrue(payload["agent_native_capabilities"]["wechat_live_send_harness"])
        self.assertFalse(payload["agent_native_capabilities"]["live_gui_harness"])

    def test_cli_generic_harness_blocks_unknown_app_before_native_execution(self):
        with patch("dating_boost.cli.NativeGuiHarness") as harness_class:
            exit_code, payload = _run_cli_json([
                "harness",
                "doctor",
                "--app-id",
                "hinge",
                "--no-capture",
                "--json",
            ])

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "unsupported_native_harness_for_app")
        self.assertEqual(payload["app_id"], "hinge")
        self.assertEqual(payload["supported_native_harness_apps"], ["tinder", "wechat", "bumble"])
        harness_class.assert_not_called()

    def test_bumble_launch_dry_run_uses_home_search_without_send_support(self):
        runner = FakeRunner(ocr_text="今天 周五\n搜索\n电话\n微信\nChrome\n")
        harness = NativeGuiHarness(app_id="bumble", platform="darwin", runner=runner)

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
        harness = NativeGuiHarness(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.launch_bumble(dry_run=False)

        self.assertEqual(payload["status"], "ok")
        type_step = next(step for step in payload["executed_steps"] if step["intent"] == "type_app_name_verified")
        self.assertTrue(type_step["result"]["retried_after_input_source_switch"])
        self.assertTrue(any("key code 49" in " ".join(command) and "control down" in " ".join(command) for command in runner.commands))
        self.assertGreaterEqual(
            sum(1 for command in runner.commands if "key code 49" in " ".join(command) and "control down" not in " ".join(command)),
            2,
        )

    def test_bumble_launch_does_not_switch_input_source_when_first_search_has_app_result(self):
        runner = FakeRunner(
            ocr_text=[
                "今天 周五\n搜索\n电话\n微信\nChrome\n",
                "Bumble\nApp\n",
                "Bumble\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
            ],
        )
        harness = NativeGuiHarness(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.launch_bumble(dry_run=False)

        self.assertEqual(payload["status"], "ok")
        type_step = next(step for step in payload["executed_steps"] if step["intent"] == "type_app_name_verified")
        self.assertFalse(type_step["result"]["retried_after_input_source_switch"])
        self.assertTrue(type_step["result"]["ime_commit_after_typing"])
        self.assertTrue(any("key code 49" in " ".join(command) and "control down" not in " ".join(command) for command in runner.commands))
        self.assertFalse(any("key code 49" in " ".join(command) and "control down" in " ".join(command) for command in runner.commands))

    def test_bumble_action_and_workflow_dry_runs_are_navigation_only(self):
        harness = NativeGuiHarness(app_id="bumble", platform="darwin", runner=FakeRunner(ocr_text="Bumble\n聊天\n"))

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
        harness = NativeGuiHarness(app_id="bumble", platform="darwin", runner=runner)

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
        )
        harness = NativeGuiHarness(app_id="bumble", platform="darwin", runner=runner)

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
        self.assertEqual(payload["target_binding_verification"]["status"], "ok")
        self.assertTrue(any(command[:2] == ["xcrun", "swift"] for command in runner.commands))
        self.assertFalse(any('keystroke "v"' in " ".join(command) for command in runner.commands))

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
        harness = NativeGuiHarness(app_id="bumble", platform="darwin", runner=runner)

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
        harness = NativeGuiHarness(app_id="bumble", platform="darwin", runner=runner)

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
        harness = NativeGuiHarness(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.send_bumble_message(
            "hi",
            dry_run=False,
            target_binding={"required_visible_text": ["Opening Move", "Aa"], "target_match_id": "match_bumble"},
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "target_binding_not_target_specific")
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))

    def test_bumble_send_message_blocks_on_opening_move_page_without_user_confirmation_path(self):
        runner = FakeRunner(ocr_text="旺仔的Opening Move\n旺仔预设了Opening Move。发送消息回复。\n回复\n")
        harness = NativeGuiHarness(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.send_bumble_message("That is a good question.", dry_run=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "bumble_opening_move_requires_user_confirmation")

    def test_bumble_bottom_tab_action_requires_complete_top_level_nav(self):
        runner = FakeRunner(
            ocr_text="Bumble\nPremium\n查看喜欢您的人\n",
            missing_commands={"xcrun"},
        )
        harness = NativeGuiHarness(app_id="bumble", platform="darwin", runner=runner)

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
        harness = NativeGuiHarness(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.run_bumble_action("open-chats", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["executed_steps"][0]["intent"], "tap_bumble_chats_tab")

    def test_bumble_workflow_blocks_when_step_postcondition_is_not_verified(self):
        runner = FakeRunner(
            ocr_text=[
                "Bumble\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
                "Bumble\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
                "Bumble\n个人档案\n发现\n浏览用户\n为你心动\n聊天\n",
            ],
        )
        harness = NativeGuiHarness(app_id="bumble", platform="darwin", runner=runner)

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
        harness = NativeGuiHarness(app_id="bumble", platform="darwin", runner=runner)

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

    def test_core_graphics_command_v_reports_explicit_contract_for_failures(self):
        class FailingRunner:
            def run(self, command, *, input=None):
                self.command = command
                return _result(stderr="keyboard denied", returncode=1)

        runner = FailingRunner()

        payload = core_graphics_command_v(runner)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "core_graphics_command_v_failed")
        self.assertEqual(payload["input_backend_contract_schema_version"], 2)
        self.assertIn("keyboard denied", payload["stderr"])
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

    def test_window_info_skips_iphone_mirroring_floating_overlay(self):
        runner = FakeRunner(
            ocr_text="Tinder\n个人资料\n编辑个人资料\n",
            window_info_stdout=[
                "true, 1094, 776, 108, 28, \n",
                "true, 1067, 57, 348, 766, iPhone Mirroring\n",
            ],
        )
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.doctor(capture=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["window"]["width"], 348)
        self.assertEqual(payload["window"]["height"], 766)

    def test_tinder_launch_dry_run_forces_home_and_search_when_not_in_tinder(self):
        runner = FakeRunner(ocr_text="今天 周四 6月4日\n搜索\n电话\n微信\nChrome\n")
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

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
        self.assertFalse(any("keystroke" in " ".join(command) for command in runner.commands))

    def test_tinder_launch_executes_home_search_and_taps_app_result(self):
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
            [
                "open_iphone_home_screen",
                "open_ios_spotlight",
                "type_app_name_verified",
                "tap_tinder_search_result_icon",
            ],
        )
        self.assertTrue(any('keystroke "Tinder"' in " ".join(command) for command in runner.commands))
        self.assertEqual(payload["executed_steps"][-1]["tap_ratio"], {"x": 0.18, "y": 0.20})

    def test_open_profile_launch_if_needed_combines_launch_and_profile_navigation(self):
        runner = FakeRunner(ocr_text="周三\n03\n搜索\n电话\n微信\nChrome\n")
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.open_tinder_profile(dry_run=True, launch_if_needed=True)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            [step["intent"] for step in payload["planned_steps"]],
            [
                "open_iphone_home_screen",
                "open_ios_spotlight",
                "type_app_name_verified",
                "tap_tinder_search_result_icon",
                "tap_tinder_profile_tab",
            ],
        )

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

    def test_visual_self_profile_does_not_override_ios_home_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = NativeGuiHarness(
                app_id="tinder",
                platform="darwin",
                runner=FakeRunner(
                    ocr_text="今天 周四 6月4日\n搜索\n电话\n微信\nChrome\n",
                    screenshot_bytes=_tinder_bottom_nav_png("profile"),
                ),
            )

            payload = harness.capture_window(output=Path(temp_dir) / "ios-home.png")

        self.assertEqual(payload["text_state"], "ios_home_screen")
        self.assertEqual(payload["state"], "ios_home_screen")

    def test_visual_self_profile_does_not_override_non_tinder_app_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = NativeGuiHarness(
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
            harness = NativeGuiHarness(
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
                    harness = NativeGuiHarness(
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

    def test_visual_bumble_browse_uses_bottom_nav_and_header_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = NativeGuiHarness(
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
            harness = NativeGuiHarness(
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
            harness = NativeGuiHarness(
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
            harness = NativeGuiHarness(
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
            harness = NativeGuiHarness(
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
            harness = NativeGuiHarness(
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
        harness = NativeGuiHarness(app_id="bumble", platform="darwin", runner=runner)

        payload = harness.observe_bumble_screen()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["screen_state"], "bumble_conversation")
        self.assertTrue(payload["layout_hints"]["live_send_supported"])
        self.assertTrue(payload["layout_hints"]["draft_staging_supported"])
        self.assertFalse(payload["layout_hints"]["visual_only_exact_verification_allowed"])

    def test_bumble_top_level_page_uses_bottom_nav_and_header_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = NativeGuiHarness(
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

    def test_tinder_observe_preserves_visual_bottom_active_tab_for_home_surfaces(self):
        runner = FakeRunner(ocr_text="20:29 RO 37\n", screenshot_bytes=_tinder_bottom_nav_png("likes"))
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.observe_tinder_screen()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["screen_state"], "tinder_home")
        self.assertEqual(payload["layout_hints"]["page"], "home")
        self.assertEqual(payload["layout_hints"]["bottom_active_tab"], "likes")
        self.assertEqual(payload["layout_hints"]["visual_bottom_active_tab"], "likes")

    def test_spotlight_bottom_search_candidate_bar_is_not_tinder_bottom_nav(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            harness = NativeGuiHarness(
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
            screenshot = _tinder_bottom_nav_png("profile")
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
        self.assertIn("wheel", payloads[1]["planned_steps"][0])
        self.assertIn("wheel", payloads[2]["planned_steps"][0])
        self.assertIn("wheel", payloads[3]["planned_steps"][0])
        self.assertIn("wheel", payloads[10]["planned_steps"][0])
        thread_profile_step = payloads[6]["planned_steps"][0]
        self.assertEqual(thread_profile_step["tap_ratio"], {"x": 0.5, "y": 0.14})
        return_to_chats_step = payloads[-2]["planned_steps"][0]
        self.assertEqual(return_to_chats_step["intent"], "tap_thread_back_to_chats")
        feedback_survey_step = payloads[-1]["planned_steps"][0]
        self.assertEqual(feedback_survey_step["intent"], "tap_tinder_feedback_survey_ignore")

    def test_tinder_open_conversation_can_target_visible_row_y_ratio_after_scroll(self):
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=FakeRunner(ocr_text="Tinder\n聊天"))

        payload = harness.run_tinder_action("open-conversation", dry_run=True, y_ratio=0.71)

        self.assertEqual(payload["status"], "ok")
        step = payload["planned_steps"][0]
        self.assertEqual(step["intent"], "tap_conversation_row")
        self.assertEqual(step["tap_ratio"], {"x": 0.5, "y": 0.71})

    def test_tinder_open_conversation_can_target_visible_name_without_raw_text_in_plan(self):
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=FakeRunner(ocr_text="Tinder\n聊天"))

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
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

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

    def test_tinder_observe_marks_subscription_paywall_for_agent_recovery(self):
        runner = FakeRunner(
            ocr_text=(
                "TINDER GOLD\n"
                "See Who Likes You and match with them instantly with Tinder Gold™\n"
                "Select a plan\n"
                "Continue - $18.99 total\n"
            )
        )
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.observe_tinder_screen()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["screen_state"], "tinder_subscription_paywall")
        self.assertEqual(payload["layout_hints"]["page"], "subscription_paywall")
        self.assertTrue(payload["layout_hints"]["subscription_paywall_visible"])
        self.assertEqual(payload["next_host_action"], "dismiss_subscription_paywall_and_renavigate")
        self.assertNotIn("18.99", json.dumps(payload, ensure_ascii=False))

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
        self.assertTrue(payload["evidence"]["input_cleared_after_send"])
        self.assertTrue(payload["evidence"]["outbound_message_verified"])
        self.assertIn("post_action_observation_id", payload)
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
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "Testing send path, please ignore.",
            dry_run=False,
            target_binding={"required_visible_text": ["Iris"], "target_match_id": "match_iris"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["staged_text_verification"]["status"], "ok")
        self.assertEqual(payload["outbound_message_verification"]["status"], "ok")

    def test_tinder_send_message_reuses_existing_staged_text_after_safe_block(self):
        runner = FakeRunner(
            ocr_text=[
                "Iris\nlriss613\nGIF Testing send path, please ignore] 1)\n",
                "Iris\nlriss613\nGIF Testing send path, please ignore] 1)\n",
                "Iris\nlriss613\nGIF Testing send path, please ignore] 1)\n",
                "Iris\nlriss613\nTesting send path, please ignore] 1)\n",
            ],
            screenshot_bytes=_tinder_conversation_send_button_png(),
        )
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "Testing send path, please ignore.",
            dry_run=False,
            target_binding={"required_visible_text": ["Iris"], "target_match_id": "match_iris"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["staged_text_verification"]["reused_existing_staged_text"])
        self.assertEqual([step["intent"] for step in payload["executed_steps"]], ["tap_tinder_send_button"])
        self.assertFalse(any(command and command[0] == "pbcopy" for command in runner.commands))
        self.assertFalse(any('keystroke "v"' in " ".join(command) for command in runner.commands))

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
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

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
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

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

    def test_tinder_action_dismisses_subscription_paywall_without_purchase_path(self):
        runner = FakeRunner(
            ocr_text=[
                "TINDER GOLD\nSelect a plan\nContinue - $18.99 total\n",
                "Tinder\n聊天\n新的配对\n消息\n",
            ]
        )
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.run_tinder_action("dismiss-subscription-paywall", dry_run=False)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["executed_steps"][0]["intent"], "tap_tinder_subscription_paywall_close")
        self.assertEqual(payload["verification"]["state"], "tinder_messages")
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
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "今晚可以聊十分钟吗？",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "needs_verification")
        self.assertEqual(payload["reason"], "outbound_message_not_verified")
        self.assertFalse(payload["evidence"]["input_cleared_after_send"])
        self.assertFalse(payload["evidence"]["outbound_message_verified"])

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
        harness = NativeGuiHarness(app_id="tinder", platform="darwin", runner=runner)

        payload = harness.send_tinder_message(
            "send me your plan",
            dry_run=False,
            target_binding={"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
        )

        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["evidence"]["input_cleared_after_send"])
        self.assertTrue(payload["evidence"]["outbound_message_verified"])

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
                "expires_at": "2099-01-01T00:00:00Z",
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
                "policy": {"allowed": True},
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
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
                "policy": {"allowed": True},
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
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
        self.assertEqual(payload["reason"], "confirmation_contract_required")
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
                "policy": {"allowed": True},
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_bea"},
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
                "policy": {"allowed": True},
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
            })

            with patch("dating_boost.cli.NativeGuiHarness") as harness_class:
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
                "policy": {"allowed": True},
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
            })

            with patch("dating_boost.cli.NativeGuiHarness") as harness_class:
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

    def test_cli_real_send_accepts_valid_autonomous_audit_binding_for_supported_apps(self):
        for app_id, match_id, candidate_key, marker, command, method_name in (
            ("tinder", "match_ada", "tinder_ada", "Ada", ["harness", "tinder", "send-message"], "send_tinder_message"),
            ("wechat", "match_wechat", "wechat_ada", "Ada", ["harness", "wechat", "send-message"], "send_wechat_message"),
            ("bumble", "match_bumble", "bumble_ada", "Ada", ["harness", "bumble", "send-message"], "send_bumble_message"),
        ):
            with self.subTest(app_id=app_id):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    data_dir = root / "data"
                    draft_text = "今晚可以聊十分钟吗？"
                    payload_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
                    auth_id = f"auth_{app_id}_live"
                    draft_path = root / f"{app_id}-draft.txt"
                    auth_path = root / "auth.json"
                    action_path = root / "action_request.json"
                    draft_path.write_text(draft_text, encoding="utf-8")
                    _write_json(auth_path, _live_send_auth(app_id, authorization_id=auth_id, allowed_match_ids=[match_id]))
                    _write_json(action_path, {
                        "schema_version": 1,
                        "action_request_id": f"act_{app_id}_send",
                        "action": "send_message",
                        "app_id": app_id,
                        "match_id": match_id,
                        "candidate_key": candidate_key,
                        "payload_hash": payload_hash,
                        "precondition_hash": "pre_hash",
                        "autonomous_audit_binding": _autonomous_audit_binding(
                            authorization_id=auth_id,
                            target_match_id=match_id,
                            payload_hash=payload_hash,
                        ),
                        "requires_post_action_verification": True,
                        "policy": {"allowed": True},
                        "target_binding": {
                            "required_visible_text": [marker],
                            "target_match_id": match_id,
                            "candidate_key": candidate_key,
                        },
                    })

                    with patch("dating_boost.cli.NativeGuiHarness") as harness_class:
                        getattr(harness_class.return_value, method_name).return_value = {
                            "schema_version": 1,
                            "status": "ok",
                            "app_id": app_id,
                            "action": "send_message",
                        }
                        exit_code, payload = _run_cli_json([
                            *command,
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

                self.assertEqual(exit_code, 0)
                self.assertEqual(payload["status"], "ok")
                getattr(harness_class.return_value, method_name).assert_called_once()

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
                "policy": {"allowed": True},
                "target_binding": {
                    "required_visible_text": ["Opening Move", "Aa"],
                    "target_match_id": "match_bumble",
                    "candidate_key": "bumble_ada",
                },
            })

            with patch("dating_boost.cli.NativeGuiHarness") as harness_class:
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
        runner = FakeRunner(ocr_text="滑动\n探索\n赞\n聊天\n个人资料\n", missing_commands={"xcrun"})
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

    def test_cli_tinder_action_accepts_visible_name_and_target_binding_for_conversation_open(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            binding_path = Path(temp_dir) / "target-binding.json"
            _write_json(
                binding_path,
                {"required_visible_text": ["Iris"], "target_match_id": "match_iris", "candidate_key": "tinder_iris"},
            )
            with patch("dating_boost.cli.NativeGuiHarness") as harness_class:
                harness_class.return_value.run_tinder_action.return_value = {
                    "schema_version": 2,
                    "status": "ok",
                    "action": "open-conversation",
                }
                exit_code, payload = _run_cli_json([
                    "harness",
                    "tinder",
                    "action",
                    "open-conversation",
                    "--visible-name",
                    "Iris",
                    "--target-binding",
                    str(binding_path),
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


def _tinder_bottom_nav_png(active_tab: str) -> bytes:
    width, height = 200, 400
    pixels = [[(0, 0, 0, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.04, 0.895, 0.96, 0.985, (18, 18, 18, 255))
    slots = [
        ("home", 0.07, 0.25),
        ("explore", 0.25, 0.41),
        ("likes", 0.41, 0.57),
        ("chats", 0.57, 0.74),
        ("profile", 0.74, 0.93),
    ]
    for name, x1, x2 in slots:
        center = (x1 + x2) / 2
        if name == active_tab:
            fill(x1 + 0.01, 0.905, x2 - 0.01, 0.972, (82, 82, 82, 255))
        fill(center - 0.025, 0.925, center + 0.025, 0.940, (238, 238, 238, 255))
        fill(center - 0.040, 0.952, center + 0.040, 0.965, (238, 238, 238, 255))
        if name == "likes":
            fill(center + 0.018, 0.920, center + 0.045, 0.940, (245, 210, 70, 255))

    return _png_from_pixels(pixels, width, height)


def _bumble_browse_png() -> bytes:
    width, height = 200, 400
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.05, 0.10, 0.23, 0.13, (18, 18, 18, 255))
    fill(0.04, 0.18, 0.96, 0.88, (83, 132, 176, 255))
    fill(0.06, 0.73, 0.20, 0.81, (250, 214, 70, 255))
    fill(0.76, 0.70, 0.96, 0.82, (250, 214, 70, 255))
    fill(0.06, 0.89, 0.94, 0.98, (255, 255, 255, 255))
    for center in (0.11, 0.26, 0.50, 0.68, 0.88):
        fill(center - 0.020, 0.905, center + 0.020, 0.930, (80, 80, 80, 255))
        fill(center - 0.040, 0.948, center + 0.040, 0.965, (45, 45, 45, 255))
    return _png_from_pixels(pixels, width, height)


def _bumble_chat_list_png() -> bytes:
    width, height = 200, 400
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.05, 0.105, 0.16, 0.135, (18, 18, 18, 255))
    fill(0.04, 0.20, 0.18, 0.30, (150, 105, 80, 255))
    fill(0.23, 0.20, 0.37, 0.30, (75, 130, 180, 255))
    fill(0.43, 0.20, 0.57, 0.30, (120, 120, 120, 255))
    fill(0.05, 0.36, 0.95, 0.45, (245, 245, 245, 255))
    fill(0.08, 0.38, 0.52, 0.43, (230, 230, 230, 255))
    fill(0.06, 0.50, 0.18, 0.59, (105, 160, 115, 255))
    fill(0.28, 0.50, 0.45, 0.52, (28, 28, 28, 255))
    fill(0.28, 0.535, 0.36, 0.55, (80, 80, 80, 255))
    fill(0.06, 0.89, 0.94, 0.98, (255, 255, 255, 255))
    for center in (0.11, 0.26, 0.50, 0.68):
        fill(center - 0.020, 0.905, center + 0.020, 0.930, (105, 105, 105, 255))
        fill(center - 0.040, 0.948, center + 0.040, 0.965, (90, 90, 90, 255))
    fill(0.86, 0.902, 0.92, 0.935, (18, 18, 18, 255))
    fill(0.84, 0.948, 0.92, 0.965, (18, 18, 18, 255))
    return _png_from_pixels(pixels, width, height)


def _bumble_conversation_png(*, active_send_button: bool = False, outgoing_bubble: bool = True) -> bytes:
    width, height = 200, 400
    pixels = [[(255, 255, 255, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.15, 0.095, 0.23, 0.155, (105, 160, 115, 255))
    fill(0.27, 0.112, 0.40, 0.137, (25, 25, 25, 255))
    fill(0.66, 0.105, 0.72, 0.145, (35, 35, 35, 255))
    fill(0.79, 0.105, 0.86, 0.145, (35, 35, 35, 255))
    fill(0.92, 0.105, 0.96, 0.145, (35, 35, 35, 255))
    fill(0.40, 0.18, 0.96, 0.27, (245, 245, 245, 255))
    fill(0.05, 0.27, 0.18, 0.32, (245, 245, 245, 255))
    if outgoing_bubble:
        fill(0.80, 0.34, 0.96, 0.40, (248, 211, 59, 255))
    fill(0.12, 0.90, 0.88, 0.955, (248, 248, 248, 255))
    fill(0.16, 0.92, 0.21, 0.94, (95, 95, 95, 255))
    fill(0.93 if active_send_button else 0.91, 0.90, 0.98, 0.955, (248, 211, 59, 255) if active_send_button else (225, 225, 225, 255))
    return _png_from_pixels(pixels, width, height)


def _spotlight_search_bottom_png() -> bytes:
    width, height = 200, 400
    pixels = [[(0, 0, 0, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.06, 0.905, 0.94, 0.955, (34, 34, 34, 255))
    fill(0.10, 0.922, 0.14, 0.937, (235, 235, 235, 255))
    fill(0.18, 0.923, 0.37, 0.938, (235, 235, 235, 255))
    fill(0.86, 0.918, 0.90, 0.942, (235, 235, 235, 255))
    fill(0.12, 0.958, 0.32, 0.990, (35, 115, 245, 255))
    fill(0.35, 0.958, 0.45, 0.990, (190, 190, 190, 255))
    return _png_from_pixels(pixels, width, height)


def _tinder_conversation_send_button_png() -> bytes:
    width, height = 200, 400
    pixels = [[(0, 0, 0, 255) for _ in range(width)] for _ in range(height)]

    def fill(x1: float, y1: float, x2: float, y2: float, color: tuple[int, int, int, int]) -> None:
        for y in range(int(y1 * height), int(y2 * height)):
            for x in range(int(x1 * width), int(x2 * width)):
                pixels[y][x] = color

    fill(0.04, 0.90, 0.13, 0.98, (35, 35, 35, 255))
    fill(0.15, 0.91, 0.86, 0.975, (25, 25, 25, 255))
    fill(0.20, 0.93, 0.72, 0.95, (230, 230, 230, 255))
    fill(0.875, 0.905, 0.955, 0.985, (12, 116, 235, 255))
    fill(0.905, 0.925, 0.925, 0.965, (245, 245, 245, 255))
    return _png_from_pixels(pixels, width, height)


def _png_from_pixels(pixels: list[list[tuple[int, int, int, int]]], width: int, height: int) -> bytes:
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
