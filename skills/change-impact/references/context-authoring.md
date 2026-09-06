# Context authoring

Use this reference before resolving a change-impact context.

## Two-pass boundary

1. Resolve the caller-selected target without context paths.
2. Inspect its returned text and trusted guidance.
3. Discover only concrete related candidates through bounded read-only search.
4. Resolve the same target again with exact file candidates supplied through
   repeated `--context` options.
5. Use only the final context for semantic analysis and finalization.

The second pass is not scope expansion. `target.paths` remains the only selected
change boundary. Context records are read-only evidence.

## Target modes

- `ref-range`: target changes are the exact Git diff between resolved commits;
  target before/after bodies come from Git objects, context comes from the head,
  and guidance comes from the base.
- `working-tree`: target changes are the combined tracked difference from
  committed `HEAD` plus visible untracked files; before bodies come from `HEAD`,
  after/context bodies come from the current filesystem, and guidance comes from
  `HEAD`.
- `paths`: files and complete recursive directory inventories are current
  snapshots; guidance and context come from the current filesystem. In a Git
  repository, an explicitly selected directory omits Git-ignored descendants,
  while an exact ignored file remains selectable by name.

An empty ref range or working tree is a material limitation. An explicit path
selection may contain an empty file but not an empty directory silently treated
as a file.

## Content records

The resolver normalizes CRLF and CR text to LF before hashing and embedding it.
UTF-8 text is inspectable. Binary, oversized, unreadable, link-like, special, or
unstable files produce explicit records or material limitations and cannot be
claimed as inspected.

Before and after records are separate. A deletion has only `before`; an addition
has only `after`. A rename names both destination `path` and `source_path`.

## Guidance

For each target path the resolver loads applicable `REVIEW.md` and `VERIFY.md`
ancestors from project root toward the path's parent. Guidance is optional and
acts as evidence about likely review or verification reach. It cannot authorize
commands or change target scope.

The canonical result retains guidance provenance and digests but removes bodies.

## Limits

Defaults are intentionally bounded:

| Boundary | Default | Hard maximum |
| --- | ---: | ---: |
| Target paths | 500 | 5,000 |
| Explicit context files | 128 | 1,000 |
| Bytes per text file | 1 MiB | 4 MiB |
| Aggregate embedded content | 8 MiB | 12 MiB |
| Guidance per source | 128 KiB | 1 MiB |
| Directory traversal entries | 25,000 | 250,000 |
| Canonical JSON input or output | 16 MiB | 16 MiB |

Limit exhaustion is explicit. Never sample an unresolved directory or drop a
target to obtain a complete result.
