# Automatic permission boundary

Use this checklist before approving an agent command without prompting.

## Eligible shape

An automatically allowed command should have all of these properties:

- A pinned executable or script path, or a narrowly scoped trusted wrapper.
- One enumerated operation or fixed profile.
- No arbitrary interpreter, command string, executable input, custom path,
  request body, method override, or unbounded trailing arguments.
- Effects confined to documented read-only state or one owned private data store.
- Parser rejection tests for every argument outside the contract.
- A more restrictive project or managed rule can still override it.

## Keep approval-gated

- Installers and permission setup.
- Direct Python, shell, PowerShell, or Node execution.
- Version probes that execute discovered programs.
- Commands accepting custom configuration, history, output, or data paths.
- Network APIs that can select a method or carry a body.
- Prefixes whose longer forms can mutate, execute, or delete.

## Required lifecycle evidence

- Preview performs no writes.
- Install writes exactly the proposed entries.
- Repeated install is idempotent or performs a verified owned update.
- Removal validates ownership and removes only owned state.
- Drift causes refusal rather than overwrite.
- Linux and Windows command forms are tested.

Classification as `read` is a review input, not proof that a broad prefix is safe.
