---
name: build-interactive-diagram
description: Create polished, self-contained HTML diagrams for architecture, workflows, state transitions, comparisons, timelines, and other explanations that materially benefit from interaction. Use when a browser visual would communicate relationships better than terminal prose, especially in remote Codex or Claude conversations; optionally publish the result through the serve-artifacts skill.
---

# Build Interactive Diagram

Create a temporary browser artifact when interaction materially improves the
explanation. Use prose or a small Markdown table for simple facts and one-step
flows. Keep long-term product documentation in its owning repository.

## Build the visual

1. Choose the smallest useful form: flow for sequence, graph for dependencies,
   timeline for change, or grouped cards for comparison and ownership.
2. Create a new bounded output directory outside the installed skill. Copy
   `assets/starter/` into it when the starter matches; never edit the installed copy.
3. Replace the sample model and labels with the user's actual content. Remove
   controls that do not help the explanation.
4. Keep everything local: HTML, CSS, JavaScript, SVG, and data files. Do not add a
   CDN, analytics, external fonts, or a framework merely for presentation.
5. Make the first viewport understandable without interaction, then use selection,
   filtering, focus, or progressive detail to reveal more.

Read [diagram-quality.md](references/diagram-quality.md) while building or reviewing
the visual. It contains the layout, interaction, accessibility, and QA contract.

## Validate and deliver

- Open or request the entry page through a local HTTP server; do not claim visual
  quality from source inspection alone.
- Exercise every control, keyboard focus, narrow layout, empty state, and long label.
- Check the browser console and ensure all assets resolve without network access.
- If `serve-artifacts` is available, publish the directory with a short relevant
  TTL and return its browser URL. Follow that skill for remote/Tailscale setup.
- If the host is unavailable, return the absolute entry-file path and concise local
  serving instructions. The diagram skill must remain useful on its own.
- Summarize what the visual shows in the conversation so the result is still useful
  to someone who cannot open it.

Do not embed private context, credentials, raw transcripts, or unrelated repository
files. When revising an existing artifact, create a new published copy and revoke
the old one after the user confirms it is no longer needed.
