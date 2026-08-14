# Private and shared agent context

`agent-context` resolves optional knowledge and preferences from explicitly
registered context repositories. It is for facts such as domain terminology,
work conventions, home preferences, and repository background. It does not
replace `AGENTS.md`, permission policy, or a skill's safety invariants.

The public default context ships with the skill. Private values should live in a
separate repository or directory that is never committed to Agent Kit. Start
from `templates/context-repo/`, copy its example files to a private location,
and review the schema in
`skills/agent-context/references/context-schema.md`.

## Register sources and projects

Create a user registry at the OS-native path documented by the schema, or set
`AGENT_KIT_CONTEXT_CONFIG` to an absolute registry path. The registry names each
allowed source and maps a project by its exact resolved filesystem path or an
exact Git remote URL. Nothing is selected by directory name, parent traversal,
fuzzy matching, or network discovery.

Use separate sources when ownership or synchronization differs—for example a
personal user source, a work profile repository, a professional domain
repository, and a repository-specific source. A project mapping chooses the
profile, domain, and repository sources. Globally configured user sources still
apply. An explicit `--use` list replaces the mapped project sources for that
invocation while retaining global user context.

Resolution order is:

1. public defaults;
2. user context;
3. profile context;
4. domain context;
5. repository context;
6. explicit session context.

Later values override earlier values in mergeable categories. Sources at the
same layer retain registry order. Output includes the winning source for every
value, so an agent can explain where a preference came from. Only the bundled
public layer may define locked invariants.

## Inspect safely

From the installed skill directory, validate configuration without printing
context values:

```bash
python scripts/context.py doctor
```

Resolve the registered context as Markdown or JSON only when the current task
needs it:

```bash
python scripts/context.py resolve --project /absolute/path/to/project
python scripts/context.py resolve --project /absolute/path/to/project --json
python scripts/context.py resolve --project /absolute/path/to/project --use work-profile --use finance-domain
```

The resolver is read-only. It creates no registry, mapping, cache, log,
permission, or context file. It rejects unregistered IDs, relative source paths,
symlinked source roots/files, invalid layers, unknown schema keys, ambiguous
project matches, private invariants, and literal values in `secret_refs`.

Use symbolic references such as `env:ACCOUNT_TOKEN`, `file:/mounted/secret`, or
`keychain:item-name` when context needs to name a secret. The resolver never
fetches those references. Do not put actual credentials, private keys, tokens,
or secret text in a context file.

## What belongs where

- Put mandatory task steps, safety rules, and correctness-critical reference
  data in the relevant skill.
- Put public cross-skill defaults in the bundled Agent Kit context.
- Put personal, work, home, domain, and project knowledge in private sources.
- Put repository authority and contribution rules in `AGENTS.md`.
- Put maintainer architecture, release, and extension guidance under `docs/`.

This keeps each skill useful on its own while allowing deliberate, auditable
customization where the user has registered it.
