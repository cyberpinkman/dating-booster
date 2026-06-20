# Standalone Agent Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone Dating Booster agent runtime that can consume the existing managed-session/operator contracts without breaking the current host-agent-native workflow.

**Architecture:** Keep the existing host-native path as the stable production route. Add a standalone runtime as a new consumer of managed-session/operator work items: first with fixture/manual observations, then with local model-backed drafting, then with daemon-supervised sessions, and only after that with live GUI staging/send through the existing managed-send verification contract.

**Tech Stack:** Python 3.11+, existing `JsonStorage`, existing `ManagedSessionRepository`, existing `OperatorRepository`, existing `ModelBackend` and `OpenAIBackend`, pytest, current CLI style in `dating_boost/cli.py`.

---

## Current Baseline

Current inspection was done on 2026-06-20 in `/Users/pink/Documents/dating-booster`.

- Branch: `main`.
- Remote state: local `main` matched `origin/main` during inspection.
- Current commit: `48cbd17 chore: sync latest workspace updates`.
- Version: `1.0.0-rc.2.dev0`.
- Existing runtime surfaces:
  - `dating-boost-host-loop` owns the supervised host-loop path.
  - `dating-boost managed-session` owns bounded session scheduling and wake conditions.
  - `dating-boost operator` owns serial work item generation and audit result ingestion.
  - `dating-boostd` exists, but `dating_boost/core/daemon.py` is a heartbeat, lock, launchd, status, install, uninstall, and stop wrapper. It does not own perception, model planning, operator tick execution, confirmation, or GUI actions.
  - `dating_boost/intelligence/backends.py` already defines `ModelBackend`, `ScriptedBackend`, and `OpenAIBackend`.
  - `dating_boost/intelligence/draft_generation.py` already has refinement and audit support.
  - `dating_boost/core/managed_gui_send.py` already protects managed live send, but it is coupled to a host-loop port object.
- Capabilities facts:
  - `local_daemon: true`.
  - `local_daemon_scope: local_cli_and_launchd_support_not_a_persistent_dating_listener`.
  - `llm_owned_by_host_agent: true`.
  - `repo_computer_use_execution_backend: false`.
  - `managed_session_global_background: false`.
  - `managed_live_send_guidance.direct_harness_scope: executor_internal_only`.
- Current full regression command:

```bash
PYTHONPATH=. uv run --extra test pytest -q
```

Current observed result in this workspace:

```text
12 failed, 777 passed, 167 subtests passed in 635.61s
```

Current failing tests observed before this plan was written:

- `tests/test_agent_native_launch_docs.py::AgentNativeLaunchDocsTests::test_smoke_script_default_data_dir_keeps_artifacts_after_exit`
- `tests/test_agent_native_launch_docs.py::AgentNativeLaunchDocsTests::test_smoke_script_runs_complete_fixture_workflow`
- `tests/test_agent_native_manual_workflow.py::AgentNativeManualWorkflowTests::test_reward_delegation_fixture_runs_screenshot_to_context_to_policy_to_feedback`
- `tests/test_automation_session.py::AutomationSessionTests::test_due_nudge_with_fresh_draft_generates_one_send_request`
- `tests/test_automation_session.py::AutomationSessionTests::test_failed_send_result_allows_same_payload_retry_with_new_request_id`
- `tests/test_automation_session.py::AutomationSessionTests::test_mismatched_action_result_does_not_complete_pending_send`
- `tests/test_automation_session.py::AutomationSessionTests::test_session_step_processes_scan_batch_and_prevents_duplicate_sends`
- `tests/test_automation_session.py::AutomationSessionTests::test_session_step_requeues_revision_when_content_policy_blocks_draft`
- `tests/test_automation_session.py::AutomationSessionTests::test_session_stop_report_and_resume`
- `tests/test_automation_session.py::AutomationSessionTests::test_stale_same_payload_hash_in_non_active_state_retries_instead_of_suppressing`
- `tests/test_production_reliability.py::ProductionReliabilityTests::test_automation_step_outputs_run_id_idempotency_key_lock_and_replays_same_key`
- `tests/test_production_reliability.py::ProductionReliabilityTests::test_default_idempotency_key_ignores_scan_cursor_and_capture_time`

These failures are not part of the standalone migration itself. They are a migration gate: the standalone runtime must not be built on a red host-native baseline.

## Product Conclusion

The current codebase is no longer a simple MVP. It already contains the right reusable core:

- app profiles and registry.
- local memory and context.
- draft evidence and draft generation.
- policy and confirmation contracts.
- managed-session and operator state machines.
- runtime scope enforcement.
- GUI harness adapters.
- managed live send verification.

The missing product piece is a standalone agent runtime that replaces host-agent responsibilities one by one:

| Responsibility | Current Owner | Standalone Target Owner |
| --- | --- | --- |
| Visual observation and screen interpretation | Host agent plus harness docs | `StandaloneObservationProvider` with fixture/manual first and live provider later |
| Draft planning and reply generation | Host agent or `dating-boost draft` CLI | `StandaloneDraftPlanner` using `ModelBackend` |
| Work item execution loop | Host-loop supervisor or human host | `StandaloneAgentRuntime` |
| Session scheduling | `managed-session` returns `host_work_required` | `StandaloneSessionRepository` calls managed-session and consumes work |
| Confirmation and wait points | Host conversation | CLI/daemon session status files and confirmation commands |
| GUI staging/send | Host-loop plus `ManagedGuiSendRunner` | shared managed-send port reused by host-loop and standalone runtime |
| User reports | Host-loop/managed-session final output | standalone session report using existing relationship report |

## Non-Negotiable Boundaries

- Do not replace `managed-session`, `operator`, app adapters, or target-binding rules.
- Do not make daemon mode globally listen outside a user-started session.
- Do not add direct raw click/type authority to model backends.
- Do not execute direct `harness <app> send-message` from standalone code unless the action request came from existing operator or confirmation contracts.
- Do not loosen `runtime_scope_mismatch`, safety pause, target binding, exact staged-text, outbound evidence, or post-action verification.
- Do not introduce fake fallback replies when model generation fails. Return a structured blocked result.
- Do not make `OpenAIBackend` a hard dependency for users running scripted or host-native workflows.

## File Structure

Create:

- `dating_boost/core/standalone_session.py`
  Own standalone session state, config, status, stop, and event log.

- `dating_boost/core/standalone_runtime.py`
  Consume managed-session/operator work items using observation, drafting, and action ports.

- `dating_boost/core/standalone_observation.py`
  Define observation provider interfaces plus fixture/manual providers.

- `dating_boost/core/standalone_actions.py`
  Define stage/live action executor interfaces and initial dry/stage executors.

- `dating_boost/intelligence/backend_factory.py`
  Centralize `scripted` and `openai` backend construction currently embedded in CLI behavior.

- `tests/test_standalone_session.py`
  Session repository and CLI state tests.

- `tests/test_standalone_runtime.py`
  Runtime work item consumption tests with fixture observations.

- `tests/test_standalone_model_loop.py`
  Draft planner tests with `ScriptedBackend`.

- `tests/test_standalone_actions.py`
  Stage, confirmation, blocked live-send, and audit-result tests.

- `tests/test_daemon_standalone.py`
  Daemon run-once integration tests for standalone sessions.

Modify:

- `dating_boost/cli.py`
  Add `standalone-session` command group and route backend selection through `backend_factory.py`.

- `dating_boost/core/capabilities.py`
  Advertise standalone runtime capabilities only after tests pass.

- `dating_boost/core/daemon.py`
  Add run-once standalone tick support without changing launchd install semantics.

- `dating_boost/core/managed_gui_send.py`
  Introduce a typed port for host-loop and standalone send execution before standalone live send is enabled.

- `dating_boost/host_loop.py`
  Adapt to the typed managed-send port without changing current behavior.

- `README.md`
  Add human-facing standalone status only after the CLI exists.

- `AGENTS.md`
  Add host-agent guidance that host-native remains the default route and standalone is opt-in.

- `docs/ARCHITECTURE.md`
  Update mature architecture status after the standalone fixture loop passes.

- `docs/README.md`
  Add standalone module map and verification commands.

## Migration Gates

Gate A must be green before code migration starts:

```bash
PYTHONPATH=. uv run --extra test pytest -q
```

Expected:

```text
passed
```

If Gate A fails with the current 12 known failures, repair the baseline in a separate branch or commit before starting Task 1. Do not mix baseline repair and standalone migration in one commit.

Gate B is the fixture standalone gate:

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_session.py tests/test_standalone_runtime.py tests/test_standalone_model_loop.py -q
```

Expected:

```text
passed
```

Gate C is the full migration gate:

```bash
PYTHONPATH=. uv run --extra test pytest -q
```

Expected:

```text
passed
```

---

## Round 1: Standalone Session State

### Task 1: Add Standalone Session Repository

**Files:**
- Create: `dating_boost/core/standalone_session.py`
- Test: `tests/test_standalone_session.py`
- Modify: `dating_boost/core/capabilities.py`

- [ ] **Step 1: Write failing session repository tests**

Add `tests/test_standalone_session.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

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
                scan_interval_seconds=120,
            )
            status = repo.status()
            stopped = repo.stop(reason="manual_stop")
            session_path = data_dir / "standalone_session" / "session.json"
            events_path = data_dir / "standalone_session" / "events.jsonl"

        self.assertEqual(started["status"], "active")
        self.assertEqual(status["session"]["app_id"], "tinder")
        self.assertEqual(status["session"]["send_mode"], "stage")
        self.assertEqual(stopped["status"], "stopped")
        self.assertTrue(session_path.exists())
        self.assertTrue(events_path.exists())

    def test_start_rejects_live_without_managed_gui_send(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = StandaloneSessionRepository(Path(temp_dir) / "data")

            payload = repo.start(
                app_id="tinder",
                runtime=None,
                send_mode="live",
                observation_source={"type": "fixture_dir", "path": "tests/fixtures/standalone"},
                backend={"type": "scripted", "path": "tests/fixtures/intelligence/scripted_reply.json"},
                scan_interval_seconds=120,
                managed_gui_send=False,
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "managed_gui_send_required_for_live_mode")
```

Run:

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_session.py -q
```

Expected: fails because `dating_boost.core.standalone_session` does not exist.

- [ ] **Step 2: Implement `StandaloneSessionRepository`**

Create `dating_boost/core/standalone_session.py` with:

```python
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dating_boost.apps.registry import supported_app_ids
from dating_boost.core.storage import JsonStorage


STANDALONE_SESSION_SCHEMA_VERSION = 1
STANDALONE_EVENT_SCHEMA_VERSION = 1
STANDALONE_SESSION_PATH = Path("standalone_session") / "session.json"
STANDALONE_EVENTS_PATH = Path("standalone_session") / "events.jsonl"
SUPPORTED_SEND_MODES = {"stage", "live"}


class StandaloneSessionRepository:
    def __init__(self, root: Path):
        self.root = root
        self._storage = JsonStorage(root)

    def start(
        self,
        *,
        app_id: str,
        runtime: str | None,
        send_mode: str,
        observation_source: dict[str, Any],
        backend: dict[str, Any],
        scan_interval_seconds: int,
        managed_gui_send: bool = False,
    ) -> dict[str, Any]:
        if app_id not in set(supported_app_ids()):
            return _payload("blocked", reason=f"unsupported_app:{app_id}")
        if send_mode not in SUPPORTED_SEND_MODES:
            return _payload("blocked", reason="unsupported_send_mode")
        if send_mode == "live" and not managed_gui_send:
            return _payload("blocked", reason="managed_gui_send_required_for_live_mode")
        session = {
            "schema_version": STANDALONE_SESSION_SCHEMA_VERSION,
            "session_id": f"standalone_{_digest({'pid': os.getpid(), 'now': _now_iso()})[:16]}",
            "status": "active",
            "app_id": app_id,
            "runtime": runtime,
            "send_mode": send_mode,
            "managed_gui_send": bool(managed_gui_send),
            "observation_source": dict(observation_source),
            "backend": dict(backend),
            "scan_interval_seconds": max(1, int(scan_interval_seconds)),
            "started_at": _now_iso(),
            "updated_at": _now_iso(),
            "stopped_at": None,
            "stop_reason": None,
            "last_tick": None,
        }
        self._storage.write_json(STANDALONE_SESSION_PATH, session)
        self._append_event("start", {"session_id": session["session_id"], "app_id": app_id})
        return _payload("active", session=session)

    def status(self) -> dict[str, Any]:
        try:
            session = self._storage.read_json(
                STANDALONE_SESSION_PATH,
                expected_schema_version=STANDALONE_SESSION_SCHEMA_VERSION,
            )
        except FileNotFoundError:
            return _payload("not_found", reason="standalone_session_not_started")
        return _payload(str(session.get("status") or "unknown"), session=session)

    def stop(self, *, reason: str) -> dict[str, Any]:
        payload = self.status()
        if payload.get("status") == "not_found":
            return _payload("stopped", reason=reason)
        session = dict(payload["session"])
        session["status"] = "stopped"
        session["stopped_at"] = _now_iso()
        session["updated_at"] = session["stopped_at"]
        session["stop_reason"] = reason
        self._storage.write_json(STANDALONE_SESSION_PATH, session)
        self._append_event("stop", {"session_id": session["session_id"], "reason": reason})
        return _payload("stopped", session=session, reason=reason)

    def record_tick(self, tick: dict[str, Any]) -> dict[str, Any]:
        payload = self.status()
        if payload.get("status") != "active":
            return payload
        session = dict(payload["session"])
        session["last_tick"] = dict(tick)
        session["updated_at"] = _now_iso()
        self._storage.write_json(STANDALONE_SESSION_PATH, session)
        self._append_event("tick", {"session_id": session["session_id"], "tick": tick})
        return _payload("ok", session=session)

    def _append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self._storage.append_jsonl(
            STANDALONE_EVENTS_PATH,
            {
                "schema_version": STANDALONE_EVENT_SCHEMA_VERSION,
                "event_type": event_type,
                "created_at": _now_iso(),
                "payload": payload,
            },
        )


def _payload(status: str, **kwargs: Any) -> dict[str, Any]:
    return {"schema_version": STANDALONE_SESSION_SCHEMA_VERSION, "status": status, **kwargs}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
```

- [ ] **Step 3: Add capability flags**

Modify `dating_boost/core/capabilities.py` so `agent_native_capabilities` includes:

```python
"standalone_agent_runtime": True,
"standalone_agent_default_mode": "fixture_or_manual_first",
"standalone_agent_live_gui_default": False,
"standalone_agent_uses_existing_operator_contract": True,
```

Add assertions to `tests/test_standalone_session.py`:

```python
from dating_boost.core.capabilities import build_capabilities


def test_capabilities_expose_standalone_runtime_contract(self):
    payload = build_capabilities(data_dir=Path(".local/dating-boost"))
    caps = payload["agent_native_capabilities"]

    self.assertTrue(caps["standalone_agent_runtime"])
    self.assertEqual(caps["standalone_agent_default_mode"], "fixture_or_manual_first")
    self.assertFalse(caps["standalone_agent_live_gui_default"])
    self.assertTrue(caps["standalone_agent_uses_existing_operator_contract"])
```

Run:

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_session.py -q
```

Expected: passes.

- [ ] **Step 4: Commit Round 1**

```bash
git add dating_boost/core/standalone_session.py dating_boost/core/capabilities.py tests/test_standalone_session.py
git commit -m "feat: add standalone session state"
```

---

## Round 2: Fixture And Manual Observation Providers

### Task 2: Add Standalone Observation Ports

**Files:**
- Create: `dating_boost/core/standalone_observation.py`
- Test: `tests/test_standalone_runtime.py`

- [ ] **Step 1: Write failing observation provider tests**

Add to `tests/test_standalone_runtime.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from dating_boost.core.standalone_observation import FixtureObservationProvider


class FixtureObservationProviderTests(unittest.TestCase):
    def test_loads_message_list_and_thread_observations_in_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            (fixture_dir / "message_list.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "observation_type": "message_list",
                    "app_id": "tinder",
                    "message_list_snapshot": {"entries": [{"candidate_key": "row_ada", "visible_name": "Ada"}]},
                    "scan_cursor": {"current": None, "next": None, "exhausted": True},
                }),
                encoding="utf-8",
            )
            (fixture_dir / "thread_row_ada.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "observation_type": "thread",
                    "app_id": "tinder",
                    "match_identity_hints": {"visible_name": "Ada", "conversation_fingerprint": "ada-fp"},
                    "conversation_observation": {"visible_messages": [{"sender": "match", "text": "你定"}]},
                }),
                encoding="utf-8",
            )
            provider = FixtureObservationProvider(fixture_dir)

            message_list = provider.observe_message_list(app_id="tinder", scan_cursor={})
            thread = provider.observe_thread(app_id="tinder", candidate_key="row_ada")

        self.assertEqual(message_list["observation_type"], "message_list")
        self.assertEqual(thread["observation_type"], "thread")
        self.assertEqual(thread["candidate_key"], "row_ada")
```

Run:

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_runtime.py::FixtureObservationProviderTests -q
```

Expected: fails because `standalone_observation.py` does not exist.

- [ ] **Step 2: Implement provider protocols and fixture provider**

Create `dating_boost/core/standalone_observation.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class StandaloneObservationProvider(Protocol):
    def observe_message_list(self, *, app_id: str, scan_cursor: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def observe_thread(self, *, app_id: str, candidate_key: str) -> dict[str, Any]:
        raise NotImplementedError

    def observe_current_thread(self, *, app_id: str) -> dict[str, Any]:
        raise NotImplementedError


class FixtureObservationProvider:
    def __init__(self, fixture_dir: Path):
        self.fixture_dir = fixture_dir

    def observe_message_list(self, *, app_id: str, scan_cursor: dict[str, Any]) -> dict[str, Any]:
        payload = self._read("message_list.json")
        payload.setdefault("schema_version", 1)
        payload["observation_type"] = "message_list"
        payload["app_id"] = app_id
        payload.setdefault("scan_cursor", scan_cursor or {"current": None, "next": None, "exhausted": True})
        return payload

    def observe_thread(self, *, app_id: str, candidate_key: str) -> dict[str, Any]:
        payload = self._read(f"thread_{_safe_name(candidate_key)}.json")
        payload.setdefault("schema_version", 1)
        payload["observation_type"] = "thread"
        payload["app_id"] = app_id
        payload["candidate_key"] = candidate_key
        return payload

    def observe_current_thread(self, *, app_id: str) -> dict[str, Any]:
        payload = self._read("current_thread.json")
        payload.setdefault("schema_version", 1)
        payload["observation_type"] = "thread"
        payload["app_id"] = app_id
        payload.setdefault("candidate_key", "current_thread")
        return payload

    def precheck_payload(self, *, app_id: str) -> dict[str, Any]:
        path = self.fixture_dir / "precheck.json"
        if path.exists():
            payload = self._read("precheck.json")
        else:
            payload = {"schema_version": 1, "status": "ok", "screen_state": "fixture_ready"}
        payload["app_id"] = app_id
        return payload

    def _read(self, name: str) -> dict[str, Any]:
        path = self.fixture_dir / name
        if not path.exists():
            raise FileNotFoundError(f"fixture observation missing: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"fixture observation must be a JSON object: {path}")
        return value


class FixturePrecheckHarness:
    def __init__(self, provider: FixtureObservationProvider, *, app_id: str):
        self.provider = provider
        self.app_id = app_id

    def observe(self) -> dict[str, Any]:
        return self.provider.precheck_payload(app_id=self.app_id)


def fixture_harness_factory(provider: FixtureObservationProvider):
    def _factory(app_id: str, runtime: str | None = None) -> FixturePrecheckHarness:
        return FixturePrecheckHarness(provider, app_id=app_id)

    return _factory


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
```

- [ ] **Step 3: Run provider tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_runtime.py::FixtureObservationProviderTests -q
```

Expected: passes.

- [ ] **Step 4: Commit Round 2**

```bash
git add dating_boost/core/standalone_observation.py tests/test_standalone_runtime.py
git commit -m "feat: add standalone observation providers"
```

---

## Round 3: Standalone Runtime Consumes Operator Work

### Task 3: Implement Runtime Tick For Read-Only Work Items

**Files:**
- Create: `dating_boost/core/standalone_runtime.py`
- Modify: `tests/test_standalone_runtime.py`

- [ ] **Step 1: Write failing runtime tests**

Append to `tests/test_standalone_runtime.py`:

```python
from dating_boost.core.managed_session import ManagedSessionRepository
from dating_boost.core.standalone_runtime import StandaloneAgentRuntime
from dating_boost.core.standalone_observation import FixtureObservationProvider, fixture_harness_factory


class StandaloneRuntimeTests(unittest.TestCase):
    def test_tick_consumes_scan_message_list_work_item(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            (fixture_dir / "message_list.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "observation_type": "message_list",
                    "app_id": "tinder",
                    "captured_at": "2026-06-20T00:00:00Z",
                    "message_list_snapshot": {"entries": []},
                    "scan_cursor": {"current": None, "next": None, "exhausted": True},
                }),
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
            runtime = StandaloneAgentRuntime(data_dir, observation_provider=provider)

            tick = runtime.tick()
            state = runtime.operator.get_state_payload()

        self.assertEqual(started["status"], "active")
        self.assertEqual(tick["status"], "work_consumed")
        self.assertEqual(tick["work_item_type"], "scan_message_list")
        self.assertIsNotNone(state["pending_scan_batch"])
```

Use this local helper in the same file:

```python
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
```

Run:

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_runtime.py::StandaloneRuntimeTests -q
```

Expected: fails because `StandaloneAgentRuntime` does not exist.

- [ ] **Step 2: Implement read-only runtime tick**

Create `dating_boost/core/standalone_runtime.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.core.managed_session import ManagedSessionRepository
from dating_boost.core.operator import OperatorRepository
from dating_boost.core.standalone_observation import StandaloneObservationProvider


class StandaloneAgentRuntime:
    def __init__(self, root: Path, *, observation_provider: StandaloneObservationProvider):
        self.root = root
        self.observation_provider = observation_provider
        self.managed = ManagedSessionRepository(root)
        self.operator = OperatorRepository(root)

    def tick(self) -> dict[str, Any]:
        managed_payload = self.managed.tick()
        if managed_payload.get("status") != "host_work_required":
            return {
                "schema_version": 1,
                "status": str(managed_payload.get("status") or "unknown"),
                "managed_session": managed_payload,
            }
        work_item = managed_payload.get("work_item")
        if not isinstance(work_item, dict):
            return {"schema_version": 1, "status": "blocked", "reason": "managed_session_missing_work_item"}
        return self.consume_work_item(work_item, managed_payload=managed_payload)

    def consume_work_item(self, work_item: dict[str, Any], *, managed_payload: dict[str, Any]) -> dict[str, Any]:
        app_id = str(managed_payload.get("app_id") or work_item.get("app_id") or "tinder")
        work_type = str(work_item.get("work_item_type") or "")
        if work_type == "scan_message_list":
            observation = self.observation_provider.observe_message_list(
                app_id=app_id,
                scan_cursor=dict(work_item.get("scan_cursor") or {}),
            )
            ingested = self.operator.ingest_observation(observation)
            return _consumed(work_type, ingested, work_item)
        if work_type == "open_thread":
            candidate_key = str(work_item.get("candidate_key") or "")
            observation = self.observation_provider.observe_thread(app_id=app_id, candidate_key=candidate_key)
            ingested = self.operator.ingest_observation(observation)
            return _consumed(work_type, ingested, work_item)
        if work_type == "observe_current_thread":
            observation = self.observation_provider.observe_current_thread(app_id=app_id)
            ingested = self.operator.ingest_observation(observation)
            return _consumed(work_type, ingested, work_item)
        if work_type in {"wait", "scheduled_wait"}:
            return {"schema_version": 1, "status": "no_work", "work_item_type": work_type, "work_item": work_item}
        if work_type in {"blocked", "handoff"}:
            return {"schema_version": 1, "status": work_type, "work_item_type": work_type, "work_item": work_item}
        if work_type == "send_message":
            return {
                "schema_version": 1,
                "status": "needs_action_executor",
                "work_item_type": work_type,
                "work_item": work_item,
                "next_step": "configure_standalone_action_executor",
            }
        return {"schema_version": 1, "status": "blocked", "reason": f"unsupported_work_item_type:{work_type}"}


def _consumed(work_type: str, ingested: dict[str, Any], work_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "work_consumed",
        "work_item_type": work_type,
        "work_item_id": work_item.get("work_item_id"),
        "ingested": ingested,
    }
```

- [ ] **Step 3: Run read-only runtime tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_runtime.py -q
```

Expected: passes.

- [ ] **Step 4: Commit Round 3**

```bash
git add dating_boost/core/standalone_runtime.py tests/test_standalone_runtime.py
git commit -m "feat: consume operator work in standalone runtime"
```

---

## Round 4: Standalone CLI

### Task 4: Add `standalone-session` CLI Commands

**Files:**
- Modify: `dating_boost/cli.py`
- Modify: `tests/test_standalone_session.py`

- [ ] **Step 1: Write failing CLI tests**

Append to `tests/test_standalone_session.py`:

```python
from contextlib import redirect_stdout
from io import StringIO

from dating_boost.cli import main


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
            start_exit, start_payload = self._run_cli([
                "standalone-session",
                "start",
                "--data-dir",
                str(data_dir),
                "--app-id",
                "tinder",
                "--send-mode",
                "stage",
                "--observation-fixture-dir",
                str(fixture_dir),
                "--backend",
                "scripted",
                "--scripted-backend-output",
                "tests/fixtures/intelligence/scripted_reply.json",
                "--json",
            ])
            status_exit, status_payload = self._run_cli([
                "standalone-session",
                "status",
                "--data-dir",
                str(data_dir),
                "--json",
            ])
            stop_exit, stop_payload = self._run_cli([
                "standalone-session",
                "stop",
                "--data-dir",
                str(data_dir),
                "--json",
            ])

        self.assertEqual(start_exit, 0)
        self.assertEqual(start_payload["status"], "active")
        self.assertEqual(status_exit, 0)
        self.assertEqual(status_payload["status"], "active")
        self.assertEqual(stop_exit, 0)
        self.assertEqual(stop_payload["status"], "stopped")
```

Run:

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_session.py::StandaloneSessionCliTests -q
```

Expected: fails because `standalone-session` is not a CLI group.

- [ ] **Step 2: Add parser group**

Modify `dating_boost/cli.py` parser setup near `managed-session`:

```python
standalone_parser = subparsers.add_parser("standalone-session", help="Standalone local agent session commands.")
standalone_subparsers = standalone_parser.add_subparsers(dest="standalone_command", required=True)

standalone_start_parser = standalone_subparsers.add_parser("start")
standalone_start_parser.add_argument("--data-dir", type=Path, required=True)
standalone_start_parser.add_argument("--app-id", required=True)
standalone_start_parser.add_argument("--runtime")
standalone_start_parser.add_argument("--send-mode", choices=["stage", "live"], default="stage")
standalone_start_parser.add_argument("--managed-gui-send", action="store_true")
standalone_start_parser.add_argument("--observation-fixture-dir", type=Path, required=True)
standalone_start_parser.add_argument("--backend", choices=["scripted", "openai"], default="scripted")
standalone_start_parser.add_argument("--model", default="gpt-4.1-mini")
standalone_start_parser.add_argument("--scripted-backend-output", type=Path)
standalone_start_parser.add_argument("--scan-interval", type=int, default=120)
standalone_start_parser.add_argument("--json", action="store_true")
standalone_start_parser.set_defaults(func=_handle_standalone_session_start)

standalone_tick_parser = standalone_subparsers.add_parser("tick")
standalone_tick_parser.add_argument("--data-dir", type=Path, required=True)
standalone_tick_parser.add_argument("--json", action="store_true")
standalone_tick_parser.set_defaults(func=_handle_standalone_session_tick)

standalone_status_parser = standalone_subparsers.add_parser("status")
standalone_status_parser.add_argument("--data-dir", type=Path, required=True)
standalone_status_parser.add_argument("--json", action="store_true")
standalone_status_parser.set_defaults(func=_handle_standalone_session_status)

standalone_stop_parser = standalone_subparsers.add_parser("stop")
standalone_stop_parser.add_argument("--data-dir", type=Path, required=True)
standalone_stop_parser.add_argument("--reason", default="manual_stop")
standalone_stop_parser.add_argument("--json", action="store_true")
standalone_stop_parser.set_defaults(func=_handle_standalone_session_stop)
```

Add handlers near managed-session handlers:

```python
def _handle_standalone_session_start(args: argparse.Namespace) -> int:
    from dating_boost.core.standalone_session import StandaloneSessionRepository

    backend = {"type": args.backend, "model": args.model}
    if args.scripted_backend_output is not None:
        backend["path"] = str(args.scripted_backend_output)
    payload = StandaloneSessionRepository(args.data_dir).start(
        app_id=args.app_id,
        runtime=args.runtime,
        send_mode=args.send_mode,
        observation_source={"type": "fixture_dir", "path": str(args.observation_fixture_dir)},
        backend=backend,
        scan_interval_seconds=args.scan_interval,
        managed_gui_send=bool(args.managed_gui_send),
    )
    _print_json(payload)
    return 0 if payload.get("status") == "active" else 2


def _handle_standalone_session_tick(args: argparse.Namespace) -> int:
    from dating_boost.core.standalone_observation import FixtureObservationProvider
    from dating_boost.core.standalone_runtime import StandaloneAgentRuntime
    from dating_boost.core.standalone_session import StandaloneSessionRepository

    status = StandaloneSessionRepository(args.data_dir).status()
    session = status.get("session") if isinstance(status.get("session"), dict) else None
    if not isinstance(session, dict):
        _print_json(status)
        return 2
    source = session.get("observation_source") if isinstance(session.get("observation_source"), dict) else {}
    provider = FixtureObservationProvider(Path(str(source.get("path") or "")))
    payload = StandaloneAgentRuntime(args.data_dir, observation_provider=provider).tick()
    StandaloneSessionRepository(args.data_dir).record_tick(payload)
    _print_json(payload)
    return 0 if payload.get("status") not in {"blocked", "error"} else 2


def _handle_standalone_session_status(args: argparse.Namespace) -> int:
    from dating_boost.core.standalone_session import StandaloneSessionRepository

    payload = StandaloneSessionRepository(args.data_dir).status()
    _print_json(payload)
    return 0 if payload.get("status") != "not_found" else 2


def _handle_standalone_session_stop(args: argparse.Namespace) -> int:
    from dating_boost.core.standalone_session import StandaloneSessionRepository

    payload = StandaloneSessionRepository(args.data_dir).stop(reason=args.reason)
    _print_json(payload)
    return 0
```

- [ ] **Step 3: Run CLI tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_session.py -q
```

Expected: passes.

- [ ] **Step 4: Commit Round 4**

```bash
git add dating_boost/cli.py tests/test_standalone_session.py
git commit -m "feat: add standalone session CLI"
```

---

## Round 5: Model-Owned Draft Planning

### Task 5: Extract Backend Factory And Add Standalone Draft Planner

**Files:**
- Create: `dating_boost/intelligence/backend_factory.py`
- Modify: `dating_boost/cli.py`
- Create: `tests/test_standalone_model_loop.py`
- Modify: `dating_boost/core/standalone_runtime.py`

- [ ] **Step 1: Write backend factory tests**

Create `tests/test_standalone_model_loop.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from dating_boost.intelligence.backend_factory import create_model_backend
from dating_boost.intelligence.backends import BackendCapability, ScriptedBackend


class BackendFactoryTests(unittest.TestCase):
    def test_creates_scripted_backend_from_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            payload_path = Path(temp_dir) / "scripted.json"
            payload_path.write_text(
                json.dumps({"best_reply": "好呀", "safer_reply": "可以", "bolder_reply": "走", "why_this_works": "短"}),
                encoding="utf-8",
            )

            backend = create_model_backend({"type": "scripted", "path": str(payload_path)})

        self.assertIsInstance(backend, ScriptedBackend)
        self.assertIn(BackendCapability.GENERATE_STRUCTURED, backend.capabilities)

    def test_rejects_unknown_backend_type(self):
        with self.assertRaisesRegex(ValueError, "unsupported_model_backend"):
            create_model_backend({"type": "unknown"})
```

Run:

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_model_loop.py::BackendFactoryTests -q
```

Expected: fails because `backend_factory.py` does not exist.

- [ ] **Step 2: Implement backend factory**

Create `dating_boost/intelligence/backend_factory.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dating_boost.intelligence.backends import ModelBackend, OpenAIBackend, ScriptedBackend


def create_model_backend(config: dict[str, Any]) -> ModelBackend:
    backend_type = str(config.get("type") or "scripted")
    if backend_type == "scripted":
        path = config.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("scripted_backend_path_required")
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return ScriptedBackend(payload)
    if backend_type == "openai":
        model = str(config.get("model") or "gpt-4.1-mini")
        return OpenAIBackend(model=model)
    raise ValueError(f"unsupported_model_backend:{backend_type}")
```

Modify `dating_boost/cli.py` `_select_backend(args)` to call `create_model_backend()` instead of constructing backends inline. Keep CLI output shape unchanged.

- [ ] **Step 3: Add standalone draft planner contract**

Append to `dating_boost/core/standalone_runtime.py`:

```python
class StandaloneDraftPlanner:
    def __init__(self, root: Path, *, backend_config: dict[str, Any]):
        self.root = root
        self.backend_config = dict(backend_config)

    def draft_for_match(self, *, match_id: str, mode: str) -> dict[str, Any]:
        from dating_boost.core.draft_evidence import build_draft_evidence
        from dating_boost.core.draft_review_audit import DraftReviewAuditRepository
        from dating_boost.core.draft_generation_audit import DraftGenerationAuditRepository
        from dating_boost.core.repositories import ObservationRepository
        from dating_boost.core.models import ReplyMode
        from dating_boost.intelligence.backend_factory import create_model_backend
        from dating_boost.intelligence.draft_generation import generate_reply_with_refinement
        from dating_boost.policy.draft_review import review_draft

        reply_mode = ReplyMode(mode)
        observation = ObservationRepository(self.root).load_latest_observation(match_id)
        evidence = build_draft_evidence(
            self.root,
            match_id,
            reply_mode=reply_mode,
            observation=observation,
            draft_kind="reply",
            user_reactivated=False,
            now=None,
            app_id=observation.app_id if observation else None,
            runtime=None,
            require_user_profile_source=True,
        )
        if evidence.status != "ok":
            return {"schema_version": 1, "status": "blocked", "reason": evidence.primary_reason, "draft_evidence": evidence.public_dict()}
        generation = generate_reply_with_refinement(
            evidence,
            backend=create_model_backend(self.backend_config),
            audit_root=self.root,
        )
        if generation.status != "ok" or generation.draft_payload is None:
            return {"schema_version": 1, "status": "blocked", "reason": generation.primary_reason, "draft_generation_summary": generation.summary()}
        review = review_draft(
            generation.draft_payload,
            evidence.context_pack,
            mode="autonomous",
            observation=observation,
            planner_recommendation=evidence.planner_recommendation,
        )
        DraftReviewAuditRepository(self.root).append_review(
            review,
            draft_payload=generation.draft_payload,
            context_pack=evidence.context_pack,
            mode="autonomous",
            target_match_id=match_id,
        )
        return {
            "schema_version": 1,
            "status": "ok" if review.allowed_for_autonomous_send else "blocked",
            "reason": None if review.allowed_for_autonomous_send else review.primary_reason,
            "draft": generation.draft_payload,
            "draft_generation_summary": generation.summary(),
            "draft_review": review.public_dict() if hasattr(review, "public_dict") else {"status": review.status},
        }
```

If `DraftReviewDecision` has no `public_dict()` method, keep the existing `_draft_review_public_dict()` in `cli.py` and add a small shared serializer in `dating_boost/policy/draft_review.py` before using it here.

- [ ] **Step 4: Add model loop tests**

Add a test that creates user profile, ingests `tests/fixtures/intelligence/app_observation_chat.json`, configures `ScriptedBackend`, calls `StandaloneDraftPlanner(data_dir, backend_config=config).draft_for_match(match_id=match_id, mode="adaptive")`, and asserts the result returns either `ok` or a policy-specific `blocked` reason. Use the existing scripted fixture and existing strict evidence requirements.

Run:

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_model_loop.py -q
```

Expected: passes.

- [ ] **Step 5: Commit Round 5**

```bash
git add dating_boost/intelligence/backend_factory.py dating_boost/cli.py dating_boost/core/standalone_runtime.py tests/test_standalone_model_loop.py
git commit -m "feat: add standalone model draft planner"
```

---

## Round 6: Stage-Mode Action Execution

### Task 6: Add Stage Executor And Live Wait Point

**Files:**
- Create: `dating_boost/core/standalone_actions.py`
- Modify: `dating_boost/core/standalone_runtime.py`
- Test: `tests/test_standalone_actions.py`

- [ ] **Step 1: Write failing action executor tests**

Create `tests/test_standalone_actions.py`:

```python
import tempfile
import unittest
from pathlib import Path

from dating_boost.core.standalone_actions import StageOnlyActionExecutor


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
        self.assertEqual(result["result_status"], "staged")

    def test_live_without_executor_returns_wait_point(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executor = StageOnlyActionExecutor(Path(temp_dir) / "data", send_mode="live")

            result = executor.execute({"work_item_type": "send_message", "action_request_id": "act_1"}, app_id="tinder")

        self.assertEqual(result["status"], "needs_live_executor")
        self.assertEqual(result["next_host_action"], "enable_managed_gui_send_or_switch_to_stage")
```

Run:

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_actions.py -q
```

Expected: fails because `standalone_actions.py` does not exist.

- [ ] **Step 2: Implement stage executor**

Create `dating_boost/core/standalone_actions.py`:

```python
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol

from dating_boost.core.operator import OperatorRepository


class StandaloneActionExecutor(Protocol):
    def execute(self, work_item: dict[str, Any], *, app_id: str) -> dict[str, Any]:
        raise NotImplementedError


class StageOnlyActionExecutor:
    def __init__(self, root: Path, *, send_mode: str = "stage"):
        self.root = root
        self.send_mode = send_mode

    def execute(self, work_item: dict[str, Any], *, app_id: str) -> dict[str, Any]:
        if self.send_mode == "live":
            return {
                "schema_version": 1,
                "status": "needs_live_executor",
                "action_request_id": work_item.get("action_request_id"),
                "next_host_action": "enable_managed_gui_send_or_switch_to_stage",
            }
        text = str(work_item.get("payload_text") or "")
        payload = {
            "schema_version": 1,
            "action": "send_message",
            "app_id": app_id,
            "action_request_id": work_item.get("action_request_id"),
            "target_match_id": work_item.get("target_match_id") or work_item.get("match_id"),
            "payload_hash": work_item.get("payload_hash") or _sha256(text),
            "result_status": "staged",
            "evidence": {
                "stage_mode": True,
                "draft_text_hash": _sha256(text),
                "live_send_executed": False,
            },
        }
        recorded = OperatorRepository(self.root).record_stage_result(payload)
        return {
            "schema_version": 1,
            "status": "stage_recorded",
            "action_request_id": payload["action_request_id"],
            "result_status": "staged",
            "recorded": recorded,
        }


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
```

- [ ] **Step 3: Wire executor into runtime**

Modify `StandaloneAgentRuntime.__init__`:

```python
def __init__(
    self,
    root: Path,
    *,
    observation_provider: StandaloneObservationProvider,
    action_executor: StandaloneActionExecutor | None = None,
):
    self.root = root
    self.observation_provider = observation_provider
    self.action_executor = action_executor
    self.managed = ManagedSessionRepository(root)
    self.operator = OperatorRepository(root)
```

Modify the `send_message` branch:

```python
if work_type == "send_message":
    if self.action_executor is None:
        return {
            "schema_version": 1,
            "status": "needs_action_executor",
            "work_item_type": work_type,
            "work_item": work_item,
            "next_step": "configure_standalone_action_executor",
        }
    return self.action_executor.execute(work_item, app_id=app_id)
```

- [ ] **Step 4: Run action tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_actions.py tests/test_standalone_runtime.py -q
```

Expected: passes.

- [ ] **Step 5: Commit Round 6**

```bash
git add dating_boost/core/standalone_actions.py dating_boost/core/standalone_runtime.py tests/test_standalone_actions.py tests/test_standalone_runtime.py
git commit -m "feat: add standalone stage executor"
```

---

## Round 7: Daemon Run-Once Integration

### Task 7: Let `dating-boostd run --once` Tick Standalone Session When Active

**Files:**
- Modify: `dating_boost/core/daemon.py`
- Modify: `dating_boost/cli.py`
- Test: `tests/test_daemon_standalone.py`

- [ ] **Step 1: Write failing daemon test**

Create `tests/test_daemon_standalone.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from dating_boost.core.daemon import DaemonRepository
from dating_boost.core.standalone_session import StandaloneSessionRepository


class DaemonStandaloneTests(unittest.TestCase):
    def test_run_once_reports_standalone_session_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            fixture_dir = Path(temp_dir) / "fixtures"
            fixture_dir.mkdir()
            (fixture_dir / "message_list.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "observation_type": "message_list",
                    "app_id": "tinder",
                    "message_list_snapshot": {"entries": []},
                    "scan_cursor": {"current": None, "next": None, "exhausted": True},
                }),
                encoding="utf-8",
            )
            StandaloneSessionRepository(data_dir).start(
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

        self.assertEqual(payload["status"], "stopped")
        self.assertIn("standalone_tick", payload)
```

Run:

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_daemon_standalone.py -q
```

Expected: fails because `DaemonRepository.run()` has no `standalone_tick` argument.

- [ ] **Step 2: Add daemon standalone option**

Modify `DaemonRepository.run` signature:

```python
def run(self, *, once: bool, owner: str, now: str, standalone_tick: bool = False) -> dict[str, Any]:
```

Add helper in `dating_boost/core/daemon.py`:

```python
def _run_standalone_tick(root: Path) -> dict[str, Any] | None:
    from dating_boost.core.standalone_observation import FixtureObservationProvider
    from dating_boost.core.standalone_runtime import StandaloneAgentRuntime
    from dating_boost.core.standalone_session import StandaloneSessionRepository

    status = StandaloneSessionRepository(root).status()
    if status.get("status") != "active":
        return None
    session = status.get("session") if isinstance(status.get("session"), dict) else {}
    source = session.get("observation_source") if isinstance(session.get("observation_source"), dict) else {}
    if source.get("type") != "fixture_dir":
        return {"schema_version": 1, "status": "blocked", "reason": "unsupported_standalone_observation_source"}
    provider = FixtureObservationProvider(Path(str(source.get("path") or "")))
    tick = StandaloneAgentRuntime(root, observation_provider=provider).tick()
    StandaloneSessionRepository(root).record_tick(tick)
    return tick
```

In the `once` branch, before writing `once_completed`, add:

```python
standalone_payload = _run_standalone_tick(self.root) if standalone_tick else None
```

Include it in the return payload:

```python
"standalone_tick": standalone_payload,
```

Modify CLI daemon run parser:

```python
daemon_run_parser.add_argument("--standalone-tick", action="store_true")
```

Modify `_handle_daemon_run`:

```python
payload = DaemonRepository(args.data_dir).run(
    once=bool(args.once),
    owner=args.owner,
    now=_now_iso(),
    standalone_tick=bool(args.standalone_tick),
)
```

- [ ] **Step 3: Run daemon standalone tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_daemon_standalone.py tests/test_standalone_session.py -q
```

Expected: passes.

- [ ] **Step 4: Commit Round 7**

```bash
git add dating_boost/core/daemon.py dating_boost/cli.py tests/test_daemon_standalone.py
git commit -m "feat: tick standalone sessions from daemon"
```

---

## Round 8: Managed Live Send Port Extraction

### Task 8: Make Managed Send Runner Host-Port Based

**Files:**
- Modify: `dating_boost/core/managed_gui_send.py`
- Modify: `dating_boost/host_loop.py`
- Create: `tests/test_standalone_live_send_port.py`

- [ ] **Step 1: Write port conformance test**

Create `tests/test_standalone_live_send_port.py`:

```python
import unittest

from dating_boost.core.managed_gui_send import ManagedGuiSendHostPort


class ManagedGuiSendPortTests(unittest.TestCase):
    def test_protocol_declares_required_methods(self):
        required = {
            "_finish",
            "_runtime_live_send_block_reason",
            "_target_profile_block_reason",
            "_authorization_path",
            "_live_send_action_request",
            "_run_cli_json",
            "_append_timeline",
            "_work_file",
            "_clear_host_work_item",
        }

        protocol_attrs = set(ManagedGuiSendHostPort.__annotations__)

        self.assertTrue(required.issubset(protocol_attrs))
```

Run:

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_live_send_port.py -q
```

Expected: fails because `ManagedGuiSendHostPort` does not exist.

- [ ] **Step 2: Add typed host port**

Modify `dating_boost/core/managed_gui_send.py`:

```python
from typing import Protocol


class ManagedGuiSendHostPort(Protocol):
    args: Any
    data_dir: Path
    work_dir: Path
    action_results_recorded: list[dict[str, Any]]

    _finish: Any
    _runtime_live_send_block_reason: Any
    _target_profile_block_reason: Any
    _authorization_path: Any
    _live_send_action_request: Any
    _run_cli_json: Any
    _append_timeline: Any
    _work_file: Any
    _clear_host_work_item: Any
```

Change `ManagedGuiSendRunner.__init__` to:

```python
def __init__(self, host: ManagedGuiSendHostPort):
    self.host = host
```

Keep host-loop behavior unchanged.

- [ ] **Step 3: Add standalone live send blocked port**

Add a minimal port in `dating_boost/core/standalone_actions.py` that returns blocked until a complete standalone GUI port is implemented:

```python
class StandaloneManagedGuiSendExecutor:
    def __init__(self, root: Path):
        self.root = root

    def execute(self, work_item: dict[str, Any], *, app_id: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": "blocked",
            "reason": "standalone_live_gui_send_not_enabled",
            "action_request_id": work_item.get("action_request_id"),
            "app_id": app_id,
            "next_host_action": "use_host_loop_live_send_or_stage_mode",
        }
```

This preserves the current safety boundary while preparing the port extraction.

- [ ] **Step 4: Run port tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_live_send_port.py tests/test_standalone_actions.py tests/test_operator_host_loop.py -q
```

Expected: passes.

- [ ] **Step 5: Commit Round 8**

```bash
git add dating_boost/core/managed_gui_send.py dating_boost/host_loop.py dating_boost/core/standalone_actions.py tests/test_standalone_live_send_port.py tests/test_standalone_actions.py
git commit -m "refactor: define managed send host port"
```

---

## Round 9: Documentation And Startup Contracts

### Task 9: Document Standalone As Opt-In Runtime

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/README.md`
- Modify: `tests/test_public_production.py`
- Modify: `tests/test_agent_native_launch_docs.py`

- [ ] **Step 1: Add docs assertions**

Add assertions to existing docs tests:

```python
def test_docs_describe_standalone_as_opt_in(self):
    readme = Path("README.md").read_text(encoding="utf-8")
    agents = Path("AGENTS.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")

    self.assertIn("standalone-session", readme)
    self.assertIn("host-native remains the default", agents)
    self.assertIn("Standalone Agent Runtime", architecture)
```

Run:

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_public_production.py tests/test_agent_native_launch_docs.py -q
```

Expected: fails until docs are updated.

- [ ] **Step 2: Update README**

Add a short section after `全对象托管`:

```markdown
## Standalone Agent Runtime

`standalone-session` is the opt-in migration path from host-native workflows to a local Dating Booster agent. Host-native remains the default production route. The first standalone mode consumes the same managed-session/operator contracts with fixture or manual observations; live GUI send remains disabled unless the existing authorization, target binding, staged-text verification, and post-action verification contracts are satisfied.

Example fixture start:

```bash
dating-boost standalone-session start --data-dir .local/dating-boost --app-id tinder --send-mode stage --observation-fixture-dir tests/fixtures/standalone --backend scripted --scripted-backend-output tests/fixtures/intelligence/scripted_reply.json --json
dating-boost standalone-session tick --data-dir .local/dating-boost --json
dating-boost standalone-session status --data-dir .local/dating-boost --json
```
```

- [ ] **Step 3: Update AGENTS.md**

Add under `Managed session`:

```markdown
## Standalone session

Host-native remains the default route for Codex, Claude Code, OpenClaw, and Hermes. Use `standalone-session` only when the user explicitly asks to run Dating Booster's local standalone agent runtime.

Initial standalone mode is fixture/manual-first:

```bash
dating-boost standalone-session start --data-dir .local/dating-boost --app-id tinder --send-mode stage --observation-fixture-dir tests/fixtures/standalone --backend scripted --scripted-backend-output tests/fixtures/intelligence/scripted_reply.json --json
dating-boost standalone-session tick --data-dir .local/dating-boost --json
dating-boost standalone-session stop --data-dir .local/dating-boost --json
```

Do not use standalone mode to bypass host-loop live-send rules. Live send still requires the same operator-generated action request, user authorization, runtime scope, target binding, exact staged-text verification, and post-action evidence.
```

- [ ] **Step 4: Update architecture docs**

Add a `Standalone Agent Runtime` subsection to `docs/ARCHITECTURE.md`:

```markdown
## Standalone Agent Runtime

The standalone runtime is a new consumer of existing managed-session and operator contracts. It does not fork policy, planner, memory, app adapter, runtime scope, or managed-send rules.

Migration order:

1. fixture/manual observations.
2. local `ModelBackend` draft planning.
3. daemon-supervised run-once ticks.
4. live GUI staging and send only through existing verification contracts.
```

- [ ] **Step 5: Update project map**

Add to `docs/README.md` runtime surfaces:

```markdown
- Standalone session: `dating-boost standalone-session` consumes managed-session/operator work without a host agent, starting with fixture/manual observations and stage mode.
```

- [ ] **Step 6: Run docs tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_public_production.py tests/test_agent_native_launch_docs.py -q
```

Expected: passes.

- [ ] **Step 7: Commit Round 9**

```bash
git add README.md AGENTS.md docs/ARCHITECTURE.md docs/README.md tests/test_public_production.py tests/test_agent_native_launch_docs.py
git commit -m "docs: document standalone runtime migration"
```

---

## Round 10: Final Verification

### Task 10: Run Focused And Full Regression

**Files:**
- No new files.

- [ ] **Step 1: Run standalone focused suite**

```bash
PYTHONPATH=. uv run --extra test pytest \
  tests/test_standalone_session.py \
  tests/test_standalone_runtime.py \
  tests/test_standalone_model_loop.py \
  tests/test_standalone_actions.py \
  tests/test_daemon_standalone.py \
  tests/test_standalone_live_send_port.py \
  -q
```

Expected:

```text
passed
```

- [ ] **Step 2: Run host-native regression slices**

```bash
PYTHONPATH=. uv run --extra test pytest \
  tests/test_managed_session.py \
  tests/test_operator_host_loop.py \
  tests/test_automation_session.py \
  tests/test_production_reliability.py \
  tests/test_agent_native_launch_docs.py \
  -q
```

Expected:

```text
passed
```

- [ ] **Step 3: Run complete regression**

```bash
PYTHONPATH=. uv run --extra test pytest -q
```

Expected:

```text
passed
```

- [ ] **Step 4: Verify capabilities**

```bash
python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost
```

Expected JSON fields:

```json
{
  "agent_native_capabilities": {
    "standalone_agent_runtime": true,
    "standalone_agent_default_mode": "fixture_or_manual_first",
    "standalone_agent_live_gui_default": false,
    "standalone_agent_uses_existing_operator_contract": true
  }
}
```

- [ ] **Step 5: Commit final adjustments**

```bash
git add dating_boost tests README.md AGENTS.md docs
git commit -m "test: verify standalone runtime migration"
```

## Execution Notes

Implementation order is strict:

1. Repair the current red baseline first.
2. Add fixture/manual standalone runtime before model-backed drafting.
3. Add model-backed drafting before daemon run-once integration.
4. Add daemon run-once before live GUI execution.
5. Keep live send blocked in standalone until the managed-send port has parity with host-loop.

The first shippable standalone milestone is:

```text
standalone-session start
-> standalone-session tick
-> consumes fixture/manual message-list and thread observations
-> builds/uses existing memory and operator state
-> produces stage-mode or wait-point results
-> records auditable events
```

That milestone is useful because it proves the independent agent loop without touching the riskiest part of the system: real GUI send.

## Self-Review

- Spec coverage: the plan covers daemon ownership, model backend ownership, observation ownership, action execution, confirmation boundaries, docs, and tests.
- Boundary check: no task permits private APIs, direct service automation, anti-detection behavior, bulk operations, automatic likes, contact exchange, appointment commitment, or direct handcrafted action requests.
- Type consistency: `StandaloneSessionRepository`, `StandaloneAgentRuntime`, `FixtureObservationProvider`, `StageOnlyActionExecutor`, and `create_model_backend` are consistently named across tasks.
- Current-state consistency: the plan treats existing `managed-session`, `operator`, `host-loop`, `ModelBackend`, and `managed_gui_send` as reusable contracts rather than obsolete code.
