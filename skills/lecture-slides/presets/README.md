# Presets

A preset is one named, selectable lecture style: one course's or one
teacher's look and authoring rules. The core skill (`scripts/`,
`references/deck-spec.md`, `references/themes/default.yaml`) never mentions a
specific course. Everything course-specific lives in a preset folder.

Select one per deck with `deck.preset: <name>` in the spec, or with
`--preset <name>` on the command line. With no preset, the core defaults apply:
the neutral `default` theme, Calibri, and English placeholder strings.

## Shipped presets

| Preset | Style | Language | Themes |
|---|---|---|---|
| `zh-classroom` | Three of the lab's course decks (空間濾波, U-Net 語意分割, 分類與決策樹): Times New Roman + 標楷體, question titles, a running case, 【按】 notes | zh-TW | `warm-paper` (default), `navy-academic` |

## What a preset folder holds

```
presets/<name>/
  preset.yaml        # manifest (required)
  style-guide.md     # authoring rules Claude follows for this preset
  themes/*.yaml      # colour themes; looked up before the core themes
  motifs.py          # optional: title-slide motifs, MOTIFS = {name: draw}
  examples/*.yaml    # a demo deck in this preset
```

`preset.yaml` keys:

| Key | Meaning | Core default |
|---|---|---|
| `name`, `description` | identifier and one-line summary | — |
| `language` | language the decks and speaker notes are written in | follow the user |
| `style_guide` | file holding the preset's authoring rules | core rules in SKILL.md |
| `default_theme` | theme used when the spec names none | `default` |
| `fonts` | `latin`, `east_asian`, `mono` faces | Calibri, (theme's), Courier New |
| `strings` | `image_placeholder`, `meta_separator` | `[Image] `, ` · ` |
| `notes.click_marker` | how speaker notes mark a click | `[click]` |
| `motifs` | module defining `MOTIFS` | none |

A theme may also carry a `fonts` block; it overrides the preset's.

## Adding a preset from new example decks

1. Copy `zh-classroom/` to `presets/<new-name>/` and edit `preset.yaml`.
2. Measure the examples instead of eyeballing them: render them with
   `scripts/render_preview.py`, and count fonts, sizes, text colours and fills
   across all slides with `python-pptx`. Put the measured colours in
   `themes/` and the faces in `fonts`.
3. Rewrite `style-guide.md` so each rule holds across the new examples and
   cites the slide it comes from. Do not carry over rules the new examples
   do not show.
4. Delete `motifs.py` (and the `motifs` key) unless the new style has its own
   title-slide motif.
5. Write one demo spec under `examples/` and build it. Add the preset to the
   table above.
