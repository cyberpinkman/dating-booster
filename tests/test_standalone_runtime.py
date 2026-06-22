import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.core.draft_evidence import UserMemoryRepository
from dating_boost.core.managed_session import ManagedSessionRepository
from dating_boost.core.standalone_actions import StageOnlyActionExecutor
from dating_boost.core.standalone_observation import (
    FixtureObservationProvider,
    _thread_fixture_name,
    fixture_harness_factory,
)
from dating_boost.core.standalone_runtime import StandaloneAgentRuntime


AUTOMATION_FIXTURE_DIR = Path("tests/fixtures/automation")


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

    def test_runtime_blocks_provider_failure_without_crashing(self):
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
        self.assertEqual(payload["reason"], "observation_capture_failed")
        self.assertEqual(payload["error_type"], "FileNotFoundError")

    def test_runtime_blocks_ingest_failure_without_crashing(self):
        class Provider:
            def observe_message_list(self, **kwargs):
                return {
                    "schema_version": 1,
                    "observation_type": "message_list",
                    "app_id": "tinder",
                    "message_list_snapshot": {"entries": []},
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = StandaloneAgentRuntime(Path(temp_dir) / "data", observation_provider=Provider())
            runtime.operator.ingest_observation = lambda observation: (_ for _ in ()).throw(ValueError("bad observation"))

            payload = runtime.consume_work_item(
                {"schema_version": 1, "work_item_type": "scan_message_list"},
                managed_payload={"schema_version": 1, "status": "host_work_required", "app_id": "tinder"},
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "observation_ingest_failed")
        self.assertEqual(payload["error_type"], "ValueError")
        self.assertEqual(payload["error_message"], "bad observation")

    def test_runtime_returns_provider_blocked_observation_without_ingesting(self):
        class Provider:
            def observe_thread(self, **kwargs):
                return {
                    "schema_version": 1,
                    "status": "blocked",
                    "reason": "current_thread_visual_identity_not_verified",
                    "observation_type": "thread",
                    "app_id": "tashuo",
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = StandaloneAgentRuntime(Path(temp_dir) / "data", observation_provider=Provider())

            payload = runtime.consume_work_item(
                {"schema_version": 1, "work_item_type": "open_thread", "candidate_key": "row_ada"},
                managed_payload={"schema_version": 1, "status": "host_work_required", "app_id": "tashuo"},
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "current_thread_visual_identity_not_verified")
        self.assertEqual(payload["observation_type"], "thread")
        self.assertEqual(payload["observation"]["status"], "blocked")

    def test_fixture_runtime_reaches_stage_recorded_through_operator_send_message(self):
        with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T00:00:00Z"}):
            with tempfile.TemporaryDirectory() as temp_dir:
                data_dir = Path(temp_dir) / "data"
                fixture_dir = Path(temp_dir) / "fixtures"
                fixture_dir.mkdir()
                _init_profile(data_dir)
                (fixture_dir / "message_list.json").write_text(
                    json.dumps(_single_candidate_message_list_observation("row_ada"), ensure_ascii=False),
                    encoding="utf-8",
                )
                (fixture_dir / "thread_row_ada.json").write_text(
                    json.dumps(_thread_observation("row_ada"), ensure_ascii=False),
                    encoding="utf-8",
                )
                provider = FixtureObservationProvider(fixture_dir)
                managed = ManagedSessionRepository(
                    data_dir,
                    harness_factory=fixture_harness_factory(provider),
                )
                started = managed.start(
                    app_id="tinder",
                    authorization=json.loads((AUTOMATION_FIXTURE_DIR / "auth_send.json").read_text(encoding="utf-8")),
                    goal=None,
                    availability=None,
                    send_mode="stage",
                    managed_gui_send=False,
                )
                runtime = StandaloneAgentRuntime(
                    data_dir,
                    observation_provider=provider,
                    harness_factory=fixture_harness_factory(provider),
                    action_executor=StageOnlyActionExecutor(data_dir, send_mode="stage"),
                )

                scan_tick = runtime.tick()
                open_tick = runtime.tick()
                runtime.managed.tick = lambda: (_ for _ in ()).throw(AssertionError("managed precheck should not run before send continuation"))
                final_tick = runtime.tick()

        self.assertEqual(started["status"], "active")
        self.assertEqual(scan_tick["status"], "work_consumed")
        self.assertEqual(scan_tick["work_item_type"], "scan_message_list")
        self.assertEqual(open_tick["status"], "work_consumed")
        self.assertEqual(open_tick["work_item_type"], "open_thread")
        self.assertEqual(final_tick["status"], "stage_recorded")
        self.assertEqual(final_tick["result_status"], "succeeded")
        self.assertEqual(final_tick["recorded"]["status"], "ok")
        self.assertNotEqual(final_tick.get("reason"), "operator_draft_work_item_not_available")
        self.assertNotEqual(final_tick.get("status"), "needs_operator_draft_work_item")

    def test_runtime_runs_managed_precheck_before_continuation_open_thread(self):
        with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T00:00:00Z"}):
            with tempfile.TemporaryDirectory() as temp_dir:
                data_dir = Path(temp_dir) / "data"
                fixture_dir = Path(temp_dir) / "fixtures"
                fixture_dir.mkdir()
                _init_profile(data_dir)
                message_list = _message_list_observation()
                entries = message_list["message_list_snapshot"]["entries"]
                message_list["message_list_snapshot"]["entries"] = [
                    entry for entry in entries if entry["candidate_key"] in {"row_ada", "row_bea"}
                ]
                (fixture_dir / "message_list.json").write_text(
                    json.dumps(message_list, ensure_ascii=False),
                    encoding="utf-8",
                )
                first_thread = _thread_observation("row_ada")
                first_thread.pop("draft", None)
                (fixture_dir / "thread_row_ada.json").write_text(
                    json.dumps(first_thread, ensure_ascii=False),
                    encoding="utf-8",
                )
                (fixture_dir / "thread_row_bea.json").write_text(
                    json.dumps(_thread_observation("row_bea"), ensure_ascii=False),
                    encoding="utf-8",
                )
                provider = FixtureObservationProvider(fixture_dir)
                managed = ManagedSessionRepository(
                    data_dir,
                    harness_factory=fixture_harness_factory(provider),
                )
                managed.start(
                    app_id="tinder",
                    authorization=json.loads((AUTOMATION_FIXTURE_DIR / "auth_send.json").read_text(encoding="utf-8")),
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
                original_managed_tick = runtime.managed.tick
                managed_tick_calls: list[str] = []

                runtime.tick()
                open_first = runtime.tick()

                def wrapped_managed_tick():
                    managed_tick_calls.append("tick")
                    return original_managed_tick()

                runtime.managed.tick = wrapped_managed_tick
                open_second = runtime.tick()

        self.assertEqual(open_first["work_item_type"], "open_thread")
        self.assertEqual(open_second["status"], "work_consumed")
        self.assertEqual(open_second["work_item_type"], "open_thread")
        self.assertEqual(managed_tick_calls, ["tick"])

    def test_runtime_uses_draft_planner_when_thread_observation_has_no_draft(self):
        class FakeDraftPlanner:
            def __init__(self):
                self.calls = []

            def draft_for_match(self, *, match_id: str, mode: str) -> dict[str, object]:
                self.calls.append({"match_id": match_id, "mode": mode})
                return {
                    "schema_version": 1,
                    "status": "ok",
                    "match_id": match_id,
                    "mode": mode,
                    "draft": _thread_observation("row_ada")["draft"],
                    "draft_generation_summary": {"status": "ok", "source": "unit_fake"},
                    "draft_review": {"allowed_for_managed_send": True},
                }

        with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T00:00:00Z"}):
            with tempfile.TemporaryDirectory() as temp_dir:
                data_dir = Path(temp_dir) / "data"
                fixture_dir = Path(temp_dir) / "fixtures"
                fixture_dir.mkdir()
                _init_profile(data_dir)
                (fixture_dir / "message_list.json").write_text(
                    json.dumps(_single_candidate_message_list_observation("row_ada"), ensure_ascii=False),
                    encoding="utf-8",
                )
                thread_without_draft = _thread_observation("row_ada")
                thread_without_draft.pop("draft")
                (fixture_dir / "thread_row_ada.json").write_text(
                    json.dumps(thread_without_draft, ensure_ascii=False),
                    encoding="utf-8",
                )
                provider = FixtureObservationProvider(fixture_dir)
                planner = FakeDraftPlanner()
                managed = ManagedSessionRepository(
                    data_dir,
                    harness_factory=fixture_harness_factory(provider),
                )
                started = managed.start(
                    app_id="tinder",
                    authorization=json.loads((AUTOMATION_FIXTURE_DIR / "auth_send.json").read_text(encoding="utf-8")),
                    goal=None,
                    availability=None,
                    send_mode="stage",
                    managed_gui_send=False,
                )
                runtime = StandaloneAgentRuntime(
                    data_dir,
                    observation_provider=provider,
                    harness_factory=fixture_harness_factory(provider),
                    action_executor=StageOnlyActionExecutor(data_dir, send_mode="stage"),
                    draft_planner=planner,
                )

                scan_tick = runtime.tick()
                open_tick = runtime.tick()
                final_tick = runtime.tick()

        self.assertEqual(started["status"], "active")
        self.assertEqual(scan_tick["work_item_type"], "scan_message_list")
        self.assertEqual(open_tick["work_item_type"], "open_thread")
        self.assertEqual(planner.calls[0]["mode"], "adaptive")
        self.assertEqual(final_tick["status"], "stage_recorded")
        self.assertEqual(final_tick["result_status"], "succeeded")


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


def _init_profile(data_dir: Path) -> None:
    _run_cli(
        [
            "init-profile",
            "--data-dir",
            str(data_dir),
            "--input",
            "tests/fixtures/intelligence/user_profile.json",
        ]
    )
    _run_cli(
        [
            "user",
            "ingest-profile",
            "--data-dir",
            str(data_dir),
            "--input",
            "tests/fixtures/intelligence/user_dating_profile.json",
        ]
    )
    _run_cli(
        [
            "user",
            "ingest-interview",
            "--data-dir",
            str(data_dir),
            "--input",
            "tests/fixtures/intelligence/user_self_interview.json",
        ]
    )
    UserMemoryRepository(data_dir).ensure_profile_source(
        app_id="tinder",
        runtime="default",
        observed_at="2026-05-26T00:00:00Z",
    )


def _run_cli(argv: list[str]) -> dict[str, object]:
    output = StringIO()
    with redirect_stdout(output):
        code = main(argv)
    if code != 0:
        raise AssertionError(output.getvalue())
    return json.loads(output.getvalue())


def _message_list_observation() -> dict[str, object]:
    scan = json.loads((AUTOMATION_FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
    return {
        "schema_version": 1,
        "observation_type": "message_list",
        "session_id": scan["session_id"],
        "app_id": scan["app_id"],
        "captured_at": scan["captured_at"],
        "scan_cursor": scan["scan_cursor"],
        "scan_budget": scan["scan_budget"],
        "provenance": scan["provenance"],
        "message_list_snapshot": scan["message_list_snapshot"],
    }


def _single_candidate_message_list_observation(candidate_key: str) -> dict[str, object]:
    payload = _message_list_observation()
    entries = payload["message_list_snapshot"]["entries"]
    payload["message_list_snapshot"]["entries"] = [
        entry for entry in entries if entry["candidate_key"] == candidate_key
    ]
    return payload


def _thread_observation(candidate_key: str) -> dict[str, object]:
    scan = json.loads((AUTOMATION_FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
    for item in scan["thread_observations"]:
        if item["candidate_key"] == candidate_key:
            payload = dict(item)
            payload["schema_version"] = 1
            payload["observation_type"] = "thread"
            if isinstance(payload.get("draft"), dict):
                payload["draft"] = {
                    **payload["draft"],
                    "draft_generation_id": "draft_generation_standalone_runtime_fixture",
                    "draft_self_review_summary": {
                        "schema_version": 1,
                        "ai_or_weird_probability": 0,
                        "status": "ok",
                        "source": "unit_fixture",
                    },
                }
            return payload
    raise AssertionError(f"missing fixture thread observation: {candidate_key}")


if __name__ == "__main__":
    unittest.main()
