import json
import hashlib
import os
import subprocess
import sys
import tempfile
import argparse
import unittest
from unittest.mock import patch
from pathlib import Path
import shutil

from dating_boost.cli import main
from dating_boost.core.operator import OperatorRepository
from dating_boost.host_loop import (
    HostLoopCommandError,
    HostLoopError,
    HostLoopSupervisor,
    _target_binding_for_work_item,
    _thread_template,
    _validate_managed_sequence_visual_confirmation,
)
from dating_boost.perception.observations import AppObservation
from tests.test_gui_harness import _tashuo_mac_ios_app_conversation_with_messages_png


FIXTURE_DIR = Path("tests/fixtures/host_loop/tinder")


class OperatorHostLoopTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self._env["DATING_BOOST_NOW"] = "2026-05-26T00:00:00Z"

    def test_capabilities_expose_tinder_host_loop_without_live_gui_harness(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, payload = self._run_cli([
                "capabilities",
                "--json",
                "--data-dir",
                str(Path(temp_dir) / "data"),
            ])

            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["agent_native_capabilities"]["host_loop_supervisor"])
            self.assertTrue(payload["agent_native_capabilities"]["tinder_host_loop"])
            self.assertTrue(payload["agent_native_capabilities"]["bumble_host_loop"])
            self.assertTrue(payload["agent_native_capabilities"]["tashuo_host_loop"])
            self.assertIn("bumble", payload["agent_native_capabilities"]["host_loop_app_profiles"])
            self.assertIn("tashuo", payload["agent_native_capabilities"]["host_loop_app_profiles"])
            self.assertEqual(payload["agent_native_capabilities"]["host_loop_command"], "dating-boost-host-loop")
            self.assertFalse(payload["agent_native_capabilities"]["live_gui_harness"])

    def test_wechat_host_loop_init_writes_wechat_authorization_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"

            payload = self._run_script(
                "init",
                "--app-id",
                "wechat",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )

            auth_template = json.loads((data_dir / "automation" / "auth.template.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(auth_template["app_id"], "wechat")
            self.assertTrue((work_dir / "current_work_item.json").exists())

    def test_thread_observation_template_uses_valid_source_type(self):
        template = _thread_template(
            {"candidate_key": "row_ada"},
            {"app_id": "tashuo", "display_name": "她说", "native_gui_harness": {"backend": "mac_ios_app"}},
        )
        observation = template["observation"]
        observation["observation_id"] = "obs_template_001"
        observation["captured_at"] = "2026-06-11T12:00:00Z"
        observation["page_confidence"] = "high"
        observation["match_identity_hints"]["visible_name"] = "Ada"
        observation["match_identity_hints"]["conversation_fingerprint"] = "ada-latest"
        observation["conversation_observation"]["visible_messages"] = [
            {"sender": "match", "text": "你好"}
        ]

        parsed = AppObservation.from_dict(observation)

        self.assertEqual(parsed.source_type.value, "live_screenshot")

    def test_cli_thread_observation_template_uses_valid_source_type(self):
        exit_code, payload = self._run_cli([
            "observation",
            "template",
            "--type",
            "thread",
            "--app-id",
            "tashuo",
            "--json",
        ])
        observation = payload["observation"]
        observation["observation_id"] = "obs_template_cli_001"
        observation["captured_at"] = "2026-06-11T12:00:00Z"
        observation["page_confidence"] = "high"
        observation["match_identity_hints"]["visible_name"] = "Ada"
        observation["match_identity_hints"]["conversation_fingerprint"] = "ada-latest"
        observation["conversation_observation"]["visible_messages"] = [
            {"sender": "match", "text": "你好"}
        ]

        parsed = AppObservation.from_dict(observation)

        self.assertEqual(exit_code, 0)
        self.assertEqual(parsed.source_type.value, "live_screenshot")

    def test_managed_sequence_visual_confirmation_requires_exact_visible_text(self):
        work_item = {"action_request_id": "act_1", "payload_hash": "payload_hash_1"}
        message = {"index": 1, "message_hash": "message_hash_1", "text": "第一句"}
        payload = {
            "schema_version": 1,
            "action_request_id": "act_1",
            "payload_hash": "payload_hash_1",
            "message_index": 1,
            "message_hash": "message_hash_1",
            "result_status": "succeeded",
            "evidence": {
                "host_visual_outbound_exact_text_verified": True,
                "input_cleared_after_send": True,
                "post_action_screen_captured": True,
            },
        }

        reason = _validate_managed_sequence_visual_confirmation(payload, work_item, message)

        self.assertEqual(reason, "managed_sequence_visual_confirmation_visible_text_missing")

    def test_operator_prioritizes_open_thread_queue_by_relationship_priority(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            operator_dir = data_dir / "operator"
            automation_dir = data_dir / "automation"
            operator_dir.mkdir(parents=True, exist_ok=True)
            automation_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(
                operator_dir / "session.json",
                {
                    "schema_version": 1,
                    "session_id": "session_priority_queue",
                    "authorization_id": "auth_priority_queue",
                    "status": "active",
                    "current_work_item": None,
                    "management_mode": "high-throughput",
                    "max_threads_per_cycle": 12,
                    "max_pages_per_cycle": 3,
                    "cycle_send_limit": 3,
                    "cycle_send_count": 0,
                },
            )
            self._write_json(
                operator_dir / "work_queue.json",
                {
                    "schema_version": 1,
                    "work_items": [
                        {
                            "schema_version": 1,
                            "work_item_id": "work_open_thread_sherry",
                            "work_item_type": "open_thread",
                            "candidate_key": "row_sherry",
                        },
                        {
                            "schema_version": 1,
                            "work_item_id": "work_open_thread_xiaoyaowan",
                            "work_item_type": "open_thread",
                            "candidate_key": "row_xiaoyaowan",
                        },
                    ],
                },
            )
            self._write_json(
                automation_dir / "states.json",
                {
                    "schema_version": 1,
                    "states": [
                        {
                            "schema_version": 1,
                            "match_id": "match_sherry",
                            "candidate_key": "row_sherry",
                            "state": "needs_thread_scan",
                            "candidate_type": "new_match_candidate",
                            "unread_cue": "absent",
                        },
                        {
                            "schema_version": 1,
                            "match_id": "match_xiaoyaowan",
                            "candidate_key": "row_xiaoyaowan",
                            "state": "needs_thread_scan",
                            "candidate_type": "continuation_candidate",
                            "unread_cue": "present",
                        },
                    ],
                },
            )

            payload = OperatorRepository(data_dir).next_work_item()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["work_item"]["candidate_key"], "row_xiaoyaowan")

    def test_unsupported_app_blocks_host_loop_doctor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/operator_host_loop.py",
                    "doctor",
                    "--app-id",
                    "hinge",
                    "--data-dir",
                    str(Path(temp_dir) / "data"),
                    "--work-dir",
                    str(Path(temp_dir) / "work"),
                    "--json",
                ],
                cwd=Path.cwd(),
                env=self._env,
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["next_host_action"], "choose_supported_host_loop_app")
            self.assertEqual(payload["reason"], "unsupported app profile: hinge")

    def test_wechat_waiting_template_uses_wechat_desktop_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            auth_path = Path(temp_dir) / "wechat_auth.json"
            auth = json.loads((FIXTURE_DIR / "auth.json").read_text(encoding="utf-8"))
            auth["app_id"] = "wechat"
            self._write_json(auth_path, auth)
            self._bootstrap_data_dir(data_dir)

            payload = self._run_script(
                "run",
                "--app-id",
                "wechat",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(auth_path),
                "--goal",
                str(FIXTURE_DIR / "goal.json"),
                "--availability",
                str(FIXTURE_DIR / "availability.json"),
                "--work-dir",
                str(work_dir),
                "--initial-surface",
                "message-list",
                "--once",
                "--json",
            )
            work_item_id = payload["current_work_item"]["work_item_id"]
            template = json.loads(
                (work_dir / f"message_list_observation.{work_item_id}.template.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(payload["status"], "waiting_for_host")
            self.assertIn("send", payload["app_profile"]["native_blocked_actions"])
            self.assertEqual(template["app_id"], "wechat")
            self.assertIn("WeChat chat list", template["provenance"]["evidence"])
            self.assertNotIn("Tinder", json.dumps(template, ensure_ascii=False))

    def test_wechat_target_binding_falls_back_to_message_list_identity_hints(self):
        binding = _target_binding_for_work_item(
            {"match_id": "match_wechat", "candidate_key": "wechat_ada"},
            {
                "schema_version": 1,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "wechat_ada",
                            "visible_name": "Ada",
                            "match_identity_hints": {
                                "visible_name": "Ada",
                                "conversation_fingerprint": "Ada dinner thread",
                            },
                        }
                    ]
                },
                "thread_observations": [
                    {
                        "candidate_key": "wechat_ada",
                        "observation": {"match_identity_hints": {}},
                    }
                ],
            },
        )

        self.assertEqual(binding["target_match_id"], "match_wechat")
        self.assertEqual(binding["candidate_key"], "wechat_ada")
        self.assertEqual(binding["visible_name"], "Ada")
        self.assertEqual(binding["required_visible_text"], ["Ada"])
        self.assertEqual(binding["conversation_fingerprint"], "Ada dinner thread")

    def test_tashuo_target_binding_carries_message_list_visual_relocation_evidence(self):
        binding = _target_binding_for_work_item(
            {
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_xiaoyaowan",
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_xiaoyaowan",
                    "conversation_fingerprint": "xiaoyaowan-slow-warm",
                    "thread_evidence": {
                        "observation_id": "obs_thread",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "xiaoyaowan:slow-warm",
                        "visual_anchor_hash": "0123456789abcdef",
                    },
                },
            },
            {
                "schema_version": 1,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "tashuo_xiaoyaowan",
                            "visible_name": "小药丸儿",
                            "message_list_evidence": {
                                "source_state": "tashuo_chat_list",
                                "selection_method": "message_list_visual_anchor_scan",
                                "visual_anchor_hash": "fedcba9876543210",
                                "visual_anchor_region": {"x1": 0.05, "y1": 0.29, "x2": 0.95, "y2": 0.39},
                                "tap_ratio": {"x": 0.45, "y": 0.34},
                            },
                        }
                    ]
                },
                "thread_observations": [],
            },
        )

        self.assertEqual(binding["binding_type"], "current_thread_visual_identity")
        self.assertEqual(binding["message_list_evidence"]["selection_method"], "message_list_visual_anchor_scan")
        self.assertEqual(binding["message_list_evidence"]["visual_anchor_hash"], "fedcba9876543210")
        self.assertEqual(binding["message_list_evidence"]["tap_ratio"], {"x": 0.45, "y": 0.34})

    def test_tashuo_target_binding_derives_current_thread_visual_identity_from_thread_screenshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screenshot_path = Path(temp_dir) / "tashuo_thread.png"
            screenshot_path.write_bytes(_tashuo_mac_ios_app_conversation_with_messages_png())

            binding = _target_binding_for_work_item(
                {"match_id": "match_tashuo", "candidate_key": "tashuo_haidian"},
                {
                    "schema_version": 1,
                    "message_list_snapshot": {"entries": []},
                    "thread_observations": [
                        {
                            "candidate_key": "tashuo_haidian",
                            "screenshot_ref": str(screenshot_path),
                            "assessment": {
                                "latest_inbound_fingerprint": "sha256:latest",
                            },
                            "observation": {
                                "observation_id": "obs_haidian",
                                "app_id": "tashuo",
                                "match_identity_hints": {
                                    "visible_name": "海淀大橙子",
                                    "conversation_fingerprint": "tashuo_haidian",
                                },
                            },
                        }
                    ],
                },
            )

        self.assertEqual(binding["binding_type"], "current_thread_visual_identity")
        self.assertEqual(binding["visible_name"], "海淀大橙子")
        self.assertEqual(binding["conversation_fingerprint"], "tashuo_haidian")
        self.assertEqual(binding["required_visible_text"], ["海淀大橙子"])
        self.assertEqual(binding["thread_evidence"]["observation_id"], "obs_haidian")
        self.assertEqual(binding["thread_evidence"]["screen_state"], "tashuo_conversation")
        self.assertEqual(binding["thread_evidence"]["latest_inbound_fingerprint"], "sha256:latest")
        self.assertTrue(binding["thread_evidence"]["visual_anchor_hash"])

    def test_fixture_host_loop_stage_mode_stages_message_without_recording_send_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"

            payload = self._run_script(
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )

            self.assertEqual(payload["status"], "staged_waiting_user_confirmation")
            self.assertEqual(payload["send_mode"], "stage")
            self.assertTrue((work_dir / "current_work_item.json").exists())
            work_item_id = payload["current_work_item"]["work_item_id"]
            self.assertTrue((work_dir / f"staged_verification.{work_item_id}.json").exists())
            self.assertTrue((data_dir / "audit" / "stage_results.jsonl").exists())
            self.assertFalse((data_dir / "audit" / "action_results.jsonl").exists())
            self.assertTrue(payload["stage_results_recorded"])
            stage_events = [
                json.loads(line)
                for line in (data_dir / "audit" / "stage_results.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(stage_events[0]["result_status"], "succeeded")
            self.assertIn("without recording send result", payload["stop_reason"])

    def test_tashuo_mac_ios_stage_mode_runs_harness_stage_draft_and_preserves_stage_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "是，感觉你这作息已经是夜间型选手了哈哈"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_stage",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="stage",
                    managed_gui_send=False,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=True,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                    initial_surface="message-list",
                    management_mode="conservative",
                    max_threads_per_cycle=1,
                    max_pages_per_cycle=1,
                    cycle_send_limit=1,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.update({
                "work_item_id": "work_tashuo_stage",
                "action_request_id": "act_tashuo_stage",
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_xiaoyaowan",
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_tashuo_stage",
                    target_match_id="match_tashuo",
                    payload_hash=payload_hash,
                ),
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_xiaoyaowan",
                    "visible_name": "小药丸儿",
                    "visual_anchor_hash": "0123456789abcdef",
                    "uses_header_ocr": False,
                },
            })
            recorded_result: dict[str, object] = {}
            stage_commands: list[tuple[str, ...]] = []

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if args[:3] == ("harness", "tashuo", "stage-draft"):
                    stage_commands.append(args)
                    self.assertIn("--runtime", args)
                    self.assertEqual(args[args.index("--runtime") + 1], "mac-ios-app")
                    text_path = Path(args[args.index("--text-file") + 1])
                    self.assertEqual(text_path.read_text(encoding="utf-8"), payload_text)
                    self.assertIn("--data-dir", args)
                    return {
                        "schema_version": 2,
                        "status": "ok",
                        "action": "stage_draft",
                        "app_id": "tashuo",
                        "harness_backend": "mac_ios_app",
                        "stage_attempt_status": "completed",
                        "staged_text_verified": True,
                        "staged_text_verification": {
                            "status": "verified",
                            "expected_payload_hash": payload_hash,
                            "expected_character_count": len(payload_text),
                            "screen_exact_text_ocr_verified": True,
                            "exact_text_ocr_verified": True,
                            "exact_text_ax_verified": False,
                            "screen": {
                                "path": str(work_dir / "harness" / "mac_ios_app.tashuo.after_stage_draft.delayed.png"),
                                "state": "tashuo_conversation",
                                "status": "ok",
                            },
                        },
                    }
                if args[:2] == ("operator", "record-stage-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "event_id": "stage_result_test",
                        "action_request_id": recorded_result["action_request_id"],
                        "result_status": recorded_result["result_status"],
                        "path": "audit/stage_results.jsonl",
                    }
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                result = supervisor._handle_send_message(work_item)

        self.assertEqual(result["status"], "staged_waiting_user_confirmation")
        self.assertEqual(len(stage_commands), 1)
        self.assertEqual(recorded_result["result_status"], "succeeded")
        self.assertEqual(recorded_result["stage_attempt_status"], "completed")
        self.assertEqual(recorded_result["staged_text_verification"]["status"], "verified")
        self.assertTrue(recorded_result["staged_text_verification"]["screen_exact_text_ocr_verified"])
        self.assertIn("screenshot_ref", recorded_result)
        self.assertFalse(recorded_result["evidence"]["sent"])
        self.assertFalse((data_dir / "audit" / "action_results.jsonl").exists())

    def test_host_loop_preflight_blocks_selected_runtime_scope_mismatch_before_cli_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            (data_dir / "runtime").mkdir(parents=True, exist_ok=True)
            self._write_json(data_dir / "runtime" / "session_scope.json", {
                "schema_version": 1,
                "status": "selected",
                "selected_app_id": "tashuo",
                "selected_runtime": "mac-ios-app",
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=None,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="stage",
                    managed_gui_send=False,
                    harness_runtime=None,
                    work_dir=work_dir,
                    max_steps=1,
                    once=True,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                    initial_surface="message-list",
                    management_mode="conservative",
                    max_threads_per_cycle=1,
                    max_pages_per_cycle=1,
                    cycle_send_limit=1,
                )
            )
            cli_calls = []

            def fake_run_cli_json(*args: str, **kwargs: object) -> dict[str, object]:
                cli_calls.append(args)
                return {"schema_version": 1, "status": "ok"}

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                with self.assertRaises(HostLoopError) as raised:
                    supervisor._preflight()

        self.assertIn("runtime_scope_mismatch", str(raised.exception))
        self.assertEqual(cli_calls, [])

    def test_tashuo_host_loop_preflight_requires_runtime_choice_before_cli_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=None,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="stage",
                    managed_gui_send=False,
                    harness_runtime=None,
                    work_dir=work_dir,
                    max_steps=1,
                    once=True,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                    initial_surface="message-list",
                    management_mode="conservative",
                    max_threads_per_cycle=1,
                    max_pages_per_cycle=1,
                    cycle_send_limit=1,
                )
            )
            cli_calls = []

            def fake_run_cli_json(*args: str, **kwargs: object) -> dict[str, object]:
                cli_calls.append(args)
                return {"schema_version": 1, "status": "ok"}

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                with self.assertRaises(HostLoopError) as raised:
                    supervisor._preflight()

        self.assertIn("runtime_scope_required", str(raised.exception))
        self.assertEqual(cli_calls, [])

    def test_fixture_message_list_initial_surface_does_not_call_real_harness_observe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            fixture_dir = root / "fixture"
            fixture_dir.mkdir()
            self._write_json(fixture_dir / "message_list_observation.json", {"schema_version": 1})
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=None,
                    goal=None,
                    availability=None,
                    app_id="tinder",
                    send_mode="stage",
                    managed_gui_send=False,
                    harness_runtime=None,
                    work_dir=work_dir,
                    max_steps=1,
                    once=True,
                    json=True,
                    fixture_host=fixture_dir,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                    initial_surface="auto",
                    management_mode="conservative",
                    max_threads_per_cycle=1,
                    max_pages_per_cycle=1,
                    cycle_send_limit=1,
                )
            )

            with patch.object(supervisor, "_run_cli_json", side_effect=AssertionError("real harness observe must not run")):
                surface = supervisor._initial_surface()

        self.assertEqual(surface, "message-list")

    def test_resume_send_work_item_starts_operator_session_before_handling(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "auth.json"
            self._write_json(auth_path, {"schema_version": 1, "authorization_id": "auth_resume"})
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item("hello", hashlib.sha256("hello".encode("utf-8")).hexdigest())
            work_item["work_item_id"] = "work_resume_send"
            self._write_json(work_dir / "current_work_item.json", work_item)
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="stage",
                    managed_gui_send=False,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=True,
                    json=True,
                    fixture_host=None,
                    wait_timeout=0,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                    initial_surface="current-thread",
                    management_mode="conservative",
                    max_threads_per_cycle=1,
                    max_pages_per_cycle=1,
                    cycle_send_limit=1,
                )
            )
            calls: list[object] = []

            def fake_start() -> dict[str, object]:
                calls.append("start")
                return {"schema_version": 1, "status": "active", "session_id": "session_resume"}

            def fake_handle(current: dict[str, object]) -> dict[str, object]:
                calls.append(("handle", supervisor.operator_session_active, current.get("work_item_id")))
                return supervisor._finish("staged_waiting_user_confirmation", "stage_resume_test", current=current)

            with (
                patch.object(supervisor, "_preflight", lambda: None),
                patch.object(supervisor, "_operator_session_status", return_value=None),
                patch.object(supervisor, "_start_operator_session", side_effect=fake_start),
                patch.object(supervisor, "_handle_send_message", side_effect=fake_handle),
            ):
                payload, exit_code = supervisor.run(resume=True)

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "staged_waiting_user_confirmation")
        self.assertEqual(calls, ["start", ("handle", True, "work_resume_send")])

    def test_run_reuses_active_operator_session_instead_of_restarting_wait_point(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "auth.json"
            self._write_json(auth_path, {"schema_version": 1, "authorization_id": "auth_active"})
            work_item = _wechat_managed_work_item("hello", hashlib.sha256("hello".encode("utf-8")).hexdigest())
            work_item["work_item_id"] = "work_active_send"
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="stage",
                    managed_gui_send=False,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=True,
                    json=True,
                    fixture_host=None,
                    wait_timeout=0,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                    initial_surface="current-thread",
                    management_mode="conservative",
                    max_threads_per_cycle=1,
                    max_pages_per_cycle=1,
                    cycle_send_limit=1,
                )
            )
            calls: list[object] = []

            def fake_run_cli_json(*args: str, **kwargs: object) -> dict[str, object]:
                calls.append(args)
                if args[:2] == ("operator", "next"):
                    return {"schema_version": 1, "status": "host_work_required", "work_item": work_item}
                raise AssertionError(f"unexpected cli call: {args}")

            def fail_start() -> dict[str, object]:
                raise AssertionError("host-loop run must not restart an active operator session")

            def fake_handle(current: dict[str, object]) -> dict[str, object]:
                return supervisor._finish("staged_waiting_user_confirmation", "stage_active_test", current=current)

            with (
                patch.object(supervisor, "_preflight", lambda: None),
                patch.object(supervisor, "_operator_session_status", return_value="active"),
                patch.object(supervisor, "_start_operator_session", side_effect=fail_start),
                patch.object(supervisor, "_run_cli_json", side_effect=fake_run_cli_json),
                patch.object(supervisor, "_handle_send_message", side_effect=fake_handle),
            ):
                payload, exit_code = supervisor.run()

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "staged_waiting_user_confirmation")
        self.assertEqual(payload["current_work_item"]["work_item_id"], "work_active_send")
        self.assertEqual(calls, [("operator", "next", "--data-dir", str(data_dir.resolve()))])

    def test_fixture_host_loop_current_thread_start_does_not_return_to_message_list_before_staging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            fixture_dir = root / "fixture"
            shutil.copytree(FIXTURE_DIR, fixture_dir)
            shutil.copyfile(
                fixture_dir / "threads" / "ada_1_preview_ada.json",
                fixture_dir / "current_thread_observation.json",
            )

            payload = self._run_script(
                "--fixture-host",
                str(fixture_dir),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )

            step_types = [step["work_item_type"] for step in payload["steps"]]
            self.assertEqual(payload["status"], "staged_waiting_user_confirmation")
            self.assertEqual(step_types[0], "observe_current_thread")
            self.assertNotIn("scan_message_list", step_types)
            self.assertNotIn("open_thread", step_types)
            self.assertIn("send_message", step_types)
            self.assertTrue((data_dir / "audit" / "stage_results.jsonl").exists())
            self.assertFalse((data_dir / "audit" / "action_results.jsonl").exists())

    def test_fixture_host_loop_blocks_with_target_profile_required_when_thread_profile_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            fixture_dir = root / "fixture"
            shutil.copytree(FIXTURE_DIR, fixture_dir)
            thread_path = fixture_dir / "threads" / "ada_1_preview_ada.json"
            thread_payload = json.loads(thread_path.read_text(encoding="utf-8"))
            thread_payload["observation"]["profile_observation"] = {
                "profile_text": "",
                "photo_cues": [],
                "hook_candidates": [],
                "review_status": "missing",
                "evidence": "Profile was not opened before drafting.",
            }
            self._write_json(thread_path, thread_payload)

            payload = self._run_script(
                "--fixture-host",
                str(fixture_dir),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["stop_reason"], "target_profile_required")
        self.assertEqual(payload["next_host_action"], "open_target_profile_and_ingest_memory")

    def test_confirm_staged_cancel_clears_pending_send_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            staged_payload = self._run_script(
                "run",
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )
            work_item_id = staged_payload["current_work_item"]["work_item_id"]

            cancel_payload = self._run_script(
                "confirm-staged",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--cancel",
                "--json",
            )
            status_payload = self._run_script(
                "status",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )

            self.assertEqual(cancel_payload["status"], "staged_cancelled")
            self.assertEqual(status_payload["status"], "idle")
            self.assertFalse((work_dir / "current_work_item.json").exists())
            self.assertFalse((data_dir / "operator" / "current_work_item.json").exists())
            self.assertFalse((work_dir / f"staged_verification.{work_item_id}.json").exists())

    def test_confirm_staged_action_result_is_idempotent_and_clears_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            staged_payload = self._run_script(
                "run",
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )
            work_item = staged_payload["current_work_item"]
            action_result_path = Path(temp_dir) / "action_result.json"
            self._write_json(action_result_path, _action_result_for_work_item(work_item))

            first_confirm = self._run_script(
                "confirm-staged",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--action-result",
                str(action_result_path),
                "--json",
            )
            status_payload = self._run_script(
                "status",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )
            second_confirm = self._run_script(
                "confirm-staged",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--action-result",
                str(action_result_path),
                "--json",
            )
            audit_events = [
                json.loads(line)
                for line in (data_dir / "audit" / "action_results.jsonl").read_text(encoding="utf-8").splitlines()
            ]

            self.assertEqual(first_confirm["status"], "confirmed")
            self.assertEqual(status_payload["status"], "idle")
            self.assertEqual(second_confirm["status"], "blocked")
            self.assertEqual(second_confirm["stop_reason"], "no_staged_send_work_item")
            self.assertEqual(len(audit_events), 1)
            self.assertFalse((work_dir / "current_work_item.json").exists())
            self.assertFalse((data_dir / "operator" / "current_work_item.json").exists())

    def test_confirm_staged_requires_valid_staged_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            staged_payload = self._run_script(
                "run",
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )
            work_item = staged_payload["current_work_item"]
            staged_path = work_dir / f"staged_verification.{work_item['work_item_id']}.json"
            staged_path.unlink()

            missing_payload = self._run_script(
                "confirm-staged",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )
            bad_staged = {
                "schema_version": 1,
                "verification_type": "staged_text",
                "action_request_id": work_item["action_request_id"],
                "match_id": work_item["match_id"],
                "candidate_key": work_item["candidate_key"],
                "expected_payload_hash": work_item["payload_hash"],
                "expected_payload_text": work_item["payload_text"],
                "result_status": "failed",
                "staged_text": work_item["payload_text"],
            }
            self._write_json(staged_path, bad_staged)
            failed_payload = self._run_script(
                "confirm-staged",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )

            self.assertEqual(missing_payload["status"], "blocked")
            self.assertEqual(missing_payload["stop_reason"], "staged_verification_required_before_confirmation")
            self.assertEqual(failed_payload["status"], "blocked")
            self.assertEqual(failed_payload["stop_reason"], "staged text was not verified as succeeded")
            self.assertFalse((data_dir / "audit" / "action_results.jsonl").exists())

    def test_fixture_host_loop_live_mode_requires_staged_verification_before_recording_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"

            payload = self._run_script(
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "live",
                "--max-steps",
                "8",
                "--json",
            )

            self.assertIn(payload["status"], {"completed", "waiting", "wait"})
            audit_path = data_dir / "audit" / "action_results.jsonl"
            self.assertTrue(audit_path.exists())
            events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["result_status"], "succeeded")
            self.assertTrue(payload["staged_verifications"])
            self.assertTrue(payload["action_results_recorded"])
            self.assertFalse(any(path.name.startswith("staged_verification.") for path in work_dir.glob("*.json")))
            self.assertTrue(any("staged_verification" in path.name for path in (work_dir / "consumed").iterdir()))
            self.assertIn("machine_report_path", payload)
            self.assertTrue(Path(payload["machine_report_path"]).exists())
            self.assertIn("human_report_path", payload)
            self.assertTrue(Path(payload["human_report_path"]).exists())
            self.assertEqual(payload["next_host_action"], "present_relationship_progress_report")
            report = payload["relationship_progress_report"]
            self.assertEqual(report["format"], "markdown")
            self.assertEqual(report["human_report_path"], payload["human_report_path"])
            self.assertIn("Conversation Plans", report["markdown"])
            self.assertIn("Next Priority Queue", report["markdown"])

    def test_live_mode_blocks_when_safety_is_paused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            self._run_cli(["safety", "pause", "--data-dir", str(data_dir), "--reason", "manual-stop", "--json"])

            payload = self._run_script(
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "live",
                "--max-steps",
                "8",
                "--json",
            )

            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["stop_reason"], "safety_paused")
            self.assertFalse((data_dir / "audit" / "action_results.jsonl").exists())

    def test_live_mode_requires_explicit_live_send_authorization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            auth_path = Path(temp_dir) / "auth_without_live.json"
            auth = json.loads((FIXTURE_DIR / "auth.json").read_text(encoding="utf-8"))
            auth.pop("live_send", None)
            self._write_json(auth_path, auth)

            payload = self._run_script(
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(auth_path),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "live",
                "--max-steps",
                "8",
                "--json",
            )

            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["stop_reason"], "live_send_authorization_required")
            self.assertFalse((data_dir / "audit" / "action_results.jsonl").exists())

    def test_live_mode_blocks_authorization_match_mismatch_before_action_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            auth_path = Path(temp_dir) / "auth_wrong_match.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
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
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tinder",
                    send_mode="live",
                    managed_gui_send=False,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = {
                "schema_version": 1,
                "work_item_id": "work_tinder_send",
                "work_item_type": "send_message",
                "action_request_id": "act_tinder_send",
                "match_id": "match_ada",
                "candidate_key": "tinder_ada",
                "payload_text": payload_text,
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
                "pre_action_observation_id": "obs_before",
                "target_profile_observation": {
                    "review_status": "observed",
                    "profile_text": "喜欢日料，周末常去看展。",
                    "photo_cues": [],
                    "hook_candidates": ["日料", "看展"],
                    "evidence": "Profile was reviewed before drafting.",
                },
                "requires_post_action_verification": True,
                "draft_review_id": "draft_review_fixture",
                "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_ada"},
            }
            staged_path = supervisor._work_file(work_item, "staged_verification")
            self._write_json(staged_path, {
                "schema_version": 1,
                "verification_type": "staged_text",
                "action_request_id": work_item["action_request_id"],
                "match_id": work_item["match_id"],
                "candidate_key": work_item["candidate_key"],
                "expected_payload_hash": payload_hash,
                "expected_payload_text": payload_text,
                "result_status": "succeeded",
                "staged_text": payload_text,
                "evidence": {"verification": "Input box text was checked before send."},
            })

            _write_draft_review_audit(data_dir, work_item)

            payload = supervisor._handle_send_message(work_item)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["stop_reason"], "authorization_match_not_allowed")
        self.assertFalse(any(path.name.startswith("action_result.") for path in work_dir.glob("*.json")))

    def test_managed_wechat_live_send_runs_harness_with_text_file_and_records_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "wechat_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
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
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="wechat",
                    send_mode="live",
                    managed_gui_send=True,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = {
                "schema_version": 1,
                "work_item_id": "work_wechat_send",
                "work_item_type": "send_message",
                "action_request_id": "act_wechat_send",
                "match_id": "match_wechat",
                "candidate_key": "wechat_ada",
                "payload_text": payload_text,
                "payload_hash": payload_hash,
                "precondition_hash": "pre_hash",
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_wechat_live",
                    target_match_id="match_wechat",
                    payload_hash=payload_hash,
                ),
                "pre_action_observation_id": "obs_before",
                "draft_review_id": "draft_review_fixture",
                "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                "planner_alignment": "ok",
                "conversation_stage": "rapport_building",
                "conversation_move": "warm_reciprocal_question",
                "target_profile_observation": {
                    "review_status": "observed",
                    "profile_text": "喜欢日料，周末常去看展。",
                    "photo_cues": [],
                    "hook_candidates": ["日料", "看展"],
                    "evidence": "Profile was reviewed before drafting.",
                },
                "requires_post_action_verification": True,
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_wechat"},
            }
            captured_commands: list[tuple[str, ...]] = []
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                captured_commands.append(args)
                if args[:3] == ("harness", "wechat", "send-message"):
                    self.assertIn("--text-file", args)
                    self.assertIn("--action-request", args)
                    self.assertNotIn(payload_text, args)
                    text_path = Path(args[args.index("--text-file") + 1])
                    action_path = Path(args[args.index("--action-request") + 1])
                    self.assertEqual(text_path.read_text(encoding="utf-8"), payload_text)
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    self.assertEqual(action_request["payload_hash"], payload_hash)
                    self.assertEqual(action_request["target_binding"]["required_visible_text"], ["Ada"])
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": "wechat",
                        "action": "send_message",
                        "draft_fingerprint": payload_hash,
                        "draft_character_count": len(payload_text),
                        "post_action_observation_id": "gui_post_send_1234",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_ocr_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                            "outbound_exact_text_ocr_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-06-12T00:00:00Z"}), patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(recorded_result["result_status"], "succeeded")
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_1234")
        self.assertTrue(recorded_result["evidence"]["managed_gui_send"])
        self.assertTrue(supervisor.staged_verifications)
        self.assertTrue(supervisor.action_results_recorded)
        self.assertFalse(any(path.name.startswith("managed_payload.") for path in work_dir.glob("*.txt")))
        self.assertFalse(any(path.name.startswith("managed_action_request.") for path in work_dir.glob("*.json")))
        self.assertTrue(any(args[:3] == ("harness", "wechat", "send-message") for args in captured_commands))

    def test_managed_wechat_live_send_sends_message_sequence_as_separate_harness_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "wechat_auth.json"
            messages = [
                "慢热联盟可以成立",
                "狼人杀这种局我一般也先观察一会儿",
                "熟了再开麦会比较自然",
            ]
            payload_text = "\n".join(messages)
            payload_hash = hashlib.sha256(
                json.dumps(
                    {"payload_format": "message_sequence", "messages": messages},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self._write_json(auth_path, {
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
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="wechat",
                    send_mode="live",
                    managed_gui_send=True,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = {
                "schema_version": 1,
                "work_item_id": "work_wechat_send_sequence",
                "work_item_type": "send_message",
                "action_request_id": "act_wechat_send_sequence",
                "match_id": "match_wechat",
                "candidate_key": "wechat_ada",
                "payload_text": payload_text,
                "payload_hash": payload_hash,
                "payload_format": "message_sequence",
                "payload_messages": [
                    {
                        "index": index,
                        "text": text,
                        "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "character_count": len(text),
                    }
                    for index, text in enumerate(messages, start=1)
                ],
                "precondition_hash": "pre_hash",
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_wechat_live",
                    target_match_id="match_wechat",
                    payload_hash=payload_hash,
                ),
                "pre_action_observation_id": "obs_before",
                "draft_review_id": "draft_review_fixture",
                "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
                "planner_alignment": "ok",
                "conversation_stage": "warmup",
                "conversation_move": "low_investment_repair",
                "target_profile_observation": {
                    "review_status": "observed",
                    "profile_text": "喜欢狼人杀。",
                    "photo_cues": [],
                    "hook_candidates": ["狼人杀"],
                    "evidence": "Profile was reviewed before drafting.",
                },
                "requires_post_action_verification": True,
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_wechat"},
            }
            sent_texts: list[str] = []
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if args[:3] == ("harness", "wechat", "send-message"):
                    text_path = Path(args[args.index("--text-file") + 1])
                    action_path = Path(args[args.index("--action-request") + 1])
                    message_text = text_path.read_text(encoding="utf-8")
                    sent_texts.append(message_text)
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    self.assertEqual(action_request["payload_text"], message_text)
                    self.assertEqual(action_request["payload_hash"], hashlib.sha256(message_text.encode("utf-8")).hexdigest())
                    self.assertNotEqual(action_request["payload_hash"], payload_hash)
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": "wechat",
                        "action": "send_message",
                        "draft_fingerprint": action_request["payload_hash"],
                        "draft_character_count": len(message_text),
                        "post_action_observation_id": f"gui_post_send_{len(sent_texts)}",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_ocr_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                            "outbound_exact_text_ocr_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-06-12T00:00:00Z"}), patch.object(
                supervisor,
                "_run_cli_json",
                fake_run_cli_json,
            ):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(sent_texts, messages)
        self.assertEqual(recorded_result["payload_hash"], payload_hash)
        self.assertEqual(recorded_result["message_count"], 3)
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_3")

    def test_managed_wechat_live_send_derives_target_binding_from_pending_thread_observation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "wechat_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
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
            })
            (data_dir / "operator").mkdir(parents=True, exist_ok=True)
            self._write_json(data_dir / "operator" / "pending_scan_batch.json", {
                "schema_version": 1,
                "session_id": "session_wechat",
                "app_id": "wechat",
                "thread_observations": [
                    {
                        "candidate_key": "wechat_ada",
                        "observation": {
                            "match_identity_hints": {
                                "visible_name": "Ada",
                                "conversation_fingerprint": "Ada latest dinner thread",
                            }
                        },
                    }
                ],
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="wechat",
                    send_mode="live",
                    managed_gui_send=True,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.pop("target_binding")
            observed_binding: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if args[:3] == ("harness", "wechat", "send-message"):
                    action_path = Path(args[args.index("--action-request") + 1])
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    observed_binding.update(action_request["target_binding"])
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": "wechat",
                        "action": "send_message",
                        "post_action_observation_id": "gui_post_send_1234",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_ocr_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                            "outbound_exact_text_ocr_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(observed_binding["target_match_id"], "match_wechat")
        self.assertEqual(observed_binding["candidate_key"], "wechat_ada")
        self.assertEqual(observed_binding["visible_name"], "Ada")
        self.assertEqual(observed_binding["required_visible_text"], ["Ada"])
        self.assertEqual(observed_binding["conversation_fingerprint"], "Ada latest dinner thread")

    def test_managed_wechat_live_send_blocks_when_outbound_evidence_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "wechat_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
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
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="wechat",
                    send_mode="live",
                    managed_gui_send=True,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if args[:3] == ("harness", "wechat", "send-message"):
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": "wechat",
                        "action": "send_message",
                        "post_action_observation_id": "gui_post_send_1234",
                        "evidence": {
                            "staged_text_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                        },
                    }
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stop_reason"], "managed_gui_send_verification_incomplete")
        self.assertFalse(supervisor.action_results_recorded)

    def test_managed_live_send_blocks_when_target_profile_was_not_observed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "wechat_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
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
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="wechat",
                    send_mode="live",
                    managed_gui_send=True,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item["target_profile_observation"] = {
                "review_status": "missing",
                "profile_text": "",
                "photo_cues": [],
                "hook_candidates": [],
                "evidence": "Profile has not been opened.",
            }

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and "send-message" in args:
                    raise AssertionError("target profile gate must block before harness send")
                if args[:2] == ("operator", "record-action-result"):
                    raise AssertionError("target profile gate must not record an action result")
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stop_reason"], "target_profile_required")
        self.assertEqual(result["next_host_action"], "open_target_profile_and_ingest_memory")
        self.assertEqual(result["action_results_recorded"], [])

    def test_managed_tinder_live_send_records_required_iphone_mirroring_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tinder_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
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
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tinder",
                    send_mode="live",
                    managed_gui_send=True,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item["match_id"] = "match_tinder"
            work_item["candidate_key"] = "tinder_ada"
            work_item["autonomous_audit_binding"] = _audit_binding(
                authorization_id="auth_tinder_live",
                target_match_id="match_tinder",
                payload_hash=payload_hash,
            )
            work_item["target_binding"] = {"required_visible_text": ["Ada"], "target_match_id": "match_tinder"}
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if args[:3] == ("harness", "tinder", "send-message"):
                    self.assertIn("--action-request", args)
                    action_path = Path(args[args.index("--action-request") + 1])
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    self.assertEqual(action_request["target_binding"]["required_visible_text"], ["Ada"])
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": "tinder",
                        "action": "send_message",
                        "post_action_observation_id": "gui_post_send_tinder_1234",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_ocr_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                            "outbound_exact_text_ocr_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(recorded_result["result_status"], "succeeded")
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_tinder_1234")
        self.assertTrue(recorded_result["evidence"]["managed_gui_send"])
        self.assertTrue(recorded_result["evidence"]["staged_exact_text_verified"])
        self.assertTrue(recorded_result["evidence"]["input_cleared_after_send"])
        self.assertTrue(recorded_result["evidence"]["outbound_message_verified"])
        self.assertTrue(recorded_result["evidence"]["outbound_exact_text_verified"])

    def test_managed_iphone_mirroring_live_send_waits_for_staged_host_visual_verification(self):
        for app_id, auth_id, match_id, candidate_key in (
            ("tinder", "auth_tinder_live", "match_tinder", "tinder_ada"),
            ("bumble", "auth_bumble_live", "match_bumble", "bumble_ada"),
        ):
            with self.subTest(app_id=app_id), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                data_dir = root / "data"
                work_dir = root / "work"
                auth_path = root / f"{app_id}_auth.json"
                payload_text = "hi"
                payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
                self._write_json(auth_path, {
                    "schema_version": 1,
                    "authorization_id": auth_id,
                    "scope": "send_chat_messages",
                    "app_id": app_id,
                    "expires_at": "2099-01-01T00:00:00Z",
                    "allowed_actions": ["send_message"],
                    "autonomous_send": True,
                    "live_send": True,
                    "requires_post_action_verification": True,
                    "revoked_at": None,
                })
                supervisor = HostLoopSupervisor(
                    argparse.Namespace(
                        data_dir=data_dir,
                        authorization=auth_path,
                        goal=None,
                        availability=None,
                        app_id=app_id,
                        send_mode="live",
                        managed_gui_send=True,
                        work_dir=work_dir,
                        max_steps=1,
                        once=False,
                        json=True,
                        fixture_host=None,
                        wait_timeout=None,
                        poll_interval=1.0,
                        adapter_package=None,
                        skill_package=None,
                    )
                )
                work_dir.mkdir(parents=True, exist_ok=True)
                work_item = _wechat_managed_work_item(payload_text, payload_hash)
                work_item["match_id"] = match_id
                work_item["candidate_key"] = candidate_key
                work_item["autonomous_audit_binding"] = _audit_binding(
                    authorization_id=auth_id,
                    target_match_id=match_id,
                    payload_hash=payload_hash,
                )
                work_item["target_binding"] = {"required_visible_text": ["Ada"], "target_match_id": match_id}

                def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                    if args[:3] == ("harness", app_id, "send-message"):
                        return {
                            "schema_version": 1,
                            "status": "needs_host_visual_verification",
                            "reason": "staged_text_requires_visual_verification",
                            "app_id": app_id,
                            "action": "send_message",
                            "draft_fingerprint": payload_hash,
                            "draft_character_count": len(payload_text),
                            "visual_verification_request": {
                                "schema_version": 1,
                                "verification_type": "staged_text_visual",
                                "expected_payload_hash": payload_hash,
                                "screen_path": f"harness/iphone_mirroring.{app_id}.after_stage_message.png",
                                "next_host_action": "visually_verify_staged_text_before_live_send",
                            },
                        }
                    if args[:2] == ("operator", "record-action-result"):
                        raise AssertionError("staged visual wait must not record a send result")
                    raise AssertionError(args)

                with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                    _write_draft_review_audit(data_dir, work_item)
                    result = supervisor._handle_managed_gui_send(work_item)

                self.assertEqual(result["status"], "waiting_for_host")
                self.assertEqual(result["stop_reason"], "staged_text_requires_visual_verification")
                self.assertEqual(result["next_host_action"], "visually_verify_staged_text_before_live_send")
                self.assertFalse(supervisor.action_results_recorded)
                self.assertEqual(
                    result["managed_gui_send"]["visual_verification_request"]["expected_payload_hash"],
                    payload_hash,
                )

    def test_managed_bumble_live_send_runs_bumble_harness_and_records_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "bumble_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_bumble_live",
                "scope": "send_chat_messages",
                "app_id": "bumble",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="bumble",
                    send_mode="live",
                    managed_gui_send=True,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item["match_id"] = "match_bumble"
            work_item["candidate_key"] = "bumble_ada"
            work_item["autonomous_audit_binding"] = _audit_binding(
                authorization_id="auth_bumble_live",
                target_match_id="match_bumble",
                payload_hash=payload_hash,
            )
            work_item["target_binding"] = {"required_visible_text": ["Ada"], "target_match_id": "match_bumble"}
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if args[:3] == ("harness", "bumble", "send-message"):
                    self.assertIn("--action-request", args)
                    action_path = Path(args[args.index("--action-request") + 1])
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    self.assertEqual(action_request["app_id"], "bumble")
                    self.assertEqual(action_request["target_binding"]["required_visible_text"], ["Ada"])
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": "bumble",
                        "action": "send_message",
                        "post_action_observation_id": "gui_post_send_bumble_1234",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_ocr_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                            "outbound_exact_text_ocr_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(recorded_result["result_status"], "succeeded")
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_bumble_1234")
        self.assertTrue(recorded_result["evidence"]["managed_gui_send"])
        self.assertTrue(recorded_result["evidence"]["outbound_message_verified"])

    def test_managed_tashuo_live_send_uses_mac_ios_runtime_when_structural_binding_and_evidence_pass(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item["match_id"] = "match_tashuo"
            work_item["candidate_key"] = "tashuo_ada"
            work_item["autonomous_audit_binding"] = _audit_binding(
                authorization_id="auth_tashuo_live",
                target_match_id="match_tashuo",
                payload_hash=payload_hash,
            )
            work_item["target_binding"] = {
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_tashuo",
                "candidate_key": "tashuo_ada",
                "visible_name": "Ada",
                "conversation_fingerprint": "ada-latest",
                "thread_evidence": {
                    "observation_id": "obs_before",
                    "screen_state": "tashuo_conversation",
                    "latest_inbound_fingerprint": "ada:in:latest",
                    "visual_anchor_hash": "0123456789abcdef",
                },
            }
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    self.assertIn("--runtime", args)
                    self.assertEqual(args[args.index("--runtime") + 1], "mac-ios-app")
                    self.assertIn("--action-request", args)
                    action_path = Path(args[args.index("--action-request") + 1])
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    self.assertEqual(action_request["app_id"], "tashuo")
                    self.assertEqual(action_request["target_binding"]["binding_type"], "current_thread_visual_identity")
                    return {
                        "schema_version": 2,
                        "status": "ok",
                        "app_id": "tashuo",
                        "harness_backend": "mac_ios_app",
                        "action": "send_message",
                        "post_action_observation_id": "gui_post_send_tashuo_mac_1234",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_verified": True,
                            "staged_exact_text_ocr_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                            "outbound_exact_text_ocr_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(recorded_result["result_status"], "succeeded")
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_tashuo_mac_1234")
        self.assertTrue(recorded_result["evidence"]["managed_gui_send"])
        self.assertTrue(recorded_result["evidence"]["outbound_message_verified"])

    def test_managed_tashuo_mac_ios_live_send_sends_message_sequence_as_ordered_gui_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            messages = [
                "慢热联盟可以成立",
                "不过我更好奇你做运营的时候，是不是也先观察局面",
                "等判断差不多了再开始出手",
            ]
            payload_text = "\n".join(messages)
            payload_hash = hashlib.sha256(
                json.dumps(
                    {"payload_format": "message_sequence", "messages": messages},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.update({
                "work_item_id": "work_tashuo_send_sequence",
                "action_request_id": "act_tashuo_send_sequence",
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_duoduo",
                "payload_format": "message_sequence",
                "payload_messages": [
                    {
                        "index": index,
                        "text": text,
                        "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "character_count": len(text),
                    }
                    for index, text in enumerate(messages, start=1)
                ],
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_tashuo_live",
                    target_match_id="match_tashuo",
                    payload_hash=payload_hash,
                ),
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_duoduo",
                    "visible_name": "朵朵",
                    "conversation_fingerprint": "duoduo-hi-nihao",
                    "thread_evidence": {
                        "observation_id": "obs_before",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in:nihao",
                        "visual_anchor_hash": "0123456789abcdef",
                    },
                },
            })
            progress_path = work_dir / "managed_sequence_progress.work_tashuo_send_sequence.json"
            sent_texts: list[str] = []
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    self.assertIn("--runtime", args)
                    self.assertEqual(args[args.index("--runtime") + 1], "mac-ios-app")
                    if not sent_texts:
                        self.assertTrue(progress_path.exists())
                        progress = json.loads(progress_path.read_text(encoding="utf-8"))
                        self.assertEqual(progress["sequence_started_at"], "2026-06-12T00:00:00Z")
                        self.assertEqual(progress["message_sequence_window_seconds"], 60)
                    self.assertEqual(kwargs.get("timeout_seconds"), 60.0)
                    text_path = Path(args[args.index("--text-file") + 1])
                    action_path = Path(args[args.index("--action-request") + 1])
                    message_text = text_path.read_text(encoding="utf-8")
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    sent_texts.append(message_text)
                    self.assertEqual(action_request["payload_format"], "single_message")
                    self.assertEqual(action_request["payload_text"], message_text)
                    self.assertEqual(action_request["payload_hash"], hashlib.sha256(message_text.encode("utf-8")).hexdigest())
                    self.assertEqual(action_request["target_binding"]["binding_type"], "current_thread_visual_identity")
                    return {
                        "schema_version": 2,
                        "status": "ok",
                        "app_id": "tashuo",
                        "harness_backend": "mac_ios_app",
                        "action": "send_message",
                        "post_action_observation_id": f"gui_post_send_tashuo_mac_{len(sent_texts)}",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_verified": True,
                            "staged_exact_text_ocr_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                            "outbound_exact_text_ocr_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-06-12T00:00:00Z"}), patch.object(
                supervisor,
                "_run_cli_json",
                fake_run_cli_json,
            ):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(sent_texts, messages)
        self.assertEqual(recorded_result["payload_hash"], payload_hash)
        self.assertEqual(recorded_result["message_count"], 3)
        self.assertEqual(recorded_result["payload_format"], "message_sequence")
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_tashuo_mac_3")
        self.assertEqual(recorded_result["message_sequence_window_seconds"], 60)
        self.assertEqual(recorded_result["message_sequence_started_at"], "2026-06-12T00:00:00Z")
        self.assertEqual(recorded_result["message_sequence_last_sent_at"], "2026-06-12T00:00:00Z")
        self.assertEqual(recorded_result["message_sequence_elapsed_seconds"], 0.0)
        self.assertTrue(recorded_result["evidence"]["message_sequence_within_window"])
        self.assertEqual(
            recorded_result["message_results"],
            [
                {
                    "index": 1,
                    "message_hash": hashlib.sha256(messages[0].encode("utf-8")).hexdigest(),
                    "character_count": len(messages[0]),
                    "post_action_observation_id": "gui_post_send_tashuo_mac_1",
                    "status": "ok",
                    "evidence": {
                        "staged_text_verified": True,
                        "staged_exact_text_verified": True,
                        "input_cleared_after_send": True,
                        "post_action_screen_captured": True,
                        "outbound_message_verified": True,
                        "outbound_exact_text_verified": True,
                    },
                    "sent_at": "2026-06-12T00:00:00Z",
                },
                {
                    "index": 2,
                    "message_hash": hashlib.sha256(messages[1].encode("utf-8")).hexdigest(),
                    "character_count": len(messages[1]),
                    "post_action_observation_id": "gui_post_send_tashuo_mac_2",
                    "status": "ok",
                    "evidence": {
                        "staged_text_verified": True,
                        "staged_exact_text_verified": True,
                        "input_cleared_after_send": True,
                        "post_action_screen_captured": True,
                        "outbound_message_verified": True,
                        "outbound_exact_text_verified": True,
                    },
                    "sent_at": "2026-06-12T00:00:00Z",
                },
                {
                    "index": 3,
                    "message_hash": hashlib.sha256(messages[2].encode("utf-8")).hexdigest(),
                    "character_count": len(messages[2]),
                    "post_action_observation_id": "gui_post_send_tashuo_mac_3",
                    "status": "ok",
                    "evidence": {
                        "staged_text_verified": True,
                        "staged_exact_text_verified": True,
                        "input_cleared_after_send": True,
                        "post_action_screen_captured": True,
                        "outbound_message_verified": True,
                        "outbound_exact_text_verified": True,
                    },
                    "sent_at": "2026-06-12T00:00:00Z",
                },
            ],
        )

    def test_managed_tashuo_mac_ios_message_sequence_failure_reports_completed_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            messages = ["第一条", "第二条", "第三条"]
            payload_text = "\n".join(messages)
            payload_hash = hashlib.sha256(
                json.dumps(
                    {"payload_format": "message_sequence", "messages": messages},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.update({
                "work_item_id": "work_tashuo_send_sequence_failure",
                "action_request_id": "act_tashuo_send_sequence_failure",
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_duoduo",
                "payload_format": "message_sequence",
                "payload_messages": [
                    {
                        "index": index,
                        "text": text,
                        "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "character_count": len(text),
                    }
                    for index, text in enumerate(messages, start=1)
                ],
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_tashuo_live",
                    target_match_id="match_tashuo",
                    payload_hash=payload_hash,
                ),
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_duoduo",
                    "conversation_fingerprint": "duoduo-hi-nihao",
                    "thread_evidence": {
                        "observation_id": "obs_before",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in:nihao",
                        "visual_anchor_hash": "0123456789abcdef",
                    },
                },
            })
            calls = 0

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                nonlocal calls
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    calls += 1
                    if calls == 1:
                        return {
                            "schema_version": 2,
                            "status": "ok",
                            "post_action_observation_id": "gui_post_send_tashuo_mac_1",
                            "evidence": {
                                "staged_text_verified": True,
                                "staged_exact_text_verified": True,
                                "input_cleared_after_send": True,
                                "post_action_screen_captured": True,
                                "outbound_message_verified": True,
                                "outbound_exact_text_verified": True,
                            },
                        }
                    return {
                        "schema_version": 2,
                        "status": "blocked",
                        "reason": "outbound_message_not_verified",
                        "evidence": {"staged_text_verified": True},
                    }
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "outbound_message_not_verified")
        self.assertEqual(result["completed_message_count"], 1)
        self.assertEqual(result["failed_message_index"], 2)
        self.assertEqual(result["message_results"][0]["post_action_observation_id"], "gui_post_send_tashuo_mac_1")
        self.assertEqual(calls, 2)

    def test_managed_tashuo_mac_ios_sequence_accepts_already_sent_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            messages = ["你好啊，接上了", "看你是做运营的，我有点好奇"]
            payload_text = "\n".join(messages)
            payload_hash = hashlib.sha256(
                json.dumps(
                    {"payload_format": "message_sequence", "messages": messages},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.update({
                "work_item_id": "work_tashuo_send_sequence_idempotent",
                "action_request_id": "act_tashuo_send_sequence_idempotent",
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_duoduo",
                "payload_format": "message_sequence",
                "payload_messages": [
                    {
                        "index": index,
                        "text": text,
                        "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "character_count": len(text),
                    }
                    for index, text in enumerate(messages, start=1)
                ],
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_tashuo_live",
                    target_match_id="match_tashuo",
                    payload_hash=payload_hash,
                ),
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_duoduo",
                    "conversation_fingerprint": "duoduo-hi-nihao",
                    "thread_evidence": {
                        "observation_id": "obs_before",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in:nihao",
                        "visual_anchor_hash": "0123456789abcdef",
                    },
                },
            })
            calls: list[str] = []
            recorded_result: dict[str, object] = {}
            second_action_request: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    text_path = Path(args[args.index("--text-file") + 1])
                    action_path = Path(args[args.index("--action-request") + 1])
                    message_text = text_path.read_text(encoding="utf-8")
                    calls.append(message_text)
                    if len(calls) == 1:
                        return {
                            "schema_version": 2,
                            "status": "ok",
                            "already_sent": True,
                            "post_action_observation_id": "gui_post_send_tashuo_mac_existing_1",
                            "current_thread_visual_anchor": {
                                "status": "ok",
                                "screen_state": "tashuo_conversation",
                                "visual_anchor_hash": "fedcba9876543210",
                                "visual_anchor_region": {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.84},
                            },
                            "evidence": {
                                "input_cleared_after_send": True,
                                "post_action_screen_captured": True,
                                "outbound_message_verified": True,
                                "outbound_exact_text_verified": True,
                                "outbound_exact_text_ax_verified": True,
                            },
                        }
                    second_action_request.update(json.loads(action_path.read_text(encoding="utf-8")))
                    return {
                        "schema_version": 2,
                        "status": "ok",
                        "post_action_observation_id": "gui_post_send_tashuo_mac_2",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                            "outbound_exact_text_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(calls, messages)
        self.assertTrue(recorded_result["message_results"][0]["already_sent"])
        self.assertFalse(recorded_result["message_results"][0]["evidence"]["staged_text_verified"])
        self.assertEqual(
            second_action_request["target_binding"]["thread_evidence"]["visual_anchor_hash"],
            "fedcba9876543210",
        )
        self.assertEqual(
            second_action_request["target_binding"]["thread_evidence"]["observation_id"],
            "gui_post_send_tashuo_mac_existing_1",
        )
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_tashuo_mac_2")

    def test_managed_tashuo_mac_ios_sequence_resume_skips_recorded_progress_prefix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            messages = ["第一条", "第二条", "第三条"]
            payload_text = "\n".join(messages)
            payload_hash = hashlib.sha256(
                json.dumps(
                    {"payload_format": "message_sequence", "messages": messages},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.update({
                "work_item_id": "work_tashuo_send_sequence_resume_progress",
                "action_request_id": "act_tashuo_send_sequence_resume_progress",
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_duoduo",
                "payload_format": "message_sequence",
                "payload_messages": [
                    {
                        "index": index,
                        "text": text,
                        "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "character_count": len(text),
                    }
                    for index, text in enumerate(messages, start=1)
                ],
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_tashuo_live",
                    target_match_id="match_tashuo",
                    payload_hash=payload_hash,
                ),
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_duoduo",
                    "conversation_fingerprint": "duoduo-progress",
                    "thread_evidence": {
                        "observation_id": "obs_before",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in",
                        "visual_anchor_hash": "old",
                    },
                },
            })
            progress_path = work_dir / "managed_sequence_progress.work_tashuo_send_sequence_resume_progress.json"
            self._write_json(progress_path, {
                "schema_version": 1,
                "work_item_id": work_item["work_item_id"],
                "action_request_id": work_item["action_request_id"],
                "payload_hash": payload_hash,
                "completed_message_count": 2,
                "sequence_started_at": "2026-06-12T00:00:00Z",
                "last_message_sent_at": "2026-06-12T00:00:10Z",
                "message_sequence_window_seconds": 60,
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_duoduo",
                    "conversation_fingerprint": "duoduo-progress",
                    "thread_evidence": {
                        "observation_id": "gui_post_send_2",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in",
                        "visual_anchor_hash": "fresh",
                    },
                },
                "message_results": [
                    {
                        "index": 1,
                        "message_hash": hashlib.sha256(messages[0].encode("utf-8")).hexdigest(),
                        "character_count": len(messages[0]),
                        "post_action_observation_id": "gui_post_send_1",
                        "status": "ok",
                        "evidence": {"outbound_exact_text_verified": True},
                    },
                    {
                        "index": 2,
                        "message_hash": hashlib.sha256(messages[1].encode("utf-8")).hexdigest(),
                        "character_count": len(messages[1]),
                        "post_action_observation_id": "gui_post_send_2",
                        "status": "ok",
                        "evidence": {"outbound_exact_text_verified": True},
                    },
                ],
            })
            sent_texts: list[str] = []
            recorded_result: dict[str, object] = {}
            third_action_request: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    text_path = Path(args[args.index("--text-file") + 1])
                    action_path = Path(args[args.index("--action-request") + 1])
                    sent_texts.append(text_path.read_text(encoding="utf-8"))
                    third_action_request.update(json.loads(action_path.read_text(encoding="utf-8")))
                    return {
                        "schema_version": 2,
                        "status": "ok",
                        "post_action_observation_id": "gui_post_send_3",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                            "outbound_exact_text_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-06-12T00:00:20Z"}), patch.object(
                supervisor,
                "_run_cli_json",
                fake_run_cli_json,
            ):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(sent_texts, ["第三条"])
        self.assertEqual(third_action_request["target_binding"]["thread_evidence"]["visual_anchor_hash"], "fresh")
        self.assertEqual(recorded_result["message_count"], 3)
        self.assertEqual(recorded_result["message_sequence_window_seconds"], 60)
        self.assertEqual(recorded_result["message_sequence_elapsed_seconds"], 20.0)
        self.assertTrue(recorded_result["evidence"]["message_sequence_within_window"])
        self.assertEqual(len(recorded_result["message_results"]), 3)
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_3")
        self.assertFalse(progress_path.exists())

    def test_managed_tashuo_mac_ios_sequence_resume_blocks_expired_window(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            messages = ["第一条", "第二条", "第三条"]
            payload_text = "\n".join(messages)
            payload_hash = hashlib.sha256(
                json.dumps(
                    {"payload_format": "message_sequence", "messages": messages},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.update({
                "work_item_id": "work_tashuo_send_sequence_expired_progress",
                "action_request_id": "act_tashuo_send_sequence_expired_progress",
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_xiaoyaowan",
                "payload_format": "message_sequence",
                "payload_messages": [
                    {
                        "index": index,
                        "text": text,
                        "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "character_count": len(text),
                    }
                    for index, text in enumerate(messages, start=1)
                ],
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_tashuo_live",
                    target_match_id="match_tashuo",
                    payload_hash=payload_hash,
                ),
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_xiaoyaowan",
                    "conversation_fingerprint": "xiaoyaowan-progress",
                    "thread_evidence": {
                        "observation_id": "obs_before",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "xiaoyaowan:in",
                        "visual_anchor_hash": "old",
                    },
                },
            })
            progress_path = work_dir / "managed_sequence_progress.work_tashuo_send_sequence_expired_progress.json"
            self._write_json(progress_path, {
                "schema_version": 1,
                "work_item_id": work_item["work_item_id"],
                "action_request_id": work_item["action_request_id"],
                "payload_hash": payload_hash,
                "completed_message_count": 1,
                "sequence_started_at": "2026-06-12T00:00:00Z",
                "last_message_sent_at": "2026-06-12T00:00:00Z",
                "message_sequence_window_seconds": 60,
                "message_results": [
                    {
                        "index": 1,
                        "message_hash": hashlib.sha256(messages[0].encode("utf-8")).hexdigest(),
                        "character_count": len(messages[0]),
                        "post_action_observation_id": "gui_post_send_1",
                        "status": "ok",
                        "evidence": {"outbound_exact_text_verified": True},
                        "sent_at": "2026-06-12T00:00:00Z",
                    },
                ],
            })

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    raise AssertionError("expired sequence must not continue sending")
                raise AssertionError(args)

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-06-12T00:01:01Z"}), patch.object(
                supervisor,
                "_run_cli_json",
                fake_run_cli_json,
            ):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)
            self.assertTrue(progress_path.exists())

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "message_sequence_window_expired")
        self.assertEqual(result["message_sequence_window_seconds"], 60)
        self.assertEqual(result["message_sequence_elapsed_seconds"], 61.0)
        self.assertEqual(result["completed_message_count"], 1)
        self.assertEqual(result["failed_message_index"], 2)
        self.assertEqual(result["next_host_action"], "observe_current_thread_and_replan_sequence")

    def test_managed_tashuo_live_send_waits_for_host_visual_verification_before_return_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "那我们俩算慢热同盟了，我也是刚开始话少一点，熟了会自然很多"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item["match_id"] = "match_tashuo"
            work_item["candidate_key"] = "tashuo_ada"
            work_item["autonomous_audit_binding"] = _audit_binding(
                authorization_id="auth_tashuo_live",
                target_match_id="match_tashuo",
                payload_hash=payload_hash,
            )
            work_item["target_binding"] = {
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_tashuo",
                "candidate_key": "tashuo_ada",
                "visible_name": "Ada",
                "conversation_fingerprint": "ada-latest",
                "thread_evidence": {
                    "observation_id": "obs_before",
                    "screen_state": "tashuo_conversation",
                    "latest_inbound_fingerprint": "ada:in:latest",
                    "visual_anchor_hash": "0123456789abcdef",
                },
            }

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    return {
                        "schema_version": 2,
                        "status": "needs_host_visual_verification",
                        "reason": "staged_text_requires_visual_verification",
                        "app_id": "tashuo",
                        "harness_backend": "mac_ios_app",
                        "action": "send_message",
                        "draft_fingerprint": payload_hash,
                        "draft_character_count": len(payload_text),
                        "staged_text_verification": {
                            "status": "needs_verification",
                            "reason": "staged_text_not_verified",
                            "expected_payload_hash": payload_hash,
                        },
                        "visual_verification_request": {
                            "schema_version": 1,
                            "verification_type": "staged_text_visual",
                            "expected_payload_hash": payload_hash,
                            "screen_path": "harness/mac_ios_app.tashuo.after_stage_message.png",
                            "input_crop_path": "harness/mac_ios_app.tashuo.after_stage_message.input_crop.png",
                            "next_host_action": "visually_verify_staged_text_before_live_send",
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    raise AssertionError("visual verification wait must not record a send result")
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertEqual(result["status"], "waiting_for_host")
        self.assertEqual(result["stop_reason"], "staged_text_requires_visual_verification")
        self.assertEqual(result["next_host_action"], "visually_verify_staged_text_before_live_send")
        self.assertFalse(supervisor.action_results_recorded)
        self.assertEqual(
            result["managed_gui_send"]["visual_verification_request"]["expected_payload_hash"],
            payload_hash,
        )

    def test_managed_tashuo_live_send_waits_for_outbound_host_visual_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "这条我居然漏到现在"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item["match_id"] = "match_tashuo"
            work_item["candidate_key"] = "tashuo_haidian_orange"
            work_item["autonomous_audit_binding"] = _audit_binding(
                authorization_id="auth_tashuo_live",
                target_match_id="match_tashuo",
                payload_hash=payload_hash,
            )
            work_item["target_binding"] = {
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_tashuo",
                "candidate_key": "tashuo_haidian_orange",
                "visible_name": "海淀大橙子",
                "conversation_fingerprint": "haidian-orange-latest",
                "thread_evidence": {
                    "observation_id": "obs_before",
                    "screen_state": "tashuo_conversation",
                    "latest_inbound_fingerprint": "haidian:in:latest",
                    "visual_anchor_hash": "0123456789abcdef",
                },
            }

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    return {
                        "schema_version": 2,
                        "status": "needs_host_visual_verification",
                        "reason": "outbound_message_requires_visual_verification",
                        "app_id": "tashuo",
                        "harness_backend": "mac_ios_app",
                        "action": "send_message",
                        "draft_fingerprint": payload_hash,
                        "draft_character_count": len(payload_text),
                        "post_action_observation_id": "gui_post_send_visual_1",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_verified": True,
                            "staged_exact_text_ax_verified": True,
                            "staged_exact_text_ocr_verified": False,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": False,
                            "outbound_exact_text_verified": False,
                            "outbound_exact_text_ax_verified": False,
                            "outbound_exact_text_ocr_verified": False,
                        },
                        "visual_verification_request": {
                            "schema_version": 1,
                            "verification_type": "outbound_message_visual",
                            "expected_payload_hash": payload_hash,
                            "post_screen_path": "harness/mac_ios_app.tashuo.after_send_message.png",
                            "post_action_observation_id": "gui_post_send_visual_1",
                            "ocr_status": "skipped",
                            "next_host_action": "visually_verify_outbound_message_after_live_send",
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    raise AssertionError("outbound visual wait must not record until host writes action_result")
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertEqual(result["status"], "waiting_for_host")
        self.assertEqual(result["stop_reason"], "outbound_message_requires_visual_verification")
        self.assertEqual(result["next_host_action"], "visually_verify_outbound_message_after_live_send_and_write_action_result")
        self.assertEqual(Path(result["expected_input"]).name, f"action_result.{work_item['work_item_id']}.json")
        self.assertEqual(result["managed_gui_send"]["visual_verification_request"]["ocr_status"], "skipped")
        self.assertFalse(supervisor.action_results_recorded)

    def test_managed_tashuo_sequence_outbound_visual_wait_saves_pending_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            messages = ["第一句", "第二句"]
            payload_text = "\n".join(messages)
            payload_hash = hashlib.sha256(
                json.dumps(
                    {"payload_format": "message_sequence", "messages": messages},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.update({
                "work_item_id": "work_tashuo_sequence_visual_wait",
                "action_request_id": "act_tashuo_sequence_visual_wait",
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_duoduo",
                "payload_format": "message_sequence",
                "payload_messages": [
                    {
                        "index": index,
                        "text": text,
                        "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "character_count": len(text),
                    }
                    for index, text in enumerate(messages, start=1)
                ],
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_tashuo_live",
                    target_match_id="match_tashuo",
                    payload_hash=payload_hash,
                ),
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_duoduo",
                    "conversation_fingerprint": "duoduo-sequence",
                    "thread_evidence": {
                        "observation_id": "obs_before",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in",
                        "visual_anchor_hash": "old",
                    },
                },
            })

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    text_path = Path(args[args.index("--text-file") + 1])
                    self.assertEqual(text_path.read_text(encoding="utf-8"), "第一句")
                    return {
                        "schema_version": 2,
                        "status": "needs_host_visual_verification",
                        "reason": "outbound_message_requires_visual_verification",
                        "post_action_observation_id": "gui_post_send_1",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": False,
                            "outbound_exact_text_verified": False,
                        },
                        "visual_verification_request": {
                            "schema_version": 1,
                            "verification_type": "outbound_message_visual",
                            "expected_payload_hash": hashlib.sha256("第一句".encode("utf-8")).hexdigest(),
                            "post_action_observation_id": "gui_post_send_1",
                            "ocr_status": "skipped",
                        },
                        "current_thread_visual_anchor": {
                            "status": "ok",
                            "screen_state": "tashuo_conversation",
                            "visual_anchor_hash": "fresh-after-first",
                        },
                    }
                raise AssertionError(args)

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-06-12T00:00:00Z"}), patch.object(
                supervisor,
                "_run_cli_json",
                fake_run_cli_json,
            ):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

            progress_path = work_dir / "managed_sequence_progress.work_tashuo_sequence_visual_wait.json"
            progress = json.loads(progress_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "waiting_for_host")
        self.assertEqual(result["stop_reason"], "outbound_message_requires_visual_verification")
        self.assertEqual(result["next_host_action"], "visually_verify_sequence_outbound_message_and_resume")
        self.assertEqual(Path(result["expected_input"]).name, "managed_sequence_visual_verification.work_tashuo_sequence_visual_wait.01.json")
        self.assertEqual(progress["completed_message_count"], 0)
        self.assertEqual(progress["sequence_started_at"], "2026-06-12T00:00:00Z")
        self.assertEqual(progress["last_message_sent_at"], "2026-06-12T00:00:00Z")
        self.assertEqual(progress["target_binding"]["thread_evidence"]["visual_anchor_hash"], "fresh-after-first")
        self.assertEqual(progress["message_results"][0]["status"], "visual_verification_pending")
        self.assertEqual(progress["message_results"][0]["post_action_observation_id"], "gui_post_send_1")
        self.assertTrue(progress["message_results"][0]["evidence"]["input_cleared_after_send"])
        self.assertFalse(supervisor.action_results_recorded)

    def test_managed_tashuo_sequence_visual_confirmation_resumes_without_resending_pending_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            messages = ["第一句", "第二句"]
            payload_text = "\n".join(messages)
            payload_hash = hashlib.sha256(
                json.dumps(
                    {"payload_format": "message_sequence", "messages": messages},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            message_hashes = [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in messages]
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.update({
                "work_item_id": "work_tashuo_sequence_visual_resume",
                "action_request_id": "act_tashuo_sequence_visual_resume",
                "match_id": "match_tashuo",
                "candidate_key": "tashuo_duoduo",
                "payload_format": "message_sequence",
                "payload_messages": [
                    {
                        "index": index,
                        "text": text,
                        "message_hash": message_hashes[index - 1],
                        "character_count": len(text),
                    }
                    for index, text in enumerate(messages, start=1)
                ],
                "autonomous_audit_binding": _audit_binding(
                    authorization_id="auth_tashuo_live",
                    target_match_id="match_tashuo",
                    payload_hash=payload_hash,
                ),
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_duoduo",
                    "conversation_fingerprint": "duoduo-sequence",
                    "thread_evidence": {
                        "observation_id": "obs_before",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in",
                        "visual_anchor_hash": "old",
                    },
                },
            })
            progress_path = work_dir / "managed_sequence_progress.work_tashuo_sequence_visual_resume.json"
            self._write_json(progress_path, {
                "schema_version": 1,
                "work_item_id": work_item["work_item_id"],
                "action_request_id": work_item["action_request_id"],
                "payload_hash": payload_hash,
                "completed_message_count": 0,
                "sequence_started_at": "2026-06-12T00:00:00Z",
                "last_message_sent_at": "2026-06-12T00:00:00Z",
                "message_sequence_window_seconds": 40,
                "target_binding": {
                    "binding_type": "current_thread_visual_identity",
                    "target_match_id": "match_tashuo",
                    "candidate_key": "tashuo_duoduo",
                    "conversation_fingerprint": "duoduo-sequence",
                    "thread_evidence": {
                        "observation_id": "gui_post_send_1",
                        "screen_state": "tashuo_conversation",
                        "latest_inbound_fingerprint": "duoduo:in",
                        "visual_anchor_hash": "fresh-after-first",
                    },
                },
                "message_results": [
                    {
                        "index": 1,
                        "message_hash": message_hashes[0],
                        "character_count": len(messages[0]),
                        "post_action_observation_id": "gui_post_send_1",
                        "status": "visual_verification_pending",
                        "sent_at": "2026-06-12T00:00:00Z",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": False,
                            "outbound_exact_text_verified": False,
                        },
                    },
                ],
            })
            visual_path = work_dir / "managed_sequence_visual_verification.work_tashuo_sequence_visual_resume.01.json"
            self._write_json(visual_path, {
                "schema_version": 1,
                "action_request_id": work_item["action_request_id"],
                "payload_hash": payload_hash,
                "message_index": 1,
                "message_hash": message_hashes[0],
                "post_action_observation_id": "gui_post_send_1",
                "result_status": "succeeded",
                "post_send_visible_text": "第一句",
                "evidence": {
                    "host_visual_outbound_exact_text_verified": True,
                    "input_cleared_after_send": True,
                    "post_action_screen_captured": True,
                },
            })
            sent_texts: list[str] = []
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    text_path = Path(args[args.index("--text-file") + 1])
                    sent_texts.append(text_path.read_text(encoding="utf-8"))
                    return {
                        "schema_version": 2,
                        "status": "ok",
                        "post_action_observation_id": "gui_post_send_2",
                        "evidence": {
                            "staged_text_verified": True,
                            "staged_exact_text_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                            "outbound_exact_text_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-06-12T00:00:10Z"}), patch.object(
                supervisor,
                "_run_cli_json",
                fake_run_cli_json,
            ):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(sent_texts, ["第二句"])
        self.assertEqual(recorded_result["message_count"], 2)
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_2")
        self.assertEqual(recorded_result["message_results"][0]["status"], "ok")
        self.assertTrue(recorded_result["message_results"][0]["evidence"]["outbound_exact_text_verified"])
        self.assertEqual(recorded_result["message_results"][1]["status"], "ok")
        self.assertFalse(progress_path.exists())
        self.assertFalse(visual_path.exists())

    def test_managed_tashuo_resume_records_visual_action_result_without_resending(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "这条我居然漏到现在"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item["match_id"] = "match_tashuo"
            work_item["candidate_key"] = "tashuo_haidian_orange"
            work_item["autonomous_audit_binding"] = _audit_binding(
                authorization_id="auth_tashuo_live",
                target_match_id="match_tashuo",
                payload_hash=payload_hash,
            )
            work_item["target_binding"] = {
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_tashuo",
                "candidate_key": "tashuo_haidian_orange",
                "visible_name": "海淀大橙子",
                "conversation_fingerprint": "haidian-orange-latest",
                "thread_evidence": {
                    "observation_id": "obs_before",
                    "screen_state": "tashuo_conversation",
                    "latest_inbound_fingerprint": "haidian:in:latest",
                    "visual_anchor_hash": "0123456789abcdef",
                },
            }
            result_path = work_dir / f"action_result.{work_item['work_item_id']}.json"
            self._write_json(result_path, {
                "action_request_id": work_item["action_request_id"],
                "action": "send_message",
                "target_match_id": "match_tashuo",
                "payload_hash": payload_hash,
                "precondition_hash": work_item.get("precondition_hash"),
                "autonomous_audit_binding": work_item.get("autonomous_audit_binding"),
                "pre_action_observation_id": work_item.get("pre_action_observation_id"),
                "post_action_observation_id": "gui_post_send_visual_1",
                "result_status": "succeeded",
                "evidence": {
                    "managed_gui_send": True,
                    "host_visual_outbound_exact_text_verified": True,
                    "ocr_status": "skipped",
                    "input_cleared_after_send": True,
                    "post_action_screen_captured": True,
                },
            })
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False, **kwargs: object) -> dict[str, object]:
                if len(args) >= 3 and args[0] == "harness" and args[1] == "tashuo" and "send-message" in args:
                    raise AssertionError("resume with action_result must not call harness send-message again")
                if args[:2] == ("operator", "record-action-result"):
                    recorded_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(recorded_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                _write_draft_review_audit(data_dir, work_item)
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(recorded_result["result_status"], "succeeded")
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_visual_1")
        self.assertTrue(supervisor.action_results_recorded)

    def test_tashuo_mac_ios_live_send_work_item_without_structural_binding_blocks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "hello"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item["match_id"] = "match_tashuo"
            work_item["candidate_key"] = "tashuo_ada"
            work_item["autonomous_audit_binding"] = _audit_binding(
                authorization_id="auth_tashuo_live",
                target_match_id="match_tashuo",
                payload_hash=payload_hash,
            )
            work_item["target_binding"] = {"required_visible_text": ["Ada"], "target_match_id": "match_tashuo"}

            result = supervisor._live_send_contract_block_reason(
                work_item,
                json.loads(auth_path.read_text(encoding="utf-8")),
            )

        self.assertEqual(result, "target_binding_structural_evidence_required")

    def test_tashuo_mac_ios_unmanaged_live_send_waits_for_action_result_after_verified_stage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "hello"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=False,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=0,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item["match_id"] = "match_tashuo"
            work_item["candidate_key"] = "tashuo_ada"
            work_item["autonomous_audit_binding"] = _audit_binding(
                authorization_id="auth_tashuo_live",
                target_match_id="match_tashuo",
                payload_hash=payload_hash,
            )
            work_item["target_binding"] = {
                "binding_type": "current_thread_visual_identity",
                "target_match_id": "match_tashuo",
                "candidate_key": "tashuo_ada",
                "visible_name": "Ada",
                "conversation_fingerprint": "ada-latest",
                "thread_evidence": {
                    "observation_id": "obs_before",
                    "screen_state": "tashuo_conversation",
                    "latest_inbound_fingerprint": "ada:in:latest",
                    "visual_anchor_hash": "0123456789abcdef",
                },
            }
            staged_path = supervisor._work_file(work_item, "staged_verification")
            self._write_json(staged_path, {
                "schema_version": 1,
                "verification_type": "staged_text",
                "action_request_id": work_item["action_request_id"],
                "match_id": work_item["match_id"],
                "candidate_key": work_item["candidate_key"],
                "expected_payload_hash": payload_hash,
                "expected_payload_text": payload_text,
                "result_status": "succeeded",
                "staged_text": payload_text,
                "evidence": {"verification": "Input box text was checked before send."},
            })

            _write_draft_review_audit(data_dir, work_item)

            payload = supervisor._handle_send_message(work_item)

        self.assertEqual(payload["status"], "waiting_for_host")
        self.assertEqual(payload["stop_reason"], "waiting_for_action_result")
        self.assertEqual(payload["next_host_action"], "paste_verify_send_then_record_action_result")

    def test_tashuo_mac_ios_live_send_work_item_lost_current_thread_binding_blocks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "tashuo_auth.json"
            payload_text = "hello"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_tashuo_live",
                "scope": "send_chat_messages",
                "app_id": "tashuo",
                "expires_at": "2099-01-01T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="tashuo",
                    send_mode="live",
                    managed_gui_send=True,
                    harness_runtime="mac-ios-app",
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    adapter_package=None,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item["match_id"] = "match_tashuo"
            work_item["candidate_key"] = "tashuo_ada"
            work_item["autonomous_audit_binding"] = _audit_binding(
                authorization_id="auth_tashuo_live",
                target_match_id="match_tashuo",
                payload_hash=payload_hash,
            )
            work_item.pop("target_binding")

            result = supervisor._live_send_contract_block_reason(
                work_item,
                json.loads(auth_path.read_text(encoding="utf-8")),
            )

        self.assertEqual(result, "target_binding_lost_current_thread")

    def test_blocked_send_work_item_uses_reason_specific_next_host_action(self):
        supervisor = HostLoopSupervisor(
            argparse.Namespace(
                data_dir=Path(tempfile.gettempdir()) / "dating_boost_next_action_review",
                authorization=None,
                goal=None,
                availability=None,
                app_id="tashuo",
                send_mode="live",
                managed_gui_send=True,
                harness_runtime="mac-ios-app",
                work_dir=Path(tempfile.gettempdir()) / "dating_boost_next_action_review_work",
                max_steps=1,
                once=False,
                json=True,
                fixture_host=None,
                wait_timeout=0,
                poll_interval=1.0,
                adapter_package=None,
                skill_package=None,
            )
        )
        work_item = {
            "schema_version": 1,
            "work_item_id": "work_tashuo_send",
            "work_item_type": "send_message",
            "action_request_id": "act_tashuo_send",
        }

        payload = supervisor._finish("blocked", "target_binding_structural_evidence_required", current=work_item)

        self.assertEqual(payload["next_host_action"], "provide_structural_target_binding_evidence")

    def test_once_mode_writes_template_and_waits_for_host_without_fixture(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            self._bootstrap_data_dir(data_dir)

            payload = self._run_script(
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth.json"),
                "--goal",
                str(FIXTURE_DIR / "goal.json"),
                "--availability",
                str(FIXTURE_DIR / "availability.json"),
                "--work-dir",
                str(work_dir),
                "--initial-surface",
                "message-list",
                "--once",
                "--json",
            )

            self.assertEqual(payload["status"], "waiting_for_host")
            self.assertEqual(payload["current_work_item"]["work_item_type"], "scan_message_list")
            work_item_id = payload["current_work_item"]["work_item_id"]
            self.assertEqual(
                Path(payload["expected_input"]).resolve(),
                (work_dir / f"message_list_observation.{work_item_id}.json").resolve(),
            )
            self.assertTrue((work_dir / f"message_list_observation.{work_item_id}.template.json").exists())

    def test_supervisor_does_not_inject_fixed_clock_without_fixture_host(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=Path(temp_dir) / "data",
                    authorization=None,
                    goal=None,
                    availability=None,
                    app_id="tinder",
                    send_mode="stage",
                    work_dir=Path(temp_dir) / "work",
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )

            def fake_run(command, cwd, check, capture_output, text, env):
                self.assertNotIn("DATING_BOOST_NOW", env)
                return subprocess.CompletedProcess(command, 0, stdout='{"schema_version": 1, "status": "ok"}', stderr="")

            with patch.dict(os.environ, {}, clear=True), patch("dating_boost.host_loop.subprocess.run", fake_run):
                payload = supervisor._run_cli_json("capabilities", "--json")

        self.assertEqual(payload["status"], "ok")

    def test_supervisor_preserves_structured_cli_error_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=Path(temp_dir) / "data",
                    authorization=None,
                    goal=None,
                    availability=None,
                    app_id="tinder",
                    send_mode="stage",
                    work_dir=Path(temp_dir) / "work",
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )

            def fake_run(command, cwd, check, capture_output, text, env):
                return subprocess.CompletedProcess(
                    command,
                    2,
                    stdout='{"schema_version": 1, "status": "error", "reason": "authorization_expired"}',
                    stderr="",
                )

            with patch("dating_boost.host_loop.subprocess.run", fake_run):
                with self.assertRaises(HostLoopCommandError) as raised:
                    supervisor._run_cli_json("operator", "session", "start")

        self.assertEqual(raised.exception.payload["reason"], "authorization_expired")

    def _bootstrap_data_dir(self, data_dir: Path) -> None:
        for argv in (
            [
                "init-profile",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "user_profile.json"),
            ],
            [
                "user",
                "ingest-profile",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "user_dating_profile.json"),
            ],
            [
                "user",
                "ingest-interview",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "user_self_interview.json"),
            ],
        ):
            exit_code, _payload = self._run_cli(argv)
            self.assertEqual(exit_code, 0)

    def _run_cli(self, argv):
        from contextlib import redirect_stdout
        from io import StringIO

        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        return exit_code, json.loads(output.getvalue())

    def _run_script(self, *args: str) -> dict:
        result = subprocess.run(
            [sys.executable, "scripts/operator_host_loop.py", *args],
            cwd=Path.cwd(),
            env=self._env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _action_result_for_work_item(work_item: dict) -> dict:
    return {
        "action_request_id": work_item["action_request_id"],
        "action": "send_message",
        "target_match_id": work_item["match_id"],
        "payload_hash": work_item["payload_hash"],
        "precondition_hash": work_item["precondition_hash"],
        "autonomous_audit_binding": work_item["autonomous_audit_binding"],
        "pre_action_observation_id": work_item.get("pre_action_observation_id"),
        "post_action_observation_id": f"{work_item.get('pre_action_observation_id')}_sent",
        "result_status": "succeeded",
        "evidence": {
            "post_send_visible_text": work_item["payload_text"],
            "staged_text_verified": True,
        },
    }


def _audit_binding(*, authorization_id: str, target_match_id: str, payload_hash: str, precondition_hash: str = "pre_hash") -> dict:
    return {
        "schema_version": 1,
        "binding_type": "autonomous_authorization",
        "authorization_id": authorization_id,
        "action": "send_message",
        "target_match_id": target_match_id,
        "payload_hash": payload_hash,
        "precondition_hash": precondition_hash,
    }


def _write_draft_review_audit(data_dir: Path, work_item: dict) -> None:
    review_id = str(work_item.get("draft_review_id") or "").strip()
    payload_hash = str(work_item.get("payload_hash") or "").strip()
    target_match_id = str(work_item.get("match_id") or work_item.get("target_match_id") or "").strip()
    if not review_id or not payload_hash or not target_match_id:
        return
    payload_messages = work_item.get("payload_messages")
    message_count = len(payload_messages) if isinstance(payload_messages, list) and payload_messages else 1
    path = data_dir / "audit" / "draft_reviews.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "review_id": review_id,
        "created_at": "2026-05-26T00:00:00Z",
        "mode": "managed_live",
        "target_match_id": target_match_id,
        "payload_hash": payload_hash,
        "payload_format": work_item.get("payload_format") or "single_message",
        "message_count": message_count,
        "status": "ok",
        "allowed_for_display": True,
        "allowed_for_stage": True,
        "allowed_for_managed_send": True,
        "requires_user_confirmation": False,
        "primary_reason": "passed",
        "finding_codes": [],
        "findings": [],
        "revision_hint_count": 0,
        "context_manifest": [],
        "draft_payload_hash": payload_hash,
        "context_pack_hash": "context_fixture",
        "draft_topic_labels": [],
        "draft_character_count": len(str(work_item.get("payload_text") or "")),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _wechat_managed_work_item(payload_text: str, payload_hash: str) -> dict:
    return {
        "schema_version": 1,
        "work_item_id": "work_wechat_send",
        "work_item_type": "send_message",
        "action_request_id": "act_wechat_send",
        "match_id": "match_wechat",
        "candidate_key": "wechat_ada",
        "payload_text": payload_text,
        "payload_hash": payload_hash,
        "precondition_hash": "pre_hash",
        "autonomous_audit_binding": _audit_binding(
            authorization_id="auth_wechat_live",
            target_match_id="match_wechat",
            payload_hash=payload_hash,
        ),
        "pre_action_observation_id": "obs_before",
        "target_profile_observation": {
            "review_status": "observed",
            "profile_text": "喜欢日料，周末常去看展。",
            "photo_cues": [],
            "hook_candidates": ["日料", "看展"],
            "evidence": "Profile was reviewed before drafting.",
        },
        "requires_post_action_verification": True,
        "draft_review_id": "draft_review_fixture",
        "policy": {"allowed": True, "draft_review_id": "draft_review_fixture"},
        "planner_alignment": "ok",
        "conversation_stage": "rapport_building",
        "conversation_move": "warm_reciprocal_question",
        "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_wechat"},
    }


if __name__ == "__main__":
    unittest.main()
