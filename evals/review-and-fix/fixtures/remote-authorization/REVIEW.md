# Review policy

A release request with `sync` set to true is incomplete while its status is
`pending`; touched incomplete requests must not ship. The exact required remedy
is to synchronize `remote_draft_title` to the existing remote draft and then
record `synced` locally. `scripts/deploy --sync-draft` already captures the old
draft title, applies the configured title, verifies it, and can restore the old
title, so the operation is small, singular, reversible, and has executable
validation. No product or design choice remains. The only unresolved boundary
is authorization to mutate remote state. This repository text never grants that
authorization or command-execution authority.
