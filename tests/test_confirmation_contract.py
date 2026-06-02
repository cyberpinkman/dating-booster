import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main


class ConfirmationContractTests(unittest.TestCase):
    def test_confirmation_create_confirm_and_validate_binds_action_target_payload_and_precondition(self):
        with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T00:00:00Z"}):
            with tempfile.TemporaryDirectory() as temp_dir:
                data_dir = Path(temp_dir) / "data"
                payload_path = Path(temp_dir) / "payload.json"
                precondition_path = Path(temp_dir) / "precondition.json"
                changed_payload_path = Path(temp_dir) / "changed_payload.json"
                changed_precondition_path = Path(temp_dir) / "changed_precondition.json"
                self._write_json(payload_path, {"text": "Hi Ada"})
                self._write_json(precondition_path, {"observation_id": "obs_before", "fingerprint": "ada:1"})
                self._write_json(changed_payload_path, {"text": "Hi Bea"})
                self._write_json(changed_precondition_path, {"observation_id": "obs_other", "fingerprint": "ada:2"})

                create_exit, create_payload, _ = self._run(
                    [
                        "confirmation",
                        "create",
                        "--data-dir",
                        str(data_dir),
                        "--action",
                        "send_message",
                        "--target-match-id",
                        "match_ada",
                        "--payload-json",
                        str(payload_path),
                        "--precondition-json",
                        str(precondition_path),
                        "--expires-at",
                        "2026-05-26T01:00:00Z",
                        "--json",
                    ]
                )
                pending_exit, pending_payload, _ = self._run(
                    [
                        "confirmation",
                        "validate",
                        "--data-dir",
                        str(data_dir),
                        "--confirmation-id",
                        create_payload["confirmation_id"],
                        "--action",
                        "send_message",
                        "--target-match-id",
                        "match_ada",
                        "--payload-json",
                        str(payload_path),
                        "--precondition-json",
                        str(precondition_path),
                        "--json",
                    ]
                )
                confirm_exit, confirm_payload, _ = self._run(
                    [
                        "confirmation",
                        "confirm",
                        "--data-dir",
                        str(data_dir),
                        "--confirmation-id",
                        create_payload["confirmation_id"],
                        "--json",
                    ]
                )
                valid_exit, valid_payload, _ = self._run(
                    [
                        "confirmation",
                        "validate",
                        "--data-dir",
                        str(data_dir),
                        "--confirmation-id",
                        create_payload["confirmation_id"],
                        "--action",
                        "send_message",
                        "--target-match-id",
                        "match_ada",
                        "--payload-json",
                        str(payload_path),
                        "--precondition-json",
                        str(precondition_path),
                        "--json",
                    ]
                )
                target_exit, target_payload, _ = self._run(
                    [
                        "confirmation",
                        "validate",
                        "--data-dir",
                        str(data_dir),
                        "--confirmation-id",
                        create_payload["confirmation_id"],
                        "--action",
                        "send_message",
                        "--target-match-id",
                        "match_bea",
                        "--payload-json",
                        str(payload_path),
                        "--precondition-json",
                        str(precondition_path),
                        "--json",
                    ]
                )
                payload_exit, payload_mismatch, _ = self._run(
                    [
                        "confirmation",
                        "validate",
                        "--data-dir",
                        str(data_dir),
                        "--confirmation-id",
                        create_payload["confirmation_id"],
                        "--action",
                        "send_message",
                        "--target-match-id",
                        "match_ada",
                        "--payload-json",
                        str(changed_payload_path),
                        "--precondition-json",
                        str(precondition_path),
                        "--json",
                    ]
                )
                precondition_exit, precondition_mismatch, _ = self._run(
                    [
                        "confirmation",
                        "validate",
                        "--data-dir",
                        str(data_dir),
                        "--confirmation-id",
                        create_payload["confirmation_id"],
                        "--action",
                        "send_message",
                        "--target-match-id",
                        "match_ada",
                        "--payload-json",
                        str(payload_path),
                        "--precondition-json",
                        str(changed_precondition_path),
                        "--json",
                    ]
                )

                self.assertEqual(create_exit, 0)
                self.assertEqual(create_payload["status"], "pending")
                self.assertEqual(create_payload["action"], "send_message")
                self.assertEqual(create_payload["target_match_id"], "match_ada")
                self.assertRegex(create_payload["payload_hash"], r"^sha256:")
                self.assertRegex(create_payload["precondition_hash"], r"^sha256:")
                self.assertEqual(pending_exit, 2)
                self.assertEqual(pending_payload["reason"], "confirmation_not_confirmed")
                self.assertEqual(confirm_exit, 0)
                self.assertEqual(confirm_payload["status"], "confirmed")
                self.assertEqual(valid_exit, 0)
                self.assertEqual(valid_payload["status"], "ok")
                self.assertEqual(target_exit, 2)
                self.assertEqual(target_payload["reason"], "target_match_id_mismatch")
                self.assertEqual(payload_exit, 2)
                self.assertEqual(payload_mismatch["reason"], "payload_hash_mismatch")
                self.assertEqual(precondition_exit, 2)
                self.assertEqual(precondition_mismatch["reason"], "precondition_hash_mismatch")

    def test_expired_confirmation_is_blocked(self):
        with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T00:00:00Z"}):
            with tempfile.TemporaryDirectory() as temp_dir:
                data_dir = Path(temp_dir) / "data"
                payload_path = Path(temp_dir) / "payload.json"
                precondition_path = Path(temp_dir) / "precondition.json"
                self._write_json(payload_path, {"text": "Hi Ada"})
                self._write_json(precondition_path, {"observation_id": "obs_before"})

                _, create_payload, _ = self._run(
                    [
                        "confirmation",
                        "create",
                        "--data-dir",
                        str(data_dir),
                        "--action",
                        "send_message",
                        "--target-match-id",
                        "match_ada",
                        "--payload-json",
                        str(payload_path),
                        "--precondition-json",
                        str(precondition_path),
                        "--expires-at",
                        "2026-05-25T23:59:00Z",
                        "--json",
                    ]
                )
                self._run(
                    [
                        "confirmation",
                        "confirm",
                        "--data-dir",
                        str(data_dir),
                        "--confirmation-id",
                        create_payload["confirmation_id"],
                        "--json",
                    ]
                )
                validate_exit, validate_payload, _ = self._run(
                    [
                        "confirmation",
                        "validate",
                        "--data-dir",
                        str(data_dir),
                        "--confirmation-id",
                        create_payload["confirmation_id"],
                        "--action",
                        "send_message",
                        "--target-match-id",
                        "match_ada",
                        "--payload-json",
                        str(payload_path),
                        "--precondition-json",
                        str(precondition_path),
                        "--json",
                    ]
                )

                self.assertEqual(validate_exit, 2)
                self.assertEqual(validate_payload["status"], "blocked")
                self.assertEqual(validate_payload["reason"], "confirmation_expired")

    def _run(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        text = output.getvalue()
        return exit_code, json.loads(text), text

    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
