# Install From GitHub

Use Codex's `skill-installer` to install this skill from the repository path:

```text
Install the Codex skill from https://github.com/cyberpinkman/dating-booster/tree/v0.1.7/skills/dating-booster-codex
```

Restart Codex after installation so the new skill is discovered.

On first use, the skill runs:

```bash
python3 scripts/doctor.py --json --data-dir .local/dating-boost
```

If the local `dating-boost` CLI is missing or too old, run:

```bash
python3 scripts/bootstrap_cli.py
```

Then run the doctor again. Do not observe dating app content until doctor and
`dating-boost capabilities --json --data-dir .local/dating-boost` both pass.
