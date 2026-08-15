# Interactive diagram quality contract

Use this checklist while creating or reviewing a browser diagram.

## Information design

- Give the page a one-sentence takeaway, not a generic "diagram" title.
- Encode one primary relationship. Use color, position, and line style consistently.
- Put essential labels on the canvas; keep longer explanations in a detail panel.
- Show direction on connections and provide a text summary of the selected item.
- Prefer two to seven visible groups. Collapse or filter larger models.
- Use domain terms from the conversation and avoid unexplained abbreviations.

## Interaction

- Make nodes real buttons or links with visible hover, focus, and selected states.
- Selection should update an adjacent detail panel without losing spatial context.
- Filters must state what they hide, expose an "all" state, and never leave the
  user with a mysteriously blank canvas.
- Recompute connectors after resize and content changes.
- Keep navigation within the artifact and do not require network requests.

## Visual system

- Use a restrained palette with sufficient contrast and a neutral canvas.
- Establish hierarchy through type size, weight, spacing, and grouping before color.
- Use subtle depth and motion; honor `prefers-reduced-motion`.
- Keep labels readable at 320 CSS pixels and avoid horizontal page scrolling.
- Make the artifact feel intentional, but do not decorate beyond the explanation.

## Accessibility and QA

- Use semantic headings, landmarks, buttons, lists, and an informative document title.
- Maintain logical keyboard order and a visible focus ring.
- Never rely on color alone; pair it with labels, shape, or line style.
- Include an `aria-live` region only when selection changes information elsewhere.
- Test every interactive state, missing/long data, resize behavior, and zero network.
- Verify the final served URL, not only the source directory.
