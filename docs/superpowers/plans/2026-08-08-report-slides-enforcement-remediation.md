# report-slides Enforcement Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the Phase A/B report-slides workflow from prose-directed gates into deterministic approval, production, review, retry, preview, resume, and completion enforcement.

**Architecture:** Keep `presentation_state.py` as the public CLI while extracting event loading, gate predicates, and atomic workflow actions into focused modules so the state file remains below 1000 lines. All supported artifact producers call one shared guard before creating directories or files, and agent-authored outputs enter the final tree only through an atomic publication command. Contract validators and an offline acceptance suite provide the evidence each state transition consumes.

**Tech Stack:** Python 3.11, PyYAML, Pillow, python-pptx, stdlib `hashlib`/`json`/`fcntl`/`pathlib`, pytest; no network, model, cloud, or GPU calls.

## Global Constraints

- Implement against `docs/superpowers/specs/2026-08-08-report-slides-remediation-phase-c-design.md` and retain the original multi-agent design wherever the delta does not override it.
- Use Google-style docstrings and complete type annotations for every public module, function, class, and method.
- Keep every touched Python file below approximately 1000 lines; extract focused modules instead of extending `presentation_state.py` beyond that limit.
- Write code, comments, docstrings, log messages, fixture prose, and commit subjects in English.
- Fail closed with structured JSON; never invent approval, review, artifact, or migration evidence.
- Preserve resource resolution, styles, diagram plans/manifests, asset reuse, native/data/generative/hybrid routes, SVG/PPTX export, pixel inspection, structural validation, and editability disclosure.
- New workflow contract documents use `schema_version: 1` and canonical SHA-256 over UTF-8 JSON with sorted keys and compact separators.
- Run deterministic tests without external models, network access, or GPU.
- Do not begin the Phase C plan until every remediation acceptance test passes.

---

### Task 1: Canonical contract hashing and strict Deck Plan/Approval validation

**Files:**
- Create: `skills/report-slides/scripts/presentation_contracts.py`
- Modify: `skills/report-slides/scripts/validate_deck_plan.py:1-154`
- Modify: `skills/report-slides/scripts/tests/test_validate_deck_plan.py`
- Create: `skills/report-slides/scripts/tests/test_presentation_contracts.py`

**Interfaces:**
- Produces: `load_contract(path: Path) -> Any`, `canonical_json_bytes(document: Any) -> bytes`, `contract_sha256(document: Any) -> str`, `validate_schema_version(document: Any) -> list[str]`, `validate_acyclic_dependencies(nodes: set[str], edges: dict[str, list[str]], field: str) -> list[str]`.
- Produces: strict `validate_deck_plan(doc: Any) -> list[str]` and `validate_deck_approval(doc: Any) -> list[str]` used by later workflow actions.

- [ ] **Step 1: Write failing canonicalization and strict-plan tests**

```python
def test_contract_digest_is_format_independent(tmp_path: Path) -> None:
    yaml_doc = {"schema_version": 1, "deck_id": "deck-1", "items": [2, 1]}
    assert contract_sha256(yaml_doc) == hashlib.sha256(
        b'{"deck_id":"deck-1","items":[2,1],"schema_version":1}'
    ).hexdigest()


def test_plan_requires_complete_user_preview_fields(tmp_path: Path) -> None:
    plan = valid_plan()
    for field in ("schema_version", "plan_version", "core_narrative", "status",
                  "excluded_content", "known_gaps", "authored_by"):
        invalid = dict(plan)
        invalid.pop(field)
        result = run_plan_validator(tmp_path, invalid)
        assert result.returncode == 1
        assert any(field in error for error in json.loads(result.stdout)["errors"])


def test_plan_rejects_empty_evidence_and_dependency_cycle(tmp_path: Path) -> None:
    plan = valid_plan()
    plan["slides"][0]["evidence_refs"] = []
    plan["slides"][0]["dependencies"] = ["slide-02"]
    plan["slides"][1]["dependencies"] = ["slide-01"]
    errors = validate_deck_plan(plan)
    assert any("evidence_refs" in error for error in errors)
    assert any("cycle" in error for error in errors)
```

- [ ] **Step 2: Run the new tests and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_presentation_contracts.py tests/test_validate_deck_plan.py -v`

Expected: FAIL because `presentation_contracts.py` does not exist and the current validator accepts incomplete plans/approvals.

- [ ] **Step 3: Implement canonical loading, hashing, cycle detection, and strict fields**

Use this canonicalization exactly:

```python
def canonical_json_bytes(document: Any) -> bytes:
    """Serialize a contract deterministically for digest calculation."""
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def contract_sha256(document: Any) -> str:
    """Return the canonical SHA-256 digest for a contract document."""
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()
```

Require plan status `reviewed` before approval. Require every slide's `dependencies` and `open_questions` as lists, non-empty evidence references, declared dependency IDs, and an acyclic dependency graph. Require Approval fields `schema_version`, `deck_id`, positive `plan_version`, 64-character lowercase `plan_sha256`, `decision`, `approved_by`, RFC3339-Z `approved_at`, and `approval_mode` in `interactive|explicit_noninteractive|preapproved`.

- [ ] **Step 4: Run focused tests and existing compatibility tests**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_presentation_contracts.py tests/test_validate_deck_plan.py -v`

Expected: PASS. Update old valid fixtures to the new complete contract; do not weaken negative assertions.

- [ ] **Step 5: Commit Task 1**

```bash
git add skills/report-slides/scripts/presentation_contracts.py \
  skills/report-slides/scripts/validate_deck_plan.py \
  skills/report-slides/scripts/tests/test_presentation_contracts.py \
  skills/report-slides/scripts/tests/test_validate_deck_plan.py
git commit -m "feat(report-slides): enforce plan and approval contracts"
```

---

### Task 2: Add Slide Specification validation and complete modular contracts

**Files:**
- Create: `skills/report-slides/scripts/validate_slide_spec.py`
- Create: `skills/report-slides/scripts/tests/test_validate_slide_spec.py`
- Modify: `skills/report-slides/scripts/validate_visual_module.py:1-155`
- Modify: `skills/report-slides/scripts/tests/test_validate_visual_module.py`

**Interfaces:**
- Produces: `validate_slide_spec(doc: Any) -> list[str]` and CLI `--spec PATH --json`.
- Produces: strict `validate_complex_visual_spec(doc: Any) -> list[str]`, `validate_module_spec(module: Any, index: int) -> list[str]`, and `validate_worker_assignment(doc: Any) -> list[str]`.

- [ ] **Step 1: Write failing Slide Specification and anchor-integrity tests**

```python
def test_slide_spec_requires_protected_content_and_complete_regions() -> None:
    spec = valid_slide_spec()
    spec["reading_order"] = ["missing-region"]
    errors = validate_slide_spec(spec)
    assert any("reading_order" in error for error in errors)
    for field in ("approved_takeaway", "approved_takeaway_sha256",
                  "approved_evidence_refs", "approved_evidence_sha256"):
        missing = valid_slide_spec()
        missing.pop(field)
        assert any(field in error for error in validate_slide_spec(missing))


def test_complex_spec_requires_exact_connection_anchors() -> None:
    spec = valid_complex_spec()
    spec["connections"] = [{
        "from": "observation-input.not-declared",
        "to": "latent-dynamics.observation-embedding",
    }]
    errors = validate_complex_visual_spec(spec)
    assert any("not-declared" in error and "output anchor" in error for error in errors)


def test_module_dependencies_are_declared_and_acyclic() -> None:
    spec = valid_complex_spec()
    spec["modules"][0]["dependencies"] = ["decoder-output"]
    spec["modules"][3]["dependencies"] = ["observation-input"]
    assert any("cycle" in error for error in validate_complex_visual_spec(spec))
```

- [ ] **Step 2: Run the contract tests and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_validate_slide_spec.py tests/test_validate_visual_module.py -v`

Expected: FAIL because the slide validator is absent and anchors/style/dependencies remain optional.

- [ ] **Step 3: Implement the strict validators**

Slide Specification must validate `schema_version`, `slide_id`, information hierarchy, reading order, unique regions with numeric `[x1,y1,x2,y2]` bounds inside `1200x675`, `text_to_visual_ratio` as a number from 0 through 1, visual emphasis, expected complexity, reusable components, all seven complexity signals, protected content/digests, and nullable `requires_complex_workflow` before detector execution.

ModuleSpec must require `id`, `purpose`, `semantic_responsibility`, `route`, `module_type`, anchor lists, dependency list, positive `dimensions.width/height`, `style_tokens_ref`, `editability`, `annotation_requirements`, and nullable `reuse_of`. Worker Assignment must require the generated module ID, worker type, dependency IDs, `spec_sha256`, `inputs_resolved`, `assigned_at`, and explicit `blocker`.

Resolve endpoints as exact `<module-id>.<anchor>` pairs and enforce `from` against `output_anchors`, `to` against `input_anchors`.

- [ ] **Step 4: Run focused contract tests**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_validate_slide_spec.py tests/test_validate_visual_module.py tests/test_complex_visual_detector.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add skills/report-slides/scripts/validate_slide_spec.py \
  skills/report-slides/scripts/validate_visual_module.py \
  skills/report-slides/scripts/tests/test_validate_slide_spec.py \
  skills/report-slides/scripts/tests/test_validate_visual_module.py
git commit -m "feat(report-slides): validate slide and module contracts"
```

---

### Task 3: Persist plan versions, artifacts, assignments, and readable review history

**Files:**
- Create: `skills/report-slides/scripts/presentation_events.py`
- Create: `skills/report-slides/scripts/tests/test_presentation_events.py`
- Modify: `skills/report-slides/scripts/presentation_state.py:1-980`
- Modify: `skills/report-slides/scripts/tests/test_presentation_state.py`

**Interfaces:**
- Produces: `load_review_results(project_root: Path, subject_ids: set[str] | None = None) -> list[dict[str, Any]]`.
- Produces state stores `plans.yaml`, `assignments.yaml`, and `artifacts.yaml` plus loaders/creators for each.
- Extends `query(project_root: Path, deck_id: str) -> dict[str, Any]` with plan versions, approval identity, assignments, artifacts, reviews, draft records, blockers, and `next_actions`.

- [ ] **Step 1: Write failing persistence and resume tests**

```python
def test_registering_plan_versions_preserves_prior_digest(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    deck = create_deck(project)
    first = register_plan_record(project, deck["id"], "plans/plan-v0001.yaml", "a" * 64, "planner")
    second = register_plan_record(project, deck["id"], "plans/plan-v0002.yaml", "b" * 64, "planner")
    assert first["version"] == 1
    assert second["version"] == 2
    assert second["supersedes_plan_id"] == first["id"]


def test_query_includes_review_history_and_next_actions(tmp_path: Path) -> None:
    project, deck_id, slide_id = prepared_project(tmp_path)
    record_review(project, "slide", slide_id, "scientific-reviewer", "scientific", "passed")
    resumed = query(project, deck_id)
    assert resumed["review_results"][0]["reviewer_role"] == "scientific"
    assert resumed["next_actions"] == ["record_visual_quality_review"]
```

- [ ] **Step 2: Run state/event tests and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_presentation_events.py tests/test_presentation_state.py -v`

Expected: FAIL because immutable review events cannot currently be loaded and the new stores do not exist.

- [ ] **Step 3: Extract event I/O and add durable record stores**

Move daily JSONL append/read behavior into `presentation_events.py`. Malformed JSONL must raise `StateParseError` with shard path and line number. Add id-keyed records with referential validation and canonical relative paths. Update Deck/Slide/Module fields from the approved design and keep `presentation_state.py` below 1000 lines.

Use the query shape exactly:

```python
return {
    "deck": deck,
    "plans": plans,
    "approval": approval,
    "slides": slides,
    "visual_modules": modules,
    "assignments": assignments,
    "artifacts": artifacts,
    "review_results": reviews,
    "revision_requests": revisions,
    "draft_preview": draft_preview,
    "draft_decision": draft_decision,
    "blockers": blockers,
    "next_actions": next_actions,
}
```

- [ ] **Step 4: Run state, query, and integrity tests**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_presentation_events.py tests/test_presentation_state.py -v`

Expected: PASS, including two fresh-process queries returning identical content without duplicates.

- [ ] **Step 5: Commit Task 3**

```bash
git add skills/report-slides/scripts/presentation_events.py \
  skills/report-slides/scripts/presentation_state.py \
  skills/report-slides/scripts/tests/test_presentation_events.py \
  skills/report-slides/scripts/tests/test_presentation_state.py
git commit -m "feat(report-slides): persist resumable workflow evidence"
```

---

### Task 4: Implement gate predicates and atomic workflow actions

**Files:**
- Create: `skills/report-slides/scripts/presentation_gates.py`
- Create: `skills/report-slides/scripts/presentation_workflow.py`
- Create: `skills/report-slides/scripts/tests/test_presentation_gates.py`
- Create: `skills/report-slides/scripts/tests/test_presentation_workflow.py`
- Modify: `skills/report-slides/scripts/presentation_state.py`

**Interfaces:**
- Produces `assert_plan_reviewable(project_root: Path, deck_id: str) -> dict`, `assert_plan_approvable(project_root: Path, approval: dict) -> dict`, `assert_production_allowed(project_root: Path, deck_id: str) -> dict`, `assert_module_assignable(project_root: Path, module_id: str, assignment: dict) -> dict`, `assert_module_publishable(project_root: Path, module_id: str, artifact: dict) -> dict`, `assert_slide_passable(project_root: Path, slide_id: str) -> dict`, `assert_draft_reviewable(project_root: Path, deck_id: str, preview: dict) -> dict`, and `assert_deck_completable(project_root: Path, deck_id: str, completion: dict) -> dict`.
- Produces the eight atomic workflow actions specified in the approved design.
- Adds public CLI actions `--register-plan`, `--record-content-review`, `--approve-deck`, `--record-production-review`, `--request-targeted-revision`, `--register-draft-preview`, `--approve-draft`, and `--complete-deck`.

- [ ] **Step 1: Write failing approval and completion-gate tests**

```python
def test_approval_requires_independent_passing_review(tmp_path: Path) -> None:
    project, deck_id, plan_path = registered_plan(tmp_path, authored_by="planner-a")
    write_plan_review(project, deck_id, reviewer_id="planner-a", status="passed")
    with pytest.raises(ApprovalGateError, match="reviewer must differ"):
        approve_deck(project, write_approval(project, deck_id, plan_path))


def test_unsupported_claim_blocks_approval(tmp_path: Path) -> None:
    project, deck_id, plan_path = registered_plan(tmp_path, authored_by="planner-a")
    write_plan_review(
        project, deck_id, reviewer_id="reviewer-b", status="failed",
        findings=[plan_finding("unsupported-claim")],
    )
    with pytest.raises(ApprovalGateError, match="unsupported-claim"):
        approve_deck(project, write_approval(project, deck_id, plan_path))


def test_completion_requires_both_review_roles_and_final_pptx_gates(tmp_path: Path) -> None:
    project, deck_id = deck_at_validating(tmp_path, omit="visual_quality")
    with pytest.raises(CompletionGateError, match="visual_quality"):
        complete_deck(project, deck_id, completion_record(project, deck_id))


def test_generic_status_cli_cannot_bypass_approval_or_completion(tmp_path: Path) -> None:
    project, deck_id = deck_awaiting_approval(tmp_path)
    approve = run_state_cli(project, "--set-deck-status", "--deck-id", deck_id,
                            "--status", "approved", "--json")
    assert approve.returncode == 1
    assert json.loads(approve.stdout)["error"] == "ApprovalGateError"

    completion_project, completion_deck_id = deck_at_validating(
        tmp_path / "completion", omit="pptx_render"
    )
    complete = run_state_cli(completion_project, "--set-deck-status", "--deck-id",
                             completion_deck_id, "--status", "completed", "--json")
    assert complete.returncode == 1
    assert json.loads(complete.stdout)["error"] == "CompletionGateError"
```

- [ ] **Step 2: Run workflow tests and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_presentation_gates.py tests/test_presentation_workflow.py -v`

Expected: FAIL because gated atomic actions do not exist.

- [ ] **Step 3: Implement pure predicates and workflow-level locking**

Define named exceptions `PlanGateError`, `ApprovalGateError`, `ProductionGateError`, `AssignmentGateError`, `PublicationGateError`, `ReviewGateError`, `DraftGateError`, and `CompletionGateError`, all carrying `predicate`, `deck_id`, and `blockers`.

Critical state changes must occur only inside workflow actions under `.research/presentations/state/workflow.lock`. The legacy generic status CLI delegates gated targets to those actions and fails when their evidence document is absent; it cannot directly approve, pass, draft-approve, or complete a record. `approve_deck` copies the validated source to `decks/<deck-id>/plans/plan-vNNNN.yaml`, verifies digest/version/reviewer independence, records approval, and advances atomically. `complete_deck` verifies current records and never trusts a caller-supplied `completion_allowed` boolean.

- [ ] **Step 4: Wire CLI structured errors and run tests**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_presentation_gates.py tests/test_presentation_workflow.py tests/test_presentation_state.py -v`

Expected: PASS; every rejected CLI action returns exit 1 and JSON keys `error`, `predicate`, `deck_id`, and `blockers`.

- [ ] **Step 5: Commit Task 4**

```bash
git add skills/report-slides/scripts/presentation_gates.py \
  skills/report-slides/scripts/presentation_workflow.py \
  skills/report-slides/scripts/presentation_state.py \
  skills/report-slides/scripts/tests/test_presentation_gates.py \
  skills/report-slides/scripts/tests/test_presentation_workflow.py
git commit -m "feat(report-slides): enforce atomic workflow gates"
```

---

### Task 5: Guard every artifact producer and add atomic artifact publication

**Files:**
- Create: `skills/report-slides/scripts/publish_presentation_artifact.py`
- Create: `skills/report-slides/scripts/tests/test_publish_presentation_artifact.py`
- Create: `skills/report-slides/scripts/tests/test_artifact_entrypoint_gates.py`
- Modify: `skills/report-slides/scripts/generate_slides.py:656-706`
- Modify: `skills/report-slides/scripts/to_pptx.py:145-182`
- Modify: `skills/report-slides/scripts/svg_to_pptx/__main__.py:40-71`
- Modify: `skills/report-slides/scripts/render_review_sheet.py`
- Modify: `skills/report-slides/scripts/tests/test_render_review_sheet.py`

**Interfaces:**
- Produces: `publish_artifact(project_root: Path, deck_id: str, source: Path, destination: Path, artifact_kind: str, slide_id: str | None, module_id: str | None, producer_id: str, contract_path: Path) -> dict[str, Any]`.
- Every CLI adds required `--deck-id`; `--project-root` defaults through `find_project_root(Path.cwd())`.

- [ ] **Step 1: Write actual-entrypoint skipped-approval tests**

```python
@pytest.mark.parametrize("entrypoint", ["generate", "embed-pptx", "native-pptx", "review-sheet"])
def test_artifact_entrypoint_writes_nothing_before_approval(
    entrypoint: str, tmp_path: Path
) -> None:
    project, deck_id = deck_awaiting_approval(tmp_path)
    output = project / "out"
    result = run_entrypoint(entrypoint, project, deck_id, output)
    assert result.returncode == 1
    assert not output.exists()
    assert json.loads(result.stdout)["error"] == "ProductionGateError"


def test_publish_rejects_modified_protected_digest(tmp_path: Path) -> None:
    project, deck_id, slide_id, assignment = approved_assignment(tmp_path)
    assignment["approved_takeaway_sha256"] = "0" * 64
    with pytest.raises(PublicationGateError, match="takeaway"):
        publish_artifact(project, deck_id, staged_svg(tmp_path), final_svg(project),
                         "module-svg", slide_id, None, "worker-a",
                         write_yaml(tmp_path / "assignment.yaml", assignment))
```

- [ ] **Step 2: Run artifact tests and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_artifact_entrypoint_gates.py tests/test_publish_presentation_artifact.py -v`

Expected: FAIL; current entrypoints write without deck context.

- [ ] **Step 3: Add pre-write guards and publisher validation**

Parse all arguments before side effects, call `assert_production_allowed`, then create output parents. Publication verifies the assignment/spec digests, exact anchors, dimensions, style reference, editability declaration, and destination containment under the resolved slides role. It copies to a sibling temporary file, `fsync`s, atomically replaces, then records the artifact digest. On any validation failure neither destination nor artifact record exists.

- [ ] **Step 4: Run artifact and legacy renderer tests**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_artifact_entrypoint_gates.py tests/test_publish_presentation_artifact.py tests/test_render_review_sheet.py svg_to_pptx/tests -v`

Expected: PASS. Update existing CLI tests to construct an approved deck; keep pure rendering-function tests independent of workflow storage.

- [ ] **Step 5: Commit Task 5**

```bash
git add skills/report-slides/scripts/publish_presentation_artifact.py \
  skills/report-slides/scripts/generate_slides.py \
  skills/report-slides/scripts/to_pptx.py \
  skills/report-slides/scripts/render_review_sheet.py \
  skills/report-slides/scripts/svg_to_pptx/__main__.py \
  skills/report-slides/scripts/tests/test_publish_presentation_artifact.py \
  skills/report-slides/scripts/tests/test_artifact_entrypoint_gates.py \
  skills/report-slides/scripts/tests/test_render_review_sheet.py
git commit -m "feat(report-slides): guard presentation artifact writes"
```

---

### Task 6: Enforce independent reviews, selective retry, and superseding revisions

**Files:**
- Modify: `skills/report-slides/scripts/presentation_workflow.py`
- Modify: `skills/report-slides/scripts/presentation_gates.py`
- Create: `skills/report-slides/scripts/tests/test_review_retry_workflow.py`
- Modify: `skills/report-slides/scripts/tests/test_presentation_workflow.py`

**Interfaces:**
- Consumes: stored Review Result, Revision Request, Slide, Module, Assignment, and Artifact records.
- Produces: atomic failure-to-revision behavior and replacement records linked by `supersedes_slide_id`/`supersedes_module_id`.
- Produces: validated `revision_kind` values `revise_slide`, `add_slide`, `remove_slide`, `reorder_slides`, `change_emphasis`, `change_audience`, `change_duration`, `review_finding`, `module_retry`, and `slide_retry`.

- [ ] **Step 1: Write failing independent-review and selective-retry tests**

```python
def test_scientific_pass_does_not_satisfy_visual_quality_gate(tmp_path: Path) -> None:
    project, slide_id = slide_at_review_required(tmp_path)
    record_production_review(project, passing_review(slide_id, "scientific"))
    assert load_slides(project)[slide_id]["status"] == "review_required"
    record_production_review(project, passing_review(slide_id, "visual_quality"))
    assert load_slides(project)[slide_id]["status"] == "passed"


def test_failed_module_retry_preserves_sibling_artifact(tmp_path: Path) -> None:
    project, failed_id, sibling_id, sibling_path = reviewed_modules(tmp_path)
    before = (sibling_path.stat().st_mtime_ns, contract_sha256(load_yaml(sibling_path)))
    replacement = request_targeted_revision(project, revision_for(failed_id))
    after = (sibling_path.stat().st_mtime_ns, contract_sha256(load_yaml(sibling_path)))
    assert load_modules(project)[failed_id]["status"] == "superseded"
    assert replacement["supersedes_module_id"] == failed_id
    assert load_modules(project)[sibling_id]["status"] == "passed"
    assert after == before


@pytest.mark.parametrize(
    "revision_kind",
    ["revise_slide", "add_slide", "remove_slide", "reorder_slides",
     "change_emphasis", "change_audience", "change_duration"],
)
def test_user_plan_revision_actions_create_new_reviewable_plan(
    tmp_path: Path, revision_kind: str
) -> None:
    project, deck_id = deck_awaiting_approval(tmp_path)
    result = request_targeted_revision(
        project, plan_revision(deck_id, revision_kind, requested_by="user")
    )
    assert result["revision_kind"] == revision_kind
    assert load_decks(project)[deck_id]["status"] == "planning"
```

- [ ] **Step 2: Run retry tests and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_review_retry_workflow.py -v`

Expected: FAIL because review events do not currently drive state and `passed -> producing` is illegal.

- [ ] **Step 3: Implement role-specific review aggregation and replacement creation**

Reject duplicate role/round records, reviewer self-review where prohibited, and findings inconsistent with status. A failed review creates one Revision Request targeting explicit current IDs. Targeted revision marks each target superseded and creates replacement records at `planned` with `attempt = prior.attempt + 1`; never reset passed records to producing.

- [ ] **Step 4: Run workflow and concurrency tests**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_review_retry_workflow.py tests/test_presentation_workflow.py tests/test_presentation_state.py -v`

Expected: PASS, including two independent modules reaching producing while a dependent module remains ready.

- [ ] **Step 5: Commit Task 6**

```bash
git add skills/report-slides/scripts/presentation_workflow.py \
  skills/report-slides/scripts/presentation_gates.py \
  skills/report-slides/scripts/tests/test_review_retry_workflow.py \
  skills/report-slides/scripts/tests/test_presentation_workflow.py
git commit -m "feat(report-slides): enforce selective review retries"
```

---

### Task 7: Add complete plan preview and full-deck draft review gate

**Files:**
- Create: `skills/report-slides/scripts/render_plan_preview.py`
- Create: `skills/report-slides/scripts/tests/test_render_plan_preview.py`
- Modify: `skills/report-slides/scripts/render_review_sheet.py`
- Modify: `skills/report-slides/scripts/tests/test_render_review_sheet.py`
- Modify: `skills/report-slides/scripts/presentation_workflow.py`
- Create: `skills/report-slides/scripts/tests/test_draft_review_gate.py`

**Interfaces:**
- Produces: `format_plan_preview(plan: dict[str, Any]) -> str` and CLI `--plan PATH` writing only stdout.
- Produces: `register_draft_preview(project_root: Path, preview_path: Path) -> dict[str, Any]` validation of rendered slide set, contact sheet, titles, takeaways, and artifact digests.
- Produces: separate draft decision modes `interactive` and `explicit_noninteractive` (`--yes-draft`).

- [ ] **Step 1: Write failing preview coverage tests**

```python
def test_plan_preview_contains_every_approval_field() -> None:
    output = format_plan_preview(valid_plan())
    for text in ("Purpose", "Audience", "Duration", "Core narrative",
                 "Known gaps", "Excluded content", "slide-01",
                 "Key takeaway", "Evidence", "Planned visual"):
        assert text in output


def test_draft_preview_requires_every_rendered_slide(tmp_path: Path) -> None:
    project, deck_id, preview = passed_deck_preview(tmp_path)
    preview["rendered_slide_paths"].pop()
    with pytest.raises(DraftGateError, match="rendered slide set"):
        register_draft_preview(project, write_preview(preview))


def test_initial_yes_does_not_approve_draft(tmp_path: Path) -> None:
    project, deck_id = deck_with_plan_approval_mode(tmp_path, "explicit_noninteractive")
    assert query(project, deck_id)["draft_decision"] is None
```

- [ ] **Step 2: Run preview tests and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_render_plan_preview.py tests/test_draft_review_gate.py -v`

Expected: FAIL because neither complete plan formatting nor persisted draft approval exists.

- [ ] **Step 3: Implement stdout plan preview and registered contact-sheet preview**

The plan formatter prints all required fields without writing presentation artifacts. Draft registration verifies exactly one rendered PNG for each current slide, one contact sheet produced from that set, and title/takeaway equality with the approved plan. `approve_draft` requires user identity or explicit `--yes-draft`; it advances to validating only after the preview record passes.

- [ ] **Step 4: Run preview, rendering, and workflow tests**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_render_plan_preview.py tests/test_draft_review_gate.py tests/test_render_review_sheet.py tests/test_presentation_workflow.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 7**

```bash
git add skills/report-slides/scripts/render_plan_preview.py \
  skills/report-slides/scripts/render_review_sheet.py \
  skills/report-slides/scripts/presentation_workflow.py \
  skills/report-slides/scripts/tests/test_render_plan_preview.py \
  skills/report-slides/scripts/tests/test_render_review_sheet.py \
  skills/report-slides/scripts/tests/test_draft_review_gate.py
git commit -m "feat(report-slides): enforce complete preview gates"
```

---

### Task 8: Migrate existing workflow state without inventing evidence

**Files:**
- Create: `skills/report-slides/scripts/migrate_presentation_state.py`
- Create: `skills/report-slides/scripts/tests/test_migrate_presentation_state.py`
- Modify: `skills/report-slides/scripts/presentation_state.py`

**Interfaces:**
- Produces: `migrate_state(project_root: Path, dry_run: bool) -> dict[str, Any]` and CLI `--project-root PATH [--dry-run] --json`.
- Produces migration report fields `source_schema_version`, `target_schema_version`, `migrated_ids`, `blocked_ids`, `blockers`, and `changed_paths`.

- [ ] **Step 1: Write failing migration tests**

```python
def test_migration_blocks_unverifiable_approved_deck(tmp_path: Path) -> None:
    project, deck_id = legacy_approved_deck_without_approval(tmp_path)
    report = migrate_state(project, dry_run=False)
    assert deck_id in report["blocked_ids"]
    assert load_decks(project)[deck_id]["status"] == "blocked"
    assert "approval evidence" in " ".join(report["blockers"][deck_id])


def test_dry_run_changes_no_files(tmp_path: Path) -> None:
    project = legacy_project(tmp_path)
    before = snapshot_tree(project / ".research" / "presentations")
    migrate_state(project, dry_run=True)
    assert snapshot_tree(project / ".research" / "presentations") == before
```

- [ ] **Step 2: Run migration tests and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_migrate_presentation_state.py -v`

Expected: FAIL because no migration command exists.

- [ ] **Step 3: Implement deterministic backup, conversion, and blockers**

Write a timestamped backup beside state only in non-dry-run mode. Map planning states directly, copy verifiable paths/digests, and block approved-or-later legacy decks missing approval/review evidence. Re-running against target schema returns an idempotent no-op report.

- [ ] **Step 4: Run migration and state-integrity tests**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_migrate_presentation_state.py tests/test_presentation_state.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 8**

```bash
git add skills/report-slides/scripts/migrate_presentation_state.py \
  skills/report-slides/scripts/presentation_state.py \
  skills/report-slides/scripts/tests/test_migrate_presentation_state.py
git commit -m "feat(report-slides): migrate gated presentation state"
```

---

### Task 9: Align orchestrator instructions, personas, and setup packaging

**Files:**
- Modify: `skills/report-slides/SKILL.md`
- Modify: `skills/report-slides/agents/research_narrative_planner_agent.md`
- Modify: `skills/report-slides/agents/content_reviewer_agent.md`
- Modify: `skills/report-slides/agents/slide_architect_agent.md`
- Modify: `skills/report-slides/agents/complex_visual_decomposer_agent.md`
- Modify: `skills/report-slides/agents/data_visualization_worker_agent.md`
- Modify: `skills/report-slides/agents/architecture_diagram_worker_agent.md`
- Modify: `skills/report-slides/agents/conceptual_illustration_worker_agent.md`
- Modify: `skills/report-slides/agents/annotation_worker_agent.md`
- Modify: `skills/report-slides/agents/visual_integration_agent.md`
- Modify: `skills/report-slides/agents/scientific_visual_reviewer_agent.md`
- Modify: `skills/report-slides/agents/visual_quality_reviewer_agent.md`
- Modify: `skills/report-slides/scripts/setup.sh`
- Modify: `skills/report-slides/scripts/setup.ps1`
- Modify: `skills/report-slides/scripts/tests/test_agent_persona_docs.py`
- Modify: `skills/report-slides/scripts/tests/test_setup_scripts.py`

**Interfaces:**
- Consumes only public atomic workflow CLI actions; no persona may instruct direct final artifact writes or generic gated status transitions.
- Setup scripts install every new runtime module and validator.

- [ ] **Step 1: Write failing documentation/package contract tests**

```python
def test_skill_uses_atomic_actions_and_no_illegal_transition_examples() -> None:
    text = SKILL.read_text(encoding="utf-8")
    for action in ("--register-plan", "--record-content-review", "--approve-deck",
                   "--request-targeted-revision", "--register-draft-preview",
                   "--approve-draft", "--complete-deck"):
        assert action in text
    assert "planning -> approved" not in text
    assert "passed -> producing" not in text


def test_workers_publish_only_through_artifact_command() -> None:
    for path in WORKER_PERSONAS:
        text = path.read_text(encoding="utf-8")
        assert "publish_presentation_artifact.py" in text
        assert "final destination" in text
        assert "MUST NOT write" in text
```

- [ ] **Step 2: Run docs/setup tests and confirm RED**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_agent_persona_docs.py tests/test_setup_scripts.py tests/test_visual_review_docs.py -v`

Expected: FAIL until instructions and setup copies name the new guarded workflow.

- [ ] **Step 3: Rewrite stage commands around atomic actions**

Preserve the 15-stage order, but make Stage 5 display the complete deterministic plan preview, Stage 9 publish only staged worker outputs, Stages 11/12 record role-specific review actions, Stage 13 create/register the contact sheet and wait for draft approval, and Stage 15 call `--complete-deck`. Document `--yes` and `--yes-draft` separately. Remove impossible transitions and manual pre-check-only patterns.

- [ ] **Step 4: Update setup copies and run documentation tests**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_agent_persona_docs.py tests/test_setup_scripts.py tests/test_visual_review_docs.py -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 9**

```bash
git add skills/report-slides/SKILL.md skills/report-slides/agents \
  skills/report-slides/scripts/setup.sh skills/report-slides/scripts/setup.ps1 \
  skills/report-slides/scripts/tests/test_agent_persona_docs.py \
  skills/report-slides/scripts/tests/test_setup_scripts.py
git commit -m "docs(report-slides): align agents with enforced workflow"
```

---

### Task 10: Add the complete deterministic remediation acceptance suite

**Files:**
- Create: `skills/report-slides/scripts/tests/test_multiagent_acceptance.py`
- Create: `skills/report-slides/scripts/tests/fixtures/multiagent/README.md`
- Create: `skills/report-slides/scripts/tests/fixtures/multiagent/plan.yaml`
- Create: `skills/report-slides/scripts/tests/fixtures/multiagent/slide_spec.yaml`
- Create: `skills/report-slides/scripts/tests/fixtures/multiagent/visual_spec.yaml`
- Create: `skills/report-slides/scripts/tests/fixtures/multiagent/reviews.yaml`

**Interfaces:**
- One subprocess-driven suite maps each original Acceptance Criterion 13 scenario to a named test and uses actual artifact CLIs for approval boundaries.

- [ ] **Step 1: Add the eleven scenario tests with explicit names and assertions**

Implement this exact scenario matrix:

| Test name | Setup | Required assertions |
|---|---|---|
| `test_skipped_approval_writes_no_artifact` | Deck at `awaiting_approval`; invoke `generate_slides.py` | exit 1, `ProductionGateError`, output directory absent |
| `test_rejected_plan_stays_in_content_review` | Record failed content review | deck remains `content_review`, no approval record |
| `test_plan_revision_increments_and_supersedes` | Register two valid plans | versions are 1 and 2; v2 points to superseded v1 |
| `test_unsupported_claim_blocks_approval` | Failed plan review with `unsupported-claim` | approval exits 1 and deck never reaches `approved` |
| `test_complex_visual_requires_valid_decomposition` | Complex detector returns true; omit visual spec | assignment exits 1 with `AssignmentGateError` |
| `test_independent_modules_run_while_dependency_waits` | Two root modules and one dependent module | roots reach `producing`; dependent stays `ready` |
| `test_failed_module_retry_preserves_siblings` | Fail one of two passed modules | target is superseded, replacement attempt increments, sibling digest/mtime unchanged |
| `test_scientific_review_failure_targets_revision` | Failed scientific review | only named targets receive linked revision request |
| `test_visual_quality_failure_is_independent` | Scientific pass plus visual-quality fail | slide does not pass and visual finding is retained |
| `test_partial_slide_regeneration_preserves_other_slides` | Revise one of two passed slides | only target gets replacement; other slide artifact digest/mtime unchanged |
| `test_interrupted_workflow_resumes_without_duplicates` | Query from two new processes mid-production | complete query objects equal and record counts do not increase |

Each test constructs its own temporary Git project and invokes public CLIs with:

```python
result = subprocess.run(
    command,
    cwd=project,
    capture_output=True,
    text=True,
    check=False,
)
```

- [ ] **Step 2: Run the acceptance file and fix fixture-only errors**

Run: `cd skills/report-slides/scripts && python3 -m pytest tests/test_multiagent_acceptance.py -v`

Expected: PASS. A product-code failure returns work to the owning earlier task instead of weakening an assertion.

- [ ] **Step 3: Add draft/final completion acceptance assertions**

Extend the interrupted-workflow scenario through contact-sheet registration, draft decision, PPTX structural validation, final rendered-PNG review, and completion. Assert no deck completes if any one record is removed.

- [ ] **Step 4: Run complete report-slides suite**

Run: `cd skills/report-slides/scripts && python3 -m pytest -v`

Expected: all tests pass with no network/model/GPU requirement.

- [ ] **Step 5: Commit Task 10**

```bash
git add skills/report-slides/scripts/tests/test_multiagent_acceptance.py \
  skills/report-slides/scripts/tests/fixtures/multiagent
git commit -m "test(report-slides): cover enforced multi-agent workflow"
```

---

### Task 11: Final remediation verification and Phase C entry gate

**Files:**
- Modify only if verification exposes a remediation defect; do not add Phase C artifacts in this task.

**Interfaces:**
- Produces a verified green remediation baseline and exact commit hash consumed by the Phase C plan.

- [ ] **Step 1: Run static and focused verification**

```bash
git diff --check
python3 -m compileall -q skills/report-slides/scripts
cd skills/report-slides/scripts
python3 -m pytest tests/test_multiagent_acceptance.py -v
python3 -m pytest -v
```

Expected: every command exits 0.

- [ ] **Step 2: Run repository tests under CI Python 3.11**

From repository root run: `python3.11 -m pytest scripts/ tests/ -q`

Expected: exit 0. If Python 3.11 is unavailable, record this as an environment blocker and run the command in the same Python 3.11 environment used by `.github/workflows/pytest.yml`; do not claim the suite passed from Python 3.10 results.

- [ ] **Step 3: Verify compatibility artifacts and file-size limits**

```bash
python3 -m pytest skills/report-slides/scripts/svg_to_pptx/tests -v
wc -l skills/report-slides/scripts/presentation_state.py \
  skills/report-slides/scripts/presentation_workflow.py \
  skills/report-slides/scripts/presentation_gates.py
git status --short
```

Expected: converter tests pass, each listed file is below 1000 lines, and only intentional changes exist.

- [ ] **Step 4: Record the Phase C entry decision**

Capture the remediation commit hash with `git rev-parse HEAD`. Phase C may start only when Steps 1-3 are green and there are no unresolved P1/P2 review findings.

- [ ] **Step 5: Commit verification-only corrections if any**

If corrections were necessary:

```bash
git add skills/report-slides
git commit -m "fix(report-slides): close remediation verification findings"
```

If no correction was necessary, create no empty commit.
