# Contributing

Read `AGENTS.md` first. Work from a non-default branch and deliver changes through
a pull request. Never develop in an installed copy under `.codex/skills`,
`.claude/skills`, a plugin cache, or a user data directory.

## Source and generated state

Treat this repository and `toolkit.toml` as the source of truth. Do not commit:

- generated Codex rules, Claude settings entries, or permission ownership state;
- `history.jsonl`, `discovered-tools.tsv`, todo entries, indexes, archives, locks,
  or local domain/classification overrides;
- transcripts, credentials, caches, build output, or temporary test files;
- installed or packaged copies of resources.

## Add or change a resource

1. Add or update its reviewed `toolkit.toml` entry.
2. Keep installable skills self-contained and dependency-free unless the catalog
   explicitly declares a requirement.
3. Keep skill `SKILL.md` focused on agent operating instructions. Put detailed
   maintainer material under `docs/` and tests under `tests/`.
4. Add or update evaluation cases under `evals/<resource>/` for behavioral
   changes.
5. Update compatibility, security, provenance, and changelog information when
   their claims change.
6. Run `python scripts/agent_kit.py check` and inspect the final diff.

Every skill requires frontmatter containing only `name` and `description` plus a
matching `agents/openai.yaml`. Preserve plain Markdown and standard-library Python
compatibility for Claude Code.

For an installable skill, also add or update its `[[plugins]]` mapping. A plugin
may contain one skill or an explicitly reviewed related group, but each
installable skill must belong to exactly one plugin. Plugin manifests and the
marketplace are generated from `toolkit.toml` plus skill metadata; do not commit
generated plugin trees or edit packaged copies.

### Skill content boundary

- Put universal runtime decisions, commands, and safety invariants in `SKILL.md`.
- Put operation-specific runtime detail in a directly linked `references/` file
  and state exactly when the agent should read it.
- Put architecture, compatibility evidence, extension procedures, testing, and
  release guidance under `docs/`; do not ship skill-local README, contributor,
  changelog, or installation files.
- Keep harness names in runtime guidance only when they change behavior, such as
  storage sharing, state paths, permission setup, or transcript interpretation.
  Record support claims in `toolkit.toml` and `docs/compatibility.md`.
- Keep harness UI metadata under `agents/`; another harness ignoring that metadata
  is a maintainer compatibility fact, not an everyday skill instruction.

Avoid duplicating the same rule across `SKILL.md`, references, and maintainer
docs. Installed skills must remain self-contained, so do not move information out
of the skill when an agent needs it to perform or safely interpret runtime work.

### Shared and private context

Keep correctness-critical runtime knowledge inside the skill that needs it. Use
the public `agent-context` defaults only for broadly shared preferences or facts
that are useful across skills, and do not create a hidden dependency on private
context. Private domain, work, home, and repository context belongs in separate
untracked repositories or directories registered by the user.

Context changes knowledge and preferences, not repository authority: it cannot
override `AGENTS.md`, safety rules, or a skill's runtime invariants. Use symbolic
secret references rather than secret values, and add resolver tests whenever
precedence, matching, validation, or disclosure behavior changes.

## Command classifications

Treat `skills/tool-audit/references/command-classes.tsv` as reviewed policy, not
generated inventory. Include broadly applicable CLI semantics only. Keep private
or machine-specific discoveries in the runtime data directory and reviewed local
overrides in `command-classes.local.tsv` there.

- Use a specific subcommand entry to override a `*` default.
- Use `mixed` when flags or later arguments can change safety.
- Do not mark a command `read` merely to avoid a prompt.
- Do not add a synthetic command unless the repository provides that wrapper.
- Verify upstream CLI documentation before changing a classification.

## Permission safety boundary

Only fixed safe dispatchers may appear in generated automatic permission rules:

- `tool-audit/scripts/audit.py` plus one enumerated argument-free profile;
- `todo-capture/scripts/todo_safe.py` plus one reviewed subcommand.

Do not add caller-controlled paths, commands, executable inputs, method overrides,
request bodies, or arbitrary trailing arguments. Keep setup, custom-path helpers,
version probes, learned inventory writes, and the repository installer gated.

For any permission change, test dry-run, install, repeat install, parser rejection,
drift handling, exact removal, and Linux/Windows command forms. Regenerate rules
only in temporary agent homes and never commit them.

## Privacy

Use synthetic minimal transcript fixtures. Never commit real session text or
credentials. Add a regression test whenever output begins to include a new field;
aggregate reports must not expose raw prompts, authorization values, bearer
tokens, or secret-bearing command arguments.

## Validation and CI

Run:

```bash
python scripts/agent_kit.py check
python scripts/agent_kit.py doctor
```

CI runs the canonical check on Ubuntu and Windows with Python 3.11 and 3.13. Keep
tests network-free and cover paths containing spaces, non-default agent homes,
packaged copies, and ownership-aware lifecycle behavior.

Committed CCPM files under `.claude/` are also part of the repository contract.
Use only its documented PRD, epic, and task status enums; the canonical check
validates status values, task-derived progress, completed-epic consistency, and
that completed epics live under `.claude/epics/archived/`.

Behavioral evaluation cases supplement deterministic tests. Forward-test a
substantial skill change with a fresh agent context without leaking the intended
answer, then document any compatibility limitation rather than overstating proof.

## Releases

Follow `docs/releasing.md`. Update catalog versions and `CHANGELOG.md`, validate,
merge through the protected branch, then create the matching signed or annotated
tag. The release workflow verifies the tag, rebuilds and tests the repository,
and publishes deterministic archives and checksums.

Remote repository settings are maintained by the narrow, preview-first
`scripts/configure_github.py` helper. Do not generalize it into an arbitrary API
client, and do not run its apply mode as part of validation or CI.

## Provenance

When adapting third-party material, update `THIRD_PARTY_NOTICES.md` with the exact
project, immutable upstream commit, license, affected paths, and modifications.
Do not assume the repository MIT license can relicense imported material.
