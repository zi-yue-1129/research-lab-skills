# Deck spec (YAML) for `build_deck.py`

A deck spec is one YAML file: a `deck` header and a list of `slides`. Image
paths are relative to the spec file. A missing image becomes a labelled,
dashed placeholder and a build warning, so a draft deck always builds.

`examples/generic-demo.yaml` uses every layout with no preset;
`presets/zh-classroom/examples/knn-demo.yaml` is the same deck in the
`zh-classroom` preset.

## Header

```yaml
deck:
  preset: zh-classroom        # optional; a folder under presets/ (or a path)
  theme: warm-paper          # optional; the preset's themes, then the core's, or a path
  course: 人工智慧導論
  week: 第七週
  title: 看鄰居猜類別：K 近鄰
  author: 授課教師
  sections: [看資料, 量距離, 檢查, 比方法]   # nav chips, 3–5 short names
```

With no `preset` the core defaults apply (theme `default`, Calibri). With a
preset and no `theme`, the preset's `default_theme` applies.

## Fields every slide may carry

| Key | Meaning |
|---|---|
| `layout` | one of the layouts below (required) |
| `title` | a question or a claim, ≤ 22 CJK characters |
| `section` | which `deck.sections` chip to light up |
| `takeaway` | one centred sentence above the footer |
| `source` | footnote: dataset, paper, image licence, or 本課實際計算 |
| `notes` | full speaker script; mark clicks with the preset's click marker |

## Inline markup (any text field)

- `**詞**` colours a span with the emphasis tone (`alert`).
- `{positive:詞}`, `{info:詞}`, `{highlight:詞}`, `{alert:詞}` pick a tone.

## Layouts

| Layout | Use it for | Keys |
|---|---|---|
| `title` | opening slide | `title`, `subtitle` (the hook question), `image` (left-bleed photo) or `motif` (a name the active preset's `motifs.py` defines, e.g. `tree` in `zh-classroom`) |
| `agenda` | numbered stages | `items: [{label, note, tone}]`, `current` (1-based) |
| `facts` | the opening case | `image`, `caption`, `heading`, `facts: [{key: value}]`, `question`, `tone` |
| `compare` | last week vs this week, A vs B | `panels:` exactly 2 × `{heading, tone, lines, image}` |
| `cards` | 1–4 outcomes / options side by side | `cards: [{heading, tone, fill_tone, dots: [filled, total], lines, value, value_label}]`, optional `band`, `card_height` |
| `formula` | formula after a worked case | `cards` (optional row above), `band: {expr, plain, aside}`, `steps` (arrowed cards), `result: {expr}` |
| `numbers` | big measured numbers | `stats: [{value, label, tone}]`, plus `image` + `caption` or `panel` (a card) on the left |
| `table` | a slice of the dataset | `headers`, `rows`, `highlight_col` (0-based), `caption`, `width` |
| `bars` | compare one score across options | `items: [{label, value, note}]`, `max`, `best` (0-based), `axis_label` |
| `flow` | a pipeline, left to right | `steps: [{heading, tone, lines, image}]` |
| `image` | a figure from a paper or a result | `image`, `caption`, `quote` |
| `code` | ≤ 12 lines of code | `code`, `label`, `points: [{heading, text, tone}]` |
| `sources` | the closing source list | `items: [...]` |

Tones: `positive`, `alert`, `info`, `highlight`, `neutral`.

## Build warnings

`build_deck.py` prints a warning, not an error, when a slide has no notes, no
source footnote, a long title, an image placeholder, or text that probably
overflows its box. Fix every warning before handing the deck over.
