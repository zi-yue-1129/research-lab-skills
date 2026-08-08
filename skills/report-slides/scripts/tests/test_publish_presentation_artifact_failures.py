"""Failure-injection tests for atomic presentation artifact publication."""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from presentation_contracts import contract_sha256
from presentation_events import create_assignment_record, load_artifacts
from presentation_gates import PublicationGateError
from presentation_state import set_module_status
from publish_presentation_artifact import publish_artifact
from test_publish_presentation_artifact import (
    _configure_slides_role,
    _approved_module_project,
    approved_assignment,
    final_svg,
    staged_svg,
)


def _module_publish_fixture(tmp_path: Path) -> tuple[Path, str, str, Path]:
    """Create an approved module with a current persisted assignment."""
    project, deck_id, module_id, module, spec = _approved_module_project(tmp_path)
    _configure_slides_role(project)
    set_module_status(project, module_id, "assigned")
    assignment_path = project / "assignment.yaml"
    assignment = {
        "schema_version": 1,
        "module_id": module_id,
        "worker_type": "architecture",
        "dependencies": [],
        "spec_sha256": contract_sha256(spec),
        "inputs_resolved": True,
        "assigned_at": "2026-08-08T00:00:00Z",
        "blocker": None,
    }
    assignment_path.write_text(yaml.safe_dump(assignment), encoding="utf-8")
    create_assignment_record(
        project,
        deck_id,
        module_id=module_id,
        assignment_path="assignment.yaml",
        worker_id="worker-a",
        worker_type="architecture",
        spec_sha256=contract_sha256(spec),
        dependencies=[],
        inputs_resolved=True,
        slide_id=module["slide_id"],
    )
    return project, deck_id, module_id, assignment_path


def test_state_locks_follow_repository_visual_modules_then_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acquire state sidecars in the repository's established order."""
    import publish_presentation_artifact as publisher

    paths = publisher._state_paths(tmp_path, True)
    events: list[Path] = []

    @contextmanager
    def observed_lock(root: Path, path: Path) -> Iterator[None]:
        events.append(path)
        yield

    monkeypatch.setattr(publisher._events, "_locked_file", observed_lock)
    with publisher._state_locks(tmp_path, paths):
        pass
    assert events == [
        tmp_path / ".research/presentations/state/visual_modules.yaml",
        tmp_path / ".research/presentations/state/artifacts.yaml",
    ]


def test_restore_aggregates_rollback_operation_and_temp_cleanup_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserve both rollback replace and rollback-temp cleanup failures."""
    import publish_presentation_artifact as publisher

    path = tmp_path / "artifact.svg"
    path.write_bytes(b"prior")
    snapshot = (b"prior", 0o640)
    original_unlink = Path.unlink

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("rollback replace")

    def fail_rollback_cleanup(target: Path, *args: Any, **kwargs: Any) -> None:
        if ".rollback." in target.name:
            raise OSError("rollback temp cleanup")
        original_unlink(target, *args, **kwargs)

    monkeypatch.setattr(publisher.os, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_rollback_cleanup)
    with pytest.raises(PublicationGateError) as raised:
        publisher._restore_path_atomic(path, snapshot)
    assert "rollback replace" in str(raised.value)
    assert "rollback temp cleanup" in str(raised.value)
    monkeypatch.undo()
    for temporary in path.parent.glob(".*.rollback.*.tmp"):
        original_unlink(temporary, missing_ok=True)


def test_primary_and_rollback_directory_fsync_errors_are_both_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Report distinct low-level primary and rollback directory fsync errors."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    destination = final_svg(project)
    import publish_presentation_artifact as publisher

    original_fsync = publisher.os.fsync
    directory_calls = 0

    def fail_directory_fsync(file_descriptor: int) -> None:
        nonlocal directory_calls
        target = Path(os.readlink(f"/proc/self/fd/{file_descriptor}"))
        if target.resolve() == destination.parent.resolve():
            directory_calls += 1
            if directory_calls == 1:
                raise OSError("primary directory fsync")
            if directory_calls == 2:
                raise OSError("rollback directory fsync")
        original_fsync(file_descriptor)

    monkeypatch.setattr(publisher.os, "fsync", fail_directory_fsync)
    with pytest.raises(PublicationGateError) as raised:
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            "slide-svg",
            slide_id,
            None,
            "worker-a",
            project / "slide-spec.yaml",
        )
    messages = " ".join(str(blocker) for blocker in raised.value.blockers)
    assert "primary directory fsync" in messages
    assert "rollback directory fsync" in messages


def test_publish_restores_all_state_files_after_later_state_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restore every state file and destination after a later commit failure."""
    project, deck_id, module_id, assignment_path = _module_publish_fixture(tmp_path)
    destination = project / "docs/slides/module.svg"
    publish_artifact(
        project, deck_id, staged_svg(tmp_path), destination, "module-svg",
        None, module_id, "worker-a", assignment_path,
    )
    artifacts_path = project / ".research/presentations/state/artifacts.yaml"
    modules_path = project / ".research/presentations/state/visual_modules.yaml"
    for path in (destination, artifacts_path, modules_path):
        path.chmod(0o640)
    snapshots = {path: (path.read_bytes(), path.stat().st_mode & 0o777) for path in (destination, artifacts_path, modules_path)}
    source = tmp_path / "changed.svg"
    source.write_bytes(b"changed")
    import publish_presentation_artifact as publisher

    original_replace = publisher.os.replace
    replaced: list[Path] = []

    def fail_later_state_replace(source_path: Path, target: Path) -> None:
        replaced.append(Path(target))
        if Path(target) == artifacts_path:
            raise OSError("later state replace")
        original_replace(source_path, target)

    monkeypatch.setattr(publisher.os, "replace", fail_later_state_replace)
    with pytest.raises(PublicationGateError):
        publish_artifact(
            project, deck_id, source, destination, "module-svg",
            None, module_id, "worker-a", assignment_path,
        )
    assert modules_path in replaced
    for path, (payload, mode) in snapshots.items():
        assert path.read_bytes() == payload
        assert path.stat().st_mode & 0o777 == mode


def test_publish_aggregates_primary_and_same_rollback_temp_cleanup_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Report primary state, rollback replace, and same-temp cleanup failures."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    destination = final_svg(project)
    publish_artifact(
        project, deck_id, staged_svg(tmp_path), destination, "slide-svg",
        slide_id, None, "worker-a", project / "slide-spec.yaml",
    )
    artifacts_path = project / ".research/presentations/state/artifacts.yaml"
    import publish_presentation_artifact as publisher

    original_replace = publisher.os.replace
    original_unlink = Path.unlink
    replace_calls = 0

    def fail_primary_and_rollback(source: Path, target: Path) -> None:
        nonlocal replace_calls
        if Path(target) == artifacts_path:
            replace_calls += 1
            raise OSError("primary state replace" if replace_calls == 1 else "rollback replace")
        original_replace(source, target)

    def fail_rollback_cleanup(target: Path, *args: Any, **kwargs: Any) -> None:
        if ".artifacts.yaml.rollback." in target.name:
            raise OSError("rollback temp cleanup")
        original_unlink(target, *args, **kwargs)

    monkeypatch.setattr(publisher.os, "replace", fail_primary_and_rollback)
    monkeypatch.setattr(Path, "unlink", fail_rollback_cleanup)
    with pytest.raises(PublicationGateError) as raised:
        publish_artifact(
            project, deck_id, staged_svg(tmp_path), destination, "slide-svg",
            slide_id, None, "worker-a", project / "slide-spec.yaml",
        )
    messages = " ".join(str(blocker) for blocker in raised.value.blockers)
    assert "primary state replace" in messages
    assert "rollback replace" in messages
    assert "rollback temp cleanup" in messages
    monkeypatch.undo()
    for temporary in artifacts_path.parent.glob(".*.rollback.*.tmp"):
        original_unlink(temporary, missing_ok=True)


def test_publish_handles_short_write_without_false_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a staging short write and clean its temporary sibling."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    destination = final_svg(project)
    import publish_presentation_artifact as publisher

    original_write = publisher.os.write
    write_calls = 0

    def short_write(file_descriptor: int, payload: bytes) -> int:
        nonlocal write_calls
        write_calls += 1
        if write_calls == 1:
            return original_write(file_descriptor, payload[:1])
        return 0

    monkeypatch.setattr(publisher.os, "write", short_write)
    with pytest.raises(PublicationGateError, match="short_write"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            "slide-svg",
            slide_id,
            None,
            "worker-a",
            project / "slide-spec.yaml",
        )
    assert not destination.exists()
    assert load_artifacts(project) == {}
    assert not list(destination.parent.glob(".*.tmp"))


def test_publish_records_digest_from_destination_after_replace(tmp_path: Path) -> None:
    """Persist the digest measured from bytes at the replaced destination."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    destination = final_svg(project)
    source = staged_svg(tmp_path)
    result = publish_artifact(
        project,
        deck_id,
        source,
        destination,
        "slide-svg",
        slide_id,
        None,
        "worker-a",
        project / "slide-spec.yaml",
    )
    expected = hashlib.sha256(destination.read_bytes()).hexdigest()
    assert result["sha256"] == expected
    assert load_artifacts(project)[result["id"]]["sha256"] == expected


def test_publish_rejects_post_replace_digest_drift_without_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject bytes that differ when the replaced destination is measured."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    destination = final_svg(project)
    import publish_presentation_artifact as publisher

    original_digest = publisher._destination_digest

    def drifted_digest(path: Path) -> tuple[int, str]:
        size, digest = original_digest(path)
        if path == destination.resolve():
            return size, "0" * 64
        return size, digest

    monkeypatch.setattr(publisher, "_destination_digest", drifted_digest)
    with pytest.raises(PublicationGateError, match="destination_digest_mismatch"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            "slide-svg",
            slide_id,
            None,
            "worker-a",
            project / "slide-spec.yaml",
        )
    assert not destination.exists()
    assert load_artifacts(project) == {}


@pytest.mark.parametrize("failure", ["replace", "directory_fsync", "state_write"])
def test_publish_rolls_back_recoverable_failures(
    failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leave no destination or record after deterministic publication failures."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    destination = final_svg(project)
    import publish_presentation_artifact as publisher

    if failure == "replace":
        monkeypatch.setattr(publisher.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("replace")))
    elif failure == "directory_fsync":
        original_fsync = publisher.os.fsync
        directory_calls = 0

        def fail_directory_fsync(file_descriptor: int) -> None:
            nonlocal directory_calls
            try:
                target = Path(os.readlink(f"/proc/self/fd/{file_descriptor}"))
            except OSError:
                original_fsync(file_descriptor)
                return
            if target.resolve() == destination.parent.resolve():
                directory_calls += 1
                if directory_calls == 1:
                    raise OSError("fsync")
            original_fsync(file_descriptor)

        monkeypatch.setattr(publisher.os, "fsync", fail_directory_fsync)
    else:
        artifacts_path = project / ".research/presentations/state/artifacts.yaml"
        original_replace = publisher.os.replace

        def fail_state_replace(source: Path, target: Path) -> None:
            if Path(target) == artifacts_path:
                raise OSError("state")
            original_replace(source, target)

        monkeypatch.setattr(publisher.os, "replace", fail_state_replace)
    with pytest.raises(PublicationGateError):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            "slide-svg",
            slide_id,
            None,
            "worker-a",
            project / "slide-spec.yaml",
        )
    assert not destination.exists()
    assert load_artifacts(project) == {}
    assert not list(destination.parent.glob(".*.tmp"))


def test_publish_cleans_state_store_temp_after_state_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Remove a state-store sibling temp when its write fails."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    destination = final_svg(project)
    import publish_presentation_artifact as publisher

    artifacts_path = project / ".research/presentations/state/artifacts.yaml"
    original_replace = publisher.os.replace

    def fail_state_replace(source: Path, target: Path) -> None:
        if Path(target) == artifacts_path:
            raise OSError("state write")
        original_replace(source, target)

    monkeypatch.setattr(publisher.os, "replace", fail_state_replace)
    with pytest.raises(PublicationGateError):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            "slide-svg",
            slide_id,
            None,
            "worker-a",
            project / "slide-spec.yaml",
        )
    assert not destination.exists()
    assert load_artifacts(project) == {}
    state_dir = project / ".research/presentations/state"
    assert not list(state_dir.glob("*.stage.*.tmp"))


def test_publish_reports_temp_cleanup_failure_explicitly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expose temporary cleanup failure instead of masking it."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    destination = final_svg(project)
    import publish_presentation_artifact as publisher

    original_unlink = Path.unlink

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("replace")

    def fail_temp_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        if path.name.startswith(f".{destination.name}.") and ".rollback." not in path.name:
            raise OSError("cleanup")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(publisher.os, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_temp_unlink)
    with pytest.raises(PublicationGateError, match="temp_cleanup_failed"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            "slide-svg",
            slide_id,
            None,
            "worker-a",
            project / "slide-spec.yaml",
        )
    assert not destination.exists()
    assert load_artifacts(project) == {}


def test_publish_reports_rollback_failure_explicitly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never mask a rollback failure behind the original publication error."""
    project, deck_id, slide_id, _ = approved_assignment(tmp_path)
    _configure_slides_role(project)
    destination = final_svg(project)
    import publish_presentation_artifact as publisher

    publish_artifact(
        project,
        deck_id,
        staged_svg(tmp_path),
        destination,
        "slide-svg",
        slide_id,
        None,
        "worker-a",
        project / "slide-spec.yaml",
    )
    original_replace = publisher.os.replace
    replace_calls = 0

    def fail_primary_and_rollback(source: Path, target: Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls <= 2:
            raise OSError("rollback")
        original_replace(source, target)

    monkeypatch.setattr(publisher.os, "replace", fail_primary_and_rollback)
    with pytest.raises(PublicationGateError, match="rollback_failed"):
        publish_artifact(
            project,
            deck_id,
            staged_svg(tmp_path),
            destination,
            "slide-svg",
            slide_id,
            None,
            "worker-a",
            project / "slide-spec.yaml",
        )
