# Tool audit architecture and support

## Purpose

`tool-audit` inventories CLI programs without executing them, analyzes local
Claude Code and Codex transcripts, classifies observed shell commands, and
reports narrow permission candidates. It also measures aggregate conversation,
approval, and autonomous-loop friction without printing transcript samples. It
never silently edits permission configuration.

## Installation

Install the complete `skills/tool-audit` directory into the current agent's
personal skills directory, using its normal skill installer when available.
Codex commonly uses `$CODEX_HOME/skills` (default `~/.codex/skills`), while
Claude commonly uses `~/.claude/skills` or the corresponding configured home.

On first use, preview the permission proposal without `--install`:

```bash
python <skill-dir>/scripts/setup_permissions.py --agent codex
python <skill-dir>/scripts/setup_permissions.py --agent claude
```

After a human reviews and explicitly accepts that proposal, rerun with
`--install --yes`. The setup is intentionally separate from copying the skill;
installers should not silently grant command or filesystem permissions.

## Safety model

`scripts/audit.py` is the only automatic-permission surface. It accepts one
enumerated profile and no additional arguments. The profiles dispatch to
predetermined reports and the default snapshot location.

These capable helpers intentionally remain approval-gated:

| Helper | Why it is gated |
|---|---|
| `setup_permissions.py` | Modifies Codex or Claude configuration |
| `inventory_versions.py` | Executes programs discovered on `PATH` |
| `inventory_learn.py` | Writes generated discovery data |
| `snapshot_custom.py` | Accepts an arbitrary history path |
| Direct report scripts | Accept custom filters and configuration paths |

Codex setup generates a dedicated `rules/tool-audit.rules`. Claude setup adds
exact, non-wildcard `Bash(...)` entries and the Claude snapshot directory to
the sandbox write allowlist. Setup is a dry run unless the user explicitly
confirms installation.

The Codex config audit evaluates effective automatic allowances: an `allow`
entry fully covered by a `prompt` or `forbidden` prefix is not reported as
auto-approved. This follows Codex's most-restrictive-rule-wins behavior.

## Catalog versus local discovery

`references/command-classes.tsv` is a committed, curated baseline describing
common command semantics. It is not a list of programs installed on the
maintainer's machine and must not be generated automatically.

`inventory.py` discovers the current machine on every run. `inventory_learn.py`
can stage unknown names in the private runtime data directory for review. That
generated `discovered-tools.tsv` is local state and must not be committed.

After reviewing a machine-specific command, put its TSV row in
`<tool-audit-data>/command-classes.local.tsv`. Local rows override the bundled
baseline. The skill never promotes discoveries automatically because a command
name and version do not prove that its behavior is read-only.

## Runtime paths

The skill honors `CODEX_HOME` and `CLAUDE_CONFIG_DIR` for agent state. Runtime
audit data uses:

| Platform | Base path |
|---|---|
| Linux | `${XDG_STATE_HOME:-~/.local/state}/tool-audit/<agent>` |
| Windows | `%LOCALAPPDATA%\tool-audit\<agent>` |
| macOS | `~/Library/Application Support/tool-audit/<agent>` |

Set `TOOL_AUDIT_DATA_DIR` to place the `tool-audit` directory under a custom
shared parent. Installed skill files are resolved relative to each script, so
the skill directory itself may be relocated. Rerun permission setup after a
relocation because generated commands contain absolute paths.

## Compatibility

| Environment | Current verification |
|---|---|
| Codex on Linux | Real local transcripts and command-policy checks |
| Claude on Linux | Synthetic transcripts and temporary settings fixtures |
| Codex on Windows | Windows CI and platform-specific unit tests |
| Claude on Windows | Windows CI and configuration fixtures |

Python 3 is required. Direct Codex tool calls and Claude `tool_use` records are
counted exactly. JavaScript-wrapped Codex `exec` calls are extracted statically;
a call site inside a loop can therefore represent multiple runtime calls.

`usage-errors` recognizes explicit `is_error` results, direct Codex shell
process exit records, and stable patch-failure markers. Known comparison or
no-match statuses are reported separately. Newer wrapped `exec` transcripts do
not always preserve structured nested result metadata, so ambiguous failures
remain attributed to the wrapper rather than guessed.

`usage-friction` reports only aggregate counts and byte sizes. It separates
interactive, autonomous, Claude, and recognized Codex subagent sources; reports
short-choice, continuation, next-step, and correction signals; summarizes role
prompt size and completion signals; and counts parseable guardian decisions.
It does not retain or print message samples. Outcome categories are explicitly
heuristic and may overlap.

Permission-config output redacts common authorization headers, bearer tokens,
credential flags, and secret-bearing environment assignments before printing.
This is defense in depth: do not place credentials in permission rules, command
arguments, or committed fixtures.

## Runtime content boundary

`SKILL.md` contains fixed-profile selection, invocation, and universal safety
invariants. `references/report-guide.md` contains operation-specific semantics and
limitations and should be loaded only for the selected report family. The
classification TSV remains a script-consumed runtime asset rather than prose that
must be loaded for every audit.

Keep architecture, compatibility evidence, and extension procedures in this
document. The installed skill should name Codex or Claude Code only when their
state locations, permission configuration, or transcript formats change runtime
behavior.

## Maintainer checklist

- Add a tool classification in `references/command-classes.tsv` and add its
  category label in `inventory.py` when applicable. Verify upstream behavior and
  test every important read/write boundary.
- Add a measured anti-pattern in `usage.py` and cover it with synthetic transcript
  fixtures.
- Keep every safe `audit.py` profile argument-free. Update setup expectations,
  test rejection of trailing arguments, rerun permission setup, and verify Codex
  output with `codex execpolicy check` when available.
- When changing transcript parsing, preserve the Claude report concepts (`Bash`,
  `Read`, `Grep`, `Glob`, `--settings`, and `CLAUDE_CONFIG_DIR`) through the
  normalization layer and add minimal raw JSONL fixtures for both supported
  agents.
- Keep the skill plain Markdown plus dependency-free Python. Codex
  `agents/openai.yaml` metadata is intentionally ignored by Claude Code.

Do not commit generated rules, agent settings, snapshots, permission state, or
machine-specific discovery output.
