"""Tests for profile.py -- Research Profile CLI."""
import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "profile.py"
_spec = importlib.util.spec_from_file_location("research_profile", SCRIPT)
profile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(profile)


def _write_profile(root: Path, name: str, manifest: str, files: dict = None) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "profile.yaml").write_text(textwrap.dedent(manifest), encoding="utf-8")
    for rel, content in (files or {}).items():
        target = directory / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return directory


@pytest.fixture
def profiles_root(tmp_path: Path) -> Path:
    root = tmp_path / "profiles"
    root.mkdir()
    _write_profile(root, "plain-voice", """\
        name: plain-voice
        description: Short declarative sentences.
        axes:
          voice:
            rules: voice.md
        """, {"voice.md": "# Voice\n"})
    _write_profile(root, "english-ieee", """\
        name: english-ieee
        description: English body, IEEE citations.
        axes:
          language:
            body: en
            abstract: [en]
          venue:
            citation_style: ieee
        """)
    _write_profile(root, "combined", """\
        name: combined
        description: Voice plus venue, with one override.
        extends: [plain-voice, english-ieee]
        axes:
          language:
            abstract: [en, zh-TW]
          slides:
            report-slides: paper
        """)
    return root


def test_available_profiles_lists_only_dirs_with_manifest(profiles_root):
    (profiles_root / "not-a-profile").mkdir()
    assert profile.available_profiles(profiles_root) == [
        "combined", "english-ieee", "plain-voice"]


def test_resolve_merges_extends_in_order_and_child_wins(profiles_root):
    resolved = profile.resolve("combined", profiles_root)
    assert resolved["chain"] == ["plain-voice", "english-ieee", "combined"]
    assert resolved["axes"]["language"] == {"body": "en", "abstract": ["en", "zh-TW"]}
    assert resolved["axes"]["venue"] == {"citation_style": "ieee"}
    assert resolved["axes"]["slides"] == {"report-slides": "paper"}
    assert resolved["axes"]["voice"]["rules"] == str(profiles_root / "plain-voice" / "voice.md")


def test_resolve_rejects_cycle(tmp_path):
    root = tmp_path / "profiles"
    _write_profile(root, "a-one", "name: a-one\ndescription: x\nextends: [b-two]\n")
    _write_profile(root, "b-two", "name: b-two\ndescription: x\nextends: [a-one]\n")
    with pytest.raises(profile.ProfileError, match="cycle"):
        profile.resolve("a-one", root)


def test_resolve_unknown_profile_names_available(profiles_root):
    with pytest.raises(profile.ProfileError, match="available: combined"):
        profile.resolve("missing", profiles_root)


@pytest.mark.parametrize("manifest, files, expected", [
    ("name: other\ndescription: x\naxes: {venue: {citation_style: ieee}}\n", {},
     "must equal the directory name"),
    ("name: bad-one\ndescription: x\naxes: {tone: {a: b}}\n", {}, "unknown axis 'tone'"),
    ("name: bad-one\ndescription: x\naxes: {voice: {rules: nope.md}}\n", {},
     "missing file 'nope.md'"),
    ("name: bad-one\ndescription: x\naxes: {venue: {citation_style: harvard}}\n", {},
     "citation_style must be one of"),
    ("name: bad-one\ndescription: x\naxes: {language: {body: English}}\n", {},
     "language.body must be a language tag"),
    ("name: bad-one\ndescription: x\naxes: {language: {abstract: []}}\n", {},
     "language.abstract must be a non-empty list"),
    ("name: bad-one\ndescription: x\naxes: {slides: {report-slides: My Style}}\n", {},
     "kebab-case style or preset name"),
    ("name: bad-one\ndescription: ''\naxes: {venue: {citation_style: ieee}}\n", {},
     "description is required"),
    ("name: bad-one\ndescription: x\n", {}, "sets no axes and extends nothing"),
])
def test_validate_manifest_reports_problems(tmp_path, manifest, files, expected):
    root = tmp_path / "profiles"
    _write_profile(root, "bad-one", manifest, files)
    problems = profile.validate_manifest("bad-one", profile.load_manifest("bad-one", root), root)
    assert any(expected in p for p in problems), problems


def test_validate_manifest_rejects_non_kebab_directory(tmp_path):
    root = tmp_path / "profiles"
    _write_profile(root, "Bad_Name", "name: Bad_Name\ndescription: x\naxes: {venue: {citation_style: ieee}}\n")
    problems = profile.validate_manifest("Bad_Name", profile.load_manifest("Bad_Name", root), root)
    assert any("kebab-case" in p for p in problems)


def test_active_with_nothing_set_returns_core_defaults(tmp_path, profiles_root):
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    state = profile.active(project, root=profiles_root)
    assert state["status"] == "none"
    assert state["axes"] == profile.CORE_DEFAULTS


def test_active_project_file_then_session_override(tmp_path, profiles_root):
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    profile.write_project_profile(project, "english-ieee")

    state = profile.active(project, root=profiles_root)
    assert (state["profile"], state["source"]) == ("english-ieee", "project")
    assert state["axes"]["language"]["body"] == "en"
    # interface was not set by the profile, so the core default survives
    assert state["axes"]["language"]["interface"] == profile.FOLLOW_USER
    assert state["axes"]["voice"] is None

    state = profile.active(project, session="plain-voice", root=profiles_root)
    assert (state["profile"], state["source"]) == ("plain-voice", "session")
    assert state["axes"]["voice"]["rules"].endswith("voice.md")


def test_clearing_project_profile(tmp_path, profiles_root):
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    profile.write_project_profile(project, "english-ieee")
    profile.write_project_profile(project, None)
    assert profile.read_project_profile(project) is None


def test_read_project_profile_rejects_list(tmp_path):
    project = tmp_path / "project"
    (project / ".research").mkdir(parents=True)
    (project / ".research" / "profile.yaml").write_text("profile: [a, b]\n", encoding="utf-8")
    with pytest.raises(profile.ProfileError, match="single profile name"):
        profile.read_project_profile(project)


def test_cli_active_outside_project_reports_core_defaults(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), "--active", "--json"],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "none"


def test_cli_set_refuses_unknown_profile(tmp_path):
    (tmp_path / ".git").mkdir()
    result = subprocess.run([sys.executable, str(SCRIPT), "--set", "does-not-exist", "--json"],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2
    assert "unknown profile" in json.loads(result.stdout)["error"]
    assert not (tmp_path / ".research" / "profile.yaml").exists()


def test_bundled_profiles_are_valid():
    result = subprocess.run([sys.executable, str(SCRIPT), "--validate", "--json"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
