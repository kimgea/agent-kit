---
name: tool-audit
description: Audit CLI tooling on this machine and how Codex or Claude Code agents use tools across sessions. Use when asked what CLI tools are installed, which tools or subcommands agents use and how often, whether agents use tools efficiently, how commands split into read/write/destructive classes, which installed tools are unused, which MCP or tool calls fail, how usage changes over time, or which read-only commands might be safe permission candidates.
---

# tool-audit

Answer tooling questions from real local data with the fixed profiles exposed by
`scripts/audit.py`. Use direct helpers only when custom filters are required.

## Bootstrap permissions safely

On first use or after relocating the skill, run
`python <skill-dir>/scripts/setup_permissions.py --agent <current-agent>` without
`--install` and show its proposal. Install only after explicit user approval by
rerunning with `--install --yes`. The bootstrap approves only `audit.py` plus one
enumerated, argument-free profile. Setup, arbitrary Python, direct helpers,
version probes, catalog writes, and custom paths remain gated. More restrictive
project or managed policies still win.

Restart Codex after installing Codex rules. Use an approved `--remove --yes` to
remove only entries recorded by setup.

## Select a fixed profile

| Question | Profile |
|---|---|
| What CLI tools are installed here? | `inventory` or `inventory-json` |
| Include uncategorized tools | `inventory-uncategorized` or `inventory-uncategorized-json` |
| How are tools used across sessions? | `usage` |
| Are agents using tools efficiently? | `usage-efficiency` |
| Which way are usage trends moving? | `usage-trends` |
| How is MCP used? | `usage-mcp` |
| Which tool calls fail? | `usage-errors` |
| Where do sessions, approvals, or autonomous loops create friction? | `usage-friction` |
| Which tools have we forgotten? | `usage-forgotten` |
| What should we allowlist next? | `config-suggest` |
| Is permission config safe or consistent? | `config-lint` |
| Audit config and suggest together | `config` |
| Record, view, or compare tooling state | `snapshot`, `snapshot-history`, or `snapshot-changes` |

Fixed profiles deliberately accept no passthrough arguments. For custom scope,
invoke `usage.py` directly with `--agent`, `--project`, `--since`, or `--until`, or
invoke `config_audit.py` with explicit custom arguments; those calls remain
approval-gated.

Before interpreting a result, read only the matching section of
[report-guide.md](references/report-guide.md): inventory, snapshots and trends,
permission configuration, or session usage and failures.

## Run the selected profile

Resolve `<skill-dir>` from the current skill location and invoke scripts by
absolute path without changing directory. Use `python3`, `python`, or Windows
`py -3`, whichever names Python 3 on the machine.

```bash
python <skill-dir>/scripts/audit.py usage-efficiency
python <skill-dir>/scripts/audit.py inventory
python <skill-dir>/scripts/audit.py config-lint
python <skill-dir>/scripts/audit.py snapshot
```

## Preserve the safety boundary

- Inventory profiles walk `PATH` without executing discovered programs. Run the
  approval-gated `inventory_versions.py` only when versions are actually needed.
- Treat permission suggestions as narrow candidates for human review, never as
  proof that a prefix is safe. The reports propose rules but do not edit agent
  configuration.
- Report transcript findings in aggregate. Never print or retain raw prompt
  samples, credentials, authorization values, or secret-bearing arguments.
- Keep ambiguous command classifications `mixed`; do not broaden them merely to
  avoid permission prompts.
- State report limitations instead of assigning wrapped or ambiguous events to
  the wrong command.
