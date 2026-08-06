"""Tests for complex_visual_detector.py."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "complex_visual_detector.py"

_ALL_FALSE_SIGNALS = {
    "region_count": 2, "route_count": 1, "multi_stage": False, "mixed_technique": False,
    "heavy_cross_region_connections": False, "expected_reuse": False, "not_atomic": False,
}


def _write_thresholds(tmp_path: Path, region: int = 3, route: int = 1) -> Path:
    path = tmp_path / "thresholds.yaml"
    path.write_text(f"region_count_threshold: {region}\nroute_count_threshold: {route}\n")
    return path


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


def test_all_signals_false_and_under_threshold_does_not_trigger(tmp_path: Path) -> None:
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(json.dumps(_ALL_FALSE_SIGNALS))
    thresholds_path = _write_thresholds(tmp_path)

    result = _run("--signals", str(signals_path), "--thresholds", str(thresholds_path), "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {"requires_complex_workflow": False, "triggered_signals": []}


def test_region_count_over_threshold_triggers(tmp_path: Path) -> None:
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(json.dumps({**_ALL_FALSE_SIGNALS, "region_count": 4}))
    thresholds_path = _write_thresholds(tmp_path, region=3)

    result = _run("--signals", str(signals_path), "--thresholds", str(thresholds_path), "--json")

    data = json.loads(result.stdout)
    assert data["requires_complex_workflow"] is True
    assert "region_count" in data["triggered_signals"]


def test_route_count_over_threshold_triggers(tmp_path: Path) -> None:
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(json.dumps({**_ALL_FALSE_SIGNALS, "route_count": 2}))
    thresholds_path = _write_thresholds(tmp_path, route=1)

    result = _run("--signals", str(signals_path), "--thresholds", str(thresholds_path), "--json")

    data = json.loads(result.stdout)
    assert data["requires_complex_workflow"] is True
    assert "route_count" in data["triggered_signals"]


def test_each_qualitative_signal_triggers_independently(tmp_path: Path) -> None:
    thresholds_path = _write_thresholds(tmp_path)
    for key in ("multi_stage", "mixed_technique", "heavy_cross_region_connections", "expected_reuse", "not_atomic"):
        signals_path = tmp_path / f"signals_{key}.json"
        signals_path.write_text(json.dumps({**_ALL_FALSE_SIGNALS, key: True}))

        result = _run("--signals", str(signals_path), "--thresholds", str(thresholds_path), "--json")

        data = json.loads(result.stdout)
        assert data["requires_complex_workflow"] is True, key
        assert key in data["triggered_signals"]


def test_missing_signal_key_raises(tmp_path: Path) -> None:
    incomplete = {k: v for k, v in _ALL_FALSE_SIGNALS.items() if k != "region_count"}
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(json.dumps(incomplete))
    thresholds_path = _write_thresholds(tmp_path)

    result = _run("--signals", str(signals_path), "--thresholds", str(thresholds_path), "--json")

    assert result.returncode != 0


def test_default_thresholds_file_is_used_when_not_specified(tmp_path: Path) -> None:
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(json.dumps(_ALL_FALSE_SIGNALS))

    result = _run("--signals", str(signals_path), "--json")

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {"requires_complex_workflow": False, "triggered_signals": []}
