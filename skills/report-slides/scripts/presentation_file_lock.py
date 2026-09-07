#!/usr/bin/env python3
"""presentation_file_lock.py -- one exclusive-lock primitive for both platforms.

Every write path in the presentation state store serializes on an exclusive
lock held for a read-modify-write critical section. That lock was `fcntl.flock`
called directly from seven modules, each importing `fcntl` at module scope --
which is POSIX-only, so on Windows those modules raised `ModuleNotFoundError`
on *import*. The store was not merely unable to lock there; it was unable to
load, taking the read, validate and render paths down with it.

This module is the single place that knows how a platform excludes writers:

* POSIX -- `fcntl.flock(fd, LOCK_EX | LOCK_NB)`, an advisory whole-file lock,
  exactly as every call site did before. The behaviour on Linux and macOS is
  unchanged, deliberately: this is a passthrough, not a reimplementation.
* Windows -- `msvcrt.locking(fd, LK_NBLCK, ...)`, a *mandatory* byte-range
  lock. `passport_as_reset_boundary.md` names this as the compliant non-POSIX
  primitive, alongside `portalocker`; `msvcrt` is chosen because it is in the
  standard library and adds no dependency.

Contention is normalized to `EAGAIN` on both platforms so a caller can keep the
one retry idiom the store already uses:

    while True:
        try:
            acquire_exclusive(fd)
            break
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            ...deadline check, then sleep...

Anything else -- a filesystem that refuses locks, a bad descriptor -- keeps its
own errno and propagates, because those are real failures and the callers
already distinguish them from contention.
"""
from __future__ import annotations

import errno
import os
import sys

#: Bytes locked on Windows. `msvcrt.locking` takes a byte range rather than
#: locking the whole file, so the range has to be a constant every participant
#: agrees on; locks may extend past EOF, which is what makes one byte enough
#: for the empty sidecar files the store locks.
_WINDOWS_LOCK_BYTES = 1

#: True when this platform excludes writers through `msvcrt` rather than
#: `fcntl`. Read it instead of re-testing `sys.platform` at call sites.
USES_BYTE_RANGE_LOCKS = sys.platform == "win32"


def acquire_exclusive(descriptor: int) -> None:
    """Take an exclusive lock on `descriptor`, failing immediately if held.

    Args:
        descriptor: An open file descriptor. On Windows the lock covers a
            fixed range at offset 0 and the file position is restored, so the
            caller's position is preserved on both platforms.

    Raises:
        OSError: `EAGAIN` when another holder has the lock -- the signal to
            retry -- and the platform's own errno for any other failure.
    """
    if USES_BYTE_RANGE_LOCKS:
        _acquire_windows(descriptor)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def acquire_exclusive_blocking(descriptor: int) -> None:
    """Wait for an exclusive lock on `descriptor` rather than failing at once.

    The store's own write paths never use this -- they poll `acquire_exclusive`
    against a deadline so a stuck peer surfaces as a timeout. It exists for
    code that genuinely wants to *wait*, such as a test's competing thread that
    must still be blocked when a rollback releases the lock.

    Args:
        descriptor: An open file descriptor.

    Raises:
        OSError: If the wait fails, or -- on Windows only -- if the lock is
            still held when the platform gives up.

    Note:
        The two platforms wait differently. POSIX blocks indefinitely; Windows
        `LK_LOCK` retries ten times at one-second intervals and then raises. A
        caller that must not give up has to loop.
    """
    if USES_BYTE_RANGE_LOCKS:
        _lock_windows_range("LK_LOCK", descriptor)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX)


def release(descriptor: int) -> None:
    """Release the exclusive lock held on `descriptor`.

    Args:
        descriptor: The descriptor passed to a successful `acquire_exclusive`.

    Raises:
        OSError: If the platform refuses the unlock.
    """
    if USES_BYTE_RANGE_LOCKS:
        _release_windows(descriptor)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


def _acquire_windows(descriptor: int) -> None:
    """Take the Windows byte-range lock, normalizing contention to `EAGAIN`.

    Args:
        descriptor: An open file descriptor.

    Raises:
        OSError: `EAGAIN` on contention; the original error otherwise.
    """
    _lock_windows_range("LK_NBLCK", descriptor)


def _lock_windows_range(mode_name: str, descriptor: int) -> None:
    """Apply one `msvcrt.locking` mode over the module's fixed byte range.

    Args:
        mode_name: `"LK_NBLCK"` to fail immediately on contention, or
            `"LK_LOCK"` to let the platform retry before giving up.
        descriptor: An open file descriptor.

    Raises:
        OSError: `EAGAIN` on contention; the original error otherwise.
    """
    import msvcrt

    mode = getattr(msvcrt, mode_name)
    position = os.lseek(descriptor, 0, os.SEEK_CUR)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, mode, _WINDOWS_LOCK_BYTES)
        except OSError as exc:
            # Contention surfaces two ways here and neither means on Windows
            # what it means on POSIX: EDEADLOCK is the documented "could not
            # lock" code, while a measured cross-process attempt against a
            # held lock actually reports EACCES (ERROR_LOCK_VIOLATION mapped
            # through the CRT). Normalize both to the one contention errno the
            # retry loops watch for, and let anything else through untouched.
            #
            # The cost of folding EACCES in is that a genuine permission
            # failure retries until the caller's deadline instead of failing
            # at once. That is bounded, it surfaces as the same
            # LockTimeoutError a stuck peer produces, and POSIX `flock` is
            # equally ambiguous -- it also reports contention as EACCES or
            # EAGAIN -- so the two platforms stay honest about the same thing.
            if exc.errno in (errno.EDEADLOCK, errno.EACCES):
                raise OSError(errno.EAGAIN, "file is locked by another holder") from exc
            raise
    finally:
        os.lseek(descriptor, position, os.SEEK_SET)


def _release_windows(descriptor: int) -> None:
    """Release the Windows byte-range lock over the same fixed range.

    Args:
        descriptor: The descriptor holding the lock.

    Raises:
        OSError: If the unlock is refused.
    """
    import msvcrt

    position = os.lseek(descriptor, 0, os.SEEK_CUR)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, _WINDOWS_LOCK_BYTES)
    finally:
        os.lseek(descriptor, position, os.SEEK_SET)
