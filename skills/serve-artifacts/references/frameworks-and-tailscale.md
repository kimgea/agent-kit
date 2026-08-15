# Framework and Tailscale operations

Read this reference only for framework base paths, first-time remote access, or
removing the owned Tailscale Serve route.

## Static framework output

The host serves each artifact below:

```text
/agent-artifacts/c/<artifact-id>/
```

For Vite, prefer a relative build base:

```js
export default { base: "./" }
```

Publish the resulting `dist/` directory. Client-side routers also need `--spa`
when their routes are not emitted as files.

Frameworks that require an absolute base path need an ID before building:

```bash
python <skill-dir>/scripts/artifact_host.py reserve --title "Preview" --ttl 4h --json
```

Use `content_base_path` from the JSON as the build-time base, then publish with
the reserved `id`. For a Next.js static export, set `output: "export"` and use
that path as `basePath` before building; publish its export directory. This is a
build-output contract, not permission for the host to run Node or a package manager.

For an already-running dynamic app, reserve the ID, configure the app for the same
base path, and proxy it with `--id <id> --preserve-prefix`. Ordinary GET/HEAD HTTP
works; WebSockets, server lifecycle, authentication, databases, and production
reliability remain outside this host.

## Tailnet-only HTTPS

No special application networking is required. The Python service stays on
`127.0.0.1`; Tailscale Serve terminates HTTPS at the machine's MagicDNS name and
proxies only the `/agent-artifacts` path.

First run the preview:

```bash
python <skill-dir>/scripts/artifact_host.py tailscale-setup --json
```

Explain these consequences before applying:

- the route becomes reachable by devices and users allowed by the tailnet policy;
- Tailscale Serve persists across terminal sessions and restarts;
- enabling HTTPS can publish the machine's MagicDNS certificate name in public
  certificate-transparency logs;
- the command changes only the reviewed path on HTTPS port 443 and never enables
  Funnel.

After explicit approval, apply the exact preview with:

```bash
python <skill-dir>/scripts/artifact_host.py tailscale-setup --apply --yes --json
```

The command refuses to claim a pre-existing unowned path. Existing unrelated
Serve handlers remain untouched.

Preview and remove only the owned path with:

```bash
python <skill-dir>/scripts/artifact_host.py tailscale-remove --json
python <skill-dir>/scripts/artifact_host.py tailscale-remove --apply --yes --json
```

Do not use `tailscale serve reset`: it can remove unrelated user routes.
