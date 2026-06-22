import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


def _load_doctor_module():
    path = Path("scripts/tashuo_mac_ios_standalone_doctor.py")
    spec = importlib.util.spec_from_file_location("tashuo_mac_ios_standalone_doctor", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TaShuoStandaloneDoctorScriptTests(unittest.TestCase):
    def test_doctor_loads_env_and_reports_minimax_auth_failure(self):
        module = _load_doctor_module()
        seen_env = {}

        def fake_run_cli(steps, name, *command, allow_failure=False, env=None):
            payloads = {
                "capabilities": {"status": "ok", "agent_native_capabilities": {"supported_app_profiles": ["tashuo"]}},
                "data_doctor": {"status": "ok", "storage_backend": "sqlite"},
                "runtime_select_mac_ios_app": {"status": "selected"},
                "runtime_status_mac_ios_app": {"status": "selected"},
                "support_session_start": {"status": "active", "session_id": "support_1"},
                "harness_doctor_mac_ios_app": {"status": "ok"},
                "support_session_stop": {"status": "stopped"},
            }
            payload = payloads[name]
            steps.append({"name": name, "status": payload["status"], "returncode": 0, "reason": payload.get("reason")})
            return payload

        def fake_probe(*, env, api_key_env, base_url, model):
            seen_env.update(env)
            return {
                "status": "blocked",
                "reason": "minimax_probe_failed",
                "error_type": "AuthenticationError",
                "error_message": "invalid api key (2049)",
                "model": model,
                "base_url": base_url,
                "api_key_env": api_key_env,
                "env_present": bool(env.get(api_key_env)),
            }

        original_run_cli = module._run_cli
        original_probe = module._probe_minimax
        module._run_cli = fake_run_cli
        module._probe_minimax = fake_probe
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                env_file = root / ".env"
                env_file.write_text("MINIMAX_API_KEY=test-key\n", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(["--data-dir", str(root / "data"), "--env-file", str(env_file), "--json"])
        finally:
            module._run_cli = original_run_cli
            module._probe_minimax = original_probe

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "minimax_probe_failed")
        self.assertEqual(seen_env["MINIMAX_API_KEY"], "test-key")
        minimax_step = next(step for step in payload["steps"] if step["name"] == "minimax_probe")
        self.assertEqual(minimax_step["status"], "blocked")
        self.assertEqual(minimax_step["error_type"], "AuthenticationError")

    def test_doctor_blocks_harness_permission_failure_before_minimax_probe(self):
        module = _load_doctor_module()
        probe_called = False

        def fake_run_cli(steps, name, *command, allow_failure=False, env=None):
            payloads = {
                "capabilities": {"status": "ok", "agent_native_capabilities": {"supported_app_profiles": ["tashuo"]}},
                "data_doctor": {"status": "ok", "storage_backend": "sqlite"},
                "runtime_select_mac_ios_app": {"status": "selected"},
                "runtime_status_mac_ios_app": {"status": "selected"},
                "support_session_start": {"status": "active", "session_id": "support_1"},
                "harness_doctor_mac_ios_app": {
                    "status": "blocked",
                    "reason": "host_appleevents_unavailable",
                    "diagnostic": {"category": "host_appleevents_unavailable"},
                },
                "support_session_stop": {"status": "stopped"},
            }
            payload = payloads[name]
            steps.append({"name": name, "status": payload["status"], "returncode": 0, "reason": payload.get("reason")})
            return payload

        def fake_probe(**kwargs):
            nonlocal probe_called
            probe_called = True
            return {"status": "ok"}

        original_run_cli = module._run_cli
        original_probe = module._probe_minimax
        module._run_cli = fake_run_cli
        module._probe_minimax = fake_probe
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(["--data-dir", str(root / "data"), "--json"])
        finally:
            module._run_cli = original_run_cli
            module._probe_minimax = original_probe

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "host_appleevents_unavailable")
        self.assertFalse(probe_called)
        self.assertEqual(payload["support_session_id"], "support_1")

    def test_doctor_reports_ok_when_required_checks_pass(self):
        module = _load_doctor_module()

        def fake_run_cli(steps, name, *command, allow_failure=False, env=None):
            payloads = {
                "capabilities": {"status": "ok", "agent_native_capabilities": {"supported_app_profiles": ["tashuo"]}},
                "data_doctor": {"status": "ok", "storage_backend": "sqlite"},
                "runtime_select_mac_ios_app": {"status": "selected"},
                "runtime_status_mac_ios_app": {"status": "selected"},
                "support_session_start": {"status": "active", "session_id": "support_1"},
                "harness_doctor_mac_ios_app": {"status": "ok"},
                "support_session_stop": {"status": "stopped"},
            }
            payload = payloads[name]
            steps.append({"name": name, "status": payload["status"], "returncode": 0, "reason": payload.get("reason")})
            return payload

        original_run_cli = module._run_cli
        original_probe = module._probe_minimax
        module._run_cli = fake_run_cli
        module._probe_minimax = lambda **kwargs: {"status": "ok", "reason": None, "env_present": True}
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(["--data-dir", str(root / "data"), "--json"])
        finally:
            module._run_cli = original_run_cli
            module._probe_minimax = original_probe

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["reason"], "standalone_doctor_ok")


if __name__ == "__main__":
    unittest.main()
