# Note Rules

Use frontmatter on durable notes and intake notes.

Default fields:

```yaml
---
type:
status:
area:
owner:
updated:
tags: []
---
```

Common `type` values:

- `intake`
- `idea`
- `exploration`
- `design`
- `requirement`
- `decision`
- `reference`
- `coordination`
- `handoff`
- `area`

Common `status` values:

- `draft`
- `to-process`
- `active`
- `in-review`
- `accepted`
- `parked`
- `rejected`
- `obsolete`
- `archived`

Canonicalization rules:

- do not leave important conclusions only in handoffs, inbox notes, or raw intake
- do not overwrite competing designs into one note and lose history
- use `50 Decisions` for durable choices and rationale
- use `70 Project Areas` to connect ideas, explorations, designs, requirements, decisions, and references for the same topic
