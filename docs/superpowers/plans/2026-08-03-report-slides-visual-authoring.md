# Report Slides Visual Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a visual-authoring workflow to `report-slides` that plans subfigures, uses native, data, generative, or hybrid rendering, reviews rendered pixels, reuses project assets, and preserves or discloses PPTX editability.

**Architecture:** Keep `SKILL.md` as the orchestration layer and place drawing, image-generation, reuse, and review contracts in focused references. Add deterministic Python utilities for asset-manifest validation and raster review-sheet composition, then forward-test identical scenarios before and after the skill change. Continue using the existing SVG-to-native-PPTX package for editable export.

**Tech Stack:** Markdown, Python 3.8+, PyYAML, Pillow, pytest, SVG 1.1, `python-pptx`, existing `svg_to_pptx`, image generation, and model visual inspection.

## Global Constraints

- Every implementation subagent uses `luna` with reasoning effort `max`.
- Every specification or code reviewer uses `gpt-5.6-terra` with reasoning effort `high`.
- Never use any `sol` model. If `luna:max` is unavailable, stop before implementation and ask the user; do not substitute another model.
- After each task, run two `terra:high` reviews in order: specification compliance, then code/document quality. The `luna:max` implementer fixes findings; both gates pass before the next task.
- Treat each task commit as provisional until both reviews pass. After review fixes, stage only paths listed in that task's `Files` block, run `git diff --cached --check`, amend with `git commit --amend --no-edit`, rerun the task tests, and require `test -z "$(git status --porcelain)"` before the next task.
- Execute Tasks 1–8 in a dedicated worktree created with `superpowers:using-git-worktrees`; never implement directly on the user's main checkout.
- Runtime project visual assets live under `docs/slides/assets/diagrams/<diagram_id>/`; do not create a cross-project library. Task 7's self-contained tracked example is the only fixture exception and mirrors the same per-diagram contents below its example directory.
- Use `1200 × 675` coordinates for slides and manifest bounding boxes.
- Every public Python module, class, function, and method has complete type annotations and a Google-style docstring.
- Code comments, docstrings, CLI messages, logs, and commit subjects are English.
- Missing inputs, dependencies, renderers, and invalid manifests are explicit errors; no silent fallback may claim equivalent quality.
- Statistical data, labels, legends, and factual annotations never come from a generative image model.
- Generated art may remain raster, but factual overlays remain editable and the result declares `native`, `hybrid`, or `raster` editability.
- Agents inspect rendered pixels at subfigure and slide level and revise until the gate passes. Blocked review is not completion.
- Reused visuals retain semantic identity and record `based_on_revision` plus named changed regions. Materially different visuals use a new ID with `derived_from`.
- Preserve the existing SVG-to-native-PPTX converter and its tests. Animation remains out of scope.

---

## File Map

| Path | Change | Responsibility |
|---|---|---|
| `evals/report-slides-visual-authoring/{scenarios.yaml,baseline.md,after.md}` | Create | RED/GREEN prompts and evidence |
| `skills/report-slides/scripts/validate_diagram_manifest.py` | Create | Validate one asset manifest or an asset library |
| `skills/report-slides/scripts/tests/test_validate_diagram_manifest.py` | Create | Validator tests |
| `skills/report-slides/scripts/render_review_sheet.py` | Create | Compose rendered previews into a labeled PNG |
| `skills/report-slides/scripts/tests/test_render_review_sheet.py` | Create | Review-sheet tests |
| `skills/report-slides/scripts/tests/test_setup_scripts.py` | Create | Setup contract tests |
| `skills/report-slides/scripts/{setup.sh,setup.ps1}` | Modify | Install utilities and create asset directories |
| `requirements-dev.txt` | Modify | Add Pillow |
| `.gitignore` | Modify | Track PNG artifacts only for the visual-authoring example |
| `skills/report-slides/references/diagram-workflow.md` | Create | Brief, reuse, manifest, and change workflow |
| `skills/report-slides/references/diagram-patterns.md` | Create | Per-visual recipes |
| `skills/report-slides/references/generative-visuals.md` | Create | Image-generation and overlay rules |
| `skills/report-slides/references/visual-review.md` | Create | Pixel-review gates and loop |
| `skills/report-slides/SKILL.md` | Modify | Mandatory orchestration and reporting |
| `examples/report-slides/visual-authoring/` | Create | Complete reviewed editable-PPTX example |

## Python Interfaces

| Module | Public interface |
|---|---|
| `validate_diagram_manifest` | immutable `ValidationIssue(manifest: Path, path: str, message: str)` |
| `validate_diagram_manifest` | `validate_manifest(manifest_path: Path) -> List[ValidationIssue]` |
| `validate_diagram_manifest` | `validate_asset_library(root: Path) -> List[ValidationIssue]` |
| `validate_diagram_manifest` | `validate_diagram_plan(plan_path: Path) -> List[ValidationIssue]` |
| `validate_diagram_manifest` | `main(argv: Optional[Sequence[str]] = None) -> int` |
| `render_review_sheet` | `compose_review_sheet(image_paths: Sequence[Path], output_path: Path, *, columns: int = 2, cell_width: int = 600, cell_height: int = 338) -> Path` |
| `render_review_sheet` | `main(argv: Optional[Sequence[str]] = None) -> int` |

The validator returns every issue in deterministic path order. The review-sheet utility accepts rendered PNG/JPEG inputs only; SVG source inspection is not visual review.

---

### Task 0: Verify Required Agent Models

**Files:** None.

**Interfaces:**
- Consumes: runtime model overrides
- Produces: explicit go/no-go before implementation

- [ ] **Step 1: Probe `luna:max` without writes**

Dispatch model `luna`, effort `max`, with `Reply with exactly READY. Do not inspect or modify files.` Expected: `READY`. A model-selection error stops execution and is reported to the user.

- [ ] **Step 2: Probe `terra:high` without writes**

Dispatch `gpt-5.6-terra`, effort `high`, with the same prompt. Expected: `READY`.

- [ ] **Step 3: Enforce the `sol` prohibition**

Inspect every later dispatch model field. Any `sol` value is a hard stop.

- [ ] **Step 4: Create and verify an isolated worktree**

Use `superpowers:using-git-worktrees`. Record the worktree path, branch, clean baseline, and current commit. Before Task 1 require:

```bash
test -n "$(git branch --show-current)"
test -z "$(git status --porcelain)"
```

---

### Task 1: Establish the RED Skill Baseline

**Files:**
- Create: `evals/report-slides-visual-authoring/scenarios.yaml`
- Create: `evals/report-slides-visual-authoring/baseline.md`

**Interfaces:**
- Consumes: current `skills/report-slides/SKILL.md`
- Produces: five prompts and verbatim baseline evidence for Task 6

- [ ] **Step 1: Create scenarios before skill edits**

Create this exact contract:

```yaml
schema_version: 1
skill_path: skills/report-slides/SKILL.md
scenarios:
  - id: architecture-planning
    prompt: >-
      Use report-slides to plan one slide explaining ingestion, feature
      processing, training, evaluation, human approval, and publishing.
      Describe artifacts created before drawing and how PPTX stays editable.
    required:
      - named subfigures or regions
      - editable nodes labels and connectors
      - rendered-pixel review before completion
  - id: hybrid-generative-visual
    prompt: >-
      Plan a conceptual researcher-and-AI-lab slide. Use generated imagery where
      useful, keep factual annotations editable, and state files and disclosures.
    required:
      - raster illustration separated from editable factual overlays
      - no generated prose labels legends or precise values
      - prompt sources and editability recorded
  - id: statistical-integrity
    prompt: >-
      Plan an accuracy chart from 72.1, 81.6, 98.4, and 100.0. Explain how data
      integrity and rendered visual quality are verified.
    required:
      - deterministic rendering rather than image generation
      - reconstructable source data
      - chart and complete-slide pixel review
  - id: reuse-and-change-disclosure
    prompt: >-
      A project training-pipeline diagram gains a human-review branch and failure
      return path. Explain whether to redraw or modify and how to report location.
    required:
      - asset-library search first
      - previous source modified instead of unrelated regeneration
      - based_on_revision region bbox change and reason
      - change-focused delivery summary
  - id: completion-report
    prompt: >-
      A deck contains a native architecture diagram, a hybrid conceptual image,
      and a data chart. Show the per-visual completion report you would return
      after export and validation.
    required:
      - diagram type slide location route ID and action
      - reused source and changed regions with reasons
      - editability and review rounds
      - separate SVG preview PPTX structure and PPTX render validation
      - remaining raster layers and rationale
```

- [ ] **Step 2: Run each prompt with isolated `luna:max` agents**

Agents receive only the skill path and scenario prompt, without rubric, design, or testing context. They do not modify files.

- [ ] **Step 3: Score with `terra:high`**

For every scenario, record `Raw response`, `Score`, and `Observed failure pattern`. Each requirement is `[pass]` or `[fail]` with explicit evidence. Do not infer unstated behavior.

- [ ] **Step 4: Verify RED and commit**

```bash
rg -n "\[fail\]" evals/report-slides-visual-authoring/baseline.md
git add evals/report-slides-visual-authoring
git commit -m "test(report-slides): capture visual authoring baseline"
```

Expected: at least one target failure. If none exists, stop and remove redundant guidance from later tasks.

- [ ] **Step 5: Complete both `terra:high` reviews**

Review scenario compliance first, then evidence quality and leakage. The `luna:max` implementer reruns affected cases until both reviewers say `APPROVED`.

---

### Task 2: Add the Diagram Manifest Validator

**Files:**
- Create: `skills/report-slides/scripts/validate_diagram_manifest.py`
- Create: `skills/report-slides/scripts/tests/test_validate_diagram_manifest.py`

**Interfaces:**
- Consumes: `docs/slides/assets/diagrams/*/manifest.yaml`
- Produces: `ValidationIssue`, `validate_manifest`, `validate_asset_library`, and CLI `--manifest`/`--root`

- [ ] **Step 1: Write failing core tests**

Use a helper that creates `source.svg`, `review.json`, and this complete payload:

```python
payload: Dict[str, object] = {
    "schema_version": 1,
    "diagram_id": asset_dir.name,
    "purpose": "Explain training and evaluation.",
    "diagram_type": "architecture",
    "authoring_route": "native",
    "editability": "native",
    "source_files": ["source.svg"],
    "used_in": [{"deck": "weekly-progress", "slide": 4}],
    "derived_from": None,
    "based_on_revision": None,
    "changes": [],
    "generation": None,
    "review": {"status": "passed", "artifact": "review.json"},
}
```

Tests require: complete asset returns `[]`; missing source reports `source_files[0]`; invalid asset IDs from `a-asset` and `z-asset` are returned in directory order.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=skills/report-slides/scripts python3 -m pytest \
  skills/report-slides/scripts/tests/test_validate_diagram_manifest.py -q
```

Expected: `ModuleNotFoundError: validate_diagram_manifest`.

- [ ] **Step 3: Implement the typed core**

Define enumerations for diagram types (`architecture`, `flowchart`, `timeline`, `statistical`, `conceptual`, `hybrid`, `status`), editability (`native`, `hybrid`, `raster`), review status (`draft`, `failed`, `passed`), and kebab-case IDs. Implement the interface map with full Google-style docstrings.

Collect all errors for: schema version; ID and directory match; purpose; diagram type; `authoring_route` in `native`, `data`, `generative`, or `hybrid`; editability; non-empty relative existing source files that cannot escape the asset directory; positive `used_in.slide`; string-or-null derivation fields; change entries with region/change/reason; finite bbox satisfying `0 <= x1 < x2 <= 1200` and `0 <= y1 < y2 <= 675`; and a relative existing review artifact when status is passed. An empty asset root reports `no manifest.yaml files found`.

Enforce route-specific provenance:

- `native`: `source_files` contains at least one `.svg`;
- `data`: `source_files` contains `data.json` and at least one `.svg`;
- `generative`: `generation` declares existing relative `prompt`, existing relative `output` (`.png`/`.jpg`), and a list of relative reference paths;
- `hybrid`: the generative contract plus an editable `.svg` overlay in `source_files`;
- when a generative/hybrid edit sets `based_on_revision` or non-empty `changes`, `generation.references` is non-empty.

Use Python 3.8-compatible annotations from `typing`: `Any`, `Dict`, `List`, `Mapping`, `Optional`, and `Sequence`. Do not use built-in generics or `X | None`.

- [ ] **Step 4: Add edge and CLI tests**

Test malformed YAML root, ID mismatch, unknown enums, path traversal, invalid slide, invalid bbox, missing review artifact, empty library, and every route-specific provenance branch.

Add `validate_diagram_plan` tests for this schema:

```yaml
schema_version: 1
deck_id: weekly-progress
visuals:
  - diagram_id: training-pipeline
    slide: 4
    purpose: Explain the publishing gate.
    regions: [ingestion, training, evaluation-stage, publishing]
    route: native
    editability: native
    reuse:
      action: modify
      asset_id: training-pipeline
```

Require kebab-case `deck_id`/`diagram_id`, positive slide, non-empty purpose and unique non-empty regions, enumerated route/editability, and reuse action in `create`, `reuse`, `modify`, `derive`. `reuse`, `modify`, and `derive` require `asset_id`; `create` forbids it. For `reuse` and `modify`, `asset_id` must equal `diagram_id`; only `derive` may use a different new `diagram_id`. Add positive and negative tests for this identity rule. The CLI uses a required mutually exclusive group with `--manifest`, `--root`, and `--plan`. Invalid output is `ERROR <path>:<field>: <message>` with exit `1`; valid output identifies whether manifest, library, or plan validation passed.

- [ ] **Step 5: Run GREEN, commit, and review**

```bash
PYTHONPATH=skills/report-slides/scripts python3 -m pytest \
  skills/report-slides/scripts/tests/test_validate_diagram_manifest.py -q
git add skills/report-slides/scripts/validate_diagram_manifest.py \
  skills/report-slides/scripts/tests/test_validate_diagram_manifest.py
git commit -m "feat(report-slides): validate diagram asset manifests"
```

Run `terra:high` specification review and code-quality review. Resume `luna:max` for fixes, stage only the two Task 2 files, amend the provisional commit, and rerun tests until both approve. Assert a clean tree before Task 3.

---

### Task 3: Add Review-Sheet Composition and Setup Support

**Files:**
- Create: `skills/report-slides/scripts/render_review_sheet.py`
- Create: `skills/report-slides/scripts/tests/test_render_review_sheet.py`
- Create: `skills/report-slides/scripts/tests/test_setup_scripts.py`
- Modify: `skills/report-slides/scripts/setup.sh`
- Modify: `skills/report-slides/scripts/setup.ps1`
- Modify: `requirements-dev.txt`

**Interfaces:**
- Consumes: already-rendered PNG/JPEG files
- Produces: the typed `compose_review_sheet` interface above, a repeated-`--input` CLI, and setup installation of both new utilities

- [ ] **Step 1: Add Pillow and write failing tests**

Append `Pillow>=10.0` to `requirements-dev.txt`. Create two `120 × 68` red/blue PNG fixtures and assert:

```python
result = compose_review_sheet(
    [first, second], output, columns=2, cell_width=120, cell_height=68
)
assert result == output
with Image.open(output) as sheet:
    assert sheet.size == (264, 116)
    assert sheet.getpixel((62, 42))[0] > 200
    assert sheet.getpixel((194, 42))[2] > 200
```

Also require `FileNotFoundError` for missing input and `ValueError` for SVG input, empty input, or non-positive geometry. Run the focused test and expect `ModuleNotFoundError`.

- [ ] **Step 2: Implement review-sheet composition**

Define `GAP = 8`, `HEADER_HEIGHT = 28`, and `BACKGROUND = (245, 247, 250)`. Implement the interface-map signature with a Google-style docstring. Validate extensions before decoding, use `ImageOps.contain`, center previews, label cells with `path.name`, convert decoded images to RGB, and create the output parent explicitly.

The CLI takes repeated `--input`, required `--out`, and positive `--columns`, `--cell-width`, and `--cell-height`. Success prints `OK: review sheet written to <path>`; decode/write failures print `ERROR: <detail>` to stderr and return `1`.

- [ ] **Step 3: Write setup tests and update both setup scripts**

Run `setup.sh` from a temporary project and assert these outputs:

```text
scripts/generate_slides.py
scripts/validate_diagram_manifest.py
scripts/render_review_sheet.py
docs/slides/reports/
docs/slides/assets/diagrams/
```

Read `setup.ps1` and assert both script names plus `docs\slides\assets\diagrams`. Update the shell implementation with:

```bash
mkdir -p scripts docs/slides/reports docs/slides/assets/diagrams
cp "$SCRIPT_DIR/generate_slides.py" scripts/
cp "$SCRIPT_DIR/validate_diagram_manifest.py" scripts/
cp "$SCRIPT_DIR/render_review_sheet.py" scripts/
```

Add equivalent `New-Item` and `Copy-Item` operations to PowerShell. Setup output states that Pillow is required only for review-sheet composition.

- [ ] **Step 4: Run GREEN and commit**

```bash
PYTHONPATH=skills/report-slides/scripts python3 -m pytest \
  skills/report-slides/scripts/tests/test_render_review_sheet.py \
  skills/report-slides/scripts/tests/test_setup_scripts.py -q
git add requirements-dev.txt skills/report-slides/scripts/render_review_sheet.py \
  skills/report-slides/scripts/setup.sh skills/report-slides/scripts/setup.ps1 \
  skills/report-slides/scripts/tests/test_render_review_sheet.py \
  skills/report-slides/scripts/tests/test_setup_scripts.py
git commit -m "feat(report-slides): add visual review sheet tooling"
```

- [ ] **Step 5: Complete both `terra:high` reviews**

Run specification and code-quality reviews, then resume `luna:max` for fixes. Stage only the six Task 3 paths, amend the provisional commit, rerun tests, and assert a clean tree before both reviewers return `APPROVED`.

---

### Task 4: Add Focused Visual-Authoring References

**Files:**
- Create: `skills/report-slides/references/diagram-workflow.md`
- Create: `skills/report-slides/references/diagram-patterns.md`
- Create: `skills/report-slides/references/generative-visuals.md`
- Create: `skills/report-slides/references/visual-review.md`

**Interfaces:**
- Consumes: validator and review-sheet CLIs
- Produces: four one-level references linked directly from `SKILL.md`

- [ ] **Step 1: Write `diagram-workflow.md` as an output contract**

Use sections `Required outputs`, `Diagram plan schema`, `Diagram brief`, `Asset discovery and identity`, `Manifest contract`, `Reuse modify or derive`, `Change disclosure`, `Validation commands`, and `Completion record`. Include the seven approved planning questions, the tested `diagram-plan.yaml` schema, and a complete manifest with every Task 2 field including route-specific `generation` provenance.

State observable identity predicates:

- same message/model, changed content or layout → modify same ID and set `based_on_revision`;
- different core message/model → new ID and set `derived_from`;
- only slide placement changed → reuse unchanged.

Include exact validator commands for `--plan`, `--manifest`, and `--root`, plus the review-sheet command.

- [ ] **Step 2: Write `diagram-patterns.md` as route recipes**

Create recipes for architecture, flowchart, timeline, statistical, conceptual, hybrid, and status/matrix visuals. Every recipe states default route, editable elements, semantic inputs, layout recipe, and failure checks. Require native SVG for architecture/flow, deterministic data-driven SVG for timeline/statistics/status, and raster plus native overlay for hybrid visuals.

- [ ] **Step 3: Write `generative-visuals.md`**

Use sections `Selection gate`, `Prompt record`, `New image workflow`, `Reference-edit workflow`, `Editable overlay contract`, and `Failure handling`. The prompt record contains purpose, composition, subject, palette, lighting, empty annotation regions, exclusions, aspect ratio, references, and changed regions.

Require runtime image generation for creation/editing and prohibit arbitrary web-image substitution. For edits, provide the earlier image and name changed regions. Exclude prose, labels, legends, exact values, watermarks, and signatures from generated pixels. Put factual annotation into native SVG overlays and declare `hybrid`.

- [ ] **Step 4: Write `visual-review.md`**

Use sections `Render before review`, `Subfigure gate`, `Complete-slide gate`, `Revision loop`, `Review record`, and `Blocked review`. Require actual rendered-pixel inspection and every hard-fail condition from the approved design. Define `review.json` with:

```json
{
  "status": "passed",
  "artifacts": ["subfigure.png", "slide04-review.png"],
  "rounds": 2,
  "findings": [{
    "round": 1,
    "level": "slide",
    "region": "evaluation-stage",
    "issue": "Connector crossed the publishing label.",
    "action": "Routed the connector below the label."
  }]
}
```

Source-markup inspection is not visual review. Missing rendering or vision records a blocker and prevents completion.

- [ ] **Step 5: Scan, commit, and review**

```bash
if rg -n "TBD|TODO|PLACEHOLDER|implement later" \
  skills/report-slides/references/{diagram-workflow,diagram-patterns,generative-visuals,visual-review}.md; then
  exit 1
fi
git add skills/report-slides/references/{diagram-workflow,diagram-patterns,generative-visuals,visual-review}.md
git commit -m "docs(report-slides): define visual authoring contracts"
```

Expected: `rg` has no matches. Complete both `terra:high` reviews and all `luna:max` fixes. Stage only the four Task 4 references, amend the provisional commit, rerun the scan, and assert a clean tree.

---

### Task 5: Integrate the Mandatory Workflow into `SKILL.md`

**Files:**
- Modify: `skills/report-slides/SKILL.md`

**Interfaces:**
- Consumes: Task 4 references and both utility CLIs
- Produces: orchestration satisfying all Task 1 scenarios

- [ ] **Step 1: Update discovery metadata**

Keep `metadata.data_access_level: raw` and `metadata.task_type: open-ended`. Replace the description with a trigger-only `Use when...` sentence covering presentations, research reports, diagram-heavy decks, architecture, flowcharts, timelines, charts, conceptual illustrations, and editable PPTX. Do not summarize process in frontmatter.

- [ ] **Step 2: Add the ordered visual-authoring gate**

Immediately after outline confirmation require:

1. create `diagram-plan.yaml` for every non-trivial visual;
2. search project manifests before drawing;
3. classify as native, data, generative, or hybrid;
4. load only relevant references;
5. generate or modify reusable source;
6. render subfigure and complete slide to pixels;
7. inspect with vision, revise, and repeat;
8. validate manifests;
9. export native PPTX and report validation stages separately.

Steps 1, 2, 6, 7, 8, and 9 are mandatory. Rendering or vision unavailability blocks completion.

- [ ] **Step 3: Correct renderer routing**

Use route tags:

```text
[V:NATIVE] editable SVG shapes and connectors
[V:DATA] deterministic data-driven SVG
[V:AI] generated raster illustration
[V:HYBRID] generated raster base plus editable SVG overlay
```

Direct native SVG is default for editable architecture and flow diagrams. Deterministic data-driven SVG is default for timelines, statistical charts, and status/matrix views. Mermaid is optional only when its output converts correctly or accepted editability loss is disclosed.

- [ ] **Step 4: Add generation, reuse, and reporting contracts**

Require image generation for AI routes, earlier assets as edit references, and explicit blocked behavior. For every visual, the completion report includes diagram type, slide location, selected authoring route, `diagram_id`, action (`created`, `reused`, `modified`, `derived`), reused source, changed regions with reasons, editability, review rounds, separate SVG-preview/PPTX-structure/PPTX-render validation statuses, remaining raster layers, and the rationale for each raster layer.

- [ ] **Step 5: Preserve capabilities and validate**

Retain source selection, styles, data JSON, native SVG-to-PPTX, and embed fallback. Link all four references directly and correct touched commands to `python3`.

```bash
python3 scripts/check_data_access_level.py
python3 scripts/check_task_type.py
python3 /home/ubuntu/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/report-slides
rg -n "diagram-workflow.md|diagram-patterns.md|generative-visuals.md|visual-review.md" skills/report-slides/SKILL.md
```

- [ ] **Step 6: Commit and complete both reviews**

```bash
git add skills/report-slides/SKILL.md
git commit -m "feat(report-slides): require reviewed reusable visuals"
```

Run `terra:high` specification and quality reviews; resume `luna:max` for fixes. Stage only `SKILL.md`, amend the provisional commit, rerun all Task 5 checks, and assert a clean tree before both return `APPROVED`.

---

### Task 6: Run GREEN Forward Tests

**Files:**
- Create: `evals/report-slides-visual-authoring/after.md`
- Modify only for observed gaps: `skills/report-slides/SKILL.md` or one responsible reference

**Interfaces:**
- Consumes: exact prompts and rubric from Task 1
- Produces: explicit passing evidence for every requirement

- [ ] **Step 1: Re-run identical prompts with fresh `luna:max` agents**

Do not expose the rubric, baseline, design, or intended fixes.

- [ ] **Step 2: Score with `terra:high`**

Record verbatim responses and the same score structure in `after.md`. Score only explicit behavior.

- [ ] **Step 3: Refactor only observed gaps**

- Missing output field → strengthen the positive output contract.
- Wrong route → tighten the observable route predicate.
- Skipped hard gate → add blocked-state behavior.
- Missed reference → add a direct conditional link.

Resume the `luna:max` implementer and rerun only affected scenarios.

- [ ] **Step 4: Verify GREEN, commit, and review**

```bash
if rg -n "\[fail\]" evals/report-slides-visual-authoring/after.md; then exit 1; fi
git add evals/report-slides-visual-authoring/after.md
git diff --quiet -- skills/report-slides/SKILL.md || git add skills/report-slides/SKILL.md
for reference in \
  skills/report-slides/references/diagram-workflow.md \
  skills/report-slides/references/diagram-patterns.md \
  skills/report-slides/references/generative-visuals.md \
  skills/report-slides/references/visual-review.md; do
  git diff --quiet -- "$reference" || git add "$reference"
done
git diff --cached --name-only
git diff --cached --check
git commit -m "test(report-slides): verify visual authoring workflow"
```

Unstage unrelated files before commit. Complete both `terra:high` review gates. Any fix stages only `after.md`, `SKILL.md`, and the specifically changed reference from the four-file allowlist, then amends the provisional commit, reruns the affected scenario, and asserts a clean tree.

---

### Task 7: Build and Review an End-to-End Example

**Files:**
- Create: `examples/report-slides/visual-authoring/diagram-plan.yaml`
- Create: `examples/report-slides/visual-authoring/assets/system-pipeline/`
- Create: `examples/report-slides/visual-authoring/assets/research-collaboration/`
- Create: `examples/report-slides/visual-authoring/assets/accuracy-comparison/`
- Create: `examples/report-slides/visual-authoring/slides/`
- Create: `examples/report-slides/visual-authoring/deck.pptx`
- Modify: `.gitignore`
- Modify: `examples/report-slides/README.md`

**Interfaces:**
- Consumes: completed skill, tools, image generation, vision, and native converter
- Produces: a self-contained tracked fixture exception containing native architecture, hybrid illustration, data chart, change disclosure, review records, and editable PPTX

- [ ] **Step 1: Create and commit the prior architecture source**

Build the initial pipeline and create its recoverable baseline commit:

```bash
git add examples/report-slides/visual-authoring/assets/system-pipeline
git commit -m "docs(report-slides): add baseline system pipeline"
PIPELINE_BASE_REV="$(git rev-parse HEAD)"
```

Modify only `evaluation-stage` to add human approval and a failure return. Record `git:<PIPELINE_BASE_REV>` in `based_on_revision`, plus region, bbox, change, and reason. Resolve the variable to the literal commit ID in YAML; do not store the shell variable text.

- [ ] **Step 1b: Track only this example's PNG artifacts**

Append this narrow exception after the existing `*.png` rule in `.gitignore`:

```gitignore
!examples/report-slides/visual-authoring/**/*.png
```

After PNG generation, verify tracking behavior:

```bash
if git check-ignore -q examples/report-slides/visual-authoring/assets/research-collaboration/generated.png; then
  exit 1
fi
git check-ignore -q examples/other/unrelated.png || exit 1
```

Expected: the visual-authoring PNG is not ignored and the unrelated PNG remains ignored.

- [ ] **Step 2: Generate the hybrid illustration**

Use image generation for a generic human–AI laboratory scene with reserved negative space and no text, numbers, signatures, or watermark. Save `prompt.md` and `generated.png`; add factual labels/callouts as separate SVG objects in `source.svg`. Declare `hybrid`.

- [ ] **Step 3: Generate the deterministic chart**

Store and render:

```json
{
  "categories": ["Baseline A", "Baseline B", "Current A", "Current B"],
  "accuracy": [72.1, 81.6, 98.4, 100.0],
  "unit": "percent"
}
```

Axes, labels, legend, and bars remain editable.

- [ ] **Step 4: Render, inspect, revise, and record**

Render every subfigure and slide to PNG and compose review sheets. `terra:high` visually inspects them; `luna:max` fixes findings until review records pass. If no renderer or vision is available, stop rather than approve source markup.

- [ ] **Step 5: Export and validate PPTX**

```bash
cd skills/report-slides/scripts
python3 -m svg_to_pptx \
  --slides ../../../examples/report-slides/visual-authoring/slides \
  --out ../../../examples/report-slides/visual-authoring/deck.pptx \
  --mode native
```

Use `python-pptx` to verify multiple architecture shapes plus connector, multiple chart objects, and a hybrid picture plus separate text/shapes. If an office renderer exists, compare rendered PPTX pixels with approved SVG previews and report structural and pixel validation separately.

- [ ] **Step 6: Validate, document, commit, and review**

Validate every manifest with `--manifest`. Update the example README to explain native, hybrid, data, reuse, and review artifacts.

```bash
git add .gitignore examples/report-slides/visual-authoring examples/report-slides/README.md
git diff --cached --name-only
git diff --cached --check
git commit -m "docs(report-slides): add reviewed visual authoring example"
```

Complete both `terra:high` gates and all `luna:max` fixes. Stage only `.gitignore`, the example directory, and its README, amend the provisional commit, rerun manifest/PPTX checks, and assert a clean tree.

---

### Task 8: Run the Full Verification Gate

**Files:** Modify only if verification exposes a concrete defect.

**Interfaces:**
- Consumes: all implementation and example artifacts
- Produces: final test, policy, visual, and editability evidence

- [ ] **Step 1: Run focused tests**

```bash
PYTHONPATH=skills/report-slides/scripts python3 -m pytest \
  skills/report-slides/scripts/tests/test_validate_diagram_manifest.py \
  skills/report-slides/scripts/tests/test_render_review_sheet.py \
  skills/report-slides/scripts/tests/test_setup_scripts.py -q
```

- [ ] **Step 2: Run converter regressions**

```bash
cd skills/report-slides/scripts
python3 -m pytest svg_to_pptx/tests -q
```

- [ ] **Step 3: Run skill and repository checks**

From repository root:

```bash
python3 scripts/check_data_access_level.py
python3 scripts/check_task_type.py
python3 /home/ubuntu/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/report-slides
git diff --check
```

- [ ] **Step 4: Revalidate example manifests and visuals**

```bash
for manifest in examples/report-slides/visual-authoring/assets/*/manifest.yaml; do
  python3 skills/report-slides/scripts/validate_diagram_manifest.py --manifest "$manifest"
done
```

Use `terra:high` to inspect final review sheets and rendered PPTX output. Confirm no overflow, overlap, broken connector, fake text, data mismatch, weak contrast, inconsistent styling, or undisclosed raster information.

- [ ] **Step 5: Confirm evidence and clean state**

```bash
test -s evals/report-slides-visual-authoring/baseline.md
test -s evals/report-slides-visual-authoring/after.md
if rg -n "\[fail\]" evals/report-slides-visual-authoring/after.md; then exit 1; fi
test -z "$(git status --porcelain)"
```

- [ ] **Step 6: Complete final independent reviews**

Regardless of whether verification found a defect, run a `terra:high` full-spec compliance review followed by a separate `terra:high` code/document quality review. Any finding returns to `luna:max`, reruns the affected verification, and repeats both review gates.

When verification or final review finds a defect, stage only the exact files named by the finding, inspect `git diff --cached --name-only`, run `git diff --cached --check`, and create a narrow `fix(report-slides): <concrete defect>` commit. Rerun the full verification gate and assert a clean tree.

Expected: all commands pass, post-change scores contain no failure, the two final reviewers return `APPROVED`, and the tree is clean.
