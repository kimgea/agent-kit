# TODO entry conventions

The authority for how entries are named, structured, and retired. `todo.py`
enforces the mechanical parts; this file is the reasoning.

## What belongs here

Work that was **consciously deferred** and needs a pointer so it can be picked up
cold: the decision, where the code is, and what the next person must know before
touching it.

- **Not a spec.** An entry is a pickup pointer, target **15–30 lines**. If it needs
  a real design, the entry says so and the design lives in the repo's `specs/`.
- **Not a scratch list.** "Rename this variable" belongs in a commit, not here.

## Layout (in the data store)

```
<data-store>/                 OS-native private dir (see below)
  INDEX.md                    one line per active entry, grouped by repo
  domains.local.tsv           machine-specific repo/domain vocabulary
  <repo>/                     one folder per repo, created on its first entry
    <domain>-<slug>.md
    archive/                  finished or dropped entries, moved here verbatim
```

`<data-store>` resolves (via `_common.py: data_root()`) to `%LOCALAPPDATA%\todo-capture`
(Windows), `~/Library/Application Support/todo-capture` (macOS), or
`${XDG_STATE_HOME:-~/.local/state}/todo-capture` (Linux). `$TODO_CAPTURE_DATA_DIR`
overrides the base. The approval-gated direct `todo.py` helper accepts a full custom
path as a subcommand-level `--dir`; the auto-approved `todo_safe.py` dispatcher
does not. The default store is **shared across
agents** (Claude + Codex) — there is no per-agent split. Do not create a repo folder
before it has an entry.

## Naming

`<domain>-<slug>.md`, lowercase kebab-case. The filename (minus `.md`) is the
entry's stable **id** — reference entries as `[[api-permission-domain-model]]`.
Never number entries: numbering needs a counter, collides between sessions, and
carries no meaning.

`<domain>` and `<repo>` must come from the **domain vocabulary**: the bundled
portable baseline `references/domains.tsv` (generic `_general` domains only) plus the
machine-specific `<data-store>/domains.local.tsv` (local rows extend/override the
baseline). If nothing fits, use `todo_safe.py domain-add` for a project-specific
row or add a broadly portable one to the bundled baseline in source; never invent
an unlisted variant inline. `todo_safe.py new` refuses an unknown repo/domain.

The id (`<domain>-<slug>`) must be **unique across all repos** — it carries no repo
component, so `harness-hooks` under `test` and under `_general` would collide.
Some domains (`harness`) exist in more than one repo, so make the slug distinctive
enough to stay unique. `todo_safe.py new` refuses a colliding id and `check` flags any
duplicate.

## Frontmatter

```yaml
---
repo: test            # folder name; _general for cross-repo/machine-level
domain: api      # must match the filename prefix and a domains.tsv row
status: todo            # todo | in-progress | blocked
created: 2026-07-29     # absolute dates only, never "last week"
source: PR #3551        # optional — where this came from (PR, ticket, conversation)
priority: normal        # optional — high | normal | low
---
```

`repo`, `domain`, `status`, `created` are required (`todo_safe.py check` flags a
missing one).

## Lifecycle

- **Vocabulary:** `todo_safe.py domain-add --repo R --domain D --note N`
  atomically appends a validated local row without granting direct store edits.
- **Add:** `todo_safe.py new --repo R --domain D --slug S --title T --why ...
  --where ... --what ... --out-of-scope ...` atomically writes the complete
  pickup pointer from `TEMPLATE.md` and rebuilds the derived `INDEX.md`.
- **Finish:** `todo_safe.py done <id> --note "..."` moves the file to `<repo>/archive/`,
  deletes its `INDEX.md` line, and appends a `**Resolved:**` line (its only edit)
  saying what happened and where (PR #, commit) — or, if dropped, why. **Never
  delete an entry**; the reasoning is the value.
- **Audit:** `todo_safe.py check` reports file, vocabulary, frontmatter, symlink,
  duplicate-id, and index drift without changing the store.

Entry files are authoritative; `INDEX.md` is a derived view. Every mutation holds
the store lock, writes files through atomic replacement, and rebuilds the index.
On POSIX, store directories are mode `0700` and generated files are `0600`.

## Writing rules

- **Absolute dates** — `2026-07-29`, never "yesterday" / "last sprint".
- **Cite locations** — `file.cs:123`, and name the symbol too (line numbers drift).
- **State constraints, not plans** — the load-bearing caller, the breaking-change
  surface, the thing that looks like a bug but isn't.
- **No fluff** — lead with the concrete fact; no "improves maintainability".
- **Self-contained** — an agent working in the data store has no repo project
  memory loaded; the entry must stand alone.
- **Verify before recommending** — an entry may be months old; confirm named
  files/symbols still exist before acting on it, and correct the entry if they moved.
