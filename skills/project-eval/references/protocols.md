# Project-eval protocol family

## Contents

- Repository adoption
- Definition contract
- Result families
- Portable bundles
- Private state
- Consumer rules

## Repository adoption

Skill or plugin installation does not create evaluation definitions. Use the
deterministic `readiness` operation to distinguish a ready suite from missing,
partial, invalid, or unsafe setup. Its canonical
`project-eval-setup-result/v1` output can be consumed by another agent or tool.

`bootstrap` is preview-only unless the caller explicitly selects both `--apply`
and `--yes`. It creates one absent `evals/project/` tree from bundled,
digest-listed assets and never merges with or overwrites existing content. The
starter case proves materialization and grading mechanics only. It is not
evidence that the adopting project's behavior is covered.

Project owners may separately adopt `instructions/project-eval-lifecycle.md`
as project-level agent guidance. Neither installation nor bootstrap edits agent
instructions, initializes private state, schedules work, or invokes a model.

## Definition contract

The recommended repository layout is `evals/project/`, with one or more explicit
suite JSON files and bounded relative fixture references. Definitions never
load by ancestor traversal and never gain authority from `AGENTS.md`.
Pass the repository, eval root, and suite path separately; the suite and every
fixture must resolve beneath the eval root without link-like components.

Suite schema: `project-eval-suite/v1`.

Each case declares:

- stable identifier, title, kind, and owner-set importance;
- relative fixture and task text;
- supported platforms and required capabilities;
- evaluator-owned assertion identifiers; and
- whether the case belongs to visible development, hidden holdout, or protected
  regression coverage.

Profiles bind selected cases, repetitions, invocation/time/token/cost ceilings,
network availability, and permitted effect classes. A retry consumes the same
profile envelope.

## Result families

Schemas version independently:

- `project-eval-run-result/v1`;
- `project-eval-setup-result/v1`;
- `project-eval-experiment-binding/v1`;
- `project-eval-comparison/v1`;
- `project-eval-bundle/v1`;
- `eval-candidate-result/v1`;
- `eval-experiment-result/v1`; and
- `eval-suite-audit-result/v1`.

They share producer identity, exact target and configuration digests,
completion, outcome, next action, bounded typed evidence references, and
material limitations. They do not share one universal payload. Run receipts
bind the repository, definition, fixture set, prepared case, grader, runner,
agent, model, instructions, profile, environment, and canonical configuration
before comparison. `project-eval-comparison/v1` records an exact-condition
comparison without granting authority or collapsing correctness, completion,
important-case performance, duration, and tokens into one score.

Canonical JSON is the semantic result. Render human output only after validation.
Consumers reject incompatible major versions and preserve producer-native states.

`eval-experiment-result/v1` binds one predeclared objective, exact starting
repository surfaces, baseline and candidate run digests, matching runner
conditions, protected quality gates, cumulative budget consumption, stop
reason, and structured candidate patches. A `clear_improvement` requires a
strict beyond-tolerance gain plus every repetition, required-case, holdout,
regression, effect, budget, and limitation gate. The result never grants patch
application authority.

`project-eval-experiment-binding/v1` is emitted only when an explicit profile
run receives both an experiment variant and a create-only binding destination.
It binds the complete canonical result to that variant, patch, base revision,
and starting surfaces after preflight and postflight checks. Run the producer
from a trusted copy outside the worktree whose harness surfaces are being
compared.

## Portable bundles

A bundle is a deterministic ZIP with stored entries, fixed metadata, a canonical
`manifest.json`, one canonical `result.json`, and optional bounded sanitized JSON
evidence. Every member has a size, media type, and SHA-256 digest.

Export replaces free-form failure and evidence summaries with fixed redaction
markers while retaining their digests. Only strict run-result evidence is
portable in the first slice; later result families must not be added to bundles
until their complete schemas and privacy behavior are implemented. Import
validates the complete archive before writing private state. Reject
absolute paths, backslashes, dot segments, links, special entries, duplicate
names, unknown members, excessive counts or sizes, digest mismatch, invalid
schemas, and prohibited sensitive fields. Imported evidence is always labeled
`evidence_only`; a hash proves integrity, not who produced the bundle.

Do not include raw transcripts, prompts, reasoning, event streams, stderr,
credentials, environment-variable values, or disposable workspaces.

## Private state

Default roots:

- Linux: `$XDG_STATE_HOME/agent-kit/project-eval`, otherwise
  `~/.local/state/agent-kit/project-eval`;
- macOS: `~/Library/Application Support/Agent Kit/project-eval`;
- Windows: `%LOCALAPPDATA%\Agent Kit\project-eval`.

Git repositories store an opaque namespace identifier in the Git common
directory so worktrees share evidence while a fresh clone starts independently.
Non-Git projects bind to a digest of the canonical local path. Only an explicit
user option may select another state root or link clones. Repository content
cannot redirect private state.

Receipts and bundles are immutable and content-addressed. The index is rebuilt
from those files and is never authority. Retention may remove unpinned evidence;
committed definitions must remain usable without it.

## Consumer rules

- Validate known canonical artifacts before use.
- Treat imports as evidence, not an accepted baseline or action authority.
- Compare runs only when relevant case, agent, model, runner, environment, and
  budget dimensions match.
- Use a consumer-owned deterministic adapter for known formats or a fresh
  bounded non-editing normalizer for unfamiliar output.
- Keep target, command, edit, persistence, publication, and acceptance authority
  with the consuming lead.
