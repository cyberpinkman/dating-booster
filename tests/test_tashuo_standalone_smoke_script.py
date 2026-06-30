import importlib.util
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


def _load_smoke_module():
    path = Path("scripts/tashuo_mac_ios_standalone_smoke.py")
    spec = importlib.util.spec_from_file_location("tashuo_mac_ios_standalone_smoke", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _alpha_gate_stage_result() -> dict:
    return {
        "schema_version": 1,
        "event_type": "stage_result",
        "event_id": "stage_result_test",
        "action_request_id": "act_1",
        "target_match_id": "match_1",
        "payload_hash": "hash_1",
        "precondition_hash": "pre_hash_1",
        "pre_action_observation_id": "obs_1",
        "result_status": "succeeded",
        "evidence": {
            "stage_mode": True,
            "draft_text_hash": "draft_hash_1",
            "live_send_executed": False,
        },
        "stage_attempt_status": "completed",
        "staged_text_verified": True,
        "staged_text_verification": {"status": "verified", "exact_text_ax_verified": True},
        "target_verification": {"status": "ok"},
        "created_at": "2026-06-22T00:00:00Z",
    }


def _stage_recorded_tick_payload() -> dict:
    return {
        "status": "stage_recorded",
        "reason": "stage_recorded",
        "recorded": {
            "event_id": "stage_result_test",
            "action_request_id": "act_1",
            "target_match_id": "match_1",
            "payload_hash": "hash_1",
        },
    }


def _clear_input_payload() -> dict:
    return {
        "schema_version": 2,
        "status": "ok",
        "action": "clear-message-input",
        "input_cleared": True,
        "final_input_character_count": 0,
        "final_input_verification": {
            "schema_version": 1,
            "status": "ok",
            "verification_method": "unit_fake",
            "input_cleared": True,
            "final_input_character_count": 0,
            "reason": None,
        },
    }


def _write_alpha_gate_stage_result_for_cmd(cmd: list[str]) -> None:
    data_dir = Path(cmd[cmd.index("--data-dir") + 1])
    audit_dir = data_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "stage_results.jsonl").write_text(
        json.dumps(_alpha_gate_stage_result()) + "\n",
        encoding="utf-8",
    )


class TaShuoStandaloneSmokeScriptTests(unittest.TestCase):
    def test_smoke_runs_stage_only_standalone_commands(self):
        module = _load_smoke_module()
        calls = []

        def fake_run(cmd, check=False, capture_output=False, text=False, cwd=None, env=None, timeout=None):
            calls.append(cmd)
            payload = {"status": "ok"}
            if "tick" in cmd:
                _write_alpha_gate_stage_result_for_cmd(cmd)
                payload = _stage_recorded_tick_payload()
            if "clear-message-input" in cmd:
                payload = _clear_input_payload()
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                vision = root / "vision.json"
                vision.write_text(json.dumps({"status": "ok", "rows": []}), encoding="utf-8")
                backend = root / "backend.json"
                backend.write_text(json.dumps({"best_reply": "你好"}), encoding="utf-8")
                exit_code = module.main(
                    [
                        "--data-dir",
                        str(root / "data"),
                        "--output-dir",
                        str(root / "harness"),
                        "--authorization",
                        str(auth),
                        "--vision-backend",
                        "scripted",
                        "--scripted-vision-output",
                        str(vision),
                        "--backend",
                        "scripted",
                        "--scripted-backend-output",
                        str(backend),
                        "--json",
                    ]
                )
        finally:
            module.subprocess.run = original_run

        command_args = [call[3:] for call in calls]
        self.assertEqual(exit_code, 0)
        self.assertIn(["runtime", "select", "--data-dir", str(root / "data"), "--app-id", "tashuo", "--runtime", "mac-ios-app", "--json"], command_args)
        self.assertTrue(
            any(
                command[:2] == ["standalone-session", "start"]
                and "--app-id" in command
                and "tashuo" in command
                and "--runtime" in command
                and "mac-ios-app" in command
                and "--observation-source" in command
                and "live-gui" in command
                and "--send-mode" in command
                and "stage" in command
                for command in command_args
            )
        )
        self.assertIn(["standalone-session", "tick", "--data-dir", str(root / "data"), "--json"], command_args)
        self.assertIn(
            ["standalone-session", "stop", "--data-dir", str(root / "data"), "--reason", "smoke_complete", "--json"],
            command_args,
        )
        self.assertTrue(any(command[:4] == ["harness", "tashuo", "action", "clear-message-input"] for command in command_args))
        flattened = [item for command in command_args for item in command]
        self.assertNotIn("--managed-gui-send", flattened)

    def test_smoke_confirms_managed_session_config_before_start(self):
        module = _load_smoke_module()
        calls = []
        start_count = 0

        def fake_run(cmd, check=False, capture_output=False, text=False, cwd=None, env=None, timeout=None):
            nonlocal start_count
            calls.append(cmd)
            payload = {"status": "ok"}
            returncode = 0
            if cmd[3:5] == ["standalone-session", "start"]:
                start_count += 1
                if start_count == 1:
                    returncode = 2
                    payload = {
                        "status": "blocked",
                        "reason": "managed_session_config_confirmation_required",
                        "required_confirm_token": "managed-session-config:abc",
                    }
                else:
                    payload = {"status": "active"}
            if "tick" in cmd:
                _write_alpha_gate_stage_result_for_cmd(cmd)
                payload = _stage_recorded_tick_payload()
            if "clear-message-input" in cmd:
                payload = _clear_input_payload()
            return subprocess.CompletedProcess(cmd, returncode, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                exit_code = module.main(
                    [
                        "--data-dir",
                        str(root / "data"),
                        "--authorization",
                        str(auth),
                        "--vision-backend",
                        "openai",
                        "--backend",
                        "openai",
                        "--json",
                    ]
                )
        finally:
            module.subprocess.run = original_run

        start_commands = [call[3:] for call in calls if call[3:5] == ["standalone-session", "start"]]
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(start_commands), 2)
        self.assertNotIn("--config-confirm", start_commands[0])
        self.assertIn("--config-confirm", start_commands[1])
        self.assertIn("managed-session-config:abc", start_commands[1])

    def test_smoke_confirmation_retry_preserves_scripted_output_flags(self):
        module = _load_smoke_module()
        calls = []
        start_count = 0

        def fake_run(cmd, check=False, capture_output=False, text=False, cwd=None, env=None, timeout=None):
            nonlocal start_count
            calls.append(cmd)
            payload = {"status": "ok"}
            returncode = 0
            if cmd[3:5] == ["standalone-session", "start"]:
                start_count += 1
                if start_count == 1:
                    returncode = 2
                    payload = {
                        "status": "blocked",
                        "reason": "managed_session_config_confirmation_required",
                        "required_confirm_token": "managed-session-config:abc",
                    }
                else:
                    payload = {"status": "active"}
            if "tick" in cmd:
                _write_alpha_gate_stage_result_for_cmd(cmd)
                payload = _stage_recorded_tick_payload()
            if "clear-message-input" in cmd:
                payload = _clear_input_payload()
            return subprocess.CompletedProcess(cmd, returncode, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                vision = root / "vision.json"
                vision.write_text(json.dumps({"status": "ok", "rows": []}), encoding="utf-8")
                backend = root / "backend.json"
                backend.write_text(json.dumps({"best_reply": "你好"}), encoding="utf-8")
                exit_code = module.main(
                    [
                        "--data-dir",
                        str(root / "data"),
                        "--authorization",
                        str(auth),
                        "--vision-backend",
                        "scripted",
                        "--scripted-vision-output",
                        str(vision),
                        "--backend",
                        "scripted",
                        "--scripted-backend-output",
                        str(backend),
                        "--json",
                    ]
                )
        finally:
            module.subprocess.run = original_run

        start_commands = [call[3:] for call in calls if call[3:5] == ["standalone-session", "start"]]
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(start_commands), 2)
        confirmed_start = start_commands[1]
        self.assertIn("--scripted-vision-output", confirmed_start)
        self.assertIn(str(vision), confirmed_start)
        self.assertIn("--scripted-backend-output", confirmed_start)
        self.assertIn(str(backend), confirmed_start)
        self.assertIn("--config-confirm", confirmed_start)
        self.assertLess(
            confirmed_start.index(str(backend)),
            confirmed_start.index("--config-confirm"),
        )

    def test_smoke_passes_minimax_backend_and_vision_options(self):
        module = _load_smoke_module()
        calls = []

        def fake_run(cmd, check=False, capture_output=False, text=False, cwd=None, env=None, timeout=None):
            calls.append((cmd, env or {}))
            payload = {"status": "ok"}
            if cmd[3:5] == ["standalone-session", "start"]:
                payload = {"status": "active"}
            if "tick" in cmd:
                _write_alpha_gate_stage_result_for_cmd(cmd)
                payload = _stage_recorded_tick_payload()
            if "clear-message-input" in cmd:
                payload = _clear_input_payload()
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                env_file = root / ".env"
                env_file.write_text("MINIMAX_API_KEY=test-key\n", encoding="utf-8")
                exit_code = module.main(
                    [
                        "--data-dir",
                        str(root / "data"),
                        "--output-dir",
                        str(root / "harness"),
                        "--authorization",
                        str(auth),
                        "--vision-backend",
                        "minimax",
                        "--backend",
                        "minimax",
                        "--model",
                        "MiniMax-M3",
                        "--vision-model",
                        "MiniMax-M3",
                        "--minimax-api-key-env",
                        "MINIMAX_API_KEY",
                        "--env-file",
                        str(env_file),
                        "--json",
                    ]
                )
        finally:
            module.subprocess.run = original_run

        command_args = [call[0][3:] for call in calls]
        start_commands = [command for command in command_args if command[:2] == ["standalone-session", "start"]]
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(start_commands), 1)
        start = start_commands[0]
        self.assertIn("--vision-backend", start)
        self.assertIn("minimax", start)
        self.assertIn("--backend", start)
        self.assertIn("--model", start)
        self.assertIn("MiniMax-M3", start)
        self.assertIn("--vision-model", start)
        self.assertIn("--minimax-api-key-env", start)
        self.assertIn("--minimax-request-timeout-seconds", start)
        self.assertEqual(start[start.index("--minimax-request-timeout-seconds") + 1], "30.0")
        self.assertEqual(calls[0][1].get("MINIMAX_API_KEY"), "test-key")

    def test_smoke_defaults_to_minimax_m3(self):
        module = _load_smoke_module()
        calls = []

        def fake_run(cmd, check=False, capture_output=False, text=False, cwd=None, env=None, timeout=None):
            calls.append(cmd)
            payload = {"status": "ok"}
            if cmd[3:5] == ["standalone-session", "start"]:
                payload = {"status": "active"}
            if "tick" in cmd:
                _write_alpha_gate_stage_result_for_cmd(cmd)
                payload = _stage_recorded_tick_payload()
            if "clear-message-input" in cmd:
                payload = _clear_input_payload()
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                exit_code = module.main(
                    [
                        "--data-dir",
                        str(root / "data"),
                        "--authorization",
                        str(auth),
                        "--json",
                    ]
                )
        finally:
            module.subprocess.run = original_run

        start = next(call[3:] for call in calls if call[3:5] == ["standalone-session", "start"])
        self.assertEqual(exit_code, 0)
        self.assertIn("--vision-backend", start)
        self.assertIn("minimax", start)
        self.assertIn("--backend", start)
        self.assertIn("minimax", start)
        self.assertIn("--model", start)
        self.assertIn("MiniMax-M3", start)
        self.assertIn("--vision-model", start)
        self.assertIn("--minimax-base-url", start)
        self.assertIn("https://api.minimaxi.com/v1", start)
        self.assertIn("--minimax-request-timeout-seconds", start)
        self.assertEqual(start[start.index("--minimax-request-timeout-seconds") + 1], "30.0")

    def test_smoke_continues_while_ticks_make_structural_progress(self):
        module = _load_smoke_module()
        calls = []
        tick_count = 0

        def fake_run(cmd, check=False, capture_output=False, text=False, cwd=None, env=None, timeout=None):
            nonlocal tick_count
            calls.append(cmd)
            payload = {"status": "ok"}
            if cmd[3:5] == ["standalone-session", "start"]:
                payload = {"status": "active"}
            if cmd[3:5] == ["standalone-session", "tick"]:
                tick_count += 1
                if tick_count < 7:
                    payload = {
                        "status": "work_consumed",
                        "work_item_type": "open_thread",
                        "work_item_id": f"work_{tick_count}",
                        "ingested": {
                            "observation_id": f"obs_{tick_count}",
                            "match_id": f"match_{tick_count}",
                        },
                    }
                else:
                    _write_alpha_gate_stage_result_for_cmd(cmd)
                    payload = _stage_recorded_tick_payload()
            if "clear-message-input" in cmd:
                payload = _clear_input_payload()
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--authorization",
                            str(auth),
                            "--vision-backend",
                            "openai",
                            "--backend",
                            "openai",
                            "--json",
                        ]
                    )
        finally:
            module.subprocess.run = original_run

        payload = json.loads(stdout.getvalue())
        tick_commands = [call for call in calls if call[3:5] == ["standalone-session", "tick"]]
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(len(tick_commands), 7)

    def test_smoke_blocks_when_tick_repeats_without_progress(self):
        module = _load_smoke_module()
        calls = []

        def fake_run(cmd, check=False, capture_output=False, text=False, cwd=None, env=None, timeout=None):
            calls.append(cmd)
            payload = {"status": "ok"}
            if cmd[3:5] == ["standalone-session", "start"]:
                payload = {"status": "active"}
            if cmd[3:5] == ["standalone-session", "tick"]:
                payload = {
                    "status": "work_consumed",
                    "work_item_type": "open_thread",
                    "work_item_id": "same_work",
                    "ingested": {"observation_id": "same_observation", "match_id": "same_match"},
                }
            if "clear-message-input" in cmd:
                payload = _clear_input_payload()
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--authorization",
                            str(auth),
                            "--vision-backend",
                            "openai",
                            "--backend",
                            "openai",
                            "--json",
                        ]
                    )
        finally:
            module.subprocess.run = original_run

        payload = json.loads(stdout.getvalue())
        tick_commands = [call for call in calls if call[3:5] == ["standalone-session", "tick"]]
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "standalone_tick_no_progress:work_consumed")
        self.assertEqual(len(tick_commands), 3)

    def test_smoke_reports_operator_no_work_detail_with_priority_queue(self):
        module = _load_smoke_module()
        calls = []

        def fake_run(cmd, check=False, capture_output=False, text=False, cwd=None, env=None, timeout=None):
            calls.append(cmd)
            payload = {"status": "ok"}
            if cmd[3:5] == ["standalone-session", "start"]:
                payload = {"status": "active"}
            if cmd[3:5] == ["standalone-session", "tick"]:
                payload = {
                    "status": "no_work",
                    "managed_session": {
                        "operator": {
                            "work_item": {
                                "work_item_type": "wait",
                                "reason": "no_eligible_operator_work",
                                "next_priority_queue": [
                                    {"candidate_key": "row_1", "match_id": "match_1", "state": "needs_thread_scan"}
                                ],
                            }
                        }
                    },
                }
            if "clear-message-input" in cmd:
                payload = _clear_input_payload()
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--authorization",
                            str(auth),
                            "--vision-backend",
                            "openai",
                            "--backend",
                            "openai",
                            "--json",
                        ]
                    )
        finally:
            module.subprocess.run = original_run

        payload = json.loads(stdout.getvalue())
        tick_commands = [call for call in calls if call[3:5] == ["standalone-session", "tick"]]
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "standalone_tick_no_work:no_eligible_operator_work_with_priority_queue")
        self.assertEqual(len(tick_commands), 1)

    def test_smoke_reports_blocked_tick_payload_when_tick_command_returns_nonzero(self):
        module = _load_smoke_module()
        calls = []

        def fake_run(cmd, check=False, capture_output=False, text=False, cwd=None, env=None, timeout=None):
            calls.append(cmd)
            payload = {"status": "ok"}
            returncode = 0
            if cmd[3:5] == ["standalone-session", "start"]:
                payload = {"status": "active"}
            if "tick" in cmd:
                payload = {
                    "status": "blocked",
                    "reason": "observation_capture_failed",
                    "error_type": "AuthenticationError",
                    "error_message": "invalid api key (2049)",
                    "work_item_type": "scan_message_list",
                }
                returncode = 2
            if "clear-message-input" in cmd:
                payload = _clear_input_payload()
            return subprocess.CompletedProcess(cmd, returncode, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--authorization",
                            str(auth),
                            "--vision-backend",
                            "openai",
                            "--backend",
                            "openai",
                            "--json",
                        ]
                    )
        finally:
            module.subprocess.run = original_run

        payload = json.loads(stdout.getvalue())
        tick_step = next(step for step in payload["steps"] if step["cmd"][:2] == ["standalone-session", "tick"])
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "observation_capture_failed")
        self.assertEqual(tick_step["error_type"], "AuthenticationError")
        self.assertEqual(tick_step["error_message"], "invalid api key (2049)")
        command_args = [call[3:] for call in calls]
        stop_index = next(index for index, command in enumerate(command_args) if command[:2] == ["standalone-session", "stop"])
        cleanup_index = next(index for index, command in enumerate(command_args) if command[:4] == ["harness", "tashuo", "action", "clear-message-input"])
        self.assertLess(stop_index, cleanup_index)

    def test_smoke_reports_command_timeout_and_stops_session(self):
        module = _load_smoke_module()
        calls = []

        def fake_run(cmd, check=False, capture_output=False, text=False, cwd=None, env=None, timeout=None):
            calls.append((cmd, timeout))
            payload = {"status": "ok"}
            if cmd[3:5] == ["standalone-session", "start"]:
                payload = {"status": "active"}
            if cmd[3:5] == ["standalone-session", "tick"]:
                raise subprocess.TimeoutExpired(cmd, timeout)
            if "clear-message-input" in cmd:
                payload = _clear_input_payload()
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--authorization",
                            str(auth),
                            "--vision-backend",
                            "openai",
                            "--backend",
                            "openai",
                            "--step-timeout-seconds",
                            "7",
                            "--json",
                        ]
                    )
        finally:
            module.subprocess.run = original_run

        payload = json.loads(stdout.getvalue())
        tick_step = next(step for step in payload["steps"] if step["cmd"][:2] == ["standalone-session", "tick"])
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "command_timeout:standalone-session tick")
        self.assertEqual(tick_step["reason"], "command_timeout:standalone-session tick")
        self.assertEqual(tick_step["timeout_seconds"], 7.0)
        command_args = [call[0][3:] for call in calls]
        stop_index = next(index for index, command in enumerate(command_args) if command[:2] == ["standalone-session", "stop"])
        cleanup_index = next(index for index, command in enumerate(command_args) if command[:4] == ["harness", "tashuo", "action", "clear-message-input"])
        self.assertLess(stop_index, cleanup_index)

    def test_smoke_keyboard_interrupt_returns_json_and_skips_gui_cleanup(self):
        module = _load_smoke_module()
        calls = []

        def fake_run(cmd, check=False, capture_output=False, text=False, cwd=None, env=None, timeout=None):
            calls.append(cmd)
            payload = {"status": "ok"}
            if cmd[3:5] == ["standalone-session", "start"]:
                payload = {"status": "active"}
            if cmd[3:5] == ["standalone-session", "tick"]:
                raise KeyboardInterrupt
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--authorization",
                            str(auth),
                            "--vision-backend",
                            "openai",
                            "--backend",
                            "openai",
                            "--json",
                        ]
                    )
        finally:
            module.subprocess.run = original_run

        payload = json.loads(stdout.getvalue())
        command_args = [call[3:] for call in calls]
        tick_step = next(step for step in payload["steps"] if step["cmd"][:2] == ["standalone-session", "tick"])
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "standalone_smoke_interrupted_by_user")
        self.assertEqual(tick_step["reason"], "command_interrupted:standalone-session tick")
        self.assertEqual(tick_step["error_type"], "KeyboardInterrupt")
        self.assertTrue(any(command[:2] == ["standalone-session", "stop"] for command in command_args))
        self.assertFalse(any(command[:4] == ["harness", "tashuo", "action", "clear-message-input"] for command in command_args))
        self.assertEqual(payload["final_input_cleanup"]["reason"], "final_input_cleanup_skipped_after_user_interrupt")
        self.assertTrue(payload["final_input_cleanup"]["skipped"])

    def test_smoke_stop_interrupt_returns_json_and_skips_gui_cleanup(self):
        module = _load_smoke_module()
        calls = []

        def fake_run(cmd, check=False, capture_output=False, text=False, cwd=None, env=None, timeout=None):
            calls.append(cmd)
            payload = {"status": "ok"}
            if cmd[3:5] == ["standalone-session", "start"]:
                payload = {"status": "active"}
            if cmd[3:5] == ["standalone-session", "tick"]:
                _write_alpha_gate_stage_result_for_cmd(cmd)
                payload = _stage_recorded_tick_payload()
            if cmd[3:5] == ["standalone-session", "stop"]:
                raise KeyboardInterrupt
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--authorization",
                            str(auth),
                            "--vision-backend",
                            "openai",
                            "--backend",
                            "openai",
                            "--json",
                        ]
                    )
        finally:
            module.subprocess.run = original_run

        payload = json.loads(stdout.getvalue())
        command_args = [call[3:] for call in calls]
        stop_step = next(step for step in payload["steps"] if step["cmd"][:2] == ["standalone-session", "stop"])
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "standalone_smoke_interrupted_by_user")
        self.assertEqual(stop_step["reason"], "command_interrupted:standalone-session stop")
        self.assertEqual(stop_step["error_type"], "KeyboardInterrupt")
        self.assertFalse(any(command[:4] == ["harness", "tashuo", "action", "clear-message-input"] for command in command_args))
        self.assertEqual(payload["final_input_cleanup"]["reason"], "final_input_cleanup_skipped_after_user_interrupt")

    def test_smoke_cleanup_interrupt_returns_json_and_blocks_success(self):
        module = _load_smoke_module()
        calls = []

        def fake_run(cmd, check=False, capture_output=False, text=False, cwd=None, env=None, timeout=None):
            calls.append(cmd)
            payload = {"status": "ok"}
            if cmd[3:5] == ["standalone-session", "start"]:
                payload = {"status": "active"}
            if cmd[3:5] == ["standalone-session", "tick"]:
                _write_alpha_gate_stage_result_for_cmd(cmd)
                payload = _stage_recorded_tick_payload()
            if cmd[3:7] == ["harness", "tashuo", "action", "clear-message-input"]:
                raise KeyboardInterrupt
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--authorization",
                            str(auth),
                            "--vision-backend",
                            "openai",
                            "--backend",
                            "openai",
                            "--json",
                        ]
                    )
        finally:
            module.subprocess.run = original_run

        payload = json.loads(stdout.getvalue())
        cleanup_step = next(step for step in payload["steps"] if step["cmd"][:4] == ["harness", "tashuo", "action", "clear-message-input"])
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "final_input_cleanup_interrupted_by_user")
        self.assertEqual(payload["final_input_cleanup"]["reason"], "final_input_cleanup_interrupted_by_user")
        self.assertEqual(cleanup_step["reason"], "command_interrupted:harness tashuo")
        self.assertEqual(cleanup_step["error_type"], "KeyboardInterrupt")

    def test_smoke_blocks_stage_recorded_without_alpha_gate_audit_evidence(self):
        module = _load_smoke_module()

        def fake_run(cmd, check=False, capture_output=False, text=False, cwd=None, env=None, timeout=None):
            payload = {"status": "ok"}
            if cmd[3:5] == ["standalone-session", "start"]:
                payload = {"status": "active"}
            if cmd[3:5] == ["standalone-session", "tick"]:
                payload = _stage_recorded_tick_payload()
            if "clear-message-input" in cmd:
                payload = _clear_input_payload()
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        module.subprocess.run = fake_run
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--authorization",
                            str(auth),
                            "--vision-backend",
                            "openai",
                            "--backend",
                            "openai",
                            "--json",
                        ]
                    )
        finally:
            module.subprocess.run = original_run

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "alpha_gate_stage_result_missing")
        self.assertEqual(payload["alpha_release_gate"]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
