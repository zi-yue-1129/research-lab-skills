#!/usr/bin/env python3
"""POSIX directory-FD helpers for no-follow project-relative file access.

Every path component is opened relative to an already-open directory
descriptor. Callers retain the returned parent descriptor across the complete
operation so later pathname swaps cannot redirect leaf access.
"""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class NoFollowPathError(RuntimeError):
    """Raised when a path cannot be traversed without following symlinks."""


class MissingPathError(NoFollowPathError):
    """Raised when required no-follow path components do not exist."""


@dataclass
class AnchoredPath:
    """One project-relative leaf anchored by an open parent directory.

    Attributes:
        parent_fd: Open descriptor for the leaf's containing directory.
        leaf_name: Final path component addressed relative to parent_fd.
        display_path: Absolute lexical path used only for diagnostics.
    """

    parent_fd: int
    leaf_name: str
    display_path: Path

    def close(self) -> None:
        """Close the retained parent descriptor."""
        os.close(self.parent_fd)

    def stat_leaf(self) -> os.stat_result | None:
        """Return no-follow leaf metadata, or None when it is absent."""
        try:
            return os.stat(
                self.leaf_name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return None

    def open_leaf(self, flags: int, mode: int = 0o777) -> int:
        """Open the leaf relative to the retained parent without following it.

        Args:
            flags: POSIX flags for os.open.
            mode: Creation mode used when flags includes O_CREAT.

        Returns:
            The opened leaf descriptor.

        Raises:
            NoFollowPathError: If no-follow support is unavailable or the leaf
                cannot be opened safely.
        """
        if not hasattr(os, "O_NOFOLLOW"):
            raise NoFollowPathError(
                f"os.O_NOFOLLOW is required for anchored access: {self.display_path}"
            )
        try:
            return os.open(
                self.leaf_name,
                flags | os.O_NOFOLLOW,
                mode,
                dir_fd=self.parent_fd,
            )
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EISDIR, errno.ENOTDIR):
                raise NoFollowPathError(
                    f"leaf must be a no-follow regular path: {self.display_path}"
                ) from exc
            raise

    def unlink_leaf(self) -> None:
        """Unlink the anchored leaf without resolving its display path."""
        os.unlink(self.leaf_name, dir_fd=self.parent_fd)

    def replace_leaf(self, temporary_name: str) -> None:
        """Atomically replace the anchored leaf from a sibling temporary."""
        os.replace(
            temporary_name,
            self.leaf_name,
            src_dir_fd=self.parent_fd,
            dst_dir_fd=self.parent_fd,
        )

    def fsync_parent(self) -> None:
        """Fsync the retained parent directory descriptor."""
        os.fsync(self.parent_fd)


def sidecar_path(path: Path) -> Path:
    """Return the stable sibling sidecar path for one data file."""
    return path.with_suffix(path.suffix + ".lock")


def temporary_path(path: Path) -> Path:
    """Return a unique same-directory transaction staging path."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return path.with_name(f".{path.name}.transaction.{stamp}.{uuid.uuid4().hex[:8]}.tmp")


def release_sidecar(descriptor: int) -> None:
    """Release and close one locked sidecar descriptor."""
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)


def fsync_directory(path: Path) -> None:
    """Fsync one directory after a visible filesystem change."""
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_regular_file(path: Path) -> None:
    """Fsync one regular file without following its leaf symlink."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise NoFollowPathError(f"file fsync requires os.O_NOFOLLOW: {path}")
    descriptor = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise NoFollowPathError(f"fsync target must be a regular file: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def open_parent_no_follow(
    project_root: Path,
    relative_path: str,
    *,
    create_parents: bool,
) -> AnchoredPath:
    """Anchor a canonical relative leaf through directory-FD traversal.

    Args:
        project_root: Existing absolute or resolvable project directory.
        relative_path: Canonical project-relative POSIX leaf path.
        create_parents: Whether missing parent components should be created.

    Returns:
        An anchored leaf whose parent descriptor remains open.

    Raises:
        NoFollowPathError: If the path is noncanonical, a directory component
            is a symlink or non-directory, or required POSIX flags are absent.
    """
    parts = _canonical_parts(relative_path)
    root = project_root.resolve()
    directory_flags = _directory_flags()
    try:
        current_fd = os.open(str(root), directory_flags)
    except OSError as exc:
        raise NoFollowPathError(
            f"cannot open project root without following symlinks: {root}"
        ) from exc
    return _walk_parent(
        current_fd,
        root,
        parts,
        directory_flags,
        create_parents=create_parents,
    )


def open_parent_beneath(
    directory_anchor: AnchoredPath,
    relative_path: str,
    *,
    create_parents: bool,
) -> AnchoredPath:
    """Anchor a relative leaf beneath an already-retained directory.

    Args:
        directory_anchor: Anchor whose parent descriptor is the trusted base.
        relative_path: Canonical POSIX path relative to that base directory.
        create_parents: Whether missing parent components should be created.

    Returns:
        An anchored leaf beneath the same retained directory hierarchy.
    """
    parts = _canonical_parts(relative_path)
    current_fd = os.dup(directory_anchor.parent_fd)
    return _walk_parent(
        current_fd,
        directory_anchor.display_path.parent,
        parts,
        _directory_flags(),
        create_parents=create_parents,
    )


def read_regular_siblings(directory_anchor: AnchoredPath) -> dict[str, bytes]:
    """Read every regular sibling through one retained directory descriptor.

    Args:
        directory_anchor: Anchor whose parent directory should be enumerated.

    Returns:
        A name-to-bytes map for every directory entry.

    Raises:
        NoFollowPathError: If an entry is not a stable regular no-follow file.
    """
    contents: dict[str, bytes] = {}
    for name in os.listdir(directory_anchor.parent_fd):
        _require_leaf_name(name)
        sibling = AnchoredPath(
            directory_anchor.parent_fd,
            name,
            directory_anchor.display_path.with_name(name),
        )
        metadata = sibling.stat_leaf()
        if metadata is None or not stat.S_ISREG(metadata.st_mode):
            raise NoFollowPathError(
                f"journal child must be a regular no-follow file: {sibling.display_path}"
            )
        contents[name], _ = read_stable_regular(sibling)
    return contents


def read_stable_regular(anchored: AnchoredPath) -> tuple[bytes, os.stat_result]:
    """Read a stable regular leaf through its retained parent descriptor.

    Args:
        anchored: Anchored leaf to read.

    Returns:
        Exact content and opened-file metadata.

    Raises:
        NoFollowPathError: If the leaf is not regular or changes while read.
    """
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = anchored.open_leaf(flags)
    except OSError as exc:
        raise NoFollowPathError(
            f"cannot open regular leaf safely: {anchored.display_path}"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise NoFollowPathError(
                f"leaf must be a regular file: {anchored.display_path}"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        closed = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    content = b"".join(chunks)
    opened_identity = _file_identity(opened)
    if opened_identity != _file_identity(closed) or len(content) != opened.st_size:
        raise NoFollowPathError(f"leaf changed while reading: {anchored.display_path}")
    return content, opened


def restore_regular(
    anchored: AnchoredPath,
    temporary_name: str,
    *,
    exists: bool,
    content: bytes,
    mode: int,
    mtime_ns: int | None,
) -> None:
    """Restore one exact regular-file preimage through an anchored parent.

    Args:
        anchored: Retained parent and target leaf.
        temporary_name: Unique sibling used for atomic replacement.
        exists: Whether the preimage target existed.
        content: Exact preimage bytes.
        mode: Exact preimage permission bits.
        mtime_ns: Optional exact preimage modification time.

    Raises:
        NoFollowPathError: If an existing target is not a regular file.
        OSError: If restoration or durability synchronization fails.
    """
    metadata = anchored.stat_leaf()
    if metadata is not None and not stat.S_ISREG(metadata.st_mode):
        raise NoFollowPathError(
            f"recovery target must be a regular no-follow file: {anchored.display_path}"
        )
    if not exists:
        if metadata is not None:
            anchored.unlink_leaf()
            anchored.fsync_parent()
        return
    try:
        write_bytes_at(
            anchored,
            temporary_name,
            content,
            mode,
            exact_mode=True,
        )
        anchored.replace_leaf(temporary_name)
    except BaseException:
        try:
            os.unlink(temporary_name, dir_fd=anchored.parent_fd)
        except FileNotFoundError:
            pass
        raise
    anchored.fsync_parent()
    if mtime_ns is not None:
        os.utime(
            anchored.leaf_name,
            ns=(mtime_ns, mtime_ns),
            dir_fd=anchored.parent_fd,
            follow_symlinks=False,
        )
        descriptor = anchored.open_leaf(os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        anchored.fsync_parent()


def write_bytes_at(
    anchored: AnchoredPath,
    temporary_name: str,
    content: bytes,
    mode: int,
    *,
    exact_mode: bool,
) -> None:
    """Write, chmod, and fsync one fresh sibling through a parent descriptor.

    Args:
        anchored: Retained parent directory for the temporary sibling.
        temporary_name: Canonical single-component temporary name.
        content: Exact bytes to write.
        mode: Requested creation mode.
        exact_mode: Whether mode must override the process umask exactly.

    Raises:
        OSError: If creation, writing, chmod, or fsync fails.
        NoFollowPathError: If temporary_name is not one path component.
    """
    _require_leaf_name(temporary_name)
    descriptor = _open_sibling(
        anchored,
        temporary_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        mode,
    )
    try:
        _write_all(descriptor, content, anchored.display_path)
        applied_mode = mode if exact_mode else os.fstat(descriptor).st_mode & 0o777
        os.fchmod(descriptor, applied_mode)
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=anchored.parent_fd)
        except OSError:
            pass
        raise
    os.close(descriptor)
    anchored.fsync_parent()


def acquire_sidecar(anchored: AnchoredPath, timeout_seconds: int) -> int:
    """Open and exclusively lock a stable anchored sidecar.

    Args:
        anchored: CAS object whose sibling sidecar must be locked.
        timeout_seconds: Maximum nonnegative lock wait in seconds.

    Returns:
        The locked regular sidecar descriptor.

    Raises:
        NoFollowPathError: If the sidecar is unsafe or the lock times out.
    """
    lock_name = anchored.leaf_name + ".lock"
    try:
        existing = os.stat(
            lock_name,
            dir_fd=anchored.parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        existing = None
    if existing is not None and not stat.S_ISREG(existing.st_mode):
        raise NoFollowPathError(
            f"sidecar must be a regular no-follow file: {anchored.display_path}.lock"
        )
    try:
        descriptor = _open_sibling(
            anchored,
            lock_name,
            os.O_RDWR | os.O_CREAT,
            0o666,
        )
    except OSError as exc:
        raise NoFollowPathError(
            f"cannot open sidecar safely: {anchored.display_path}.lock"
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise NoFollowPathError(
                f"sidecar must be regular: {anchored.display_path}.lock"
            )
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return descriptor
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise NoFollowPathError(
                        f"could not acquire sidecar within {timeout_seconds}s: "
                        f"{anchored.display_path}.lock"
                    ) from exc
                time.sleep(0.05)
    except BaseException:
        os.close(descriptor)
        raise


def _open_sibling(
    anchored: AnchoredPath,
    name: str,
    flags: int,
    mode: int,
) -> int:
    """Open one sibling without following its leaf."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise NoFollowPathError(
            f"os.O_NOFOLLOW is required for anchored access: {anchored.display_path}"
        )
    return os.open(
        name,
        flags | os.O_NOFOLLOW,
        mode,
        dir_fd=anchored.parent_fd,
    )


def _write_all(descriptor: int, content: bytes, display_path: Path) -> None:
    """Write every byte or fail explicitly on a zero-length write."""
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written <= 0:
            raise OSError(f"short write while staging {display_path}")
        offset += written


def _walk_parent(
    current_fd: int,
    display_root: Path,
    parts: tuple[str, ...],
    directory_flags: int,
    *,
    create_parents: bool,
) -> AnchoredPath:
    """Walk parent components from an owned starting directory descriptor."""
    display_path = display_root.joinpath(*parts)
    try:
        if not stat.S_ISDIR(os.fstat(current_fd).st_mode):
            raise NoFollowPathError(
                f"anchored root must be a directory: {display_root}"
            )
        for component in parts[:-1]:
            if create_parents:
                try:
                    os.mkdir(component, mode=0o777, dir_fd=current_fd)
                except FileExistsError:
                    pass
            try:
                next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            except OSError as exc:
                if exc.errno == errno.ENOENT and not create_parents:
                    raise MissingPathError(
                        f"missing directory component: {display_path}"
                    ) from exc
                if exc.errno in (errno.ELOOP, errno.ENOTDIR, errno.EACCES):
                    raise NoFollowPathError(
                        "directory component must be no-follow and regular: "
                        f"{display_path}"
                    ) from exc
                raise
            os.close(current_fd)
            current_fd = next_fd
        return AnchoredPath(current_fd, parts[-1], display_path)
    except BaseException:
        os.close(current_fd)
        raise


def _file_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    """Return fields that reveal replacement or mutation during a read."""
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _canonical_parts(relative_path: str) -> tuple[str, ...]:
    """Return exact canonical POSIX components for one relative leaf path."""
    if (
        not isinstance(relative_path, str)
        or not relative_path
        or relative_path.startswith("/")
        or "\\" in relative_path
        or "\x00" in relative_path
    ):
        raise NoFollowPathError(
            f"path must be canonical project-relative POSIX text: {relative_path!r}"
        )
    parts = tuple(relative_path.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise NoFollowPathError(
            f"path must be canonical project-relative POSIX text: {relative_path!r}"
        )
    return parts


def _require_leaf_name(name: str) -> None:
    """Require one canonical leaf component."""
    if not name or name in {".", ".."} or "/" in name or "\\" in name or "\x00" in name:
        raise NoFollowPathError(
            f"temporary name must be one canonical component: {name!r}"
        )


def _directory_flags() -> int:
    """Return required flags for retained no-follow directory descriptors."""
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise NoFollowPathError(
            "POSIX O_DIRECTORY and O_NOFOLLOW are required for anchored traversal"
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags
