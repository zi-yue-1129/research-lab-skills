# report-slides Multi-Agent Redesign — Phase B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Phase A's state store and contract validators into a working multi-agent workflow: rewrite `SKILL.md` as the orchestrator that drives all 15 stages, and write the 11 agent persona files that do the planning, review, and visual-production work.

**Architecture:** `SKILL.md` is the orchestrator (Decision 3 in the design spec — no separate orchestrator persona file). At each stage it either performs deterministic work itself (calling `presentation_state.py` / the validators via CLI) or dispatches exactly one agent persona via the Task tool. Every artifact-producing step is gated by `presentation_state.py --check-production-allowed`, which is already enforced in the scripts from Phase A — Phase B's job is to make the *workflow* actually reach and respect that gate, not to add new enforcement code.

**Tech Stack:** Markdown persona files (frontmatter `name`/`description`, following the `deep-research/agents/*.md` convention exactly), Python 3 (stdlib `argparse`/`json` + `PyYAML`), `pytest`.

## Global Constraints

- **Source of truth for architecture:** `docs/superpowers/specs/2026-08-06-report-slides-multiagent-design.md`, including its "0b. Decisions confirmed before Phase B implementation" section. Every task below implements a piece of that document; where this plan gives more concrete detail (exact stage list, exact file paths, exact CLI flags), that detail is authoritative for implementation because it was derived directly from the Phase-A code, not re-derived from prose.
- **Contract document storage location (new decision, needed for Phase B, not specified in Phase A):** the Deck Plan, Deck Approval, Slide Specification, Complex Visual Specification, and Worker Assignment YAML documents (the actual contract *files*, as opposed to the lightweight status records `presentation_state.py` keeps in `state/*.yaml`) live under `.research/presentations/decks/<deck_id>/`:
  - `.research/presentations/decks/<deck_id>/plan.yaml` — Deck Plan
  - `.research/presentations/decks/<deck_id>/approval.yaml` — Deck Approval
  - `.research/presentations/decks/<deck_id>/slides/<plan_slide_id>/spec.yaml` — Slide Specification
  - `.research/presentations/decks/<deck_id>/slides/<plan_slide_id>/visual_spec.yaml` — Complex Visual Specification (only for slides with `requires_complex_workflow: true`)
  - `.research/presentations/decks/<deck_id>/slides/<plan_slide_id>/modules/<module_key>/assignment.yaml` — Worker Assignment
  This directory is under the same `.research/presentations/` root Phase A already `.gitignore`s (`_ensure_research_gitignore` in `presentation_state.py`) — no new gitignore entry needed, `decks/` is not `state/`, `events/`, or `cache/` but the existing pattern `state/*.lock` etc. does not need to cover it since nothing here is locked/atomic-written; a plain `mkdir -p` + YAML dump is sufficient because each file is written by exactly one stage, once, before the next stage reads it. This directory holds workflow bookkeeping, not final deliverables — final SVG/PNG/PPTX/manifest artifacts still go to `$SLIDES_DIR/reports/YYYY-MM-DD_<name>/` exactly as today.
- **All new script invocations use the `find ~/.claude -path` lookup pattern**, matching how `validate_visual_review.py` is already invoked in the current `SKILL.md` (line ~617) and how `deep-research`/`agent-state` agents locate `state.py` — never a bare `scripts/<name>.py` relative path (that pattern is reserved for the setup.sh-copied trio `generate_slides.py`/`validate_diagram_manifest.py`/`render_review_sheet.py`, which Phase B does not change). Example:
  ```bash
  PSTATE="$(find ~/.claude -path "*/report-slides/scripts/presentation_state.py" | head -1)"
  python3 "$PSTATE" --create-deck --title "<deck title>" --json
  ```
- **`setup.sh`/`setup.ps1` are out of scope for Phase B.** The five new Phase-A scripts (`presentation_state.py`, `complex_visual_detector.py`, `validate_deck_plan.py`, `validate_visual_module.py`, `validate_pptx_structure.py`) are never copied into the project; they run from the skill bundle via the `find` pattern above, the same as `validate_visual_review.py` already does.
- **`test_visual_review_docs.py` (`skills/report-slides/scripts/tests/test_visual_review_docs.py`) must keep passing unmodified.** It asserts these exact literal tokens exist in `SKILL.md`: `statuses.svg_preview`, `statuses.pptx_structure`, `statuses.pptx_render`, `rendered_png_paths`, `model_vision.inspected_paths`, `conversion_artifacts`, `overall.completion_allowed`, `blocked`, `not_applicable`, `source-pixel` — plus (word-boundary-normalized) the phrases `"statuses.pptx_render"` + `"authoritative"`, `"LibreOffice"` + `"rendered_png_paths"` + `"model_vision.inspected_paths"` + `"direct"`, `"completion_allowed"` + `"blocked"`, `"not_applicable"` + (`"reasons"` or `"reason"`), and `"svg_to_pptx"` + `"native"` + `"editable"`. The rewritten `SKILL.md` must keep the existing "PPTX export" section (or an equivalent with the same tokens) verbatim-enough to satisfy this test — run `python3 -m pytest scripts/tests/test_visual_review_docs.py -v` from `skills/report-slides/` after every `SKILL.md` edit.
- **Agent persona file convention** (from `skills/deep-research/agents/*.md`, the only precedent in this repo): YAML frontmatter with exactly `name` and `description` (no `metadata` block — that's a `SKILL.md`-only field); an `## Stage Boundary` section (this repo's `deep-research` agents call it "Phase Boundary" — report-slides uses "Stage" throughout its own vocabulary, so name it `## Stage Boundary` for consistency with this skill, not "Phase Boundary") stating the agent's assigned stage number(s) and a "You MUST NOT" bullet list; a `## Output Format` section with a fenced YAML/JSON skeleton using the exact contract field names from the design spec §3 table; ends with a `## Quality Criteria` bullet list. Every agent file is a **single-stage or single-purpose** agent — it never calls the Task tool itself and never advances `deck`/`slide`/`module` status (that is always the orchestrator's job, done after reading the agent's returned output).
- **`--dependencies`, `--findings-json` etc. take a JSON array/object as a single shell argument** — always build these with `python3 -c "import json,sys; print(json.dumps(...))"` or a heredoc in examples, never hand-quoted JSON, to avoid shell-escaping mistakes in copy-pasted commands.
- **File size:** no new file exceeds ~700 lines. `SKILL.md` currently is 659 lines; if the rewrite would push it past ~900, split stage-specific narrative detail out into `references/agent-roles.md` — but per Decision 6 (§0b of the design spec), `references/agent-roles.md` is deferred to Phase C, so prefer keeping `SKILL.md` itself under budget by being concise in prose and precise in the stage table, not by creating that file early.
- **Docstrings and type hints** on every new/modified Python function, per this project's global code style standard — already the pattern in every Phase A script; Task 1 (the only Python task in this plan) follows it.
- **Commit language, comments, and docstrings: English**, regardless of the conversation language, per the global code style standard.

---

### Task 1: Plan-level Review Result findings validation

**Files:**
- Modify: `skills/report-slides/scripts/validate_visual_review.py`
- Test: `skills/report-slides/scripts/tests/test_validate_visual_review.py`

**Interfaces:**
- Consumes: `_ALLOWED_FINDING_KINDS`, `_ALLOWED_FINDING_SOURCES`, `_ALLOWED_FINDING_DISPOSITIONS`, `ValidationIssue`, `_check_artifact_path`, `VALID_STATUSES` (all already defined in this file).
- Produces: `validate_review_result_findings(findings: List[Any], artifact_root: Optional[Path] = None) -> List[ValidationIssue]` and `validate_review_result(doc: Mapping[str, Any], artifact_root: Optional[Path] = None) -> List[ValidationIssue]` — both used directly by Task 4's Content Reviewer agent instructions (which tell the agent to run this validator on its own output before returning) and by the orchestrator's Stage 4 gate in Task 2's `SKILL.md`.

This resolves the known gap recorded in the design spec §3 ("Phase A status of the findings reuse") and closes Decision 5 (§0b): a plan-level Review Result's `findings` currently has no schema anywhere validating it, because the existing `_validate_findings` requires every finding to carry `scope`/`artifact_path`/`source`/`disposition` where `source` must be one of the three visual-inspection gates — fields that don't apply to a Content Reviewer's plan-level finding.

- [ ] **Step 1: Write the failing tests**

Add to `skills/report-slides/scripts/tests/test_validate_visual_review.py` (use this file's existing `_complete_payload`/`_write_asset` style fixtures already present in the file; do not invent new fixture helper names):

```python
from validate_visual_review import validate_review_result, validate_review_result_findings


def test_plan_review_finding_does_not_require_scope_or_artifact_path():
    findings = [
        {
            "kind": "unsupported-claim",
            "description": "Slide 3 claims a 40% speedup with no cited benchmark.",
            "source": "plan_review",
            "disposition": "open",
        }
    ]
    issues = validate_review_result_findings(findings)
    assert issues == []


def test_plan_review_finding_rejects_unknown_kind():
    findings = [
        {
            "kind": "not-a-real-kind",
            "description": "x",
            "source": "plan_review",
            "disposition": "open",
        }
    ]
    issues = validate_review_result_findings(findings)
    assert any(issue.path.endswith(".kind") for issue in issues)


def test_visual_gate_finding_still_requires_scope_and_artifact_path():
    findings = [
        {
            "kind": "clipping",
            "description": "Text clipped in the top-right region.",
            "source": "svg-preview",
            "disposition": "open",
        }
    ]
    issues = validate_review_result_findings(findings)
    paths = {issue.path for issue in issues}
    assert any(p.endswith(".scope") for p in paths)


def test_validate_review_result_accepts_a_well_formed_plan_review():
    doc = {
        "subject_type": "plan",
        "subject_id": "deck_20260808_ab12cd",
        "reviewer_role": "content_reviewer",
        "status": "failed",
        "round": 1,
        "findings": [
            {
                "kind": "duplicated-content",
                "description": "Slides 5 and 7 both restate the same limitation.",
                "source": "plan_review",
                "disposition": "open",
            }
        ],
    }
    assert validate_review_result(doc) == []


def test_validate_review_result_rejects_bad_subject_type():
    doc = {
        "subject_type": "not-a-type",
        "subject_id": "x",
        "reviewer_role": "content_reviewer",
        "status": "failed",
        "round": 1,
        "findings": [],
    }
    issues = validate_review_result(doc)
    assert any(issue.path == "subject_type" for issue in issues)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd skills/report-slides/scripts
python3 -m pytest tests/test_validate_visual_review.py -k "plan_review or validate_review_result" -v
```
Expected: `ImportError`/`AttributeError` — `validate_review_result_findings` and `validate_review_result` don't exist yet.

- [ ] **Step 3: Add `plan_review` as an allowed finding source**

In `skills/report-slides/scripts/validate_visual_review.py`, extend `_ALLOWED_FINDING_SOURCES`:

```python
_ALLOWED_FINDING_SOURCES: Tuple[str, ...] = (
    "svg-preview",
    "pptx-structure",
    "pptx-render",
    # Plan-level review source (Content Reviewer, Stage 4) -- findings from
    # this source describe the Deck Plan itself, not a rendered artifact, so
    # `scope`/`artifact_path` are optional rather than required for them.
    "plan_review",
)
_PLAN_LEVEL_FINDING_SOURCE = "plan_review"
```

- [ ] **Step 4: Extract the per-finding validation into a reusable function**

Replace the inner-loop body of `_validate_findings` (the `for index, finding in enumerate(findings):` block, lines ~160-194 in the current file) with a call to a new function, and implement that function so `scope`/`artifact_path` are only required when the finding's `source` is not `plan_review`:

```python
def _validate_finding_entry(
    finding_path: str,
    finding: Any,
    artifact_root: Optional[Path],
) -> List[ValidationIssue]:
    """Validate one finding entry, shared by gate-level and plan-level review.

    Args:
        finding_path: Dotted path to this finding, for error messages.
        finding: The parsed finding mapping.
        artifact_root: Artifact root for `artifact_path` resolution, or
            ``None`` when the caller has no artifact root (plan-level
            review results, which have no rendered artifact).

    Returns:
        A list of validation issues; empty if the finding is valid.
    """
    issues: List[ValidationIssue] = []
    if not isinstance(finding, Mapping):
        return [ValidationIssue(finding_path, "must be a mapping")]
    kind = finding.get("kind")
    if kind not in _ALLOWED_FINDING_KINDS:
        issues.append(ValidationIssue(f"{finding_path}.kind", f"unknown finding kind: {kind!r}"))
    source = finding.get("source")
    if source not in _ALLOWED_FINDING_SOURCES:
        issues.append(
            ValidationIssue(f"{finding_path}.source", f"unknown finding source: {source!r}")
        )
    is_plan_level = source == _PLAN_LEVEL_FINDING_SOURCE
    if not is_plan_level:
        if not isinstance(finding.get("scope"), Mapping):
            issues.append(ValidationIssue(f"{finding_path}.scope", "must be a mapping"))
        artifact_path = finding.get("artifact_path")
        issues.extend(
            _check_artifact_path(f"{finding_path}.artifact_path", artifact_path, artifact_root)
        )
    else:
        if "scope" in finding and not isinstance(finding["scope"], Mapping):
            issues.append(ValidationIssue(f"{finding_path}.scope", "must be a mapping if present"))
        if "artifact_path" in finding and finding["artifact_path"] is not None:
            issues.extend(
                _check_artifact_path(
                    f"{finding_path}.artifact_path", finding["artifact_path"], artifact_root
                )
            )
    description = finding.get("description")
    if not isinstance(description, str) or not description.strip():
        issues.append(ValidationIssue(f"{finding_path}.description", "must be a non-empty string"))
    disposition = finding.get("disposition")
    if disposition not in _ALLOWED_FINDING_DISPOSITIONS:
        issues.append(
            ValidationIssue(f"{finding_path}.disposition", f"unknown disposition: {disposition!r}")
        )
    return issues
```

Update `_validate_findings` to call `_validate_finding_entry` per finding (preserving its existing `has_open_finding`/"passing status must not retain an open finding" logic, which stays in `_validate_findings` since it depends on the gate's own `status` field, not on any single finding).

- [ ] **Step 5: Add `validate_review_result_findings` and `validate_review_result`**

```python
def validate_review_result_findings(
    findings: Any,
    artifact_root: Optional[Path] = None,
) -> List[ValidationIssue]:
    """Validate the findings list of a standalone Review Result document.

    Used for Review Result records that are not one of the three PPTX
    visual-inspection gates (svg_preview/pptx_structure/pptx_render) --
    currently, the Content Reviewer's plan-level review at Stage 4.

    Args:
        findings: The parsed `findings` list.
        artifact_root: Optional artifact root for `artifact_path`
            resolution; plan-level findings normally omit `artifact_path`
            entirely, so this is usually `None`.

    Returns:
        A list of validation issues; empty if every finding is valid.
    """
    if not isinstance(findings, list):
        return [ValidationIssue("findings", "must be a list (use [] for a clean pass)")]
    issues: List[ValidationIssue] = []
    for index, finding in enumerate(findings):
        issues.extend(_validate_finding_entry(f"findings[{index}]", finding, artifact_root))
    return issues


_REVIEW_RESULT_SUBJECT_TYPES = frozenset({"plan", "module", "slide", "deck"})


def validate_review_result(
    doc: Mapping[str, Any],
    artifact_root: Optional[Path] = None,
) -> List[ValidationIssue]:
    """Validate a standalone Review Result document.

    Args:
        doc: The parsed Review Result mapping (`presentation_state.py`'s
            `record_review` contract: `subject_type`, `subject_id`,
            `reviewer_role`, `status`, `findings`, `round`).
        artifact_root: Passed through to `validate_review_result_findings`.

    Returns:
        A list of validation issues; empty if the document is valid.
    """
    issues: List[ValidationIssue] = []
    if not isinstance(doc, Mapping):
        return [ValidationIssue("<root>", "must be a mapping")]
    subject_type = doc.get("subject_type")
    if subject_type not in _REVIEW_RESULT_SUBJECT_TYPES:
        issues.append(
            ValidationIssue(
                "subject_type",
                f"must be one of {sorted(_REVIEW_RESULT_SUBJECT_TYPES)}, got {subject_type!r}",
            )
        )
    for field in ("subject_id", "reviewer_role"):
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(ValidationIssue(field, "required non-empty string"))
    status = doc.get("status")
    if status not in VALID_STATUSES:
        issues.append(ValidationIssue("status", f"must be one of {sorted(VALID_STATUSES)}, got {status!r}"))
    round_number = doc.get("round")
    if not isinstance(round_number, int) or isinstance(round_number, bool):
        issues.append(ValidationIssue("round", "required int"))
    issues.extend(validate_review_result_findings(doc.get("findings"), artifact_root))
    return issues
```

- [ ] **Step 6: Wire a `--review-result` CLI mode**

In `main()`, change `--record` from unconditionally `required=True` to part of a mutually exclusive group with a new `--review-result`, and make `--root` optional (only meaningful with `--record`):

```python
    parser.add_argument(
        "--record", type=Path, help="Path to a PPTX visual-review.json record."
    )
    parser.add_argument(
        "--review-result", type=Path, help="Path to a standalone Review Result JSON document."
    )
    parser.add_argument(
        "--root",
        type=Path,
        help="Artifact root for relative paths in --record. Ignored for --review-result.",
    )
```

Add a mutual-exclusivity check right after `parsed = parser.parse_args(arguments)`:

```python
    if bool(parsed.record) == bool(parsed.review_result):
        parser.error("exactly one of --record or --review-result is required")
    if parsed.record and not parsed.root:
        parser.error("--root is required with --record")
```

Branch the rest of `main()` on which was given: the existing `--record` path is unchanged; the new `--review-result` path loads the JSON, calls `validate_review_result`, prints `ERROR <path>: <message>` per issue exactly like the existing branch, and exits `0` only if there are no issues (no `completion_allowed` concept applies to a standalone Review Result — it is a raw validation gate, not a completion decision).

- [ ] **Step 7: Run the tests to verify they pass**

```bash
cd skills/report-slides/scripts
python3 -m pytest tests/test_validate_visual_review.py -v
```
Expected: all tests pass, including the 5 new ones and every pre-existing case.

- [ ] **Step 8: Run the full existing report-slides suite to confirm no regression**

```bash
cd skills/report-slides/scripts
python3 -m pytest -v
```
Expected: all tests pass (Phase A left this at 293; this task should land at 298).

- [ ] **Step 9: Commit**

```bash
git add skills/report-slides/scripts/validate_visual_review.py skills/report-slides/scripts/tests/test_validate_visual_review.py
git commit -m "feat(report-slides): validate plan-level Review Result findings"
```

---

### Task 2: Rewrite SKILL.md as the 15-stage orchestrator

**Files:**
- Modify: `skills/report-slides/SKILL.md`

**Interfaces:**
- Consumes: `presentation_state.py` CLI (`--create-deck`, `--set-deck-status`, `--create-slide`, `--set-slide-status`, `--create-visual-module`, `--set-module-status`, `--record-review`, `--create-revision-request`, `--check-production-allowed`, `--query`, `--validate`, all taking `--json`); `validate_deck_plan.py --plan/--approval`; `validate_visual_module.py --spec/--assignment`; `complex_visual_detector.py --signals --thresholds`; `validate_pptx_structure.py --pptx --expected-slides [--declared-editability]`; `validate_visual_review.py --record --root` / `--review-result` (Task 1); the 11 agent files from Tasks 3-13 (dispatched by name via the Task tool — this task can be implemented and tested before Tasks 3-13 exist, since it only needs each agent's *name* and *contract*, both fixed by the design spec, not its file content).
- Produces: the full 15-stage workflow narrative every later task's agent file cross-references by stage number.

This is the highest-risk task in this plan — it is a single ~700-900 line prose/procedure document, not code, so "tests" are (a) the existing literal-string doc test in Global Constraints, which must keep passing, and (b) a manual walk-through checklist at the end of this task that a human or the task reviewer runs against the new text.

- [ ] **Step 1: Confirm the baseline doc test passes before touching anything**

```bash
cd skills/report-slides/scripts
python3 -m pytest tests/test_visual_review_docs.py -v
```
Expected: all pass (this file is untouched by Phase A; establishes the bar the rewrite must keep clearing).

- [ ] **Step 2: Keep Setup (Steps 1-2) and Style system sections unchanged**

The existing `## Setup (first use in a project)` (directory resolution, script install, Mermaid check) and `## Style system` sections (lines 22-132 of the current file) are unchanged by this redesign — no part of the task specification calls for changing directory resolution or styling. Copy them verbatim into the rewritten file.

- [ ] **Step 3: Replace `## Workflow` with the 15-stage workflow**

Replace everything from `## Workflow` through the end of `### 5. Update logs and rebuild index` (the old Stages 1-5) with the following stage structure. Each stage below states: what runs, who runs it (orchestrator = deterministic CLI calls / user interaction; or one specific agent name), its state-machine effect, and its exit condition. Write each as its own `### N. <Name>` subsection, in this exact order, each containing the described content in full prose plus the given commands/examples (not abbreviated):

**Stage 1 — Create the Deck.** Orchestrator. After Setup, before asking the user anything:
```bash
PSTATE="$(find ~/.claude -path "*/report-slides/scripts/presentation_state.py" | head -1)"
DECK_JSON=$(python3 "$PSTATE" --create-deck --title "<deck working title>" --json)
DECK_ID=$(echo "$DECK_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
```
`deck.status` starts at `planning`. State the exact rule from the design spec's Enforcement Mechanism: no SVG/PNG/PPTX/manifest is ever written before `deck.status` reaches `approved`, and this is enforced by `--check-production-allowed`, not by prose discipline.

**Stage 2 — Ask (one message).** Orchestrator. This is the existing Step 2 questionnaire (source/audience/charts/language/emphasis/style) — copy it verbatim from the current file, unchanged; it still runs before any planning.

**Stage 3 — Narrative planning.** Dispatch `research_narrative_planner_agent` (Task tool) with: the resolved log/passport content from Stage 2, `$DECK_ID`, and instructions to write `.research/presentations/decks/$DECK_ID/plan.yaml` (a Deck Plan document per the design spec §3 contract table) and return its path. Orchestrator then runs:
```bash
DDP="$(find ~/.claude -path "*/report-slides/scripts/validate_deck_plan.py" | head -1)"
python3 "$DDP" --plan ".research/presentations/decks/$DECK_ID/plan.yaml" --json
```
A non-`valid` result is a bug in the agent's output, not a workflow state — re-dispatch the same agent with the validator's errors, do not proceed. Once valid, `deck.status: planning -> content_review`.

**Stage 4 — Content review.** Dispatch `content_reviewer_agent` with the Deck Plan path. The agent returns a Review Result (`subject_type: plan`, `subject_id: $DECK_ID`); orchestrator writes it and validates:
```bash
python3 "$PSTATE" --record-review --subject-type plan --subject-id "$DECK_ID" \
    --reviewer-role content_reviewer --status <passed|failed> \
    --findings-json "$(cat review_result_findings.json)" --round 1 --json
VVR="$(find ~/.claude -path "*/report-slides/scripts/validate_visual_review.py" | head -1)"
python3 "$VVR" --review-result review_result.json --json
```
If `status: failed`, `deck.status` stays `content_review`; feed the findings back into the Research Narrative Planner (Stage 3) as a Revision Request (`--create-revision-request --subject-type plan --subject-id "$DECK_ID" --requested-by reviewer --instructions "<findings summary>"`) and re-run Stage 3-4 against a new `plan_version`. If `status: passed`, `deck.status: content_review -> awaiting_approval`.

**Stage 5 — Approval gate.** Orchestrator, interactive by default. Present the approved-by-content-review Deck Plan to the user in the same style as the current outline-confirmation prompt (numbered slide list, one line per slide: title + intended visual type tag), and wait for one of: `approve`, or a revision instruction (`revise a slide`, `add a slide`, `remove a slide`, `reorder`, `change emphasis`, `change audience`, `change duration`). A revision instruction becomes a Revision Request fed back to Stage 3 exactly as in Stage 4's revise path (`deck.status: awaiting_approval -> planning`), and the plan re-enters Stage 3-5. On `approve`:
```bash
python3 "$PSTATE" --set-deck-status --deck-id "$DECK_ID" --status approved --json
```
Write `.research/presentations/decks/$DECK_ID/approval.yaml` (Deck Approval document: `decision: approve`, `approved_by`, `approved_at`).

**Non-interactive escape hatch (applies to Stages 1-5 as a whole):** if invoked with `--yes`, skip the interactive wait in Stage 5 only — Stages 3-4 (planning + content review) still run and must still pass — and auto-approve with `approved_by: "auto (--yes)"`. If invoked with `--approved-plan-file PATH`, skip Stages 3-4-5 entirely: validate the given file with `validate_deck_plan.py --plan`, copy it to `.research/presentations/decks/$DECK_ID/plan.yaml`, and go directly to `deck.status: planning -> approved` with `approved_by: "pre-approved (--approved-plan-file)"`. Without either flag, legacy single-message invocation (today's default) still creates a Deck and passes through `content_review -> awaiting_approval` and stops for the interactive gate — this is the concrete mechanism satisfying "Legacy invocation must now enter the approval workflow unless an explicit non-interactive option is provided."

**Stage 6 — Slide specification.** For each `SlidePlanEntry` in the approved plan: `python3 "$PSTATE" --create-slide --deck-id "$DECK_ID" --plan-slide-id <slide-01> --title "<title>" --json`, then dispatch `slide_architect_agent` with that slide's plan entry, returning a Slide Specification written to `.research/presentations/decks/$DECK_ID/slides/<plan_slide_id>/spec.yaml`, including the `complexity_signals` object (`region_count`, `route_count`, `multi_stage`, `mixed_technique`, `heavy_cross_region_connections`, `expected_reuse`, `not_atomic`). `slide.status: planned -> ready`.

**Stage 7 — Complexity detection.** Orchestrator, deterministic, per slide:
```bash
CVD="$(find ~/.claude -path "*/report-slides/scripts/complex_visual_detector.py" | head -1)"
python3 "$CVD" --signals ".../spec.yaml#complexity_signals-as-json" --json
```
(Extract `complexity_signals` from the Slide Specification into a small JSON file first — `complex_visual_detector.py` takes `--signals PATH` pointing at a signals-only document, not the full spec.) The result's `requires_complex_workflow` decides the branch: `false` → skip to Stage 9 using exactly today's `generate_slides.py`/agent-authored-SVG path for this slide (Compatibility Criterion 2 — no module is created, the slide moves `ready -> producing -> review_required -> passed` directly against its own single visual). `true` → continue to Stage 8.

**Stage 8 — Complex visual decomposition.** Only for slides where Stage 7 returned `true`. Dispatch `complex_visual_decomposer_agent` with the Slide Specification; it returns a Complex Visual Specification (written to `.research/presentations/decks/$DECK_ID/slides/<plan_slide_id>/visual_spec.yaml`). Validate:
```bash
DVM="$(find ~/.claude -path "*/report-slides/scripts/validate_visual_module.py" | head -1)"
python3 "$DVM" --spec ".../visual_spec.yaml" --json
```
Then create one Visual Module record per `ModuleSpec`:
```bash
python3 "$PSTATE" --create-visual-module --slide-id "$SLIDE_ID" --module-key <module-id> \
    --module-type <data_visualization|architecture|conceptual|annotation> \
    --dependencies $(python3 -c "import json; print(' '.join(json.load(open('deps.json'))))") --json
```

**Stage 9 — Module production.** For each Visual Module whose dependencies are all `passed` (query with `--query --deck-id "$DECK_ID" --json` and inspect `visual_modules`), transition it to `producing` (`--set-module-status --module-id "$MODULE_ID" --status producing --json` — this call itself fails if a dependency is not yet `passed`, so it doubles as the readiness check) and dispatch the matching worker agent by `module_type`: `data_visualization_worker_agent`, `architecture_diagram_worker_agent`, `conceptual_illustration_worker_agent`, or `annotation_worker_agent`. Independent modules (no shared dependency) may be dispatched in the same turn since each is a separate Task-tool call; a module with an unresolved dependency stays `ready`/`blocked` until its dependency reaches `passed`. Each worker writes its module's own manifest (via the existing mandatory visual-authoring gate, Stage 3.1-3.4 of the pre-redesign workflow, reused unchanged per §5 of the design spec — each module is its own `diagram_id`-equivalent asset) and returns; orchestrator sets `--status review_required`.

**Stage 10 — Visual integration.** Once every module for a slide is `review_required` or later, dispatch `visual_integration_agent` with all of that slide's module manifests and the Complex Visual Specification's `connections`/`layout`. It assembles the integrated SVG and writes the integration manifest (`modules_ref` pointing at the Complex Visual Specification, per §5 of the design spec).

**Stage 11 — Scientific review.** Dispatch `scientific_visual_reviewer_agent` per slide (simple or integrated) with the rendered visual and its manifest. Record the result: `--record-review --subject-type slide --subject-id "$SLIDE_ID" --reviewer-role scientific --status <passed|failed> ...`. `failed` → every module still `producing`/`review_required` for that slide (or the simple slide itself) moves to `revision_required`, an new Revision Request is created (`--requested-by reviewer`), and only the affected module(s) re-enter `producing` (Stage 9) — siblings stay `passed`, satisfying the partial-regeneration requirement.

**Stage 12 — Visual quality review.** Dispatch `visual_quality_reviewer_agent`, same mechanics as Stage 11 but `--reviewer-role visual_quality`, and explicitly independent of Stage 11 — a slide only reaches `passed` when both reviews pass; either one failing alone triggers the same `revision_required` path scoped to that reviewer's findings.

**Stage 13 — Draft review gate.** Orchestrator, interactive. Once every slide/module for the deck is `passed`, `deck.status: producing -> draft_review`. Present the draft to the user (list every slide, its route tag, and its review outcomes). The user may approve (`deck.status: draft_review -> validating`, continue to Stage 14) or request targeted regeneration of specific slides (`deck.status: draft_review -> producing`, only the named slides'/modules' status is reset to `producing`, re-entering Stage 9-12 — everything else keeps its `passed` status and its existing artifacts untouched, satisfying the partial-slide-regeneration acceptance criterion).

**Stage 14 — Export and production.** Orchestrator, deterministic — this is the existing "4. Generate slides" and "PPTX export" sections of the pre-redesign `SKILL.md`, unchanged in mechanics but now preceded by the gate:
```bash
python3 "$PSTATE" --check-production-allowed --deck-id "$DECK_ID" --json
```
which fails closed (nonzero exit, no file written) if `deck.status` is somehow earlier than `approved` — copy the existing `[A]`/`[B]`/`[C]` generation sections and the `## PPTX export` section from the current file verbatim; they are unchanged.

**Stage 15 — PPTX structural validation and completion.** Orchestrator. Extends the existing visual-review gate (keep it verbatim — this is what `test_visual_review_docs.py` checks) with the new structural validator as an additional, real check before `statuses.pptx_structure` is recorded:
```bash
VPS="$(find ~/.claude -path "*/report-slides/scripts/validate_pptx_structure.py" | head -1)"
python3 "$VPS" --pptx "$SLIDES_DIR/reports/.../deck.pptx" --expected-slides <N> \
    --declared-editability declared_editability.json --json
```
Map its `{status, relationship_violations, editability_mismatches}` output into the review record's `statuses.pptx_structure` object (this mapping — supplying `round`/`reviewed_by`/`inspected_paths`/`revision_required`/`started_at`/`completed_at`/`findings` around the validator's raw facts — is exactly the "Phase B entry criterion" the design spec §5b flags; implement it here as a small deterministic mapping, not a new script). `deck.status: validating -> completed` only when `validate_visual_review.py --record` (the full completion gate, unchanged from before this redesign) passes; a failure moves `deck.status: validating -> revising` and creates a Revision Request against the failing slide(s).

- [ ] **Step 4: Keep every literal-string-tested phrase intact**

Grep the new file for each token in the Global Constraints list above; every one must still be present, and the three multi-token assertions (`pptx_render` + `authoritative`; `LibreOffice` + `rendered_png_paths` + `model_vision.inspected_paths` + `direct`; `not_applicable` + `reason(s)`) must still co-occur in the file.

- [ ] **Step 5: Run the doc test**

```bash
cd skills/report-slides/scripts
python3 -m pytest tests/test_visual_review_docs.py -v
```
Expected: all pass, unmodified from Step 1.

- [ ] **Step 6: Run the full existing suite**

```bash
cd skills/report-slides/scripts
python3 -m pytest -v
```
Expected: all pass (no Python was touched in this task; this just confirms nothing else broke).

- [ ] **Step 7: Manual walk-through checklist (record the result in the commit body, not as a new test file)**

Read the finished `SKILL.md` top to bottom and confirm: (1) every one of the 15 stages above is present as its own subsection in order; (2) every stage names either "Orchestrator" or one exact agent filename (matching Tasks 3-13's file names); (3) the non-interactive escape hatch section is present and covers both `--yes` and `--approved-plan-file`; (4) Stage 7's simple-slide pass-through is stated explicitly (Compatibility Criterion 2); (5) the existing Setup/Style/PPTX-export/Summary-output/Edge-cases sections from the old file are all still present, unchanged in content.

- [ ] **Step 8: Commit**

```bash
git add skills/report-slides/SKILL.md
git commit -m "feat(report-slides): rewrite SKILL.md as the 15-stage multi-agent orchestrator"
```

---

### Task 3: `research_narrative_planner_agent.md`

**Files:**
- Create: `skills/report-slides/agents/research_narrative_planner_agent.md`
- Test: `skills/report-slides/scripts/tests/test_agent_persona_docs.py` (new file — this task creates it)

**Interfaces:**
- Consumes: research-log/passport content and the Stage 2 answers, handed to it in its dispatch prompt (not read by the agent itself from disk beyond the log files it's given).
- Produces: a Deck Plan document (`deck_id`, `purpose`, `audience`, `estimated_duration_minutes`, `slides: [SlidePlanEntry]`, `excluded_content`, `known_gaps`, `status`) written to the path its dispatch prompt names (`.research/presentations/decks/<deck_id>/plan.yaml`, per Task 2 Stage 3) — the exact shape Task 2's Stage 3 validates with `validate_deck_plan.py --plan` and Task 4's Content Reviewer consumes.

- [ ] **Step 1: Write the failing doc test**

Create `skills/report-slides/scripts/tests/test_agent_persona_docs.py`:

```python
"""Documentation contract tests for the report-slides agent persona files.

Each test asserts that one persona file names the exact stage number(s),
MUST-NOT boundary, and contract field names its role requires -- so an
agent file cannot silently drift away from the design spec's Agent Roster
and Contract tables.
"""

from pathlib import Path

_AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents"


def _read(name: str) -> str:
    return (_AGENTS_DIR / name).read_text(encoding="utf-8")


def test_research_narrative_planner_agent_names_stage_and_boundary():
    text = _read("research_narrative_planner_agent.md")
    assert "name: research_narrative_planner_agent" in text
    assert "Stage 3" in text
    assert "Stage Boundary" in text
    assert "approve its own plan" in text
    for field in (
        "deck_id", "purpose", "audience", "estimated_duration_minutes",
        "slide_id", "key_takeaway", "evidence_refs", "intended_visual_type",
        "visual_rationale", "speaker_message", "dependencies", "open_questions",
    ):
        assert field in text, f"missing contract field: {field}"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd skills/report-slides/scripts
python3 -m pytest tests/test_agent_persona_docs.py -v
```
Expected: `FileNotFoundError` — `research_narrative_planner_agent.md` doesn't exist yet.

- [ ] **Step 3: Write `skills/report-slides/agents/research_narrative_planner_agent.md`**

Frontmatter:
```yaml
---
name: research_narrative_planner_agent
description: "Reads research-log or passport source material and drafts a Deck Plan: purpose, audience, and one SlidePlanEntry per proposed slide, with evidence references and open questions made explicit"
---
```

Required sections, in order, with the following content requirements (write full prose around these — this is not itself the file, it is what the file must contain):

1. `# Research Narrative Planner — Deck Plan Drafting` + `## Role Definition` (2-4 sentences: you turn source material into a structured Deck Plan; you propose narrative structure, you do not judge your own plan's quality or approve it).
2. `## Stage Boundary` — state assignment to **Stage 3** of the report-slides workflow. `You MUST NOT`: author any visual asset yourself (that is Stage 6+, `slide_architect_agent` and the worker agents); approve your own plan (that is Stage 4/5 — `content_reviewer_agent` and the user); invoke or simulate another agent's output.
3. `## Inputs` — describe what the dispatch prompt gives you: resolved research-log entries or passport stage records, the Stage 2 answers (audience/emphasis/duration hints/language), and the `deck_id` already created by the orchestrator.
4. `## Drafting Procedure` — narrative-arc analysis (progression via `follows:` chains, key results, failures — reuse the existing pre-redesign outline-analysis guidance about `follows:` chains verbatim as a starting point, since that logic is unchanged, just now producing a structured document instead of a printed outline); one `SlidePlanEntry` per proposed slide with every field from the Output Format below filled with real content (no placeholder titles); explicit `excluded_content` (material seen but deliberately left out, with why) and `known_gaps` (missing evidence/data the plan proceeds without).
5. `## Output Format` — a fenced `yaml` block showing the full Deck Plan document shape with the exact field names, one filled representative `SlidePlanEntry`:
```yaml
deck_id: <string, from dispatch prompt>
purpose: <string>
audience: <string>
estimated_duration_minutes: <number>
status: planning
slides:
  - slide_id: slide-01
    title: <string>
    purpose: <string>
    key_takeaway: <string>
    evidence_refs: [<string>, ...]
    intended_visual_type: native | data | generative | hybrid | none
    visual_rationale: <string>
    speaker_message: <string>
    dependencies: [<slide_id>, ...]
    open_questions: [<string>, ...]
excluded_content: [<string>, ...]
known_gaps: [<string>, ...]
```
6. `## Before Returning` — instruct the agent to validate its own output before returning: `python3 "$(find ~/.claude -path "*/report-slides/scripts/validate_deck_plan.py" | head -1)" --plan <path> --json`, and to fix any reported error before returning rather than returning invalid output for the orchestrator to catch.
7. `## Quality Criteria` — every slide has a non-empty `key_takeaway`; `intended_visual_type` matches the content (not defaulted to `native` for everything); `dependencies` only reference earlier `slide_id`s already in the plan; `known_gaps` is non-empty whenever the plan proceeds on an unverified claim.

- [ ] **Step 4: Run the doc test to verify it passes**

```bash
cd skills/report-slides/scripts
python3 -m pytest tests/test_agent_persona_docs.py -v
```

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/agents/research_narrative_planner_agent.md skills/report-slides/scripts/tests/test_agent_persona_docs.py
git commit -m "feat(report-slides): add research_narrative_planner_agent persona"
```

---

### Task 4: `content_reviewer_agent.md`

**Files:**
- Create: `skills/report-slides/agents/content_reviewer_agent.md`
- Modify: `skills/report-slides/scripts/tests/test_agent_persona_docs.py`

**Interfaces:**
- Consumes: the Deck Plan document written by Task 3's agent.
- Produces: a Review Result (`subject_type: plan`, `findings[].source: plan_review`, using the six plan-level `kind` values `unsupported-claim`, `duplicated-content`, `missing-limitation`, `excessive-background`, `unnecessary-visual`, `weak-continuity`) that Task 1's `validate_review_result` validates and Task 2's Stage 4 records.

- [ ] **Step 1: Write the failing doc test** — append to `test_agent_persona_docs.py`:

```python
def test_content_reviewer_agent_names_stage_and_finding_kinds():
    text = _read("content_reviewer_agent.md")
    assert "name: content_reviewer_agent" in text
    assert "Stage 4" in text
    assert "Stage Boundary" in text
    assert "approve a plan it authored" in text or "approve a plan it reviewed" in text
    for kind in (
        "unsupported-claim", "duplicated-content", "missing-limitation",
        "excessive-background", "unnecessary-visual", "weak-continuity",
    ):
        assert kind in text, f"missing finding kind: {kind}"
    assert "plan_review" in text
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Write `skills/report-slides/agents/content_reviewer_agent.md`**

Frontmatter:
```yaml
---
name: content_reviewer_agent
description: "Reviews a Deck Plan for unsupported claims, duplicated content, missing limitations, excessive background, unnecessary visuals, and weak continuity between slides, before it reaches the user approval gate"
---
```

Required sections:

1. `## Role Definition` — you are the quality gate between planning and user approval; you find problems, you do not fix them (fixing is `research_narrative_planner_agent`'s job on the next round) and you do not approve/reject on the user's behalf (the user's own approval is Stage 5, separate from your Stage 4 review).
2. `## Stage Boundary` — **Stage 4**. `You MUST NOT`: approve a plan it authored — you never author or revise slide content yourself; you never modify the Deck Plan file, only report findings against it; you never invoke another agent.
3. `## Review Checklist`, one subsection per finding kind, each defining what triggers it:
   - `unsupported-claim`: a `key_takeaway` or `speaker_message` states a result with no matching `evidence_refs` entry.
   - `duplicated-content`: two or more slides restate the same `key_takeaway` without a stated reason (e.g., recap slide).
   - `missing-limitation`: a slide claims a strong/surprising result with no counterpart in `known_gaps` or `open_questions` addressing its caveats.
   - `excessive-background`: more than roughly a third of slides are pure context/background with no `key_takeaway` tied to the deck's stated `purpose`.
   - `unnecessary-visual`: `intended_visual_type` is not `none` for a slide whose content is adequately a short bullet list (no data, no structural relationship to show).
   - `weak-continuity`: a slide's `dependencies` reference a slide whose content it does not actually build on, or a narrative jump with no bridging `speaker_message`.
4. `## Output Format` — a fenced `yaml` block for the Review Result, `subject_type: plan`, using `source: plan_review` on every finding, `status: passed` only when there are zero `open` findings:
```yaml
subject_type: plan
subject_id: <deck_id>
reviewer_role: content_reviewer
status: passed | failed
round: <int>
findings:
  - kind: unsupported-claim | duplicated-content | missing-limitation | excessive-background | unnecessary-visual | weak-continuity
    description: <string, cites the specific slide_id(s)>
    source: plan_review
    disposition: open
```
5. `## Before Returning` — validate with `validate_visual_review.py --review-result <path> --json` (Task 1's new mode); fix formatting errors before returning.
6. `## Quality Criteria` — every finding names at least one concrete `slide_id`; `status: failed` whenever any finding has `disposition: open`; no finding kind used outside its defined trigger above.

- [ ] **Step 4: Run the doc test to verify it passes.**

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/agents/content_reviewer_agent.md skills/report-slides/scripts/tests/test_agent_persona_docs.py
git commit -m "feat(report-slides): add content_reviewer_agent persona"
```

---

### Task 5: `slide_architect_agent.md`

**Files:**
- Create: `skills/report-slides/agents/slide_architect_agent.md`
- Modify: `skills/report-slides/scripts/tests/test_agent_persona_docs.py`

**Interfaces:**
- Consumes: one `SlidePlanEntry` from the approved Deck Plan.
- Produces: a Slide Specification (§3 contract table) including `complexity_signals`, consumed by Task 2's Stage 7 (`complex_visual_detector.py`) and, when `requires_complex_workflow: true`, by Task 6's Complex Visual Decomposer.

- [ ] **Step 1: Write the failing doc test** — append:

```python
def test_slide_architect_agent_names_stages_and_complexity_signals():
    text = _read("slide_architect_agent.md")
    assert "name: slide_architect_agent" in text
    assert "Stage 6" in text and "Stage 7" in text
    assert "Stage Boundary" in text
    assert "change an approved takeaway" in text or "an approved evidence reference" in text
    for field in (
        "information_hierarchy", "reading_order", "layout_regions", "text_to_visual_ratio",
        "visual_emphasis", "expected_complexity", "reusable_components", "requires_complex_workflow",
        "region_count", "route_count", "multi_stage", "mixed_technique",
        "heavy_cross_region_connections", "expected_reuse", "not_atomic",
    ):
        assert field in text, f"missing contract field: {field}"
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Write `skills/report-slides/agents/slide_architect_agent.md`**

Frontmatter:
```yaml
---
name: slide_architect_agent
description: "Turns one approved SlidePlanEntry into a Slide Specification: information hierarchy, layout regions, and the complexity signals that decide whether the slide needs complex-visual decomposition"
---
```

Required sections:

1. `## Role Definition` — you take one already-approved plan entry and design its layout and complexity profile; you never revisit whether the slide should exist or what its message is (that was decided at Stages 3-5).
2. `## Stage Boundary` — **Stages 6, 7**. `You MUST NOT`: change an approved `key_takeaway` or an approved `evidence_refs` entry — if you believe the plan is wrong, return a blocker in your output instead of silently altering plan-level content; author any visual asset (that starts at Stage 8/9).
3. `## Layout Procedure` (Stage 6) — derive `information_hierarchy` (ordered list of the slide's content elements, most important first), `reading_order` (region ids in the order a viewer's eye should move), `layout_regions` (each with a `region_id` and a `bbox` in the same `[x1, y1, x2, y2]` endpoint-coordinate convention already used elsewhere in this skill for the `1200x675` slide canvas), `text_to_visual_ratio`, `visual_emphasis`, `expected_complexity`, `reusable_components` (asset ids found via manifest search, reused unchanged from the pre-existing asset-discovery convention).
4. `## Complexity Signals Procedure` (Stage 7 input) — for each of the seven signals, state exactly how to determine it: `region_count`/`route_count` are counted directly from `layout_regions` and the number of distinct authoring routes needed; the five qualitative booleans (`multi_stage`, `mixed_technique`, `heavy_cross_region_connections`, `expected_reuse`, `not_atomic`) are explicit judgment calls the agent must answer, never left absent (`complex_visual_detector.py` requires `region_count`/`route_count` to be real ints, not bools — state this explicitly since it is a real, tested failure mode in `complex_visual_detector.py`).
5. `## Output Format` — fenced `yaml`:
```yaml
slide_id: <plan_slide_id>
information_hierarchy: [<string>, ...]
reading_order: [<region_id>, ...]
layout_regions:
  - region_id: <string>
    bbox: [x1, y1, x2, y2]
text_to_visual_ratio: <string, e.g. "30/70">
visual_emphasis: <string>
expected_complexity: low | medium | high
reusable_components: [<asset_id>, ...]
requires_complex_workflow: <bool, set by Stage 7's complex_visual_detector.py, not by this agent>
complexity_signals:
  region_count: <int>
  route_count: <int>
  multi_stage: <bool>
  mixed_technique: <bool>
  heavy_cross_region_connections: <bool>
  expected_reuse: <bool>
  not_atomic: <bool>
```
State explicitly that `requires_complex_workflow` is left absent/null by this agent and filled in by the orchestrator's Stage 7 call to `complex_visual_detector.py` — the agent supplies the signals, not the decision.
6. `## Quality Criteria` — every `layout_regions` entry has a `bbox` fully inside `[0, 0, 1200, 675]`; `region_count` equals `len(layout_regions)`; every qualitative signal is an explicit `true`/`false`, never omitted.

- [ ] **Step 4: Run the doc test to verify it passes.**

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/agents/slide_architect_agent.md skills/report-slides/scripts/tests/test_agent_persona_docs.py
git commit -m "feat(report-slides): add slide_architect_agent persona"
```

---

### Task 6: `complex_visual_decomposer_agent.md`

**Files:**
- Create: `skills/report-slides/agents/complex_visual_decomposer_agent.md`
- Modify: `skills/report-slides/scripts/tests/test_agent_persona_docs.py`

**Interfaces:**
- Consumes: a Slide Specification with `requires_complex_workflow: true`.
- Produces: a Complex Visual Specification (`visual_id`, `message`, `modules: [ModuleSpec]`, `connections`, `layout`) validated by `validate_visual_module.py --spec` (Task 2 Stage 8) and consumed by Task 2's module-creation loop and by every worker agent (Tasks 7-10).

- [ ] **Step 1: Write the failing doc test** — append:

```python
def test_complex_visual_decomposer_agent_names_stage_and_module_fields():
    text = _read("complex_visual_decomposer_agent.md")
    assert "name: complex_visual_decomposer_agent" in text
    assert "Stage 8" in text
    assert "Stage Boundary" in text
    assert "author any visual asset itself" in text
    for field in (
        "visual_id", "message", "modules", "connections", "layout",
        "route", "module_type", "input_anchors", "output_anchors",
        "dependencies", "style_tokens_ref", "editability", "reuse_of",
    ):
        assert field in text, f"missing contract field: {field}"
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Write `skills/report-slides/agents/complex_visual_decomposer_agent.md`**

Frontmatter:
```yaml
---
name: complex_visual_decomposer_agent
description: "Breaks one slide's complex visual into independently produced modules with typed connections, anchors, and dependencies, so specialized workers can build it in parallel"
---
```

Required sections:

1. `## Role Definition` — you decide *how* a complex visual is decomposed into modules, not what any module looks like; module authoring is the worker agents' job (Stage 9).
2. `## Stage Boundary` — **Stage 8**. `You MUST NOT`: author any visual asset itself; approve its own decomposition (there is no separate approval step for a decomposition, but the orchestrator's `validate_visual_module.py --spec` check is authoritative, not this agent's own judgment of completeness).
3. `## Decomposition Procedure` — from the Slide Specification's `complexity_signals` and `layout_regions`, identify semantically independent pieces; assign each a `route` (`native|data|generative|hybrid`, same enum used throughout this skill) and `module_type` (`data_visualization|architecture|conceptual|annotation` — matching one of the four Task 7-10 worker agents exactly); name `input_anchors`/`output_anchors` (stable connection points other modules or the integration step attach to) and `dependencies` (module ids, referentially checked by `validate_visual_module.py` against the declared module id set — an undeclared dependency id is a hard validator error, not a warning); set `reuse_of` when a module is identical to one already produced elsewhere in the deck (found via manifest search, same reuse-identity discipline as the rest of this skill), else `null`.
4. `## Output Format` — fenced `yaml`:
```yaml
visual_id: <string>
message: <string, the one thing this whole visual must communicate>
modules:
  - id: <module_key, unique within this spec>
    purpose: <string>
    route: native | data | generative | hybrid
    module_type: data_visualization | architecture | conceptual | annotation
    input_anchors: [<string>, ...]
    output_anchors: [<string>, ...]
    dependencies: [<module_id>, ...]
    style_tokens_ref: <path to style file, or null>
    editability: native | hybrid | raster
    reuse_of: <module_id, or null>
connections:
  - from: <module_id.output_anchor>
    to: <module_id.input_anchor>
layout:
  direction: <string, e.g. "left-to-right">
  hierarchy: [<module_id>, ...]
```
5. `## Before Returning` — validate with `validate_visual_module.py --spec <path> --json`; every `connections[].from`/`.to` endpoint's module id must be declared in `modules`, and the validator enforces this — fix any reported error before returning.
6. `## Quality Criteria` — no module has itself in its own `dependencies` (a cycle); every module referenced by `connections` exists in `modules`; `reuse_of` (when set) names a module id that exists somewhere in the project's manifests, not a fabricated id.

- [ ] **Step 4: Run the doc test to verify it passes.**

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/agents/complex_visual_decomposer_agent.md skills/report-slides/scripts/tests/test_agent_persona_docs.py
git commit -m "feat(report-slides): add complex_visual_decomposer_agent persona"
```

---

### Task 7: `data_visualization_worker_agent.md`

**Files:**
- Create: `skills/report-slides/agents/data_visualization_worker_agent.md`
- Modify: `skills/report-slides/scripts/tests/test_agent_persona_docs.py`

**Interfaces:**
- Consumes: one `ModuleSpec` with `module_type: data_visualization` plus a Worker Assignment.
- Produces: the module's manifest (existing `validate_diagram_manifest.py` schema, unchanged) plus its rendered SVG/PNG, via the existing mandatory visual-authoring gate.

- [ ] **Step 1: Write the failing doc test** — append:

```python
def test_data_visualization_worker_agent_names_stage_and_route():
    text = _read("data_visualization_worker_agent.md")
    assert "name: data_visualization_worker_agent" in text
    assert "Stage 9" in text
    assert "Stage Boundary" in text
    assert "Modify scientific content" in text or "modify scientific content" in text
    assert "data" in text and "route" in text
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Write `skills/report-slides/agents/data_visualization_worker_agent.md`**

Frontmatter:
```yaml
---
name: data_visualization_worker_agent
description: "Produces one assigned data-visualization module (charts, tables, metric displays, timelines) as an independently reusable, manifest-tracked asset via the [A] Python renderer or [V:DATA] SVG route"
---
```

Required sections:

1. `## Role Definition` — you produce exactly one module, the one named in your Worker Assignment; you do not decide what data to show or what it means (that was decided at Stages 3-6/8), only how to render it correctly.
2. `## Stage Boundary` — **Stage 9**. `You MUST NOT`: modify scientific content — the numbers, labels, and claims your module renders come from the plan/evidence you were given, verbatim; author modules outside your assignment — you produce exactly the one `module_id` named in your Worker Assignment, never a sibling module even if it looks related.
3. `## Production Procedure` — reference the existing `[A] Python renderer` and `[V:DATA]` SVG conventions from this skill's `SKILL.md` §"Generate slides" verbatim (chart types, `slide_data.json` shape) as your primary route; you MAY use `[V:NATIVE]` SVG for a data module when a chart type does not fit the Python renderer's supported types. Run the full mandatory visual-authoring gate (manifest search, route classification, render, pixel-vision review) exactly as already defined in `SKILL.md`'s gate section — this task does not change that gate, only scopes it to one module instead of one whole slide.
4. `## Output Format` — your module's `manifest.yaml` (existing schema, unchanged: `schema_version, diagram_id, purpose, diagram_type, authoring_route, editability, source_files, used_in, derived_from, based_on_revision, changes, generation, review`) plus a short return summary naming `module_id`, `manifest path`, `route`, `editability`, and pixel-review outcome.
5. `## Before Returning` — the module's manifest passes `validate_diagram_manifest.py --manifest <path>`; the module's render passed pixel-vision review per the existing gate.
6. `## Quality Criteria` — every number/label in the rendered module traces to a value in your assignment's input data, not invented; `editability` accurately reflects the actual output (no raster module claiming `native`).

- [ ] **Step 4: Run the doc test to verify it passes.**

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/agents/data_visualization_worker_agent.md skills/report-slides/scripts/tests/test_agent_persona_docs.py
git commit -m "feat(report-slides): add data_visualization_worker_agent persona"
```

---

### Task 8: `architecture_diagram_worker_agent.md`

**Files:**
- Create: `skills/report-slides/agents/architecture_diagram_worker_agent.md`
- Modify: `skills/report-slides/scripts/tests/test_agent_persona_docs.py`

**Interfaces:** same shape as Task 7, `module_type: architecture`.

- [ ] **Step 1: Write the failing doc test** — append:

```python
def test_architecture_diagram_worker_agent_names_stage_and_route():
    text = _read("architecture_diagram_worker_agent.md")
    assert "name: architecture_diagram_worker_agent" in text
    assert "Stage 9" in text
    assert "Stage Boundary" in text
    assert "modify scientific content" in text.lower()
    assert "native" in text
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Write `skills/report-slides/agents/architecture_diagram_worker_agent.md`**

Frontmatter:
```yaml
---
name: architecture_diagram_worker_agent
description: "Produces one assigned architecture/flow-diagram module as an editable, manifest-tracked asset via the [V:NATIVE] SVG route (or Mermaid when it converts without editability loss)"
---
```

Same section structure as Task 7's file, with role-specific content:
1. `## Role Definition` — structural/flow diagrams (architecture, pipelines, state machines) for one assigned module.
2. `## Stage Boundary` — **Stage 9**, same two `MUST NOT` bullets as Task 7 (modify scientific content; author modules outside your assignment), reworded for architecture content ("the structure and connections your module renders come from the ModuleSpec's `input_anchors`/`output_anchors`/`connections`, not invented").
3. `## Production Procedure` — `[V:NATIVE]` direct SVG is the default per this skill's existing routing table; Mermaid (`[B]`) is optional only when conversion preserves editability (reuse the existing Mermaid guidance from `SKILL.md` verbatim: `mmdc` availability check, fallback to native SVG if unavailable or lossy).
4. `## Output Format` — identical manifest shape to Task 7.
5. `## Before Returning` / `## Quality Criteria` — same pattern as Task 7, with an architecture-specific criterion: every `input_anchors`/`output_anchors` named in the ModuleSpec is present as an actual connector endpoint in the rendered SVG, so the Visual Integration agent (Stage 10) can connect this module to its neighbors without guessing coordinates.

- [ ] **Step 4: Run the doc test to verify it passes.**

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/agents/architecture_diagram_worker_agent.md skills/report-slides/scripts/tests/test_agent_persona_docs.py
git commit -m "feat(report-slides): add architecture_diagram_worker_agent persona"
```

---

### Task 9: `conceptual_illustration_worker_agent.md`

**Files:**
- Create: `skills/report-slides/agents/conceptual_illustration_worker_agent.md`
- Modify: `skills/report-slides/scripts/tests/test_agent_persona_docs.py`

**Interfaces:** same shape as Task 7, `module_type: conceptual`.

- [ ] **Step 1: Write the failing doc test** — append:

```python
def test_conceptual_illustration_worker_agent_names_stage_and_route():
    text = _read("conceptual_illustration_worker_agent.md")
    assert "name: conceptual_illustration_worker_agent" in text
    assert "Stage 9" in text
    assert "Stage Boundary" in text
    assert "modify scientific content" in text.lower()
    assert "generative" in text
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Write `skills/report-slides/agents/conceptual_illustration_worker_agent.md`**

Frontmatter:
```yaml
---
name: conceptual_illustration_worker_agent
description: "Produces one assigned conceptual-illustration module as a runtime-generated raster asset via the [V:AI] generative route when native shapes cannot adequately represent the idea"
---
```

Same section structure:
1. `## Role Definition` — free-form conceptual visuals for one assigned module, used only when structure/data routes do not fit.
2. `## Stage Boundary` — **Stage 9**, same two `MUST NOT` bullets, reworded ("the concept your module illustrates comes from the ModuleSpec's `purpose`, not invented").
3. `## Production Procedure` — `[V:AI]` generative route per this skill's existing rules verbatim: no factual labels/legends/values inside generated pixels; provide the earlier asset and name every changed region for an edit, never substitute an unrelated image; `prompt.md` recorded per the existing `generation`/`editability` reporting contract.
4. `## Output Format` — same manifest shape, with `generation.prompt`/`generation.output`/`generation.references` populated (per this skill's existing 3.4 response-facing contract, reused verbatim).
5. `## Before Returning` / `## Quality Criteria` — same pattern; conceptual-specific criterion: no factual claim, number, or label appears baked into the raster pixels (all such content stays in accompanying native overlay text or the slide's own text elements).

- [ ] **Step 4: Run the doc test to verify it passes.**

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/agents/conceptual_illustration_worker_agent.md skills/report-slides/scripts/tests/test_agent_persona_docs.py
git commit -m "feat(report-slides): add conceptual_illustration_worker_agent persona"
```

---

### Task 10: `annotation_worker_agent.md`

**Files:**
- Create: `skills/report-slides/agents/annotation_worker_agent.md`
- Modify: `skills/report-slides/scripts/tests/test_agent_persona_docs.py`

**Interfaces:** same shape as Task 7, `module_type: annotation`.

- [ ] **Step 1: Write the failing doc test** — append:

```python
def test_annotation_worker_agent_names_stage_and_route():
    text = _read("annotation_worker_agent.md")
    assert "name: annotation_worker_agent" in text
    assert "Stage 9" in text
    assert "Stage Boundary" in text
    assert "modify scientific content" in text.lower()
    assert "hybrid" in text
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Write `skills/report-slides/agents/annotation_worker_agent.md`**

Frontmatter:
```yaml
---
name: annotation_worker_agent
description: "Produces one assigned annotation module -- factual labels, callouts, and overlays composed onto another module's raster base -- via the [V:HYBRID] route"
---
```

Same section structure:
1. `## Role Definition` — factual overlay content for one assigned module, always composed onto an existing raster base named in the module's `dependencies`.
2. `## Stage Boundary` — **Stage 9**, same two `MUST NOT` bullets; additionally: you MUST NOT run before the raster base module you depend on has reached `passed` (this is enforced by `presentation_state.py --set-module-status`'s dependency gate, but state it here so the agent does not attempt to work around a `blocked` assignment).
3. `## Production Procedure` — `[V:HYBRID]`: an editable SVG overlay composed with the dependency's raster base in the same `1200x675` coordinate system; factual labels/legends/values live only in this overlay, never baked into the raster base (mirrors the rule stated from the other side in Task 9's file).
4. `## Output Format` — same manifest shape, `authoring_route: hybrid`, `editability` reflecting the overlay's own editability (the overlay layer is native even though the composed result has a raster layer beneath it — disclose this exactly, per the existing editability-loss disclosure convention).
5. `## Before Returning` / `## Quality Criteria` — same pattern; annotation-specific criterion: every label/callout traces to a value in the plan's evidence, and the overlay's `bbox`es stay within the base module's bounds.

- [ ] **Step 4: Run the doc test to verify it passes.**

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/agents/annotation_worker_agent.md skills/report-slides/scripts/tests/test_agent_persona_docs.py
git commit -m "feat(report-slides): add annotation_worker_agent persona"
```

---

### Task 11: `visual_integration_agent.md`

**Files:**
- Create: `skills/report-slides/agents/visual_integration_agent.md`
- Modify: `skills/report-slides/scripts/tests/test_agent_persona_docs.py`

**Interfaces:**
- Consumes: every `passed` module manifest for one slide, plus that slide's Complex Visual Specification (`connections`, `layout`).
- Produces: the integration manifest (§5 of the design spec: `source_files` is the final integrated SVG, `modules_ref` lists the module manifests composed).

- [ ] **Step 1: Write the failing doc test** — append:

```python
def test_visual_integration_agent_names_stage_and_modules_ref():
    text = _read("visual_integration_agent.md")
    assert "name: visual_integration_agent" in text
    assert "Stage 10" in text
    assert "Stage Boundary" in text
    assert "Redraw a validated module without cause" in text or "redraw a validated module" in text.lower()
    assert "modules_ref" in text
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Write `skills/report-slides/agents/visual_integration_agent.md`**

Frontmatter:
```yaml
---
name: visual_integration_agent
description: "Assembles a slide's already-produced, already-reviewed modules into one integrated visual, following the Complex Visual Specification's connections and layout -- without redrawing any module's own content"
---
```

Required sections:

1. `## Role Definition` — you compose, you do not create; every module you integrate has already passed production and is treated as fixed content.
2. `## Stage Boundary` — **Stage 10**. `You MUST NOT`: redraw a validated module without cause — if a module's content looks wrong, return a blocker naming the module instead of silently changing it (that is a `revision_required` case for Stage 11/12, not something you fix); invent new scientific content — every element of the integrated visual traces to a module's own manifest or the Complex Visual Specification's `connections`/`layout`, nothing added.
3. `## Integration Procedure` — read the Complex Visual Specification's `layout.direction`/`layout.hierarchy` to place modules; read `connections` to draw connectors between named `input_anchors`/`output_anchors` (from Task 6's spec); compose into one SVG at the slide's `1200x675` canvas; write the integration manifest with `modules_ref` pointing at the Complex Visual Specification file and `source_files` pointing at the new integrated SVG.
4. `## Output Format` — fenced `yaml` for the integration manifest, extending the existing manifest schema with the one new field from Phase A:
```yaml
schema_version: <int>
diagram_id: <string, this integration's own id>
purpose: <string>
diagram_type: <string>
authoring_route: native | data | generative | hybrid
editability: native | hybrid | raster
source_files: [<path to integrated SVG>]
modules_ref: <path to this slide's Complex Visual Specification>
used_in: [<slide reference>]
derived_from: null
based_on_revision: null
changes: []
generation: {}
review: {}
```
5. `## Before Returning` — validate with `validate_diagram_manifest.py --manifest <path>` (the existing `modules_ref` optional-field support added in Phase A); run the full pixel-render/vision-review gate on the integrated result exactly as any other visual.
6. `## Quality Criteria` — every module named in the Complex Visual Specification's `modules` list appears somewhere in the integrated visual; no connector references an anchor not present in some module's own manifest.

- [ ] **Step 4: Run the doc test to verify it passes.**

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/agents/visual_integration_agent.md skills/report-slides/scripts/tests/test_agent_persona_docs.py
git commit -m "feat(report-slides): add visual_integration_agent persona"
```

---

### Task 12: `scientific_visual_reviewer_agent.md`

**Files:**
- Create: `skills/report-slides/agents/scientific_visual_reviewer_agent.md`
- Modify: `skills/report-slides/scripts/tests/test_agent_persona_docs.py`

**Interfaces:**
- Consumes: a slide's (or module's) rendered visual plus the evidence it is meant to represent.
- Produces: a Review Result (`reviewer_role: scientific`) recorded via `presentation_state.py --record-review` at Task 2's Stage 11.

- [ ] **Step 1: Write the failing doc test** — append:

```python
def test_scientific_visual_reviewer_agent_names_stage_and_boundary():
    text = _read("scientific_visual_reviewer_agent.md")
    assert "name: scientific_visual_reviewer_agent" in text
    assert "Stage 11" in text
    assert "Stage Boundary" in text
    assert "aesthetic" in text.lower()
    assert "reviewer_role: scientific" in text or "reviewer_role" in text and "scientific" in text
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Write `skills/report-slides/agents/scientific_visual_reviewer_agent.md`**

Frontmatter:
```yaml
---
name: scientific_visual_reviewer_agent
description: "Judges whether a produced visual is scientifically/semantically correct -- data accurately represented, structure accurately depicted, no fabricated or misleading content -- independent of its rendering quality"
---
```

Required sections:

1. `## Role Definition` — you check truth, not looks; rendering/aesthetic defects are `visual_quality_reviewer_agent`'s job (Stage 12), a fully independent gate from yours.
2. `## Stage Boundary` — **Stage 11**. `You MUST NOT`: judge rendering/aesthetic quality (clipping, overlap, alignment, text-reflow — those are Stage 12's findings kinds, not yours); modify the visual you are reviewing.
3. `## Review Checklist` — data values in the visual match the source evidence exactly; structural/architecture diagrams accurately depict the described relationships (no invented components, no dropped connections); no claim in the visual exceeds what the evidence supports; units/axes/labels are not misleading (e.g., truncated y-axis presented without disclosure).
4. `## Output Format` — fenced `yaml` for the Review Result, reusing the same `findings[].kind` vocabulary as `_ALLOWED_FINDING_KINDS` where applicable, or `other` with a specific `description` when the defect is scientific-content-specific and none of the existing kinds fit:
```yaml
subject_type: slide | module
subject_id: <slide_id or module_id>
reviewer_role: scientific
status: passed | failed
round: <int>
findings:
  - kind: other
    description: <string, specific and falsifiable, e.g. "chart shows 45% but source data says 38%">
    source: svg-preview | pptx-render
    scope: {slide: <slide_id>, region: <region_id or module_id>}
    disposition: open
```
5. `## Quality Criteria` — every `failed` status has at least one `open` finding with a falsifiable, checkable description (not "seems off").

- [ ] **Step 4: Run the doc test to verify it passes.**

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/agents/scientific_visual_reviewer_agent.md skills/report-slides/scripts/tests/test_agent_persona_docs.py
git commit -m "feat(report-slides): add scientific_visual_reviewer_agent persona"
```

---

### Task 13: `visual_quality_reviewer_agent.md`

**Files:**
- Create: `skills/report-slides/agents/visual_quality_reviewer_agent.md`
- Modify: `skills/report-slides/scripts/tests/test_agent_persona_docs.py`

**Interfaces:**
- Consumes: a slide's (or module's) rendered visual.
- Produces: a Review Result (`reviewer_role: visual_quality`) recorded via `presentation_state.py --record-review` at Task 2's Stage 12, using the existing rendering-defect `findings[].kind` vocabulary (`clipping`, `overlap`, `text-reflow`, `connector-drift`, `crop`, `unreadably-small-text`, `missing-image`, `z-order`, `alignment`, `other`) — this is the same vocabulary the pre-redesign single-agent gate already used; this agent is the first to use it as one of two independent gates rather than the only gate.

- [ ] **Step 1: Write the failing doc test** — append:

```python
def test_visual_quality_reviewer_agent_names_stage_and_finding_kinds():
    text = _read("visual_quality_reviewer_agent.md")
    assert "name: visual_quality_reviewer_agent" in text
    assert "Stage 12" in text
    assert "Stage Boundary" in text
    assert "scientific" in text.lower() and "semantic" in text.lower()
    for kind in (
        "clipping", "overlap", "text-reflow", "connector-drift", "crop",
        "unreadably-small-text", "missing-image", "z-order", "alignment",
    ):
        assert kind in text, f"missing finding kind: {kind}"
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Write `skills/report-slides/agents/visual_quality_reviewer_agent.md`**

Frontmatter:
```yaml
---
name: visual_quality_reviewer_agent
description: "Judges whether a produced visual renders correctly -- no clipping, overlap, text-reflow, connector drift, cropping, unreadable text, missing images, z-order, or alignment defects -- independent of its scientific correctness"
---
```

Required sections:

1. `## Role Definition` — you check how it looks, not whether it's true; scientific/semantic correctness is `scientific_visual_reviewer_agent`'s job (Stage 11), a fully independent gate from yours.
2. `## Stage Boundary` — **Stage 12**. `You MUST NOT`: judge scientific/semantic correctness — a visual that is aesthetically perfect but represents the wrong data still passes your gate and is Stage 11's problem, not yours; modify the visual you are reviewing.
3. `## Review Checklist` — this is exactly the pre-redesign pixel-inspection review this skill already performs (`references/visual-review.md`'s vision-review procedure, reused unchanged), now scoped as its own independent gate: for each of the nine rendering-defect kinds (`clipping`, `overlap`, `text-reflow`, `connector-drift`, `crop`, `unreadably-small-text`, `missing-image`, `z-order`, `alignment`), state the concrete visual symptom that triggers it, one line each.
4. `## Output Format` — fenced `yaml`, same shape as Task 12's but `reviewer_role: visual_quality` and findings using the nine rendering-defect kinds (or `other`):
```yaml
subject_type: slide | module
subject_id: <slide_id or module_id>
reviewer_role: visual_quality
status: passed | failed
round: <int>
findings:
  - kind: clipping | overlap | text-reflow | connector-drift | crop | unreadably-small-text | missing-image | z-order | alignment | other
    description: <string>
    source: svg-preview | pptx-render
    scope: {slide: <slide_id>, region: <region_id or module_id>}
    disposition: open
```
5. `## Quality Criteria` — every finding names a specific `region`/module within `scope`, not "the slide" generically; `status: passed` requires zero `open` findings.

- [ ] **Step 4: Run the doc test to verify it passes.**

- [ ] **Step 5: Run the full suite one final time**

```bash
cd skills/report-slides/scripts
python3 -m pytest -v
```
Expected: all pass — 298 (Task 1) + 11 new doc tests (Tasks 3-13) = 309, plus everything from Phase A untouched.

- [ ] **Step 6: Commit**

```bash
git add skills/report-slides/agents/visual_quality_reviewer_agent.md skills/report-slides/scripts/tests/test_agent_persona_docs.py
git commit -m "feat(report-slides): add visual_quality_reviewer_agent persona"
```
