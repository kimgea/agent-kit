# Tailscale Serve adapter

Read this reference only after the user selects tailnet-only HTTPS through
Tailscale Serve. The core host does not require Tailscale.

## First-time machine and tailnet setup

Tailscale Serve terminates HTTPS at the machine's MagicDNS name and proxies only
the `/agent-artifacts` path to the loopback host. The tailnet may first require an
administrator to enable Serve. The Tailscale CLI prints the applicable enablement
URL when this is necessary.

The local account also needs authority to manage Serve routes. If Tailscale reports
`serve config denied`, explain that this one-time command grants the current local
account Tailscale operator privileges and ask the user to run it themselves:

```bash
sudo tailscale set --operator="$USER"
```

Do not request, receive, or pipe a sudo password. Operator access is broader than
this artifact route, so do not apply it silently.

## Tailnet-only HTTPS

Keep the artifact host on its default `127.0.0.1` binding. First preview:

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

The command allows extra time for first-time HTTPS setup, returns a concise timeout
error, and refuses to claim a pre-existing unowned path. Existing unrelated Serve
handlers remain untouched.

Preview and remove only the owned path with:

```bash
python <skill-dir>/scripts/artifact_host.py tailscale-remove --json
python <skill-dir>/scripts/artifact_host.py tailscale-remove --apply --yes --json
```

Do not use `tailscale serve reset`: it can remove unrelated user routes.
