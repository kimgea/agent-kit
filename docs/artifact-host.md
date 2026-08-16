# Transient interactive artifacts

The artifacts plugin adds two independently useful skills:

- `build-interactive-diagram` turns an explanation into a self-contained,
  responsive HTML visual;
- `serve-artifacts` validates, copies, serves, expires, and revokes temporary web
  bundles through one local lifecycle.

They are grouped in one Codex plugin because creation and delivery form one user
workflow. Standalone archives still let Codex, Claude Code, or another compatible
skill installer deploy either skill separately. The producer has a path-only
fallback and does not require the host.

## Why the core is a CLI

The deterministic Python CLI is both the user control plane and the stable adapter
boundary. A skill can invoke it directly, a future MCP server can wrap the same
operations, and humans can diagnose it over SSH. An MCP server would add protocol
and process configuration without improving the current local workflow; a Docker
image would complicate loopback, filesystem, and Tailscale integration. Neither is
required for the initial capability.

The host uses only Python's standard library. It does not install Node, run builds,
start framework applications, or execute caller-provided commands.

## Runtime model

Runtime state is shared across agent harnesses and stored outside repositories:

| Platform | Default state root |
|---|---|
| Linux | `${XDG_STATE_HOME:-~/.local/state}/agent-kit/artifacts` |
| macOS | `~/Library/Application Support/AgentKit/artifacts` |
| Windows | `%LOCALAPPDATA%\AgentKit\artifacts` |

`ARTIFACT_HOST_STATE_DIR` may select an absolute root for isolated testing. It is
not a permission-safe dispatcher argument and should remain approval-gated in any
automatic command policy.

The store contains a private registry, copied static bundles, an authenticated
runtime record, and optional ownership metadata for one Tailscale Serve path.
Artifacts receive 192-bit random IDs and a required TTL from one second through
30 days. The default is 24 hours.

The service defaults to `127.0.0.1:4177`. Publishing starts it in the background;
`serve` provides a foreground mode for supervisors and diagnostics. Remote use can
bind to one exact IPv4 interface only with `--allow-remote`; wildcard listeners are
rejected. An optional advertised URL affects returned links, not routing. No HTTP
route lists, publishes, revokes, or otherwise manages artifacts. The stop endpoint
requires the private per-process token and is used only by the CLI.

## Supported artifact forms

| Form | Support | Notes |
|---|---|---|
| One HTML file | Full | Published as `index.html` |
| Multipage static directory | Full | Relative navigation; no directory listings |
| Client-side SPA | Full | Use `--spa` for entry-page fallback |
| Vite/React static build | Full | Prefer Vite `base: "./"` |
| Next.js static export | Full with configuration | Reserve an ID, use its slash-free `content_base_path` as `basePath`, and set `trailingSlash: true` |
| Existing loopback HTTP app | Limited proxy | GET/HEAD, no WebSockets or process supervision; base-path-aware apps can preserve the prefix |
| Dynamic Next.js deployment | Producer-owned | The host can proxy an already-running, correctly configured instance but does not make it durable or production-ready |

Static publishers can reserve an ID before a framework build. This keeps build
execution outside the host while giving frameworks a final, slash-free absolute
base path. Next.js exports additionally use `trailingSlash: true` so secondary
routes become directory index files rather than requiring host rewrite rules.

## Browser and filesystem boundary

Publication rejects:

- symlinked sources, directories, files, or state files;
- hidden bundle paths, special files, executable/server-side suffixes, traversal,
  missing entry pages, and duplicate or invalid reserved IDs;
- more than 1,000 files, more than 100 MiB total, or a file over 25 MiB.

Static files are copied with private permissions. Revoke and expiry reject
symlinked content roots or artifact directories, surface deletion failures, and
remove registry ownership only after deleting the owned copy. They never touch
the producer's source. Registry replacement is atomic and mutations use a
cross-platform process lock.

Artifacts render inside a constrained viewer iframe. Response policy disables
plugins, external connections, framing by other origins, referrers, device APIs,
and MIME sniffing while allowing same-origin scripts, styles, images, workers, and
connections needed by interactive static applications. The viewer is defense in
depth, not a malware sandbox: publish only content the user or agent has reviewed.
A random artifact URL is a capability link, not an additional identity layer.

Proxy targets must be explicit `http://127.0.0.1:<port>` or
`http://localhost:<port>` URLs. The proxy does not follow redirects server-side,
forwards only a narrow header set, strips cookies and authentication, injects the
artifact policy, and caps responses at 10 MiB.

## Provider-neutral remote access

The artifact lifecycle does not depend on Tailscale. Four exposure modes share the
same static/proxy records and capability URLs:

| Mode | Server binding | External dependency | Lifecycle owner |
|---|---|---|---|
| Same-machine browser | Loopback | None | Artifact host |
| SSH port forwarding | Loopback | Existing SSH client | SSH session |
| Direct private LAN or VPN | One exact IPv4 interface | Reachable private network | Artifact host process |
| Existing reverse proxy | Loopback | User-owned proxy and access policy | Proxy owner |

Direct binding requires an explicit interface, `--allow-remote`, and review of who
can reach that interface and port. `--advertise-url` accepts a plain origin or an
`/agent-artifacts` base and makes the returned `browser_url` useful with private DNS.
It configures no DNS, firewall, TLS, authentication, or reverse proxy.

Tailscale Serve remains one optional reverse-proxy adapter. It maps HTTPS at the
machine's MagicDNS name and `/agent-artifacts` to the loopback service. Setup and
removal are preview-first, own only their exact path, preserve unrelated handlers,
and never enable Funnel. Removal revalidates the recorded hostname, HTTPS port,
path, and proxy target against live Serve status before mutation. First-time use
may require a tailnet administrator to enable Serve and a local administrator to
assign the invoking account as Tailscale operator. HTTPS can expose the MagicDNS
certificate name in certificate-transparency logs, so those changes remain
explicit rather than part of core host installation.

Terminal-to-browser handoff belongs to the client environment. The host returns
full visible URLs, but does not launch remote browsers, modify client clipboards,
configure terminal emulators, or create shortened aliases or QR handoffs. Opening
or copying the URL remains client-owned.

## Typical operations

From an installed `serve-artifacts` skill:

```bash
python scripts/artifact_host.py doctor --json
python scripts/artifact_host.py publish /path/to/site --title "Flow" --ttl 4h --json
python scripts/artifact_host.py list --json
python scripts/artifact_host.py revoke <artifact-id> --json
```

For direct access over an already approved private network, start first with
`--bind-address <private-ipv4> --allow-remote --advertise-url <browser-base>`.
For Tailscale Serve, preview `tailscale-setup --json`; apply or remove its owned
route only after reviewing the adapter-specific consequences.

## Deliberate extension points

Specialized producer skills should exchange only the artifact directory and CLI
JSON contract with the host; they must not import its Python internals. A future MCP
adapter should expose the same bounded operations and never add arbitrary command
execution. Network providers remain replaceable exposure adapters rather than host
dependencies. A future container image is appropriate only for a server deployment
with explicit volume, interface, and lifecycle semantics, not as the default agent
installation format.
