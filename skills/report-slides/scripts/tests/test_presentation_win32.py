"""Tests for the NT anchored-traversal primitives.

The point of this layer is a security property, not a convenience: a component
resolved once must not be re-resolvable through a link swapped in afterwards.
These tests therefore build the actual attack shape -- a junction pointing at a
sibling directory -- and assert the primitives refuse it, rather than only
checking that ordinary opens succeed.

Windows only; the whole module skips elsewhere, so the Linux CI image collects
it and moves on.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="NT anchored traversal is Windows-only",
)

if sys.platform == "win32":  # pragma: no branch - import guard for other hosts
    import presentation_win32 as win32
    from presentation_no_follow import MissingPathError, NoFollowPathError


def _make_junction(link: Path, target: Path) -> bool:
    """Create a directory junction, reporting whether the host allowed it.

    A junction is used rather than a symlink because `mklink /J` needs no
    administrator rights or Developer Mode, so the security assertions still
    run on an ordinary developer machine.

    Args:
        link: Path of the junction to create.
        target: Directory the junction should point at.

    Returns:
        True when the junction now exists.
    """
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and link.exists()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project root holding `state/decks.yaml`."""
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "decks.yaml").write_bytes(b"decks: {}\n")
    return tmp_path


@pytest.fixture
def root_handle(project: Path):
    """An open handle for the project root, closed after the test."""
    handle = win32.open_root_directory(str(project))
    yield handle
    win32.close_handle(handle)


def test_open_root_directory_opens_an_absolute_path(root_handle: int) -> None:
    """The traversal anchor opens without a parent handle."""
    assert isinstance(root_handle, int)
    assert root_handle != 0


def test_open_child_directory_is_relative_to_the_parent(root_handle: int) -> None:
    """A component opens against the parent handle, not a rebuilt path."""
    child = win32.open_child_directory(root_handle, "state")
    try:
        assert isinstance(child, int)
    finally:
        win32.close_handle(child)


def test_open_child_file_reads_through_a_bridged_descriptor(root_handle: int) -> None:
    """A handle bridges to a descriptor the rest of the store can use."""
    state = win32.open_child_directory(root_handle, "state")
    try:
        handle = win32.open_child_file(state, "decks.yaml")
        descriptor = win32.handle_to_descriptor(handle)
        try:
            assert os.read(descriptor, 64) == b"decks: {}\n"
        finally:
            # The descriptor owns the handle once bridged.
            os.close(descriptor)
    finally:
        win32.close_handle(state)


def test_missing_component_raises_missing_path_error(root_handle: int) -> None:
    """An absent directory is distinguishable from an unsafe one."""
    with pytest.raises(MissingPathError):
        win32.open_child_directory(root_handle, "absent")


def test_open_child_directory_refuses_a_junction(project: Path, root_handle: int) -> None:
    """The O_NOFOLLOW equivalent: a linked component is refused, not followed."""
    if not _make_junction(project / "link", project / "state"):
        pytest.skip("host does not permit creating a junction")

    with pytest.raises(NoFollowPathError, match="no-follow"):
        win32.open_child_directory(root_handle, "link")


def test_stat_child_reports_a_junction_instead_of_refusing_it(
    project: Path, root_handle: int
) -> None:
    """Stat describes what is there so a caller can detect the link itself."""
    if not _make_junction(project / "link", project / "state"):
        pytest.skip("host does not permit creating a junction")

    metadata = win32.stat_child(root_handle, "link")
    assert metadata is not None
    assert metadata.is_link is True


def test_stat_child_returns_none_for_an_absent_component(root_handle: int) -> None:
    """Absence is None, matching the POSIX helper's contract."""
    assert win32.stat_child(root_handle, "absent") is None


def test_stat_child_reports_posix_shaped_identity(project: Path, root_handle: int) -> None:
    """Identity, size and mtime carry the names the store compares on."""
    state = win32.open_child_directory(root_handle, "state")
    try:
        metadata = win32.stat_child(state, "decks.yaml")
    finally:
        win32.close_handle(state)

    assert metadata is not None
    assert metadata.st_size == len(b"decks: {}\n")
    assert metadata.st_ino != 0
    assert metadata.st_dev != 0
    assert metadata.is_link is False
    assert metadata.is_directory is False
    # Written moments ago, so far past the 1970 epoch the conversion is sound.
    assert metadata.st_mtime_ns > 1_500_000_000_000_000_000


def test_identity_distinguishes_a_replaced_file(project: Path, root_handle: int) -> None:
    """A rewritten file reports a different identity -- the swap detector."""
    state = win32.open_child_directory(root_handle, "state")
    try:
        before = win32.stat_child(state, "decks.yaml")
        (project / "state" / "decks.yaml").unlink()
        (project / "state" / "decks.yaml").write_bytes(b"decks: {replaced: 1}\n")
        after = win32.stat_child(state, "decks.yaml")
    finally:
        win32.close_handle(state)

    assert before is not None and after is not None
    assert (before.st_dev, before.st_ino, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
    )


def test_identity_is_stable_for_an_untouched_file(root_handle: int) -> None:
    """Two stats of the same file agree, so the detector does not false-alarm."""
    state = win32.open_child_directory(root_handle, "state")
    try:
        first = win32.stat_child(state, "decks.yaml")
        second = win32.stat_child(state, "decks.yaml")
    finally:
        win32.close_handle(state)

    assert (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def test_make_child_directory_creates_and_is_idempotent(root_handle: int) -> None:
    """Creating an existing directory is a no-op, as `create_parents` needs."""
    win32.make_child_directory(root_handle, "events")
    win32.make_child_directory(root_handle, "events")
    metadata = win32.stat_child(root_handle, "events")
    assert metadata is not None
    assert metadata.is_directory is True


def test_open_child_file_can_create(root_handle: int) -> None:
    """A sidecar lock file is created on first use."""
    handle = win32.open_child_file(root_handle, "state.lock", writable=True, create=True)
    os.close(win32.handle_to_descriptor(handle, os.O_RDWR))
    assert win32.stat_child(root_handle, "state.lock") is not None


def test_flush_directory_requires_a_writable_handle(project: Path) -> None:
    """The fsync equivalent works, but only on a writable parent handle."""
    handle = win32.open_root_directory(str(project), writable=True)
    try:
        win32.flush_directory(handle)
    finally:
        win32.close_handle(handle)


def test_flush_directory_on_a_read_only_handle_is_refused(root_handle: int) -> None:
    """A read-only handle cannot flush, so the writable flag is not cosmetic."""
    with pytest.raises(PermissionError):
        win32.flush_directory(root_handle)


def test_open_child_directory_rejects_a_file(root_handle: int) -> None:
    """Requiring a directory mirrors O_DIRECTORY."""
    state = win32.open_child_directory(root_handle, "state")
    try:
        with pytest.raises(NoFollowPathError):
            win32.open_child_directory(state, "decks.yaml")
    finally:
        win32.close_handle(state)


def test_rename_child_replaces_atomically(project: Path, root_handle: int) -> None:
    """The staging-then-rename step the store's durability depends on."""
    state = win32.open_child_directory(root_handle, "state")
    try:
        (project / "state" / "decks.yaml.tmp").write_bytes(b"decks: {new: 1}\n")
        win32.rename_child(state, "decks.yaml.tmp", "decks.yaml")

        assert (project / "state" / "decks.yaml").read_bytes() == b"decks: {new: 1}\n"
        assert not (project / "state" / "decks.yaml.tmp").exists()
    finally:
        win32.close_handle(state)


def test_rename_child_can_refuse_to_replace(project: Path, root_handle: int) -> None:
    """`replace=False` leaves an existing target alone."""
    state = win32.open_child_directory(root_handle, "state")
    try:
        (project / "state" / "other.yaml").write_bytes(b"other\n")
        with pytest.raises(Exception):
            win32.rename_child(state, "other.yaml", "decks.yaml", replace=False)
        assert (project / "state" / "decks.yaml").read_bytes() == b"decks: {}\n"
    finally:
        win32.close_handle(state)


def test_unlink_child_removes_a_file(project: Path, root_handle: int) -> None:
    """Deleting a component mirrors `os.unlink(name, dir_fd=...)`."""
    state = win32.open_child_directory(root_handle, "state")
    try:
        win32.unlink_child(state, "decks.yaml")
        assert not (project / "state" / "decks.yaml").exists()
        assert win32.stat_child(state, "decks.yaml") is None
    finally:
        win32.close_handle(state)


def test_unlink_child_refuses_a_junction(project: Path, root_handle: int) -> None:
    """A link is refused rather than followed, even when deleting."""
    if not _make_junction(project / "link", project / "state"):
        pytest.skip("host does not permit creating a junction")

    with pytest.raises(NoFollowPathError):
        win32.unlink_child(root_handle, "link")
    assert (project / "state" / "decks.yaml").exists()
