#!/usr/bin/env python3
"""Filesystem scope guards shared by presentation-state migration."""

from __future__ import annotations

import os
import stat
import hashlib
from pathlib import Path
from typing import Iterator, Mapping

from presentation_artifact_provenance import canonical_source_digest


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
NULLABLE_PATH_FIELDS = frozenset(
    {
        "slide_spec_path",
        "visual_spec_path",
        "assignment_path",
        "artifact_manifest_path",
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
    if not isinstance(raw_value, str) or not raw_value or "\x00" in raw_value:
        raise MigrationError(f"path must be a non-empty relative path: {raw_value!r}")
    if raw_value.startswith("/") or "\\" in raw_value:
        raise MigrationError(f"path must be project-relative and POSIX-normalized: {raw_value!r}")
    parts = raw_value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise MigrationError(f"path traversal or non-normalized path rejected: {raw_value!r}")
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


def validate_record_paths(project_root: Path, value: object) -> None:
    """Validate canonical path fields recursively with alias-cycle checks.

    Args:
        project_root: Root used to resolve and inspect path values.
        value: YAML/JSON mapping or list to validate recursively.

    Returns:
        ``None`` after all recognized path fields pass validation.

    Raises:
        MigrationError: If a path field is malformed, unknown, unsafe, or has
            a list/mapping shape inconsistent with its canonical schema.
    """
    _validate_record_paths(project_root, value, stack=set())


def _validate_record_paths(project_root: Path, value: object, stack: set[int]) -> None:
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
                _validate_draft_preview(project_root, value, stack)
            nullable_fields = _nullable_fields_for_record(value)
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
                _validate_record_paths(project_root, child_value, stack)
        else:
            for item in value:
                _validate_record_paths(project_root, item, stack)
    finally:
        stack.remove(id(value))


def _nullable_fields_for_record(value: Mapping[object, object]) -> frozenset[str]:
    """Return path fields nullable for one exact planned record schema.

    Nullability is intentionally tied to the public placeholder records rather
    than to a field name.  Assignment records and arbitrary event payloads do
    not receive any nullable path allowance.
    """
    if "event" in value or value.get("status") != "planned":
        return frozenset()
    keys = set(value)
    if {"id", "deck_id", "plan_slide_id", "title", "status"}.issubset(keys):
        return frozenset({"slide_spec_path"})
    if {"id", "slide_id", "module_key", "module_type", "status"}.issubset(keys):
        return frozenset({"visual_spec_path", "assignment_path", "artifact_manifest_path"})
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
    project_root: Path, preview: Mapping[object, object], stack: set[int]
) -> None:
    """Validate draft-preview artifact maps against their enclosing identity.

    The path-keyed maps are one evidence set: their keys must be exactly the
    ordered rendered-slide paths plus the contact-sheet path.  Every artifact
    is hashed from the current regular file, while binding metadata is checked
    against the enclosing preview and rendered-slide entries.
    """
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
        if ("slide_record_id" in raw_entry) != ("attempt" in raw_entry):
            raise MigrationError("rendered slide persisted record fields must appear together")
        if "slide_record_id" in raw_entry:
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
