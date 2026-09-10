# Local project-eval operator guidance

Start by inspecting repository readiness. If no suite exists, preview the
synthetic bootstrap before any creation. Applying the starter requires one
explicit operation with both apply and confirmation flags; adopting lifecycle
guidance in project agent instructions is a separate deliberate change. Neither
operation invokes a model.

For an existing suite, validate the committed definition before invoking its
selected profile. A run must name an explicit profile, model, and reasoning
level, and model execution must be explicitly requested by the caller.

The workspace and host roots contain private, disposable run material. The
runner securely creates absent roots with private permissions. Existing roots
are accepted only when they are already private. Prefer letting the runner
create absent roots instead of adding a manual setup step with default
permissions.

The `smoke` profile includes a fixed local Python check, so its caller must
explicitly allow project checks. It declares no network access or hidden
grader. Return the canonical result without initializing persistent state.

After the run, validate the canonical receipt, confirm disposable contents were
removed, and confirm the repository remains clean. Record this plan in
`run-plan.json` using only values from `run-plan.schema.json`. Do not invoke a
model or use network access while preparing the plan.
