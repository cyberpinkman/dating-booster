import json
import tempfile
import unittest
from pathlib import Path

from dating_boost.core.managed_session import ManagedSessionRepository
from dating_boost.core.standalone_observation import (
    FixtureObservationProvider,
    _thread_fixture_name,
    fixture_harness_factory,
)
from dating_boost.core.standalone_runtime import StandaloneAgentRuntime


class FixtureObservationProviderTests(unittest.TestCase):
    def test_loads_message_list_and_thread_observations_in_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            (fixture_dir / "message_list.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "observation_type": "message_list",
                        "app_id": "tinder",
                        "message_list_snapshot": {
                            "entries": [{"candidate_key": "row_ada", "visible_name": "Ada"}]
                        },
                        "scan_cursor": {"current": None, "next": None, "exhausted": True},
                    }
                ),
                encoding="utf-8",
            )
            (fixture_dir / "thread_row_ada.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "observation_type": "thread",
                        "app_id": "tinder",
                        "match_identity_hints": {"visible_name": "Ada", "conversation_fingerprint": "ada-fp"},
                        "conversation_observation": {"visible_messages": [{"sender": "match", "text": "你定"}]},
                    }
                ),
                encoding="utf-8",
            )
            provider = FixtureObservationProvider(fixture_dir)

            message_list = provider.observe_message_list(app_id="tinder", scan_cursor={})
            thread = provider.observe_thread(app_id="tinder", candidate_key="row_ada")

        self.assertEqual(message_list["observation_type"], "message_list")
        self.assertEqual(thread["observation_type"], "thread")
        self.assertEqual(thread["candidate_key"], "row_ada")

    def test_rejects_invalid_scan_cursor_and_preserves_empty_cursor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            (fixture_dir / "message_list.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "observation_type": "message_list",
                        "app_id": "tinder",
                        "message_list_snapshot": {"entries": []},
                    }
                ),
                encoding="utf-8",
            )
            provider = FixtureObservationProvider(fixture_dir)

            message_list = provider.observe_message_list(app_id="tinder", scan_cursor={})

            with self.assertRaises(ValueError):
                provider.observe_message_list(app_id="tinder", scan_cursor=["not", "a", "mapping"])

        self.assertEqual(message_list["scan_cursor"], {})

    def test_unsafe_candidate_keys_use_hash_suffix_to_avoid_aliasing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            unsafe_name = _thread_fixture_name("a/b")
            safe_name = _thread_fixture_name("a_b")
            self.assertNotEqual(unsafe_name, safe_name)
            (fixture_dir / unsafe_name).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "observation_type": "thread",
                        "app_id": "tinder",
                        "conversation_observation": {"visible_messages": [{"sender": "match", "text": "unsafe"}]},
                    }
                ),
                encoding="utf-8",
            )
            (fixture_dir / safe_name).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "observation_type": "thread",
                        "app_id": "tinder",
                        "conversation_observation": {"visible_messages": [{"sender": "match", "text": "safe"}]},
                    }
                ),
                encoding="utf-8",
            )
            provider = FixtureObservationProvider(fixture_dir)

            unsafe_thread = provider.observe_thread(app_id="tinder", candidate_key="a/b")
            safe_thread = provider.observe_thread(app_id="tinder", candidate_key="a_b")

            with self.assertRaises(ValueError):
                provider.observe_thread(app_id="tinder", candidate_key="")

        self.assertEqual(unsafe_thread["conversation_observation"]["visible_messages"][0]["text"], "unsafe")
        self.assertEqual(safe_thread["conversation_observation"]["visible_messages"][0]["text"], "safe")

    def test_precheck_harness_echoes_runtime_when_provided(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            provider = FixtureObservationProvider(fixture_dir)
            harness = fixture_harness_factory(provider)("tinder", runtime="default")

            payload = harness.observe()

        self.assertEqual(payload["app_id"], "tinder")
        self.assertEqual(payload["runtime"], "default")
        self.assertEqual(payload["screen_state"], "fixture_ready")


class StandaloneRuntimeTests(unittest.TestCase):
    def test_tick_consumes_scan_message_list_work_item_and_writes_pending_scan_batch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            (fixture_dir / "message_list.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "observation_type": "message_list",
                        "app_id": "tinder",
                        "captured_at": "2026-06-20T00:00:00Z",
                        "message_list_snapshot": {
                            "entries": [{"candidate_key": "row_ada", "visible_name": "Ada"}]
                        },
                        "scan_cursor": {"current": None, "next": None, "exhausted": True},
                    }
                ),
                encoding="utf-8",
            )
            provider = FixtureObservationProvider(fixture_dir)
            managed = ManagedSessionRepository(
                data_dir,
                harness_factory=fixture_harness_factory(provider),
            )
            started = managed.start(
                app_id="tinder",
                authorization=_auth("tinder"),
                goal=None,
                availability=None,
                send_mode="stage",
                managed_gui_send=False,
            )
            runtime = StandaloneAgentRuntime(
                data_dir,
                observation_provider=provider,
                harness_factory=fixture_harness_factory(provider),
            )

            tick = runtime.tick()
            state = runtime.operator.get_state_payload()

        self.assertEqual(started["status"], "active")
        self.assertEqual(tick["status"], "work_consumed")
        self.assertEqual(tick["work_item_type"], "scan_message_list")
        self.assertEqual(tick["ingested"]["entry_count"], 1)
        self.assertIsNotNone(state["pending_scan_batch"])
        self.assertEqual(state["pending_scan_batch"]["message_list_snapshot"]["entries"][0]["candidate_key"], "row_ada")

    def test_send_message_work_item_requires_action_executor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            provider = FixtureObservationProvider(fixture_dir)
            runtime = StandaloneAgentRuntime(Path(temp_dir) / "data", observation_provider=provider)
            work_item = {
                "schema_version": 1,
                "work_item_id": "action_request_1",
                "work_item_type": "send_message",
                "action_request_id": "action_request_1",
                "match_id": "match_ada",
            }

            payload = runtime.consume_work_item(
                work_item,
                managed_payload={"schema_version": 1, "status": "host_work_required", "app_id": "tinder"},
            )

        self.assertEqual(payload["status"], "needs_action_executor")
        self.assertEqual(payload["work_item_type"], "send_message")

    def test_runtime_blocks_malformed_work_item_contexts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            provider = FixtureObservationProvider(fixture_dir)
            runtime = StandaloneAgentRuntime(Path(temp_dir) / "data", observation_provider=provider)

            missing_app = runtime.consume_work_item(
                {"schema_version": 1, "work_item_type": "scan_message_list"},
                managed_payload={"schema_version": 1, "status": "host_work_required"},
            )
            bad_cursor = runtime.consume_work_item(
                {"schema_version": 1, "work_item_type": "scan_message_list", "scan_cursor": ["bad"]},
                managed_payload={"schema_version": 1, "status": "host_work_required", "app_id": "tinder"},
            )
            bad_candidate = runtime.consume_work_item(
                {"schema_version": 1, "work_item_type": "open_thread", "candidate_key": ""},
                managed_payload={"schema_version": 1, "status": "host_work_required", "app_id": "tinder"},
            )

        self.assertEqual(missing_app["status"], "blocked")
        self.assertEqual(missing_app["reason"], "invalid_app_id")
        self.assertEqual(bad_cursor["status"], "blocked")
        self.assertEqual(bad_cursor["reason"], "invalid_scan_cursor")
        self.assertEqual(bad_candidate["status"], "blocked")
        self.assertEqual(bad_candidate["reason"], "invalid_candidate_key")

    def test_runtime_blocks_provider_or_ingest_failure_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            provider = FixtureObservationProvider(fixture_dir)
            runtime = StandaloneAgentRuntime(Path(temp_dir) / "data", observation_provider=provider)

            payload = runtime.consume_work_item(
                {"schema_version": 1, "work_item_type": "scan_message_list"},
                managed_payload={"schema_version": 1, "status": "host_work_required", "app_id": "tinder"},
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "observation_ingest_failed")
        self.assertEqual(payload["error_type"], "FileNotFoundError")


def _auth(app_id: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "authorization_id": f"auth_{app_id}",
        "scope": "send_chat_messages",
        "app_id": app_id,
        "expires_at": "2026-12-31T00:00:00Z",
        "allowed_match_ids": [],
        "allowed_actions": ["send_message"],
        "autonomous_send": False,
        "autonomous_nudge": False,
        "goal_ids": [],
        "quiet_hours": [],
        "requires_post_action_verification": True,
        "created_at": "2026-06-20T00:00:00Z",
        "revoked_at": None,
    }


if __name__ == "__main__":
    unittest.main()
