---
name: report-slides
description: Use when creating presentations and research reports, especially diagram-heavy decks with architecture, flowcharts, timelines, charts, conceptual illustrations, or editable PPTX output.
metadata:
  data_access_level: raw
  task_type: open-ended
---

# Report Slides

Generates a slide deck from research log entries using three source paths:
- **[A]** `generate_slides.py` — data-driven slides (charts, tables, metrics)
- **[B]** Mermaid (`mmdc`) — diagram slides (flowcharts, architectures, state machines)
- **[C]** Claude SVG — free-form slides (conceptual layouts, text-heavy content)

Every non-trivial visual goes through the mandatory visual-authoring gate below.
After generation, slides can optionally be exported as native editable PPTX shapes,
with SVG embedding retained as the backward-compatible fallback.

---

## Setup (first use in a project)

### Step 1 — Resolve directories (always first)

**Resolve the slides and research-log directories before anything else** — in
particular before the auto-setup check in Step 2, which creates directories
under `$SLIDES_DIR` (see `skills/resource-resolver/SKILL.md`):

```bash
# macOS / Linux / Git Bash:
RESOLVE="$(find ~/.claude -path "*/resource-resolver/scripts/resolve.py" | head -1)"
SLIDES_JSON=$(python "$RESOLVE" --role slides --json)
SLIDES_DIR=$(echo "$SLIDES_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
if d.get('status') == 'resolved':
    print(d['primary'])
")
LOG_JSON=$(python "$RESOLVE" --role research_log --json)
RESEARCH_LOG_DIR=$(echo "$LOG_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
if d.get('status') == 'resolved':
    print(d['primary'])
")
```

```powershell
# Windows (PowerShell):
$RESOLVE = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter resolve.py |
    Where-Object FullName -like "*resource-resolver*" | Select-Object -First 1).FullName
$SlidesJson = python $RESOLVE --role slides --json | ConvertFrom-Json
$SLIDES_DIR = if ($SlidesJson.status -eq "resolved") { $SlidesJson.primary } else { "" }
$LogJson = python $RESOLVE --role research_log --json | ConvertFrom-Json
$RESEARCH_LOG_DIR = if ($LogJson.status -eq "resolved") { $LogJson.primary } else { "" }
```

Only a `"resolved"` status yields a usable path — a `stale_mapping` response
also carries a non-empty `primary`, so never read `primary` without checking
`status`. If either variable comes back empty, inspect the corresponding JSON
(`$SLIDES_JSON` / `$LOG_JSON`) and follow the branching rules in the "Calling
convention for other skills" section of `skills/resource-resolver/SKILL.md`:
an `error` key means surface `message` and stop; `status: "stale_mapping"`
means the configured directory is gone and the user must re-confirm it (do not
silently recreate it); only `"unresolved"` / `"no_candidates"` leads to the
normal first-use confirmation flow.

**Do not run Step 2 until `$SLIDES_DIR` is a confirmed, non-empty path.**
Setup creates directories under it, and creating them from an unconfirmed or
empty value would write outside the intended project layout.

The rest of this file refers to the resolved slides directory as
`$SLIDES_DIR` and the resolved research log directory as `$RESEARCH_LOG_DIR`.

Shell state does not persist across separate tool-call invocations. When a
later section needs these paths in a new bash/PowerShell call, either re-run
the resolve snippet above in that same call, or substitute the already-resolved
path as a literal value into the command.

### Step 2 — Install project scripts

**macOS / Linux / Git Bash:**
```bash
bash "$(find ~/.claude -path "*/report-slides/scripts/setup.sh" | head -1)" "$SLIDES_DIR"
```

**Windows (PowerShell):**
```powershell
& (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter setup.ps1 |
    Where-Object FullName -like "*report-slides*" | Select-Object -First 1).FullName $SLIDES_DIR
```

This copies `generate_slides.py`, `validate_diagram_manifest.py`, and `render_review_sheet.py` into `scripts/` and creates both `$SLIDES_DIR/reports/` and `$SLIDES_DIR/assets/diagrams/`. `to_pptx.py` stays in the skill bundle and is invoked directly from there.

**Auto-setup:** if you invoke `/report-slides` and `scripts/generate_slides.py` is missing, run the setup command above automatically before proceeding — no need to ask the user. This is only ever automatic *after* Step 1 has produced a confirmed `$SLIDES_DIR`; if the `slides` role is still unconfigured or stale, resolve and confirm it with the user first, because setup creates directories.

Check for Mermaid (optional, for diagram slides):
```bash
# macOS / Linux
which mmdc && echo "Mermaid OK" || echo "Mermaid missing (npm i -g @mermaid-js/mermaid-cli)"
# Windows
Get-Command mmdc -ErrorAction SilentlyContinue && "Mermaid OK" || "Mermaid missing (npm i -g @mermaid-js/mermaid-cli)"
```

---

## Style system

Slides inherit colors and fonts from a **style file** — a `.md` file with YAML frontmatter.
Three built-in styles ship with this skill: `default`, `minimal`, `dark`, `paper`.
Full schema and color role descriptions are in `references/styles/STYLES.md` (read it when resolving styles).

**Project default:** if `$SLIDES_DIR/_style.md` exists it is applied automatically to every deck.

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
and the path is resolved and validated at the gate.

`--style` and `--tokens` are composed before rendering, not applied in sequence
afterwards. The result is written to `<out>/_effective.tokens.yaml`, and that
file — not the file passed to `--tokens` — is what `$STYLE_TOKENS_REF` must
point at for the rest of the pipeline. A style file may set the value of a
colour role or the sans font family; a key naming no role is an error, because
the role names are the vocabulary every downstream check is written against.

### set-style \<name\>

Copy a built-in style as the project default (one command):

```bash
# macOS / Linux / Git Bash:
bash "$(find ~/.claude -path "*/report-slides/scripts/set-style.sh" | head -1)" <name>
# Windows (PowerShell):
& (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter set-style.ps1 |
    Where-Object FullName -like "*report-slides*" | Select-Object -First 1).FullName <name>
# built-in names: default  minimal  dark  paper
```

To **create a custom style**: make `$SLIDES_DIR/styles/<name>.md` using the schema in
`references/styles/STYLES.md`, then copy it to `$SLIDES_DIR/_style.md` to activate it as the project default.

---

## Workflow

This is a 15-stage, approval-gated, multi-agent pipeline. `presentation_state.py`
is the state machine of record: every stage transition below is a call into it,
not a prose convention. Nothing that is not deterministic orchestrator logic is
performed by the orchestrator itself — planning, review, and visual authoring
are always dispatched to a named agent via the Task tool, and the orchestrator's
job is to create records, validate agent output, and gate transitions.

### Schema-v2 migration preflight

Run the presentation workflow from the project root. Before the first workflow
action for an existing presentation state, inspect the `version` or
`schema_version` header in every YAML file under
`.research/presentations/state/`. All existing state stores must have one
shared schema version; mixed, malformed, or unsupported headers are not safe to
infer from a single file.

The required operator flow is:

```text
inspect schema -> migrate-state --dry-run -> migrate-state -> workflow action
```

Use the existing migration entry point; it is the only state-migration command:

```bash
PROJECT_ROOT="$(git rev-parse --show-toplevel)"
MIGRATE="$(find ~/.claude -path "*/report-slides/scripts/migrate_presentation_state.py" | head -1)"

STATE_DIR="$PROJECT_ROOT/.research/presentations/state"
if [ -d "$STATE_DIR" ]; then
  rg -n --glob '*.yaml' '^(version|schema_version):' "$STATE_DIR"
else
  echo "No presentation state exists; continue with Stage 1."
fi

# Preview first: this creates no locks, directories, sidecars, journals,
# backups, CAS objects, or mtimes.
python3 "$MIGRATE" --project-root "$PROJECT_ROOT" --dry-run --json

# Apply only after reviewing the dry-run JSON report.
python3 "$MIGRATE" --project-root "$PROJECT_ROOT" --json
```

Schema 0 and schema 1 are read-only workflow states. Any workflow write before
migration fails with the structured JSON error `MigrationRequiredError` and
identifies its source and required target schema version. After successful
migration, schema 2 is the only workflow-write schema; re-running migration on
schema 2 is an exact no-op.

Schema-2 gates authorize only the immutable evidence envelope selected by the
current deck pointer and the corresponding verified CAS bytes. They never fall
back to a legacy event or a path-based assertion. Operational lock sidecars
coordinate access only: they are not workflow evidence. Historical envelopes
remain audit history, but an envelope marked `historical_unavailable` cannot
authorize a current gate. A targeted revision preserves prior immutable
evidence and clears the current preview, draft-approval, and completion
evidence pointers; create and validate fresh current evidence before the next
gated action.

### 1. Create the Deck

Orchestrator. After Setup, before asking the user anything, create the Deck
record so every later stage has a `$DECK_ID` to attach state to:

```bash
PSTATE="$(find ~/.claude -path "*/report-slides/scripts/presentation_state.py" | head -1)"
DECK_JSON=$(python3 "$PSTATE" --create-deck --title "<deck working title>" --json)
DECK_ID=$(echo "$DECK_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
```

`deck.status` starts at `planning`. Enforcement Mechanism (the exact rule from
the design spec): no SVG, PNG, PPTX, or manifest is ever written before
`deck.status` reaches `approved`, and this is enforced by
`--check-production-allowed` (Stage 14), not by prose discipline — a
production call against an unapproved deck fails closed.

### 2. Ask (one message)

Before asking, show the user what already exists to select from — reuse the
existing log-discovery step:

```bash
cat "$RESEARCH_LOG_DIR/INDEX.md" 2>/dev/null \
  || find "$RESEARCH_LOG_DIR" -maxdepth 1 -name "*.md" ! -name "INDEX.md" | sort -r | head -20
```

Show the user which entries exist and which have already been made into slide
decks. If no log files exist, tell the user to run `/research-log add` first
and stop.

**Academic data source (optional).** When the user passes `--source academic`
or selects "academic pipeline" as source in the question below:

1. Check for a passport YAML file (default: `docs/passport.yaml`; override with `--passport <path>`)
2. Run the bridge script to extract stage data:
   ```bash
   BRIDGE="$(find ~/.claude -path "*/research-lab-skills/bridge/scripts/passport_to_log.py" 2>/dev/null | head -1)"
   python3 "$BRIDGE" --passport docs/passport.yaml
   ```
3. Use the extracted stage records as input for slide generation instead of research-log entries.

If no passport file exists, fall back to research-log source and notify the user.

This is the existing questionnaire — copy it verbatim from the current file,
unchanged; it still runs before any planning:

1. Source? (`research-log` = experiment logs (default) / `academic` = pipeline passport data)
   If research-log: which logs? (`all` / `recent-N` / by name / date range)
   If academic: passport file path? (default: `docs/passport.yaml`)
2. Audience? (advisor / team meeting / conference)
3. Charts? (`list` = output paths to `chart_list.md` / `embed` = base64 into SVG)
4. Language? (follow log language / force English / force another language)
5. Emphasis? (progression / final results / failure analysis / let Claude decide)
6. Style? (skip = use `$SLIDES_DIR/_style.md` if present / name a built-in / `custom` to create one)

Read the selected log files (or the academic bridge output) and any
`CLAUDE.md` for project context and baselines. This resolved log/passport
content is exactly what Stage 3 receives.

### 3. Narrative planning

Dispatch `research_narrative_planner_agent` (Task tool) with: the resolved
log/passport content from Stage 2, `$DECK_ID`, and instructions to write
`.research/presentations/decks/$DECK_ID/plan.yaml` (a Deck Plan document per
the design spec §3 contract table) and return its path. Orchestrator then
runs:

```bash
DDP="$(find ~/.claude -path "*/report-slides/scripts/validate_deck_plan.py" | head -1)"
python3 "$DDP" --plan ".research/presentations/decks/$DECK_ID/plan.yaml" --json
```

A non-`valid` result is a bug in the agent's output, not a workflow state —
re-dispatch the same agent with the validator's errors, do not proceed. Once
valid, `deck.status: planning -> content_review`.

### 4. Content review

Dispatch `content_reviewer_agent` with the Deck Plan path. The agent returns a
Review Result (`subject_type: plan`, `subject_id: $DECK_ID`); orchestrator
writes it and validates:

```bash
python3 "$PSTATE" --record-review --subject-type plan --subject-id "$DECK_ID" \
    --reviewer-role content_reviewer --status <passed|failed> \
    --findings-json "$(cat review_result_findings.json)" --round 1 --json
VVR="$(find ~/.claude -path "*/report-slides/scripts/validate_visual_review.py" | head -1)"
python3 "$VVR" --review-result review_result.json
```

If `status: failed`, `deck.status` stays `content_review`; feed the findings
back into the Research Narrative Planner (Stage 3) as a Revision Request
(`--create-revision-request --subject-type plan --subject-id "$DECK_ID"
--requested-by reviewer --instructions "<findings summary>"`) and re-run
Stage 3-4 against a new `plan_version`. If `status: passed`, `deck.status:
content_review -> awaiting_approval`.

### 5. Approval gate

Orchestrator, interactive by default. Present the approved-by-content-review
Deck Plan to the user in the same style as the current outline-confirmation
prompt — a numbered slide list, one line per slide: title plus intended
visual type tag:

```
Proposed slide structure (N slides):

#01  Title                   [C]
#02  Background & Goal       [C: two_column]
#03  Experiment Timeline     [A: bullet_list] [V:DATA]
#04  Changes                 [A: bullet_list] [V:DATA]
#05  Results                 [A: bar_chart]   [V:DATA]
#06  Comparison              [A: table]       [V:DATA]
#07  Architecture            [C: native SVG]  [V:NATIVE]
#08  Conclusion & Next Steps [C: conclusion]

[A] Python  [B] Mermaid  [C] Claude SVG

Confirm? (say "ok" to proceed, or specify changes)
```

Wait for one of: `approve`, or a revision instruction (`revise a slide`, `add
a slide`, `remove a slide`, `reorder`, `change emphasis`, `change audience`,
`change duration`). A revision instruction becomes a Revision Request fed
back to Stage 3 exactly as in Stage 4's revise path (`deck.status:
awaiting_approval -> planning`), and the plan re-enters Stage 3-5. On
`approve`:

```bash
python3 "$PSTATE" --set-deck-status --deck-id "$DECK_ID" --status approved --json
```

Write `.research/presentations/decks/$DECK_ID/approval.yaml` (Deck Approval
document: `decision: approve`, `approved_by`, `approved_at`).

#### Non-interactive escape hatch (applies to Stages 1-5 as a whole)

If invoked with `--yes`, skip the interactive wait in Stage 5 only — Stages
3-4 (planning and content review) still run and must still pass — and
auto-approve with `approved_by: "auto (--yes)"`. If invoked with
`--approved-plan-file PATH`, skip Stages 3-4-5 entirely: validate the given
file with `validate_deck_plan.py --plan`, copy it to
`.research/presentations/decks/$DECK_ID/plan.yaml`, and go directly to
`deck.status: planning -> approved` with `approved_by: "pre-approved
(--approved-plan-file)"`. Without either flag, legacy single-message
invocation (today's default) still creates a Deck and passes through
`content_review -> awaiting_approval` and stops for the interactive gate —
this is the concrete mechanism satisfying "Legacy invocation must now enter
the approval workflow unless an explicit non-interactive option is
provided."

### 6. Slide specification

Before creating any Slide record, move the deck out of `approved` and into
production — `approved` only ever transitions to `producing` (or `blocked`),
and Stage 13's later `producing -> draft_review` transition depends on the
deck having reached `producing` here:

```bash
python3 "$PSTATE" --set-deck-status --deck-id "$DECK_ID" --status producing --json
```

For each `SlidePlanEntry` in the approved plan:
`python3 "$PSTATE" --create-slide --deck-id "$DECK_ID" --plan-slide-id
<slide-01> --title "<title>" --json`, then dispatch `slide_architect_agent`
with that slide's plan entry, returning a Slide Specification written to
`.research/presentations/decks/$DECK_ID/slides/<plan_slide_id>/spec.yaml`,
including the `complexity_signals` object (`region_count`, `route_count`,
`multi_stage`, `mixed_technique`, `heavy_cross_region_connections`,
`expected_reuse`, `not_atomic`). `slide.status: planned -> ready`.

### 7. Complexity detection

Orchestrator, deterministic, per slide:

```bash
CVD="$(find ~/.claude -path "*/report-slides/scripts/complex_visual_detector.py" | head -1)"
python3 "$CVD" --signals ".../spec.yaml#complexity_signals-as-json" --json
```

(Extract `complexity_signals` from the Slide Specification into a small JSON
file first — `complex_visual_detector.py` takes `--signals PATH` pointing at
a signals-only document, not the full spec.) The result's
`requires_complex_workflow` decides the branch: `false` → skip to Stage 9
using exactly today's `generate_slides.py`/agent-authored-SVG path for this
slide (Compatibility Criterion 2 — no module is created, the slide moves
`ready -> assigned -> producing -> review_required -> passed` directly
against its own single visual). `true` → continue to Stage 8.

### 8. Complex visual decomposition

Only for slides where Stage 7 returned `true`. Dispatch
`complex_visual_decomposer_agent` with the Slide Specification; it returns a
Complex Visual Specification (written to
`.research/presentations/decks/$DECK_ID/slides/<plan_slide_id>/visual_spec.yaml`).
Validate:

```bash
DVM="$(find ~/.claude -path "*/report-slides/scripts/validate_visual_module.py" | head -1)"
python3 "$DVM" --spec ".../visual_spec.yaml" --json
```

Then create one Visual Module record per `ModuleSpec`. `--dependencies` takes
the state store's own generated `id`s (e.g. `module_xxxxx`), never the
Complex Visual Specification's `module_key`s — `create_visual_module` raises
`VisualModuleNotFoundError` for anything not already a real record in the
store. This means:

- **Modules must be created in dependency order.** A `ModuleSpec` whose
  `dependencies` list is non-empty cannot be created until every module it
  depends on already exists as a record — topologically sort `modules` by
  `dependencies` before issuing any `--create-visual-module` call.
- **The orchestrator must maintain a `module_key -> generated id` mapping.**
  Each `--create-visual-module --json` call returns the new record's
  generated `id`; store it keyed by that `ModuleSpec`'s `id` (its
  `module_key`). Before creating a later module, translate its
  `ModuleSpec.dependencies` (module_keys) through this mapping into the
  corresponding generated ids and pass only those to `--dependencies`.

```bash
declare -A MODULE_ID_MAP  # module_key -> generated id, populated as each module is created
# For a module whose ModuleSpec.dependencies are module_keys already present in MODULE_ID_MAP:
RESOLVED_DEPS=()
for dep_key in "${MODULE_SPEC_DEPENDENCIES[@]}"; do
    RESOLVED_DEPS+=("${MODULE_ID_MAP[$dep_key]}")
done
MODULE_JSON=$(python3 "$PSTATE" --create-visual-module --slide-id "$SLIDE_ID" --module-key <module-id-from-spec> \
    --module-type <data_visualization|architecture|conceptual|annotation> \
    --dependencies "${RESOLVED_DEPS[@]}" --json)
MODULE_ID_MAP[<module-id-from-spec>]=$(echo "$MODULE_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
```

### 9. Module production

Every Visual Module created in Stage 8 starts at `planned`. The legal path to
`producing` is `planned -> ready -> assigned -> producing` — `planned ->
producing` is illegal and raises `ValueError` at runtime, so the orchestrator
must walk each intermediate state explicitly:

1. **`planned -> ready`.** Once Stage 8 finishes creating a module's record,
   transition it to `ready`: `python3 "$PSTATE" --set-module-status
   --module-id "$MODULE_ID" --status ready --json`.
2. For each Visual Module at `ready` whose dependencies are all `passed`
   (query with `--query --deck-id "$DECK_ID" --json` and inspect
   `visual_modules`), write its **Worker Assignment** document to
   `.research/presentations/decks/$DECK_ID/slides/<plan_slide_id>/modules/<module_key>/assignment.yaml`
   (fields: `module_id` the store's generated id, `worker_type` one of
   `data_visualization|architecture|conceptual|annotation`, `assigned_at`,
   `inputs_resolved: bool`, `blocker: str|null`), then validate it:
   ```bash
   DVM="$(find ~/.claude -path "*/report-slides/scripts/validate_visual_module.py" | head -1)"
   python3 "$DVM" --assignment ".../modules/<module_key>/assignment.yaml" --json
   ```
3. **`ready -> assigned`.** `python3 "$PSTATE" --set-module-status
   --module-id "$MODULE_ID" --status assigned --json`, then dispatch the
   matching worker agent by `module_type`: `data_visualization_worker_agent`,
   `architecture_diagram_worker_agent`, `conceptual_illustration_worker_agent`,
   or `annotation_worker_agent` — pass the Worker Assignment's path in the
   dispatch so the worker knows where to read its assignment from.
4. **`assigned -> producing`.** `python3 "$PSTATE" --set-module-status
   --module-id "$MODULE_ID" --status producing --json` — this call itself
   fails if a dependency is not yet `passed`, so it doubles as the readiness
   check.

Independent modules (no shared dependency) may be dispatched in the same turn
since each is a separate Task-tool call; a module whose dependency has not yet
reached `passed` stays at `ready` (or `blocked`) — it does not advance to
`assigned`/`producing` until that dependency resolves. Each worker writes its
module's own manifest via the mandatory visual-authoring gate below
(§9.1-9.4) — reused unchanged from the pre-redesign workflow per §5 of the
design spec, since each module is its own `diagram_id`-equivalent asset — and
returns; orchestrator sets `--status review_required`.

#### 9.1 Mandatory visual-authoring gate

Immediately after outline confirmation, before drawing or generating any visual,
run this ordered gate for every non-trivial visual, including charts and
conceptual illustrations:

1. **Plan:** create `diagram-plan.yaml` with one entry per visual.
2. **Discover:** search project `manifest.yaml` files by purpose, diagram type,
   and semantic regions before drawing.
3. **Classify:** select exactly one route: native, data, generative, or hybrid,
   and record its route tag.
4. **Reference:** load only the relevant references below for the selected route.
5. **Author:** create or modify a reusable source; resolve reuse, modification,
   or derivation identity before route-specific generation. **Tabular data and
   charts MUST be authored as `<g data-pptx-role="table"|"chart"
   data-pptx-source="..." data-pptx-bbox="x,y,w,h">` around the preview
   markup, never as hand-drawn grid rects or bars — see
   `references/diagram-patterns.md`. Any semantic diagram node (a box plus
   icon plus label, a timeline event, a legend entry) MUST be wrapped in
   `<g data-pptx-role="group" data-node-id="...">`. These are hard
   requirements enforced by `validate_native_objects.py` (step 8), not style
   preferences.**
6. **Render:** render both the subfigure and the complete slide to pixels.
7. **Review:** inspect both pixel renders with model vision, revise the source,
   and repeat the render/vision loop until both gates pass.
8. **Manifest:** validate the plan, each manifest, and the asset root:
   `python3 scripts/validate_diagram_manifest.py --plan <plan>`,
   `python3 scripts/validate_diagram_manifest.py --manifest <manifest>`, and
   `python3 scripts/validate_diagram_manifest.py --root <asset-root>`. Also
   run the native-object safety net against the slide's SVG directory:
   `python3 scripts/validate_native_objects.py --svg-dir <dir>` — a non-zero
   exit is a hard blocker; fix the missing marker and re-render.
9. **output-format branch — export, convert, and directly inspect, or mark
   not applicable:**

   ```
   if output_format is pptx:
       require statuses.svg_preview passed before export
       export the actual deck.pptx
       run `python3 scripts/validate_native_objects.py --pptx <deck.pptx>` as
           a hard blocker before validating package structure -- a non-zero
           exit means a table/chart/node pattern reached the PPTX without
           its native construct; fix the source marker or converter branch
           and re-export
       validate package structure into statuses.pptx_structure
       convert the actual deck.pptx with LibreOffice or an equivalent
           office renderer (never the source SVG)
       produce exactly one final PNG for every expected slide under
           rendered_png_paths
       send every final PNG path directly to model_vision as
           model_vision.inspected_paths
       record statuses.pptx_render
       allow completion only when statuses.svg_preview,
           statuses.pptx_structure, and statuses.pptx_render are all passed
   otherwise:
       record both statuses.pptx_structure and statuses.pptx_render as
           not_applicable with a non-empty reason
       use statuses.svg_preview as the final, authoritative visual gate
   ```

   `statuses.pptx_render` is the authoritative final visual gate for a PPTX
   deliverable: a source SVG preview and a passing `statuses.pptx_structure`
   never override it. Unavailable conversion or unavailable/partial direct
   final-PNG inspection is `blocked`, not `passed` — a source PNG, a review
   sheet, or the structure report cannot satisfy the missing
   `model_vision.inspected_paths` evidence. A `blocked` or `failed` status on
   any required gate sets `overall.completion_allowed` to `false`.

Missing rendering or model-vision review is a hard blocker: retain the failing
artifact, record the blocker, and do not mark the visual or deck complete.

#### 9.2 Visual routes and references

In `diagram-plan.yaml`, set the validator-facing `route` field. In
`manifest.yaml`, set the validator-facing `authoring_route` field. Both fields
must use exactly one enum value: `native`, `data`, `generative`, or `hybrid`.
The bracketed values below are display/report/outline tags, not validator enum
values:

| Display/report/outline tag | Route and default |
|---|---|
| `[V:NATIVE]` | Editable SVG shapes and connectors; default for architecture and flowcharts. |
| `[V:DATA]` | Deterministic data-driven SVG; default for timelines, statistical charts, and status/matrix views. |
| `[V:AI]` | Runtime-generated raster illustration for conceptual visuals when native shapes are not sufficient. |
| `[V:HYBRID]` | Runtime-generated raster base plus an editable SVG overlay for factual annotations and structure. |

Direct native SVG is the default for editable architecture and flow diagrams.
Mermaid is optional only when its output converts correctly; if conversion
loses editability, disclose that loss in the manifest and completion report.
Do not label an embedded or raster-only Mermaid result as `[V:NATIVE]`.

Read only the references needed for the selected route and gate:

- [diagram-workflow.md](references/diagram-workflow.md) — plans, manifests, identity, and completion records.
- [diagram-patterns.md](references/diagram-patterns.md) — route recipes and failure checks.
- [generative-visuals.md](references/generative-visuals.md) — runtime generation and reference edits.
- [visual-review.md](references/visual-review.md) — pixel rendering, vision review, and blockers.

#### 9.3 Generation, reuse, and reporting contract

- `[V:AI]` and `[V:HYBRID]` require runtime image generation for creation or
  editing. For an edit, provide the earlier asset to the image-generation
  capability and name every changed region and reason. Never substitute an
  arbitrary web image or unrelated redraw.
- Search manifests before authoring. Assets remain `reused` when unchanged,
  including for placement-only changes. If the core message and model stay the same, modify
  the same `diagram_id` with `based_on_revision` only for a content/layout
  revision. A changed core message or model derives a new ID with `derived_from`.
  Missing generation capability, an edit reference, rendering, vision, or
  factual input blocks the affected visual; do not silently fall back.
- The completion report records, for every visual: `diagram_type`, `slide`,
  `authoring_route` and route tag, `diagram_id`, action (`created`, `reused`,
  `modified`, or `derived`), reused source, changed regions with reasons,
  editability, remaining raster layers, and the rationale for each raster
  layer. It records the review evidence using the exact record field names —
  `statuses.svg_preview`, `statuses.pptx_structure`, `statuses.pptx_render`,
  each with `reviewed_by`, `inspected_paths`, `findings`, `revision_required`,
  and its review-round number — never the three gates collapsed into one
  status. For a PPTX deliverable, the `statuses.pptx_render` entry also
  carries `renderer.name`, `renderer.version`, `renderer.conversion_format`,
  `conversion_artifacts`, `rendered_png_paths`, `model_vision.inspected_paths`,
  and `visual_checks`; `model_vision.inspected_paths` must equal the converted
  PNG set named in `rendered_png_paths` — `comparison_reference_paths` are
  optional diagnostics only and never substitute for that set. `overall`
  reports `overall.authority` (`pptx-render` for PPTX output,
  `source-pixel` otherwise) and `overall.completion_allowed`; an open finding
  or an incomplete direct-inspection set keeps `completion_allowed` `false`.

#### 9.4 Response-facing contract

Fresh plans and completion responses must expose these required fields and
claims:

- **High-priority reuse scenario:** When the user asks whether to modify/redraw
  an existing visual, the answer **MUST** be a filled concrete record using
  `manifest_asset_search`, `slide`, `diagram_id`, `action`, `reused_source`,
  `based_on_revision`, `changes` with a numeric `bbox` expressed as
  `[x1, y1, x2, y2]` endpoint coordinates, `change`, and `reason`,
  and `delivery_summary`; do not answer with instructions such as `report
  <actual slide>`, angle-bracket placeholders, `[x,y]` placeholders, or a
  prose-only checklist. If no source or revision can actually be discovered,
  output an explicit blocker record instead of fabricating continuity. Planning
  examples may use the concrete representative record already shown.

- `regions`: Architecture and flow plans enumerate every named subfigure or
  semantic region in `diagram-plan.yaml` and repeat the same names in the
  response.
- `review`: State explicitly that each subfigure and the complete slide were
  rendered to pixels, inspected with model vision, and revised and re-rendered
  until passing; validation-status lists alone are insufficient. For a PPTX
  deliverable, additionally state that the actual `deck.pptx` was converted
  with LibreOffice (or an equivalent office renderer) and that every
  converted PNG under `rendered_png_paths` was directly inspected by
  `model_vision` before `statuses.pptx_render` was recorded — a source-pixel
  pass and a passing `statuses.pptx_structure` are not substitutes for that
  direct inspection.
- `generation` and `editability`: For `route: generative` /
  `authoring_route: generative` `[V:AI]` and `route: hybrid` /
  `authoring_route: hybrid` `[V:HYBRID]`, name `prompt.md` and report manifest
  `generation.prompt`, `generation.output`, and `generation.references`
  provenance, plus editability and any raster, embedding, or conversion-loss
  disclosures.
- Filled example: `manifest_asset_search: "found assets/diagram-library/human-review-flow.svg"; slide: 4; diagram_id: human-review-flow-v2; action: modified; reused_source: assets/diagram-library/human-review-flow.svg; based_on_revision: git:4b29f2a; changes: [{region: human-review-branch, bbox: [612, 184, 860, 316], change: "clarified approval branch", reason: "approval branch"}]; delivery_summary: "Modified slide 4 using the reused human-review flow asset."`
- `reuse.action`, `based_on_revision`, and `changes`: State that the
  asset-library/manifest search happened first. Same-core-message-and-model
  revisions use a concrete, non-placeholder `based_on_revision` value and
  list every changed `region` with its `bbox` and `reason`. Unchanged
  placement-only assets remain `reuse` in the plan and `reused` in the
  response; core-message or model changes use a new ID with `derived_from`.
  Reuse/change prompts must return a filled record (not instructions), with
  `manifest_asset_search` set to a found result or blocker and all of `slide`,
  `diagram_id`, `action`, `reused_source`, `based_on_revision`, `changes`
  (named `region`, numeric `bbox` in `[x1, y1, x2, y2]` endpoint-coordinate
  form, `change`, and `reason`), and
  `delivery_summary`.

##### Reuse/change response template

Every fresh execution answer must be a filled concrete record, not
instructions. Begin by stating the `manifest/asset-library search` result,
including the found source or blocker. Then include `slide`, `diagram_id`,
`action`, `reused_source`, and `based_on_revision`; list `changes` with a
named `region`, numeric `bbox`, `change`, and `reason` for each entry; finish
with a change-focused `delivery_summary`.
Every `bbox` is an endpoint-coordinate tuple `[x1, y1, x2, y2]` within the
1200x675 slide; never use `[x, y, width, height]`.

Planning examples may use clearly labeled representative concrete values.
Execution responses must use the discovered revision and never fabricate
continuity. An unavailable source or revision blocks completion. Placement-
only changes remain `reuse` in plans and `reused` in responses; a changed
core message or model still derives a new ID with `derived_from`.

```yaml
manifest_asset_search: "Found source via assets/manifest.yaml: assets/diagram-library/human-review-flow.svg"
slide: 4
diagram_id: human-review-flow-v2
action: modified
reused_source: assets/diagram-library/human-review-flow.svg
based_on_revision: "git:4b29f2a"
changes:
  - region: human-review-branch
    bbox: [612, 184, 860, 316]
    change: "Added the reviewer decision split."
    reason: "Make approval and rejection outcomes explicit."
  - region: failure-return-path
    bbox: [780, 356, 1084, 452]
    change: "Rerouted the return connector to the retry node."
    reason: "Show the actual failure recovery path."
delivery_summary: "Modified slide 4 from git:4b29f2a; changed two regions and preserved placement-only reuse."
```

**Dynamic inclusion rules:**
- Timeline: only with ≥2 entries linked via `follows:`
- Architecture: only if logs describe structural/model changes
- Failure slide: only if logs have content under `## Failures`
- Fewer slides (4–5) for single-entry logs; more for conference talks

### 10. Visual integration

Once every module for a slide is `review_required` or later, dispatch
`visual_integration_agent` with all of that slide's module manifests and the
Complex Visual Specification's `connections`/`layout`. It assembles the
integrated SVG and writes the integration manifest (`modules_ref` pointing at
the Complex Visual Specification, per §5 of the design spec).

**Visual-style gate (deterministic, blocking).** Before any reviewer is
dispatched for a slide, run the linter over that slide's authored SVG:

```bash
VVS="$(find ~/.claude -path "*/report-slides/scripts/validate_visual_style.py" | head -1)"
# $SLIDE_SVG is the integrated SVG this stage just wrote; $STYLE_TOKENS_REF is
# the `_effective.tokens.yaml` from §"Tokens and style", not the file passed to
# `--tokens` at generation time.
timeout 120 python3 "$VVS" \
  --svg "$SLIDE_SVG" --tokens "$STYLE_TOKENS_REF" --json \
  --record "$PROJECT_ROOT" --subject-type slide --subject-id "$SLIDE_ID"
```

The validator is run out of the installed skill bundle, like every other
validator in this file. It is not copied into the project by `setup.sh`: it
imports `visual_style/`, `fonts.py`, and `design_tokens.py` from beside itself,
and those resolve only in the bundle. Run it once per slide: `--subject-id`
names the slide the recorded result belongs to, so a single invocation covering
several slides would file every result under one of them.

The exit code is not the gate; the recorded result is. `assert_slide_passable`
refuses a slide with no lint evidence, with evidence older than the current SVG
or token file, or with outstanding hard errors — so re-running the linter after
every edit is not diligence, it is the only way the slide ever passes. It also
hashes the published SVG on disk and re-reads the recorded token file, so
overwriting either after the run refuses the slide rather than inheriting the
old result; a token file that has been moved or deleted is refused too, because
a check that cannot run is not a check that passed. Both are cleared by running
the linter again. Exit
code 1 also blocks the slide immediately: the module returns to
`revision_required` with the findings attached, and Stages 11–12 are not
entered.

This gate is deterministic and measures only what a ruler can settle — safe
area, overlap, spacing, type floors, contrast, palette conformance, connector
attachment and routing, component consistency, and slide load. It replaces no
human judgement; it removes from human judgement the defects that never needed
it.

Warnings do not block. They are handed to the art-direction reviewer, who must
answer each one by rule id in `linter_warnings_answered`; an `art_direction`
review that passes with a warning unanswered is refused.

### 11. Scientific review

Dispatch `scientific_visual_reviewer_agent` per slide (simple or integrated)
with the rendered visual and its manifest. Record the result:
`--record-review --subject-type slide --subject-id "$SLIDE_ID"
--reviewer-role scientific --status <passed|failed> ...`. `failed` → every
module still `producing`/`review_required` for that slide (or the simple
slide itself) moves to `revision_required`, a new Revision Request is created
(`--requested-by reviewer`), and only the affected module(s) re-enter
`producing` (Stage 9) — siblings stay `passed`, satisfying the
partial-regeneration requirement.

### 12. Visual review (two independent gates)

Dispatch `render_integrity_reviewer_agent` with `--reviewer-role
render_integrity`, same mechanics as Stage 11. It judges the rendered pixels
against the source and nothing else; the deterministic gate at the end of Stage
10 has already settled every measurable property.

Dispatch `art_direction_reviewer_agent` with `--reviewer-role art_direction`.
It judges composition, hierarchy, imagery, and whether the slide states its
claim, and it receives the linter's warnings as context.

All three reviews — scientific, render integrity, art direction — are
independent. A slide reaches `passed` only when all three pass; any one failing
triggers the `revision_required` path scoped to that reviewer's findings.

### 13. Draft review gate

Orchestrator, interactive. Once every slide/module for the deck is `passed`,
`deck.status: producing -> draft_review`. Present the draft to the user (list
every slide, its route tag, and its review outcomes). The user may approve
(`deck.status: draft_review -> validating`, continue to Stage 14) or request
targeted regeneration of specific slides (`deck.status: draft_review ->
producing`, only the named slides'/modules' status is reset to `producing`,
re-entering Stage 9-12 — everything else keeps its `passed` status and its
existing artifacts untouched, satisfying the partial-slide-regeneration
acceptance criterion).

### 14. Export and production

Orchestrator, deterministic — this is the existing "4. Generate slides" and
"PPTX export" sections of the pre-redesign `SKILL.md`, unchanged in mechanics
but now preceded by the gate:

```bash
python3 "$PSTATE" --check-production-allowed --deck-id "$DECK_ID" --json
```

which fails closed (nonzero exit, no file written) if `deck.status` is
somehow earlier than `approved`. The generation mechanics that follow are
unchanged from before this redesign:

#### 14.1 Resolve style

Before generating, determine which style file to use and export `STYLE_FILE`:

```bash
STYLE_FILE=""
[ -f "$SLIDES_DIR/_style.md" ] && STYLE_FILE="$SLIDES_DIR/_style.md"
```

If the user named a style in Stage 2's Q6, search in order:
1. `$SLIDES_DIR/styles/<name>.md` (project-local)
2. Skill bundle `styles/<name>.md` (built-in)

Set `STYLE_FILE` to whichever path exists. If the user chose `custom`, read `references/styles/STYLES.md`
and ask for the required frontmatter values, then write `$SLIDES_DIR/styles/<name>.md`.

#### 14.2 Generate slides

Output directory: `$SLIDES_DIR/reports/YYYY-MM-DD_<name>/`

##### [A] Python renderer — usually [V:DATA]

**Supported types:** `title` `bullet_list` `bar_chart` `line_chart` `pie_chart` `table` `metric_cards` `two_column` `timeline` `conclusion` `score_trajectory` `pipeline_status`

`bar_chart`, `line_chart`, `pie_chart`, `table`, and `timeline` are exported as
real native PPTX chart/table/group objects — the renderer emits the
`data-pptx-role` markers automatically (see §9.1). Prefer one of these types
over hand-authored SVG whenever the content is tabular or chart data.

Write `slide_data.json` then run:
```bash
python3 scripts/generate_slides.py --data <dir>/slide_data.json --out <dir>/ \
    ${STYLE_FILE:+--style "$STYLE_FILE"}
# Re-render one slide:
python3 scripts/generate_slides.py --data <dir>/slide_data.json --out <dir>/ --slide N \
    ${STYLE_FILE:+--style "$STYLE_FILE"}
```

**JSON format:**
```json
{
  "meta": {
    "experiment": "<deck-name>",
    "date": "YYYY-MM-DD",
    "footer": "<name> · YYYY-MM-DD"
  },
  "slides": [
    { "index": 1, "type": "title",
      "title": "...", "subtitle": "...", "author": "...", "date": "YYYY-MM-DD" },

    { "index": 2, "type": "bar_chart",
      "title": "...", "categories": ["A", "B"],
      "series": [
        { "label": "baseline", "color": "#d97706", "values": [72.1, 81.6] },
        { "label": "this run", "color": "#059669", "values": [98.4, 100.0] }
      ],
      "y_max": 100, "unit": "%", "note": "n=..." },

    { "index": 3, "type": "line_chart",
      "title": "...", "categories": ["E1", "E2", "E3"],
      "series": [
        { "label": "train loss", "color": "#3b82f6", "values": [80, 60, 45] }
      ],
      "y_max": 100, "unit": "%", "note": "n=..." },

    { "index": 4, "type": "pie_chart",
      "title": "...", "categories": ["Train", "Dev", "Test"],
      "values": [70, 15, 15],
      "colors": ["#3b82f6", "#059669", "#d97706"], "note": "n=..." },

    { "index": 5, "type": "table",
      "title": "...", "columns": ["Metric", "Before", "After", "Delta"],
      "rows": [["Accuracy", "81.6%", "100%", "+18.4%"]],
      "highlight_col": 3 },

    { "index": 6, "type": "metric_cards",
      "title": "...", "metrics": [
        { "label": "Overall", "value": "99.8%", "color": "#059669", "change": "+27%" }
      ]},

    { "index": 7, "type": "timeline",
      "title": "...", "events": [
        { "label": "v1 baseline", "date": "2024-10-01", "color": "#d97706", "detail": "72%" },
        { "label": "v2 final",    "date": "2024-11-02", "color": "#059669", "detail": "100%" }
      ]},

    { "index": 8, "type": "two_column",
      "title": "...",
      "left":  { "title": "Problem",      "content": ["point 1", "point 2"] },
      "right": { "title": "This Run",     "content": ["point 1", "point 2"] } },

    { "index": 9, "type": "bullet_list",
      "title": "...", "bullets": ["item 1", "item 2"], "numbered": true },

    { "index": 10, "type": "conclusion",
      "title": "...",
      "conclusions": ["finding 1", "finding 2"],
      "next_steps":  ["step 1", "step 2"] },

    { "index": 11, "type": "score_trajectory",
      "title": "Review Score Progression",
      "dimensions": ["Originality", "Methodology", "Clarity", "Citations", "Contribution"],
      "rounds": [
        { "label": "Round 1", "scores": [3, 4, 3, 2, 3] },
        { "label": "Round 2", "scores": [4, 4, 4, 4, 4] }
      ],
      "note": "D1-D5 rubric, scale 1-5" },

    { "index": 12, "type": "pipeline_status",
      "title": "Pipeline Progress",
      "stages": [
        { "number": 1, "name": "RESEARCH", "status": "PASS", "date": "2026-06-08" },
        { "number": 2, "name": "WRITE",    "status": "PASS", "date": "2026-06-10" },
        { "number": 2.5, "name": "INTEGRITY", "status": "PENDING", "date": null }
      ]}
  ]
}
```

`unit` (`bar_chart`, `line_chart`) is appended to every axis tick and value
label, and defaults to empty. Declare it whenever the numbers have one --
`"%"`, `" req/s"`, `" ms"` -- and leave it out otherwise: the renderer used to
append `%` unconditionally, which labelled a throughput of 340 requests per
second as `340.0%`. The y-axis gutter is measured from the widest tick the
unit produces, so a long unit does not run into the left margin.

Only include [A] slides in `slide_data.json`.

##### [B] Mermaid (optional source for [V:NATIVE])

Write a `.mmd` file then convert:
```bash
cat > <dir>/slideNN.mmd << 'EOF'
flowchart LR
  A["Input"] --> B["Model"] --> C["Output"]
EOF
mmdc -i <dir>/slideNN.mmd -o <dir>/slideNN_diagram.svg \
     --theme neutral --width 1200 --height 675
```

Use Mermaid only when its output converts correctly to the selected editable
route. If `mmdc` is unavailable, fall back to [C] for that slide and note the
route and editability in the summary. If the conversion yields only an
embedded or raster result, disclose the editability loss instead of calling it
`[V:NATIVE]`.

Prefer `flowchart LR` for pipelines, `flowchart TD` for training stages, `stateDiagram-v2` for state machines.

##### [C] Claude SVG — [V:NATIVE], [V:AI], or [V:HYBRID] source

Write SVG directly. If `STYLE_FILE` is set, read it and load `references/styles/STYLES.md` for the full
role descriptions; otherwise use the defaults in the table below.

| Style key | SVG usage | Default |
|-----------|-----------|---------|
| — | Canvas: `viewBox="0 0 1200 675"` | fixed |
| `bg` | Slide background `<rect fill="..."/>` | `#ffffff` |
| `primary` | Title text, bullet markers, accents | `#1e3a5f` |
| `border` | Divider line, card borders | `#e2e8f0` |
| `body` | Main paragraph text | `#374151` |
| `muted` | Footer, axis labels, captions | `#64748b` |
| `font` | `font-family` attribute | `'Helvetica Neue', Arial, sans-serif` |
| `positive` | Success / improvement values | `#059669` |
| `warn` | Caution values | `#d97706` |
| `danger` | Error / regression values | `#dc2626` |

Rules for `[V:NATIVE]`: no `<image>` tags; escape `&` `<` `>` in text; split long text with `<tspan dy="...">`. `[V:AI]` keeps the generated PNG/JPG as a separate raster base. `[V:HYBRID]` composes that raster base with an editable SVG overlay in the same `1200x675` coordinate system. For `[V:AI]` and `[V:HYBRID]`, do not put factual labels, legends, or values in generated pixels. Native PPTX exports overlay elements as separate shapes when supported, while embed/fallback output must disclose remaining raster layers and editability loss.

##### Charts

**list:** Collect chart paths from `## Charts` sections in the selected log files. Write `chart_list.md` grouped by slide.

**embed:** Base64-encode each PNG and insert as `<image>` in the relevant SVG.

### 15. PPTX structural validation and completion

Orchestrator. Extends the existing visual-review gate (kept verbatim above in
§9.1, and in `references/visual-review.md` — this is what
`test_visual_review_docs.py` checks) with the new structural validator as an
additional, real check before `statuses.pptx_structure` is recorded:

```bash
VPS="$(find ~/.claude -path "*/report-slides/scripts/validate_pptx_structure.py" | head -1)"
python3 "$VPS" --pptx "$SLIDES_DIR/reports/.../deck.pptx" --expected-slides <N> \
    --declared-editability declared_editability.json --json
```

Map its `{status, relationship_violations, editability_mismatches}` output
into the review record's `statuses.pptx_structure` object (this mapping —
supplying `round`/`reviewed_by`/`inspected_paths`/`revision_required`/
`started_at`/`completed_at`/`findings` around the validator's raw facts — is
exactly the "Phase B entry criterion" the design spec §5b flags; implement it
here as a small deterministic mapping, not a new script). `deck.status:
validating -> completed` only when `validate_visual_review.py --record` (the
full completion gate, unchanged from before this redesign) passes; a failure
moves `deck.status: validating -> revising` and creates a Revision Request
against the failing slide(s).

Once the deck reaches `completed`, close out the bookkeeping from the
pre-redesign workflow: add the deck path to `slide_decks:` in each included
log file's frontmatter and rebuild `INDEX.md`.

---

## PPTX export (optional)

After slides are generated:

**Native shapes (recommended) — fully editable in PowerPoint:**
```bash
# macOS / Linux / Git Bash:
cd "$(find ~/.claude -path "*/report-slides/scripts" -type d | head -1)"
python3 -m svg_to_pptx \
    --slides "$SLIDES_DIR/reports/YYYY-MM-DD_<name>/" \
    --out    "$SLIDES_DIR/reports/YYYY-MM-DD_<name>/deck.pptx"
```

Native mode converts every SVG element to editable shapes: rectangles, ovals, text boxes, connectors, and paths (including Bézier curves). Text labels inside shapes are embedded directly — double-click a shape in PowerPoint to edit its text. Connectors re-route when shapes are moved. Content wrapped in a `data-pptx-role="table"`/`"chart"` marker becomes a real PPTX table or chart object (double-click to edit cell text or the chart's underlying data series, exactly like a manually-inserted PowerPoint table/chart); content wrapped in `data-pptx-role="group"` becomes one native Group shape.

**SVG embed (backward-compatible, viewable but shapes are not individually editable):**
```bash
python3 -m svg_to_pptx --slides output/ --out deck.pptx --mode embed
# or equivalently:
python3 to_pptx.py \
    --slides "$SLIDES_DIR/reports/YYYY-MM-DD_<name>/" \
    --out    "$SLIDES_DIR/reports/YYYY-MM-DD_<name>/deck.pptx"
```

Only `python-pptx` and `lxml` required — no cairosvg, Pillow, or image converter needed.

**A PPTX export is not the final visual check.** Exporting `deck.pptx` only
produces the artifact `statuses.pptx_render` will judge — it is not itself
evidence that the deck looks correct, and neither is inspecting the SVG
source or the PPTX's internal object tree. Immediately after export:

1. Validate the produced package's structure (relationships, editable
   objects, image references) into `statuses.pptx_structure`. This never
   inspects visual placement.
2. Convert the actual `deck.pptx` — never the source SVG — with LibreOffice
   or an equivalent available office renderer, producing exactly one PNG per
   expected slide (see `references/visual-review.md` for the concrete
   `libreoffice`/`pdftoppm` commands).
3. Send every converted PNG path directly to model vision as
   `model_vision.inspected_paths` and record the outcome as
   `statuses.pptx_render` — the authoritative final visual gate.
4. Validate the resulting review record with
   `python3 skills/report-slides/scripts/validate_visual_review.py --record <path> --root <path>`
   (see `references/diagram-workflow.md`).

If LibreOffice or an equivalent renderer is unavailable, or the direct
final-PNG inspection cannot be completed, record `statuses.pptx_render` as
`blocked` with the exact missing capability and set
`overall.completion_allowed` to `false` — do not report the deck complete
from the SVG preview, the review sheet, or the PPTX structure result alone.

---

## Summary output

After all slides are generated, print:
- Output directory and slide list with rendering path tags ([A] / [B] / [C])
- One completion record per non-trivial visual with its route tag, `diagram_id`,
  type, slide, action, reused source, changed regions and reasons, editability,
  `statuses.svg_preview`, `statuses.pptx_structure`, and `statuses.pptx_render`
  (each with `reviewed_by`, `inspected_paths`, `findings`, `revision_required`,
  and round count — for PPTX, also `renderer.name`/`version`/
  `conversion_format`, `conversion_artifacts`, `rendered_png_paths`, and
  `model_vision.inspected_paths`), `overall.authority` and
  `overall.completion_allowed`, and remaining raster layers with their
  rationale
- `slide_data.json` re-render tip for [A] slides
- `chart_list.md` note if applicable
- Updated log files
- PPTX path if exported
- Import tips: drag SVG into Keynote (macOS); LibreOffice Impress opens SVG natively

---

## Edge cases

| Situation | Handling |
|-----------|---------|
| No log files exist | Stop; instruct user to run `/research-log add` |
| No numeric data in logs | Use `bullet_list` or `two_column` instead of charts |
| No `follows:` chain | Skip timeline slide |
| `mmdc` not found | Fall back to [C]; note in summary |
| Only 1 log entry | Limit to 4–5 slides |
| Chart file paths missing | Mark with ⚠ in `chart_list.md` |
| No baseline data | Skip comparison table |
