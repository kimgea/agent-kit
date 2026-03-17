---
name: obsidian-cli
description: Operate a user's Obsidian vault through the `obsidian` CLI for note CRUD, daily notes, search, tasks, properties, tags, links, bookmarks, templates, bases, history, sync, workspace commands, and plugin or theme development. Use when Codex needs to act inside a running Obsidian app or automate vault operations from the terminal, including reading or updating notes, querying vault state, or debugging plugins and themes with developer commands. Skip for purely conceptual questions about the Obsidian UI, settings navigation, plugin or theme recommendations, or syntax explanations that do not require executing CLI commands.
---

# Obsidian CLI

## Overview

Use the `obsidian` CLI to control a running Obsidian desktop app for scripting, automation, vault management, and plugin or theme development.

Read `references/command-reference.md` when you need specific command groups, parameters, formats, compatibility notes, or troubleshooting steps. Run `obsidian help` or `obsidian help <command>` before guessing about flags or newly added behavior, and use the official help page as fallback: https://help.obsidian.md/cli

## Prerequisites

| Requirement | Notes |
| --- | --- |
| Obsidian Desktop | Use the 1.12 installer series. The official help page on March 11, 2026 still describes the CLI as part of the 1.12 line. |
| CLI enabled | Enable **Settings -> General -> Command line interface** and follow the registration prompt. |
| App availability | The CLI targets the desktop app. If Obsidian is not already open, the first command may launch it. |

## Operating Rules

- Use `key=value` parameters and bare flags. Quote values with spaces.
- If the current working directory is a vault, that vault is used by default. Otherwise the active vault is used.
- Use `vault=<name>` or `vault=<id>` as the first parameter to target a specific vault.
- Use `file=<name>` for wikilink-style name resolution. Use `path=<vault-relative-path>` when exact targeting matters.
- Treat `path=` values as vault-relative, not filesystem-absolute.
- Prefer read commands before write commands when the request could alter existing content.
- Prefer `format=json`, `format=csv`, or `format=tsv` when the output will be parsed.
- Use `--copy` only when the user explicitly wants clipboard behavior.

## Core Workflows

### Read, create, search, and update notes

```bash
obsidian read path="Projects/Case Notes.md"
obsidian create name="New Note" content="# Title\n\nBody text"
obsidian append file="Case Notes" content="- [ ] Follow up"
obsidian prepend path="Projects/Case Notes.md" content="## Context"
obsidian search query="hikikomori" limit=20
obsidian search:context query="todo" path="Projects"
```

### Daily notes, metadata, tasks, and links

```bash
obsidian daily
obsidian daily:read
obsidian daily:append content="- [ ] Review leads"
obsidian property:set path="Projects/Case Notes.md" name="status" value="active"
obsidian tags counts sort=count
obsidian tasks todo
obsidian task ref="Daily/2026-03-11.md:12" toggle
obsidian backlinks file="Case Notes" counts
obsidian orphans total
```

### Templates, bases, sync, history, and wider vault operations

```bash
obsidian create path="Projects/New Feature" template="project-template"
obsidian base:query path="Planning/Roadmap.base" format=json
obsidian sync:status
obsidian history path="Projects/Case Notes.md"
obsidian diff file="Case Notes" from=1 to=2
obsidian bookmarks verbose
```

### Plugin and theme development loop

1. Reload the plugin, snippet, or theme you are testing.
2. Check JavaScript errors and console output.
3. Inspect the UI with screenshot, DOM, or CSS commands.
4. Use `eval` for small API probes.

```bash
obsidian plugin:reload id=my-plugin
obsidian dev:errors
obsidian dev:debug on
obsidian dev:console level=error limit=20
obsidian dev:screenshot path="debug/plugin.png"
obsidian dev:dom selector=".workspace-leaf" text
obsidian dev:css selector=".workspace-leaf" prop=background-color
obsidian eval code="app.vault.getFiles().length"
```

## Guardrails

- Prefer `path=` over `file=` whenever duplicate note names are possible.
- `create path=` should omit the `.md` extension.
- `move to=` should include the full destination path.
- `prepend` inserts after frontmatter, not at byte zero.
- `template:insert` targets the active editor only. Use `create ... template=...` to make a new file from a template.
- `sync:*` commands control Sync inside the desktop app. For sync without the desktop app, see Headless Sync: https://help.obsidian.md/sync/headless
- Older examples may show a bare vault name before the command. Current official docs use `vault=<name>` or `vault=<id>` as the first parameter.

## Stop and Report

Stop and surface the issue when any of the following happens:

- The CLI is missing from `PATH` or the registration step failed.
- Obsidian does not launch or the CLI cannot connect to the running app.
- A `file=` lookup is ambiguous and the exact note is unclear.
- The requested operation is destructive and the target path is still uncertain.
- Platform-specific PATH or registration problems persist after basic troubleshooting.