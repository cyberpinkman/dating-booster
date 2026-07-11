# Production Integrity Fixes Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make encrypted SQLite the canonical runtime store, reject unbound operator results before mutation, make built wheels self-contained, prevent adapter-resource drift, and enforce the intended application/core boundary in CI.

**Architecture:** `JsonStorage` remains the repository-facing API, but new and migrated data directories persist only through `ProductionDataStore`; filesystem JSON is supported only as an explicit pre-migration legacy format. Operator result ingestion validates the current work item before any audit or automation mutation. Runtime profiles and installable adapter resources are packaged under `dating_boost/resources` and checked against source copies. TaShuo release workflows and the native GUI implementation live under app/harness packages, with compatibility imports kept intentionally thin.

**Tech Stack:** Python 3.11+, SQLite/WAL, existing `PayloadCipher`, `unittest`/pytest, setuptools, Ruff, mypy, pytest-cov, GitHub Actions.

**Execution constraint:** Do not create commits unless the user explicitly requests them. Preserve unrelated worktree state.

---

### Task 1: Make encrypted SQLite canonical and remove split-brain writes

**Files:**
- Modify: `tests/test_storage.py`
- Modify: `tests/test_production_data.py`
- Modify: `dating_boost/core/storage.py`
- Modify: `dating_boost/core/production_store_schema.py`
- Modify: `dating_boost/core/production_store_records.py`
- Modify: `dating_boost/core/operator.py`
- Modify: `dating_boost/core/runtime_scope.py`
- Modify: `dating_boost/core/daemon.py`
- Modify: `dating_boost/host_loop.py`

**Step 1: Write failing storage tests**

Add tests proving that a fresh `JsonStorage` write creates an encrypted SQLite store without a plaintext JSON mirror, migrated source JSON is removed after an encrypted backup snapshot exists, concurrent appends preserve every distinct event, and `data doctor` blocks plaintext legacy residue in a migrated directory.

**Step 2: Run the tests to verify the red state**

Run: `DATING_BOOST_KEY_PROVIDER=local python3 -m pytest tests/test_storage.py tests/test_production_data.py -q`

Expected: failures showing plaintext files remain, fresh writes do not initialize SQLite, and doctor ignores residue.

**Step 3: Implement the canonical-store contract**

Add an empty-store initializer and exact document/stream deletion methods to `ProductionDataStore`. Route `JsonStorage` reads/writes/appends/deletes through SQLite whenever the database exists; initialize encrypted SQLite on the first write to a clean root; retain locked filesystem operations only for legacy pre-migration roots. During migration, validate first, commit encrypted rows, create an encrypted SQLite snapshot, then remove legacy JSON/JSONL sources. Extend doctor output with a plaintext-residue check.

**Step 4: Replace direct managed-state file deletion/read fallbacks**

Use the storage API for operator, daemon, and runtime-scope deletion. Make host-loop’s operator fallback read through `JsonStorage`, so canonical SQLite state remains resumable without plaintext mirrors.

**Step 5: Run focused and adjacent tests**

Run: `DATING_BOOST_KEY_PROVIDER=local python3 -m pytest tests/test_storage.py tests/test_production_data.py tests/test_runtime_scope.py tests/test_daemon.py tests/test_operator_session.py tests/test_operator_host_loop.py -q`

Expected: PASS.

### Task 2: Bind operator results before any state mutation

**Files:**
- Modify: `tests/test_operator_session.py`
- Modify: `dating_boost/core/operator.py`

**Step 1: Write failing result-binding tests**

Add action and stage tests that submit a mismatched `action_request_id` while a send work item is current. Assert that ingestion raises a contract error, audit streams and automation state remain unchanged, the cycle send count is unchanged, and the current work item remains active. Add a no-current-item rejection case.

**Step 2: Run the tests to verify the red state**

Run: `DATING_BOOST_KEY_PROVIDER=local python3 -m pytest tests/test_operator_session.py -q -k 'result and (mismatch or current)'`

Expected: failures demonstrating mutation before binding validation.

**Step 3: Add preflight binding validation**

Validate active session, current `send_message` work item, `action_request_id`, target, action, payload hash, and precondition hash before appending an audit event or applying automation state. Use the validated current item for outbound-turn recording and make mismatches explicit errors rather than silent no-ops.

**Step 4: Run operator and host-loop regressions**

Run: `DATING_BOOST_KEY_PROVIDER=local python3 -m pytest tests/test_operator_session.py tests/test_operator_host_loop.py tests/test_operator_host_loop_managed_send.py tests/test_operator_host_loop_live_guards.py -q`

Expected: PASS.

### Task 3: Make the wheel self-contained

**Files:**
- Add: `dating_boost/resources/app_profiles/*.json`
- Add: `dating_boost/resources/schemas/app_profile.schema.json`
- Modify: `dating_boost/apps/registry.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_app_profiles.py`
- Modify: `tests/test_ci_config.py`
- Modify: `.github/workflows/ci.yml`

**Step 1: Write failing package-resource tests**

Require packaged app profiles/schema to match the repository source byte-for-byte and require CI to install the built wheel into an isolated environment and run `dating-boost capabilities` outside the checkout.

**Step 2: Run the tests to verify the red state**

Run: `python3 -m pytest tests/test_app_profiles.py tests/test_ci_config.py -q`

Expected: failures because packaged profiles and the isolated wheel smoke do not exist.

**Step 3: Package profiles and load them via importlib.resources**

Copy the authoritative profile/schema resources into `dating_boost/resources`, include them in setuptools package data, and make the registry load packaged resources independent of the repository layout.

**Step 4: Add and run a real wheel smoke**

Build the wheel, install it into a temporary virtual environment, change to `/tmp`, and verify that capabilities reports all four app profiles.

Expected: PASS with `bumble`, `tashuo`, `tinder`, and `wechat` present.

### Task 4: Eliminate Codex adapter source/package drift

**Files:**
- Modify: `dating_boost/resources/agent_adapters/codex/dating-booster-codex/SKILL.md`
- Modify: `dating_boost/resources/agent_adapters/codex/dating-booster-codex/skill-package.json`
- Modify: `tests/test_skill_package.py`
- Modify: `dating_boost/core/release.py`
- Modify: `tests/test_public_production.py`

**Step 1: Write failing parity and release-doctor tests**

Compare all installable Codex adapter files against `skills/dating-booster-codex` and assert release doctor reports a specific issue when a packaged copy differs.

**Step 2: Run the tests to verify the red state**

Run: `python3 -m pytest tests/test_skill_package.py tests/test_public_production.py -q -k 'parity or release_doctor'`

Expected: failures on the known SKILL/metadata drift.

**Step 3: Synchronize resources and enforce parity**

Update the packaged copies from their source files and add release-doctor tree hashing/parity validation so source-only checks cannot approve stale wheel resources.

**Step 4: Run adapter/release regressions**

Run: `python3 -m pytest tests/test_skill_package.py tests/test_app_adapters.py tests/test_public_production.py -q`

Expected: PASS.

### Task 5: Restore ownership boundaries and add quality gates

**Files:**
- Move implementation: `dating_boost/core/gui_harness.py` to `dating_boost/harness/native_gui.py`
- Add compatibility facade: `dating_boost/core/gui_harness.py`
- Move implementation: `dating_boost/core/tashuo_*.py` to `dating_boost/apps/tashuo/`
- Add compatibility facades: `dating_boost/core/tashuo_*.py`
- Modify imports in: `dating_boost/apps/iphone_targeting_common.py`, `dating_boost/apps/legacy.py`, `dating_boost/core/capabilities.py`, `dating_boost/cli_harness.py`, `scripts/tashuo_*.py`, and affected tests
- Add: `tests/test_architecture_boundaries.py`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_ci_config.py`

**Step 1: Write failing architecture and CI tests**

Assert that core compatibility facades contain no app/harness implementation, implementation modules reside under their owning package, and CI executes critical Ruff checks, scoped strict mypy checks, coverage threshold enforcement, and the isolated wheel smoke.

**Step 2: Run the tests to verify the red state**

Run: `python3 -m pytest tests/test_architecture_boundaries.py tests/test_ci_config.py -q`

Expected: failures against current ownership and CI configuration.

**Step 3: Move implementations and retain compatibility imports**

Move code mechanically, update internal imports to the owning packages, and leave only explicit re-export facades in `core` for downstream compatibility. Keep behavior unchanged.

**Step 4: Add executable quality gates**

Add pinned-major dev dependencies and minimal enforceable Ruff/mypy/coverage configuration. Run the exact commands locally and tune only to existing intentional dynamic boundaries, not by blanket exclusion.

Run: `python3 -m ruff check dating_boost tests scripts`

Run: `python3 -m mypy`

Run: `DATING_BOOST_KEY_PROVIDER=local python3 -m pytest --cov=dating_boost --cov-report=term --cov-fail-under=60`

Expected: PASS.

### Task 6: Final release verification

**Files:**
- Verify all modified files

**Step 1: Run the complete suite**

Run: `DATING_BOOST_KEY_PROVIDER=local python3 -m pytest -q`

Expected: all tests pass.

**Step 2: Run static, packaging, and release checks**

Run: `python3 -m ruff check dating_boost tests scripts`

Run: `python3 -m mypy`

Run: `python3 -m build`

Run the isolated wheel capabilities smoke from `/tmp`.

Run: `DATING_BOOST_KEY_PROVIDER=local python3 scripts/agent_native_smoke.py`

Run: `python3 -m dating_boost.cli release doctor --json`

Run: `python3 -m compileall -q dating_boost scripts tests`

Run: `git diff --check`

Expected: every command succeeds and the wheel reports all supported app profiles.

**Step 3: Review the final diff**

Confirm no plaintext fixture/data artifacts, generated build directories, local keys, or unrelated changes are included. Record residual risks and exact verification results in the final response.
