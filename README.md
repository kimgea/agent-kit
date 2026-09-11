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
| `change-impact` | Map the evidence-backed reach of exact changes before review, verification, or remediation | Reads selected targets, bounded related context, and applicable guidance; writes output only when explicitly requested |
| `eval-candidate-audit` | Propose repository eval cases from caller-selected sanitized session evidence | Reads only selected evidence and current suite definitions; writes output only when explicitly requested |
| `eval-harness-experiment` | Compare paired harness or instruction variants under protected quality gates | Reads committed selected surfaces, canonical baseline receipts, and project-eval-bound candidate runs; writes only explicit context/result outputs and never applies patches |
| `eval-suite-audit` | Recommend compact, evidence-preserving lifecycle changes for a selected committed eval suite | Reads committed definitions and explicitly selected compatible evidence; writes output only when explicitly requested |
| `grill-me` | Pressure-test decisions, plans, artifacts, and diagnoses | None |
| `project-eval` | Inspect readiness, bootstrap, run, grade, compare, and exchange bounded local repository evaluations | Reads repository-owned definitions; bootstrap writes only an explicitly selected absent eval root; model runs and private state remain separate explicit operations |
| `project-review` | Review bounded changes under root and nested `REVIEW.md` guidance | Reads project source and optional user guidance; writes output only when explicitly requested |
| `review-and-fix` | Safely address local review findings through decision, verification, and fresh-review gates | Reads bounded project/review/verification data; changes only eligible or approved local files |
| `review-guidance-audit` | Improve hierarchical `REVIEW.md` guidance without editing it | Reads selected project files and review guidance; writes output only when explicitly requested |
| `verification-harness-audit` | Assess whether selected local checks provide meaningful, timely, reliable protection | Reads bounded harness, context, guidance, and authorized command summaries; writes output only when explicitly requested |
| `verify-project` | Plan or perform evidence-driven verification of exact current local changes | Reads bounded project context; may run caller-authorized local checks and create only declared disposable outputs |
| `serve-artifacts` | Host and revoke transient web artifacts locally or through a selected private-network adapter | Private OS-native artifact copies, lifecycle state, and optional adapter ownership |
| `todo-capture` | Preserve deferred work as shared pickup pointers | Private OS-native state directory |
| `tool-audit` | Audit local tools, agent usage, friction, and permissions | Private OS-native state plus read-only transcript access |

See [compatibility](docs/compatibility.md) for the tested support matrix. The
[agent-context guide](docs/agent-context.md) explains how to layer private work,
home, or domain knowledge over the public defaults without committing it here.
The [artifact host guide](docs/artifact-host.md) covers temporary interactive
visuals, framework output, lifecycle limits, and provider-neutral browser access.
The [change-impact guide](docs/change-impact.md) explains exact target binding,
bounded related context, impact relationships, and advisory handoffs into review,
verification, and remediation planning. Those three consumers now invoke it
conditionally for unresolved material reach and skip it for contained work.
The [project-review guide](docs/project-review.md) covers hierarchical review
policy, trusted-base behavior, structured findings, and verification authority.
The [review-and-fix guide](docs/review-and-fix.md) explains neutral reviewer
normalization, conservative automatic-fix eligibility, canonical verification,
and fresh acceptance.
The [review-guidance audit guide](docs/review-guidance-audit.md) explains scoped
guidance analysis, context compaction, placement, and when automated checks can
replace or only support review rules.
The [verification harness audit guide](docs/verification-harness-audit.md)
explains harness-centered scope, assertion and command-wiring analysis, local CI
inspection, evidence calibration, and canonical output.
The [verify-project guide](docs/verify-project.md) explains current-state target
binding, hierarchical `VERIFY.md`, progressive local checks, mutation evidence,
and canonical verification results.
The [local behavioral evaluation guide](docs/behavioral-evals.md) explains how
maintainers can run fresh-agent skill evaluations locally while keeping paid
model calls out of the canonical gate and GitHub Actions.
The [project evaluation system](docs/project-eval-system.md) includes
independently installable `project-eval` execution, `eval-candidate-audit`
discovery, `eval-suite-audit` lifecycle curation, and quality-gated paired
experiments through `eval-harness-experiment`. Installing that plugin exposes
the skills but does not alter a repository. `project-eval readiness` can inspect
setup without mutation, and its preview-first bootstrap creates a synthetic
starter only after explicit apply confirmation. Projects can separately adopt
the optional `instructions/project-eval-lifecycle.md` fragment.
The [skill ecosystem guide](docs/skill-ecosystem.md) maps current capability
roles, safe handoffs, workflow bundles, and supporting infrastructure. Its
[roadmap](docs/skill-roadmap.md) separates the next local capability from likely
and exploratory ideas without treating them as shipped features.

## Install a skill

Use a tagged checkout or release rather than an unpinned `main` when installing
for repeatable use. For an ownership-aware installation, clone the tagged toolkit
release, then install only the selected skill:

```bash
git clone --branch v1.15.0 --depth 1 https://github.com/kimgea/agent-kit.git
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
`project-review` plugin groups change-impact, project review, review-and-fix,
review-guidance audit, verification-harness audit, and verify-project. The release
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

- `instructions/` — reviewed global or project instruction fragments that
  require deliberate human adoption, including optional eval lifecycle triggers.
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

Read [AGENTS.md](AGENTS.md) and [CONTRIBUTING.md](CONTRIBUTING.md), then validate
the final commit range with the same conservative selector used by pull-request
CI:

```bash
python scripts/agent_kit.py validate-range --base BASE_SHA --head HEAD_SHA
```

The selector uses a focused documentation profile only for the narrow documented
allowlist in a clean checkout and otherwise runs the full canonical gate. Run
that full gate directly for release preparation or when an exact clean range is
unavailable:

```bash
python scripts/agent_kit.py check
```

The full gate validates catalog parity, skill frontmatter and UI metadata, local links,
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
