import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "validate_native_objects.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, check=False,
    )


def _write_svg(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">{body}</svg>',
        encoding="utf-8",
    )
    return path


def test_unmarked_table_grid_is_flagged(tmp_path: Path):
    grid = "".join(
        f'<rect x="{60 + c * 200}" y="{75 + r * 50}" width="190" height="45" fill="#eee"/>'
        for r in range(3) for c in range(3)
    )
    _write_svg(tmp_path, "slide01_table.svg", grid)
    result = _run("--svg-dir", str(tmp_path))
    assert result.returncode == 1
    assert "table_like" in result.stderr


def test_marked_table_is_not_flagged(tmp_path: Path):
    grid = "".join(
        f'<rect x="{60 + c * 200}" y="{75 + r * 50}" width="190" height="45" fill="#eee"/>'
        for r in range(3) for c in range(3)
    )
    _write_svg(
        tmp_path, "slide01_table.svg",
        f'<g data-pptx-role="table" data-pptx-source="d.json" '
        f'data-pptx-bbox="60,75,600,150">{grid}</g>',
    )
    result = _run("--svg-dir", str(tmp_path))
    assert result.returncode == 0


def test_unmarked_bar_cluster_is_flagged(tmp_path: Path):
    bars = "".join(
        f'<rect x="{130 + i * 100}" y="{500 - i * 40}" width="60" height="{20 + i * 40}" fill="#369"/>'
        for i in range(4)
    )
    _write_svg(tmp_path, "slide02_bar.svg", bars)
    result = _run("--svg-dir", str(tmp_path))
    assert result.returncode == 1
    assert "chart_like" in result.stderr


def test_unmarked_node_cluster_is_flagged(tmp_path: Path):
    cluster = (
        '<g><rect x="100" y="100" width="200" height="80" fill="#eee"/>'
        '<circle cx="120" y="120" r="10" fill="#333"/>'
        '<text x="200" y="140">Encoder</text></g>'
    )
    _write_svg(tmp_path, "slide03_arch.svg", cluster)
    result = _run("--svg-dir", str(tmp_path))
    assert result.returncode == 1
    assert "node_cluster_like" in result.stderr


def test_clean_svg_passes(tmp_path: Path):
    _write_svg(tmp_path, "slide04_title.svg",
              '<text x="600" y="300">Just a title</text>')
    result = _run("--svg-dir", str(tmp_path))
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_pptx_mode_requires_svg_dir_or_pptx_exclusively():
    result = _run()
    assert result.returncode != 0


def test_text_missing_x_and_y_is_flagged(tmp_path: Path):
    _write_svg(tmp_path, "slide05_label.svg", "<text>Floating label</text>")
    result = _run("--svg-dir", str(tmp_path))
    assert result.returncode == 1
    assert "text_missing_coords" in result.stderr


def test_text_with_coords_only_on_tspan_is_flagged(tmp_path: Path):
    _write_svg(
        tmp_path, "slide06_label.svg",
        '<text><tspan x="200" y="140">Multi-Head</tspan>'
        '<tspan x="200" dy="15">Attention</tspan></text>',
    )
    result = _run("--svg-dir", str(tmp_path))
    assert result.returncode == 1
    assert "text_missing_coords" in result.stderr


def test_text_missing_only_y_is_flagged(tmp_path: Path):
    _write_svg(tmp_path, "slide07_label.svg", '<text x="200">Label</text>')
    result = _run("--svg-dir", str(tmp_path))
    assert result.returncode == 1
    assert "text_missing_coords" in result.stderr


def test_text_with_x_and_y_on_the_element_passes(tmp_path: Path):
    _write_svg(tmp_path, "slide08_label.svg",
              '<text x="200" y="140">Compliant label</text>')
    result = _run("--svg-dir", str(tmp_path))
    assert result.returncode == 0
