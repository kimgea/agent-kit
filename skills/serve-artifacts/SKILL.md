---
name: serve-artifacts
description: Publish, inspect, and revoke transient browser-based artifacts through a local-first host with optional private-network or reverse-proxy access. Use when an agent has generated HTML, a multipage static site, a Vite or React build, a Next.js static export, or an already-running local web app that the user should open in a local or remote browser.
---

# Serve Artifacts

Use the bundled dependency-free host as the shared delivery layer for temporary
web output. Keep durable documentation in its owning repository instead.

## Publish a static artifact

1. Keep the source bundle outside the installed skill and out of Git unless the
   user explicitly wants durable project documentation.
2. Make asset and navigation URLs relative when possible. Do not include secrets,
   credentials, transcript dumps, analytics, or external trackers.
3. Publish the file or directory. The command starts the loopback host if needed:

```bash
python <skill-dir>/scripts/artifact_host.py publish <path> --title "<title>" --ttl 24h --json
```

Use `--entry <relative-file>` for a non-default entry page and `--spa` only when
unknown paths should fall back to that entry. Return `browser_url`. Also include
the provider-specific URL field when useful and explain its reachability.
When terminal and browser run on different machines, return the full URL visibly.
Client-side browser launching, clipboard integration, and terminal configuration
remain outside this skill.

The host copies validated source files into private runtime state. Editing or
deleting the source after publication does not mutate the published copy.

## Framework builds and local apps

- Publish existing Vite, React, or other static build output exactly like a
  directory. Configure the build for relative assets when possible.
- For a build that needs its final base path, first run `reserve --json`, build
  for the returned `content_base_path`, then pass the returned ID to
  `publish --id <id>`.
- For a Next.js static export, reserve first and use the returned path as the
  build-time `basePath`; publish the exported directory after the producer builds it.
- To expose an already-running HTTP app, use `proxy http://127.0.0.1:<port>`.
  Add `--preserve-prefix` only when the app was configured for the returned
  artifact prefix. The host never runs or supervises the app and supports ordinary
  HTTP navigation, not WebSockets or a full production deployment.

Read [frameworks.md](references/frameworks.md) when a framework needs base-path
configuration. Read [remote-access.md](references/remote-access.md) only when the
browser is not on the host. If the user selects Tailscale Serve, then read
[tailscale-serve.md](references/tailscale-serve.md).

## Lifecycle operations

Use the same script for the complete lifecycle:

```bash
python <skill-dir>/scripts/artifact_host.py status --json
python <skill-dir>/scripts/artifact_host.py list --json
python <skill-dir>/scripts/artifact_host.py revoke <artifact-id> --json
python <skill-dir>/scripts/artifact_host.py cleanup --json
python <skill-dir>/scripts/artifact_host.py stop --json
python <skill-dir>/scripts/artifact_host.py doctor --json
```

Artifacts expire after their TTL, up to 30 days. Revoke an artifact immediately
when the user is finished or if its content was shared accidentally. Treat each
unguessable artifact URL as a capability link: the selected network boundary limits
the audience, but the host does not add per-artifact authentication.

## Safety boundaries

- Keep the default loopback binding unless the user needs remote access. Bind
  directly only to one reviewed IPv4 interface with `--allow-remote`; wildcard
  listeners remain forbidden.
- Treat public tunnels or durable cloud publication as separate workflows that
  require an explicit user choice. Do not infer them from a request for a browser URL.
- Preview provider configuration and explain its reachability, persistence, and
  identity consequences before applying it.
- Proxy only a user-selected, already-running `http://127.0.0.1` or `localhost`
  target. Never pass a build, shell, package-manager, or server command to the host.
- Do not bypass rejected symlinks, path escapes, file limits, executable types,
  expiry, or ownership checks.
