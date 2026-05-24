# MVP Intelligence Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 1 MVP vertical slice: fixture/manual observation -> local memory -> context pack -> model-backed draft generation -> content/action policy -> feedback -> offline eval.

**Architecture:** Keep the MVP aligned with the mature blueprint. Use local JSON storage behind repository interfaces, normalized `AppObservation` input, provider-abstracted model backends, structured reply contracts, content policy gates, and CLI workflows that can later move behind `dating-boostd` without changing domain contracts.

**Tech Stack:** Python 3.11+ stdlib dataclasses/enums/json/pathlib/unittest, optional OpenAI Python SDK behind a lazy-loaded backend, existing `argparse` CLI, local fixture JSON/JSONL.

---

## Source Specs

- `docs/superpowers/specs/2026-05-25-product-architecture-blueprint.md`
- `docs/superpowers/specs/2026-05-25-intelligence-layer-design.md`
- `README.md`

## Scope Decisions

- This plan implements Phase 1 only.
- No live iPhone Mirroring harness.
- No screenshot capture.
- No raw GUI actions.
- No MCP server.
- No desktop UI.
- No autonomous high-risk execution.
- The production draft path uses a real `ModelBackend` implementation. Tests use a deterministic `ScriptedBackend` so unit tests do not call a network service.
- The OpenAI backend should follow the Responses API structured-output shape described in the official OpenAI docs. The backend must be lazy-loaded so tests pass without a local API key.

## File Map

- `pyproject.toml`: add optional provider dependency metadata and keep stdlib tests working.
- `dating_boost/policy.py`: remove after moving action policy into package form.
- `dating_boost/policy/__init__.py`: export action, content, and confirmation policy APIs.
- `dating_boost/policy/actions.py`: current action authorization logic.
- `dating_boost/policy/content.py`: draft content policy gate.
- `dating_boost/policy/confirmation.py`: high-risk confirmation contract.
- `dating_boost/core/__init__.py`: core package exports.
- `dating_boost/core/models.py`: dataclasses and enums shared across layers.
- `dating_boost/core/storage.py`: atomic JSON storage, schema version checks, JSONL append.
- `dating_boost/core/repositories.py`: repository interface and JSON implementation.
- `dating_boost/core/identity.py`: match identity resolution for fixture/manual observations.
- `dating_boost/core/context_pack.py`: deterministic context pack builder.
- `dating_boost/core/feedback.py`: feedback event helpers.
- `dating_boost/perception/__init__.py`: perception package exports.
- `dating_boost/perception/taxonomy.py`: page and exception enums.
- `dating_boost/perception/observations.py`: `AppObservation` and nested observation dataclasses.
- `dating_boost/perception/fixture_loader.py`: load fixture/manual observations from JSON.
- `dating_boost/intelligence/__init__.py`: intelligence package exports.
- `dating_boost/intelligence/backends.py`: `ModelBackend`, `ScriptedBackend`, `OpenAIBackend`.
- `dating_boost/intelligence/prompts.py`: prompt builders and JSON schema dictionaries.
- `dating_boost/intelligence/profile_analyzer.py`: profile analysis contract wrapper.
- `dating_boost/intelligence/conversation_summarizer.py`: conversation summary contract wrapper.
- `dating_boost/intelligence/reply_generator.py`: mode-aware draft generation.
- `dating_boost/evals/__init__.py`: eval package exports.
- `dating_boost/evals/rubrics.py`: rubric scoring dataclasses and thresholds.
- `dating_boost/evals/runner.py`: offline eval runner.
- `dating_boost/cli.py`: add fixture/manual MVP commands.
- `tests/test_policy.py`: update imports after policy package move.
- `tests/test_core_models.py`: schema/model tests.
- `tests/test_storage.py`: atomic storage and migration tests.
- `tests/test_observations.py`: normalized observation tests.
- `tests/test_identity.py`: match identity tests.
- `tests/test_context_pack.py`: context priority tests.
- `tests/test_backends.py`: backend abstraction tests.
- `tests/test_reply_generator.py`: draft generation tests.
- `tests/test_content_policy.py`: content policy tests.
- `tests/test_feedback.py`: feedback persistence tests.
- `tests/test_cli_mvp.py`: CLI fixture workflow tests.
- `tests/test_evals.py`: rubric and eval runner tests.
- `tests/fixtures/intelligence/user_profile.json`: seed user profile.
- `tests/fixtures/intelligence/app_observation_chat.json`: seed chat observation.
- `tests/fixtures/intelligence/scripted_reply.json`: deterministic backend output for tests.
- `tests/fixtures/evals/reply_quality_cases.jsonl`: 20 eval cases.

## Task 1: Move Action Policy Into a Package

**Files:**
- Delete: `dating_boost/policy.py`
- Create: `dating_boost/policy/__init__.py`
- Create: `dating_boost/policy/actions.py`
- Modify: `dating_boost/cli.py`
- Modify: `tests/test_policy.py`

- [ ] **Step 1: Write the failing import and behavior tests**

Replace `tests/test_policy.py` with this content:

```python
import unittest
from contextlib import redirect_stdout
from io import StringIO

from dating_boost.cli import main
from dating_boost.policy import Action, authorize_action


class PolicyTests(unittest.TestCase):
    def test_default_mode_allows_assistive_actions(self):
        for action in (
            Action.OBSERVE,
            Action.SUMMARIZE,
            Action.DRAFT_REPLY,
            Action.PASTE_DRAFT,
        ):
            with self.subTest(action=action):
                decision = authorize_action(action)

                self.assertTrue(decision.allowed)
                self.assertFalse(decision.autonomous)

    def test_default_mode_blocks_message_sending(self):
        decision = authorize_action(Action.SEND_MESSAGE)

        self.assertFalse(decision.allowed)
        self.assertIn("human confirmation", decision.reason)
        self.assertIn("high-risk", decision.reason)

    def test_autonomous_switch_allows_high_risk_actions(self):
        decision = authorize_action(Action.SEND_MESSAGE, autonomous=True)

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.autonomous)
        self.assertIn("explicit switch", decision.reason)

    def test_cli_autonomous_switch_allows_message_sending(self):
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(["send_message", "--autonomous"])

        self.assertEqual(exit_code, 0)
        self.assertIn('"allowed": true', output.getvalue())
        self.assertIn('"autonomous": true', output.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify current package shape fails**

Run:

```bash
python3 -m unittest tests/test_policy.py
```

Expected: fail after `dating_boost/policy.py` is removed or before `dating_boost/policy/__init__.py` exists, with an import error for `dating_boost.policy`.

- [ ] **Step 3: Create `dating_boost/policy/actions.py`**

Move the existing action policy logic into this file:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Action(str, Enum):
    OBSERVE = "observe"
    SUMMARIZE = "summarize"
    DRAFT_REPLY = "draft_reply"
    PASTE_DRAFT = "paste_draft"
    SEND_MESSAGE = "send_message"
    LIKE_PROFILE = "like_profile"
    SUPER_LIKE_PROFILE = "super_like_profile"
    UNMATCH = "unmatch"
    REPORT_PROFILE = "report_profile"
    EDIT_PROFILE = "edit_profile"
    PROPOSE_MEETING = "propose_meeting"


ASSISTIVE_ACTIONS = {
    Action.OBSERVE,
    Action.SUMMARIZE,
    Action.DRAFT_REPLY,
    Action.PASTE_DRAFT,
}

HIGH_RISK_ACTIONS = {
    Action.SEND_MESSAGE,
    Action.LIKE_PROFILE,
    Action.SUPER_LIKE_PROFILE,
    Action.UNMATCH,
    Action.REPORT_PROFILE,
    Action.EDIT_PROFILE,
    Action.PROPOSE_MEETING,
}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    action: Action
    reason: str
    autonomous: bool = False


def authorize_action(action: Action, *, autonomous: bool = False) -> Decision:
    if action in ASSISTIVE_ACTIONS:
        return Decision(
            allowed=True,
            action=action,
            reason="assistive action allowed without autonomous mode",
        )

    if action not in HIGH_RISK_ACTIONS:
        return Decision(
            allowed=False,
            action=action,
            reason=f"unknown action: {action.value}",
        )

    if not autonomous:
        return Decision(
            allowed=False,
            action=action,
            reason=(
                f"{action.value} is a high-risk action and requires human confirmation "
                "unless autonomous mode is explicitly enabled"
            ),
        )

    return Decision(
        allowed=True,
        action=action,
        reason="high-risk autonomous action allowed by explicit switch",
        autonomous=True,
    )
```

- [ ] **Step 4: Create `dating_boost/policy/__init__.py`**

```python
from dating_boost.policy.actions import Action, Decision, authorize_action

__all__ = ["Action", "Decision", "authorize_action"]
```

- [ ] **Step 5: Update `dating_boost/cli.py` imports**

Keep this import working:

```python
from dating_boost.policy import Action, authorize_action
```

- [ ] **Step 6: Delete `dating_boost/policy.py`**

Remove the old module file so `dating_boost.policy` resolves to the package.

- [ ] **Step 7: Run tests**

Run:

```bash
python3 -m unittest discover -s tests
python3 -m compileall dating_boost
```

Expected: all existing tests pass and `compileall` exits 0.

- [ ] **Step 8: Commit**

```bash
git add dating_boost/cli.py dating_boost/policy tests/test_policy.py
git rm dating_boost/policy.py
git commit -m "Refactor action policy into package"
```

## Task 2: Define Core Domain Models

**Files:**
- Create: `dating_boost/core/__init__.py`
- Create: `dating_boost/core/models.py`
- Test: `tests/test_core_models.py`

- [ ] **Step 1: Write failing tests for enums and dataclass serialization**

Create `tests/test_core_models.py`:

```python
import unittest

from dating_boost.core.models import (
    Confidence,
    MemoryItem,
    MemoryKind,
    MemoryStatus,
    ReplyMode,
    UserProfile,
)


class CoreModelTests(unittest.TestCase):
    def test_memory_item_round_trips_to_dict(self):
        item = MemoryItem(
            id="mem_1",
            kind=MemoryKind.FACT,
            content={"education": "Chinese university graduate"},
            source_type="user_input",
            evidence="User entered this during onboarding",
            confidence=Confidence.USER_CONFIRMED,
            created_at="2026-05-25T00:00:00Z",
            last_seen_at="2026-05-25T00:00:00Z",
        )

        encoded = item.to_dict()
        decoded = MemoryItem.from_dict(encoded)

        self.assertEqual(decoded.id, "mem_1")
        self.assertEqual(decoded.kind, MemoryKind.FACT)
        self.assertEqual(decoded.confidence, Confidence.USER_CONFIRMED)
        self.assertEqual(decoded.status, MemoryStatus.ACTIVE)

    def test_user_profile_contains_persona_and_stance_ranges(self):
        profile = UserProfile(
            schema_version=1,
            user_id="user_local",
            facts=[],
            preferences=[],
            boundaries=[],
            style_examples=["short and dry"],
            goals=["practice dating conversations"],
            persona_baseline="reserved",
            persona_range=["warmer", "more outgoing"],
            stance_range=["can express curiosity about new interests"],
            updated_at="2026-05-25T00:00:00Z",
        )

        self.assertEqual(profile.default_reply_mode, ReplyMode.ADAPTIVE)
        self.assertIn("more outgoing", profile.persona_range)
        self.assertIn("can express curiosity about new interests", profile.stance_range)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify failure**

```bash
python3 -m unittest tests/test_core_models.py
```

Expected: fail with `ModuleNotFoundError: No module named 'dating_boost.core'`.

- [ ] **Step 3: Create `dating_boost/core/models.py`**

Implement these model types:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    USER_CONFIRMED = "user_confirmed"


class MemoryKind(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    BOUNDARY = "boundary"
    INFERENCE = "inference"
    SUMMARY = "summary"
    HOOK = "hook"
    COMMITMENT = "commitment"
    RISK = "risk"
    FEEDBACK = "feedback"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    CONFLICTED = "conflicted"
    ARCHIVED = "archived"
    REJECTED = "rejected"


class ReplyMode(str, Enum):
    SELF = "self"
    ADAPTIVE = "adaptive"
    RECIPIENT_OPTIMIZED = "recipient_optimized"


class Divergence(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class MemoryItem:
    id: str
    kind: MemoryKind
    content: dict[str, Any]
    source_type: str
    evidence: str
    confidence: Confidence
    created_at: str
    last_seen_at: str
    supersedes: list[str] = field(default_factory=list)
    status: MemoryStatus = MemoryStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["confidence"] = self.confidence.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryItem":
        return cls(
            id=data["id"],
            kind=MemoryKind(data["kind"]),
            content=dict(data["content"]),
            source_type=data["source_type"],
            evidence=data["evidence"],
            confidence=Confidence(data["confidence"]),
            created_at=data["created_at"],
            last_seen_at=data["last_seen_at"],
            supersedes=list(data.get("supersedes", [])),
            status=MemoryStatus(data.get("status", MemoryStatus.ACTIVE.value)),
        )


@dataclass(frozen=True)
class UserProfile:
    schema_version: int
    user_id: str
    facts: list[MemoryItem]
    preferences: list[MemoryItem]
    boundaries: list[MemoryItem]
    style_examples: list[str]
    goals: list[str]
    persona_baseline: str
    persona_range: list[str]
    stance_range: list[str]
    updated_at: str
    default_reply_mode: ReplyMode = ReplyMode.ADAPTIVE
```

- [ ] **Step 4: Create `dating_boost/core/__init__.py`**

```python
from dating_boost.core.models import (
    Confidence,
    Divergence,
    MemoryItem,
    MemoryKind,
    MemoryStatus,
    ReplyMode,
    UserProfile,
)

__all__ = [
    "Confidence",
    "Divergence",
    "MemoryItem",
    "MemoryKind",
    "MemoryStatus",
    "ReplyMode",
    "UserProfile",
]
```

- [ ] **Step 5: Run tests**

```bash
python3 -m unittest tests/test_core_models.py
python3 -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add dating_boost/core tests/test_core_models.py
git commit -m "Add core domain models"
```

## Task 3: Add Atomic JSON Storage

**Files:**
- Create: `dating_boost/core/storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write failing storage tests**

Create `tests/test_storage.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from dating_boost.core.storage import (
    JsonStorage,
    SchemaVersionError,
    StorageCorruptionError,
)


class StorageTests(unittest.TestCase):
    def test_json_storage_writes_and_reads_document_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = JsonStorage(Path(temp_dir))
            storage.write_json(Path("user_profile.json"), {"schema_version": 1, "name": "local"})

            result = storage.read_json(Path("user_profile.json"), expected_schema_version=1)

            self.assertEqual(result["name"], "local")

    def test_unknown_schema_version_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "user_profile.json"
            path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
            storage = JsonStorage(Path(temp_dir))

            with self.assertRaises(SchemaVersionError):
                storage.read_json(Path("user_profile.json"), expected_schema_version=1)

    def test_corrupt_json_raises_storage_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "broken.json"
            path.write_text("{broken", encoding="utf-8")
            storage = JsonStorage(Path(temp_dir))

            with self.assertRaises(StorageCorruptionError):
                storage.read_json(Path("broken.json"), expected_schema_version=1)

    def test_jsonl_append_writes_one_object_per_line(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = JsonStorage(Path(temp_dir))
            storage.append_jsonl(Path("feedback_events.jsonl"), {"event_id": "fb_1"})
            storage.append_jsonl(Path("feedback_events.jsonl"), {"event_id": "fb_2"})

            lines = (Path(temp_dir) / "feedback_events.jsonl").read_text(encoding="utf-8").splitlines()

            self.assertEqual([json.loads(line)["event_id"] for line in lines], ["fb_1", "fb_2"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify failure**

```bash
python3 -m unittest tests/test_storage.py
```

Expected: fail with `ModuleNotFoundError` or import error for `dating_boost.core.storage`.

- [ ] **Step 3: Create `dating_boost/core/storage.py`**

```python
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class StorageError(RuntimeError):
    pass


class StorageCorruptionError(StorageError):
    pass


class SchemaVersionError(StorageError):
    pass


class JsonStorage:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def read_json(self, relative_path: Path, *, expected_schema_version: int) -> dict[str, Any]:
        path = self.root / relative_path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StorageCorruptionError(f"corrupt JSON: {relative_path}") from exc
        if data.get("schema_version") != expected_schema_version:
            raise SchemaVersionError(
                f"expected schema_version {expected_schema_version} for {relative_path}, "
                f"got {data.get('schema_version')}"
            )
        return data

    def write_json(self, relative_path: Path, data: dict[str, Any]) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with temp_path.open("r+", encoding="utf-8") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)

    def append_jsonl(self, relative_path: Path, data: dict[str, Any]) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
```

- [ ] **Step 4: Run tests**

```bash
python3 -m unittest tests/test_storage.py
python3 -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add dating_boost/core/storage.py tests/test_storage.py
git commit -m "Add atomic JSON storage"
```

## Task 4: Add Normalized Observation Contract and Fixture Loader

**Files:**
- Create: `dating_boost/perception/__init__.py`
- Create: `dating_boost/perception/taxonomy.py`
- Create: `dating_boost/perception/observations.py`
- Create: `dating_boost/perception/fixture_loader.py`
- Create: `tests/fixtures/intelligence/app_observation_chat.json`
- Test: `tests/test_observations.py`

- [ ] **Step 1: Write failing observation tests**

Create `tests/test_observations.py`:

```python
import unittest
from pathlib import Path

from dating_boost.perception.fixture_loader import load_observation
from dating_boost.perception.observations import AppObservation
from dating_boost.perception.taxonomy import PageType, SourceType


class ObservationTests(unittest.TestCase):
    def test_loads_chat_observation_fixture(self):
        observation = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))

        self.assertEqual(observation.source_type, SourceType.MANUAL_FIXTURE)
        self.assertEqual(observation.page_type, PageType.CHAT_THREAD)
        self.assertEqual(observation.match_identity_hints.visible_name, "Alex")
        self.assertEqual(observation.conversation_observation.visible_messages[-1]["text"], "What are you up to this weekend?")

    def test_observation_round_trips_to_dict(self):
        observation = AppObservation.minimal(
            observation_id="obs_1",
            source_type=SourceType.USER_INPUT,
            app_id="generic",
            captured_at="2026-05-25T00:00:00Z",
            page_type=PageType.CHAT_THREAD,
        )

        decoded = AppObservation.from_dict(observation.to_dict())

        self.assertEqual(decoded.observation_id, "obs_1")
        self.assertEqual(decoded.page_type, PageType.CHAT_THREAD)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Create fixture JSON**

Create `tests/fixtures/intelligence/app_observation_chat.json`:

```json
{
  "observation_id": "obs_chat_001",
  "source_type": "manual_fixture",
  "app_id": "tinder",
  "adapter_id": "manual.fixture.v1",
  "captured_at": "2026-05-25T00:00:00Z",
  "page_type": "chat_thread",
  "page_confidence": "high",
  "match_identity_hints": {
    "visible_name": "Alex",
    "profile_cues": ["likes live music", "has a dog"],
    "conversation_fingerprint": "alex-weekend-question",
    "evidence": "Visible chat header and latest message"
  },
  "profile_observation": {
    "profile_text": "Live music, coffee, long walks.",
    "photo_cues": ["dog appears in one photo"],
    "hook_candidates": ["Ask about live music", "Ask about the dog"]
  },
  "conversation_observation": {
    "visible_messages": [
      {"sender": "user", "text": "That concert photo looks fun."},
      {"sender": "match", "text": "It was. What are you up to this weekend?"}
    ],
    "input_state": "empty",
    "thread_cues": ["weekend plan question"]
  },
  "element_observations": [],
  "exception_state": "none",
  "provenance": {
    "evidence": "Manual fixture",
    "redaction_status": "synthetic"
  },
  "raw_ref": null
}
```

- [ ] **Step 3: Run test to verify failure**

```bash
python3 -m unittest tests/test_observations.py
```

Expected: fail because `dating_boost.perception` does not exist.

- [ ] **Step 4: Implement taxonomy and observation dataclasses**

Create `dating_boost/perception/taxonomy.py` with `SourceType`, `PageType`, and `ExceptionState` enums. Create `dating_boost/perception/observations.py` with `MatchIdentityHints`, `ProfileObservation`, `ConversationObservation`, and `AppObservation` dataclasses. Each dataclass needs `to_dict` and `from_dict`. `AppObservation.minimal` should construct empty nested observations.

Use enum values exactly matching the fixture strings:

```python
class SourceType(str, Enum):
    MANUAL_FIXTURE = "manual_fixture"
    SCREENSHOT_FIXTURE = "screenshot_fixture"
    LIVE_SCREENSHOT = "live_screenshot"
    USER_INPUT = "user_input"
```

- [ ] **Step 5: Implement fixture loader**

Create `dating_boost/perception/fixture_loader.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from dating_boost.perception.observations import AppObservation


def load_observation(path: Path) -> AppObservation:
    return AppObservation.from_dict(json.loads(path.read_text(encoding="utf-8")))
```

- [ ] **Step 6: Run tests**

```bash
python3 -m unittest tests/test_observations.py
python3 -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add dating_boost/perception tests/fixtures/intelligence/app_observation_chat.json tests/test_observations.py
git commit -m "Add normalized observation contract"
```

## Task 5: Add JSON Memory Repository

**Files:**
- Create: `dating_boost/core/repositories.py`
- Test: `tests/test_repositories.py`

- [ ] **Step 1: Write failing repository tests**

Create `tests/test_repositories.py`:

```python
import tempfile
import unittest
from pathlib import Path

from dating_boost.core.models import UserProfile
from dating_boost.core.repositories import JsonMemoryRepository


class RepositoryTests(unittest.TestCase):
    def test_saves_and_loads_user_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = JsonMemoryRepository(Path(temp_dir))
            profile = UserProfile(
                schema_version=1,
                user_id="user_local",
                facts=[],
                preferences=[],
                boundaries=[],
                style_examples=["concise"],
                goals=["practice"],
                persona_baseline="reserved",
                persona_range=["warmer"],
                stance_range=["open to new interests"],
                updated_at="2026-05-25T00:00:00Z",
            )

            repo.save_user_profile(profile)
            loaded = repo.load_user_profile()

            self.assertEqual(loaded.user_id, "user_local")
            self.assertEqual(loaded.persona_range, ["warmer"])

    def test_appends_feedback_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = JsonMemoryRepository(Path(temp_dir))

            repo.append_feedback_event("match_1", {"event_id": "fb_1", "label": "accepted"})
            repo.append_feedback_event("match_1", {"event_id": "fb_2", "label": "too_long"})
            events = repo.load_feedback_events("match_1")

            self.assertEqual([event["event_id"] for event in events], ["fb_1", "fb_2"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify failure**

```bash
python3 -m unittest tests/test_repositories.py
```

Expected: fail because `dating_boost.core.repositories` does not exist.

- [ ] **Step 3: Implement repository**

Create `JsonMemoryRepository` with:

- `save_user_profile(profile: UserProfile) -> None`
- `load_user_profile() -> UserProfile`
- `append_feedback_event(match_id: str, event: dict[str, object]) -> None`
- `load_feedback_events(match_id: str) -> list[dict[str, object]]`

Use `JsonStorage` from Task 3. Serialize `ReplyMode` as string in `UserProfile` helpers. Store user profile at `user_profile.json`, feedback at `matches/<match_id>/feedback_events.jsonl`.

- [ ] **Step 4: Run tests**

```bash
python3 -m unittest tests/test_repositories.py
python3 -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add dating_boost/core/repositories.py tests/test_repositories.py
git commit -m "Add JSON memory repository"
```

## Task 6: Add Match Identity Resolver

**Files:**
- Create: `dating_boost/core/identity.py`
- Test: `tests/test_identity.py`

- [ ] **Step 1: Write failing identity tests**

Create `tests/test_identity.py`:

```python
import unittest
from pathlib import Path

from dating_boost.core.identity import IdentityConfidence, resolve_match_identity
from dating_boost.perception.fixture_loader import load_observation


class IdentityTests(unittest.TestCase):
    def test_creates_new_match_when_no_candidates_exist(self):
        observation = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))

        result = resolve_match_identity(observation, existing_matches=[])

        self.assertEqual(result.confidence, IdentityConfidence.NEW)
        self.assertTrue(result.match_id.startswith("match_"))
        self.assertFalse(result.requires_user_confirmation)

    def test_low_confidence_name_only_match_requires_confirmation(self):
        observation = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))

        result = resolve_match_identity(
            observation,
            existing_matches=[{"match_id": "match_existing", "display_name": "Alex"}],
        )

        self.assertEqual(result.confidence, IdentityConfidence.LOW)
        self.assertTrue(result.requires_user_confirmation)

    def test_high_confidence_match_uses_profile_and_fingerprint(self):
        observation = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))

        result = resolve_match_identity(
            observation,
            existing_matches=[
                {
                    "match_id": "match_alex",
                    "display_name": "Alex",
                    "profile_cues": ["likes live music", "has a dog"],
                    "conversation_fingerprint": "alex-weekend-question",
                }
            ],
        )

        self.assertEqual(result.match_id, "match_alex")
        self.assertEqual(result.confidence, IdentityConfidence.HIGH)
        self.assertFalse(result.requires_user_confirmation)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify failure**

```bash
python3 -m unittest tests/test_identity.py
```

Expected: fail because `dating_boost.core.identity` does not exist.

- [ ] **Step 3: Implement identity resolver**

Implement `IdentityConfidence` enum with `NEW`, `HIGH`, `MEDIUM`, `LOW`, `CONFLICT`. Implement `IdentityResult` dataclass with `match_id`, `confidence`, `requires_user_confirmation`, and `reason`. Use visible name, overlapping profile cues, and conversation fingerprint exactly as described in the tests.

- [ ] **Step 4: Run tests**

```bash
python3 -m unittest tests/test_identity.py
python3 -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add dating_boost/core/identity.py tests/test_identity.py
git commit -m "Add match identity resolver"
```

## Task 7: Add Context Pack Builder

**Files:**
- Create: `dating_boost/core/context_pack.py`
- Test: `tests/test_context_pack.py`

- [ ] **Step 1: Write failing context pack tests**

Create `tests/test_context_pack.py`:

```python
import unittest

from dating_boost.core.context_pack import build_context_pack
from dating_boost.core.models import ReplyMode


class ContextPackTests(unittest.TestCase):
    def test_context_pack_prioritizes_boundaries_and_latest_message(self):
        pack = build_context_pack(
            user_profile={
                "boundaries": [{"content": {"text": "Do not claim overseas study"}}],
                "facts": [{"content": {"education": "Chinese university graduate"}}],
                "style_examples": ["short dry humor"],
            },
            match_profile={
                "possible_interests": [{"label": "live music", "confidence": "high"}],
                "conversation_hooks": ["Ask about recent concert"],
            },
            conversation_memory={
                "recent_messages": [
                    {"sender": "match", "text": "What are you up to this weekend?"}
                ],
                "open_threads": ["weekend plan question"],
                "commitments": [],
                "running_summary": "They discussed concerts.",
            },
            reply_mode=ReplyMode.ADAPTIVE,
            max_items=6,
        )

        labels = [item["label"] for item in pack["items"]]

        self.assertLess(labels.index("user_boundaries"), labels.index("match_hooks"))
        self.assertLess(labels.index("latest_message"), labels.index("conversation_summary"))
        self.assertEqual(pack["reply_mode"], "adaptive")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify failure**

```bash
python3 -m unittest tests/test_context_pack.py
```

Expected: fail because `dating_boost.core.context_pack` does not exist.

- [ ] **Step 3: Implement context pack builder**

Create `build_context_pack` that returns a dict with `reply_mode`, `items`, and `safety_constraints`. Add items in this exact priority:

1. `user_boundaries`
2. `user_hard_facts`
3. `latest_message`
4. `open_threads`
5. `historical_commitments`
6. `recent_messages`
7. `conversation_summary`
8. `match_hooks`
9. `style_examples`
10. `low_confidence_hypotheses`

Respect `max_items` by slicing after priority order is built.

- [ ] **Step 4: Run tests**

```bash
python3 -m unittest tests/test_context_pack.py
python3 -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add dating_boost/core/context_pack.py tests/test_context_pack.py
git commit -m "Add context pack builder"
```

## Task 8: Add Model Backend Abstraction

**Files:**
- Modify: `pyproject.toml`
- Create: `dating_boost/intelligence/__init__.py`
- Create: `dating_boost/intelligence/backends.py`
- Create: `tests/fixtures/intelligence/scripted_reply.json`
- Test: `tests/test_backends.py`

- [ ] **Step 1: Write failing backend tests**

Create `tests/test_backends.py`:

```python
import json
import unittest
from pathlib import Path

from dating_boost.intelligence.backends import BackendCapability, ScriptedBackend


class BackendTests(unittest.TestCase):
    def test_scripted_backend_returns_structured_payload(self):
        payload = json.loads(Path("tests/fixtures/intelligence/scripted_reply.json").read_text(encoding="utf-8"))
        backend = ScriptedBackend(payload)

        result = backend.generate_structured(
            system_prompt="Return draft JSON.",
            user_prompt="Draft a reply.",
            schema={"type": "object"},
        )

        self.assertEqual(result["best_reply"], "Sounds fun. Any good live music spots you recommend?")

    def test_backend_declares_capabilities(self):
        backend = ScriptedBackend({"ok": True})

        self.assertIn(BackendCapability.GENERATE_STRUCTURED, backend.capabilities)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Create scripted reply fixture**

Create `tests/fixtures/intelligence/scripted_reply.json`:

```json
{
  "best_reply": "Sounds fun. Any good live music spots you recommend?",
  "safer_reply": "Nice. Any live music places you like around here?",
  "bolder_reply": "Now I need your best live music recommendation.",
  "why_this_works": "It uses the match's live music cue and answers with curiosity.",
  "risk_flags": [],
  "missing_info": [],
  "mode_notes": "Adaptive mode keeps the user's concise style while adding warmth.",
  "persona_divergence": "low",
  "stance_divergence": "low"
}
```

- [ ] **Step 3: Run test to verify failure**

```bash
python3 -m unittest tests/test_backends.py
```

Expected: fail because `dating_boost.intelligence.backends` does not exist.

- [ ] **Step 4: Update `pyproject.toml`**

Add an optional dependency group:

```toml
[project.optional-dependencies]
openai = ["openai>=2,<3"]
```

- [ ] **Step 5: Implement `dating_boost/intelligence/backends.py`**

Define:

- `BackendCapability` enum.
- `ModelBackend` protocol.
- `ScriptedBackend`.
- `OpenAIBackend` with lazy import of `openai.OpenAI`.

`OpenAIBackend.generate_structured` should accept `system_prompt`, `user_prompt`, and `schema`. It should call the OpenAI Responses API using structured output. Keep provider-specific code inside this class.

- [ ] **Step 6: Run tests**

```bash
python3 -m unittest tests/test_backends.py
python3 -m unittest discover -s tests
```

Expected: all tests pass without requiring `OPENAI_API_KEY`, because the tests use `ScriptedBackend`.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml dating_boost/intelligence tests/fixtures/intelligence/scripted_reply.json tests/test_backends.py
git commit -m "Add model backend abstraction"
```

## Task 9: Add Reply Generation Contract

**Files:**
- Create: `dating_boost/intelligence/prompts.py`
- Create: `dating_boost/intelligence/reply_generator.py`
- Test: `tests/test_reply_generator.py`

- [ ] **Step 1: Write failing reply generator tests**

Create `tests/test_reply_generator.py`:

```python
import json
import unittest
from pathlib import Path

from dating_boost.core.models import ReplyMode
from dating_boost.intelligence.backends import ScriptedBackend
from dating_boost.intelligence.reply_generator import generate_reply


class ReplyGeneratorTests(unittest.TestCase):
    def test_generate_reply_returns_structured_drafts(self):
        backend = ScriptedBackend(
            json.loads(Path("tests/fixtures/intelligence/scripted_reply.json").read_text(encoding="utf-8"))
        )
        context_pack = {
            "reply_mode": ReplyMode.ADAPTIVE.value,
            "items": [
                {"label": "latest_message", "content": "What are you up to this weekend?"},
                {"label": "match_hooks", "content": ["live music"]},
            ],
            "safety_constraints": ["Do not invent hard facts."],
        }

        response = generate_reply(context_pack, ReplyMode.ADAPTIVE, backend)

        self.assertEqual(response.best_reply, "Sounds fun. Any good live music spots you recommend?")
        self.assertEqual(response.persona_divergence.value, "low")
        self.assertEqual(response.stance_divergence.value, "low")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify failure**

```bash
python3 -m unittest tests/test_reply_generator.py
```

Expected: fail because `dating_boost.intelligence.reply_generator` does not exist.

- [ ] **Step 3: Implement prompt schema and reply dataclass**

In `dating_boost/intelligence/prompts.py`, define `REPLY_SCHEMA` with required keys:

- `best_reply`
- `safer_reply`
- `bolder_reply`
- `why_this_works`
- `risk_flags`
- `missing_info`
- `mode_notes`
- `persona_divergence`
- `stance_divergence`

In `dating_boost/intelligence/reply_generator.py`, define `DraftResponse` dataclass and `generate_reply(context_pack, reply_mode, backend)`.

- [ ] **Step 4: Run tests**

```bash
python3 -m unittest tests/test_reply_generator.py
python3 -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add dating_boost/intelligence/prompts.py dating_boost/intelligence/reply_generator.py tests/test_reply_generator.py
git commit -m "Add reply generation contract"
```

## Task 10: Add Content Policy Gate

**Files:**
- Create: `dating_boost/policy/content.py`
- Modify: `dating_boost/policy/__init__.py`
- Test: `tests/test_content_policy.py`

- [ ] **Step 1: Write failing content policy tests**

Create `tests/test_content_policy.py`:

```python
import unittest

from dating_boost.intelligence.reply_generator import DraftResponse
from dating_boost.policy.content import evaluate_draft_content


class ContentPolicyTests(unittest.TestCase):
    def test_blocks_hard_fact_violation(self):
        draft = DraftResponse(
            best_reply="I studied in London too.",
            safer_reply="That sounds interesting.",
            bolder_reply="London stories are always fun.",
            why_this_works="Claims shared background.",
            risk_flags=[],
            missing_info=[],
            mode_notes="",
            persona_divergence="low",
            stance_divergence="high",
        )
        context_pack = {
            "items": [
                {"label": "user_hard_facts", "content": {"education": "Chinese university graduate"}},
                {"label": "user_boundaries", "content": "Do not claim overseas study"},
            ]
        }

        decision = evaluate_draft_content(draft, context_pack)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.severity, "high")

    def test_allows_labeled_stance_shift(self):
        draft = DraftResponse(
            best_reply="I am open to checking out a live show this weekend.",
            safer_reply="A live show could be fun.",
            bolder_reply="Pick a live show and I might be in.",
            why_this_works="Expresses future openness without claiming past experience.",
            risk_flags=[],
            missing_info=[],
            mode_notes="Changes stance toward live music.",
            persona_divergence="low",
            stance_divergence="medium",
        )

        decision = evaluate_draft_content(draft, {"items": []})

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.severity, "low")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify failure**

```bash
python3 -m unittest tests/test_content_policy.py
```

Expected: fail because `dating_boost.policy.content` does not exist.

- [ ] **Step 3: Implement content policy**

Create `ContentPolicyDecision` dataclass and `evaluate_draft_content`. For MVP, implement deterministic checks:

- If a user boundary text appears to forbid overseas study and a draft contains `studied in London`, block with high severity.
- If `stance_divergence` is medium or high but `mode_notes` is empty, require user confirmation.
- Otherwise allow.

- [ ] **Step 4: Export content policy**

Update `dating_boost/policy/__init__.py` to export `ContentPolicyDecision` and `evaluate_draft_content`.

- [ ] **Step 5: Run tests**

```bash
python3 -m unittest tests/test_content_policy.py
python3 -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add dating_boost/policy/__init__.py dating_boost/policy/content.py tests/test_content_policy.py
git commit -m "Add content policy gate"
```

## Task 11: Add Feedback Events

**Files:**
- Create: `dating_boost/core/feedback.py`
- Test: `tests/test_feedback.py`

- [ ] **Step 1: Write failing feedback tests**

Create `tests/test_feedback.py`:

```python
import tempfile
import unittest
from pathlib import Path

from dating_boost.core.feedback import FeedbackLabel, create_feedback_event
from dating_boost.core.repositories import JsonMemoryRepository


class FeedbackTests(unittest.TestCase):
    def test_feedback_event_contains_mode_and_label(self):
        event = create_feedback_event(
            event_id="fb_1",
            match_id="match_alex",
            draft_id="draft_1",
            mode="adaptive",
            label=FeedbackLabel.ACCEPTED,
            created_at="2026-05-25T00:00:00Z",
        )

        self.assertEqual(event["label"], "accepted")
        self.assertEqual(event["mode"], "adaptive")

    def test_feedback_event_persists_through_repository(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = JsonMemoryRepository(Path(temp_dir))
            event = create_feedback_event(
                event_id="fb_1",
                match_id="match_alex",
                draft_id="draft_1",
                mode="adaptive",
                label=FeedbackLabel.TOO_LONG,
                created_at="2026-05-25T00:00:00Z",
            )

            repo.append_feedback_event("match_alex", event)

            self.assertEqual(repo.load_feedback_events("match_alex")[0]["label"], "too_long")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify failure**

```bash
python3 -m unittest tests/test_feedback.py
```

Expected: fail because `dating_boost.core.feedback` does not exist.

- [ ] **Step 3: Implement feedback helpers**

Create `FeedbackLabel` enum with `accepted`, `edited`, `rejected`, `too_long`, `too_short`, `too_boring`, `too_aggressive`, `too_flirty`, `too_formal`, `not_like_me`, `good_hook`, `bad_hook`, `wrong_assumption`. Implement `create_feedback_event`.

- [ ] **Step 4: Run tests**

```bash
python3 -m unittest tests/test_feedback.py
python3 -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add dating_boost/core/feedback.py tests/test_feedback.py
git commit -m "Add feedback events"
```

## Task 12: Add MVP CLI Workflow

**Files:**
- Modify: `dating_boost/cli.py`
- Create: `tests/fixtures/intelligence/user_profile.json`
- Test: `tests/test_cli_mvp.py`

- [ ] **Step 1: Create user profile fixture**

Create `tests/fixtures/intelligence/user_profile.json`:

```json
{
  "schema_version": 1,
  "user_id": "user_local",
  "facts": [],
  "preferences": [],
  "boundaries": [],
  "style_examples": ["short, warm, dry humor"],
  "goals": ["practice better dating conversations"],
  "persona_baseline": "reserved",
  "persona_range": ["warmer", "more outgoing"],
  "stance_range": ["can express curiosity about new interests"],
  "updated_at": "2026-05-25T00:00:00Z",
  "default_reply_mode": "adaptive"
}
```

- [ ] **Step 2: Write failing CLI workflow tests**

Create `tests/test_cli_mvp.py`:

```python
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost.cli import main


class CliMvpTests(unittest.TestCase):
    def test_init_profile_import_observation_and_draft_with_scripted_backend(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = StringIO()
            data_dir = Path(temp_dir)

            with redirect_stdout(output):
                init_exit = main([
                    "init-profile",
                    "--data-dir",
                    str(data_dir),
                    "--input",
                    "tests/fixtures/intelligence/user_profile.json",
                ])
                import_exit = main([
                    "import-observation",
                    "--data-dir",
                    str(data_dir),
                    "--input",
                    "tests/fixtures/intelligence/app_observation_chat.json",
                ])
                draft_exit = main([
                    "draft",
                    "--data-dir",
                    str(data_dir),
                    "--match-id",
                    "match_alex",
                    "--mode",
                    "adaptive",
                    "--scripted-backend-output",
                    "tests/fixtures/intelligence/scripted_reply.json",
                ])

            self.assertEqual(init_exit, 0)
            self.assertEqual(import_exit, 0)
            self.assertEqual(draft_exit, 0)
            self.assertIn("Sounds fun", output.getvalue())
            self.assertTrue((data_dir / "user_profile.json").exists())

    def test_feedback_command_appends_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)

            exit_code = main([
                "feedback",
                "--data-dir",
                str(data_dir),
                "--match-id",
                "match_alex",
                "--draft-id",
                "draft_1",
                "--mode",
                "adaptive",
                "--label",
                "accepted",
            ])

            events_path = data_dir / "matches" / "match_alex" / "feedback_events.jsonl"
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]

            self.assertEqual(exit_code, 0)
            self.assertEqual(events[0]["label"], "accepted")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify failure**

```bash
python3 -m unittest tests/test_cli_mvp.py
```

Expected: fail because `init-profile`, `import-observation`, `draft`, and `feedback` commands do not exist.

- [ ] **Step 4: Refactor `dating_boost/cli.py` to subcommands**

Keep legacy single-action authorization working. Add subcommands:

- `authorize <action> [--autonomous]`
- `init-profile --data-dir <path> --input <json>`
- `import-observation --data-dir <path> --input <json>`
- `draft --data-dir <path> --match-id <id> --mode <mode> --scripted-backend-output <json>`
- `feedback --data-dir <path> --match-id <id> --draft-id <id> --mode <mode> --label <label>`

Legacy calls such as `python3 -m dating_boost.cli send_message` should continue by detecting when the first argument is an `Action` value.

- [ ] **Step 5: Run tests**

```bash
python3 -m unittest tests/test_cli_mvp.py
python3 -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add dating_boost/cli.py tests/fixtures/intelligence/user_profile.json tests/test_cli_mvp.py
git commit -m "Add MVP CLI workflow"
```

## Task 13: Add Offline Eval Runner

**Files:**
- Create: `dating_boost/evals/__init__.py`
- Create: `dating_boost/evals/rubrics.py`
- Create: `dating_boost/evals/runner.py`
- Create: `tests/fixtures/evals/reply_quality_cases.jsonl`
- Test: `tests/test_evals.py`

- [ ] **Step 1: Write failing eval tests**

Create `tests/test_evals.py`:

```python
import unittest
from pathlib import Path

from dating_boost.evals.runner import run_reply_quality_eval


class EvalTests(unittest.TestCase):
    def test_reply_quality_eval_requires_twenty_cases_and_passes_seed_file(self):
        result = run_reply_quality_eval(Path("tests/fixtures/evals/reply_quality_cases.jsonl"))

        self.assertEqual(result.case_count, 20)
        self.assertTrue(result.passed)
        self.assertGreaterEqual(result.averages["groundedness"], 4.7)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Create eval fixture file with 20 passing cases**

Create `tests/fixtures/evals/reply_quality_cases.jsonl` with 20 lines. Each line should have this shape:

```json
{"case_id":"case_001","scores":{"groundedness":5,"safety":5,"context_use":4,"voice_match":4,"adaptive_usefulness":4},"hard_fact_sample":true,"boundary_sample":true}
```

Use `case_001` through `case_020`. Make all `groundedness` and `safety` scores 5. Make all other metric scores 4 or 5.

- [ ] **Step 3: Run test to verify failure**

```bash
python3 -m unittest tests/test_evals.py
```

Expected: fail because `dating_boost.evals.runner` does not exist.

- [ ] **Step 4: Implement rubric and runner**

`run_reply_quality_eval(path)` should:

- read JSONL cases.
- require at least 20 cases.
- calculate averages for `groundedness`, `safety`, `context_use`, `voice_match`, and `adaptive_usefulness`.
- fail if groundedness average is below 4.7.
- fail if safety average is below 4.7.
- fail if any hard-fact sample has groundedness below 4.
- fail if any boundary sample has safety below 4.
- fail if context_use, voice_match, or adaptive_usefulness average is below 4.0.

- [ ] **Step 5: Run tests**

```bash
python3 -m unittest tests/test_evals.py
python3 -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add dating_boost/evals tests/fixtures/evals/reply_quality_cases.jsonl tests/test_evals.py
git commit -m "Add offline reply quality eval"
```

## Task 14: Final Verification and README Update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README with MVP commands**

Add a section titled `MVP intelligence workflow` with these commands:

```bash
python3 -m dating_boost.cli init-profile --data-dir .local/dating-boost --input tests/fixtures/intelligence/user_profile.json
python3 -m dating_boost.cli import-observation --data-dir .local/dating-boost --input tests/fixtures/intelligence/app_observation_chat.json
python3 -m dating_boost.cli draft --data-dir .local/dating-boost --match-id match_alex --mode adaptive --scripted-backend-output tests/fixtures/intelligence/scripted_reply.json
python3 -m dating_boost.cli feedback --data-dir .local/dating-boost --match-id match_alex --draft-id draft_1 --mode adaptive --label accepted
python3 -m unittest discover -s tests
```

Also state that `--scripted-backend-output` is for deterministic local tests and fixture demos, not the production LLM path.

- [ ] **Step 2: Run full verification**

```bash
python3 -m unittest discover -s tests
python3 -m compileall dating_boost
python3 -m dating_boost.cli observe
python3 -m dating_boost.cli send_message
python3 -m dating_boost.cli send_message --autonomous
```

Expected:

- unittest exits 0.
- compileall exits 0.
- observe exits 0 with `"allowed": true`.
- send_message exits 2 with `"allowed": false`.
- send_message `--autonomous` exits 0 with `"allowed": true`.

- [ ] **Step 3: Run MVP fixture smoke**

```bash
rm -rf .local/dating-boost
python3 -m dating_boost.cli init-profile --data-dir .local/dating-boost --input tests/fixtures/intelligence/user_profile.json
python3 -m dating_boost.cli import-observation --data-dir .local/dating-boost --input tests/fixtures/intelligence/app_observation_chat.json
python3 -m dating_boost.cli draft --data-dir .local/dating-boost --match-id match_alex --mode adaptive --scripted-backend-output tests/fixtures/intelligence/scripted_reply.json
python3 -m dating_boost.cli feedback --data-dir .local/dating-boost --match-id match_alex --draft-id draft_1 --mode adaptive --label accepted
```

Expected: all commands exit 0, draft output includes `best_reply`, and `.local/dating-boost/matches/match_alex/feedback_events.jsonl` exists.

- [ ] **Step 4: Commit final docs**

```bash
git add README.md
git commit -m "Document MVP intelligence workflow"
```

## Coverage Checklist

- Product blueprint `Observation Contract`: Tasks 4, 6, 12.
- Product blueprint `ModelBackend Contract`: Task 8.
- Product blueprint `Content Policy Gate`: Task 10.
- Product blueprint `Storage Atomicity and Migration`: Tasks 3, 5.
- Product blueprint MVP vertical slice: Tasks 2 through 13.
- Intelligence spec user profile and stance/persona range: Tasks 2, 7, 9.
- Intelligence spec match identity: Task 6.
- Intelligence spec context pack priority: Task 7.
- Intelligence spec reply modes and draft output contract: Task 9.
- Intelligence spec feedback loop: Task 11.
- Intelligence spec eval pass criteria: Task 13.
- Existing action policy gate: Tasks 1, 12, 14.

## Implementation Detail Appendix

Use these signatures and behavior rules when a task refers to a module by responsibility rather than pasting a full file body.

### Observation Dataclasses

`dating_boost/perception/observations.py` must expose:

```python
@dataclass(frozen=True)
class MatchIdentityHints:
    visible_name: str | None
    profile_cues: list[str]
    conversation_fingerprint: str | None
    evidence: str

@dataclass(frozen=True)
class ProfileObservation:
    profile_text: str
    photo_cues: list[str]
    hook_candidates: list[str]

@dataclass(frozen=True)
class ConversationObservation:
    visible_messages: list[dict[str, str]]
    input_state: str
    thread_cues: list[str]

@dataclass(frozen=True)
class AppObservation:
    observation_id: str
    source_type: SourceType
    app_id: str
    adapter_id: str
    captured_at: str
    page_type: PageType
    page_confidence: Confidence
    match_identity_hints: MatchIdentityHints
    profile_observation: ProfileObservation
    conversation_observation: ConversationObservation
    element_observations: list[dict[str, object]]
    exception_state: ExceptionState
    provenance: dict[str, str]
    raw_ref: str | None
```

Each dataclass must implement `to_dict` and `from_dict`. Enum values must serialize to strings. `AppObservation.minimal(observation_id, source_type, app_id, captured_at, page_type)` must create empty nested values and `exception_state=ExceptionState.NONE`.

### Repository Serialization

`JsonMemoryRepository` must convert `UserProfile.default_reply_mode` to and from its string value. It must serialize `MemoryItem` values using `MemoryItem.to_dict()` and load them with `MemoryItem.from_dict()`. It must never expose `JsonStorage` paths to callers.

### Identity Resolver

`resolve_match_identity(observation, existing_matches)` must:

```python
@dataclass(frozen=True)
class IdentityResult:
    match_id: str
    confidence: IdentityConfidence
    requires_user_confirmation: bool
    reason: str
```

Scoring:

- no candidates -> `IdentityConfidence.NEW`, generated id `match_<lowercase visible name or observation id>`, confirmation false.
- one candidate with same `display_name`, overlapping profile cue, and same `conversation_fingerprint` -> high, confirmation false.
- one candidate with same `display_name` plus either cue overlap or fingerprint match -> medium, confirmation false.
- name-only match -> low, confirmation true.
- multiple same-name candidates -> conflict, confirmation true.

### Context Pack Builder

`build_context_pack(user_profile, match_profile, conversation_memory, reply_mode, max_items)` returns:

```python
{
  "reply_mode": "adaptive",
  "items": [{"label": "latest_message", "content": "What are you up to this weekend?", "priority": 3}],
  "safety_constraints": [
    "Do not invent hard facts.",
    "Do not present stance modulation as past fact.",
    "Label medium or high persona/stance divergence."
  ]
}
```

The builder must be deterministic: same input order returns same output order. It must not call a model.

### Backend Interface

`dating_boost/intelligence/backends.py` must define:

```python
class BackendCapability(str, Enum):
    GENERATE_STRUCTURED = "generate_structured"
    ANALYZE_IMAGE = "analyze_image"
    SUMMARIZE = "summarize"
    SCORE = "score"

class ModelBackend(Protocol):
    capabilities: set[BackendCapability]

    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, object],
    ) -> dict[str, object]:
        raise NotImplementedError
```

`ScriptedBackend` returns its configured payload and is only for deterministic tests and fixture demos. `OpenAIBackend` lazy-imports `openai.OpenAI` inside `__init__` or `generate_structured`, not at module import time.

### Draft Response Contract

`DraftResponse` must normalize divergence strings into `Divergence` enum values and preserve `risk_flags` and `missing_info` as lists of strings.

```python
@dataclass(frozen=True)
class DraftResponse:
    best_reply: str
    safer_reply: str
    bolder_reply: str
    why_this_works: str
    risk_flags: list[str]
    missing_info: list[str]
    mode_notes: str
    persona_divergence: Divergence
    stance_divergence: Divergence
```

### CLI Result Shapes

`init-profile` prints:

```json
{"ok": true, "user_id": "user_local"}
```

`import-observation` prints:

```json
{"ok": true, "match_id": "match_alex", "identity_confidence": "new"}
```

`draft` prints the complete `DraftResponse` JSON plus content policy decision:

```json
{"ok": true, "draft": {"best_reply": "Sounds fun. Any good live music spots you recommend?"}, "content_policy": {"allowed": true}}
```

`feedback` prints:

```json
{"ok": true, "event_id": "fb_20260525_000001"}
```

### Eval Result Contract

`run_reply_quality_eval(path)` must return:

```python
@dataclass(frozen=True)
class EvalResult:
    case_count: int
    passed: bool
    averages: dict[str, float]
    failures: list[str]
```

The runner must not call a model. It scores fixture JSONL only.

## Execution Notes

- Run tasks in order.
- Commit after every task.
- Do not add live GUI control in this phase.
- Do not store raw screenshots in this phase.
- Do not use a scripted backend as the production LLM path.
- Do not hardcode API keys.
- If a live OpenAI backend smoke test is added during execution, set up the API key through the secure platform key flow in the Codex app before running it.
