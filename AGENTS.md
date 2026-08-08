# Agent-kit repository contract

This file is the authoritative operating contract for agents working in this
repository. `CLAUDE.md` points Claude Code to the same contract.

## Purpose and source of truth

- Treat this checkout as the source of truth for reusable agent resources.
- Treat copies under Codex, Claude Code, plugin, or user data directories as
  deployments. Never develop in an installed copy.
- Keep every skill independently installable. Runtime code and references needed
  by a skill must remain inside that skill directory.
- Keep repository-only validation, packaging, and installation code under
  `scripts/`; installed skills must not import it.

## Safe working rules

- Begin with read-only inspection. Do not change global agent configuration,
  permissions, installed skills, releases, or remote repository state unless the
  user explicitly requested that mutation.
- Never silently grant permissions. Permission setup must preview by default and
  require an explicit apply flag plus confirmation.
- Do not automatically approve a general installer, arbitrary interpreter,
  caller-controlled path, command passthrough, or executable input.
- Treat permission rules, safe dispatchers, command classifications, hooks, and
  installers as security boundaries. Changes to them require boundary tests.
- Keep transcripts, generated rules, agent settings, permission state, runtime
  data, caches, credentials, and machine-specific discoveries out of Git.
- Never print or persist secrets or raw transcript content in aggregate reports.
- Preserve unrelated user changes. Do not use destructive Git operations or
  force pushes.

## Editing and discovery

- Read the affected resource's instructions and its catalog entry before editing.
- Use `rg` or `rg --files` for search and discovery.
- Use `apply_patch` for hand-authored edits.
- Keep skill frontmatter limited to `name` and `description`.
- Keep human maintainer material under `docs/`, tests under `tests/`, and
  progressive-disclosure references under the affected skill.
- Update `toolkit.toml`, documentation, tests, and evaluation cases when a
  resource's interface, compatibility, risk, or lifecycle changes.

## GitHub access

- For every read-only GitHub REST API request, use `gh-api-get`. Direct `gh api`
  is forbidden because method and payload flags can turn a visually read-like
  command into a mutation.
- Use normal purpose-specific read commands such as `gh pr view` when they fit.
- Perform GitHub mutations only when requested, from a non-default branch, and
  through a pull request. Never bypass required checks. Only the configured
  `kimgea` owner identity may merge a pull request into `main`, and an agent may
  do so only when the user has requested delivery into `main`.

## Required validation

Run this canonical gate before committing:

```bash
python scripts/agent_kit.py check
```

For a permission-boundary change, also prove:

- dry-run output is non-mutating;
- install is exact and repeatable;
- extra arguments and custom paths stay gated;
- removal affects only state owned by that installer;
- Linux and Windows behavior is covered;
- generated runtime files remain untracked.

Use `python scripts/agent_kit.py doctor` to inspect local compatibility. A green
validator is evidence only for checks it actually performs; review the diff and
the applicable threat model before publishing.
