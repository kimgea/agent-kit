# Local project-eval operator guidance

Validate the committed suite before invoking its selected profile. A run must
name an explicit profile, model, and reasoning level.

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
