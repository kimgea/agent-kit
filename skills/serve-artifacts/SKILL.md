---
name: serve-artifacts
description: Publish, inspect, and revoke transient browser-based artifacts through a loopback host, with optional tailnet-only HTTPS through Tailscale Serve. Use when an agent has generated HTML, a multipage static site, a Vite or React build, a Next.js static export, or an already-running local web app that the user should open in a local or remote browser.
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
unknown paths should fall back to that entry. Return `tailnet_url` when present;
otherwise return `local_url` and explain that the latter opens only on the host.

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

Read [frameworks-and-tailscale.md](references/frameworks-and-tailscale.md) when a
framework needs base-path configuration, a remote browser needs first-time
Tailscale setup, or a Tailscale route must be removed.

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
unguessable artifact URL as a capability link: Tailscale access rules limit the
audience, but the host does not add per-artifact authentication.

## Safety boundaries

- Bind only to the fixed loopback interface. Do not modify the script to listen
  on all interfaces; use the reviewed Tailscale adapter for remote access.
- Never use Tailscale Funnel or another public tunnel for this workflow.
- Preview Tailscale setup or removal first. Apply it only after the user explicitly
  approves the persistent tailnet exposure and certificate-transparency notice.
- Proxy only a user-selected, already-running `http://127.0.0.1` or `localhost`
  target. Never pass a build, shell, package-manager, or server command to the host.
- Do not bypass rejected symlinks, path escapes, file limits, executable types,
  expiry, or ownership checks.
