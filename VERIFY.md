# Agent Kit verification

## Required for pass

- Run `python scripts/agent_kit.py check` after all source, catalog,
  documentation, tracking, test, and evaluation changes are complete.
- Use focused standard-library unit tests while iterating, then rely on the
  canonical gate to check catalog parity, links, packages, generated-file
  hygiene, schemas, evaluation fixtures, and the full test suite.
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
