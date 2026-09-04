# report-slides Visual Quality Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `report-slides` an enforceable design-token contract, presentation-scale typography, faithful SVG→PPTX export, a deterministic visual linter, and a review stage that can name art-direction defects — so decks stop looking amateur and machine-generated.

**Architecture:** A validated YAML token contract (`design_tokens.py` + JSON Schema) becomes the single source of visual truth. Both rendering routes resolve it: the deterministic Python renderer reads it instead of hard-coded 10–14pt literals, and the native SVG route receives it through a now-mandatory `style_tokens_ref`. A new `visual_style/` package lints authored SVG against the resolved tokens with numeric thresholds. The existing `visual_quality_reviewer_agent` is narrowed to render integrity, and a new `art_direction_reviewer_agent` gains authority to reject compositionally weak slides.

**Tech Stack:** Python 3.11 (`.github/workflows/pytest.yml` pins 3.11; existing modules such as `presentation_gates.py` already use 3.10+ syntax, so new code may too), PyYAML, jsonschema, Pillow (font metrics), fontTools, lxml, python-pptx, `fc-match`/`fc-list` (fontconfig), pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-report-slides-visual-quality-design.md`

## Global Constraints

- All code comments, docstrings, log messages, and commit subjects in English.
- Every function signature carries type hints; every public module/function/class/method carries a Google-style docstring.
- No silent failures. No bare `except:`. `except Exception` only when it re-raises or logs with `exc_info=True` plus a comment stating why execution continues. Never `except ...: pass`. Never add `# noqa`, `# type: ignore`, or `# pragma: no cover`.
- Keep files under ~1000 lines; split into modules when exceeded.
- Red before green: run each new test and see it FAIL for the intended reason before implementing, then see it pass. Report both runs.
- Never weaken a test to make it green — no added `skip`/`xfail`, no loosened assertions, no `--deselect`.
- Every command is time-bound: `timeout <secs> python3 -m pytest ...`.
- Canvas is fixed at `1200 × 675`. SVG `font-size` maps 1:1 to PowerPoint points.
- Tests live in `skills/report-slides/scripts/tests/`. `pyproject.toml` sets `pythonpath = ["."]`; run pytest from the repository root.
- Token files are YAML. Style `.md` frontmatter is retained as human documentation only and is never the machine contract.
- Do not modify the evidence, manifest, transaction, or provenance machinery.

---

## File Map

| File | Action | Phase |
|------|--------|-------|
| `skills/report-slides/scripts/conftest.py` | Create | 1 |
| `.github/workflows/pytest.yml` | Modify (run and gate `skills/`) | 1 |
| `skills/report-slides/references/design-tokens.schema.json` | Create | 1 |
| `skills/report-slides/references/tokens/default.tokens.yaml` | Create | 1 |
| `skills/report-slides/scripts/design_tokens.py` | Create | 1 |
| `skills/report-slides/scripts/tests/test_design_tokens.py` | Create | 1 |
| `skills/report-slides/scripts/validate_design_tokens.py` | Create | 1 |
| `skills/report-slides/scripts/tests/test_validate_design_tokens.py` | Create | 1 |
| `skills/report-slides/scripts/fonts.py` | Create | 1 |
| `skills/report-slides/scripts/tests/test_fonts.py` | Create | 1 |
| `skills/report-slides/scripts/validate_visual_module.py` | Modify (`_validate_style_tokens_ref`, line 285) | 1 |
| `skills/report-slides/scripts/tests/test_style_tokens_ref_enforcement.py` | Create | 1 |
| `skills/report-slides/scripts/generate_slides.py` | Modify (`S`, `apply_style`, `frame`, 33 font-size sites) | 2 |
| `skills/report-slides/scripts/tests/test_generate_slides_typography.py` | Create | 2 |
| `skills/report-slides/references/styles/STYLES.md` | Modify (point at the token contract) | 2 |
| `skills/report-slides/SKILL.md` | Modify (Style system section; `--tokens` flag) | 2 |
| `skills/report-slides/scripts/svg_to_pptx/shapes.py` | Modify (`_apply_font` 200–220, `_add_rect` 29–45) | 3 |
| `skills/report-slides/scripts/svg_to_pptx/connector.py` | Modify (`_add_line` 57–68) | 3 |
| `skills/report-slides/scripts/svg_to_pptx/style_parser.py` | Modify (`apply_stroke`; add dash/alpha/gradient wiring) | 3 |
| `skills/report-slides/scripts/svg_to_pptx/converter.py` | Modify (`_resolve_defs`, `_dispatch_element`) | 3 |
| `skills/report-slides/scripts/svg_to_pptx/tests/test_fidelity.py` | Create | 3 |
| `skills/report-slides/agents/architecture_diagram_worker_agent.md` | Modify (resolve tokens; declare roles) | 3 |
| `skills/report-slides/references/diagram-patterns.md` | Modify (token-driven geometry) | 3 |
| `skills/report-slides/scripts/tests/test_effective_tokens.py` | Create | 4 |

---

## Phase Overview

| Phase | Theme | Tasks |
|-------|-------|-------|
| 1 | Token contract and enforcement | 0–5 |
| 2 | Presentation-scale typography | 6–9 |
| 3 | SVG→PPTX export fidelity | 10–15 |
| 4 | One token set, compiled | 16 |

Phases are ordered by dependency. Task 0 is a prerequisite for every other
task in both plans — none of their per-file `Run:` commands work without it.
Tasks 11–14 are independent of Phases 1–2; Task 10 consumes `fonts.py` from
Task 5, Task 15 consumes everything, and Task 16 closes the contract by making
the style override and the token file one artifact — which the second plan's
linter and workflow gate both read.

## Scope: this is plan 1 of 2

The spec covers two separable subsystems. This plan delivers the first, which is
independently shippable: after Task 14 the visual system has an enforced machine
contract, both rendering routes typeset for projection, and SVG→PPTX export is
faithful.

The second subsystem — the deterministic visual linter (spec D4), the review split
(spec D5), and generative art direction (spec D6) — is a separate plan,
`docs/superpowers/plans/2026-09-04-report-slides-visual-review.md`. It consumes
`design_tokens.py` and `fonts.py` from this plan and must be executed after it.

**Out of scope of both plans (separate design required):** automatic graph layout
via ELK/Graphviz/dagre. See spec §5.

## Why Phase 2 is four tasks rather than one

`generate_slides.py` contains 33 font-size sites (lines 140, 145, 174, 183, 188,
191, 210, 214, 237, 261, 278, 287, 290, 319, 331, 347, 394, 398, 453, 472, 519,
521, 526, 545, 555, 560, 606, 611, 617, 640, 651, 653, 656). Raising body text
from 13 to 21 is a 62% increase, and every renderer's vertical offsets
(`y + 10`, `cy + 36`, `CB + 20`, `py + 30`, `iy + 7`, …) were tuned against the
small sizes. Swapping the numbers alone produces overlapping and clipped text.

Each Phase 2 task therefore re-tunes one renderer family's geometry and ends with
a rendered-pixel check, not only a unit test. A task that changed all 33 sites at
once could not be reviewed or reverted per renderer.

---

## Phase 1: Token Contract and Enforcement

---

### Task 0: Make the report-slides suite importable file-by-file

Every `Run:` line in this plan and in plan 2 targets a single test file. Today
that does not work: the modules under `skills/report-slides/scripts/` are plain
top-level modules, not an installed package, and the tests import them by bare
name (`from presentation_gates import ...`). Collecting the *directory* happens
to work because pytest prepends the argument's basedir; collecting one *file*
under `scripts/tests/` does not, because `tests/` has no `__init__.py`, so the
inserted basedir is `scripts/tests`, not `scripts`.

Both plans previously worked around this with a per-file
`sys.path.insert(...)` preamble and a linter-suppression comment on each
deferred import — which the Global Constraints of both plans forbid. This task
removes the need for the workaround once, for the whole suite.

`svg_to_pptx/tests/` is unaffected: `svg_to_pptx/` and its `tests/` are real
packages, so pytest already walks up to `scripts/`. The gap is only
`scripts/tests/`.

**Files:**
- Create: `skills/report-slides/scripts/conftest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: bare-name importability of every module in
  `skills/report-slides/scripts/` from any pytest invocation. Every subsequent
  task in this plan and in plan 2 depends on it, and none of them may reintroduce
  a `sys.path` preamble in a test file.

- [x] **Step 1: Observe the failure**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_presentation_gates.py -q`

Expected: FAIL at collection, verbatim:

```
E   ModuleNotFoundError: No module named 'presentation_contracts'
ERROR skills/report-slides/scripts/tests/test_presentation_gates.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.08s
```

This is an existing defect, not one this plan introduces. It is listed as Task 0
because 27 later steps in the two plans cannot be run until it is fixed.

- [x] **Step 2: Record the collection baseline**

Run: `timeout 900 python3 -m pytest --collect-only -q | tail -1`
Expected: `4008 tests collected` (or higher on a later checkout). Write the
number down; Step 4 asserts it does not move.

- [x] **Step 3: Add the conftest**

Create `skills/report-slides/scripts/conftest.py`:

```python
"""Make the report-slides script package importable from any pytest rootdir.

The modules in this directory are plain top-level modules, not an installed
package, and the tests import them by bare name (`import presentation_gates`).
Collecting the directory happens to work because pytest prepends the argument's
basedir, but collecting a single test file under `tests/` does not, because
`tests/` is not a package: the inserted basedir is `tests/`, not this directory.
Anchoring sys.path here makes every invocation behave the same, which is what
lets the plans' per-file `Run:` commands work without a bootstrap preamble in
each test module.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
```

The `if` guard matters: pytest imports a conftest once per session, but a
developer running two directories in one invocation should not accumulate
duplicate `sys.path` entries.

- [x] **Step 4: Run the same file and the whole suite**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_presentation_gates.py -q`
Expected: PASS — `18 passed`.

Run: `timeout 900 python3 -m pytest --collect-only -q | tail -1`
Expected: the same count as Step 2 — `4008 tests collected`. A conftest that
changes `sys.path` can shadow a module of the same name elsewhere in the tree;
an unchanged count is the check that it has not.

- [x] **Step 5: Bring `skills/` into the CI gate**

`.github/workflows/pytest.yml` runs `pytest scripts/ tests/` and its `paths:`
filters never mention `skills/**`. The 1506 tests under
`skills/report-slides/scripts/` therefore do not gate any pull request today;
only `test-count-monotonic.yml`, which runs a bare `pytest --collect-only`, sees
them, and that gate counts tests without running them.

In `.github/workflows/pytest.yml`, add `'skills/**'` to both `paths:` lists and
change the run step to:

```yaml
        run: pytest scripts/ tests/ skills/
```

- [x] **Step 6: Commit**

```bash
git add skills/report-slides/scripts/conftest.py .github/workflows/pytest.yml
git commit -m "test: anchor sys.path for report-slides scripts and gate skills/ in CI"
```

---

### Task 1: Design token schema and default token file

**Files:**
- Create: `skills/report-slides/references/design-tokens.schema.json`
- Create: `skills/report-slides/references/tokens/default.tokens.yaml`
- Test: `skills/report-slides/scripts/tests/test_design_tokens.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the on-disk token contract. Task 2 loads it, Task 3 validates it via
  CLI, Tasks 6–7 and 13–17 read roles from it. Schema `$id` is
  `https://claude-research-skills/report-slides/design-tokens/v1`.

- [x] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_design_tokens.py`:

```python
"""Tests for the design-token contract and its loader."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

_SKILL_DIR = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _SKILL_DIR / "references" / "design-tokens.schema.json"
_DEFAULT_TOKENS = _SKILL_DIR / "references" / "tokens" / "default.tokens.yaml"


def test_schema_file_exists_and_is_valid_json_schema() -> None:
    """The token schema must exist and be a usable Draft 2020-12 schema."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)


def test_default_tokens_validate_against_schema() -> None:
    """The shipped default token file must satisfy the schema."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    tokens = yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(tokens)


@pytest.mark.parametrize(
    "role,minimum",
    [
        ("slide_title", 30),
        ("takeaway", 24),
        ("body", 20),
        ("node_label", 18),
        ("axis", 16),
        ("caption", 16),
        ("footnote", 12),
    ],
)
def test_default_typography_meets_presentation_floors(role: str, minimum: int) -> None:
    """Default type roles must not fall below the presentation-scale floors."""
    tokens = yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))
    assert tokens["typography"]["roles"][role]["size"] >= minimum


def test_schema_rejects_typography_below_floor() -> None:
    """A token file setting body text to document scale must fail validation."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    tokens = yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))
    tokens["typography"]["roles"]["body"]["size"] = 10
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(tokens)
```

- [x] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_design_tokens.py -v`
Expected: FAIL — `FileNotFoundError` for `design-tokens.schema.json`.

- [x] **Step 3: Create the schema**

Create `skills/report-slides/references/design-tokens.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://claude-research-skills/report-slides/design-tokens/v1",
  "title": "report-slides design tokens",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "name", "canvas", "typography", "spacing",
               "surfaces", "connectors", "color", "chart", "icons", "density"],
  "properties": {
    "schema_version": {"const": 1},
    "name": {"type": "string", "minLength": 1},
    "description": {"type": "string"},
    "canvas": {
      "type": "object",
      "additionalProperties": false,
      "required": ["width", "height", "safe_area", "grid"],
      "properties": {
        "width": {"const": 1200},
        "height": {"const": 675},
        "grid": {"type": "integer", "minimum": 4, "maximum": 16},
        "safe_area": {
          "type": "object",
          "additionalProperties": false,
          "required": ["left", "right", "top", "bottom"],
          "properties": {
            "left": {"type": "integer", "minimum": 24},
            "right": {"type": "integer", "minimum": 24},
            "top": {"type": "integer", "minimum": 24},
            "bottom": {"type": "integer", "minimum": 24}
          }
        }
      }
    },
    "typography": {
      "type": "object",
      "additionalProperties": false,
      "required": ["family", "roles", "max_sizes_per_slide"],
      "properties": {
        "family": {
          "type": "object",
          "additionalProperties": {"type": "string", "minLength": 1},
          "required": ["sans", "mono"]
        },
        "max_sizes_per_slide": {"type": "integer", "minimum": 2, "maximum": 6},
        "roles": {
          "type": "object",
          "additionalProperties": false,
          "required": ["deck_title", "slide_title", "takeaway", "body",
                       "node_label", "axis", "caption", "footnote"],
          "properties": {
            "deck_title":  {"$ref": "#/$defs/typeRole36"},
            "slide_title": {"$ref": "#/$defs/typeRole30"},
            "takeaway":    {"$ref": "#/$defs/typeRole24"},
            "body":        {"$ref": "#/$defs/typeRole20"},
            "node_label":  {"$ref": "#/$defs/typeRole18"},
            "axis":        {"$ref": "#/$defs/typeRole16"},
            "caption":     {"$ref": "#/$defs/typeRole16"},
            "footnote":    {"$ref": "#/$defs/typeRole12"}
          }
        }
      }
    },
    "spacing": {
      "type": "object",
      "additionalProperties": false,
      "required": ["scale", "node_padding", "node_gap_min", "connector_clearance_min"],
      "properties": {
        "scale": {"type": "array", "minItems": 4,
                  "items": {"type": "integer", "minimum": 2}},
        "node_padding": {
          "type": "object",
          "additionalProperties": false,
          "required": ["x", "y"],
          "properties": {"x": {"type": "integer", "minimum": 16},
                         "y": {"type": "integer", "minimum": 12}}
        },
        "node_gap_min": {"type": "integer", "minimum": 24},
        "connector_clearance_min": {"type": "integer", "minimum": 12}
      }
    },
    "surfaces": {
      "type": "object",
      "minProperties": 1,
      "additionalProperties": {"$ref": "#/$defs/surface"}
    },
    "connectors": {
      "type": "object",
      "additionalProperties": false,
      "required": ["stroke_width", "arrowhead", "dash_patterns"],
      "properties": {
        "stroke_width": {"type": "number", "minimum": 1},
        "arrowhead": {
          "type": "object",
          "additionalProperties": false,
          "required": ["style", "size"],
          "properties": {
            "style": {"enum": ["triangle", "stealth", "arrow", "oval",
                               "diamond", "none"]},
            "size": {"enum": ["small", "medium", "large"]}
          }
        },
        "dash_patterns": {
          "type": "object",
          "additionalProperties": {"type": "string"},
          "required": ["solid", "dashed", "dotted"]
        }
      }
    },
    "color": {
      "type": "object",
      "additionalProperties": false,
      "required": ["roles", "decorative_roles", "contrast"],
      "properties": {
        "roles": {
          "type": "object",
          "minProperties": 5,
          "additionalProperties": {"$ref": "#/$defs/hex"}
        },
        "decorative_roles": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Roles exempt from the graphic contrast floor: dividers, gridlines, surface fills."
        },
        "contrast": {
          "type": "object",
          "additionalProperties": false,
          "required": ["text_min", "large_text_min", "graphic_min"],
          "properties": {
            "text_min": {"type": "number", "minimum": 4.5},
            "large_text_min": {"type": "number", "minimum": 3.0},
            "graphic_min": {"type": "number", "minimum": 3.0}
          }
        }
      }
    },
    "chart": {
      "type": "object",
      "additionalProperties": false,
      "required": ["palette"],
      "properties": {
        "palette": {"type": "array", "minItems": 3,
                    "items": {"$ref": "#/$defs/hex"}}
      }
    },
    "icons": {
      "type": "object",
      "additionalProperties": false,
      "required": ["family", "stroke_width", "optical_size", "forbidden_when"],
      "properties": {
        "family": {"type": ["string", "null"]},
        "stroke_width": {"type": "number", "minimum": 1},
        "optical_size": {"type": "integer", "minimum": 16},
        "forbidden_when": {"type": "array", "items": {"type": "string"}}
      }
    },
    "density": {
      "type": "object",
      "additionalProperties": false,
      "required": ["occupancy_min", "occupancy_max", "max_bullets"],
      "properties": {
        "occupancy_min": {"type": "number", "minimum": 0, "maximum": 1},
        "occupancy_max": {"type": "number", "minimum": 0, "maximum": 1},
        "max_bullets": {"type": "integer", "minimum": 1, "maximum": 10}
      }
    }
  },
  "$defs": {
    "hex": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
    "typeRoleBase": {
      "type": "object",
      "additionalProperties": false,
      "required": ["size", "weight", "line_height", "max_lines", "family"],
      "properties": {
        "size": {"type": "number"},
        "weight": {"type": "integer", "minimum": 100, "maximum": 900},
        "line_height": {"type": "number", "minimum": 1.0, "maximum": 2.0},
        "max_lines": {"type": "integer", "minimum": 1, "maximum": 12},
        "family": {"type": "string", "minLength": 1}
      }
    },
    "typeRole36": {"allOf": [{"$ref": "#/$defs/typeRoleBase"},
                             {"properties": {"size": {"minimum": 36}}}]},
    "typeRole30": {"allOf": [{"$ref": "#/$defs/typeRoleBase"},
                             {"properties": {"size": {"minimum": 30}}}]},
    "typeRole24": {"allOf": [{"$ref": "#/$defs/typeRoleBase"},
                             {"properties": {"size": {"minimum": 24}}}]},
    "typeRole20": {"allOf": [{"$ref": "#/$defs/typeRoleBase"},
                             {"properties": {"size": {"minimum": 20}}}]},
    "typeRole18": {"allOf": [{"$ref": "#/$defs/typeRoleBase"},
                             {"properties": {"size": {"minimum": 18}}}]},
    "typeRole16": {"allOf": [{"$ref": "#/$defs/typeRoleBase"},
                             {"properties": {"size": {"minimum": 16}}}]},
    "typeRole12": {"allOf": [{"$ref": "#/$defs/typeRoleBase"},
                             {"properties": {"size": {"minimum": 12}}}]},
    "surface": {
      "type": "object",
      "additionalProperties": false,
      "required": ["radius", "border_width", "fill", "border", "padding"],
      "properties": {
        "radius": {"type": "integer", "minimum": 0, "maximum": 32},
        "border_width": {"type": "number", "minimum": 0},
        "fill": {"type": "string", "minLength": 1},
        "border": {"type": "string", "minLength": 1},
        "padding": {
          "type": "object",
          "additionalProperties": false,
          "required": ["x", "y"],
          "properties": {"x": {"type": "integer", "minimum": 0},
                         "y": {"type": "integer", "minimum": 0}}
        }
      }
    }
  }
}
```

> **Why `$defs/typeRoleNN` wrappers:** in Draft 2020-12 a sibling `properties`
> next to `$ref` *is* applied (this changed from Draft 7, where siblings were
> ignored), so `{"$ref": ..., "properties": {"size": {"minimum": 30}}}` would also
> enforce the floor — both forms were verified against `jsonschema` before this
> plan was written. The explicit `allOf` wrappers are used anyway because they
> state the composition unambiguously and survive a future downgrade of the
> declared draft. Either way, `test_schema_rejects_typography_below_floor` is the
> check that proves the floor is live; do not remove it.

- [x] **Step 4: Create the default token file**

Create `skills/report-slides/references/tokens/default.tokens.yaml`.

Colour values were measured against `#ffffff`: `primary` 11.50:1, `body` 10.31:1,
`muted` 4.76:1, `line` 7.58:1, `positive` 5.48:1, `warn` 5.02:1, `danger` 6.47:1.
`divider` (1.23:1), `card` (1.05:1), and `bg` are decorative and listed in
`decorative_roles`. Chart palette entries measure 11.50, 5.47, 5.02, 5.70, 6.47,
and 4.99:1 — all above the 4.5 text floor, so chart marks may carry labels.

```yaml
schema_version: 1
name: default
description: >-
  Academic blue on white, typeset for projection. Machine contract for the
  report-slides visual system; references/styles/STYLES.md is prose guidance only.

canvas:
  width: 1200
  height: 675
  grid: 8
  safe_area: {left: 48, right: 48, top: 36, bottom: 36}

typography:
  family:
    sans: "Inter, 'DejaVu Sans', 'Liberation Sans', Arial, sans-serif"
    mono: "'DejaVu Sans Mono', 'Liberation Mono', 'Courier New', monospace"
  max_sizes_per_slide: 4
  roles:
    deck_title:  {size: 44, weight: 700, line_height: 1.15, max_lines: 3, family: sans}
    slide_title: {size: 32, weight: 700, line_height: 1.20, max_lines: 2, family: sans}
    takeaway:    {size: 26, weight: 600, line_height: 1.35, max_lines: 3, family: sans}
    body:        {size: 21, weight: 400, line_height: 1.45, max_lines: 8, family: sans}
    node_label:  {size: 18, weight: 600, line_height: 1.25, max_lines: 3, family: sans}
    axis:        {size: 16, weight: 400, line_height: 1.20, max_lines: 2, family: sans}
    caption:     {size: 16, weight: 400, line_height: 1.35, max_lines: 3, family: sans}
    footnote:    {size: 12, weight: 400, line_height: 1.30, max_lines: 2, family: sans}

spacing:
  scale: [4, 8, 12, 16, 24, 32, 48, 64]
  node_padding: {x: 16, y: 12}
  node_gap_min: 24
  connector_clearance_min: 12

surfaces:
  node:    {radius: 8,  border_width: 1.5, fill: card, border: line,    padding: {x: 16, y: 12}}
  card:    {radius: 12, border_width: 1.0, fill: card, border: divider, padding: {x: 24, y: 16}}
  callout: {radius: 8,  border_width: 1.5, fill: bg,   border: primary, padding: {x: 16, y: 12}}

connectors:
  stroke_width: 2
  arrowhead: {style: triangle, size: medium}
  dash_patterns:
    solid: ""
    dashed: "8 4"
    dotted: "2 4"

color:
  roles:
    primary:  "#1e3a5f"
    bg:       "#ffffff"
    body:     "#374151"
    muted:    "#64748b"
    line:     "#475569"
    divider:  "#e2e8f0"
    card:     "#f8fafc"
    positive: "#047857"
    warn:     "#b45309"
    danger:   "#b91c1c"
  decorative_roles: [divider, card, bg]
  contrast:
    text_min: 4.5
    large_text_min: 3.0
    graphic_min: 3.0

chart:
  palette: ["#1e3a5f", "#0f766e", "#b45309", "#7c3aed", "#b91c1c", "#4d7c0f"]

icons:
  family: null
  stroke_width: 1.5
  optical_size: 24
  forbidden_when:
    - "the icon repeats identically across every node and carries no distinction"
    - "the icon is decorative garnish rather than a domain symbol"
    - "no icon family is configured"

density:
  occupancy_min: 0.30
  occupancy_max: 0.78
  max_bullets: 6
```

- [x] **Step 5: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_design_tokens.py -v`
Expected: PASS — 10 passed (3 plain tests plus one parametrised 7 ways).

- [x] **Step 6: Commit**

```bash
git add skills/report-slides/references/design-tokens.schema.json \
        skills/report-slides/references/tokens/default.tokens.yaml \
        skills/report-slides/scripts/tests/test_design_tokens.py
git commit -m "feat(report-slides): add validated design-token contract"
```

---

### Task 2: Design token loader

**Files:**
- Create: `skills/report-slides/scripts/design_tokens.py`
- Test: `skills/report-slides/scripts/tests/test_design_tokens.py` (append)

**Interfaces:**
- Consumes: `references/design-tokens.schema.json` and a token YAML file (Task 1).
- Produces, all imported by Tasks 3, 4, 6, 7, and 13–17:
  - `SCHEMA_PATH: Path`, `DEFAULT_TOKENS_PATH: Path`
  - `class TokenError(ValueError)`
  - `@dataclass(frozen=True) class TypeRole` — `size: float`, `weight: int`,
    `line_height: float`, `max_lines: int`, `family: str`
  - `semantic_errors(data: Mapping[str, Any]) -> List[str]` — the cross-field
    checks JSON Schema cannot express
  - `class DesignTokens` with `load(path: Union[str, Path]) -> DesignTokens`,
    `digest -> str`, `path -> Path`, `raw -> Mapping[str, Any]`,
    `type_role(name: str) -> TypeRole`, `font_stack(family_key: str) -> str`,
    `color(role: str) -> str`, `is_decorative(role: str) -> bool`,
    `surface(name: str) -> Mapping[str, Any]`

- [x] **Step 1: Write the failing test**

Append to `skills/report-slides/scripts/tests/test_design_tokens.py`:

```python
from design_tokens import DesignTokens, TokenError


def test_loader_reads_default_tokens() -> None:
    """The loader returns typed roles and colours from the default file."""
    tokens = DesignTokens.load(_DEFAULT_TOKENS)
    assert tokens.type_role("slide_title").size == 32
    assert tokens.type_role("slide_title").weight == 700
    assert tokens.color("primary") == "#1e3a5f"
    assert tokens.is_decorative("divider") is True
    assert tokens.is_decorative("line") is False
    assert tokens.surface("node")["radius"] == 8
    assert "Inter" in tokens.font_stack("sans")


def test_loader_digest_is_content_sensitive_not_whitespace_sensitive(
    tmp_path: Path,
) -> None:
    """The digest tracks token content, ignoring trailing whitespace."""
    original = _DEFAULT_TOKENS.read_text(encoding="utf-8")
    same = tmp_path / "same.tokens.yaml"
    same.write_text(original + "\n\n", encoding="utf-8")
    changed = tmp_path / "changed.tokens.yaml"
    changed.write_text(original.replace("size: 32", "size: 34"), encoding="utf-8")

    baseline = DesignTokens.load(_DEFAULT_TOKENS).digest
    assert DesignTokens.load(same).digest == baseline
    assert DesignTokens.load(changed).digest != baseline


def test_the_shipped_default_is_semantically_coherent() -> None:
    """The token file this plan ships passes its own cross-field checks."""
    import yaml

    from design_tokens import semantic_errors

    assert semantic_errors(
        yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))) == []


def test_an_inverted_occupancy_range_is_reported() -> None:
    """A range no slide can satisfy is schema-valid and unusable.

    Both bounds are numbers in [0, 1], so JSON Schema is content. Nothing else
    in the pipeline compares them, so the failure would surface as every slide
    reporting both `underfilled` and `overfilled` at once.
    """
    import yaml

    from design_tokens import semantic_errors

    data = yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))
    data["density"]["occupancy_min"] = 0.9
    errors = semantic_errors(data)
    assert any("occupancy_min" in error for error in errors)


def test_a_surface_naming_an_unknown_colour_role_is_reported() -> None:
    """`fill: cardd` is a string, and a string is all the schema requires."""
    import yaml

    from design_tokens import semantic_errors

    data = yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))
    data["surfaces"]["node"]["fill"] = "cardd"
    errors = semantic_errors(data)
    assert any("surfaces.node.fill" in error for error in errors)


def test_a_type_role_naming_an_unknown_family_is_reported() -> None:
    """A role pointing at a font family that does not exist is caught early."""
    import yaml

    from design_tokens import semantic_errors

    data = yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))
    data["typography"]["roles"]["body"]["family"] = "serif"
    errors = semantic_errors(data)
    assert any("typography.roles.body.family" in error for error in errors)


def test_an_unordered_spacing_scale_is_reported() -> None:
    """A spacing scale is an ordered vocabulary, not a bag of numbers."""
    import yaml

    from design_tokens import semantic_errors

    data = yaml.safe_load(_DEFAULT_TOKENS.read_text(encoding="utf-8"))
    data["spacing"]["scale"] = [8, 4, 12]
    errors = semantic_errors(data)
    assert any("spacing.scale" in error for error in errors)


def test_loader_raises_on_schema_violation(tmp_path: Path) -> None:
    """An invalid token file raises TokenError instead of falling back."""
    bad = tmp_path / "bad.tokens.yaml"
    bad.write_text(
        _DEFAULT_TOKENS.read_text(encoding="utf-8").replace("size: 21", "size: 9"),
        encoding="utf-8",
    )
    with pytest.raises(TokenError) as excinfo:
        DesignTokens.load(bad)
    assert "typography" in str(excinfo.value)


def test_loader_raises_on_missing_file(tmp_path: Path) -> None:
    """A missing token file raises TokenError, never a silent default."""
    with pytest.raises(TokenError):
        DesignTokens.load(tmp_path / "does-not-exist.yaml")


def test_unknown_role_raises() -> None:
    """Requesting an undefined type role or colour raises TokenError."""
    tokens = DesignTokens.load(_DEFAULT_TOKENS)
    with pytest.raises(TokenError):
        tokens.type_role("subtitle")
    with pytest.raises(TokenError):
        tokens.color("accent")
```

- [x] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_design_tokens.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'design_tokens'` at collection.

- [x] **Step 3: Write the loader**

Create `skills/report-slides/scripts/design_tokens.py`:

```python
"""Design-token contract loader for report-slides.

The token file is the machine contract for the visual system. Style Markdown
frontmatter remains human documentation and is never read by renderers.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Union

import jsonschema
import yaml

_REFERENCES_DIR = Path(__file__).resolve().parent.parent / "references"
SCHEMA_PATH = _REFERENCES_DIR / "design-tokens.schema.json"
DEFAULT_TOKENS_PATH = _REFERENCES_DIR / "tokens" / "default.tokens.yaml"


class TokenError(ValueError):
    """Raised when a token file is missing, unparsable, or schema-invalid.

    Never caught in order to substitute built-in defaults: an unusable token file
    is a hard failure, because a silently ignored style is indistinguishable from
    a correctly applied one.
    """


@dataclass(frozen=True)
class TypeRole:
    """One resolved typographic role.

    Attributes:
        size: Font size in SVG units, which map 1:1 to PowerPoint points.
        weight: CSS numeric font weight.
        line_height: Multiplier applied to `size` for baseline spacing.
        max_lines: Maximum permitted rendered lines for this role.
        family: Key into the token `typography.family` mapping.
    """

    size: float
    weight: int
    line_height: float
    max_lines: int
    family: str


class DesignTokens:
    """A validated, immutable view over one design-token file."""

    def __init__(self, data: Mapping[str, Any], path: Path) -> None:
        """Store validated token data and compute its digest.

        Args:
            data: Token mapping already validated against the schema.
            path: Filesystem path the tokens were loaded from.
        """
        self._data = data
        self._path = path
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        self._digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def load(cls, path: Union[str, Path]) -> "DesignTokens":
        """Load and validate a token file.

        Args:
            path: Path to a `.tokens.yaml` file.

        Returns:
            A validated `DesignTokens` instance.

        Raises:
            TokenError: If the file is missing, unparsable, or violates the schema.
        """
        token_path = Path(path)
        try:
            raw_text = token_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TokenError(f"cannot read token file {token_path}: {exc}") from exc
        try:
            data = yaml.safe_load(raw_text)
        except yaml.YAMLError as exc:
            raise TokenError(f"cannot parse token file {token_path}: {exc}") from exc
        if not isinstance(data, dict):
            raise TokenError(f"token file {token_path} must contain a mapping")
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        try:
            jsonschema.Draft202012Validator(schema).validate(data)
        except jsonschema.ValidationError as exc:
            location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
            raise TokenError(
                f"token file {token_path} is invalid at {location}: {exc.message}"
            ) from exc
        errors = semantic_errors(data)
        if errors:
            joined = "; ".join(errors)
            raise TokenError(f"token file {token_path} is inconsistent: {joined}")
        return cls(data, token_path)

    @property
    def digest(self) -> str:
        """Return the sha256 hex digest of the canonicalised token content."""
        return self._digest

    @property
    def path(self) -> Path:
        """Return the path the tokens were loaded from."""
        return self._path

    @property
    def raw(self) -> Mapping[str, Any]:
        """Return the underlying token mapping."""
        return self._data

    def type_role(self, name: str) -> TypeRole:
        """Return one typographic role.

        Args:
            name: Role key, such as `slide_title` or `node_label`.

        Returns:
            The resolved `TypeRole`.

        Raises:
            TokenError: If the role is not defined.
        """
        roles = self._data["typography"]["roles"]
        if name not in roles:
            raise TokenError(
                f"undefined type role {name!r}; defined roles: {sorted(roles)}"
            )
        role = roles[name]
        return TypeRole(
            size=float(role["size"]),
            weight=int(role["weight"]),
            line_height=float(role["line_height"]),
            max_lines=int(role["max_lines"]),
            family=str(role["family"]),
        )

    def font_stack(self, family_key: str) -> str:
        """Return the CSS font stack for a family key.

        Args:
            family_key: Key into `typography.family`, such as `sans`.

        Returns:
            The CSS `font-family` value.

        Raises:
            TokenError: If the family key is not defined.
        """
        families = self._data["typography"]["family"]
        if family_key not in families:
            raise TokenError(
                f"undefined font family {family_key!r}; "
                f"defined families: {sorted(families)}"
            )
        return str(families[family_key])

    def color(self, role: str) -> str:
        """Return the hex value for a colour role.

        Args:
            role: Colour role key, such as `primary`.

        Returns:
            A `#rrggbb` string.

        Raises:
            TokenError: If the role is not defined.
        """
        roles = self._data["color"]["roles"]
        if role not in roles:
            raise TokenError(
                f"undefined colour role {role!r}; defined roles: {sorted(roles)}"
            )
        return str(roles[role])

    def is_decorative(self, role: str) -> bool:
        """Return whether a colour role is exempt from the graphic contrast floor.

        Args:
            role: Colour role key.

        Returns:
            True when the role is listed in `color.decorative_roles`.
        """
        return role in self._data["color"]["decorative_roles"]

    def surface(self, name: str) -> Mapping[str, Any]:
        """Return one surface definition.

        Args:
            name: Surface key, such as `node` or `card`.

        Returns:
            The surface mapping with `radius`, `border_width`, `fill`, `border`,
            and `padding`.

        Raises:
            TokenError: If the surface is not defined.
        """
        surfaces = self._data["surfaces"]
        if name not in surfaces:
            raise TokenError(
                f"undefined surface {name!r}; defined surfaces: {sorted(surfaces)}"
            )
        return surfaces[name]


def semantic_errors(data: Mapping[str, Any]) -> List[str]:
    """Return the cross-field inconsistencies JSON Schema cannot express.

    A schema validates each value against its own constraint and knows nothing
    about the relationships between them. A token file with
    `occupancy_min: 0.9, occupancy_max: 0.3`, or a surface whose `fill` names a
    colour role that does not exist, is schema-valid and unusable -- and the
    failure surfaces several files away from the mistake, as a `TokenError` from
    `color()` during a render, or as a linter finding nobody can explain.

    Args:
        data: A schema-valid token mapping.

    Returns:
        Human-readable inconsistencies, empty when the file is coherent.
    """
    errors: List[str] = []
    color_roles = set(data["color"]["roles"])
    families = set(data["typography"]["family"])

    density = data["density"]
    if density["occupancy_min"] >= density["occupancy_max"]:
        errors.append(
            f"density.occupancy_min ({density['occupancy_min']}) must be below "
            f"occupancy_max ({density['occupancy_max']}); as written no slide "
            f"can satisfy both"
        )

    for name, role in sorted(data["typography"]["roles"].items()):
        if role["family"] not in families:
            errors.append(
                f"typography.roles.{name}.family names {role['family']!r}, "
                f"which is not in typography.family ({sorted(families)})"
            )

    for name, surface in sorted(data["surfaces"].items()):
        for key in ("fill", "border"):
            if surface[key] not in color_roles:
                errors.append(
                    f"surfaces.{name}.{key} names {surface[key]!r}, which is "
                    f"not a colour role ({sorted(color_roles)})"
                )

    unknown = sorted(set(data["color"]["decorative_roles"]) - color_roles)
    if unknown:
        errors.append(
            f"color.decorative_roles names {unknown}, which are not colour "
            f"roles; a decorative exemption for a role nothing uses silently "
            f"exempts nothing"
        )

    scale = data["spacing"]["scale"]
    if sorted(set(scale)) != list(scale):
        errors.append(
            f"spacing.scale {scale} must be strictly ascending and unique; a "
            f"spacing scale is an ordered vocabulary, and a repeated or "
            f"out-of-order step makes 'the next step up' undefined"
        )
    # Deliberately not checked: that every step is a multiple of `canvas.grid`.
    # The shipped scale opens with 4 against a grid of 8, and `node_padding.y`
    # is 12. A half-step for tight internal padding is ordinary practice, and a
    # rule that rejected it would reject this plan's own token file.
    return errors

```

- [x] **Step 4: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_design_tokens.py -v`
Expected: PASS — 20 passed.

- [x] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/design_tokens.py \
        skills/report-slides/scripts/tests/test_design_tokens.py
git commit -m "feat(report-slides): add design-token loader with digest and hard failures"
```

---

### Task 3: Token validator CLI

**Files:**
- Create: `skills/report-slides/scripts/validate_design_tokens.py`
- Test: `skills/report-slides/scripts/tests/test_validate_design_tokens.py`

**Interfaces:**
- Consumes: `design_tokens.DesignTokens`, `design_tokens.TokenError` (Task 2).
- Produces: CLI `python3 scripts/validate_design_tokens.py --tokens PATH [--json]`,
  exit 0 when valid and 1 when not; and
  `validate_token_file(path: Path) -> list[str]` imported by Task 4.

The CLI mirrors the existing validator convention in this skill: a `{"valid":
bool, "errors": [...]}` JSON payload on stdout and a non-zero exit on failure.

- [x] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_validate_design_tokens.py`:

```python
"""Tests for the design-token validator CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parents[2]
_SCRIPT = _SKILL_DIR / "scripts" / "validate_design_tokens.py"
_DEFAULT_TOKENS = _SKILL_DIR / "references" / "tokens" / "default.tokens.yaml"


def test_cli_accepts_default_tokens() -> None:
    """The shipped default token file validates and exits zero."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--tokens", str(_DEFAULT_TOKENS), "--json"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["valid"] is True


def test_cli_rejects_invalid_tokens(tmp_path: Path) -> None:
    """A token file below the typography floor exits non-zero with an error."""
    bad = tmp_path / "bad.tokens.yaml"
    bad.write_text(
        _DEFAULT_TOKENS.read_text(encoding="utf-8").replace("size: 21", "size: 9"),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--tokens", str(bad), "--json"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["valid"] is False
    assert payload["errors"]


def test_validate_token_file_returns_errors(tmp_path: Path) -> None:
    """The importable helper returns errors rather than raising."""
    from validate_design_tokens import validate_token_file

    assert validate_token_file(_DEFAULT_TOKENS) == []
    missing = tmp_path / "nope.yaml"
    errors = validate_token_file(missing)
    assert len(errors) == 1
    assert "nope.yaml" in errors[0]
```

- [x] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_validate_design_tokens.py -v`
Expected: FAIL — the subprocess exits 2 with `can't open file ... validate_design_tokens.py`, and the third test fails on `ModuleNotFoundError`.

- [x] **Step 3: Write the CLI**

Create `skills/report-slides/scripts/validate_design_tokens.py`:

```python
#!/usr/bin/env python3
"""Validate a report-slides design-token file against the token schema."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from design_tokens import DesignTokens, TokenError


def validate_token_file(path: Path) -> list[str]:
    """Validate one token file.

    Args:
        path: Path to a `.tokens.yaml` file.

    Returns:
        A list of human-readable errors; empty when the file is valid.
    """
    try:
        DesignTokens.load(path)
    except TokenError as exc:
        return [str(exc)]
    return []


def main() -> None:
    """Run token validation and exit non-zero on any error."""
    parser = argparse.ArgumentParser(
        description="Validate a report-slides design-token file."
    )
    parser.add_argument("--tokens", metavar="PATH", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    errors = validate_token_file(args.tokens)
    result = {"valid": not errors, "errors": errors}
    print(json.dumps(result) if args.json else json.dumps(result, indent=2))
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_validate_design_tokens.py -v`
Expected: PASS — 3 passed.

- [x] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/validate_design_tokens.py \
        skills/report-slides/scripts/tests/test_validate_design_tokens.py
git commit -m "feat(report-slides): add design-token validator CLI"
```

---

### Task 4: Make `style_tokens_ref` mandatory and resolvable

**Files:**
- Modify: `skills/report-slides/scripts/validate_visual_module.py` (`_validate_style_tokens_ref`, lines 285–294; add `validate_style_tokens_resolvable`)
- Modify: `skills/report-slides/scripts/presentation_gates.py:413`
- Modify: `skills/report-slides/scripts/publish_presentation_artifact.py:417`
- Modify: `skills/report-slides/scripts/validate_visual_module.py:348` (`main`)
- Test: `skills/report-slides/scripts/tests/test_style_tokens_ref_enforcement.py`

**Interfaces:**
- Consumes: `validate_design_tokens.validate_token_file` (Task 3);
  `design_tokens.DesignTokens` (Task 2).
- Produces, exported from `validate_visual_module`:
  - `validate_style_tokens_resolvable(doc: Any, base_dir: Path) -> list[str]`
  - `resolved_token_digest(doc: Any, base_dir: Path) -> str` — the digest of the
    token set the module is held to, for the caller to persist

**Provenance.** A module spec that records only "`style_tokens_ref` resolved" is
recording that some file was fine at some past moment. It does not say which
file, so nothing downstream can tell whether the tokens changed after the module
was produced — and that is precisely the question Task 14's lint evidence has to
answer, and the question a stale-evidence check is made of. `main` therefore
prints the digest alongside the validation result, and the caller that writes the
module spec persists it beside `style_tokens_ref`:

```python
def resolved_token_digest(doc: Any, base_dir: Path) -> str:
    """Return the digest of the token set a module spec resolves to.

    Args:
        doc: A module or complex-visual specification mapping.
        base_dir: Directory the spec's relative paths resolve against.

    Returns:
        The `DesignTokens.digest` of the resolved file.

    Raises:
        TokenError: If the reference does not resolve or does not validate.
            Callers must not substitute a default: a module validated against
            the wrong token set is worse than one validated against none, since
            the record then asserts something false.
    """
    return DesignTokens.load(
        (base_dir / str(doc["style_tokens_ref"])).resolve()).digest
```

Once plan 1 Task 16 lands, the path a deck's `style_tokens_ref` points at is the
composed `_effective.tokens.yaml`, so this digest is the digest of the tokens the
slide was actually drawn with — not of the base file before its style override.

**Background:** `docs/superpowers/specs/2026-08-06-report-slides-multiagent-design.md:108`
records this as a known deferred gap — "it does not validate `style_tokens_ref` …
Tightening this … is deferred to Phase B or a hardening pass." Presence is now
checked; resolution never was. This task closes it.

**Design note — why two functions rather than threading `base_dir`:**
`validate_module_spec`, `validate_complex_visual_spec`, and
`validate_worker_assignment` are called from `presentation_gates.py`,
`publish_presentation_artifact.py`, `presentation_module_lineage.py`, and five
places in `test_validate_visual_module.py`. Adding a required `base_dir`
parameter to them would churn every call site. Instead the *syntactic* rule
(non-null string) tightens in place, and the *filesystem* rule lands in a new
function that only callers holding the document's path invoke.

- [x] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_style_tokens_ref_enforcement.py`:

```python
"""Tests that ModuleSpec style_tokens_ref is mandatory and resolvable."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from validate_visual_module import (
    validate_module_spec,
    validate_style_tokens_resolvable,
)

_SKILL_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_TOKENS = _SKILL_DIR / "references" / "tokens" / "default.tokens.yaml"


def _module(style_tokens_ref: object) -> dict:
    """Build a minimal ModuleSpec carrying the given style_tokens_ref."""
    return {
        "module_id": "m1",
        "module_type": "architecture",
        "purpose": "test",
        "authoring_route": "native",
        "editability": "native",
        "style_tokens_ref": style_tokens_ref,
        "annotation_requirements": [],
        "dimensions": {"width": 1200, "height": 675},
        "input_anchors": [],
        "output_anchors": [],
        "dependencies": [],
        "reuse_of": None,
    }


def test_null_style_tokens_ref_is_rejected() -> None:
    """A null style_tokens_ref is no longer an accepted value."""
    errors = validate_module_spec(_module(None), 0)
    assert any("style_tokens_ref" in error for error in errors)


def test_empty_style_tokens_ref_is_rejected() -> None:
    """An empty or whitespace-only reference is rejected."""
    errors = validate_module_spec(_module("   "), 0)
    assert any("style_tokens_ref" in error for error in errors)


def test_valid_reference_passes_syntactic_check() -> None:
    """A non-empty string reference passes the syntactic check."""
    errors = validate_module_spec(_module("tokens/default.tokens.yaml"), 0)
    assert not any("style_tokens_ref" in error for error in errors)


def test_resolvable_check_accepts_present_token_file(tmp_path: Path) -> None:
    """A reference resolving to a valid token file yields no errors."""
    shutil.copy(_DEFAULT_TOKENS, tmp_path / "deck.tokens.yaml")
    doc = {"modules": [_module("deck.tokens.yaml")]}
    assert validate_style_tokens_resolvable(doc, tmp_path) == []


def test_resolvable_check_rejects_missing_token_file(tmp_path: Path) -> None:
    """A reference pointing at nothing is a hard error, not a fallback."""
    doc = {"modules": [_module("absent.tokens.yaml")]}
    errors = validate_style_tokens_resolvable(doc, tmp_path)
    assert len(errors) == 1
    assert "absent.tokens.yaml" in errors[0]


def test_resolvable_check_rejects_invalid_token_file(tmp_path: Path) -> None:
    """A reference to a schema-invalid token file is a hard error."""
    bad = tmp_path / "deck.tokens.yaml"
    bad.write_text(
        _DEFAULT_TOKENS.read_text(encoding="utf-8").replace("size: 21", "size: 9"),
        encoding="utf-8",
    )
    doc = {"modules": [_module("deck.tokens.yaml")]}
    errors = validate_style_tokens_resolvable(doc, tmp_path)
    assert len(errors) == 1
    assert "typography" in errors[0]


def test_resolvable_check_rejects_escape_from_base_dir(tmp_path: Path) -> None:
    """A reference must not escape the document's directory."""
    doc = {"modules": [_module("../outside.tokens.yaml")]}
    errors = validate_style_tokens_resolvable(doc, tmp_path)
    assert len(errors) == 1
    assert "outside" in errors[0]
```

- [x] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_style_tokens_ref_enforcement.py -v`
Expected: FAIL — `ImportError: cannot import name 'validate_style_tokens_resolvable'`.

- [x] **Step 3: Tighten the syntactic rule**

In `skills/report-slides/scripts/validate_visual_module.py`, replace
`_validate_style_tokens_ref` (lines 285–294) with:

```python
def _validate_style_tokens_ref(
    module: dict[str, Any], prefix: str, errors: list[str]
) -> None:
    """Require a non-empty design-token path.

    `null` is no longer accepted. An unresolved style reference is
    indistinguishable from a correctly applied style at render time, so the
    reference must always name a token file. Whether that file exists and
    validates is checked separately by `validate_style_tokens_resolvable`,
    which needs the document's directory.

    Args:
        module: Parsed ModuleSpec mapping.
        prefix: Error-message prefix identifying the module position.
        errors: Accumulator appended to in place.
    """
    if "style_tokens_ref" not in module:
        errors.append(f"{prefix}.style_tokens_ref: required non-empty string")
        return
    value = module["style_tokens_ref"]
    if not isinstance(value, str) or not value.strip():
        errors.append(
            f"{prefix}.style_tokens_ref: must be a non-empty string "
            f"naming a design-token file, got {value!r}"
        )
```

- [x] **Step 4: Add the resolution check**

Append to `skills/report-slides/scripts/validate_visual_module.py`, above `main()`:

```python
def validate_style_tokens_resolvable(doc: Any, base_dir: Path) -> list[str]:
    """Check that every module's style_tokens_ref resolves to valid tokens.

    Args:
        doc: Parsed Complex Visual Specification mapping.
        base_dir: Directory the specification was loaded from; references
            resolve relative to it and may not escape it.

    Returns:
        Deterministically ordered human-readable validation errors.
    """
    from validate_design_tokens import validate_token_file

    errors: list[str] = []
    modules = doc.get("modules") if isinstance(doc, dict) else None
    if not isinstance(modules, list):
        return errors
    resolved_base = base_dir.resolve()
    for index, module in enumerate(modules):
        if not isinstance(module, dict):
            continue
        ref = module.get("style_tokens_ref")
        if not isinstance(ref, str) or not ref.strip():
            continue  # already reported by _validate_style_tokens_ref
        prefix = f"modules[{index}].style_tokens_ref"
        candidate = (resolved_base / ref.strip()).resolve()
        try:
            candidate.relative_to(resolved_base)
        except ValueError:
            errors.append(
                f"{prefix}: {ref!r} resolves outside the specification directory"
            )
            continue
        for error in validate_token_file(candidate):
            errors.append(f"{prefix}: {error}")
    return errors
```

- [x] **Step 5: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_style_tokens_ref_enforcement.py -v`
Expected: PASS — 7 passed.

- [x] **Step 6: Wire the check into the three callers that hold a path**

In `skills/report-slides/scripts/validate_visual_module.py`, in `main()`, replace
the `errors = validate_complex_visual_spec(...)` line (line 348) with:

```python
        if args.spec:
            errors = validate_complex_visual_spec(document)
            errors.extend(validate_style_tokens_resolvable(document, target.parent))
        else:
            errors = validate_worker_assignment(document)
```

In `skills/report-slides/scripts/presentation_gates.py`, after line 413's
`validate_complex_visual_spec(spec_document)` block, add the resolution check
using the same spec path that block already holds. In
`skills/report-slides/scripts/publish_presentation_artifact.py`, do the same after
line 417. Read the surrounding lines in each file to find the local variable
holding the specification path, and pass its `.parent`.

- [x] **Step 7: Run the full existing suite to catch regressions**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/tests/ -q`
Expected: PASS. If existing fixtures set `style_tokens_ref: null`, they are now
invalid by design — update each fixture to name a real token file. Do not relax
the new rule to accommodate a fixture; state in the commit message which fixtures
changed and why the old expectation was wrong.

- [x] **Step 8: Commit**

```bash
git add skills/report-slides/scripts/validate_visual_module.py \
        skills/report-slides/scripts/presentation_gates.py \
        skills/report-slides/scripts/publish_presentation_artifact.py \
        skills/report-slides/scripts/tests/
git commit -m "feat(report-slides): require and resolve ModuleSpec style_tokens_ref"
```

---

### Task 5: Font stack resolution and metrics

**Files:**
- Create: `skills/report-slides/scripts/fonts.py`
- Test: `skills/report-slides/scripts/tests/test_fonts.py`

**Interfaces:**
- Consumes: `fc-match`/`fc-list` (fontconfig), Pillow's `ImageFont`.
- Produces, imported by Tasks 6, 8, and 15:
  - `class FontError(RuntimeError)`
  - `parse_font_stack(css_family: str) -> list[str]`
  - `is_family_available(family: str) -> bool`
  - `resolve_font_stack(css_family: str) -> str` — first installed family, or
    raises `FontError` when none is installed
  - `FC_WEIGHT_NAMES: Dict[int, str]` — CSS numeric weight to the fontconfig
    weight constant that selects the matching face
  - `font_file_for(family: str, weight: int = 400) -> Path`
  - `text_width(text: str, family: str, size: float, weight: int = 400) -> float`
  - `vertical_metrics(family: str, size: float, weight: int = 400)
    -> Tuple[float, float]` — measured `(ascent, descent)` in SVG units.
    `generate_slides.frame` uses it to keep the footer's descenders inside the
    safe area, and plan 2's `TextRun.bbox` uses it so the linter models the same
    box the renderer drew.

**Why this exists:** `svg_to_pptx/shapes.py:217-220` sets
`run.font.name` to the first *listed* family, so `'Helvetica Neue', Arial,
sans-serif` becomes `Helvetica` — a face installed on neither Linux nor the
default token stack. Picking the first *installed* family instead makes the SVG
preview and the PPTX export agree. Task 15's typography rules also need real
glyph advance widths; character-count estimates are not accurate enough to judge
overflow. `svg_to_pptx/text_converter.py:15` currently approximates with
`_CHAR_W_FACTOR = 0.65`.

**Environment note:** on the development machine `fc-match "Inter"` resolves to
`DejaVu Sans`, i.e. Inter is *not* installed, while `Liberation Sans` resolves to
itself. The default token stack lists `Inter` first precisely so this code path is
exercised: `resolve_font_stack` must skip Inter and return `DejaVu Sans`.

- [x] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_fonts.py`:

```python
"""Tests for font stack resolution and text metrics."""

from __future__ import annotations

import shutil

import pytest

from fonts import (
    FontError,
    font_file_for,
    is_family_available,
    parse_font_stack,
    resolve_font_stack,
    text_width,
    vertical_metrics,
)

# Requires fontconfig; the whole module is meaningless without it.
pytestmark = pytest.mark.skipif(
    shutil.which("fc-match") is None,
    reason="fontconfig (fc-match) is not installed",
)


def test_parse_font_stack_preserves_multi_word_families() -> None:
    """Multi-word quoted families survive parsing intact."""
    stack = parse_font_stack("'Helvetica Neue', Arial, sans-serif")
    assert stack == ["Helvetica Neue", "Arial", "sans-serif"]


def test_parse_font_stack_handles_double_quotes_and_spacing() -> None:
    """Double-quoted names and irregular spacing parse correctly."""
    stack = parse_font_stack('Inter ,  "DejaVu Sans Mono" , monospace')
    assert stack == ["Inter", "DejaVu Sans Mono", "monospace"]


def test_dejavu_sans_is_available() -> None:
    """DejaVu Sans ships with essentially every Linux image."""
    assert is_family_available("DejaVu Sans") is True


def test_absent_family_is_not_available() -> None:
    """A nonsense family name is reported unavailable, not silently substituted."""
    assert is_family_available("Totally Not A Real Font 9x7") is False


def test_resolve_skips_uninstalled_first_choice() -> None:
    """Resolution returns the first installed family, not the first listed."""
    resolved = resolve_font_stack(
        "Totally Not A Real Font 9x7, 'DejaVu Sans', sans-serif"
    )
    assert resolved == "DejaVu Sans"


def test_resolve_raises_when_nothing_is_installed() -> None:
    """A stack with no installed family raises instead of guessing."""
    with pytest.raises(FontError) as excinfo:
        resolve_font_stack("Nope One 9x7, 'Nope Two 9x7'")
    assert "Nope One 9x7" in str(excinfo.value)


def test_generic_keyword_alone_raises() -> None:
    """A stack of only CSS generic keywords cannot be resolved to a face."""
    with pytest.raises(FontError):
        resolve_font_stack("sans-serif")


def test_text_width_scales_with_size_and_length() -> None:
    """Measured width grows with both font size and string length."""
    narrow = text_width("Model", "DejaVu Sans", 18)
    wide = text_width("Model", "DejaVu Sans", 36)
    longer = text_width("Model architecture", "DejaVu Sans", 18)
    assert wide > narrow > 0
    assert longer > narrow
    assert 1.8 < wide / narrow < 2.2


def test_bold_is_measured_with_the_bold_face() -> None:
    """A weight that selects a different face must measure differently.

    `text_width` accepted a `weight` argument and threw it away, so every one of
    the four token roles at weight 600 or 700 -- `deck_title`, `slide_title`,
    `takeaway`, `node_label` -- was measured with the regular face. On this
    machine that under-measures by 12.9%, which is roughly one character in
    eight: enough to decide whether a title fits on two lines.

    The assertion is an inequality rather than a number because face metrics are
    a property of the installed font, not of this code.
    """
    family = resolve_font_stack("DejaVu Sans, sans-serif")
    text = "Token contract and enforcement"
    regular = text_width(text, family, 32, weight=400)
    bold = text_width(text, family, 32, weight=700)
    assert bold > regular, (
        f"weight is being ignored: {family} measures {bold} at 700 and "
        f"{regular} at 400"
    )


def test_a_weight_between_the_css_steps_still_resolves() -> None:
    """An unusual but schema-legal weight rounds rather than raising."""
    family = resolve_font_stack("DejaVu Sans, sans-serif")
    assert font_file_for(family, 650) == font_file_for(family, 700)


def test_vertical_metrics_are_measured_not_assumed() -> None:
    """Ascent is near a full em and descent is non-zero, unlike the 0.8/0 guess.

    The exact values are DejaVu Sans on the reference image; assert them so a
    font update that shifts every text extent is noticed, not absorbed.
    """
    assert vertical_metrics("DejaVu Sans", 32) == (30.0, 8.0)
    assert vertical_metrics("DejaVu Sans", 12) == (12.0, 3.0)


def test_vertical_metrics_scale_with_size() -> None:
    """A larger size reserves more space above and below the baseline."""
    small_ascent, small_descent = vertical_metrics("DejaVu Sans", 12)
    large_ascent, large_descent = vertical_metrics("DejaVu Sans", 36)
    assert large_ascent > small_ascent
    assert large_descent > small_descent


def test_vertical_metrics_reject_unavailable_family() -> None:
    """An uninstalled family is an error, not a silently substituted face."""
    with pytest.raises(FontError):
        vertical_metrics("Nonexistent Face 12345", 20)


def test_text_width_rejects_unavailable_family() -> None:
    """Measuring with an uninstalled family raises rather than approximating."""
    with pytest.raises(FontError):
        text_width("Model", "Totally Not A Real Font 9x7", 18)
```

- [x] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_fonts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fonts'` at collection.

- [x] **Step 3: Write the module**

Create `skills/report-slides/scripts/fonts.py`:

```python
"""Font stack resolution and text metrics for report-slides.

Two jobs. First, pick the font family that is actually installed, so the SVG
preview and the PPTX export render with the same face. Second, measure real
glyph advance widths, so overflow checks do not rely on character counts.
"""
from __future__ import annotations

import functools
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import ImageFont

_GENERIC_FAMILIES = frozenset(
    {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui"}
)
_FC_TIMEOUT_SECONDS = 15


class FontError(RuntimeError):
    """Raised when no requested font family is installed, or metrics fail.

    Never caught in order to fall back to an arbitrary face: a substituted font
    changes every text extent on the slide, so the caller must be told.
    """


def parse_font_stack(css_family: str) -> List[str]:
    """Split a CSS `font-family` value into ordered family names.

    Multi-word names keep their spaces; surrounding quotes are stripped. This is
    the behaviour `svg_to_pptx/shapes.py` lacked, where splitting on whitespace
    turned `'Helvetica Neue'` into `Helvetica`.

    Args:
        css_family: A CSS `font-family` value.

    Returns:
        Family names in declaration order, including generic keywords.
    """
    families: List[str] = []
    for part in css_family.split(","):
        name = part.strip().strip("'\"").strip()
        name = re.sub(r"\s+", " ", name)
        if name:
            families.append(name)
    return families


@functools.lru_cache(maxsize=256)
def is_family_available(family: str) -> bool:
    """Return whether fontconfig resolves a family to itself.

    `fc-match` always returns some face, so availability is determined by
    comparing the resolved family against the requested one.

    Args:
        family: A concrete family name, not a CSS generic keyword.

    Returns:
        True when the family is installed.

    Raises:
        FontError: If fontconfig is unavailable or fails to run.
    """
    if family.lower() in _GENERIC_FAMILIES:
        return False
    if shutil.which("fc-match") is None:
        raise FontError("fontconfig (fc-match) is required to resolve font families")
    try:
        result = subprocess.run(
            ["fc-match", "--format=%{family}", family],
            capture_output=True, text=True, timeout=_FC_TIMEOUT_SECONDS, check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise FontError(f"fc-match failed for {family!r}: {exc}") from exc
    resolved = {alias.strip().lower() for alias in result.stdout.split(",")}
    return family.strip().lower() in resolved


def resolve_font_stack(css_family: str) -> str:
    """Return the first installed family in a CSS font stack.

    Args:
        css_family: A CSS `font-family` value.

    Returns:
        The first family name in the stack that is installed.

    Raises:
        FontError: If no concrete family in the stack is installed.
    """
    families = parse_font_stack(css_family)
    for family in families:
        if is_family_available(family):
            return family
    raise FontError(
        f"no installed font family in stack {css_family!r}; "
        f"tried {families}. Install one of them or change the token font stack."
    )


# fontconfig has its own weight scale and does not accept CSS numbers. Without
# this map every weight resolves to the same face, and a bold title is measured
# with the regular one -- on this machine that under-measures by 12.9%, which is
# the difference between a title that fits on two lines and one that does not.
FC_WEIGHT_NAMES: Dict[int, str] = {
    100: "thin", 200: "extralight", 300: "light", 400: "regular",
    500: "medium", 600: "demibold", 700: "bold", 800: "extrabold",
    900: "black",
}


def _fc_weight(weight: int) -> str:
    """Return the fontconfig weight constant nearest a CSS numeric weight.

    Args:
        weight: A CSS numeric font weight.

    Returns:
        The fontconfig weight constant, e.g. `bold` for 700. Values between the
        nine CSS steps round to the nearest step rather than raising: a token
        file is validated against the 100-900 range by the schema, and an
        unusual-but-legal 650 should resolve to a face, not fail the render.
    """
    return FC_WEIGHT_NAMES[min(FC_WEIGHT_NAMES, key=lambda step: abs(step - weight))]


@functools.lru_cache(maxsize=256)
def font_file_for(family: str, weight: int = 400) -> Path:
    """Return the font file backing a family at a weight.

    Args:
        family: A concrete, installed family name.
        weight: CSS numeric font weight. Cached as part of the key, so regular
            and bold never share an entry.

    Returns:
        Path to the font file.

    Raises:
        FontError: If the family is not installed or has no file.
    """
    if not is_family_available(family):
        raise FontError(f"font family {family!r} is not installed")
    try:
        result = subprocess.run(
            ["fc-match", "--format=%{file}", f"{family}:weight={_fc_weight(weight)}"],
            capture_output=True, text=True, timeout=_FC_TIMEOUT_SECONDS, check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise FontError(f"fc-match failed for {family!r}: {exc}") from exc
    path = Path(result.stdout.strip())
    if not path.is_file():
        raise FontError(f"font family {family!r} resolved to missing file {path}")
    return path


def text_width(text: str, family: str, size: float, weight: int = 400) -> float:
    """Measure the advance width of a string in SVG units.

    Args:
        text: The string to measure.
        family: A concrete, installed family name.
        size: Font size in SVG units, which map 1:1 to PowerPoint points.
        weight: CSS numeric weight. Selects the concrete face, because a bold
            face is materially wider than its regular sibling and measuring one
            with the other is how a title silently overflows.

    Returns:
        The advance width in SVG units.

    Raises:
        FontError: If the family is not installed or the face cannot be loaded.
    """
    return float(_face(family, size, weight).getlength(text))


def vertical_metrics(
    family: str, size: float, weight: int = 400
) -> Tuple[float, float]:
    """Measure a face's ascent and descent in SVG units.

    These are the face's own design metrics, not the ink extent of a particular
    string: they are what a renderer must reserve above and below a baseline for
    *any* text at this size, which is what a safe-area or overlap check needs.

    They are measured rather than assumed because the assumption is wrong. A
    common guess is 0.8 em of ascent and no descent; DejaVu Sans actually
    reports ascent 30 / descent 8 at size 32, and ascent 12 / descent 3 at
    size 12. A footer baseline placed on the safe-area boundary therefore hangs
    three units outside it.

    Args:
        family: A concrete, installed family name.
        size: Font size in SVG units, which map 1:1 to PowerPoint points.
        weight: CSS numeric font weight. A bold face can carry a taller ascent
            than its regular sibling; on this machine DejaVu Sans does not, but
            that is a property of one family and not a rule.

    Returns:
        `(ascent, descent)`, both positive, in SVG units. `ascent` is the
        distance from the baseline to the top of the em box; `descent` the
        distance from the baseline down to its bottom.

    Raises:
        FontError: If the family is not installed or the face cannot be loaded.
    """
    ascent, descent = _face(family, size, weight).getmetrics()
    return float(ascent), float(descent)


def _face(family: str, size: float, weight: int = 400) -> "ImageFont.FreeTypeFont":
    """Load a Pillow face for a family at a size and weight.

    Args:
        family: A concrete, installed family name.
        size: Font size in SVG units.
        weight: CSS numeric font weight.

    Returns:
        The loaded face.

    Raises:
        FontError: If the family is not installed or the face cannot be loaded.
    """
    font_path = font_file_for(family, weight)
    try:
        return ImageFont.truetype(str(font_path), size=max(1, int(round(size))))
    except OSError as exc:
        raise FontError(
            f"cannot load face {font_path} for {family!r} at size {size}: {exc}"
        ) from exc
```

- [x] **Step 4: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_fonts.py -v`
Expected: PASS — 14 passed.

- [x] **Step 5: Verify the default token stack resolves on this machine**

Run:

```bash
timeout 60 python3 -c "
import sys; sys.path.insert(0, 'skills/report-slides/scripts')
from design_tokens import DesignTokens, DEFAULT_TOKENS_PATH
from fonts import resolve_font_stack
t = DesignTokens.load(DEFAULT_TOKENS_PATH)
for key in ('sans', 'mono'):
    print(key, '->', resolve_font_stack(t.font_stack(key)))
"
```

Expected: both keys print an installed family. On a machine without Inter this
prints `sans -> DejaVu Sans`. If either raises `FontError`, add the missing family
to the token stack rather than weakening `resolve_font_stack`.

- [x] **Step 6: Commit**

```bash
git add skills/report-slides/scripts/fonts.py \
        skills/report-slides/scripts/tests/test_fonts.py
git commit -m "feat(report-slides): resolve font stacks to installed faces and measure real text extents"
```

---

## Phase 2: Presentation-Scale Typography

---

### Task 6: Token plumbing and the slide frame

**Files:**
- Modify: `skills/report-slides/scripts/generate_slides.py` (`S` dict lines 24–40; `apply_style` lines 69–94; `frame` lines 133–146; `svg` lines 148–152; argparse line 854; `main` line 877)
- Test: `skills/report-slides/scripts/tests/test_generate_slides_typography.py`

**Interfaces:**
- Consumes: `design_tokens.DesignTokens`, `design_tokens.DEFAULT_TOKENS_PATH`,
  `design_tokens.TokenError` (Task 2); `fonts.resolve_font_stack` (Task 5).
- Produces, used by Tasks 7–9:
  - `apply_tokens(tokens_path: Optional[Path]) -> None` — loads tokens into the
    module-level `S` and `TYPE` mappings
  - `TYPE: Dict[str, TypeRole]` — resolved type roles, keyed by role name
  - `t_size(role: str) -> float`, `t_weight(role: str) -> int`,
    `t_lh(role: str) -> float`
  - `frame(title: str, footer: str = "", *, variant: str = "left") -> str`
  - `S["font_resolved"]` — the installed family name
  - The marker contract every renderer must honour, and which plan 2's linter
    reads: every `<text>` carries `data-style-role="<typography role>"`; every
    element that intentionally runs past the safe area carries
    `data-bleed="true"`; node groups carry `data-node-id`; connectors carry
    `data-from`/`data-to`. Without these, plan 2's rules do not fire — they skip
    the element and report clean, which is indistinguishable from passing. Task 9
    Step 8 enforces the `<text>` half mechanically.

**What changes and why:** `frame()` (line 140) hard-codes a 20pt centred title at
`y=44` with a full-width hairline at `y=54` and a 10pt footer at `y=660`. Spec
§2.2 and §2.8 record both defects: the size is document scale, and the arrangement
is the "generated deck" signature. `apply_style` (line 69) additionally returns
silently when frontmatter parses empty, so a typo in a style file is
indistinguishable from success — spec §2.15.

- [x] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_generate_slides_typography.py`:

```python
"""Tests that the deterministic renderer typesets at presentation scale."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import generate_slides as gs
from design_tokens import TokenError

_SKILL_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_TOKENS = _SKILL_DIR / "references" / "tokens" / "default.tokens.yaml"
_FONT_SIZE_RE = re.compile(r'font-size="([0-9.]+)"')


@pytest.fixture(autouse=True)
def _tokens_applied() -> None:
    """Apply the default token file before each test."""
    gs.apply_tokens(_DEFAULT_TOKENS)


def test_apply_tokens_populates_type_roles() -> None:
    """Type roles become available with presentation-scale sizes."""
    assert gs.t_size("slide_title") == 32
    assert gs.t_size("body") == 21
    assert gs.t_size("footnote") == 12
    assert gs.t_weight("slide_title") == 700


def test_apply_tokens_resolves_an_installed_font() -> None:
    """The resolved font family is one that is actually installed."""
    assert gs.S["font_resolved"]
    assert "sans-serif" not in gs.S["font_resolved"]


def test_frame_title_is_at_presentation_scale() -> None:
    """The slide title uses the slide_title role, not a 20pt literal."""
    markup = gs.frame("Experiment Overview", footer="deck 1/8")
    sizes = {float(m) for m in _FONT_SIZE_RE.findall(markup)}
    assert 32 in sizes
    assert 20 not in sizes


def test_frame_footer_is_not_below_the_footnote_floor() -> None:
    """No text in the frame falls below the footnote floor of 12."""
    markup = gs.frame("Experiment Overview", footer="deck 1/8")
    sizes = [float(m) for m in _FONT_SIZE_RE.findall(markup)]
    assert sizes
    assert min(sizes) >= 12


def test_frame_left_variant_is_not_centred() -> None:
    """The default frame variant left-aligns the title inside the safe area."""
    markup = gs.frame("Experiment Overview")
    assert 'text-anchor="middle"' not in markup
    assert 'x="48"' in markup


def test_frame_centered_variant_is_available() -> None:
    """A centred variant remains available for section dividers."""
    markup = gs.frame("Part II", variant="centered")
    assert 'text-anchor="middle"' in markup


def test_frame_rejects_unknown_variant() -> None:
    """An unknown frame variant raises rather than silently picking a default."""
    with pytest.raises(ValueError):
        gs.frame("Experiment Overview", variant="diagonal")


def test_apply_tokens_defaults_to_shipped_contract() -> None:
    """Passing None loads the shipped default token file."""
    gs.apply_tokens(None)
    assert gs.t_size("body") == 21


def test_apply_tokens_raises_on_invalid_file(tmp_path: Path) -> None:
    """An invalid token file raises instead of leaving built-in defaults."""
    bad = tmp_path / "bad.tokens.yaml"
    bad.write_text(
        _DEFAULT_TOKENS.read_text(encoding="utf-8").replace("size: 21", "size: 9"),
        encoding="utf-8",
    )
    with pytest.raises(TokenError):
        gs.apply_tokens(bad)


def test_apply_style_raises_on_unparsable_frontmatter(tmp_path: Path) -> None:
    """A style file with no usable frontmatter is an error, not a no-op."""
    broken = tmp_path / "broken.md"
    broken.write_text("no frontmatter here\n", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        gs.apply_style(str(broken))
    assert "broken.md" in str(excinfo.value)
```

- [x] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_generate_slides_typography.py -v`
Expected: FAIL — `AttributeError: module 'generate_slides' has no attribute 'apply_tokens'`.

- [x] **Step 3: Add token plumbing**

In `skills/report-slides/scripts/generate_slides.py`, immediately after the `S`
dict (line 40), add:

```python
TYPE: Dict[str, TypeRole] = {}
_TOKENS: Optional[DesignTokens] = None


def apply_tokens(tokens_path: Optional[Path]) -> None:
    """Load a design-token file into the module-level style state.

    Args:
        tokens_path: Path to a `.tokens.yaml` file, or None for the shipped
            default contract.

    Raises:
        TokenError: If the token file is missing or schema-invalid.
        FontError: If no family in the token font stack is installed.
    """
    global _TOKENS
    _TOKENS = DesignTokens.load(tokens_path or DEFAULT_TOKENS_PATH)
    TYPE.clear()
    for role in _TOKENS.raw["typography"]["roles"]:
        TYPE[role] = _TOKENS.type_role(role)
    S["w"] = _TOKENS.raw["canvas"]["width"]
    S["h"] = _TOKENS.raw["canvas"]["height"]
    S["grid"] = _TOKENS.raw["canvas"]["grid"]
    S["safe"] = dict(_TOKENS.raw["canvas"]["safe_area"])
    for role in ("bg", "body", "muted", "card", "primary",
                 "positive", "warn", "danger", "line", "divider"):
        S[role] = _TOKENS.color(role)
    # Legacy key names still referenced by the renderers.
    S["accent"] = _TOKENS.color("primary")
    S["good"] = _TOKENS.color("positive")
    S["border"] = _TOKENS.color("divider")
    S["blue"] = _TOKENS.raw["chart"]["palette"][0]
    S["white"] = "#ffffff"
    S["font"] = _TOKENS.font_stack("sans")
    S["font_resolved"] = resolve_font_stack(S["font"])
    S["top_bar_h"] = 0


def _role(role: str) -> TypeRole:
    """Return one resolved type role.

    Args:
        role: Role key such as `body`.

    Returns:
        The resolved `TypeRole`.

    Raises:
        RuntimeError: If `apply_tokens` has not been called.
        TokenError: If the role is undefined.
    """
    if not TYPE:
        raise RuntimeError(
            "apply_tokens() must be called before rendering; "
            "type roles are not loaded"
        )
    if role not in TYPE:
        raise TokenError(
            f"undefined type role {role!r}; defined roles: {sorted(TYPE)}"
        )
    return TYPE[role]


def t_size(role: str) -> float:
    """Return the font size for a type role."""
    return _role(role).size


def t_weight(role: str) -> int:
    """Return the numeric font weight for a type role."""
    return _role(role).weight


def t_lh(role: str) -> float:
    """Return the line-height multiplier for a type role."""
    return _role(role).line_height
```

Add these imports at the top of the file, beside the existing ones:

```python
from typing import Dict, Optional

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens, TokenError, TypeRole
from fonts import resolve_font_stack, vertical_metrics
```

- [x] **Step 4: Make `apply_style` fail loudly**

Replace the early return in `apply_style` (line 72) so an unusable style file is
an error. Keep the rest of the function, and map `primary` onto both `primary` and
the legacy `accent` key:

```python
def apply_style(style_path: str) -> None:
    """Load a style .md file and override colour keys in the global S dict.

    Style Markdown remains a colour override for backwards compatibility; sizes
    and spacing come from the token contract. An unparsable or empty style file
    raises: a silently ignored style is indistinguishable from an applied one.

    Args:
        style_path: Path to a style `.md` file with YAML frontmatter.

    Raises:
        ValueError: If the file has no usable frontmatter keys.
    """
    fm = _parse_frontmatter(style_path)
    if not fm:
        raise ValueError(
            f"style file {style_path} has no usable YAML frontmatter; "
            f"expected keys such as primary/bg/body (see references/styles/STYLES.md)"
        )
    key_map = {
        "primary":  "accent",
        "bg":       "bg",
        "body":     "body",
        "muted":    "muted",
        "border":   "border",
        "card":     "card",
        "positive": "good",
        "warn":     "warn",
        "danger":   "danger",
        "font":     "font",
    }
    for style_key, s_key in key_map.items():
        if style_key in fm:
            S[s_key] = fm[style_key]
    if "primary" in fm:
        S["primary"] = fm["primary"]
    if "font" in fm:
        S["font_resolved"] = resolve_font_stack(fm["font"])
    print(f"  [style] Applied: {style_path}")
```

Note that `top_bar_h` is deliberately no longer read from style frontmatter: the
top accent bar is removed in Step 5. Delete the `if "top_bar_h" in fm:` block
(lines 89–93).

- [x] **Step 5: Rebuild `frame()` from tokens**

Replace `frame()` (lines 133–146) with:

```python
_FRAME_VARIANTS = ("left", "centered")


def frame(title: str, footer: str = "", *, variant: str = "left") -> str:
    """Render the shared slide frame: title, rule, and footer.

    The former 6px top accent bar and centred 20pt title are gone. The title now
    uses the `slide_title` role inside the token safe area, and the rule sits
    under the title's baseline rather than at a fixed y=54.

    Args:
        title: Slide title text.
        footer: Optional footer text, rendered at the `footnote` role.
        variant: `left` for the standard left-aligned title, `centered` for
            section dividers.

    Returns:
        SVG markup for the frame elements.

    Raises:
        ValueError: If `variant` is not a known frame variant.
    """
    if variant not in _FRAME_VARIANTS:
        raise ValueError(
            f"unknown frame variant {variant!r}; expected one of {_FRAME_VARIANTS}"
        )
    safe = S["safe"]
    size = t_size("slide_title")
    # `size` is used here, not the measured ascent, because three later tasks
    # place their content against `rule_y = safe.top + slide_title + 16`. It is
    # a conservative proxy: DejaVu Sans reports ascent 30 at size 32, so the
    # title's em box starts 2 units *inside* the safe area. Task 6's test pins
    # that, so a font whose ascent exceeds its em size fails loudly rather than
    # clipping silently.
    baseline = safe["top"] + size
    rule_y = baseline + 16
    x = S["w"] / 2 if variant == "centered" else safe["left"]
    anchor = "middle" if variant == "centered" else "start"

    parts = [
        f'<rect width="{S["w"]}" height="{S["h"]}" fill="{S["bg"]}" '
        f'data-bleed="true"/>',
        f'<text x="{x:g}" y="{baseline:g}" font-size="{size:g}" '
        f'font-weight="{t_weight("slide_title")}" fill="{S["accent"]}" '
        f'data-style-role="slide_title" '
        f'text-anchor="{anchor}">{esc(title)}</text>',
        f'<line x1="{safe["left"]}" y1="{rule_y:g}" '
        f'x2="{S["w"] - safe["right"]}" y2="{rule_y:g}" '
        f'stroke="{S["divider"]}" stroke-width="1.5" '
        f'data-bleed="true" data-style-role="divider"/>',
    ]
    if footer:
        fs = t_size("footnote")
        # The baseline is lifted by the measured descent so the footer's
        # descenders end *on* the safe-area boundary rather than three units
        # past it. Placing the baseline on the boundary is the obvious-looking
        # choice and is wrong: plan 2's `safe-area` rule reports it on every
        # slide that carries a footer.
        _, descent = vertical_metrics(
            S["font_resolved"], fs, t_weight("footnote"))
        baseline_y = S["h"] - safe["bottom"] - descent
        parts.append(
            f'<text x="{S["w"] - safe["right"]}" y="{baseline_y:g}" '
            f'font-size="{fs:g}" fill="{S["muted"]}" '
            f'data-style-role="footnote" '
            f'text-anchor="end">{esc(footer)}</text>'
        )
    return "\n  ".join(parts)
```

Also update `svg()` (line 149) to emit the resolved family so the SVG preview and
the PPTX export agree:

```python
def svg(body: str) -> str:
    """Wrap slide body markup in the root SVG element.

    Args:
        body: Slide content markup.

    Returns:
        A complete SVG document string.
    """
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {S["w"]} {S["h"]}" '
            f'font-family="{S["font_resolved"]}">\n'
            f'  {body}\n</svg>\n')
```

- [x] **Step 6: Add the `--tokens` flag and call `apply_tokens` first**

In the argparse block, after the `--style` argument (line 855), add:

```python
    ap.add_argument("--tokens", metavar="FILE", type=Path, default=None,
                    help="Design-token .tokens.yaml file "
                         "(default: references/tokens/default.tokens.yaml)")
```

In `main()`, replace the `if args.style: apply_style(args.style)` block (line 877)
with:

```python
    apply_tokens(args.tokens)
    if args.style:
        apply_style(args.style)
```

`apply_tokens` must run first: it establishes sizes, spacing, and the resolved
font, and `apply_style` then overrides colours only.

- [x] **Step 7: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_generate_slides_typography.py -v`
Expected: PASS — 10 passed.

- [x] **Step 8: Run the existing suite**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/tests/ -q`

Expected: failures in renderer tests that assert the old 20pt title, the top
accent bar, or `top_bar_h`. Those expectations are now wrong by design — spec
§2.2 and §2.8. Update each such assertion to the token-driven value and state in
the commit message which expectations changed and why. Do not reintroduce the top
bar or the 20pt title to keep a test green.

- [x] **Step 9: Commit**

```bash
git add skills/report-slides/scripts/generate_slides.py \
        skills/report-slides/scripts/tests/
git commit -m "feat(report-slides): drive renderer typography and frame from design tokens"
```

---

### Task 7: Text-dominant renderers at presentation scale

**Files:**
- Modify: `skills/report-slides/scripts/generate_slides.py` — `wrap` (lines 126–139), `render_title` (158–195), `render_bullet_list` (197–219), `render_conclusion` (625–667)
- Test: `skills/report-slides/scripts/tests/test_generate_slides_typography.py` (append)

**Interfaces:**
- Consumes: `t_size`, `t_weight`, `t_lh`, `S`, `frame` (Task 6);
  `fonts.text_width` (Task 5).
- Produces, used by Tasks 8 and 9:
  `wrap_to_width(text: str, max_width: float, role: str) -> list[str]`

**Literal → role mapping for this task:**

| Line | Literal | Role | New size |
|-----:|--------:|------|---------:|
| 174 | `30` | `deck_title` | 44 |
| 183 | `16` | `takeaway` | 26 |
| 188 | `13` | `caption` | 16 |
| 191 | `10` | `footnote` | 12 |
| 210 | `11` | `footnote` | 12 |
| 214 | `14` | `body` | 21 |
| 640 | `14` | `takeaway` | 26 |
| 651 | `10` | `footnote` | 12 |
| 653 | `13` | `body` | 21 |
| 656 | `13` | `body` | 21 |

**Geometry re-tune rules.** Every vertical advance must derive from the role, not
from a literal tuned for small text:

- Line advance is `t_size(role) * t_lh(role)`, never a literal such as `24` or `28`.
- Block advance is `lines * t_size(role) * t_lh(role) + gap`, where `gap` comes
  from the token spacing scale (`S["spacing"]`).
- Character-count wrapping (`wrap(item, 88)`) is replaced by measured wrapping:
  88 characters at 14pt and at 21pt occupy different widths, so the old budgets
  overflow once sizes rise.
- Bullet marker radii scale with the label: `r = t_size("body") * 0.28` for dots,
  `r = t_size("footnote") * 0.75` for numbered discs.

- [x] **Step 1: Write the failing test**

Append to `skills/report-slides/scripts/tests/test_generate_slides_typography.py`:

```python
def test_wrap_to_width_respects_measured_width() -> None:
    """Wrapping breaks lines by measured width, not character count."""
    text = "Model architecture and evaluation protocol for the ablation study"
    narrow = gs.wrap_to_width(text, 300, "body")
    wide = gs.wrap_to_width(text, 900, "body")
    assert len(narrow) > len(wide)
    for line in narrow:
        assert gs.measured_width(line, "body") <= 300


def test_wrap_to_width_never_drops_words() -> None:
    """Every input word survives wrapping."""
    text = "alpha beta gamma delta epsilon zeta eta theta"
    joined = " ".join(gs.wrap_to_width(text, 200, "body"))
    assert joined.split() == text.split()


def test_wrap_to_width_keeps_overlong_word_on_its_own_line() -> None:
    """A single word wider than the budget is not silently dropped."""
    lines = gs.wrap_to_width("supercalifragilisticexpialidocious", 40, "body")
    assert lines == ["supercalifragilisticexpialidocious"]


def _sizes(markup: str) -> set:
    """Collect every font-size value present in SVG markup."""
    return {float(m) for m in _FONT_SIZE_RE.findall(markup)}


def test_title_slide_uses_deck_title_role() -> None:
    """The title slide headline uses deck_title, not a 30pt literal."""
    markup = gs.render_title(
        {"title": "Ablation Study", "subtitle": "Round 3",
         "author": "Lab", "date": "2026-09-04"},
        {"footer": "1/8"},
    )
    sizes = _sizes(markup)
    assert 44 in sizes
    assert 30 not in sizes
    assert min(sizes) >= 12


def test_bullet_list_body_is_at_least_twenty() -> None:
    """Bullet body text sits at the body role, never at 14."""
    markup = gs.render_bullet_list(
        {"title": "Findings", "bullets": ["one finding", "another finding"]},
        {"footer": "2/8"},
    )
    sizes = _sizes(markup)
    assert 21 in sizes
    assert 14 not in sizes
    assert min(sizes) >= 12


def test_numbered_bullets_stay_inside_the_canvas() -> None:
    """Six numbered bullets still fit within the canvas height."""
    markup = gs.render_bullet_list(
        {"title": "Findings", "numbered": True,
         "bullets": [f"finding number {i}" for i in range(6)]},
        {},
    )
    ys = [float(m) for m in re.findall(r'<circle cx="[0-9.]+" cy="([0-9.]+)"', markup)]
    assert ys
    assert max(ys) <= gs.S["h"] - gs.S["safe"]["bottom"]


def test_conclusion_blocks_use_roles() -> None:
    """Conclusion headings and items use takeaway and body roles."""
    markup = gs.render_conclusion(
        {"title": "Conclusion", "conclusions": ["it worked"],
         "next_steps": ["scale it up"]},
        {},
    )
    sizes = _sizes(markup)
    assert 26 in sizes
    assert 21 in sizes
    assert 13 not in sizes
```

- [x] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_generate_slides_typography.py -v -k "wrap or title_slide or bullet or conclusion"`
Expected: FAIL — `AttributeError: module 'generate_slides' has no attribute 'wrap_to_width'`.

- [x] **Step 3: Give `tlines` its style role**

`tlines` (line 123) writes its own `<text>` element and is called from five
sites in this plan, so it takes the role rather than leaving each caller to
patch the emitted string. Replace it with:

```python
def tlines(lines: list, x, y, size, color, anchor="start", weight="normal",
           lh=1.45, *, role: str) -> str:
    """Render a multi-line text element.

    Args:
        lines: Already-wrapped lines, one per rendered line.
        x: Left, centre, or right coordinate, per `anchor`.
        y: Baseline of the first line.
        size: Font size in SVG units.
        color: Fill colour.
        anchor: SVG `text-anchor` value.
        weight: SVG `font-weight` value.
        lh: Line-height multiplier, applied to `size` for each `dy` after the
            first line.
        role: The typography role this text realises. Keyword-only and
            mandatory: plan 2's linter skips a `<text>` with no
            `data-style-role`, so an optional marker with a default would let a
            caller silently disable `type-floor` and `token-color` for its text.

    Returns:
        SVG markup for one `<text>` element.
    """
    spans = []
    for i, line in enumerate(lines):
        dy = "0" if i == 0 else f"{size * lh:.1f}"
        spans.append(f'<tspan x="{x}" dy="{dy}">{esc(line)}</tspan>')
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'fill="{color}" text-anchor="{anchor}" '
            f'data-style-role="{role}">{"".join(spans)}</text>')
```

Pass the role at all five call sites in this task and Task 9: `role=title_role`
and `role=sub_role` in `render_title_slide`, and `role="body"` in
`render_bullet_list`, `render_two_column`, and `render_conclusion`. Because the
parameter is keyword-only with no default, a missed call site is a `TypeError`
at import time rather than an unmarked element at review time.

- [x] **Step 4: Add measured wrapping**

In `skills/report-slides/scripts/generate_slides.py`, after the existing `wrap`
function (line 139), add:

```python
def measured_width(text: str, role: str) -> float:
    """Measure a string's advance width at a type role's size.

    Args:
        text: The string to measure.
        role: Type role key, such as `body`.

    Returns:
        Advance width in SVG units.
    """
    return text_width(text, S["font_resolved"], t_size(role), t_weight(role))


def wrap_to_width(text: str, max_width: float, role: str) -> list:
    """Wrap text to a pixel budget using real font metrics.

    Character-count wrapping cannot survive a size change: 88 characters at 14
    units and at 21 units occupy different widths. A word wider than the budget
    is kept on its own line rather than dropped.

    Args:
        text: The string to wrap.
        max_width: Available width in SVG units.
        role: Type role key used for measurement.

    Returns:
        Wrapped lines; always at least one entry.
    """
    words = str(text).split()
    if not words:
        return [""]
    lines: list = []
    current: list = []
    for word in words:
        candidate = " ".join(current + [word])
        if current and measured_width(candidate, role) > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines
```

Add `from fonts import resolve_font_stack, text_width, vertical_metrics` in
place of the Task 6 import line.

- [x] **Step 5: Re-render the three text renderers**

In `render_title`, replace lines 174–192 with:

```python
    title_role = "deck_title"
    title_lines = wrap_to_width(title, S["w"] - 2 * S["safe"]["left"] - 160, title_role)
    title_adv = t_size(title_role) * t_lh(title_role)
    title_y = 255 - (len(title_lines) - 1) * (title_adv / 2)
    parts.append(tlines(title_lines, cx, title_y, t_size(title_role),
                        S["accent"], "middle", str(t_weight(title_role)),
                        t_lh(title_role)))

    div_y = title_y + len(title_lines) * title_adv
    parts.append(f'<line x1="200" y1="{div_y:g}" x2="1000" y2="{div_y:g}" '
                 f'stroke="{S["divider"]}" stroke-width="1.5"/>')

    base_y = div_y + 40
    if subtitle:
        sub_role = "takeaway"
        sub_lines = wrap_to_width(subtitle, S["w"] - 2 * S["safe"]["left"] - 120,
                                  sub_role)
        parts.append(tlines(sub_lines, cx, base_y, t_size(sub_role),
                            S["muted"], "middle", str(t_weight(sub_role)),
                            t_lh(sub_role)))
        base_y += len(sub_lines) * t_size(sub_role) * t_lh(sub_role) + 12

    meta_str = "  ·  ".join(filter(None, [author, date]))
    if meta_str:
        parts.append(f'<text x="{cx}" y="{base_y + t_size("caption"):g}" '
                     f'font-size="{t_size("caption"):g}" '
                     f'data-style-role="caption" '
                     f'fill="{S["muted"]}" text-anchor="middle">{esc(meta_str)}</text>')
    if footer:
        # Same lift as `frame()`: the baseline sits a measured descent
        # above the safe-area boundary, not on it.
        fs = t_size("footnote")
        _, descent = vertical_metrics(
            S["font_resolved"], fs, t_weight("footnote"))
        parts.append(f'<text x="{S["w"] - S["safe"]["right"]}" '
                     f'y="{S["h"] - S["safe"]["bottom"] - descent:g}" '
                     f'font-size="{fs:g}" fill="{S["muted"]}" '
                     f'data-style-role="footnote" '
                     f'text-anchor="end">{esc(footer)}</text>')
```

Delete the two `<rect ... height="8" fill="{S["accent"]}"/>` bars at lines 169–170:
the top and bottom accent bars are part of the templated signature removed in
Task 6.

In `render_bullet_list`, replace lines 203–218 with:

```python
    parts = [frame(title, footer)]
    safe = S["safe"]
    x_dot = safe["left"] + 14
    x_text = safe["left"] + 52
    text_budget = S["w"] - x_text - safe["right"]
    body_adv = t_size("body") * t_lh("body")
    y = t_size("slide_title") + safe["top"] + 56
    for i, item in enumerate(bullets):
        lines = wrap_to_width(str(item), text_budget, "body")
        if numbered:
            r = t_size("footnote") * 0.75
            parts.append(f'<circle cx="{x_dot}" cy="{y - t_size("body") * 0.32:g}" '
                         f'r="{r:g}" fill="{S["accent"]}"/>')
            parts.append(f'<text x="{x_dot}" '
                         f'y="{y - t_size("body") * 0.32 + r * 0.55:g}" '
                         f'font-size="{t_size("footnote"):g}" font-weight="700" '
                         f'data-style-role="footnote" '
                         f'fill="{S["white"]}" text-anchor="middle">{i + 1}</text>')
        else:
            parts.append(f'<circle cx="{x_dot}" cy="{y - t_size("body") * 0.30:g}" '
                         f'r="{t_size("body") * 0.28:g}" fill="{S["accent"]}"/>')
        parts.append(tlines(lines, x_text, y, t_size("body"), S["body"],
                            "start", str(t_weight("body")), t_lh("body")))
        y += len(lines) * body_adv + S["spacing"][2]
```

`S["spacing"]` is the token spacing scale; add it in Task 6's `apply_tokens` if not
already present:

```python
    S["spacing"] = list(_TOKENS.raw["spacing"]["scale"])
```

In `render_conclusion`, inside `block`, replace the heading, rule, and item hunks
(lines 640–656) with:

```python
        out.append(f'<text x="{px + 24}" y="{py + 24 + t_size("takeaway"):g}" '
                   f'font-size="{t_size("takeaway"):g}" '
                   f'font-weight="{t_weight("takeaway")}" '
                   f'data-style-role="takeaway" '
                   f'fill="{color}">{esc(heading)}</text>')
        rule_y = py + 24 + t_size("takeaway") + 14
        out.append(f'<line x1="{px + 24}" y1="{rule_y:g}" '
                   f'x2="{px + pw - 24}" y2="{rule_y:g}" '
                   f'stroke="{S["divider"]}" stroke-width="1"/>')

        iy = rule_y + 24 + t_size("body")
        body_adv = t_size("body") * t_lh("body")
        for idx, item in enumerate(items):
            lines = wrap_to_width(str(item), pw - 96, "body")
            if numbered:
                r = t_size("footnote") * 0.85
                out.append(f'<circle cx="{px + 32}" '
                           f'cy="{iy - t_size("body") * 0.32:g}" '
                           f'r="{r:g}" fill="{color}"/>')
                out.append(f'<text x="{px + 32}" '
                           f'y="{iy - t_size("body") * 0.32 + r * 0.55:g}" '
                           f'font-size="{t_size("footnote"):g}" font-weight="700" '
                           f'data-style-role="footnote" '
                           f'fill="{S["white"]}" text-anchor="middle">{idx + 1}</text>')
                out.append(tlines(lines, px + 32 + r + 16, iy, t_size("body"),
                                  S["body"], "start", str(t_weight("body")),
                                  t_lh("body")))
            else:
                out.append(f'<circle cx="{px + 32}" '
                           f'cy="{iy - t_size("body") * 0.30:g}" '
                           f'r="{t_size("body") * 0.28:g}" fill="{color}"/>')
                out.append(tlines(lines, px + 32 + t_size("body") * 0.28 + 16, iy,
                                  t_size("body"), S["body"], "start",
                                  str(t_weight("body")), t_lh("body")))
            iy += len(lines) * body_adv + S["spacing"][2]
```

Also change the two `block(...)` call sites (lines 661–662) so the panels start
below the new title rule and use the token safe area:

```python
    panel_top = S["safe"]["top"] + t_size("slide_title") + 40
    panel_h = S["h"] - panel_top - S["safe"]["bottom"] - 16
    panel_w = (S["w"] - 2 * S["safe"]["left"] - 40) / 2
    parts += block(conclusions, S["safe"]["left"], panel_top, panel_w, panel_h,
                   S["accent"], c_head, numbered=False)
    parts += block(next_steps, S["safe"]["left"] + panel_w + 40, panel_top,
                   panel_w, panel_h, S["good"], n_head, numbered=True)
```

- [x] **Step 6: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_generate_slides_typography.py -v`
Expected: PASS — all tests green.

- [x] **Step 7: Render and inspect the pixels**

Unit tests confirm sizes but not legibility. Render the three slide types and look
at them:

```bash
timeout 300 python3 -c "
import sys; sys.path.insert(0, 'skills/report-slides/scripts')
import generate_slides as gs
import cairosvg, pathlib
gs.apply_tokens(None)
out = pathlib.Path('/tmp/task7-render'); out.mkdir(parents=True, exist_ok=True)
cases = {
  'title': (gs.render_title, {'title': 'Sparse Attention Ablation Study',
      'subtitle': 'Round 3 results across four sequence lengths',
      'author': 'Research Lab', 'date': '2026-09-04'}),
  'bullets': (gs.render_bullet_list, {'title': 'Findings', 'numbered': True,
      'bullets': ['Throughput improved 2.1x at 8k context with no quality loss',
                  'Memory scales linearly rather than quadratically',
                  'Gains vanish below 1k context, where dense attention wins',
                  'Kernel launch overhead dominates at small batch sizes',
                  'Results replicate across three random seeds',
                  'Remaining gap to theoretical peak is 18 percent']}),
  'conclusion': (gs.render_conclusion, {'title': 'Conclusion and Next Steps',
      'conclusions': ['Sparse attention pays off above 4k context',
                      'The crossover point is dataset dependent'],
      'next_steps': ['Profile the kernel launch path',
                     'Extend the sweep to 32k context']}),
}
for name, (fn, payload) in cases.items():
    svg = fn(payload, {'footer': 'deck 1/8'})
    (out / f'{name}.svg').write_text(svg, encoding='utf-8')
    cairosvg.svg2png(bytestring=svg.encode('utf-8'),
                     write_to=str(out / f'{name}.png'),
                     output_width=1600, output_height=900)
    print('wrote', out / f'{name}.png')
"
```

Then open each PNG and confirm: no clipped or overlapping text, bullets inside the
safe area, the title block reads as a deliberate composition rather than a
centred template, and body text is comfortably legible at a glance. If anything
overflows, adjust the geometry formulas above — do not reduce a role's size to
make text fit.

- [x] **Step 8: Run the existing suite**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/tests/ -q`
Expected: PASS. Update any renderer fixture asserting the old sizes, and say in
the commit message which expectations changed and why the old values were wrong.

- [x] **Step 9: Commit**

```bash
git add skills/report-slides/scripts/generate_slides.py \
        skills/report-slides/scripts/tests/
git commit -m "feat(report-slides): typeset title, bullet, and conclusion slides at presentation scale"
```

---

### Task 8: Chart renderers at presentation scale

**Files:**
- Modify: `skills/report-slides/scripts/generate_slides.py` — chart area constants (lines 97–98), `render_bar_chart` (220–297), `render_line_chart` (299–354), `render_pie_chart` (356–407)
- Test: `skills/report-slides/scripts/tests/test_generate_slides_typography.py` (append)

**Interfaces:**
- Consumes: `t_size`, `t_weight`, `t_lh`, `S` (Task 6); `wrap_to_width`,
  `measured_width` (Task 7).
- Produces: `chart_area() -> tuple[float, float, float, float]` returning
  `(left, right, top, bottom)` computed from tokens, replacing the module-level
  `CL, CR, CT, CB` constants; and `CW`/`CH` derived from it.

**Literal → role mapping for this task:**

| Line | Literal | Purpose | Role | New size |
|-----:|--------:|---------|------|---------:|
| 237 | `10` | y-axis tick labels (bar) | `axis` | 16 |
| 261 | `12` | category labels (bar) | `axis` | 16 |
| 278 | `11` | bar value labels | `footnote` | 12 |
| 287 | `12` | legend labels (bar) | `axis` | 16 |
| 290 | `10` | chart note (bar) | `footnote` | 12 |
| 319 | `10` | y-axis tick labels (line) | `axis` | 16 |
| 331 | `12` | x-axis labels (line) | `axis` | 16 |
| 347 | `10` | chart note (line) | `footnote` | 12 |
| 394 | `13` | pie legend labels | `axis` | 16 |
| 398 | `10` | pie note | `footnote` | 12 |

**Why the chart area must move.** Line 97 fixes
`CL, CR, CT, CB = 130, 1100, 100, 520`. Three of the four are now wrong:

- `CT = 100` was clearance for a 20pt title baseline at `y=44`. Task 6 puts the
  title baseline at `safe.top + slide_title = 36 + 32 = 68` with its rule at
  `84`, so the plot must start at `84 + 24 = 108`.
- `CB = 520` left `675 - 520 = 155` units for category labels at 12pt plus a
  legend at 12pt. At 16pt both grow; the legend row and note need
  `axis * lh + 24` more.
- `CL = 130` must clear the widest y-tick label at 16pt plus an 8-unit gap,
  measured rather than assumed.

- [x] **Step 1: Write the failing test**

Append to `skills/report-slides/scripts/tests/test_generate_slides_typography.py`:

```python
def test_chart_area_clears_the_title_rule() -> None:
    """The plot top sits below the frame rule, not at the old y=100."""
    left, right, top, bottom = gs.chart_area()
    rule_y = gs.S["safe"]["top"] + gs.t_size("slide_title") + 16
    assert top > rule_y
    assert bottom < gs.S["h"] - gs.S["safe"]["bottom"]
    assert right <= gs.S["w"] - gs.S["safe"]["right"]


def test_chart_area_left_margin_fits_axis_labels() -> None:
    """The left margin clears the widest tick label at the axis role."""
    left, _, _, _ = gs.chart_area()
    assert left >= gs.measured_width("100%", "axis") + gs.S["safe"]["left"] + 8


def test_bar_chart_axis_labels_are_at_least_sixteen() -> None:
    """Bar chart axis and category labels use the axis role."""
    markup = gs.render_bar_chart(
        {"index": 1, "title": "Throughput",
         "categories": ["1k", "4k", "8k", "16k"],
         "series": [{"label": "sparse", "values": [10, 40, 70, 95]},
                    {"label": "dense", "values": [30, 45, 50, 52]}],
         "y_max": 100, "note": "higher is better"},
        {"footer": "3/8"},
    )
    sizes = _sizes(markup)
    assert 16 in sizes
    assert 10 not in sizes
    assert min(sizes) >= 12


def test_line_chart_axis_labels_are_at_least_sixteen() -> None:
    """Line chart axis labels use the axis role."""
    markup = gs.render_line_chart(
        {"index": 2, "title": "Loss",
         "categories": ["e1", "e2", "e3"],
         "series": [{"label": "train", "values": [90, 50, 30]}],
         "y_max": 100},
        {},
    )
    sizes = _sizes(markup)
    assert 16 in sizes
    assert 10 not in sizes or 10 not in {s for s in sizes if s < 12}
    assert min(sizes) >= 12


def test_pie_chart_legend_is_at_least_sixteen() -> None:
    """Pie chart legend labels use the axis role."""
    markup = gs.render_pie_chart(
        {"index": 3, "title": "Budget",
         "categories": ["compute", "storage", "network"],
         "values": [60, 25, 15]},
        {},
    )
    sizes = _sizes(markup)
    assert 16 in sizes
    assert 13 not in sizes
    assert min(sizes) >= 12


def test_bar_chart_legend_entries_do_not_collide() -> None:
    """Legend entries are spaced by measured label width, not a fixed 230."""
    markup = gs.render_bar_chart(
        {"index": 4, "title": "Comparison",
         "categories": ["a", "b"],
         "series": [
             {"label": "an extremely long series label that overruns", "values": [1, 2]},
             {"label": "second", "values": [3, 4]},
         ],
         "y_max": 10},
        {},
    )
    xs = sorted(
        float(m) for m in re.findall(
            r'<rect x="([0-9.]+)" y="[0-9.]+" width="16" height="12"', markup)
    )
    assert len(xs) == 2
    first_label = "an extremely long series label that overruns"
    assert xs[1] - xs[0] >= gs.measured_width(first_label, "axis") + 22
```

- [x] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_generate_slides_typography.py -v -k "chart"`
Expected: FAIL — `AttributeError: module 'generate_slides' has no attribute 'chart_area'`.

- [x] **Step 3: Replace the fixed chart area with a token-derived one**

Replace lines 97–98 of `skills/report-slides/scripts/generate_slides.py`:

```python
# Chart drawing area
CL, CR, CT, CB = 130, 1100, 100, 520
CW, CH = CR - CL, CB - CT
```

with:

```python
def chart_area() -> tuple:
    """Compute the plot rectangle from the active tokens.

    The area clears the frame rule at the top, the widest y-tick label on the
    left, and the category-label plus legend plus note rows at the bottom. The
    former fixed `130, 1100, 100, 520` was tuned for 10-12 unit chart text and
    a 20 unit title, both of which changed.

    Returns:
        `(left, right, top, bottom)` in SVG units.
    """
    safe = S["safe"]
    rule_y = safe["top"] + t_size("slide_title") + 16
    top = rule_y + 24
    left = safe["left"] + measured_width("100%", "axis") + 8
    right = S["w"] - safe["right"]
    axis_adv = t_size("axis") * t_lh("axis")
    foot_adv = t_size("footnote") * t_lh("footnote")
    # category labels, then legend row, then note row
    bottom = S["h"] - safe["bottom"] - (axis_adv + axis_adv + foot_adv + 24)
    return left, right, top, bottom
```

Every use of `CL`, `CR`, `CT`, `CB`, `CW`, `CH` inside the three chart renderers
becomes a local unpack at the top of the renderer:

```python
    CL, CR, CT, CB = chart_area()
    CW, CH = CR - CL, CB - CT
```

Add that line immediately after each renderer's `chart_parts = []`
(bar: line 230; line chart and pie chart: the equivalent position). Delete the
module-level constants so no renderer can silently keep the old values.

- [x] **Step 4: Apply the role mapping and re-space the legend**

In each of the ten sites in the mapping table above, replace the literal
`font-size="N"` with `font-size="{t_size(ROLE):g}"` using the role from the table,
add `font-weight="{t_weight(ROLE)}"` where the site currently hard-codes a
weight, and add `data-style-role="ROLE"` with the same role. The marker is not
cosmetic: plan 2's `type-floor` and `token-color` rules read it, and an element
without one is skipped rather than flagged, so the rules would report clean on
markup they never examined. Task 9 Step 8 asserts this mechanically over every
renderer.

Replace the fixed-pitch legend loop in `render_bar_chart` (lines 282–287) with
measured spacing:

```python
    legend_x = CL
    legend_y = CB + t_size("axis") * t_lh("axis") + 16
    swatch = t_size("axis") * 0.75
    for si, ser in enumerate(series):
        color = ser.get("color", S["blue"])
        label = str(ser.get("label", ""))
        chart_parts.append(f'<rect x="{legend_x:.1f}" '
                           f'y="{legend_y - swatch:.1f}" '
                           f'width="{swatch:.1f}" height="{swatch:.1f}" '
                           f'fill="{color}"/>')
        chart_parts.append(f'<text x="{legend_x + swatch + 8:.1f}" '
                           f'y="{legend_y:.1f}" '
                           f'font-size="{t_size("axis"):g}" '
                           f'data-style-role="axis" '
                           f'fill="{S["body"]}">{esc(label)}</text>')
        legend_x += swatch + 8 + measured_width(label, "axis") + 32
```

Move the chart note to its own row below the legend so it can no longer collide
with the last legend entry (lines 289–291):

```python
    if note:
        note_y = legend_y + t_size("footnote") * t_lh("footnote") + 12
        chart_parts.append(f'<text x="{CR}" y="{note_y:.1f}" '
                           f'font-size="{t_size("footnote"):g}" '
                           f'data-style-role="footnote" '
                           f'fill="{S["muted"]}" text-anchor="end">{esc(note)}</text>')
```

Apply the same note treatment in `render_line_chart` (line 347) and
`render_pie_chart` (line 398).

Update the `_wrap_pptx_role(...)` `bbox` argument in each chart renderer (bar:
line 294) so the declared native-chart bounding box matches the new plot area:

```python
    parts.append(_wrap_pptx_role("chart", slide_index, chart_parts,
                                 bbox=(CL, CT, CR - CL, CB - CT),
                                 style_keys=("font",)))
```

- [x] **Step 5: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_generate_slides_typography.py -v`
Expected: PASS — all tests green.

- [x] **Step 6: Render and inspect the pixels**

```bash
timeout 300 python3 -c "
import sys; sys.path.insert(0, 'skills/report-slides/scripts')
import generate_slides as gs
import cairosvg, pathlib
gs.apply_tokens(None)
out = pathlib.Path('/tmp/task8-render'); out.mkdir(parents=True, exist_ok=True)
cases = {
  'bar': (gs.render_bar_chart, {'index': 1, 'title': 'Throughput by context length',
      'categories': ['1k','4k','8k','16k','32k'],
      'series': [{'label':'sparse attention','values':[10,40,70,95,98]},
                 {'label':'dense attention','values':[30,45,50,52,51]}],
      'y_max': 100, 'note': 'higher is better'}),
  'line': (gs.render_line_chart, {'index': 2, 'title': 'Validation loss',
      'categories': ['e1','e2','e3','e4','e5'],
      'series': [{'label':'train','values':[90,60,42,33,29]},
                 {'label':'val','values':[92,66,50,44,41]}],
      'y_max': 100, 'note': 'three seeds averaged'}),
  'pie': (gs.render_pie_chart, {'index': 3, 'title': 'Compute budget',
      'categories': ['pretraining','fine-tuning','evaluation','infrastructure'],
      'values': [55,20,15,10], 'note': 'GPU-hours'}),
}
for name, (fn, payload) in cases.items():
    svg = fn(payload, {'footer': 'deck 3/8'})
    (out / f'{name}.svg').write_text(svg, encoding='utf-8')
    cairosvg.svg2png(bytestring=svg.encode('utf-8'),
                     write_to=str(out / f'{name}.png'),
                     output_width=1600, output_height=900)
    print('wrote', out / f'{name}.png')
"
```

Open each PNG and confirm: tick labels are not clipped at the left edge, category
labels do not overlap each other, the legend fits on one row without colliding
with the note, and no plot element crosses the frame rule. If the legend overflows
the right edge with many series, wrap it to a second row rather than shrinking the
axis role.

- [x] **Step 7: Run the existing suite**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/tests/ -q`
Expected: PASS. Native-chart tests asserting the old `bbox=(60, 70, 1080, 500)`
now see the token-derived box; update those expectations and record in the commit
message why the old constant was wrong.

- [x] **Step 8: Commit**

```bash
git add skills/report-slides/scripts/generate_slides.py \
        skills/report-slides/scripts/tests/
git commit -m "feat(report-slides): typeset chart renderers at presentation scale"
```

---

### Task 9: Layout renderers at presentation scale

**Files:**
- Modify: `skills/report-slides/scripts/generate_slides.py` — `render_table` (425–486), `render_metric_cards` (488–529), `render_two_column` (531–568), `render_timeline` (570–623)
- Test: `skills/report-slides/scripts/tests/test_generate_slides_typography.py` (append)

**Interfaces:**
- Consumes: `t_size`, `t_weight`, `t_lh`, `S`, `frame` (Task 6); `wrap_to_width`,
  `measured_width` (Task 7); `chart_area` is not used here.
- Produces: `class SlideCapacityError(ValueError)`, raised when content cannot fit
  at presentation scale.

**This task has a review checkpoint after Step 5.** It rewrites four renderers,
and the two halves fail differently: the table and the metric cards are grid
arithmetic, while the two-column and timeline layouts have to decide what to do
when content will not fit. A reviewer should be able to reject the second half
without unwinding the first, so Step 6 opens with its own commit of Steps 1–5
and the task ends with a second. Run Step 7's tests before each. If the timeline
work turns out to be larger than it looks — measured event spacing is the one
place here with real layout judgement in it — stop after the first commit and
say so; a half-finished renderer behind one commit is what makes a task like
this hard to review.

**Literal → role mapping for this task:**

| Line | Literal | Purpose | Role | New size |
|-----:|--------:|---------|------|---------:|
| 453 | `13` | table header cells | `node_label` | 18 |
| 472 | `13` | table body cells | `body` | 21 |
| 519 | `13` | metric card label | `caption` | 16 |
| 521 | `38` | metric card value | `deck_title` | 44 |
| 526 | `12` | metric card change | `footnote` | 12 |
| 545 | `14` | two-column heading | `takeaway` | 26 |
| 555 | `13` | two-column body | `body` | 21 |
| 560 | `13` | two-column list item | `body` | 21 |
| 606 | `13` | timeline event label | `node_label` | 18 |
| 611 | `10` | timeline date | `footnote` | 12 |
| 617 | `11` | timeline detail | `caption` | 16 |

**The capacity decision.** `render_table` line 441 computes
`row_h = min(50, 450 / (len(rows) + 1))`. With 13-unit text a 9-row table gets
45-unit rows and just fits. At the 21-unit body role a row needs
`21 * 1.45 + 2 * 12 = 54.5` units, so the same table no longer fits.

Shrinking the text to fit is exactly the defect this plan exists to remove, and
silently clipping rows would hide data. The renderer therefore **raises
`SlideCapacityError`** naming the row count, the capacity, and the fix (split the
table across slides, or drop columns). This follows the repository's
no-silent-failures rule: content that cannot be shown legibly is an error, not a
rendering option.

- [x] **Step 1: Write the failing test**

Append to `skills/report-slides/scripts/tests/test_generate_slides_typography.py`:

```python
def test_table_cells_are_at_presentation_scale() -> None:
    """Table header and body cells use node_label and body roles."""
    markup = gs.render_table(
        {"index": 1, "title": "Results",
         "columns": ["config", "acc", "delta"],
         "rows": [["baseline", "81.2", "—"], ["sparse", "83.4", "+2.2"]]},
        {"footer": "4/8"},
    )
    sizes = _sizes(markup)
    assert 18 in sizes
    assert 21 in sizes
    assert 13 not in sizes


def test_table_rows_never_shrink_below_the_body_role() -> None:
    """Row height accommodates the body role plus vertical padding."""
    markup = gs.render_table(
        {"index": 1, "title": "Results",
         "columns": ["a", "b"],
         "rows": [["1", "2"], ["3", "4"], ["5", "6"]]},
        {},
    )
    heights = {
        float(m) for m in re.findall(r'height="([0-9.]+)" fill="#', markup)
    }
    needed = gs.t_size("body") * gs.t_lh("body")
    assert heights
    assert min(heights) >= needed


def test_table_raises_when_rows_cannot_fit() -> None:
    """An over-long table is an error, not silently shrunken text."""
    rows = [[f"row {i}", str(i)] for i in range(40)]
    with pytest.raises(gs.SlideCapacityError) as excinfo:
        gs.render_table(
            {"index": 1, "title": "Results", "columns": ["name", "n"], "rows": rows},
            {},
        )
    message = str(excinfo.value)
    assert "40" in message
    assert "split" in message.lower()


def test_metric_cards_use_display_and_caption_roles() -> None:
    """Metric labels, values, and changes all come from roles."""
    markup = gs.render_metric_cards(
        {"index": 2, "title": "Headline numbers",
         "metrics": [{"label": "throughput", "value": "2.1x", "change": "+110%"},
                     {"label": "memory", "value": "0.6x", "change": "-40%"}]},
        {},
    )
    sizes = _sizes(markup)
    assert 44 in sizes
    assert 16 in sizes
    assert 38 not in sizes
    assert min(sizes) >= 12


def test_two_column_headings_and_body_use_roles() -> None:
    """Two-column headings use takeaway and body text uses body."""
    markup = gs.render_two_column(
        {"index": 3, "title": "Comparison",
         "left": {"heading": "Before", "content": "dense attention throughout"},
         "right": {"heading": "After", "content": "sparse above 4k context"}},
        {},
    )
    sizes = _sizes(markup)
    assert 26 in sizes
    assert 21 in sizes
    assert 13 not in sizes


def test_timeline_labels_use_node_and_caption_roles() -> None:
    """Timeline labels, dates, and details use their roles."""
    markup = gs.render_timeline(
        {"index": 4, "title": "Schedule",
         "events": [{"label": "kickoff", "date": "2026-01", "detail": "scope agreed"},
                    {"label": "midpoint", "date": "2026-05", "detail": "first results"},
                    {"label": "delivery", "date": "2026-09", "detail": "paper submitted"}]},
        {},
    )
    sizes = _sizes(markup)
    assert 18 in sizes
    assert 16 in sizes
    assert min(sizes) >= 12
    assert 11 not in sizes


def test_timeline_events_stay_inside_the_safe_area() -> None:
    """Timeline text does not run past the safe area at the new sizes."""
    markup = gs.render_timeline(
        {"index": 4, "title": "Schedule",
         "events": [{"label": f"milestone {i}", "date": f"2026-0{i}",
                     "detail": "a reasonably long detail string"}
                    for i in range(1, 6)]},
        {},
    )
    ys = [float(m) for m in re.findall(r'<text x="[0-9.\-]+" y="([0-9.]+)"', markup)]
    assert ys
    assert max(ys) <= gs.S["h"] - gs.S["safe"]["bottom"]
```

- [x] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_generate_slides_typography.py -v -k "table or metric or two_column or timeline"`
Expected: FAIL — `AttributeError: module 'generate_slides' has no attribute 'SlideCapacityError'`.

- [x] **Step 3: Add the capacity error**

In `skills/report-slides/scripts/generate_slides.py`, after the `TYPE`/`_TOKENS`
declarations added in Task 6, add:

```python
class SlideCapacityError(ValueError):
    """Raised when content cannot be rendered legibly at presentation scale.

    Shrinking type below a token role, or clipping rows, would hide the problem
    rather than solve it. The caller must split the content across slides or
    reduce it.
    """
```

- [x] **Step 4: Re-render the table**

In `render_table`, replace lines 439–455 with:

```python
    safe = S["safe"]
    tl = safe["left"]
    tr = S["w"] - safe["right"]
    tw = tr - tl
    col_w = tw / n_cols
    top_y = safe["top"] + t_size("slide_title") + 40

    header_h = t_size("node_label") * t_lh("node_label") + 2 * 12
    body_h = t_size("body") * t_lh("body") + 2 * 12
    available = S["h"] - top_y - safe["bottom"]
    capacity = int((available - header_h) // body_h)
    if len(rows) > capacity:
        raise SlideCapacityError(
            f"table has {len(rows)} rows but only {capacity} fit at the body "
            f"role ({t_size('body'):g} units); split the table across slides or "
            f"drop columns rather than shrinking the text"
        )
    row_h = body_h
    table_h = header_h + row_h * len(rows)

    table_parts = [
        f'<rect x="{tl}" y="{top_y}" width="{tw}" '
        f'height="{header_h:.1f}" fill="{S["accent"]}"/>'
    ]
    for ci, col in enumerate(columns):
        cx = tl + ci * col_w + col_w / 2
        table_parts.append(
            f'<text x="{cx:.1f}" y="{top_y + header_h * 0.66:.1f}" '
            f'font-size="{t_size("node_label"):g}" '
            f'font-weight="{t_weight("node_label")}" fill="{S["white"]}" '
            f'data-style-role="node_label" '
            f'text-anchor="middle">{esc(col)}</text>')
```

In the row loop, replace `ry = top_y + (ri + 1) * row_h` with
`ry = top_y + header_h + ri * row_h`, replace `cy = ry + row_h * 0.63` with
`cy = ry + row_h * 0.66`, and change the cell text size at line 472 to
`font-size="{t_size("body"):g}"`.

- [x] **Step 5: Re-render the metric cards**

In `render_metric_cards`, replace lines 497–527 with:

```python
    cols = 2 if n == 4 else min(n, 3)
    rows = (n + cols - 1) // cols
    safe = S["safe"]
    top = safe["top"] + t_size("slide_title") + 40
    gap = S["spacing"][4]
    cw = (S["w"] - 2 * safe["left"] - (cols - 1) * gap) / cols
    ch = (S["h"] - top - safe["bottom"] - (rows - 1) * gap) / rows
    surface = _TOKENS.surface("card")

    min_ch = (t_size("caption") * t_lh("caption")
              + t_size("deck_title") * t_lh("deck_title")
              + t_size("footnote") * t_lh("footnote")
              + 2 * surface["padding"]["y"] + 24)
    if ch < min_ch:
        raise SlideCapacityError(
            f"{n} metric cards need {min_ch:.0f} units of height each but only "
            f"{ch:.0f} are available; use fewer cards per slide"
        )

    for i, m in enumerate(metrics):
        col = i % cols
        row = i // cols
        cx = safe["left"] + col * (cw + gap)
        cy = top + row * (ch + gap)
        color = m.get("color", S["blue"])
        label = m.get("label", "")
        value = m.get("value", "")
        change = m.get("change", "")

        parts.append(f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{cw:.1f}" '
                     f'height="{ch:.1f}" rx="{surface["radius"]}" '
                     f'fill="{S["card"]}" stroke="{S["divider"]}" '
                     f'stroke-width="{surface["border_width"]}"/>')
        parts.append(f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{cw:.1f}" '
                     f'height="5" rx="4" fill="{color}"/>')
        label_y = cy + surface["padding"]["y"] + t_size("caption") + 8
        parts.append(f'<text x="{cx + cw / 2:.1f}" y="{label_y:.1f}" '
                     f'font-size="{t_size("caption"):g}" '
                     f'data-style-role="caption" '
                     f'fill="{S["muted"]}" text-anchor="middle">{esc(label)}</text>')
        parts.append(f'<text x="{cx + cw / 2:.1f}" '
                     f'y="{cy + ch / 2 + t_size("deck_title") * 0.36:.1f}" '
                     f'font-size="{t_size("deck_title"):g}" '
                     f'font-weight="{t_weight("deck_title")}" fill="{color}" '
                     f'data-style-role="deck_title" '
                     f'text-anchor="middle">{esc(value)}</text>')
        if change:
            cc = (S["good"] if "+" in str(change)
                  else (S["danger"] if "-" in str(change) else S["muted"]))
            parts.append(f'<text x="{cx + cw / 2:.1f}" '
                         f'y="{cy + ch - surface["padding"]["y"]:.1f}" '
                         f'font-size="{t_size("footnote"):g}" fill="{cc}" '
                         f'data-style-role="footnote" '
                         f'text-anchor="middle">{esc(change)}</text>')
```

- [x] **Step 6: Re-render the two-column and timeline slides**

First commit the checkpoint, so the two halves can be reviewed apart:

```bash
timeout 300 python3 -m pytest \
    skills/report-slides/scripts/tests/test_generate_slides_typography.py -q
git add skills/report-slides/scripts/generate_slides.py \
        skills/report-slides/scripts/tests/test_generate_slides_typography.py
git commit -m "refactor(report-slides): put tables and metric cards on the token roles

Both renderers now take every size, weight, and vertical offset from the type
roles, declare data-style-role on every text element, and raise
SlideCapacityError rather than shrinking type to fit."
```

Then, for `render_two_column` (lines 531–568) and `render_timeline` (570–623), apply the
mapping table rows for lines 545, 555, 560, 606, 611, and 617, and re-derive every
vertical offset from the role:

- Replace each `font-size="N"` with `font-size="{t_size(ROLE):g}"`, add
  `font-weight="{t_weight(ROLE)}"` where a weight is hard-coded, and add
  `data-style-role="ROLE"` with the same role — see Step 4 of Task 8 for why the
  marker is load-bearing rather than decorative.
- Replace every `wrap(text, N)` call with
  `wrap_to_width(text, <available width>, ROLE)`, where the available width is the
  panel or column width minus twice the surface padding.
- Replace every literal line advance (`28 * len(lines)`, `25`, `20`) with
  `len(lines) * t_size(ROLE) * t_lh(ROLE)`.
- Replace panel origins with `safe["left"]` / `safe["top"] + t_size("slide_title") + 40`
  and panel gaps with `S["spacing"][4]`, matching Step 5.
- In `render_timeline`, space events by measured label width: an event's minimum
  horizontal slot is `measured_width(longest_label_line, "node_label") + S["spacing"][3]`.
  If the events do not fit across the axis, raise `SlideCapacityError` naming the
  event count rather than letting labels overlap.

- [x] **Step 7: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_generate_slides_typography.py -v`
Expected: PASS — all tests green.

- [x] **Step 8: Assert no small-type literal, and no unroled text, survives**

Add this final guard test to the same file:

```python
_SWEEP_PAYLOADS = {
    "title": {"title": "T", "subtitle": "S", "author": "A", "date": "D"},
    "bullet_list": {"title": "T", "bullets": ["one", "two"]},
    "bar_chart": {"index": 1, "title": "T", "categories": ["a", "b"],
                  "series": [{"label": "s", "values": [1, 2]}], "y_max": 10,
                  "note": "n"},
    "line_chart": {"index": 2, "title": "T", "categories": ["a", "b"],
                   "series": [{"label": "s", "values": [1, 2]}], "y_max": 10},
    "pie_chart": {"index": 3, "title": "T", "categories": ["a", "b"],
                  "values": [1, 2]},
    "table": {"index": 4, "title": "T", "columns": ["c1", "c2"],
              "rows": [["1", "2"]]},
    "metric_cards": {"index": 5, "title": "T",
                     "metrics": [{"label": "l", "value": "1", "change": "+1"}]},
    "two_column": {"index": 6, "title": "T",
                   "left": {"heading": "L", "content": "lc"},
                   "right": {"heading": "R", "content": "rc"}},
    "timeline": {"index": 7, "title": "T",
                 "events": [{"label": "e", "date": "d", "detail": "x"}]},
    "conclusion": {"index": 8, "title": "T", "conclusions": ["c"],
                   "next_steps": ["n"]},
}


def test_no_renderer_emits_type_below_the_footnote_floor() -> None:
    """Every renderer's output respects the footnote floor of 12 units."""
    for slide_type, payload in _SWEEP_PAYLOADS.items():
        markup = gs.RENDERERS[slide_type](payload, {"footer": "f"})
        sizes = [float(m) for m in _FONT_SIZE_RE.findall(markup)]
        assert sizes, f"{slide_type} emitted no sized text"
        assert min(sizes) >= 12, f"{slide_type} emitted {min(sizes)} unit text"


def test_every_text_element_declares_a_known_style_role() -> None:
    """No renderer may emit a `<text>` without naming its typography role.

    Plan 2's linter reads `data-style-role` to decide which type floor, which
    colour set, and which decorative exemption apply. An element without one is
    not merely unstyled: `check_type_floor` and `check_token_color` skip it, so
    those rules report clean on markup they never examined. The failure is
    silent by construction, which is why it is asserted mechanically here rather
    than left to review. A misspelt role produces the same silent skip as an
    omission, so the value is checked against the token file too.
    """
    roles = set(gs._TOKENS.raw["typography"]["roles"])
    for slide_type, payload in _SWEEP_PAYLOADS.items():
        fragment = gs.RENDERERS[slide_type](payload, {"footer": "f"})
        root = etree.fromstring(gs.svg(fragment).encode("utf-8"))
        elements = list(root.iter("{http://www.w3.org/2000/svg}text"))
        assert elements, f"{slide_type} emitted no text at all"
        for elem in elements:
            declared = elem.get("data-style-role")
            assert declared, (
                f"{slide_type} emitted <text> with no data-style-role: "
                f"{etree.tostring(elem)[:120]!r}"
            )
            assert declared in roles, (
                f"{slide_type} declared style role {declared!r}, which the "
                f"token file does not define"
            )
```

Add `from lxml import etree` to the test module's imports; the repository
already depends on lxml through `svg_to_pptx`.

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_generate_slides_typography.py -v -k "footnote_floor or style_role"`
Expected: PASS — 2 passed. If a renderer fails the floor, fix that renderer — do
not lower the floor. If a renderer fails the role check, add the role from the
`t_size(...)` call already on that line — never delete the assertion.

- [x] **Step 9: Render and inspect the pixels**

```bash
timeout 300 python3 -c "
import sys; sys.path.insert(0, 'skills/report-slides/scripts')
import generate_slides as gs
import cairosvg, pathlib
gs.apply_tokens(None)
out = pathlib.Path('/tmp/task9-render'); out.mkdir(parents=True, exist_ok=True)
cases = {
  'table': ('table', {'index':1,'title':'Ablation results',
      'columns':['configuration','accuracy','delta','throughput'],
      'rows':[['dense baseline','81.2','—','1.00x'],
              ['sparse k=64','83.4','+2.2','1.85x'],
              ['sparse k=32','82.9','+1.7','2.10x'],
              ['sparse k=16','80.1','-1.1','2.40x']],
      'highlight_col':2}),
  'metrics': ('metric_cards', {'index':2,'title':'Headline numbers',
      'metrics':[{'label':'throughput','value':'2.1x','change':'+110%'},
                 {'label':'peak memory','value':'0.6x','change':'-40%'},
                 {'label':'accuracy','value':'83.4','change':'+2.2'}]}),
  'two_column': ('two_column', {'index':3,'title':'Before and after',
      'left':{'heading':'Dense attention','content':'Quadratic memory growth limits context to 4k on a single device.'},
      'right':{'heading':'Sparse attention','content':'Linear memory growth reaches 32k context with a 2.1x throughput gain.'}}),
  'timeline': ('timeline', {'index':4,'title':'Project schedule',
      'events':[{'label':'kickoff','date':'2026-01','detail':'scope agreed'},
                {'label':'first results','date':'2026-04','detail':'baseline reproduced'},
                {'label':'midpoint review','date':'2026-06','detail':'sweep complete'},
                {'label':'submission','date':'2026-09','detail':'paper submitted'}]}),
}
for name, (kind, payload) in cases.items():
    svg = gs.RENDERERS[kind](payload, {'footer':'deck 5/8'})
    (out / f'{name}.svg').write_text(svg, encoding='utf-8')
    cairosvg.svg2png(bytestring=svg.encode('utf-8'),
                     write_to=str(out / f'{name}.png'),
                     output_width=1600, output_height=900)
    print('wrote', out / f'{name}.png')
"
```

Open each PNG and confirm: table cells are not clipped horizontally, metric values
dominate their cards without touching the edges, two-column body text does not
overflow its panel, and timeline labels do not overlap. Fix geometry, never sizes.

- [x] **Step 10: Run the existing suite**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/tests/ -q`
Expected: PASS. Any fixture with a table longer than the new capacity now raises
`SlideCapacityError` by design; split that fixture across slides and say so in the
commit message.

- [x] **Step 11: Commit**

```bash
git add skills/report-slides/scripts/generate_slides.py \
        skills/report-slides/scripts/tests/
git commit -m "feat(report-slides): typeset layout renderers at presentation scale"
```

---

## Phase 3: SVG→PPTX Export Fidelity

---

### Task 10: Preserve multi-word font families and resolve to an installed face

**Files:**
- Modify: `skills/report-slides/scripts/svg_to_pptx/shapes.py` (`_apply_font`, lines 200–220)
- Test: `skills/report-slides/scripts/svg_to_pptx/tests/test_shapes.py` (append)

**Interfaces:**
- Consumes: `fonts.parse_font_stack`, `fonts.resolve_font_stack`,
  `fonts.FontError` (Task 5).
- Produces: no new public symbol; `_apply_font` behaviour changes.

**The defect.** `shapes.py:217-220` reads:

```python
    ff = style.get("font-family", parent_style.get("font-family", ""))
    if ff:
        first = re.split(r"[,\s]+", ff.strip())[0].strip("'\"")
        if first:
            run.font.name = first
```

Splitting on `[,\s]+` breaks any multi-word family. The default style font
`'Helvetica Neue', Arial, sans-serif` yields `run.font.name = "Helvetica"` — a
face installed on neither Linux nor the token stack — so the PPTX renders with a
silent substitution while the SVG preview shows something else (spec §2.3).

**Migration consequence.** After this change, converting an SVG whose entire font
stack is uninstalled raises `FontError` instead of silently substituting. That is
intended: a substituted face changes every text extent on the slide. Task 6 makes
the deterministic renderer emit only resolved families, so this only affects
hand-authored SVG, where the failure is actionable — install the font or change
the stack.

- [x] **Step 1: Write the failing test**

Append to `skills/report-slides/scripts/svg_to_pptx/tests/test_shapes.py`:

```python
def test_multi_word_font_family_is_not_truncated():
    """A quoted multi-word family is never split into its first word."""
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<text x="100" y="100" font-size="21" '
        "font-family=\"'DejaVu Sans', Arial, sans-serif\">Node</text>"
    )
    style = compute_style(elem, {})
    from svg_to_pptx.shapes import _write_label
    shape = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(1000000), Emu(500000))
    _write_label(shape, elem, style, CS, (100, 100, 200, 40))
    name = shape.text_frame.paragraphs[0].runs[0].font.name
    assert name == "DejaVu Sans"
    assert name != "DejaVu"


def test_uninstalled_first_family_falls_through_to_installed_one():
    """Resolution skips an uninstalled first choice rather than using it."""
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<text x="100" y="100" font-size="21" '
        "font-family=\"Totally Not A Real Font 9x7, 'DejaVu Sans'\">Node</text>"
    )
    style = compute_style(elem, {})
    from svg_to_pptx.shapes import _write_label
    shape = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(1000000), Emu(500000))
    _write_label(shape, elem, style, CS, (100, 100, 200, 40))
    assert shape.text_frame.paragraphs[0].runs[0].font.name == "DejaVu Sans"


def test_fully_uninstalled_stack_raises():
    """A stack with no installed family raises rather than substituting."""
    from fonts import FontError
    from svg_to_pptx.shapes import _write_label
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<text x="100" y="100" font-size="21" '
        'font-family="Nope One 9x7, \'Nope Two 9x7\'">Node</text>'
    )
    style = compute_style(elem, {})
    shape = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(1000000), Emu(500000))
    with pytest.raises(FontError):
        _write_label(shape, elem, style, CS, (100, 100, 200, 40))


def test_absent_font_family_leaves_the_run_name_unset():
    """No font-family attribute means no explicit run font name."""
    from svg_to_pptx.shapes import _write_label
    slide, _ = _blank_slide()
    elem = etree.fromstring('<text x="100" y="100" font-size="21">Node</text>')
    style = compute_style(elem, {})
    shape = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(1000000), Emu(500000))
    _write_label(shape, elem, style, CS, (100, 100, 200, 40))
    assert shape.text_frame.paragraphs[0].runs[0].font.name is None
```

Add `from pathlib import Path` and the scripts directory to `sys.path` at the top
of the test file if not already present, so `fonts` is importable:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
```

- [x] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/svg_to_pptx/tests/test_shapes.py -v -k "font_family or font_famil or uninstalled or truncated"`
Expected: FAIL — `assert 'DejaVu' == 'DejaVu Sans'` on the first test, because the
current code truncates at the space.

- [x] **Step 3: Fix `_apply_font`**

In `skills/report-slides/scripts/svg_to_pptx/shapes.py`, replace lines 217–220
with:

```python
    ff = style.get("font-family", parent_style.get("font-family", ""))
    if ff and parse_font_stack(ff):
        # Resolve to a family that is actually installed. Taking the first
        # listed family, or splitting on whitespace, silently substitutes a
        # different face and desynchronises the SVG preview from the PPTX.
        run.font.name = resolve_font_stack(ff)
```

Add the import at the top of the file:

```python
from fonts import parse_font_stack, resolve_font_stack
```

- [x] **Step 4: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/svg_to_pptx/tests/test_shapes.py -v`
Expected: PASS — all tests green.

- [x] **Step 5: Run the converter suite**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/svg_to_pptx/tests/ -q`
Expected: PASS. Fixtures whose SVG declares only uninstalled families now raise;
change those fixtures to a stack containing `DejaVu Sans` and say why in the
commit message.

- [x] **Step 6: Commit**

```bash
git add skills/report-slides/scripts/svg_to_pptx/shapes.py \
        skills/report-slides/scripts/svg_to_pptx/tests/test_shapes.py
git commit -m "fix(report-slides): resolve SVG font stacks to installed faces in PPTX export"
```

---

### Task 11: Export rounded rectangles as rounded rectangles

**Files:**
- Modify: `skills/report-slides/scripts/svg_to_pptx/shapes.py` (`_add_rect`, lines 29–45)
- Test: `skills/report-slides/scripts/svg_to_pptx/tests/test_shapes.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: no new public symbol; `_add_rect` behaviour changes.

**The defect.** `_add_rect` always calls `slide.shapes.add_shape(1, ...)`, which is
`MSO_SHAPE.RECTANGLE`, and never reads `rx`/`ry`. Every rounded card authored in
SVG — and the token contract gives `node` an 8-unit radius and `card` a 12-unit
radius — exports as a sharp box (spec §2.4).

**Verified PowerPoint semantics.** `MSO_SHAPE.ROUNDED_RECTANGLE` is shape id `5`
and carries exactly one adjustment, default `0.16667`, serialised as
`<a:gd name="adj" fmla="val 16667"/>`. The adjustment is the corner radius as a
fraction of the shorter side, so `adjustment = rx / min(width, height)`, clamped
to `0.5` (a stadium). Both facts were checked against `python-pptx` before this
plan was written.

- [x] **Step 1: Write the failing test**

Append to `skills/report-slides/scripts/svg_to_pptx/tests/test_shapes.py`:

```python
def test_sharp_rect_stays_a_rectangle():
    """A rect with no rx keeps the plain rectangle geometry."""
    slide, _ = _blank_slide()
    elem = etree.fromstring('<rect x="0" y="0" width="200" height="100" fill="#fff"/>')
    style = compute_style(elem, {})
    dispatch_shape(slide, elem, style, CS, None)
    prst = slide.shapes[0]._element.find(
        ".//{http://schemas.openxmlformats.org/drawingml/2006/main}prstGeom"
    ).get("prst")
    assert prst == "rect"


def test_rounded_rect_becomes_round_rect_geometry():
    """A rect with rx exports as roundRect, not a sharp box."""
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<rect x="0" y="0" width="200" height="100" rx="8" fill="#fff"/>'
    )
    style = compute_style(elem, {})
    dispatch_shape(slide, elem, style, CS, None)
    prst = slide.shapes[0]._element.find(
        ".//{http://schemas.openxmlformats.org/drawingml/2006/main}prstGeom"
    ).get("prst")
    assert prst == "roundRect"


def test_rounded_rect_adjustment_matches_the_svg_radius():
    """The corner adjustment is rx as a fraction of the shorter side."""
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<rect x="0" y="0" width="200" height="100" rx="10" fill="#fff"/>'
    )
    style = compute_style(elem, {})
    dispatch_shape(slide, elem, style, CS, None)
    # rx=10 against a 100-unit shorter side -> 0.10
    assert slide.shapes[0].adjustments[0] == pytest.approx(0.10, abs=0.005)


def test_rounded_rect_adjustment_is_clamped_to_a_stadium():
    """An rx larger than half the shorter side clamps instead of overflowing."""
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<rect x="0" y="0" width="200" height="100" rx="400" fill="#fff"/>'
    )
    style = compute_style(elem, {})
    dispatch_shape(slide, elem, style, CS, None)
    assert slide.shapes[0].adjustments[0] == pytest.approx(0.5, abs=0.001)


def test_ry_alone_also_rounds_the_rect():
    """SVG allows ry without rx; both must round the shape."""
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<rect x="0" y="0" width="200" height="100" ry="8" fill="#fff"/>'
    )
    style = compute_style(elem, {})
    dispatch_shape(slide, elem, style, CS, None)
    prst = slide.shapes[0]._element.find(
        ".//{http://schemas.openxmlformats.org/drawingml/2006/main}prstGeom"
    ).get("prst")
    assert prst == "roundRect"
```

- [x] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/svg_to_pptx/tests/test_shapes.py -v -k "round or sharp or ry_alone"`
Expected: FAIL — `assert 'rect' == 'roundRect'`, because `_add_rect` hard-codes
shape id `1`.

- [x] **Step 3: Read the radius and pick the geometry**

Replace `_add_rect` (lines 29–45) in
`skills/report-slides/scripts/svg_to_pptx/shapes.py` with:

```python
_MSO_RECTANGLE = 1
_MSO_ROUNDED_RECTANGLE = 5
_MAX_CORNER_ADJUSTMENT = 0.5


def _corner_radius(elem: Any) -> float:
    """Return the SVG corner radius of a rect element.

    SVG permits `rx` alone, `ry` alone, or both; a single value mirrors to the
    other axis. PowerPoint's roundRect has one symmetric radius, so the larger
    of the two is used.

    Args:
        elem: The `<rect>` element.

    Returns:
        The corner radius in SVG units; 0 when the rect is sharp.
    """
    values = []
    for attr in ("rx", "ry"):
        raw = elem.get(attr)
        if raw is None:
            continue
        try:
            values.append(abs(float(raw)))
        except ValueError:
            # A malformed radius must not silently become a sharp corner.
            raise ValueError(
                f"rect has non-numeric {attr}={raw!r}; fix the SVG source"
            )
    return max(values) if values else 0.0


def _add_rect(slide: Any, elem: Any, style: Dict,
              cs: CoordSystem, label_elem: Optional[Any]) -> Any:
    """Add one SVG rect to the slide as a native PPTX shape.

    A rect carrying `rx` or `ry` becomes a roundRect whose corner adjustment
    reproduces the authored radius, so token surface radii survive export.

    Args:
        slide: Target PPTX slide.
        elem: The `<rect>` element.
        style: Computed style mapping for the element.
        cs: Coordinate system mapping SVG units to EMU.
        label_elem: Optional `<text>` element to write into the shape.

    Returns:
        The created PPTX shape.
    """
    svg_x = float(elem.get("x", 0))
    svg_y = float(elem.get("y", 0))
    svg_w = float(elem.get("width", 0))
    svg_h = float(elem.get("height", 0))
    x = cs.x(svg_x)
    y = cs.y(svg_y)
    w = max(1, cs.x(svg_w))
    h = max(1, cs.y(svg_h))

    radius = _corner_radius(elem)
    shorter = min(svg_w, svg_h)
    if radius > 0 and shorter > 0:
        shape = slide.shapes.add_shape(
            _MSO_ROUNDED_RECTANGLE, Emu(x), Emu(y), Emu(w), Emu(h))
        shape.adjustments[0] = min(radius / shorter, _MAX_CORNER_ADJUSTMENT)
    else:
        shape = slide.shapes.add_shape(
            _MSO_RECTANGLE, Emu(x), Emu(y), Emu(w), Emu(h))

    apply_fill(shape, style.get("fill", "black"))
    apply_stroke(shape, style)
    if label_elem is not None:
        _write_label(shape, label_elem, style, cs,
                     (svg_x, svg_y, svg_w, svg_h))
    return shape
```

- [x] **Step 4: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/svg_to_pptx/tests/test_shapes.py -v`
Expected: PASS — all tests green.

- [x] **Step 5: Confirm the whole converter suite still passes**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/svg_to_pptx/tests/ -q`
Expected: PASS. A test asserting `prst == "rect"` for a rect that does carry `rx`
was encoding the bug; update it and say so in the commit message.

- [x] **Step 6: Commit**

```bash
git add skills/report-slides/scripts/svg_to_pptx/shapes.py \
        skills/report-slides/scripts/svg_to_pptx/tests/test_shapes.py
git commit -m "fix(report-slides): export SVG rounded rects as native roundRect geometry"
```

---

### Task 12: Connector arrowheads

**Files:**
- Modify: `skills/report-slides/scripts/svg_to_pptx/style_parser.py` (`_STYLE_ATTRS` line 66; add line-end helpers)
- Modify: `skills/report-slides/scripts/svg_to_pptx/connector.py` (`_add_line`, lines 57–68)
- Test: `skills/report-slides/scripts/svg_to_pptx/tests/test_connector.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces, in `style_parser`:
  - `LINE_END_TYPES: frozenset` — `{"none", "triangle", "stealth", "arrow", "oval", "diamond"}`
  - `LINE_END_SIZES: dict` — `{"small": "sm", "medium": "med", "large": "lg"}`
  - `ensure_ln_child(ln: Any, tag: str) -> Any` — insert-or-get an `a:ln` child in
    DrawingML schema order
  - `apply_line_ends(shape: Any, style: Dict[str, str]) -> None`

  Task 13 reuses `ensure_ln_child` for `a:prstDash`.

**The defect.** `connector.py:57-68` sets only line colour and width;
`marker-start` and `marker-end` are never parsed, and `_STYLE_ATTRS` does not
collect them. Architecture diagrams therefore export with headless lines, or with
arrowheads drawn as separate polygons that detach from the connector when it moves
(spec §2.5).

**Why child order matters.** DrawingML's `CT_LineProperties` fixes the child
sequence: a fill (`a:noFill`/`a:solidFill`/`a:gradFill`/`a:pattFill`), then a dash
(`a:prstDash`/`a:custDash`), then a join (`a:round`/`a:bevel`/`a:miter`), then
`a:headEnd`, then `a:tailEnd`. Appending blindly produces a file PowerPoint often
tolerates but LibreOffice — the renderer this skill's review gate uses — may not.
`ensure_ln_child` therefore inserts by position, not by append.

**Marker mapping.** An SVG `marker-end="url(#id)"` names a marker element, whose
shape this converter cannot introspect reliably. The rule is: a non-`none` marker
reference produces an arrowhead, and its type is declared on the **connector
element itself** — `data-pptx-arrowhead` for both ends, or
`data-pptx-arrowhead-start` / `data-pptx-arrowhead-end` to differ. It defaults
to `triangle`. An unknown explicit value is an error, not a silent default.

Putting the declaration on the connector rather than on the `<marker>` is
deliberate and is what Task 15 tells hand-authors to write: one `<marker>` in
`<defs>` is typically shared by every connector on the slide, so an attribute
there cannot express "this one ends in a stealth arrow and that one does not",
and resolving through `<defs>` would make a connector's appearance depend on an
element nowhere near it.

**Polylines.** `connector.py:41-52` converts a `<polyline>` into one connector
per segment, all sharing one style mapping. Arrowheads must therefore be applied
by the *dispatcher*, which knows which segment is first and which is last, and
not inside `_add_line`, which sees one segment and cannot tell. Calling it per
segment puts an arrowhead in the middle of every elbow connector on the slide.

- [x] **Step 1: Write the failing test**

Append to `skills/report-slides/scripts/svg_to_pptx/tests/test_connector.py`:

```python
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _line_ends(conn):
    """Return (headEnd, tailEnd) elements of a connector's line properties."""
    ln = conn._element.find(f".//{_A}ln")
    if ln is None:
        return None, None
    return ln.find(f"{_A}headEnd"), ln.find(f"{_A}tailEnd")


def test_plain_line_has_no_arrowheads():
    """A line without marker attributes exports without arrowheads."""
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<line x1="0" y1="0" x2="100" y2="0" stroke="#475569" stroke-width="2"/>'
    )
    style = compute_style(elem, {})
    conns = dispatch_connector(slide, elem, style, CS)
    head, tail = _line_ends(conns[0])
    assert head is None
    assert tail is None


def test_marker_end_produces_a_tail_arrowhead():
    """marker-end becomes an OOXML tailEnd triangle."""
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<line x1="0" y1="0" x2="100" y2="0" stroke="#475569" '
        'stroke-width="2" marker-end="url(#arrow)"/>'
    )
    style = compute_style(elem, {})
    conns = dispatch_connector(slide, elem, style, CS)
    head, tail = _line_ends(conns[0])
    assert head is None
    assert tail is not None
    assert tail.get("type") == "triangle"


def test_marker_start_produces_a_head_arrowhead():
    """marker-start becomes an OOXML headEnd."""
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<line x1="0" y1="0" x2="100" y2="0" stroke="#475569" '
        'stroke-width="2" marker-start="url(#arrow)"/>'
    )
    style = compute_style(elem, {})
    conns = dispatch_connector(slide, elem, style, CS)
    head, tail = _line_ends(conns[0])
    assert head is not None
    assert head.get("type") == "triangle"
    assert tail is None


def test_marker_none_is_not_an_arrowhead():
    """An explicit marker-end="none" adds nothing."""
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<line x1="0" y1="0" x2="100" y2="0" stroke="#475569" '
        'stroke-width="2" marker-end="none"/>'
    )
    style = compute_style(elem, {})
    conns = dispatch_connector(slide, elem, style, CS)
    _, tail = _line_ends(conns[0])
    assert tail is None


def test_explicit_arrowhead_type_is_honoured():
    """data-pptx-arrowhead on the element overrides the triangle default."""
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<line x1="0" y1="0" x2="100" y2="0" stroke="#475569" stroke-width="2" '
        'marker-end="url(#a)" data-pptx-arrowhead="stealth"/>'
    )
    style = compute_style(elem, {})
    conns = dispatch_connector(slide, elem, style, CS)
    _, tail = _line_ends(conns[0])
    assert tail.get("type") == "stealth"


def test_unknown_arrowhead_type_raises():
    """An unrecognised arrowhead name is an error, not a silent default."""
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<line x1="0" y1="0" x2="100" y2="0" stroke="#475569" stroke-width="2" '
        'marker-end="url(#a)" data-pptx-arrowhead="harpoon"/>'
    )
    style = compute_style(elem, {})
    with pytest.raises(ValueError) as excinfo:
        dispatch_connector(slide, elem, style, CS)
    assert "harpoon" in str(excinfo.value)


def test_a_polyline_carries_arrowheads_only_at_its_ends():
    """An elbow connector has two ends, not one per bend.

    `dispatch_connector` turns a polyline into one connector per segment. If the
    arrowhead is applied per segment, a four-point elbow -- the standard shape
    for routing around a node in an architecture diagram -- exports with three
    arrowheads pointing into the middle of itself.
    """
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<polyline points="0,0 100,0 100,80 200,80" stroke="#475569" '
        'stroke-width="2" marker-end="url(#a)"/>'
    )
    style = compute_style(elem, {})
    conns = dispatch_connector(slide, elem, style, CS)
    assert len(conns) == 3
    tails = [_line_ends(conn)[1] for conn in conns]
    assert [tail is not None for tail in tails] == [False, False, True]


def test_a_closed_polygon_has_no_arrowheads():
    """A polygon has no ends, so a marker on it declares nothing to apply."""
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<polygon points="0,0 100,0 50,80" stroke="#475569" '
        'stroke-width="2" marker-end="url(#a)"/>'
    )
    style = compute_style(elem, {})
    conns = dispatch_connector(slide, elem, style, CS)
    assert all(_line_ends(conn) == (None, None) for conn in conns)


def test_the_two_ends_can_differ():
    """A connector may start plain and end in a stealth arrow."""
    slide, _ = _blank_slide()
    elem = etree.fromstring(
        '<line x1="0" y1="0" x2="100" y2="0" stroke="#475569" stroke-width="2" '
        'marker-start="url(#a)" marker-end="url(#a)" '
        'data-pptx-arrowhead-start="oval" data-pptx-arrowhead-end="stealth"/>'
    )
    style = compute_style(elem, {})
    conns = dispatch_connector(slide, elem, style, CS)
    head, tail = _line_ends(conns[0])
    assert head.get("type") == "oval"
    assert tail.get("type") == "stealth"


def test_ensure_ln_child_keeps_schema_order():
    """Line-property children are inserted in DrawingML's required order."""
    from svg_to_pptx.style_parser import ensure_ln_child
    slide, _ = _blank_slide()
    conn = slide.shapes.add_connector(1, Emu(0), Emu(0), Emu(100000), Emu(0))
    ln = conn.line._get_or_add_ln()
    # Deliberately request them out of order.
    ensure_ln_child(ln, "a:tailEnd")
    ensure_ln_child(ln, "a:prstDash")
    ensure_ln_child(ln, "a:headEnd")
    ensure_ln_child(ln, "a:solidFill")
    tags = [child.tag.split("}")[-1] for child in ln]
    assert tags == ["solidFill", "prstDash", "headEnd", "tailEnd"]
```

Ensure the test file imports `pytest`, `Emu`, and `dispatch_connector`; add any
missing import at the top.

- [x] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/svg_to_pptx/tests/test_connector.py -v -k "arrowhead or marker or ln_child"`
Expected: FAIL — `ImportError: cannot import name 'ensure_ln_child'`, and the
marker tests fail because no `tailEnd` is produced.

- [x] **Step 3: Collect the marker attributes**

In `skills/report-slides/scripts/svg_to_pptx/style_parser.py`, extend
`_STYLE_ATTRS` (line 66) with the marker and arrowhead attributes:

```python
_STYLE_ATTRS = (
    "fill", "stroke", "stroke-width", "stroke-dasharray", "opacity",
    "font-size", "font-weight", "font-style", "font-family", "text-anchor",
    "transform", "fill-opacity", "stroke-opacity",
    "marker-start", "marker-end",
    "data-pptx-arrowhead", "data-pptx-arrowhead-size",
    "data-pptx-arrowhead-start", "data-pptx-arrowhead-end",
)
```

- [x] **Step 4: Add the line-end helpers**

Append to `skills/report-slides/scripts/svg_to_pptx/style_parser.py`:

```python
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

# DrawingML CT_LineProperties fixes this child order. Inserting out of order
# yields a file PowerPoint often tolerates but LibreOffice may reject.
_LN_CHILD_ORDER = (
    "a:noFill", "a:solidFill", "a:gradFill", "a:pattFill",
    "a:prstDash", "a:custDash",
    "a:round", "a:bevel", "a:miter",
    "a:headEnd", "a:tailEnd",
)

LINE_END_TYPES = frozenset(
    {"none", "triangle", "stealth", "arrow", "oval", "diamond"}
)
LINE_END_SIZES = {"small": "sm", "medium": "med", "large": "lg"}


def _qn_a(tag: str) -> str:
    """Return the namespaced form of an `a:`-prefixed DrawingML tag name.

    Args:
        tag: A tag name such as `a:tailEnd`.

    Returns:
        The `{namespace}local` form.

    Raises:
        ValueError: If the tag is not `a:`-prefixed.
    """
    if not tag.startswith("a:"):
        raise ValueError(f"expected an 'a:'-prefixed tag, got {tag!r}")
    return f"{{{_A_NS}}}{tag[2:]}"


def ensure_ln_child(ln: Any, tag: str) -> Any:
    """Get or insert a child of `a:ln`, preserving DrawingML schema order.

    Args:
        ln: The `a:ln` element.
        tag: An `a:`-prefixed child tag name from `_LN_CHILD_ORDER`.

    Returns:
        The existing or newly inserted child element.

    Raises:
        ValueError: If the tag is not a known line-property child.
    """
    if tag not in _LN_CHILD_ORDER:
        raise ValueError(
            f"unknown line-property child {tag!r}; "
            f"expected one of {_LN_CHILD_ORDER}"
        )
    qualified = _qn_a(tag)
    existing = ln.find(qualified)
    if existing is not None:
        return existing
    rank = _LN_CHILD_ORDER.index(tag)
    element = etree.Element(qualified)
    for position, child in enumerate(ln):
        child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        prefixed = f"a:{child_tag}"
        if prefixed in _LN_CHILD_ORDER and _LN_CHILD_ORDER.index(prefixed) > rank:
            ln.insert(position, element)
            return element
    ln.append(element)
    return element


def _requested_line_end(marker_value: str) -> bool:
    """Return whether a marker attribute value asks for an arrowhead.

    Args:
        marker_value: The raw `marker-start` or `marker-end` value.

    Returns:
        True for a `url(#id)` reference, False for absent/`none`.
    """
    value = (marker_value or "").strip().lower()
    return bool(value) and value != "none"


def _end_type(style: Dict[str, str], which: str) -> str:
    """Resolve one end's arrowhead type.

    Args:
        style: Computed style mapping for the SVG connector element.
        which: `start` or `end`.

    Returns:
        A validated OOXML line-end type name.

    Raises:
        ValueError: If the declared type is unrecognised.
    """
    declared = (
        style.get(f"data-pptx-arrowhead-{which}")
        or style.get("data-pptx-arrowhead")
        or "triangle"
    )
    end_type = declared.strip().lower()
    if end_type not in LINE_END_TYPES:
        raise ValueError(
            f"unknown arrowhead type {end_type!r}; "
            f"expected one of {sorted(LINE_END_TYPES)}"
        )
    return end_type


def apply_line_ends(
    shape: Any, style: Dict[str, str], *, head: bool = True, tail: bool = True
) -> None:
    """Apply SVG marker attributes to one connector as OOXML arrowheads.

    An SVG `<marker>` element's geometry cannot be introspected reliably, so any
    `url(#id)` reference produces an arrowhead. Its type is declared on the
    connector element -- `data-pptx-arrowhead-start`, `data-pptx-arrowhead-end`,
    or `data-pptx-arrowhead` for both -- and defaults to `triangle`.

    Args:
        shape: A PPTX connector or shape with line properties.
        style: Computed style mapping for the SVG element.
        head: Whether this shape carries the connector's start. False for every
            segment of a polyline except the first.
        tail: Whether this shape carries the connector's end. False for every
            segment of a polyline except the last.

    Raises:
        ValueError: If an explicit arrowhead type or size is unrecognised.
    """
    wants_head = head and _requested_line_end(style.get("marker-start", ""))
    wants_tail = tail and _requested_line_end(style.get("marker-end", ""))
    if not (wants_head or wants_tail):
        return

    size_name = (style.get("data-pptx-arrowhead-size") or "medium").strip().lower()
    if size_name not in LINE_END_SIZES:
        raise ValueError(
            f"unknown arrowhead size {size_name!r}; "
            f"expected one of {sorted(LINE_END_SIZES)}"
        )
    ooxml_size = LINE_END_SIZES[size_name]

    ln = shape.line._get_or_add_ln()
    for wanted, which, tag in ((wants_head, "start", "a:headEnd"),
                               (wants_tail, "end", "a:tailEnd")):
        if not wanted:
            continue
        end_type = _end_type(style, which)
        if end_type == "none":
            continue
        element = ensure_ln_child(ln, tag)
        element.set("type", end_type)
        element.set("w", ooxml_size)
        element.set("len", ooxml_size)
```

- [x] **Step 5: Call it from the connector dispatcher, not from `_add_line`**

In `skills/report-slides/scripts/svg_to_pptx/connector.py`, add
`apply_line_ends` to the existing import from `.style_parser`. Call it from
`dispatch_connector`, which is the only place that knows which segment is the
connector's start and which is its end. `_add_line` sees one segment and would
put an arrowhead on all of them.

Replace the `line` branch's `return` (line 40) with:

```python
        conn = _add_line(slide, cs.x(x1), cs.y(y1), cs.x(x2), cs.y(y2), style)
        apply_line_ends(conn, style)
        return [conn]
```

and, in the `polyline`/`polygon` branch, after the segment loop and the closing
segment, before `return connectors`:

```python
        if connectors:
            # A polyline is one connector drawn as many segments. Only its two
            # ends carry arrowheads; a closed polygon has no ends at all.
            if not closed:
                apply_line_ends(connectors[0], style, head=True, tail=False)
                apply_line_ends(connectors[-1], style, head=False, tail=True)
```

The old instruction to call it inside `_add_line` immediately before
`return conn` would have produced an arrowhead on every segment of every elbow
connector, which is most connectors in an architecture diagram.

```python
    apply_line_ends(conn, style)
    return conn
```

- [x] **Step 6: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/svg_to_pptx/tests/test_connector.py -v`
Expected: PASS — all tests green.

- [x] **Step 7: Run the converter suite**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/svg_to_pptx/tests/ -q`
Expected: PASS.

- [x] **Step 8: Commit**

```bash
git add skills/report-slides/scripts/svg_to_pptx/style_parser.py \
        skills/report-slides/scripts/svg_to_pptx/connector.py \
        skills/report-slides/scripts/svg_to_pptx/tests/test_connector.py
git commit -m "feat(report-slides): export SVG markers as native PPTX arrowheads"
```

---

### Task 13: Dash patterns and opacity

**Files:**
- Modify: `skills/report-slides/scripts/svg_to_pptx/style_parser.py` (`apply_fill` lines 113–121, `apply_stroke` lines 120–133; add dash and alpha helpers)
- Test: `skills/report-slides/scripts/svg_to_pptx/tests/test_style_parser.py` (append)

**Interfaces:**
- Consumes: `ensure_ln_child` (Task 12).
- Produces:
  - `PRST_DASH_VALUES: frozenset`
  - `dash_style_for(dasharray: str, stroke_width: float) -> Optional[str]`
  - `apply_dash(shape: Any, style: Dict[str, str]) -> None`
  - `apply_alpha(shape: Any, style: Dict[str, str]) -> None`

**The defect.** `_STYLE_ATTRS` collects `stroke-dasharray`, `opacity`,
`fill-opacity`, and `stroke-opacity` into every style dict, and no code path ever
applies any of them (spec §2.6). A dashed boundary authored in SVG exports solid,
and a translucent overlay exports fully opaque — which changes what the slide
appears to say.

**Dash mapping.** OOXML has a preset enum, not arbitrary dash arrays, so the
mapping is by pattern shape relative to stroke width:

| SVG dasharray | Condition | `prstDash` |
|---|---|---|
| absent or `none` | — | not set (solid) |
| two values | `dash / stroke_width <= 2` | `sysDot` |
| two values | `dash / stroke_width <= 6` | `dash` |
| two values | otherwise | `lgDash` |
| four values | — | `dashDot` |
| six values | — | `lgDashDotDot` |

With the token defaults (`stroke_width: 2`, `dashed: "8 4"`, `dotted: "2 4"`),
`dashed` maps to `dash` and `dotted` maps to `sysDot`.

- [x] **Step 1: Write the failing test**

Append to `skills/report-slides/scripts/svg_to_pptx/tests/test_style_parser.py`:

```python
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def test_dash_style_for_token_patterns():
    """The token dash patterns map to the intended OOXML presets."""
    from svg_to_pptx.style_parser import dash_style_for
    assert dash_style_for("", 2) is None
    assert dash_style_for("none", 2) is None
    assert dash_style_for("2 4", 2) == "sysDot"
    assert dash_style_for("8 4", 2) == "dash"
    assert dash_style_for("40 8", 2) == "lgDash"
    assert dash_style_for("8 4 2 4", 2) == "dashDot"
    assert dash_style_for("20 4 2 4 2 4", 2) == "lgDashDotDot"


def test_dash_style_for_rejects_malformed_array():
    """A non-numeric dasharray is an error, not a silent solid line."""
    from svg_to_pptx.style_parser import dash_style_for
    with pytest.raises(ValueError):
        dash_style_for("8 wide", 2)


def test_apply_dash_sets_prst_dash_in_schema_order():
    """apply_dash writes a:prstDash before any line-end child."""
    from svg_to_pptx.style_parser import apply_dash, apply_line_ends
    slide, _ = _blank_slide()
    conn = slide.shapes.add_connector(1, Emu(0), Emu(0), Emu(100000), Emu(0))
    style = {"stroke": "#475569", "stroke-width": "2",
             "stroke-dasharray": "8 4", "marker-end": "url(#a)"}
    apply_line_ends(conn, style)
    apply_dash(conn, style)
    ln = conn._element.find(f".//{_A}ln")
    tags = [child.tag.split("}")[-1] for child in ln]
    assert "prstDash" in tags
    assert tags.index("prstDash") < tags.index("tailEnd")
    assert ln.find(f"{_A}prstDash").get("val") == "dash"


def test_apply_dash_leaves_solid_lines_alone():
    """No dasharray means no prstDash element at all."""
    from svg_to_pptx.style_parser import apply_dash
    slide, _ = _blank_slide()
    conn = slide.shapes.add_connector(1, Emu(0), Emu(0), Emu(100000), Emu(0))
    apply_dash(conn, {"stroke": "#475569", "stroke-width": "2"})
    ln = conn._element.find(f".//{_A}ln")
    assert ln is None or ln.find(f"{_A}prstDash") is None


def test_apply_alpha_sets_fill_transparency():
    """fill-opacity becomes an a:alpha child of the fill colour."""
    from svg_to_pptx.style_parser import apply_alpha, apply_fill
    slide, _ = _blank_slide()
    shape = slide.shapes.add_shape(1, Emu(0), Emu(0), Emu(100000), Emu(100000))
    style = {"fill": "#3b82f6", "fill-opacity": "0.25"}
    apply_fill(shape, style["fill"])
    apply_alpha(shape, style)
    alpha = shape._element.find(f".//{_A}solidFill/{_A}srgbClr/{_A}alpha")
    assert alpha is not None
    assert alpha.get("val") == "25000"


def test_apply_alpha_multiplies_opacity_and_fill_opacity():
    """opacity and fill-opacity compose multiplicatively."""
    from svg_to_pptx.style_parser import apply_alpha, apply_fill
    slide, _ = _blank_slide()
    shape = slide.shapes.add_shape(1, Emu(0), Emu(0), Emu(100000), Emu(100000))
    apply_fill(shape, "#3b82f6")
    apply_alpha(shape, {"fill": "#3b82f6", "opacity": "0.5", "fill-opacity": "0.5"})
    alpha = shape._element.find(f".//{_A}solidFill/{_A}srgbClr/{_A}alpha")
    assert alpha.get("val") == "25000"


def test_apply_alpha_is_a_no_op_at_full_opacity():
    """An opaque element gains no alpha element."""
    from svg_to_pptx.style_parser import apply_alpha, apply_fill
    slide, _ = _blank_slide()
    shape = slide.shapes.add_shape(1, Emu(0), Emu(0), Emu(100000), Emu(100000))
    apply_fill(shape, "#3b82f6")
    apply_alpha(shape, {"fill": "#3b82f6"})
    assert shape._element.find(f".//{_A}solidFill/{_A}srgbClr/{_A}alpha") is None


def test_apply_alpha_rejects_out_of_range_opacity():
    """An opacity outside 0..1 is an error rather than being clamped silently."""
    from svg_to_pptx.style_parser import apply_alpha, apply_fill
    slide, _ = _blank_slide()
    shape = slide.shapes.add_shape(1, Emu(0), Emu(0), Emu(100000), Emu(100000))
    apply_fill(shape, "#3b82f6")
    with pytest.raises(ValueError):
        apply_alpha(shape, {"fill": "#3b82f6", "fill-opacity": "1.5"})
```

Add `_blank_slide` to this test file if it is not already defined, matching the
helper in `test_shapes.py`, plus imports for `pytest` and `Emu`.

- [x] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/svg_to_pptx/tests/test_style_parser.py -v -k "dash or alpha"`
Expected: FAIL — `ImportError: cannot import name 'dash_style_for'`.

- [x] **Step 3: Add the dash and alpha helpers**

Append to `skills/report-slides/scripts/svg_to_pptx/style_parser.py`:

```python
PRST_DASH_VALUES = frozenset({
    "solid", "dot", "dash", "lgDash", "dashDot", "lgDashDot",
    "lgDashDotDot", "sysDash", "sysDot", "sysDashDot", "sysDashDotDot",
})


def dash_style_for(dasharray: str, stroke_width: float) -> Optional[str]:
    """Map an SVG stroke-dasharray to an OOXML preset dash name.

    OOXML carries a preset enum rather than arbitrary dash arrays, so the
    pattern is classified by its first dash length relative to the stroke
    width, and by how many values the array has.

    Args:
        dasharray: The raw `stroke-dasharray` value.
        stroke_width: Stroke width in SVG units; used as the scale reference.

    Returns:
        A `prstDash` value, or None when the stroke is solid.

    Raises:
        ValueError: If the array contains a non-numeric entry.
    """
    raw = (dasharray or "").strip()
    if not raw or raw.lower() == "none":
        return None
    parts = [token for token in re.split(r"[,\s]+", raw) if token]
    try:
        values = [float(token) for token in parts]
    except ValueError as exc:
        raise ValueError(
            f"malformed stroke-dasharray {dasharray!r}: {exc}"
        ) from exc
    if not values:
        return None
    if len(values) >= 6:
        return "lgDashDotDot"
    if len(values) >= 4:
        return "dashDot"
    scale = stroke_width if stroke_width > 0 else 1.0
    ratio = values[0] / scale
    if ratio <= 2:
        return "sysDot"
    if ratio <= 6:
        return "dash"
    return "lgDash"


def apply_dash(shape: Any, style: Dict[str, str]) -> None:
    """Apply an SVG stroke-dasharray to a shape's line properties.

    Args:
        shape: A PPTX shape or connector.
        style: Computed style mapping for the SVG element.

    Raises:
        ValueError: If the dasharray is malformed.
    """
    width_raw = style.get("stroke-width", "1")
    try:
        stroke_width = float(re.sub(r"[^0-9.]", "", width_raw) or "1")
    except ValueError:
        stroke_width = 1.0
    dash = dash_style_for(style.get("stroke-dasharray", ""), stroke_width)
    if dash is None:
        return
    ln = shape.line._get_or_add_ln()
    ensure_ln_child(ln, "a:prstDash").set("val", dash)


def _opacity_factor(style: Dict[str, str], specific_key: str) -> float:
    """Compute the effective opacity for a fill or stroke.

    Args:
        style: Computed style mapping for the SVG element.
        specific_key: Either `fill-opacity` or `stroke-opacity`.

    Returns:
        The product of `opacity` and the specific opacity, in 0..1.

    Raises:
        ValueError: If either value is non-numeric or outside 0..1.
    """
    factor = 1.0
    for key in ("opacity", specific_key):
        raw = style.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            value = float(str(raw).strip())
        except ValueError as exc:
            raise ValueError(f"malformed {key}={raw!r}: {exc}") from exc
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{key}={raw!r} is outside the range 0..1")
        factor *= value
    return factor


def _set_alpha(color_elem: Any, factor: float) -> None:
    """Set an `a:alpha` child on a DrawingML colour element.

    Args:
        color_elem: An `a:srgbClr` element.
        factor: Opacity in 0..1.
    """
    qualified = _qn_a("a:alpha")
    existing = color_elem.find(qualified)
    if existing is not None:
        color_elem.remove(existing)
    alpha = etree.SubElement(color_elem, qualified)
    alpha.set("val", str(int(round(factor * 100000))))


def apply_alpha(shape: Any, style: Dict[str, str]) -> None:
    """Apply SVG opacity to a shape's fill and stroke colours.

    `opacity` composes multiplicatively with `fill-opacity` and
    `stroke-opacity`, matching SVG semantics. A fully opaque element is left
    untouched so the XML stays minimal.

    Args:
        shape: A PPTX shape or connector.
        style: Computed style mapping for the SVG element.

    Raises:
        ValueError: If an opacity value is malformed or out of range.
    """
    fill_factor = _opacity_factor(style, "fill-opacity")
    stroke_factor = _opacity_factor(style, "stroke-opacity")
    element = shape._element
    if fill_factor < 1.0:
        fill_color = element.find(
            f".//{{{_A_NS}}}solidFill/{{{_A_NS}}}srgbClr")
        if fill_color is not None:
            _set_alpha(fill_color, fill_factor)
    if stroke_factor < 1.0:
        line_color = element.find(
            f".//{{{_A_NS}}}ln/{{{_A_NS}}}solidFill/{{{_A_NS}}}srgbClr")
        if line_color is not None:
            _set_alpha(line_color, stroke_factor)
```

Add `Optional` to the `typing` import at the top of the file if it is not already
imported.

- [x] **Step 4: Call the helpers from every shape path**

In `skills/report-slides/scripts/svg_to_pptx/shapes.py`, extend the import from
`.style_parser` with `apply_alpha` and `apply_dash`, and call them after
`apply_stroke` in `_add_rect` and `_add_oval`:

```python
    apply_fill(shape, style.get("fill", "black"))
    apply_stroke(shape, style)
    apply_dash(shape, style)
    apply_alpha(shape, style)
```

In `skills/report-slides/scripts/svg_to_pptx/connector.py`, call them in
`_add_line` alongside `apply_line_ends`:

```python
    apply_dash(conn, style)
    apply_alpha(conn, style)
    apply_line_ends(conn, style)
    return conn
```

`apply_dash` must run before `apply_line_ends` only for readability; correctness
comes from `ensure_ln_child`, which inserts by schema position regardless of call
order — the test `test_apply_dash_sets_prst_dash_in_schema_order` proves it by
calling them in the reverse order.

In `skills/report-slides/scripts/svg_to_pptx/path_to_pptx.py`, apply the same two
calls wherever the module currently calls `apply_fill`/`apply_stroke`; read the
file to locate those sites.

- [x] **Step 5: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/svg_to_pptx/tests/ -v`
Expected: PASS — all tests green.

- [x] **Step 6: Commit**

```bash
git add skills/report-slides/scripts/svg_to_pptx/style_parser.py \
        skills/report-slides/scripts/svg_to_pptx/shapes.py \
        skills/report-slides/scripts/svg_to_pptx/connector.py \
        skills/report-slides/scripts/svg_to_pptx/path_to_pptx.py \
        skills/report-slides/scripts/svg_to_pptx/tests/
git commit -m "feat(report-slides): apply SVG dash patterns and opacity in PPTX export"
```

---

### Task 14: Wire gradient fills and remove the swallowed shape-registry error

**Files:**
- Modify: `skills/report-slides/scripts/svg_to_pptx/converter.py` (`_resolve_defs` lines 134–140; `_dispatch_element` shape-registry block lines 258–279; `_pptx_style` line 562)
- Modify: `skills/report-slides/scripts/svg_to_pptx/style_parser.py` (add `parse_linear_gradient`, `apply_paint`)
- Modify: `skills/report-slides/scripts/svg_to_pptx/shapes.py` (`_add_rect`, `_add_oval` — call `apply_paint`)
- Test: `skills/report-slides/scripts/svg_to_pptx/tests/test_integration.py` (append)

**Interfaces:**
- Consumes: `apply_gradient_fill` (already present at `style_parser.py:179`),
  `apply_fill`, `apply_alpha` (Task 13).
- Produces:
  - `parse_linear_gradient(elem: Any) -> tuple[list[tuple[str, str]], float]` —
    `(stops, angle_degrees)`
  - `apply_paint(shape: Any, style: Dict[str, str]) -> None` — dispatches to
    `apply_gradient_fill` or `apply_fill`
  - `SvgConverter._gradient_defs: Dict[str, tuple[list, float]]`

**Two defects, one task.** They sit in the same code path.

1. **Dead gradient support (spec §2.6).** `apply_gradient_fill()` at
   `style_parser.py:179` is complete and tested, but nothing calls it. A
   `fill="url(#grad)"` currently reaches `resolve_color`, which returns `None`,
   so the shape silently gets no fill at all.
2. **A swallowed exception (spec §2.15).** `_dispatch_element` wraps the
   shape-registry bookkeeping in `except Exception: pass`. A malformed geometry
   attribute drops the shape from `_shape_registry`, so `_bind_connectors` can no
   longer anchor a connector to it — producing exactly the dangling arrows the
   review gate is supposed to catch, with no diagnostic. This violates the
   repository's no-silent-failures rule.

- [x] **Step 1: Write the failing test**

Append to `skills/report-slides/scripts/svg_to_pptx/tests/test_integration.py`:

```python
_A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

_GRADIENT_SVG = """\
<svg viewBox="0 0 1200 675" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="fade" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#1e3a5f"/>
      <stop offset="100%" stop-color="#0f766e"/>
    </linearGradient>
  </defs>
  <rect x="100" y="100" width="400" height="200" fill="url(#fade)"/>
</svg>"""

_BAD_GEOMETRY_SVG = """\
<svg viewBox="0 0 1200 675" xmlns="http://www.w3.org/2000/svg">
  <rect x="100" y="100" width="not-a-number" height="200" fill="#1e3a5f"/>
</svg>"""


def test_gradient_fill_produces_a_grad_fill_element() -> None:
    """A url(#id) fill resolves to a native OOXML gradient, not an empty fill."""
    slide, _ = _conv(_GRADIENT_SVG)
    shape = slide.shapes[0]
    grad = shape._element.find(f".//{_A_NS}gradFill")
    assert grad is not None
    stops = grad.findall(f"{_A_NS}gsLst/{_A_NS}gs")
    assert len(stops) == 2
    assert stops[0].find(f"{_A_NS}srgbClr").get("val") == "1E3A5F"
    assert stops[1].find(f"{_A_NS}srgbClr").get("val") == "0F766E"


def test_gradient_stops_carry_their_offsets() -> None:
    """Stop offsets survive as OOXML gs positions."""
    slide, _ = _conv(_GRADIENT_SVG)
    grad = slide.shapes[0]._element.find(f".//{_A_NS}gradFill")
    positions = [gs.get("pos") for gs in grad.findall(f"{_A_NS}gsLst/{_A_NS}gs")]
    assert positions == ["0", "100000"]


def test_solid_fill_is_unaffected_by_gradient_support() -> None:
    """A plain hex fill still produces a solidFill, not a gradient."""
    slide, _ = _conv(_DIAGRAM_SVG)
    shape = slide.shapes[0]
    assert shape._element.find(f".//{_A_NS}solidFill") is not None
    assert shape._element.find(f".//{_A_NS}gradFill") is None


def test_percentage_gradient_coordinates_are_accepted() -> None:
    """`x2="100%"` is ordinary SVG and must not crash the converter.

    linearGradient coordinates default to objectBoundingBox units, where a
    percentage and a fraction mean the same thing, and most authoring tools emit
    the percentage. `float("100%")` raises `ValueError`, so before this the
    converter died on markup it should render.
    """
    svg = _GRADIENT_SVG.replace('x2="1"', 'x2="100%"')
    slide, _ = _conv(svg)
    assert slide.shapes[0]._element.find(f".//{_A_NS}gradFill") is not None


def test_a_nonsense_gradient_coordinate_is_named() -> None:
    """An unparsable coordinate says which attribute was wrong."""
    svg = _GRADIENT_SVG.replace('x2="1"', 'x2="halfway"')
    with pytest.raises(ValueError) as excinfo:
        _conv(svg)
    assert "x2" in str(excinfo.value)


@pytest.mark.parametrize("attribute,value", [
    ("gradientUnits", "userSpaceOnUse"),
    ("spreadMethod", "reflect"),
    ("gradientTransform", "rotate(45)"),
])
def test_an_unsupported_gradient_feature_is_refused(
        attribute: str, value: str) -> None:
    """Features that change the rendering are refused, not dropped.

    Accepting the markup and ignoring the feature exports a deck that looks
    wrong with nothing in the log to explain it -- and the person who sees the
    render is not the person reading the code.
    """
    svg = _GRADIENT_SVG.replace(
        '<linearGradient id="fade"',
        f'<linearGradient id="fade" {attribute}="{value}"')
    with pytest.raises(ValueError) as excinfo:
        _conv(svg)
    assert attribute in str(excinfo.value)


def test_a_stop_opacity_that_would_be_dropped_is_refused() -> None:
    """DrawingML stops here carry no alpha, so a translucent stop is an error."""
    svg = _GRADIENT_SVG.replace(
        'stop-color="#0f766e"', 'stop-color="#0f766e" stop-opacity="0.4"')
    with pytest.raises(ValueError) as excinfo:
        _conv(svg)
    assert "stop-opacity" in str(excinfo.value)


def test_malformed_geometry_raises_instead_of_dropping_the_shape() -> None:
    """A bad geometry attribute is reported, not silently swallowed."""
    with pytest.raises(ValueError) as excinfo:
        _conv(_BAD_GEOMETRY_SVG)
    assert "not-a-number" in str(excinfo.value)


def test_the_whole_deck_route_still_exports(tmp_path: Path) -> None:
    """The gradient path also survives the directory-to-deck entry point.

    `convert_file(slides_dir, out_path)` is the route `SKILL.md` actually calls;
    the in-memory `_conv` helper bypasses `prs.save`, so a shape that python-pptx
    accepts in memory but refuses to serialise would slip through every other
    test in this task.
    """
    slides_dir = tmp_path / "slides"
    slides_dir.mkdir()
    (slides_dir / "slide01.svg").write_text(_GRADIENT_SVG, encoding="utf-8")
    out = tmp_path / "deck.pptx"
    convert_file(str(slides_dir), str(out))
    assert out.exists()
    assert len(Presentation(str(out)).slides) == 1
```

These tests use `_conv`, the helper already defined at
`skills/report-slides/scripts/svg_to_pptx/tests/test_integration.py:44`, which
returns `(slide, prs)` from an in-memory `SvgConverter` run. Do **not** call
`convert_file(path)`: its real signature is
`convert_file(slides_dir: str, out_path: str, verbose: bool = False) -> None`
(`converter.py:620`) — it globs `slide*.svg` from a *directory*, writes a deck,
and returns nothing. `Path` is already imported at the top of that file; add the
import if a future refactor removes it.

- [x] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/svg_to_pptx/tests/test_integration.py -v -k "gradient or malformed or whole_deck"`
Expected: FAIL — `assert None is not None` for the gradient tests, and
`DID NOT RAISE` for the malformed-geometry test. `test_the_whole_deck_route_still_exports`
passes from the start; it is a regression guard for the serialisation step, not a
driver of this change.

- [x] **Step 3: Parse gradient definitions**

Append to `skills/report-slides/scripts/svg_to_pptx/style_parser.py`:

```python
def parse_linear_gradient(elem: Any) -> Tuple[List[Tuple[str, str]], float]:
    """Read stops and direction from an SVG `<linearGradient>` element.

    Args:
        elem: The `<linearGradient>` element.

    Returns:
        `(stops, angle_degrees)`, where each stop is `(offset, color)` in the
        form `apply_gradient_fill` expects, and the angle is measured from the
        positive x-axis.

    Raises:
        ValueError: If the element declares no usable stops.
    """
    _reject_unsupported_gradient(elem)
    stops: List[Tuple[str, str]] = []
    for child in elem:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag != "stop":
            continue
        offset = child.get("offset", "0")
        inline = parse_inline_style(child.get("style", ""))
        color = child.get("stop-color") or inline.get("stop-color")
        if color is None:
            raise ValueError(
                f"gradient stop at offset {offset!r} has no stop-color"
            )
        opacity = child.get("stop-opacity") or inline.get("stop-opacity")
        if opacity is not None and float(opacity) != 1.0:
            raise ValueError(
                f"gradient stop at offset {offset!r} sets stop-opacity="
                f"{opacity!r}; DrawingML gradient stops here carry no alpha, "
                f"so this would be dropped. Bake the opacity into stop-color "
                f"or use a solid fill with fill-opacity."
            )
        stops.append((offset, color))
    if not stops:
        raise ValueError(
            f"linearGradient {elem.get('id')!r} declares no stops"
        )
    x1 = _gradient_coord(elem.get("x1"), 0.0, "x1")
    y1 = _gradient_coord(elem.get("y1"), 0.0, "y1")
    x2 = _gradient_coord(elem.get("x2"), 1.0, "x2")
    y2 = _gradient_coord(elem.get("y2"), 0.0, "y2")
    angle = _math.degrees(_math.atan2(y2 - y1, x2 - x1))
    return stops, angle


# The SVG gradient model is much larger than what DrawingML's `a:gradFill` can
# express, and than what this converter reads. Each of these would change how a
# gradient looks and none of them is implemented, so each is refused by name.
# Silently ignoring them exports a deck that looks wrong with nothing to explain
# it, which is the expensive failure -- the author sees the render, not the code.
_UNSUPPORTED_GRADIENT_ATTRS = {
    "gradientTransform": "a transformed gradient",
    "{http://www.w3.org/1999/xlink}href": "gradient inheritance",
    "href": "gradient inheritance",
}


def _gradient_coord(raw: Optional[str], default: float, name: str) -> float:
    """Parse one linearGradient coordinate in objectBoundingBox units.

    Args:
        raw: The attribute value, or `None` when absent.
        default: The SVG default for this attribute.
        name: The attribute name, for the error message.

    Returns:
        The coordinate as a fraction, so `"50%"` and `"0.5"` both give `0.5`.

    Raises:
        ValueError: If the value is neither a number nor a percentage.
    """
    if raw is None:
        return default
    text = raw.strip()
    try:
        if text.endswith("%"):
            return float(text[:-1]) / 100.0
        return float(text)
    except ValueError as exc:
        raise ValueError(
            f"linearGradient {name}={raw!r} is neither a number nor a "
            f"percentage; only objectBoundingBox units are supported"
        ) from exc


def _reject_unsupported_gradient(elem: Any) -> None:
    """Refuse a gradient using a feature this converter does not implement.

    Args:
        elem: The `<linearGradient>` element.

    Raises:
        ValueError: If the gradient declares an unsupported feature.
    """
    for attr, description in _UNSUPPORTED_GRADIENT_ATTRS.items():
        if elem.get(attr) is not None:
            raise ValueError(
                f"linearGradient {elem.get('id')!r} uses {description} "
                f"({attr}), which this converter does not support"
            )
    units = elem.get("gradientUnits", "objectBoundingBox")
    if units != "objectBoundingBox":
        raise ValueError(
            f"linearGradient {elem.get('id')!r} sets gradientUnits={units!r}; "
            f"only objectBoundingBox is supported"
        )
    spread = elem.get("spreadMethod", "pad")
    if spread != "pad":
        raise ValueError(
            f"linearGradient {elem.get('id')!r} sets spreadMethod={spread!r}; "
            f"DrawingML gradient fills pad, and reflect/repeat would render "
            f"differently in the export than in the SVG preview"
        )


def apply_paint(shape: Any, style: Dict[str, str]) -> None:
    """Fill a shape with either a resolved gradient or a solid colour.

    The converter pre-resolves `fill="url(#id)"` into `_gradient_stops` and
    `_gradient_angle` entries on the style mapping, because only the converter
    holds the document's `<defs>` index.

    Args:
        shape: A PPTX shape.
        style: Computed style mapping for the SVG element.
    """
    stops = style.get("_gradient_stops")
    if stops:
        apply_gradient_fill(shape, stops, float(style.get("_gradient_angle", 0.0)))
        return
    apply_fill(shape, style.get("fill", "black"))
```

Add `List`, `Optional`, and `Tuple` to the `typing` import if absent.

**On the narrowed subset.** `_reject_unsupported_gradient` refuses
`gradientTransform`, href inheritance, `gradientUnits="userSpaceOnUse"`, and any
`spreadMethod` other than `pad`; `_gradient_coord` accepts numbers and
percentages and refuses everything else; a stop with `stop-opacity` other than 1
is refused because `a:gradFill` stops here carry no alpha. These are refusals,
not deferrals. Each names a feature whose absence would change the rendering, and
the alternative — accepting the markup and dropping the feature — produces a
deck that looks wrong with nothing in the log to explain it. Widening the subset
later is a change to this function with its own tests; widening it by accident
is what this prevents. Also remove the silent
early return inside `apply_gradient_fill` (line 185) so a missing `spPr` is
reported:

```python
    spPr = sp.find(qn("p:spPr"))
    if spPr is None:
        raise ValueError(
            "shape has no p:spPr element; cannot apply a gradient fill"
        )
```

- [x] **Step 4: Index gradients in the converter and inject them into styles**

In `skills/report-slides/scripts/svg_to_pptx/converter.py`, add
`self._gradient_defs: Dict[str, Any] = {}` beside the existing `self._defs`
initialisation in `__init__`, then extend `_resolve_defs`:

```python
    def _resolve_defs(self) -> None:
        """Index `<defs>` children by id, parsing gradients as they are found."""
        from .style_parser import parse_linear_gradient
        for elem in self.root.iter():
            if _local_tag(elem) != "defs":
                continue
            for child in elem:
                eid = child.get("id")
                if not eid:
                    continue
                self._defs[eid] = child
                if _local_tag(child) == "linearGradient":
                    self._gradient_defs[eid] = parse_linear_gradient(child)
```

In `_pptx_style` (line 562), after the style mapping is computed and before it is
returned, resolve a paint-server reference:

```python
        fill = style.get("fill", "")
        match = re.match(r"url\(#([^)]+)\)", fill.strip()) if fill else None
        if match:
            gradient_id = match.group(1)
            if gradient_id not in self._gradient_defs:
                raise ValueError(
                    f"fill references unknown paint server {gradient_id!r}; "
                    f"defined gradients: {sorted(self._gradient_defs)}"
                )
            stops, angle = self._gradient_defs[gradient_id]
            style["_gradient_stops"] = stops
            style["_gradient_angle"] = angle
```

Add `import re` to the module imports if absent.

- [x] **Step 5: Use `apply_paint` in the shape builders**

In `skills/report-slides/scripts/svg_to_pptx/shapes.py`, replace
`apply_fill(shape, style.get("fill", "black"))` with `apply_paint(shape, style)`
in both `_add_rect` and `_add_oval`, and add `apply_paint` to the
`.style_parser` import.

- [x] **Step 6: Stop swallowing the shape-registry error**

Replace the `try` / `except Exception: pass` block in `_dispatch_element`
(lines 258–279) so geometry parsing failures surface. Keep the same registry
entry, but let the `float()` conversion raise with context:

```python
            if shape is not None and tag in ("rect", "circle", "ellipse"):
                # A malformed geometry attribute must not silently drop the
                # shape from the anchor registry: _bind_connectors would then
                # leave connectors dangling with no diagnostic.
                try:
                    if tag == "rect":
                        bx = float(elem.get("x", 0))
                        by = float(elem.get("y", 0))
                        bw = float(elem.get("width", 0))
                        bh = float(elem.get("height", 0))
                    elif tag == "circle":
                        cx = float(elem.get("cx", 0))
                        cy = float(elem.get("cy", 0))
                        r = float(elem.get("r", 0))
                        bx, by, bw, bh = cx - r, cy - r, 2 * r, 2 * r
                    else:
                        cx = float(elem.get("cx", 0))
                        cy = float(elem.get("cy", 0))
                        rx = float(elem.get("rx", 0))
                        ry = float(elem.get("ry", 0))
                        bx, by, bw, bh = cx - rx, cy - ry, 2 * rx, 2 * ry
                except ValueError as exc:
                    raise ValueError(
                        f"<{tag}> has a non-numeric geometry attribute: {exc}"
                    ) from exc
                self._shape_registry.append(
                    (elem, bx, by, bw, bh, shape.shape_id))
```

Note that `dispatch_shape` itself parses the same attributes earlier, so a
malformed value already raises there; this change removes the second, silent
swallow so the message is not lost if the earlier path ever changes.

- [x] **Step 7: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/svg_to_pptx/tests/ -v`
Expected: PASS — all tests green.

- [x] **Step 8: Check the whole skill suite**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/ -q`
Expected: PASS. If `_dispatch_children`'s broad per-child guard now surfaces a
previously hidden error in a fixture, fix the fixture; do not restore the swallow.

- [x] **Step 9: Commit**

```bash
git add skills/report-slides/scripts/svg_to_pptx/
git commit -m "feat(report-slides): wire SVG gradient fills and stop swallowing geometry errors"
```

---

### Task 15: Point the native SVG route at the token contract

**Files:**
- Modify: `skills/report-slides/agents/architecture_diagram_worker_agent.md`
- Modify: `skills/report-slides/references/diagram-patterns.md`
- Modify: `skills/report-slides/references/styles/STYLES.md`
- Modify: `skills/report-slides/SKILL.md` (Style system section, lines 108–130)
- Test: `skills/report-slides/scripts/tests/test_token_docs.py`

**Interfaces:**
- Consumes: everything from Tasks 1–14.
- Produces: no code symbol; a documentation contract enforced by a test.

**The defect.** `generate_slides.py --style` reaches only the `data` route.
Architecture diagrams take the `native` route, where an agent hand-authors SVG,
and `architecture_diagram_worker_agent.md` never mentions the style file,
`_style.md`, or `STYLES.md` — of eleven agent definitions only
`complex_visual_decomposer_agent.md` contains the string at all (spec §2.8).
Diagram colours, radii, stroke weights, and type sizes are therefore improvised
per module, which is the inconsistency that reads as machine-generated.

Documentation alone is not enforcement, so this task ships a test that fails if
the instruction is ever dropped.

- [x] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_token_docs.py`:

```python
"""Tests that the native SVG route documents its token obligations."""
from __future__ import annotations

from pathlib import Path

import pytest

_SKILL_DIR = Path(__file__).resolve().parents[2]
_AGENTS = _SKILL_DIR / "agents"
_REFERENCES = _SKILL_DIR / "references"

_NATIVE_ROUTE_AGENTS = (
    "architecture_diagram_worker_agent.md",
    "annotation_worker_agent.md",
    "data_visualization_worker_agent.md",
    "conceptual_illustration_worker_agent.md",
)


@pytest.mark.parametrize("agent_file", _NATIVE_ROUTE_AGENTS)
def test_worker_agents_reference_the_token_contract(agent_file: str) -> None:
    """Every module worker is told to resolve style_tokens_ref."""
    text = (_AGENTS / agent_file).read_text(encoding="utf-8")
    assert "style_tokens_ref" in text, (
        f"{agent_file} does not tell the worker to resolve its design tokens"
    )
    assert "design-tokens" in text or "tokens.yaml" in text


@pytest.mark.parametrize("agent_file", _NATIVE_ROUTE_AGENTS)
def test_worker_agents_require_the_linter_markers(agent_file: str) -> None:
    """Hand-authored SVG must declare what the linter needs to read.

    These workers are the primary producers of the markup plan 2's node,
    connector, and clearance rules exist for. An element with no
    `data-style-role` or `data-node-id` is skipped by those rules, not flagged,
    so a diagram that omits them passes by never being examined -- which is
    strictly worse than having no linter, because the report says "clean".
    """
    text = (_AGENTS / agent_file).read_text(encoding="utf-8")
    for marker in ("data-style-role", "data-node-id", "data-bleed"):
        assert marker in text, f"{agent_file} does not require {marker}"


def test_the_diagram_worker_requires_declared_connector_endpoints() -> None:
    """A connector without declared endpoints cannot be checked for drift."""
    text = (_AGENTS / "architecture_diagram_worker_agent.md").read_text(
        encoding="utf-8")
    assert "data-from" in text
    assert "data-to" in text
    assert "marker-end" in text


def test_diagram_patterns_requires_token_driven_geometry() -> None:
    """diagram-patterns.md names the token surfaces and roles."""
    text = (_REFERENCES / "diagram-patterns.md").read_text(encoding="utf-8")
    for expected in ("style_tokens_ref", "node_label", "node_gap_min",
                     "surfaces", "connectors"):
        assert expected in text, f"diagram-patterns.md omits {expected}"


def test_styles_md_defers_to_the_token_contract() -> None:
    """STYLES.md states that tokens, not frontmatter, are the machine contract."""
    text = (_REFERENCES / "styles" / "STYLES.md").read_text(encoding="utf-8")
    assert "design-tokens.schema.json" in text
    assert "documentation" in text.lower()


def test_styles_md_no_longer_prescribes_the_old_skeleton() -> None:
    """The 20pt centred title and top accent bar are gone from the guidance."""
    text = (_REFERENCES / "styles" / "STYLES.md").read_text(encoding="utf-8")
    assert 'font-size="20"' not in text
    assert "top_bar_h" not in text


def test_skill_md_documents_the_tokens_flag() -> None:
    """SKILL.md tells the operator how to select a token file."""
    text = (_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    assert "--tokens" in text
    assert "validate_design_tokens.py" in text
```

- [x] **Step 2: Run test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_token_docs.py -v`
Expected: FAIL — every assertion, because none of these documents mentions the
token contract yet.

- [x] **Step 3: Update `architecture_diagram_worker_agent.md`**

In the Production Procedure, insert a new step between the current step 4
("Reference") and step 5 ("Author"):

```markdown
4b. **Resolve tokens:** Load the design-token file named by your ModuleSpec's
   `style_tokens_ref` and derive every visual constant from it. Validate it
   first:

   ```bash
   VDT="$(find ~/.claude -path "*/report-slides/scripts/validate_design_tokens.py" | head -1)"
   python3 "$VDT" --tokens <style_tokens_ref>
   ```

   You MUST NOT invent a colour, radius, stroke weight, gap, or font size. Every
   one comes from the token file:

   - Node fill, border, radius, and padding: `surfaces.node`.
   - Node label type: `typography.roles.node_label` — never below its size.
   - Connector width, arrowhead style and size, dash pattern:
     `connectors.*`. Draw arrowheads with `marker-end`, never as a separate
     polygon: a hand-drawn arrow polygon detaches from its connector on export
     and is a hard finding.
   - Minimum gap between nodes: `spacing.node_gap_min`. Minimum clearance
     between a connector and an unrelated node: `spacing.connector_clearance_min`.
   - Content stays inside `canvas.safe_area`; positions snap to `canvas.grid`.
   - Colours come from `color.roles` by name. A raw hex value not present in the
     token set is a defect.

   A module whose `style_tokens_ref` cannot be resolved is a blocker. Do not
   fall back to built-in defaults.

4c. **Declare what you drew.** Every element carries the marker that says which
   token decision it realises. These are not annotations for a human reader:
   the visual-style linter reads them, and an element without them is *skipped*
   rather than flagged, so an unmarked diagram passes every rule by never being
   examined.

   - Every `<text>`: `data-style-role="<typography role>"` — the same role you
     took the size from.
   - Every node's group: `<g data-node-id="<stable id>">`, and the node's own
     shape inside it. Node ids are what let the linter tell "these two boxes are
     too close" from "this label is inside its own box".
   - Every shape drawn from a surface or colour role:
     `data-style-role="<role>"`, for example `node.primary`, `divider`, or
     `chart.bar`. A `chart.*` or `mark.*` role also exempts the element from the
     layout grid, because a data mark is positioned by its value.
   - Every connector: `data-from="<node id>" data-to="<node id>"`, plus
     `marker-end` for its arrowhead. The declared endpoints are what make a
     drifted connector falsifiable — without them, an endpoint that has come
     adrift is indistinguishable from one placed deliberately, and the rule
     cannot fire. A `<line>` with none of these is read as a plain rule, not a
     connector, and is not checked for attachment.
   - Anything that runs past `canvas.safe_area` on purpose, such as a full-bleed
     background: `data-bleed="true"`. Without it the safe-area rule reports it
     on every slide, and the rule gets trained away as noise.

   A diagram that resolves its tokens correctly but declares none of this is
   invisible to every check downstream of it.
```

Add the same two blocks, with the surface and role names appropriate to each
route, to `annotation_worker_agent.md`, `data_visualization_worker_agent.md`,
and `conceptual_illustration_worker_agent.md` — for the conceptual worker, the
tokens and the markers govern the *overlay* layer, not the generated pixels.

- [x] **Step 4: Update `diagram-patterns.md`**

Add a section immediately after the file's opening paragraph:

```markdown
## Token-driven geometry

Every route in this file draws its constants from the design-token file named by
the module's `style_tokens_ref`, validated with `validate_design_tokens.py`.
Nothing below is a free choice:

| Visual property | Token path |
|---|---|
| Node fill / border / radius / padding | `surfaces.node` |
| Card fill / border / radius / padding | `surfaces.card` |
| Callout fill / border / radius / padding | `surfaces.callout` |
| Node label size, weight, line height, max lines | `typography.roles.node_label` |
| Axis and legend type | `typography.roles.axis` |
| Caption type | `typography.roles.caption` |
| Connector width, arrowhead, dash | `connectors.*` |
| Minimum node-to-node gap | `spacing.node_gap_min` |
| Minimum connector clearance | `spacing.connector_clearance_min` |
| Grid quantum and safe area | `canvas.grid`, `canvas.safe_area` |
| Semantic colours | `color.roles` |
| Chart series colours | `chart.palette` |
| When icons are forbidden | `icons.forbidden_when` |

Two rules apply to every route's **Failure checks** list in addition to the ones
already stated there: a colour that is not in `color.roles` fails, and two
instances of the same semantic component that differ in radius, stroke weight,
padding, or type role fail.
```

- [x] **Step 5: Update `STYLES.md`**

Replace the "Applying to [C] Claude SVG slides" section — the one prescribing
`font-size="20"` at `y="44"`, the `top_bar_h` accent bar, and the `y="54"` rule —
with:

```markdown
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
```

Delete the `top_bar_h` row from the frontmatter schema table and from every
built-in style file (`default.md`, `minimal.md`, `dark.md`, `paper.md`).

- [x] **Step 6: Update `SKILL.md`**

In the "Style system" section (lines 108–130), add before the `set-style` block:

```markdown
### Design tokens (the machine contract)

Sizes, spacing, radii, connector geometry, contrast floors, and density budgets
come from a design-token file, not from style Markdown. The shipped default is
`references/tokens/default.tokens.yaml`; select another with `--tokens`.

```bash
# Validate a token file before use:
python3 "$(find ~/.claude -path "*/report-slides/scripts/validate_design_tokens.py" | head -1)" \
    --tokens <file>

# Render with a specific token file:
python3 scripts/generate_slides.py --tokens <file> --data <json> --out <dir> --deck-id <id>
```

Every ModuleSpec must name a token file in `style_tokens_ref`; `null` is rejected
and the path is resolved and validated at the gate. Style `.md` files remain
available for colour overrides only, applied after tokens.
```

- [x] **Step 7: Run test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_token_docs.py -v`
Expected: PASS — 13 passed.

- [x] **Step 8: Run the full skill suite**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/ -q`
Expected: PASS. Doc-consistency tests asserting the old `top_bar_h` schema row now
fail by design; update them and record why in the commit message.

- [x] **Step 9: Commit**

```bash
git add skills/report-slides/agents/ \
        skills/report-slides/references/ \
        skills/report-slides/SKILL.md \
        skills/report-slides/scripts/tests/test_token_docs.py
git commit -m "docs(report-slides): bind the native SVG route to the design-token contract"
```

---

## Phase 4: One Token Set, Compiled

### Task 16: Compile the effective token set and make everything read it

This plan opens by calling the token file the machine-readable source of truth,
and then Task 6 Step 6 keeps `apply_style`, which overwrites nine colour keys and
the resolved font in `S` *after* `apply_tokens` has run. Those are two sources of
truth, and the second one wins.

The second plan then lints against `$STYLE_TOKENS_REF` — the token file on disk,
before any style override. Its `token-color` rule is a hard error: "a colour
absent from `color.roles`". So a deck that legitimately sets `primary: "#7B2D8E"`
in its style Markdown renders in that colour, exports in that colour, and then
fails the build with a hard error on every element that uses it. The same holds
for `font`: `apply_style` re-resolves `S["font_resolved"]`, and the linter goes
on measuring text with the token font, so every width it computes is for a face
the slide does not use.

Neither is a rule bug. Both are what happens when two artifacts describe one
slide and only one of them is checked.

The fix is not to delete style Markdown — a deck's palette is a real thing users
set, and STYLES.md ships eight of them. It is to make the override happen
*before* anything reads the tokens, and to write the result down. A style file
supplies values for roles that already exist; it may not invent a role, because
the role names are what the rest of the system is written against.

**Files:**
- Modify: `skills/report-slides/scripts/design_tokens.py` — add
  `with_overrides` and `dump`
- Modify: `skills/report-slides/scripts/generate_slides.py` — `main`, and delete
  the `apply_style` colour mutation Task 6 Step 4 preserved
- Test: `skills/report-slides/scripts/tests/test_effective_tokens.py`
- Modify: `skills/report-slides/SKILL.md` — the `--style` and `--tokens` copy

**Interfaces:**
- Consumes: `design_tokens.{DesignTokens, TokenError}` (Task 2);
  `generate_slides._parse_frontmatter` (existing, line 46);
  `fonts.resolve_font_stack` (Task 5).
- Produces:
  - `STYLE_KEY_TO_ROLE: Dict[str, str]` — style frontmatter key to colour role
  - `DesignTokens.from_mapping(raw: Mapping[str, Any]) -> DesignTokens` —
    `load`'s validation half, factored out
  - `DesignTokens.with_overrides(overrides: Mapping[str, str]) -> DesignTokens`
  - `DesignTokens.dump(path: Path) -> Path` — writes canonical YAML; the set's
    `digest` property is unchanged by writing and remains the identifier
  - `generate_slides.effective_tokens(tokens_path: Optional[Path],
    style_path: Optional[str], out_dir: Path) -> Tuple[Path, str]` — the written
    path and its digest

- [ ] **Step 1: Write the failing test**

Create `skills/report-slides/scripts/tests/test_effective_tokens.py`:

```python
"""One slide, one token set, one digest.

A style Markdown file that changes a colour after the tokens are loaded creates
a second description of the same slide -- and the linter reads the first one.
These tests pin the composition order and the artifact that records the result.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import generate_slides as gs
from design_tokens import DesignTokens, TokenError

_SKILL_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_TOKENS = _SKILL_DIR / "references" / "tokens" / "default.tokens.yaml"


def _style(tmp_path: Path, body: str) -> Path:
    """Write a style Markdown file with the given frontmatter body."""
    path = tmp_path / "custom.md"
    path.write_text(f"---\n{body}\n---\n\n# Custom\n", encoding="utf-8")
    return path


def test_an_override_reaches_the_token_set(tmp_path: Path) -> None:
    """The style file's primary colour becomes the token role's value."""
    style = _style(tmp_path, 'primary: "#7B2D8E"')
    path, _ = gs.effective_tokens(_DEFAULT_TOKENS, str(style), tmp_path)
    assert DesignTokens.load(path).color("primary") == "#7B2D8E"


def test_the_effective_file_is_what_the_renderer_used(tmp_path: Path) -> None:
    """`S` and the written artifact agree, so the linter sees what was drawn.

    This is the whole point. Before this task the renderer used the override and
    the linter used the file, and `token-color` -- a hard error -- fired on
    every element painted in the deck's own accent colour.
    """
    style = _style(tmp_path, 'primary: "#7B2D8E"')
    path, _ = gs.effective_tokens(_DEFAULT_TOKENS, str(style), tmp_path)
    gs.apply_tokens(path)
    assert gs.S["primary"] == "#7B2D8E"
    assert gs.S["accent"] == "#7B2D8E"


def test_the_digest_changes_with_the_style(tmp_path: Path) -> None:
    """A different palette is a different contract and gets a different digest."""
    _, plain = gs.effective_tokens(_DEFAULT_TOKENS, None, tmp_path / "a")
    _, styled = gs.effective_tokens(
        _DEFAULT_TOKENS, str(_style(tmp_path, 'primary: "#7B2D8E"')),
        tmp_path / "b")
    assert plain != styled


def test_the_digest_is_the_written_sets_own_digest(tmp_path: Path) -> None:
    """One token set, one digest: reloading the file reproduces it.

    `DesignTokens.digest` already identifies a token set by content. Minting a
    second, byte-level digest here would give the system two answers to "which
    tokens is this slide held to", which is the defect this task removes, one
    level up.
    """
    path, digest = gs.effective_tokens(_DEFAULT_TOKENS, None, tmp_path)
    assert DesignTokens.load(path).digest == digest


def test_the_same_inputs_produce_the_same_digest(tmp_path: Path) -> None:
    """Composition is deterministic; the digest identifies inputs, not runs."""
    _, first = gs.effective_tokens(_DEFAULT_TOKENS, None, tmp_path / "a")
    _, second = gs.effective_tokens(_DEFAULT_TOKENS, None, tmp_path / "b")
    assert first == second


def test_a_style_key_with_no_role_is_refused(tmp_path: Path) -> None:
    """A style file may set a role's value; it may not invent a role.

    The role names are the vocabulary the renderer, the worker agents, the
    linter, and the PPTX converter are all written against. Accepting an unknown
    key would put a colour in the effective token set that nothing can refer to,
    and the failure would surface much later as an unexplained hard error.
    """
    style = _style(tmp_path, 'chartreuse: "#7FFF00"')
    with pytest.raises(TokenError) as caught:
        gs.effective_tokens(_DEFAULT_TOKENS, str(style), tmp_path)
    assert "chartreuse" in str(caught.value)


def test_a_malformed_colour_is_refused(tmp_path: Path) -> None:
    """The composed set is validated, not merely merged."""
    style = _style(tmp_path, 'primary: "not a colour"')
    with pytest.raises(TokenError):
        gs.effective_tokens(_DEFAULT_TOKENS, str(style), tmp_path)


def test_a_font_override_is_resolved_into_the_token_set(tmp_path: Path) -> None:
    """The font the renderer measures with is the font the linter measures with."""
    style = _style(tmp_path, 'font: "DejaVu Sans, sans-serif"')
    path, _ = gs.effective_tokens(_DEFAULT_TOKENS, str(style), tmp_path)
    assert "DejaVu Sans" in DesignTokens.load(path).font_stack("sans")


def test_no_style_still_writes_an_effective_file(tmp_path: Path) -> None:
    """Every deck has an effective token set, so the gate has one thing to read."""
    path, digest = gs.effective_tokens(_DEFAULT_TOKENS, None, tmp_path)
    assert path.is_file() and len(digest) == 64
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_effective_tokens.py -v`
Expected: FAIL — `AttributeError: module 'generate_slides' has no attribute 'effective_tokens'`.

- [ ] **Step 3: Add `with_overrides` and `dump` to `DesignTokens`**

In `design_tokens.py`, beside `load`:

```python
    def with_overrides(self, overrides: Mapping[str, str]) -> "DesignTokens":
        """Return a copy with colour roles and the sans font family replaced.

        Overrides name existing roles. Inventing a role is refused rather than
        merged: the role names are the vocabulary the renderer, the worker
        agents, the linter, and the converter are all written against, and a
        role only one of them knows about is worse than no role at all.

        Args:
            overrides: Role name to value. The key `font` is special-cased onto
                `typography.family.sans`.

        Returns:
            A new `DesignTokens`, validated against the schema.

        Raises:
            TokenError: If a key names no existing role, or the result fails
                schema or semantic validation.
        """
        raw = copy.deepcopy(self.raw)
        roles = raw["color"]["roles"]
        for key, value in overrides.items():
            if key == "font":
                raw["typography"]["family"]["sans"] = value
                continue
            if key not in roles:
                raise TokenError(
                    f"style override {key!r} names no colour role; "
                    f"known roles are {', '.join(sorted(roles))}"
                )
            roles[key] = value
        return DesignTokens.from_mapping(raw)

    def dump(self, path: Path) -> Path:
        """Write the token set as canonical YAML.

        Sorted keys and a fixed dumper make the bytes a function of the content
        alone, so two runs over the same inputs produce the same file.

        Args:
            path: Destination file. Parent directories are created.

        Returns:
            The path written, for chaining. The set's identity is its `digest`
            property, which survives the round trip unchanged.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(self.raw, sort_keys=True, allow_unicode=True),
            encoding="utf-8")
        return path
```

`from_mapping` is `load`'s validation half, factored out: `load` becomes "read
the YAML, then `from_mapping`". Both run the JSON Schema check and
`semantic_errors` from Task 2, so a composed set is held to exactly the same
contract as a written one — that is what makes `test_a_malformed_colour_is_refused`
pass without a second validator. Add `copy` and `Mapping` to the module imports.

`digest` must be computed from `raw` rather than from the file's bytes, so that
a composed set has a digest before it is written and the same one after. If
Task 2 implemented it by hashing the file, move it onto the canonical dump of
`raw` here and keep
`test_loader_digest_is_content_sensitive_not_whitespace_sensitive` passing —
that test already states the property this relies on.

- [ ] **Step 4: Compose in `generate_slides.py`**

Add, beside `apply_tokens`:

```python
# Style Markdown keys are historical; the token roles are the contract. This map
# is the only place the two vocabularies meet.
STYLE_KEY_TO_ROLE: Dict[str, str] = {
    "primary": "primary", "bg": "bg", "body": "body", "muted": "muted",
    "border": "border", "card": "card", "positive": "positive",
    "warn": "warn", "danger": "danger", "font": "font",
}


def effective_tokens(
    tokens_path: Optional[Path], style_path: Optional[str], out_dir: Path
) -> Tuple[Path, str]:
    """Compose tokens with a style override and write the result.

    The composed file is the single artifact the renderer loads, the linter
    reads, and the workflow gate digests. Composing before anything reads the
    tokens is what keeps those three from disagreeing.

    Args:
        tokens_path: Token file, or `None` for the shipped default.
        style_path: Style Markdown file, or `None`.
        out_dir: Directory to write `_effective.tokens.yaml` into.

    Returns:
        The written path and the composed set's digest.

    Raises:
        TokenError: If the style names an unknown role or the composed set
            fails validation.
        ValueError: If the style file has no usable frontmatter.
    """
    tokens = DesignTokens.load(tokens_path or DEFAULT_TOKENS_PATH)
    if style_path is not None:
        frontmatter = _parse_frontmatter(style_path)
        if not frontmatter:
            raise ValueError(
                f"style file {style_path} has no usable YAML frontmatter; "
                f"expected keys such as primary/bg/body "
                f"(see references/styles/STYLES.md)"
            )
        unknown = sorted(set(frontmatter) - set(STYLE_KEY_TO_ROLE))
        if unknown:
            raise TokenError(
                f"style file {style_path} sets {', '.join(unknown)}, which "
                f"name no colour role"
            )
        overrides = {
            STYLE_KEY_TO_ROLE[key]: value
            for key, value in frontmatter.items() if key in STYLE_KEY_TO_ROLE
        }
        if "font" in overrides:
            overrides["font"] = resolve_font_stack(overrides["font"])
        tokens = tokens.with_overrides(overrides)
    path = out_dir / "_effective.tokens.yaml"
    tokens.dump(path)
    return path, tokens.digest
```

Then delete `apply_style` entirely, and replace its call in `main`:

```python
    tokens_path, tokens_digest = effective_tokens(
        args.tokens, args.style, Path(args.out))
    apply_tokens(tokens_path)
    print(f"  [tokens] {tokens_path} sha256={tokens_digest[:12]}")
```

Deleting `apply_style` rather than leaving it unused is deliberate: a function
that mutates `S` after `apply_tokens` is exactly the defect, and leaving it in
the module is an invitation to call it.

- [ ] **Step 5: Run the test to verify it passes**

Run: `timeout 300 python3 -m pytest skills/report-slides/scripts/tests/test_effective_tokens.py -v`
Expected: PASS — 9 passed.

- [ ] **Step 6: Run the suite and fix the fallout**

Run: `timeout 900 python3 -m pytest skills/report-slides/scripts/tests/ -q`

Expected: the two `apply_style` tests from Task 6 Step 3 now fail with
`AttributeError`. Their claim has moved, not disappeared:
`test_apply_style_raises_on_unparsable_frontmatter` becomes
`test_effective_tokens_raises_on_unparsable_frontmatter`, calling
`effective_tokens` with the same broken file and expecting the same
`ValueError`. Rewrite them where they stand; do not delete them, and do not keep
`apply_style` alive to save them.

- [ ] **Step 7: Say so in `SKILL.md`**

In the Style system section, replace the sentence describing `--style` as a
colour override with:

```markdown
`--style` and `--tokens` are composed before rendering, not applied in sequence
afterwards. The result is written to `<out>/_effective.tokens.yaml`, and that
file — not the file passed to `--tokens` — is what `$STYLE_TOKENS_REF` must
point at for the rest of the pipeline. A style file may set the value of a
colour role or the sans font family; a key naming no role is an error, because
the role names are the vocabulary every downstream check is written against.
```

- [ ] **Step 8: Commit**

```bash
git add skills/report-slides/scripts/design_tokens.py \
        skills/report-slides/scripts/generate_slides.py \
        skills/report-slides/scripts/tests/test_effective_tokens.py \
        skills/report-slides/scripts/tests/test_generate_slides_typography.py \
        skills/report-slides/SKILL.md
git commit -m "feat(report-slides): compile one effective token set per deck

apply_style overwrote nine colour keys and the resolved font in S after
apply_tokens had run, so a deck had two descriptions of itself and only the
token file was ever checked. A style-set accent colour would have failed the
token-color hard error on every element that used it, and every text width the
linter computed would have been for a face the slide did not use.

Style Markdown is now composed into the token set before anything reads it, the
result is written to _effective.tokens.yaml with a digest, and apply_style is
deleted. A style key naming no colour role is refused rather than merged."
```

---

## Final Verification

Run after Task 16, before declaring this plan complete.

- [ ] **Step 1: Full suite**

Run: `timeout 1800 python3 -m pytest skills/report-slides/ -q`
Expected: PASS with no skips other than the fontconfig guard in `test_fonts.py`.
Paste the pytest summary line into the completion report.

- [ ] **Step 2: End-to-end deck, SVG and PPTX**

Render a deck exercising every renderer, convert it, and confirm both outputs
agree:

```bash
timeout 600 python3 skills/report-slides/scripts/generate_slides.py \
    --tokens skills/report-slides/references/tokens/default.tokens.yaml \
    --data <a slide_data.json covering all ten slide types> \
    --out /tmp/final-check/svg --deck-id <approved deck id>

timeout 600 python3 skills/report-slides/scripts/generate_slides.py \
    --to-pptx /tmp/final-check/svg --pptx-out /tmp/final-check/deck.pptx \
    --deck-id <approved deck id>

timeout 900 soffice --headless --convert-to pdf \
    --outdir /tmp/final-check /tmp/final-check/deck.pptx
```

- [ ] **Step 3: Inspect the pixels**

Render both the source SVGs and the LibreOffice-converted PPTX pages to PNG and
compare them side by side. Confirm, for every slide:

- no text below 12 units;
- the same font face in both outputs;
- rounded cards are rounded in the PPTX;
- connectors carry arrowheads that stay attached;
- dashed strokes are dashed and translucent fills are translucent;
- nothing is clipped, overlapping, or outside the safe area.

Any disagreement between the SVG and the PPTX is a Phase 3 regression: fix the
converter, not the source SVG.

- [ ] **Step 4: Confirm the spec's success criteria**

Walk `docs/superpowers/specs/2026-09-04-report-slides-visual-quality-design.md`
§6 and confirm criteria 1–4 hold. Criteria 5–7 belong to the second plan and are
expected to be outstanding; say so explicitly rather than implying full coverage.

---

## Self-Review

Performed against the spec after writing this plan.

**Spec coverage.** Every defect in spec §2 that this plan owns maps to a task:
§2.2 → Tasks 6–9; §2.3 → Task 10; §2.4 → Task 11; §2.5 → Task 12;
§2.6 → Tasks 13–14; §2.7 → Task 4; §2.8 → Tasks 6 and 15; §2.9 → Tasks 1–3;
§2.15 → Tasks 6 and 14. Task 16 answers no spec defect either: §D2 calls the
token file the machine-readable source of truth, and `apply_style` quietly made
it the second-to-last word. Task 0 exists because every
`Run:` command in both plans failed at collection without it, and because the
1506 tests already under `skills/` gate no pull request. A plan whose verification
steps cannot be executed verifies nothing, so it comes first. Spec §3.3's adopted cherry-picks land in Tasks 12–13, and
its two rejections (Bézier construction, `latex_to_unicode`) are correctly absent.

Deliberately **not** covered here, and carried by the second plan:
§2.1 (generative imagery), §2.10 (auto-layout — deferred entirely per spec §5),
§2.11 (measurable gates), §2.12 (reviewer remit), §2.13 (no slide-level art
direction), §2.14 (route guidance inconsistency in
`research_narrative_planner_agent.md:38`).

**Placeholder scan.** No task contains "TBD", "implement later", "add error
handling", "write tests for the above", or "similar to Task N". Tasks 9 and 15
describe transformations rather than full file rewrites in two places — Task 9
Step 6 for `render_two_column`/`render_timeline`, and Task 15 Step 3 for the three
sibling worker agents. Both name the exact files, the exact line numbers, the
exact substitutions, and ship a test that fails until the work is done, so an
implementer has no open decision.

**Type consistency.** `DesignTokens.load` returns `DesignTokens` in Tasks 2, 3, 4,
and 6. `TypeRole` fields are `size`/`weight`/`line_height`/`max_lines`/`family`
throughout. `t_size`/`t_weight`/`t_lh` keep their names in Tasks 6, 7, 8, and 9.
`resolve_font_stack` returns `str` in Tasks 5, 6, and 10.
`vertical_metrics(family: str, size: float, weight: int = 400)
-> Tuple[float, float]` is defined in
Task 5, used in Tasks 6 and 9 to lift the footer baseline off the safe-area
boundary, and imported by the second plan's Task 2 — both documents measure the
text box with the same function rather than with two sets of guessed constants.
`font_file_for(family: str, weight: int = 400) -> Path` keys its cache by both,
so `text_width` measures a 700-weight title with the bold face; measuring it
with the regular one under-reports by 12.9% on the development machine, and four
of the eight token roles carry a weight of 600 or more.
`tlines` takes a keyword-only, mandatory `role: str` from Task 7 Step 3 onward,
so no call site can emit unroled text by omission. Task 14 calls
`convert_file(slides_dir: str, out_path: str, verbose: bool = False) -> None`
through the existing `_conv` helper, matching `converter.py:620`; it does not
treat the return value as a document, because there is none. `ensure_ln_child` is
defined in Task 12 and reused in Task 13 with the same signature. `apply_paint`
supersedes the direct `apply_fill` call in Task 14, after Tasks 11 and 13 had used
`apply_fill` — Task 14 Step 5 changes both call sites explicitly rather than
leaving them inconsistent.

**Marker contract.** The second plan's rules read `data-style-role`,
`data-node-id`, `data-bleed`, `data-from`, and `data-to`. An element carrying
none of them is *skipped* by those rules rather than flagged, so markup that
omits them passes every check by never being examined — a report that says
"clean" about a diagram nothing looked at. Both producers of slide SVG therefore
emit them: `generate_slides.py` in Tasks 6–9, enforced by Task 9 Step 8's sweep
over every rendered fragment, and the four hand-authoring worker agents in
Task 15 Step 4c, enforced by a test per agent. Task 9 Step 8 fails on any text
element whose role is absent from the token file's `typography.roles`, which is
what keeps the two vocabularies from drifting apart.

**Known ordering constraint.** Task 13 adds `apply_alpha` calls to `_add_rect`,
and Task 14 replaces the `apply_fill` line in the same function. Execute 13 before
14, as numbered.

---

## Revision, after review

Both plans were reviewed by an independent agent and by a verification pass over
the repository. What follows is what survived verification, with the evidence,
because several defects were the kind that pass a reading and fail an execution.

**Defects fixed in this plan:**

| Defect | Evidence | Where it landed |
|---|---|---|
| Every per-file `Run:` command in both plans failed at collection | `pytest skills/report-slides/scripts/tests/test_presentation_gates.py` → `ModuleNotFoundError: No module named 'presentation_contracts'`, 0 collected. With the new `conftest.py`: `18 passed` | **Task 0** |
| The 1506 tests under `skills/` gate no pull request | `.github/workflows/pytest.yml` runs `pytest scripts/ tests/`; its `paths:` filters never mention `skills/**` | Task 0 Step 5 |
| Both plans forbade linter-suppression comments in Global Constraints and then used one 27 times | Removed by Task 0's conftest; neither document now contains the suppression | Task 0 |
| Plan 2's rules all key off `data-style-role`; this plan emitted it zero times | `grep -c data-style-role` returned 0 | Tasks 6–9 and 15, enforced by Task 9 Step 8 |
| The footer's descenders hung outside the safe area on every slide | `frame()` put the baseline at `675 − 36 = 639`; DejaVu Sans reports descent 3 at size 12, so the box ended at 642 — a `safe-area` error on every slide with a footer | Task 6 |
| The text box was modelled from guessed constants | Measured with Pillow: ascent/descent are 30/8 at size 32 and 12/3 at size 12, not 0.8 em and no descent | `fonts.vertical_metrics`, Task 5 |
| Font weight was accepted and discarded | `text_width` documented that it ignored `weight`. Measured: DejaVu Sans Bold is 585.81 units against Regular's 518.91 for one string at size 32 — 12.9% wider. Four of the eight token roles are weight 600 or 700 | `FC_WEIGHT_NAMES`, Task 5 |
| Task 14 called `convert_file(path)` and used the return value | `converter.py:620` is `convert_file(slides_dir: str, out_path: str, verbose: bool = False) -> None` | Task 14, via `_conv` |
| Hand-authored diagrams emitted none of the markers the linter reads | The four worker agents are the primary producers of the markup plan 2's node and connector rules exist for | Task 15 Step 4c |
| Arrowhead type was documented on the `<marker>` and read from the connector | The prose said one thing, `apply_line_ends` and its test said another. One `<marker>` in `<defs>` is shared by every connector, so it cannot carry a per-connector answer | Task 12 |
| Every segment of a polyline got an arrowhead | `connector.py:41-52` emits one `_add_line` per segment sharing one style dict. A four-point elbow — the standard shape for routing around a node — exported with three arrowheads pointing into its own middle | Task 12 Step 5 |
| A gradient with percentage coordinates crashed the converter | `float(elem.get("x1", 0))` raises on `x1="0%"`, which is ordinary SVG; linearGradient coordinates default to objectBoundingBox units and percentages are what most tools emit. `gradientUnits`, `gradientTransform`, `spreadMethod`, href inheritance, and `stop-opacity` were read by nothing and would have been dropped silently | Task 13 |
| The token schema could not express its own invariants | JSON Schema validates each value alone: `occupancy_min: 0.9` with `occupancy_max: 0.3` is valid, as is a surface whose `fill` names a colour role that does not exist | `design_tokens.semantic_errors`, Task 2 |
| `style_tokens_ref` validated a file and forgot which file | Spec §D3 asks for provenance; the recorded fact was "some token file was fine at some past moment" | `resolved_token_digest`, Task 4 |
| The token file was called the source of truth and `apply_style` overwrote it | `apply_style` replaces nine colour keys and the resolved font in `S` *after* `apply_tokens`. Plan 2 lints the file on disk, and its `token-color` rule is a hard error — so a deck that set its own accent colour would fail the build on every element using it | **Task 16** |

**Two findings were rejected.**

An earlier correction to this plan raised Task 12's expected pass count from 11
to 12. That was wrong: the counting script attributed to Task 12 a test the task
appends to a *different* file. The reviewer was right and the count is 11.

The reviewer also read `test_fonts.py`'s module-level skip when `fc-match` is
absent as a violation of the no-skips posture. It is not: the repository's rule
permits a skip for an absent optional dependency when it is marked and names the
dependency, which this one does. Mocking font discovery in a module whose entire
subject is font discovery would test the mock.

**One finding was accepted in part.** Task 9 rewrites four renderers under one
commit, so a reviewer could not reject the timeline work while accepting the
table work. Splitting it into two tasks would renumber Tasks 10–16 and every
cross-reference in both documents; it now carries a review checkpoint and two
commits instead, which gives the same rejection granularity.
