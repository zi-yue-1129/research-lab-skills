# Report Slides Evidence Schema v2 Design

## Status

Approved interactively on 2026-08-09. This design supersedes the Task 8
schema-v1 migration target in the report-slides enforcement remediation plan.
It does not replace the remaining remediation or Phase C plans.

## Problem

Schema v1 stores authorization evidence in mutable paths and several partially
overlapping event, gate, workflow, and migration validators. This creates four
recurring failure classes:

1. Record schemas drift between producers and migration.
2. Immutable historical evidence is incorrectly judged against current state.
3. Declared artifact digests can diverge from the bytes used for authorization.
4. Ordinary workflow lock sidecars are confused with semantic state.

Incremental special cases have not produced a stable contract. Schema v2 must
make evidence identity, temporal scope, artifact bytes, and current pointers
explicit.

## Goals

- Migrate schema 0 and schema 1 projects to schema 2.
- Make schema 2 reruns exact no-ops for bytes, modes, and mtimes.
- Store authorization evidence in immutable, versioned envelopes.
- Store authoritative artifact bytes in a content-addressed store (CAS).
- Separate historical integrity from current gate validity.
- Give decks explicit pointers to current preview, approval, and completion
  evidence.
- Use shared pure contract validators across producers, gates, and migration.
- Preserve historical audit event shards byte-for-byte.
- Fail closed without inventing plans, reviews, approvals, artifacts, attempts,
  identities, timestamps, or evidence.

## Non-goals

- Rewriting or deleting existing immutable JSONL history.
- Silently repairing unverifiable active evidence.
- Maintaining a permanent schema-v1 authorization fallback.
- Introducing remote artifact storage or garbage collection.
- Retrofitting unrelated report-slides state or renderer behavior.

## Chosen Architecture

### Shared contract kernel

A pure contract layer is the single authority for:

- store records by record kind and lifecycle;
- evidence envelopes by evidence kind;
- intrinsic historical validation;
- active evidence projection;
- canonical operational-entry classification;
- canonical hashing and content-addressed references.

The kernel accepts an immutable parsed snapshot and explicit context. It does
not load mutable live files. Producers, gates, and migration call the same
kernel so that accepted output and accepted migrated input cannot drift.

Migration follows this flow:

```text
scope classification
  -> no-follow immutable snapshot
  -> store-record validation
  -> intrinsic historical validation
  -> active evidence projection
  -> conversion plan
  -> durable migration or dry-run report
```

### Schema versions

The migration supports exactly:

- schema 0 to schema 2;
- schema 1 to schema 2;
- schema 2 to schema 2 as an exact no-op.

Mixed, boolean, negative, malformed, or future versions fail closed. Schema 1
is not a final target after this design is implemented.

## Evidence Store

Schema v2 adds `.research/presentations/state/evidence.yaml`. It contains an
`evidence` mapping keyed by immutable evidence ID. Every envelope has exact
typed fields:

- `id`;
- `schema_version: 2`;
- `evidence_kind`;
- `deck_id`;
- `plan_id`;
- `plan_version`;
- `plan_sha256`;
- `subject_ids`;
- `producer_id`;
- `artifact_refs`;
- `source_event_id`;
- `created_at` as RFC3339;
- `availability`, either `available` or `historical_unavailable`;
- `evidence_sha256`, computed over the canonical envelope payload excluding
  `evidence_sha256` itself.

Kind-specific payloads refine this base schema. Unknown fields, kinds, aliases,
or boolean-as-integer values fail closed unless explicitly documented by a
versioned contract.

### Current deck pointers

Schema v2 deck records use:

- `draft_preview_evidence_id`;
- `draft_approval_evidence_id`;
- `completion_evidence_id`.

The pointers must resolve to envelopes owned by the same deck and appropriate
kind. Non-current historical envelopes remain in the evidence store without a
deck pointer.

For legacy completed decks, migration binds `completion_evidence_id` only when
there is exactly one unambiguous, fully verifiable candidate. Zero or multiple
candidates block the deck; migration never applies a latest-event heuristic.
Non-completed decks cannot retain a current completion pointer.

## Content-addressed Artifact Store

Authoritative artifact bytes are stored at:

```text
.research/presentations/evidence/sha256/<first-two-hex>/<full-sha256>
```

Envelope artifact references contain the digest, CAS relative path, artifact
kind, subject binding, and original output path as provenance. The original
mutable path is never sufficient to authorize a gate.

Migration materializes verified existing artifacts into CAS:

- read with no-follow descriptors;
- require regular files;
- recompute SHA-256 from bytes;
- write sibling temporary files;
- verify complete writes and final digest;
- fsync file and containing directories;
- publish atomically;
- deduplicate identical bytes.

If an object already exists, its bytes must match its path digest. A mismatch
fails closed.

## Temporal Evidence Semantics

### Historical preview and completion

Historical `draft_preview` and `deck_completion` events receive intrinsic
validation only. Intrinsic validation checks exact event shape, canonical event
digest, internal identities, ordered metadata, artifact declaration and binding
consistency, and original provenance. It does not compare the event with the
current active plan or slides.

When original historical artifact bytes are unavailable, migration preserves
the event and creates an envelope with `availability:
historical_unavailable`. It does not fabricate bytes or CAS objects. Such an
envelope cannot be used by a current gate.

### Active preview

Only `deck.draft_preview_evidence_id` designates the active preview. It must
match:

- the exact current approved plan ID, version, and canonical digest;
- the exact ordered set of active, non-superseded, passed slides;
- current slide record IDs and attempts;
- approved plan titles and takeaways;
- persisted artifact records;
- available CAS objects whose bytes match every declared digest.

### Active approval

Only `deck.draft_approval_evidence_id` designates the active draft decision. It
must bind the active preview evidence ID and digest, carry valid explicit
identity and decision metadata, and satisfy the existing interactive or
explicit-noninteractive approval rules.

### Active completion

Only `deck.completion_evidence_id` designates active completion. It must bind
the current approval, required visual-review evidence, final PPTX, authoritative
rendered PNG set, persisted artifact records, and available CAS objects.

Revision clears all affected current evidence pointers atomically. Historical
envelopes and event shards remain intact but cannot satisfy current gates.

## Module Record Contract

The shared module validator defines a base record and a targeted-replacement
refinement rather than migration-owned whole-record whitelists.

A targeted replacement must preserve the source module identity relationships,
use `status: planned`, use `revision_kind: module_retry`, increment the attempt,
bind the exact revision request, and reset assignment and artifact-manifest
paths to null.

Spec digest compatibility is an explicit alias group:

- new producers emit `visual_spec_sha256`;
- legacy data may contain only `spec_sha256`;
- both are accepted only when their values are identical;
- conflicting aliases fail closed;
- a non-null visual spec path requires a valid digest alias matching the
  referenced contract;
- migration preserves accepted legacy aliases and does not silently rewrite or
  delete them.

Nullability depends on the authoritative store, record kind, lifecycle, and
relation to the source record. Field-name or key-subset inference is forbidden.

## Event-kind Registry

Artifact evidence is legal only for registered event kinds.

### Draft preview

- Exact artifact set: ordered rendered slides plus contact sheet.
- Exact rendered-slide and contact-sheet bindings.
- Intrinsic or active validation according to pointer reachability.

### Deck completion

- Exact artifact set derives from the referenced visual-review record: final
  PPTX plus all authoritative rendered PNGs.
- Every digest is checked against CAS bytes.
- Exactly one persisted artifact record must match each required path, deck,
  kind, and digest.
- Preview-style `artifact_bindings` are rejected unless a future versioned
  completion schema defines them.

Other event kinds cannot carry artifact maps unless registered by their own
versioned contract.

## Producer and Gate Cutover

New workflow actions atomically append their audit event, write a schema-v2
envelope, materialize or reference CAS objects, and update the deck pointer.

Gates trust only schema-v2 evidence pointers and CAS bytes. They never fall back
to old events when v2 evidence is missing. Schema 0 or 1 workflow operations
return a structured `MigrationRequiredError`; migration is the only supported
conversion entrypoint.

## Operational Lock Policy

Locks are operational entries, not evidence. Migration accepts only direct,
regular, non-symlink files at:

- `state/workflow.lock`;
- `state/<known-store>.yaml.lock`;
- `events/<valid-calendar-date>.jsonl.lock`.

Canonical store or shard locks may exist without their data file because normal
pre-write and failed operations preserve stable lock inodes. Lock contents and
modes have no semantic meaning.

Migration rejects unknown names or locations, nested lock directories,
temporary files, invalid event dates, symlinks, FIFOs, devices, sockets, and
other special entries. Operational locks are excluded from semantic parsing,
backups, CAS, and `changed_paths`.

## Transactions and Failure Handling

Dry-run builds the same immutable snapshot and conversion plan but creates no
locks, directories, sidecars, journals, backups, CAS objects, or mtimes.

Wet migration acquires locks in this order:

```text
workflow.lock
  -> state store sidecars
  -> event shard sidecars
  -> CAS shard locks
```

It then re-discovers and revalidates scope. Backups come from locked preimages.
The evidence store, deck pointers, CAS objects, and schema-version updates
commit in one durable transaction.

Ordinary failures restore exact bytes, modes, mtimes, and absence. BaseException
paths leave a durable recovery journal; the next wet migration recovers before
analysis. A successful rerun at schema 2 is an exact no-op.

Unverifiable active evidence blocks its deck. Historical unavailable evidence
does not fail migration. Invalid input fails before backup or mutation.

## Migration Report

The public report retains the existing exact six-key contract:

- `source_schema_version`;
- `target_schema_version`;
- `migrated_ids`;
- `blocked_ids`;
- `blockers`;
- `changed_paths`.

`target_schema_version` is `2`. CAS objects, evidence store changes, schema
stores, and backup root appear in deterministic project-relative
`changed_paths` only when they are created or changed. Operational locks are
excluded.

## Acceptance Matrix

### Schema and no-op

- 0 to 2 and 1 to 2 migrations succeed for verifiable fixtures.
- 2 to 2 is byte-, mode-, and mtime-identical and creates no filesystem entry.
- Mixed, future, boolean, negative, or malformed versions fail without writes.

### Records

- Fresh modules and real workflow-produced targeted replacements validate.
- Canonical and legacy spec digest aliases validate; conflicting aliases fail.
- Assignment records cannot spoof module nullability.
- Mixed identities and unknown path-bearing fields fail before writes.

### Temporal evidence

- Historical previews and completions survive revision.
- Missing historical bytes produce `historical_unavailable` envelopes.
- Historical envelopes never authorize current gates.
- Active preview requires exact plan, ordered active passed slides, metadata,
  attempts, artifact records, CAS objects, and bytes.
- Active completion requires current approval and exact authoritative outputs.
- Missing, extra, duplicate, stale, non-passed, drifted, or ambiguous evidence
  blocks without fabrication.

### CAS and artifact integrity

- Identical bytes deduplicate.
- First, middle, and final artifact mutations are detected with the exact path.
- Existing CAS digest mismatch, missing source, symlink, FIFO, short write,
  replace failure, and fsync failure all fail closed.
- Rollback and crash recovery preserve exact bytes, modes, mtimes, and absence.

### Producers and gates

- New actions atomically write event, envelope, CAS, and pointer.
- Schema 0 and 1 actions return structured migration-required errors.
- Gates never fall back to legacy events.
- Revision atomically clears current pointers while retaining history.

### Scope and locks

- Real workflow-created locks and canonical orphan regular locks are accepted.
- Unknown, nested, temporary, invalid-date, symlink, and special entries fail.

### Verification

- Focused migration, evidence, CAS, producer, gate, and transaction suites pass.
- The full `tests svg_to_pptx/tests` suite passes.
- Ruff, compileall, import-cycle checks, and `git diff --check` pass.
- An independent Sol xhigh reviewer reports no Critical or Important findings.

## Rollout Boundary

This design replaces the remaining Task 8 implementation approach. Task 9 and
later remediation tasks remain blocked until schema-v2 migration, producer
cutover, gates, transactions, and independent review are complete.
