"""Unit tests for check_spec_consistency.py.

Pre-#171, check_spec_consistency.py uses module-level ROOT + ERRORS state.
These tests monkey-patch ROOT into a TemporaryDirectory containing a minimal
fixture README, drive a specific checker directly, and read ERRORS. When
#171 lands the schema-driven manifest, these tests rewrite to call the
manifest runner instead.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.checks import check_spec_consistency as csc


# Minimal ja-JP README capturing the version-bearing surfaces the lint needs
# to police: badge, release tag link, three release blocks (current + two
# prior so the symmetric structure with check_readme_zh_sections is visible),
# four localized mode headings, four skill-detail headings, and the DOCX line.
JA_README_TEMPLATE = """\
# research-lab-skills

[![Version](https://img.shields.io/badge/version-v{ver}-blue)](https://github.com/starpig1129/research-lab-skills/releases/tag/v{ver})

## 学術研究スキル（ARS）

整合性ゲート (Stage 2.5 / Stage 4.5)

### クイックスタート

- calibration モード
"""


def _write_ja_readme(root: Path, version: str) -> None:
    (root / "README.ja-JP.md").write_text(
        JA_README_TEMPLATE.format(ver=version), encoding="utf-8"
    )


# Minimal zh-CN README capturing the version-bearing surfaces the lint needs
# to police via ZH_README_CONFIGS[1]: badge, release tag link, the same
# release-block list as zh-TW, four Simplified-Chinese localized mode
# headings, four skill-detail headings, and the Simplified-Chinese DOCX line.
ZH_CN_README_TEMPLATE = """\
# research-lab-skills

[![Version](https://img.shields.io/badge/version-v{ver}-blue)](https://github.com/starpig1129/research-lab-skills/releases/tag/v{ver})

## 学术研究技能（ARS）

integrity check (Stage 2.5)
"""


def _write_zh_cn_readme(root: Path, version: str) -> None:
    (root / "README.zh-CN.md").write_text(
        ZH_CN_README_TEMPLATE.format(ver=version), encoding="utf-8"
    )


# zh-TW fixture matching ZH_README_CONFIGS[0]. check_readme_zh_sections
# iterates BOTH configs, so to test the zh-CN branch in isolation we still
# need a passing zh-TW companion (or vice versa). The minimal zh-TW fixture
# below uses the same shape with Traditional-Chinese localized strings.
ZH_TW_README_TEMPLATE = """\
# research-lab-skills

[![Version](https://img.shields.io/badge/version-v{ver}-blue)](https://github.com/starpig1129/research-lab-skills/releases/tag/v{ver})

## 學術研究技能（ARS）

integrity check (Stage 2.5)
"""


def _write_zh_tw_readme(root: Path, version: str) -> None:
    (root / "README.zh-TW.md").write_text(
        ZH_TW_README_TEMPLATE.format(ver=version), encoding="utf-8"
    )


class TestReadmeJaSections(unittest.TestCase):
    def setUp(self) -> None:
        # check_spec_consistency uses module-level ROOT and ERRORS. Reset and
        # restore around each test so state does not leak between cases.
        self._orig_root = csc.ROOT
        self._orig_errors = list(csc.ERRORS)
        csc.ERRORS.clear()

    def tearDown(self) -> None:
        csc.ROOT = self._orig_root
        csc.ERRORS.clear()
        csc.ERRORS.extend(self._orig_errors)

    def test_aligned_ja_readme_passes(self) -> None:
        """A README.ja-JP.md whose badge / tag link agree with suite version
        v1.1.0 and has the required ARS heading and integrity gate must pass."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            csc.ROOT = root
            _write_ja_readme(root, version="1.1.0")

            csc.check_readme_ja_sections()

            self.assertEqual(
                csc.ERRORS, [],
                msg=f"unexpected errors on aligned fixture: {csc.ERRORS!r}",
            )

    def test_stale_ja_badge_fails(self) -> None:
        """If README.ja-JP.md keeps a stale v0.9.0 badge while the suite
        version is v1.1.0, the lint must surface the drift."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            csc.ROOT = root
            stale = JA_README_TEMPLATE.format(ver="1.1.0").replace(
                "version-v1.1.0-blue", "version-v0.9.0-blue"
            ).replace(
                "releases/tag/v1.1.0", "releases/tag/v0.9.0"
            )
            (root / "README.ja-JP.md").write_text(stale, encoding="utf-8")

            csc.check_readme_ja_sections()

            self.assertTrue(
                any("README.ja-JP.md" in e and "1.1.0" in e for e in csc.ERRORS),
                msg=f"expected ja-JP drift error in: {csc.ERRORS!r}",
            )


class TestReadmeZhSections(unittest.TestCase):
    """Coverage for the ZH_README_CONFIGS tuple branch added when zh-CN
    joined zh-TW under check_readme_zh_sections. check_readme_zh_sections
    iterates both configs, so both fixtures must exist on every test path."""

    def setUp(self) -> None:
        self._orig_root = csc.ROOT
        self._orig_errors = list(csc.ERRORS)
        csc.ERRORS.clear()

    def tearDown(self) -> None:
        csc.ROOT = self._orig_root
        csc.ERRORS.clear()
        csc.ERRORS.extend(self._orig_errors)

    def test_aligned_zh_cn_readme_passes(self) -> None:
        """Both zh-TW and zh-CN fixtures aligned to v1.1.0 with required ARS
        headings and Stage 2.5 references produce no lint errors."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            csc.ROOT = root
            _write_zh_tw_readme(root, version="1.1.0")
            _write_zh_cn_readme(root, version="1.1.0")

            csc.check_readme_zh_sections()

            self.assertEqual(
                csc.ERRORS, [],
                msg=f"unexpected errors on aligned zh fixtures: {csc.ERRORS!r}",
            )

    def test_stale_zh_cn_badge_fails(self) -> None:
        """If README.zh-CN.md keeps a stale v0.9.0 badge while the suite
        version is v1.1.0, the lint must surface the drift on the zh-CN
        branch specifically."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            csc.ROOT = root
            _write_zh_tw_readme(root, version="1.1.0")
            stale = ZH_CN_README_TEMPLATE.format(ver="1.1.0").replace(
                "version-v1.1.0-blue", "version-v0.9.0-blue"
            ).replace(
                "releases/tag/v1.1.0", "releases/tag/v0.9.0"
            )
            (root / "README.zh-CN.md").write_text(stale, encoding="utf-8")

            csc.check_readme_zh_sections()

            self.assertTrue(
                any("README.zh-CN.md" in e and "1.1.0" in e for e in csc.ERRORS),
                msg=f"expected zh-CN drift error in: {csc.ERRORS!r}",
            )


# Minimal docs/ARCHITECTURE.md fixture carrying the THREE marker kinds the invariant-4 check (#345)
# must distinguish: current-component markers (mermaid node + component/stage rows, which MUST equal
# the suite version), a feature-history timeline marker (`vX.Y.Z : <feature>`, which must NOT be
# policed), and a prose mention of `academic-pipeline vX.Y.Z` (provenance narrative, which must also
# NOT be policed — it is excluded by the table-row anchor). `{comp}` = current-component version;
# `{hist}` = timeline version; `{prose}` = the version named in the narrative provenance line.
ARCHITECTURE_TEMPLATE = """\
# Architecture

```mermaid
flowchart TD
    Pipeline[academic-pipeline<br/>orchestrator<br/>v{comp}<br/>Agent Team: 5]
```

| Stage | Gate | ... |
|-------|------|-----|
| **2.5 INTEGRITY** | `academic-pipeline` v{comp} (gate) | VERIFIED_ONLY |
| **6. PROCESS SUMMARY** | `academic-pipeline` v{comp} | VERIFIED_ONLY |

| Component | Role |
|-----------|------|
| `academic-pipeline` v{comp} | orchestrator (delegates to sub-skill modes) |

The `academic-pipeline` v{prose} release first introduced the integrity gate (narrative provenance).

```mermaid
timeline
    title ARS evolution timeline
    v{hist} : deterministic citation verification gate (#182)
```
"""


def _write_architecture_fixture(
    root: Path, *, suite: str, comp: str, hist: str, prose: str | None = None
) -> None:
    """Write `.claude/CLAUDE.md` (suite version source) + a docs/ARCHITECTURE.md fixture.

    `prose` defaults to the suite version so the narrative line is innocuous unless a test
    deliberately sets it to a stale version to assert the prose mention is not policed.
    """
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "CLAUDE.md").write_text(
        f"# ARS\n\n- **Suite version**: {suite} (per CHANGELOG.md)\n", encoding="utf-8"
    )
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "ARCHITECTURE.md").write_text(
        ARCHITECTURE_TEMPLATE.format(comp=comp, hist=hist, prose=prose or suite),
        encoding="utf-8",
    )


class TestArchitectureComponentVersion(unittest.TestCase):
    """#345: invariant-4 lint for docs/ARCHITECTURE.md current-component version markers."""

    def setUp(self) -> None:
        self._orig_root = csc.ROOT
        self._orig_errors = list(csc.ERRORS)
        csc.ERRORS.clear()

    def tearDown(self) -> None:
        csc.ROOT = self._orig_root
        csc.ERRORS.clear()
        csc.ERRORS.extend(self._orig_errors)

    def test_aligned_passes(self) -> None:
        """All component markers at the suite version → no errors (timeline at an older version
        is fine — it records history)."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            csc.ROOT = root
            _write_architecture_fixture(root, suite="3.11.1", comp="3.11.1", hist="3.11.0")

            csc.check_architecture_component_version()

            self.assertEqual(
                csc.ERRORS, [], msg=f"unexpected errors on aligned fixture: {csc.ERRORS!r}"
            )

    def test_stale_component_marker_fails(self) -> None:
        """A current-component marker left at the prior version (the exact #343/#344 drift) must
        fail — both the mermaid node and the rows carry the stale version here."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            csc.ROOT = root
            _write_architecture_fixture(root, suite="3.11.1", comp="3.11.0", hist="3.11.0")

            csc.check_architecture_component_version()

            self.assertTrue(
                any("ARCHITECTURE.md" in e and "3.11.0" in e and "3.11.1" in e for e in csc.ERRORS),
                msg=f"expected stale-component drift error in: {csc.ERRORS!r}",
            )

    def test_stale_timeline_marker_does_not_fail(self) -> None:
        """The critical distinction: a timeline `vX.Y.Z : <feature>` node at a DIFFERENT version
        from the suite must NOT fail — it records which version shipped a feature, and a
        naive `v3.x` scan would wrongly flag it. Component markers are aligned here."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            csc.ROOT = root
            # Component markers all at the suite version; only the timeline records an old version.
            _write_architecture_fixture(root, suite="3.11.1", comp="3.11.1", hist="3.9.4")

            csc.check_architecture_component_version()

            self.assertEqual(
                csc.ERRORS, [],
                msg=f"timeline marker must not be policed, but got: {csc.ERRORS!r}",
            )

    def test_missing_component_marker_fails(self) -> None:
        """If the component markers vanish entirely (e.g. a refactor removes them), the check must
        surface that rather than silently passing on an empty match."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            csc.ROOT = root
            (root / ".claude").mkdir(parents=True, exist_ok=True)
            (root / ".claude" / "CLAUDE.md").write_text(
                "- **Suite version**: 3.11.1 (per CHANGELOG.md)\n", encoding="utf-8"
            )
            (root / "docs").mkdir(parents=True, exist_ok=True)
            (root / "docs" / "ARCHITECTURE.md").write_text(
                "# Architecture\n\nNo component markers here.\n", encoding="utf-8"
            )

            csc.check_architecture_component_version()

            self.assertTrue(
                any("no mermaid" in e or "no `academic-pipeline" in e for e in csc.ERRORS),
                msg=f"expected missing-marker error in: {csc.ERRORS!r}",
            )

    def test_four_component_aligned_passes(self) -> None:
        """#352 P2: the repo's own grammar ships 4-component versions (v3.9.4.2). A suite and
        component markers both at a 4-component version must pass — the version regex must capture
        the FULL token, not truncate to three components."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            csc.ROOT = root
            _write_architecture_fixture(root, suite="3.9.4.2", comp="3.9.4.2", hist="3.9.4")

            csc.check_architecture_component_version()

            self.assertEqual(
                csc.ERRORS, [],
                msg=f"unexpected errors on aligned 4-component fixture: {csc.ERRORS!r}",
            )

    def test_four_component_marker_against_three_component_suite_fails(self) -> None:
        """#352 P2 (the silent-pass this fix closes): suite is the 3-component `3.9.4` but a
        component marker carries the 4-component `3.9.4.2`. A truncating `\\d+\\.\\d+\\.\\d+`
        would capture `3.9.4` from the marker and falsely pass (3.9.4 == 3.9.4). The full-token
        capture must instead see `3.9.4.2` and fail it against the suite."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            csc.ROOT = root
            _write_architecture_fixture(root, suite="3.9.4", comp="3.9.4.2", hist="3.9.4")

            csc.check_architecture_component_version()

            # The error must name the FULL 4-component marker as != the 3-component suite. Asserting
            # on `!= suite v3.9.4` (not just substring `3.9.4`, which is contained in `3.9.4.2`)
            # proves the captured marker was the full `3.9.4.2`, i.e. the truncation was closed.
            self.assertTrue(
                any("v3.9.4.2" in e and "!= suite v3.9.4 " in e for e in csc.ERRORS),
                msg=f"expected 4-vs-3-component drift error in: {csc.ERRORS!r}",
            )

    def test_prose_provenance_mention_does_not_fail(self) -> None:
        """#352 P3: a narrative line naming `academic-pipeline v<old>` (feature provenance) must
        NOT be policed against the suite version — only markdown table-row component cells are.
        Component markers + timeline are aligned/innocuous; only the prose line is stale."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            csc.ROOT = root
            _write_architecture_fixture(
                root, suite="3.11.1", comp="3.11.1", hist="3.9.4", prose="3.9.4"
            )

            csc.check_architecture_component_version()

            self.assertEqual(
                csc.ERRORS, [],
                msg=f"prose provenance mention must not be policed, but got: {csc.ERRORS!r}",
            )


if __name__ == "__main__":
    unittest.main()
