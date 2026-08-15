# Remote browser access

Read this reference only when the browser is not on the artifact-host machine.
Select the smallest exposure mechanism that matches the user's environment.

## Selection

1. Keep the default loopback host for a browser on the same machine.
2. Keep loopback and use SSH port forwarding when the browser device can maintain
   an SSH session. This changes no server network binding.
3. Bind to one private LAN or VPN IPv4 address when approved devices can reach
   that interface directly.
4. Keep loopback and use an existing trusted reverse proxy when the environment
   already provides one.
5. Use a provider adapter such as Tailscale Serve only when the user selects it.

Public tunnels and durable hosted sites are different publication workflows. Do
not create one merely because the user asked for a remote browser URL.

## SSH forwarding

Forward the remote loopback port to the browser device while the SSH connection
remains open:

```bash
ssh -L 4177:127.0.0.1:4177 <host>
```

Open the returned `local_url` on that device. Account for an existing SSH session
or occupied local port rather than silently starting another connection.

## Direct private-interface binding

Identify the exact private LAN or VPN IPv4 address that the browser can reach.
Explain that every device allowed to contact that interface and port can attempt
artifact URLs. Then start the host explicitly:

```bash
python <skill-dir>/scripts/artifact_host.py start \
  --bind-address <private-ipv4> \
  --allow-remote \
  --advertise-url http://<reachable-name-or-ip>:4177 \
  --json
```

The server rejects hostnames, IPv6, multicast, and wildcard addresses as bind
targets. It never accepts `0.0.0.0`; select one interface. `--advertise-url` only
controls returned links and must not be presented as proof that a route is reachable.
Publish normally after the host starts and return `browser_url`.

## Existing reverse proxy

Keep the server on loopback. Configure the separately owned proxy to map either
its origin or `/agent-artifacts` to `http://127.0.0.1:4177`, preserving the request
path. Start the host with the reviewed browser-facing base:

```bash
python <skill-dir>/scripts/artifact_host.py start \
  --advertise-url https://artifacts.example/agent-artifacts \
  --json
```

The host does not configure, authenticate, or revoke a generic reverse proxy.
Treat its access policy and TLS lifecycle as the proxy owner's responsibility.

## Phone terminals

When the user is running the agent from Termux, return both the URL and:

```bash
termux-open-url '<browser_url>'
```

Do not shorten capability IDs merely to improve copying; that would weaken URL
entropy. A QR code is useful only when the browser is on a different device.
