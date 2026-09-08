# Lifecycle rubric

## Actions

- `keep`: preserve distinct useful behavior coverage.
- `refresh`: retain intent while updating stale fixtures, terminology,
  architecture, or grading details.
- `merge`: combine two or more overlapping cases into one bounded case.
- `simplify`: reduce context, assertions, repetitions, or setup without losing
  the protected behavior.
- `demote`: lower owner-visible importance or move coverage out of a required
  profile. This always requires a decision.
- `retire`: remove a case only on a permitted evidence-backed retirement basis.

## Retirement threshold

Permitted retirement bases are removed behavior, duplicate coverage,
superseded coverage, obsolete fixture/architecture, no unique agent-behavior
value, or high cost without unique coverage. Age, repeated passing, and absence
of recent failures may support context but are never sufficient bases.

For `retire`, name what unique coverage remains and where replacement coverage
lives. If coverage is lost, changed, or unknown, require a decision. Git history
is the archive after a separately authorized actor removes the current case.

## Compaction and additions

Look for duplication and unnecessary context at every suite size. Increase the
search pressure as fixture bytes, prompt context, repetitions, or run time grow.
Before proposing new coverage, check whether an existing case can be extended,
parameterized, merged, refreshed, or replaced more compactly.

## Confidence and readiness

Confidence describes evidentiary support, not importance. A non-keep change is
ready only when confidence is at least medium, coverage is preserved, cost does
not materially increase, and no material limitation remains. Demotion, coverage
loss/change/uncertainty, and cost increase/uncertainty require a decision.
