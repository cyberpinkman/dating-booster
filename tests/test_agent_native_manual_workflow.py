import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost.cli import main


FIXTURE_DIR = Path("tests/fixtures/agent_native")


class AgentNativeManualWorkflowTests(unittest.TestCase):
    def test_reward_delegation_fixture_runs_screenshot_to_context_to_policy_to_feedback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            context_path = Path(temp_dir) / "context.json"

            capabilities_exit, capabilities, _ = self._run([
                "capabilities",
                "--json",
                "--data-dir",
                str(data_dir),
            ])
            init_exit, _, _ = self._run([
                "init-profile",
                "--data-dir",
                str(data_dir),
                "--input",
                "tests/fixtures/intelligence/user_profile.json",
            ])
            ingest_exit, ingest, _ = self._run([
                "memory",
                "ingest-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "reward_delegation_observation.json"),
            ])
            match_id = ingest["match_id"]
            get_exit, match_payload, _ = self._run([
                "memory",
                "get-match",
                "--data-dir",
                str(data_dir),
                "--match-id",
                match_id,
            ])
            context_exit, context_payload, _ = self._run([
                "context",
                "build",
                "--data-dir",
                str(data_dir),
                "--match-id",
                match_id,
                "--mode",
                "adaptive",
            ])
            context_path.write_text(json.dumps(context_payload, ensure_ascii=False), encoding="utf-8")
            policy_exit, policy_payload, policy_text = self._run([
                "policy",
                "check-draft",
                "--input",
                str(FIXTURE_DIR / "reward_delegation_draft.json"),
                "--context",
                str(context_path),
            ])
            feedback_exit, feedback_payload, _ = self._run([
                "feedback",
                "record",
                "--data-dir",
                str(data_dir),
                "--match-id",
                match_id,
                "--draft-id",
                "reward_delegation_draft_1",
                "--mode",
                "adaptive",
                "--label",
                "accepted",
            ])

            self.assertEqual(capabilities_exit, 0)
            self.assertTrue(capabilities["agent_native_capabilities"]["llm_owned_by_host_agent"])
            self.assertEqual(init_exit, 0)
            self.assertEqual(ingest_exit, 0)
            self.assertEqual(ingest["observation_id"], "obs_reward_delegation_001")
            self.assertEqual(get_exit, 0)
            self.assertIn("obs_reward_delegation_001", match_payload["match"]["observation_ids"])
            self.assertEqual(context_exit, 0)
            self.assertEqual(context_payload["context_pack"]["reply_mode"], "adaptive")
            self.assertEqual(self._context_item(context_payload, "latest_message")["text"], "你定")
            self.assertIn("日料", self._context_item(context_payload, "conversation_summary"))
            self.assertIn("take_the_lead", " ".join(self._context_item(context_payload, "match_hooks")))
            self.assertEqual(policy_exit, 0)
            self.assertTrue(policy_payload["policy"]["allowed"])
            self.assertNotIn("亲亲", policy_text)
            self.assertEqual(feedback_exit, 0)
            self.assertEqual(feedback_payload["status"], "ok")

            feedback_path = data_dir / "matches" / match_id / "feedback_events.jsonl"
            feedback_events = [
                json.loads(line)
                for line in feedback_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(feedback_events[0]["label"], "accepted")
            self.assertEqual(feedback_events[0]["draft_id"], "reward_delegation_draft_1")

    def test_workflow_draft_runner_orchestrates_reward_fixture(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"

            init_exit, _, _ = self._run([
                "init-profile",
                "--data-dir",
                str(data_dir),
                "--input",
                "tests/fixtures/intelligence/user_profile.json",
            ])
            workflow_exit, workflow_payload, workflow_text = self._run([
                "workflow",
                "draft",
                "--data-dir",
                str(data_dir),
                "--observation",
                str(FIXTURE_DIR / "reward_delegation_observation.json"),
                "--draft",
                str(FIXTURE_DIR / "reward_delegation_draft.json"),
                "--mode",
                "adaptive",
                "--feedback-label",
                "accepted",
                "--draft-id",
                "reward_delegation_draft_1",
            ])

            self.assertEqual(init_exit, 0)
            self.assertEqual(workflow_exit, 0)
            self.assertEqual(workflow_payload["schema_version"], 1)
            self.assertEqual(workflow_payload["workflow"], "draft")
            self.assertEqual(workflow_payload["status"], "ok")
            self.assertEqual(workflow_payload["steps"]["capabilities"], "ok")
            self.assertEqual(workflow_payload["steps"]["ingest_observation"], "ok")
            self.assertEqual(workflow_payload["steps"]["context_build"], "ok")
            self.assertEqual(workflow_payload["steps"]["policy_check_draft"], "ok")
            self.assertEqual(workflow_payload["steps"]["feedback_record"], "ok")
            self.assertEqual(workflow_payload["observation_id"], "obs_reward_delegation_001")
            self.assertEqual(workflow_payload["context_pack"]["reply_mode"], "adaptive")
            self.assertEqual(self._context_item(workflow_payload, "latest_message")["text"], "你定")
            self.assertTrue(workflow_payload["policy"]["allowed"])
            self.assertEqual(workflow_payload["draft"]["conversation_move"], "take_the_lead")
            self.assertEqual(workflow_payload["feedback"]["label"], "accepted")
            self.assertNotIn("亲亲", workflow_text)

            feedback_path = data_dir / "matches" / workflow_payload["match_id"] / "feedback_events.jsonl"
            self.assertTrue(feedback_path.exists())

    def _run(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        text = output.getvalue()
        return exit_code, json.loads(text), text

    def _context_item(self, context_payload, label):
        for item in context_payload["context_pack"]["items"]:
            if item["label"] == label:
                return item["content"]
        self.fail(f"missing context item: {label}")


if __name__ == "__main__":
    unittest.main()
