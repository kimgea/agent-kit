# Global agent safety fragment

Copy or adapt this fragment into the user-wide instruction file for the active
harness. Review local tool paths before installation.

```markdown
Start with read-only inspection and keep mutations inside the user-requested
scope. Do not change global configuration, permissions, installed resources, or
remote services unless the user requested that mutation.

Use `rg` or `rg --files` for search. Preserve unrelated worktree changes and use
patch-based edits. Never use destructive Git recovery or force pushes without an
explicit, target-specific request.

For read-only GitHub REST requests use the reviewed `gh-api-get` wrapper. Direct
`gh api` is forbidden because method and body flags can make it mutating. Use
purpose-specific `gh` read commands where available.

Automatic permissions must target a fixed executable or script plus an
enumerated, argument-free profile. Keep arbitrary interpreters, custom paths,
command passthrough, setup programs, installers, and executable discovery
approval-gated.

When unrelated actionable work is consciously deferred, use the installed
`todo-capture` skill to preserve a pickup pointer instead of leaving a vague note.
```

Do not install this fragment silently. Global instructions influence every agent
session and require human review.
