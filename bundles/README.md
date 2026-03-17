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
