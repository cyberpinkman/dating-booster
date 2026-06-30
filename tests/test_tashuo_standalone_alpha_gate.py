import json
import importlib.util
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost.core.tashuo_standalone_alpha_gate import evaluate_alpha_gate


def _load_gate_script():
    path = Path("scripts/tashuo_mac_ios_standalone_alpha_gate.py")
    spec = importlib.util.spec_from_file_location("tashuo_mac_ios_standalone_alpha_gate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _smoke_payload() -> dict:
    return {
        "schema_version": 1,
        "status": "ok",
        "reason": "tashuo_standalone_stage_smoke_complete",
        "steps": [
            {
                "cmd": ["standalone-session", "tick", "--data-dir", "data", "--json"],
                "returncode": 0,
                "status": "stage_recorded",
                "reason": "stage_recorded",
                "recorded": {
                    "event_id": "stage_result_abc",
                    "action_request_id": "act_1",
                    "target_match_id": "match_1",
                    "payload_hash": "hash_1",
                },
            }
        ],
        "final_input_verification": {
            "schema_version": 1,
            "status": "ok",
            "verification_method": "unit_fake",
            "input_cleared": True,
            "final_input_character_count": 0,
            "reason": None,
        },
    }


def _stage_result(**overrides) -> dict:
    event = {
        "schema_version": 1,
        "event_type": "stage_result",
        "event_id": "stage_result_abc",
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
        "staged_text_verification": {
            "status": "verified",
            "exact_text_ax_verified": True,
        },
        "target_verification": {
            "status": "ok",
            "verification_method": "tashuo_stage_target_in_place_vision_identity_check",
        },
        "created_at": "2026-06-22T00:00:00Z",
    }
    event.update(overrides)
    return event


def _write_stage_result(data_dir: Path, event: dict) -> None:
    audit_dir = data_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "stage_results.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")


class TaShuoStandaloneAlphaGateTests(unittest.TestCase):
    def test_gate_accepts_real_stage_only_smoke_with_durable_exact_stage_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _write_stage_result(data_dir, _stage_result())

            payload = evaluate_alpha_gate(_smoke_payload(), data_dir=data_dir)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["reason"], "tashuo_standalone_alpha_gate_passed")
        self.assertEqual(payload["stage_result"]["event_id"], "stage_result_abc")
        self.assertTrue(payload["checks"]["stage_only"])
        self.assertTrue(payload["checks"]["staged_text_verified"])
        self.assertTrue(payload["checks"]["target_verified"])

    def test_gate_rejects_status_only_success_without_durable_stage_audit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = evaluate_alpha_gate(_smoke_payload(), data_dir=Path(temp_dir) / "data")

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "alpha_gate_stage_result_missing")

    def test_gate_rejects_stage_recorded_tick_without_stage_result_binding(self):
        smoke = _smoke_payload()
        smoke["steps"][0].pop("recorded")
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _write_stage_result(data_dir, _stage_result())

            payload = evaluate_alpha_gate(smoke, data_dir=data_dir)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "alpha_gate_final_tick_stage_binding_missing")

    def test_gate_rejects_stale_stage_audit_not_bound_to_final_tick(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _write_stage_result(data_dir, _stage_result(event_id="stage_result_old"))

            payload = evaluate_alpha_gate(_smoke_payload(), data_dir=data_dir)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "alpha_gate_stage_result_not_bound_to_final_tick")

    def test_gate_rejects_stage_result_without_exact_staged_text_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _write_stage_result(
                data_dir,
                _stage_result(
                    staged_text_verified=False,
                    staged_text_verification={"status": "needs_user_verification"},
                ),
            )

            payload = evaluate_alpha_gate(_smoke_payload(), data_dir=data_dir)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "alpha_gate_staged_text_not_verified")

    def test_gate_rejects_stage_result_without_precondition_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            event = _stage_result()
            event.pop("precondition_hash")
            _write_stage_result(data_dir, event)

            payload = evaluate_alpha_gate(_smoke_payload(), data_dir=data_dir)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "alpha_gate_precondition_hash_missing")

    def test_gate_rejects_success_without_final_empty_input_verification(self):
        smoke = _smoke_payload()
        smoke.pop("final_input_verification")
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _write_stage_result(data_dir, _stage_result())

            payload = evaluate_alpha_gate(smoke, data_dir=data_dir)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "alpha_gate_final_input_not_verified_empty")

    def test_gate_rejects_direct_send_command_in_smoke_steps(self):
        smoke = _smoke_payload()
        smoke["steps"].append({"cmd": ["harness", "tashuo", "send-message"], "status": "ok"})
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _write_stage_result(data_dir, _stage_result())

            payload = evaluate_alpha_gate(smoke, data_dir=data_dir)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "alpha_gate_direct_send_command_present")

    def test_gate_script_checks_saved_smoke_json(self):
        module = _load_gate_script()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            smoke_json = root / "smoke.json"
            smoke_json.write_text(json.dumps(_smoke_payload()), encoding="utf-8")
            _write_stage_result(data_dir, _stage_result())
            stdout = StringIO()

            with redirect_stdout(stdout):
                exit_code = module.main(["--data-dir", str(data_dir), "--smoke-json", str(smoke_json), "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["reason"], "tashuo_standalone_alpha_gate_passed")


if __name__ == "__main__":
    unittest.main()
