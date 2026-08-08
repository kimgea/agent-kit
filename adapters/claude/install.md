# Claude Code adapter

Claude Code normally discovers personal skills under
`${CLAUDE_CONFIG_DIR}/skills`, with `CLAUDE_CONFIG_DIR` defaulting to `~/.claude`.

Use `python scripts/agent_kit.py install <skill> --agent claude` to preview the
resolved source and destination. Apply only after review with `--apply --yes`.
The installer copies the skill and records ownership; it does not modify
`settings.json` or grant filesystem access.

For a skill that offers permission setup, run the installed
`scripts/setup_permissions.py --agent claude` without `--install`, review the
exact Bash, PowerShell, Read, Edit, and sandbox proposal, then explicitly apply
it. Run `claude doctor` when the CLI is available.

Use `doctor` to detect installed drift and `uninstall` to preview a recoverable
move into the agent-kit trash directory.
