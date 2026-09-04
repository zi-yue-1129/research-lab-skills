"""Design-token contract loader for report-slides.

The token file is the machine contract for the visual system. Style Markdown
frontmatter remains human documentation and is never read by renderers.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Union

import jsonschema
import yaml

_REFERENCES_DIR = Path(__file__).resolve().parent.parent / "references"
SCHEMA_PATH = _REFERENCES_DIR / "design-tokens.schema.json"
DEFAULT_TOKENS_PATH = _REFERENCES_DIR / "tokens" / "default.tokens.yaml"


class TokenError(ValueError):
    """Raised when a token file is missing, unparsable, or schema-invalid.

    Never caught in order to substitute built-in defaults: an unusable token file
    is a hard failure, because a silently ignored style is indistinguishable from
    a correctly applied one.
    """


@dataclass(frozen=True)
class TypeRole:
    """One resolved typographic role.

    Attributes:
        size: Font size in SVG units, which map 1:1 to PowerPoint points.
        weight: CSS numeric font weight.
        line_height: Multiplier applied to `size` for baseline spacing.
        max_lines: Maximum permitted rendered lines for this role.
        family: Key into the token `typography.family` mapping.
    """

    size: float
    weight: int
    line_height: float
    max_lines: int
    family: str


class DesignTokens:
    """A validated, immutable view over one design-token file."""

    def __init__(self, data: Mapping[str, Any], path: Path) -> None:
        """Store validated token data and compute its digest.

        Args:
            data: Token mapping already validated against the schema.
            path: Filesystem path the tokens were loaded from.
        """
        self._data = data
        self._path = path
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        self._digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def load(cls, path: Union[str, Path]) -> "DesignTokens":
        """Load and validate a token file.

        Args:
            path: Path to a `.tokens.yaml` file.

        Returns:
            A validated `DesignTokens` instance.

        Raises:
            TokenError: If the file is missing, unparsable, or violates the schema.
        """
        token_path = Path(path)
        try:
            raw_text = token_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TokenError(f"cannot read token file {token_path}: {exc}") from exc
        try:
            data = yaml.safe_load(raw_text)
        except yaml.YAMLError as exc:
            raise TokenError(f"cannot parse token file {token_path}: {exc}") from exc
        if not isinstance(data, dict):
            raise TokenError(f"token file {token_path} must contain a mapping")
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        try:
            jsonschema.Draft202012Validator(schema).validate(data)
        except jsonschema.ValidationError as exc:
            location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
            raise TokenError(
                f"token file {token_path} is invalid at {location}: {exc.message}"
            ) from exc
        errors = semantic_errors(data)
        if errors:
            joined = "; ".join(errors)
            raise TokenError(f"token file {token_path} is inconsistent: {joined}")
        return cls(data, token_path)

    @property
    def digest(self) -> str:
        """Return the sha256 hex digest of the canonicalised token content."""
        return self._digest

    @property
    def path(self) -> Path:
        """Return the path the tokens were loaded from."""
        return self._path

    @property
    def raw(self) -> Mapping[str, Any]:
        """Return the underlying token mapping."""
        return self._data

    def type_role(self, name: str) -> TypeRole:
        """Return one typographic role.

        Args:
            name: Role key, such as `slide_title` or `node_label`.

        Returns:
            The resolved `TypeRole`.

        Raises:
            TokenError: If the role is not defined.
        """
        roles = self._data["typography"]["roles"]
        if name not in roles:
            raise TokenError(
                f"undefined type role {name!r}; defined roles: {sorted(roles)}"
            )
        role = roles[name]
        return TypeRole(
            size=float(role["size"]),
            weight=int(role["weight"]),
            line_height=float(role["line_height"]),
            max_lines=int(role["max_lines"]),
            family=str(role["family"]),
        )

    def font_stack(self, family_key: str) -> str:
        """Return the CSS font stack for a family key.

        Args:
            family_key: Key into `typography.family`, such as `sans`.

        Returns:
            The CSS `font-family` value.

        Raises:
            TokenError: If the family key is not defined.
        """
        families = self._data["typography"]["family"]
        if family_key not in families:
            raise TokenError(
                f"undefined font family {family_key!r}; "
                f"defined families: {sorted(families)}"
            )
        return str(families[family_key])

    def color(self, role: str) -> str:
        """Return the hex value for a colour role.

        Args:
            role: Colour role key, such as `primary`.

        Returns:
            A `#rrggbb` string.

        Raises:
            TokenError: If the role is not defined.
        """
        roles = self._data["color"]["roles"]
        if role not in roles:
            raise TokenError(
                f"undefined colour role {role!r}; defined roles: {sorted(roles)}"
            )
        return str(roles[role])

    def is_decorative(self, role: str) -> bool:
        """Return whether a colour role is exempt from the graphic contrast floor.

        Args:
            role: Colour role key.

        Returns:
            True when the role is listed in `color.decorative_roles`.
        """
        return role in self._data["color"]["decorative_roles"]

    def surface(self, name: str) -> Mapping[str, Any]:
        """Return one surface definition.

        Args:
            name: Surface key, such as `node` or `card`.

        Returns:
            The surface mapping with `radius`, `border_width`, `fill`, `border`,
            and `padding`.

        Raises:
            TokenError: If the surface is not defined.
        """
        surfaces = self._data["surfaces"]
        if name not in surfaces:
            raise TokenError(
                f"undefined surface {name!r}; defined surfaces: {sorted(surfaces)}"
            )
        return surfaces[name]


def semantic_errors(data: Mapping[str, Any]) -> List[str]:
    """Return the cross-field inconsistencies JSON Schema cannot express.

    A schema validates each value against its own constraint and knows nothing
    about the relationships between them. A token file with
    `occupancy_min: 0.9, occupancy_max: 0.3`, or a surface whose `fill` names a
    colour role that does not exist, is schema-valid and unusable -- and the
    failure surfaces several files away from the mistake, as a `TokenError` from
    `color()` during a render, or as a linter finding nobody can explain.

    Args:
        data: A schema-valid token mapping.

    Returns:
        Human-readable inconsistencies, empty when the file is coherent.
    """
    errors: List[str] = []
    color_roles = set(data["color"]["roles"])
    families = set(data["typography"]["family"])

    density = data["density"]
    if density["occupancy_min"] >= density["occupancy_max"]:
        errors.append(
            f"density.occupancy_min ({density['occupancy_min']}) must be below "
            f"occupancy_max ({density['occupancy_max']}); as written no slide "
            f"can satisfy both"
        )

    for name, role in sorted(data["typography"]["roles"].items()):
        if role["family"] not in families:
            errors.append(
                f"typography.roles.{name}.family names {role['family']!r}, "
                f"which is not in typography.family ({sorted(families)})"
            )

    for name, surface in sorted(data["surfaces"].items()):
        for key in ("fill", "border"):
            if surface[key] not in color_roles:
                errors.append(
                    f"surfaces.{name}.{key} names {surface[key]!r}, which is "
                    f"not a colour role ({sorted(color_roles)})"
                )

    unknown = sorted(set(data["color"]["decorative_roles"]) - color_roles)
    if unknown:
        errors.append(
            f"color.decorative_roles names {unknown}, which are not colour "
            f"roles; a decorative exemption for a role nothing uses silently "
            f"exempts nothing"
        )

    scale = data["spacing"]["scale"]
    if sorted(set(scale)) != list(scale):
        errors.append(
            f"spacing.scale {scale} must be strictly ascending and unique; a "
            f"spacing scale is an ordered vocabulary, and a repeated or "
            f"out-of-order step makes 'the next step up' undefined"
        )
    # Deliberately not checked: that every step is a multiple of `canvas.grid`.
    # The shipped scale opens with 4 against a grid of 8, and `node_padding.y`
    # is 12. A half-step for tight internal padding is ordinary practice, and a
    # rule that rejected it would reject this plan's own token file.

    return errors
