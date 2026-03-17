# agent-kit

Agent-first repository for reusable agent assets.

Primary use:
- software development agents
- reusable skills, prompts, workflows, and provider packaging
 - reusable skills, prompts, workflows, bundles, and agents

Secondary use:
- personal or non-coding agents when they fit the same asset model

Classification rule:
- organize by asset type, not by domain
- distinguish software, personal, and other usage through tags, manifests, and bundles

Read this order:
1. `AGENTKIT_SPEC.md`
2. `CATALOG.yaml`
3. directory `README.md` files for the area being changed

Repository rules:
- add real assets only
- do not add examples as placeholders
- keep prose short and operational
- prefer machine-readable metadata over narrative documentation
- update `CATALOG.yaml` whenever adding, removing, or renaming an asset

Top-level asset directories:
- `agents/`
- `skills/`
- `prompts/`
- `tools/`
- `workflows/`
- `bundles/`


Some skill sources copied or heavely used as inspiration
- https://github.com/htdt/godogen
- https://github.com/kepano/obsidian-skills
- https://github.com/thedivergentai/gd-agentic-skills