# Agent Kit verification

## Required for pass

- On the final commit, run `python scripts/agent_kit.py validate-range --base
  BASE_SHA --head HEAD_SHA` from a clean exact-head or direct merge checkout.
- The documentation profile is limited to the named root maintainer documents,
  `docs/**/*.md`, `.claude/**/*.md`, and the pull-request template. Every mixed,
  empty, unknown, unclassifiable, runtime, guidance, workflow, or release change
  uses `python scripts/agent_kit.py check`; never relabel one manually.
- Use focused standard-library tests while iterating. The selected final profile
  then checks its documented repository, tracking, compilation, and test scope.
- For platform-sensitive path, locking, process, or permission behavior, retain
  Linux and Windows coverage. A local Linux result does not establish native
  Windows behavior.

## Conditional expansion

- Rebuild all package forms and verify checksums and standalone self-containment
  when skill membership, plugin grouping, runtime files, or packaging changes.
- Run the affected deterministic behavioral suite after changing a canonical
  producer, consumer adapter, grader, or evaluation contract.
- Run fresh model-backed behavioral evaluations locally only when semantic skill
  behavior changes or retained evidence no longer matches the final harness.
  Never add agent-model execution to hosted CI.
- Apply the additional permission-boundary proofs in `AGENTS.md` when changing
  installers, permission setup, safe dispatchers, hooks, or command
  classification.

## Expected disposable artifacts

- Python bytecode caches, `.eval-results/`, and package output under `dist/` may
  be created by declared checks. They are disposable outputs, not authority to
  modify source, fixtures, configuration, guidance, or pre-existing user data.
- Use a separately allocated empty run-owned temporary directory for other
  transient check output. Do not treat every ignored path as writable.
