# Codex adapter

Codex normally discovers personal skills under `${CODEX_HOME}/skills`, with
`CODEX_HOME` defaulting to `~/.codex`.

Use `python scripts/agent_kit.py install <skill> --agent codex` to preview the
resolved source and destination. Apply only after review with `--apply --yes`.
The installer copies the skill and records ownership; it does not run the
skill's permission bootstrap.

For a skill that offers permission setup, run the installed
`scripts/setup_permissions.py --agent codex` without `--install`, review the
proposal, then explicitly apply it. Restart Codex after rule changes.

Use `doctor` to detect installed drift and `uninstall` to preview a recoverable
move into the agent-kit trash directory.
