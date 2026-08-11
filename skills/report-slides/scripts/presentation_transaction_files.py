"""Narrow anchored ordinary-file primitives for workflow transactions."""

from __future__ import annotations

import os
import json
import re
import stat
from typing import Any, Callable, Mapping, Sequence

from presentation_no_follow import AnchoredPath, read_stable_regular


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
        or not transaction_id
        or not isinstance(entries, list)
        or not entries
        or not isinstance(staged, list)
        or any(not isinstance(item, str) for item in staged)
        or len(staged) != len(set(staged))
    ):
        raise ValueError(f"invalid transaction journal shape: {name}")
    return transaction_id, entries, staged


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
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o400,
        dir_fd=anchor.parent_fd,
    )
    try:
        crash("rewrite_after_create" if rewrite else "after_create")
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise OSError("journal publication made no write progress")
            offset += written
        crash("rewrite_after_write" if rewrite else "after_write")
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        crash("rewrite_after_fsync" if rewrite else "after_fsync")
        crash("rewrite_before_rename" if rewrite else "before_rename")
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
    crash("rewrite_after_rename" if rewrite else "after_rename")


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
    if not isinstance(document, dict):
        raise ValueError(f"invalid transaction journal temporary: {name}")
    transaction_id = document.get("transaction_id")
    paths = document.get("paths")
    if set(document) not in (
        {"transaction_id", "paths"},
        {"transaction_id", "paths", "staged_paths"},
    ):
        raise ValueError(f"invalid transaction journal temporary fields: {name}")
    if not isinstance(transaction_id, str) or not isinstance(paths, list) or not paths:
        raise ValueError(f"invalid transaction journal temporary: {name}")
    if "staged_paths" in document:
        staged = document["staged_paths"]
        known = {
            entry.get("path") for entry in paths
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        }
        if (
            not isinstance(staged, list)
            or any(not isinstance(path, str) or path not in known for path in staged)
            or len(staged) != len(set(staged))
        ):
            raise ValueError(f"invalid staged journal paths: {name}")
    return transaction_id, paths


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
