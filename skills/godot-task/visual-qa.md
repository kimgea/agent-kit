# Visual Quality Assurance

Analyze game screenshots against the visual reference. Use one of two modes based on scene type.

## Static Mode

For scenes without meaningful motion such as decoration, terrain, or UI. Use two images: the reference and one representative screenshot.

```bash
mkdir -p visual-qa
N=$(ls visual-qa/*.md 2>/dev/null | wc -l); N=$((N + 1))
python3 skills/godot-task/scripts/visual_qa.py \
  --context "Goal: ...\nRequirements: ...\nVerify: ..." \
  reference.png screenshots/{task}/frame0003.png > visual-qa/${N}.md
```

Pick a representative frame, not the first frame, because initialization artifacts often show up there.

## Dynamic Mode

For scenes with motion, animation, or physics. Use the reference plus frames sampled at 2 FPS cadence, meaning every `capture_fps / 2` frame.

```bash
# Example: captured at --fixed-fps 10 -> step=5, select every 5th frame
# 30s at 10fps = 300 frames -> 60 selected frames + 1 reference = 61 images
mkdir -p visual-qa
N=$(ls visual-qa/*.md 2>/dev/null | wc -l); N=$((N + 1))
STEP=5  # capture_fps / 2
FRAMES=$(ls screenshots/{task}/frame*.png | awk "NR % $STEP == 0")
python3 skills/godot-task/scripts/visual_qa.py \
  --context "Goal: ...\nRequirements: ...\nVerify: ..." \
  reference.png $FRAMES > visual-qa/${N}.md
```

Gemini handles large image batches well for this workflow.

## --context

Pass the task's goal, requirements, and verify text from `PLAN.md` or the active task specification.

The QA has two objectives:

1. Quality verification first: visual defects, bugs, implementation shortcuts, and logic problems.
2. Goal verification second: whether the result matches what the task asked for.

## Common

- Output: markdown report with verdict (`pass`, `fail`, or `warning`), reference match, goal assessment, and per-issue details
- Severity: `major` and `minor` must be fixed; `note` is cosmetic
- Save stdout to `visual-qa/{N}.md` as test evidence
- Requires `GEMINI_API_KEY` or `GOOGLE_API_KEY`
- Depends on the `google-genai` Python package

## Handling Failures

When verdict is `fail`, treat the issues as high-signal feedback.

- Fixable issues such as placement, scale, materials, clipping, z-fighting, or animation logic should be fixed, then re-captured and re-checked.
- If the issue is upstream, such as wrong assets, a wrong approach, or an architectural mismatch, stop and report it clearly to the caller.

Use at most three fix-and-rerun cycles. If the result is still failing after that, report the remaining issues and stop.
