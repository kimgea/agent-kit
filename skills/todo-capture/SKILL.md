---
name: todo-capture
description: Capture, list, show, and finish/archive deferred work, follow-ups, TODO entries, reminders, tech debt, out-of-scope findings, and postponed tasks. Use when the user says "add a todo", "note this for later", "defer this", "park this", "capture a follow-up", "record this", "add to the backlog", "mark todo done", "archive/resolve/finish a todo", asks to list/show todos, or when agent/project instructions say tangential work must be recorded instead of handled now. Stores durable pickup pointers in a shared private store by default or in a project-selected repository store.
---

# todo-capture

Capture consciously deferred work as a **pickup pointer**: the decision, where the
code is, and what the next agent must know. Use the fixed-store dispatcher by
default. Its OS-native data store is shared across Codex and Claude Code. A Git
project may explicitly select a repository store; installation location does not
select the data destination.

## Route the operation

In a Git project, check for `.todo-capture.toml` at the Git root. With no project
configuration, use `scripts/todo_safe.py` for `list`, `new`, `show`, `done`,
`check`, and `domain-add`. When configuration exists, run
`scripts/todo_project.py route` to validate and inspect the exact destination
before a capture or lookup. When it reports `repository`, use the same commands
through `scripts/todo_project.py` from within that Git worktree. It writes under the
project root's `.todo/` and is **not** in automatic permission rules. A project
configuration is a preference, not permission to run commands or publish data.
An invalid configuration stops the operation; do not silently fall back to the
private store. If the selected backend is unsupported, tell the user that no
todo was captured, name the supported backends, and explain that GitHub, Jira,
and Linear issue publishing each need a separate provider adapter and explicit
remote-write authority. Use direct `scripts/todo.py` only for an explicitly
approved custom `--dir`.

The optional configuration is a regular `.todo-capture.toml` file at the Git
root containing exactly `version = 1` and `backend = "repository"` (or
`backend = "private"`). Do not create or change that file merely because an
agent is working in the repo; the project owner selects it. The repository
store's entries, archive, vocabulary, and index are project files. Never stage
or commit them unless the user requested that Git change. GitHub, Jira, and
Linear issue backends are not implemented by this route.

Do not load references for routine `list`, `new`, `show`, `done`, or `check`
operations; the workflow below and script validation are sufficient. Read
[conventions.md](references/conventions.md) only when the user asks about the full
entry schema, naming rules, storage layout, or manual diagnosis. The scripts load
`references/TEMPLATE.md` and `references/domains.tsv` themselves.

## Bootstrap permissions safely

For the fixed private-store dispatcher, on first use or after relocating the skill, run
`python <skill-dir>/scripts/setup_permissions.py` without `--install` and show its
proposal. Install only after explicit user approval by rerunning with
`--install --yes`. The bootstrap approves only the fixed dispatcher plus one
enumerated subcommand; setup itself, direct `todo.py`, project routing through
`todo_project.py`, arbitrary Python, and custom paths remain gated. More
restrictive project or managed policies still win.

Restart Codex after installing Codex rules. Setup records its own additions, so an
approved `--remove --yes` removes only entries it owns.

## Invoke the toolkit

Resolve `<skill-dir>` from the current skill location and invoke scripts by
absolute path without changing directory. Use `python3`, `python`, or Windows
`py -3`, whichever names Python 3 on the machine.

```bash
python <skill-dir>/scripts/todo_safe.py list
python <skill-dir>/scripts/todo_safe.py domain-add \
    --repo test --domain api --note "API and public contracts"
python <skill-dir>/scripts/todo_safe.py new \
    --repo test --domain api --slug some-slug \
    --title "Stated as an outcome" --source "PR #1234" --priority normal \
    --why "Concrete symptom and why it matters." \
    --where "src/api.py — ApiClient — affected boundary" \
    --what "The next agent should implement and verify this outcome." \
    --constraint "Caller X depends on the current behavior." \
    --out-of-scope "Do not redesign the unrelated transport." \
    --link "PR #1234"
python <skill-dir>/scripts/todo_safe.py show <id> [--repo R]
python <skill-dir>/scripts/todo_safe.py done <id> [--repo R] --note "Fixed in PR #1300"
python <skill-dir>/scripts/todo_safe.py check
```

`list` accepts `--repo`, `--domain`, `--status`, `--priority`, and `--json`.

## Capture useful entries

1. Never assume a repository/domain vocabulary row exists. If it is new or not
   confirmed, add a validated machine-local row with `domain-add` before `new`;
   if `new` rejects an unknown row, add it and retry. Never edit the vocabulary
   ad hoc or invent an inline variant.
2. Run `new` with complete **Why / Where / What to do / Constraints / Out of scope
   / Links** content. Cite file paths and symbols, use absolute dates, state facts
   and constraints, and omit motivational fluff.
3. Let the command create the entry and rebuild `INDEX.md`. Entry files are
   authoritative; the index is derived.

Ids use `<domain>-<slug>` and must remain unique across repositories. The command
validates the vocabulary and refuses collisions.

## Finish without losing history

Run `done <id> --note "what happened and where (PR, commit, or reason dropped)"`.
It moves the entry to the repository archive, removes its index line, and appends
the resolution. Never delete an entry or overwrite an archived id; the retained
reasoning is part of the value.

Mutations use locking and atomic replacement so concurrent agents cannot lose one
another's updates. Use `check` to report structural, vocabulary, duplicate-id,
symlink, frontmatter, and index drift without modifying the store.
