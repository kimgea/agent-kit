# Tool-audit report guide

Read only the section matching the selected fixed profile. These details explain
how to interpret the report; they are not additional permission grants.

## Inventory

`inventory.py` walks `PATH` on every run and does not execute discovered programs.
It respects `PATHEXT` on Windows and executable bits on Unix. It labels results
with the category overlay in `inventory.py` and the read/write class from
`command-classes.tsv`; anything unrecognized is reported as uncategorized.

The OS filter suppresses Windows system plumbing and Unix system directories
while leaving common user locations such as `/usr/local` and `/opt/homebrew`
visible. On Linux, an unknown tool installed only in `/usr/bin` can therefore be
filtered as system plumbing. Use the approval-gated version probe only when paths
and classifications are insufficient.

`command-classes.tsv` is a reviewed portable baseline, not an inventory of one
machine. A specific subcommand overrides the `*` default. Local reviewed rows in
`<tool-audit-data>/command-classes.local.tsv` override the bundled baseline.

## Snapshots and trends

`usage-trends` recomputes weekly metrics while source transcripts still exist.
Snapshots preserve selected aggregate state in a private OS data directory:
`%LOCALAPPDATA%\tool-audit\<agent>` on Windows,
`${XDG_STATE_HOME:-~/.local/state}/tool-audit/<agent>` on Linux, and
`~/Library/Application Support/tool-audit/<agent>` on macOS.
`TOOL_AUDIT_DATA_DIR` overrides the base. Custom snapshot paths use
`snapshot_custom.py` and remain approval-gated.

Use trends to evaluate direction over time. Use snapshots to compare retained
points even after original transcripts or machine state change.

## Permission configuration

`config_audit.py` reads Claude `settings.json` rules or Codex `rules/*.rules`
entries without executing them.

- `config-suggest` cross-references observed usage, `read` classifications, and
  existing rules. Review whether a suggested prefix could also begin a mutating
  compound command before recommending it.
- `config-lint` reports effectively allowed destructive commands as errors,
  write/mixed commands as warnings, and network, executable, or unknown commands
  for review. In Codex, a covering `prompt` or `forbidden` rule shadows an `allow`
  rule because the most restrictive decision wins.
- `config` combines the audit and suggestion views; it still does not edit either
  permission file.

The classification catalog informs Claude and Codex audits, but a reviewed class
is evidence about command semantics rather than automatic permission approval.

## Session usage and failures

Direct Codex function calls and Claude `tool_use` records are counted exactly.
For JavaScript-wrapped Codex `exec`, the parser counts statically visible nested
call sites and literal shell commands. A call inside a programmatic loop can run
multiple times, so treat those numbers as conservative call-site counts.

`usage-errors` recognizes explicit error results, direct Codex nonzero process
records, and stable patch-failure markers. It separates known no-match or
difference statuses. When a wrapped result cannot be tied to exactly one nested
call, leave it nested or unattributed instead of guessing.

Interpret the remaining profiles as follows:

- `usage-efficiency` measures redundant directory changes, non-native search/read
  tools, repeated reads, and native-versus-shell usage.
- `usage-trends` buckets those metrics by ISO week.
- `usage-mcp` groups calls by MCP server and tool.
- `usage-friction` reports aggregate source, prompt-size, short-choice,
  continuation, next-step, repeated-issue, and guardian-decision signals. Its
  heuristic outcome categories can overlap.
- `usage-forgotten` compares installed programs with tools seen in transcripts;
  "never invoked" means unseen in the selected history, not inherently useless.

Permission-config output redacts common authorization headers, bearer tokens,
credential flags, and secret-bearing environment assignments. Treat redaction as
defense in depth, not permission to place secrets in configuration or arguments.
