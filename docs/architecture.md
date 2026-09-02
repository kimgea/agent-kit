# Repository architecture

## Layers

`toolkit.toml` is the reviewed resource registry. `scripts/agent_kit.py` is the
repository lifecycle interface. Installable resources remain self-contained under
`skills/`; repository tooling never becomes a runtime import for a deployed skill.

Each installable skill belongs to exactly one cataloged plugin. Release packaging
derives plugin manifests, plugin trees, and the marketplace from the catalog and
skill UI metadata. These are distributions of canonical skill sources, not a
second development layer. A plugin may group related skills later, but a single
skill is the default ownership and versioning boundary. The `artifacts` plugin is
an explicit coherent group: its producer and host remain independently installable,
but together form the normal create-and-deliver workflow.

Non-skill resources stay organized by asset type:

- instructions, templates, and policies are reviewed text assets;
- hooks are deterministic defense-in-depth components;
- adapters describe harness-specific integration;
- tools are reusable executables or wrappers;
- evaluations are behavioral fixtures outside installed skills.

Executable behavioral evaluation remains repository-maintainer infrastructure.
The provider-neutral core materializes synthetic repositories, resolves
lead-owned target context in host-private storage, grades canonical JSON,
detects exact file and directory mutation, and records bounded local evidence.
Fixed runner adapters and skill dependencies are selected in trusted harness
code rather than suite data; every dependency is frozen and separately
digested. V1 invokes Codex only through an explicit local command. Descriptive
suites remain valid for skills that have not adopted a stable executable
contract.

## Context layering

`agent-context` provides an optional read-only bridge between public defaults and
separate private context repositories. It loads only sources registered in the
user's OS-native registry and selects project context by an exact resolved path
or exact Git remote. There is no directory crawling, fuzzy matching, network
lookup, or automatic project enrollment.

Layers merge from public to user, profile, domain, repository, and explicit
session context. Later values override earlier values within mergeable knowledge
categories, while provenance remains visible. Public invariants are locked;
private context cannot replace repository instructions, permission boundaries,
or skill safety rules. Skills remain complete without any private source.

## Transient artifact delivery

`build-interactive-diagram` is a producer and `serve-artifacts` is the shared
delivery layer. They communicate through a directory plus the host's JSON CLI,
never cross-skill Python imports. This keeps future producers independent from
server implementation details and leaves a stable seam for a later MCP adapter.

The host is a local-first, standard-library background service backed by private
OS-native state. It defaults to loopback and can bind to one explicitly reviewed
private IPv4 interface; wildcard listeners remain forbidden. Static bundles are
validated and copied atomically under random TTL-bound IDs. An optional proxy accepts
only already-running loopback HTTP targets; the host never runs builds or applications.

Remote access is a replaceable adapter boundary: SSH forwarding, direct private
LAN or VPN binding, and an existing reverse proxy all use the same host contract.
Tailscale Serve is one optional adapter whose preview-first setup owns one path,
preserves unrelated handlers, and never enables public Funnel access. Durable
documentation and cloud publication remain separate owning-repository workflows.

## Project review

`project-review` separates deterministic review context from semantic judgment.
Its resolver enumerates a bounded Git change or explicit path scope and loads the
applicable `REVIEW.md` chain for each target. For change reviews, repository
guidance comes from the trusted base commit or committed `HEAD`, so changed rules
cannot lower the bar applied to their own change.

One lead reviewer owns evidence, calibration, deduplication, coverage, and the
verdict. It may delegate coherent path groups, but subreview results remain
candidates until the lead verifies them. The lead creates one schema-versioned
JSON result; a standard-library helper validates it and deterministically renders
the human report. GitHub publishing, fixes, approvals, and merges are separate
consumer boundaries.

Static inspection is the default. Repository guidance may recommend verification
commands but cannot authorize them. Only the current caller or bounded user-global
review guidance can authorize execution, after which normal agent permissions
still apply.

`review-and-fix` is the local remediation consumer. It keeps each reviewer
result as a separate neutral batch, deterministically bridges validated
`project-review` JSON, and uses a fresh subagent to normalize other output.
Installed profiles define conservative mappings for canonical
`review-guidance-audit` and `verification-harness-audit` results without adding
producer-specific runtime imports or deterministic adapters. Lead-owned
envelopes keep target/source provenance outside normalizer control and carry an
explicit canonical reviewer outcome; deterministic
`project-review` conversion also rejects a reviewer target that differs from the
lead-owned expected target. A second fresh context reports facts for a proposed
remedy; lead-owned selection stays outside planner control, and the runtime
helper binds those facts to the canonical batch and exact reviewed paths before
mechanically deriving whether the plan is routine, needs a user decision, or
requires separate authorization. Audit scope never grants edit scope: a related
guidance destination or harness path must be explicitly selected and freshly
audited before planning. Producer incompleteness and decision-required
recommendations stay fail-closed.
The fixer cannot accept its own result: the same reviewer set reruns from fresh
context, with stable fingerprints, target/reviewer drift detection, no-progress
stopping, an explicit pass outcome, and a three-round limit. Ref ranges are
immutable review-only snapshots; remediation uses a freshly reviewed
working-tree or path target.
The optional canonical workflow result binds the run to a separate lead-owned
context, derives status from embedded canonical batches and plans, matches exact
changed-file digests to applied automatic plans, and requires a review round
after the last accepted change. Local behavioral fixtures independently enforce
the same mutation boundary; the workflow result cannot authorize or conceal an
undeclared edit.

`review-guidance-audit` maintains the policy layer rather than reviewing or
fixing a change. Its current-filesystem resolver maps a caller-selected file
part, file, directory, or project to every relevant file and the applicable
user-global plus root-to-nearest repository guidance chain. The semantic agent
inspects guidance and implementation independently, then reconciles usefulness,
coverage, placement, conflicts, and context cost. A separate finalizer binds the
result to resolver-owned target and provenance and renders human output from the
same canonical JSON.

Harness recommendations remain subordinate to guidance recommendations. A
complete deterministic check required in the ordinary review loop may replace
prose; slow, late, optional, or partial controls only support or narrow the
remaining human-review rule. General harness auditing and future storage of
review-cycle pain-point evidence remain separate adapter and skill boundaries.

`verification-harness-audit` owns that general harness-quality boundary. Its
current-filesystem resolver freezes a caller-selected part, file, directory, or
project; progressively records no-link inventory; loads the optional
active-agent user-global plus root-to-nearest repository review chain; and keeps
related implementation and contracts outside the finding boundary. Every
installed runtime helper remains inside the skill. Shared hierarchy behavior is
checked through repository conformance fixtures rather than a cross-skill
runtime import.

One lead traces existing requirements through checks, assertions, fixtures,
canonical command wiring, feedback tiers, platforms, isolation, determinism,
and failure visibility. Local provider-specific CI configuration is project data
for that trace, but provider APIs, remote run state, and provider-wide policy are
outside the boundary. Static analysis is the default; only the caller or bounded
user-global guidance can authorize an exact local command plan.

The semantic draft cannot own target, inventory, guidance, execution, evidence
source, identifier, count, or status fields. A standard-library finalizer binds
recommendations to resolver-owned authority, calibrates measured timing and
flakiness evidence, derives `INCOMPLETE`, `IMPROVEMENTS`, or `PASS`, and renders
human output from canonical JSON. `review-and-fix` consumes that output through
its installed conservative reviewer profile and independent generic
normalization. A deterministic adapter, publisher, evidence store, and dedicated
harness-remediation workflow remain separate future components.

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
metadata, descriptive evaluation JSON, executable suite fixtures and simulated
grading, local Markdown links, generated-file hygiene, Python compilation, and
unit tests. It snapshots Git status before and after execution to detect
validation side effects. It never invokes an agent model; model-backed behavioral
runs are explicit local operations and never part of hosted CI.

Release packaging uses fixed timestamps, sorted paths, stable permissions, and a
single Linux release job. It emits standalone skill archives, cataloged plugin
archives, and one marketplace archive. Bundles include the repository license and
third-party notices, and one `SHA256SUMS` covers every archive.

## Trust boundaries

Automatic permission eligibility is defined in `policies/permission-boundary.md`.
The catalog documents sensitivity and setup requirements but does not itself
grant trust. Agent instructions, GitHub branch controls, pinned Actions, code
ownership, tests, and human review provide independent layers.
