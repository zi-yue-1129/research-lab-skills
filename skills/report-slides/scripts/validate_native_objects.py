#!/usr/bin/env python3
"""validate_native_objects.py -- safety-net gate for native PPTX table/chart/
group objects.

The primary defense is the agent-authoring rule (SKILL.md Stage 9.1 and the
data_visualization_worker_agent / architecture_diagram_worker_agent
instructions): author tables/charts/semantic node clusters with the
data-pptx-role SVG marker so svg_to_pptx/converter.py materializes real
PPTX objects. This script catches the two ways that rule can be missed:

  --svg-dir DIR   static pre-conversion scan: flags hand-drawn SVG shape
                  patterns (table grids, bar clusters, box+icon+label node
                  clusters) that are NOT wrapped in a data-pptx-role marker.
  --pptx FILE     post-conversion scan: opens the produced .pptx and flags
                  slides with an autoshape cluster matching those same
                  patterns and no accompanying native table/chart/group
                  object -- catching a converter bug that silently fell
                  through to shape-flattening despite a correctly
                  marked-up source SVG.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import yaml
from lxml import etree

DEFAULT_THRESHOLDS_PATH = (
    Path(__file__).resolve().parent.parent / "references" / "native_object_thresholds.yaml"
)


@dataclass(frozen=True)
class Finding:
    slide: str
    kind: str
    message: str


def load_thresholds(path: Path = DEFAULT_THRESHOLDS_PATH) -> Dict[str, float]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    required = ("min_grid_rows", "min_grid_cols", "min_bar_count",
                "min_cluster_shapes", "position_tolerance_px")
    thresholds: Dict[str, float] = {}
    for key in required:
        if key not in doc:
            raise ValueError(f"{path}: missing required key {key!r}")
        thresholds[key] = doc[key]
    return thresholds


def _local_tag(elem: Any) -> str:
    tag = elem.tag
    return tag.split("}")[-1] if isinstance(tag, str) and "}" in tag else str(tag)


def _has_pptx_role_ancestor(elem: Any) -> bool:
    node = elem.getparent()
    while node is not None:
        if node.get("data-pptx-role") in ("table", "chart", "group"):
            return True
        node = node.getparent()
    return False


def _close(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance


def _rect_box(elem: Any) -> Tuple[float, float, float, float]:
    return (
        float(elem.get("x", 0)), float(elem.get("y", 0)),
        float(elem.get("width", 0)), float(elem.get("height", 0)),
    )


def scan_svg(svg_path: Path, thresholds: Dict[str, float]) -> List[Finding]:
    """Flag hand-drawn table/chart/node patterns missing a data-pptx-role marker."""
    tree = etree.parse(str(svg_path))
    root = tree.getroot()
    tol = thresholds["position_tolerance_px"]

    rects = [
        elem for elem in root.iter()
        if _local_tag(elem) == "rect" and not _has_pptx_role_ancestor(elem)
    ]

    findings: List[Finding] = []
    findings.extend(_scan_table_like(svg_path.name, rects, thresholds, tol))
    findings.extend(_scan_bar_like(svg_path.name, rects, thresholds, tol))
    findings.extend(_scan_node_clusters(svg_path.name, root, thresholds))
    return findings


def _scan_table_like(slide_name: str, rects: List[Any],
                     thresholds: Dict[str, float], tol: float) -> List[Finding]:
    boxes = [_rect_box(r) for r in rects if r.get("width") and r.get("height")]
    row_groups: Dict[float, List[Tuple[float, float, float, float]]] = {}
    for x, y, w, h in boxes:
        matched_key = next((key for key in row_groups if _close(key, y, tol)), None)
        row_groups.setdefault(matched_key if matched_key is not None else y, []).append((x, y, w, h))

    grid_rows = [row for row in row_groups.values()
                if len(row) >= thresholds["min_grid_cols"]]
    if len(grid_rows) >= thresholds["min_grid_rows"]:
        return [Finding(
            slide_name, "table_like",
            f"{len(grid_rows)} rows of >= {thresholds['min_grid_cols']} aligned "
            "rects look like a hand-drawn table. Wrap the table in "
            '<g data-pptx-role="table" data-pptx-source="..." data-pptx-bbox="...">.',
        )]
    return []


def _scan_bar_like(slide_name: str, rects: List[Any],
                   thresholds: Dict[str, float], tol: float) -> List[Finding]:
    boxes = [_rect_box(r) for r in rects if r.get("width") and r.get("height")]
    baseline_groups: Dict[float, List[Tuple[float, float, float, float]]] = {}
    for x, y, w, h in boxes:
        baseline = y + h
        matched_key = next((key for key in baseline_groups if _close(key, baseline, tol)), None)
        baseline_groups.setdefault(
            matched_key if matched_key is not None else baseline, []
        ).append((x, y, w, h))

    for baseline, group in baseline_groups.items():
        heights = {round(h, 1) for _, _, _, h in group}
        if len(group) >= thresholds["min_bar_count"] and len(heights) > 1:
            return [Finding(
                slide_name, "chart_like",
                f"{len(group)} rects sharing baseline y={baseline:.0f} with "
                "varying heights look like a hand-drawn bar chart. Wrap the "
                'chart in <g data-pptx-role="chart" data-pptx-source="..." '
                'data-pptx-bbox="...">.',
            )]
    return []


def _scan_node_clusters(slide_name: str, root: Any,
                        thresholds: Dict[str, float]) -> List[Finding]:
    findings: List[Finding] = []
    for g in root.iter():
        if _local_tag(g) != "g" or g.get("data-pptx-role") is not None:
            continue
        if _has_pptx_role_ancestor(g):
            continue
        shape_children = [c for c in g if _local_tag(c) in
                         ("rect", "circle", "ellipse", "path", "image")]
        text_children = [c for c in g if _local_tag(c) == "text"]
        if len(shape_children) >= thresholds["min_cluster_shapes"] and text_children:
            findings.append(Finding(
                slide_name, "node_cluster_like",
                f"<g> with {len(shape_children)} shapes and a label looks like "
                "an unmarked diagram node. Wrap it in "
                '<g data-pptx-role="group" data-node-id="...">.',
            ))
    return findings


def scan_pptx(pptx_path: Path, thresholds: Dict[str, float]) -> List[Finding]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(str(pptx_path))
    findings: List[Finding] = []
    tol = thresholds["position_tolerance_px"]

    for slide_index, slide in enumerate(prs.slides, start=1):
        has_native_table = any(getattr(s, "has_table", False) for s in slide.shapes)
        has_native_chart = any(getattr(s, "has_chart", False) for s in slide.shapes)
        has_group = any(s.shape_type == MSO_SHAPE_TYPE.GROUP for s in slide.shapes)
        rect_like = [s for s in slide.shapes if s.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE]

        row_groups: Dict[int, int] = {}
        for shape in rect_like:
            matched_key = next(
                (key for key in row_groups if abs(key - shape.top) <= tol), None
            )
            key = matched_key if matched_key is not None else shape.top
            row_groups[key] = row_groups.get(key, 0) + 1
        grid_rows = sum(1 for count in row_groups.values()
                       if count >= thresholds["min_grid_cols"])

        slide_label = f"slide{slide_index}"
        if grid_rows >= thresholds["min_grid_rows"] and not has_native_table:
            findings.append(Finding(
                slide_label, "table_like",
                f"{grid_rows} rows of aligned autoshapes and no native table "
                "object -- converter likely fell through to shape-flattening.",
            ))
        if (len(rect_like) >= thresholds["min_cluster_shapes"] and not has_group
                and not has_native_table and not has_native_chart):
            findings.append(Finding(
                slide_label, "node_cluster_like",
                f"{len(rect_like)} ungrouped autoshapes -- if these form one "
                "semantic diagram node, they should be a native Group.",
            ))

    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect hand-drawn table/chart/node patterns missing "
                     "native PPTX table/chart/group objects."
    )
    targets = parser.add_mutually_exclusive_group(required=True)
    targets.add_argument("--svg-dir", type=Path,
                         help="Directory of slide*.svg files (pre-conversion scan).")
    targets.add_argument("--pptx", type=Path,
                         help="Produced .pptx file (post-conversion scan).")
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS_PATH)
    args = parser.parse_args(argv)

    thresholds = load_thresholds(args.thresholds)

    if args.svg_dir is not None:
        findings: List[Finding] = []
        for svg_path in sorted(args.svg_dir.glob("slide*.svg")):
            findings.extend(scan_svg(svg_path, thresholds))
    else:
        findings = scan_pptx(args.pptx, thresholds)

    if findings:
        for finding in findings:
            print(f"ERROR {finding.slide} [{finding.kind}]: {finding.message}",
                 file=sys.stderr)
        return 1

    print("OK: no unmarked table/chart/node patterns found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
