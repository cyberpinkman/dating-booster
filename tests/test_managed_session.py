import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.core.automation import AutomationRepository
from dating_boost.core.managed_session import ManagedSessionRepository


FIXTURE_DIR = Path("tests/fixtures/automation")


class FakeHarness:
    def __init__(self, *, app_id="tinder", tinder_payload=None, wechat_payload=None, bumble_payload=None):
        self.app_id = app_id
        self.tinder_payload = tinder_payload or _app_payload("tinder")
        self.wechat_payload = wechat_payload or _app_payload("wechat")
        self.bumble_payload = bumble_payload or _app_payload("bumble")
        self.tinder_observe_count = 0
        self.wechat_observe_count = 0
        self.bumble_observe_count = 0

    def for_app(self, app_id):
        self.app_id = app_id
        return self

    def observe(self):
        if self.app_id == "wechat":
            return self.observe_wechat_screen()
        if self.app_id == "bumble":
            return self.observe_bumble_screen()
        return self.observe_tinder_screen()

    def observe_tinder_screen(self):
        self.tinder_observe_count += 1
        return dict(self.tinder_payload)

    def observe_wechat_screen(self):
        self.wechat_observe_count += 1
        return dict(self.wechat_payload)

    def observe_bumble_screen(self):
        self.bumble_observe_count += 1
        return dict(self.bumble_payload)


class ManagedSessionTests(unittest.TestCase):
    def setUp(self):
        self._clock_patch = patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T11:00:00Z"})
        self._clock_patch.start()

    def tearDown(self):
        self._clock_patch.stop()

    def test_capabilities_expose_managed_session_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, payload = self._run_cli(["capabilities", "--json", "--data-dir", temp_dir])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["schema_versions"]["managed_session"], 1)
        self.assertEqual(payload["schema_versions"]["managed_wake_event"], 1)
        self.assertIn("managed-session start", payload["supported_commands"])
        self.assertIn("managed-session tick", payload["supported_commands"])
        self.assertIn("managed-session run", payload["supported_commands"])
        self.assertIn("managed-session notify", payload["supported_commands"])
        self.assertIn("managed-session status", payload["supported_commands"])
        self.assertIn("managed-session stop", payload["supported_commands"])
        self.assertTrue(payload["agent_native_capabilities"]["managed_session"])
        self.assertEqual(payload["agent_native_capabilities"]["managed_session_default_scan_interval_seconds"], 120)
        self.assertIn("bumble", payload["agent_native_capabilities"]["managed_session_app_profiles"])

    def test_start_blocks_live_mode_without_managed_gui_authorization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            payload = self._start_repo(data_dir, send_mode="live", managed_gui_send=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "managed_gui_send_required_for_live_mode")

    def test_tinder_missing_iphone_mirroring_stops_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            repo = ManagedSessionRepository(
                data_dir,
                harness_factory=lambda app_id: FakeHarness(
                    app_id=app_id,
                    tinder_payload=_app_payload("tinder", status="blocked", reason="iphone_mirroring_window_not_found")
                ),
            )
            payload = repo.start(
                app_id="tinder",
                authorization=_auth("tinder"),
                goal=_json(FIXTURE_DIR / "goal_meet.json"),
                availability=_json(FIXTURE_DIR / "availability_weekend.json"),
                send_mode="stage",
                managed_gui_send=False,
            )

        self.assertEqual(payload["status"], "stopped")
        self.assertEqual(payload["reason"], "iphone_mirroring_window_not_found")
        self.assertEqual(payload["next_host_action"], "enable_iphone_mirroring_and_restart_managed_session")

    def test_wechat_unavailable_pauses_without_send_work(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            repo = ManagedSessionRepository(
                data_dir,
                harness_factory=lambda app_id: FakeHarness(
                    app_id=app_id,
                    wechat_payload=_app_payload("wechat", status="blocked", reason="wechat_window_not_found")
                ),
            )
            payload = repo.start(
                app_id="wechat",
                authorization=_auth("wechat"),
                goal=_json(FIXTURE_DIR / "goal_meet.json"),
                availability=_json(FIXTURE_DIR / "availability_weekend.json"),
                send_mode="stage",
                managed_gui_send=False,
            )

        self.assertEqual(payload["status"], "paused")
        self.assertEqual(payload["reason"], "wechat_window_not_found")
        self.assertNotIn("work_item", payload)

    def test_bumble_can_start_managed_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            harness = FakeHarness(bumble_payload=_app_payload("bumble"))
            repo = ManagedSessionRepository(data_dir, harness_factory=lambda app_id: harness.for_app(app_id))
            payload = repo.start(
                app_id="bumble",
                authorization=_auth("bumble"),
                goal=_json(FIXTURE_DIR / "goal_meet.json"),
                availability=_json(FIXTURE_DIR / "availability_weekend.json"),
                send_mode="stage",
                managed_gui_send=False,
            )

        self.assertEqual(payload["status"], "active")
        self.assertEqual(payload["app_id"], "bumble")
        self.assertEqual(harness.bumble_observe_count, 1)

    def test_notify_wake_returns_existing_operator_scan_work(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            repo = self._started_repo(data_dir, scan_interval_seconds=3600)

            no_work = repo.tick()
            notify = repo.notify(source="manual", app_id="tinder")
            woke = repo.tick()
            reused = repo.tick()

        self.assertEqual(no_work["status"], "no_work")
        self.assertEqual(notify["status"], "ok")
        self.assertEqual(woke["status"], "host_work_required")
        self.assertIn("notify_event", woke["wake_reasons"])
        self.assertEqual(woke["work_item"]["work_item_type"], "scan_message_list")
        self.assertEqual(reused["status"], "host_work_required")
        self.assertIn("existing_operator_work", reused["wake_reasons"])
        self.assertEqual(reused["work_item"]["work_item_type"], "scan_message_list")

    def test_notify_wake_is_scoped_to_active_session_app(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            repo = self._started_repo(data_dir, scan_interval_seconds=3600)

            wrong_app_notify = repo.notify(source="manual", app_id="wechat")
            payload = repo.tick()

        self.assertEqual(wrong_app_notify["status"], "ok")
        self.assertEqual(payload["status"], "no_work")
        self.assertNotIn("work_item", payload)
        self.assertNotIn("notify_event", payload.get("wake_reasons", []))

    def test_nudge_due_wakes_host_but_not_before_due_time(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            repo = self._started_repo(data_dir, scan_interval_seconds=3600)
            AutomationRepository(data_dir).step(_json(FIXTURE_DIR / "scan_batch_nudge.json"))
            self._set_managed_last_scan(data_dir, "2026-05-26T11:00:00Z")

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T11:29:00Z"}):
                not_due = repo.tick()
            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T11:31:00Z"}):
                due = repo.tick()

        self.assertEqual(not_due["status"], "no_work")
        self.assertEqual(due["status"], "host_work_required")
        self.assertIn("nudge_due", due["wake_reasons"])
        self.assertEqual(due["work_item"]["work_item_type"], "scan_message_list")

    def test_next_wake_prefers_earliest_nudge_due_over_scan_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            repo = self._started_repo(data_dir, scan_interval_seconds=3600)
            AutomationRepository(data_dir).step(_json(FIXTURE_DIR / "scan_batch_nudge.json"))
            self._set_managed_last_scan(data_dir, "2026-05-26T11:00:00Z")

            payload = repo.tick()

        self.assertEqual(payload["status"], "no_work")
        self.assertEqual(payload["next_wake_at"], "2026-05-26T11:30:00Z")
        self.assertEqual(payload["next_wake_reason"], "nudge_due")

    def test_already_nudged_fingerprint_does_not_wake(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            repo = self._started_repo(data_dir, scan_interval_seconds=3600)
            AutomationRepository(data_dir).step(_json(FIXTURE_DIR / "scan_batch_nudge.json"))
            states_path = data_dir / "automation" / "states.json"
            states_payload = json.loads(states_path.read_text(encoding="utf-8"))
            states_payload["states"][0]["last_nudged_inbound_fingerprint"] = "gia:in:absurd-comedy"
            states_path.write_text(json.dumps(states_payload, ensure_ascii=False), encoding="utf-8")
            self._set_managed_last_scan(data_dir, "2026-05-26T11:00:00Z")

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T11:31:00Z"}):
                payload = repo.tick()

        self.assertEqual(payload["status"], "no_work")
        self.assertNotIn("work_item", payload)

    def test_safety_pause_and_quiet_hours_block_tick(self):
        for name, auth_overrides, expected_status, expected_reason in (
            ("safety", {}, "paused", "safety_paused"),
            ("quiet", {"quiet_hours": [{"start": "00:00", "end": "23:59"}]}, "paused", "authorization_quiet_hours"),
        ):
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    data_dir = Path(temp_dir) / "data"
                    self._init_profile(data_dir)
                    repo = self._started_repo(data_dir, auth=_auth("tinder", **auth_overrides))
                    if name == "safety":
                        self._run_cli(["safety", "pause", "--data-dir", str(data_dir), "--reason", "test"])

                    payload = repo.tick()

                self.assertEqual(payload["status"], expected_status)
                self.assertEqual(payload["reason"], expected_reason)
                self.assertNotIn("work_item", payload)

    def test_run_wait_short_timeout_returns_no_work_without_raw_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            raw_text = "Ada said a private sentence"
            repo = self._started_repo(
                data_dir,
                scan_interval_seconds=3600,
                harness=FakeHarness(tinder_payload=_app_payload("tinder", raw_text=raw_text)),
            )
            observe_count_before_wait = repo._harness_factory("tinder").tinder_observe_count

            payload = repo.run(wait=True, wait_timeout_seconds=0.01, poll_interval_seconds=0.01)
            encoded = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["status"], "no_work")
        self.assertEqual(repo._harness_factory("tinder").tinder_observe_count, observe_count_before_wait + 1)
        self.assertNotIn(raw_text, encoded)
        self.assertIn("screen_fingerprint", encoded)

    def test_cli_start_status_and_stop(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            auth_path = Path(temp_dir) / "auth.json"
            _write_json(auth_path, _auth("tinder"))
            with patch(
                "dating_boost.core.managed_session.create_adapter",
                side_effect=lambda app_id: FakeHarness(app_id=app_id, tinder_payload=_app_payload("tinder")),
            ):
                start_exit, start_payload = self._run_cli([
                    "managed-session",
                    "start",
                    "--app-id",
                    "tinder",
                    "--data-dir",
                    str(data_dir),
                    "--authorization",
                    str(auth_path),
                    "--goal",
                    str(FIXTURE_DIR / "goal_meet.json"),
                    "--availability",
                    str(FIXTURE_DIR / "availability_weekend.json"),
                    "--scan-interval",
                    "3600",
                    "--json",
                ])
            status_exit, status_payload = self._run_cli(["managed-session", "status", "--data-dir", str(data_dir), "--json"])
            stop_exit, stop_payload = self._run_cli(["managed-session", "stop", "--data-dir", str(data_dir), "--json"])

        self.assertEqual(start_exit, 0)
        self.assertEqual(start_payload["status"], "active")
        self.assertEqual(status_exit, 0)
        self.assertEqual(status_payload["status"], "active")
        self.assertEqual(stop_exit, 0)
        self.assertEqual(stop_payload["status"], "stopped")

    def _started_repo(
        self,
        data_dir,
        *,
        auth=None,
        scan_interval_seconds=120,
        harness=None,
    ):
        repo = ManagedSessionRepository(
            data_dir,
            harness_factory=lambda app_id: (harness or FakeHarness(app_id=app_id)).for_app(app_id),
        )
        payload = repo.start(
            app_id=str((auth or _auth("tinder")).get("app_id") or "tinder"),
            authorization=auth or _auth("tinder"),
            goal=_json(FIXTURE_DIR / "goal_meet.json"),
            availability=_json(FIXTURE_DIR / "availability_weekend.json"),
            send_mode="stage",
            managed_gui_send=False,
            scan_interval_seconds=scan_interval_seconds,
        )
        self.assertEqual(payload["status"], "active")
        self._set_managed_last_scan(data_dir, "2026-05-26T11:00:00Z")
        return repo

    def _start_repo(self, data_dir, *, send_mode="stage", managed_gui_send=False):
        repo = ManagedSessionRepository(data_dir, harness_factory=lambda app_id: FakeHarness(app_id=app_id))
        return repo.start(
            app_id="tinder",
            authorization=_auth("tinder"),
            goal=_json(FIXTURE_DIR / "goal_meet.json"),
            availability=_json(FIXTURE_DIR / "availability_weekend.json"),
            send_mode=send_mode,
            managed_gui_send=managed_gui_send,
        )

    def _set_managed_last_scan(self, data_dir, value):
        path = data_dir / "managed_session" / "session.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["last_scan_at"] = value
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _init_profile(self, data_dir):
        self._run_cli([
            "init-profile",
            "--data-dir",
            str(data_dir),
            "--input",
            "tests/fixtures/intelligence/user_profile.json",
        ])
        self._run_cli([
            "user",
            "ingest-profile",
            "--data-dir",
            str(data_dir),
            "--input",
            "tests/fixtures/intelligence/user_dating_profile.json",
        ])
        self._run_cli([
            "user",
            "ingest-interview",
            "--data-dir",
            str(data_dir),
            "--input",
            "tests/fixtures/intelligence/user_self_interview.json",
        ])

    def _run_cli(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        return exit_code, json.loads(output.getvalue())


def _app_payload(app_id, *, status="ok", reason=None, raw_text=""):
    if app_id == "wechat":
        state = "wechat_chat_list"
        layout = {"chat_list_present": True, "unread_marker_present": False}
    else:
        state = "tinder_messages"
        layout = {"page": "chats", "reply_required_marker_present": False, "conversation_list_present": True}
    return {
        "schema_version": 2,
        "status": status,
        "reason": reason,
        "app_id": app_id,
        "screen_state": state,
        "layout_hints": layout,
        "screen": {
            "status": "ok",
            "state": state,
            "text_fingerprint": "fingerprint_" + app_id,
            "text_character_count": len(raw_text),
        },
    }


def _auth(app_id, **overrides):
    payload = _json(FIXTURE_DIR / "auth_send.json")
    payload["app_id"] = app_id
    payload["live_send"] = True
    payload.update(overrides)
    return payload


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
