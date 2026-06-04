# Claude Code Install

Install the Python CLI first:

```bash
python3 -m pip install "dating-booster==1.0.0rc1"
dating-boost release doctor --json
```

For test installs, give the repository URL to Claude Code or another
shell-capable agent and let it clone, inspect, and install from source:

```bash
git clone https://github.com/cyberpinkman/dating-booster.git
cd dating-booster
python3 -m pip install --user -e .
python3 -m dating_boost.cli adapter claude-code install --scope user --json
python3 -m dating_boost.cli adapter claude-code doctor --data-dir ~/.dating-boost --json
```

Install the Claude Code skill into the current project:

```bash
dating-boost adapter claude-code install --scope project --target . --json
dating-boost adapter claude-code doctor --data-dir .local/dating-boost --json
```

The skill is installed at `.claude/skills/dating-booster/`.

如果希望所有 Claude Code 项目都能使用 Dating Booster，可以安装到用户级路径：

```bash
dating-boost adapter claude-code install --scope user --json
```

用户级 skill 路径是 `~/.claude/skills/dating-booster/`。

Before real dating-app work, run:

```bash
dating-boost data doctor --data-dir .local/dating-boost --json
dating-boost capabilities --json --data-dir .local/dating-boost
```

If data doctor reports `needs_migration`, run:

```bash
dating-boost data migrate --data-dir .local/dating-boost --json
```
