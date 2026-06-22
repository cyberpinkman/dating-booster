# TaShuo mac-ios-app Standalone Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TaShuo (`app_id=tashuo`, `runtime=mac-ios-app`) the primary standalone Dating Booster path by shipping a stage-first closed loop: prepare message page, perceive visible rows, open a thread, read visible conversation context, generate a policy-checked draft, and stage it in the real TaShuo Mac iOS app.

**Architecture:** Reuse existing managed-session, operator, memory, draft, policy, runtime-scope, and TaShuo harness contracts. Add only the missing standalone pieces: live GUI source selection, TaShuo vision perception, target cache, provider factory, real stage executor, and a bounded smoke script.

**Tech Stack:** Python 3.11+, existing CLI in `dating_boost/cli.py`, `StandaloneSessionRepository`, `StandaloneAgentRuntime`, `ManagedSessionRepository`, `OperatorRepository`, TaShuo adapter in `dating_boost/apps/tashuo/`, existing `ModelBackend` plus a new vision-structured backend, pytest, macOS Accessibility/ScreenCapture through the existing harness layer.

---

## Scope Decision

The product decision is TaShuo-first, stage-first, phone-free.

This plan is intentionally narrower than the first draft. It does not try to solve standalone live send, Tinder/Bumble/WeChat expansion, or global background automation. Those are separate follow-up plans after the TaShuo stage loop proves real utility.

First releasable internal loop:

```text
runtime select tashuo/mac-ios-app
  -> standalone-session start --observation-source live-gui --send-mode stage
  -> prepare-message-page
  -> observe screenshot
  -> VLM/vision parser extracts visible chat rows and tap targets
  -> operator selects work item
  -> provider opens the selected thread using cached visual target
  -> VLM/vision parser extracts visible messages and identity evidence
  -> existing memory/context/draft/policy path produces send_message work item
  -> standalone stage executor calls real TaShuo stage_draft
  -> exact staged-text verification is recorded
```

## What Already Exists

- `dating_boost/apps/tashuo/adapter.py` exposes `launch`, `observe`, `run_action`, `run_workflow`, `stage_draft`, and `send_message`.
- `dating_boost/apps/tashuo/native.py` already supports `prepare-message-page`, `open-conversation`, and mac-ios-app `stage_draft`.
- `dating_boost/core/standalone_session.py` persists standalone session state.
- `dating_boost/core/standalone_runtime.py` consumes managed-session/operator work items through an observation provider and action executor.
- `dating_boost/core/standalone_actions.py` has stage-result recording and keeps standalone live send blocked by default.
- `dating_boost/core/operator.py` already emits `scan_message_list`, `open_thread`, `observe_current_thread`, and `send_message`; there is no need to invent a new draft work item for this milestone.
- `dating_boost/intelligence/backend_factory.py` already creates scripted and OpenAI text backends for draft generation.
- `scripts/tashuo_mac_ios_managed_smoke.py` already proves the managed TaShuo mac-ios-app path can be smoke-tested without sending.

## NOT In Scope

- Standalone live send bridge. Keep `StandaloneManagedGuiSendExecutor` blocked in this plan.
- Cross-app standalone runtime contract for Tinder, Bumble, or WeChat.
- Question-gate staging or sending.
- Recommendation likes, passes, screen-tap chat starts, payments, profile edits, unmatch, report, call, or contact exchange.
- Global background listener or always-on daemon behavior.
- OCR-first fallback for TaShuo message list navigation.

## Release Criteria

This plan is complete only when all of the following are true:

- `capabilities` reports TaShuo mac-ios-app as the standalone primary app/runtime.
- `standalone-session start` works for TaShuo mac-ios-app without `--observation-fixture-dir`.
- `standalone-session tick` can run with a live GUI provider through the provider factory.
- Message-list perception extracts at least one candidate row from a screenshot fixture with `candidate_key`, `tap_ratio`, `visible_name` or explicit unknown-name evidence, `latest_preview`, and `visual_anchor_hash`.
- Thread perception extracts visible message turns and current-thread visual identity from a screenshot fixture.
- Provider opens a thread using cached visual target data, not a fixed row number and not only header OCR.
- A full fixture-backed runtime test reaches `stage_recorded` through the existing operator `send_message` work item.
- Real stage mode calls TaShuo `stage_draft` and records exact staged-text evidence.
- Live send remains blocked by default.
- A local smoke script exercises TaShuo standalone stage mode and reports clear blocked/no-work reasons instead of fake success.

`visual_message_list_planning_required` is acceptable as a diagnostic status during development. It is not acceptable as a release condition for the main TaShuo standalone loop.

## File Structure

Create:

- `dating_boost/intelligence/vision_backends.py`
  Structured image-analysis backend protocol, scripted test backend, and OpenAI-backed implementation.

- `dating_boost/intelligence/vision_backend_factory.py`
  Builds scripted or OpenAI vision backends from standalone session config.

- `dating_boost/apps/tashuo/perception.py`
  TaShuo message-list and conversation screenshot perception schemas plus normalization helpers.

- `dating_boost/apps/tashuo/standalone.py`
  TaShuo standalone provider, target cache, precheck harness wrapper, and stage executor.

- `dating_boost/core/standalone_provider_factory.py`
  Builds observation provider, precheck harness factory, action executor, and draft planner dependencies from persisted standalone session config.

- `scripts/tashuo_mac_ios_standalone_smoke.py`
  Bounded stage-only local smoke wrapper.

- `tests/test_tashuo_perception.py`
  Vision parser and schema tests using scripted vision payloads and screenshot fixture paths.

- `tests/test_tashuo_standalone_provider.py`
  Provider and target-cache tests with fake adapter and scripted vision backend.

- `tests/test_tashuo_standalone_session.py`
  CLI/session/factory tests for `live-gui` source.

- `tests/test_tashuo_standalone_smoke_script.py`
  Smoke script command assembly and cleanup tests.

Modify:

- `dating_boost/cli.py`
  Add `--observation-source {fixture,live-gui}`, `--vision-backend`, `--vision-model`, `--scripted-vision-output`, and `--output-dir`.

- `dating_boost/core/capabilities.py`
  Advertise TaShuo mac-ios-app as standalone primary.

- `dating_boost/core/daemon.py`
  Reconstruct standalone runtime ports through `standalone_provider_factory.py`.

- `dating_boost/core/standalone_session.py`
  Persist `vision_backend` and live GUI output directory.

- `dating_boost/core/standalone_runtime.py`
  Pass action executor and draft planner through the tick path without inventing new operator work item types.

- `README.md`, `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/README.md`
  Make TaShuo mac-ios-app standalone stage mode the primary standalone quick path.

## Data Flow

```text
standalone-session start
  |
  | writes standalone_session/session.json
  v
ManagedSessionRepository.start
  |
  | calls harness_factory(app_id, runtime).observe()
  v
TaShuoStandalonePrecheckHarness.observe
  |
  | prepare-message-page + observe
  v
managed session active or paused with explicit reason

standalone-session tick
  |
  v
StandaloneAgentRuntime.tick
  |
  | managed-session asks for host work
  v
scan_message_list -> TaShuo provider -> perception -> operator.ingest_observation
open_thread      -> target cache -> open-conversation -> perception -> operator.ingest_observation
send_message     -> TaShuo stage executor -> stage_draft -> operator.record_stage_result
```

## Runtime Contracts

Persist live GUI source:

```json
{
  "observation_source": {
    "type": "live_gui",
    "app_id": "tashuo",
    "runtime": "mac-ios-app",
    "output_dir": ".local/dating-boost-standalone-harness"
  },
  "vision_backend": {
    "type": "openai",
    "model": "gpt-4.1-mini"
  }
}
```

Persist fixture source:

```json
{
  "observation_source": {
    "type": "fixture_dir",
    "path": "tests/fixtures/standalone"
  },
  "vision_backend": {
    "type": "scripted",
    "path": "tests/fixtures/standalone/tashuo_vision_script.json"
  }
}
```

Target cache entry:

```json
{
  "candidate_key": "tashuo_visual_7f83a1d2",
  "tap_ratio": {"x": 0.50, "y": 0.42},
  "visible_name": "Ada",
  "latest_preview": "刚刚发来一条消息",
  "visual_anchor_hash": "7f83a1d2",
  "observed_at": "2026-06-21T00:00:00Z"
}
```

Thread observation must include:

```json
{
  "observation_type": "thread",
  "app_id": "tashuo",
  "runtime": "mac-ios-app",
  "candidate_key": "tashuo_visual_7f83a1d2",
  "match_identity_hints": {
    "binding_type": "current_thread_visual_identity",
    "visual_anchor_hash": "thread_anchor_hash",
    "visible_name": "Ada"
  },
  "conversation_observation": {
    "visible_messages": [
      {"direction": "inbound", "text": "你好呀", "confidence": "high"}
    ]
  }
}
```

## Implementation Tasks

### Task 1: Advertise TaShuo standalone primary path

**Files:**

- Modify: `dating_boost/core/capabilities.py`
- Modify: `tests/test_standalone_session.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/README.md`

- [ ] **Step 1: Write the failing capabilities assertions**

Add to `tests/test_standalone_session.py::StandaloneSessionRepositoryTests.test_capabilities_expose_standalone_runtime_contract`:

```python
self.assertTrue(caps["standalone_agent_runtime"])
self.assertEqual(caps["standalone_agent_primary_app"], "tashuo")
self.assertEqual(caps["standalone_agent_primary_runtime"], "mac-ios-app")
self.assertEqual(caps["standalone_agent_default_mode"], "tashuo_mac_ios_app_stage_first")
self.assertTrue(caps["standalone_agent_phone_free_primary_runtime"])
self.assertTrue(caps["standalone_agent_fixture_mode_supported"])
self.assertFalse(caps["standalone_agent_live_gui_default"])
self.assertEqual(caps["standalone_agent_secondary_apps"], ["tinder", "bumble", "wechat"])
```

- [ ] **Step 2: Run the focused failing test**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_session.py::StandaloneSessionRepositoryTests::test_capabilities_expose_standalone_runtime_contract -q
```

Expected:

```text
FAILED
KeyError: 'standalone_agent_primary_app'
```

- [ ] **Step 3: Implement capabilities**

In `dating_boost/core/capabilities.py`, replace the standalone capability block with:

```python
"standalone_agent_runtime": True,
"standalone_agent_primary_app": "tashuo",
"standalone_agent_primary_runtime": "mac-ios-app",
"standalone_agent_default_mode": "tashuo_mac_ios_app_stage_first",
"standalone_agent_phone_free_primary_runtime": True,
"standalone_agent_fixture_mode_supported": True,
"standalone_agent_live_gui_default": False,
"standalone_agent_uses_existing_operator_contract": True,
"standalone_agent_secondary_apps": ["tinder", "bumble", "wechat"],
```

- [ ] **Step 4: Update docs quick path**

Use this TaShuo standalone quick path in `README.md`, `AGENTS.md`, `docs/ARCHITECTURE.md`, and `docs/README.md`:

```bash
dating-boost runtime select --data-dir .local/dating-boost --app-id tashuo --runtime mac-ios-app --json
DATING_BOOST_KEY_PROVIDER=local dating-boost standalone-session start --data-dir .local/dating-boost --authorization auth.json --app-id tashuo --runtime mac-ios-app --send-mode stage --observation-source live-gui --vision-backend openai --backend openai --json
DATING_BOOST_KEY_PROVIDER=local dating-boost standalone-session tick --data-dir .local/dating-boost --json
DATING_BOOST_KEY_PROVIDER=local dating-boost standalone-session status --data-dir .local/dating-boost --json
```

Keep Tinder fixture examples under `Fixture and cross-app development`.

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_session.py tests/test_agent_native_launch_docs.py -q
```

Expected:

```text
passed
```

- [ ] **Step 6: Commit**

```bash
git add dating_boost/core/capabilities.py tests/test_standalone_session.py README.md AGENTS.md docs/ARCHITECTURE.md docs/README.md
git commit -m "docs: make tashuo mac ios standalone the primary path"
```

### Task 2: Add structured vision backend for TaShuo perception

**Files:**

- Create: `dating_boost/intelligence/vision_backends.py`
- Create: `dating_boost/intelligence/vision_backend_factory.py`
- Create: `tests/test_vision_backends.py`

- [ ] **Step 1: Write failing backend tests**

Create `tests/test_vision_backends.py`:

```python
from pathlib import Path
import json
import tempfile
import unittest

from dating_boost.intelligence.vision_backend_factory import create_vision_backend


class VisionBackendFactoryTests(unittest.TestCase):
    def test_scripted_vision_backend_returns_payloads_in_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "vision.json"
            path.write_text(json.dumps([{"status": "ok", "kind": "list"}, {"status": "ok", "kind": "thread"}]), encoding="utf-8")
            backend = create_vision_backend({"type": "scripted", "path": str(path)})
            first = backend.analyze_image_structured("system", "user", Path("screen1.png"), {"type": "object"})
            second = backend.analyze_image_structured("system", "user", Path("screen2.png"), {"type": "object"})
        self.assertEqual(first["kind"], "list")
        self.assertEqual(second["kind"], "thread")

    def test_scripted_vision_backend_requires_path(self):
        with self.assertRaises(ValueError) as raised:
            create_vision_backend({"type": "scripted"})
        self.assertEqual(str(raised.exception), "scripted_vision_backend_path_required")
```

- [ ] **Step 2: Run failing tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_vision_backends.py -q
```

Expected:

```text
FAILED
ModuleNotFoundError: No module named 'dating_boost.intelligence.vision_backend_factory'
```

- [ ] **Step 3: Implement `vision_backends.py`**

Create `dating_boost/intelligence/vision_backends.py`:

```python
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Protocol


class VisionBackend(Protocol):
    def analyze_image_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: Path,
        schema: Mapping[str, object],
    ) -> dict[str, Any]:
        raise NotImplementedError


class ScriptedVisionBackend:
    def __init__(self, payload: Mapping[str, object] | list[Mapping[str, object]]):
        self._payloads = [deepcopy(dict(item)) for item in payload] if isinstance(payload, list) else [deepcopy(dict(payload))]
        self._cursor = 0

    def analyze_image_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: Path,
        schema: Mapping[str, object],
    ) -> dict[str, Any]:
        if self._cursor >= len(self._payloads):
            return deepcopy(self._payloads[-1])
        payload = deepcopy(self._payloads[self._cursor])
        self._cursor += 1
        return payload


class OpenAIVisionBackend:
    def __init__(self, model: str = "gpt-4.1-mini"):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAIVisionBackend requires the optional OpenAI SDK. Install with "
                "`pip install 'dating-booster[models]'` or `pip install 'openai>=2,<3'`."
            ) from exc
        self._client = OpenAI()
        self._model = model

    def analyze_image_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: Path,
        schema: Mapping[str, object],
    ) -> dict[str, Any]:
        image_bytes = image_path.read_bytes()
        import base64

        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        response = self._client.responses.create(
            model=self._model,
            input=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_prompt},
                        {"type": "input_image", "image_url": data_url},
                    ],
                },
            ],
            text={"format": {"type": "json_schema", "name": "vision_response", "schema": dict(schema), "strict": True}},
        )
        output_text = getattr(response, "output_text", "")
        if not isinstance(output_text, str) or not output_text.strip():
            raise RuntimeError("OpenAI vision response did not contain output_text.")
        parsed = json.loads(output_text)
        if not isinstance(parsed, dict):
            raise RuntimeError("OpenAI vision response was not a JSON object.")
        return parsed
```

- [ ] **Step 4: Implement `vision_backend_factory.py`**

Create `dating_boost/intelligence/vision_backend_factory.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dating_boost.intelligence.vision_backends import OpenAIVisionBackend, ScriptedVisionBackend, VisionBackend


def create_vision_backend(config: dict[str, Any]) -> VisionBackend:
    backend_type = str(config.get("type") or "scripted")
    if backend_type == "scripted":
        path = config.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("scripted_vision_backend_path_required")
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return ScriptedVisionBackend(payload)
        if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
            return ScriptedVisionBackend(payload)
        raise ValueError("scripted_vision_backend_output_must_be_object_or_array")
    if backend_type == "openai":
        return OpenAIVisionBackend(model=str(config.get("model") or "gpt-4.1-mini"))
    raise ValueError(f"unsupported_vision_backend:{backend_type}")
```

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_vision_backends.py -q
```

Expected:

```text
passed
```

- [ ] **Step 6: Commit**

```bash
git add dating_boost/intelligence/vision_backends.py dating_boost/intelligence/vision_backend_factory.py tests/test_vision_backends.py
git commit -m "feat: add structured vision backend"
```

### Task 3: Add TaShuo screenshot perception schemas

**Files:**

- Create: `dating_boost/apps/tashuo/perception.py`
- Create: `tests/test_tashuo_perception.py`

- [ ] **Step 1: Write failing perception tests**

Create `tests/test_tashuo_perception.py`:

```python
from pathlib import Path
import tempfile
import unittest

from dating_boost.apps.tashuo.perception import (
    analyze_tashuo_conversation,
    analyze_tashuo_message_list,
)
from dating_boost.intelligence.vision_backends import ScriptedVisionBackend


class TaShuoPerceptionTests(unittest.TestCase):
    def test_message_list_requires_screen_path(self):
        backend = ScriptedVisionBackend({"status": "ok", "rows": []})
        payload = analyze_tashuo_message_list({"status": "ok", "screen": {}}, backend=backend)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "screen_path_required_for_tashuo_message_list_perception")

    def test_message_list_normalizes_rows_and_candidate_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            backend = ScriptedVisionBackend(
                {
                    "status": "ok",
                    "rows": [
                        {
                            "tap_ratio": {"x": 0.50, "y": 0.42},
                            "visible_name": "Ada",
                            "latest_preview": "刚刚发来一条消息",
                            "visual_anchor_hash": "7f83a1d2",
                            "confidence": "high",
                        }
                    ],
                }
            )
            payload = analyze_tashuo_message_list({"status": "ok", "screen": {"path": str(screen)}}, backend=backend)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["rows"][0]["candidate_key"], "tashuo_visual_7f83a1d2")
        self.assertEqual(payload["rows"][0]["tap_ratio"], {"x": 0.5, "y": 0.42})

    def test_message_list_blocks_without_tap_ratio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            backend = ScriptedVisionBackend({"status": "ok", "rows": [{"visible_name": "Ada", "visual_anchor_hash": "7f83a1d2"}]})
            payload = analyze_tashuo_message_list({"status": "ok", "screen": {"path": str(screen)}}, backend=backend)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "tashuo_message_row_tap_ratio_required")

    def test_conversation_normalizes_visible_messages_and_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "thread.png"
            screen.write_bytes(b"png")
            backend = ScriptedVisionBackend(
                {
                    "status": "ok",
                    "visible_name": "Ada",
                    "visual_anchor_hash": "threadhash",
                    "visible_messages": [{"direction": "inbound", "text": "你好呀", "confidence": "high"}],
                }
            )
            payload = analyze_tashuo_conversation({"status": "ok", "screen": {"path": str(screen)}}, backend=backend)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["identity"]["visual_anchor_hash"], "threadhash")
        self.assertEqual(payload["visible_messages"][0]["text"], "你好呀")
```

- [ ] **Step 2: Run failing tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_tashuo_perception.py -q
```

Expected:

```text
FAILED
ModuleNotFoundError: No module named 'dating_boost.apps.tashuo.perception'
```

- [ ] **Step 3: Implement TaShuo perception module**

Create `dating_boost/apps/tashuo/perception.py`:

```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from dating_boost.intelligence.vision_backends import VisionBackend


MESSAGE_LIST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "rows"],
    "properties": {
        "status": {"type": "string", "enum": ["ok", "blocked"]},
        "reason": {"type": "string"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["tap_ratio", "visual_anchor_hash", "confidence"],
                "properties": {
                    "tap_ratio": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["x", "y"],
                        "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                    },
                    "visible_name": {"type": "string"},
                    "latest_preview": {"type": "string"},
                    "visual_anchor_hash": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
            },
        },
    },
}

CONVERSATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["status", "visual_anchor_hash", "visible_messages"],
    "properties": {
        "status": {"type": "string", "enum": ["ok", "blocked"]},
        "reason": {"type": "string"},
        "visible_name": {"type": "string"},
        "visual_anchor_hash": {"type": "string"},
        "visible_messages": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["direction", "text", "confidence"],
                "properties": {
                    "direction": {"type": "string", "enum": ["inbound", "outbound", "system", "unknown"]},
                    "text": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
            },
        },
    },
}


def analyze_tashuo_message_list(observation: dict[str, Any], *, backend: VisionBackend) -> dict[str, Any]:
    screen_path = _screen_path(observation)
    if screen_path is None:
        return _blocked("screen_path_required_for_tashuo_message_list_perception")
    result = backend.analyze_image_structured(
        "Analyze the TaShuo message list screenshot. Return only visible chat rows with precise tap ratios.",
        "Extract candidate rows. Do not infer hidden rows. If no clear row exists, return an empty rows array.",
        screen_path,
        MESSAGE_LIST_SCHEMA,
    )
    if result.get("status") == "blocked":
        return _blocked(str(result.get("reason") or "tashuo_message_list_perception_blocked"))
    rows: list[dict[str, Any]] = []
    for raw in result.get("rows") if isinstance(result.get("rows"), list) else []:
        row = _normalize_row(raw)
        if row.get("status") == "blocked":
            return row
        rows.append(row)
    if not rows:
        return _blocked("tashuo_message_list_no_visible_rows")
    return {"schema_version": 1, "status": "ok", "rows": rows}


def analyze_tashuo_conversation(observation: dict[str, Any], *, backend: VisionBackend) -> dict[str, Any]:
    screen_path = _screen_path(observation)
    if screen_path is None:
        return _blocked("screen_path_required_for_tashuo_conversation_perception")
    result = backend.analyze_image_structured(
        "Analyze the TaShuo conversation screenshot. Return visible identity evidence and visible messages.",
        "Extract only visible messages. Preserve direction and text. Do not invent missing context.",
        screen_path,
        CONVERSATION_SCHEMA,
    )
    if result.get("status") == "blocked":
        return _blocked(str(result.get("reason") or "tashuo_conversation_perception_blocked"))
    anchor = str(result.get("visual_anchor_hash") or "").strip()
    if not anchor:
        return _blocked("current_thread_visual_identity_not_verified")
    messages = [item for item in result.get("visible_messages", []) if isinstance(item, dict) and str(item.get("text") or "").strip()]
    return {
        "schema_version": 1,
        "status": "ok",
        "identity": {
            "binding_type": "current_thread_visual_identity",
            "visual_anchor_hash": anchor,
            "visible_name": str(result.get("visible_name") or "").strip() or None,
        },
        "visible_messages": messages,
    }


def _normalize_row(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return _blocked("tashuo_message_row_must_be_object")
    tap_ratio = raw.get("tap_ratio")
    if not isinstance(tap_ratio, dict) or "x" not in tap_ratio or "y" not in tap_ratio:
        return _blocked("tashuo_message_row_tap_ratio_required")
    anchor = str(raw.get("visual_anchor_hash") or "").strip()
    if not anchor:
        anchor = _row_hash(raw)
    return {
        "candidate_key": f"tashuo_visual_{anchor}",
        "tap_ratio": {"x": round(float(tap_ratio["x"]), 4), "y": round(float(tap_ratio["y"]), 4)},
        "visible_name": str(raw.get("visible_name") or "").strip() or None,
        "latest_preview": str(raw.get("latest_preview") or "").strip() or None,
        "visual_anchor_hash": anchor,
        "confidence": str(raw.get("confidence") or "medium"),
    }


def _screen_path(observation: dict[str, Any]) -> Path | None:
    screen = observation.get("screen") if isinstance(observation.get("screen"), dict) else {}
    value = screen.get("path")
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value)


def _row_hash(raw: dict[str, Any]) -> str:
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def _blocked(reason: str) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason}
```

- [ ] **Step 4: Run perception tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_tashuo_perception.py -q
```

Expected:

```text
passed
```

- [ ] **Step 5: Commit**

```bash
git add dating_boost/apps/tashuo/perception.py tests/test_tashuo_perception.py
git commit -m "feat: add tashuo vision perception"
```

### Task 4: Add standalone provider factory and live-gui CLI source

**Files:**

- Create: `dating_boost/core/standalone_provider_factory.py`
- Modify: `dating_boost/cli.py`
- Modify: `dating_boost/core/daemon.py`
- Modify: `dating_boost/core/standalone_session.py`
- Test: `tests/test_tashuo_standalone_session.py`

- [ ] **Step 1: Write factory and CLI tests**

Create `tests/test_tashuo_standalone_session.py`:

```python
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import tempfile
import unittest

from dating_boost.cli import main
from dating_boost.core.standalone_provider_factory import build_standalone_runtime_ports


class StandaloneProviderFactoryTests(unittest.TestCase):
    def test_tashuo_live_gui_source_builds_ports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            vision = Path(temp_dir) / "vision.json"
            vision.write_text(json.dumps({"status": "ok", "rows": []}), encoding="utf-8")
            ports = build_standalone_runtime_ports(
                Path(temp_dir) / "data",
                {
                    "app_id": "tashuo",
                    "runtime": "mac-ios-app",
                    "send_mode": "stage",
                    "managed_gui_send": False,
                    "observation_source": {"type": "live_gui", "app_id": "tashuo", "runtime": "mac-ios-app", "output_dir": str(Path(temp_dir) / "harness")},
                    "vision_backend": {"type": "scripted", "path": str(vision)},
                },
            )
        self.assertEqual(ports["status"], "ok")
        self.assertEqual(ports["observation_source_type"], "live_gui")
        self.assertIsNotNone(ports["observation_provider"])
        self.assertIsNotNone(ports["harness_factory"])
        self.assertIsNotNone(ports["action_executor"])

    def test_live_gui_blocks_non_tashuo_runtime(self):
        ports = build_standalone_runtime_ports(
            Path("data"),
            {
                "app_id": "tinder",
                "runtime": "default",
                "send_mode": "stage",
                "managed_gui_send": False,
                "observation_source": {"type": "live_gui", "app_id": "tinder", "runtime": "default"},
                "vision_backend": {"type": "scripted", "path": "missing.json"},
            },
        )
        self.assertEqual(ports["status"], "blocked")
        self.assertEqual(ports["reason"], "unsupported_live_gui_observation_source")


class StandaloneTaShuoCliTests(unittest.TestCase):
    def _run_cli(self, argv):
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = main(argv)
        return code, json.loads(buffer.getvalue())

    def test_cli_blocks_live_gui_without_vision_backend(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth = root / "auth.json"
            auth.write_text('{"schema_version":1,"authorization_id":"auth","app_id":"tashuo","send_mode":"stage"}', encoding="utf-8")
            code, payload = self._run_cli([
                "standalone-session",
                "start",
                "--data-dir",
                str(root / "data"),
                "--authorization",
                str(auth),
                "--app-id",
                "tashuo",
                "--runtime",
                "mac-ios-app",
                "--send-mode",
                "stage",
                "--observation-source",
                "live-gui",
                "--json",
            ])
        self.assertEqual(code, 2)
        self.assertEqual(payload["reason"], "vision_backend_required_for_live_gui_source")
```

- [ ] **Step 2: Run failing tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_tashuo_standalone_session.py -q
```

Expected:

```text
FAILED
ModuleNotFoundError: No module named 'dating_boost.core.standalone_provider_factory'
```

- [ ] **Step 3: Implement provider factory**

Create `dating_boost/core/standalone_provider_factory.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.core.standalone_actions import StageOnlyActionExecutor, StandaloneManagedGuiSendExecutor
from dating_boost.core.standalone_observation import FixtureObservationProvider, fixture_harness_factory
from dating_boost.intelligence.vision_backend_factory import create_vision_backend


def build_standalone_runtime_ports(root: Path, session: dict[str, Any]) -> dict[str, Any]:
    source = session.get("observation_source") if isinstance(session.get("observation_source"), dict) else {}
    source_type = str(source.get("type") or "").strip()
    send_mode = str(session.get("send_mode") or "stage")

    if source_type == "fixture_dir":
        source_path = source.get("path")
        if not isinstance(source_path, str) or not source_path.strip():
            return _blocked("standalone_observation_fixture_dir_required")
        fixture_dir = Path(source_path).expanduser().resolve()
        if not fixture_dir.is_dir():
            return _blocked("observation_fixture_dir_not_found")
        provider = FixtureObservationProvider(fixture_dir)
        return {
            "schema_version": 1,
            "status": "ok",
            "observation_source_type": "fixture_dir",
            "observation_provider": provider,
            "harness_factory": fixture_harness_factory(provider),
            "action_executor": StageOnlyActionExecutor(root, send_mode=send_mode),
        }

    if source_type == "live_gui":
        app_id = str(source.get("app_id") or session.get("app_id") or "").strip()
        runtime = str(source.get("runtime") or session.get("runtime") or "").strip()
        if app_id != "tashuo" or runtime != "mac-ios-app":
            return _blocked("unsupported_live_gui_observation_source")
        vision_config = session.get("vision_backend") if isinstance(session.get("vision_backend"), dict) else {}
        if not vision_config:
            return _blocked("vision_backend_required_for_live_gui_source")
        from dating_boost.apps.tashuo.standalone import (
            TaShuoMacIosStageExecutor,
            TaShuoMacIosStandaloneObservationProvider,
            TaShuoStandalonePrecheckHarness,
        )

        output_dir = Path(source.get("output_dir") or root / "standalone_harness").expanduser()
        vision_backend = create_vision_backend(dict(vision_config))
        provider = TaShuoMacIosStandaloneObservationProvider(root=root, output_dir=output_dir, vision_backend=vision_backend)

        def _harness_factory(factory_app_id: str, runtime: str | None = None) -> TaShuoStandalonePrecheckHarness:
            return TaShuoStandalonePrecheckHarness(provider, app_id=factory_app_id, runtime=runtime)

        return {
            "schema_version": 1,
            "status": "ok",
            "observation_source_type": "live_gui",
            "observation_provider": provider,
            "harness_factory": _harness_factory,
            "action_executor": StandaloneManagedGuiSendExecutor(root)
            if send_mode == "live"
            else TaShuoMacIosStageExecutor(root=root, output_dir=output_dir),
        }

    return _blocked("unsupported_standalone_observation_source")


def _blocked(reason: str) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason}
```

- [ ] **Step 4: Add CLI args and persist vision config**

In `dating_boost/cli.py`, change the standalone start parser:

```python
standalone_start_parser.add_argument("--observation-source", choices=["fixture", "live-gui"], default="live-gui")
standalone_start_parser.add_argument("--observation-fixture-dir", type=Path)
standalone_start_parser.add_argument("--output-dir", type=Path)
standalone_start_parser.add_argument("--vision-backend", choices=["scripted", "openai"])
standalone_start_parser.add_argument("--vision-model", default="gpt-4.1-mini")
standalone_start_parser.add_argument("--scripted-vision-output", type=Path)
```

In `_handle_standalone_session_start`, build:

```python
vision_backend = {}
if args.observation_source == "live-gui":
    if args.vision_backend is None:
        payload = {"schema_version": 1, "status": "blocked", "reason": "vision_backend_required_for_live_gui_source"}
        _print_json(payload)
        return 2
    if args.vision_backend == "scripted":
        if args.scripted_vision_output is None:
            payload = {"schema_version": 1, "status": "blocked", "reason": "scripted_vision_output_required"}
            _print_json(payload)
            return 2
        vision_backend = {"type": "scripted", "path": str(args.scripted_vision_output.expanduser().resolve())}
    else:
        vision_backend = {"type": "openai", "model": args.vision_model}
```

In `dating_boost/core/standalone_session.py`, extend `StandaloneSessionRepository.start`:

```python
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
    vision_backend: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

Persist it in the session payload:

```python
"vision_backend": dict(vision_backend or {}),
```

Pass `vision_backend=vision_backend` from `_handle_standalone_session_start` into `repository.start(...)`.

- [ ] **Step 5: Refactor CLI tick and daemon tick to use factory**

In `_handle_standalone_session_tick` and `dating_boost/core/daemon.py::_run_standalone_tick`, use:

```python
ports = build_standalone_runtime_ports(args.data_dir, session)
if ports.get("status") != "ok":
    _print_json(ports)
    return 2
payload = StandaloneAgentRuntime(
    args.data_dir,
    observation_provider=ports["observation_provider"],
    harness_factory=ports["harness_factory"],
    action_executor=ports["action_executor"],
).tick()
```

For daemon, return the blocked payload instead of printing it.

- [ ] **Step 6: Run tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_tashuo_standalone_session.py tests/test_daemon_standalone.py tests/test_standalone_session.py -q
```

Expected:

```text
passed
```

- [ ] **Step 7: Commit**

```bash
git add dating_boost/core/standalone_provider_factory.py dating_boost/cli.py dating_boost/core/daemon.py dating_boost/core/standalone_session.py tests/test_tashuo_standalone_session.py
git commit -m "feat: support tashuo standalone live gui source"
```

### Task 5: Implement TaShuo standalone provider and target cache

**Files:**

- Create: `dating_boost/apps/tashuo/standalone.py`
- Test: `tests/test_tashuo_standalone_provider.py`

- [ ] **Step 1: Write provider tests**

Create `tests/test_tashuo_standalone_provider.py`:

```python
from pathlib import Path
import tempfile
import unittest

from dating_boost.apps.tashuo.standalone import TaShuoMacIosStandaloneObservationProvider, TaShuoStandaloneTargetCache
from dating_boost.intelligence.vision_backends import ScriptedVisionBackend


class FakeTaShuoAdapter:
    def __init__(self, screen_path: str):
        self.screen_path = screen_path
        self.calls = []

    def run_action(self, action, *, dry_run=False, output_dir=None, **options):
        self.calls.append(("run_action", action, options))
        return {"schema_version": 1, "status": "ok", "screen_state": "tashuo_chat_list"}

    def observe(self, *, output_dir=None):
        self.calls.append(("observe", None, {}))
        return {"schema_version": 1, "status": "ok", "screen_state": "tashuo_chat_list", "screen": {"path": self.screen_path}}

    def stage_draft(self, draft_text, *, dry_run=False, output_dir=None):
        self.calls.append(("stage_draft", draft_text, {}))
        return {"schema_version": 1, "status": "ok", "stage_attempt_status": "completed", "staged_text_verified": True}


class TaShuoStandaloneProviderTests(unittest.TestCase):
    def test_message_list_observation_caches_visual_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            adapter = FakeTaShuoAdapter(str(screen))
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=Path(temp_dir) / "data",
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend({"status": "ok", "rows": [{"tap_ratio": {"x": 0.5, "y": 0.42}, "visible_name": "Ada", "latest_preview": "你好", "visual_anchor_hash": "7f83a1d2", "confidence": "high"}]}),
                adapter_factory=lambda: adapter,
            )
            payload = provider.observe_message_list(app_id="tashuo", scan_cursor={})
            cached = TaShuoStandaloneTargetCache(Path(temp_dir) / "data").get("tashuo_visual_7f83a1d2")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["candidates"][0]["tap_ratio"], {"x": 0.5, "y": 0.42})
        self.assertEqual(cached["visible_name"], "Ada")

    def test_observe_thread_uses_cached_tap_ratio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "thread.png"
            screen.write_bytes(b"png")
            data_dir = Path(temp_dir) / "data"
            TaShuoStandaloneTargetCache(data_dir).put({"candidate_key": "tashuo_visual_7f83a1d2", "tap_ratio": {"x": 0.5, "y": 0.42}, "visible_name": "Ada", "latest_preview": "你好", "visual_anchor_hash": "7f83a1d2"})
            adapter = FakeTaShuoAdapter(str(screen))
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=data_dir,
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend({"status": "ok", "visible_name": "Ada", "visual_anchor_hash": "threadhash", "visible_messages": [{"direction": "inbound", "text": "你好呀", "confidence": "high"}]}),
                adapter_factory=lambda: adapter,
            )
            payload = provider.observe_thread(app_id="tashuo", candidate_key="tashuo_visual_7f83a1d2")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(adapter.calls[0][0], "run_action")
        self.assertEqual(adapter.calls[0][2]["tap_ratio"], {"x": 0.5, "y": 0.42})
        self.assertEqual(payload["conversation_observation"]["visible_messages"][0]["text"], "你好呀")

    def test_observe_thread_blocks_without_cached_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=Path(temp_dir) / "data",
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend({"status": "ok", "visible_messages": [], "visual_anchor_hash": "hash"}),
                adapter_factory=lambda: FakeTaShuoAdapter(str(Path(temp_dir) / "screen.png")),
            )
            payload = provider.observe_thread(app_id="tashuo", candidate_key="missing")
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "tashuo_standalone_target_not_found")
```

- [ ] **Step 2: Run failing provider tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_tashuo_standalone_provider.py -q
```

Expected:

```text
FAILED
ModuleNotFoundError: No module named 'dating_boost.apps.tashuo.standalone'
```

- [ ] **Step 3: Implement `standalone.py`**

Create `dating_boost/apps/tashuo/standalone.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dating_boost.apps.registry import create_adapter
from dating_boost.apps.tashuo.perception import analyze_tashuo_conversation, analyze_tashuo_message_list
from dating_boost.core.standalone_actions import StageOnlyActionExecutor
from dating_boost.core.storage import JsonStorage
from dating_boost.intelligence.vision_backends import VisionBackend


TARGET_CACHE_PATH = Path("standalone_session") / "tashuo_targets.json"


class TaShuoStandaloneTargetCache:
    def __init__(self, root: Path):
        self._storage = JsonStorage(root)

    def put(self, target: dict[str, Any]) -> None:
        current = self._read()
        candidate_key = str(target.get("candidate_key") or "").strip()
        if not candidate_key:
            raise ValueError("candidate_key_required")
        current[candidate_key] = {**target, "observed_at": _now_iso()}
        self._storage.write_json(TARGET_CACHE_PATH, {"schema_version": 1, "targets": current})

    def get(self, candidate_key: str) -> dict[str, Any] | None:
        return self._read().get(candidate_key)

    def _read(self) -> dict[str, Any]:
        try:
            payload = self._storage.read_json(TARGET_CACHE_PATH, expected_schema_version=1)
        except FileNotFoundError:
            return {}
        targets = payload.get("targets") if isinstance(payload.get("targets"), dict) else {}
        return {str(key): value for key, value in targets.items() if isinstance(value, dict)}


class TaShuoMacIosStandaloneObservationProvider:
    def __init__(
        self,
        *,
        root: Path,
        output_dir: Path,
        vision_backend: VisionBackend,
        adapter_factory: Callable[[], Any] | None = None,
    ):
        self.root = root
        self.output_dir = output_dir
        self.vision_backend = vision_backend
        self.adapter_factory = adapter_factory or (lambda: create_adapter("tashuo", runtime="mac-ios-app"))
        self.targets = TaShuoStandaloneTargetCache(root)

    def precheck_payload(self, *, app_id: str) -> dict[str, Any]:
        if app_id != "tashuo":
            return _blocked("unsupported_app_for_tashuo_provider", app_id=app_id)
        adapter = self.adapter_factory()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        prepared = adapter.run_action("prepare-message-page", dry_run=False, output_dir=self.output_dir)
        if prepared.get("status") != "ok":
            return _blocked(str(prepared.get("reason") or "prepare_message_page_failed"), app_id=app_id)
        observed = adapter.observe(output_dir=self.output_dir)
        return observed if observed.get("status") == "ok" else _blocked(str(observed.get("reason") or "observe_failed"), app_id=app_id)

    def observe_message_list(self, *, app_id: str, scan_cursor: dict[str, Any]) -> dict[str, Any]:
        if app_id != "tashuo":
            return _blocked("unsupported_app_for_tashuo_provider", app_id=app_id, observation_type="message_list")
        precheck = self.precheck_payload(app_id=app_id)
        if precheck.get("status") != "ok":
            return {**precheck, "observation_type": "message_list"}
        perceived = analyze_tashuo_message_list(precheck, backend=self.vision_backend)
        if perceived.get("status") != "ok":
            return {**perceived, "observation_type": "message_list", "app_id": app_id, "runtime": "mac-ios-app"}
        candidates = []
        for row in perceived["rows"]:
            self.targets.put(row)
            candidates.append(row)
        return {
            "schema_version": 1,
            "status": "ok",
            "observation_type": "message_list",
            "app_id": app_id,
            "runtime": "mac-ios-app",
            "scan_cursor": dict(scan_cursor),
            "candidates": candidates,
            "provenance": {"app_id": app_id, "runtime": "mac-ios-app", "source": "standalone_live_gui"},
        }

    def observe_thread(self, *, app_id: str, candidate_key: str) -> dict[str, Any]:
        target = self.targets.get(candidate_key)
        if target is None:
            return _blocked("tashuo_standalone_target_not_found", app_id=app_id, observation_type="thread", candidate_key=candidate_key)
        adapter = self.adapter_factory()
        opened = adapter.run_action(
            "open-conversation",
            dry_run=False,
            output_dir=self.output_dir,
            tap_ratio=target["tap_ratio"],
            visual_target_label=target.get("visible_name"),
            visual_target_preview=target.get("latest_preview"),
        )
        if opened.get("status") != "ok":
            return _blocked(str(opened.get("reason") or "open_thread_failed"), app_id=app_id, observation_type="thread", candidate_key=candidate_key)
        return self.observe_current_thread(app_id=app_id, candidate_key=candidate_key, cached_target=target)

    def observe_current_thread(
        self,
        *,
        app_id: str,
        candidate_key: str = "current_thread",
        cached_target: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        adapter = self.adapter_factory()
        observed = adapter.observe(output_dir=self.output_dir)
        if observed.get("status") != "ok":
            return _blocked(str(observed.get("reason") or "observe_thread_failed"), app_id=app_id, observation_type="thread", candidate_key=candidate_key)
        perceived = analyze_tashuo_conversation(observed, backend=self.vision_backend)
        if perceived.get("status") != "ok":
            return {**perceived, "observation_type": "thread", "app_id": app_id, "runtime": "mac-ios-app", "candidate_key": candidate_key}
        identity = dict(perceived["identity"])
        if cached_target and cached_target.get("visible_name") and not identity.get("visible_name"):
            identity["visible_name"] = cached_target.get("visible_name")
        return {
            "schema_version": 1,
            "status": "ok",
            "observation_type": "thread",
            "app_id": app_id,
            "runtime": "mac-ios-app",
            "candidate_key": candidate_key,
            "match_identity_hints": identity,
            "conversation_observation": {"visible_messages": perceived["visible_messages"]},
            "provenance": {"app_id": app_id, "runtime": "mac-ios-app", "source": "standalone_live_gui"},
        }


class TaShuoStandalonePrecheckHarness:
    def __init__(self, provider: TaShuoMacIosStandaloneObservationProvider, *, app_id: str, runtime: str | None):
        self.provider = provider
        self.app_id = app_id
        self.runtime = runtime

    def observe(self) -> dict[str, Any]:
        payload = self.provider.precheck_payload(app_id=self.app_id)
        payload["runtime"] = self.runtime
        return payload


class TaShuoMacIosStageExecutor(StageOnlyActionExecutor):
    def __init__(self, *, root: Path, output_dir: Path, adapter_factory: Callable[[], Any] | None = None):
        super().__init__(root, send_mode="stage")
        self.output_dir = output_dir
        self.adapter_factory = adapter_factory or (lambda: create_adapter("tashuo", runtime="mac-ios-app"))

    def execute(self, work_item: dict[str, Any], *, app_id: str) -> dict[str, Any]:
        text = str(work_item.get("payload_text") or "")
        adapter = self.adapter_factory()
        staged = adapter.stage_draft(text, dry_run=False, output_dir=self.output_dir)
        if staged.get("status") != "ok":
            return {"schema_version": 1, "status": "blocked", "reason": str(staged.get("reason") or "tashuo_stage_draft_failed"), "action_request_id": work_item.get("action_request_id")}
        if not (staged.get("staged_text_verified") is True or staged.get("stage_attempt_status") == "completed"):
            return {"schema_version": 1, "status": "blocked", "reason": "exact_staged_text_not_verified", "action_request_id": work_item.get("action_request_id")}
        result = super().execute(work_item, app_id=app_id)
        result["gui_stage"] = {key: value for key, value in staged.items() if key in {"schema_version", "status", "stage_attempt_status", "staged_text_verified", "staged_text_verification"}}
        return result


def _blocked(reason: str, *, app_id: str, **extra: Any) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason, "app_id": app_id, "runtime": "mac-ios-app", **extra}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
```

- [ ] **Step 4: Run provider tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_tashuo_standalone_provider.py tests/test_tashuo_perception.py -q
```

Expected:

```text
passed
```

- [ ] **Step 5: Commit**

```bash
git add dating_boost/apps/tashuo/standalone.py tests/test_tashuo_standalone_provider.py
git commit -m "feat: add tashuo standalone provider"
```

### Task 6: Prove full standalone operator-to-stage loop

**Files:**

- Modify: `dating_boost/core/standalone_runtime.py`
- Modify: `dating_boost/cli.py`
- Test: `tests/test_standalone_runtime.py`
- Test: `tests/test_standalone_model_loop.py`

- [ ] **Step 1: Add an end-to-end runtime test**

Add a test to `tests/test_standalone_runtime.py` that starts an operator/managed session, uses a scripted provider returning one message-list row and one thread observation, uses existing scripted draft backend, ticks until a `send_message` work item appears, and asserts `StageOnlyActionExecutor` records `stage_recorded`.

Use these key assertions:

```python
self.assertEqual(final_tick["status"], "stage_recorded")
self.assertEqual(final_tick["action_request_id"], send_work_item["action_request_id"])
self.assertEqual(final_tick["result_status"], "succeeded")
```

Also assert the runtime never returns:

```python
self.assertNotEqual(final_tick.get("reason"), "operator_draft_work_item_not_available")
self.assertNotEqual(final_tick.get("status"), "needs_operator_draft_work_item")
```

- [ ] **Step 2: Run failing runtime tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_runtime.py tests/test_standalone_model_loop.py -q
```

Expected:

```text
FAILED
runtime does not yet continue through send_message to stage_recorded
```

- [ ] **Step 3: Wire existing draft planner without new work item types**

Update `StandaloneAgentRuntime.__init__` to accept `draft_planner: StandaloneDraftPlanner | None = None`.

In `consume_work_item`, keep current work item support:

```python
scan_message_list -> observe_message_list -> operator.ingest_observation
open_thread -> observe_thread -> operator.ingest_observation
observe_current_thread -> observe_current_thread -> operator.ingest_observation
send_message -> action_executor.execute
```

Do not add a `needs_operator_draft_work_item` state. If operator does not emit `send_message`, return the existing operator/managed-session status and include the latest work item for debugging.

- [ ] **Step 4: Pass action executor and draft planner from CLI tick**

In `_handle_standalone_session_tick`, instantiate:

```python
from dating_boost.core.standalone_runtime import StandaloneAgentRuntime, StandaloneDraftPlanner

draft_planner = StandaloneDraftPlanner(args.data_dir, backend_config=session.get("backend") or {})
runtime = StandaloneAgentRuntime(
    args.data_dir,
    observation_provider=ports["observation_provider"],
    harness_factory=ports["harness_factory"],
    action_executor=ports["action_executor"],
    draft_planner=draft_planner,
)
```

If current `StandaloneAgentRuntime` does not need `draft_planner` to make operator emit `send_message`, keep the dependency for future explicit use but assert it is not required for fixture flow.

- [ ] **Step 5: Run runtime tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_standalone_runtime.py tests/test_standalone_model_loop.py tests/test_standalone_actions.py -q
```

Expected:

```text
passed
```

- [ ] **Step 6: Commit**

```bash
git add dating_boost/core/standalone_runtime.py dating_boost/cli.py tests/test_standalone_runtime.py tests/test_standalone_model_loop.py
git commit -m "feat: complete standalone operator stage loop"
```

### Task 7: Add TaShuo standalone smoke script and reporting

**Files:**

- Create: `scripts/tashuo_mac_ios_standalone_smoke.py`
- Create: `tests/test_tashuo_standalone_smoke_script.py`
- Modify: `dating_boost/core/standalone_session.py`
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Write smoke script tests**

Create `tests/test_tashuo_standalone_smoke_script.py` with subprocess mocks that assert command arrays include:

```python
["runtime", "select", "--app-id", "tashuo", "--runtime", "mac-ios-app"]
["standalone-session", "start", "--app-id", "tashuo", "--runtime", "mac-ios-app", "--observation-source", "live-gui", "--send-mode", "stage"]
["standalone-session", "tick"]
["standalone-session", "stop"]
```

Assert the script does not append `--managed-gui-send`.

- [ ] **Step 2: Run failing smoke tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_tashuo_standalone_smoke_script.py -q
```

Expected:

```text
FAILED
FileNotFoundError: scripts/tashuo_mac_ios_standalone_smoke.py
```

- [ ] **Step 3: Implement the smoke script**

Create `scripts/tashuo_mac_ios_standalone_smoke.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / ".local" / "dating-boost-tashuo-standalone-smoke"
DEFAULT_OUTPUT_DIR = ROOT / ".local" / "dating-boost-tashuo-standalone-harness"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded TaShuo mac-ios-app standalone stage smoke.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument("--vision-backend", choices=["scripted", "openai"], default="openai")
    parser.add_argument("--scripted-vision-output", type=Path)
    parser.add_argument("--backend", choices=["scripted", "openai"], default="openai")
    parser.add_argument("--scripted-backend-output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    steps: list[dict[str, object]] = []
    status = "ok"
    reason = "tashuo_standalone_stage_smoke_complete"
    try:
        _run_step(steps, ["runtime", "select", "--data-dir", str(args.data_dir), "--app-id", "tashuo", "--runtime", "mac-ios-app", "--json"])
        start_cmd = [
            "standalone-session",
            "start",
            "--data-dir",
            str(args.data_dir),
            "--authorization",
            str(args.authorization),
            "--app-id",
            "tashuo",
            "--runtime",
            "mac-ios-app",
            "--send-mode",
            "stage",
            "--observation-source",
            "live-gui",
            "--output-dir",
            str(args.output_dir),
            "--vision-backend",
            args.vision_backend,
            "--backend",
            args.backend,
            "--json",
        ]
        if args.scripted_vision_output is not None:
            start_cmd.extend(["--scripted-vision-output", str(args.scripted_vision_output)])
        if args.scripted_backend_output is not None:
            start_cmd.extend(["--scripted-backend-output", str(args.scripted_backend_output)])
        _run_step(steps, start_cmd)
        _run_step(steps, ["standalone-session", "tick", "--data-dir", str(args.data_dir), "--json"])
    except subprocess.CalledProcessError as exc:
        status = "blocked"
        reason = f"command_failed:{exc.returncode}"
    finally:
        try:
            _run_step(steps, ["standalone-session", "stop", "--data-dir", str(args.data_dir), "--reason", "smoke_complete", "--json"])
        except subprocess.CalledProcessError:
            pass

    payload = {"schema_version": 1, "status": status, "reason": reason, "steps": steps}
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else f"{status}: {reason}")
    return 0 if status == "ok" else 2


def _run_step(steps: list[dict[str, object]], dating_boost_args: list[str]) -> None:
    cmd = [sys.executable, "-m", "dating_boost.cli", *dating_boost_args]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=ROOT)
    steps.append({"cmd": dating_boost_args, "returncode": result.returncode})


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add stop/status reporting**

In `StandaloneSessionRepository.stop`, include:

```python
last_tick = session.get("last_tick") if isinstance(session.get("last_tick"), dict) else {}
return _payload(
    "stopped",
    session=session,
    reason=reason,
    last_blocking_reason=last_tick.get("reason"),
    relationship_progress_report=last_tick.get("relationship_progress_report"),
)
```

Keep existing fields already returned by `stop`.

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_tashuo_standalone_smoke_script.py tests/test_standalone_session.py -q
```

Expected:

```text
passed
```

- [ ] **Step 6: Update docs and commit**

Document:

```bash
DATING_BOOST_KEY_PROVIDER=local python3 scripts/tashuo_mac_ios_standalone_smoke.py --authorization auth.json --vision-backend openai --backend openai --json
```

Commit:

```bash
git add scripts/tashuo_mac_ios_standalone_smoke.py tests/test_tashuo_standalone_smoke_script.py dating_boost/core/standalone_session.py README.md AGENTS.md
git commit -m "feat: add tashuo standalone stage smoke"
```

## Verification Matrix

Run focused suites:

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_vision_backends.py tests/test_tashuo_perception.py tests/test_tashuo_standalone_provider.py -q
```

Expected:

```text
passed
```

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_tashuo_standalone_session.py tests/test_standalone_session.py tests/test_standalone_runtime.py tests/test_standalone_actions.py -q
```

Expected:

```text
passed
```

Run regression slices:

```bash
PYTHONPATH=. uv run --extra test pytest tests/test_operator_session.py tests/test_operator_host_loop.py tests/test_gui_harness.py tests/test_app_profiles.py -q
```

Expected:

```text
passed
```

Run full regression:

```bash
PYTHONPATH=. uv run --extra test pytest -q
```

Expected:

```text
passed
```

Run local stage-only smoke:

```bash
DATING_BOOST_KEY_PROVIDER=local python3 scripts/tashuo_mac_ios_standalone_smoke.py --authorization auth.json --vision-backend openai --backend openai --json
```

Expected success when TaShuo is installed, logged in, and a visible chat row exists:

```json
{
  "schema_version": 1,
  "status": "ok",
  "reason": "tashuo_standalone_stage_smoke_complete"
}
```

Expected blocked examples when environment is not ready:

```json
{"status": "blocked", "reason": "command_failed:2"}
```

The smoke must never report success by inventing rows, messages, or staged evidence.

## Follow-Up Plans

Create separate plans after this one lands:

- Standalone managed live send bridge through the existing host-loop managed-send transaction contract.
- WeChat macOS continuation-channel standalone runtime.
- Tinder/Bumble iPhone Mirroring standalone providers.
- TaShuo question-gate observation and draft support without autonomous send.

## Self-Review

Spec coverage:

- TaShuo-first primary route: Task 1.
- Phone-free mac-ios-app path: Tasks 1, 4, 5, and 7.
- No mock/fallback product path: Tasks 2, 3, 5, and release criteria require structured vision and real stage evidence.
- Existing architecture reuse: Tasks 4, 5, and 6 reuse managed-session, operator, provider ports, and stage audit.
- Live send default-off: NOT in scope and `StandaloneManagedGuiSendExecutor` remains blocked.

Placeholder scan:

- No placeholder markers, no empty error-handling instruction, and no fake-success branch.

Type/API consistency:

- `create_adapter` is called only with supported keyword arguments: `runtime`.
- `ManagedGuiSendRunner` is not used in this plan.
- Persisted live GUI source uses `type=live_gui`; CLI input uses `--observation-source live-gui`.
- App id is `tashuo`; runtime CLI string is `mac-ios-app`; app profile normalized key remains `mac_ios_app`.
