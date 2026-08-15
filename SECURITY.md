# Security policy

## Supported versions

Security fixes are applied to the latest tagged release and `main`. Install a
tagged release for reproducibility and upgrade when a security release appears.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository when available.
If it is unavailable, contact the maintainer privately and do not open a public
issue containing credentials, transcript excerpts, a working permission bypass,
or destructive proof-of-concept commands.

Include the affected resource and version, operating system and harness, the
smallest safe reproduction, expected boundary, actual behavior, and whether any
credentials or private transcript data may have been exposed.

## Security boundaries

Treat these as security-sensitive:

- permission installers, generated Codex rules, and Claude settings entries;
- fixed safe dispatchers and their argument parsers;
- command safety classifications and allowlist suggestions;
- transcript parsing, aggregation, and output redaction;
- repository installation, update, uninstall, and release packaging;
- GitHub Actions and third-party action references.
- the fixed GitHub repository configuration helper and default-branch ruleset.
- artifact path validation, private runtime state, loopback proxy confinement,
  lifecycle ownership, browser response policy, and Tailscale Serve setup.

Permission setup must be dry-run by default. Repository installation must never
grant runtime permissions as a side effect. A safe dispatcher must not accept an
arbitrary command, executable, custom data path, or unreviewed subcommand.

## Data handling

`tool-audit` reads local agent transcripts and configuration. Reports and
snapshots must retain only the documented aggregate data and must not emit raw
prompts, command arguments containing secrets, access tokens, or transcript
samples. `todo-capture` stores user-authored deferred-work context locally and
must preserve private OS-native permissions where the platform supports them.

No bundled resource may upload runtime data unless its documentation and catalog
entry explicitly declare the network destination and the user approves it.

`serve-artifacts` stores only user-selected artifact copies and local lifecycle
metadata. It must bind to loopback, reject links and escapes, proxy only explicit
loopback HTTP targets, expose no unauthenticated management API, and keep Tailscale
configuration preview-first and scoped to its owned path. Artifact URLs are
capability links and must never contain secrets or raw transcripts.
