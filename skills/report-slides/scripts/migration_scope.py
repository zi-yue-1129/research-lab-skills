#!/usr/bin/env python3
"""Filesystem scope guards shared by presentation-state migration."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Iterator


class MigrationError(RuntimeError):
    """Raised when a migration scope contains unsafe filesystem entries."""


def iter_scope_entries(root: Path) -> Iterator[Path]:
    """Yield regular files directly below ``root`` while rejecting extras."""
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
    """Reject a state/event scope whose parent path redirects elsewhere."""
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
