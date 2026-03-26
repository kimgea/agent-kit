## Spec Checklist

### Before Writing

- Resolve the target spec root.
- Read the target spec folder if it already exists.
- Read the implementation queue only when the workspace has one.
- Read 1-3 nearby specs that are structurally similar when they exist.
- Confirm which phase the user asked for.
- If a phase is being skipped, note assumptions the skipped phase would have pinned down.
- Write only that phase. Do not modify existing spec files the user did not ask you to touch.

### Requirements Checklist

- [ ] **Summary**: 2-4 sentence overview of feature purpose
- [ ] **Glossary / Key Terms**: Domain terms defined to prevent ambiguity
- [ ] **Requirements list**: Each requirement has a stable ID, description, and acceptance criteria
- [ ] **Acceptance criteria**: Every requirement has testable conditions (Given/When/Then or verifiable statements)
- [ ] **In scope**: Clear statement of what this spec covers
- [ ] **Deferrals**: Explicitly deferred items with rationale
- [ ] **Boundaries and clarifications**: Assumptions, constraints, edge cases
- [ ] **Non-functional requirements**: Performance, security, auditability, data integrity
- [ ] **Implementation-agnostic**: No tech stack, no schemas, no code
- [ ] **Self-reviewed**: 2-3 scenarios (including edge cases) walked through; gaps found and patched

### Design Checklist

- [ ] **Architecture overview**: High-level structure with diagram (ASCII/Mermaid) when multi-component
- [ ] **Components and file paths**: Modules/files listed with repo-relative paths
- [ ] **Design decisions with rationale**: Choices, alternatives considered, trade-offs
- [ ] **Data models**: Schemas, interfaces, or structures in the target system's notation
- [ ] **Integration points**: How feature connects to existing code, with file path references
- [ ] **Code references**: Existing files the design builds on or modifies
- [ ] **Battle-test scenarios**: 2-3 realistic end-to-end scenarios traced through the design
- [ ] **Risks and mitigations**: Failure modes, bottlenecks, security concerns with countermeasures
- [ ] **Self-reviewed**: Scenarios verified against the design, including failure paths; gaps patched

### Tasks Checklist

- [ ] **Checkbox format**: Every task and subtask uses `- [ ]` for progress tracking
- [ ] **Task descriptions**: Each task has a clear description of what to do
- [ ] **Requirement traceability**: Each task references which requirement ID(s) it satisfies
- [ ] **Validation criteria**: Each task has both automated and manual verification steps
- [ ] **Numbered phases**: Tasks organized into logical, incrementally-verifiable phases
- [ ] **Checkpoints**: Verification gates after each phase
- [ ] **Definition of Done**: Final section listing completion conditions for the entire spec
- [ ] **Self-reviewed**: Plan walked through to verify it would produce the designed system

### Stop Gates

- After `requirements.md`, stop and wait for the user.
- After `design.md`, stop and wait for the user.
- After `tasks.md`, stop and wait for the user before starting the next spec.
