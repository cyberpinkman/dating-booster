import copy
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost.cli import main


FIXTURE_DIR = Path("tests/fixtures/automation")


class ObservationAuthoringTests(unittest.TestCase):
    def test_observation_validate_accepts_operator_ready_thread(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_path = Path(temp_dir) / "thread.json"
            thread_path.write_text(json.dumps(_thread_observation(), ensure_ascii=False), encoding="utf-8")

            exit_code, payload = self._run([
                "observation",
                "validate",
                "--input",
                str(thread_path),
                "--json",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")

    def test_observation_validate_accepts_thread_with_no_new_inbound_after_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            thread = _thread_observation()
            thread["turn_boundary_evidence"] = {
                "latest_user_outbound_text": "两个😉有点像在打暗号哈哈，晚上好呀，你现在是在摸鱼还是准备休息了",
                "latest_user_outbound_index": 1,
                "latest_inbound_after_user": [],
            }
            thread["observation"]["conversation_observation"]["latest_inbound_messages"] = []
            thread["assessment"]["latest_match_message"] = "No new inbound after latest user outbound."
            thread["assessment"]["latest_inbound_fingerprint"] = "no_new_inbound_after_user"
            thread["assessment"]["recommended_next"] = "wait"
            thread_path = Path(temp_dir) / "no_new_inbound_thread.json"
            thread_path.write_text(json.dumps(thread, ensure_ascii=False), encoding="utf-8")

            exit_code, payload = self._run([
                "observation",
                "validate",
                "--input",
                str(thread_path),
                "--json",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")

    def test_observation_validate_rejects_thread_that_operator_ingest_would_reject(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            thread = _thread_observation()
            thread["assessment"] = {"conversation_stage": "warmup"}
            thread["draft"] = None
            thread["planner_assessment"] = {"schema_version": 1, "conversation_stage": "warmup"}
            thread_path = Path(temp_dir) / "bad_thread.json"
            thread_path.write_text(json.dumps(thread, ensure_ascii=False), encoding="utf-8")

            exit_code, payload = self._run([
                "observation",
                "validate",
                "--input",
                str(thread_path),
                "--json",
            ])

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "error")
        self.assertTrue(any("thread.assessment.latest_inbound_fingerprint" in error for error in payload["errors"]))
        self.assertTrue(any("thread.draft must be an object" in error for error in payload["errors"]))
        self.assertTrue(any("thread.planner_assessment.latest_turn_summary" in error for error in payload["errors"]))

    def _run(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        return exit_code, json.loads(output.getvalue())


def _thread_observation():
    scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
    thread = copy.deepcopy(scan["thread_observations"][0])
    thread["schema_version"] = 1
    thread["observation_type"] = "thread"
    thread["identity_confidence"] = "high"
    thread["identity_evidence"] = "Fixture row and visible thread match."
    thread["screenshot_ref"] = ""
    thread["turn_boundary_evidence"] = {
        "latest_user_outbound_text": "你猜猜会有什么奖励",
        "latest_user_outbound_index": 0,
        "latest_inbound_after_user": ["你定"],
    }
    thread["observation"]["conversation_observation"]["latest_inbound_messages"] = [
        {
            "sender": "match",
            "text": "你定",
            "is_after_latest_outbound": True,
        }
    ]
    return thread


if __name__ == "__main__":
    unittest.main()
