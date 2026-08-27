import hashlib
import json
import os
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.cli_sessions import _managed_run_authorization
from dating_boost.core.live_send_contract import validate_live_send_contract
from dating_boost.core.managed_run import JsonManagedRunStore, ManagedAuthorization, ManagedRun, ManagedRunConfig


class FakeManagedRunRuntime:
    def __init__(self):
        self.calls = []

    def current_run_id(self):
        self.calls.append(("current_run_id",))
        return "run_current"

    def start(self, config, *, run_id=None):
        self.calls.append(("start", config, run_id))
        return {"schema_version": 1, "status": "active", "run_id": run_id or "run_created"}

    def tick(self, run_id):
        self.calls.append(("tick", run_id))
        return {"schema_version": 1, "status": "waiting", "run_id": run_id}

    def run(self, run_id, *, max_steps, wait=False, poll_interval_seconds=1.0):
        if wait:
            self.calls.append(("run_wait", run_id, max_steps, poll_interval_seconds))
        else:
            self.calls.append(("run", run_id, max_steps))
        return {"schema_version": 1, "status": "waiting", "run_id": run_id}

    def status(self, run_id):
        self.calls.append(("status", run_id))
        return {"schema_version": 1, "status": "active", "run_id": run_id}

    def pause(self, run_id, *, reason):
        self.calls.append(("pause", run_id, reason))
        return {"schema_version": 1, "status": "paused", "run_id": run_id}

    def resume(self, run_id):
        self.calls.append(("resume", run_id))
        return {"schema_version": 1, "status": "active", "run_id": run_id}

    def stop(self, run_id, *, reason):
        self.calls.append(("stop", run_id, reason))
        return {"schema_version": 1, "status": "stopped", "run_id": run_id}


class ManageCliTests(unittest.TestCase):
    def test_capabilities_expose_managed_run_as_the_public_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, payload = self._run(["capabilities", "--data-dir", temp_dir, "--json"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["schema_versions"]["managed_run"], 1)
        self.assertEqual(
            payload["agent_native_capabilities"]["managed_run_lifecycle"],
            ["start", "status", "pause", "resume", "stop"],
        )
        self.assertEqual(
            payload["agent_native_capabilities"]["managed_run_host_runner_commands"],
            ["run", "tick"],
        )
        self.assertTrue(payload["agent_native_capabilities"]["managed_run_live_action_port_wired"])
        self.assertTrue(payload["agent_native_capabilities"]["managed_run_foreground_wait_loop"])
        self.assertFalse(payload["agent_native_capabilities"]["managed_run_start_spawns_runner"])
        self.assertFalse(payload["agent_native_capabilities"]["managed_run_background_daemon"])
        self.assertEqual(
            payload["agent_native_capabilities"]["managed_run_runner_supervision"],
            "host_process_required",
        )
        self.assertFalse(payload["agent_native_capabilities"]["managed_run_deep_doctor_each_start"])
        self.assertFalse(payload["agent_native_capabilities"]["managed_run_support_session_each_start"])
        self.assertFalse(payload["agent_native_capabilities"]["managed_run_environment_qualified"])
        self.assertEqual(
            payload["agent_native_capabilities"]["managed_run_canary_state_source"],
            "static_release_claim",
        )
        self.assertFalse(payload["agent_native_capabilities"]["managed_run_real_gui_canary_passed"])
        for command in ("start", "run", "tick", "status", "pause", "resume", "stop"):
            self.assertIn(f"manage {command}", payload["supported_commands"])
        self.assertIn("managed-session start", payload["supported_commands"])

    def test_unconfigured_runtime_is_an_explicit_block_not_a_false_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("dating_boost.cli_sessions._build_managed_run_runtime", return_value=None):
                exit_code, payload = self._run(["manage", "tick", "--data-dir", temp_dir, "--json"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "managed_run_runtime_not_configured")
        self.assertEqual(payload["next_host_action"], "register_managed_run_ports")

    def test_start_accepts_product_flags_without_a_config_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "dating_boost.core.managed_run_provider.managed_run_start_readiness",
                return_value=None,
            ), patch("dating_boost.cli_sessions._build_managed_run_runtime", return_value=None):
                exit_code, payload = self._run(
                    [
                        "manage",
                        "start",
                        "--data-dir",
                        temp_dir,
                        "--app-id",
                        "tashuo",
                        "--runtime",
                        "mac-ios-app",
                        "--duration-minutes",
                        "90",
                        "--send-budget",
                        "4",
                        "--no-nudge",
                        "--management-mode",
                        "conservative",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["reason"], "managed_run_runtime_not_configured")

    def test_start_defaults_to_the_single_flagship_app_and_runtime(self):
        runtime = FakeManagedRunRuntime()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "dating_boost.core.managed_run_provider.managed_run_start_readiness",
                return_value=None,
            ), patch("dating_boost.cli_sessions._build_managed_run_runtime", return_value=runtime):
                exit_code, payload = self._run(
                    [
                        "manage",
                        "start",
                        "--data-dir",
                        temp_dir,
                        "--run-id",
                        "run_default_flagship",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["run_id"], "run_default_flagship")
        _, config, _ = runtime.calls[-1]
        self.assertEqual(config.app_id, "tashuo")
        self.assertEqual(config.runtime, "mac-ios-app")
        self.assertFalse(config.nudge_enabled)

    def test_start_flags_bind_one_managed_authorization_and_budget(self):
        runtime = FakeManagedRunRuntime()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "dating_boost.core.managed_run_provider.managed_run_start_readiness",
                return_value=None,
            ), patch("dating_boost.cli_sessions._build_managed_run_runtime", return_value=runtime):
                exit_code, payload = self._run(
                    [
                        "manage",
                        "start",
                        "--data-dir",
                        temp_dir,
                        "--app-id",
                        "tashuo",
                        "--runtime",
                        "mac-ios-app",
                        "--duration-minutes",
                        "90",
                        "--send-budget",
                        "4",
                        "--no-nudge",
                        "--management-mode",
                        "conservative",
                        "--run-id",
                        "run_flags",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["run_id"], "run_flags")
        operation, config, run_id = runtime.calls[-1]
        self.assertEqual(operation, "start")
        self.assertEqual(run_id, "run_flags")
        self.assertEqual(config.app_id, "tashuo")
        self.assertEqual(config.runtime, "mac-ios-app")
        self.assertEqual(config.duration_minutes, 90)
        self.assertEqual(config.max_sends_per_run, 4)
        self.assertFalse(config.nudge_enabled)
        self.assertEqual(config.authorization.allowed_actions, ("send_message",))
        self.assertTrue(config.authorization.allow_all_targets)

    def test_start_blocks_before_runtime_when_autonomous_user_profile_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("dating_boost.cli_sessions._build_managed_run_runtime") as build_runtime:
                exit_code, payload = self._run(
                    [
                        "manage",
                        "start",
                        "--data-dir",
                        temp_dir,
                        "--app-id",
                        "tashuo",
                        "--runtime",
                        "mac-ios-app",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "needs_user_profile")
        self.assertEqual(payload["reason"], "autonomous_requires_user_profile")
        self.assertFalse(payload["user_profile_readiness"]["ready"])
        self.assertEqual(payload["next_host_action"], "complete_user_self_model")
        build_runtime.assert_not_called()

    def test_generated_authorization_has_a_bounded_existing_live_send_contract(self):
        args = Namespace(
            authorization=None,
            app_id="tashuo",
            runtime="mac-ios-app",
            duration_minutes=90,
            send_budget=4,
            nudge=False,
            management_mode="conservative",
        )
        with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-08-27T04:00:00Z"}):
            authorization = _managed_run_authorization(args)

        self.assertEqual(authorization["scope"], "send_chat_messages")
        self.assertEqual(authorization["created_at"], "2026-08-27T04:00:00Z")
        self.assertEqual(authorization["expires_at"], "2026-08-27T05:30:00Z")
        self.assertEqual(authorization["allowed_match_ids"], [])
        self.assertTrue(authorization["autonomous_send"])
        self.assertFalse(authorization["autonomous_nudge"])
        self.assertTrue(authorization["requires_post_action_verification"])
        self.assertEqual(authorization["quiet_hours"], [{"start": "23:00", "end": "08:00"}])
        self.assertIsNone(authorization["revoked_at"])

        draft_text = "收到，今天还挺有意思的"
        payload_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
        target_id = "match_contract"
        precondition_hash = "precondition_contract"
        action_request = {
            "action": "send_message",
            "action_request_id": "request_contract",
            "app_id": "tashuo",
            "target_match_id": target_id,
            "payload_hash": payload_hash,
            "requires_post_action_verification": True,
            "policy": {"allowed": True, "draft_review_id": "review_contract"},
            "draft_review_id": "review_contract",
            "target_binding": {
                "target_match_id": target_id,
                "candidate_key": "candidate_contract",
                "visible_name": "小明",
            },
            "candidate_key": "candidate_contract",
            "precondition_hash": precondition_hash,
            "autonomous_audit_binding": {
                "binding_type": "autonomous_authorization",
                "authorization_id": authorization["authorization_id"],
                "action": "send_message",
                "target_match_id": target_id,
                "payload_hash": payload_hash,
                "precondition_hash": precondition_hash,
            },
            "planner_alignment": "ok",
            "conversation_stage": "active_chat",
            "conversation_move": "reply",
        }
        reason = validate_live_send_contract(
            authorization,
            action_request,
            app_id="tashuo",
            draft_text=draft_text,
            data_dir=None,
            now="2026-08-27T04:01:00Z",
        )

        self.assertIsNone(reason)

    def test_existing_authorization_with_an_empty_target_list_is_not_silently_expanded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            authorization_path = Path(temp_dir) / "authorization.json"
            authorization_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "authorization_id": "auth_no_targets",
                        "scope": "send_chat_messages",
                        "app_id": "tashuo",
                        "runtime": "mac-ios-app",
                        "allowed_actions": ["send_message"],
                        "allowed_match_ids": [],
                        "autonomous_send": True,
                        "autonomous_nudge": True,
                        "live_send": True,
                        "requires_post_action_verification": True,
                        "created_at": "2026-08-27T04:00:00Z",
                        "expires_at": "2026-08-27T06:00:00Z",
                        "revoked_at": None,
                    }
                ),
                encoding="utf-8",
            )
            args = Namespace(
                authorization=authorization_path,
                app_id="tashuo",
                runtime="mac-ios-app",
            )
            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-08-27T04:00:00Z"}):
                with self.assertRaisesRegex(ValueError, "authorization_has_no_targets"):
                    _managed_run_authorization(args)

    def test_existing_authorization_rejects_malformed_quiet_hours_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            authorization_path = Path(temp_dir) / "authorization.json"
            authorization_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "authorization_id": "auth_bad_quiet_hours",
                        "scope": "send_chat_messages",
                        "app_id": "tashuo",
                        "runtime": "mac-ios-app",
                        "allowed_actions": ["send_message"],
                        "allowed_match_ids": ["match_1"],
                        "autonomous_send": True,
                        "live_send": True,
                        "requires_post_action_verification": True,
                        "quiet_hours": [{"start": "25:00", "end": "08:00"}],
                        "created_at": "2026-08-27T04:00:00Z",
                        "expires_at": "2026-08-27T06:00:00Z",
                        "revoked_at": None,
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-08-27T04:00:00Z"}), patch(
                "dating_boost.core.managed_run_provider.managed_run_start_readiness"
            ) as readiness, patch("dating_boost.cli_sessions._build_managed_run_runtime") as build_runtime:
                exit_code, payload = self._run(
                    [
                        "manage",
                        "start",
                        "--data-dir",
                        temp_dir,
                        "--app-id",
                        "tashuo",
                        "--runtime",
                        "mac-ios-app",
                        "--authorization",
                        str(authorization_path),
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "authorization_quiet_hours_invalid")
        readiness.assert_not_called()
        build_runtime.assert_not_called()

    def test_hidden_config_cannot_bypass_quiet_hours_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "managed-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "app_id": "tashuo",
                        "runtime": "mac-ios-app",
                        "authorization": {
                            "authorization_id": "auth_hidden_config",
                            "scope": "send_chat_messages",
                            "app_id": "tashuo",
                            "runtime": "mac-ios-app",
                            "allowed_actions": ["send_message"],
                            "allow_all_targets": True,
                            "autonomous_send": True,
                            "live_send": True,
                            "requires_post_action_verification": True,
                            "quiet_hours": [{"start": "23:99", "end": "08:00"}],
                            "expires_at": "2099-01-01T00:00:00Z",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "dating_boost.core.managed_run_provider.managed_run_start_readiness"
            ) as readiness, patch("dating_boost.cli_sessions._build_managed_run_runtime") as build_runtime:
                exit_code, payload = self._run(
                    [
                        "manage",
                        "start",
                        "--data-dir",
                        temp_dir,
                        "--config",
                        str(config_path),
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "authorization_quiet_hours_invalid")
        readiness.assert_not_called()
        build_runtime.assert_not_called()

    def test_start_help_exposes_the_product_contract_and_hides_development_config(self):
        output = StringIO()
        with self.assertRaises(SystemExit), redirect_stdout(output):
            main(["manage", "start", "--help"])
        help_text = output.getvalue()

        for flag in (
            "--app-id",
            "--runtime",
            "--duration-minutes",
            "--send-budget",
            "--quiet-hours",
            "--nudge",
            "--no-nudge",
        ):
            self.assertIn(flag, help_text)
        self.assertNotIn("--management-mode", help_text)
        self.assertNotIn("--authorization", help_text)
        self.assertNotIn("--config", help_text)

    def test_lifecycle_defaults_to_the_current_durable_run(self):
        runtime = FakeManagedRunRuntime()
        commands = [
            (["manage", "tick"], ("tick", "run_current")),
            (["manage", "run", "--max-steps", "7"], ("run", "run_current", 7)),
            (["manage", "status"], ("status", "run_current")),
            (["manage", "pause", "--reason", "user_break"], ("pause", "run_current", "user_break")),
            (["manage", "resume"], ("resume", "run_current")),
            (["manage", "stop", "--reason", "done"], ("stop", "run_current", "done")),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("dating_boost.cli_sessions._build_managed_run_runtime", return_value=runtime):
                for argv, expected_call in commands:
                    exit_code, payload = self._run([*argv, "--data-dir", temp_dir, "--json"])
                    self.assertEqual(exit_code, 0)
                    self.assertEqual(payload["run_id"], "run_current")
                    self.assertEqual(runtime.calls[-1], expected_call)

    def test_explicit_run_id_does_not_resolve_the_current_run(self):
        runtime = FakeManagedRunRuntime()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("dating_boost.cli_sessions._build_managed_run_runtime", return_value=runtime):
                exit_code, payload = self._run(
                    ["manage", "status", "--data-dir", temp_dir, "--run-id", "run_selected", "--json"]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["run_id"], "run_selected")
        self.assertEqual(runtime.calls, [("status", "run_selected")])

    def test_lifecycle_uses_the_durable_store_even_without_registered_ports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            port = object()
            runtime = ManagedRun(JsonManagedRunStore(data_dir), port, port, port)
            runtime.start(
                ManagedRunConfig(
                    app_id="tashuo",
                    runtime="mac-ios-app",
                    authorization=ManagedAuthorization(
                        authorization_id="auth_cli_lifecycle",
                        app_id="tashuo",
                        runtime="mac-ios-app",
                        allow_all_targets=True,
                    ),
                    max_sends_per_run=4,
                ),
                run_id="run_durable",
            )

            status_exit, status = self._run(["manage", "status", "--data-dir", temp_dir, "--json"])
            pause_exit, paused = self._run(["manage", "pause", "--data-dir", temp_dir, "--json"])
            resume_exit, resumed = self._run(["manage", "resume", "--data-dir", temp_dir, "--json"])
            stop_exit, stopped = self._run(["manage", "stop", "--data-dir", temp_dir, "--json"])

        self.assertEqual((status_exit, status["status"]), (0, "active"))
        self.assertEqual((pause_exit, paused["status"]), (0, "paused"))
        self.assertEqual((resume_exit, resumed["status"]), (0, "active"))
        self.assertEqual((stop_exit, stopped["status"]), (0, "stopped"))
        self.assertEqual(stopped["run_id"], "run_durable")

    def test_run_rejects_a_non_positive_step_limit_before_calling_runtime(self):
        runtime = FakeManagedRunRuntime()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("dating_boost.cli_sessions._build_managed_run_runtime", return_value=runtime):
                exit_code, payload = self._run(
                    ["manage", "run", "--data-dir", temp_dir, "--max-steps", "0", "--json"]
                )

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["reason"], "max_steps_must_be_positive")
        self.assertEqual(runtime.calls, [])

    def test_run_wait_forwards_polling_options_without_changing_non_wait_calls(self):
        runtime = FakeManagedRunRuntime()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("dating_boost.cli_sessions._build_managed_run_runtime", return_value=runtime):
                exit_code, payload = self._run(
                    [
                        "manage",
                        "run",
                        "--data-dir",
                        temp_dir,
                        "--max-steps",
                        "7",
                        "--wait",
                        "--poll-interval",
                        "0.25",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["run_id"], "run_current")
        self.assertEqual(runtime.calls[-1], ("run_wait", "run_current", 7, 0.25))

    def test_run_wait_rejects_a_non_positive_poll_interval(self):
        runtime = FakeManagedRunRuntime()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("dating_boost.cli_sessions._build_managed_run_runtime", return_value=runtime):
                exit_code, payload = self._run(
                    [
                        "manage",
                        "run",
                        "--data-dir",
                        temp_dir,
                        "--wait",
                        "--poll-interval",
                        "0",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["reason"], "poll_interval_must_be_positive")
        self.assertEqual(runtime.calls, [])

    @staticmethod
    def _run(argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        return exit_code, json.loads(output.getvalue())


if __name__ == "__main__":
    unittest.main()
