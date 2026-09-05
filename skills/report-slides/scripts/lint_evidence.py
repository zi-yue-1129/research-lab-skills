"""Persisted evidence that the visual-style linter ran, and on what.

The linter's exit code is not a gate. It exists for the length of one shell
command, in a process nothing else observes, and by the time
`assert_slide_passable` decides whether a slide may pass, the only honest answer
available to it is "no idea". This module gives that question an answer that
survives: an append-only event recording which rules fired, over which bytes,
under which token set.

Binding the result to both digests is the point. A lint result is a statement
about a specific SVG under a specific token file; change either and the
statement is not false, it is about something else. Evidence that no longer
matches is therefore treated as absent -- and reported distinctly, because
"nobody linted this" and "this was linted before it was rewritten" call for
different actions from the person reading the blocker.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import presentation_events as events
from design_tokens import DesignTokens, TokenError
from presentation_artifact_provenance import (
    MODULE_ARTIFACT_KINDS, SLIDE_ARTIFACT_KINDS,
)
from visual_style.report import LintReport

LINT_EVENT_TYPE = "visual_style_lint"

# The linted artifact for each subject kind, checked against the provenance
# module's own vocabulary so a renamed kind fails here rather than silently
# matching nothing and reading as "never linted".
_ARTIFACT_KIND_FOR_SUBJECT = {"slide": "slide-svg", "module": "module-svg"}
assert _ARTIFACT_KIND_FOR_SUBJECT["slide"] in SLIDE_ARTIFACT_KINDS
assert _ARTIFACT_KIND_FOR_SUBJECT["module"] in MODULE_ARTIFACT_KINDS

_SUBJECT_KEY = {"slide": "slide_id", "module": "module_id"}


def record_lint_evidence(
    project_root: Path,
    subject_type: str,
    subject_id: str,
    artifact_sha256: str,
    tokens_sha256: str,
    report: LintReport,
    tokens_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist one lint result as an immutable event.

    Args:
        project_root: Project root owning the presentation state.
        subject_type: `slide` or `module`.
        subject_id: The subject's generated identifier.
        artifact_sha256: Digest of the exact SVG bytes that were linted.
        tokens_sha256: Digest of the resolved token file the rules read.
        report: The result of `validate_visual_style.lint_svg`.
        tokens_path: Where that token file was read from. Recorded so the gate
            can notice the file changing after the run, which silently changes
            what every recorded result means.

    Returns:
        The persisted event mapping.

    Raises:
        ValueError: If `subject_type` is not a linted subject type.
    """
    if subject_type not in _ARTIFACT_KIND_FOR_SUBJECT:
        raise ValueError(
            f"subject_type must be slide or module, got {subject_type!r}")
    event: Dict[str, Any] = {
        "event": LINT_EVENT_TYPE,
        "id": f"lint-{uuid.uuid4().hex[:12]}",
        "ts": datetime.now(timezone.utc).isoformat(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "artifact_sha256": artifact_sha256,
        "tokens_sha256": tokens_sha256,
        "tokens_path": tokens_path,
        "errors": sorted({finding.rule for finding in report.findings
                          if finding.severity == "error"}),
        "warnings": sorted({finding.rule for finding in report.findings
                            if finding.severity == "warning"}),
    }
    events.append_event(project_root, event)
    return event


def _matching_events(
    project_root: Path, subject_type: str, subject_id: str
) -> List[Dict[str, Any]]:
    """Return every lint event recorded for one subject, oldest first.

    Args:
        project_root: Project root owning the presentation state.
        subject_type: `slide` or `module`.
        subject_id: The subject's generated identifier.

    Returns:
        The subject's lint events in chronological order.
    """
    return [
        event
        for event in events.load_events(project_root,
                                        event_type=LINT_EVENT_TYPE)
        if event.get("subject_type") == subject_type
        and event.get("subject_id") == subject_id
    ]


def current_lint_evidence(
    project_root: Path,
    subject_type: str,
    subject_id: str,
    artifact_sha256: str,
    tokens_sha256: str,
) -> Optional[Dict[str, Any]]:
    """Return the most recent evidence matching both digests exactly.

    Args:
        project_root: Project root owning the presentation state.
        subject_type: `slide` or `module`.
        subject_id: The subject's generated identifier.
        artifact_sha256: Digest of the SVG as it stands now.
        tokens_sha256: Digest of the token file as it stands now.

    Returns:
        The latest matching event, or `None` when the subject has never been
        linted in this exact configuration.
    """
    matches = [
        event
        for event in _matching_events(project_root, subject_type, subject_id)
        if event.get("artifact_sha256") == artifact_sha256
        and event.get("tokens_sha256") == tokens_sha256
    ]
    # `load_events` returns chronological order, so the last match is current.
    return matches[-1] if matches else None


def latest_lint_tokens_digest(
    project_root: Path, subject_type: str, subject_id: str
) -> Optional[str]:
    """Return the token digest the subject's most recent lint run used.

    A deck whose slides are all simple has no visual modules, so it declares no
    `style_tokens_ref` anywhere and there is no independent statement of which
    token set it is held to. The gate then binds the result to the SVG bytes
    alone and reports the token set the run itself recorded, which is weaker
    than a declaration but is what the deck actually asserts.

    Args:
        project_root: Project root owning the presentation state.
        subject_type: `slide` or `module`.
        subject_id: The subject's generated identifier.

    Returns:
        The `tokens_sha256` of the latest lint event, or `None` if the subject
        has never been linted.
    """
    events_for_subject = _matching_events(project_root, subject_type, subject_id)
    if not events_for_subject:
        return None
    digest = events_for_subject[-1].get("tokens_sha256")
    return str(digest) if digest else None


def _newest_svg_digests(
    project_root: Path, subject_type: str, subject_id: str
) -> List[str]:
    """Return the digests published for this subject at its newest timestamp.

    The artifact store is a map keyed by generated id, so it carries no order
    of its own and `created_at` resolves to the second. Two publications inside
    one second are therefore genuinely unordered, and this returns both rather
    than picking one.

    Args:
        project_root: Project root owning the presentation state.
        subject_type: `slide` or `module`.
        subject_id: The subject's generated identifier.

    Returns:
        The distinct digests carrying the newest `created_at`, sorted; empty
        when nothing has been published.
    """
    kind = _ARTIFACT_KIND_FOR_SUBJECT.get(subject_type)
    if kind is None:
        return []
    key = _SUBJECT_KEY[subject_type]
    records = [
        record for record in events.load_artifacts(project_root).values()
        if isinstance(record, Mapping)
        and record.get("artifact_kind") == kind
        and record.get(key) == subject_id
    ]
    if not records:
        return []
    newest = max(str(record.get("created_at", "")) for record in records)
    return sorted({
        str(record.get("sha256"))
        for record in records
        if str(record.get("created_at", "")) == newest and record.get("sha256")
    })


def current_svg_digest(
    project_root: Path, subject_type: str, subject_id: str
) -> Optional[str]:
    """Return the digest of the subject's current published SVG artifact.

    Args:
        project_root: Project root owning the presentation state.
        subject_type: `slide` or `module`.
        subject_id: The subject's generated identifier.

    Returns:
        The `sha256` of the most recent `slide-svg` or `module-svg` artifact
        record for this subject; `None` if none has been published, or if two
        publications share the newest timestamp and disagree, since there is
        then no fact of the matter about which bytes are current.
    """
    digests = _newest_svg_digests(project_root, subject_type, subject_id)
    return digests[0] if len(digests) == 1 else None


def lint_blockers(
    project_root: Path, subject_type: str, subject_id: str, tokens_sha256: str
) -> List[Dict[str, Any]]:
    """Report why the linter does not currently clear this subject.

    Args:
        project_root: Project root owning the presentation state.
        subject_type: `slide` or `module`.
        subject_id: The subject's generated identifier.
        tokens_sha256: Digest of the token file the subject is held to.

    Returns:
        Machine-readable blockers; empty means the linter passes on the current
        bytes. `lint_artifact_missing` means no SVG has been published at all,
        `lint_artifact_ambiguous` that two publications share the newest
        timestamp and disagree about the bytes,
        `lint_evidence_missing` that it has never been linted,
        `lint_evidence_stale` that the evidence predates the current bytes or
        token set, and `lint_failed` that hard errors are outstanding.
    """
    published = _newest_svg_digests(project_root, subject_type, subject_id)
    if not published:
        return [{"reason": "lint_artifact_missing"}]
    if len(published) > 1:
        return [{"reason": "lint_artifact_ambiguous", "digests": published}]
    artifact_sha256 = published[0]
    evidence = current_lint_evidence(
        project_root, subject_type, subject_id, artifact_sha256, tokens_sha256)
    if evidence is None:
        prior = _matching_events(project_root, subject_type, subject_id)
        reason = "lint_evidence_stale" if prior else "lint_evidence_missing"
        return [{"reason": reason}]
    drifted = _tokens_file_drifted(evidence)
    if drifted is not None:
        return [{"reason": "lint_tokens_changed", "tokens_path": drifted}]
    if evidence["errors"]:
        return [{"reason": "lint_failed", "rules": list(evidence["errors"])}]
    return []


def _tokens_file_drifted(evidence: Mapping[str, Any]) -> Optional[str]:
    """Return the token path whose content no longer matches the run, if any.

    Nothing in the state store records which token set a deck is held to, so
    the run's own token file is the contract. That makes editing the file after
    the run a silent change to what every recorded result means -- the only
    check available is that the file still hashes to what the run saw.

    Args:
        evidence: A lint event from `current_lint_evidence`.

    Returns:
        The recorded path when the file still exists and no longer matches, and
        `None` when it matches, was not recorded, or is no longer on this
        machine -- a result recorded elsewhere is not evidence of drift.
    """
    recorded = evidence.get("tokens_path")
    if not isinstance(recorded, str) or not recorded:
        return None
    path = Path(recorded)
    if not path.is_file():
        return None
    try:
        current = DesignTokens.load(path).digest
    except TokenError:
        # The file is there but no longer a valid token set, so it certainly is
        # not the one the run measured against.
        return recorded
    return None if current == evidence.get("tokens_sha256") else recorded


def unanswered_warnings(
    evidence: Mapping[str, Any], review: Mapping[str, Any]
) -> List[str]:
    """Return the warning rules this review has not answered.

    A warning is answered only by a non-empty answer naming that exact rule.
    Answers naming rules the run did not raise are ignored rather than credited:
    otherwise a reviewer could discharge every warning by pasting the answers
    from a different slide.

    Args:
        evidence: A lint event from `current_lint_evidence`.
        review: A Review Result mapping.

    Returns:
        The unanswered warning rules, sorted.
    """
    answers = review.get("linter_warnings_answered", [])
    if not isinstance(answers, (list, tuple)):
        answers = []
    answered = {
        str(entry.get("rule"))
        for entry in answers
        if isinstance(entry, Mapping) and str(entry.get("answer", "")).strip()
    }
    return sorted(set(evidence.get("warnings", [])) - answered)
