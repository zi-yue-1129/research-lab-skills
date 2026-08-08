# report-slides Enforcement Remediation and Phase C Design

## 1. Status and purpose

This specification is an approved design delta to
`2026-08-06-report-slides-multiagent-design.md`. It keeps the existing
multi-agent role split, resource resolver, rendering stack, visual-authoring
routes, style system, SVG-to-PPTX converter, pixel-review workflow, PPTX
structural validation, and editability disclosure. It corrects the places
where the Phase A and Phase B implementation currently describes a gate but
does not enforce it.

Delivery remains sequential:

1. Complete the enforcement-remediation plan and pass its acceptance suite.
2. Freeze the corrected contracts and workflow interfaces.
3. Execute Phase C against those frozen interfaces.

Phase C must not begin while a remediation acceptance test is failing.

## 2. Remediation goals

The remediation must make these properties deterministic rather than
instruction-only:

- No supported artifact-producing command can write an SVG, PNG, PPTX,
  diagram manifest, module manifest, integration manifest, or slide output
  directory before plan approval.
- Approval is bound to one validated plan version and SHA-256 digest.
- Planner and content reviewer identities are different.
- An unsupported-claim finding blocks plan approval.
- A complex slide cannot start module production without a validated Complex
  Visual Specification.
- A worker cannot publish a manifest whose protected takeaway/evidence digest,
  module anchors, dimensions, or style contract differs from its assignment;
  independent scientific review checks the rendered meaning itself.
- Scientific and visual-quality reviews are separate persisted gates.
- Only the failed or explicitly revised slide/module can re-enter production.
- A first complete-deck contact sheet is reviewed before final validation.
- Resume returns enough persisted information to continue without repeating
  passed work or losing review history.
- Completion is impossible while any required contract, artifact, review, or
  validation gate is absent or failing.

Arbitrary filesystem writes by a user with shell access are outside the threat
model. Enforcement applies to every supported report-slides CLI, orchestrator
action, and agent publication path.

## 3. Architecture

### 3.1 State storage and workflow actions

`presentation_state.py` remains the public state CLI and durable record store.
Critical transitions gain predicate checks; their current source status alone
is no longer sufficient.

New module `presentation_workflow.py` owns high-level atomic actions:

- `register_plan(project_root: Path, deck_id: str, plan_path: Path,
  authored_by: str) -> dict`
- `record_content_review(project_root: Path, deck_id: str,
  review_path: Path) -> dict`
- `approve_deck(project_root: Path, approval_path: Path) -> dict`
- `record_production_review(project_root: Path, review_path: Path) -> dict`
- `request_targeted_revision(project_root: Path,
  revision_path: Path) -> dict`
- `register_draft_preview(project_root: Path, preview_path: Path) -> dict`
- `approve_draft(project_root: Path, decision_path: Path) -> dict`
- `complete_deck(project_root: Path, deck_id: str,
  completion_record_path: Path) -> dict`

Each action holds a workflow-level sidecar lock while it validates inputs,
appends immutable events, and updates mutable state. Existing per-file locks
remain for safe storage writes. Public CLI paths must use the workflow actions;
low-level mutation helpers are not exposed as bypasses for gated transitions.

The state model adds:

- Deck: `plan_version`, `approved_plan_version`, `approved_plan_sha256`,
  `approval_id`, `draft_preview_id`, and `draft_approval_id`.
- Slide: `approved_takeaway_sha256`, `approved_evidence_sha256`,
  `slide_spec_path`, and `slide_spec_sha256`.
- Visual Module: `visual_spec_path`, `assignment_path`, `artifact_manifest_path`,
  `attempt`, and `supersedes_module_id`.
- Review Result: persisted and queryable `reviewer_id`, `reviewer_role`,
  `subject_type`, `subject_id`, `status`, `findings`, `round`, and timestamps.
- Artifact record: `deck_id`, optional `slide_id` and `module_id`, artifact kind,
  relative path, SHA-256 digest, producer identity, and creation time.

The initial registered plan is version 1. Every accepted plan revision creates
the next version and supersedes the prior version. A plan file is never edited
in place after registration; approval references its immutable versioned copy.

### 3.2 Gate predicates

New `presentation_gates.py` contains pure, deterministic predicate functions
used by the state CLI and artifact publishers:

- `assert_plan_reviewable(...)`
- `assert_plan_approvable(...)`
- `assert_production_allowed(...)`
- `assert_module_assignable(...)`
- `assert_module_publishable(...)`
- `assert_slide_passable(...)`
- `assert_draft_reviewable(...)`
- `assert_deck_completable(...)`

Every failure returns a named exception and structured JSON containing the
failed predicate and blocker. A gate never substitutes a default, silently
drops a finding, or advances state after a partial write.

Approval requires a valid plan, a passing content review by an identity other
than the plan author, no blocking findings, and matching plan version/digest.
`--approved-plan-file` uses the same atomic approval action with
`approval_mode: preapproved`; it does not attempt the currently illegal generic
`planning -> approved` transition. `--yes` uses
`approval_mode: explicit_noninteractive` and still requires planning and
content review.

A slide becomes `passed` only after separate passing review events from
`scientific` and `visual_quality`. A deck becomes `completed` only when every
current slide/module is passed, the approved draft preview exists, the final
PPTX structure result passes, the final PPTX-render review passes, and the
completion record validates.

### 3.3 Artifact publication

All supported artifact-producing entry points add required `--deck-id` and
optional `--project-root` arguments. They call the shared production gate
before creating their output directory or opening an output file:

- `generate_slides.py`
- `to_pptx.py`
- `python3 -m svg_to_pptx`
- `render_review_sheet.py`
- any setup/helper mode that creates presentation output

Agent-authored SVGs and manifests are first written to an orchestrator-provided
temporary staging directory after approval. New
`publish_presentation_artifact.py` validates the relevant approved plan, slide
specification, visual/module specification, worker assignment, declared
anchors, style reference, dimensions, and content digests before atomically
moving the staged artifact into its resolved presentation destination and
recording its digest. Agents must not publish directly to the final destination.

Existing rendering functions remain reusable internally. The supported CLI
behavior changes intentionally: a raw artifact-generation invocation without
`--deck-id` exits without writing and directs the caller to invoke the
report-slides workflow. A legacy report-slides skill invocation enters planning
and approval. Explicit `--yes` or a valid preapproved-plan document supplies
the workflow's required non-interactive authorization; neither bypasses
production review or final validation.

### 3.4 Contract validation

The existing small Python validators remain the machine-readable enforcement
mechanism. Remediation adds `validate_slide_spec.py` and tightens the current
validators without replacing the visual-authoring manifest or visual-review
schemas.

All newly introduced workflow contract documents use `schema_version: 1`.
Digests are SHA-256 over canonical UTF-8 JSON with sorted keys and compact
separators, independent of whether the source document was YAML or JSON.

Deck Plan requires:

- `deck_id`, positive integer `plan_version`, `purpose`, `audience`, positive
  `estimated_duration_minutes`, `core_narrative`, `status`, `slides`,
  `excluded_content`, `known_gaps`, and `authored_by`.
- Every slide requires non-empty `slide_id`, `title`, `purpose`,
  `key_takeaway`, non-empty `evidence_refs`,
  `intended_visual_type`, `visual_rationale`, `speaker_message`, plus explicit
  lists for `dependencies` and `open_questions`.
- Slide dependencies reference declared slide IDs and contain no cycles.

Whether a title expresses a conclusion is a Content Reviewer check rather than
a string-schema heuristic. A generic topic title can be structurally valid but
cannot receive a passing content review without an explicit reviewer finding
and revision.

Deck Approval requires `deck_id`, positive `plan_version`, `plan_sha256`,
`decision`, `approved_by`, `approved_at`, and `approval_mode`. A revise decision
requires non-empty revision requests; an approve decision must not carry
unresolved revision requests.

Slide Specification requires all fields defined by the architecture contract,
valid region IDs and bounding boxes, complete reading-order references, a
numeric text-to-visual ratio, explicit complexity signals, and copies/digests
of the approved takeaway and evidence references. The deterministic complexity
detector, not the architect, supplies `requires_complex_workflow`.

Complex Visual Specification and ModuleSpec require the complete module model:
semantic responsibility, route, module type, input/output anchors,
dependencies, dimensions, style token reference, editability, annotations,
and reuse relationship. Dependencies must reference declared modules and be
acyclic. Every connection endpoint must reference an exact declared anchor,
not merely a declared module.

Worker Assignment requires a real state-store module ID, matching worker type,
resolved dependency IDs, approved specification digest, inputs-resolved flag,
assignment timestamp, and an explicit blocker value. An assignment with
unresolved inputs cannot enter `assigned` or `producing`.

Review Result validates reviewer role, reviewer identity, subject, round,
status, and role-appropriate findings. Revision Request validates an exact
target set, requested-by identity, instructions, and the artifacts/specifications
it supersedes. Workflow-state validation cross-checks every stored path and
foreign key.

### 3.5 Review, retry, and resume

Recording a failed scientific or visual-quality review atomically moves only
the named current subjects to `revision_required` and creates a linked Revision
Request. Retrying increments `attempt`; passed siblings remain passed and their
artifact digests and modification times remain unchanged.

The legal targeted-revision path is not `passed -> producing`. The current
passed record becomes `superseded`, a replacement record is created in
`planned`, and that replacement proceeds through the normal production states.
The revision relationship preserves history and makes partial regeneration
auditable.

`--query --deck-id` returns deck, plan versions, approval, slides, modules,
assignments, artifact records, review results, revision requests, draft preview,
draft decision, blockers, and the next legal actions. Repeating the query or
resuming in a new process creates no duplicate record.

### 3.6 Complete plan and draft previews

Before initial approval, a deterministic plan-preview formatter prints:

- purpose, audience, duration, slide count, and core narrative;
- every slide title, takeaway, evidence reference, and planned visual;
- known missing information and excluded content.

After slide reviews pass, `render_review_sheet.py` produces a full-deck contact
sheet and a draft-preview record containing every slide title and approved
takeaway. The user may approve it, request a targeted revision, or use a
separate explicit `--yes-draft` option. Initial `--yes` approval does not imply
draft approval.

## 4. Deterministic acceptance testing

Tests use fixture contracts and local renderers only. They make no model,
network, cloud, or GPU calls. The remediation acceptance suite covers all
original scenarios:

1. An actual SVG/PPTX producer refuses skipped approval and writes nothing.
2. A rejected plan remains in content review.
3. A plan revision increments version and supersedes the old version.
4. An unsupported claim blocks approval.
5. A complex slide requires a validated decomposition before production.
6. Independent modules may produce concurrently; dependent ones wait.
7. A failed module retry leaves passed siblings and their files unchanged.
8. Scientific review failure and visual-quality review failure are independent.
9. Partial slide regeneration creates only replacement records for targets.
10. Resume returns exact state and review history without duplication.
11. Draft completion requires a contact sheet and user/non-interactive draft
    decision.
12. Completion requires passing structure and rendered-PPTX visual review.

Focused report-slides tests run first. The repository `scripts/` and `tests/`
suites run under the Python version configured by CI. Environment failures are
reported separately from product failures and do not get converted into passes.

## 5. Phase C deliverables

Phase C begins only after the remediation suite passes and the corrected
contracts are frozen.

### 5.1 Contract and role references

Create:

- `skills/report-slides/references/contracts.md`: field-level reference,
  invariants, enums, versioning rules, examples, and validator commands for all
  contracts.
- `skills/report-slides/references/agent-roles.md`: orchestrator and eleven agent
  roles, stage ownership, allowed inputs/outputs, prohibitions, retry ownership,
  and dispatch dependency rules.

Both documents link to the canonical validators and persona files rather than
duplicating executable logic.

### 5.2 Complete modular architecture example

Create `examples/report-slides/modular-architecture-workflow/` as a committed,
offline-reproducible example. Its central visual communicates how observation
and command inputs influence latent-state prediction and decoding. It contains
at least these four architecture modules:

1. `observation-input`, with no dependencies.
2. `command-input`, with no dependencies.
3. `latent-dynamics`, depending on both input modules.
4. `decoder-output`, depending on `latent-dynamics`.

An annotation module supplies callouts and terminology without changing the
scientific message. The two input modules demonstrate parallel production; a
committed failed-review/retry record for one target demonstrates selective
regeneration without modifying its siblings.

The example includes:

- source research excerpt and evidence map;
- versioned Deck Plan and Content Review Result;
- Deck Approval bound to plan version/digest;
- Slide Specifications and complexity-detector result;
- Complex Visual Specification;
- Worker Assignments and versioned module manifests/sources;
- integration manifest and integrated SVG;
- separate scientific and visual-quality Review Results;
- full-deck rendered slides and contact sheet;
- draft approval decision;
- editable PPTX, structural validation result, rendered-PPTX review record,
  and editability disclosure;
- targeted revision and interrupted-resume snapshots;
- a README with deterministic regeneration and validation commands.

Generated PPTX files remain under `examples/**`, consistent with repository
tracking rules.

### 5.3 Example validation

Add an offline example-consistency checker and tests that verify:

- all documented paths exist;
- every contract passes its canonical validator;
- stored digests match files;
- module dependencies and anchors resolve;
- there are at least four architecture components;
- independent/dependent execution order is demonstrated;
- retry changes only its target;
- SVG, contact sheet, PPTX, and final review records are present;
- the final state is completed and resume output is self-consistent.

Phase C is complete only when the focused suite, complete report-slides suite,
example regeneration check, and supported-version repository suite have been
run and their results recorded.

## 6. Compatibility and migration

- Existing resource-resolver roles and output locations remain authoritative.
- Simple slides continue through the efficient non-decomposed path.
- Existing route and editability enums remain unchanged.
- Existing diagram manifests remain valid because new linkage fields are
  additive for legacy assets; newly produced modular assets use the stricter
  current contract version.
- Existing SVG/PPTX conversion behavior remains unchanged after authorization.
- Legacy invocations enter planning and approval instead of producing
  immediately. This intentional behavior change satisfies the original safety
  requirement.
- Existing workflow state is migrated by an explicit deterministic command.
  A state record that cannot be mapped without inventing approval or review
  evidence becomes `blocked` with a migration report.

## 7. Non-goals

- Replacing the resource resolver, style system, SVG renderer, PPTX converter,
  visual-review stack, or diagram-manifest system.
- Cloud scheduling or distributed job execution.
- Persisting agent chain-of-thought or scratch reasoning.
- Allowing multiple agents to generate competing complete decks.
- Modifying approved research conclusions automatically.
- Expanding into manuscript, experiment, or full research-lifecycle
  orchestration.

## 8. Completion criteria

Remediation is complete when every gate described above is enforced by the
supported runtime paths and every deterministic acceptance test passes.

Phase C is complete when both reference documents and the complete modular
example are committed, reproducible offline, validated against the frozen
contracts, and demonstrated through final PPTX completion and resume.
