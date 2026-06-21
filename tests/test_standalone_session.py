import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost.cli import main
from dating_boost.core.capabilities import build_capabilities
from dating_boost.core.standalone_session import StandaloneSessionRepository


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SCRIPTED_REPLY_PATH = FIXTURE_DIR / "intelligence" / "scripted_reply.json"


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
        self.assertIn("standalone-session start", payload["supported_commands"])


class StandaloneSessionCliTests(unittest.TestCase):
    def _run_cli(self, argv):
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = main(argv)
        return code, json.loads(buffer.getvalue())

    def test_cli_start_status_stop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            auth_path = Path(temp_dir) / "auth.json"
            auth_path.write_text(json.dumps(_auth("tinder")), encoding="utf-8")
            start_args = [
                "standalone-session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(auth_path),
                "--app-id",
                "tinder",
                "--send-mode",
                "stage",
                "--observation-fixture-dir",
                str(fixture_dir),
                "--backend",
                "scripted",
                "--scripted-backend-output",
                str(SCRIPTED_REPLY_PATH),
                "--json",
            ]
            confirm_exit, confirm_payload = self._run_cli(start_args)
            start_exit, start_payload = self._run_cli(
                start_args[:-1] + ["--config-confirm", confirm_payload["required_confirm_token"], "--json"]
            )
            status_exit, status_payload = self._run_cli(
                [
                    "standalone-session",
                    "status",
                    "--data-dir",
                    str(data_dir),
                    "--json",
                ]
            )
            stop_exit, stop_payload = self._run_cli(
                [
                    "standalone-session",
                    "stop",
                    "--data-dir",
                    str(data_dir),
                    "--json",
                ]
            )

        self.assertEqual(confirm_exit, 2)
        self.assertEqual(confirm_payload["reason"], "managed_session_config_confirmation_required")
        self.assertEqual(start_exit, 0)
        self.assertEqual(start_payload["status"], "active")
        self.assertEqual(status_exit, 0)
        self.assertEqual(status_payload["status"], "active")
        self.assertEqual(stop_exit, 0)
        self.assertEqual(stop_payload["status"], "stopped")

    def test_cli_start_requires_managed_session_config_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            auth_path = Path(temp_dir) / "auth.json"
            auth_path.write_text(json.dumps(_auth("tinder")), encoding="utf-8")

            start_args = [
                "standalone-session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(auth_path),
                "--app-id",
                "tinder",
                "--send-mode",
                "stage",
                "--observation-fixture-dir",
                str(fixture_dir),
                "--backend",
                "scripted",
                "--scripted-backend-output",
                str(SCRIPTED_REPLY_PATH),
                "--json",
            ]
            confirm_exit, confirm_payload = self._run_cli(start_args)

        self.assertEqual(confirm_exit, 2)
        self.assertEqual(confirm_payload["status"], "blocked")
        self.assertEqual(confirm_payload["reason"], "managed_session_config_confirmation_required")
        self.assertTrue(confirm_payload["required_confirm_token"].startswith("managed-session-config:"))
        self.assertEqual(
            confirm_payload["proposed_config"]["message_list_scan_boundary"],
            {"type": "first_historical_row", "history_cutoff_days": 7},
        )
        self.assertFalse((data_dir / "managed_session" / "session.json").exists())
        self.assertFalse((data_dir / "standalone_session" / "session.json").exists())

    def test_cli_start_then_tick_consumes_fixture_work(self):
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
                        "message_list_snapshot": {"entries": []},
                        "scan_cursor": {"current": None, "next": None, "exhausted": True},
                    }
                ),
                encoding="utf-8",
            )
            auth_path = Path(temp_dir) / "auth.json"
            auth_path.write_text(json.dumps(_auth("tinder")), encoding="utf-8")
            start_args = [
                "standalone-session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(auth_path),
                "--app-id",
                "tinder",
                "--send-mode",
                "stage",
                "--observation-fixture-dir",
                str(fixture_dir),
                "--backend",
                "scripted",
                "--scripted-backend-output",
                str(SCRIPTED_REPLY_PATH),
                "--json",
            ]
            confirm_exit, confirm_payload = self._run_cli(start_args)
            start_exit, _start_payload = self._run_cli(
                start_args[:-1] + ["--config-confirm", confirm_payload["required_confirm_token"], "--json"]
            )
            tick_exit, tick_payload = self._run_cli(
                [
                    "standalone-session",
                    "tick",
                    "--data-dir",
                    str(data_dir),
                    "--json",
                ]
            )

        self.assertEqual(confirm_exit, 2)
        self.assertEqual(confirm_payload["reason"], "managed_session_config_confirmation_required")
        self.assertEqual(start_exit, 0)
        self.assertEqual(tick_exit, 0)
        self.assertEqual(tick_payload["status"], "work_consumed")
        self.assertEqual(tick_payload["work_item_type"], "scan_message_list")


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
