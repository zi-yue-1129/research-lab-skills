---
name: lecture-slides
description: "Build an editable teaching deck (.pptx) for a course lecture, tutorial, or onboarding talk: question titles, a running concrete example, cards and charts drawn as native shapes, section chips, footnoted sources, n / N page numbers, and full speaker notes. A named preset selects one course's look (e.g. tku-lecture, the lab's TKU lecture style). Triggers: 上課簡報, 教學投影片, 講義簡報, 做一份課程簡報, 第 N 週的投影片, lecture slides, teaching deck, course slides, make slides like the examples."
metadata:
  version: "1.0.0"
  last_updated: "2026-10-27"
  status: active
  data_access_level: raw
  task_type: open-ended
  related_skills:
    - report-slides
    - deep-research
---

# Lecture Slides

Makes a teaching deck in which every element is a native PowerPoint shape the
teacher can edit. The skill has two parts:

- **The core** is course-agnostic: the deck spec (`references/deck-spec.md`),
  13 layouts, the slide chrome, the lint warnings, and a neutral `default`
  theme.
- **Presets** (`presets/<name>/`) each package one named style: its authoring
  rules, themes, fonts, strings, and title motifs. `presets/README.md` lists
  them and explains how to add one.

| Preset | Use when |
|---|---|
| *(none)* | no house style is asked for |
| `tku-lecture` | the user wants the lab's TKU course style ("像範例那樣", 淡江課程簡報, 跟上次一樣的課程風格) |

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

### 1. Pick the preset, then ask (one message)

Choose the preset from the table above. If one applies, read its
`preset.yaml` and its style guide now; the style guide's rules take precedence
over the core rules below, and its `language` sets the language of slides and
notes. Then ask only what you cannot infer:

1. Topic, course name, and week number
2. Audience level
3. Length (default: 20–30 slides for a 2-hour class)
4. Theme, if the preset ships more than one
5. Material to build from: papers, notebooks, datasets, photos, last week's deck

### 2. Plan the story before any slide

Show the user a short outline before building. Core rules, which apply with
or without a preset:

- **One running case.** One concrete instance, asked about early and answered
  near the end.
- **3–5 sections**, which become the nav chips.
- **Titles are questions or claims**, not topic labels. Read the titles alone:
  they should tell the lecture.
- **Every number has an origin.** Measured, computed in a notebook, or cited.
  Never invent a figure; mark illustrative numbers as such in `source`.
- **Every slide has speaker notes**, written as spoken lines, with the
  preset's click marker (`notes.click_marker`) at each click.

### 3. Write the deck spec

Write `<topic>.yaml` per `references/deck-spec.md`, setting `deck.preset` if
one applies. Put images beside the spec and reference them by relative path.
A preset's `examples/` folder shows a full spec in its style.

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

Open the contact sheet and check: nothing overflows or collides, each slide
has one idea, emphasis colour is used once, the running case returns at the
end, and the preset's style guide holds. LibreOffice substitutes fonts it
lacks (for example 標楷體), so judge layout here, not typeface.

### 6. Deliver

Give the user the `.pptx`, the spec, and the list of image placeholders still
to fill. Say which numbers are illustrative and which are measured.

## Limits of the core

- Slides are 16:9 (13.33 × 7.5 in); layout geometry is fixed to that size.
- The overflow warning estimates text width (CJK = 1 em, other = 0.5 em); the
  preview is the real check.
