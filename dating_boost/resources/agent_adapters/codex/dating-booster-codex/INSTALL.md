# Installing the Codex Skill

This package is the Codex-first Dating Booster workflow. It lets Codex use the
local `dating-boost` CLI for memory, context, policy, feedback, and action audit
while the host agent owns the LLM and any computer-use interaction.

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

For local development from the repository root:

```bash
python3 -m pip install -e ".[test]"
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/dating-booster-codex "${CODEX_HOME:-$HOME/.codex}/skills/"
```

If you are developing inside this repository, Codex can also read the skill
directly from `skills/dating-booster-codex` without copying it.

## Startup Check

Before any host agent observes visible dating app content, choose a local data
directory and run the skill doctor:

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
- For managed sessions, check `dating-boost daemon status --data-dir .local/dating-boost --json`
  and use `dating-boost safety status --data-dir .local/dating-boost --json`.
- A different `source_spec_commit` is a warning if version, schema, and command
  checks pass.

Stop before observing dating app content if compatibility fails.

## Fixture Smoke Test

Run the complete local fixture workflow:

```bash
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
- Live send is not the default. It requires `--send-mode live`, `live_send: true`
  in authorization, an unpaused safety switch, staged-text verification, and
  post-action verification. Agent-facing live sends must use `managed-session`
  or `dating-boost-host-loop` with `--managed-gui-send`. The direct
  `harness <app> send-message --authorization --action-request` command is
  executor-internal only; do not handcraft action requests.

## First Real Manual Workflow

1. Run the startup check.
2. Ask the user to confirm that Codex may process visible dating app content.
3. Convert visible profile/chat content into the observation contract in
   `references/observation-authoring.md`.
4. Run `dating-boost memory ingest-observation --data-dir .local/dating-boost --input observation.json`.
5. Run `dating-boost context build --data-dir .local/dating-boost --match-id MATCH_ID --mode adaptive` and save the context JSON.
6. Draft in the host agent and save the draft JSON.
7. Run `dating-boost policy check-draft --input draft.json --context context.json`.
8. Paste or send only according to the user's chosen experiment mode.
9. Record stage-only evidence with `dating-boost operator record-stage-result`, or live-send post-action evidence with `dating-boost action record-result`.
