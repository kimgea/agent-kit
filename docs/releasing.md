# Releasing

## Prepare

1. Work from a non-default branch and ensure `main` is current.
2. Update `toolkit_version` and every changed resource version in `toolkit.toml`.
3. Update `CHANGELOG.md`, compatibility claims, and third-party notices.
4. Run `python scripts/agent_kit.py check`.
5. Optionally inspect local deterministic artifacts with
   `python scripts/agent_kit.py package --format all` and remove `dist/` afterward.
6. Merge through a pull request after required CI and independent exact-head
   review when the user requested implementation or delivery.

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
rerun after correcting it. It enables one no-bypass default-branch protection
ruleset and retires the obsolete owner-only update restriction when present. It
also configures four required Linux/Windows checks, linear squash history,
force-push and deletion protection, SHA-pinned GitHub-owned Actions only, a
read-only workflow token, Dependabot vulnerability alerts and security updates,
private vulnerability reporting, and immutable releases.

GitHub does not allow a pull-request author to approve their own pull request.
The repository currently has one human owner identity, so the protection ruleset
requires the PR and CI path but sets the approving-review count to zero.
`CODEOWNERS` remains an explicit ownership and review-routing record. Increase
the review count only after a distinct trusted reviewer is available.

GitHub requires repository write permission to merge a pull request. Keep write,
maintain, and admin access limited to `kimgea` and identities deliberately
controlled by the owner. External contributors retain normal public read, fork,
and pull-request access but cannot merge. Owner-controlled agents may merge only
after the user requested implementation or delivery, required checks passed, and
the independent exact-head review is clean.

This boundary assumes no other person or app is granted repository write access,
administration, or the ability to edit rulesets. Granting write access grants
merge authority after protected-branch requirements pass; granting administration
also grants control over those requirements.

## Upgrade and rollback

Users should check out or download the desired immutable version, then run the
normal dry-run `install` command. Agent-kit updates only an owned, unchanged
deployment and retains the replaced version in private trash.

Use `rollback` to preview and restore the newest owned deployment. For a release
older than the newest retained deployment, check out that tag and run `install`.
Skill permissions are versioned separately by each setup script and must be
previewed again after a relocation or permission-interface change.
