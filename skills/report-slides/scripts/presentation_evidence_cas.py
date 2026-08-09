#!/usr/bin/env python3
"""No-follow planning and durable staging for evidence CAS objects.

This module reads only explicitly declared project-relative source paths.  It
does not interpret evidence envelopes; the shared evidence contract owns that
responsibility.  Planned objects can then be staged through one already-locked
``WorkflowTransaction`` with immutable SHA-256 path validation.
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from presentation_transactions import WorkflowTransaction


_SHA256_HEX = frozenset("0123456789abcdef")
_READ_SIZE = 64 * 1024


class CasError(ValueError):
    """Raised when an artifact cannot safely become a CAS object."""


@dataclass(frozen=True)
class CasObject:
    """One verified immutable content-addressed object.

    Attributes:
        digest: Lowercase SHA-256 of ``content``.
        relative_path: Canonical project-relative evidence CAS location.
        content: Exact verified source bytes.
        mode: Fixed immutable CAS publication permission bits (``0o444``).
    """

    digest: str
    relative_path: Path
    content: bytes
    mode: int


def cas_relative_path(digest: str) -> Path:
    """Return the canonical schema-v2 path for one lowercase SHA-256.

    Args:
        digest: Expected lowercase hexadecimal SHA-256 digest.

    Returns:
        The canonical evidence CAS path relative to a project root.

    Raises:
        CasError: If ``digest`` is not exactly a lowercase SHA-256 digest.
    """
    _require_digest(digest)
    return Path(".research/presentations/evidence/sha256") / digest[:2] / digest


def read_verified_source(project_root: Path, relative_path: str) -> CasObject:
    """Read and hash one regular source with no-follow semantics.

    Args:
        project_root: Root containing the declared source artifact.
        relative_path: Canonical project-relative source provenance path.

    Returns:
        A source-byte snapshot, digest, canonical CAS path, and immutable mode.

    Raises:
        CasError: If the path is malformed, missing, a symlink or special
            file, changes while read, or cannot be read without following
            links.
    """
    canonical_relative = _canonical_relative_path(relative_path)
    root = _project_root(project_root)
    source = root / canonical_relative
    _reject_symlink_components(root, source, canonical_relative)
    descriptor = _open_regular_source(source, canonical_relative)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise CasError(
                f"source must be a regular file: {canonical_relative}"
            )
        content = _read_all(descriptor, canonical_relative)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if _identity(before) != _identity(after) or len(content) != before.st_size:
        raise CasError(f"source changed while reading: {canonical_relative}")
    digest = hashlib.sha256(content).hexdigest()
    return CasObject(
        digest=digest,
        relative_path=cas_relative_path(digest),
        content=content,
        mode=0o444,
    )


def plan_cas_objects(
    project_root: Path,
    source_paths: Mapping[str, Path],
) -> dict[str, CasObject]:
    """Return deduplicated CAS objects without mutating the filesystem.

    Args:
        project_root: Root against which every provenance path is interpreted.
        source_paths: Canonical provenance paths mapped to their local source
            paths.  Every source must name exactly its provenance path under
            ``project_root``.

    Returns:
        A digest-keyed, deterministic mapping of immutable planned objects.

    Raises:
        CasError: If a provenance path is malformed, a source is outside the
            project or mismatched to its provenance, or source verification
            fails.
    """
    if not isinstance(source_paths, Mapping):
        raise CasError("source_paths must be a mapping of provenance paths to Path values")
    root = _project_root(project_root)
    planned: dict[str, CasObject] = {}
    for raw_relative, raw_source in sorted(source_paths.items(), key=lambda item: item[0]):
        canonical_relative = _canonical_relative_path(raw_relative)
        if not isinstance(raw_source, Path):
            raise CasError(
                f"source path for {canonical_relative} must be a pathlib.Path"
            )
        source_relative = _source_relative_path(root, raw_source)
        if source_relative != canonical_relative:
            raise CasError(
                f"source path {source_relative} does not match provenance {canonical_relative}"
            )
        object_ = read_verified_source(root, canonical_relative)
        existing = planned.get(object_.digest)
        if existing is not None and existing.content != object_.content:
            raise CasError(
                f"SHA-256 collision while planning CAS object {object_.digest}"
            )
        if existing is None:
            planned[object_.digest] = object_
    return planned


def stage_cas_objects(
    transaction: WorkflowTransaction,
    project_root: Path,
    objects: Mapping[str, CasObject],
) -> tuple[Path, ...]:
    """Stage verified CAS objects through an already-locked transaction.

    Args:
        transaction: Active transaction whose selected targets include every
            planned CAS path. This function never acquires locks.
        project_root: Root used to derive canonical targets. It must match the
            active transaction root.
        objects: Digest-keyed verified immutable CAS objects to stage.

    Returns:
        Canonical absolute CAS targets in deterministic digest order.

    Raises:
        CasError: If a planned object has an invalid digest, path, content, or
            mode.  Transaction errors propagate when its selected target set
            is incomplete or publication cannot safely proceed.
    """
    root = _project_root(project_root)
    if transaction.project_root != root:
        raise CasError("project_root does not match the active transaction root")
    if not isinstance(objects, Mapping):
        raise CasError("objects must be a mapping of SHA-256 digests to CasObject values")
    targets: list[Path] = []
    for digest, object_ in sorted(objects.items(), key=lambda item: item[0]):
        _validate_planned_object(digest, object_)
        target = root / object_.relative_path
        targets.append(target)
        try:
            snapshot_content, _, _ = transaction.snapshot(target)
        except ValueError as exc:
            raise CasError(f"CAS transaction target is not selected: {target}") from exc
        existing = _read_existing_object(target, object_.relative_path, digest)
        if existing is None:
            transaction.stage_bytes(target, object_.content, mode=0o444)
            continue
        if existing != object_.content:
            raise CasError(f"CAS object bytes do not match digest: {digest}")
        if snapshot_content != existing:
            raise CasError(f"CAS object changed after transaction lock: {target}")
    return tuple(targets)


def _require_digest(digest: object) -> None:
    """Require one exact lowercase hexadecimal SHA-256 digest."""
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in _SHA256_HEX for character in digest)
    ):
        raise CasError("digest must be a lowercase SHA-256 hexadecimal string")


def _canonical_relative_path(relative_path: object) -> str:
    """Return one canonical lexical project-relative POSIX path."""
    if not isinstance(relative_path, str) or not relative_path:
        raise CasError("source path must be a non-empty canonical project-relative path")
    if relative_path.startswith("/") or "\\" in relative_path or "\x00" in relative_path:
        raise CasError("source path must be a canonical project-relative POSIX path")
    parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in parts) or "/".join(parts) != relative_path:
        raise CasError("source path must be a canonical project-relative POSIX path")
    return relative_path


def _project_root(project_root: Path) -> Path:
    """Resolve an existing project root and reject non-directory inputs."""
    if not isinstance(project_root, Path):
        raise CasError("project_root must be a pathlib.Path")
    try:
        root = project_root.resolve(strict=True)
    except OSError as exc:
        raise CasError(f"project root cannot be resolved: {project_root}") from exc
    if not root.is_dir():
        raise CasError(f"project root must be a directory: {project_root}")
    return root


def _source_relative_path(project_root: Path, source: Path) -> str:
    """Return the canonical lexical provenance path for one source path."""
    candidate = source if source.is_absolute() else project_root / source
    try:
        relative = candidate.relative_to(project_root).as_posix()
    except ValueError as exc:
        raise CasError(f"source path escapes project root: {source}") from exc
    return _canonical_relative_path(relative)


def _reject_symlink_components(project_root: Path, source: Path, relative_path: str) -> None:
    """Reject every existing symlink in a declared source path."""
    try:
        components = source.relative_to(project_root).parts
    except ValueError as exc:
        raise CasError(f"source path escapes project root: {relative_path}") from exc
    current = project_root
    for component in components:
        current = current / component
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise CasError(f"cannot inspect source path {relative_path}: {exc}") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise CasError(f"source path contains a symlink: {relative_path}")


def _open_regular_source(source: Path, relative_path: str) -> int:
    """Open one artifact descriptor without following links or blocking FIFOs."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise CasError(
            f"source reading requires os.O_NOFOLLOW: {relative_path}"
        )
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        return os.open(str(source), flags)
    except FileNotFoundError as exc:
        raise CasError(f"missing source artifact: {relative_path}") from exc
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EISDIR):
            raise CasError(f"source path is not a regular no-follow file: {relative_path}") from exc
        raise CasError(f"cannot open source artifact {relative_path}: {exc}") from exc


def _read_all(descriptor: int, relative_path: str) -> bytes:
    """Read one opened source descriptor completely without silent short reads."""
    chunks: list[bytes] = []
    while True:
        try:
            chunk = os.read(descriptor, _READ_SIZE)
        except OSError as exc:
            raise CasError(f"cannot read source artifact {relative_path}: {exc}") from exc
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    """Return source metadata that must remain stable during an evidence read."""
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _validate_planned_object(digest: object, object_: object) -> None:
    """Reject hand-constructed or corrupted objects before transaction staging."""
    _require_digest(digest)
    if not isinstance(object_, CasObject):
        raise CasError(f"CAS object for {digest} must be a CasObject")
    if object_.digest != digest:
        raise CasError(f"CAS object key does not match object digest: {digest}")
    if object_.relative_path != cas_relative_path(digest):
        raise CasError(f"CAS object path does not match object digest: {digest}")
    if hashlib.sha256(object_.content).hexdigest() != digest:
        raise CasError(f"CAS object content does not match object digest: {digest}")
    if object_.mode != 0o444:
        raise CasError(f"CAS object mode is invalid: {digest}")


def _read_existing_object(
    target: Path, relative_path: Path, expected_digest: str
) -> bytes | None:
    """Return verified existing CAS bytes without following a target symlink."""
    try:
        metadata = os.lstat(target)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CasError(f"cannot inspect CAS object {relative_path}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CasError(f"CAS object must be a regular no-follow file: {relative_path}")
    if not hasattr(os, "O_NOFOLLOW"):
        raise CasError(f"CAS verification requires os.O_NOFOLLOW: {relative_path}")
    try:
        descriptor = os.open(str(target), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise CasError(f"cannot open CAS object {relative_path}: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise CasError(f"CAS object must be a regular file: {relative_path}")
        content = _read_all(descriptor, relative_path.as_posix())
        closed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if _identity(opened) != _identity(closed) or len(content) != opened.st_size:
        raise CasError(f"CAS object changed while reading: {relative_path}")
    if hashlib.sha256(content).hexdigest() != expected_digest:
        raise CasError(f"CAS object bytes do not match digest: {expected_digest}")
    return content
