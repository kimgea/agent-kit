# Obsidian CLI Reference

Updated against the official Obsidian CLI help page on March 11, 2026, with additional structure adapted from user-provided command notes.
Primary sources:
- https://help.obsidian.md/cli
- https://help.obsidian.md/sync/headless

## Table of Contents

1. Syntax and targeting
2. General and TUI commands
3. Files, folders, and random notes
4. Daily notes
5. Search
6. Properties and aliases
7. Tags
8. Tasks
9. Links
10. Bookmarks
11. Templates
12. Plugins
13. Publish
14. Sync
15. Themes and CSS snippets
16. Commands and hotkeys
17. Bases
18. History and diff
19. Workspace, tabs, and recents
20. Developer commands
21. Vault and utility commands
22. Output formats and piping
23. Platform and install notes
24. Compatibility and troubleshooting

## Syntax and Targeting

Base syntax:

```bash
obsidian <command> [key=value ...] [flags]
```

Rules:

- Parameters use `key=value`.
- Flags are bare switches such as `open`, `overwrite`, `total`, `counts`, or `case`.
- Quote values that contain spaces.
- Use `\n` for newlines and `\t` for tabs in content strings.
- If the current working directory is a vault, that vault is targeted by default. Otherwise the active vault is used.
- Use `vault=<name>` or `vault=<id>` as the first parameter to target a specific vault.
- Use `file=<name>` for wikilink-style note resolution.
- Use `path=<vault-relative-path>` when exact targeting matters.
- If both `file` and `path` are omitted, many commands default to the active file.
- Add `--copy` to copy output to the clipboard.

Examples:

```bash
obsidian read file="Recipe"
obsidian read path="Templates/Recipe.md"
obsidian vault="Work Notes" search query="standup"
```

## General and TUI Commands

Top-level commands:

```bash
obsidian help
obsidian help search
obsidian version
obsidian reload
obsidian restart
```

Running `obsidian` with no subcommand opens the interactive TUI.

Useful TUI behavior from the official docs:

- Autocomplete
- Command history
- Reverse search with `Ctrl+R`
- `vault:open <name-or-id>` to switch vaults inside the TUI

## Files, Folders, and Random Notes

### File inspection and listing

```bash
obsidian file
obsidian file path="Projects/Case Notes.md"
obsidian files
obsidian files ext=md
obsidian files folder="Projects" total
obsidian folder path="Projects" info=files
obsidian folders total
```

### Open, read, create, append, prepend

```bash
obsidian open file="Case Notes"
obsidian open path="Projects/Case Notes.md" newtab
obsidian read file="Case Notes"
obsidian create name="Untitled"
obsidian create path="Projects/New Feature" content="# Title\n\nBody"
obsidian create path="Projects/New Feature" template="project-template" overwrite
obsidian append path="Projects/Case Notes.md" content="New paragraph"
obsidian prepend path="Projects/Case Notes.md" content="## Context"
```

Notes:

- `create path=` should omit `.md`; Obsidian adds the extension.
- `append` and `prepend` support `inline` to avoid adding a newline.
- `prepend` inserts after frontmatter.

### Move, rename, delete, random

```bash
obsidian move path="Projects/Old.md" to="Archive/Old.md"
obsidian rename path="Projects/Case Notes.md" name="Case Notes Revised"
obsidian delete path="Projects/Case Notes.md"
obsidian delete path="Projects/Case Notes.md" permanent
obsidian random
obsidian random newtab
obsidian random:read folder="Projects"
```

Notes:

- `move` can rename and relocate in one command.
- `rename` preserves the extension if it is omitted from `name=`.
- Automatic internal-link updates follow the user's Obsidian setting.

## Daily Notes

Commands:

```bash
obsidian daily
obsidian daily:path
obsidian daily:read
obsidian daily:append content="- [ ] Buy groceries"
obsidian daily:append content="Inline text" inline
obsidian daily:prepend content="## Morning"
```

Notes:

- The Daily Notes core plugin must be configured.
- `daily:path` returns the expected path even if the note does not yet exist.
- If Obsidian can create the daily note, it uses the configured daily-note settings and template.

## Search

### Search by file path result

```bash
obsidian search query="meeting notes"
obsidian search query="todo" path="Projects" limit=10
obsidian search query="release" format=json
obsidian search query="IMPORTANT" case
obsidian search query="meeting" total
```

### Search with context

```bash
obsidian search:context query="meeting notes"
obsidian search:context query="todo" path="Projects" limit=10
obsidian search:context query="IMPORTANT" case
obsidian search:context query="todo" format=json
```

### Open search view

```bash
obsidian search:open query="meeting notes"
```

Notes:

- `search` returns matching file paths.
- `search:context` returns matching lines with context.
- Prefer `format=json` when piping into another tool or agent.

## Properties and Aliases

### Property discovery

```bash
obsidian properties
obsidian properties active
obsidian properties path="Projects/Case Notes.md"
obsidian properties name="status" counts
obsidian properties format=json
```

### Property read, set, remove

```bash
obsidian property:read path="Projects/Case Notes.md" name="status"
obsidian property:set path="Projects/Case Notes.md" name="status" value="active"
obsidian property:set path="Projects/Case Notes.md" name="priority" value="2" type=number
obsidian property:set path="Projects/Case Notes.md" name="done" value="true" type=checkbox
obsidian property:set path="Projects/Case Notes.md" name="tags" value="project,alpha" type=list
obsidian property:remove path="Projects/Case Notes.md" name="draft"
```

### Aliases

```bash
obsidian aliases
obsidian aliases active
obsidian aliases path="Projects/Case Notes.md" verbose
```

Notes:

- Official docs expose `type=text|list|number|checkbox|date|datetime` for `property:set`.
- When list or typed-property behavior matters, verify with `property:read` after writing.

## Tags

Commands:

```bash
obsidian tags
obsidian tags all
obsidian tags counts
obsidian tags counts sort=count format=json
obsidian tags path="Projects/Case Notes.md"
obsidian tag name="project/alpha"
obsidian tag name="project/alpha" verbose total
```

Notes:

- Tags can come from both frontmatter and inline `#tag` syntax.
- Nested tags such as `project/alpha` are supported.

## Tasks

### List tasks

```bash
obsidian tasks
obsidian tasks all
obsidian tasks todo
obsidian tasks done
obsidian tasks daily total
obsidian tasks path="Projects/Case Notes.md"
obsidian tasks status="?"
obsidian tasks verbose format=json
```

### Show or update a task

```bash
obsidian task file="Projects/Case Notes.md" line=12
obsidian task ref="Projects/Case Notes.md:12" toggle
obsidian task daily line=3 done
obsidian task file="Projects/Case Notes.md" line=12 status="-"
```

Notes:

- `tasks verbose` is useful when you need a stable `ref=<path:line>`.
- `todo`, `done`, and `status="<char>"` are mutually useful filters or updates depending on the command.

## Links

Commands:

```bash
obsidian backlinks path="Projects/Case Notes.md"
obsidian backlinks path="Projects/Case Notes.md" counts total format=json
obsidian links path="Projects/Case Notes.md" total
obsidian unresolved
obsidian unresolved verbose counts
obsidian orphans total
obsidian deadends total
```

Notes:

- `backlinks` lists incoming links.
- `links` lists outgoing links.
- `unresolved`, `orphans`, and `deadends` are useful vault hygiene commands.

## Bookmarks

Commands:

```bash
obsidian bookmarks
obsidian bookmarks verbose format=json
obsidian bookmark file="Projects/Case Notes.md"
obsidian bookmark file="Projects/Case Notes.md" subpath="#Open Questions"
obsidian bookmark folder="Projects"
obsidian bookmark search="status:open" title="Open Status"
obsidian bookmark url="https://example.com" title="Reference"
```

## Templates

Commands:

```bash
obsidian templates total
obsidian template:read name="weekly-review"
obsidian template:read name="weekly-review" resolve title="My Note"
obsidian template:insert name="weekly-review"
obsidian create path="Projects/New Feature" template="weekly-review"
```

Notes:

- `template:insert` targets the active editor and does not accept `path=`.
- Use `create ... template=...` to create a new file from a template.

## Plugins

Commands:

```bash
obsidian plugins
obsidian plugins filter=community versions format=json
obsidian plugins:enabled filter=community
obsidian plugins:restrict
obsidian plugins:restrict on
obsidian plugin id="dataview"
obsidian plugin:enable id="calendar" filter=community
obsidian plugin:disable id="calendar" filter=community
obsidian plugin:install id="dataview" enable
obsidian plugin:uninstall id="dataview"
obsidian plugin:reload id="my-plugin"
```

Notes:

- `plugins versions` behavior from older examples now maps to `plugins versions` or `plugins filter=community versions`, per current docs.
- Core and community plugins can be filtered with `filter=core|community` where supported.

## Publish

Commands:

```bash
obsidian publish:site
obsidian publish:list total
obsidian publish:status
obsidian publish:status new
obsidian publish:status changed
obsidian publish:status deleted
obsidian publish:add file="Projects/Case Notes.md"
obsidian publish:add changed
obsidian publish:remove path="Projects/Case Notes.md"
obsidian publish:open file="Case Notes"
```

Notes:

- `publish:add changed` publishes all currently changed files.
- `publish:open` opens the published page for the active or targeted file.

## Sync

Commands:

```bash
obsidian sync
obsidian sync on
obsidian sync off
obsidian sync:status
obsidian sync:history path="Projects/Case Notes.md" total
obsidian sync:read path="Projects/Case Notes.md" version=3
obsidian sync:restore path="Projects/Case Notes.md" version=3
obsidian sync:open path="Projects/Case Notes.md"
obsidian sync:deleted total
```

Notes:

- These commands control Sync within the desktop app.
- For syncing without the desktop app, use Obsidian Headless: https://help.obsidian.md/sync/headless

## Themes and CSS Snippets

Commands:

```bash
obsidian themes
obsidian themes versions
obsidian theme
obsidian theme name="Minimal"
obsidian theme:set name="Minimal"
obsidian theme:set name=""
obsidian theme:install name="Minimal" enable
obsidian theme:uninstall name="Minimal"
obsidian snippets
obsidian snippets:enabled
obsidian snippet:enable name="custom-theme"
obsidian snippet:disable name="custom-theme"
```

## Commands and Hotkeys

Commands:

```bash
obsidian commands
obsidian commands filter="app:"
obsidian command id="app:open-settings"
obsidian hotkeys
obsidian hotkeys verbose format=json
obsidian hotkey id="app:open-settings" verbose
```

Typical workflow:

```bash
obsidian commands filter="canvas:"
obsidian command id="canvas:new-file"
```

## Bases

Commands:

```bash
obsidian bases
obsidian base:views file="tasks"
obsidian base:create file="tasks" name="buy-milk" content="Buy milk" open
obsidian base:query file="tasks"
obsidian base:query file="tasks" view="Kanban" format=json
obsidian base:query path="Planning/Roadmap.base" format=csv
```

Supported `base:query` formats in the current docs: `json`, `csv`, `tsv`, `md`, `paths`.

## History and Diff

Commands:

```bash
obsidian diff
obsidian diff file="Case Notes" from=1 to=2
obsidian diff path="Projects/Case Notes.md" filter=sync
obsidian history:list
obsidian history path="Projects/Case Notes.md"
obsidian history:read path="Projects/Case Notes.md"
obsidian history:read path="Projects/Case Notes.md" version=3
obsidian history:restore path="Projects/Case Notes.md" version=3
obsidian history:open path="Projects/Case Notes.md"
```

Notes:

- `diff` compares current, local history, and sync history versions.
- `history:*` uses File Recovery snapshots, not Sync history.

## Workspace, Tabs, and Recents

Commands:

```bash
obsidian workspace
obsidian workspace ids
obsidian workspaces total
obsidian workspace:save name="Review Layout"
obsidian workspace:load name="Review Layout"
obsidian workspace:delete name="Review Layout"
obsidian tabs ids
obsidian tab:open file="Projects/Case Notes.md"
obsidian tab:open view="graph"
obsidian recents total
```

## Developer Commands

Commands:

```bash
obsidian devtools
obsidian dev:debug on
obsidian dev:debug off
obsidian dev:errors
obsidian dev:errors clear
obsidian dev:console limit=20 level=error
obsidian dev:console clear
obsidian dev:screenshot path="debug/plugin.png"
obsidian dev:dom selector=".workspace-leaf"
obsidian dev:dom selector=".workspace-leaf" text
obsidian dev:dom selector=".workspace-leaf" total
obsidian dev:dom selector=".workspace-leaf" attr=class
obsidian dev:dom selector=".workspace-leaf" css=color
obsidian dev:css selector=".workspace-leaf"
obsidian dev:css selector=".workspace-leaf" prop=color
obsidian dev:cdp method="Runtime.evaluate" params='{"expression":"1+1"}'
obsidian dev:mobile on
obsidian dev:mobile off
obsidian eval code="app.vault.getFiles().length"
```

Notes:

- `dev:console` is only useful once logging is being captured; if output is empty, run `dev:debug on` first.
- Keep `eval` snippets short and single-line when possible.
- Use `dev:dom`, `dev:css`, and screenshots together when debugging layout issues.

## Vault and Utility Commands

Commands:

```bash
obsidian vault
obsidian vault info=path
obsidian vaults verbose
obsidian outline path="Projects/Case Notes.md" format=tree
obsidian wordcount path="Projects/Case Notes.md"
obsidian wordcount path="Projects/Case Notes.md" words
obsidian unique name="Daily Scratch" content="Hello" open
obsidian web url="https://example.com" newtab
```

## Output Formats and Piping

Common formats seen in current docs:

- `text`
- `json`
- `csv`
- `tsv`
- `yaml`
- `md`
- `paths`
- `tree`

Not every command supports every format. Default to `text` or `json` when uncertain.

Examples:

```bash
obsidian search query="meeting" format=json
obsidian tags counts sort=count format=json
obsidian tasks todo format=json
obsidian base:query file="tasks" format=csv
obsidian hotkeys verbose format=json
```

## Platform and Install Notes

Current official guidance on March 11, 2026:

- Obsidian CLI requires the Obsidian 1.12 installer line.
- The help page still describes the feature as part of the 1.12 early-access track.
- The CLI registration step updates PATH or symlinks differently by platform.

### Windows

- Current docs call out the 1.12.4+ installer for Windows troubleshooting.
- Windows uses an `Obsidian.com` terminal redirector next to `Obsidian.exe` so stdin and stdout work correctly.
- If `obsidian` resolves but commands do not behave correctly, reinstall or re-register the CLI and restart the terminal.

### macOS

- CLI registration adds `/Applications/Obsidian.app/Contents/MacOS` to `~/.zprofile`.
- If you use Bash or Fish, add that directory to the shell-specific PATH config manually.

### Linux

- CLI registration typically creates `/usr/local/bin/obsidian`.
- If sudo is unavailable, the fallback may be `~/.local/bin/obsidian`.
- AppImage, Snap, and Flatpak installs may need additional PATH or config fixes. Re-check the official troubleshooting section if the binary resolves incorrectly.

## Compatibility and Troubleshooting

Checklist:

- Confirm the CLI is enabled in **Settings -> General -> Command line interface**.
- Restart the terminal after registering the CLI so PATH changes take effect.
- If Obsidian is closed, try a simple command like `obsidian help` and allow it to launch the app.
- Use `obsidian help <command>` when a flag seems unsupported or examples disagree.
- Switch from `file=` to `path=` if name resolution is ambiguous.
- Prefer current official `vault=<name>` or `vault=<id>` syntax instead of older bare-vault examples.
- On Windows, verify the registered CLI launcher works correctly if `obsidian` resolves but commands fail.
- If you need sync without the desktop app, use Headless Sync rather than forcing the desktop CLI into a server workflow.