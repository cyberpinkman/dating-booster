import json
import tempfile
import unittest
from pathlib import Path

from dating_boost.core.capabilities import build_capabilities
from dating_boost.core.standalone_session import StandaloneSessionRepository


class StandaloneSessionTests(unittest.TestCase):
    def test_start_status_stop_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            repo = StandaloneSessionRepository(data_dir)

            started = repo.start(
                app_id="tinder",
                runtime=None,
                send_mode="stage",
                observation_source={"type": "fixture_dir", "path": "tests/fixtures/standalone"},
                backend={"type": "scripted", "path": "tests/fixtures/intelligence/scripted_reply.json"},
                scan_interval_seconds=0,
            )
            ticked = repo.record_tick({"status": "ok", "work_items_processed": 0})
            status = repo.status()
            stopped = repo.stop(reason="manual_stop")
            session_path = data_dir / "standalone_session" / "session.json"
            events_path = data_dir / "standalone_session" / "events.jsonl"
            persisted = json.loads(session_path.read_text(encoding="utf-8"))
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            session_path_exists = session_path.exists()
            events_path_exists = events_path.exists()

        self.assertEqual(started["status"], "active")
        self.assertEqual(started["session"]["schema_version"], 1)
        self.assertEqual(started["session"]["scan_interval_seconds"], 1)
        self.assertEqual(ticked["status"], "ok")
        self.assertEqual(status["session"]["app_id"], "tinder")
        self.assertEqual(status["session"]["send_mode"], "stage")
        self.assertEqual(status["session"]["last_tick"]["work_items_processed"], 0)
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped["session"]["status"], "stopped")
        self.assertEqual(stopped["session"]["stop_reason"], "manual_stop")
        self.assertEqual(persisted["status"], "stopped")
        self.assertTrue(session_path_exists)
        self.assertTrue(events_path_exists)
        self.assertEqual([event["event_type"] for event in events], ["start", "tick", "stop"])

    def test_start_rejects_live_without_managed_gui_send(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = StandaloneSessionRepository(Path(temp_dir) / "data")

            blocked = repo.start(
                app_id="tinder",
                runtime=None,
                send_mode="live",
                observation_source={"type": "fixture_dir", "path": "tests/fixtures/standalone"},
                backend={"type": "scripted", "path": "tests/fixtures/intelligence/scripted_reply.json"},
                scan_interval_seconds=120,
                managed_gui_send=False,
            )
            allowed = repo.start(
                app_id="tinder",
                runtime=None,
                send_mode="live",
                observation_source={"type": "fixture_dir", "path": "tests/fixtures/standalone"},
                backend={"type": "scripted", "path": "tests/fixtures/intelligence/scripted_reply.json"},
                scan_interval_seconds=120,
                managed_gui_send=True,
            )

        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["reason"], "managed_gui_send_required_for_live_mode")
        self.assertEqual(allowed["status"], "active")
        self.assertTrue(allowed["session"]["managed_gui_send"])

    def test_start_rejects_active_session_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = StandaloneSessionRepository(Path(temp_dir) / "data")

            first = repo.start(
                app_id="tinder",
                runtime=None,
                send_mode="stage",
                observation_source={"type": "fixture_dir", "path": "tests/fixtures/standalone"},
                backend={"type": "scripted", "path": "tests/fixtures/intelligence/scripted_reply.json"},
                scan_interval_seconds=120,
            )
            second = repo.start(
                app_id="tinder",
                runtime=None,
                send_mode="stage",
                observation_source={"type": "fixture_dir", "path": "tests/fixtures/other"},
                backend={"type": "scripted", "path": "tests/fixtures/intelligence/other.json"},
                scan_interval_seconds=30,
            )
            invalid_tick = repo.record_tick(["not", "a", "mapping"])

        self.assertEqual(first["status"], "active")
        self.assertEqual(second["status"], "blocked")
        self.assertEqual(second["reason"], "standalone_session_already_active")
        self.assertEqual(second["session"]["session_id"], first["session"]["session_id"])
        self.assertEqual(invalid_tick["status"], "blocked")
        self.assertEqual(invalid_tick["reason"], "invalid_tick_payload")

    def test_capabilities_expose_standalone_runtime_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = build_capabilities(data_dir=Path(temp_dir) / "data")
            caps = payload["agent_native_capabilities"]

        self.assertTrue(caps["standalone_agent_runtime"])
        self.assertEqual(caps["standalone_agent_default_mode"], "fixture_or_manual_first")
        self.assertFalse(caps["standalone_agent_live_gui_default"])
        self.assertTrue(caps["standalone_agent_uses_existing_operator_contract"])


if __name__ == "__main__":
    unittest.main()
