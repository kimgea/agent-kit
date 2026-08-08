# Todo capture architecture and support

## Purpose

`todo-capture` stores consciously deferred work as pickup-pointer Markdown
entries shared by Codex and Claude Code. Entry files are authoritative;
`INDEX.md` is a deterministic derived view of active entries.

## Installation and setup

Install the complete `skills/todo-capture` directory into each harness that
should discover it: normally `$CODEX_HOME/skills` (default `~/.codex/skills`)
and `$CLAUDE_CONFIG_DIR/skills` (default `~/.claude/skills`). Installed copies
are deployments; make changes in this repository and reinstall after testing.

From each installed copy, preview its harness-specific proposal:

```bash
python <codex-skill>/scripts/setup_permissions.py --agent codex
python <claude-skill>/scripts/setup_permissions.py --agent claude
```

Only after a human accepts the preview, rerun with `--install --yes`. Setup is
idempotent, tracks only entries it owns, migrates its previously recorded Claude
rules, and supports `--remove --yes`. More restrictive managed policy still wins.

## Permission boundary

Generated Codex and Claude shell rules target only the absolute
`scripts/todo_safe.py` path plus one known subcommand. The dispatcher accepts
free-form todo data but has no `--dir`, command passthrough, or executable input.
`scripts/todo.py` retains custom `--dir` support and remains approval-gated.

Claude setup also grants the data directory as an additional working directory,
allows reading the store, permits direct edits only to active entry bodies, and
adds the directory to `sandbox.filesystem.allowWrite`
for the Python dispatcher. Derived indexes, archives, locks, and the setup
vocabulary and ownership record are outside direct Edit rules. The fixed
`domain-add` command performs validated vocabulary changes. On native Windows it
generates PowerShell and Git-Bash command forms; on Linux and macOS it generates
Bash forms. Codex setup writes one dedicated generated rules file.

## Data and consistency model

| Platform | Shared store |
|---|---|
| Linux | `${XDG_STATE_HOME:-~/.local/state}/todo-capture` |
| Windows | `%LOCALAPPDATA%\todo-capture` |
| macOS | `~/Library/Application Support/todo-capture` |

`TODO_CAPTURE_DATA_DIR` replaces the platform base and the skill appends
`todo-capture`. Direct `todo.py <command> --dir <path>` selects an exact custom
store for an explicitly approved call.

Repository, domain, slug, and id values are validated single path components.
Local vocabulary rows are validated before use, custom-vocabulary symlinks are
rejected, entry traversal skips symlinks, and computed paths are checked for
containment. Newline-bearing metadata is rejected or safely quoted.

`new` accepts the complete pickup-pointer body as validated section arguments,
so an agent does not need direct filesystem access to create a useful entry.
`domain-add` similarly updates the machine-local vocabulary atomically. These
fixed-store commands make the full capture workflow available to Codex without
granting broad write access to the shared data directory.

Mutations take a cross-platform OS file lock. Files are written to a temporary
file, flushed, and atomically replaced; `done` moves the resolved entry without
overwriting an archive. Every successful mutation rebuilds `INDEX.md` from the
active files, so concurrent sessions cannot lose index updates. `check` is
read-only and reports structural, metadata, vocabulary, duplicate-id, symlink,
and index drift. On POSIX, generated directories use `0700` and files use `0600`.
The Claude permission ownership record lives under the Claude configuration
directory, not inside the agent-editable todo store, and is validated before it
can remove any rule.

## Compatibility and validation

The skill is dependency-free Python 3. Repository CI runs its lifecycle,
permission, safety-boundary, concurrency, storage-mode, and path-resolution tests
on Python 3.11 and 3.13 for both Ubuntu and Windows. Local installation should
also be checked with `claude doctor` and Codex policy evaluation when those CLIs
are present.

## Runtime content boundary

`SKILL.md` contains the fixed command workflow, approval boundary, shared-store
fact, and data-integrity invariants needed during normal use. The bundled
`references/conventions.md` is runtime documentation for tasks that require the
full schema, naming rules, layout, or manual diagnosis; the scripts consume the
template and baseline vocabulary directly.

Keep installation architecture, support evidence, and extension procedures in
this document. Mention Codex or Claude Code in the installed instructions only
when their different configuration or shared data behavior changes the action an
agent should take.

## Maintainer checklist

- Keep machine-specific domains in `<data-store>/domains.local.tsv`; do not
  commit them.
- Change the entry shape in `references/TEMPLATE.md`; `new` consumes it directly.
- Add broadly portable domains to `references/domains.tsv`; add machine-specific
  domains through the fixed `domain-add` command.
- Keep direct custom paths and setup/configuration writes outside automatic
  permission rules.
- Add lifecycle and permission-boundary tests before extending a command parser.
- Keep a new subcommand approval-gated until its parser and effects have boundary
  tests. Add it to `_common.py: SAFE_SUBCOMMANDS` only after explicit safety
  review, then update and rerun permission setup.
- Test repeated install and exact removal when changing permission setup.
- Keep `todo.py` and `_common.py` dependency-free and cross-platform.
- Never commit generated rules, settings, permission state, todo data, or locks.
