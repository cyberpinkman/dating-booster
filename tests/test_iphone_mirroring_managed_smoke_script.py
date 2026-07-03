import importlib.util
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path


def _load_smoke_module():
    path = Path("scripts/iphone_mirroring_managed_smoke.py")
    spec = importlib.util.spec_from_file_location("iphone_mirroring_managed_smoke", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class IPhoneMirroringManagedSmokeScriptTests(unittest.TestCase):
    def test_reads_supported_profiles_from_capabilities_agent_native_section(self):
        module = _load_smoke_module()
        payload = {
            "schema_version": 1,
            "agent_native_capabilities": {
                "supported_app_profiles": ["tinder", "bumble"],
                "managed_session_harness_runtime_selection": True,
            },
        }

        self.assertEqual(module._supported_app_profiles(payload), ["tinder", "bumble"])
        summary = module._summarize_payload("capabilities", payload)

        self.assertEqual(summary["supported_app_profiles"], ["tinder", "bumble"])
        self.assertTrue(summary["managed_session_harness_runtime_selection"])

    def test_smoke_rejects_user_supplied_max_pages_per_cycle(self):
        module = _load_smoke_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            args = _args(root, max_pages_per_cycle=1)
            payload = module.run_smoke(args)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "message_list_scan_boundary_framework_controlled")
        self.assertEqual(
            payload["message_list_scan_boundary"],
            {"type": "first_historical_row", "history_cutoff_days": 7},
        )

    def test_locked_iphone_mirroring_blocks_before_managed_session_start(self):
        module = _load_smoke_module()
        calls = []

        def fake_run_cli(steps, name, *command, allow_failure=False):
            calls.append(name)
            payloads = {
                "skill_doctor": {"status": "ok", "capabilities_ok": True},
                "release_doctor": {"status": "ok"},
                "data_doctor": {"status": "ok", "storage_backend": "sqlite"},
                "capabilities": {
                    "agent_native_capabilities": {"supported_app_profiles": ["tinder", "bumble"]},
                    "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
                },
                "runtime_select_default": {"status": "selected"},
                "runtime_status_default": {"status": "selected"},
                "support_session_start": {"status": "active", "session_id": "support_1"},
                "harness_doctor_iphone_mirroring": {"status": "blocked", "reason": "iphone_mirroring_locked"},
                "support_session_stop": {"status": "stopped"},
            }
            payload = payloads[name]
            steps.append(
                {
                    "name": name,
                    "status": payload.get("status") or "ok",
                    "returncode": 0,
                    "reason": payload.get("reason"),
                    "cmd": list(command),
                    "payload": payload,
                }
            )
            return payload

        original_run_cli = module._run_cli
        module._run_cli = fake_run_cli
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                payload = module.run_smoke(_args(Path(temp_dir)))
        finally:
            module._run_cli = original_run_cli

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "iphone_mirroring_locked")
        self.assertNotIn("managed_session_start", calls)
        self.assertIn("support_session_stop", calls)

    def test_skill_doctor_blocks_before_runtime_selection(self):
        module = _load_smoke_module()
        calls = []

        def fake_run_cli(steps, name, *command, allow_failure=False):
            calls.append(name)
            payload = {
                "status": "incompatible",
                "capabilities_ok": False,
                "missing_commands": ["harness tinder send-message"],
                "schema_mismatches": [],
                "next_action": "stop",
            }
            steps.append(
                {
                    "name": name,
                    "status": payload["status"],
                    "returncode": 0,
                    "reason": payload.get("reason"),
                    "cmd": list(command),
                    "payload": payload,
                }
            )
            return payload

        original_run_cli = module._run_cli
        module._run_cli = fake_run_cli
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                payload = module.run_smoke(_args(Path(temp_dir)))
        finally:
            module._run_cli = original_run_cli

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "incompatible")
        self.assertEqual(calls, ["skill_doctor"])

    def test_data_doctor_migrates_before_capabilities_and_gui(self):
        module = _load_smoke_module()
        calls = []
        data_doctor_count = 0

        def fake_run_cli(steps, name, *command, allow_failure=False):
            nonlocal data_doctor_count
            calls.append(name)
            payloads = _base_payloads()
            if name == "data_doctor":
                data_doctor_count += 1
                payload = {"status": "needs_migration", "storage_backend": "json"}
            elif name == "data_migrate":
                payload = {"status": "ok", "storage_backend": "sqlite"}
            elif name == "data_doctor_after_migrate":
                payload = {"status": "ok", "storage_backend": "sqlite"}
            else:
                payload = payloads[name]
            steps.append(
                {
                    "name": name,
                    "status": payload.get("status") or "ok",
                    "returncode": 0,
                    "reason": payload.get("reason"),
                    "cmd": list(command),
                    "payload": payload,
                }
            )
            return payload

        original_run_cli = module._run_cli
        module._run_cli = fake_run_cli
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                payload = module.run_smoke(_args(Path(temp_dir), accept_managed_session_config=True))
        finally:
            module._run_cli = original_run_cli

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(data_doctor_count, 1)
        self.assertLess(calls.index("data_migrate"), calls.index("capabilities"))
        self.assertLess(calls.index("data_doctor_after_migrate"), calls.index("capabilities"))

    def test_direct_harness_scope_mismatch_blocks_before_runtime_selection(self):
        module = _load_smoke_module()
        calls = []

        def fake_run_cli(steps, name, *command, allow_failure=False):
            calls.append(name)
            payloads = _base_payloads()
            payloads["capabilities"] = {
                "agent_native_capabilities": {"supported_app_profiles": ["tinder", "bumble"]},
                "managed_live_send_guidance": {"direct_harness_scope": "host_public"},
            }
            payload = payloads[name]
            steps.append(
                {
                    "name": name,
                    "status": payload.get("status") or "ok",
                    "returncode": 0,
                    "reason": payload.get("reason"),
                    "cmd": list(command),
                    "payload": payload,
                }
            )
            return payload

        original_run_cli = module._run_cli
        module._run_cli = fake_run_cli
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                payload = module.run_smoke(_args(Path(temp_dir)))
        finally:
            module._run_cli = original_run_cli

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "direct_harness_scope_not_executor_internal_only")
        self.assertNotIn("runtime_select_default", calls)

    def test_prepare_message_page_failure_blocks_before_managed_session_start(self):
        module = _load_smoke_module()
        calls = []

        def fake_run_cli(steps, name, *command, allow_failure=False):
            calls.append(name)
            payloads = _base_payloads()
            payloads["prepare_message_page_iphone_mirroring"] = {
                "status": "blocked",
                "reason": "tinder_messages_not_verified",
            }
            payload = payloads[name]
            steps.append(
                {
                    "name": name,
                    "status": payload.get("status") or "ok",
                    "returncode": 0,
                    "reason": payload.get("reason"),
                    "cmd": list(command),
                    "payload": payload,
                }
            )
            return payload

        original_run_cli = module._run_cli
        module._run_cli = fake_run_cli
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                payload = module.run_smoke(_args(Path(temp_dir)))
        finally:
            module._run_cli = original_run_cli

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "tinder_messages_not_verified")
        self.assertIn("prepare_message_page_iphone_mirroring", calls)
        self.assertNotIn("managed_session_start", calls)

    def test_managed_session_config_confirmation_required_without_explicit_acceptance(self):
        module = _load_smoke_module()
        calls = []

        def fake_run_cli(steps, name, *command, allow_failure=False):
            calls.append((name, list(command)))
            payloads = _base_payloads()
            payloads["managed_session_start"] = {
                "status": "blocked",
                "reason": "managed_session_config_confirmation_required",
                "required_confirm_token": "managed-session-config:abc",
                "proposed_config": {"app_id": "bumble", "send_mode": "stage"},
            }
            payload = payloads[name]
            steps.append(
                {
                    "name": name,
                    "status": payload.get("status") or "ok",
                    "returncode": 0,
                    "reason": payload.get("reason"),
                    "cmd": list(command),
                    "payload": payload,
                }
            )
            return payload

        original_run_cli = module._run_cli
        module._run_cli = fake_run_cli
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                payload = module.run_smoke(_args(Path(temp_dir), app_id="bumble"))
        finally:
            module._run_cli = original_run_cli

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "managed_session_config_confirmation_required")
        self.assertFalse(any(name == "managed_session_start_confirmed" for name, _command in calls))

    def test_explicit_config_acceptance_retries_with_confirm_token_and_stops_session(self):
        module = _load_smoke_module()
        calls = []

        def fake_run_cli(steps, name, *command, allow_failure=False):
            calls.append((name, list(command)))
            payloads = _base_payloads()
            payloads["managed_session_start"] = {
                "status": "blocked",
                "reason": "managed_session_config_confirmation_required",
                "required_confirm_token": "managed-session-config:abc",
                "proposed_config": {"app_id": "tinder", "send_mode": "stage"},
            }
            payloads["managed_session_start_confirmed"] = {"status": "active"}
            payloads["managed_session_tick"] = {"status": "no_work"}
            payloads["managed_session_stop"] = {"status": "stopped"}
            payload = payloads[name]
            steps.append(
                {
                    "name": name,
                    "status": payload.get("status") or "ok",
                    "returncode": 0,
                    "reason": payload.get("reason"),
                    "cmd": list(command),
                    "payload": payload,
                }
            )
            return payload

        original_run_cli = module._run_cli
        module._run_cli = fake_run_cli
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                payload = module.run_smoke(_args(Path(temp_dir), accept_managed_session_config=True))
        finally:
            module._run_cli = original_run_cli

        self.assertEqual(payload["status"], "ok")
        confirmed = next(command for name, command in calls if name == "managed_session_start_confirmed")
        self.assertIn("--config-confirm", confirmed)
        self.assertIn("managed-session-config:abc", confirmed)
        self.assertIn("managed_session_stop", [name for name, _command in calls])


def _args(
    root: Path,
    *,
    app_id: str = "tinder",
    max_pages_per_cycle: int | None = None,
    accept_managed_session_config: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        app_id=app_id,
        data_dir=root / "data",
        work_dir=root / "work",
        authorization=root / "auth.json",
        goal=root / "goal.json",
        availability=root / "availability.json",
        management_mode="conservative",
        max_threads_per_cycle=None,
        max_pages_per_cycle=max_pages_per_cycle,
        cycle_send_limit=None,
        accept_managed_session_config=accept_managed_session_config,
        json=True,
    )


def _base_payloads() -> dict[str, dict]:
    return {
        "skill_doctor": {"status": "ok", "capabilities_ok": True},
        "release_doctor": {"status": "ok"},
        "data_doctor": {"status": "ok", "storage_backend": "sqlite"},
        "capabilities": {
            "agent_native_capabilities": {"supported_app_profiles": ["tinder", "bumble"]},
            "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
        },
        "runtime_select_default": {"status": "selected"},
        "runtime_status_default": {"status": "selected"},
        "support_session_start": {"status": "active", "session_id": "support_1"},
        "harness_doctor_iphone_mirroring": {"status": "ok"},
        "harness_launch_dry_run": {"status": "ok"},
        "harness_observe": {"status": "ok"},
        "prepare_message_page_iphone_mirroring": {
            "status": "ok",
            "next_host_action": "visual_plan_message_list",
        },
        "managed_session_start": {"status": "active"},
        "managed_session_tick": {"status": "no_work"},
        "managed_session_stop": {"status": "stopped"},
        "support_session_stop": {"status": "stopped"},
    }


if __name__ == "__main__":
    unittest.main()
