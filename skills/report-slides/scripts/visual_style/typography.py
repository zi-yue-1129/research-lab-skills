"""Typography rules: size floors, size variety, and text length budgets."""
from __future__ import annotations

from typing import List, Optional, Tuple

from design_tokens import DesignTokens, TokenError, TypeRole

from .report import Finding
from .scene import Scene, TextRun

RULES: Tuple[str, ...] = ("type-floor", "type-variety", "overlong-text")

BODY_WORD_BUDGET = 90
_SIZE_TOLERANCE = 0.5


def _role_name(run: TextRun) -> Optional[str]:
    """Map a run's style role onto a typography role name.

    Authoring roles are dotted, such as `node.label`; typography roles are
    underscored, such as `node_label`. A single-segment role is used as is.

    Args:
        run: The text run.

    Returns:
        The typography role name, or None when the run declares no role.
    """
    if not run.style_role:
        return None
    return run.style_role.replace(".", "_")


def _smallest_role(tokens: DesignTokens) -> Tuple[str, float]:
    """Return the smallest declared typography role and its size.

    Args:
        tokens: The resolved token set.

    Returns:
        `(role_name, size)` for the smallest role.
    """
    roles = tokens.raw["typography"]["roles"]
    name = min(roles, key=lambda key: float(roles[key]["size"]))
    return name, float(roles[name]["size"])


def check_type_floor(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report text rendered below the floor its role sets.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `type-floor` error per offending run.
    """
    fallback_name, fallback_size = _smallest_role(tokens)
    findings: List[Finding] = []
    for run in scene.texts:
        name = _role_name(run)
        if name is None:
            if run.size < fallback_size - _SIZE_TOLERANCE:
                findings.append(Finding(
                    rule="type-floor", severity="error",
                    message=f"{run.element_id} is {run.size:g} with no declared "
                            f"style role; the smallest role {fallback_name} is "
                            f"{fallback_size:g}",
                    element_id=run.element_id, location=(run.x, run.y)))
            continue
        try:
            role: TypeRole = tokens.type_role(name)
        except TokenError:
            findings.append(Finding(
                rule="type-floor", severity="error",
                message=f"{run.element_id} declares style role "
                        f"{run.style_role!r}, which resolves to {name!r} and is "
                        f"not defined in the token file",
                element_id=run.element_id, location=(run.x, run.y)))
            continue
        if run.size < role.size - _SIZE_TOLERANCE:
            findings.append(Finding(
                rule="type-floor", severity="error",
                message=f"{run.element_id} is {run.size:g}; role {name} "
                        f"requires at least {role.size:g}",
                element_id=run.element_id, location=(run.x, run.y)))
    return findings


def check_type_variety(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report slides using more distinct sizes than the token budget allows.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        At most one `type-variety` warning.
    """
    budget = int(tokens.raw["typography"]["max_sizes_per_slide"])
    sizes = sorted({round(run.size, 2) for run in scene.texts})
    if len(sizes) <= budget:
        return []
    rendered = ", ".join(f"{size:g}" for size in sizes)
    return [Finding(
        rule="type-variety", severity="warning",
        message=f"slide uses {len(sizes)} distinct font sizes ({rendered}); "
                f"typography.max_sizes_per_slide is {budget}")]


def check_overlong_text(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Report text exceeding its line budget or the body word budget.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        One `overlong-text` warning per offending run.
    """
    findings: List[Finding] = []
    for run in scene.texts:
        name = _role_name(run)
        if name is None:
            continue
        try:
            role = tokens.type_role(name)
        except TokenError:
            # Unknown roles are already reported by check_type_floor; reporting
            # them twice would inflate one defect into two.
            continue
        if run.line_count > role.max_lines:
            findings.append(Finding(
                rule="overlong-text", severity="warning",
                message=f"{run.element_id} runs to {run.line_count} lines; "
                        f"role {name} allows {role.max_lines}",
                element_id=run.element_id, location=(run.x, run.y)))
        if name == "body":
            words = len(run.text.split())
            if words > BODY_WORD_BUDGET:
                findings.append(Finding(
                    rule="overlong-text", severity="warning",
                    message=f"{run.element_id} carries {words} words; the body "
                            f"budget is {BODY_WORD_BUDGET}",
                    element_id=run.element_id, location=(run.x, run.y)))
    return findings


def check(scene: Scene, tokens: DesignTokens) -> List[Finding]:
    """Run every typography rule.

    Args:
        scene: The parsed slide.
        tokens: The resolved token set.

    Returns:
        All typography findings, unordered.
    """
    findings: List[Finding] = []
    findings.extend(check_type_floor(scene, tokens))
    findings.extend(check_type_variety(scene, tokens))
    findings.extend(check_overlong_text(scene, tokens))
    return findings
