# report-slides Multi-Agent Redesign — Architecture Specification

## 0. Audit Summary (what exists today)

Full audit detail is in the accompanying research trace; the load-bearing facts:

- **No enforced approval gate exists.** `SKILL.md` Step 3 asks the agent to print an outline and wait for a literal `"ok"` reply, but nothing in code stops slide/SVG/PPTX generation from starting anyway. This is the root of Problem 1.
- **One agent does everything.** `generate_slides.py`/`to_pptx.py` are pure deterministic renderers (no LLM calls); all planning, authoring, and review judgment happens inline in a single Claude session following `SKILL.md` prose. This is Problem 2.
- **A "diagram" is one atomic unit.** `validate_diagram_manifest.py`'s manifest schema has one `source_files` set per `diagram_id`, `regions` are just string labels for change-tracking, and there is no schema concept of a module, an anchor, or a typed connection between visual pieces. This is Problem 3.
- **Existing contracts to extend, not replace:** the diagram-manifest schema, the diagram-plan schema, and the visual-review-record schema (all in `validate_diagram_manifest.py` / `validate_visual_review.py`), plus the four-route enum (`native | data | generative | hybrid`) and the `editability` enum (`native | hybrid | raster`).
- **Style system** is a small token schema (10 optional keys) resolved by project-relative filename, not a closed enum — new agents can reference it unchanged.
- **`svg_to_pptx/`** is a self-contained, untouched-by-this-redesign rendering/conversion library; out of scope per the task.
- **Resource resolver**: report-slides uses only the shared `slides` and `research_log` roles; it defines no roles of its own today.
- **Regression surface:** `test_visual_review_docs.py` asserts literal substrings exist in `SKILL.md`/reference docs — any prose rewrite must keep those strings or update the test in lockstep. `test_validate_diagram_manifest.py` (44 cases) and `test_validate_visual_review.py` (13 cases) pin the existing schemas exactly.
- **Notable discrepancy, now resolved:** the task says to preserve "PPTX structure validation" as an existing capability. It does not exist as real code — `validate_visual_review.py` only checks that a review-record JSON *claims* a `pptx_structure` status in the right shape; no script anywhere parses an actual `.pptx` file's internal structure. Decision: this redesign adds a real structural validator (§5b) rather than continuing to preserve only the schema-only illusion of one.

## Decisions confirmed before implementation

Four architectural forks were presented for confirmation; all four are reflected in this document as written:

1. **State/contract storage** — a new, independent `presentation_state.py` module (not an extension of `agent-state`), under `.research/presentations/`, sharing `agent-state`'s proven pattern (locking, atomic YAML writes, id-keyed maps, `--validate`) without importing its code or creating a cross-skill dependency.
2. **PPTX structure validation** — build a real structural validator (new scope, §5b), not just preserve the existing schema-only gate.
3. **Orchestrator execution model** — `SKILL.md` itself is the orchestrator (matching the existing `deep-research`/`academic-pipeline` precedent in this repo); no separate `presentation_orchestrator_agent.md` persona file.
4. **Delivery** — phased: **Phase A** (state store + all contract validators + the deterministic approval/production gate + their tests) → **Phase B** (`SKILL.md` rewrite + all 11 agent persona files) → **Phase C** (worked example + reference docs). Each phase gets its own plan and full subagent-driven-development review cycle before the next begins.

## 1. Agent Roster

One orchestrator + ten specialized agents, following this repo's existing `deep-research`/`academic-pipeline` convention exactly: each agent is a Markdown persona file under `skills/report-slides/agents/*.md` (frontmatter `name`/`description`, a Phase/Stage Boundary block stating what it MUST NOT do, an Output Format section), dispatched via the Task tool by whichever Claude session is running `report-slides`. There is no separate always-running orchestrator *process* — matching how `deep-research`/`academic-pipeline` already work in this repo, the **orchestrator role is `report-slides/SKILL.md` itself**: the calling session reads it, and at each stage either does deterministic work itself (calling the state/validator CLIs below) or dispatches one agent persona via the Task tool. This keeps the design consistent with the only precedent that exists in this codebase, rather than inventing a new "orchestrator" execution model.

| # | Agent | File | Stage(s) | MUST NOT |
|---|---|---|---|---|
| — | *(Orchestrator = SKILL.md-driven session, not a persona file)* | `SKILL.md` | 1, 5, 13(gate), 15 | Author slide content or visuals itself |
| 1 | Research Narrative Planner | `agents/research_narrative_planner_agent.md` | 3 | Author visuals; approve its own plan |
| 2 | Content Reviewer | `agents/content_reviewer_agent.md` | 4 | Approve a plan it authored; author/revise slide content itself (returns findings only) |
| 3 | Slide Architect | `agents/slide_architect_agent.md` | 6, 7 | Change an approved takeaway or evidence reference |
| 4 | Complex Visual Decomposer | `agents/complex_visual_decomposer_agent.md` | 8 | Author any visual asset itself; approve its own decomposition |
| 5 | Data Visualization Worker | `agents/data_visualization_worker_agent.md` | 9 | Modify scientific content; author modules outside its assignment |
| 6 | Architecture Diagram Worker | `agents/architecture_diagram_worker_agent.md` | 9 | (same as above) |
| 7 | Conceptual Illustration Worker | `agents/conceptual_illustration_worker_agent.md` | 9 | (same as above) |
| 8 | Annotation Worker | `agents/annotation_worker_agent.md` | 9 | (same as above) |
| 9 | Visual Integration | `agents/visual_integration_agent.md` | 10 | Redraw a validated module without cause; invent new scientific content |
| 10 | Scientific Visual Reviewer | `agents/scientific_visual_reviewer_agent.md` | 11 | Judge rendering/aesthetic quality (that's role 11 below) |
| 11 | Visual Quality Reviewer | `agents/visual_quality_reviewer_agent.md` | 12 | Judge scientific/semantic correctness (that's role 10 above) |

(Numbering above follows the task's own "## 1-11" role list; the table's `#` column is the file roster, 1-11 excluding the orchestrator row.)

## 2. Workflow State Machine

### Deck states (exactly the task's required list)

```
planning -> content_review -> awaiting_approval -> approved -> producing
  -> draft_review -> revising -> validating -> completed
                                      \-> blocked (from any state)
content_review -> planning        (reviewer requests plan revision)
awaiting_approval -> planning     (user requests plan revision)
draft_review -> producing         (user requests targeted regeneration; only affected slides/modules re-enter `producing`)
validating -> revising            (final PPTX validation fails)
```

### Slide / visual-module states (exactly the task's required list)

```
planned -> ready -> assigned -> producing -> review_required -> passed
                                     \-> revision_required -> producing (retry)
any -> blocked            (unresolved dependency, missing input, or capped retries)
passed -> superseded      (a later revision replaces it)
```

A **Slide** aggregates the status of its **visual modules** (a simple slide with no complex visual has zero modules and moves `planned -> ready -> producing -> review_required -> passed` directly against its own single visual). A Deck cannot reach `completed` while any Slide/module is in `blocked`, `revision_required`, or `producing`.

### Enforcement mechanism (this is what makes Acceptance Criterion 1 real, not aspirational)

Every script that writes a presentation artifact (SVG, PNG, PPTX, or a diagram/module manifest) takes a `--deck-id` and, before writing anything, calls the state store to confirm the Deck is at or past `approved`. If not, it exits nonzero with a structured JSON error and writes nothing. This is a deterministic, unit-testable guard — no LLM involved — and is exactly how Acceptance Criterion 13's "skipped approval" test scenario is verified: invoke the production entry point against a Deck still in `awaiting_approval` and assert it refuses.

## 3. State & Contract Store

**New, dedicated module — not an extension of `agent-state`.** See Open Decision D1 for the alternative and why this is the recommendation.

- **Location:** `.research/presentations/` at the project root (same `find .git ancestor` root-finding convention `agent-state` already uses), auto-`.gitignore`d the same way. Reusing the `.research/` top-level name (rather than inventing a new dot-directory) keeps exactly one "internal workflow bookkeeping lives here, never commit it" convention in this repo instead of two. Layout mirrors `agent-state` exactly — one flat, id-keyed YAML map per entity type (not one subdirectory per deck): `.research/presentations/state/decks.yaml`, `state/slides.yaml`, `state/visual_modules.yaml`, `state/revision_requests.yaml`, plus append-only daily-sharded `events/YYYY-MM-DD.jsonl` for immutable Review Result facts.
- **Module:** `skills/report-slides/scripts/presentation_state.py`, implemented with the same primitives `agent-state` proved out this session: sidecar-lock-file writes, atomic YAML replace, id-keyed maps for mutable records, append-only JSONL for immutable events (review results), a `schema_version` field, and a `--validate` referential-integrity pass. It is a **new, independent implementation** (not an import of `agent-state`'s code) so report-slides gains no dependency on a different skill's internals; the two modules simply share a proven pattern.
- **CLI shape** (mirrors `agent-state`'s `state.py` conventions): `--create-deck`, `--set-deck-status`, `--create-slide`, `--set-slide-status`, `--create-visual-module`, `--set-module-status`, `--record-review`, `--query --deck-id ID`, `--validate`, `--json`.

### Contracts (schema field lists; full JSON Schema-equivalent detail goes in `references/contracts.md`, not restated here)

| Contract | Key fields |
|---|---|
| **Deck Plan** | `deck_id`, `purpose`, `audience`, `estimated_duration_minutes`, `slides: [SlidePlanEntry]`, `excluded_content: [str]`, `known_gaps: [str]`, `status` |
| **SlidePlanEntry** (one per planned slide, embedded in Deck Plan) | `slide_id`, `title`, `purpose`, `key_takeaway`, `evidence_refs: [str]`, `intended_visual_type`, `visual_rationale`, `speaker_message`, `dependencies: [slide_id]`, `open_questions: [str]` |
| **Deck Approval** | `deck_id`, `plan_version`, `decision: approve\|revise`, `revisions_requested: [RevisionRequest]`, `approved_by`, `approved_at` |
| **Slide Specification** (Slide Architect's output) | `slide_id`, `information_hierarchy: [str]`, `reading_order: [region_id]`, `layout_regions: [{region_id, bbox}]`, `text_to_visual_ratio`, `visual_emphasis`, `expected_complexity`, `reusable_components: [asset_id]`, `requires_complex_workflow: bool`, `complexity_signals: {region_count, route_count, multi_stage: bool, mixed_technique: bool, heavy_cross_region_connections: bool, expected_reuse: bool, not_atomic: bool}` |
| **Complex Visual Specification** | exactly the task's §7 fields: `visual_id`, `message`, `modules: [ModuleSpec]`, `connections: [{from, to}]`, `layout: {direction, hierarchy}` |
| **ModuleSpec** | `id`, `purpose`, `route` (`native\|data\|generative\|hybrid`), `module_type` (`data_visualization\|architecture\|conceptual\|annotation`), `input_anchors: [str]`, `output_anchors: [str]`, `dependencies: [module_id]`, `style_tokens_ref`, `editability`, `reuse_of: module_id\|null` |
| **Worker Assignment** | `module_id`, `worker_type`, `assigned_at`, `inputs_resolved: bool`, `blocker: str\|null` |
| **Review Result** | `subject_type: plan\|module\|slide\|deck`, `subject_id`, `reviewer_role`, `status: passed\|failed\|blocked`, `findings: [{kind, description, severity}]`, `round` |
| **Revision Request** | `subject_type`, `subject_id`, `requested_by: user\|reviewer`, `instructions`, `superseded_subject_id: str\|null` |
| **Workflow State** | the Deck/Slide/Module status records themselves, as persisted by `presentation_state.py` — not a separate contract, it's what the store *is*. |

`Content Reviewer` findings reuse the same `findings[].kind` shape already established by `validate_visual_review.py` (`kind`, `description`, plus a `severity`/`disposition`-style field) rather than inventing a parallel vocabulary — extended with plan-level kinds: `unsupported-claim`, `duplicated-content`, `missing-limitation`, `excessive-background`, `unnecessary-visual`, `weak-continuity`.

**Phase A status of ModuleSpec enforcement (known gap):** `validate_visual_module.py`'s `validate_module_spec` treats `input_anchors`/`output_anchors`/`dependencies` as *optional-if-present* — they are type-checked only when the key exists, never required — and it does not validate `style_tokens_ref` or `reuse_of` at all. It also does not referentially check `dependencies` entries against the declared module ids, unlike `connections`, which does get that check. So the acceptance criterion "Modules expose stable anchors, dependencies, and style contracts" is stated by the contract table above but is **not yet fully enforced by the schema validator** as shipped in Phase A. Tightening this — requiring anchor and `style_tokens_ref` presence, and adding referential integrity for `dependencies` — is deferred to Phase B or a hardening pass.

**Phase A status of the findings reuse (known gap):** the six plan-level kinds were added to the enum in Phase A, but `validate_visual_review.py`'s `_validate_findings` still requires every finding to carry `scope`/`artifact_path`/`source`/`disposition` — fields that only make sense for the three existing visual-inspection gates (`svg_preview`, `pptx_structure`, `pptx_render`). A plan-level finding has no `artifact_path` and no visual-gate `source`, so **no schema anywhere currently validates a plan-level Review Result's findings**: neither `validate_deck_plan.py` nor `validate_visual_module.py` validates findings at all, despite `presentation_state.py`'s `record_review` docstring implying they do. Phase B must resolve this either by adding a plan-level `source` value and making `artifact_path`/`scope` conditional on the source, or by building a dedicated plan-level findings validator.

## 4. Approval Boundary (Stages 1-5)

Before Deck Approval, the workflow may only write to the **in-memory/temporary** representation the Research Narrative Planner and Content Reviewer pass between themselves and to `presentation_state.py`'s Deck Plan record (plain YAML/JSON bookkeeping — not a presentation artifact). It is a hard rule, enforced by the guard in §2, that no script producing SVG/PNG/PPTX/diagram-manifest output may run while `deck.status < approved`. `presentation_state.py --create-deck`/`--set-deck-status` themselves never touch the resolved `slides` directory from resource-resolver — only Stage 6 onward writes there.

Supported user actions at the approval gate (`approve`, `revise a slide`, `add a slide`, `remove a slide`, `reorder`, `change emphasis`, `change audience`, `change duration`) are all expressed as a `Revision Request` fed back into the Research Narrative Planner, which regenerates the affected part of the Deck Plan and re-enters `content_review`. Non-interactive mode requires an explicit `--yes` CLI flag or `--approved-plan-file PATH` (a plan the user pre-approved out of band); its absence is what makes the "skipped approval" test scenario meaningful to test at all.

## 5. Complex Visual Module Model (extends, does not replace, the diagram manifest)

The existing per-diagram manifest schema (`manifest.yaml`: `schema_version, diagram_id, purpose, diagram_type, authoring_route, editability, source_files, used_in, derived_from, based_on_revision, changes, generation, review`) is **unchanged** for simple (non-decomposed) visuals — this is how Compatibility Criterion 12 and "existing simple slides... must not be forced through complex decomposition" hold.

For a visual that entered the complex-visual workflow, its manifest gains one new optional key, `modules_ref: <path to the Complex Visual Specification YAML>`, and one manifest is written **per module** (each module is its own `diagram_id`-equivalent asset with its own `source_files`, so each module stays independently reusable/versioned exactly like today's atomic diagrams), plus one **integration manifest** for the assembled visual whose `source_files` is the final integrated SVG and whose new `modules_ref` lists the module manifests it composed. `used_in`/`derived_from`/`changes`/`review` all keep their current meaning at both the module and integration level, so partial revision (Acceptance Criterion 10) is just "one module's manifest re-enters `review.status: draft`" without touching its siblings' manifests.

## 5b. PPTX Structural Validation (new capability, Stage 15)

`scripts/validate_pptx_structure.py` — a new, dependency-light validator (stdlib `zipfile`/`xml.etree.ElementTree` plus the `python-pptx` already required by `to_pptx.py`; no new dependencies), fully deterministic and offline, satisfying Acceptance Criterion 15. Given a `.pptx` path and the deck's `expected_slides`/manifest set, it checks:

- **Package integrity:** the file is a valid zip; `[Content_Types].xml` and `ppt/presentation.xml` parse as well-formed XML.
- **Slide count:** the number of `<p:sldId>` entries in `ppt/presentation.xml`'s slide list matches `expected_slides` (reusing the field *name* `validate_visual_review.py` already defines — but not its type: here it is a scalar count, there a list of slide numbers; see the note below).
- **Relationship integrity:** for every slide, every `r:embed`/`r:id`/`r:link` reference inside `ppt/slides/slideN.xml` resolves to an entry in `ppt/slides/_rels/slideN.xml.rels`, and that entry's `Target` exists inside the package (catches broken image/media references — a real defect class `svg_to_pptx`'s post-processing zip surgery could in principle introduce).
- **Editability cross-check:** per slide, classifies shape content into "vector shapes present" (`<p:sp>`/`<p:cxnSp>` with real geometry, not just a full-bleed picture) vs. "raster-only" (a single `<p:pic>` covering the slide bounds), and returns this as a fact (`slide_editability_observed: native|raster|hybrid`) the caller cross-checks against what the manifest/module declared — a mismatch (e.g. manifest claims `native` but the slide is one raster picture) is a **finding**, not a silent pass.

`validate_pptx_structure.py` emits the structural *facts* — slide count, relationship integrity, editability classification — as its own independent output shape: `{status, checked_at, slide_count_expected, slide_count_actual, relationship_violations: [...], editability_mismatches: [...]}`. This is deliberately **not** the review-record's `statuses.pptx_structure` object: the two share only the `status` field, and `--expected-slides` here is a scalar count whereas the review record's `expected_slides` is a list of slide numbers. Mapping these facts into a full `statuses.pptx_structure` object — supplying the fields the validator does not and cannot know (`round`, `reviewed_by`, `inspected_paths`, `revision_required`, `started_at`, `completed_at`, `findings`) — is the job of the **Phase B** consumer that assembles the actual review record, and is an explicit Phase B entry criterion rather than something Phase A implements. What Phase A guarantees is that those structural facts are now derived from the real file instead of asserted by an agent. This closes the gap identified in §0 without touching `svg_to_pptx/`'s generation code — it is a read-only auditor of what that code already produced.

## 6. Complex Visual Detection (Stage 7)

A deterministic function in `presentation_state.py` (or a small sibling module `complex_visual_detector.py`), reading a config file `references/complex_visual_thresholds.yaml` (new, style-file-like: plain key: value, resolved the same project-relative way as `_style.md`):

```yaml
region_count_threshold: 3       # ">more than three semantic regions"
route_count_threshold: 1        # ">uses more than one authoring route"
```

takes the Slide Architect's recorded `complexity_signals` (§3 table) as input and returns `requires_complex_workflow: bool` plus which signal(s) fired. The two count-based criteria are threshold-driven and configurable per this file; the four inherently qualitative criteria (multi-stage/data-flow, mixed-technique, heavy cross-region connections, "not reliably atomic") are recorded as explicit booleans the Slide Architect must answer (not left implicit) and OR'd into the same decision — so the decision function itself is 100% deterministic and testable even though some of its *inputs* are agent-assessed judgment calls recorded as data, not prose.

## 7. Compatibility Plan

- Existing CLI entry points (`generate_slides.py`, `to_pptx.py`, `validate_diagram_manifest.py`, `validate_visual_review.py`, `svg_to_pptx/`) keep their current signatures and behavior for already-authored input — this redesign adds callers/gates around them, not replacements.
- The four-route enum and `editability` enum are reused verbatim by `ModuleSpec.route`/`.editability`.
- Legacy invocation (today's single-message workflow) now always creates a Deck and passes through `content_review -> awaiting_approval` before any artifact is written — per the task's explicit requirement — but for a Deck whose every slide is simple (no `requires_complex_workflow`), Stages 7-10 (detection/decomposition/specialized workers/integration) are a no-op pass-through and slide production uses exactly today's `generate_slides.py`/agent-authored-SVG path. This is what keeps existing efficient simple-slide generation intact per Compatibility Criterion 2.
- `--yes`/`--approved-plan-file` give the non-interactive escape hatch the task requires, satisfying "Legacy invocation should remain supported, but it must now enter the approval workflow unless an explicit non-interactive option is provided."

## 8. File Layout (new/changed)

```
skills/report-slides/
  SKILL.md                                   # rewritten: orchestrator instructions, stage-by-stage dispatch
  agents/                                    # new
    research_narrative_planner_agent.md
    content_reviewer_agent.md
    slide_architect_agent.md
    complex_visual_decomposer_agent.md
    data_visualization_worker_agent.md
    architecture_diagram_worker_agent.md
    conceptual_illustration_worker_agent.md
    annotation_worker_agent.md
    visual_integration_agent.md
    scientific_visual_reviewer_agent.md
    visual_quality_reviewer_agent.md
  scripts/
    presentation_state.py                    # new — state store + CLI
    complex_visual_detector.py                # new — deterministic threshold decision
    validate_deck_plan.py                     # new — Deck Plan / SlidePlanEntry schema
    validate_visual_module.py                 # new — Complex Visual Spec / ModuleSpec schema
    validate_diagram_manifest.py              # extended: optional `modules_ref` key
    validate_visual_review.py                 # extended: plan-level finding kinds
    validate_pptx_structure.py                # new — real PPTX structural validator (§5b)
    generate_slides.py, to_pptx.py, svg_to_pptx/   # unchanged
    tests/                                    # new test files for the above, existing ones untouched
  references/
    contracts.md                              # new — full field-level schema reference for all 9 contracts
    complex_visual_thresholds.yaml            # new — detection config
    agent-roles.md                            # new — short index of the 11 agent files + stage map
    (existing diagram-patterns.md, diagram-workflow.md, generative-visuals.md, visual-review.md, styles/ — unchanged)
  examples/
    modular-architecture-diagram/             # new — required by Acceptance Criterion 14
```

## 9. Testing Strategy

Every item in Acceptance Criterion 13 is a **state-machine or contract-validation** test against `presentation_state.py`/`validate_deck_plan.py`/`validate_visual_module.py`/`complex_visual_detector.py` via subprocess — the same pattern `agent-state`'s `test_state_cli.py` already uses in this repo — never a real LLM call, satisfying Acceptance Criterion 15:

| Scenario | Test shape |
|---|---|
| skipped approval | call a production-guarded script against a Deck in `awaiting_approval`; assert nonzero exit, no file written |
| rejected plan | `--record-review` with `status: failed` on a plan; assert Deck stays in `content_review`, not `awaiting_approval` |
| plan revision | Revision Request round-trips to a new plan version; old version marked superseded |
| unsupported claim | Content Reviewer finding with `kind: unsupported-claim`; assert it blocks `awaiting_approval` |
| complex visual decomposition | Slide Architect signals trip `complex_visual_detector`; assert `requires_complex_workflow: true` and a Complex Visual Spec is required before module production can start |
| parallel independent modules | two modules with no shared dependency both reach `ready` simultaneously; a module with an unresolved dependency stays `blocked` |
| failed module retry | `--set-module-status revision_required`; only that module re-enters `producing`, siblings stay `passed` |
| scientific review failure | `--record-review reviewer_role=scientific status=failed`; module/slide moves to `revision_required` |
| visual-quality review failure | same, `reviewer_role=visual_quality` — asserted as an independent gate from scientific review |
| partial slide regeneration | one slide revised; sibling slides' manifests/state untouched (assert file mtimes / status unchanged) |
| interrupted workflow resume | kill and re-invoke against the same `deck_id`; state store returns the exact prior in-flight status, no duplicate records created |

`validate_pptx_structure.py` (§5b) gets its own deterministic, offline test suite built from small synthetic/fixture `.pptx` files (a minimal valid deck, one with a deliberately broken relationship reference, one with a manifest/rendered-output editability mismatch) — no dependency on the other scenarios above, since it operates purely on a finished `.pptx` file.

Existing `svg_to_pptx/` and `scripts/tests/` suites (item 12) run unmodified and must stay green; `test_visual_review_docs.py`'s literal-string assertions are updated in lockstep with any `SKILL.md`/reference-doc wording this redesign touches, not treated as untouchable.
