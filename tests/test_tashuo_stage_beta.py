import json
import subprocess
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.apps.tashuo.standalone import TaShuoMacIosStageExecutor
from dating_boost.core.safety import SafetyRepository
from dating_boost.core import tashuo_stage_beta as beta
from dating_boost.core.runtime_scope import RuntimeScopeRepository
from dating_boost.core.storage import JsonStorage


def _stage_beta_auth(**overrides):
    payload = {
        "schema_version": 1,
        "authorization_id": "auth_tashuo_beta_stage",
        "app_id": "tashuo",
        "scope": "send_chat_messages",
        "allowed_actions": ["send_message"],
        "allowed_match_ids": [],
        "goal_ids": [],
        "autonomous_send": True,
        "autonomous_nudge": False,
        "live_send": False,
        "requires_post_action_verification": True,
        "quiet_hours": [],
        "created_at": "2026-06-30T00:00:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "revoked_at": None,
    }
    payload.update(overrides)
    return payload


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _release_smoke_payload() -> dict:
    return {
        "schema_version": 1,
        "status": "ok",
        "reason": "tashuo_standalone_stage_smoke_complete",
        "steps": [
            {"cmd": ["standalone-session", "start", "--send-mode", "stage"], "status": "active", "returncode": 0},
            {"cmd": ["standalone-session", "tick"], "status": "stage_recorded", "returncode": 0},
        ],
        "final_input_verification": {
            "schema_version": 1,
            "status": "ok",
            "input_cleared": True,
            "final_input_character_count": 0,
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
            },
            "stage_binding": {
                "action_request_id": "act_1",
                "target_match_id": "match_1",
                "payload_hash": "payload_hash_1",
            },
            "stage_result": {
                "evidence": {"stage_mode": True, "live_send_executed": False},
            },
        },
    }


def _release_evidence_payload() -> dict:
    smoke_runs = []
    for run_number in range(1, 21):
        smoke_runs.append(
            {
                "schema_version": 1,
                "run_number": run_number,
                "initial_surface": "message-list",
                "status": "ok",
                "reason": "tashuo_stage_alpha_run_passed",
                "alpha_release_gate": {
                    "status": "ok",
                    "checks": {
                        "stage_only": True,
                        "live_send_not_executed": True,
                        "staged_text_verified": True,
                        "target_verified": True,
                        "final_input_empty": True,
                    },
                },
                "stage_binding": {
                    "action_request_id": "act_1",
                    "target_match_id": "match_1",
                    "payload_hash": "payload_hash_1",
                },
            }
        )
    return {
        "schema_version": 1,
        "status": "ok",
        "reason": "tashuo_stage_alpha_release_gate_passed",
        "git_commit": "unit",
        "tool_version": "unit",
        "data_schema_version": 2,
        "runtime_scope": {"status": "selected", "selected_app_id": "tashuo", "selected_runtime": "mac-ios-app"},
        "run_summary": {"runs_required": 20, "runs_completed": 20, "runs_passed": 20, "pass_rate": 1.0},
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
        "support_bundle_path": "/tmp/support.zip",
        "steps": [{"cmd": ["release", "doctor", "--json"], "status": "ok", "returncode": 0}],
        "smoke_runs": smoke_runs,
    }


def _write_release_bundle(path: Path) -> None:
    payload = _release_evidence_payload()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("alpha_release_evidence.json", json.dumps(payload, ensure_ascii=False))
        for run in payload["smoke_runs"]:
            run_number = int(run["run_number"])
            archive.writestr(f"runs/run_{run_number:02d}_smoke.json", json.dumps(_release_smoke_payload(), ensure_ascii=False))
            archive.writestr(f"runs/run_{run_number:02d}_summary.json", json.dumps(run, ensure_ascii=False))
        archive.writestr("support/dating-boost-support-strict.zip", b"strict")


def _gate_payload(
    *,
    action_request_id: str = "act_1",
    target_match_id: str = "match_1",
    payload_hash: str = "payload_hash_1",
) -> dict:
    return {
        "schema_version": 1,
        "status": "ok",
        "reason": "tashuo_stage_alpha_release_gate_passed",
        "runs_required": 1,
        "runs_completed": 1,
        "runs_passed": 1,
        "initial_surface": "message-list",
        "checks": {
            "zero_live_send_execution": True,
            "zero_high_risk_action": True,
            "strict_support_bundle": True,
        },
        "support_bundle_path": "/tmp/support.zip",
        "evidence_bundle_path": "/tmp/evidence.zip",
        "smoke_runs": [
            {
                "schema_version": 1,
                "run_number": 1,
                "status": "ok",
                "reason": "tashuo_stage_alpha_run_passed",
                "stage_binding": {
                    "action_request_id": action_request_id,
                    "target_match_id": target_match_id,
                    "payload_hash": payload_hash,
                },
                "final_input_verification": {
                    "status": "ok",
                    "input_cleared": True,
                    "final_input_character_count": 0,
                },
                "alpha_release_gate": {
                    "status": "ok",
                    "checks": {"target_verified": True},
                },
            }
        ],
    }


def _stage_result(
    *,
    action_request_id: str = "act_1",
    target_match_id: str = "match_1",
    payload_hash: str = "payload_hash_1",
    precondition_hash: str | None = "pre_hash_1",
) -> dict:
    payload = {
        "schema_version": 1,
        "event_type": "stage_result",
        "action_request_id": action_request_id,
        "target_match_id": target_match_id,
        "payload_hash": payload_hash,
        "pre_action_observation_id": "obs_1",
        "result_status": "succeeded",
        "evidence": {"stage_mode": True, "live_send_executed": False},
        "stage_attempt_status": "completed",
        "staged_text_verified": True,
        "staged_text_verification": {"status": "verified"},
        "target_verification": {"status": "ok"},
    }
    if precondition_hash is not None:
        payload["precondition_hash"] = precondition_hash
    return payload


class TaShuoStageBetaTests(unittest.TestCase):
    def test_capabilities_list_release_gate_and_beta_commands(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["capabilities", "--json", "--data-dir", temp_dir])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        for command in (
            "release gate tashuo-stage-alpha",
            "beta readiness",
            "beta feedback record",
            "beta tashuo-stage start",
            "beta tashuo-stage run",
            "beta tashuo-stage status",
            "beta tashuo-stage stop",
            "beta tashuo-stage report",
        ):
            self.assertIn(command, payload["supported_commands"])
        self.assertEqual(payload["schema_versions"]["beta_session"], 1)
        self.assertEqual(payload["schema_versions"]["beta_report"], 1)
        self.assertEqual(payload["schema_versions"]["beta_feedback"], 1)

    def test_release_gate_cli_wrapper_validates_existing_bundle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = Path(temp_dir) / "alpha_release_evidence_bundle.zip"
            _write_release_bundle(bundle)
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "release",
                        "gate",
                        "tashuo-stage-alpha",
                        "--validate-evidence-bundle",
                        str(bundle),
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["runtime_scope"]["selected_runtime"], "mac-ios-app")
        self.assertEqual(payload["run_summary"]["runs_passed"], 20)

    def test_beta_start_blocks_live_send_authorization_before_preflight(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth = _write_json(root / "auth.json", _stage_beta_auth(live_send=True))
            with patch.object(beta.subprocess, "run") as mocked_run:
                payload = beta.start_tashuo_stage_beta(
                    data_dir=root / "data",
                    authorization_path=auth,
                    work_dir=root / "work",
                )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "beta_authorization_live_send_must_be_false")
        mocked_run.assert_not_called()

    def test_beta_start_blocks_safety_paused_before_support_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth = _write_json(root / "auth.json", _stage_beta_auth())
            calls = []

            def fake_run_cli(steps, args, *, env, name, allow_failure=False):
                calls.append(args)
                if args[:2] == ["release", "doctor"]:
                    return {"status": "ok"}
                if args[:2] == ["data", "doctor"]:
                    return {"status": "ok"}
                if args[:1] == ["capabilities"]:
                    return {
                        "schema_version": 1,
                        "supported_app_profiles": ["tashuo"],
                        "agent_native_capabilities": {"tashuo_mac_ios_app_runtime": True},
                        "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
                    }
                if args[:2] == ["user", "readiness"]:
                    return {"status": "ready", "ready": True}
                if args[:2] == ["runtime", "select"]:
                    return {"status": "selected", "selected_app_id": "tashuo", "selected_runtime": "mac-ios-app"}
                if args[:2] == ["runtime", "status"]:
                    return {"status": "selected", "selected_app_id": "tashuo", "selected_runtime": "mac-ios-app"}
                if args[:2] == ["safety", "status"]:
                    return {"paused": True, "reason": "user_pause"}
                if args[:3] == ["support", "session", "start"]:
                    return {"status": "active", "session_id": "support_1"}
                return {"status": "ok"}

            with patch.object(beta, "_run_cli", side_effect=fake_run_cli):
                payload = beta.start_tashuo_stage_beta(
                    data_dir=root / "data",
                    authorization_path=auth,
                    work_dir=root / "work",
                )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "safety_paused")
        self.assertFalse(any(call[:3] == ["support", "session", "start"] for call in calls))

    def test_beta_start_blocks_missing_minimax_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth = _write_json(root / "auth.json", _stage_beta_auth())
            calls = []

            def fake_run_cli(steps, args, *, env, name, allow_failure=False):
                calls.append(args)
                if args[:2] == ["release", "doctor"]:
                    return {"status": "ok"}
                if args[:2] == ["data", "doctor"]:
                    return {"status": "ok"}
                if args[:1] == ["capabilities"]:
                    return {
                        "schema_version": 1,
                        "supported_app_profiles": ["tashuo"],
                        "agent_native_capabilities": {"tashuo_mac_ios_app_runtime": True},
                        "managed_live_send_guidance": {"direct_harness_scope": "executor_internal_only"},
                    }
                if args[:2] == ["user", "readiness"]:
                    return {"status": "ready", "ready": True}
                if args[:2] == ["runtime", "select"]:
                    return {"status": "selected", "selected_app_id": "tashuo", "selected_runtime": "mac-ios-app"}
                if args[:2] == ["runtime", "status"]:
                    return {"status": "selected", "selected_app_id": "tashuo", "selected_runtime": "mac-ios-app"}
                if args[:2] == ["safety", "status"]:
                    return {"paused": False, "reason": None}
                if args[:3] == ["support", "session", "start"]:
                    return {"status": "active", "session_id": "support_1"}
                return {"status": "ok"}

            with patch.object(beta, "_run_cli", side_effect=fake_run_cli), patch.dict(beta.os.environ, {}, clear=True):
                payload = beta.start_tashuo_stage_beta(
                    data_dir=root / "data",
                    authorization_path=auth,
                    work_dir=root / "work",
                )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "MINIMAX_API_KEY_missing")
        self.assertFalse(any(call[:3] == ["support", "session", "start"] for call in calls))

    def test_beta_run_writes_report_when_audit_binding_is_complete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            auth = _write_json(root / "auth.json", _stage_beta_auth())
            env_file = _write_json(root / "not-json.env", {})
            env_file.write_text("MINIMAX_API_KEY=test\n", encoding="utf-8")
            RuntimeScopeRepository(data_dir).select(app_id="tashuo", runtime="mac-ios-app")
            JsonStorage(data_dir).write_json(
                beta.BETA_SESSION_PATH,
                {
                    "schema_version": 1,
                    "status": "active",
                    "session_id": "beta_1",
                    "authorization_path": str(auth),
                    "work_dir": str(root / "work"),
                    "stage_result_count_at_start": 0,
                    "stage_result_cursor": 0,
                    "support_session_id": "support_outer",
                    "allowed_runtime_actions": ["observe", "open_ordinary_chat", "stage_draft", "clear_input"],
                    "run_records": [],
                },
            )
            audit_path = data_dir / "audit" / "stage_results.jsonl"
            audit_path.parent.mkdir(parents=True, exist_ok=True)

            def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False, env=None, timeout=None):
                self.assertEqual(cmd[1:5], ["-m", "dating_boost.cli", "release", "gate"])
                self.assertIn("--support-session-id", cmd)
                self.assertEqual(cmd[cmd.index("--support-session-id") + 1], "support_outer")
                audit_path.write_text(json.dumps(_stage_result()) + "\n", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_gate_payload()), stderr="")

            with patch.object(beta.subprocess, "run", side_effect=fake_run):
                payload = beta.run_tashuo_stage_beta(data_dir=data_dir, env_file=env_file)

            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["beta_report"]["audit_summary"]["complete"], True)
            self.assertEqual(payload["beta_report"]["live_send_execution_count"], 0)
            self.assertTrue((data_dir / beta.BETA_REPORT_PATH).is_file())
            self.assertTrue((root / "work" / "beta_report.json").is_file())
            session = json.loads((data_dir / beta.BETA_SESSION_PATH).read_text(encoding="utf-8"))
            self.assertEqual(session["stage_result_cursor"], 1)
            self.assertEqual(session["run_records"][0]["stage_result_count"], 1)

    def test_beta_run_blocks_when_stage_audit_binding_is_incomplete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            auth = _write_json(root / "auth.json", _stage_beta_auth())
            env_file = root / ".env"
            env_file.write_text("MINIMAX_API_KEY=test\n", encoding="utf-8")
            RuntimeScopeRepository(data_dir).select(app_id="tashuo", runtime="mac-ios-app")
            JsonStorage(data_dir).write_json(
                beta.BETA_SESSION_PATH,
                {
                    "schema_version": 1,
                    "status": "active",
                    "session_id": "beta_1",
                    "authorization_path": str(auth),
                    "work_dir": str(root / "work"),
                    "stage_result_count_at_start": 0,
                    "stage_result_cursor": 0,
                    "support_session_id": "support_outer",
                    "run_records": [],
                },
            )
            audit_path = data_dir / "audit" / "stage_results.jsonl"
            audit_path.parent.mkdir(parents=True, exist_ok=True)

            def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False, env=None, timeout=None):
                audit_path.write_text(json.dumps(_stage_result(precondition_hash=None)) + "\n", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_gate_payload()), stderr="")

            with patch.object(beta.subprocess, "run", side_effect=fake_run):
                payload = beta.run_tashuo_stage_beta(data_dir=data_dir, env_file=env_file)

            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["reason"], "beta_stage_audit_incomplete")
            self.assertIn("run[1].stage_result[1].precondition_hash", payload["beta_report"]["audit_summary"]["missing"])
            self.assertTrue((data_dir / beta.BETA_REPORT_PATH).is_file())

    def test_beta_stop_report_preserves_run_audit_summary_without_smoke_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            auth = _write_json(root / "auth.json", _stage_beta_auth())
            env_file = root / ".env"
            env_file.write_text("MINIMAX_API_KEY=test\n", encoding="utf-8")
            RuntimeScopeRepository(data_dir).select(app_id="tashuo", runtime="mac-ios-app")
            JsonStorage(data_dir).write_json(
                beta.BETA_SESSION_PATH,
                {
                    "schema_version": 1,
                    "status": "active",
                    "session_id": "beta_1",
                    "authorization_path": str(auth),
                    "work_dir": str(root / "work"),
                    "support_session_id": "support_outer",
                    "stage_result_count_at_start": 0,
                    "stage_result_cursor": 0,
                    "run_records": [],
                },
            )
            audit_path = data_dir / "audit" / "stage_results.jsonl"
            audit_path.parent.mkdir(parents=True, exist_ok=True)

            def fake_run(cmd, cwd=None, check=False, capture_output=False, text=False, env=None, timeout=None):
                audit_path.write_text(json.dumps(_stage_result()) + "\n", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(_gate_payload()), stderr="")

            def fake_run_cli(steps, args, *, env, name, allow_failure=False):
                if args[:3] == ["support", "session", "stop"]:
                    return {"status": "stopped"}
                if args[:2] == ["support", "bundle"]:
                    output = Path(args[args.index("--output") + 1])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(b"strict")
                    return {"status": "ok", "output": str(output), "redaction": "strict"}
                return {"status": "ok"}

            with patch.object(beta.subprocess, "run", side_effect=fake_run):
                run_payload = beta.run_tashuo_stage_beta(data_dir=data_dir, env_file=env_file)
            with patch.object(beta, "_run_cli", side_effect=fake_run_cli):
                stop_payload = beta.stop_tashuo_stage_beta(data_dir=data_dir, env_file=env_file)
            report_payload = beta.report_tashuo_stage_beta(data_dir=data_dir)

        self.assertEqual(run_payload["status"], "ok")
        self.assertEqual(stop_payload["status"], "stopped")
        self.assertTrue(stop_payload["beta_report"]["audit_summary"]["complete"])
        self.assertTrue(report_payload["audit_summary"]["complete"])
        self.assertEqual(report_payload["staged_count"], 1)

    def test_beta_authorization_blocks_expired_authorization(self):
        payload = beta.validate_stage_beta_authorization(_stage_beta_auth(expires_at="2026-01-01T00:00:00Z"))

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "beta_authorization_expired")

    def test_beta_feedback_rejects_raw_draft_and_records_hash_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            blocked = beta.record_stage_beta_feedback(
                data_dir=data_dir,
                feedback={
                    "status": "edited",
                    "target_match_id": "match_1",
                    "draft_hash": "hash_1",
                    "draft_text": "raw text must not be stored",
                },
            )
            recorded = beta.record_stage_beta_feedback(
                data_dir=data_dir,
                feedback={
                    "status": "accepted_as_is",
                    "target_match_id": "match_1",
                    "draft_hash": "hash_1",
                    "action_request_id": "act_1",
                },
            )

            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(recorded["status"], "ok")
            feedback_path = data_dir / beta.BETA_FEEDBACK_PATH
            text = feedback_path.read_text(encoding="utf-8")
            self.assertIn("accepted_as_is", text)
            self.assertNotIn("raw text must not be stored", text)

    def test_tashuo_stage_executor_blocks_on_safety_pause_before_gui_adapter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            SafetyRepository(data_dir).pause(reason="unit_pause", created_at="2026-06-30T00:00:00Z")
            adapter_created = []
            executor = TaShuoMacIosStageExecutor(
                root=data_dir,
                output_dir=Path(temp_dir) / "harness",
                adapter_factory=lambda: adapter_created.append(True),
            )
            payload = executor.execute(
                {
                    "work_item_type": "send_message",
                    "action_request_id": "act_1",
                    "candidate_key": "tashuo_visual_1",
                    "payload_text": "hello",
                    "payload_hash": "hash_1",
                    "target_match_id": "match_1",
                },
                app_id="tashuo",
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "safety_paused")
        self.assertEqual(adapter_created, [])


if __name__ == "__main__":
    unittest.main()
