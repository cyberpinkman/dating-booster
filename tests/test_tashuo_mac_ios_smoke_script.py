import importlib.util
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path


def _load_smoke_module():
    path = Path("scripts/tashuo_mac_ios_managed_smoke.py")
    spec = importlib.util.spec_from_file_location("tashuo_mac_ios_managed_smoke", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TaShuoMacIosManagedSmokeScriptTests(unittest.TestCase):
    def test_reads_supported_profiles_from_capabilities_agent_native_section(self):
        module = _load_smoke_module()
        payload = {
            "schema_version": 1,
            "agent_native_capabilities": {
                "supported_app_profiles": ["tinder", "tashuo"],
                "tashuo_mac_ios_app_runtime": True,
                "managed_session_harness_runtime_selection": True,
            },
        }

        self.assertEqual(module._supported_app_profiles(payload), ["tinder", "tashuo"])
        summary = module._summarize_payload("capabilities", payload)

        self.assertEqual(summary["supported_app_profiles"], ["tinder", "tashuo"])
        self.assertTrue(summary["tashuo_mac_ios_app_runtime"])
        self.assertTrue(summary["managed_session_harness_runtime_selection"])

    def test_summary_preserves_window_probe_from_preflight(self):
        module = _load_smoke_module()
        summary = module._summarize_payload(
            "prepare_message_page_mac_ios_app",
            {
                "status": "blocked",
                "reason": "mac_ios_app_process_has_no_windows",
                "preflight": {
                    "window_probe": {
                        "frontmost_process": "iPhone Mirroring",
                        "processes": [
                            {
                                "process_name": "tashuo",
                                "process_exists": True,
                                "frontmost": False,
                                "visible": True,
                                "window_count": 0,
                                "stdout": "false, true, 0",
                            }
                        ],
                    }
                },
            },
        )

        self.assertEqual(summary["window_probe"]["frontmost_process"], "iPhone Mirroring")
        self.assertEqual(summary["window_probe"]["processes"][0]["process_name"], "tashuo")
        self.assertEqual(summary["window_probe"]["processes"][0]["window_count"], 0)
        self.assertNotIn("stdout", summary["window_probe"]["processes"][0])

    def test_window_not_found_doctor_result_continues_to_prepare_message_page(self):
        module = _load_smoke_module()
        calls = []

        def fake_run_cli(steps, name, *command, allow_failure=False):
            calls.append(name)
            payloads = {
                "capabilities": {
                    "agent_native_capabilities": {"supported_app_profiles": ["tashuo"]},
                },
                "runtime_select_mac_ios_app": {"status": "selected"},
                "runtime_status_mac_ios_app": {"status": "selected"},
                "support_session_start": {"status": "active", "session_id": "support_1"},
                "harness_doctor_mac_ios_app": {
                    "status": "blocked",
                    "reason": "mac_ios_app_window_not_found",
                },
                "prepare_message_page_mac_ios_app": {"status": "ok"},
                "managed_session_start_mac_ios_app": {"status": "active"},
                "managed_session_tick_mac_ios_app": {"status": "no_work"},
                "managed_session_stop": {"status": "stopped"},
                "support_session_stop": {"status": "stopped"},
            }
            payload = payloads[name]
            steps.append(
                {
                    "name": name,
                    "status": payload.get("status") or "ok",
                    "returncode": 0,
                    "reason": payload.get("reason"),
                    "payload": payload,
                }
            )
            return payload

        original_run_cli = module._run_cli
        module._run_cli = fake_run_cli
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                args = SimpleNamespace(
                    data_dir=root / "data",
                    work_dir=root / "work",
                    authorization=root / "auth.json",
                    goal=root / "goal.json",
                    availability=root / "availability.json",
                    management_mode="conservative",
                    max_threads_per_cycle=1,
                    max_pages_per_cycle=1,
                    cycle_send_limit=0,
                    skip_prepare_message_page=False,
                    json=True,
                )
                payload = module.run_smoke(args)
        finally:
            module._run_cli = original_run_cli

        self.assertEqual(payload["status"], "ok")
        self.assertIn("prepare_message_page_mac_ios_app", calls)
        self.assertIn("mac_ios_app_process_has_no_windows", module._RECOVERABLE_DOCTOR_REASONS)


if __name__ == "__main__":
    unittest.main()
