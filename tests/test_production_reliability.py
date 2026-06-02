import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.core.production_store import ProductionDataStore


FIXTURE_DIR = Path("tests/fixtures/automation")


class ProductionReliabilityTests(unittest.TestCase):
    def setUp(self):
        self._clock_patch = patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T00:00:00Z"})
        self._clock_patch.start()

    def tearDown(self):
        self._clock_patch.stop()

    def test_automation_step_outputs_run_id_idempotency_key_lock_and_replays_same_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run(
                [
                    "automation",
                    "session",
                    "start",
                    "--data-dir",
                    str(data_dir),
                    "--authorization",
                    str(FIXTURE_DIR / "auth_send.json"),
                ]
            )

            first_exit, first_payload, _ = self._run(
                [
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(FIXTURE_DIR / "scan_batch_initial.json"),
                    "--run-id",
                    "run-prod-1",
                    "--idempotency-key",
                    "idem-prod-1",
                ]
            )
            replay_exit, replay_payload, _ = self._run(
                [
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(FIXTURE_DIR / "scan_batch_initial.json"),
                    "--run-id",
                    "run-prod-2",
                    "--idempotency-key",
                    "idem-prod-1",
                ]
            )

            self.assertEqual(first_exit, 0)
            self.assertEqual(first_payload["status"], "ok")
            self.assertEqual(first_payload["run_id"], "run-prod-1")
            self.assertEqual(first_payload["idempotency_key"], "idem-prod-1")
            self.assertEqual(first_payload["lock"]["lock_name"], "automation_session_step")
            self.assertEqual(first_payload["lock"]["status"], "released")
            self.assertEqual(len(first_payload["action_requests"]), 1)
            self.assertIn("autonomous_audit_binding", first_payload["action_requests"][0])

            self.assertEqual(replay_exit, 0)
            self.assertEqual(replay_payload["status"], "ok")
            self.assertEqual(replay_payload["run_id"], "run-prod-1")
            self.assertEqual(replay_payload["idempotency_key"], "idem-prod-1")
            self.assertEqual(replay_payload["action_requests"], [])
            self.assertEqual(
                replay_payload["replayed_action_request_ids"],
                [first_payload["action_requests"][0]["action_request_id"]],
            )
            self.assertIn("idempotency_replay", replay_payload["warnings"])
            self.assertIn("duplicate_send_request_suppressed", replay_payload["warnings"])
            self.assertEqual(replay_payload["lock"]["status"], "replayed")

    def test_default_idempotency_key_ignores_scan_cursor_and_capture_time(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            first_scan = Path(temp_dir) / "first_scan.json"
            second_scan = Path(temp_dir) / "second_scan.json"
            first_payload = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            second_payload = dict(first_payload)
            second_payload["scan_cursor"] = "cursor_changed"
            second_payload["captured_at"] = "2026-05-26T00:05:00Z"
            self._write_json(first_scan, first_payload)
            self._write_json(second_scan, second_payload)
            self._init_profile(data_dir)
            self._run(
                [
                    "automation",
                    "session",
                    "start",
                    "--data-dir",
                    str(data_dir),
                    "--authorization",
                    str(FIXTURE_DIR / "auth_send.json"),
                ]
            )

            _, first_step, _ = self._run(
                [
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(first_scan),
                ]
            )
            _, second_step, _ = self._run(
                [
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(second_scan),
                ]
            )

            self.assertEqual(second_step["idempotency_key"], first_step["idempotency_key"])
            self.assertEqual(second_step["action_requests"], [])
            self.assertIn("idempotency_replay", second_step["warnings"])

    def test_active_automation_lock_blocks_step_and_expired_lock_is_taken_over(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run(
                [
                    "automation",
                    "session",
                    "start",
                    "--data-dir",
                    str(data_dir),
                    "--authorization",
                    str(FIXTURE_DIR / "auth_send.json"),
                ]
            )
            store = ProductionDataStore(data_dir)
            store.ensure_schema()
            store.write_lock(
                "automation_session_step",
                owner="test-owner",
                run_id="run-existing",
                started_at="2026-05-26T00:00:00Z",
                expires_at="2026-05-26T00:30:00Z",
                status="active",
            )

            blocked_exit, blocked_payload, _ = self._run(
                [
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(FIXTURE_DIR / "scan_batch_initial.json"),
                    "--run-id",
                    "run-blocked",
                ]
            )
            store.write_lock(
                "automation_session_step",
                owner="test-owner",
                run_id="run-expired",
                started_at="2026-05-25T23:00:00Z",
                expires_at="2026-05-25T23:30:00Z",
                status="active",
            )
            takeover_exit, takeover_payload, _ = self._run(
                [
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(FIXTURE_DIR / "scan_batch_initial.json"),
                    "--run-id",
                    "run-takeover",
                ]
            )

            self.assertEqual(blocked_exit, 0)
            self.assertEqual(blocked_payload["status"], "blocked")
            self.assertEqual(blocked_payload["reason"], "automation_lock_active")
            self.assertEqual(blocked_payload["lock"]["owner"], "test-owner")
            self.assertEqual(blocked_payload["action_requests"], [])
            self.assertEqual(takeover_exit, 0)
            self.assertEqual(takeover_payload["status"], "ok")
            self.assertTrue(takeover_payload["lock"]["takeover"])

    def test_operator_next_respects_local_decision_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run(
                [
                    "operator",
                    "session",
                    "start",
                    "--data-dir",
                    str(data_dir),
                    "--authorization",
                    str(FIXTURE_DIR / "auth_send.json"),
                ]
            )
            store = ProductionDataStore(data_dir)
            store.ensure_schema()
            store.write_lock(
                "operator_next",
                owner="test-owner",
                run_id="run-operator",
                started_at="2026-05-26T00:00:00Z",
                expires_at="2026-05-26T00:30:00Z",
                status="active",
            )

            exit_code, payload, _ = self._run(["operator", "next", "--data-dir", str(data_dir)])

            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["reason"], "automation_lock_active")
            self.assertEqual(payload["lock"]["owner"], "test-owner")

    def test_operator_success_result_without_confirmation_or_binding_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            (data_dir / "automation").mkdir(parents=True)
            (data_dir / "operator").mkdir(parents=True)
            self._write_json(
                data_dir / "automation" / "states.json",
                {
                    "schema_version": 1,
                    "states": [
                        {
                            "schema_version": 1,
                            "match_id": "match_ada",
                            "state": "send_requested",
                            "last_action": "send_message",
                            "last_action_request_id": "action_request_ada",
                            "last_outbound_payload_hash": "hash_ada",
                            "last_pre_action_observation_id": "obs_before",
                            "last_precondition_hash": "sha256:precondition",
                            "last_autonomous_audit_binding": {
                                "schema_version": 1,
                                "binding_type": "autonomous_authorization",
                                "authorization_id": "auth_send",
                                "action": "send_message",
                                "target_match_id": "match_ada",
                                "payload_hash": "hash_ada",
                                "precondition_hash": "sha256:precondition",
                            },
                        }
                    ],
                },
            )
            self._write_json(
                data_dir / "operator" / "session.json",
                {
                    "schema_version": 1,
                    "session_id": "session_operator",
                    "status": "active",
                    "current_work_item": {
                        "schema_version": 1,
                        "work_item_id": "action_request_ada",
                        "work_item_type": "send_message",
                        "action_request_id": "action_request_ada",
                    },
                },
            )
            action_result_path = Path(temp_dir) / "action_result.json"
            self._write_json(
                action_result_path,
                {
                    "action_request_id": "action_request_ada",
                    "action": "send_message",
                    "target_match_id": "match_ada",
                    "payload_hash": "hash_ada",
                    "pre_action_observation_id": "obs_before",
                    "post_action_observation_id": "obs_after",
                    "result_status": "succeeded",
                    "evidence": {"verification": "post-send bubble visible"},
                },
            )

            exit_code, payload, _ = self._run(
                [
                    "operator",
                    "record-action-result",
                    "--data-dir",
                    str(data_dir),
                    "--input",
                    str(action_result_path),
                ]
            )

            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "error")
            self.assertEqual(payload["reason"], "confirmation_contract_required")

    def _init_profile(self, data_dir):
        self._run(
            [
                "init-profile",
                "--data-dir",
                str(data_dir),
                "--input",
                "tests/fixtures/intelligence/user_profile.json",
            ]
        )
        self._run(
            [
                "user",
                "ingest-profile",
                "--data-dir",
                str(data_dir),
                "--input",
                "tests/fixtures/intelligence/user_dating_profile.json",
            ]
        )
        self._run(
            [
                "user",
                "ingest-interview",
                "--data-dir",
                str(data_dir),
                "--input",
                "tests/fixtures/intelligence/user_self_interview.json",
            ]
        )

    def _run(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        text = output.getvalue()
        return exit_code, json.loads(text), text

    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
