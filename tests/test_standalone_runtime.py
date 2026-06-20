import json
import tempfile
import unittest
from pathlib import Path

from dating_boost.core.standalone_observation import (
    FixtureObservationProvider,
    _thread_fixture_name,
    fixture_harness_factory,
)


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


if __name__ == "__main__":
    unittest.main()
