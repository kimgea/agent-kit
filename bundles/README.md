# Bundles

Purpose: curated capability sets selected by a human and consumed by an agent.

Bundles are the main composition surface.

Place here:
- capability selections
- policy defaults
- provider-agnostic inclusion rules
- recommended project starting sets such as `godot-core`, `godot-ui`, or `obsidian-core`

Do not place here:
- standalone asset definitions
- duplicated asset content

Real asset path:

```text
bundles/<bundle-id>/
  manifest.yaml
  bundle.yaml
```

Use bundles when a human wants to pick a known working set without naming many individual skills.

Bundle application rule:
- a bundle is not itself a skill
- do not try to install a bundle as if it were a single skill
- read `bundle.yaml`
- resolve the listed included skills
- then load or install those skills individually

Install behavior:
- "install this bundle" means install each included skill
- default Codex behavior installs skills into the Codex skills directory, not into repo-local isolated storage, unless the caller provides a different install convention

GitHub usage:
- when a bundle is referenced by GitHub URL, resolve the bundle file first
- then install the included skills from their `skills/<skill-id>/` paths in the same repo
