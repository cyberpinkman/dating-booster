import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost.cli import main
from dating_boost.core.daemon import DaemonRepository
from dating_boost.core.managed_session import ManagedSessionRepository
from dating_boost.core.standalone_observation import FixtureObservationProvider, fixture_harness_factory
from dating_boost.core.standalone_session import StandaloneSessionRepository


class DaemonStandaloneTests(unittest.TestCase):
    def test_run_once_ticks_active_standalone_session(self):
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
                        "message_list_snapshot": {"entries": []},
                        "scan_cursor": {"current": None, "next": None, "exhausted": True},
                    }
                ),
                encoding="utf-8",
            )
            provider = FixtureObservationProvider(fixture_dir)
            managed_start = ManagedSessionRepository(data_dir, harness_factory=fixture_harness_factory(provider)).start(
                app_id="tinder",
                authorization=_auth("tinder"),
                goal=None,
                availability=None,
                send_mode="stage",
                managed_gui_send=False,
            )
            standalone_start = StandaloneSessionRepository(data_dir).start(
                app_id="tinder",
                runtime=None,
                send_mode="stage",
                observation_source={"type": "fixture_dir", "path": str(fixture_dir)},
                backend={"type": "scripted", "path": "tests/fixtures/intelligence/scripted_reply.json"},
                scan_interval_seconds=120,
            )

            payload = DaemonRepository(data_dir).run(
                once=True,
                owner="test",
                now="2026-06-20T00:00:00Z",
                standalone_tick=True,
            )

        self.assertEqual(managed_start["status"], "active")
        self.assertEqual(standalone_start["status"], "active")
        self.assertEqual(payload["status"], "stopped")
        self.assertIn("standalone_tick", payload)
        self.assertEqual(payload["standalone_tick"]["status"], "work_consumed")

    def test_run_once_reports_blocked_standalone_tick_for_missing_fixture_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            standalone_start = StandaloneSessionRepository(data_dir).start(
                app_id="tinder",
                runtime=None,
                send_mode="stage",
                observation_source={"type": "fixture_dir", "path": str(Path(temp_dir) / "missing")},
                backend={"type": "scripted", "path": "tests/fixtures/intelligence/scripted_reply.json"},
                scan_interval_seconds=120,
            )

            payload = DaemonRepository(data_dir).run(
                once=True,
                owner="test",
                now="2026-06-20T00:00:00Z",
                standalone_tick=True,
            )

        self.assertEqual(standalone_start["status"], "active")
        self.assertEqual(payload["status"], "stopped")
        self.assertEqual(payload["standalone_tick"]["status"], "blocked")
        self.assertEqual(payload["standalone_tick"]["reason"], "observation_fixture_dir_not_found")

    def test_cli_run_once_returns_nonzero_when_standalone_tick_blocks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            StandaloneSessionRepository(data_dir).start(
                app_id="tinder",
                runtime=None,
                send_mode="stage",
                observation_source={"type": "fixture_dir", "path": str(Path(temp_dir) / "missing")},
                backend={"type": "scripted", "path": "tests/fixtures/intelligence/scripted_reply.json"},
                scan_interval_seconds=120,
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                exit_code = main(
                    [
                        "daemon",
                        "run",
                        "--data-dir",
                        str(data_dir),
                        "--once",
                        "--standalone-tick",
                        "--json",
                    ]
                )
            payload = json.loads(buffer.getvalue())

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["standalone_tick"]["status"], "blocked")


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
