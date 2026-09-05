#!/usr/bin/env python3
"""Style-anchor registry and banned-motif scan for generative illustration."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple, Union

import yaml

from design_tokens import DesignTokens

ANCHORS_PATH = (Path(__file__).resolve().parent.parent
                / "references" / "style-anchors" / "anchors.yaml")

_REQUIRED_FIELDS = ("id", "name", "summary", "applies_to", "composition",
                    "line_treatment", "palette_roles", "forbidden",
                    "reference_images")

# Spec D6: "Three candidates are generated and ranked blind against the anchor."
# Task 12 validates the generative record against this constant rather than a
# literal, so the width is stated once.
CANDIDATE_COUNT: int = 3

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

BANNED_MOTIFS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("glowing-neural-sphere",
     ("glowing neural", "neural network sphere", "glowing brain",
      "luminous network", "glowing orb of nodes")),
    ("light-ribbons",
     ("light ribbon", "flowing light", "light stream", "energy ribbon",
      "swirling light")),
    ("abstract-data-city",
     ("data city", "city of data", "digital cityscape", "skyline of data",
      "abstract cityscape")),
    ("anonymous-figure-at-laptop",
     ("lab coat", "figure at a laptop", "researcher at a laptop",
      "person at a laptop", "silhouette at a computer")),
    ("circuit-board-metaphor",
     ("glowing circuit", "circuit board background", "circuitry pattern",
      "circuit-like", "circuit pathway")),
    ("holographic-interface",
     ("holographic", "floating ui panel", "futuristic interface",
      "translucent dashboard floating")),
    ("binary-rain",
     ("binary rain", "falling ones and zeros", "cascading code")),
    ("handshake-of-human-and-machine",
     ("robot hand", "human hand touching", "handshake with a robot")),
    ("idea-lightbulb",
     ("lightbulb moment", "glowing lightbulb", "bulb of ideas")),
    ("gears-as-thinking",
     ("gears turning in", "cogs in the mind", "gears as thought")),
)


class AnchorError(ValueError):
    """Raised when the anchor registry is malformed or an anchor is unknown."""


@dataclass(frozen=True)
class ReferenceImage:
    """One curated reference image, pinned by content.

    Attributes:
        path: Resolved path to the image on disk.
        sha256: The digest recorded in the registry, verified on load.
    """

    path: Path
    sha256: str


@dataclass(frozen=True)
class StyleAnchor:
    """One bounded visual language an illustration must belong to.

    The anchor's identity is `reference_images`. The prose fields say what to
    attend to in those references and bind the anchor to the token palette; they
    do not stand in for the images. Spec D6 requires this: an anchor described
    only in words is the adjective list that produced the failure in spec 2.1.

    Attributes:
        anchor_id: Stable identifier cited by prompts.
        name: Human-readable name.
        summary: What the anchor is, in one sentence.
        applies_to: Subject kinds this anchor suits.
        composition: What to attend to in the references' frame arrangement.
        line_treatment: How lines, fills, and light behave in the references.
        palette_roles: Colour roles from the design-token file that may appear.
        forbidden: What this anchor refuses.
        reference_images: The curated references. Never empty.
    """

    anchor_id: str
    name: str
    summary: str
    applies_to: Tuple[str, ...]
    composition: str
    line_treatment: str
    palette_roles: Tuple[str, ...]
    forbidden: Tuple[str, ...]
    reference_images: Tuple[ReferenceImage, ...]


def _load_reference_images(entry: Mapping[str, Any], anchor_id: str,
                           base_dir: Path) -> Tuple[ReferenceImage, ...]:
    """Resolve and verify one anchor's reference images.

    Args:
        entry: The raw registry entry.
        anchor_id: The anchor being loaded, for error messages.
        base_dir: Directory the registry's relative paths resolve against.

    Returns:
        The verified references, in registry order.

    Raises:
        AnchorError: If the list is empty or malformed, a digest is not a
            64-character hex string, a file is missing, or a file's content does
            not match its recorded digest.
    """
    raw = entry.get("reference_images")
    if not isinstance(raw, list) or not raw:
        raise AnchorError(
            f"anchor {anchor_id!r} must list at least one entry under "
            f"'reference_images'; an anchor described only in prose is the "
            f"adjective list spec D6 refuses")
    references: List[ReferenceImage] = []
    for position, item in enumerate(raw):
        if not isinstance(item, dict) or not item.get("path") \
                or not item.get("sha256"):
            raise AnchorError(
                f"anchor {anchor_id!r} reference {position} must be a mapping "
                f"with 'path' and 'sha256'")
        digest = str(item["sha256"]).strip().lower()
        if not _SHA256_RE.match(digest):
            raise AnchorError(
                f"anchor {anchor_id!r} reference {item['path']!r} records "
                f"{digest!r}, which is not a SHA-256 digest")
        image_path = (base_dir / str(item["path"])).resolve()
        try:
            content = image_path.read_bytes()
        except OSError as exc:
            raise AnchorError(
                f"anchor {anchor_id!r} cites reference {item['path']!r} which "
                f"cannot be read at {image_path}: {exc}") from exc
        actual = hashlib.sha256(content).hexdigest()
        if actual != digest:
            raise AnchorError(
                f"anchor {anchor_id!r} reference {item['path']!r} has digest "
                f"{actual} but the registry records {digest}. A reference "
                f"swapped underneath an anchor is a different anchor: every "
                f"illustration ranked against the old one now belongs to a "
                f"different deck. Update the digest deliberately, in the same "
                f"commit as the replacement.")
        references.append(ReferenceImage(path=image_path, sha256=digest))
    return tuple(references)


def load_anchors(path: Union[str, Path] = ANCHORS_PATH
                 ) -> Dict[str, StyleAnchor]:
    """Load and validate the anchor registry.

    Args:
        path: Path to an `anchors.yaml` registry.

    Returns:
        A mapping from anchor id to anchor.

    Raises:
        AnchorError: If the file is missing, unparsable, an entry omits a
            required field, or a reference image is missing or does not match
            its recorded digest.
    """
    registry_path = Path(path)
    try:
        raw_text = registry_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AnchorError(f"cannot read anchor registry {registry_path}: {exc}"
                          ) from exc
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise AnchorError(f"cannot parse anchor registry {registry_path}: {exc}"
                          ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("anchors"), list):
        raise AnchorError(
            f"{registry_path} must contain a top-level 'anchors' list")

    anchors: Dict[str, StyleAnchor] = {}
    for position, entry in enumerate(data["anchors"]):
        if not isinstance(entry, dict):
            raise AnchorError(
                f"{registry_path} anchor {position} is not a mapping")
        missing = [field for field in _REQUIRED_FIELDS if not entry.get(field)]
        if missing:
            raise AnchorError(
                f"{registry_path} anchor {entry.get('id', position)!r} omits "
                f"required field(s): {', '.join(missing)}")
        anchor_id = str(entry["id"])
        if anchor_id in anchors:
            raise AnchorError(f"{registry_path} declares {anchor_id!r} twice")
        anchors[anchor_id] = StyleAnchor(
            anchor_id=anchor_id,
            name=str(entry["name"]),
            summary=str(entry["summary"]).strip(),
            applies_to=tuple(str(item) for item in entry["applies_to"]),
            composition=str(entry["composition"]).strip(),
            line_treatment=str(entry["line_treatment"]).strip(),
            palette_roles=tuple(str(item) for item in entry["palette_roles"]),
            forbidden=tuple(str(item) for item in entry["forbidden"]),
            reference_images=_load_reference_images(
                entry, anchor_id, registry_path.parent),
        )
    # An empty registry is the shipped state, not an error: spec D6 ships it
    # empty and makes populating it a human action. `get_anchor` is where that
    # state becomes a refusal, so the caller learns it at the point of use.
    return anchors


def anchor_available(path: Union[str, Path] = ANCHORS_PATH) -> bool:
    """Return whether any anchor is registered.

    Args:
        path: Path to the registry.

    Returns:
        True when at least one anchor is curated. False means the generative
        illustration route is closed and modules downgrade to a native
        editorial composition.

    Raises:
        AnchorError: If the registry exists but is malformed.
    """
    return bool(load_anchors(path))


def get_anchor(anchor_id: str,
               path: Union[str, Path] = ANCHORS_PATH) -> StyleAnchor:
    """Return one anchor by id.

    Args:
        anchor_id: The anchor to fetch.
        path: Path to the registry.

    Returns:
        The anchor.

    Raises:
        AnchorError: If the id is not registered. There is deliberately no
            default anchor: silently substituting one would reintroduce the
            unanchored prompt this registry exists to prevent.
    """
    anchors = load_anchors(path)
    if not anchors:
        raise AnchorError(
            f"the style-anchor registry at {Path(path)} is empty, so the "
            f"generative illustration route is closed and this module must "
            f"downgrade to a native editorial composition. Populating the "
            f"registry with curated reference images is a human action: see "
            f"references/style-anchors/README.md.")
    if anchor_id not in anchors:
        raise AnchorError(
            f"unknown style anchor {anchor_id!r}; registered anchors: "
            f"{', '.join(sorted(anchors))}")
    return anchors[anchor_id]


def scan_for_banned_motifs(text: str) -> List[str]:
    """Return the banned motifs a prompt asks for.

    Args:
        text: Prompt text.

    Returns:
        The ids of every banned motif whose trigger phrases appear, in registry
        order. An empty list is not a guarantee that the produced image is
        clean; it only means the prompt did not ask for a known motif.
    """
    haystack = re.sub(r"\s+", " ", text.lower())
    hits: List[str] = []
    for motif_id, phrases in BANNED_MOTIFS:
        if any(phrase in haystack for phrase in phrases):
            hits.append(motif_id)
    return hits


def prompt_fragment(anchor: StyleAnchor, tokens: DesignTokens) -> str:
    """Render an anchor as the art-direction block of a prompt.

    Args:
        anchor: The anchor to render.
        tokens: The resolved token set, used to expand palette roles into hex.

    Returns:
        A prompt fragment naming the anchor, the reference images the candidate
        will be ranked against, its composition and line treatment, its concrete
        palette, and what it refuses.

    Raises:
        TokenError: If the anchor names a colour role the token file lacks.
    """
    palette = ", ".join(
        f"{role} {tokens.color(role)}" for role in anchor.palette_roles)
    refusals = "; ".join(anchor.forbidden)
    # The references are named, with a digest prefix, so the recorded prompt
    # says which images the candidate was directed against. A fragment carrying
    # only the prose is the adjective list again.
    references = "; ".join(
        f"{reference.path.name} ({reference.sha256[:12]})"
        for reference in anchor.reference_images)
    return (
        f"style_anchor: {anchor.anchor_id} ({anchor.name}). "
        f"{anchor.summary} "
        f"Match these reference images: {references}. "
        f"Composition: {anchor.composition} "
        f"Line treatment: {anchor.line_treatment} "
        f"Palette, and no colour outside it: {palette}. "
        f"Do not include: {refusals}."
    )
