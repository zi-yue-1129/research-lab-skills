"""Automatic checks for the research deck quality standard.

See ``references/deck-quality/standard.md`` for the rules. Typical use at the
end of a deck generator::

    from deck_quality import enforce
    enforce("out/deck-20261105T183000.pptx", preset="zh-kai-times",
            exceptions="deck.exceptions.yaml", check_name=True)

``enforce`` raises ``DeckQualityError`` when any finding is not covered by a
listed exception, which makes the generator fail.
"""
from .config import RULES, Config, ConfigError, available_presets, load_exceptions, load_preset
from .fix import (DiagonalLineError, apply_font_pairing, orthogonal_segments, prune_older,
                  timestamped_output)
from .gate import DeckQualityError, Report, check_deck, enforce, gate_cli_output
from .rules import Finding, run_checks

__all__ = [
    "RULES", "Config", "ConfigError", "available_presets", "load_exceptions", "load_preset",
    "DiagonalLineError", "apply_font_pairing", "orthogonal_segments", "prune_older",
    "timestamped_output", "DeckQualityError", "Report", "check_deck", "enforce",
    "gate_cli_output", "Finding", "run_checks",
]
