#!/usr/bin/env python3
"""Filesystem scope guards shared by presentation-state migration."""

from __future__ import annotations

import os
import stat
import hashlib
from pathlib import Path
from typing import Any, Iterator, Mapping

from presentation_artifact_provenance import canonical_source_digest
from presentation_contracts import contract_sha256
from presentation_evidence_contracts import (
    EvidenceContractError,
    legacy_nullable_path_fields,
)


class MigrationError(RuntimeError):
    """Raised when a migration scope contains unsafe filesystem entries."""


SINGULAR_PATH_KEYS = frozenset(
    {
        "path",
        "relative_path",
        "plan_path",
        "assignment_path",
        "artifact_path",
        "artifact_manifest_path",
        "completion_record_path",
        "current_plan_path",
        "slide_assignment_path",
        "slide_spec_path",
        "visual_spec_path",
        "preview_path",
        "source_path",
        "output_path",
        "rendered_path",
        "contact_sheet_path",
        "visual_review_path",
        "review_record_path",
        "review_path",
        "approval_path",
        "revision_path",
        "decision_path",
        "event_path",
        "input_path",
        "manifest_path",
    }
)
PLURAL_PATH_KEYS = frozenset(
    {
        "source_paths",
        "rendered_slide_paths",
        "source_artifacts",
        "conversion_artifacts",
        "rendered_png_paths",
        "inspected_paths",
        "comparison_reference_paths",
    }
)
MAPPING_PATH_LIST_KEYS = frozenset({"rendered_slide_paths"})
PATH_LIST_MEMBERS = frozenset({"path", "relative_path"})
PATH_KEYED_MAPPING_FIELDS = frozenset({"artifact_digests", "artifact_bindings"})
_SHA256_LENGTH = 64
_STORE_NAMES = frozenset(
    {
        "decks",
        "plans",
        "slides",
        "visual_modules",
        "assignments",
        "artifacts",
        "revision_requests",
        "events",
    }
)
_PREVIEW_FIELDS = frozenset(
    {
        "schema_version",
        "deck_id",
        "plan_version",
        "plan_sha256",
        "rendered_slide_paths",
        "contact_sheet_path",
        "slides",
        "artifact_digests",
        "artifact_bindings",
    }
)
_PERSISTED_PREVIEW_FIELDS = _PREVIEW_FIELDS | frozenset(
    {"event", "id", "preview_sha256", "ts"}
)
_RENDERED_PREVIEW_ENTRY_FIELDS = frozenset(
    {"slide_id", "path", "slide_record_id", "attempt"}
)
_PREVIEW_SLIDE_FIELDS = frozenset({"slide_id", "title", "key_takeaway"})
_STATE_STORE_NAMES = frozenset(
    {
        "decks.yaml",
        "plans.yaml",
        "slides.yaml",
        "visual_modules.yaml",
        "assignments.yaml",
        "artifacts.yaml",
        "revision_requests.yaml",
        "evidence.yaml",
    }
)


def is_canonical_operational_lock(name: object, scope: str) -> bool:
    """Return whether a direct scope entry is a supported stable lock.

    Args:
        name: Basename from one direct state or event directory entry.
        scope: Either ``state`` or ``event``.

    Returns:
        True only for a canonical regular workflow lock or data-file sidecar.
        Existence of the corresponding data file is intentionally not required.
    """
    if not isinstance(name, str):
        return False
    if scope == "state":
        return name == "workflow.lock" or (
            name.endswith(".lock")
            and name.removesuffix(".lock") in _STATE_STORE_NAMES
        )
    if scope == "event":
        return bool(
            name.endswith(".lock")
            and _event_shard_name_is_canonical(name.removesuffix(".lock"))
        )
    return False


def _event_shard_name_is_canonical(name: str) -> bool:
    """Return whether one basename is a valid calendar-dated JSONL shard."""
    if len(name) != 16 or not name.endswith(".jsonl"):
        return False
    try:
        from datetime import datetime

        datetime.strptime(name.removesuffix(".jsonl"), "%Y-%m-%d")
    except ValueError:
        return False
    return True


def iter_scope_entries(root: Path) -> Iterator[Path]:
    """Yield regular files directly below ``root`` while rejecting extras.

    Args:
        root: State or event directory to inspect.

    Returns:
        An iterator over direct regular-file entries in lexical order.

    Raises:
        MigrationError: If ``root`` or any direct entry is a symlink, special
            file, or nested directory, or if directory inspection fails.
    """
    if not root.exists():
        return
    try:
        root_metadata = os.lstat(root)
    except OSError as exc:
        raise MigrationError(f"unable to inspect state/event scope {root}: {exc}") from exc
    if stat.S_ISLNK(root_metadata.st_mode):
        raise MigrationError(f"state/event scope must not be a symlink: {root}")
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise MigrationError(f"state/event scope must be a directory: {root}")
    try:
        entries = sorted(os.scandir(root), key=lambda item: item.name)
    except OSError as exc:
        raise MigrationError(f"unable to inspect state/event scope {root}: {exc}") from exc
    for entry in entries:
        entry_path = Path(entry.path)
        try:
            metadata = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise MigrationError(f"unable to inspect state/event entry {entry_path}: {exc}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise MigrationError(f"state/event entry must not be a symlink: {entry_path}")
        if stat.S_ISDIR(metadata.st_mode):
            raise MigrationError(f"state/event scope must not contain nested directory: {entry_path}")
        if stat.S_ISREG(metadata.st_mode):
            yield entry_path
        else:
            raise MigrationError(f"state/event entry must be regular: {entry_path}")


def assert_no_symlink_ancestors(path: Path, project_root: Path) -> None:
    """Reject a state/event scope whose parent path redirects elsewhere.

    Args:
        path: Scope path whose ancestors must be checked.
        project_root: Canonical project root that bounds the scope.

    Returns:
        ``None`` after every existing ancestor is verified as non-symlink.

    Raises:
        MigrationError: If ``path`` escapes ``project_root``, an ancestor
            cannot be inspected, or an ancestor is a symbolic link.
    """
    root = project_root.resolve()
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError as exc:
        raise MigrationError(f"scope escapes project root: {path}") from exc
    current = root
    for part in relative_parts:
        current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise MigrationError(f"unable to inspect scope ancestor {current}: {exc}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise MigrationError(f"state/event scope contains a symlink ancestor: {current}")


def canonical_project_relative(
    project_root: Path, raw_value: object, *, allow_directory: bool = False
) -> str:
    """Validate one existing POSIX project-relative path safely.

    Args:
        project_root: Root against which the path is resolved.
        raw_value: Candidate project-relative path value.
        allow_directory: Whether this field explicitly permits a directory.

    Returns:
        The normalized project-relative path string.

    Raises:
        MigrationError: If the value is malformed, missing, special, a
            symlink, outside the project, or an unallowed directory.
    """
    relative_path = canonical_relative_path(raw_value)
    parts = relative_path.split("/")
    root = project_root.resolve()
    candidate = root.joinpath(*parts)
    current = root
    final_metadata: os.stat_result | None = None
    for part in parts:
        current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise MigrationError(f"unable to inspect path {raw_value!r}: {exc}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise MigrationError(f"path contains a symlink and cannot be verified: {raw_value!r}")
        if part != parts[-1] and not stat.S_ISDIR(metadata.st_mode):
            raise MigrationError(f"path ancestor is not a directory: {raw_value!r}")
        if part == parts[-1] and not stat.S_ISREG(metadata.st_mode) and not stat.S_ISDIR(metadata.st_mode):
            raise MigrationError(f"path refers to a special file: {raw_value!r}")
        if part == parts[-1]:
            final_metadata = metadata
    if final_metadata is None:
        raise MigrationError(f"path target does not exist: {raw_value!r}")
    if stat.S_ISDIR(final_metadata.st_mode) and not allow_directory:
        raise MigrationError(f"path target must be a regular file: {raw_value!r}")
    try:
        candidate.resolve(strict=False).relative_to(root)
    except (OSError, ValueError) as exc:
        raise MigrationError(f"path escapes project root: {raw_value!r}") from exc
    return "/".join(parts)


def canonical_relative_path(raw_value: object) -> str:
    """Return one lexically canonical project-relative POSIX path.

    This helper performs no filesystem access. It is therefore suitable for
    preserving an immutable historical declaration whose original bytes may no
    longer be available. Callers that require a current file must use
    :func:`canonical_project_relative` afterwards.

    Args:
        raw_value: Candidate project-relative POSIX path.

    Returns:
        The same validated canonical path string.

    Raises:
        MigrationError: If the path is empty, absolute, contains a backslash,
            NUL, traversal component, or redundant separator.
    """
    if not isinstance(raw_value, str) or not raw_value or "\x00" in raw_value:
        raise MigrationError(f"path must be a non-empty relative path: {raw_value!r}")
    if raw_value.startswith("/") or "\\" in raw_value:
        raise MigrationError(
            f"path must be project-relative and POSIX-normalized: {raw_value!r}"
        )
    parts = raw_value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise MigrationError(
            f"path traversal or non-normalized path rejected: {raw_value!r}"
        )
    return raw_value


def validate_record_paths(
    project_root: Path,
    value: object,
    *,
    store_name: str | None = None,
    current_slides: Mapping[str, Any] | None = None,
) -> None:
    """Validate canonical path fields recursively with alias-cycle checks.

    Args:
        project_root: Root used to resolve and inspect path values.
        value: YAML/JSON mapping or list to validate recursively.
        store_name: Authoritative top-level state store, ``events``, or
            ``None`` for context-free documents.  Context-free validation
            never grants nullable path fields.
        current_slides: Current slides-store records used to bind persisted
            draft-preview identity.

    Returns:
        ``None`` after all recognized path fields pass validation.

    Raises:
        MigrationError: If a path field is malformed, unknown, unsafe, or has
            a list/mapping shape inconsistent with its canonical schema.
    """
    if store_name is not None and store_name not in _STORE_NAMES:
        raise MigrationError(f"unknown authoritative migration store {store_name!r}")
    _validate_record_paths(
        project_root,
        value,
        stack=set(),
        store_name=store_name,
        current_slides=current_slides,
        root_record=True,
    )


def _validate_record_paths(
    project_root: Path,
    value: object,
    stack: set[int],
    *,
    store_name: str | None = None,
    current_slides: Mapping[str, Any] | None = None,
    root_record: bool = False,
) -> None:
    """Recursively validate one value while tracking active aliases."""
    if isinstance(value, (Mapping, list)):
        identity = id(value)
        if identity in stack:
            raise MigrationError("recursive YAML alias cycle in path-bearing state")
        stack.add(identity)
    else:
        return
    try:
        if isinstance(value, Mapping):
            is_draft_preview = value.get("event") == "draft_preview"
            if is_draft_preview:
                if not root_record or store_name != "events":
                    raise MigrationError(
                        "draft_preview must be a top-level immutable event record"
                    )
                _validate_draft_preview(
                    project_root,
                    value,
                    stack,
                    current_slides=current_slides,
                )
            nullable_fields = _nullable_fields_for_record(
                value,
                store_name=store_name if root_record else None,
            )
            for child_key, child_value in value.items():
                if isinstance(child_key, str):
                    if child_key in SINGULAR_PATH_KEYS:
                        _validate_singular_path(
                            project_root,
                            child_key,
                            child_value,
                            allow_none=child_key in nullable_fields,
                        )
                    elif child_key in PLURAL_PATH_KEYS:
                        _validate_plural_path(project_root, child_key, child_value, stack)
                    elif child_key in PATH_KEYED_MAPPING_FIELDS:
                        if not is_draft_preview:
                            _validate_path_keyed_mapping(project_root, child_key, child_value, stack)
                    elif child_key.endswith("_path") or child_key.endswith("_paths"):
                        raise MigrationError(f"unknown path-bearing field {child_key!r}")
                _validate_record_paths(
                    project_root,
                    child_value,
                    stack,
                    current_slides=current_slides,
                )
        else:
            for item in value:
                _validate_record_paths(
                    project_root,
                    item,
                    stack,
                    current_slides=current_slides,
                )
    finally:
        stack.remove(id(value))


def _nullable_fields_for_record(
    value: Mapping[object, object],
    *,
    store_name: str | None,
) -> frozenset[str]:
    """Return path fields nullable for one exact planned record schema.

    Nullability is intentionally tied to the public placeholder records rather
    than to a field name.  Assignment records and arbitrary event payloads do
    not receive any nullable path allowance.
    """
    if store_name not in {"slides", "visual_modules"} or value.get("status") != "planned":
        return frozenset()
    try:
        nullable_fields = legacy_nullable_path_fields(store_name, value)
    except EvidenceContractError as exc:
        raise MigrationError(f"invalid {store_name} record contract: {exc}") from exc
    if nullable_fields:
        return nullable_fields
    nullable_path_fields = {
        "slide_spec_path",
        "visual_spec_path",
        "assignment_path",
        "artifact_manifest_path",
    }
    if any(value.get(field) is None for field in nullable_path_fields if field in value):
        raise MigrationError(
            f"planned {store_name} record with nullable paths must match its exact public schema"
        )
    return frozenset()


def _validate_singular_path(
    project_root: Path, key: str, value: object, *, allow_none: bool = False
) -> None:
    """Validate one singular path field with contextual nullability."""
    if value is None:
        if allow_none:
            return
        raise MigrationError(f"singular path field {key!r} requires one string path")
    if isinstance(value, (Mapping, list)):
        raise MigrationError(f"singular path field {key!r} requires one string path")
    canonical_project_relative(project_root, value)


def _validate_plural_path(
    project_root: Path, key: str, value: object, stack: set[int]
) -> None:
    """Validate one explicit plural path field and its canonical entries."""
    if not isinstance(value, list):
        raise MigrationError(f"plural path field {key!r} requires a list")
    mapping_entries = key in MAPPING_PATH_LIST_KEYS
    for item in value:
        if mapping_entries:
            if not isinstance(item, Mapping):
                raise MigrationError(f"plural path field {key!r} requires mapping entries")
            members = [member for member in PATH_LIST_MEMBERS if member in item]
            if len(members) != 1:
                raise MigrationError(f"path list field {key!r} item requires exactly one canonical path member")
        elif isinstance(item, Mapping):
            raise MigrationError(f"plural path field {key!r} requires string entries")
        canonical_project_relative(project_root, item.get("path", item.get("relative_path"))) if mapping_entries else canonical_project_relative(project_root, item)
        if mapping_entries:
            _validate_record_paths(project_root, item, stack)


def _validate_path_keyed_mapping(
    project_root: Path, field: str, value: object, stack: set[int]
) -> None:
    """Validate a mapping whose keys identify concrete project artifacts.

    Args:
        project_root: Root used to resolve artifact paths.
        field: Explicit path-keyed mapping field name.
        value: Candidate digest or binding map.
        stack: Active mapping/list identities used for alias-cycle detection.

    Raises:
        MigrationError: If keys are unsafe or values do not match the current
            draft-preview digest/binding contracts.
    """
    if not isinstance(value, Mapping):
        raise MigrationError(f"path-keyed mapping field {field!r} requires a mapping")
    if not value:
        raise MigrationError(f"path-keyed mapping field {field!r} must not be empty")
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str):
            raise MigrationError(f"path-keyed mapping {field!r} keys must be strings")
        canonical_project_relative(project_root, raw_key)
        if field == "artifact_digests":
            _validate_digest(raw_value, f"artifact_digests[{raw_key!r}]")
        else:
            _validate_artifact_binding(project_root, raw_key, raw_value, stack)


def _hash_regular_file(project_root: Path, relative_path: str) -> str:
    """Hash one canonical regular project file without following symlinks."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise MigrationError(f"no-follow artifact reads are unavailable: {relative_path}")
    path = project_root / relative_path
    try:
        descriptor = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise MigrationError(f"unable to hash regular artifact {relative_path!r}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise MigrationError(f"artifact target must be a regular file: {relative_path!r}")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _validate_draft_preview(
    project_root: Path,
    preview: Mapping[object, object],
    stack: set[int],
    *,
    current_slides: Mapping[str, Any] | None,
) -> None:
    """Validate draft-preview artifact maps against their enclosing identity.

    The path-keyed maps are one evidence set: their keys must be exactly the
    ordered rendered-slide paths plus the contact-sheet path.  Every artifact
    is hashed from the current regular file, while binding metadata is checked
    against the enclosing preview and rendered-slide entries.
    """
    if set(preview) != _PERSISTED_PREVIEW_FIELDS:
        raise MigrationError(
            "persisted draft_preview fields must match the exact producer record contract"
        )
    if preview.get("event") != "draft_preview":
        raise MigrationError("persisted draft_preview event type is invalid")
    _validate_text(preview.get("id"), "draft_preview.id")
    _validate_text(preview.get("ts"), "draft_preview.ts")
    if type(preview.get("schema_version")) is not int or preview.get("schema_version") != 1:
        raise MigrationError("draft_preview.schema_version must be integer 1")
    preview_sha256 = preview.get("preview_sha256")
    _validate_digest(preview_sha256, "draft_preview.preview_sha256")
    for mapping_field in PATH_KEYED_MAPPING_FIELDS:
        raw_mapping = preview.get(mapping_field)
        if not isinstance(raw_mapping, Mapping):
            raise MigrationError(
                f"draft_preview.{mapping_field} must be a non-empty mapping"
            )
        _canonical_mapping_keys(project_root, mapping_field, raw_mapping)
    producer_payload = {field: preview[field] for field in _PREVIEW_FIELDS}
    try:
        expected_preview_sha256 = contract_sha256(producer_payload)
    except (TypeError, ValueError, RecursionError) as exc:
        raise MigrationError(f"draft_preview producer digest cannot be recomputed: {exc}") from exc

    deck_id = preview.get("deck_id")
    _validate_text(deck_id, "draft_preview.deck_id")
    plan_version = preview.get("plan_version")
    _validate_positive_int(plan_version, "draft_preview.plan_version")
    plan_sha256 = preview.get("plan_sha256")
    _validate_digest(plan_sha256, "draft_preview.plan_sha256")

    rendered = preview.get("rendered_slide_paths")
    if not isinstance(rendered, list) or not rendered:
        raise MigrationError("draft_preview.rendered_slide_paths must be a non-empty list")
    rendered_paths: list[str] = []
    rendered_entries: dict[str, Mapping[object, object]] = {}
    slide_ids: set[str] = set()
    for index, raw_entry in enumerate(rendered):
        if not isinstance(raw_entry, Mapping):
            raise MigrationError(f"draft_preview rendered slide entry {index} must be a mapping")
        slide_id = raw_entry.get("slide_id")
        _validate_text(slide_id, f"draft_preview.rendered_slide_paths[{index}].slide_id")
        if slide_id in slide_ids:
            raise MigrationError(f"duplicate rendered slide id {slide_id!r}")
        slide_ids.add(slide_id)
        raw_path = raw_entry.get("path")
        relative_path = canonical_project_relative(project_root, raw_path)
        if relative_path != raw_path:
            raise MigrationError(f"rendered slide path is not canonical: {raw_path!r}")
        if relative_path in rendered_entries:
            raise MigrationError(f"duplicate rendered slide path {relative_path!r}")
        if set(raw_entry) != _RENDERED_PREVIEW_ENTRY_FIELDS:
            raise MigrationError(
                "draft_preview rendered slide entry must contain exact current identity fields"
            )
        _validate_text(
            raw_entry.get("slide_record_id"),
            f"draft_preview.rendered_slide_paths[{index}].slide_record_id",
        )
        _validate_positive_int(
            raw_entry.get("attempt"),
            f"draft_preview.rendered_slide_paths[{index}].attempt",
        )
        rendered_paths.append(relative_path)
        rendered_entries[relative_path] = raw_entry

    raw_slides = preview.get("slides")
    if not isinstance(raw_slides, list) or not raw_slides:
        raise MigrationError("draft_preview.slides must be a non-empty list")
    preview_slide_ids: list[str] = []
    for index, raw_slide in enumerate(raw_slides):
        if not isinstance(raw_slide, Mapping) or set(raw_slide) != _PREVIEW_SLIDE_FIELDS:
            raise MigrationError(
                f"draft_preview.slides[{index}] must match the exact producer metadata fields"
            )
        for field in _PREVIEW_SLIDE_FIELDS:
            _validate_text(raw_slide.get(field), f"draft_preview.slides[{index}].{field}")
        preview_slide_ids.append(str(raw_slide["slide_id"]))
    rendered_slide_ids = [str(rendered_entries[path]["slide_id"]) for path in rendered_paths]
    if preview_slide_ids != rendered_slide_ids:
        raise MigrationError("draft_preview slide metadata order or identity mismatch")

    _validate_current_preview_slides(
        preview,
        rendered_entries,
        rendered_paths,
        current_slides=current_slides,
    )

    raw_contact = preview.get("contact_sheet_path")
    contact_path = canonical_project_relative(project_root, raw_contact)
    if contact_path != raw_contact:
        raise MigrationError(f"contact sheet path is not canonical: {raw_contact!r}")
    expected_paths = set(rendered_paths) | {contact_path}

    raw_digests = preview.get("artifact_digests")
    if not isinstance(raw_digests, Mapping) or not raw_digests:
        raise MigrationError("draft_preview.artifact_digests must be a non-empty mapping")
    digest_keys = _canonical_mapping_keys(project_root, "artifact_digests", raw_digests)
    if digest_keys != expected_paths:
        raise MigrationError(
            "artifact_digests key set must equal rendered slides plus contact sheet"
        )
    actual_digests: dict[str, str] = {}
    for path in sorted(expected_paths):
        declared = raw_digests[path]
        _validate_digest(declared, f"artifact_digests[{path!r}]")
        actual = _hash_regular_file(project_root, path)
        actual_digests[path] = actual
        if declared != actual:
            raise MigrationError(f"artifact digest mismatch for {path!r}")

    raw_bindings = preview.get("artifact_bindings")
    if not isinstance(raw_bindings, Mapping) or not raw_bindings:
        raise MigrationError("draft_preview.artifact_bindings must be a non-empty mapping")
    binding_keys = _canonical_mapping_keys(project_root, "artifact_bindings", raw_bindings)
    if binding_keys != expected_paths:
        raise MigrationError(
            "artifact_bindings key set must equal rendered slides plus contact sheet"
        )
    for path in rendered_paths:
        binding = raw_bindings[path]
        _validate_artifact_binding(project_root, path, binding, stack)
        if not isinstance(binding, Mapping):
            continue
        expected_entry = rendered_entries[path]
        _require_binding_identity(binding, path, "rendered_slide", deck_id, plan_version, plan_sha256)
        if binding.get("slide_id") != expected_entry.get("slide_id"):
            raise MigrationError(f"rendered artifact binding slide mismatch for {path!r}")
        for field in ("slide_record_id", "attempt"):
            if field in expected_entry and binding.get(field) != expected_entry.get(field):
                raise MigrationError(f"rendered artifact binding {field} mismatch for {path!r}")

    contact_binding = raw_bindings[contact_path]
    _validate_artifact_binding(project_root, contact_path, contact_binding, stack)
    if not isinstance(contact_binding, Mapping):
        return
    _require_binding_identity(
        contact_binding, contact_path, "contact_sheet", deck_id, plan_version, plan_sha256
    )
    source_paths = contact_binding.get("source_paths")
    if source_paths != rendered_paths:
        raise MigrationError("contact-sheet source_paths order or membership mismatch")
    source_sha256 = contact_binding.get("source_sha256")
    _validate_digest(source_sha256, f"artifact_bindings[{contact_path!r}].source_sha256")
    try:
        expected_source_sha256 = canonical_source_digest(
            rendered_paths, [actual_digests[path] for path in rendered_paths]
        )
    except (TypeError, ValueError) as exc:
        raise MigrationError(f"contact-sheet source digest cannot be recomputed: {exc}") from exc
    if source_sha256 != expected_source_sha256:
        raise MigrationError("contact-sheet source_sha256 mismatch")
    if preview_sha256 != expected_preview_sha256:
        raise MigrationError("draft_preview.preview_sha256 does not match producer payload")


def _validate_current_preview_slides(
    preview: Mapping[object, object],
    rendered_entries: Mapping[str, Mapping[object, object]],
    rendered_paths: list[str],
    *,
    current_slides: Mapping[str, Any] | None,
) -> None:
    """Bind persisted preview entries to exact current slide records."""
    if current_slides is None:
        raise MigrationError("draft_preview current slides-store context is required")
    deck_id = preview.get("deck_id")
    by_plan_slide_id: dict[str, Mapping[str, Any]] = {}
    for raw_slide in current_slides.values():
        if not isinstance(raw_slide, Mapping):
            raise MigrationError("current slides-store record must be a mapping")
        if raw_slide.get("deck_id") != deck_id or raw_slide.get("status") == "superseded":
            continue
        plan_slide_id = raw_slide.get("plan_slide_id")
        if not isinstance(plan_slide_id, str) or not plan_slide_id:
            raise MigrationError("current slide plan identity is invalid")
        if plan_slide_id in by_plan_slide_id:
            raise MigrationError(f"duplicate current slide identity {plan_slide_id!r}")
        by_plan_slide_id[plan_slide_id] = raw_slide
    for path in rendered_paths:
        entry = rendered_entries[path]
        plan_slide_id = str(entry["slide_id"])
        current = by_plan_slide_id.get(plan_slide_id)
        if current is None:
            raise MigrationError(f"current slide record missing for {plan_slide_id!r}")
        current_record_id = current.get("id")
        current_attempt = current.get("attempt")
        _validate_text(current_record_id, f"current slide {plan_slide_id!r}.id")
        _validate_positive_int(current_attempt, f"current slide {plan_slide_id!r}.attempt")
        if entry.get("slide_record_id") != current_record_id:
            raise MigrationError(f"draft_preview stale slide_record_id for {path!r}")
        if entry.get("attempt") != current_attempt:
            raise MigrationError(f"draft_preview stale slide attempt for {path!r}")


def _canonical_mapping_keys(
    project_root: Path, field: str, value: Mapping[object, object]
) -> set[str]:
    """Validate and return canonical keys for one artifact mapping."""
    keys: set[str] = set()
    for key in value:
        if not isinstance(key, str):
            raise MigrationError(f"path-keyed mapping {field!r} keys must be strings")
        canonical = canonical_project_relative(project_root, key)
        if canonical != key:
            raise MigrationError(f"path-keyed mapping {field!r} key is not canonical: {key!r}")
        keys.add(canonical)
    return keys


def _require_binding_identity(
    binding: Mapping[object, object],
    path: str,
    kind: str,
    deck_id: object,
    plan_version: object,
    plan_sha256: object,
) -> None:
    """Require one artifact binding to match its enclosing preview identity."""
    if binding.get("kind") != kind:
        raise MigrationError(f"artifact binding kind mismatch for {path!r}")
    for field, expected in (
        ("deck_id", deck_id),
        ("plan_version", plan_version),
        ("plan_sha256", plan_sha256),
    ):
        if binding.get(field) != expected:
            raise MigrationError(f"artifact binding {field} mismatch for {path!r}")


def _validate_digest(value: object, field: str) -> None:
    """Require one lowercase hexadecimal SHA-256 digest."""
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise MigrationError(f"{field} must be a lowercase SHA-256 digest")


def _validate_text(value: object, field: str) -> None:
    """Require one trimmed non-empty text contract field."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise MigrationError(f"{field} must be a trimmed non-empty string")


def _validate_positive_int(value: object, field: str) -> None:
    """Require one positive integer while rejecting booleans."""
    if type(value) is not int or value <= 0:
        raise MigrationError(f"{field} must be a positive integer")


def _validate_artifact_binding(
    project_root: Path, path_key: str, value: object, stack: set[int]
) -> None:
    """Validate one exact rendered-slide or contact-sheet binding."""
    if not isinstance(value, Mapping):
        raise MigrationError(f"artifact binding for {path_key!r} must be a mapping")
    kind = value.get("kind")
    if kind == "rendered_slide":
        expected_fields = frozenset(
            {
                "kind",
                "deck_id",
                "slide_id",
                "plan_version",
                "plan_sha256",
                "producer_id",
                "slide_record_id",
                "attempt",
            }
        )
        if set(value) != expected_fields:
            raise MigrationError(f"rendered artifact binding for {path_key!r} has non-canonical fields")
        for field in ("deck_id", "slide_id", "producer_id", "slide_record_id"):
            _validate_text(value.get(field), f"artifact_bindings[{path_key!r}].{field}")
        _validate_positive_int(value.get("plan_version"), f"artifact_bindings[{path_key!r}].plan_version")
        _validate_digest(value.get("plan_sha256"), f"artifact_bindings[{path_key!r}].plan_sha256")
        _validate_positive_int(value.get("attempt"), f"artifact_bindings[{path_key!r}].attempt")
        return
    if kind == "contact_sheet":
        expected_fields = frozenset(
            {
                "kind",
                "deck_id",
                "plan_version",
                "plan_sha256",
                "producer_id",
                "source_paths",
                "source_sha256",
            }
        )
        if set(value) != expected_fields:
            raise MigrationError(f"contact-sheet artifact binding for {path_key!r} has non-canonical fields")
        for field in ("deck_id", "producer_id"):
            _validate_text(value.get(field), f"artifact_bindings[{path_key!r}].{field}")
        _validate_positive_int(value.get("plan_version"), f"artifact_bindings[{path_key!r}].plan_version")
        _validate_digest(value.get("plan_sha256"), f"artifact_bindings[{path_key!r}].plan_sha256")
        _validate_digest(value.get("source_sha256"), f"artifact_bindings[{path_key!r}].source_sha256")
        _validate_plural_path(project_root, "source_paths", value.get("source_paths"), stack)
        return
    raise MigrationError(f"artifact binding for {path_key!r} has unsupported kind")
