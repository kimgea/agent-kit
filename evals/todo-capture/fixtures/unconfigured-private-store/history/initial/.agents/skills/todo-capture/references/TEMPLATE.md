---
repo: <folder name, e.g. test; _general for cross-repo/machine-level>
domain: <must match the filename prefix and a row in domains.tsv>
status: todo
created: <YYYY-MM-DD>
source: <optional — PR #, ticket, or "conversation YYYY-MM-DD">
priority: <optional — high | normal | low>
hook: <optional — INDEX one-liner; defaults to title>
---

# <One line: the change, stated as an outcome>

## Why

What's wrong or missing today, in two or three sentences. Concrete symptom, not a principle. If a decision deferred this deliberately, say who decided and when.

## Where

The code involved, with symbol names as well as line numbers (lines drift):

- `Path/To/File.cs` — `SymbolName` (`:123`) — what it does that matters here
- `Other/File.cs` — the other end of the problem

## What to do

Enough for a fresh agent to start without re-deriving the analysis. The shape of the change, not a full design. If it genuinely needs a design first, say that and say where the design should live (`specs/<area>/`).

## Constraints

The things that will bite. Each one a fact, not a worry:

- Load-bearing callers that depend on current behaviour
- Contract / public-surface changes and who they ripple into
- What looks like a bug here but is intentional
- Sequencing: what has to land first

## Out of scope

What was deliberately excluded, so nobody re-expands it silently.

## Links

Related entries as `[[other-entry-id]]`. Repo docs, ADRs, PRs by number.
