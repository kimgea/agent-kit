# Change impact

`change-impact` maps the evidence-backed reach of exact project changes. It
helps a later reviewer, verifier, planner, or fixer understand which callers,
contracts, tests, documentation, configuration, generated artifacts, platforms,
or safety boundaries deserve attention and why.

It does not decide that an affected path is defective, add that path to another
workflow, run checks, or edit anything.

## Boundary model

The skill keeps three concepts separate:

| Concept | Meaning | Authority |
|---|---|---|
| Selected target | Exact changed or explicitly selected paths being analyzed | Caller-owned |
| Frozen context | Related files inspected to prove a relationship | Read-only evidence |
| Suggested downstream scope | A reason another workflow may consider context, target, or claim expansion | Advisory only |

This separation prevents an import search or nearby test from silently turning
into review scope, command authority, or edit permission.

## Supported targets

- Git base/head ranges;
- the combined current working tree relative to committed `HEAD`, including
  visible untracked files; and
- explicit current files or recursively complete directories.

The first resolver pass freezes the selected target. After inspecting it, the
analysis lead may use bounded search to find concrete related files and rerun the
same target with those exact files as context. Only the final resolver context
may support canonical impact records.

For a ref range, before/after target content comes from Git objects, context from
the head, and guidance from the base. For a working tree, target-before and
guidance come from committed `HEAD`; current target-after and context are frozen
from the filesystem. Explicit paths use current content.

## Optional project knowledge

Applicable `REVIEW.md` and `VERIFY.md` files are loaded root-to-nearest for each
selected target. They can reveal review-sensitive contracts and verification
requirements, but remain evidence rather than authority. A changed guidance
file does not govern its own ref-range or working-tree introduction.

Projects do not need either file. Ordinary imports, calls, schemas, manifests,
tests, fixtures, documentation, and configuration can establish impact.

## Canonical workflow

The installed standard-library helpers are self-contained:

1. `impact_context.py` freezes target changes, text content, related context,
   guidance provenance, limits, and resolver limitations.
2. One semantic lead authors only impact judgments and inspected-path coverage.
3. `impact_result.py` rechecks current state where applicable, binds the context
   digest, rejects out-of-bound references, derives IDs, fingerprints, counts,
   coverage and status, and renders the human report.

Representative use:

```bash
python skills/change-impact/scripts/impact_context.py \
  --repo . --context tests/test_parser.py --output /tmp/impact-context.json \
  paths src/parser.py

python skills/change-impact/scripts/impact_result.py finalize \
  --context /tmp/impact-context.json --input /tmp/impact-draft.json \
  --format both
```

The example paths are caller-selected. Runtime helpers never execute a project
command. Result files are not written unless explicitly requested.

## Impact records

Each impact identifies selected source paths, affected target or frozen-context
locations, a typed relationship, direct/indirect/possible reach, confidence,
consequence, evidence, safe investigation direction, and one or more advisory
consumer purposes.

Typical purposes are:

- include a file as review or verification context;
- independently consider wider review target or verification claim scope;
- show a fixer that the remedy may have a wider blast radius;
- inspect potentially affected documentation; or
- ask the user when consequential intent must choose between outcomes.

`COMPLETE` means every selected target was inspected and no material limitation
prevented reliable impact analysis. It is not a correctness verdict. A complete
result can contain impacts or establish that no relationship beyond the selected
target is supported. `INCOMPLETE` never becomes “no impact.”

## Consumers

`project-review` can use impact paths as candidate context, `verify-project` can
use them as candidate claims and check-selection evidence, and `review-and-fix`
can use them while assessing remedy scope. These are compositional conventions,
not runtime imports. Each consumer validates the producer result, matches it to
its own lead-owned target, and retains all action and acceptance authority.

Third-party consumers may use the same canonical JSON. V1 intentionally ships no
automatic adapter, publisher, persistence backend, or mandatory integration.

## Evaluation and installation

Deterministic tests and local behavioral graders cover target modes, context
binding, trusted guidance, unsafe paths, drift, malformed drafts, canonical
rendering, positive impact, safe omission, and incomplete analysis. Hosted CI
runs no agent model. Fresh model-backed behavioral evaluation is an explicit
local maintainer operation.

Install the complete `skills/change-impact` directory. It requires Python 3.11
or newer and Git only for ref-range and working-tree targets. It has no network,
service, MCP, agent-product, or cross-skill runtime dependency.
