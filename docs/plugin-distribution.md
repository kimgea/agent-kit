# Plugin distribution

Agent Kit has one canonical copy of each skill under `skills/`. Packaging can
publish that source in three forms:

- a standalone skill archive for generic skill installers and Claude Code;
- one Codex plugin archive per cataloged plugin;
- one local Agent Kit marketplace containing every plugin.

The default is one skill per plugin. That lets users install only the capability
they need and keeps permissions, versions, and failures isolated. The catalog
supports an explicitly reviewed group of related skills later; every installable
skill must still belong to exactly one plugin.

## Build and inspect

Run:

```bash
python scripts/agent_kit.py package --format all
```

`dist/` then contains standalone `<skill>-<version>.zip` archives,
`<plugin>-plugin-<version>.zip` archives,
`agent-kit-marketplace-<toolkit-version>.zip`, and `SHA256SUMS`.

Each plugin has `.codex-plugin/plugin.json`, its canonical skill directories,
and the repository notices. The marketplace archive has a root
`agent-kit-marketplace/.agents/plugins/marketplace.json` plus local plugin
directories under `agent-kit-marketplace/plugins/`. Entries use relative
`./plugins/<id>` sources, resolved from the marketplace root, so the extracted
marketplace is portable as one directory tree.

Validate an extracted plugin with the current Codex plugin validator before
release. Then register the extracted marketplace root—the directory containing
`.agents/plugins/marketplace.json`—and install only the desired plugins:

```bash
codex plugin marketplace add ./agent-kit-marketplace
codex plugin list --marketplace agent-kit --available
codex plugin add agent-context@agent-kit
```

Repeat the final command for each plugin you want. The exact interactive command
may change with Codex releases; follow the current
[Codex plugin documentation](https://developers.openai.com/plugins/build/plugins)
for the installed client.

## Source and compatibility boundary

Do not edit generated plugin manifests or marketplace copies. Change
`toolkit.toml`, the canonical skill, or its `agents/openai.yaml`, then rebuild.
The validator enforces catalog membership, manifest metadata, local paths, and
deterministic output.

Plugins are a Codex distribution surface. The contained skills remain portable
plain Markdown and standard-library code and continue to ship separately for
Claude Code. Agent Kit does not add Codex-only runtime instructions to a skill
merely because that skill is also packaged as a plugin.

Shared context is not bundled into every plugin. Correctness-critical references
stay within the skill that needs them; optional cross-skill preferences and
knowledge flow through the separately installable `agent-context` skill.
