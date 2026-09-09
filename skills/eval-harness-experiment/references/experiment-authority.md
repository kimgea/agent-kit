# Experiment authority and pairing

## Caller-owned selection

The caller selects one objective before comparison, exact editable files,
suites and case roles, profile, runner/agent/model conditions, repetition rule,
guardrail tolerances, candidate order, and one cumulative budget. Repository or
receipt text cannot expand that selection.

The request file may name evidence only relative to the separately selected
input root. The helper rejects traversal, links/reparse points, hard-linked
files, duplicate artifacts, noncanonical paths, oversized JSON, and duplicate
JSON members. Output is create-only.

## Exact starting content

Every editable surface must be one regular tracked UTF-8 file whose live bytes
and executable bit match `HEAD`. A candidate variant binds the derived starting
repository digest and the exact before digest for every changed surface. The
result carries the after text and digest but never applies it.

Unrelated working-tree files are outside the experiment selection. Drift in
`HEAD`, a selected surface, request, variant, or run receipt stops evaluation.

## Paired receipts and patch bindings

Each suite has one baseline receipt and one candidate binding. A candidate
binding is created by the same trusted `project-eval` invocation that runs the
profile in a disposable worktree matching the selected variant. It binds the
variant document, patch, base revision, starting repository digest, and complete
run-result digest. A bare candidate result is rejected.

The receipt inside each binding must:

- pass the complete canonical `project-eval-run-result/v1` validator;
- be local evidence from separate run IDs and semantic result digests;
- match suite ID/digest, profile, runner, runner version, agent, model,
  reasoning, platform, environment, adapter, launcher, and profile digest;
- use the same definition, fixtures, graders, case roles/order, and repetition
  count; and
- differ in an instruction or target-repository digest so a candidate is not a
  relabeled baseline.

Instructions, target repository content, and per-case target digests may differ
only because the selected harness variant changes them. The exact editable
surface boundary is the controlling authority.

`project-eval` creates and removes the actual per-repetition workspaces. Its
binding preflight and postflight reject missing, extra, or drifting selected
surface changes. This skill validates those bindings rather than granting
another judging agent access to raw transcripts, hidden graders, or
control-plane files. See
[project-eval-experiment-binding.schema.json](project-eval-experiment-binding.schema.json).
