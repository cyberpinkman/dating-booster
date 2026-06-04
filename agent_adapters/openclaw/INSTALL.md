# Install Dating Booster For OpenClaw-Compatible Hosts

## From Source

```bash
git clone https://github.com/cyberpinkman/dating-booster.git
cd dating-booster
python3 -m pip install --user -e .
dating-boost adapter openclaw install --scope project --target . --json
dating-boost adapter openclaw doctor --data-dir .local/dating-boost --json
```

The install command copies the skill and shared references into:

```text
.openclaw/skills/dating-booster/
```

## User Install

```bash
dating-boost adapter openclaw install --scope user --json
dating-boost adapter openclaw doctor --data-dir ~/.dating-boost --json
```

This writes:

```text
~/.openclaw/skills/dating-booster/
```

## Hermes Compatibility

Hermes should install the same OpenClaw-compatible package:

```bash
dating-boost adapter hermes install --scope project --target . --json
dating-boost adapter hermes doctor --data-dir .local/dating-boost --json
```

The Hermes commands are compatibility wrappers. They intentionally do not
install a separate `.hermes` package.

## Verification

```bash
dating-boost release doctor --json
dating-boost data doctor --data-dir .local/dating-boost --json
dating-boost capabilities --json --data-dir .local/dating-boost
dating-boost-host-loop doctor --adapter-package agent_adapters/openclaw/adapter-package.json --data-dir .local/dating-boost --app-id tinder --json
```
