---
name: kiro-spec-authoring
description: Create or revise Kiro-style feature specs with gated `requirements.md`, `design.md`, and `tasks.md` phases. Use when a target repository already keeps specs in a Kiro-style folder such as `.kiro/specs`, or when the user explicitly wants to establish that workflow, including spec review, battle-testing, and queue maintenance.
---

# Kiro Spec Authoring

Write one Kiro-style spec phase at a time in the target workspace.

## Inputs

- Target workspace path
- Spec root path
- Spec id or folder name
- Requested phase, if the user already chose one

## Resolve The Spec Root
 
1. Use the path the user gives when they give one.
2. Otherwise, check whether `.kiro/specs` already exists in the target workspace:
   - **If `.kiro/specs` exists** → use it as the spec root. Name each spec folder with a flat hyphenated pattern: `{fitting-domain-name}-{fitting-task-spec}` (e.g. `.kiro/specs/auth-session-refresh`).
   - **If `.kiro/specs` does not exist** → use `specs/` as the spec root with a nested two-level structure: `specs/{fitting-domain-name}/{fitting-task-spec}` (e.g. `specs/auth/session-refresh`). Create the directories as needed.
3. In both cases, choose a short, descriptive domain name that groups related features (e.g. `auth`, `billing`, `onboarding`) and a task spec name that captures the specific feature or change.

## Workflow

1. Read the target spec folder if it already exists.
2. Read the implementation queue only when the target workspace has one.
3. Read 1-3 nearby specs when the workspace already has them.
4. Determine the phase to work on:
   - `requirements.md`
   - `design.md`
   - `tasks.md`
5. If the user did not specify a phase, default to `requirements.md`.
6. If the user asks to skip a phase (e.g., "just write the design, I know what I want"), respect that — but note any assumptions you are making that the skipped phase would normally have pinned down. For example, if writing design.md without requirements.md, call out "I'm assuming X, Y, Z — if any of these are wrong, we should write requirements first." This keeps the user informed without blocking them.
7. Create or update only the requested phase.
8. **Self-review before finishing**: After drafting the phase, pressure-test it yourself. Walk through 2-3 concrete scenarios the feature must handle — pick scenarios that exercise boundary conditions, error paths, or interactions between requirements, not just the happy path. For each scenario, trace it through the spec and check whether the spec gives a clear, unambiguous answer for what should happen. If gaps or contradictions appear, patch the spec and note what you changed and why. A self-review that finds zero issues usually means the review was too shallow — look harder at edge cases before declaring it clean.
9. Stop after that phase and wait for the user before writing the next one.
10. Update the queue only when the queue exists and the user asked for queue management or the new spec must be registered.

If the target repo has no strong local examples, fall back to `references/spec-checklist.md` instead of inventing repo lore.

## Phase Rules

### Requirements

The requirements phase produces a document that a product owner, architect, and implementation agent can all use as a shared source of truth. A requirements.md that merely lists features is not sufficient — it needs to be precise enough that two independent teams reading it would build substantially the same thing.

Every requirements.md must include these sections:

#### Summary
A 2-4 sentence overview of what the feature is and why it exists. Someone reading only this paragraph should understand the purpose of the spec.

#### Glossary / Key Terms
Define domain terms that might be ambiguous. Even when terms seem obvious, different readers bring different assumptions. A billing spec should define "subscription", "billing cycle", "proration" etc. A notifications spec should define "event", "channel", "delivery" etc.

#### Requirements List
Each requirement gets:
- A stable ID (e.g., REQ-BILLING-01) for traceability into design and tasks
- A clear description of the capability
- **Acceptance criteria**: concrete, testable conditions that determine whether the requirement is met. Write these as "Given / When / Then" or as a bullet list of verifiable statements. A requirement without acceptance criteria is just a wish.

#### Scope and Deferrals
- What is in scope for this spec
- What is explicitly deferred, with brief rationale for each deferral

#### Boundaries and Clarifications
Call out assumptions, constraints, and edge cases that could trip up implementation. Things like: "Users belong to exactly one organization", "Billing cycle is calendar-month only", "We assume payment processing is handled externally". These prevent the design phase from having to guess.

#### Non-Functional Requirements
Performance, security, auditability, data integrity expectations — anything that shapes how the system is built, not just what it does.

Additional rules:
- Keep the file implementation-agnostic. No tech stack, no database schemas, no code.
- Capture product decisions already made by the user. Do not silently invent missing behavior.
- Create `.config.kiro` only when the target workspace already uses it or the user explicitly asks for it.

### Design

The design phase translates requirements into a concrete technical blueprint. Someone reading the design should be able to plan implementation without guessing about architecture, data models, or integration points.

Every design.md must include these sections:

#### Architecture Overview
High-level description of the system's structure. Include a text-based diagram (ASCII, Mermaid, or similar) showing components and their relationships when the feature involves multiple moving parts. A design that only uses prose to describe flows is harder to review and more likely to contain hidden contradictions.

#### Components and File Paths
List the modules, files, or services that will be created or modified, with their paths relative to the repo root. This makes the design reviewable against the actual codebase.

#### Design Decisions with Rationale
For each significant choice (technology, pattern, library), state:
- What was chosen
- Why it was chosen over alternatives
- Implications and trade-offs

This matters because specs outlive the person who wrote them. Without rationale, future readers cannot tell whether a choice was deliberate or arbitrary.

#### Data Models
Show the data structures, database schemas, or API shapes the feature introduces. Use the notation that matches the target system (SQL for a SQL project, TypeScript interfaces for a TS project, etc.).

#### Integration Points
Show how the new feature connects to existing systems. Reference specific existing files, modules, or APIs by path. A design that treats the feature as isolated will produce integration surprises during implementation.

#### Code References
Point to existing code that the design builds on or modifies. Include file paths and brief descriptions of what each referenced file does.

#### Battle-Test Scenarios
Walk through 2-3 realistic scenarios end-to-end against the design. For each scenario, trace the flow through the components and verify the design handles it. If a scenario reveals a gap, patch the design before finishing.

#### Risks and Mitigations
Identify what could go wrong (failure modes, performance bottlenecks, security concerns) and how the design addresses each risk.

Additional rules:
- Prefer examples shaped like the target repo's actual runtime artifacts.
- Use JSON, YAML, code, or framework-specific examples only when that format matches the target system.
- Show how the feature fits adjacent systems instead of treating it as isolated.

### Tasks

The tasks phase produces an execution plan that an implementation agent can follow mechanically. Every task should be precise enough that the implementor does not need to make architectural decisions — those belong in the design.

Every tasks.md must include these structural elements:

#### Checkbox Structure
Every task and subtask uses checkbox format (`- [ ]`) so the implementation agent can mark items complete as work lands. This is not optional — the implementation skill depends on checkboxes to track progress.

```md
- [ ] 1. Phase name
  - [ ] 1.1 Subtask description
  - [ ] 1.2 Another subtask
```

#### Task Descriptions
Each task includes:
- A clear description of what to do
- **Requirement traceability**: which requirement ID(s) this task satisfies (e.g., "Implements REQ-BILLING-01, REQ-BILLING-02")
- **Validation criteria**: how to verify the task is done correctly. Include both:
  - Automated checks (e.g., "Run `pytest tests/test_ratelimit.py` — all tests pass")
  - Manual/review checks (e.g., "Verify the 429 response body matches the API spec format")

#### Numbered Phases
Organize tasks into logical phases that can be implemented and validated as groups. Each phase should produce a verifiable increment.

#### Checkpoints
After each phase, include a checkpoint that describes what should be true at that point. Checkpoints catch drift early — if a checkpoint fails, the implementor knows to stop and investigate before proceeding.

#### Definition of Done
A final section at the bottom that lists the conditions under which the entire spec is considered complete. This typically includes:
- All requirement IDs are covered by at least one task
- All automated tests pass
- Manual verification checklist items are confirmed
- No regressions in existing functionality

Additional rules:
- Mirror the strongest task structure already present in the target workspace when examples exist.
- Trace task groups back to requirements when the spec uses requirement IDs.
- Make tasks implementation-shaped so another agent can build the designed system from the plan.
- Tighten the plan if review shows the current tasks would not actually produce the requirements or design.

## Do Not

- Do not write `design.md` or `tasks.md` early for convenience.
- Do not create queue files, bootstrap files, or directory conventions unless the target repo already uses them or the user asks for them.
- Do not claim local repo conventions that were not observed.
- Do not start the next spec in a queue without explicit user direction.
- **Do not modify existing spec files that the user did not ask you to touch.** If you are asked to write tasks.md and the existing requirements.md is too sparse to write good tasks from, tell the user what is missing and ask whether they want you to expand it first. Do not silently rewrite it. The same applies to design.md — if you are writing tasks and the design has gaps, flag the gaps instead of patching the design yourself.

## Battle Testing

Every phase gets a self-review pass before it is presented to the user. This is built into the workflow (step 7), not something that only happens on request.

When the user explicitly asks to pressure-test a spec, do a deeper review:

- Read the source material the spec must satisfy.
- Test whether the current phase survives 3-5 concrete examples and edge cases.
- Report the pressure points clearly, with specific references to which parts of the spec are affected.
- Patch the current phase before advancing if the review exposes a real ambiguity or contradiction.
- Show the user what was tested and what was patched — do not silently fix things.

## Reference

Read [references/spec-checklist.md](./references/spec-checklist.md) for the compact review checklist and stop gates.
