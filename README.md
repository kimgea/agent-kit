# agent-kit

Portable, reusable resources for Codex and Claude Code. The toolkit ships
independently installable skills, Codex plugin bundles, an Agent Kit plugin
marketplace, agent instruction fragments, safety policies, templates, a hook,
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
| `agent-context` | Resolve explicitly registered private context for the current project | Reads registered context repositories; writes nothing |
| `build-interactive-diagram` | Create polished temporary HTML visuals for explanations | Writes only the selected artifact output directory |
| `grill-me` | Pressure-test decisions, plans, artifacts, and diagnoses | None |
| `project-review` | Review bounded changes under root and nested `REVIEW.md` guidance | Reads project source and optional user guidance; writes output only when explicitly requested |
| `review-and-fix` | Safely address local review findings through decision gates and fresh re-review | Reads bounded project/review data; changes only eligible or approved local files |
| `review-guidance-audit` | Improve hierarchical `REVIEW.md` guidance without editing it | Reads selected project files and review guidance; writes output only when explicitly requested |
| `serve-artifacts` | Host and revoke transient web artifacts locally or through a selected private-network adapter | Private OS-native artifact copies, lifecycle state, and optional adapter ownership |
| `todo-capture` | Preserve deferred work as shared pickup pointers | Private OS-native state directory |
| `tool-audit` | Audit local tools, agent usage, friction, and permissions | Private OS-native state plus read-only transcript access |

See [compatibility](docs/compatibility.md) for the tested support matrix. The
[agent-context guide](docs/agent-context.md) explains how to layer private work,
home, or domain knowledge over the public defaults without committing it here.
The [artifact host guide](docs/artifact-host.md) covers temporary interactive
visuals, framework output, lifecycle limits, and provider-neutral browser access.
The [project-review guide](docs/project-review.md) covers hierarchical review
policy, trusted-base behavior, structured findings, and verification authority.
The [review-and-fix guide](docs/review-and-fix.md) explains neutral reviewer
normalization, conservative automatic-fix eligibility, and fresh acceptance.
The [review-guidance audit guide](docs/review-guidance-audit.md) explains scoped
guidance analysis, context compaction, placement, and when automated checks can
replace or only support review rules.
The [local behavioral evaluation guide](docs/behavioral-evals.md) explains how
maintainers can run fresh-agent skill evaluations locally while keeping paid
model calls out of the canonical gate and GitHub Actions.

## Install a skill

Use a tagged checkout or release rather than an unpinned `main` when installing
for repeatable use. For an ownership-aware installation, clone the tagged toolkit
release, then install only the selected skill:

```bash
git clone --branch v1.8.0 --depth 1 https://github.com/kimgea/agent-kit.git
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

## Install Codex plugins

Every installable skill is released both as a standalone skill archive and as
part of a Codex plugin. Most plugins contain one skill. The coherent `artifacts`
plugin groups the diagram producer with the artifact host, while the
`project-review` plugin groups project review, review-and-fix, and review-guidance
audit. The release
includes an `agent-kit-marketplace-<version>.zip` catalog whose entries point to
the bundled local plugin directories. Select a focused plugin when its grouped
workflow is useful, or use a standalone archive to install one skill by itself.

After extracting the marketplace archive, register its root (the directory that
contains `.agents/plugins/marketplace.json`) with Codex and select the plugins
you want. See the [plugin distribution guide](docs/plugin-distribution.md) for
artifact layout, local development, and compatibility boundaries. Standalone
skill archives remain the portable Claude Code and generic skill-installation
format.

## Review skill permissions separately

`todo-capture` and `tool-audit` include permission bootstrap scripts. From the
installed skill, run `setup_permissions.py` without `--install` and show the
proposal. Only after human acceptance, rerun it with `--install --yes`.

The toolkit installer is intentionally not automatically approved: it can write
to agent installation directories. Only each skill's reviewed fixed dispatcher
profiles are candidates for narrow automatic permission rules.

`serve-artifacts` changes no agent permissions. Remote binding and provider setup
remain explicit. Its optional Tailscale adapter is preview-first and requires
`--apply --yes`; review operator access, the tailnet route, and the certificate-
transparency notice separately from skill installation.

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
- `templates/context-repo/` — starter files for a separate private context
  repository or directory.
- `policies/` — permission and command-safety review contracts.
- `hooks/` — optional defense-in-depth hooks; never a substitute for policy.
- `adapters/` — harness-specific installation notes.
- `tools/gh-api-get/` — portable GET-only GitHub REST API wrapper.
- `evals/` — descriptive forward-test cases plus opt-in executable synthetic
  suites for skills with stable canonical results.

These resources are cataloged but are not silently installed because they affect
global behavior or need project-specific adaptation.

## Develop and validate

Read [AGENTS.md](AGENTS.md) and [CONTRIBUTING.md](CONTRIBUTING.md), then run the
same gate used by CI:

```bash
python scripts/agent_kit.py check
```

The gate validates catalog parity, skill frontmatter and UI metadata, local links,
evaluation schemas and executable-suite fixtures, generated-file hygiene, Python
compilation, all unit tests, and that validation itself does not alter the
working tree. It never invokes a model. Run model-backed behavioral suites only
through the explicit local commands in the behavioral evaluation guide.

Build every deterministic release format locally with:

```bash
python scripts/agent_kit.py package --format all
```

See [release guidance](docs/releasing.md). Security-sensitive findings belong in
the private process described by [SECURITY.md](SECURITY.md). Licensing and
historical source information are recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
