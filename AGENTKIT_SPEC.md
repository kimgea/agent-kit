# Agent Kit Spec

Purpose: define the repository contract for agents that read from or write to this repo.

## Model

This repository stores reusable agent assets.

An asset is one of:
- agent
- skill
- prompt
- tool
- workflow
- bundle

Domain handling:
- do not create separate top-level trees for software versus personal use
- classify by asset type first
- express domain through tags, manifest metadata, and bundle composition

Source of truth:
- files under the top-level asset directories
- registry state in `CATALOG.yaml`

## General Rules

- Prefer small files with explicit purpose.
- Prefer stable filenames and lowercase hyphenated directory names.
- Do not add illustrative or dummy assets.
- Do not duplicate instructions across assets unless provider differences require it.
- Keep guidance operational. Avoid motivational or marketing language.
- When adding a real asset, include only files that materially support that asset.
- Every real asset must have `manifest.yaml`.
- Every real asset should keep free-form prose short and structured.

## Required Update Behavior

When adding a real asset:
1. create a new directory under the correct top-level asset path
2. add `manifest.yaml`
3. add the asset content files referenced by the manifest
4. register the asset in `CATALOG.yaml`

When removing or renaming a real asset:
1. update `CATALOG.yaml`
2. update any bundle or workflow that references it

## Asset Layout

Canonical real asset path:

```text
<type>/<asset-id>/
  manifest.yaml
  ...
```

Allowed `<type>` values:
- `agents`
- `skills`
- `prompts`
- `tools`
- `workflows`
- `bundles`

Asset directory names must match the asset id unless there is a documented reason not to.

## Manifest Contract

Each real asset must have a `manifest.yaml` with, at minimum:

```yaml
id: <asset-id>
type: <agent|skill|prompt|tool|workflow|bundle>
name: <short stable display name>
version: <semver>
purpose: <one sentence>
```

Recommended fields:

```yaml
tags: []
inputs: []
outputs: []
dependencies: {}
entrypoints: {}
compatibility: {}
constraints: {}
```

Only add fields that are actually used.

## Writing Style

Use this style for agent-facing text:
- short sentences
- declarative instructions
- explicit inputs, outputs, and constraints
- facts separated from inference
- no filler

Preferred structure for operational markdown:

```text
Purpose
Inputs
Outputs
Do
Do Not
Failure Modes
```

Use only the sections that materially help.

## Directory Intent

- top-level asset directories: source assets
- `CATALOG.yaml`: fast discovery index
- top-level and directory `README.md` files: concise operational guidance

## Catalog Contract

`CATALOG.yaml` is the fast discovery index.

It must:
- list all real assets
- remain concise

It must not:
- describe placeholder directories as real assets
- drift from the filesystem state
