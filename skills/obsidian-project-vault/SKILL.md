---
name: obsidian-project-vault
description: Create, initialize, audit, and operate an Obsidian vault as a shared human+agent project workspace. Use when Codex needs to set up a reusable project vault structure, process imported docs or raw intake into durable notes, establish coordination and decision records, or continue day-to-day work inside an existing project vault that uses intake, retained sources, project-area hubs, and durable design/reference/requirement/decision notes.
---

# Obsidian Project Vault

## Overview

Use this skill both to create a new project vault and to keep working inside an existing one where humans and agents share durable design knowledge instead of leaving everything in chat logs or raw imported docs.

Prefer one coherent vault model:

- `05 Intake` for active staging
- `65 Sources` for processed raw source material
- `10 Ideas` and `20 Explorations` for thinking
- `30 Designs`, `40 Requirements`, `50 Decisions`, `60 Reference`, and `70 Project Areas` for durable knowledge

Do not mirror source documents file-for-file unless that is clearly the best outcome. Synthesize toward the working knowledge layer.

## Quick Start

### Initialize A New Vault

Run the scaffold script:

```powershell
python scripts/init_project_vault.py <target-path> --project-name "<project name>" --date YYYY-MM-DD
```

Use `--force` only when intentionally overwriting existing starter files.

After initialization:

1. read `00 Start Here/Start Here.md`
2. update `01 Coordination/Current Focus.md`
3. adjust the starter docs if the project needs a different operating model

### Work In An Existing Vault

Use this path for normal work in an already initialized vault, including new design work, future intake processing, refactoring note structure, and coordination updates.

Before substantial work:

1. read `00 Start Here/Start Here.md`
2. read `01 Coordination/Current Focus.md`
3. scan `50 Decisions/Decision Index.md`
4. open the relevant note under `70 Project Areas/` if one exists

During work:

1. put new raw batches into `05 Intake/`
2. promote durable conclusions into the correct note types
3. move processed raw batches to `65 Sources/`
4. leave the coordination notes updated for the next human or agent

## Workflow

### 1. Establish Or Audit The Vault Model

Use [vault-model.md](references/vault-model.md) when setting up a new vault or checking whether an existing one is still coherent.

Verify:

- the top-level folders match the intended model
- `05 Intake` is active staging only
- `65 Sources` holds retained processed raw material
- durable conclusions land in the durable folders, not in coordination or intake

### 2. Process Intake

Use [intake-workflow.md](references/intake-workflow.md) when raw docs, transcripts, specs, or legacy design notes are added.

Default rules:

- treat intake as source material, not truth
- synthesize by concept cluster when that produces better notes
- extract contracts, data shapes, authoring models, state models, and decision logic when those details matter for future design
- move processed raw batches from `05 Intake` to `65 Sources`

### 3. Promote Durable Knowledge

Use [note-rules.md](references/note-rules.md) when deciding what note to create or where knowledge belongs.

Default promotion targets:

- `10 Ideas` for early ideas
- `20 Explorations` for alternatives or competing approaches
- `30 Designs` for structured proposals
- `40 Requirements` for build-facing constraints
- `50 Decisions` for durable decisions and rationale
- `60 Reference` for stable supporting knowledge
- `70 Project Areas` for hubs that connect related work

### 4. Leave The Vault In A Better State

After substantial work:

1. update or create the durable note that holds the result
2. leave a concise handoff in `01 Coordination/Handoff Log.md` if others need the context
3. update `01 Coordination/Current Focus.md` when priorities or blockers changed

## Resources

### `scripts/init_project_vault.py`

Initialize a starter project vault scaffold into a target directory.

### `references/vault-model.md`

Read when creating or auditing the folder and note model.

### `references/intake-workflow.md`

Read when processing imported docs or deciding whether raw material should stay in intake or move to retained sources.

### `references/note-rules.md`

Read when creating note types, frontmatter, area hubs, or decision records.

### `assets/scaffold/`

Starter vault files copied by the init script, including:

- operating docs
- coordination notes
- intake and sources READMEs
- decision index
- project-area README
- note templates
- starter `AGENTS.md`

## Output Standard

Optimize for a vault that is easy for another agent to enter cold:

- clear folder intent
- explicit canonical rules
- durable decisions separated from raw source material
- coordination notes that support handoffs
- project-area notes that connect related work
