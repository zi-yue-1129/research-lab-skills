#!/usr/bin/env python3
"""validate_pptx_structure.py -- Real structural validation of a produced
.pptx file: package integrity, slide count, relationship integrity, and
an editability cross-check against what a manifest/module declared.

Read-only auditor: never modifies the .pptx it inspects, and does not
touch svg_to_pptx/'s generation code. Stdlib zipfile/xml.etree only, no
new dependencies beyond python-pptx (already required by to_pptx.py).
"""
import argparse
import datetime
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

_NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


class PptxStructureError(ValueError):
    """Raised when the .pptx file cannot be opened or parsed at all
    (as opposed to a structural finding, which is reported, not raised)."""


def _read_xml(zf: zipfile.ZipFile, name: str) -> ET.Element:
    """Read and parse one XML part from the .pptx zip.

    Args:
        zf: The open zip archive.
        name: The part's path inside the archive.

    Returns:
        The parsed XML root element.

    Raises:
        PptxStructureError: If the part is missing or malformed.
    """
    try:
        return ET.fromstring(zf.read(name))
    except KeyError as exc:
        raise PptxStructureError(f"missing required part: {name}") from exc
    except ET.ParseError as exc:
        raise PptxStructureError(f"malformed XML in {name}: {exc}") from exc


def _slide_names(zf: zipfile.ZipFile, presentation_xml: ET.Element) -> List[str]:
    """Return slide part names in presentation order.

    Args:
        zf: The open zip archive.
        presentation_xml: The parsed ppt/presentation.xml root.

    Returns:
        Slide part paths (e.g. "ppt/slides/slide1.xml"), in the order
        <p:sldIdLst> declares them -- not a sorted glob, since order
        matters for slide-count/expected_slides correspondence.

    Raises:
        PptxStructureError: If ppt/_rels/presentation.xml.rels is missing
            or malformed.
    """
    rels = _read_xml(zf, "ppt/_rels/presentation.xml.rels")
    rid_to_target = {rel.get("Id"): rel.get("Target") for rel in rels.findall("rel:Relationship", _NS)}
    names = []
    sld_id_lst = presentation_xml.find("p:sldIdLst", _NS)
    for sld_id in (sld_id_lst if sld_id_lst is not None else []):
        rid = sld_id.get("{%s}id" % _NS["r"])
        target = rid_to_target.get(rid)
        if target:
            names.append(target if target.startswith("ppt/") else f"ppt/{target.lstrip('/')}")
    return names


def _relationship_violations(zf: zipfile.ZipFile, slide_name: str) -> List[Dict[str, Any]]:
    """Check that every r:embed/r:id/r:link referenced inside a slide
    resolves to a .rels entry whose Target exists in the package.

    Args:
        zf: The open zip archive.
        slide_name: The slide part's path.

    Returns:
        A list of violation dicts; empty if all references resolve.
    """
    violations: List[Dict[str, Any]] = []
    slide_xml = _read_xml(zf, slide_name)
    rels_name = slide_name.replace("slides/", "slides/_rels/") + ".rels"
    try:
        rels_xml = _read_xml(zf, rels_name)
        rid_to_target = {rel.get("Id"): rel.get("Target") for rel in rels_xml.findall("rel:Relationship", _NS)}
    except PptxStructureError:
        rid_to_target = {}
    referenced_rids = set()
    for elem in slide_xml.iter():
        for attr in ("{%s}embed" % _NS["r"], "{%s}id" % _NS["r"], "{%s}link" % _NS["r"]):
            rid = elem.get(attr)
            if rid:
                referenced_rids.add(rid)
    slide_dir = "/".join(slide_name.split("/")[:-1])
    for rid in referenced_rids:
        target = rid_to_target.get(rid)
        if target is None:
            violations.append({"slide": slide_name, "rid": rid, "issue": "no matching relationship entry"})
            continue
        resolved = target if target.startswith("ppt/") else f"{slide_dir}/{target}"
        resolved = resolved.replace("/./", "/").replace("slides/../", "")
        if resolved.lstrip("/") not in zf.namelist():
            violations.append({"slide": slide_name, "rid": rid, "issue": f"target does not exist: {resolved}"})
    return violations


def _observed_editability(zf: zipfile.ZipFile, slide_name: str) -> str:
    """Classify a slide's shape content.

    Args:
        zf: The open zip archive.
        slide_name: The slide part's path.

    Returns:
        "native" (vector shapes only), "raster" (a picture and no vector
        shapes), or "hybrid" (both present).
    """
    slide_xml = _read_xml(zf, slide_name)
    sp_tree = slide_xml.find(".//p:cSld/p:spTree", _NS)
    has_vector = sp_tree is not None and any(
        sp_tree.findall(f"p:{tag}", _NS) for tag in ("sp", "cxnSp")
    )
    has_picture = sp_tree is not None and len(sp_tree.findall("p:pic", _NS)) > 0
    if has_vector and has_picture:
        return "hybrid"
    if has_picture:
        return "raster"
    return "native"


def validate_pptx_structure(
    pptx_path: Path, expected_slides: int, declared_editability: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Validate a produced .pptx file's package structure.

    Args:
        pptx_path: Path to the .pptx file.
        expected_slides: Expected slide count (matches
            validate_visual_review.py's existing "expected_slides" field).
        declared_editability: Optional {slide_index_as_str: editability}
            map (as declared by the manifest/module) to cross-check
            against what's actually observed in the rendered output.

    Returns:
        {"status": "passed"|"failed", "checked_at": iso8601,
        "slide_count_expected": int, "slide_count_actual": int,
        "relationship_violations": [...], "editability_mismatches": [...]}.

    Raises:
        PptxStructureError: If the file is not a valid zip, or a required
            part is missing or malformed -- i.e. the package cannot be
            inspected at all.
    """
    try:
        zf = zipfile.ZipFile(pptx_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PptxStructureError(f"not a valid .pptx/zip file: {exc}") from exc
    with zf:
        _read_xml(zf, "[Content_Types].xml")
        presentation_xml = _read_xml(zf, "ppt/presentation.xml")
        slide_names = _slide_names(zf, presentation_xml)

        relationship_violations: List[Dict[str, Any]] = []
        editability_mismatches: List[Dict[str, Any]] = []
        for i, slide_name in enumerate(slide_names):
            relationship_violations.extend(_relationship_violations(zf, slide_name))
            observed = _observed_editability(zf, slide_name)
            declared = (declared_editability or {}).get(str(i))
            if declared and declared != observed:
                editability_mismatches.append({"slide": slide_name, "declared": declared, "observed": observed})

        status = (
            "passed"
            if len(slide_names) == expected_slides and not relationship_violations and not editability_mismatches
            else "failed"
        )
        return {
            "status": status,
            "checked_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "slide_count_expected": expected_slides,
            "slide_count_actual": len(slide_names),
            "relationship_violations": relationship_violations,
            "editability_mismatches": editability_mismatches,
        }


def main() -> None:
    """CLI entry point for validate_pptx_structure.py."""
    parser = argparse.ArgumentParser(description="Validate a .pptx file's package structure.")
    parser.add_argument("--pptx", metavar="PATH", type=Path, required=True)
    parser.add_argument("--expected-slides", type=int, required=True)
    parser.add_argument("--declared-editability", metavar="PATH", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        declared = (
            json.loads(args.declared_editability.read_text(encoding="utf-8"))
            if args.declared_editability else None
        )
        result = validate_pptx_structure(args.pptx, args.expected_slides, declared)
    except (PptxStructureError, OSError, json.JSONDecodeError) as exc:
        result = {"status": "failed", "error": str(exc)}
        print(json.dumps(result) if args.json else json.dumps(result, indent=2))
        sys.exit(1)

    print(json.dumps(result) if args.json else json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
