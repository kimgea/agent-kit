# agent-kit

Portable, reusable resources for Codex and Claude Code. The toolkit currently
ships skills, agent instruction fragments, safety policies, templates, a hook,
and a GET-only GitHub REST wrapper.

The repository is the source of truth. Installed copies are deployments and must
not be edited directly.

## Discover resources

`toolkit.toml` is the reviewed machine-readable catalog. Agents can read it
directly or use the dependency-free command:

```bash
python scripts/agent_kit.py list
python scripts/agent_kit.py list --json
python scripts/agent_kit.py doctor
```

Current skills:

| Skill | Purpose | Runtime data |
|---|---|---|
| `grill-me` | Pressure-test decisions, plans, artifacts, and diagnoses | None |
| `todo-capture` | Preserve deferred work as shared pickup pointers | Private OS-native state directory |
| `tool-audit` | Audit local tools, agent usage, friction, and permissions | Private OS-native state plus read-only transcript access |

See [compatibility](docs/compatibility.md) for the tested support matrix and the
individual documents under `docs/` for each safety model.

## Install a skill

Use a tagged checkout or release rather than an unpinned `main` when installing
for repeatable use. For an ownership-aware installation, clone the tagged toolkit
release, then install only the selected skill:

```bash
git clone --branch v1.1.1 --depth 1 https://github.com/kimgea/agent-kit.git
cd agent-kit
python scripts/agent_kit.py list
```

Individual skill archives and `SHA256SUMS` are also attached to each
[GitHub release](https://github.com/kimgea/agent-kit/releases) for use with a
normal agent skill installer. From the tagged source checkout, preview the
destination first:

```bash
python scripts/agent_kit.py install tool-audit --agent codex
python scripts/agent_kit.py install tool-audit --agent claude
```

After reviewing the source, destination, version, and unchanged permission state,
apply explicitly:

```bash
python scripts/agent_kit.py install tool-audit --agent codex --apply --yes
```

The installer:

- resolves `CODEX_HOME` or `CLAUDE_CONFIG_DIR` at runtime;
- copies only self-contained cataloged skills;
- refuses unowned or locally modified destinations;
- records private ownership state outside the installed skill;
- retains the previous verified deployment for rollback;
- never grants shell or filesystem permissions.

Normal Codex or Claude skill installers may also copy a released skill directory.
When they do, repository ownership, update, and rollback tracking are not
available unless that deployment is first removed and installed through
`agent_kit.py`.

## Review skill permissions separately

`todo-capture` and `tool-audit` include permission bootstrap scripts. From the
installed skill, run `setup_permissions.py` without `--install` and show the
proposal. Only after human acceptance, rerun it with `--install --yes`.

The toolkit installer is intentionally not automatically approved: it can write
to agent installation directories. Only each skill's reviewed fixed dispatcher
profiles are candidates for narrow automatic permission rules.

## Update, remove, or roll back

Check out the desired release, then run the same `install` command. An owned,
unchanged deployment is updated; drift is refused. To remove or restore:

```bash
python scripts/agent_kit.py uninstall tool-audit --agent codex
python scripts/agent_kit.py uninstall tool-audit --agent codex --apply --yes
python scripts/agent_kit.py rollback tool-audit --agent codex
python scripts/agent_kit.py rollback tool-audit --agent codex --apply --yes
```

Uninstall moves the verified deployment into private agent-kit trash rather than
deleting it. Permission entries are left unchanged so their own ownership-aware
setup script can preview and remove them separately.

## Reusable non-skill resources

- `instructions/` — reviewed global instruction fragments that require human
  adoption.
- `templates/` — project instruction starters.
- `policies/` — permission and command-safety review contracts.
- `hooks/` — optional defense-in-depth hooks; never a substitute for policy.
- `adapters/` — harness-specific installation notes.
- `tools/gh-api-get/` — portable GET-only GitHub REST API wrapper.
- `evals/` — realistic behavioral cases for skill forward-testing.

These resources are cataloged but are not silently installed because they affect
global behavior or need project-specific adaptation.

## Develop and validate

Read [AGENTS.md](AGENTS.md) and [CONTRIBUTING.md](CONTRIBUTING.md), then run the
same gate used by CI:

```bash
python scripts/agent_kit.py check
```

The gate validates catalog parity, skill frontmatter and UI metadata, local links,
evaluation schemas, generated-file hygiene, Python compilation, all unit tests,
and that validation itself does not alter the working tree.

Build deterministic release archives locally with:

```bash
python scripts/agent_kit.py package
```

See [release guidance](docs/releasing.md). Security-sensitive findings belong in
the private process described by [SECURITY.md](SECURITY.md). Licensing and
historical source information are recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
