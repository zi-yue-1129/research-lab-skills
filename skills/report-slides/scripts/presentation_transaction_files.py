"""Narrow anchored ordinary-file primitives for workflow transactions."""

from __future__ import annotations

import os
import json
import re
import stat
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from presentation_no_follow import (
    AnchoredPath,
    MissingPathError,
    open_parent_no_follow,
    read_regular_siblings,
    read_stable_regular,
)


_JOURNAL = re.compile(r"([0-9a-f]{32})\.json")
_JOURNAL_TEMP = re.compile(r"([0-9a-f]{32})\.json\.tmp")


def validate_journal_fields(
    document: object, name: str
) -> tuple[str, list[object], list[str]]:
    """Validate exact legacy/current journal fields and scalar containers."""
    if not isinstance(document, dict):
        raise ValueError(f"invalid transaction journal shape: {name}")
    allowed = {"transaction_id", "paths"}
    if "staged_paths" in document:
        allowed.add("staged_paths")
    if set(document) != allowed:
        raise ValueError(f"invalid transaction journal fields: {name}")
    transaction_id = document.get("transaction_id")
    entries = document.get("paths")
    staged = document.get("staged_paths", [])
    if (
        not isinstance(transaction_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", transaction_id) is None
        or not isinstance(entries, list)
        or not entries
        or not isinstance(staged, list)
        or any(not isinstance(item, str) for item in staged)
        or len(staged) != len(set(staged))
    ):
        raise ValueError(f"invalid transaction journal shape: {name}")
    return transaction_id, entries, staged


def validate_preimage_fields(entry: object, name: str) -> Mapping[str, Any]:
    """Validate one exact legacy/current journal preimage mapping."""
    if not isinstance(entry, Mapping):
        raise ValueError(f"invalid transaction journal preimage: {name}")
    base = {"path", "exists", "mode", "content"}
    if set(entry) not in (base, base | {"mtime_ns"}):
        raise ValueError(f"invalid transaction journal preimage fields: {name}")
    if (
        not isinstance(entry.get("path"), str)
        or not entry["path"]
        or type(entry.get("exists")) is not bool
        or type(entry.get("mode")) is not int
        or not isinstance(entry.get("content"), str)
    ):
        raise ValueError(f"invalid transaction journal preimage types: {name}")
    if "mtime_ns" in entry and (
        type(entry["mtime_ns"]) is not int or entry["mtime_ns"] < 0
    ):
        raise ValueError(f"invalid transaction journal preimage mtime: {name}")
    return entry


def journal_entry_names(project_root: Path) -> tuple[str, ...]:
    """List exact pending journal names through an anchored directory."""
    try:
        anchor = open_parent_no_follow(
            project_root,
            ".research/presentations/transactions/.journal-anchor",
            create_parents=False,
        )
    except MissingPathError:
        return ()
    try:
        documents = read_regular_siblings(anchor)
        _validate_sibling_modes(anchor, documents)
        return tuple(sorted(documents))
    finally:
        anchor.close()


def encode_journal_document(
    transaction_id: str,
    paths: Sequence[Mapping[str, Any]],
    staged_paths: Sequence[str],
) -> bytes:
    """Encode one deterministic durable transaction journal document."""
    document = {
        "transaction_id": transaction_id,
        "paths": list(paths),
        "staged_paths": sorted(staged_paths),
    }
    return json.dumps(document, sort_keys=True).encode("utf-8")


def matches_regular_snapshot(
    anchor: AnchoredPath,
    content: bytes,
    mode: int,
    mtime_ns: int | None,
) -> bool:
    """Return whether an anchored regular leaf already equals its preimage."""
    metadata = anchor.stat_leaf()
    if metadata is None or not stat.S_ISREG(metadata.st_mode):
        return False
    current, opened = read_stable_regular(anchor)
    return (
        current == content
        and opened.st_mode & 0o777 == mode
        and (mtime_ns is None or opened.st_mtime_ns == mtime_ns)
    )


def publish_journal(
    anchor: AnchoredPath,
    transaction_id: str,
    content: bytes,
    crash: Callable[[str], None],
    *,
    rewrite: bool,
) -> None:
    """Durably publish one canonical journal through a retained directory.

    Args:
        anchor: Retained journal-directory descriptor.
        transaction_id: Exact lowercase hexadecimal transaction identifier.
        content: Canonical journal bytes.
        crash: Test-only boundary callback.
        rewrite: Whether this publication replaces an existing journal.
    """
    temporary = f"{transaction_id}.json.tmp"
    prefix = "rewrite_" if rewrite else ""
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o400,
        dir_fd=anchor.parent_fd,
    )
    try:
        crash(f"{prefix}after_create")
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise OSError("journal publication made no write progress")
            offset += written
        crash(f"{prefix}after_write")
        os.fsync(descriptor)
        crash(f"{prefix}after_first_fsync")
        os.fchmod(descriptor, 0o600)
        crash(f"{prefix}after_chmod")
        os.fsync(descriptor)
        crash(f"{prefix}after_second_fsync")
        crash(f"{prefix}after_fsync")
        crash(f"{prefix}before_rename")
    except Exception:
        os.close(descriptor)
        os.unlink(temporary, dir_fd=anchor.parent_fd)
        anchor.fsync_parent()
        raise
    except BaseException:
        os.close(descriptor)
        raise
    os.close(descriptor)
    os.replace(
        temporary,
        f"{transaction_id}.json",
        src_dir_fd=anchor.parent_fd,
        dst_dir_fd=anchor.parent_fd,
    )
    anchor.fsync_parent()
    crash(f"{prefix}after_rename")


def reconcile_journal_temporaries(
    anchor: AnchoredPath,
    documents: Mapping[str, bytes],
) -> dict[str, bytes]:
    """Reconcile one provable canonical journal publication temporary.

    Args:
        anchor: Retained journal-directory descriptor.
        documents: Stable bytes read through that descriptor.

    Returns:
        Canonical journal documents after durable promotion or cleanup.

    Raises:
        ValueError: If a temporary is malformed, ambiguous, or unsafe.
    """
    result = dict(documents)
    _validate_sibling_modes(anchor, result)
    temporaries = sorted(name for name in result if name.endswith(".tmp"))
    if len(temporaries) > 1:
        raise ValueError("multiple transaction journal temporaries are ambiguous")
    if not temporaries:
        return result
    temporary = temporaries[0]
    match = _JOURNAL_TEMP.fullmatch(temporary)
    if match is None:
        raise ValueError(f"invalid transaction journal temporary name: {temporary}")
    metadata = os.stat(temporary, dir_fd=anchor.parent_fd, follow_symlinks=False)
    mode = metadata.st_mode & 0o777
    if not stat.S_ISREG(metadata.st_mode) or mode not in (0o400, 0o600):
        raise ValueError(f"transaction journal temporary has invalid type or mode: {temporary}")
    content = result[temporary]
    canonical = f"{match.group(1)}.json"
    if mode == 0o400:
        if content:
            transaction_id, _ = _journal_identity(content, temporary)
            if transaction_id != match.group(1):
                raise ValueError(
                    f"transaction journal temporary id does not match name: {temporary}"
                )
        os.unlink(temporary, dir_fd=anchor.parent_fd)
        anchor.fsync_parent()
        del result[temporary]
        return result
    transaction_id, paths = _journal_identity(content, temporary)
    if transaction_id != match.group(1):
        raise ValueError(f"transaction journal temporary id does not match name: {temporary}")
    if canonical in result:
        current_id, current_paths = _journal_identity(result[canonical], canonical)
        if current_id != transaction_id or current_paths != paths:
            raise ValueError(f"transaction journal rewrite is ambiguous: {temporary}")
        os.unlink(temporary, dir_fd=anchor.parent_fd)
        anchor.fsync_parent()
        del result[temporary]
        return result
    os.replace(
        temporary,
        canonical,
        src_dir_fd=anchor.parent_fd,
        dst_dir_fd=anchor.parent_fd,
    )
    anchor.fsync_parent()
    del result[temporary]
    result[canonical] = content
    return result


def _journal_identity(content: bytes, name: str) -> tuple[str, object]:
    """Return immutable publication identity from one complete journal."""
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid transaction journal temporary: {name}") from exc
    transaction_id, paths, staged = validate_journal_fields(document, name)
    for entry in paths:
        validate_preimage_fields(entry, name)
    known = {entry["path"] for entry in paths if isinstance(entry, Mapping)}
    if any(path not in known for path in staged):
        raise ValueError(f"invalid staged journal paths: {name}")
    return transaction_id, paths


def _validate_sibling_modes(
    anchor: AnchoredPath, documents: Mapping[str, bytes]
) -> None:
    """Require canonical names and exact published/incomplete marker modes."""
    for name in documents:
        metadata = os.stat(name, dir_fd=anchor.parent_fd, follow_symlinks=False)
        mode = metadata.st_mode & 0o777
        if _JOURNAL.fullmatch(name) is not None:
            if mode != 0o600:
                raise ValueError(f"published transaction journal mode is invalid: {name}")
        elif _JOURNAL_TEMP.fullmatch(name) is not None:
            if mode not in {0o400, 0o600}:
                raise ValueError(f"transaction journal temporary mode is invalid: {name}")
        else:
            raise ValueError(f"invalid transaction journal filename: {name}")


def remove_staged_siblings(anchored: AnchoredPath) -> None:
    """Remove regular transaction temporaries for one locked target.

    Args:
        anchored: Retained parent and target leaf identity.

    Raises:
        OSError: If a matching sibling is unsafe or cannot be removed.
    """
    prefix = f".{anchored.leaf_name}.transaction."
    for name in os.listdir(anchored.parent_fd):
        if not name.startswith(prefix) or not name.endswith(".tmp"):
            continue
        metadata = os.stat(name, dir_fd=anchored.parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError(f"transaction temporary must be regular: {name}")
        os.unlink(name, dir_fd=anchored.parent_fd)
    anchored.fsync_parent()


def remove_regular_sibling(anchored: AnchoredPath, name: str) -> None:
    """Remove one named regular sibling through a retained parent descriptor."""
    try:
        metadata = os.stat(name, dir_fd=anchored.parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError(f"transaction temporary must be regular: {name}")
    os.unlink(name, dir_fd=anchored.parent_fd)
