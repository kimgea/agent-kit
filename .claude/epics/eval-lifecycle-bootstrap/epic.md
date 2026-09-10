---
name: eval-lifecycle-bootstrap
status: in-progress
created: 2026-09-10T10:47:43Z
updated: 2026-09-10T11:42:31Z
progress: 75%
prd: .claude/prds/eval-lifecycle-bootstrap.md
github: null
---

# Epic: eval-lifecycle-bootstrap

## Overview

Make the existing local evaluation family easy to discover and adopt while
preserving its explicit-authority and local-first boundaries.

## Architecture Decisions

- Plugin installation exposes capabilities but does not modify repositories.
- Readiness is deterministic and read-only.
- Bootstrap is preview-first, create-only, and requires explicit apply plus
  confirmation.
- The starter suite proves mechanics but does not claim project coverage.
- Project lifecycle guidance is an optional human-adopted instruction fragment.
- Model-backed execution remains a separate explicit operation.

## Implementation Strategy

1. Implement and document readiness and bootstrap contracts.
2. Add the optional lifecycle fragment and improve discovery surfaces.
3. Prove deterministic, adversarial, cross-platform, and behavioral boundaries.
4. Validate and independently review the completed slice.

## Tasks Created

- [x] 001.md - Implement readiness and preview-first bootstrap
- [x] 002.md - Add lifecycle guidance and discovery integration
- [x] 003.md - Add tests and behavioral evaluation coverage
- [ ] 004.md - Validate, review, and prepare delivery

Total tasks: 4
Parallel tasks: 0
Sequential tasks: 4
Estimated total effort: 6-10 hours
