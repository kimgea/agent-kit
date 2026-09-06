# Impact rubric

Use this rubric to decide whether a relationship belongs in a change-impact
result. Impact is not defect severity.

## Relationship kinds

- `runtime_dependency`: imports, calls, dispatch, registration, ownership, or
  data/control flow connects the selected target to affected code.
- `public_api`: callers or users depend on an exported signature, name, shape,
  command, or documented compatibility promise.
- `data_or_wire_contract`: persisted, serialized, message, schema, migration, or
  protocol shape connects producer and consumer.
- `configuration`: behavior is selected or constrained by configuration,
  manifests, flags, or environment-facing declarations.
- `generated_artifact`: a source, generator, or checked-in output relationship
  may require coordinated regeneration or inspection.
- `test_or_fixture`: a test or fixture directly exercises or encodes the changed
  behavior. A filename resemblance alone is not proof.
- `verification_requirement`: trusted applicable `VERIFY.md` or an established
  verification entry point identifies relevant evidence.
- `review_policy`: trusted applicable `REVIEW.md` identifies a review-sensitive
  contract or boundary.
- `documentation`: user or maintainer documentation describes the changed
  behavior or public surface.
- `platform_or_packaging`: build, distribution, installation, plugin, OS, or
  release wiring consumes the changed surface.
- `security_or_privacy`: authentication, authorization, secret handling, trust,
  personal data, or ownership boundaries depend on the change.
- `operational_behavior`: failure policy, observability, deployment, rollback,
  service lifecycle, or resource use may change.
- `other`: a concrete relationship that does not fit above; explain it exactly.

## Reach

- `direct`: source evidence shows an immediate import, call, schema use,
  registration, explicit rule, or other first-order connection.
- `indirect`: a concrete chain of two or more supported relationships connects
  the selected target and affected location.
- `possible`: evidence establishes a plausible dynamic or conditional link but
  cannot prove activation statically.

Do not use `possible` as a home for speculation. If no concrete evidence anchors
the link, omit it or record a material evidence limitation.

## Confidence

- `high`: direct source or trusted contract evidence leaves no material competing
  interpretation.
- `medium`: evidence supports the relationship but dynamic selection, partial
  context, or more than one interpretation remains.
- `low`: bounded evidence supports only a possible link. Explain what would
  establish or dismiss it.

Lower confidence before broadening scope. Never upgrade confidence because a
relationship sounds risky.

## Downstream purposes

- `review_context`: relevant evidence for a review, without becoming a finding
  boundary.
- `review_target_candidate`: the review lead should independently decide whether
  the affected location belongs in its selected target.
- `verification_context`: useful for selecting or interpreting checks.
- `verification_claim_candidate`: the verifier should independently decide
  whether the affected behavior needs a material claim.
- `remediation_risk_context`: a fixer should account for the relationship before
  deciding whether a remedy remains small and singular.
- `documentation_candidate`: documentation may need inspection or coordinated
  update.
- `user_decision`: multiple consequential outcomes remain and intent must choose.

Purposes are recommendations, not authority. Prefer context purposes unless the
evidence specifically justifies considering a wider target or claim.

## Omit

Omit generic adjacency, naming similarity, directory co-location, broad “may
affect tests” statements, unrelated pre-existing defects, formatting concerns,
and relationships already represented by a more precise impact.
