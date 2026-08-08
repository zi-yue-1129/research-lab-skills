# report-slides Phase C References and Modular Example Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Document the frozen report-slides contracts and agent boundaries, then ship a complete offline-reproducible modular architecture deck that demonstrates approval, decomposition, parallel modules, selective retry, independent reviews, draft approval, editable PPTX validation, completion, and resume.

**Architecture:** Phase C consumes the green remediation interfaces without changing their semantics. A deterministic builder creates the example from committed source contracts and SVG modules, while a separate checker verifies paths, canonical digests, dependency/anchor integrity, review history, retry isolation, preview artifacts, PPTX structure, completion state, and resume consistency. Human-facing references link to executable validators instead of duplicating business logic.

**Tech Stack:** Python 3.11, PyYAML, Pillow, python-pptx, existing `svg_to_pptx`, existing visual-review/PPTX validators, stdlib hashing/JSON/XML/ZIP support, pytest; no network, model, cloud, or GPU calls.

## Global Constraints

- Start only after Task 11 of `2026-08-08-report-slides-enforcement-remediation.md` is green and its commit hash is recorded.
- Do not change frozen contract fields, gate predicates, state transitions, or artifact CLI authorization semantics in Phase C.
- If the example reveals a contract defect, stop Phase C, fix it through the remediation plan, rerun the remediation entry gate, then resume Phase C.
- Use Google-style docstrings and complete type annotations for all public Python interfaces.
- Keep each Python file below approximately 1000 lines.
- Write all committed prose, code comments, docstrings, logs, and commit subjects in English.
- Keep PPTX files under `examples/**` so repository ignore rules continue to permit tracking.
- Generate all deterministic artifacts without external models, network access, cloud services, or GPU.
- Do not persist agent chain-of-thought or scratch reasoning.

---

### Task 1: Publish the canonical contracts reference

**Files:**
- Create: `skills/report-slides/references/contracts.md`
- Create: `skills/report-slides/scripts/tests/test_contracts_reference.py`
- Modify: `skills/report-slides/SKILL.md`

**Interfaces:**
- Consumes the frozen validators and public workflow CLI from remediation.
- Produces one field-level reference for Deck Plan, Deck Approval, Slide Specification, Complex Visual Specification, ModuleSpec, Worker Assignment, Review Result, Revision Request, Draft Preview/Decision, Artifact Record, and Workflow State.

- [ ] **Step 1: Write failing reference-link and field-coverage tests**

```python
CONTRACT_FIELDS = {
    "Deck Plan": ("schema_version", "plan_version", "core_narrative", "authored_by"),
    "Deck Approval": ("plan_sha256", "approval_mode", "approved_at"),
    "Slide Specification": ("approved_takeaway_sha256", "complexity_signals"),
    "ModuleSpec": ("semantic_responsibility", "input_anchors", "style_tokens_ref"),
    "Worker Assignment": ("spec_sha256", "inputs_resolved", "blocker"),
    "Review Result": ("reviewer_id", "reviewer_role", "round", "findings"),
    "Revision Request": ("target_ids", "revision_kind", "instructions", "supersedes"),
}


def test_contract_reference_names_canonical_fields_and_commands() -> None:
    text = CONTRACTS.read_text(encoding="utf-8")
    for heading, fields in CONTRACT_FIELDS.items():
        assert f"## {heading}" in text
        for field in fields:
            assert f"`{field}`" in text
    for script in ("validate_deck_plan.py", "validate_slide_spec.py",
                   "validate_visual_module.py", "validate_visual_review.py",
                   "presentation_state.py"):
        assert script in text
```

- [ ] **Step 2: Run the reference test and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_contracts_reference.py -v`

Expected: FAIL because `references/contracts.md` does not exist.

- [ ] **Step 3: Write the complete contracts reference**

For every contract include purpose, producer, consumer, schema version, required fields with types, enums, invariants, digest/version rules, state boundary, valid YAML example, invalid example with expected validator message, and exact validation command. Document canonical JSON hashing and exact anchor endpoint rules once, then link to that section from affected contracts.

The Deck Plan example uses two declared evidence references per content slide; the Deck Approval example includes a real 64-character digest string; the ModuleSpec example includes explicit empty lists rather than omitted optional-looking fields.

- [ ] **Step 4: Link the reference from SKILL.md and run docs tests**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_contracts_reference.py tests/test_visual_review_docs.py tests/test_agent_persona_docs.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add skills/report-slides/references/contracts.md \
  skills/report-slides/scripts/tests/test_contracts_reference.py \
  skills/report-slides/SKILL.md
git commit -m "docs(report-slides): document workflow contracts"
```

---

### Task 2: Publish the orchestrator and agent-role reference

**Files:**
- Create: `skills/report-slides/references/agent-roles.md`
- Create: `skills/report-slides/scripts/tests/test_agent_roles_reference.py`
- Modify: `skills/report-slides/SKILL.md`

**Interfaces:**
- Produces a role/stage matrix for the Presentation Orchestrator and all eleven persona files, including dispatch inputs, outputs, prohibited actions, dependencies, review independence, blockers, and retry ownership.

- [ ] **Step 1: Write failing roster synchronization tests**

```python
EXPECTED_ROLES = {
    "research_narrative_planner_agent": "Stage 3",
    "content_reviewer_agent": "Stage 4",
    "slide_architect_agent": "Stages 6-7",
    "complex_visual_decomposer_agent": "Stage 8",
    "data_visualization_worker_agent": "Stage 9",
    "architecture_diagram_worker_agent": "Stage 9",
    "conceptual_illustration_worker_agent": "Stage 9",
    "annotation_worker_agent": "Stage 9",
    "visual_integration_agent": "Stage 10",
    "scientific_visual_reviewer_agent": "Stage 11",
    "visual_quality_reviewer_agent": "Stage 12",
}


def test_agent_roles_reference_matches_persona_roster() -> None:
    text = ROLES.read_text(encoding="utf-8")
    assert "Presentation Orchestrator" in text
    for role, stage in EXPECTED_ROLES.items():
        assert role in text
        assert stage in text
        assert (AGENTS / f"{role}.md").is_file()
```

- [ ] **Step 2: Run the roster test and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_agent_roles_reference.py -v`

Expected: FAIL because `references/agent-roles.md` does not exist.

- [ ] **Step 3: Write the role reference and dependency rules**

Include one table row per role with owned stages, input contracts, output contracts, allowed state actions, MUST-NOT boundary, blocker behavior, and retry scope. Add a dispatch graph in text form: planner → independent reviewer → approval → architect → detector → decomposer → dependency-ready workers → integrator → scientific reviewer → visual-quality reviewer → draft gate → completion gate.

State explicitly that independent workers may run together only when all declared dependencies have passed, and that no author may approve or review its own protected output.

- [ ] **Step 4: Link from SKILL.md and run role tests**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_agent_roles_reference.py tests/test_agent_persona_docs.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add skills/report-slides/references/agent-roles.md \
  skills/report-slides/scripts/tests/test_agent_roles_reference.py \
  skills/report-slides/SKILL.md
git commit -m "docs(report-slides): document agent ownership"
```

---

### Task 3: Create the deterministic modular-example builder and source contracts

**Files:**
- Create: `examples/report-slides/modular-architecture-workflow/README.md`
- Create: `examples/report-slides/modular-architecture-workflow/source/research-excerpt.md`
- Create: `examples/report-slides/modular-architecture-workflow/source/evidence-map.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/contracts/plan-v0001.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/contracts/content-review-round-1.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/contracts/approval.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/contracts/slide-01-spec.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/contracts/slide-02-spec.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/contracts/slide-03-spec.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/contracts/slide-02-visual-spec.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/scripts/build_example.py`
- Create: `skills/report-slides/scripts/tests/test_modular_example_builder.py`

**Interfaces:**
- Produces: `build_example(example_root: Path, check: bool) -> dict[str, Any]` and CLI `--root PATH [--check] --json`.
- Source plan contains three slides: evidence/purpose, modular architecture, and limitations/next steps.
- Complex visual contains modules `observation-input`, `command-input`, `latent-dynamics`, `decoder-output`, and `terminology-annotations`.

- [ ] **Step 1: Write failing source-contract and dependency tests**

```python
def test_example_source_contracts_validate() -> None:
    root = EXAMPLE / "contracts"
    assert validate_deck_plan(load_contract(root / "plan-v0001.yaml")) == []
    for name in ("slide-01-spec.yaml", "slide-02-spec.yaml", "slide-03-spec.yaml"):
        assert validate_slide_spec(load_contract(root / name)) == []
    visual = load_contract(root / "slide-02-visual-spec.yaml")
    assert validate_complex_visual_spec(visual) == []
    architecture = [m for m in visual["modules"] if m["module_type"] == "architecture"]
    assert [m["id"] for m in architecture] == [
        "observation-input", "command-input", "latent-dynamics", "decoder-output"
    ]
    assert visual["modules"][0]["dependencies"] == []
    assert visual["modules"][1]["dependencies"] == []
```

- [ ] **Step 2: Run builder tests and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_modular_example_builder.py -v`

Expected: FAIL because the example tree and builder do not exist.

- [ ] **Step 3: Write evidence-grounded contracts and builder skeleton**

Use this central scientific conclusion consistently: “Action commands join observation features before latent-state prediction; the decoder reconstructs the predicted state but does not establish causal improvement.” Evidence IDs `E-OBS`, `E-CMD`, `E-LATENT`, and `E-LIMIT` map to explicit lines in the research excerpt. The limitations slide states that the example demonstrates workflow mechanics and makes no empirical performance claim.

The builder validates source contracts, computes canonical digests, refreshes digest-bearing derived contracts, creates an isolated temporary project, runs public workflow actions, and returns a JSON summary. In `--check` mode it builds under a temporary directory and compares deterministic outputs to committed files without modifying the example tree.

- [ ] **Step 4: Run source-contract and check-mode tests**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_modular_example_builder.py -v`

Expected: PASS for contract validation and no-write `--check` behavior; artifact-generation assertions are added in later tasks.

- [ ] **Step 5: Commit Task 3**

```bash
git add examples/report-slides/modular-architecture-workflow \
  skills/report-slides/scripts/tests/test_modular_example_builder.py
git commit -m "feat(report-slides): add modular example contracts"
```

---

### Task 4: Author reusable modules, assignments, manifests, and integrated SVG

**Files:**
- Create: `examples/report-slides/modular-architecture-workflow/modules/observation-input/source.svg`
- Create: `examples/report-slides/modular-architecture-workflow/modules/command-input/source.svg`
- Create: `examples/report-slides/modular-architecture-workflow/modules/latent-dynamics/source-v1.svg`
- Create: `examples/report-slides/modular-architecture-workflow/modules/latent-dynamics/source-v2.svg`
- Create: `examples/report-slides/modular-architecture-workflow/modules/decoder-output/source.svg`
- Create: `examples/report-slides/modular-architecture-workflow/modules/terminology-annotations/source.svg`
- Create: `examples/report-slides/modular-architecture-workflow/modules/observation-input/assignment.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/modules/observation-input/manifest.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/modules/command-input/assignment.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/modules/command-input/manifest.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/modules/latent-dynamics/assignment.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/modules/latent-dynamics/manifest-v1.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/modules/latent-dynamics/manifest-v2.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/modules/decoder-output/assignment.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/modules/decoder-output/manifest.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/modules/terminology-annotations/assignment.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/modules/terminology-annotations/manifest.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/integration/manifest.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/slides/slide-01.svg`
- Create: `examples/report-slides/modular-architecture-workflow/slides/slide-02.svg`
- Create: `examples/report-slides/modular-architecture-workflow/slides/slide-03.svg`
- Modify: `examples/report-slides/modular-architecture-workflow/scripts/build_example.py`
- Modify: `skills/report-slides/scripts/tests/test_modular_example_builder.py`

**Interfaces:**
- Every module SVG uses the dimensions and named anchors declared by the visual specification.
- `latent-dynamics` v1 is retained as failed history; v2 supersedes it after a scientific review correction.
- Integrated slide 02 consumes only passed/current module versions and connection definitions.

- [ ] **Step 1: Add failing module source and retry-isolation tests**

```python
def test_module_sources_match_declared_anchors_and_dimensions() -> None:
    result = build_example(EXAMPLE, check=True)
    assert result["module_count"] == 5
    assert result["architecture_module_count"] == 4
    assert result["anchor_violations"] == []


def test_selective_retry_changes_only_latent_dynamics() -> None:
    summary = json.loads((EXAMPLE / "state/retry-summary.json").read_text())
    assert summary["target_module_key"] == "latent-dynamics"
    assert summary["superseded_source"] == "modules/latent-dynamics/source-v1.svg"
    assert summary["replacement_source"] == "modules/latent-dynamics/source-v2.svg"
    assert summary["unchanged_module_digests"] == {
        "observation-input": summary["before_digests"]["observation-input"],
        "command-input": summary["before_digests"]["command-input"],
        "decoder-output": summary["before_digests"]["decoder-output"],
        "terminology-annotations": summary["before_digests"]["terminology-annotations"],
    }
```

- [ ] **Step 2: Run module tests and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_modular_example_builder.py -k 'module or retry' -v`

Expected: FAIL because sources/manifests and retry evidence are absent.

- [ ] **Step 3: Author 1200x675-compatible native SVG modules and integrate them**

Use editable SVG primitives only for architecture modules: `<rect>`, `<text>`, `<line>`, `<polyline>`, and marker definitions. Put factual labels in SVG text, not raster pixels. Expose anchors as stable IDs matching the spec. Build slide 02 left-to-right: two parallel inputs, latent transition, decoder output; add cross-module connectors only in integration.

Create v1 with the command arrow incorrectly terminating after latent prediction, record the failed scientific review, then create v2 with the command path entering latent dynamics before prediction. Do not modify sibling sources or manifests.

- [ ] **Step 4: Validate manifests, sources, integration, and retry isolation**

Run:

```bash
python3 skills/report-slides/scripts/validate_diagram_manifest.py \
  --manifest examples/report-slides/modular-architecture-workflow/integration/manifest.yaml
cd skills/report-slides/scripts
python3 -m pytest tests/test_modular_example_builder.py -v
```

Expected: PASS with four architecture modules, five total modules, exact anchors, and only latent-dynamics changed by retry.

- [ ] **Step 5: Commit Task 4**

```bash
git add examples/report-slides/modular-architecture-workflow \
  skills/report-slides/scripts/tests/test_modular_example_builder.py
git commit -m "feat(report-slides): build modular architecture visual"
```

---

### Task 5: Generate review evidence, contact sheet, editable PPTX, and completion state

**Files:**
- Create: `examples/report-slides/modular-architecture-workflow/reviews/slide-02-scientific-round-1.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/reviews/slide-02-scientific-round-2.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/reviews/slide-02-visual-quality.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/reviews/deck-visual-quality.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/reviews/draft-preview.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/reviews/draft-decision.yaml`
- Create: `examples/report-slides/modular-architecture-workflow/reviews/pptx-structure.json`
- Create: `examples/report-slides/modular-architecture-workflow/reviews/pptx-render.json`
- Create: `examples/report-slides/modular-architecture-workflow/reviews/completion.json`
- Create: `examples/report-slides/modular-architecture-workflow/renders/slide-01.png`
- Create: `examples/report-slides/modular-architecture-workflow/renders/slide-02.png`
- Create: `examples/report-slides/modular-architecture-workflow/renders/slide-03.png`
- Create: `examples/report-slides/modular-architecture-workflow/renders/contact-sheet.png`
- Create: `examples/report-slides/modular-architecture-workflow/deck.pptx`
- Create: `examples/report-slides/modular-architecture-workflow/state/resume-snapshot.json`
- Create: `examples/report-slides/modular-architecture-workflow/EDITABILITY.md`
- Modify: `examples/report-slides/modular-architecture-workflow/scripts/build_example.py`
- Modify: `skills/report-slides/scripts/tests/test_modular_example_builder.py`

**Interfaces:**
- Produces a completed example deck whose final authority is the rendered PPTX review.
- Produces a resume snapshot from a fresh process before completion and a final completed query after validation.

- [ ] **Step 1: Add failing full-deck artifact and review assertions**

```python
def test_example_has_separate_reviews_and_approved_contact_sheet() -> None:
    scientific = load_contract(EXAMPLE / "reviews/slide-02-scientific-round-2.yaml")
    visual = load_contract(EXAMPLE / "reviews/slide-02-visual-quality.yaml")
    preview = load_contract(EXAMPLE / "reviews/draft-preview.yaml")
    assert scientific["reviewer_role"] == "scientific"
    assert visual["reviewer_role"] == "visual_quality"
    assert preview["rendered_slide_paths"] == [
        "renders/slide-01.png", "renders/slide-02.png", "renders/slide-03.png"
    ]
    assert preview["contact_sheet_path"] == "renders/contact-sheet.png"


def test_example_pptx_is_structurally_valid_and_completed() -> None:
    structure = load_contract(EXAMPLE / "reviews/pptx-structure.json")
    render = load_contract(EXAMPLE / "reviews/pptx-render.json")
    completion = load_contract(EXAMPLE / "reviews/completion.json")
    assert structure["status"] == "passed"
    assert render["status"] == "passed"
    assert render["authority"] == "pptx-render"
    assert completion["status"] == "completed"
```

- [ ] **Step 2: Run full-deck tests and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_modular_example_builder.py -k 'review or pptx or completed' -v`

Expected: FAIL because review/render/completion artifacts are absent.

- [ ] **Step 3: Extend builder through the guarded production workflow**

Render each SVG to PNG using the existing deterministic path, create the contact sheet from exactly those three PNGs, register and approve the draft, export native editable PPTX with `python3 -m svg_to_pptx --mode native`, run `validate_pptx_structure.py`, and build final review/completion records through public workflow actions. Capture `--query` from a new subprocess before final completion as `resume-snapshot.json`.

`EDITABILITY.md` states that native SVG rectangles, text, lines, connectors, and paths remain editable; it lists any conversion limitations found by the structural validator and does not claim raster layers are editable.

- [ ] **Step 4: Rebuild and validate all review/PPTX outputs**

Run:

```bash
python3 examples/report-slides/modular-architecture-workflow/scripts/build_example.py \
  --root examples/report-slides/modular-architecture-workflow --json
python3 examples/report-slides/modular-architecture-workflow/scripts/build_example.py \
  --root examples/report-slides/modular-architecture-workflow --check --json
cd skills/report-slides/scripts
python3 -m pytest tests/test_modular_example_builder.py -v
```

Expected: build and check exit 0, PPTX contains three slides, review PNG set is complete, and final state is completed.

- [ ] **Step 5: Commit Task 5**

```bash
git add examples/report-slides/modular-architecture-workflow \
  skills/report-slides/scripts/tests/test_modular_example_builder.py
git commit -m "feat(report-slides): complete modular deck example"
```

---

### Task 6: Add an independent offline example-consistency checker

**Files:**
- Create: `skills/report-slides/scripts/validate_modular_example.py`
- Create: `skills/report-slides/scripts/tests/test_validate_modular_example.py`
- Create: `skills/report-slides/scripts/tests/fixtures/modular-example-invalid/README.md`
- Modify: `examples/report-slides/modular-architecture-workflow/README.md`

**Interfaces:**
- Produces: `validate_example(root: Path) -> list[dict[str, str]]` and CLI `--root PATH --json` returning `{valid, findings}`.
- Reuses canonical validators and never imports `build_example.py`, preserving checker independence.

- [ ] **Step 1: Write failing checker and mutation tests**

```python
def test_committed_modular_example_passes() -> None:
    assert validate_example(EXAMPLE) == []


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("delete-contact-sheet", "missing-path"),
        ("change-module-digest", "digest-mismatch"),
        ("remove-output-anchor", "anchor-mismatch"),
        ("reduce-architecture-modules", "architecture-module-count"),
        ("modify-passed-sibling-on-retry", "retry-scope"),
        ("remove-visual-review", "missing-review-role"),
        ("mark-complete-without-pptx-render", "invalid-completion"),
    ],
)
def test_checker_rejects_contract_mutations(
    tmp_path: Path, mutation: str, expected_code: str
) -> None:
    root = copy_example(tmp_path)
    apply_mutation(root, mutation)
    assert expected_code in {finding["code"] for finding in validate_example(root)}
```

- [ ] **Step 2: Run checker tests and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_validate_modular_example.py -v`

Expected: FAIL because the independent checker does not exist.

- [ ] **Step 3: Implement all consistency checks with stable finding codes**

Check documented paths, canonical digests, every contract validator, plan/approval binding, dependency DAG, exact anchors, module count/type, parallel-ready inputs, selective retry digests, separate review roles, rendered slide set, contact sheet, PPTX package, structure/render authority, completion state, and resume snapshot consistency. Sort findings by `(code, path, message)` for deterministic output.

- [ ] **Step 4: Run checker, mutation tests, and builder check**

Run:

```bash
python3 skills/report-slides/scripts/validate_modular_example.py \
  --root examples/report-slides/modular-architecture-workflow --json
cd skills/report-slides/scripts
python3 -m pytest tests/test_validate_modular_example.py tests/test_modular_example_builder.py -v
```

Expected: committed example is valid and every mutation produces its expected finding code.

- [ ] **Step 5: Commit Task 6**

```bash
git add skills/report-slides/scripts/validate_modular_example.py \
  skills/report-slides/scripts/tests/test_validate_modular_example.py \
  skills/report-slides/scripts/tests/fixtures/modular-example-invalid \
  examples/report-slides/modular-architecture-workflow/README.md
git commit -m "test(report-slides): validate modular example integrity"
```

---

### Task 7: Integrate Phase C into indexes, setup, and documentation tests

**Files:**
- Modify: `examples/report-slides/README.md`
- Modify: `README.md`
- Modify: `skills/report-slides/SKILL.md`
- Modify: `skills/report-slides/scripts/setup.sh`
- Modify: `skills/report-slides/scripts/setup.ps1`
- Modify: `skills/report-slides/scripts/tests/test_setup_scripts.py`
- Create: `skills/report-slides/scripts/tests/test_phase_c_docs.py`

**Interfaces:**
- Makes the new reference documents, example, builder/checker commands, and editability disclosure discoverable from canonical entry points.
- Setup scripts copy `validate_modular_example.py` only when installing bundled report-slides tooling; example artifacts remain in the repository and are not copied into user projects.

- [ ] **Step 1: Write failing discoverability tests**

```python
def test_phase_c_outputs_are_discoverable() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    examples = EXAMPLES_README.read_text(encoding="utf-8")
    for name in ("references/contracts.md", "references/agent-roles.md"):
        assert name in skill
    assert "modular-architecture-workflow" in examples
    assert "build_example.py --root" in examples
    assert "validate_modular_example.py --root" in examples
    assert "EDITABILITY.md" in examples
```

- [ ] **Step 2: Run documentation/setup tests and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_phase_c_docs.py tests/test_setup_scripts.py -v`

Expected: FAIL until indexes and setup mention the Phase C outputs.

- [ ] **Step 3: Add concise links and exact offline commands**

Document what the example demonstrates, how to rebuild it, how to run check-only validation, where editability limitations are disclosed, and that the example is not empirical evidence for model performance. Keep duplicated contract prose out of README files.

- [ ] **Step 4: Run docs, setup, and link tests**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_phase_c_docs.py tests/test_setup_scripts.py tests/test_contracts_reference.py tests/test_agent_roles_reference.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 7**

```bash
git add README.md examples/report-slides/README.md skills/report-slides/SKILL.md \
  skills/report-slides/scripts/setup.sh skills/report-slides/scripts/setup.ps1 \
  skills/report-slides/scripts/tests/test_setup_scripts.py \
  skills/report-slides/scripts/tests/test_phase_c_docs.py
git commit -m "docs(report-slides): publish phase c example"
```

---

### Task 8: Final Phase C verification and completion report

**Files:**
- Modify only when verification finds an actual Phase C defect.

**Interfaces:**
- Produces verified references, deterministic example outputs, a green consistency checker, and exact test evidence for handoff.

- [ ] **Step 1: Run check-only rebuild and independent validation**

```bash
python3 examples/report-slides/modular-architecture-workflow/scripts/build_example.py \
  --root examples/report-slides/modular-architecture-workflow --check --json
python3 skills/report-slides/scripts/validate_modular_example.py \
  --root examples/report-slides/modular-architecture-workflow --json
```

Expected: both commands exit 0 and leave `git status --short` unchanged.

- [ ] **Step 2: Run focused and complete report-slides suites**

```bash
cd skills/report-slides/scripts
python3 -m pytest tests/test_contracts_reference.py \
  tests/test_agent_roles_reference.py \
  tests/test_modular_example_builder.py \
  tests/test_validate_modular_example.py \
  tests/test_phase_c_docs.py -v
python3 -m pytest -v
```

Expected: every test passes.

- [ ] **Step 3: Run repository suite under CI Python 3.11**

From repository root run: `python3.11 -m pytest scripts/ tests/ -q`

Expected: exit 0. Treat missing Python 3.11 as an environment blocker and verify in the CI-equivalent environment rather than interpreting Python 3.10 failures as Phase C regressions.

- [ ] **Step 4: Inspect generated artifacts and repository state**

```bash
python3 skills/report-slides/scripts/validate_pptx_structure.py \
  --pptx examples/report-slides/modular-architecture-workflow/deck.pptx \
  --expected-slides 3 --json
git diff --check
git status --short
```

Expected: structure status passed, three slides detected, no whitespace errors, and no uncommitted generated drift.

- [ ] **Step 5: Commit verification corrections if required**

If verification required corrections:

```bash
git add examples/report-slides/modular-architecture-workflow \
  skills/report-slides README.md examples/report-slides/README.md
git commit -m "fix(report-slides): close phase c verification findings"
```

If no correction was required, create no empty commit. The handoff reports files changed, architecture/reference additions, example contents, tests run, compatibility impact, editability limitations, and the remediation baseline commit consumed by Phase C.
