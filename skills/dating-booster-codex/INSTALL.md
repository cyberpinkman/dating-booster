# Installing the Codex Skill

This package is the Codex-first Dating Booster workflow. It lets Codex use the
local `dating-boost` CLI for memory, context, policy, feedback, and action audit
while the host agent owns the LLM and any computer-use interaction.

## Install

Preferred GitHub install path is documented in `INSTALL_FROM_GITHUB.md`.

For local development from the repository root:

```bash
python3 -m pip install -e .
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
dating-boost capabilities --json --data-dir .local/dating-boost
```

Then compare the output with `skills/dating-booster-codex/skill-package.json`:

- `tool_version` must satisfy `dating_boost_min_version`.
- `schema_versions` must satisfy `required_schema_versions`.
- `supported_commands` must contain every `required_commands` entry.
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
compatibility checks, action-result audit, and feedback recording. The preferred
manual workflow uses `dating-boost workflow draft` to combine observation
ingest, context build, host-draft policy check, and optional feedback recording.
It does not open Tinder, use iPhone Mirroring, send messages, or call an LLM.

## First Real Manual Workflow

1. Run the startup check.
2. Ask the user to confirm that Codex may process visible dating app content.
3. Convert visible profile/chat content into the observation contract in
   `references/observation-authoring.md`.
4. Draft in the host agent and save the draft JSON.
5. Run `dating-boost workflow draft --data-dir .local/dating-boost --observation observation.json --draft draft.json --mode adaptive`.
6. Paste or send only according to the user's chosen experiment mode.
7. Record post-action evidence with `dating-boost action record-result`.
