#!/usr/bin/env python3
"""Anchored no-follow helpers for project-relative file access.

Every path component is opened relative to an already-open directory, and
callers retain that parent across the complete operation, so later pathname
swaps cannot redirect leaf access.

POSIX expresses this with the `openat` family -- `dir_fd=`, `O_NOFOLLOW`,
`O_DIRECTORY`. Windows exposes none of those through the standard library, so
the same operations dispatch to `presentation_win32`, which reaches the NT
layer to get relative opens and link refusal. The dispatch is confined to this
module: the POSIX branches are unchanged, and every caller sees one API.
"""

from __future__ import annotations

import errno
import os
import stat
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import presentation_file_lock

#: True when anchored operations go through the NT backend rather than
#: `openat`. Read this instead of re-testing `sys.platform` at each site.
_WINDOWS = sys.platform == "win32"


#: Journal marker modes. The transaction journal encodes "staged but not yet
#: complete" versus "complete" in the file's *write* bit, and flipping that bit
#: is the protocol's atomic commit point -- a crash before it discards the
#: journal, a crash after it replays the journal.
#:
#: Windows has no POSIX permission bits, but it does have the one bit this
#: protocol actually needs: the read-only attribute. Python surfaces a
#: read-only file as 0o444 and a writable one as 0o666 there, so the two states
#: stay distinguishable and the protocol is unchanged in substance. The POSIX
#: values are left exactly as they were.
INCOMPLETE_MARKER_MODE = 0o444 if sys.platform == "win32" else 0o400
PUBLISHED_MARKER_MODE = 0o666 if sys.platform == "win32" else 0o600


def chmod_at(parent: int, name: str, mode: int) -> None:
    """Set a component's mode relative to its parent, without following a link.

    On Windows only the write bit is representable, as the read-only attribute;
    the rest of `mode` has no meaning there and is ignored.

    Args:
        parent: Parent directory descriptor or HANDLE.
        name: Component to modify.
        mode: POSIX permission bits.
    """
    if _WINDOWS:
        _win32().set_child_readonly(parent, name, readonly=not (mode & 0o200))
        return
    os.chmod(name, mode, dir_fd=parent, follow_symlinks=False)


def _win32():
    """Return the Windows backend module.

    Imported lazily so this module keeps loading on POSIX, where the backend's
    ctypes bindings would have nothing to bind against.

    Returns:
        The `presentation_win32` module.
    """
    import presentation_win32

    return presentation_win32


class NoFollowPathError(RuntimeError):
    """Raised when a path cannot be traversed without following symlinks."""


class MissingPathError(NoFollowPathError):
    """Raised when required no-follow path components do not exist."""


@dataclass
class AnchoredPath:
    """One project-relative leaf anchored by an open parent directory.

    Attributes:
        parent_fd: The leaf's containing directory, held open. On POSIX this is
            a file descriptor; on Windows it is a Windows HANDLE, which only
            this module's Windows branches interpret. The name is kept for both
            because every call site treats it as an opaque token.
        leaf_name: Final path component addressed relative to parent_fd.
        display_path: Absolute lexical path used only for diagnostics.
    """

    parent_fd: int
    leaf_name: str
    display_path: Path

    def close(self) -> None:
        """Close the retained parent descriptor."""
        if _WINDOWS:
            _win32().close_handle(self.parent_fd)
            return
        os.close(self.parent_fd)

    def stat_leaf(self):
        """Return no-follow leaf metadata, or None when it is absent."""
        if _WINDOWS:
            return _win32().stat_child(self.parent_fd, self.leaf_name)
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
        if _WINDOWS:
            return _open_leaf_windows(self.parent_fd, self.leaf_name, flags)
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
        if _WINDOWS:
            _win32().unlink_child(self.parent_fd, self.leaf_name)
            return
        os.unlink(self.leaf_name, dir_fd=self.parent_fd)

    def replace_leaf(self, temporary_name: str) -> None:
        """Atomically replace the anchored leaf from a sibling temporary."""
        if _WINDOWS:
            _win32().rename_child(self.parent_fd, temporary_name, self.leaf_name)
            return
        os.replace(
            temporary_name,
            self.leaf_name,
            src_dir_fd=self.parent_fd,
            dst_dir_fd=self.parent_fd,
        )

    def fsync_parent(self) -> None:
        """Fsync the retained parent directory descriptor."""
        if _WINDOWS:
            # Directory handles are opened writable on Windows precisely so
            # this flush is permitted; see `_open_directory_windows`.
            _win32().flush_directory(self.parent_fd)
            return
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
    presentation_file_lock.release(descriptor)
    os.close(descriptor)


def fsync_directory(path: Path) -> None:
    """Fsync one directory after a visible filesystem change."""
    if _WINDOWS:
        # Writable, because FlushFileBuffers refuses a read-only handle.
        handle = _win32().open_root_directory(str(path), writable=True)
        try:
            _win32().flush_directory(handle)
        finally:
            _win32().close_handle(handle)
        return
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_regular_file(path: Path) -> None:
    """Fsync one regular file without following its leaf symlink."""
    if _WINDOWS:
        # Anchored on the parent so the leaf is still resolved relative to an
        # opened directory rather than re-walked as a string.
        parent = _win32().open_root_directory(str(path.parent))
        try:
            # Writable because Windows refuses to fsync a read-only descriptor.
            handle = _win32().open_child_file(parent, path.name, writable=True)
        finally:
            _win32().close_handle(parent)
        descriptor = _win32().handle_to_descriptor(handle, os.O_RDWR)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise NoFollowPathError(f"fsync target must be a regular file: {path}")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return
    if not hasattr(os, "O_NOFOLLOW"):
        raise NoFollowPathError(f"file fsync requires os.O_NOFOLLOW: {path}")
    descriptor = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise NoFollowPathError(f"fsync target must be a regular file: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def open_leaf_at_path(path: Path, flags: int, mode: int = 0o666) -> int:
    """Open one absolute path's leaf without following it, on either platform.

    For call sites that hold an absolute path rather than an anchor. The leaf
    is still resolved relative to an opened handle for its parent, so it is not
    a plain path open with a different name.

    Args:
        path: Absolute path whose final component should be opened.
        flags: POSIX open flags (`O_RDONLY`, `O_RDWR | O_CREAT`, and
            `O_WRONLY | O_CREAT | O_EXCL` are the combinations in use).
        mode: Creation mode, applied on POSIX only.

    Returns:
        An open file descriptor.

    Raises:
        NoFollowPathError: If the leaf is a link, or cannot be opened safely.
    """
    if _WINDOWS:
        parent = _win32().open_root_directory(str(path.parent))
        try:
            return _open_leaf_windows(parent, path.name, flags)
        finally:
            _win32().close_handle(parent)
    if not hasattr(os, "O_NOFOLLOW"):
        raise NoFollowPathError(f"anchored access requires os.O_NOFOLLOW: {path}")
    return os.open(str(path), flags | os.O_NOFOLLOW, mode)


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
    if _WINDOWS:
        return _walk_parent_windows(
            _open_directory_windows(root), root, parts, create_parents=create_parents
        )
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
    if _WINDOWS:
        # Mirrors the POSIX `os.dup` below: the walk consumes one copy while
        # the caller's anchor keeps its own. NT has no "." entry to reopen a
        # directory through, so duplicating the handle is the faithful move.
        base = _win32().duplicate_handle(directory_anchor.parent_fd)
        return _walk_parent_windows(
            base,
            directory_anchor.display_path.parent,
            parts,
            create_parents=create_parents,
        )
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
    for name in list_children_at(directory_anchor.parent_fd):
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
            unlink_at(anchored.parent_fd, temporary_name)
        except (FileNotFoundError, MissingPathError):
            pass
        raise
    anchored.fsync_parent()
    if mtime_ns is not None:
        if _WINDOWS:
            _win32().set_child_times(
                anchored.parent_fd, anchored.leaf_name, mtime_ns
            )
        else:
            os.utime(
                anchored.leaf_name,
                ns=(mtime_ns, mtime_ns),
                dir_fd=anchored.parent_fd,
                follow_symlinks=False,
            )
        _fsync_leaf(anchored)
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
        # Windows carries no POSIX permission bits, so there is nothing to
        # apply there; `mode` stays meaningful only on POSIX.
        if not _WINDOWS:
            applied_mode = (
                mode if exact_mode else os.fstat(descriptor).st_mode & 0o777
            )
            os.fchmod(descriptor, applied_mode)
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        try:
            unlink_at(anchored.parent_fd, temporary_name)
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
    existing = stat_at_optional(anchored.parent_fd, lock_name)
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
                presentation_file_lock.acquire_exclusive(descriptor)
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
    if _WINDOWS:
        return _open_leaf_windows(anchored.parent_fd, name, flags)
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


def _fsync_leaf(anchored: AnchoredPath) -> None:
    """Flush an anchored leaf's contents to disk.

    POSIX will fsync a read-only descriptor; Windows will not -- its `_commit`
    needs write access and reports EBADF otherwise -- so the descriptor is
    opened read-write there. Nothing is written through it either way.

    Args:
        anchored: The leaf to flush.
    """
    descriptor = anchored.open_leaf(os.O_RDWR if _WINDOWS else os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _open_directory_windows(path: Path) -> int:
    """Open a directory as a traversal anchor on Windows.

    Opened writable because `fsync_parent` maps to `FlushFileBuffers`, which
    refuses a read-only handle -- the durability step would otherwise fail as
    an access error long after this point.

    Args:
        path: Absolute directory path.

    Returns:
        A directory HANDLE.

    Raises:
        NoFollowPathError: If the directory cannot be opened safely.
    """
    return _win32().open_root_directory(str(path), writable=True)


def _walk_parent_windows(
    current: int,
    display_root: Path,
    parts: tuple[str, ...],
    *,
    create_parents: bool,
) -> AnchoredPath:
    """Walk parent components from an owned Windows directory handle.

    The Windows twin of `_walk_parent`: same contract, same ownership rule
    (the handle is closed on any failure), same refusal of a linked component.

    Args:
        current: Owned directory HANDLE to start from.
        display_root: Lexical path used only for diagnostics.
        parts: Canonical components, the last being the leaf.
        create_parents: Whether missing parent components should be created.

    Returns:
        An anchored leaf whose parent handle stays open.

    Raises:
        MissingPathError: If a parent is absent and `create_parents` is false.
        NoFollowPathError: If a component is a link or not a directory.
    """
    display_path = display_root.joinpath(*parts)
    win32 = _win32()
    try:
        for component in parts[:-1]:
            if create_parents:
                win32.make_child_directory(current, component)
            next_handle = win32.open_child_directory(current, component, writable=True)
            win32.close_handle(current)
            current = next_handle
        return AnchoredPath(current, parts[-1], display_path)
    except BaseException:
        win32.close_handle(current)
        raise


def _open_leaf_windows(parent: int, name: str, flags: int) -> int:
    """Open an anchored leaf on Windows and bridge it to a descriptor.

    The store passes POSIX open flags, and only three combinations ever reach
    here: read-only, `O_RDWR | O_CREAT` for a sidecar, and
    `O_WRONLY | O_CREAT | O_EXCL` for a staging temporary. They are translated
    rather than reimplemented, and the result is a real file descriptor so
    `os.read`, `os.write`, `os.fstat` and the byte-range locks all keep working.

    Args:
        parent: Directory HANDLE containing the leaf.
        name: Leaf component.
        flags: POSIX open flags.

    Returns:
        A file descriptor owning the opened handle.

    Raises:
        NoFollowPathError: If the leaf is a link or cannot be opened.
    """
    writable = bool(flags & (os.O_WRONLY | os.O_RDWR))
    handle = _win32().open_child_file(
        parent,
        name,
        writable=writable,
        create=bool(flags & os.O_CREAT),
        exclusive=bool(flags & os.O_EXCL),
    )
    return _win32().handle_to_descriptor(
        handle, os.O_RDWR if writable else os.O_RDONLY
    )


def unlink_at(parent: int, name: str) -> None:
    """Delete one component relative to its parent, on either platform.

    Args:
        parent: Parent directory descriptor or HANDLE.
        name: Component to delete.
    """
    if _WINDOWS:
        _win32().unlink_child(parent, name)
        return
    os.unlink(name, dir_fd=parent)


def stat_at(parent: int, name: str):
    """Stat one component relative to its parent, without following a link.

    Matches `os.stat(..., dir_fd=..., follow_symlinks=False)` exactly, raising
    for a missing component. Callers that treat absence as a normal outcome
    want `stat_at_optional` -- the distinction matters, because a caller that
    goes on to read `.st_mode` needs the exception, not a `None`.

    Args:
        parent: Parent directory descriptor or HANDLE.
        name: Component to describe.

    Returns:
        Metadata for the component.

    Raises:
        FileNotFoundError: If the component does not exist.
    """
    if _WINDOWS:
        metadata = _win32().stat_child(parent, name)
        if metadata is None:
            raise FileNotFoundError(
                errno.ENOENT, "no such file or directory", name
            )
        return metadata
    return os.stat(name, dir_fd=parent, follow_symlinks=False)


def stat_at_optional(parent: int, name: str):
    """Stat one component, reporting absence as None rather than raising.

    Args:
        parent: Parent directory descriptor or HANDLE.
        name: Component to describe.

    Returns:
        Metadata for the component, or None when it does not exist.
    """
    try:
        return stat_at(parent, name)
    except FileNotFoundError:
        return None


def replace_at(parent: int, source_name: str, target_name: str) -> None:
    """Atomically rename one component onto another within a parent.

    Args:
        parent: Parent directory descriptor or HANDLE holding both names.
        source_name: Existing component.
        target_name: Component to replace.
    """
    if _WINDOWS:
        _win32().rename_child(parent, source_name, target_name)
        return
    os.replace(source_name, target_name, src_dir_fd=parent, dst_dir_fd=parent)


def open_at(parent: int, name: str, flags: int, mode: int = 0o666) -> int:
    """Open one component relative to a parent, without following a link.

    Args:
        parent: Parent directory descriptor or HANDLE.
        name: Component to open.
        flags: POSIX open flags.
        mode: Creation mode, applied on POSIX only.

    Returns:
        An open file descriptor.

    Raises:
        NoFollowPathError: If no-follow support is missing or the leaf is a link.
    """
    if _WINDOWS:
        return _open_leaf_windows(parent, name, flags)
    if not hasattr(os, "O_NOFOLLOW"):
        raise NoFollowPathError(f"anchored access requires os.O_NOFOLLOW: {name}")
    return os.open(name, flags | os.O_NOFOLLOW, mode, dir_fd=parent)


def list_children_at(parent: int) -> list[str]:
    """List a retained directory's entries, on either platform.

    Args:
        parent: Parent directory descriptor or HANDLE.

    Returns:
        Entry names, excluding `.` and `..`.
    """
    if _WINDOWS:
        return _win32().list_children(parent)
    return os.listdir(parent)


def _file_identity(metadata) -> tuple[int, int, int, int, int]:
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
