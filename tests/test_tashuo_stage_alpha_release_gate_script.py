import importlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


def _load_gate_module():
    return importlib.import_module("dating_boost.core.tashuo_stage_alpha_release_gate")


def _smoke_payload(
    *,
    status: str = "ok",
    reason: str = "tashuo_standalone_stage_smoke_complete",
    direct_send: bool = False,
    high_risk_alias: bool = False,
    live_send_mode: bool = False,
    managed_gui_send: bool = False,
) -> dict:
    send_mode = "live" if live_send_mode else "stage"
    steps = [
        {"cmd": ["standalone-session", "start", "--send-mode", send_mode], "status": "active", "returncode": 0},
        {"cmd": ["standalone-session", "tick"], "status": "stage_recorded", "returncode": 0},
        {"cmd": ["harness", "tashuo", "action", "clear-message-input"], "status": "ok", "returncode": 0},
    ]
    if direct_send:
        steps.append({"cmd": ["harness", "tashuo", "send-message"], "status": "ok", "returncode": 0})
    if high_risk_alias:
        steps.append({"cmd": ["harness", "tashuo", "action", "profile_edit"], "status": "ok", "returncode": 0})
    if managed_gui_send:
        steps.append({"cmd": ["dating-boost-host-loop", "run", "--managed-gui-send"], "status": "ok", "returncode": 0})
    return {
        "schema_version": 1,
        "status": status,
        "reason": reason,
        "steps": steps,
        "final_input_verification": {
            "schema_version": 1,
            "status": "ok",
            "verification_method": "unit_fake",
            "input_cleared": True,
            "final_input_character_count": 0,
            "reason": None,
        },
        "alpha_release_gate": {
            "schema_version": 1,
            "status": "ok",
            "reason": "tashuo_standalone_alpha_gate_passed",
            "checks": {
                "stage_only": True,
                "live_send_not_executed": True,
                "staged_text_verified": True,
                "target_verified": True,
                "final_input_empty": True,
                "no_direct_live_send_command": True,
            },
            "stage_binding": {
                "event_id": "stage_result_1",
                "action_request_id": "act_1",
                "target_match_id": "match_1",
                "payload_hash": "hash_1",
            },
            "stage_result": {
                "event_id": "stage_result_1",
                "precondition_hash": "pre_hash_1",
                "evidence": {
                    "stage_mode": True,
                    "live_send_executed": False,
                    "draft_text_hash": "draft_hash_1",
                },
            },
        },
    }


def _release_evidence_payload() -> dict:
    gate_summary = {
        "status": "ok",
        "reason": "tashuo_standalone_alpha_gate_passed",
        "checks": {
            "stage_only": True,
            "live_send_not_executed": True,
            "staged_text_verified": True,
            "target_verified": True,
            "final_input_empty": True,
            "no_direct_live_send_command": True,
        },
        "stage_binding": {
            "event_id": "stage_result_1",
            "action_request_id": "act_1",
            "target_match_id": "match_1",
            "payload_hash": "hash_1",
        },
    }
    smoke_runs = []
    for run_number in range(1, 21):
        surface = "current-thread" if run_number == 2 else "message-list"
        smoke_runs.append(
            {
                "schema_version": 1,
                "run_number": run_number,
                "initial_surface": surface,
                "status": "ok",
                "reason": "tashuo_stage_alpha_run_passed",
                "smoke_json": f"/tmp/run_{run_number:02d}_smoke.json",
                "alpha_release_gate": gate_summary,
                "stage_binding": gate_summary["stage_binding"],
            }
        )
    return {
        "schema_version": 1,
        "status": "ok",
        "reason": "tashuo_stage_alpha_release_gate_passed",
        "run_id": "unit_release",
        "app_id": "tashuo",
        "harness_runtime": "mac-ios-app",
        "send_mode": "stage",
        "runs_required": 20,
        "runs_completed": 20,
        "runs_passed": 20,
        "pass_rate": 1.0,
        "checks": {
            "twenty_of_twenty_passed": True,
            "required_run_count_passed": True,
            "zero_live_send_execution": True,
            "zero_high_risk_action": True,
            "strict_support_bundle": True,
            "support_bundle_required": True,
            "evidence_bundle_written": True,
        },
        "support_session_stop": {"status": "stopped"},
        "support_bundle": {"status": "ok", "output": "/tmp/support.zip", "redaction": "strict"},
        "steps": [
            {"cmd": ["release", "doctor", "--json"], "status": "ok", "returncode": 0},
            {"cmd": ["runtime", "select", "--runtime", "mac-ios-app", "--json"], "status": "selected", "returncode": 0},
        ],
        "smoke_runs": smoke_runs,
    }


def _write_release_evidence_bundle(
    path: Path,
    payload: dict,
    *,
    bad_smoke_run: int | None = None,
    live_mode_run: int | None = None,
    managed_gui_send_run: int | None = None,
    high_risk_run: int | None = None,
    raw_visual_run: int | None = None,
    missing_smoke_run: int | None = None,
    include_support_bundle: bool = True,
) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("alpha_release_evidence.json", json.dumps(payload, ensure_ascii=False))
        for run in payload["smoke_runs"]:
            run_number = int(run["run_number"])
            smoke_payload = _smoke_payload(
                direct_send=(bad_smoke_run == run_number),
                live_send_mode=(live_mode_run == run_number),
                managed_gui_send=(managed_gui_send_run == run_number),
                high_risk_alias=(high_risk_run == run_number),
            )
            if raw_visual_run == run_number:
                smoke_payload["alpha_release_gate"]["stage_result"]["target_verification"] = {
                    "status": "ok",
                    "visible_name": "小药丸儿",
                }
                smoke_payload["alpha_release_gate"]["stage_result"]["staged_text_verification"] = {
                    "status": "verified",
                    "screen": {"path": "/tmp/raw-visible-screen.png"},
                }
            if missing_smoke_run != run_number:
                archive.writestr(f"runs/run_{run_number:02d}_smoke.json", json.dumps(smoke_payload, ensure_ascii=False))
            archive.writestr(f"runs/run_{run_number:02d}_summary.json", json.dumps(run, ensure_ascii=False))
        if include_support_bundle:
            archive.writestr("support/dating-boost-support-strict.zip", b"strict support bundle")


class TaShuoStageAlphaReleaseGateScriptTests(unittest.TestCase):
    def test_validate_release_evidence_bundle_accepts_complete_twenty_run_gate(self):
        module = _load_gate_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "alpha_release_evidence_bundle.zip"
            _write_release_evidence_bundle(bundle, _release_evidence_payload())
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = module.main(["--validate-evidence-bundle", str(bundle), "--json"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["reason"], "tashuo_stage_alpha_release_evidence_validated")
        self.assertTrue(payload["checks"]["all_release_checks_true"])
        self.assertTrue(payload["checks"]["every_bundle_smoke_ok"])

    def test_validate_release_evidence_bundle_rejects_direct_send_inside_smoke(self):
        module = _load_gate_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "alpha_release_evidence_bundle.zip"
            _write_release_evidence_bundle(bundle, _release_evidence_payload(), bad_smoke_run=3)
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = module.main(["--validate-evidence-bundle", str(bundle), "--json"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["checks"]["zero_live_send_execution"])
        self.assertFalse(payload["checks"]["zero_high_risk_action"])
        self.assertFalse(payload["checks"]["every_bundle_smoke_ok"])
        self.assertTrue(
            any(
                failure.startswith("release_evidence_bundle_smoke_invalid:run_03:forbidden_command_present:send-message")
                for failure in payload["failures"]
            )
        )

    def test_validate_release_evidence_bundle_rejects_live_send_mode_inside_smoke(self):
        module = _load_gate_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "alpha_release_evidence_bundle.zip"
            _write_release_evidence_bundle(bundle, _release_evidence_payload(), live_mode_run=5)
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = module.main(["--validate-evidence-bundle", str(bundle), "--json"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["checks"]["zero_live_send_execution"])
        self.assertFalse(payload["checks"]["zero_high_risk_action"])
        self.assertFalse(payload["checks"]["every_bundle_smoke_ok"])
        self.assertTrue(
            any(
                failure.startswith("release_evidence_bundle_smoke_invalid:run_05:non_stage_send_mode_present")
                for failure in payload["failures"]
            )
        )

    def test_validate_release_evidence_bundle_rejects_managed_gui_send_inside_smoke(self):
        module = _load_gate_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "alpha_release_evidence_bundle.zip"
            _write_release_evidence_bundle(bundle, _release_evidence_payload(), managed_gui_send_run=6)
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = module.main(["--validate-evidence-bundle", str(bundle), "--json"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["checks"]["zero_live_send_execution"])
        self.assertFalse(payload["checks"]["zero_high_risk_action"])
        self.assertFalse(payload["checks"]["every_bundle_smoke_ok"])
        self.assertTrue(
            any(
                failure.startswith("release_evidence_bundle_smoke_invalid:run_06:forbidden_command_present:--managed-gui-send")
                for failure in payload["failures"]
            )
        )

    def test_validate_release_evidence_bundle_rejects_high_risk_command_inside_smoke(self):
        module = _load_gate_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "alpha_release_evidence_bundle.zip"
            _write_release_evidence_bundle(bundle, _release_evidence_payload(), high_risk_run=7)
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = module.main(["--validate-evidence-bundle", str(bundle), "--json"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertTrue(payload["checks"]["zero_live_send_execution"])
        self.assertFalse(payload["checks"]["zero_high_risk_action"])
        self.assertFalse(payload["checks"]["every_bundle_smoke_ok"])
        self.assertTrue(
            any(
                failure.startswith("release_evidence_bundle_smoke_invalid:run_07:forbidden_command_present:profile_edit")
                for failure in payload["failures"]
            )
        )

    def test_validate_release_evidence_bundle_rejects_missing_smoke_json(self):
        module = _load_gate_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "alpha_release_evidence_bundle.zip"
            _write_release_evidence_bundle(bundle, _release_evidence_payload(), missing_smoke_run=8)
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = module.main(["--validate-evidence-bundle", str(bundle), "--json"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["checks"]["every_bundle_smoke_ok"])
        self.assertIn("release_evidence_bundle_smoke_missing:run_08", payload["failures"])

    def test_validate_release_evidence_bundle_rejects_missing_strict_support_bundle(self):
        module = _load_gate_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "alpha_release_evidence_bundle.zip"
            _write_release_evidence_bundle(bundle, _release_evidence_payload(), include_support_bundle=False)
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = module.main(["--validate-evidence-bundle", str(bundle), "--json"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["checks"]["bundle_has_support_bundle"])
        self.assertIn("release_evidence_check_failed:bundle_has_support_bundle", payload["failures"])

    def test_validate_release_evidence_bundle_rejects_unredacted_visual_fields(self):
        module = _load_gate_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "alpha_release_evidence_bundle.zip"
            _write_release_evidence_bundle(bundle, _release_evidence_payload(), raw_visual_run=4)
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = module.main(["--validate-evidence-bundle", str(bundle), "--json"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["checks"]["bundle_redacted"])
        self.assertTrue(
            any("unredacted_sensitive_field:runs/run_04_smoke.json.alpha_release_gate.stage_result.target_verification.visible_name" in item for item in payload["bundle_summary"]["redaction_violations"])
        )
        self.assertTrue(
            any("unredacted_visual_path:runs/run_04_smoke.json.alpha_release_gate.stage_result.staged_text_verification.screen.path" in item for item in payload["bundle_summary"]["redaction_violations"])
        )

    def test_write_evidence_redacts_bundled_smoke_json(self):
        module = _load_gate_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = root / "work" / "run_01_message_list"
            run_dir.mkdir(parents=True)
            smoke = _smoke_payload()
            smoke["alpha_release_gate"]["stage_result"]["target_verification"] = {
                "status": "ok",
                "visible_name": "小药丸儿",
            }
            smoke["alpha_release_gate"]["stage_result"]["staged_text_verification"] = {
                "status": "verified",
                "screen": {"path": "/tmp/raw-visible-screen.png"},
            }
            smoke["payload_text"] = "不要进入 bundle 的原始草稿"
            smoke_json = run_dir / "smoke.json"
            smoke_json.write_text(json.dumps(smoke, ensure_ascii=False), encoding="utf-8")
            run_summary = {
                "schema_version": 1,
                "run_number": 1,
                "initial_surface": "message-list",
                "status": "ok",
                "reason": "tashuo_stage_alpha_run_passed",
                "smoke_json": str(smoke_json),
                "alpha_release_gate": _release_evidence_payload()["smoke_runs"][0]["alpha_release_gate"],
                "stage_binding": _release_evidence_payload()["smoke_runs"][0]["stage_binding"],
            }
            (run_dir / "run_summary.json").write_text(json.dumps(run_summary, ensure_ascii=False), encoding="utf-8")
            payload = _release_evidence_payload()
            payload["work_dir"] = str(root / "work")
            payload["smoke_runs"] = [run_summary]
            payload["failure_artifact"] = "/tmp/raw-top-level-screen.png"
            evidence_json = root / "alpha_release_evidence.json"
            evidence_bundle = root / "alpha_release_evidence_bundle.zip"

            module._write_evidence(payload, evidence_json=evidence_json, evidence_bundle=evidence_bundle)
            with zipfile.ZipFile(evidence_bundle) as archive:
                bundled_top = json.loads(archive.read("alpha_release_evidence.json").decode("utf-8"))
                bundled_smoke = json.loads(archive.read("runs/run_01_smoke.json").decode("utf-8"))

        target = bundled_smoke["alpha_release_gate"]["stage_result"]["target_verification"]
        staged = bundled_smoke["alpha_release_gate"]["stage_result"]["staged_text_verification"]
        self.assertEqual(target["visible_name"]["redacted"], True)
        self.assertEqual(staged["screen"]["redacted"], True)
        self.assertEqual(bundled_smoke["payload_text"]["redacted"], True)
        self.assertNotIn("小药丸儿", json.dumps(bundled_smoke, ensure_ascii=False))
        self.assertNotIn("raw-visible-screen.png", json.dumps(bundled_smoke, ensure_ascii=False))
        self.assertEqual(bundled_top["failure_artifact"], "[redacted_visual_artifact_path]")
        self.assertNotIn("raw-top-level-screen.png", json.dumps(bundled_top, ensure_ascii=False))

    def test_validate_release_evidence_json_without_bundle_is_diagnostic_only(self):
        module = _load_gate_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence_json = root / "alpha_release_evidence.json"
            evidence_json.write_text(json.dumps(_release_evidence_payload(), ensure_ascii=False), encoding="utf-8")
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = module.main(["--validate-evidence-json", str(evidence_json), "--json"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["checks"]["bundle_provided"])
        self.assertIn("release_evidence_check_failed:bundle_provided", payload["failures"])

    def test_release_gate_runs_mixed_twenty_gate_subset_and_writes_evidence_bundle(self):
        module = _load_gate_module()
        calls = []
        data_doctor_count = 0

        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False, env=None, timeout=None):
            nonlocal data_doctor_count
            calls.append(cmd)
            if len(cmd) > 1 and str(cmd[1]).endswith("tashuo_mac_ios_standalone_smoke.py"):
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_smoke_payload()), stderr="")
            cli = cmd[3:]
            payload = {"status": "ok"}
            returncode = 0
            if cli[:2] == ["release", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:1] == ["capabilities"]:
                payload = {
                    "supported_app_profiles": ["tashuo"],
                    "agent_native_capabilities": {"tashuo_mac_ios_app_runtime": True},
                    "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
                }
            elif cli[:2] == ["data", "doctor"]:
                data_doctor_count += 1
                payload = {"status": "needs_migration" if data_doctor_count == 1 else "ok"}
            elif cli[:2] == ["data", "migrate"]:
                payload = {"status": "ok"}
            elif cli[:2] == ["safety", "status"]:
                payload = {"paused": False, "reason": None}
            elif cli[:2] == ["user", "readiness"]:
                payload = {"status": "ready", "ready": True, "reason": "ready"}
            elif cli[:2] == ["runtime", "select"]:
                payload = {"status": "selected", "selected_app_id": "tashuo", "selected_runtime": "mac-ios-app"}
            elif cli[:2] == ["runtime", "status"]:
                payload = {"status": "selected", "selected_app_id": "tashuo", "selected_runtime": "mac-ios-app"}
            elif cli[:3] == ["support", "session", "start"]:
                payload = {"status": "active", "session_id": "support_1"}
            elif cli[:3] == ["support", "session", "stop"]:
                payload = {"status": "stopped"}
            elif cli[:2] == ["support", "bundle"]:
                output = Path(cli[cli.index("--output") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"strict support bundle")
                payload = {"status": "ok", "output": str(output), "redaction": "strict"}
            elif cli[:2] == ["harness", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:4] == ["harness", "tashuo", "action", "prepare-message-page"]:
                payload = {"status": "ok", "screen_state": "tashuo_chat_list", "next_host_action": "visual_plan_message_list"}
            return subprocess.CompletedProcess(cmd, returncode, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        original_sdk = module._openai_sdk_available
        module.subprocess.run = fake_run
        module._openai_sdk_available = lambda: True
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        try:
            root = Path(temp_dir.name)
            auth = root / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            env_file = root / ".env"
            env_file.write_text("MINIMAX_API_KEY=test\n", encoding="utf-8")
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = module.main(
                    [
                        "--data-dir",
                        str(root / "data"),
                        "--work-dir",
                        str(root / "work"),
                        "--authorization",
                        str(auth),
                        "--env-file",
                        str(env_file),
                        "--runs",
                        "3",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
        finally:
            module.subprocess.run = original_run
            module._openai_sdk_available = original_sdk

        command_args = [call[3:] if call[1:3] == ["-m", "dating_boost.cli"] else call[1:] for call in calls]
        smoke_commands = [command for command in command_args if command and str(command[0]).endswith("tashuo_mac_ios_standalone_smoke.py")]
        prepare_commands = [command for command in command_args if command[:4] == ["harness", "tashuo", "action", "prepare-message-page"]]
        preflight_launch_index = next(
            index
            for index, command in enumerate(command_args)
            if command[:3] == ["harness", "tashuo", "launch"]
            and "preflight_harness" in command[command.index("--output-dir") + 1]
        )
        harness_doctor_index = next(
            index for index, command in enumerate(command_args) if command[:2] == ["harness", "doctor"]
        )
        surfaces = [command[command.index("--initial-surface") + 1] for command in smoke_commands]

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["runs_passed"], 3)
        self.assertTrue(payload["checks"]["zero_live_send_execution"])
        self.assertTrue(payload["checks"]["zero_high_risk_action"])
        self.assertTrue(payload["checks"]["strict_support_bundle"])
        self.assertTrue(payload["checks"]["support_bundle_required"])
        self.assertEqual(surfaces, ["message-list", "current-thread", "message-list"])
        self.assertTrue(all("--minimax-request-timeout-seconds" in command for command in smoke_commands))
        self.assertTrue(
            all(command[command.index("--minimax-request-timeout-seconds") + 1] == "30.0" for command in smoke_commands)
        )
        self.assertEqual(len(prepare_commands), 2)
        self.assertLess(preflight_launch_index, harness_doctor_index)
        self.assertTrue(Path(payload["evidence_json"]).is_file())
        with zipfile.ZipFile(payload["evidence_bundle"]) as archive:
            names = set(archive.namelist())
        self.assertIn("alpha_release_evidence.json", names)
        self.assertIn("runs/run_01_smoke.json", names)
        self.assertIn("support/dating-boost-support-strict.zip", names)
        support_bundle_commands = [command for command in command_args if command[:2] == ["support", "bundle"]]
        self.assertEqual(support_bundle_commands[0][support_bundle_commands[0].index("--redaction") + 1], "strict")

    def test_release_gate_failure_still_stops_support_and_exports_bundle(self):
        module = _load_gate_module()
        calls = []

        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False, env=None, timeout=None):
            calls.append(cmd)
            if len(cmd) > 1 and str(cmd[1]).endswith("tashuo_mac_ios_standalone_smoke.py"):
                return subprocess.CompletedProcess(
                    cmd,
                    2,
                    stdout=json.dumps(_smoke_payload(status="blocked", reason="final_input_not_empty")),
                    stderr="",
                )
            cli = cmd[3:]
            payload = {"status": "ok"}
            if cli[:1] == ["capabilities"]:
                payload = {
                    "supported_app_profiles": ["tashuo"],
                    "agent_native_capabilities": {"tashuo_mac_ios_app_runtime": True},
                    "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
                }
            elif cli[:2] == ["data", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:2] == ["safety", "status"]:
                payload = {"paused": False}
            elif cli[:2] == ["user", "readiness"]:
                payload = {"status": "ready", "ready": True, "reason": "ready"}
            elif cli[:2] in (["runtime", "select"], ["runtime", "status"]):
                payload = {"status": "selected"}
            elif cli[:3] == ["support", "session", "start"]:
                payload = {"status": "active", "session_id": "support_1"}
            elif cli[:3] == ["support", "session", "stop"]:
                payload = {"status": "stopped"}
            elif cli[:2] == ["support", "bundle"]:
                output = Path(cli[cli.index("--output") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"strict support bundle")
                payload = {"status": "ok", "output": str(output), "redaction": "strict"}
            elif cli[:4] == ["harness", "tashuo", "action", "prepare-message-page"]:
                payload = {"status": "ok"}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        original_sdk = module._openai_sdk_available
        module.subprocess.run = fake_run
        module._openai_sdk_available = lambda: True
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        try:
            root = Path(temp_dir.name)
            auth = root / "auth.json"
            auth.write_text("{}", encoding="utf-8")
            env_file = root / ".env"
            env_file.write_text("MINIMAX_API_KEY=test\n", encoding="utf-8")
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = module.main(
                    [
                        "--data-dir",
                        str(root / "data"),
                        "--work-dir",
                        str(root / "work"),
                        "--authorization",
                        str(auth),
                        "--env-file",
                        str(env_file),
                        "--runs",
                        "2",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
        finally:
            module.subprocess.run = original_run
            module._openai_sdk_available = original_sdk

        command_args = [call[3:] if call[1:3] == ["-m", "dating_boost.cli"] else call[1:] for call in calls]
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["runs_completed"], 1)
        self.assertTrue(payload["checks"]["strict_support_bundle"])
        self.assertTrue(payload["checks"]["support_bundle_required"])
        self.assertTrue(any(command[:3] == ["support", "session", "stop"] for command in command_args))
        self.assertTrue(any(command[:2] == ["support", "bundle"] for command in command_args))
        self.assertTrue(Path(payload["evidence_bundle"]).is_file())

    def test_release_gate_reuses_external_support_session_without_stopping_or_bundling_it(self):
        module = _load_gate_module()
        calls = []

        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False, env=None, timeout=None):
            calls.append(cmd)
            if len(cmd) > 1 and str(cmd[1]).endswith("tashuo_mac_ios_standalone_smoke.py"):
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_smoke_payload()), stderr="")
            cli = cmd[3:]
            payload = {"status": "ok"}
            if cli[:1] == ["capabilities"]:
                payload = {
                    "supported_app_profiles": ["tashuo"],
                    "agent_native_capabilities": {"tashuo_mac_ios_app_runtime": True},
                    "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
                }
            elif cli[:2] == ["data", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:2] == ["safety", "status"]:
                payload = {"paused": False}
            elif cli[:2] == ["user", "readiness"]:
                payload = {"status": "ready", "ready": True, "reason": "ready"}
            elif cli[:2] in (["runtime", "select"], ["runtime", "status"]):
                payload = {"status": "selected", "selected_app_id": "tashuo", "selected_runtime": "mac-ios-app"}
            elif cli[:2] == ["harness", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:3] == ["harness", "tashuo", "launch"]:
                payload = {"status": "ok"}
            elif cli[:4] == ["harness", "tashuo", "action", "prepare-message-page"]:
                payload = {"status": "ok"}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        original_sdk = module._openai_sdk_available
        module.subprocess.run = fake_run
        module._openai_sdk_available = lambda: True
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                env_file = root / ".env"
                env_file.write_text("MINIMAX_API_KEY=test\n", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--work-dir",
                            str(root / "work"),
                            "--authorization",
                            str(auth),
                            "--env-file",
                            str(env_file),
                            "--runs",
                            "1",
                            "--support-session-id",
                            "support_outer",
                            "--json",
                        ]
                    )
                payload = json.loads(stdout.getvalue())
                with zipfile.ZipFile(payload["evidence_bundle"]) as archive:
                    bundle_names = set(archive.namelist())
        finally:
            module.subprocess.run = original_run
            module._openai_sdk_available = original_sdk

        command_args = [call[3:] if call[1:3] == ["-m", "dating_boost.cli"] else call[1:] for call in calls]
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["support_session_id"], "support_outer")
        self.assertTrue(payload["external_support_session"])
        self.assertFalse(payload["checks"]["support_bundle_required"])
        self.assertTrue(payload["checks"]["strict_support_bundle"])
        self.assertFalse(any(command[:3] == ["support", "session", "start"] for command in command_args))
        self.assertFalse(any(command[:3] == ["support", "session", "stop"] for command in command_args))
        self.assertFalse(any(command[:2] == ["support", "bundle"] for command in command_args))
        self.assertIn("alpha_release_evidence.json", bundle_names)
        self.assertNotIn("support/dating-boost-support-strict.zip", bundle_names)

    def test_release_gate_support_stop_interrupt_blocks_release_and_writes_evidence(self):
        module = _load_gate_module()
        calls = []

        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False, env=None, timeout=None):
            calls.append(cmd)
            if len(cmd) > 1 and str(cmd[1]).endswith("tashuo_mac_ios_standalone_smoke.py"):
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_smoke_payload()), stderr="")
            cli = cmd[3:]
            payload = {"status": "ok"}
            if cli[:1] == ["capabilities"]:
                payload = {
                    "supported_app_profiles": ["tashuo"],
                    "agent_native_capabilities": {"tashuo_mac_ios_app_runtime": True},
                    "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
                }
            elif cli[:2] == ["data", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:2] == ["safety", "status"]:
                payload = {"paused": False}
            elif cli[:2] == ["user", "readiness"]:
                payload = {"status": "ready", "ready": True, "reason": "ready"}
            elif cli[:2] in (["runtime", "select"], ["runtime", "status"]):
                payload = {"status": "selected"}
            elif cli[:3] == ["support", "session", "start"]:
                payload = {"status": "active", "session_id": "support_stop_interrupt"}
            elif cli[:3] == ["support", "session", "stop"]:
                raise KeyboardInterrupt
            elif cli[:2] == ["support", "bundle"]:
                output = Path(cli[cli.index("--output") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"strict support bundle")
                payload = {"status": "ok", "output": str(output), "redaction": "strict"}
            elif cli[:2] == ["harness", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:4] == ["harness", "tashuo", "action", "prepare-message-page"]:
                payload = {"status": "ok"}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        original_sdk = module._openai_sdk_available
        module.subprocess.run = fake_run
        module._openai_sdk_available = lambda: True
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                env_file = root / ".env"
                env_file.write_text("MINIMAX_API_KEY=test\n", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--work-dir",
                            str(root / "work"),
                            "--authorization",
                            str(auth),
                            "--env-file",
                            str(env_file),
                            "--runs",
                            "1",
                            "--json",
                        ]
                    )
                payload = json.loads(stdout.getvalue())
                evidence_bundle_exists = Path(payload["evidence_bundle"]).is_file()
        finally:
            module.subprocess.run = original_run
            module._openai_sdk_available = original_sdk

        stop_step = next(step for step in payload["steps"] if step["name"] == "support_session_stop")
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "support_session_stop_failed")
        self.assertEqual(payload["support_session_stop"]["reason"], "support_session_stop_interrupted_by_user")
        self.assertEqual(stop_step["reason"], "command_interrupted:support_session_stop")
        self.assertEqual(stop_step["error_type"], "KeyboardInterrupt")
        self.assertTrue(evidence_bundle_exists)

    def test_release_gate_support_bundle_interrupt_blocks_release_and_writes_evidence(self):
        module = _load_gate_module()
        calls = []

        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False, env=None, timeout=None):
            calls.append(cmd)
            if len(cmd) > 1 and str(cmd[1]).endswith("tashuo_mac_ios_standalone_smoke.py"):
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_smoke_payload()), stderr="")
            cli = cmd[3:]
            payload = {"status": "ok"}
            if cli[:1] == ["capabilities"]:
                payload = {
                    "supported_app_profiles": ["tashuo"],
                    "agent_native_capabilities": {"tashuo_mac_ios_app_runtime": True},
                    "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
                }
            elif cli[:2] == ["data", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:2] == ["safety", "status"]:
                payload = {"paused": False}
            elif cli[:2] == ["user", "readiness"]:
                payload = {"status": "ready", "ready": True, "reason": "ready"}
            elif cli[:2] in (["runtime", "select"], ["runtime", "status"]):
                payload = {"status": "selected"}
            elif cli[:3] == ["support", "session", "start"]:
                payload = {"status": "active", "session_id": "support_bundle_interrupt"}
            elif cli[:3] == ["support", "session", "stop"]:
                payload = {"status": "stopped"}
            elif cli[:2] == ["support", "bundle"]:
                raise KeyboardInterrupt
            elif cli[:2] == ["harness", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:4] == ["harness", "tashuo", "action", "prepare-message-page"]:
                payload = {"status": "ok"}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        original_sdk = module._openai_sdk_available
        module.subprocess.run = fake_run
        module._openai_sdk_available = lambda: True
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                env_file = root / ".env"
                env_file.write_text("MINIMAX_API_KEY=test\n", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--work-dir",
                            str(root / "work"),
                            "--authorization",
                            str(auth),
                            "--env-file",
                            str(env_file),
                            "--runs",
                            "1",
                            "--json",
                        ]
                    )
                payload = json.loads(stdout.getvalue())
                with zipfile.ZipFile(payload["evidence_bundle"]) as archive:
                    bundle_names = set(archive.namelist())
        finally:
            module.subprocess.run = original_run
            module._openai_sdk_available = original_sdk

        bundle_step = next(step for step in payload["steps"] if step["name"] == "support_bundle_strict")
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "strict_support_bundle_missing")
        self.assertEqual(payload["support_bundle"]["reason"], "support_bundle_interrupted_by_user")
        self.assertEqual(bundle_step["reason"], "command_interrupted:support_bundle_strict")
        self.assertEqual(bundle_step["error_type"], "KeyboardInterrupt")
        self.assertIn("alpha_release_evidence.json", bundle_names)
        self.assertNotIn("support/dating-boost-support-strict.zip", bundle_names)

    def test_release_gate_keyboard_interrupt_writes_partial_evidence_bundle(self):
        module = _load_gate_module()
        calls = []

        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False, env=None, timeout=None):
            calls.append(cmd)
            if len(cmd) > 1 and str(cmd[1]).endswith("tashuo_mac_ios_standalone_smoke.py"):
                raise KeyboardInterrupt
            cli = cmd[3:]
            payload = {"status": "ok"}
            if cli[:1] == ["capabilities"]:
                payload = {
                    "supported_app_profiles": ["tashuo"],
                    "agent_native_capabilities": {"tashuo_mac_ios_app_runtime": True},
                    "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
                }
            elif cli[:2] == ["data", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:2] == ["safety", "status"]:
                payload = {"paused": False}
            elif cli[:2] == ["user", "readiness"]:
                payload = {"status": "ready", "ready": True, "reason": "ready"}
            elif cli[:2] in (["runtime", "select"], ["runtime", "status"]):
                payload = {"status": "selected"}
            elif cli[:3] == ["support", "session", "start"]:
                payload = {"status": "active", "session_id": "support_interrupt"}
            elif cli[:3] == ["support", "session", "stop"]:
                payload = {"status": "stopped"}
            elif cli[:2] == ["support", "bundle"]:
                output = Path(cli[cli.index("--output") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"strict support bundle")
                payload = {"status": "ok", "output": str(output), "redaction": "strict"}
            elif cli[:2] == ["harness", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:3] == ["harness", "tashuo", "launch"]:
                payload = {"status": "ok"}
            elif cli[:4] == ["harness", "tashuo", "action", "prepare-message-page"]:
                payload = {"status": "ok", "screen_state": "tashuo_chat_list", "next_host_action": "visual_plan_message_list"}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        original_sdk = module._openai_sdk_available
        module.subprocess.run = fake_run
        module._openai_sdk_available = lambda: True
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                env_file = root / ".env"
                env_file.write_text("MINIMAX_API_KEY=test\n", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--work-dir",
                            str(root / "work"),
                            "--authorization",
                            str(auth),
                            "--env-file",
                            str(env_file),
                            "--runs",
                            "2",
                            "--json",
                        ]
                    )
                payload = json.loads(stdout.getvalue())
                run_summary_path = root / "work" / "run_01_message_list" / "run_summary.json"
                run_summary = json.loads(run_summary_path.read_text(encoding="utf-8"))
                with zipfile.ZipFile(payload["evidence_bundle"]) as archive:
                    bundle_names = set(archive.namelist())
        finally:
            module.subprocess.run = original_run
            module._openai_sdk_available = original_sdk

        command_args = [call[3:] if call[1:3] == ["-m", "dating_boost.cli"] else call[1:] for call in calls]
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "alpha_release_gate_interrupted_by_user")
        self.assertEqual(payload["runs_completed"], 1)
        self.assertEqual(payload["runs_passed"], 0)
        self.assertTrue(payload["checks"]["zero_live_send_execution"])
        self.assertTrue(payload["checks"]["zero_high_risk_action"])
        self.assertTrue(payload["checks"]["strict_support_bundle"])
        self.assertEqual(run_summary["reason"], "alpha_release_gate_interrupted_by_user")
        self.assertTrue(run_summary["interrupted"])
        self.assertIn("runs/run_01_summary.json", bundle_names)
        self.assertNotIn("runs/run_01_smoke.json", bundle_names)
        self.assertTrue(any(command[:3] == ["support", "session", "stop"] for command in command_args))
        self.assertTrue(any(command[:2] == ["support", "bundle"] for command in command_args))

    def test_release_gate_harness_doctor_failure_after_support_start_exports_bundle(self):
        module = _load_gate_module()
        calls = []

        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False, env=None, timeout=None):
            calls.append(cmd)
            cli = cmd[3:]
            payload = {"status": "ok"}
            returncode = 0
            if cli[:1] == ["capabilities"]:
                payload = {
                    "supported_app_profiles": ["tashuo"],
                    "agent_native_capabilities": {"tashuo_mac_ios_app_runtime": True},
                    "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
                }
            elif cli[:2] == ["data", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:2] == ["safety", "status"]:
                payload = {"paused": False}
            elif cli[:2] == ["user", "readiness"]:
                payload = {"status": "ready", "ready": True, "reason": "ready"}
            elif cli[:2] in (["runtime", "select"], ["runtime", "status"]):
                payload = {"status": "selected"}
            elif cli[:3] == ["support", "session", "start"]:
                payload = {"status": "active", "session_id": "support_after_start"}
            elif cli[:3] == ["support", "session", "stop"]:
                payload = {"status": "stopped"}
            elif cli[:2] == ["support", "bundle"]:
                output = Path(cli[cli.index("--output") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"strict support bundle")
                payload = {"status": "ok", "output": str(output), "redaction": "strict"}
            elif cli[:2] == ["harness", "doctor"]:
                payload = {"status": "blocked", "reason": "mac_ios_app_gui_session_not_interactive"}
                returncode = 2
            return subprocess.CompletedProcess(cmd, returncode, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        original_sdk = module._openai_sdk_available
        module.subprocess.run = fake_run
        module._openai_sdk_available = lambda: True
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                env_file = root / ".env"
                env_file.write_text("MINIMAX_API_KEY=test\n", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--work-dir",
                            str(root / "work"),
                            "--authorization",
                            str(auth),
                            "--env-file",
                            str(env_file),
                            "--runs",
                            "1",
                            "--json",
                        ]
                    )
                payload = json.loads(stdout.getvalue())
                with zipfile.ZipFile(payload["evidence_bundle"]) as archive:
                    bundle_names = set(archive.namelist())
        finally:
            module.subprocess.run = original_run
            module._openai_sdk_available = original_sdk

        command_args = [call[3:] if call[1:3] == ["-m", "dating_boost.cli"] else call[1:] for call in calls]
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "mac_ios_app_gui_session_not_interactive")
        self.assertEqual(payload["support_session_id"], "support_after_start")
        self.assertTrue(payload["checks"]["strict_support_bundle"])
        self.assertTrue(payload["checks"]["support_bundle_required"])
        self.assertTrue(any(command[:3] == ["support", "session", "stop"] for command in command_args))
        self.assertTrue(any(command[:2] == ["support", "bundle"] for command in command_args))
        self.assertIn("support/dating-boost-support-strict.zip", bundle_names)

    def test_release_gate_rejects_direct_send_command_inside_smoke_payload(self):
        module = _load_gate_module()

        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False, env=None, timeout=None):
            if len(cmd) > 1 and str(cmd[1]).endswith("tashuo_mac_ios_standalone_smoke.py"):
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_smoke_payload(direct_send=True)), stderr="")
            cli = cmd[3:]
            payload = {"status": "ok"}
            if cli[:1] == ["capabilities"]:
                payload = {
                    "supported_app_profiles": ["tashuo"],
                    "agent_native_capabilities": {"tashuo_mac_ios_app_runtime": True},
                    "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
                }
            elif cli[:2] == ["data", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:2] == ["safety", "status"]:
                payload = {"paused": False}
            elif cli[:2] == ["user", "readiness"]:
                payload = {"status": "ready", "ready": True, "reason": "ready"}
            elif cli[:2] in (["runtime", "select"], ["runtime", "status"]):
                payload = {"status": "selected"}
            elif cli[:3] == ["support", "session", "start"]:
                payload = {"status": "active", "session_id": "support_1"}
            elif cli[:3] == ["support", "session", "stop"]:
                payload = {"status": "stopped"}
            elif cli[:2] == ["support", "bundle"]:
                output = Path(cli[cli.index("--output") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"strict support bundle")
                payload = {"status": "ok", "output": str(output), "redaction": "strict"}
            elif cli[:4] == ["harness", "tashuo", "action", "prepare-message-page"]:
                payload = {"status": "ok"}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        original_sdk = module._openai_sdk_available
        module.subprocess.run = fake_run
        module._openai_sdk_available = lambda: True
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                env_file = root / ".env"
                env_file.write_text("MINIMAX_API_KEY=test\n", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--work-dir",
                            str(root / "work"),
                            "--authorization",
                            str(auth),
                            "--env-file",
                            str(env_file),
                            "--runs",
                            "1",
                            "--json",
                        ]
                    )
                payload = json.loads(stdout.getvalue())
        finally:
            module.subprocess.run = original_run
            module._openai_sdk_available = original_sdk

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["smoke_runs"][0]["reason"], "forbidden_command_present:send-message")
        self.assertEqual(payload["command_safety_violation"], "forbidden_command_present:send-message")
        self.assertFalse(payload["checks"]["zero_live_send_execution"])
        self.assertFalse(payload["checks"]["zero_high_risk_action"])

    def test_release_gate_rejects_high_risk_alias_command_inside_smoke_payload(self):
        module = _load_gate_module()

        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False, env=None, timeout=None):
            if len(cmd) > 1 and str(cmd[1]).endswith("tashuo_mac_ios_standalone_smoke.py"):
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_smoke_payload(high_risk_alias=True)), stderr="")
            cli = cmd[3:]
            payload = {"status": "ok"}
            if cli[:1] == ["capabilities"]:
                payload = {
                    "supported_app_profiles": ["tashuo"],
                    "agent_native_capabilities": {"tashuo_mac_ios_app_runtime": True},
                    "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
                }
            elif cli[:2] == ["data", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:2] == ["safety", "status"]:
                payload = {"paused": False}
            elif cli[:2] == ["user", "readiness"]:
                payload = {"status": "ready", "ready": True, "reason": "ready"}
            elif cli[:2] in (["runtime", "select"], ["runtime", "status"]):
                payload = {"status": "selected"}
            elif cli[:3] == ["support", "session", "start"]:
                payload = {"status": "active", "session_id": "support_1"}
            elif cli[:3] == ["support", "session", "stop"]:
                payload = {"status": "stopped"}
            elif cli[:2] == ["support", "bundle"]:
                output = Path(cli[cli.index("--output") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"strict support bundle")
                payload = {"status": "ok", "output": str(output), "redaction": "strict"}
            elif cli[:4] == ["harness", "tashuo", "action", "prepare-message-page"]:
                payload = {"status": "ok"}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        original_sdk = module._openai_sdk_available
        module.subprocess.run = fake_run
        module._openai_sdk_available = lambda: True
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                env_file = root / ".env"
                env_file.write_text("MINIMAX_API_KEY=test\n", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--work-dir",
                            str(root / "work"),
                            "--authorization",
                            str(auth),
                            "--env-file",
                            str(env_file),
                            "--runs",
                            "1",
                            "--json",
                        ]
                    )
                payload = json.loads(stdout.getvalue())
        finally:
            module.subprocess.run = original_run
            module._openai_sdk_available = original_sdk

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["smoke_runs"][0]["reason"], "forbidden_command_present:profile_edit")
        self.assertEqual(payload["command_safety_violation"], "forbidden_command_present:profile_edit")
        self.assertTrue(payload["checks"]["zero_live_send_execution"])
        self.assertFalse(payload["checks"]["zero_high_risk_action"])

    def test_release_gate_evidence_bundle_includes_prepare_failure_summary(self):
        module = _load_gate_module()

        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False, env=None, timeout=None):
            cli = cmd[3:]
            payload = {"status": "ok"}
            if cli[:1] == ["capabilities"]:
                payload = {
                    "supported_app_profiles": ["tashuo"],
                    "agent_native_capabilities": {"tashuo_mac_ios_app_runtime": True},
                    "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
                }
            elif cli[:2] == ["data", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:2] == ["safety", "status"]:
                payload = {"paused": False}
            elif cli[:2] == ["user", "readiness"]:
                payload = {"status": "ready", "ready": True, "reason": "ready"}
            elif cli[:2] in (["runtime", "select"], ["runtime", "status"]):
                payload = {"status": "selected"}
            elif cli[:3] == ["support", "session", "start"]:
                payload = {"status": "active", "session_id": "support_1"}
            elif cli[:3] == ["support", "session", "stop"]:
                payload = {"status": "stopped"}
            elif cli[:2] == ["support", "bundle"]:
                output = Path(cli[cli.index("--output") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"strict support bundle")
                payload = {"status": "ok", "output": str(output), "redaction": "strict"}
            elif cli[:2] == ["harness", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:4] == ["harness", "tashuo", "action", "prepare-message-page"]:
                payload = {
                    "status": "blocked",
                    "reason": "diagnostic_prepare_message_page_failed",
                    "screen_state": "unknown",
                }
                return subprocess.CompletedProcess(cmd, 2, stdout=json.dumps(payload), stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        original_sdk = module._openai_sdk_available
        module.subprocess.run = fake_run
        module._openai_sdk_available = lambda: True
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                env_file = root / ".env"
                env_file.write_text("MINIMAX_API_KEY=test\n", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--work-dir",
                            str(root / "work"),
                            "--authorization",
                            str(auth),
                            "--env-file",
                            str(env_file),
                            "--runs",
                            "1",
                            "--json",
                        ]
                    )
                payload = json.loads(stdout.getvalue())
                with zipfile.ZipFile(payload["evidence_bundle"]) as archive:
                    bundle_names = set(archive.namelist())
        finally:
            module.subprocess.run = original_run
            module._openai_sdk_available = original_sdk

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["smoke_runs"][0]["reason"], "diagnostic_prepare_message_page_failed")
        self.assertIn("runs/run_01_summary.json", bundle_names)
        self.assertNotIn("runs/run_01_smoke.json", bundle_names)
        self.assertIn("support/dating-boost-support-strict.zip", bundle_names)

    def test_release_gate_blocks_missing_model_sdk_before_support_session(self):
        module = _load_gate_module()
        calls = []

        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False, env=None, timeout=None):
            calls.append(cmd)
            cli = cmd[3:]
            payload = {"status": "ok"}
            if cli[:1] == ["capabilities"]:
                payload = {
                    "supported_app_profiles": ["tashuo"],
                    "agent_native_capabilities": {"tashuo_mac_ios_app_runtime": True},
                    "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
                }
            elif cli[:2] == ["data", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:2] == ["safety", "status"]:
                payload = {"paused": False}
            elif cli[:2] == ["user", "readiness"]:
                payload = {"status": "ready", "ready": True, "reason": "ready"}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        original_sdk = module._openai_sdk_available
        module.subprocess.run = fake_run
        module._openai_sdk_available = lambda: False
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                env_file = root / ".env"
                env_file.write_text("MINIMAX_API_KEY=test\n", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--work-dir",
                            str(root / "work"),
                            "--authorization",
                            str(auth),
                            "--env-file",
                            str(env_file),
                            "--runs",
                            "1",
                            "--json",
                        ]
                    )
                payload = json.loads(stdout.getvalue())
        finally:
            module.subprocess.run = original_run
            module._openai_sdk_available = original_sdk

        command_args = [call[3:] if call[1:3] == ["-m", "dating_boost.cli"] else call[1:] for call in calls]
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "openai_sdk_missing_for_model_backend")
        self.assertTrue(payload["checks"]["zero_live_send_execution"])
        self.assertTrue(payload["checks"]["zero_high_risk_action"])
        self.assertTrue(payload["checks"]["strict_support_bundle"])
        self.assertFalse(payload["checks"]["support_bundle_required"])
        self.assertFalse(any(command[:3] == ["support", "session", "start"] for command in command_args))
        self.assertFalse(any(command[:2] == ["harness", "doctor"] for command in command_args))

    def test_release_gate_blocks_missing_user_readiness_before_support_session(self):
        module = _load_gate_module()
        calls = []

        def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False, env=None, timeout=None):
            calls.append(cmd)
            cli = cmd[3:]
            payload = {"status": "ok"}
            if cli[:1] == ["capabilities"]:
                payload = {
                    "supported_app_profiles": ["tashuo"],
                    "agent_native_capabilities": {"tashuo_mac_ios_app_runtime": True},
                    "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
                }
            elif cli[:2] == ["data", "doctor"]:
                payload = {"status": "ok"}
            elif cli[:2] == ["safety", "status"]:
                payload = {"paused": False}
            elif cli[:2] == ["user", "readiness"]:
                payload = {
                    "status": "needs_user_profile",
                    "ready": False,
                    "reason": "missing_user_disclosure_profile",
                    "mode": "autonomous",
                    "missing": ["dating_profile", "self_interview", "shareable_material"],
                }
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        original_run = module.subprocess.run
        original_sdk = module._openai_sdk_available
        module.subprocess.run = fake_run
        module._openai_sdk_available = lambda: True
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                auth = root / "auth.json"
                auth.write_text("{}", encoding="utf-8")
                env_file = root / ".env"
                env_file.write_text("MINIMAX_API_KEY=test\n", encoding="utf-8")
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = module.main(
                        [
                            "--data-dir",
                            str(root / "data"),
                            "--work-dir",
                            str(root / "work"),
                            "--authorization",
                            str(auth),
                            "--env-file",
                            str(env_file),
                            "--runs",
                            "1",
                            "--json",
                        ]
                    )
                payload = json.loads(stdout.getvalue())
        finally:
            module.subprocess.run = original_run
            module._openai_sdk_available = original_sdk

        command_args = [call[3:] if call[1:3] == ["-m", "dating_boost.cli"] else call[1:] for call in calls]
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "missing_user_disclosure_profile")
        self.assertTrue(payload["checks"]["zero_live_send_execution"])
        self.assertTrue(payload["checks"]["zero_high_risk_action"])
        self.assertTrue(payload["checks"]["strict_support_bundle"])
        self.assertFalse(payload["checks"]["support_bundle_required"])
        readiness_step = next(step for step in payload["steps"] if step["name"] == "user_readiness_autonomous")
        self.assertEqual(
            readiness_step["summary"]["missing"],
            ["dating_profile", "self_interview", "shareable_material"],
        )
        self.assertFalse(any(command[:3] == ["support", "session", "start"] for command in command_args))
        self.assertFalse(any(command[:2] == ["harness", "doctor"] for command in command_args))


if __name__ == "__main__":
    unittest.main()
