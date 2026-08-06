#!/usr/bin/env python3
"""complex_visual_detector.py -- Deterministic decision on whether a
planned visual must enter the complex-visual decomposition workflow
(Stage 7), reading configurable numeric thresholds instead of hard-coding
them only in natural-language agent instructions.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_THRESHOLDS_PATH = Path(__file__).resolve().parent.parent / "references" / "complex_visual_thresholds.yaml"
_QUALITATIVE_SIGNALS = (
    "multi_stage", "mixed_technique", "heavy_cross_region_connections", "expected_reuse", "not_atomic",
)


def load_thresholds(path: Path = DEFAULT_THRESHOLDS_PATH) -> Dict[str, int]:
    """Load the configurable numeric detection thresholds.

    Args:
        path: Path to the thresholds YAML file.

    Returns:
        {"region_count_threshold": int, "route_count_threshold": int}.

    Raises:
        ValueError: If a required key is missing or not an int.
    """
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    thresholds = {}
    for key in ("region_count_threshold", "route_count_threshold"):
        value = doc.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{path}: {key} must be an int, got {value!r}")
        thresholds[key] = value
    return thresholds


def requires_complex_workflow(signals: Dict[str, Any], thresholds: Dict[str, int]) -> Dict[str, Any]:
    """Decide whether a planned visual requires the complex-visual workflow.

    Args:
        signals: The Slide Architect's recorded complexity_signals --
            {"region_count": int, "route_count": int, "multi_stage": bool,
            "mixed_technique": bool, "heavy_cross_region_connections": bool,
            "expected_reuse": bool, "not_atomic": bool}.
        thresholds: {"region_count_threshold": int, "route_count_threshold": int}.

    Returns:
        {"requires_complex_workflow": bool, "triggered_signals": [str, ...]}.

    Raises:
        KeyError: If a required signal key is missing from `signals`.
    """
    triggered = []
    if signals["region_count"] > thresholds["region_count_threshold"]:
        triggered.append("region_count")
    if signals["route_count"] > thresholds["route_count_threshold"]:
        triggered.append("route_count")
    for key in _QUALITATIVE_SIGNALS:
        if signals[key]:
            triggered.append(key)
    return {"requires_complex_workflow": bool(triggered), "triggered_signals": triggered}


def main() -> None:
    """CLI entry point for complex_visual_detector.py."""
    parser = argparse.ArgumentParser(description="Decide whether a planned visual requires the complex-visual workflow.")
    parser.add_argument("--signals", metavar="PATH", type=Path, required=True)
    parser.add_argument("--thresholds", metavar="PATH", type=Path, default=DEFAULT_THRESHOLDS_PATH)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        signals = json.loads(args.signals.read_text(encoding="utf-8"))
        thresholds = load_thresholds(args.thresholds)
        result = requires_complex_workflow(signals, thresholds)
    except (KeyError, ValueError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}) if args.json else f"Error: {exc}")
        sys.exit(1)

    print(json.dumps(result) if args.json else json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
