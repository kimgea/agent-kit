# Eval harness experiment review guidance

- Treat caller selection, exact surface binding, complete run-receipt
  validation, paired conditions, holdout isolation, budget accounting,
  deterministic classification, patch binding, and create-only output as trust
  boundaries.
- Prove that speed or cost cannot create a winner below the quality floor and
  that noisy wins, overfitting, regressions, effects, and drift fail closed.
- Verify the skill never edits the active checkout and that applying a returned
  patch remains outside its authority.
- Verify standalone packages do not import another installed skill or
  repository-only code.

