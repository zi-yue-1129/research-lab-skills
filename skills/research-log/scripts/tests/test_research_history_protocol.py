"""Instruction-level regression tests for proactive research history checks."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
RESEARCH_LOG = REPO_ROOT / "skills" / "research-log" / "SKILL.md"
RESEARCH_MODE = REPO_ROOT / "skills" / "research-mode" / "SKILL.md"
ROUTING_GUIDE = (
    REPO_ROOT / "skills" / "research-mode" / "references" / "routing_guide.md"
)


def _normalized_text(path: Path) -> str:
    """Return source text with Markdown line wrapping normalized to spaces."""
    return " ".join(path.read_text(encoding="utf-8").split())


def test_research_log_documents_strict_query_sequence() -> None:
    """Require discovery, manifest search, and selected retrieval in order."""
    text = _normalized_text(RESEARCH_LOG)

    for required_anchor in (
        "### query",
        "section_query.py",
        "macOS / Linux / Git Bash:",
        "Windows (PowerShell):",
        "types → search → fetch",
        "4,000",
        "8,000",
        "--cursor",
        "--chunk-cursor",
        "suggested_batches",
        "full type-cursor traversal",
        "full chunk traversal",
        "never silently truncate",
    ):
        assert required_anchor in text
    assert "must run `types` before every query" in text
    assert "may be skipped" not in text


def test_history_check_does_not_require_research_mode() -> None:
    """Require direct research intent to activate historical checking."""
    text = _normalized_text(RESEARCH_LOG)

    for required_anchor in (
        "Historical Experience Check",
        "Mode activation is not required",
        "direct research request",
        "non-empty `docs/research_log/` journal",
        "try this method",
        "change these experiment parameters",
        "why did this run fail?",
    ):
        assert required_anchor in text


def test_history_check_routes_research_events_and_reuses_session_results() -> None:
    """Require all research-intent routes and session-local duplicate avoidance."""
    text = _normalized_text(RESEARCH_LOG)

    for required_anchor in (
        "New method or experiment | Goal, Setup, Results, Failures, Conclusion",
        "Error or anomaly | Failures, Analysis, Next Steps",
        "Parameter or implementation change | Changes, Setup, Results, Analysis",
        "Costly rerun | Goal, Setup, Results, Failures",
        "at the start of a new research objective",
        "before proposing a new experimental method or configuration",
        "before a costly or long-running experiment",
        "when an error, anomalous result, or research blockage appears",
        "before repeating an experiment or operation",
        "journal state fingerprint",
        "session-local decision state",
        "does not repeat an identical query",
        "Open Problems",
    ):
        assert required_anchor in text


def test_history_check_distinguishes_interpretations_and_operation_gates() -> None:
    """Keep interpretation, advisory discussion, and costly-operation gates distinct."""
    text = _normalized_text(RESEARCH_LOG)

    for required_anchor in (
        "previously attempted and unsuccessful",
        "previously solved with an effective fix",
        "attempted with inconclusive results",
        "similar but materially different",
        "no relevant record found",
        "General research discussion: advisory",
        "Costly or long-running operation: preflight gate",
        "must not report a query failure as empty history",
        "journal is missing or contains no log entries",
        "passes without requiring the user to create one",
        "explicit user request to reproduce or verify prior work",
        "history and rerun rationale are surfaced",
    ):
        assert required_anchor in text


def test_mode_routing_covers_all_five_modes_with_report_exception() -> None:
    """Require explicit history behavior for every research mode."""
    combined = _normalized_text(RESEARCH_MODE) + _normalized_text(ROUTING_GUIDE)

    for required_anchor in (
        "`exp`",
        "`daily`",
        "`explore`",
        "`report`",
        "`publish`",
        "setup, run, failure, or rerun",
        "only when notes lead to a proposed research action",
        "before committing to a research direction already investigated",
        "reconstructing decisions, limitations, fixes, or prior evidence",
        "only when evidence or decision provenance must be recovered",
        "Direct research intent triggers the `research-log` protocol even when no mode is active",
    ):
        assert required_anchor in combined
