#!/usr/bin/env python3
"""presentation_win32.py -- POSIX anchored-traversal primitives, on Windows.

`presentation_no_follow` defends the state store against a symlink swapped in
mid-write. It does that by never re-resolving a path string: each component is
opened *relative to a descriptor for the directory that contains it*, so an
attacker who replaces a component after it was resolved cannot redirect the
next operation. The primitives are `openat(2)` and `O_NOFOLLOW`, and both are
POSIX-only -- `os.supports_dir_fd` is empty on Windows and `os.O_NOFOLLOW`
does not exist there. That is why the whole store was unavailable on Windows,
not merely unlockable.

Windows can do this; the standard library just does not expose it. The Win32
layer has no relative open, but the NT layer underneath it does, and this
module binds exactly the calls that reproduce the POSIX semantics:

    openat(dir_fd, name)  ->  NtCreateFile with OBJECT_ATTRIBUTES.RootDirectory
    O_NOFOLLOW            ->  FILE_OPEN_REPARSE_POINT, then verify the handle
    st_dev / st_ino       ->  dwVolumeSerialNumber / nFileIndexHigh:Low

The `O_NOFOLLOW` mapping is not literal, and the difference matters. POSIX
`O_NOFOLLOW` *fails* with `ELOOP` when the final component is a symlink;
`FILE_OPEN_REPARSE_POINT` *succeeds*, handing back the link object itself
instead of its target. Reproducing the POSIX contract therefore takes two
steps: open the reparse point, then ask the resulting handle whether it is one
and refuse if so. That check is not a TOCTOU window -- it interrogates the
object already opened, never a path that could be swapped underneath it, which
is the same property the POSIX version relies on.

Every function raises `NoFollowPathError` (imported from the module this one
serves) so callers handle one error type across platforms.

Windows only. Importing this module elsewhere raises at call time, not import
time, so `presentation_no_follow` can import it unconditionally.
"""
from __future__ import annotations

import ctypes
import errno
import os
import sys
from ctypes import wintypes
from typing import Tuple

#: NT status codes this module maps onto POSIX errno values.
_STATUS_SUCCESS = 0x00000000
_STATUS_NOT_A_DIRECTORY = 0xC0000103
_STATUS_OBJECT_NAME_NOT_FOUND = 0xC0000034
_STATUS_OBJECT_PATH_NOT_FOUND = 0xC000003A
_STATUS_OBJECT_NAME_COLLISION = 0xC0000035
_STATUS_ACCESS_DENIED = 0xC0000022

#: `NtCreateFile` DesiredAccess bits.
_DELETE = 0x00010000
_SYNCHRONIZE = 0x00100000
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000

#: ShareAccess. The store's readers and writers coordinate through the file
#: lock, not through Windows share modes, so sharing stays fully open and the
#: lock keeps its position as the single exclusion mechanism.
_FILE_SHARE_ALL = 0x07

#: CreateDisposition.
_FILE_OPEN = 1
_FILE_CREATE = 2
_FILE_OPEN_IF = 3

#: CreateOptions.
_FILE_DIRECTORY_FILE = 0x00000001
_FILE_SYNCHRONOUS_IO_NONALERT = 0x00000020
_FILE_NON_DIRECTORY_FILE = 0x00000040
_FILE_OPEN_REPARSE_POINT = 0x00200000

#: ObjectAttributes.
_OBJ_CASE_INSENSITIVE = 0x00000040

#: File attribute marking an object as a link of some kind.
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010

#: `NtSetInformationFile` information classes.
_FILE_RENAME_INFORMATION_CLASS = 10
_FILE_DISPOSITION_INFORMATION_CLASS = 13

#: The `\??\` prefix that reaches the Win32 namespace from the NT namespace.
_NT_PREFIX = chr(92) + "??" + chr(92)

#: 100-nanosecond intervals between the FILETIME epoch (1601) and the Unix one.
_FILETIME_EPOCH_DELTA = 116_444_736_000_000_000

_ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", wintypes.LPWSTR),
    ]


class _OBJECT_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.POINTER(_UNICODE_STRING)),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    ]


class _IO_STATUS_BLOCK(ctypes.Structure):
    _fields_ = [("Status", ctypes.c_long), ("Information", _ULONG_PTR)]


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


def _bind() -> Tuple[ctypes.WinDLL, ctypes.WinDLL]:
    """Load ntdll and kernel32 with argument types declared.

    Declaring `argtypes` is not optional on 64-bit Windows: without it ctypes
    marshals handle-sized arguments as C `int` and silently truncates them,
    which fails in ways that look like corrupt paths rather than bad calls.

    Returns:
        The bound `(ntdll, kernel32)` libraries.

    Raises:
        NoFollowPathError: If this platform is not Windows.
    """
    if sys.platform != "win32":  # pragma: no cover - platform guard
        from presentation_no_follow import NoFollowPathError

        raise NoFollowPathError(
            f"NT anchored traversal requires Windows (host platform: {sys.platform})"
        )

    ntdll = ctypes.WinDLL("ntdll")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    ntdll.NtCreateFile.restype = ctypes.c_long
    ntdll.NtCreateFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(_OBJECT_ATTRIBUTES),
        ctypes.POINTER(_IO_STATUS_BLOCK),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]
    ntdll.NtSetInformationFile.restype = ctypes.c_long
    ntdll.NtSetInformationFile.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_IO_STATUS_BLOCK),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION),
    ]
    kernel32.FlushFileBuffers.restype = wintypes.BOOL
    kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return ntdll, kernel32


_NTDLL, _KERNEL32 = (_bind() if sys.platform == "win32" else (None, None))


def _unicode_string(name: str) -> Tuple[_UNICODE_STRING, ctypes.Array]:
    """Build a `UNICODE_STRING` and the buffer it points at.

    `RtlInitUnicodeString` stores a pointer rather than copying, so the buffer
    must outlive the call. Returning it forces the caller to keep it alive --
    letting it be collected produces a garbage path, not an error.

    Args:
        name: The path component or absolute NT path.

    Returns:
        The structure and the buffer that backs it.
    """
    buffer = ctypes.create_unicode_buffer(name)
    value = _UNICODE_STRING()
    value.Length = len(name) * 2
    value.MaximumLength = value.Length + 2
    value.Buffer = ctypes.cast(buffer, wintypes.LPWSTR)
    return value, buffer


def _raise_for_status(status: int, name: str, *, missing_is_error: bool = True) -> None:
    """Translate an NT status into the exception the store expects.

    Args:
        status: The `NTSTATUS` returned by an ntdll call.
        name: Component name, for the message.
        missing_is_error: When false, a missing object raises `MissingPathError`
            rather than the generic no-follow error.

    Raises:
        MissingPathError: When the object does not exist.
        NoFollowPathError: For every other failure.
    """
    if status == _STATUS_SUCCESS:
        return

    from presentation_no_follow import MissingPathError, NoFollowPathError

    unsigned = status & 0xFFFFFFFF
    if unsigned in (_STATUS_OBJECT_NAME_NOT_FOUND, _STATUS_OBJECT_PATH_NOT_FOUND):
        if missing_is_error:
            raise MissingPathError(f"missing path component: {name}")
        raise FileNotFoundError(errno.ENOENT, "no such file or directory", name)
    if unsigned == _STATUS_NOT_A_DIRECTORY:
        raise NoFollowPathError(f"path component is not a directory: {name}")
    if unsigned == _STATUS_OBJECT_NAME_COLLISION:
        raise FileExistsError(errno.EEXIST, "file exists", name)
    if unsigned == _STATUS_ACCESS_DENIED:
        raise PermissionError(errno.EACCES, "access denied", name)
    raise NoFollowPathError(f"anchored open failed for {name}: 0x{unsigned:08X}")


def _nt_open(
    name: str,
    root: int | None,
    *,
    directory: bool | None,
    writable: bool = False,
    disposition: int = _FILE_OPEN,
    deletable: bool = False,
    missing_is_error: bool = True,
    refuse_links: bool = True,
) -> int:
    """Open `name` relative to the `root` handle -- the `openat(2)` equivalent.

    Args:
        name: One path component, or an absolute NT path when `root` is None.
        root: Handle for the containing directory, or None for an absolute open.
        directory: Require a directory (mirrors `O_DIRECTORY`), require a
            non-directory, or `None` to accept either -- which is what a stat
            needs, since it must describe whatever is actually there.
        writable: Request write access.
        disposition: NT `CreateDisposition`.
        deletable: Also request `DELETE`, needed to rename or unlink the object.
        missing_is_error: Passed through to the status translation.
        refuse_links: Reproduce `O_NOFOLLOW` by rejecting a link once opened.
            `stat_child` turns this off, because its whole job is to *report*
            that a component is a link rather than to refuse it.

    Returns:
        The opened Windows handle as an int.

    Raises:
        NoFollowPathError: If the open fails, or the opened object is a link.
    """
    name_string, keepalive = _unicode_string(name)
    attributes = _OBJECT_ATTRIBUTES()
    attributes.Length = ctypes.sizeof(_OBJECT_ATTRIBUTES)
    attributes.RootDirectory = wintypes.HANDLE(root) if root is not None else None
    attributes.ObjectName = ctypes.pointer(name_string)
    attributes.Attributes = _OBJ_CASE_INSENSITIVE
    attributes.SecurityDescriptor = None
    attributes.SecurityQualityOfService = None

    access = _GENERIC_READ | _SYNCHRONIZE
    if writable:
        access |= _GENERIC_WRITE
    if deletable:
        access |= _DELETE

    options = _FILE_SYNCHRONOUS_IO_NONALERT | _FILE_OPEN_REPARSE_POINT
    if directory is True:
        options |= _FILE_DIRECTORY_FILE
    elif directory is False:
        options |= _FILE_NON_DIRECTORY_FILE

    handle = wintypes.HANDLE()
    status_block = _IO_STATUS_BLOCK()
    status = _NTDLL.NtCreateFile(
        ctypes.byref(handle),
        access,
        ctypes.byref(attributes),
        ctypes.byref(status_block),
        None,
        0,
        _FILE_SHARE_ALL,
        disposition,
        options,
        None,
        0,
    )
    del keepalive
    _raise_for_status(status, name, missing_is_error=missing_is_error)

    opened = handle.value
    if not refuse_links:
        return opened
    # POSIX O_NOFOLLOW refuses a link; FILE_OPEN_REPARSE_POINT returns one. Ask
    # the handle what it actually opened and refuse to match POSIX. Interrogating
    # the opened object -- not the path -- is what keeps this free of a race.
    try:
        if _is_reparse_point(opened):
            from presentation_no_follow import NoFollowPathError

            raise NoFollowPathError(
                f"path component must be no-follow and regular: {name}"
            )
    except BaseException:
        close_handle(opened)
        raise
    return opened


def _is_reparse_point(handle: int) -> bool:
    """Report whether an opened handle refers to a link.

    Args:
        handle: An open Windows handle.

    Returns:
        True when the object carries the reparse-point attribute.
    """
    return bool(_handle_information(handle).dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _handle_information(handle: int) -> _BY_HANDLE_FILE_INFORMATION:
    """Read the metadata block for an open handle.

    Args:
        handle: An open Windows handle.

    Returns:
        The populated information structure.

    Raises:
        OSError: If the query fails.
    """
    information = _BY_HANDLE_FILE_INFORMATION()
    if not _KERNEL32.GetFileInformationByHandle(
        wintypes.HANDLE(handle), ctypes.byref(information)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return information


def open_root_directory(path: str, *, writable: bool = False) -> int:
    """Open an absolute directory as the anchor for a traversal.

    Args:
        path: Absolute Win32 path of the project root.
        writable: Request write access, which `flush_directory` requires.

    Returns:
        A directory handle the caller must pass to `close_handle`.

    Raises:
        NoFollowPathError: If the path is not an openable, non-link directory.
    """
    return _nt_open(_NT_PREFIX + path, None, directory=True, writable=writable)


def open_child_directory(parent: int, name: str, *, writable: bool = False) -> int:
    """Open one directory component relative to its parent handle.

    Args:
        parent: Handle for the containing directory.
        name: A single component.
        writable: Request write access, which `flush_directory` requires.

    Returns:
        The child directory handle.

    Raises:
        MissingPathError: If the component does not exist.
        NoFollowPathError: If it is a link or not a directory.
    """
    return _nt_open(name, parent, directory=True, writable=writable)


def open_child_file(
    parent: int,
    name: str,
    *,
    writable: bool = False,
    create: bool = False,
    deletable: bool = False,
) -> int:
    """Open one file component relative to its parent handle.

    Args:
        parent: Handle for the containing directory.
        name: A single component.
        writable: Request write access.
        create: Create the file when absent.
        deletable: Request DELETE, needed before renaming or unlinking.

    Returns:
        The file handle.

    Raises:
        MissingPathError: If the file is absent and `create` is false.
        NoFollowPathError: If the component is a link.
    """
    return _nt_open(
        name,
        parent,
        directory=False,
        writable=writable,
        disposition=_FILE_OPEN_IF if create else _FILE_OPEN,
        deletable=deletable,
    )


def make_child_directory(parent: int, name: str) -> None:
    """Create one directory relative to its parent handle, if absent.

    Args:
        parent: Handle for the containing directory.
        name: A single component.

    Raises:
        NoFollowPathError: If creation fails for a reason other than existence.
    """
    try:
        handle = _nt_open(name, parent, directory=True, disposition=_FILE_CREATE)
    except FileExistsError:
        return
    close_handle(handle)


def stat_child(parent: int, name: str):
    """Return no-follow metadata for a component, or None when it is absent.

    Mirrors `os.stat(name, dir_fd=..., follow_symlinks=False)` for the fields
    the store compares: identity, size, and modification time. It describes
    whatever is actually there -- file, directory, or link -- because a caller
    that wants to reject a link reads `is_link`, and one that wants to detect a
    swapped file compares identity. Refusing here would deny it both.

    Args:
        parent: Handle for the containing directory.
        name: A single component.

    Returns:
        A `WindowsStat` for the component, or None when it does not exist.
    """
    try:
        handle = _nt_open(
            name,
            parent,
            directory=None,
            missing_is_error=False,
            refuse_links=False,
        )
    except FileNotFoundError:
        return None
    try:
        return WindowsStat(_handle_information(handle))
    finally:
        close_handle(handle)


class WindowsStat:
    """The subset of `os.stat_result` the presentation store compares.

    Attributes mirror the POSIX names so call sites read the same on both
    platforms. `st_dev` and `st_ino` come from the volume serial number and
    the 64-bit file index, which together identify a file on Windows the way
    device and inode do on POSIX -- the property the store's replacement
    detection actually depends on.
    """

    def __init__(self, information: _BY_HANDLE_FILE_INFORMATION) -> None:
        """Derive POSIX-shaped fields from a Windows information block.

        Args:
            information: A populated `BY_HANDLE_FILE_INFORMATION`.
        """
        self.st_dev = int(information.dwVolumeSerialNumber)
        self.st_ino = (int(information.nFileIndexHigh) << 32) | int(
            information.nFileIndexLow
        )
        self.st_size = (int(information.nFileSizeHigh) << 32) | int(
            information.nFileSizeLow
        )
        self.st_mtime_ns = _filetime_to_ns(information.ftLastWriteTime)
        self.st_ctime_ns = _filetime_to_ns(information.ftCreationTime)
        self.st_nlink = int(information.nNumberOfLinks)
        self.is_directory = bool(
            information.dwFileAttributes & _FILE_ATTRIBUTE_DIRECTORY
        )
        self.is_link = bool(
            information.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT
        )


def _filetime_to_ns(filetime: wintypes.FILETIME) -> int:
    """Convert a FILETIME to nanoseconds since the Unix epoch.

    Args:
        filetime: A Windows FILETIME (100ns ticks since 1601).

    Returns:
        Nanoseconds since 1970. Negative inputs are not adjusted; a file dated
        before 1970 simply yields a negative value, as `st_mtime_ns` would.
    """
    ticks = (int(filetime.dwHighDateTime) << 32) | int(filetime.dwLowDateTime)
    return (ticks - _FILETIME_EPOCH_DELTA) * 100


def rename_child(
    parent: int, name: str, new_name: str, *, replace: bool = True
) -> None:
    """Rename one component within its directory, atomically.

    This is the `os.replace(src, dst, src_dir_fd=..., dst_dir_fd=...)`
    equivalent, and it is the operation the store's durability rests on: a
    write lands in a sibling temporary and is then renamed onto the target in
    one step, so a reader sees either the old file or the new one.

    Args:
        parent: Handle for the directory holding both names.
        name: Existing component to rename.
        new_name: Target component name, in the same directory.
        replace: Overwrite the target when it exists.

    Raises:
        NoFollowPathError: If the source is a link, or the rename fails.
    """
    # DELETE access is what NtSetInformationFile requires to move a name.
    handle = _nt_open(name, parent, directory=False, writable=True, deletable=True)
    try:
        name_bytes = new_name.encode("utf-16-le")
        # FILE_RENAME_INFORMATION is a variable-length struct: a fixed header
        # followed by the name inline, so it is built per call rather than
        # declared once.
        class _FILE_RENAME_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("ReplaceIfExists", ctypes.c_ubyte),
                ("RootDirectory", wintypes.HANDLE),
                ("FileNameLength", wintypes.ULONG),
                ("FileName", ctypes.c_wchar * (len(new_name) + 1)),
            ]

        information = _FILE_RENAME_INFORMATION()
        information.ReplaceIfExists = 1 if replace else 0
        information.RootDirectory = wintypes.HANDLE(parent)
        information.FileNameLength = len(name_bytes)
        information.FileName = new_name

        status_block = _IO_STATUS_BLOCK()
        status = _NTDLL.NtSetInformationFile(
            wintypes.HANDLE(handle),
            ctypes.byref(status_block),
            ctypes.byref(information),
            ctypes.sizeof(information),
            _FILE_RENAME_INFORMATION_CLASS,
        )
        _raise_for_status(status, new_name)
    finally:
        close_handle(handle)


def unlink_child(parent: int, name: str) -> None:
    """Delete one component from its directory.

    Args:
        parent: Handle for the containing directory.
        name: Component to delete.

    Raises:
        MissingPathError: If the component does not exist.
        NoFollowPathError: If it is a link, or the delete fails.
    """
    handle = _nt_open(name, parent, directory=False, deletable=True)
    try:
        disposition = ctypes.c_ubyte(1)
        status_block = _IO_STATUS_BLOCK()
        status = _NTDLL.NtSetInformationFile(
            wintypes.HANDLE(handle),
            ctypes.byref(status_block),
            ctypes.byref(disposition),
            ctypes.sizeof(disposition),
            _FILE_DISPOSITION_INFORMATION_CLASS,
        )
        _raise_for_status(status, name)
    finally:
        close_handle(handle)


def flush_directory(handle: int) -> None:
    """Flush a directory handle, the `os.fsync` equivalent for a parent.

    The handle must have been opened with `writable=True`: `FlushFileBuffers`
    requires write access and otherwise fails with `ERROR_ACCESS_DENIED`, which
    would be reported as a durability failure rather than the programming error
    it actually is.

    Args:
        handle: An open, writable directory handle.

    Raises:
        OSError: If the flush fails.
    """
    if not _KERNEL32.FlushFileBuffers(wintypes.HANDLE(handle)):
        raise ctypes.WinError(ctypes.get_last_error())


def close_handle(handle: int) -> None:
    """Close a Windows handle obtained from this module.

    Args:
        handle: The handle to close. A handle already bridged to a file
            descriptor must be closed with `os.close` instead -- the
            descriptor owns it from that point on.
    """
    _KERNEL32.CloseHandle(wintypes.HANDLE(handle))


def handle_to_descriptor(handle: int, flags: int = os.O_RDONLY) -> int:
    """Bridge a Windows handle into a file descriptor.

    Ownership transfers: closing the descriptor closes the handle, and the
    handle must not also be passed to `close_handle`. The bridge is what lets
    the rest of the store keep using `os.read`, `os.write` and the byte-range
    locks in `presentation_file_lock` unchanged.

    Args:
        handle: An open Windows handle.
        flags: `os.O_*` flags describing the descriptor.

    Returns:
        The new file descriptor.
    """
    import msvcrt

    return msvcrt.open_osfhandle(handle, flags)
