# Releasing

## Prepare

1. Work from a non-default branch and ensure `main` is current.
2. Update `toolkit_version` and every changed resource version in `toolkit.toml`.
3. Update `CHANGELOG.md`, compatibility claims, and third-party notices.
4. Run `python scripts/agent_kit.py check`.
5. Optionally inspect local deterministic artifacts with
   `python scripts/agent_kit.py package --format all` and remove `dist/` afterward.
6. Merge through a pull request after required CI and an explicit owner merge
   decision.

## Publish

Create an annotated tag matching the catalog version, such as `v1.0.0`, on the
merged `main` commit and push the tag. Do not move or recreate a published tag.

The release workflow:

- checks out the exact tag with immutable pinned Actions;
- verifies `v<toolkit_version>` equals the tag;
- runs the canonical repository gate;
- packages every installable skill and plugin plus the marketplace
  deterministically;
- creates the GitHub release and uploads each archive plus `SHA256SUMS`.

Verify the release checksums and inspect archive contents before recommending the
release for installation.
Extract the marketplace archive and run the plugin validator against each
contained plugin. A human should also smoke-test adding the extracted local
marketplace to a compatible Codex installation before announcing plugin
availability.

## Repository settings

The repository's reviewed GitHub configuration is encoded in
`scripts/configure_github.py`. It is fixed to `kimgea/agent-kit`, discovers the
named ruleset through `gh-api-get`, and exposes no arbitrary method, endpoint,
repository, or payload. Preview it after CI has run at least once:

```bash
python scripts/configure_github.py
```

After reviewing the source and preview, an authenticated administrator may apply
the exact settings with `--apply --yes`. The script is idempotent, but GitHub
settings are not transactional; if a request fails, inspect the reported step and
rerun after correcting it. It enables two separately layered default-branch
rulesets: a no-bypass pull-request and CI protection ruleset, plus an exact-user
update restriction. It also configures four required Linux/Windows checks,
linear squash history, force-push and deletion protection, SHA-pinned
GitHub-owned Actions only, a read-only workflow token, Dependabot vulnerability
alerts and security updates, private vulnerability reporting, and immutable
releases.

GitHub does not allow a pull-request author to approve their own pull request.
The repository currently has one human owner identity, so the protection ruleset
requires the PR and CI path but sets the approving-review count to zero.
`CODEOWNERS` remains an explicit ownership and review-routing record. Increase
the review count only after a distinct trusted reviewer is available.

The second ruleset restricts updates to `main` and grants a pull-request-only
bypass to the exact `kimgea` GitHub user ID. It deliberately contains no CI or
pull-request requirements: those remain in the first ruleset with no bypass
actors, so the owner exception cannot skip checks and cannot authorize a direct
push. External contributors may open pull requests, but only `kimgea` can merge
them. Agents authenticated as `kimgea` may perform that merge only when the user
has requested delivery into `main`.

This boundary assumes no other person or app is granted repository
administration or the ability to edit rulesets. An administrator can change the
repository's rules, so granting that permission is equivalent to granting
control over this boundary.

## Upgrade and rollback

Users should check out or download the desired immutable version, then run the
normal dry-run `install` command. Agent-kit updates only an owned, unchanged
deployment and retains the replaced version in private trash.

Use `rollback` to preview and restore the newest owned deployment. For a release
older than the newest retained deployment, check out that tag and run `install`.
Skill permissions are versioned separately by each setup script and must be
previewed again after a relocation or permission-interface change.
