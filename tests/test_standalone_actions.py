import tempfile
import unittest
from pathlib import Path

from dating_boost.core.standalone_actions import StageOnlyActionExecutor
from dating_boost.core.standalone_observation import FixtureObservationProvider
from dating_boost.core.standalone_runtime import StandaloneAgentRuntime


class StandaloneActionExecutorTests(unittest.TestCase):
    def test_stage_executor_records_stage_result_without_live_send(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            executor = StageOnlyActionExecutor(data_dir)
            work_item = {
                "schema_version": 1,
                "work_item_type": "send_message",
                "work_item_id": "act_1",
                "action_request_id": "act_1",
                "target_match_id": "match_ada",
                "payload_text": "好呀",
                "payload_hash": "hash_1",
            }

            result = executor.execute(work_item, app_id="tinder")

        self.assertEqual(result["status"], "stage_recorded")
        self.assertEqual(result["action_request_id"], "act_1")
        self.assertEqual(result["result_status"], "succeeded")

    def test_live_without_executor_returns_wait_point(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executor = StageOnlyActionExecutor(Path(temp_dir) / "data", send_mode="live")

            result = executor.execute(
                {
                    "work_item_type": "send_message",
                    "action_request_id": "act_1",
                    "target_match_id": "match_ada",
                    "payload_hash": "hash_1",
                },
                app_id="tinder",
            )

        self.assertEqual(result["status"], "needs_live_executor")
        self.assertEqual(result["next_host_action"], "enable_managed_gui_send_or_switch_to_stage")

    def test_live_wait_point_requires_valid_send_binding(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executor = StageOnlyActionExecutor(Path(temp_dir) / "data", send_mode="live")

            result = executor.execute({"work_item_type": "send_message", "action_request_id": "act_1"}, app_id="tinder")

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "invalid_send_work_item:target_match_id")

    def test_stage_executor_blocks_invalid_inputs_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"

            malformed = StageOnlyActionExecutor(data_dir).execute(
                {"work_item_type": "send_message", "action_request_id": ""},
                app_id="tinder",
            )
            unsupported = StageOnlyActionExecutor(data_dir, send_mode="auto").execute(
                {"work_item_type": "send_message", "action_request_id": "act_1"},
                app_id="tinder",
            )

        self.assertEqual(malformed["status"], "blocked")
        self.assertEqual(malformed["reason"], "invalid_send_work_item:action_request_id")
        self.assertEqual(unsupported["status"], "blocked")
        self.assertEqual(unsupported["reason"], "unsupported_send_mode")

    def test_runtime_uses_action_executor_for_send_message_work_item(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            runtime = StandaloneAgentRuntime(
                data_dir,
                observation_provider=FixtureObservationProvider(fixture_dir),
                action_executor=StageOnlyActionExecutor(data_dir),
            )

            result = runtime.consume_work_item(
                {
                    "schema_version": 1,
                    "work_item_type": "send_message",
                    "action_request_id": "act_1",
                    "target_match_id": "match_ada",
                    "payload_text": "好呀",
                    "payload_hash": "hash_1",
                },
                managed_payload={"schema_version": 1, "status": "host_work_required", "app_id": "tinder"},
            )

        self.assertEqual(result["status"], "stage_recorded")
        self.assertEqual(result["result_status"], "succeeded")

    def test_runtime_blocks_action_executor_exception(self):
        class ExplodingExecutor:
            def execute(self, work_item, *, app_id):
                raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            runtime = StandaloneAgentRuntime(
                data_dir,
                observation_provider=FixtureObservationProvider(fixture_dir),
                action_executor=ExplodingExecutor(),
            )

            result = runtime.consume_work_item(
                {
                    "schema_version": 1,
                    "work_item_type": "send_message",
                    "action_request_id": "act_1",
                    "target_match_id": "match_ada",
                    "payload_hash": "hash_1",
                },
                managed_payload={"schema_version": 1, "status": "host_work_required", "app_id": "tinder"},
            )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "action_executor_failed")
        self.assertEqual(result["error_type"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
