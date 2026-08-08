# Repository architecture

## Layers

`toolkit.toml` is the reviewed resource registry. `scripts/agent_kit.py` is the
repository lifecycle interface. Installable resources remain self-contained under
`skills/`; repository tooling never becomes a runtime import for a deployed skill.

Non-skill resources stay organized by asset type:

- instructions, templates, and policies are reviewed text assets;
- hooks are deterministic defense-in-depth components;
- adapters describe harness-specific integration;
- tools are reusable executables or wrappers;
- evaluations are behavioral fixtures outside installed skills.

## Installation ownership

The installer resolves the selected harness home at runtime and stores ownership
under `<agent-home>/.agent-kit/state.json`. State records the exact content digest,
version, destination, and recoverable trash deployments. POSIX state directories
and files use `0700` and `0600`.

Install and update refuse symlinked resources, unowned destinations, and content
drift. Update stages and verifies a complete copy before moving the previous owned
deployment into trash. Uninstall also moves rather than deletes. Rollback selects
only an owned recorded deployment and accepts no caller-controlled source path.

Installation never invokes a skill permission bootstrap. This separation keeps a
general repository installer out of automatic permission lists and makes each
permission grant independently reviewable and removable.

## Validation

The canonical check validates catalog/resource parity, skill frontmatter, Codex
metadata, evaluation JSON, local Markdown links, generated-file hygiene, Python
compilation, and unit tests. It snapshots Git status before and after execution to
detect validation side effects.

Release packaging uses fixed timestamps, sorted paths, stable permissions, and a
single Linux release job. Each archive includes one complete skill directory plus
the repository license and third-party notices. `SHA256SUMS` covers every archive.

## Trust boundaries

Automatic permission eligibility is defined in `policies/permission-boundary.md`.
The catalog documents sensitivity and setup requirements but does not itself
grant trust. Agent instructions, GitHub branch controls, pinned Actions, code
ownership, tests, and human review provide independent layers.
