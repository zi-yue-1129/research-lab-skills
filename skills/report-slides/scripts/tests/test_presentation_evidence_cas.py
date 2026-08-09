"""Safety, immutability, and durability tests for evidence CAS objects."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import presentation_evidence_cas
import presentation_transactions
from presentation_evidence_cas import (
    CasObject,
    CasError,
    cas_relative_path,
    plan_cas_objects,
    read_verified_source,
    stage_cas_objects,
)
from presentation_transactions import (
    SimulatedProcessDeath,
    TransactionError,
    WorkflowTransaction,
)


def fixture_regular_artifact(project_root: Path, content: bytes, name: str = "deck.pptx") -> Path:
    """Create one regular artifact under a canonical output directory.

    Args:
        project_root: Root containing the fixture output directory.
        content: Exact artifact bytes to write.
        name: File name relative to the output directory.

    Returns:
        The created regular artifact path.
    """
    source = project_root / "output" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(content)
    return source


def _cas_target(project_root: Path, content: bytes) -> Path:
    """Return the hand-derived canonical CAS location for fixture bytes."""
    digest = hashlib.sha256(content).hexdigest()
    return project_root / ".research/presentations/evidence/sha256" / digest[:2] / digest


def _planned_target(project_root: Path, content: bytes) -> tuple[Path, dict[str, CasObject]]:
    """Plan one artifact and return its target plus its digest-indexed plan."""
    source = fixture_regular_artifact(project_root, content)
    planned = plan_cas_objects(project_root, {"output/deck.pptx": source})
    return _cas_target(project_root, content), planned


def _tree_snapshot(root: Path) -> dict[str, tuple[str, bytes, int, int]]:
    """Capture exact file bytes plus mode and mtime for one sentinel tree."""
    snapshot: dict[str, tuple[str, bytes, int, int]] = {}
    for path in [root, *sorted(root.rglob("*"))]:
        metadata = path.lstat()
        kind = "symlink" if path.is_symlink() else "file" if path.is_file() else "directory"
        content = path.read_bytes() if kind == "file" else b""
        snapshot[path.relative_to(root.parent).as_posix()] = (
            kind,
            content,
            metadata.st_mode & 0o777,
            metadata.st_mtime_ns,
        )
    return snapshot


def test_plan_cas_object_hashes_source_without_following_symlink(tmp_path: Path) -> None:
    """Planning hashes a regular artifact and returns its canonical CAS path."""
    source = fixture_regular_artifact(tmp_path, b"pptx-bytes")

    planned = plan_cas_objects(tmp_path, {"output/deck.pptx": source})

    digest = hashlib.sha256(b"pptx-bytes").hexdigest()
    assert planned[digest].relative_path == Path(
        f".research/presentations/evidence/sha256/{digest[:2]}/{digest}"
    )
    assert planned[digest].content == b"pptx-bytes"


def test_plan_cas_objects_deduplicates_identical_source_bytes(tmp_path: Path) -> None:
    """Two provenance paths with identical bytes plan one immutable object."""
    first = fixture_regular_artifact(tmp_path, b"same", "first.pptx")
    second = fixture_regular_artifact(tmp_path, b"same", "second.pptx")

    planned = plan_cas_objects(
        tmp_path,
        {"output/first.pptx": first, "output/second.pptx": second},
    )

    digest = hashlib.sha256(b"same").hexdigest()
    assert list(planned) == [digest]
    assert planned[digest].content == b"same"


def test_read_verified_source_uses_immutable_cas_mode(tmp_path: Path) -> None:
    """A planned object uses the fixed immutable publication permission bits."""
    source = fixture_regular_artifact(tmp_path, b"mode")
    source.chmod(0o640)

    object_ = read_verified_source(tmp_path, "output/deck.pptx")

    assert object_.mode == 0o444


@pytest.mark.parametrize("relative_path", ["../outside.pptx", "output/../deck.pptx", "/tmp/deck.pptx"])
def test_read_verified_source_rejects_noncanonical_source_paths(
    tmp_path: Path, relative_path: str
) -> None:
    """Traversal or absolute provenance paths fail before an artifact read."""
    fixture_regular_artifact(tmp_path, b"safe")

    with pytest.raises(CasError, match="project-relative|canonical|normalized"):
        read_verified_source(tmp_path, relative_path)


def test_plan_cas_objects_rejects_source_path_mismatched_to_provenance(tmp_path: Path) -> None:
    """The mapping cannot claim one provenance path while reading another file."""
    source = fixture_regular_artifact(tmp_path, b"pptx-bytes")

    with pytest.raises(CasError, match="does not match"):
        plan_cas_objects(tmp_path, {"output/other.pptx": source})


def test_read_verified_source_rejects_missing_source(tmp_path: Path) -> None:
    """A declared artifact must exist as a regular file to be materialized."""
    with pytest.raises(CasError, match="missing source.*output/missing.pptx"):
        read_verified_source(tmp_path, "output/missing.pptx")


def test_read_verified_source_rejects_symlink_without_reading_target(tmp_path: Path) -> None:
    """A source symlink cannot redirect CAS ingestion outside the project."""
    outside = tmp_path.parent / "outside.pptx"
    outside.write_bytes(b"outside")
    source = tmp_path / "output" / "deck.pptx"
    source.parent.mkdir(parents=True)
    source.symlink_to(outside)

    with pytest.raises(CasError, match="symlink.*output/deck.pptx"):
        read_verified_source(tmp_path, "output/deck.pptx")

    assert outside.read_bytes() == b"outside"


def test_read_verified_source_anchors_parent_before_directory_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checked source directory swap cannot redirect the later leaf open."""
    project = tmp_path / "project"
    project.mkdir()
    source = fixture_regular_artifact(project, b"original")
    outside_directory = tmp_path / "outside-output"
    outside_directory.mkdir()
    outside_source = outside_directory / "deck.pptx"
    outside_source.write_bytes(b"outside")
    outside_before = _tree_snapshot(outside_directory)
    moved_directory = project / ".output-anchored"
    original_open = presentation_evidence_cas.os.open
    swapped = False

    def open_after_directory_swap(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        """Swap the checked source directory immediately before its leaf open."""
        nonlocal swapped
        path_text = os.fsdecode(path)
        leaf_open = Path(path_text) == source if dir_fd is None else path_text == source.name
        if leaf_open and not swapped:
            source.parent.rename(moved_directory)
            source.parent.symlink_to(outside_directory, target_is_directory=True)
            swapped = True
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(presentation_evidence_cas.os, "open", open_after_directory_swap)

    object_ = read_verified_source(project, "output/deck.pptx")

    assert swapped
    assert object_.content == b"original"
    assert _tree_snapshot(outside_directory) == outside_before


def test_read_verified_source_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    """A FIFO cannot block or impersonate an evidence artifact."""
    source = tmp_path / "output" / "deck.pptx"
    source.parent.mkdir(parents=True)
    os.mkfifo(source)

    with pytest.raises(CasError, match="regular file.*output/deck.pptx"):
        read_verified_source(tmp_path, "output/deck.pptx")


@pytest.mark.parametrize("mutation_point", ["first", "middle", "final"])
def test_read_verified_source_detects_mutation_during_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation_point: str
) -> None:
    """Changes before, during, or after reads fail with the provenance path."""
    source = fixture_regular_artifact(tmp_path, b"original-content")
    original_read = os.read
    read_calls = 0

    def read_with_mutation(descriptor: int, size: int) -> bytes:
        """Read one byte at a time and mutate the source at a chosen boundary."""
        nonlocal read_calls
        if mutation_point == "first" and read_calls == 0:
            source.write_bytes(b"first-mutation")
        result = original_read(descriptor, min(size, 1))
        read_calls += 1
        if mutation_point == "middle" and read_calls == 1:
            source.write_bytes(b"middle-mutation")
        if mutation_point == "final" and not result:
            source.write_bytes(b"final-mutation")
        return result

    monkeypatch.setattr(os, "read", read_with_mutation)
    with pytest.raises(CasError, match="changed while reading.*output/deck.pptx"):
        read_verified_source(tmp_path, "output/deck.pptx")


def test_stage_cas_objects_rejects_existing_object_with_mismatched_bytes(tmp_path: Path) -> None:
    """A CAS pathname never accepts bytes that disagree with its SHA-256."""
    target = _cas_target(tmp_path, b"expected")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"different")
    source = fixture_regular_artifact(tmp_path, b"expected")
    planned = plan_cas_objects(tmp_path, {"output/deck.pptx": source})

    with WorkflowTransaction([target], tmp_path) as transaction:
        with pytest.raises(CasError, match="CAS object.*digest"):
            stage_cas_objects(transaction, tmp_path, planned)


def test_stage_cas_objects_rejects_existing_symlink_before_commit(tmp_path: Path) -> None:
    """A CAS object symlink cannot redirect immutable-object verification."""
    target = _cas_target(tmp_path, b"expected")
    target.parent.mkdir(parents=True)
    outside = tmp_path / "outside-cas-object"
    outside.write_bytes(b"expected")
    target.symlink_to(outside)
    source = fixture_regular_artifact(tmp_path, b"expected")
    planned = plan_cas_objects(tmp_path, {"output/deck.pptx": source})

    with WorkflowTransaction([target], tmp_path) as transaction:
        with pytest.raises(CasError, match="regular no-follow"):
            stage_cas_objects(transaction, tmp_path, planned)

    assert target.is_symlink()
    assert outside.read_bytes() == b"expected"


def test_stage_cas_objects_rejects_existing_fifo_before_commit(tmp_path: Path) -> None:
    """A CAS FIFO cannot block or impersonate an existing immutable object."""
    target = _cas_target(tmp_path, b"expected")
    target.parent.mkdir(parents=True)
    os.mkfifo(target)
    source = fixture_regular_artifact(tmp_path, b"expected")
    planned = plan_cas_objects(tmp_path, {"output/deck.pptx": source})

    with WorkflowTransaction([target], tmp_path) as transaction:
        with pytest.raises(CasError, match="regular no-follow"):
            stage_cas_objects(transaction, tmp_path, planned)


def test_stage_cas_objects_materializes_deduplicated_content_once(tmp_path: Path) -> None:
    """Staging deduplicated plans creates one durable immutable object."""
    first = fixture_regular_artifact(tmp_path, b"shared", "first.pptx")
    second = fixture_regular_artifact(tmp_path, b"shared", "second.pptx")
    planned = plan_cas_objects(
        tmp_path,
        {"output/first.pptx": first, "output/second.pptx": second},
    )
    target = _cas_target(tmp_path, b"shared")

    previous_umask = os.umask(0o077)
    try:
        with WorkflowTransaction([target], tmp_path) as transaction:
            assert stage_cas_objects(transaction, tmp_path, planned) == (target,)
            transaction.commit()
    finally:
        os.umask(previous_umask)

    assert target.read_bytes() == b"shared"
    assert target.stat().st_mode & 0o777 == 0o444


@pytest.mark.parametrize("redirect_inside_project", [False, True])
@pytest.mark.parametrize("operation", ["commit", "rollback"])
def test_cas_transaction_anchors_directories_against_checked_path_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    redirect_inside_project: bool,
    operation: str,
) -> None:
    """Locking, publication, and rollback never mutate a swapped-in tree."""
    project = tmp_path / "project"
    project.mkdir()
    research = project / ".research"
    research.mkdir()
    target, planned = _planned_target(project, b"anchored-transaction")
    digest = target.name
    redirect = (
        project / "redirect-research"
        if redirect_inside_project
        else tmp_path / "outside-research"
    )
    (redirect / "presentations/evidence/sha256" / digest[:2]).mkdir(parents=True)
    (redirect / "presentations/transactions").mkdir(parents=True)
    (redirect / "sentinel").write_bytes(b"outside")
    redirect_before = _tree_snapshot(redirect)
    moved_research = project / ".research-anchored"
    original_mkdir = Path.mkdir
    original_open = presentation_transactions.os.open
    swapped = False

    def swap_research_directory() -> None:
        """Replace the checked project directory with an adversarial symlink."""
        nonlocal swapped
        research.rename(moved_research)
        research.symlink_to(redirect, target_is_directory=True)
        swapped = True

    def mkdir_after_directory_swap(
        path: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        """Trigger the legacy full-path race before CAS parent creation."""
        if path == target.parent and not swapped:
            swap_research_directory()
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    def open_after_directory_swap(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        """Trigger the openat race after the parent descriptor is retained."""
        if dir_fd is not None and os.fsdecode(path) == "evidence" and not swapped:
            swap_research_directory()
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(Path, "mkdir", mkdir_after_directory_swap)
    monkeypatch.setattr(presentation_transactions.os, "open", open_after_directory_swap)
    if operation == "rollback":
        monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", "1")

    try:
        with WorkflowTransaction([target], project) as transaction:
            stage_cas_objects(transaction, project, planned)
            transaction.commit()
    except (CasError, OSError, RuntimeError, TransactionError):
        pass

    assert swapped
    assert _tree_snapshot(redirect) == redirect_before
    assert not (redirect / "presentations/evidence/sha256" / digest[:2] / digest).exists()
    assert not (redirect / "presentations/evidence/sha256" / digest[:2] / f"{digest}.lock").exists()


def test_cas_recovery_uses_anchored_target_and_journal_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crash recovery survives a post-validation directory swap without escape."""
    project = tmp_path / "project"
    project.mkdir()
    target, planned = _planned_target(project, b"anchored-recovery")
    monkeypatch.setenv("PRESENTATION_TRANSACTION_CRASH_AT", "1")
    with pytest.raises(SimulatedProcessDeath, match="simulated process death"):
        with WorkflowTransaction([target], project) as transaction:
            stage_cas_objects(transaction, project, planned)
            transaction.commit()
    monkeypatch.delenv("PRESENTATION_TRANSACTION_CRASH_AT")
    research = project / ".research"
    moved_research = project / ".research-anchored"
    redirect = tmp_path / "outside-recovery"
    digest = target.name
    (redirect / "presentations/evidence/sha256" / digest[:2]).mkdir(parents=True)
    (redirect / "presentations/transactions").mkdir(parents=True)
    (redirect / "sentinel").write_bytes(b"outside")
    redirect_before = _tree_snapshot(redirect)
    original_mkdir = Path.mkdir
    original_open = presentation_transactions.os.open
    swapped = False

    def swap_research_directory() -> None:
        """Replace the recovered project directory with an outside symlink."""
        nonlocal swapped
        research.rename(moved_research)
        research.symlink_to(redirect, target_is_directory=True)
        swapped = True

    def mkdir_after_directory_swap(
        path: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        """Trigger the legacy recovery race before CAS sidecar acquisition."""
        if path == target.parent and not swapped:
            swap_research_directory()
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    def open_after_directory_swap(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        """Swap after an anchored presentations directory is open."""
        if dir_fd is not None and os.fsdecode(path) == "evidence" and not swapped:
            swap_research_directory()
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(Path, "mkdir", mkdir_after_directory_swap)
    monkeypatch.setattr(presentation_transactions.os, "open", open_after_directory_swap)

    with WorkflowTransaction([], project):
        pass

    assert swapped
    assert _tree_snapshot(redirect) == redirect_before
    assert not (moved_research / target.relative_to(research)).exists()
    assert not list((moved_research / "presentations/transactions").glob("*.json"))


def test_validly_named_fifo_journal_fails_without_blocking_or_mutation(
    tmp_path: Path,
) -> None:
    """A FIFO journal is rejected within a bounded child process."""
    target = tmp_path / ".research/presentations/state/slides.yaml"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"target-sentinel")
    journal_dir = tmp_path / ".research/presentations/transactions"
    journal_dir.mkdir(parents=True)
    journal = journal_dir / ("a" * 32 + ".json")
    os.mkfifo(journal)
    outside = tmp_path / "outside-sentinel"
    outside.write_bytes(b"outside-sentinel")
    target_before = _tree_snapshot(target.parent)
    outside_before = _tree_snapshot(outside.parent)
    child_code = """
import sys
from pathlib import Path
from presentation_transactions import TransactionError, WorkflowTransaction
try:
    with WorkflowTransaction([], Path(sys.argv[1])):
        pass
except TransactionError:
    print("structured-error")
    raise SystemExit(0)
raise SystemExit(2)
"""

    completed = subprocess.run(
        [sys.executable, "-c", child_code, str(tmp_path)],
        cwd=Path(__file__).parent.parent,
        text=True,
        capture_output=True,
        timeout=2,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "structured-error"
    assert journal.is_fifo()
    assert _tree_snapshot(target.parent) == target_before
    assert _tree_snapshot(outside.parent) == outside_before


def test_validly_named_socket_journal_fails_with_structured_error(
    tmp_path: Path,
) -> None:
    """A Unix socket journal fails closed without an unwrapped OS error."""
    journal_dir = tmp_path / ".research/presentations/transactions"
    journal_dir.mkdir(parents=True)
    journal = journal_dir / ("b" * 32 + ".json")
    os.mknod(journal, stat.S_IFSOCK | 0o600)
    outside = tmp_path / "outside-sentinel"
    outside.write_bytes(b"outside-sentinel")
    outside_before = _tree_snapshot(outside.parent)

    with pytest.raises(TransactionError, match="journal|regular|no-follow"):
        with WorkflowTransaction([], tmp_path):
            pass

    assert journal.exists()
    assert _tree_snapshot(outside.parent) == outside_before


def test_stage_cas_objects_retains_existing_valid_object_metadata(tmp_path: Path) -> None:
    """Deduplication leaves a valid immutable object's bytes, mode, and mtime intact."""
    source = fixture_regular_artifact(tmp_path, b"shared")
    target = _cas_target(tmp_path, b"shared")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"shared")
    target.chmod(0o600)
    existing_mtime = target.stat().st_mtime_ns - 1_234_567
    os.utime(target, ns=(existing_mtime, existing_mtime))
    planned = plan_cas_objects(tmp_path, {"output/deck.pptx": source})

    with WorkflowTransaction([target], tmp_path) as transaction:
        assert stage_cas_objects(transaction, tmp_path, planned) == (target,)
        transaction.commit()

    assert target.read_bytes() == b"shared"
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.stat().st_mtime_ns == existing_mtime


def test_cas_short_write_leaves_object_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A zero-byte write failure cannot publish a partial immutable object."""
    target, planned = _planned_target(tmp_path, b"short-write")

    with WorkflowTransaction([target], tmp_path) as transaction:
        monkeypatch.setattr(presentation_transactions.os, "write", lambda _fd, _data: 0)
        with pytest.raises(OSError, match="short write"):
            stage_cas_objects(transaction, tmp_path, planned)

    assert not target.exists()


def test_cas_replace_failure_rolls_back_absent_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed CAS publish restores the exact absent preimage."""
    target, planned = _planned_target(tmp_path, b"replace-failure")
    monkeypatch.setenv("PRESENTATION_TRANSACTION_FAIL_AT", "1")

    with pytest.raises(RuntimeError, match="transaction commit failed"):
        with WorkflowTransaction([target], tmp_path) as transaction:
            stage_cas_objects(transaction, tmp_path, planned)
            transaction.commit()

    assert not target.exists()


def test_cas_fsync_failure_rolls_back_absent_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A post-replace directory fsync failure restores the absent preimage."""
    target, planned = _planned_target(tmp_path, b"fsync-failure")
    original_directory_fsync = presentation_transactions.AnchoredPath.fsync_parent
    failed = False

    def fail_once_for_cas_directory(
        anchored: presentation_transactions.AnchoredPath,
    ) -> None:
        """Fail the first durability sync after the visible CAS replacement."""
        nonlocal failed
        if anchored.display_path == target and target.exists() and not failed:
            failed = True
            raise OSError("injected CAS directory fsync failure")
        original_directory_fsync(anchored)

    with WorkflowTransaction([target], tmp_path) as transaction:
        stage_cas_objects(transaction, tmp_path, planned)
        monkeypatch.setattr(
            presentation_transactions.AnchoredPath,
            "fsync_parent",
            fail_once_for_cas_directory,
        )
        with pytest.raises(RuntimeError, match="transaction commit failed"):
            transaction.commit()

    assert not target.exists()


def test_cas_crash_recovery_restores_absent_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A process death after CAS publish recovers the exact absent preimage."""
    target, planned = _planned_target(tmp_path, b"crash-recovery")
    monkeypatch.setenv("PRESENTATION_TRANSACTION_CRASH_AT", "1")

    with pytest.raises(SimulatedProcessDeath, match="simulated process death"):
        with WorkflowTransaction([target], tmp_path) as transaction:
            stage_cas_objects(transaction, tmp_path, planned)
            transaction.commit()

    monkeypatch.delenv("PRESENTATION_TRANSACTION_CRASH_AT")
    assert target.read_bytes() == b"crash-recovery"
    with WorkflowTransaction([], tmp_path):
        pass
    assert not target.exists()


def test_cas_recovery_rejects_symlinked_object_without_touching_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recovery fails closed instead of unlinking a CAS symlink after a crash."""
    target, planned = _planned_target(tmp_path, b"crash-symlink")
    monkeypatch.setenv("PRESENTATION_TRANSACTION_CRASH_AT", "1")
    with pytest.raises(SimulatedProcessDeath, match="simulated process death"):
        with WorkflowTransaction([target], tmp_path) as transaction:
            stage_cas_objects(transaction, tmp_path, planned)
            transaction.commit()
    monkeypatch.delenv("PRESENTATION_TRANSACTION_CRASH_AT")
    target.unlink()
    outside = tmp_path / "recovery-outside"
    outside.write_bytes(b"outside")
    target.symlink_to(outside)

    with pytest.raises(TransactionError, match="CAS recovery target"):
        with WorkflowTransaction([], tmp_path):
            pass

    assert target.is_symlink()
    assert outside.read_bytes() == b"outside"
    assert list((tmp_path / ".research/presentations/transactions").glob("*.json"))


def test_cas_sidecar_inode_remains_stable_after_transaction_release(tmp_path: Path) -> None:
    """Releasing a CAS transaction never unlinks the operational sidecar inode."""
    target, planned = _planned_target(tmp_path, b"stable-sidecar")

    with WorkflowTransaction([target], tmp_path) as transaction:
        stage_cas_objects(transaction, tmp_path, planned)
        transaction.commit()
    sidecar = target.with_suffix(target.suffix + ".lock")
    first_inode = sidecar.stat().st_ino
    with WorkflowTransaction([target], tmp_path):
        pass

    assert sidecar.stat().st_ino == first_inode


def test_cas_relative_path_rejects_noncanonical_digest() -> None:
    """CAS paths require exactly one lowercase hexadecimal SHA-256 digest."""
    with pytest.raises(CasError, match="lowercase SHA-256"):
        cas_relative_path("A" * 64)
