# Installing the Codex Skill

This package is the Codex-first Dating Booster workflow. It lets Codex use the
local `dating-boost` CLI for memory, context, policy, feedback, and action audit
while the host agent owns ordinary draft assistance. TaShuo mac-ios-app
ManagedRun uses the configured model and four-part action executor under host supervision.

## Install

For test installs, give the repository URL to Codex or another shell-capable
agent and let it clone, inspect, and install from source:

```bash
git clone https://github.com/cyberpinkman/dating-booster.git
cd dating-booster
python3 -m pip install --user -e .
python3 -m dating_boost.cli adapter codex install --scope user --json
python3 -m dating_boost.cli adapter codex doctor --data-dir ~/.dating-boost --json
```

For local development from the repository root, install the test dependencies and refresh the user-level skill:

```bash
python3 -m pip install -e ".[test]"
python3 -m dating_boost.cli adapter codex install --scope user --json
```

If you are developing inside this repository, Codex can also read the skill
directly from `skills/dating-booster-codex` without copying it.

## Startup Check

Run the full checks after installation, updates, migration, permission changes,
or for explicit diagnostics. Daily ManagedRun reuses the verified setup and
starts with `manage start`; follow the flagship section in `references/workflows.md`.

When these checks are due, verify the installed copy before observing visible dating app content. A user installation uses the skills directory under `CODEX_HOME` (default `~/.codex`).

```bash
dating-boost adapter codex doctor --scope user --data-dir .local/dating-boost --json
```

For a project installation, use `--scope project` and the same project directory or `--target` used at install.

To check a source package directly or diagnose CLI bootstrap, run the skill doctor:

```bash
python3 skills/dating-booster-codex/scripts/doctor.py --json --data-dir .local/dating-boost
```

If doctor returns `needs_bootstrap`, run:

```bash
python3 skills/dating-booster-codex/scripts/bootstrap_cli.py
```

Then run:

```bash
dating-boost release doctor --json
dating-boost data doctor --data-dir .local/dating-boost --json
dating-boost capabilities --json --data-dir .local/dating-boost
```

Then compare the output with `skills/dating-booster-codex/skill-package.json`:

- `tool_version` must satisfy `dating_boost_min_version`.
- `schema_versions` must satisfy `required_schema_versions`.
- `supported_commands` must contain every `required_commands` entry.
- Run `dating-boost data migrate --data-dir .local/dating-boost --json` if
  data doctor reports `needs_migration`.
- Public production requires encrypted storage. Data doctor should report
  `encryption.status: encrypted`; on macOS the production key provider is
  Keychain.
- For compatibility managed sessions, check `dating-boost daemon status --data-dir .local/dating-boost --json`
  and use `dating-boost safety status --data-dir .local/dating-boost --json`.
- A different `source_spec_commit` is a warning if version, schema, and command
  checks pass.

Stop before observing dating app content if compatibility fails.

## Fixture Smoke Test

Run the complete local fixture workflow:

```bash
DATING_BOOST_KEY_PROVIDER=local \
python3 scripts/agent_native_smoke.py --data-dir .local/dating-boost-smoke
```

If `--data-dir` is omitted, the smoke test writes to `.local/dating-boost-smoke`
so the generated artifacts remain inspectable after the script exits.

The smoke test runs capability discovery, profile initialization, observation
ingest, match lookup, context build, host-draft policy check, skill-package
compatibility checks, data doctor/migration/export, action-result audit, and feedback recording. The manual
workflow keeps observation ingest, context build, host-draft policy check, and
optional feedback recording as explicit CLI steps.
It does not open Tinder, use iPhone Mirroring, send messages, or call an LLM.

For real Tinder stage-mode private smoke, read
`references/production-stage-runbook.md`. The run must stop at
`staged_waiting_user_confirmation` and save replay, audit export, and staged
verification artifacts.

## Public Production Defaults

- macOS is the only public GUI platform target.
- SQLite payloads are encrypted by default.
- Backups require a recovery passphrase from `DATING_BOOST_RECOVERY_PASSPHRASE`,
  or `--recovery-passphrase-file`; the backup stores a passphrase-wrapped
  recovery key, not an unwrapped local data key. Do not pass recovery
  passphrases through argv.
- The local daemon supervises locks, heartbeat, recovery, and safety state; it
  does not observe or click apps.
- Diagnostics are local redacted bundles only; there is no network telemetry.
- Live send requires explicit bounded authorization, an unpaused safety switch,
  exact staged-text verification, and post-action verification. TaShuo mac-ios-app
  full management uses flagship ManagedRun; the host immediately follows
  `manage start` with `manage run --wait` for the same run.
  Compatibility sends use `managed-session` or `dating-boost-host-loop` with
  `--send-mode live --managed-gui-send` and `live_send: true` in authorization. The direct
  `harness <app> send-message --authorization --action-request` command is
  executor-internal only; do not handcraft action requests.

## First Real Manual Workflow

1. Run the startup check.
2. Ask the user to confirm the target app and that Codex may process its visible
   content.
3. Select the app/runtime in the same data dir. Start a support session only for
   a real-GUI Canary, explicit diagnostics, or support-bundle collection.
4. Convert visible profile/chat content into the observation contract in
   `references/observation-authoring.md`.
5. Run `dating-boost memory ingest-observation --data-dir .local/dating-boost --input observation.json`.
6. Run `dating-boost context build --data-dir .local/dating-boost --match-id MATCH_ID --mode adaptive` and save the context JSON.
7. Draft in the host agent and save the draft JSON.
8. Run `dating-boost policy check-draft --input draft.json --context context.json`.
9. This manual draft-assistance flow defaults to stage-only. For explicit full
   management use ManagedRun on TaShuo mac-ios-app, or managed-session/host-loop
   for compatibility workflows; direct harness send is executor-internal and
   action requests must not be handcrafted.
10. Record stage-only evidence with `dating-boost operator record-stage-result`,
    or record a verified managed live-send result with
    `dating-boost action record-result`.
11. If a support session was started, stop it; export a strict support bundle
    only when diagnostics are needed.
