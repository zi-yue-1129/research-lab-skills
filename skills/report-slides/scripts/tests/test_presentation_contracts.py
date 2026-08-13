"""Tests for canonical presentation-contract loading and validation helpers."""

import hashlib
from pathlib import Path
from typing import Any

import pytest

from presentation_contracts import (
    canonical_json_bytes,
    contract_sha256,
    load_contract,
    validate_acyclic_dependencies,
    validate_schema_version,
)


def test_contract_digest_is_format_independent(tmp_path: Path) -> None:
    """Calculate a stable digest from a document regardless of source format."""
    yaml_doc = {"schema_version": 1, "deck_id": "deck-1", "items": [2, 1]}

    assert contract_sha256(yaml_doc) == hashlib.sha256(
        b'{"deck_id":"deck-1","items":[2,1],"schema_version":1}'
    ).hexdigest()


def test_canonical_json_bytes_preserves_unicode_and_sorting() -> None:
    """Serialize Unicode values without escaping while sorting object keys."""
    document: dict[str, Any] = {"zeta": "\u6e2c\u8a66", "alpha": {"b": 2, "a": 1}}

    assert canonical_json_bytes(document) == '{"alpha":{"a":1,"b":2},"zeta":"\u6e2c\u8a66"}'.encode("utf-8")


def test_load_contract_loads_equivalent_yaml_and_json(tmp_path: Path) -> None:
    """Load YAML and JSON contract files into equal document values."""
    yaml_path = tmp_path / "plan.yaml"
    json_path = tmp_path / "plan.json"
    yaml_path.write_text("schema_version: 1\ndeck_id: deck-1\n", encoding="utf-8")
    json_path.write_text('{"schema_version": 1, "deck_id": "deck-1"}', encoding="utf-8")

    assert load_contract(yaml_path) == load_contract(json_path)


def test_load_contract_rejects_unknown_file_extension(tmp_path: Path) -> None:
    """Fail closed when a contract path does not identify a supported format."""
    path = tmp_path / "plan.txt"
    path.write_text("schema_version: 1", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported contract file extension"):
        load_contract(path)


def test_validate_schema_version_requires_version_one() -> None:
    """Reject missing, boolean, and incompatible schema version values."""
    assert validate_schema_version({"schema_version": 1}) == []
    assert validate_schema_version({}) == ["schema_version: required integer value 1"]
    assert validate_schema_version({"schema_version": True}) == [
        "schema_version: required integer value 1"
    ]
    assert validate_schema_version({"schema_version": 2}) == [
        "schema_version: required integer value 1"
    ]


def test_validate_acyclic_dependencies_reports_dependency_cycle() -> None:
    """Report a dependency cycle with the configured field name."""
    errors = validate_acyclic_dependencies(
        {"slide-01", "slide-02"},
        {"slide-01": ["slide-02"], "slide-02": ["slide-01"]},
        "dependencies",
    )

    assert errors == ["dependencies: dependency cycle detected: slide-01 -> slide-02 -> slide-01"]


def test_validate_acyclic_dependencies_reports_unknown_node() -> None:
    """Reject edges that name dependencies outside the declared node set."""
    errors = validate_acyclic_dependencies(
        {"slide-01"}, {"slide-01": ["slide-unknown"]}, "dependencies"
    )

    assert errors == ["dependencies: undeclared dependency 'slide-unknown' for 'slide-01'"]
