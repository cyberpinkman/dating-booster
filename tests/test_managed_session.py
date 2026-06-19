import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.core import managed_session as managed_session_core
from dating_boost.core.automation import AutomationRepository
from dating_boost.core.managed_session import ManagedSessionRepository


FIXTURE_DIR = Path("tests/fixtures/automation")


class FakeHarness:
    def __init__(self, *, app_id="tinder", tinder_payload=None, wechat_payload=None, bumble_payload=None, tashuo_payload=None):
        self.app_id = app_id
        self.tinder_payload = tinder_payload or _app_payload("tinder")
        self.wechat_payload = wechat_payload or _app_payload("wechat")
        self.bumble_payload = bumble_payload or _app_payload("bumble")
        self.tashuo_payload = tashuo_payload or _app_payload("tashuo")
        self.tinder_observe_count = 0
        self.wechat_observe_count = 0
        self.bumble_observe_count = 0
        self.tashuo_observe_count = 0

    def for_app(self, app_id):
        self.app_id = app_id
        return self

    def observe(self):
        if self.app_id == "wechat":
            return self.observe_wechat_screen()
        if self.app_id == "bumble":
            return self.observe_bumble_screen()
        if self.app_id == "tashuo":
            return self.observe_tashuo_screen()
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

    def observe_tashuo_screen(self):
        self.tashuo_observe_count += 1
        return dict(self.tashuo_payload)


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
        self.assertTrue(payload["agent_native_capabilities"]["multi_thread_managed_session"])
        self.assertEqual(payload["agent_native_capabilities"]["managed_session_management_modes"], ["conservative", "high-throughput"])
        self.assertEqual(payload["agent_native_capabilities"]["managed_session_default_scan_interval_seconds"], 120)
        self.assertTrue(payload["agent_native_capabilities"]["managed_session_harness_runtime_selection"])
        self.assertIn("bumble", payload["agent_native_capabilities"]["managed_session_app_profiles"])
        self.assertEqual(
            payload["agent_native_capabilities"]["managed_session_background_model"],
            "bounded_user_explicit_session_not_global_daemon",
        )
        self.assertFalse(payload["agent_native_capabilities"]["managed_session_global_background"])
        self.assertFalse(payload["agent_native_capabilities"]["managed_session_global_background_required"])
        self.assertEqual(
            payload["agent_native_capabilities"]["managed_session_global_background_reason"],
            "intentional_safety_boundary",
        )
        self.assertFalse(payload["agent_native_capabilities"]["repo_computer_use_execution_backend_required"])

    def test_cli_start_persists_high_throughput_session_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            auth_path = Path(temp_dir) / "auth.json"
            _write_json(auth_path, _auth("tashuo"))
            with patch(
                "dating_boost.core.managed_session.create_adapter",
                side_effect=lambda app_id, runtime=None: FakeHarness(app_id=app_id, tashuo_payload=_app_payload("tashuo")),
            ):
                exit_code, payload = self._run_cli([
                    "managed-session",
                    "start",
                    "--app-id",
                    "tashuo",
                    "--data-dir",
                    str(data_dir),
                    "--authorization",
                    str(auth_path),
                    "--goal",
                    str(FIXTURE_DIR / "goal_meet.json"),
                    "--availability",
                    str(FIXTURE_DIR / "availability_weekend.json"),
                    "--management-mode",
                    "high-throughput",
                    "--max-threads-per-cycle",
                    "8",
                    "--max-pages-per-cycle",
                    "3",
                    "--cycle-send-limit",
                    "2",
                    "--harness-runtime",
                    "mac-ios-app",
                    "--json",
                ])

            session = json.loads((data_dir / "managed_session" / "session.json").read_text(encoding="utf-8"))
            operator_session = json.loads((data_dir / "operator" / "session.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "active")
        expected = {
            "management_mode": "high-throughput",
            "max_threads_per_cycle": 8,
            "max_pages_per_cycle": 3,
            "cycle_send_limit": 2,
            "harness_runtime": "mac-ios-app",
        }
        for key, value in expected.items():
            self.assertEqual(session[key], value)
            if key != "harness_runtime":
                self.assertEqual(operator_session[key], value)

    def test_start_blocks_live_mode_without_managed_gui_authorization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            payload = self._start_repo(data_dir, send_mode="live", managed_gui_send=False)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "managed_gui_send_required_for_live_mode")

    def test_start_warns_for_old_memory_review_without_blocking(self):
        from dating_boost.core.memory.review_queue import ReviewItem, ReviewQueueRepository

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            ReviewQueueRepository(data_dir).enqueue(
                ReviewItem(
                    review_item_id="rev_old_session",
                    session_id="session_old",
                    match_id="match_old",
                    observation_id="obs_old",
                    proposal={
                        "predicate": "thread_cue",
                        "value": "ordinary conversation page",
                        "subject": "Old Match",
                        "scope": "conversation",
                        "fact_type": "visible_fact",
                        "confidence": "medium",
                        "evidence_text": "Old session suggestion.",
                    },
                    status="pending",
                    created_at="2026-05-25T00:00:00Z",
                    reported_at=None,
                    reviewed_at=None,
                    dedupe_key="old_session_ui_cue",
                    source="deterministic",
                    risk="low",
                )
            )

            payload = self._start_repo(data_dir)

        self.assertEqual(payload["status"], "active")
        self.assertIn("pending_memory_suggestions_require_review", payload["warnings"])
        self.assertEqual(payload["memory_review"]["pending_count"], 1)

    def test_tinder_missing_iphone_mirroring_stops_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            repo = ManagedSessionRepository(
                data_dir,
                harness_factory=lambda app_id, runtime=None: FakeHarness(
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

    def test_tashuo_mac_ios_runtime_precheck_does_not_request_iphone_mirroring(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            calls = []
            window_probe = {
                "frontmost_process": "iPhone Mirroring",
                "processes": [
                    {
                        "process_name": "tashuo",
                        "process_exists": True,
                        "frontmost": False,
                        "visible": True,
                        "window_count": 0,
                    }
                ],
            }

            def harness_factory(app_id, runtime=None):
                calls.append({"app_id": app_id, "runtime": runtime})
                return FakeHarness(
                    app_id=app_id,
                    tashuo_payload={
                        **_app_payload("tashuo", status="blocked", reason="mac_ios_app_process_has_no_windows"),
                        "window_probe": window_probe,
                    },
                )

            repo = ManagedSessionRepository(data_dir, harness_factory=harness_factory)
            payload = repo.start(
                app_id="tashuo",
                authorization=_auth("tashuo"),
                goal=_json(FIXTURE_DIR / "goal_meet.json"),
                availability=_json(FIXTURE_DIR / "availability_weekend.json"),
                send_mode="stage",
                managed_gui_send=False,
                harness_runtime="mac-ios-app",
            )

        self.assertEqual(calls, [{"app_id": "tashuo", "runtime": "mac-ios-app"}])
        self.assertEqual(payload["status"], "paused")
        self.assertEqual(payload["reason"], "mac_ios_app_process_has_no_windows")
        self.assertEqual(payload["app_precheck"]["window_probe"], window_probe)
        self.assertEqual(payload["session"]["pause_reason"], "mac_ios_app_process_has_no_windows")
        self.assertIsNone(payload["session"]["stop_reason"])
        self.assertIsNone(payload["operator_stop"])
        self.assertEqual(payload["next_host_action"], "launch_or_focus_mac_ios_app_and_resume_managed_session")
        self.assertNotEqual(payload["next_host_action"], "enable_iphone_mirroring_and_restart_managed_session")

    def test_tashuo_mac_ios_runtime_window_loss_pauses_existing_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            harness = FakeHarness(app_id="tashuo", tashuo_payload=_app_payload("tashuo"))
            repo = ManagedSessionRepository(
                data_dir,
                harness_factory=lambda app_id, runtime=None: harness.for_app(app_id),
            )
            start_payload = repo.start(
                app_id="tashuo",
                authorization=_auth("tashuo"),
                goal=_json(FIXTURE_DIR / "goal_meet.json"),
                availability=_json(FIXTURE_DIR / "availability_weekend.json"),
                send_mode="stage",
                managed_gui_send=False,
                harness_runtime="mac-ios-app",
            )
            harness.tashuo_payload = _app_payload(
                "tashuo",
                status="blocked",
                reason="mac_ios_app_process_has_no_windows",
            )
            tick_payload = repo.tick()

        self.assertEqual(start_payload["status"], "active")
        self.assertEqual(tick_payload["status"], "paused")
        self.assertEqual(tick_payload["reason"], "mac_ios_app_process_has_no_windows")
        self.assertEqual(tick_payload["session"]["pause_reason"], "mac_ios_app_process_has_no_windows")
        self.assertIsNone(tick_payload["session"]["stop_reason"])
        self.assertIsNone(tick_payload["session"]["stopped_at"])
        self.assertEqual(
            tick_payload["next_host_action"],
            "launch_or_focus_mac_ios_app_and_resume_managed_session",
        )

    def test_selected_runtime_scope_blocks_managed_session_default_runtime_precheck(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            (data_dir / "runtime").mkdir(parents=True, exist_ok=True)
            _write_json(data_dir / "runtime" / "session_scope.json", {
                "schema_version": 1,
                "status": "selected",
                "selected_app_id": "tashuo",
                "selected_runtime": "mac-ios-app",
            })
            calls = []

            def harness_factory(app_id, runtime=None):
                calls.append({"app_id": app_id, "runtime": runtime})
                return FakeHarness(app_id=app_id)

            repo = ManagedSessionRepository(data_dir, harness_factory=harness_factory)
            payload = repo.start(
                app_id="tashuo",
                authorization=_auth("tashuo"),
                goal=_json(FIXTURE_DIR / "goal_meet.json"),
                availability=_json(FIXTURE_DIR / "availability_weekend.json"),
                send_mode="stage",
                managed_gui_send=False,
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "runtime_scope_mismatch")
        self.assertEqual(payload["selected_runtime"], "mac-ios-app")
        self.assertEqual(payload["requested_runtime"], "default")
        self.assertEqual(calls, [])

    def test_tashuo_managed_session_requires_runtime_choice_before_default_precheck(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            calls = []

            def harness_factory(app_id, runtime=None):
                calls.append({"app_id": app_id, "runtime": runtime})
                return FakeHarness(app_id=app_id)

            repo = ManagedSessionRepository(data_dir, harness_factory=harness_factory)
            payload = repo.start(
                app_id="tashuo",
                authorization=_auth("tashuo"),
                goal=_json(FIXTURE_DIR / "goal_meet.json"),
                availability=_json(FIXTURE_DIR / "availability_weekend.json"),
                send_mode="stage",
                managed_gui_send=False,
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "runtime_scope_required")
        self.assertEqual(payload["requested_app_id"], "tashuo")
        self.assertEqual(payload["requested_runtime"], "default")
        self.assertEqual(calls, [])

    def test_tashuo_mac_ios_runtime_recovery_action_comes_from_app_profile(self):
        profile = _json(Path("app_profiles") / "tashuo.json")

        self.assertEqual(
            profile["managed_session"]["runtime_precheck_failure_next_host_actions"]["mac_ios_app"],
            "launch_or_focus_mac_ios_app_and_resume_managed_session",
        )
        self.assertEqual(
            profile["managed_session"]["runtime_precheck_failure_reason_next_host_actions"]["mac_ios_app"][
                "host_appleevents_unavailable"
            ],
            "check_host_automation_system_events_permission_and_resume_managed_session",
        )
        self.assertEqual(
            profile["managed_session"]["runtime_precheck_failure_statuses"]["mac_ios_app"],
            "paused",
        )

    def test_tashuo_mac_ios_host_appleevents_precheck_action_preserves_diagnostic(self):
        profile = _json(Path("app_profiles") / "tashuo.json")
        app_check = managed_session_core._safe_app_check(
            {
                "status": "blocked",
                "reason": "host_appleevents_unavailable",
                "preflight": {
                    "window_probe": {"frontmost_probe_status": "blocked"},
                    "diagnostic": {"category": "host_appleevents_unavailable"},
                },
            },
            app_id="tashuo",
        )

        self.assertEqual(app_check["reason"], "host_appleevents_unavailable")
        self.assertEqual(app_check["diagnostic"]["category"], "host_appleevents_unavailable")
        self.assertEqual(app_check["window_probe"]["frontmost_probe_status"], "blocked")
        self.assertEqual(
            managed_session_core._precheck_failure_next_host_action(
                profile["managed_session"],
                app_check,
                runtime="mac-ios-app",
            ),
            "check_host_automation_system_events_permission_and_resume_managed_session",
        )

    def test_wechat_unavailable_pauses_without_send_work(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            repo = ManagedSessionRepository(
                data_dir,
                harness_factory=lambda app_id, runtime=None: FakeHarness(
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
            repo = ManagedSessionRepository(data_dir, harness_factory=lambda app_id, runtime=None: harness.for_app(app_id))
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

    def test_scan_later_state_wakes_managed_session_before_scan_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            repo = self._started_repo(data_dir, scan_interval_seconds=3600)
            states_path = data_dir / "automation" / "states.json"
            _write_json(
                states_path,
                {
                    "schema_version": 1,
                    "states": [
                        {
                            "schema_version": 1,
                            "match_id": "provisional_scan_later",
                            "candidate_key": "row_scan_later",
                            "state": "scan_later",
                            "last_scan_cursor": {"current": "page_1", "next": "page_2", "exhausted": False},
                        }
                    ],
                },
            )

            payload = repo.tick()

        self.assertEqual(payload["status"], "host_work_required")
        self.assertIn("scan_later_pending", payload["wake_reasons"])
        self.assertEqual(payload["work_item"]["work_item_type"], "scan_message_list")
        self.assertEqual(
            payload["relationship_progress_snapshot"]["next_priority_queue"][0]["candidate_key"],
            "row_scan_later",
        )
        self.assertEqual(
            payload["relationship_progress_snapshot"]["current_work_item"]["work_item_type"],
            "scan_message_list",
        )

    def test_tick_outputs_relationship_progress_snapshot_for_no_work(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            repo = self._started_repo(data_dir, scan_interval_seconds=3600)

            payload = repo.tick()

        self.assertEqual(payload["status"], "no_work")
        self.assertEqual(payload["relationship_progress_snapshot"]["summary"]["match_count"], 0)
        self.assertEqual(payload["relationship_progress_snapshot"]["next_priority_queue"], [])

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
                side_effect=lambda app_id, runtime=None: FakeHarness(app_id=app_id, tinder_payload=_app_payload("tinder")),
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
        self.assertEqual(stop_payload["next_host_action"], "present_relationship_progress_report")
        report = stop_payload["relationship_progress_report"]
        self.assertEqual(report["format"], "markdown")
        self.assertIn("Dating Booster Session Report", report["markdown"])

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
            harness_factory=lambda app_id, runtime=None: (harness or FakeHarness(app_id=app_id)).for_app(app_id),
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
        repo = ManagedSessionRepository(data_dir, harness_factory=lambda app_id, runtime=None: FakeHarness(app_id=app_id))
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
