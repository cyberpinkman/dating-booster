# Dating Booster Project Map

This repository is structured around local-first dating workflow assistance:
the host agent observes the app UI, Dating Booster owns local memory, policy,
planning, audit, and safe staging contracts.

## Top-Level Layout

- `dating_boost/`: Python package and CLI entrypoints.
- `dating_boost/core/`: storage, policy, planning, diagnostics, production
  data handling, daemon/safety state, and native GUI harness adapters.
- `dating_boost/host_loop.py`: supervised host-loop runner for app-specific
  work items.
- `dating_boost/intelligence/`: reply generation backends and prompt wiring.
- `dating_boost/perception/`: screenshot and observation contract helpers.
- `dating_boost/policy/`: action and content safety rules.
- `dating_boost/evals/`: conversation and reply quality evaluation helpers.
- `app_profiles/`: app-specific product contracts. See
  `app_profiles/README.md`.
- `skills/dating-booster-codex/`: installable Codex skill, scripts, examples,
  and operational references.
- `scripts/`: local smoke and host-loop helper scripts.
- `tests/`: contract, policy, storage, host-loop, skill, and harness tests.
- `docs/superpowers/specs/`: product/architecture specs used while building
  the project.
- `.github/workflows/`: CI and release workflows.

## Current App Targets

| App | Current support | Native harness | Send ownership |
| --- | --- | --- | --- |
| Tinder | Host-loop, profile/chat navigation, observation, draft workflow | iPhone Mirroring on macOS | Stage/navigation only; no autonomous GUI send harness |
| WeChat | App profile, host-loop app id, desktop observation, draft staging | macOS WeChat desktop window | Stage draft only; never presses Enter or clicks Send |
| Bumble | App contract only | None | Not supported |
| Ta Shuo | App contract only | None | Not supported |

## Runtime Surfaces

- CLI: `dating_boost/cli.py` exposes data, policy, workflow, diagnostics,
  release, daemon/safety, confirmation, and harness commands.
- Host loop: `dating-boost-host-loop` supervises local work directories,
  authorization, recovery, and staged/live send mode checks.
- GUI harness: `dating_boost/core/gui_harness.py` is the only place that should
  contain native app-window automation details.
- Capabilities: `dating_boost/core/capabilities.py` is the machine-readable
  startup contract for host agents and skill installers.
- Skill: `skills/dating-booster-codex/SKILL.md` is the user-facing Codex
  operating contract; references under `skills/dating-booster-codex/references/`
  must stay aligned with CLI capabilities.

## App Expansion Path

1. Add or update `app_profiles/<app_id>.json`.
2. Decide the support level: contract-only, native observation, native
   navigation, native draft staging, or host-loop integration.
3. If native GUI support is needed, add the backend-specific adapter in
   `dating_boost/core/gui_harness.py`.
4. Expose app-specific commands in `dating_boost/cli.py` only after the harness
   contract is testable.
5. Add supported commands/capability flags in
   `dating_boost/core/capabilities.py`.
6. Add deterministic fixtures under `tests/fixtures/` and focused tests under
   `tests/`.
7. Update `README.md`, `app_profiles/README.md`, and the Codex skill references.
8. Run targeted unit tests plus `dating-boost capabilities --json` before
   publishing.

## Non-Negotiable Boundaries

- Do not add private APIs, scraping bypasses, anti-detection logic, or account
  scale-out automation.
- Do not let a harness send messages, likes, reports, payments, calls, or
  profile edits unless the policy, confirmation, staged-text verification, and
  post-action verification contracts explicitly support that action.
- Prefer paste-based draft staging for Chinese text; direct typing can corrupt
  text on both mirrored mobile apps and desktop apps.
- Treat raw OCR/screenshot content as sensitive. Public logs and diagnostics
  should use redacted layout hints.

## Useful Verification

```bash
python3 -m unittest tests.test_gui_harness tests.test_skill_package
python3 -m unittest tests.test_operator_host_loop.OperatorHostLoopTests.test_wechat_host_loop_init_writes_wechat_authorization_template
python3 -m py_compile dating_boost/core/gui_harness.py dating_boost/cli.py dating_boost/core/capabilities.py dating_boost/host_loop.py
```
