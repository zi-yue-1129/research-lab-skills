"""Tests for the style-anchor registry and the banned-motif scan."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Tuple

import pytest
import yaml
from PIL import Image

from design_tokens import DEFAULT_TOKENS_PATH, DesignTokens
from style_anchors import (
    ANCHORS_PATH, BANNED_MOTIFS, CANDIDATE_COUNT, AnchorError,
    anchor_available, get_anchor, load_anchors, prompt_fragment,
    scan_for_banned_motifs,
)


@pytest.fixture(scope="module")
def tokens() -> DesignTokens:
    """Load the shipped default token set."""
    return DesignTokens.load(DEFAULT_TOKENS_PATH)


def _write_reference(directory: Path, name: str) -> Tuple[Path, str]:
    """Write a small PNG and return its path and digest.

    A four-pixel image is enough: the registry checks file integrity, not
    picture content. The digest is computed here rather than hard-coded,
    because a literal would pin this test to one Pillow release's PNG encoder.

    Args:
        directory: Where to write the file.
        name: File name to use.

    Returns:
        `(path, sha256_hex)`.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (30, 58, 95)).save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())
    return path, hashlib.sha256(buffer.getvalue()).hexdigest()


def _registry(tmp_path: Path, **overrides: object) -> Path:
    """Write a one-anchor registry with a real reference image.

    Args:
        tmp_path: Test temporary directory.
        **overrides: Entry fields to replace or, when the value is None, drop.

    Returns:
        Path to the written `anchors.yaml`.
    """
    reference, digest = _write_reference(tmp_path / "refs", "schematic-01.png")
    entry = {
        "id": "technical-schematic",
        "name": "Technical schematic",
        "summary": "A flat drafted diagram in the manner of a paper figure.",
        "applies_to": ["system architectures"],
        "composition": "Orthogonal arrangement on a single plane.",
        "line_treatment": "Uniform-weight outlines, flat fills.",
        "palette_roles": ["primary", "body", "line", "bg"],
        "forbidden": ["glow or bloom", "photographic texture"],
        "reference_images": [
            {"path": reference.name, "sha256": digest},
        ],
    }
    for key, value in overrides.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    path = tmp_path / "refs" / "anchors.yaml"
    path.write_text(yaml.safe_dump({"anchors": [entry]}), encoding="utf-8")
    return path


def test_the_shipped_registry_is_empty_by_design() -> None:
    """Spec D6 ships the registry empty; populating it is a human action.

    Seeding it with prose anchors is what this phase exists to prevent, so the
    emptiness is asserted rather than left to convention. If this test fails
    because someone added an anchor with real curated references, that is the
    intended workflow -- update the test in the same commit and say whose
    references were added.
    """
    assert ANCHORS_PATH.is_file()
    assert load_anchors() == {}
    assert anchor_available() is False


def test_an_empty_registry_closes_the_generative_route() -> None:
    """With no anchor, `get_anchor` refuses and names the procedure."""
    with pytest.raises(AnchorError) as excinfo:
        get_anchor("technical-schematic")
    message = str(excinfo.value)
    assert "empty" in message
    assert "style-anchors/README.md" in message


def test_a_populated_anchor_declares_its_full_contract(tmp_path: Path) -> None:
    """A partial anchor cannot direct an illustration."""
    anchors = load_anchors(_registry(tmp_path))
    anchor = anchors["technical-schematic"]
    assert anchor.anchor_id == "technical-schematic"
    assert anchor.summary
    assert anchor.composition
    assert anchor.line_treatment
    assert anchor.applies_to
    assert anchor.palette_roles
    assert anchor.forbidden
    assert anchor.reference_images


def test_an_anchor_without_reference_images_is_rejected(
    tmp_path: Path,
) -> None:
    """Prose alone is the adjective list spec D6 refuses."""
    with pytest.raises(AnchorError) as excinfo:
        load_anchors(_registry(tmp_path, reference_images=None))
    assert "reference_images" in str(excinfo.value)


def test_an_empty_reference_image_list_is_rejected(tmp_path: Path) -> None:
    """An empty list is the same defect as a missing field."""
    with pytest.raises(AnchorError):
        load_anchors(_registry(tmp_path, reference_images=[]))


def test_a_missing_reference_file_is_rejected(tmp_path: Path) -> None:
    """A registry may not cite a reference that is not on disk."""
    path = _registry(tmp_path)
    (tmp_path / "refs" / "schematic-01.png").unlink()
    with pytest.raises(AnchorError) as excinfo:
        load_anchors(path)
    assert "schematic-01.png" in str(excinfo.value)


def test_a_stale_reference_digest_is_rejected(tmp_path: Path) -> None:
    """A reference swapped underneath the anchor is a different anchor.

    Two illustrations ranked against different references do not belong to the
    same deck, which is exactly the `style-drift` finding the art-direction
    reviewer reports. Failing closed here is cheaper than finding it at review.
    """
    path = _registry(tmp_path)
    reference = tmp_path / "refs" / "schematic-01.png"
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buffer, format="PNG")
    reference.write_bytes(buffer.getvalue())
    with pytest.raises(AnchorError) as excinfo:
        load_anchors(path)
    message = str(excinfo.value)
    assert "digest" in message
    assert "schematic-01.png" in message


def test_anchor_palette_roles_exist_in_the_token_file(
    tokens: DesignTokens, tmp_path: Path,
) -> None:
    """An anchor may only name colour roles the design system defines."""
    for anchor in load_anchors(_registry(tmp_path)).values():
        for role in anchor.palette_roles:
            assert tokens.color(role)


def test_get_anchor_rejects_an_unknown_id(tmp_path: Path) -> None:
    """An unknown anchor fails loudly rather than falling back to a default."""
    with pytest.raises(AnchorError) as excinfo:
        get_anchor("vibes", _registry(tmp_path))
    assert "vibes" in str(excinfo.value)


def test_a_malformed_registry_is_rejected(tmp_path: Path) -> None:
    """A registry missing required fields is an error, not a partial load."""
    bad = tmp_path / "anchors.yaml"
    bad.write_text("anchors:\n  - id: broken\n    name: Broken\n",
                   encoding="utf-8")
    with pytest.raises(AnchorError):
        load_anchors(bad)


def test_the_candidate_count_matches_the_spec() -> None:
    """Spec D6 requires three candidates ranked blind; Task 12 reads this."""
    assert CANDIDATE_COUNT == 3


def test_banned_motifs_name_the_documented_failure_mode() -> None:
    """The registry must name the motifs the shipped example actually used."""
    motif_ids = {motif_id for motif_id, _ in BANNED_MOTIFS}
    for expected in ("glowing-neural-sphere", "light-ribbons",
                     "abstract-data-city", "anonymous-figure-at-laptop"):
        assert expected in motif_ids


def test_the_scan_catches_the_shipped_examples_prompt() -> None:
    """The prompt that produced the documented failure must not pass."""
    prompt = ("A researcher in a white lab coat at a laptop, with a glowing "
              "neural network sphere and flowing light ribbons above an "
              "abstract data city skyline.")
    hits = scan_for_banned_motifs(prompt)
    assert "glowing-neural-sphere" in hits
    assert "light-ribbons" in hits
    assert "abstract-data-city" in hits
    assert "anonymous-figure-at-laptop" in hits


def test_the_scan_is_case_insensitive() -> None:
    """Capitalisation must not be an escape hatch."""
    assert scan_for_banned_motifs("A GLOWING NEURAL NETWORK sphere")


def test_a_specific_prompt_passes_the_scan() -> None:
    """A prompt about the actual subject is not penalised."""
    prompt = ("A cross-section of a three-stage retrieval pipeline showing "
              "document chunks entering an index and ranked passages leaving "
              "it, drawn as a flat schematic.")
    assert scan_for_banned_motifs(prompt) == []


def test_prompt_fragment_binds_the_anchor_to_the_tokens(
    tokens: DesignTokens, tmp_path: Path,
) -> None:
    """The generated fragment carries concrete hex values, not role names."""
    anchor = get_anchor("technical-schematic", _registry(tmp_path))
    fragment = prompt_fragment(anchor, tokens)
    assert "technical-schematic" in fragment
    assert "#" in fragment
    for role in anchor.palette_roles:
        assert tokens.color(role) in fragment
    for forbidden in anchor.forbidden:
        assert forbidden in fragment


def test_prompt_fragment_cites_the_reference_images(
    tokens: DesignTokens, tmp_path: Path,
) -> None:
    """The fragment must point at the reference, not only describe it.

    A prompt that carries the prose but drops the reference is the adjective
    list again. The digest travels with it so the record says which reference
    the illustration was directed against.
    """
    anchor = get_anchor("technical-schematic", _registry(tmp_path))
    fragment = prompt_fragment(anchor, tokens)
    for reference in anchor.reference_images:
        assert reference.path.name in fragment
        assert reference.sha256[:12] in fragment


def test_prompt_fragment_is_itself_clean(
    tokens: DesignTokens, tmp_path: Path,
) -> None:
    """The registry must not smuggle a banned motif into its own output."""
    for anchor in load_anchors(_registry(tmp_path)).values():
        assert scan_for_banned_motifs(
            prompt_fragment(anchor, tokens)) == []
