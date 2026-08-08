---
name: todo-capture
description: Capture, list, show, and finish/archive deferred work, follow-ups, TODO entries, reminders, tech debt, out-of-scope findings, and postponed tasks. Use when the user says "add a todo", "note this for later", "defer this", "park this", "capture a follow-up", "record this", "add to the backlog", "mark todo done", "archive/resolve/finish a todo", asks to list/show todos, or when agent/project instructions say tangential work must be recorded instead of handled now. Stores durable pickup-pointer entries in a shared OS-native data directory using the bundled toolkit.
---

# todo-capture

Capture consciously deferred work as a **pickup pointer**: the decision, where the
code is, and what the next agent must know. Use the fixed-store dispatcher by
default. Its OS-native data store is shared across Codex and Claude Code, so work
captured by one agent is visible to the other.

## Route the operation

Use `scripts/todo_safe.py` for `list`, `new`, `show`, `done`, `check`, and
`domain-add`. Use direct `scripts/todo.py` only for an explicitly approved custom
`--dir`.

Do not load references for routine `list`, `new`, `show`, `done`, or `check`
operations; the workflow below and script validation are sufficient. Read
[conventions.md](references/conventions.md) only when the user asks about the full
entry schema, naming rules, storage layout, or manual diagnosis. The scripts load
`references/TEMPLATE.md` and `references/domains.tsv` themselves.

## Bootstrap permissions safely

On first use or after relocating the skill, run
`python <skill-dir>/scripts/setup_permissions.py` without `--install` and show its
proposal. Install only after explicit user approval by rerunning with
`--install --yes`. The bootstrap approves only the fixed dispatcher plus one
enumerated subcommand; setup itself, direct `todo.py`, arbitrary Python, and custom
paths remain gated. More restrictive project or managed policies still win.

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
