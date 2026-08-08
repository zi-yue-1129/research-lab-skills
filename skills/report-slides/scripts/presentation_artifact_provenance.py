"""Canonical artifact provenance validation and publisher derivation helpers.

The event writer and guarded publisher share this module so artifact records
cannot drift from the evidence fields consumed by the draft-review gate.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from presentation_contracts import contract_sha256, load_contract


SLIDE_PNG_KIND = "slide-png"
REVIEW_SHEET_KIND = "review-sheet"
MODULE_ARTIFACT_KINDS = frozenset({"module-svg", "module-png", "module-pptx"})
SLIDE_ARTIFACT_KINDS = frozenset(
    {"slide-svg", "slide-png", "slide-pptx", "deck-pptx", REVIEW_SHEET_KIND}
)
SUPPORTED_ARTIFACT_KINDS = MODULE_ARTIFACT_KINDS | SLIDE_ARTIFACT_KINDS
GENERIC_ARTIFACT_KINDS = frozenset({"completion"})
_SHA256_LENGTH = 64


def mapping_key_blockers(value: Any, location: str = "document") -> list[dict[str, Any]]:
    """Return structured blockers for every non-string mapping key.

    Args:
        value: Candidate recursively nested contract value.
        location: Human-readable root path used in blocker details.

    Returns:
        Blockers in traversal order, never requiring key comparison or sorting.
    """
    blockers: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                blockers.append({
                    "reason": "mapping keys must be strings",
                    "path": location,
                    "key": repr(key),
                })
            child_location = f"{location}.{key!s}"
            blockers.extend(mapping_key_blockers(nested, child_location))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            blockers.extend(mapping_key_blockers(nested, f"{location}[{index}]"))
    return blockers


def validate_artifact_subject(
    artifact_kind: Any,
    slide_id: Any,
    module_id: Any,
    *,
    reject_unknown: bool = False,
) -> None:
    """Validate supported artifact kind and exact subject cardinality.

    Args:
        artifact_kind: Supported artifact kind.
        slide_id: Optional owning slide record identifier.
        module_id: Optional owning module record identifier.
        reject_unknown: Whether unknown non-publishing evidence kinds are
            rejected instead of accepted as untyped records.

    Raises:
        ValueError: If kind is unsupported or required/forbidden subjects are
            malformed for that kind.
    """
    if not isinstance(artifact_kind, str) or (
        reject_unknown and artifact_kind not in SUPPORTED_ARTIFACT_KINDS
    ) or (
        not reject_unknown
        and artifact_kind not in SUPPORTED_ARTIFACT_KINDS | GENERIC_ARTIFACT_KINDS
    ):
        raise ValueError(f"unsupported_artifact_kind: {artifact_kind!r}")
    if artifact_kind not in SUPPORTED_ARTIFACT_KINDS:
        return

    def _nonempty_identifier(value: Any, field: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field}_subject_required")

    if artifact_kind in MODULE_ARTIFACT_KINDS:
        _nonempty_identifier(module_id, "module")
        if slide_id is not None and (
            not isinstance(slide_id, str) or not slide_id.strip()
        ):
            raise ValueError("slide_id_subject_invalid")
        return
    if module_id is not None:
        raise ValueError(f"{artifact_kind} forbids module_id subject")
    if artifact_kind == REVIEW_SHEET_KIND:
        if slide_id is not None:
            raise ValueError("review-sheet forbids slide_id subject")
        return
    _nonempty_identifier(slide_id, "slide")


def canonical_source_digest(paths: Sequence[str], digests: Sequence[str]) -> str:
    """Return the digest for an ordered source path/digest sequence.

    Args:
        paths: Canonical project-relative source paths in source order.
        digests: SHA-256 digests corresponding one-for-one to ``paths``.

    Returns:
        Canonical SHA-256 digest of the ordered source binding.

    Raises:
        ValueError: If the sequences are empty, different lengths, duplicated,
            or contain malformed paths/digests.
    """
    if not paths or len(paths) != len(digests):
        raise ValueError("source_paths and source digests must be non-empty and equal length")
    normalized_paths: list[str] = []
    for value in paths:
        if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
            raise ValueError("source_paths must contain canonical project-relative paths")
        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("source_paths must contain canonical project-relative paths")
        normalized_paths.append(value)
    if len(set(normalized_paths)) != len(normalized_paths):
        raise ValueError("source_paths must not contain duplicates")
    normalized_digests: list[str] = []
    for digest in digests:
        if not _is_sha256(digest):
            raise ValueError("source digests must be lowercase SHA-256 values")
        normalized_digests.append(digest)
    return contract_sha256({"paths": normalized_paths, "digests": normalized_digests})


def _is_sha256(value: Any) -> bool:
    """Return whether ``value`` is a lowercase hexadecimal SHA-256 digest."""
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_positive_int(value: Any, field: str) -> int:
    """Validate one positive integer while rejecting booleans."""
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _require_digest(value: Any, field: str) -> str:
    """Validate one canonical digest field."""
    if not _is_sha256(value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _require_nonempty_text(value: Any, field: str) -> str:
    """Validate one trimmed non-empty provenance identifier."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a trimmed non-empty string")
    return value


def validate_artifact_provenance(
    artifact_kind: str,
    *,
    deck_id: str,
    slide_id: str | None,
    module_id: str | None,
    plan_version: int | None = None,
    plan_sha256: str | None = None,
    slide_record_id: str | None = None,
    attempt: int | None = None,
    source_paths: Sequence[str] | None = None,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate and normalize canonical kind-specific provenance fields.

    Args:
        artifact_kind: Persisted artifact kind.
        deck_id: Owning deck identifier.
        slide_id: Generated slide identifier, when applicable.
        module_id: Generated visual-module identifier, when applicable.
        plan_version: Positive approved plan version for typed artifacts.
        plan_sha256: Approved plan digest for typed artifacts.
        slide_record_id: Current generated slide record identifier.
        attempt: Current generated slide attempt number.
        source_paths: Ordered source artifact paths for a review sheet.
        source_sha256: Canonical ordered source digest for a review sheet.

    Returns:
        A mapping containing only canonical fields supplied for this kind.

    Raises:
        ValueError: If a required field is missing, a value has the wrong
            type, or a field forbidden for the artifact kind is supplied.
    """
    _require_nonempty_text(deck_id, "deck_id")
    if not isinstance(artifact_kind, str) or not artifact_kind.strip():
        raise ValueError("artifact_kind is required")
    if artifact_kind == REVIEW_SHEET_KIND and (slide_id is not None or module_id is not None):
        raise ValueError("review-sheet provenance forbids slide_id/module_id")
    if artifact_kind == SLIDE_PNG_KIND and module_id is not None:
        raise ValueError("slide-png provenance forbids module_id")
    if plan_version is not None:
        _require_positive_int(plan_version, "plan_version")
    if plan_sha256 is not None:
        _require_digest(plan_sha256, "plan_sha256")
    if (plan_version is None) != (plan_sha256 is None):
        raise ValueError("plan_version and plan_sha256 must be supplied together")
    if slide_record_id is not None:
        _require_nonempty_text(slide_record_id, "slide_record_id")
    if attempt is not None:
        _require_positive_int(attempt, "attempt")
    if source_paths is not None:
        normalized_source_paths = list(source_paths)
        canonical_source_digest(normalized_source_paths, ["0" * 64] * len(normalized_source_paths))
    else:
        normalized_source_paths = None
    if source_sha256 is not None:
        _require_digest(source_sha256, "source_sha256")

    if artifact_kind not in {SLIDE_PNG_KIND, REVIEW_SHEET_KIND}:
        return {
            key: value
            for key, value in (
                ("plan_version", plan_version),
                ("plan_sha256", plan_sha256),
                ("slide_record_id", slide_record_id),
                ("attempt", attempt),
                ("source_paths", normalized_source_paths),
                ("source_sha256", source_sha256),
            )
            if value is not None
        }

    if plan_version is None or plan_sha256 is None:
        raise ValueError(f"{artifact_kind} provenance requires plan_version and plan_sha256")
    if artifact_kind == SLIDE_PNG_KIND:
        if not isinstance(slide_id, str) or not slide_id.strip():
            raise ValueError("slide-png provenance requires slide_id")
        if module_id is not None:
            raise ValueError("slide-png provenance forbids module_id")
        if source_paths is not None or source_sha256 is not None:
            raise ValueError("slide-png provenance forbids source_paths/source_sha256")
        if not isinstance(slide_record_id, str) or not slide_record_id.strip():
            raise ValueError("slide-png provenance requires slide_record_id")
        _require_positive_int(attempt, "attempt")
        return {
            "plan_version": plan_version,
            "plan_sha256": plan_sha256,
            "slide_record_id": slide_record_id,
            "attempt": attempt,
        }

    if slide_id is not None or module_id is not None:
        raise ValueError("review-sheet provenance forbids slide_id/module_id")
    if slide_record_id is not None or attempt is not None:
        raise ValueError("review-sheet provenance forbids slide_record_id/attempt")
    if source_paths is None or source_sha256 is None:
        raise ValueError("review-sheet provenance requires source_paths/source_sha256")
    normalized_paths = list(source_paths)
    return {
        "plan_version": plan_version,
        "plan_sha256": plan_sha256,
        "source_paths": normalized_paths,
        "source_sha256": source_sha256,
    }


def derive_published_provenance(
    project_root: Path,
    deck_id: str,
    artifact_kind: str,
    slide_id: str | None,
) -> dict[str, Any]:
    """Derive typed provenance from the persisted current deck evidence.

    Args:
        project_root: Project root containing presentation state.
        deck_id: Deck owning the artifact.
        artifact_kind: Publisher artifact kind.
        slide_id: Generated slide identifier for slide PNGs.

    Returns:
        Canonical provenance fields ready for the artifact record.

    Raises:
        ValueError: If current plan, slide records, or ordered source PNG
            records are missing, stale, duplicate, or inconsistent.
    """
    if artifact_kind not in {SLIDE_PNG_KIND, REVIEW_SHEET_KIND}:
        return {}
    from presentation_events import canonical_relative_path, load_artifacts, load_plans
    from presentation_state import load_decks, load_slides

    decks = load_decks(project_root)
    deck = decks.get(deck_id)
    if not isinstance(deck, Mapping):
        raise ValueError(f"unknown deck_id: {deck_id}")
    plan_version = deck.get("approved_plan_version")
    _require_positive_int(plan_version, "approved_plan_version")
    plan_sha256 = deck.get("approved_plan_sha256")
    _require_digest(plan_sha256, "approved_plan_sha256")
    plan_id = deck.get("current_plan_id")
    plans = load_plans(project_root)
    plan_record = plans.get(plan_id) if isinstance(plan_id, str) else None
    if not isinstance(plan_record, Mapping):
        raise ValueError("current approved plan record is required")
    if type(plan_record.get("version")) is not int or plan_record.get("version") != plan_version:
        raise ValueError("current approved plan version mismatch")
    raw_plan_path = plan_record.get("plan_path")
    if not isinstance(raw_plan_path, str):
        raise ValueError("current approved plan path is required")
    plan_path = (project_root / canonical_relative_path(raw_plan_path)).resolve()
    if not plan_path.is_file():
        raise ValueError("current approved plan file is missing")
    plan = load_contract(plan_path)
    if not isinstance(plan, Mapping) or plan.get("deck_id") != deck_id:
        raise ValueError("current approved plan identity mismatch")
    if type(plan.get("plan_version")) is not int or plan.get("plan_version") != plan_version:
        raise ValueError("current approved plan version mismatch")
    if contract_sha256(plan) != plan_sha256:
        raise ValueError("current approved plan digest mismatch")

    slides = load_slides(project_root)
    current_slides = [
        record for record in slides.values()
        if record.get("deck_id") == deck_id and record.get("status") != "superseded"
    ]
    by_plan_id: dict[str, Mapping[str, Any]] = {}
    for record in current_slides:
        plan_slide_id = record.get("plan_slide_id")
        if not isinstance(plan_slide_id, str) or plan_slide_id in by_plan_id:
            raise ValueError("current slide records are missing or ambiguous")
        by_plan_id[plan_slide_id] = record
    plan_slides = plan.get("slides") if isinstance(plan.get("slides"), list) else []
    ordered_ids = [slide.get("slide_id") for slide in plan_slides if isinstance(slide, Mapping)]
    if len(ordered_ids) != len(by_plan_id) or any(slide_id not in by_plan_id for slide_id in ordered_ids):
        raise ValueError("current slide set does not match approved plan")

    if artifact_kind == SLIDE_PNG_KIND:
        if not isinstance(slide_id, str) or slide_id not in slides:
            raise ValueError("current slide record is required")
        slide = slides[slide_id]
        if slide.get("deck_id") != deck_id or slide.get("status") == "superseded":
            raise ValueError("current slide record is stale")
        attempt = _require_positive_int(slide.get("attempt"), "attempt")
        return validate_artifact_provenance(
            artifact_kind,
            deck_id=deck_id,
            slide_id=slide_id,
            module_id=None,
            plan_version=plan_version,
            plan_sha256=plan_sha256,
            slide_record_id=slide.get("id"),
            attempt=attempt,
        )

    artifacts = load_artifacts(project_root)
    paths: list[str] = []
    digests: list[str] = []
    for plan_slide_id in ordered_ids:
        current = by_plan_id[plan_slide_id]
        record_id = current.get("id")
        attempt = _require_positive_int(current.get("attempt"), "attempt")
        candidates = [
            artifact for artifact in artifacts.values()
            if artifact.get("deck_id") == deck_id
            and artifact.get("artifact_kind") == SLIDE_PNG_KIND
            and artifact.get("slide_id") == record_id
        ]
        for candidate in candidates:
            _require_positive_int(candidate.get("attempt"), "slide-png attempt")
        matches = [
            artifact for artifact in candidates
            if artifact.get("slide_record_id") == record_id
            and artifact.get("attempt") == attempt
        ]
        if len(matches) != 1:
            raise ValueError("each current slide requires exactly one current slide-png artifact")
        artifact = matches[0]
        raw_path = artifact.get("path")
        digest = artifact.get("sha256")
        if not isinstance(raw_path, str) or not isinstance(digest, str):
            raise ValueError("current slide-png provenance is incomplete")
        artifact_plan_version = artifact.get("plan_version")
        if type(artifact_plan_version) is not int or artifact_plan_version != plan_version:
            raise ValueError("current slide-png plan version mismatch")
        if artifact.get("plan_sha256") != plan_sha256:
            raise ValueError("current slide-png plan digest mismatch")
        producer_id = artifact.get("producer_id")
        if not isinstance(producer_id, str) or not producer_id.strip():
            raise ValueError("current slide-png producer identity is required")
        relative = canonical_relative_path(raw_path)
        candidate = (project_root / relative).resolve(strict=False)
        root = project_root.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("current slide-png path escapes project root") from exc
        source_path = project_root / relative
        if source_path.is_symlink() or not source_path.is_file():
            raise ValueError("current slide-png source file is missing or unsafe")
        actual_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        expected_digest = _require_digest(digest, "slide-png sha256")
        if actual_digest != expected_digest:
            raise ValueError("current slide-png source digest mismatch")
        paths.append(relative)
        digests.append(expected_digest)
    source_sha256 = canonical_source_digest(paths, digests)
    return validate_artifact_provenance(
        artifact_kind,
        deck_id=deck_id,
        slide_id=None,
        module_id=None,
        plan_version=plan_version,
        plan_sha256=plan_sha256,
        source_paths=paths,
        source_sha256=source_sha256,
    )


def validate_review_sheet_contract(
    project_root: Path,
    deck_id: str,
    contract: Any,
    contract_path: Path,
) -> dict[str, Any]:
    """Validate the exact current approved plan used by a review sheet.

    Args:
        project_root: Project root containing durable state.
        deck_id: Deck owning the review sheet.
        contract: Parsed Deck Plan contract.
        contract_path: Caller path for the plan contract.

    Returns:
        Canonical plan binding fields for the published artifact.

    Raises:
        ValueError: If the plan path, version, identity, or digest is stale.
    """
    from presentation_events import canonical_relative_path, load_plans
    from presentation_state import load_decks
    from validate_deck_plan import validate_deck_plan

    deck = load_decks(project_root).get(deck_id)
    if not isinstance(deck, Mapping):
        raise ValueError("unknown_deck")
    plan_id = deck.get("current_plan_id")
    plan_record = load_plans(project_root).get(plan_id) if isinstance(plan_id, str) else None
    if not isinstance(plan_record, Mapping):
        raise ValueError("current_plan_required")
    raw_path = plan_record.get("plan_path")
    if not isinstance(raw_path, str):
        raise ValueError("current_plan_path_required")
    expected_path = (project_root / canonical_relative_path(raw_path)).resolve()
    if expected_path != contract_path.resolve():
        raise ValueError("plan_path_identity_mismatch")
    if not isinstance(contract, Mapping):
        raise ValueError("plan_contract_mapping_required")
    errors = validate_deck_plan(dict(contract))
    if errors:
        raise ValueError("; ".join(errors))
    plan_version = contract.get("plan_version")
    if type(plan_version) is not int or plan_version <= 0:
        raise ValueError("plan_version_required")
    if plan_version != deck.get("approved_plan_version"):
        raise ValueError("approved_plan_version_mismatch")
    if contract.get("deck_id") != deck_id:
        raise ValueError("plan_deck_id_mismatch")
    plan_digest = contract_sha256(contract)
    if plan_digest != deck.get("approved_plan_sha256"):
        raise ValueError("approved_plan_digest_mismatch")
    if plan_record.get("sha256") != plan_digest:
        raise ValueError("plan_record_digest_mismatch")
    return {"plan_path": canonical_relative_path(raw_path), "plan_sha256": plan_digest}


def derive_validated_published_provenance(
    project_root: Path,
    deck_id: str,
    artifact_kind: str,
    slide_id: str | None,
) -> dict[str, Any]:
    """Derive and validate one publisher provenance mapping.

    Args:
        project_root: Project root containing durable presentation state.
        deck_id: Deck owning the artifact.
        artifact_kind: Canonical publisher artifact kind.
        slide_id: Generated slide record identifier for slide PNGs.

    Returns:
        Canonical provenance fields suitable for persistence.

    Raises:
        ValueError: If current plan or artifact evidence is incomplete.
    """
    provenance = derive_published_provenance(project_root, deck_id, artifact_kind, slide_id)
    validate_artifact_provenance(
        artifact_kind,
        deck_id=deck_id,
        slide_id=slide_id,
        module_id=None,
        plan_version=provenance.get("plan_version"),
        plan_sha256=provenance.get("plan_sha256"),
        slide_record_id=provenance.get("slide_record_id"),
        attempt=provenance.get("attempt"),
        source_paths=provenance.get("source_paths"),
        source_sha256=provenance.get("source_sha256"),
    )
    return provenance
