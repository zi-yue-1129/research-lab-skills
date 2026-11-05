"""Checker configuration: the core defaults, named presets, and exceptions.

The core is language-neutral. A *preset* (``references/deck-quality/presets/
<name>.yaml``) adds one language's or one house style's conventions: the font
pairing, the speaker-note click marker, the words that introduce a source
line, and public names the term rules must not flag. An *exceptions file*
waives individual findings for one deck, each with a written reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parents[2]
PRESET_DIR = SKILL_DIR / "references" / "deck-quality" / "presets"

#: Every rule the checker can report. ``EX`` is a problem in the exceptions
#: file itself and can never be waived.
RULES: dict[str, str] = {
    "A1": "CJK text in the CJK face, everything else in the Latin face",
    "A2": "each run holds one script; CJK runs set both latin and ea faces",
    "A3": "theme major and minor fonts are the same pairing",
    "B1": "mathematical notation, not code identifiers",
    "B2": "no internal version numbers, experiment codes, or run ids",
    "B4": "no source footnotes or file paths on the slide",
    "E1": "connector lines are horizontal and vertical segments only",
    "E2": "text does not overlap other text or leave the page",
    "F2": "every slide has speaker notes",
    "F3": "one click marker in the notes per click animation",
    "G1": "output is timestamped and only the newest copy is kept",
    "EX": "the exceptions file is valid and every exception is used",
}

CORE_SOURCE_LABELS = ("Source", "Sources", "Data source", "Credit", "Credits")
#: Public terms that look like experiment codes but are standard vocabulary.
CORE_ALLOW = ("F1", "L1", "L2")


@dataclass
class Config:
    """Effective settings for one check run."""

    name: str = "core"
    latin_font: str | None = None
    cjk_font: str | None = None
    click_marker: str = "[click]"
    source_labels: tuple[str, ...] = CORE_SOURCE_LABELS
    allow: tuple[str, ...] = CORE_ALLOW
    #: Rules to run; G1 runs only when the generator asks for it.
    rules: tuple[str, ...] = tuple(r for r in RULES if r not in ("G1", "EX"))

    @property
    def has_font_pairing(self) -> bool:
        return bool(self.latin_font and self.cjk_font)


class ConfigError(ValueError):
    """A preset or exceptions file cannot be used."""


def available_presets() -> list[str]:
    return sorted(p.stem for p in PRESET_DIR.glob("*.yaml"))


def load_preset(name_or_path: str | Path | None) -> Config:
    """Return the core config, extended by a preset name or YAML path."""
    if not name_or_path:
        return Config()
    path = Path(name_or_path)
    if not path.is_file():
        path = PRESET_DIR / f"{name_or_path}.yaml"
    if not path.is_file():
        raise ConfigError(f"deck-quality preset not found: {name_or_path}; "
                          f"available: {', '.join(available_presets()) or 'none'}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    fonts = data.get("fonts") or {}
    notes = data.get("notes") or {}
    terms = data.get("terms") or {}
    cfg = Config(
        name=str(data.get("name") or path.stem),
        latin_font=fonts.get("latin"),
        cjk_font=fonts.get("cjk"),
        click_marker=str(notes.get("click_marker") or Config.click_marker),
        source_labels=CORE_SOURCE_LABELS + tuple(terms.get("source_labels") or ()),
        allow=CORE_ALLOW + tuple(str(t) for t in terms.get("allow") or ()),
    )
    if bool(cfg.latin_font) != bool(cfg.cjk_font):
        raise ConfigError(f"preset {cfg.name}: fonts needs both 'latin' and 'cjk'")
    return cfg


@dataclass
class Exception_:
    """One waived finding: rule, optional slide and text match, and why."""

    rule: str
    reason: str
    slide: int | None = None
    match: str | None = None
    used: int = field(default=0, compare=False)

    def covers(self, finding) -> bool:
        if finding.rule != self.rule:
            return False
        if self.slide is not None and finding.slide != self.slide:
            return False
        if self.match and self.match not in f"{finding.subject} {finding.message}":
            return False
        return True

    def describe(self) -> str:
        where = f" slide {self.slide}" if self.slide is not None else ""
        what = f" matching {self.match!r}" if self.match else ""
        return f"{self.rule}{where}{what}"


def load_exceptions(path: str | Path | None) -> list[Exception_]:
    """Read an exceptions file. Every entry needs a known rule and a reason."""
    if not path:
        return []
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"exceptions file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("exceptions") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise ConfigError(f"{path}: expected a list under 'exceptions'")
    out: list[Exception_] = []
    for i, e in enumerate(entries, 1):
        if not isinstance(e, dict):
            raise ConfigError(f"{path}: exception {i} is not a mapping")
        rule = str(e.get("rule") or "").strip()
        reason = str(e.get("reason") or "").strip()
        if rule not in RULES or rule == "EX":
            raise ConfigError(f"{path}: exception {i} names unknown rule {rule!r}")
        if not reason:
            raise ConfigError(f"{path}: exception {i} ({rule}) has no reason; "
                              "every exception must say why it is allowed")
        slide = e.get("slide")
        out.append(Exception_(rule=rule, reason=reason,
                              slide=int(slide) if slide is not None else None,
                              match=str(e["match"]) if e.get("match") else None))
    return out
