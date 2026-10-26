---
name: lecture-slides
description: "Build an editable teaching deck (.pptx) in the lab's lecture style: question titles, one running concrete example, tinted cards and native shapes, section chips, footnoted sources, n / N page numbers, and full speaker notes. Use for course lectures, tutorials, lab onboarding talks, or any explainer deck that teaches a method step by step. Triggers: 上課簡報, 教學投影片, 講義簡報, 做一份課程簡報, 第 N 週的投影片, lecture slides, teaching deck, course slides, make slides like the examples."
metadata:
  version: "1.0.0"
  last_updated: "2026-10-26"
  status: active
  data_access_level: raw
  task_type: open-ended
  related_skills:
    - report-slides
    - deep-research
---

# Lecture Slides

Makes a teaching deck that looks and reads like the lab's own lecture decks:
a cream or white page, Times New Roman with 標楷體, one concrete example
carried from the first slide to the last, and every element a native
PowerPoint shape the teacher can edit.

Read `references/style-guide.md` before planning. It holds the teaching and
visual rules, each traced to a slide in the reference decks.

**This skill vs `report-slides`:** `report-slides` turns research-log entries
into a progress report through an approval-gated pipeline. This skill teaches
a topic to an audience. If the source is the user's own experiment logs and
the audience is an advisor or lab meeting, use `report-slides`.

## Requirements

- Python 3.10+ with `python-pptx` and `PyYAML`
- For previews: LibreOffice (`soffice`), Poppler (`pdftoppm`), and Pillow

```bash
SKILL="$(dirname "$(find ~/.claude -path '*/lecture-slides/SKILL.md' | head -1)")"
```

## Workflow

### 1. Ask (one message)

Ask only what you cannot infer:

1. Topic, course name, and week number
2. Audience level (first-year undergraduates / graduate / lab members)
3. Length (default: 20–30 slides for a 2-hour class)
4. Theme: `warm-paper` (default) or `navy-academic`
5. Material to build from: papers, notebooks, datasets, photos, last week's deck

### 2. Plan the story before any slide

Write a short outline and show it to the user before building:

- **The running case.** One concrete instance (a passenger, a photo, a
  3 × 3 grid) asked about on slide 2 and answered near the end.
- **3–5 sections**, which become the nav chips.
- **Slide titles only**, each a question or a claim. Read the titles alone:
  they should tell the lecture.
- **Where each number comes from.** Measured in class, computed in a
  notebook, or cited. Never invent a figure; if a number is illustrative,
  say so in the slide's `source`.

### 3. Write the deck spec

Write `<topic>.yaml` per `references/deck-spec.md`, choosing a layout per
slide. Write full speaker notes for every slide as spoken lines, with
`【按】` at each click. Put each image the user supplied beside the spec and
reference it by relative path.

### 4. Build

```bash
python3 "$SKILL/scripts/build_deck.py" <topic>.yaml -o <topic>.pptx
```

Exit code 2 means the spec is malformed; the message names the slide. Fix
every printed warning (missing notes or source, long title, overflow, image
placeholder) unless the user has said a placeholder is expected.

### 5. Look at it

```bash
python3 "$SKILL/scripts/render_preview.py" <topic>.pptx
```

Open the contact sheet and check each slide against the style guide: nothing
overflows or collides, each slide has one idea, emphasis colour is used once,
the running case returns at the end. LibreOffice substitutes 標楷體 when it is
not installed, so judge layout here, not typeface.

### 6. Deliver

Give the user the `.pptx`, the spec, and the list of image placeholders still
to fill. Say which numbers are illustrative and which are measured.

## Themes

| Theme | Page | Title | Emphasis |
|---|---|---|---|
| `warm-paper` | cream `#FFF8EC` | plain | rust `#9C3A24` |
| `navy-academic` | white | navy bar | crimson `#BA0C2F` |

A theme is a YAML file under `references/themes/`. To match another set of
example decks, copy one, replace the colours with values measured from the
examples, and pass its path with `--theme` or `deck.theme`.

## Extending the style from new example decks

When the user supplies more example decks, measure them rather than eyeballing:
render them with `render_preview.py`, and count fonts, sizes, text colours and
fills with `python-pptx` across all slides. Add a rule to the style guide only
when it holds across the examples, and cite the slide it comes from.
