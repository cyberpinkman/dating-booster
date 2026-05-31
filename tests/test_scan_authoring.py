import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost.cli import main


FIXTURE_DIR = Path("tests/fixtures/automation")


class ScanAuthoringTests(unittest.TestCase):
    def test_scan_template_outputs_valid_batch_skeleton(self):
        exit_code, payload = self._run(["automation", "scan", "template", "--json"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["scan_budget"], 5)
        self.assertIn("message_list_snapshot", payload)
        self.assertIn("thread_observations", payload)

    def test_scan_validate_accepts_existing_fixture(self):
        exit_code, payload = self._run([
            "automation",
            "scan",
            "validate",
            "--input",
            str(FIXTURE_DIR / "scan_batch_initial.json"),
            "--json",
        ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["error_count"], 0)

    def test_scan_validate_rejects_missing_candidate_key_and_bad_draft(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            scan["message_list_snapshot"]["entries"][0].pop("candidate_key")
            scan["thread_observations"][0]["draft"].pop("naturalness_notes")
            scan_path = Path(temp_dir) / "bad_scan.json"
            scan_path.write_text(json.dumps(scan, ensure_ascii=False), encoding="utf-8")

            exit_code, payload = self._run([
                "automation",
                "scan",
                "validate",
                "--input",
                str(scan_path),
                "--json",
            ])

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "error")
        self.assertGreaterEqual(payload["error_count"], 2)
        self.assertTrue(any("candidate_key" in error for error in payload["errors"]))
        self.assertTrue(any("naturalness_notes" in error for error in payload["errors"]))

    def test_scan_validate_rejects_values_that_session_step_parser_would_reject(self):
        with self.subTest("invalid observation enum and draft enum"):
            with tempfile.TemporaryDirectory() as temp_dir:
                scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
                scan["thread_observations"][0]["observation"]["page_type"] = "not_a_real_page"
                scan["thread_observations"][0]["draft"]["persona_divergence"] = "extreme"
                scan_path = Path(temp_dir) / "bad_parser_scan.json"
                scan_path.write_text(json.dumps(scan, ensure_ascii=False), encoding="utf-8")

                exit_code, payload = self._run([
                    "automation",
                    "scan",
                    "validate",
                    "--input",
                    str(scan_path),
                    "--json",
                ])

            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "error")
            self.assertTrue(any("observation" in error and "not_a_real_page" in error for error in payload["errors"]))
            self.assertTrue(any("draft" in error and "persona_divergence" in error for error in payload["errors"]))

        with self.subTest("invalid draft list type"):
            with tempfile.TemporaryDirectory() as temp_dir:
                scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
                scan["thread_observations"][0]["draft"]["risk_flags"] = "not-a-list"
                scan_path = Path(temp_dir) / "bad_draft_list_scan.json"
                scan_path.write_text(json.dumps(scan, ensure_ascii=False), encoding="utf-8")

                exit_code, payload = self._run([
                    "automation",
                    "scan",
                    "validate",
                    "--input",
                    str(scan_path),
                    "--json",
                ])

            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "error")
            self.assertTrue(any("draft" in error and "risk_flags" in error for error in payload["errors"]))

    def test_scan_validate_checks_optional_planner_assessment_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            scan["thread_observations"][0]["planner_assessment"] = _planner_assessment()
            good_path = Path(temp_dir) / "good_planner_scan.json"
            good_path.write_text(json.dumps(scan, ensure_ascii=False), encoding="utf-8")

            bad_scan = json.loads(json.dumps(scan))
            bad_scan["thread_observations"][0]["planner_assessment"]["scores"]["engagement"] = 101
            bad_scan["thread_observations"][0]["planner_assessment"].pop("recommended_move")
            bad_path = Path(temp_dir) / "bad_planner_scan.json"
            bad_path.write_text(json.dumps(bad_scan, ensure_ascii=False), encoding="utf-8")

            good_exit, good_payload = self._run([
                "automation",
                "scan",
                "validate",
                "--input",
                str(good_path),
                "--json",
            ])
            bad_exit, bad_payload = self._run([
                "automation",
                "scan",
                "validate",
                "--input",
                str(bad_path),
                "--json",
            ])

        self.assertEqual(good_exit, 0)
        self.assertEqual(good_payload["status"], "ok")
        self.assertEqual(bad_exit, 2)
        self.assertEqual(bad_payload["status"], "error")
        self.assertTrue(any("planner_assessment" in error and "recommended_move" in error for error in bad_payload["errors"]))
        self.assertTrue(any("planner_assessment" in error and "engagement" in error for error in bad_payload["errors"]))

    def test_scan_normalize_adds_defaults_and_preview_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scan = {
                "schema_version": 1,
                "session_id": "session_normalize",
                "app_id": "tinder",
                "captured_at": "2026-05-26T10:00:00Z",
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_1",
                            "visible_name": "A",
                            "latest_preview": "你好",
                        }
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "scan.json"
            scan_path.write_text(json.dumps(scan, ensure_ascii=False), encoding="utf-8")

            exit_code, payload = self._run([
                "automation",
                "scan",
                "normalize",
                "--input",
                str(scan_path),
                "--json",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["scan_batch"]["scan_budget"], 5)
        self.assertEqual(payload["scan_batch"]["provenance"]["author"], "host_agent")
        self.assertTrue(payload["scan_batch"]["message_list_snapshot"]["entries"][0]["latest_preview_hash"].startswith("sha256:"))

    def test_scan_assemble_combines_message_list_and_threads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            list_path = Path(temp_dir) / "list.json"
            threads_path = Path(temp_dir) / "threads.json"
            list_path.write_text(
                json.dumps(source["message_list_snapshot"], ensure_ascii=False),
                encoding="utf-8",
            )
            threads_path.write_text(
                json.dumps({"thread_observations": source["thread_observations"]}, ensure_ascii=False),
                encoding="utf-8",
            )

            exit_code, payload = self._run([
                "automation",
                "scan",
                "assemble",
                "--message-list",
                str(list_path),
                "--threads",
                str(threads_path),
                "--session-id",
                "session_assembled",
                "--captured-at",
                "2026-05-26T10:00:00Z",
                "--json",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["scan_batch"]["session_id"], "session_assembled")
        self.assertEqual(
            len(payload["scan_batch"]["thread_observations"]),
            len(source["thread_observations"]),
        )

    def _run(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        return exit_code, json.loads(output.getvalue())


if __name__ == "__main__":
    unittest.main()


def _planner_assessment():
    return {
        "schema_version": 1,
        "latest_turn_summary": "The match delegated the choice.",
        "latest_turn_type": "handoff",
        "inbound_intent": "delegate",
        "topic": {
            "current_topic": "reward",
            "topic_state": "active",
            "new_information": ["match said 你定"],
            "stale_hooks": [],
        },
        "scores": {
            "engagement": 62,
            "warmth": 55,
            "curiosity": 35,
            "comfort": 50,
            "momentum": 61,
            "topic_saturation": 20,
            "logistics_readiness": 25,
            "risk": 10,
        },
        "recommended_stage": "warmup",
        "recommended_move": "take_the_lead",
        "next_milestone": "Accept the handoff with one light decision.",
        "avoid_next": ["do not ask her to decide again"],
        "soft_invite_allowed": False,
        "confidence": "high",
        "evidence": "The latest inbound delegates the choice.",
    }
