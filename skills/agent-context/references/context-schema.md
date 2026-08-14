# Agent context schema

## Files and selection

The resolver reads one private registry and one `context.toml` from each selected
source. The registry is found at:

- Linux: `${XDG_CONFIG_HOME:-~/.config}/agent-kit/context.toml`
- macOS: `~/Library/Application Support/agent-kit/context.toml`
- Windows: `%APPDATA%\agent-kit\context.toml`

`AGENT_KIT_CONTEXT_CONFIG` may point at another registry for an isolated runtime
or test. The resolver never creates or changes that file.

The registry has this shape:

```toml
schema_version = 1
always = ["user-global"]

[[sources]]
id = "user-global"
path = "/absolute/path/to/private-global-context"

[[sources]]
id = "work"
path = "/absolute/path/to/private-work-context"

[[projects]]
path = "/absolute/path/to/project"
remotes = ["https://github.com/example/project.git"]
use = ["work"]
```

`always` may contain only `user` layers. A project matches an exact resolved path
or an exact Git remote string. Multiple matching project entries are an error.
`--use` replaces only the project `use` list, not `always`.

## Source document

Every registered source is a real, non-symlinked directory containing a real,
non-symlinked `context.toml`:

```toml
schema_version = 1
id = "work"
layer = "profile"

[invariants]

[preferences]
review-style = "Prefer small, reviewable changes."

[facts]
organization = "Example"

[resources]
handbook = "https://example.invalid/handbook"

[secret_refs]
issue-token = "env:EXAMPLE_ISSUE_TOKEN"
```

Registered layers may be `user`, `profile`, `domain`, or `repository`. A
session file must declare `session`; only the bundled defaults may declare
`public`. Private and session sources must leave `invariants` empty.

Category keys must be non-empty strings. Values in `invariants`, `preferences`,
`facts`, and `resources` must be strings, booleans, integers, finite floats, or
arrays of those scalar types. Secret-reference values must use the `env:`,
`file:`, or `keychain:` scheme and contain only restricted path or identifier
characters; they are never resolved by the tool.

## Precedence and output

Precedence is `public < user < profile < domain < repository < session`.
Registry order breaks ties within a layer, with later sources replacing the same
key. Output includes the ordered source IDs and per-key provenance. The resolver
does not cache, log, write, sync, or discover context.
