# Slide Styles Reference

Loaded by `report-slides` to resolve styles during slide generation.
Read this file when resolving a style or when writing [C] Claude SVG slides.

---

## Built-in styles

| Name | File | Best for |
|------|------|----------|
| `default` | `styles/default.md` | Academic meetings, research progress reports |
| `minimal` | `styles/minimal.md` | Print, publications, no-color contexts |
| `dark` | `styles/dark.md` | Projector rooms, conference presentations |
| `paper` | `styles/paper.md` | Thesis / journal paper style — dark teal-blue on white |

---

## Frontmatter schema

All fields are optional; missing fields fall back to `default` values.

| Key | Type | Description | Default |
|-----|------|-------------|---------|
| `name` | string | Style identifier (slug) | — |
| `description` | string | One-line description | — |
| `primary` | hex | Accent color: titles, bullets, accents | `#1e3a5f` |
| `bg` | hex | Slide background | `#ffffff` |
| `body` | hex | Main text | `#374151` |
| `muted` | hex | Captions, footer, axis labels | `#64748b` |
| `border` | hex | Dividers, card borders | `#e2e8f0` |
| `card` | hex | Card / alternating row fill | `#f8fafc` |
| `positive` | hex | Success / increase values | `#059669` |
| `warn` | hex | Caution values | `#d97706` |
| `danger` | hex | Error / decrease values | `#dc2626` |
| `font` | CSS string | `font-family` attribute | `'Helvetica Neue', Arial, sans-serif` |

---

## Relationship to the design-token contract

This file is **human documentation**. The machine contract is
`references/design-tokens.schema.json` and the token files under
`references/tokens/`. Renderers and worker agents read tokens; they do not read
this file's frontmatter for sizes, spacing, or geometry.

Style `.md` frontmatter survives for one purpose: overriding *colours* on top of
a resolved token set, for a project that wants its brand palette without a full
token file. `generate_slides.py --style` applies it after `--tokens`. A style
file with no usable frontmatter is an error, not a silent no-op.

The former fixed skeleton — a 6px top accent bar, a 20pt centred title at y=44, a
full-width rule at y=54 — is no longer prescribed. Title placement, the rule, and
the footer come from `canvas.safe_area` and `typography.roles`, and the frame
offers `left` and `centered` variants rather than one mandatory arrangement.

To select or check a token file:

```bash
python3 scripts/validate_design_tokens.py --tokens references/tokens/default.tokens.yaml
python3 scripts/generate_slides.py --tokens <file> --data ... --out ... --deck-id ...
```

Color roles within slide content:
- Section headers, bullet markers → `primary`
- Body paragraphs → `body`
- Captions, notes, secondary labels → `muted`
- Positive numbers / improvements → `positive`
- Warnings / caveats → `warn`
- Errors / regressions → `danger`

---

## Creating a custom style

Copy any built-in as a starting point and edit its frontmatter:

```yaml
---
name: mycompany
description: Company brand — teal on off-white
primary: "#0d9488"
bg: "#f8fafc"
positive: "#0d9488"
warn: "#d97706"
danger: "#dc2626"
body: "#1e293b"
muted: "#64748b"
border: "#e2e8f0"
card: "#f1f5f9"
font: "'Inter', Arial, sans-serif"
---
```

Save to `docs/slides/styles/<name>.md` for a project-local named style, or copy to
`docs/slides/_style.md` to make it the project default.
