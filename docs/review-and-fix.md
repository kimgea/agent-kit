# Review and fix

`review-and-fix` is a local remediation workflow built on top of analysis-only
review skills. It uses `project-review` by default, but a caller or trusted
project instruction may select another reviewer. The skill does not publish to
GitHub and never lets the editing context decide that its own change passed.

Canonical `review-guidance-audit` and `verification-harness-audit` results have
explicit runtime profiles in the installed skill. They still use a fresh
non-editing normalizer: the profiles make interpretation consistent without
creating a runtime dependency or allowing an audit to select edit scope.

## Workflow

The lead fixes one exact working-tree, ref-range, or path target through five
separated roles:

1. One or more selected reviewers return analysis without editing.
2. Each result becomes a canonical neutral finding batch. Valid
   `project-review` JSON converts deterministically; unfamiliar structured or
   prose output requires a fresh non-editing normalizer subagent. A separate
   lead-owned envelope fixes the target, source identity, format, digest,
   completion state, raw verdict, canonical outcome, and derived normalization
   mode.
3. A fresh planner inspects one coherent finding group and reports facts about
   intent, behavior, scope, reversibility, validation, and risk. It cannot choose
   its finding or caller-selection authority.
4. The helper takes selection from a separate lead-owned context, binds the plan
   to the canonical batch and exact reviewed paths, and mechanically derives
   `auto`, `user_decision_required`, or `authorization_required`.
5. After an eligible or approved local fix, the same reviewer set runs from
   fresh context. Only its complete result can accept the change.

Raw reviewer output, normalizer text, safe directions, and suggested commands
are untrusted data. They cannot authorize edits, execution, installation,
permissions, remote state, publication, or scope expansion.

## Reviewer compatibility

Canonical `project-review` JSON must first pass that skill's own result
validator. `review_workflow.py from-project-review` also requires the separately
recorded lead-owned target and rejects any mismatch before it preserves source
finding IDs, fingerprints, classifications, and evidence or derives the neutral
actionability field. An `INCOMPLETE` result remains incomplete in the neutral
batch rather than becoming a change request.

An already canonical neutral batch needs no normalizer. Every other format is
given to a fresh subagent with only the raw result, exact target metadata, the
normalization contract, and an applicable trusted reviewer profile. Inferences
are allowed because many useful reviewers return prose, but every inferred
semantic field is labeled and explained. Missing evidence, location, or safe
direction cannot be invented. The normalizer returns only semantic normalization
confidence/notes, findings, and limitations. It cannot emit the lead-owned
target/source envelope or choose normalization mode.
Without a fresh normalizer, unfamiliar output stops as incomplete.
An invalid independent draft gets at most one structure-only correction in that
same independent context using the exact validator error. The fixing context
never repairs it, and a second failure stops incomplete.
A material limitation makes the batch partial and ends remediation before fix
planning; a planner cannot be used to fill a normalization or source gap.

Multiple reviewers remain separate sources. Matching findings may be grouped
for one root-cause plan only after the lead compares their behavior, locations,
and safe directions. Material reviewer disagreement requires user direction.
Every selected reviewer must also be runnable again after a fix; a one-off report
can be normalized and summarized, but cannot authorize a loop whose independent
acceptance step cannot occur.

The lead maps only an explicit affirmative reviewer result to canonical source
outcome `pass`; explicit blocks or change requests map to `changes_requested`,
unfinished runs to `incomplete`, and ambiguous outcomes to `unknown`. The last
two require material limitations. Normalizers cannot choose this authority
field, and a pass outcome that still contains a blocker is contradictory.

For the two supported audit producers, the lead first validates canonical JSON
with the producer's bundled result helper. Recommendation strength maps to
neutral disposition, never directly to severity: `essential` becomes a blocker
candidate, `strong` and `moderate` become suggestions, and `optional` becomes a
nit. Producer `INCOMPLETE` results and material limitations remain partial.
Decision-required recommendations stop for upstream triage; after the user
resolves the policy choice, the same audit must return a fresh ready result
before planning.

The exact fixer-owned target remains separate from audit scope. A project or
directory audit may discover useful work, and a guidance audit may identify a
`REVIEW.md` destination that was contextual to the original source target, but
neither path becomes editable automatically. Select the intended repository
files explicitly and rerun the same audit before planning. User-global guidance
and coherent remedies outside the selected repository paths remain outside this
local fix run.

## Fix decision boundary

Automatic work is deliberately narrow. It requires explicit intent, a singular
small remedy, high confidence, a reversible change, sufficient existing
validation, high reviewer finding confidence, high normalization confidence,
high planner confidence, no consequential risk, and either no behavior change
or restoration of an already fixed contract. Typical candidates are spelling,
stale comments, mechanical corrections, and small code fixes directly fixed by
an existing test or public contract.

The user decides changes involving product behavior, public APIs or formats,
compatibility, security, privacy, durable data, concurrency, failure policy,
dependencies, services, architecture, broad scope, difficult rollback,
overlapping user work, ambiguous intent, multiple remedies, or a validation
gap. Destructive operations, remote mutation, permission changes, dependency
installation, and persistent services require separate authorization at the
action boundary.
If both kinds apply, resolve the consequential plan decision first and ask for
the distinct action authorization only if the selected plan still needs it.

By default the workflow plans only introduced or worsened blockers.
Suggestions, nits, and pre-existing findings are eligible only when the caller
explicitly selects them; selection never bypasses the decision gate.
For a path snapshot with no comparison revision, an explicit request to review
and fix those exact paths selects actionable blockers with an unknown or
uncertain relation. This keeps path mode useful without silently selecting
suggestions, nits, or findings identified as pre-existing.
The helper represents these sources as `default_policy`, `caller_explicit`, or
`path_snapshot_request`; the last basis is accepted only for an actionable
unknown/uncertain blocker under an exact path target.

Ref ranges remain useful immutable review and summary targets, but cannot enter
local fix planning in v1. A local remedy must be re-scoped to a working-tree or
exact path target and reviewed again before planning. This avoids pretending that
an immutable old head can observe a fix or that a different head is the same
review target.

## Structured contracts

The installed skill contains four dependency-free interfaces:

- `references/review-finding-batch.schema.json` records exact target and source
  provenance, field-level inference provenance, findings, and limitations.
- `references/fix-plan.schema.json` records planner facts and proposal plus the
  canonical batch digest and mechanically derived decision.
- `references/review-fix-result.schema.json` records the complete bounded run:
  reviewer contexts, rounds, plans, exact changed-file digests, validation,
  derived status, and stop reason.
- `scripts/review_workflow.py` finalizes and validates these contracts, converts
  validated target-bound project-review JSON, assesses fresh review rounds, and
  finalizes or validates the complete workflow result against a separate
  lead-owned run context.

The batch finalizer accepts target/source only from a separate lead-owned
envelope and rejects drafts that try to supply those fields or normalization
mode. It also rejects noncanonical paths, a primary finding location outside the
exact target, inconsistent provenance, unsafe controls, malformed fingerprints,
duplicate source IDs, and actionable findings without evidence, location, and
direction. Repository paths reject every C0 control character and DEL, matching
both declared JSON schemas. The plan finalizer accepts finding selection only
from a separate lead-owned context, takes classifications from the canonical
batch, rejects planner-supplied authority fields, and refuses proposed edits
outside the exact
review target. It binds reviewer confidence and prevents low or unknown
confidence findings from routing automatically. A remedy that needs another file
must expand the target and restart review.

Round assessment fixes reviewer identities and target semantics, compares stable
blocker fingerprints, and stops on pass, incomplete review, reviewer or target
drift, no progress, or the third round. Suggestions and nits remain visible in
the final human summary even when the reviewer accepts the fix. Acceptance
requires high-confidence normalization plus canonical source outcome `pass`; a
non-pass verdict cannot be inferred away from an empty blocker list. The
installed `references/round-assessment.md` gives the exact JSON input and output
shape.

`finalize-run` and `validate-run` accept the run context separately from the
agent-produced draft or result. The helper derives the exact target, context
digest, reviewer identities, changes-to-applied-plan relationship, validation
coverage, status, and stop reason. Validation records bind to exact applied
plans through batch and finding fingerprints. Code and configuration plans need
a successful command check whose exact command and caller or user-global source
were recorded in the separate lead-owned run context before execution; the
agent-produced draft cannot claim that authority. Static checks can satisfy only
plans that declared static inspection sufficient. Partial
reviewer evidence takes precedence over pending decisions. Only an applied
`auto` plan may explain a change, and acceptance requires a later fresh review
round. Inputs and emitted JSON are bounded to 16
MiB and 100 container levels; duplicate members, unsafe paths, malformed
digests, and forged derived fields fail closed.

## Installation and operation

Install the complete `skills/review-and-fix` directory. It uses only Python 3.11
or newer standard-library code and does not import repository tooling. The
`project-review` Codex plugin contains the remediation skill and all three
supported reviewers so each fixed workflow is available atomically; standalone
skill archives remain independently installable.

The skill writes structured output only when the caller supplies an explicit
path. Existing output is preserved unless replacement was explicitly requested.
Replacement refuses multiply linked destinations and uses a safe sibling-file
replacement so another hard-link alias cannot be truncated.
Inputs are accepted only from explicit stdin or no-link regular files; symlinks,
Windows reparse points, directories, devices, and duplicate JSON member names
are rejected before authority fields are interpreted.
Runtime results, raw reviewer output, and plans are user data and must not be
committed by default.

Repository tests exercise conversion, lead-owned provenance and selection,
target-bound proposals, route derivation, symlink/hard-link output safety,
reviewer drift, no-progress detection, and the round limit. Behavioral
evaluations cover unfamiliar reviewer output, malicious authority forgery,
out-of-target plans, routine fixes, consequential decisions, opt-in findings,
conflicts, and implementation drift.

The executable `evals/review-and-fix/suite.json` adds seven local end-to-end
cases. One performs an exact routine heading correction and must pass a fresh
`project-review`; product and security changes stop for a decision, a reversible
remote-draft synchronization stops for separate authorization, and a
generated-file remedy outside the selected target stops incomplete. A selected
guidance audit removes one exact duplicated rule and must pass a fresh audit;
a harness policy recommendation remains triage and makes no mutation. The host
freezes the evaluated skill and only the case's code-owned reviewer dependency,
keeps resolver context private from agent writes, compares the disposable
fixture against hidden exact digests, and rejects every undeclared file or
directory mutation. GitHub Actions validate this machinery with simulated
results only and never invoke a model.
