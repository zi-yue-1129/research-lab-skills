# Report Slides Evidence Schema v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace schema-v1 path-based authorization with schema-v2 immutable evidence envelopes, content-addressed artifact bytes, explicit current-evidence pointers, and one shared validation kernel.

**Architecture:** Producers, gates, and migration share pure evidence and record validators. Migration builds one no-follow immutable snapshot, validates historical evidence intrinsically, projects only pointer-selected evidence against current state, and commits the v2 evidence store, deck pointers, CAS objects, and schema markers atomically. Audit JSONL remains byte-identical; gates never fall back to schema-v1 events.

**Tech Stack:** Python 3.10+, PyYAML, JSONL, SHA-256, POSIX `open`/`flock`/`fsync`, existing `WorkflowTransaction`, pytest, Ruff.

## Global Constraints

- Support exactly schema 0 to 2, schema 1 to 2, and schema 2 to 2 exact no-op.
- Keep immutable JSONL event shards byte-identical during migration.
- Store CAS objects at `.research/presentations/evidence/sha256/<first-two-hex>/<full-sha256>`.
- New workflow actions write audit event, evidence envelope, CAS references, and deck pointer in one transaction.
- Gates trust only schema-v2 pointers and verified CAS bytes; no schema-v1 fallback is allowed.
- Historical unavailable artifacts remain history but cannot authorize a current gate.
- Dry-run creates no locks, directories, sidecars, journals, backups, CAS objects, or mtimes.
- Wet migration acquires workflow, state, event, then CAS locks and re-analyzes under lock.
- Never invent plans, reviews, approvals, artifacts, attempts, identities, timestamps, or evidence.
- All function signatures require type annotations; all public modules, functions, classes, and methods require complete Google-style docstrings.
- Keep every source and test file below 1000 lines.
- Write code comments, docstrings, errors, logs, and commit subjects in English.
- Do not add `Co-Authored-By` trailers and do not force-add ignored SDD reports.

---

## File Structure

New focused modules:

- `skills/report-slides/scripts/presentation_evidence_contracts.py`: schema-v2 envelope, record-kind, alias, and pointer contracts.
- `skills/report-slides/scripts/presentation_evidence_cas.py`: canonical CAS paths and no-follow byte verification/planning.
- `skills/report-slides/scripts/presentation_evidence_snapshot.py`: immutable parsed state/event/artifact snapshot.
- `skills/report-slides/scripts/presentation_evidence_projection.py`: historical-envelope conversion and current-evidence projection.
- `skills/report-slides/scripts/presentation_evidence_store.py`: evidence-store serialization and producer-side atomic staging.
- `skills/report-slides/scripts/presentation_migration_v2.py`: schema 0/1 conversion plan and schema-2 no-op analysis.

Existing modules retain these responsibilities:

- `migrate_presentation_state.py`: scope, backup, transaction orchestration, CLI, and exact six-key report.
- `migration_scope.py`: canonical scope/path/operational-lock classification only; evidence semantics move out.
- `presentation_transactions.py`: durable multi-file/CAS transaction and recovery allowlist/order.
- `presentation_workflow.py`: high-level actions and atomic pointer transitions.
- `presentation_gates.py`: named gate errors and calls into active-evidence projection.
- `presentation_events.py` and `presentation_state.py`: low-level storage with schema-version guard.

---

### Task 1: Shared Evidence and Record Contract Kernel

**Files:**
- Create: `skills/report-slides/scripts/presentation_evidence_contracts.py`
- Create: `skills/report-slides/scripts/tests/test_presentation_evidence_contracts.py`
- Modify: `skills/report-slides/scripts/migration_scope.py`
- Test: `skills/report-slides/scripts/tests/test_task8_fix_round6.py`

**Interfaces:**
- Consumes: `presentation_contracts.contract_sha256`, canonical project-relative path validation, current public slide/module constructor shapes.
- Produces: `EvidenceContractError`, `EVIDENCE_SCHEMA_VERSION`, `envelope_sha256()`, `validate_envelope()`, `validate_store_record()`, `validate_deck_evidence_pointers()`, and `artifact_policy_for_event()`.

- [ ] **Step 1: Write RED tests for exact envelope and store-record schemas**

```python
def test_module_retry_accepts_equal_digest_aliases_from_real_workflow() -> None:
    record = real_module_retry_record()
    record["spec_sha256"] = record["visual_spec_sha256"]
    validate_store_record("visual_modules", record, relations=real_relations())


def test_assignment_cannot_spoof_module_nullable_paths() -> None:
    record = real_assignment_record()
    record.update({"status": "planned", "module_key": "hero", "assignment_path": None})
    with pytest.raises(EvidenceContractError, match="assignments"):
        validate_store_record("assignments", record, relations=real_relations())
```

Cover exact envelope base fields, evidence-kind refinements, bool-as-int, unknown fields, equal/conflicting spec aliases, real producer module replacement, wrong attempt/source/revision relation, and pointer ownership/kind.

- [ ] **Step 2: Run RED**

Run:

```bash
cd skills/report-slides/scripts
python3 -m pytest tests/test_presentation_evidence_contracts.py -q
```

Expected: collection fails because `presentation_evidence_contracts` does not exist.

- [ ] **Step 3: Implement typed contract values and validators**

Define these public interfaces exactly:

```python
EVIDENCE_SCHEMA_VERSION = 2

class EvidenceContractError(ValueError):
    """Raised when a schema-v2 evidence or state contract is invalid."""

def envelope_sha256(envelope: Mapping[str, Any]) -> str:
    """Return the canonical digest excluding ``evidence_sha256``."""

def validate_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Return a validated copy of one exact schema-v2 envelope."""

def validate_store_record(
    store_name: str,
    record: Mapping[str, Any],
    *,
    relations: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate one record using authoritative store and relation context."""

def validate_deck_evidence_pointers(
    deck: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, Any]],
) -> None:
    """Validate pointer ownership, kind, lifecycle, and availability."""

def artifact_policy_for_event(event_kind: str) -> str:
    """Return ``draft_preview``, ``deck_completion``, or ``none``."""
```

Use explicit base/refinement schemas rather than arbitrary key subsets. Remove record-shape inference from `migration_scope.py`; retain only canonical path mechanics there.

- [ ] **Step 4: Run GREEN and compatibility tests**

```bash
python3 -m pytest tests/test_presentation_evidence_contracts.py tests/test_task8_fix_round6.py -q
ruff check presentation_evidence_contracts.py migration_scope.py tests/test_presentation_evidence_contracts.py
```

Expected: all pass, no file exceeds 999 lines.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/presentation_evidence_contracts.py \
  skills/report-slides/scripts/migration_scope.py \
  skills/report-slides/scripts/tests/test_presentation_evidence_contracts.py \
  skills/report-slides/scripts/tests/test_task8_fix_round6.py
git commit -m "feat(report-slides): define evidence v2 contracts"
```

---

### Task 2: Content-addressed Artifact Store

**Files:**
- Create: `skills/report-slides/scripts/presentation_evidence_cas.py`
- Create: `skills/report-slides/scripts/tests/test_presentation_evidence_cas.py`
- Modify: `skills/report-slides/scripts/presentation_transactions.py`

**Interfaces:**
- Consumes: `WorkflowTransaction.stage_bytes()`, project-relative canonical paths, SHA-256.
- Produces: `CasError`, immutable `CasObject`, `cas_relative_path()`, `read_verified_source()`, `plan_cas_objects()`, and CAS transaction target allowlisting.

- [ ] **Step 1: Write RED tests for CAS safety and durability**

```python
def test_plan_cas_object_hashes_source_without_following_symlink(tmp_path: Path) -> None:
    source = fixture_regular_artifact(tmp_path, b"pptx-bytes")
    planned = plan_cas_objects(tmp_path, {"output/deck.pptx": source})
    digest = hashlib.sha256(b"pptx-bytes").hexdigest()
    assert planned[digest].relative_path == Path(
        f".research/presentations/evidence/sha256/{digest[:2]}/{digest}"
    )
```

Add dedup, existing-object byte mismatch, missing source, traversal, symlink,
FIFO, short write, replace/fsync failure, exact rollback, crash recovery, and
mode/mtime tests.

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest tests/test_presentation_evidence_cas.py -q
```

Expected: collection fails because the CAS module does not exist.

- [ ] **Step 3: Implement CAS planning and verification**

```python
@dataclass(frozen=True)
class CasObject:
    """One verified immutable content-addressed object."""
    digest: str
    relative_path: Path
    content: bytes
    mode: int

def cas_relative_path(digest: str) -> Path:
    """Return the canonical schema-v2 path for one lowercase SHA-256."""

def read_verified_source(project_root: Path, relative_path: str) -> CasObject:
    """Read and hash one regular source with no-follow semantics."""

def plan_cas_objects(
    project_root: Path,
    source_paths: Mapping[str, Path],
) -> dict[str, CasObject]:
    """Return deduplicated CAS objects without mutating the filesystem."""
```

Extend transaction target validation and deterministic ordering for canonical
CAS paths. CAS directories and objects must be restored or retained exactly by
ordinary rollback and durable recovery.

- [ ] **Step 4: Run GREEN and transaction regression**

```bash
python3 -m pytest tests/test_presentation_evidence_cas.py tests/test_presentation_transactions.py -q
```

Expected: all pass; no stable lock sidecar is ever unlinked after release.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/presentation_evidence_cas.py \
  skills/report-slides/scripts/presentation_transactions.py \
  skills/report-slides/scripts/tests/test_presentation_evidence_cas.py \
  skills/report-slides/scripts/tests/test_presentation_transactions.py
git commit -m "feat(report-slides): add durable evidence CAS"
```

---

### Task 3: Immutable Evidence Snapshot and Historical Conversion

**Files:**
- Create: `skills/report-slides/scripts/presentation_evidence_snapshot.py`
- Create: `skills/report-slides/scripts/presentation_evidence_projection.py`
- Create: `skills/report-slides/scripts/tests/test_presentation_evidence_projection.py`
- Modify: `skills/report-slides/scripts/migrate_presentation_state.py`
- Modify: `skills/report-slides/scripts/migration_scope.py`

**Interfaces:**
- Consumes: validated store records, parsed JSONL, plan/approval/review validators, CAS planning.
- Produces: immutable `EvidenceSnapshot`, `HistoricalProjection`, `build_snapshot()`, and `project_historical_evidence()`.

- [ ] **Step 1: Write RED tests for historical temporal semantics**

```python
def test_historical_preview_survives_targeted_revision_without_current_binding(
    workflow_project: Path,
) -> None:
    preview_id = create_approved_preview_then_revise(workflow_project)
    snapshot = build_snapshot(workflow_project)
    projection = project_historical_evidence(snapshot)
    envelope = projection.by_source_event_id[preview_id]
    assert envelope["availability"] == "available"
    assert envelope["id"] not in projection.current_pointer_ids


def test_missing_historical_bytes_become_unavailable_without_fabrication(
    workflow_project: Path,
) -> None:
    source_event_id, artifact_path = create_historical_preview(workflow_project)
    artifact_path.unlink()
    projection = project_historical_evidence(build_snapshot(workflow_project))
    assert projection.by_source_event_id[source_event_id]["availability"] == "historical_unavailable"
    assert projection.cas_objects == {}
```

Cover preview and completion history, event-digest tampering, source-event ID,
ordered metadata, binding inconsistency, missing bytes, and JSONL byte identity.

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest tests/test_presentation_evidence_projection.py -q
```

Expected: collection fails because snapshot/projection modules do not exist.

- [ ] **Step 3: Implement immutable snapshot and intrinsic projection**

```python
@dataclass(frozen=True)
class EvidenceSnapshot:
    """Locked or dry-run immutable presentation state and audit history."""
    project_root: Path
    schema_version: int
    stores: Mapping[str, Mapping[str, Mapping[str, Any]]]
    events: tuple[Mapping[str, Any], ...]
    file_preimages: Mapping[Path, bytes]

@dataclass(frozen=True)
class HistoricalProjection:
    """Intrinsic envelopes and verified CAS plans derived from history."""
    envelopes: Mapping[str, Mapping[str, Any]]
    by_source_event_id: Mapping[str, Mapping[str, Any]]
    cas_objects: Mapping[str, CasObject]
    current_pointer_ids: frozenset[str]

def build_snapshot(project_root: Path, *, locked: bool = False) -> EvidenceSnapshot:
    """Read one no-follow immutable snapshot without mutating state."""

def project_historical_evidence(snapshot: EvidenceSnapshot) -> HistoricalProjection:
    """Convert valid history without applying current-state predicates."""
```

Do not compare historical attempts to current slides. Mark missing historical
bytes unavailable; reject structurally forged history. Keep `migrate_presentation_state.py`
below 1000 lines by moving parsing/indexing into the snapshot module.

- [ ] **Step 4: Run GREEN and legacy migration regressions**

```bash
python3 -m pytest tests/test_presentation_evidence_projection.py \
  tests/test_migrate_presentation_state.py tests/test_task8_fix_round6.py -q
```

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/presentation_evidence_snapshot.py \
  skills/report-slides/scripts/presentation_evidence_projection.py \
  skills/report-slides/scripts/migrate_presentation_state.py \
  skills/report-slides/scripts/migration_scope.py \
  skills/report-slides/scripts/tests/test_presentation_evidence_projection.py
git commit -m "feat(report-slides): project immutable evidence history"
```

---

### Task 4: Active Evidence Projection and Completion Pointer

**Files:**
- Modify: `skills/report-slides/scripts/presentation_evidence_projection.py`
- Modify: `skills/report-slides/scripts/presentation_evidence_contracts.py`
- Create: `skills/report-slides/scripts/tests/test_presentation_active_evidence.py`
- Modify: `skills/report-slides/scripts/tests/test_draft_review_gate.py`
- Modify: `skills/report-slides/scripts/tests/test_presentation_workflow.py`

**Interfaces:**
- Consumes: `EvidenceSnapshot`, historical envelopes, current deck pointers, approved plan, slides, artifact records, CAS objects.
- Produces: `ActiveEvidenceProjection`, `project_active_evidence()`, and deterministic deck blockers.

- [ ] **Step 1: Write RED tests for current preview and completion**

```python
def test_active_preview_requires_exact_ordered_passed_slide_set(
    approved_project: Path,
) -> None:
    snapshot = snapshot_with_extra_active_slide(approved_project)
    active = project_active_evidence(snapshot, project_historical_evidence(snapshot))
    assert active.blockers["deck-1"] == [{"reason": "active_preview_slide_set_mismatch"}]


def test_ambiguous_legacy_completion_blocks_without_latest_wins(
    completed_project: Path,
) -> None:
    append_second_valid_completion(completed_project)
    active = project_active_evidence_from_project(completed_project)
    assert active.completion_pointer_updates == {}
    assert active.blockers["deck-1"] == [{"reason": "ambiguous_completion_evidence"}]
```

Cover exact approved plan, ordered active passed slides, record IDs/attempts,
titles/takeaways, active artifact records/CAS bytes, approval pointer binding,
single completion inference, zero/multiple completion candidates, and pointer
clearing after revision.

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest tests/test_presentation_active_evidence.py -q
```

Expected: active projection API is absent.

- [ ] **Step 3: Implement active projection**

```python
@dataclass(frozen=True)
class ActiveEvidenceProjection:
    """Current pointer updates and fail-closed blockers by deck."""
    pointer_updates: Mapping[str, Mapping[str, str | None]]
    blockers: Mapping[str, tuple[Mapping[str, Any], ...]]

def project_active_evidence(
    snapshot: EvidenceSnapshot,
    history: HistoricalProjection,
) -> ActiveEvidenceProjection:
    """Validate only pointer-selected evidence against current state."""
```

Use the approved rule: history is intrinsic; pointers define current evidence.
Migration may infer one unambiguous legacy completion but never latest-wins.

- [ ] **Step 4: Run GREEN and workflow/gate regressions**

```bash
python3 -m pytest tests/test_presentation_active_evidence.py \
  tests/test_draft_review_gate.py tests/test_presentation_workflow.py \
  tests/test_presentation_gates.py -q
```

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/presentation_evidence_projection.py \
  skills/report-slides/scripts/presentation_evidence_contracts.py \
  skills/report-slides/scripts/tests/test_presentation_active_evidence.py \
  skills/report-slides/scripts/tests/test_draft_review_gate.py \
  skills/report-slides/scripts/tests/test_presentation_workflow.py
git commit -m "feat(report-slides): project current evidence pointers"
```

---

### Task 5: Schema-v2 Migration, Backup, Locks, and Exact No-op

**Files:**
- Create: `skills/report-slides/scripts/presentation_migration_v2.py`
- Create: `skills/report-slides/scripts/presentation_evidence_store.py`
- Modify: `skills/report-slides/scripts/migrate_presentation_state.py`
- Modify: `skills/report-slides/scripts/migration_scope.py`
- Modify: `skills/report-slides/scripts/presentation_transactions.py`
- Create: `skills/report-slides/scripts/tests/test_migrate_presentation_state_v2.py`
- Modify: `skills/report-slides/scripts/tests/test_migrate_presentation_state.py`

**Interfaces:**
- Consumes: snapshot, historical/active projections, CAS plans, `WorkflowTransaction`.
- Produces: `MigrationPlan`, schema-v2 evidence YAML, exact six-key report, canonical operational-lock classification.

- [ ] **Step 1: Write RED migration matrix**

```python
@pytest.mark.parametrize("source_version", [0, 1])
def test_migration_writes_v2_evidence_cas_and_pointers_atomically(
    tmp_path: Path,
    source_version: int,
) -> None:
    project = complete_legacy_project(tmp_path, source_version)
    report = migrate_state(project, dry_run=False)
    assert report["source_schema_version"] == source_version
    assert report["target_schema_version"] == 2
    assert load_yaml(project / ".research/presentations/state/evidence.yaml")["version"] == 2


def test_v2_noop_creates_nothing_and_preserves_bytes_modes_mtimes(v2_project: Path) -> None:
    before = exact_tree_snapshot(v2_project)
    report = migrate_state(v2_project, dry_run=False)
    assert report["changed_paths"] == []
    assert exact_tree_snapshot(v2_project) == before
```

Add dry-run zero writes, mixed/future/bool versions, canonical orphan locks,
unsafe locks, every commit position, backup no-overwrite, CAS failure, ordinary
rollback, BaseException recovery, event byte identity, blockers, and deterministic
`changed_paths`.

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest tests/test_migrate_presentation_state_v2.py -q
```

Expected: target version remains 1 and evidence/CAS outputs are missing.

- [ ] **Step 3: Implement migration plan and durable commit**

```python
@dataclass(frozen=True)
class MigrationPlan:
    """All deterministic schema-v2 replacements and report fields."""
    source_schema_version: int
    replacements: Mapping[Path, bytes]
    cas_objects: Mapping[Path, bytes]
    migrated_ids: tuple[str, ...]
    blocked_ids: tuple[str, ...]
    blockers: Mapping[str, tuple[Mapping[str, Any], ...]]

def build_migration_plan(snapshot: EvidenceSnapshot) -> MigrationPlan:
    """Build a schema-v2 conversion plan without filesystem mutation."""

def serialize_evidence_store(
    evidence: Mapping[str, Mapping[str, Any]],
) -> bytes:
    """Serialize deterministic schema-v2 evidence YAML."""
```

Update state schema constants to 2. Accept only canonical regular operational
locks, exclude them from backup and `changed_paths`, and preserve stable inode
sidecars. Acquire workflow lock before sidecars and CAS locks, then rebuild the
snapshot under lock before backup and commit.

- [ ] **Step 4: Run GREEN and all Task 8 tests**

```bash
python3 -m pytest tests/test_migrate_presentation_state_v2.py \
  tests/test_migrate_presentation_state.py \
  tests/test_migrate_presentation_state_round1.py \
  tests/test_migrate_presentation_state_round2.py \
  tests/test_migrate_presentation_state_round3.py \
  tests/test_task8_fix_round4.py tests/test_task8_fix_round5.py \
  tests/test_task8_fix_round6.py tests/test_presentation_transactions.py -q
```

Update older assertions only where the approved target changed from 1 to 2 or
the canonical-lock policy intentionally changed. Do not weaken safety assertions.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/presentation_migration_v2.py \
  skills/report-slides/scripts/presentation_evidence_store.py \
  skills/report-slides/scripts/migrate_presentation_state.py \
  skills/report-slides/scripts/migration_scope.py \
  skills/report-slides/scripts/presentation_transactions.py \
  skills/report-slides/scripts/tests/test_migrate_presentation_state_v2.py \
  skills/report-slides/scripts/tests/test_migrate_presentation_state.py
git commit -m "feat(report-slides): migrate presentation evidence to v2"
```

---

### Task 6: Producer Cutover and Migration-required Guard

**Files:**
- Modify: `skills/report-slides/scripts/presentation_evidence_store.py`
- Modify: `skills/report-slides/scripts/presentation_workflow.py`
- Modify: `skills/report-slides/scripts/presentation_events.py`
- Modify: `skills/report-slides/scripts/presentation_state.py`
- Create: `skills/report-slides/scripts/tests/test_presentation_evidence_workflow.py`
- Modify: `skills/report-slides/scripts/tests/test_presentation_workflow.py`
- Modify: `skills/report-slides/scripts/tests/test_presentation_state.py`

**Interfaces:**
- Consumes: v2 contracts, CAS objects, evidence serialization, transaction staging.
- Produces: `MigrationRequiredError`, `stage_evidence_transition()`, atomic v2 preview/approval/completion producers.

- [ ] **Step 1: Write RED producer and version-guard tests**

```python
@pytest.mark.parametrize("version", [0, 1])
def test_workflow_requires_migration_before_authorized_action(
    project_with_version: Path,
    version: int,
) -> None:
    set_schema_version(project_with_version, version)
    with pytest.raises(MigrationRequiredError) as error:
        register_draft_preview(project_with_version, canonical_preview())
    assert error.value.target_schema_version == 2


def test_register_preview_atomically_writes_event_envelope_cas_and_pointer(
    v2_project: Path,
) -> None:
    result = register_draft_preview(v2_project, canonical_preview())
    assert result["evidence_id"] == load_deck(v2_project)["draft_preview_evidence_id"]
    assert envelope_for(v2_project, result["evidence_id"])["source_event_id"] == result["id"]
```

Cover preview, draft approval, completion, failure at every replacement, crash
recovery, revision pointer clearing, and no event/envelope/pointer orphan.

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest tests/test_presentation_evidence_workflow.py -q
```

- [ ] **Step 3: Implement atomic evidence transitions**

```python
class MigrationRequiredError(RuntimeError):
    """Raised when a workflow action requires schema-v2 state."""

def stage_evidence_transition(
    transaction: WorkflowTransaction,
    snapshot: EvidenceSnapshot,
    *,
    event: Mapping[str, Any],
    envelope: Mapping[str, Any],
    cas_objects: Mapping[str, CasObject],
    pointer_field: str,
) -> None:
    """Stage event, envelope, CAS, and deck pointer in one transaction."""
```

Apply the schema guard before sidecar creation in low- and high-level workflow
entrypoints. Preserve structured CLI translation for migration-required errors.

- [ ] **Step 4: Run GREEN and workflow compatibility**

```bash
python3 -m pytest tests/test_presentation_evidence_workflow.py \
  tests/test_presentation_workflow.py tests/test_presentation_state.py \
  tests/test_presentation_events.py tests/test_review_retry_workflow.py -q
```

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/presentation_evidence_store.py \
  skills/report-slides/scripts/presentation_workflow.py \
  skills/report-slides/scripts/presentation_events.py \
  skills/report-slides/scripts/presentation_state.py \
  skills/report-slides/scripts/tests/test_presentation_evidence_workflow.py \
  skills/report-slides/scripts/tests/test_presentation_workflow.py \
  skills/report-slides/scripts/tests/test_presentation_state.py
git commit -m "feat(report-slides): emit evidence v2 atomically"
```

---

### Task 7: Gate Cutover to Evidence Pointers and CAS

**Files:**
- Modify: `skills/report-slides/scripts/presentation_gates.py`
- Modify: `skills/report-slides/scripts/render_plan_preview.py`
- Modify: `skills/report-slides/scripts/publish_presentation_artifact.py`
- Create: `skills/report-slides/scripts/tests/test_presentation_evidence_gates.py`
- Modify: `skills/report-slides/scripts/tests/test_presentation_gates.py`
- Modify: `skills/report-slides/scripts/tests/test_draft_review_gate.py`
- Modify: `skills/report-slides/scripts/tests/test_publish_presentation_artifact.py`

**Interfaces:**
- Consumes: `EvidenceSnapshot`, `project_active_evidence()`, verified CAS refs.
- Produces: current preview/approval/completion predicates with no legacy fallback.

- [ ] **Step 1: Write RED gate tests**

```python
def test_gate_does_not_fall_back_to_legacy_preview_event(v2_project: Path) -> None:
    append_valid_legacy_preview_event(v2_project)
    clear_pointer(v2_project, "draft_preview_evidence_id")
    with pytest.raises(DraftGateError) as error:
        assert_draft_approvable(v2_project, "deck-1", canonical_decision())
    assert error.value.blockers == [{"reason": "draft_preview_evidence_pointer_required"}]


def test_completion_gate_rejects_tampered_cas_bytes(v2_project: Path) -> None:
    tamper_current_completion_cas(v2_project)
    with pytest.raises(CompletionGateError, match="artifact_digest_mismatch"):
        assert_deck_completable(v2_project, "deck-1")
```

Cover wrong-kind/cross-deck pointers, unavailable history, stale plan/slide,
metadata drift, approval mismatch, completion ambiguity, CAS deletion/tamper,
and first/middle/final artifact mismatches.

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest tests/test_presentation_evidence_gates.py -q
```

- [ ] **Step 3: Replace legacy event fallback with active projection**

Gate entrypoints load one snapshot, validate pointer-selected envelopes, verify
CAS bytes, and return the existing exact four-key structured CLI errors. Delete
legacy fallback branches rather than keeping dual authorization paths.

```python
def assert_current_evidence(
    project_root: Path,
    deck_id: str,
    evidence_kind: str,
) -> dict[str, Any]:
    """Return one current verified envelope or raise its named gate error."""
```

Update publishers to bind created artifacts to v2 CAS/evidence context without
making pure renderers stateful.

- [ ] **Step 4: Run GREEN and publication regressions**

```bash
python3 -m pytest tests/test_presentation_evidence_gates.py \
  tests/test_presentation_gates.py tests/test_draft_review_gate.py \
  tests/test_publish_presentation_artifact.py \
  tests/test_publish_presentation_artifact_failures.py \
  tests/test_artifact_entrypoint_gates.py -q
```

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/presentation_gates.py \
  skills/report-slides/scripts/render_plan_preview.py \
  skills/report-slides/scripts/publish_presentation_artifact.py \
  skills/report-slides/scripts/tests/test_presentation_evidence_gates.py \
  skills/report-slides/scripts/tests/test_presentation_gates.py \
  skills/report-slides/scripts/tests/test_draft_review_gate.py \
  skills/report-slides/scripts/tests/test_publish_presentation_artifact.py
git commit -m "feat(report-slides): gate on evidence v2 and CAS"
```

---

### Task 8: End-to-end Acceptance and Documentation Cutover

**Files:**
- Create: `skills/report-slides/scripts/tests/test_evidence_v2_acceptance.py`
- Modify: `skills/report-slides/SKILL.md`
- Modify: `docs/superpowers/plans/2026-08-08-report-slides-enforcement-remediation.md`
- Modify: `.superpowers/sdd/2026-08-08-report-slides-enforcement-remediation/progress.md` (ignored report only; do not force-add)

**Interfaces:**
- Consumes: completed schema-v2 migration, producers, gates, transactions, and CLIs.
- Produces: one black-box acceptance suite and user-facing migration workflow.

- [ ] **Step 1: Write black-box RED acceptance tests**

```python
def test_schema1_project_migrates_then_completes_only_through_v2(tmp_path: Path) -> None:
    project = build_schema1_approved_project(tmp_path)
    assert workflow_cli(project, "complete-deck").json["error"] == "MigrationRequiredError"
    assert migration_cli(project).json["target_schema_version"] == 2
    produce_review_approve_and_complete(project)
    assert load_deck(project)["status"] == "completed"
    assert_current_evidence_and_cas_are_complete(project)


def test_revision_preserves_history_and_invalidates_current_pointers(tmp_path: Path) -> None:
    project = build_completed_v2_project(tmp_path)
    old_ids = current_pointer_ids(project)
    request_slide_revision(project)
    assert historical_envelopes_exist(project, old_ids)
    assert current_pointer_ids(project) == {"preview": None, "approval": None, "completion": None}
```

Include subprocess CLI exact JSON, dry-run zero writes, wet migration durability,
second-run no-op, revision/retry, missing historical bytes, active CAS tamper,
canonical locks, and crash recovery.

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest tests/test_evidence_v2_acceptance.py -q
```

Expected: any remaining integration or documentation contract gap fails.

- [ ] **Step 3: Update documentation and close integration gaps**

Document this exact operator flow in `SKILL.md`:

```text
inspect schema -> migrate-state --dry-run -> migrate-state -> workflow action
```

Document that schema 0/1 workflow actions fail with `MigrationRequiredError`,
schema 2 gates use only evidence pointers/CAS, operational locks are ignored as
evidence, and historical unavailable evidence cannot authorize current work.
Keep the original remediation plan as historical context and link the approved
schema-v2 spec and this implementation plan from its Task 8 section.

- [ ] **Step 4: Run full verification once from the scripts directory**

```bash
cd skills/report-slides/scripts
python3 -m pytest tests/test_evidence_v2_acceptance.py -q
python3 -m pytest tests svg_to_pptx/tests -q
ruff check presentation_evidence_contracts.py presentation_evidence_cas.py \
  presentation_evidence_snapshot.py presentation_evidence_projection.py \
  presentation_evidence_store.py presentation_migration_v2.py \
  migrate_presentation_state.py migration_scope.py presentation_transactions.py \
  presentation_workflow.py presentation_events.py presentation_state.py \
  presentation_gates.py render_plan_preview.py publish_presentation_artifact.py \
  tests/test_evidence_v2_acceptance.py
python3 -m compileall -q .
git diff --check
```

Also verify all touched source and test files are under 1000 lines, the worktree
contains no generated pollution, and a schema-v2 no-op preserves exact bytes,
modes, and mtimes.

- [ ] **Step 5: Commit**

```bash
git add skills/report-slides/scripts/tests/test_evidence_v2_acceptance.py \
  skills/report-slides/SKILL.md \
  docs/superpowers/plans/2026-08-08-report-slides-enforcement-remediation.md
git commit -m "test(report-slides): verify evidence v2 workflow"
```

---

## Per-task Review Gate

After each task:

1. The implementer records RED, GREEN, focused/full compatibility as required,
   static checks, line counts, commit hash, and concerns in the SDD task report.
2. A different Sol xhigh reviewer performs read-only spec and quality review.
3. Critical or Important findings return to a fresh Sol xhigh implementer with
   strict RED before fixes.
4. Do not begin the next task until the current task has no Critical or Important
   findings.
5. Minor findings are recorded in the ledger and deferred only when they do not
   weaken the evidence or transaction contract.

## Final Completion Gate

Task 8 schema-v2 rollout is complete only when:

- all eight tasks have accepted commits;
- the exact full report-slides suite passes on the final commit;
- schema 0/1 migration and schema 2 exact no-op acceptance pass;
- no touched file exceeds 999 lines;
- Ruff, compileall, import-cycle, and diff checks pass;
- the linked worktree is clean;
- an independent Sol xhigh final review reports zero Critical and zero Important;
- the SDD ledger records the commit range and verification evidence.
