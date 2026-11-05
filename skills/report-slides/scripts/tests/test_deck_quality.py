"""Tests for the research deck quality checker (``deck_quality``)."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.util import Inches, Pt

import deck_quality as dq
from deck_quality.__main__ import main as cli_main
from deck_quality.gate import add_gate_arguments, finish_build
from deck_quality.ooxml import NS
from deck_quality.text import em_width, split_by_script

ZH = dq.load_preset("zh-kai-times")


# ── helpers ───────────────────────────────────────────────────────────────

def new_deck():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    return prs


def add_slide(prs, notes: str | None = "講稿。"):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    if notes is not None:
        slide.notes_slide.notes_text_frame.text = notes
    return slide


def add_text(slide, text, x=1.0, y=1.0, w=6.0, h=1.0, size=18):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    box.text_frame.word_wrap = True
    box.text_frame.text = text
    for p in box.text_frame.paragraphs:
        for r in p.runs:
            r.font.size = Pt(size)
    return box


def add_clicks(slide, n: int) -> None:
    """Attach a main sequence with ``n`` on-click effects to ``slide``."""
    p = NS["p"]
    clicks = "".join(
        f'<p:par><p:cTn id="{10 + i}" fill="hold"><p:childTnLst><p:par>'
        f'<p:cTn id="{50 + i}" presetID="1" presetClass="entr" fill="hold" '
        f'nodeType="clickEffect"/></p:par></p:childTnLst></p:cTn></p:par>'
        for i in range(n))
    xml = (f'<p:timing xmlns:p="{p}"><p:tnLst><p:par><p:cTn id="1" nodeType="tmRoot">'
           f'<p:childTnLst><p:seq><p:cTn id="2" nodeType="mainSeq"><p:childTnLst>{clicks}'
           f'</p:childTnLst></p:cTn></p:seq></p:childTnLst></p:cTn></p:par></p:tnLst>'
           f'</p:timing>')
    slide._element.append(etree.fromstring(xml))


def save(prs, tmp_path: Path, name="deck.pptx") -> Path:
    path = tmp_path / name
    prs.save(str(path))
    return path


def rules_of(report) -> list[str]:
    return sorted(f.rule for f in report.findings)


def check(prs, tmp_path, cfg=None, **kw):
    return dq.check_deck(save(prs, tmp_path), cfg or dq.Config(), **kw)


# ── text helpers ──────────────────────────────────────────────────────────

def test_split_by_script_keeps_whitespace_with_the_run_before() -> None:
    assert split_by_script("誤差 Δx 小於 0.01 m") == [
        ("cjk", "誤差 "), ("latin", "Δx "), ("cjk", "小於 "), ("latin", "0.01 m")]
    assert split_by_script("  ") == [("latin", "  ")]


def test_full_width_punctuation_counts_as_cjk() -> None:
    assert split_by_script("結果：好") == [("cjk", "結果：好")]
    assert em_width("中文") == 2.0


# ── A. fonts ──────────────────────────────────────────────────────────────

def test_fonts_are_skipped_without_a_pairing(tmp_path: Path) -> None:
    prs = new_deck()
    add_text(add_slide(prs), "誤差 Δx")
    assert rules_of(check(prs, tmp_path)) == []


def test_font_rules_flag_mixed_runs_and_theme(tmp_path: Path) -> None:
    prs = new_deck()
    add_text(add_slide(prs), "誤差 Δx 小於 0.01 m")
    report = check(prs, tmp_path, ZH)
    assert "A2" in rules_of(report)
    assert rules_of(report).count("A3") == 4


def test_ea_only_cjk_run_is_an_a2_finding(tmp_path: Path) -> None:
    prs = new_deck()
    box = add_text(add_slide(prs), "中文")
    run = box.text_frame.paragraphs[0].runs[0]
    run.font.name = "Times New Roman"
    rpr = run._r.get_or_add_rPr()
    rpr.append(etree.fromstring(f'<a:ea xmlns:a="{NS["a"]}" typeface="DFKai-SB"/>'))
    dq.fix.set_theme_fonts(prs, ZH)
    report = check(prs, tmp_path, ZH)
    assert [f.rule for f in report.findings] == ["A2"]
    assert "only the ea face" in report.findings[0].message


def test_latin_run_in_wrong_face_is_a1(tmp_path: Path) -> None:
    prs = new_deck()
    box = add_text(add_slide(prs), "Accuracy")
    box.text_frame.paragraphs[0].runs[0].font.name = "Arial"
    dq.fix.set_theme_fonts(prs, ZH)
    assert rules_of(check(prs, tmp_path, ZH)) == ["A1"]


def test_apply_font_pairing_satisfies_a1_to_a3(tmp_path: Path) -> None:
    prs = new_deck()
    slide = add_slide(prs)
    box = add_text(slide, "誤差 Δx 小於 0.01 m")
    group = slide.shapes.add_group_shape()
    group.shapes.add_textbox(Inches(1), Inches(4), Inches(4), Inches(1)).text_frame.text = "群組 text"
    dq.apply_font_pairing(prs, ZH)
    runs = box.text_frame.paragraphs[0].runs
    assert [r.text for r in runs] == ["誤差 ", "Δx ", "小於 ", "0.01 m"]
    assert runs[0].font.name == "DFKai-SB" and runs[1].font.name == "Times New Roman"
    assert rules_of(check(prs, tmp_path, ZH)) == []


# ── B. wording ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, rule", [
    ("門檻 some_threshold_m 設為 0.5", "B1"),
    ("用 `dx` 表示位移", "B1"),
    ("sigma 越大越平滑", "B1"),
    ("呼叫 compute_loss() 之後", "B1"),
    ("v3.2 比較好", "B2"),
    ("E5 的結果", "B2"),
    ("run 1234567", "B2"),
    ("commit 3fa9c1d2", "B2"),
    ("Source: lab notebook", "B4"),
    ("見 results/eval.csv", "B4"),
    ("C:\\data\\x", "B4"),
])
def test_wording_rules_flag(tmp_path: Path, text: str, rule: str) -> None:
    prs = new_deck()
    add_text(add_slide(prs), text)
    assert rule in rules_of(check(prs, tmp_path))


@pytest.mark.parametrize("text", [
    "Δx 小於 0.01 m，所以沒換",
    "σ = 2 時邊緣最清楚",
    "YOLOv8 與 ResNet50 在 ImageNet-1k 上",
    "F1 與 L2 損失",
    "TP/FP/FN 的比例",
    "共 12,345,678 張影像",
    "Python 3.11 實作",
])
def test_wording_rules_leave_plain_text_alone(tmp_path: Path, text: str) -> None:
    prs = new_deck()
    add_text(add_slide(prs), text, w=10)
    assert rules_of(check(prs, tmp_path)) == []


def test_preset_adds_source_labels(tmp_path: Path) -> None:
    prs = new_deck()
    add_text(add_slide(prs), "來源：自行整理")
    assert rules_of(check(prs, tmp_path)) == []
    dq.apply_font_pairing(prs, ZH)
    assert rules_of(check(prs, tmp_path, ZH)) == ["B4"]


def test_notes_are_not_scanned_for_wording(tmp_path: Path) -> None:
    prs = new_deck()
    add_slide(prs, notes="來源：results/eval.csv，v3.2")
    assert rules_of(check(prs, tmp_path, ZH)) == ["A3"] * 4


# ── E. layout ─────────────────────────────────────────────────────────────

def test_diagonal_connector_fails_and_straight_ones_pass(tmp_path: Path) -> None:
    prs = new_deck()
    slide = add_slide(prs)
    slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(1), Inches(1), Inches(4), Inches(1))
    slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(5), Inches(1), Inches(5), Inches(4))
    slide.shapes.add_connector(MSO_CONNECTOR.ELBOW, Inches(6), Inches(1), Inches(9), Inches(3))
    assert rules_of(check(prs, tmp_path)) == []
    slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(1), Inches(5), Inches(4), Inches(6))
    slide.shapes.add_connector(MSO_CONNECTOR.CURVE, Inches(6), Inches(5), Inches(9), Inches(6))
    assert rules_of(check(prs, tmp_path)) == ["E1", "E1"]


def _freeform(slide, points, closed, arrow):
    builder = slide.shapes.build_freeform(Inches(points[0][0]), Inches(points[0][1]))
    builder.add_line_segments([(Inches(x), Inches(y)) for x, y in points[1:]], close=closed)
    shape = builder.convert_to_shape()
    if arrow:
        ln = shape.line._get_or_add_ln()
        ln.append(ln.makeelement(f'{{{NS["a"]}}}tailEnd', {"type": "triangle"}))
    return shape


def test_arrowed_open_paths_must_be_orthogonal(tmp_path: Path) -> None:
    prs = new_deck()
    slide = add_slide(prs)
    _freeform(slide, [(1, 1), (3, 1), (3, 3)], closed=False, arrow=True)       # elbow
    _freeform(slide, [(5, 1), (7, 1), (6.5, 3), (5.5, 3)], closed=True, arrow=False)  # trapezoid
    _freeform(slide, [(8, 1), (9, 2), (10, 4)], closed=False, arrow=False)     # data line
    assert rules_of(check(prs, tmp_path)) == []
    _freeform(slide, [(1, 5), (3, 6)], closed=False, arrow=True)
    assert rules_of(check(prs, tmp_path)) == ["E1"]


def test_connectors_inside_scaled_groups_are_checked(tmp_path: Path) -> None:
    prs = new_deck()
    group = add_slide(prs).shapes.add_group_shape()
    group.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(1), Inches(1), Inches(3), Inches(2))
    assert rules_of(check(prs, tmp_path)) == ["E1"]


def test_overlapping_and_off_page_text(tmp_path: Path) -> None:
    prs = new_deck()
    slide = add_slide(prs)
    add_text(slide, "第一段文字", x=1, y=1, w=4, h=0.6, size=24)
    add_text(slide, "Second label", x=6, y=1, w=4, h=0.6, size=24)
    assert rules_of(check(prs, tmp_path)) == []
    add_text(slide, "壓在上面的字", x=1.5, y=1.05, w=4, h=0.6, size=24)
    add_text(slide, "這一行會超出頁面的右邊界很多很多很多", x=11, y=6, w=4, h=0.6, size=24)
    report = check(prs, tmp_path)
    messages = " ".join(f.message for f in report.findings)
    assert "overlaps" in messages and "runs off the page" in messages


def test_wrapped_text_that_grows_into_the_next_box_overlaps(tmp_path: Path) -> None:
    prs = new_deck()
    slide = add_slide(prs)
    add_text(slide, "很長的說明文字" * 6, x=1, y=1, w=3, h=0.5, size=20)
    add_text(slide, "下一個方塊", x=1, y=1.8, w=3, h=0.5, size=20)
    assert "E2" in rules_of(check(prs, tmp_path))


# ── F. notes ──────────────────────────────────────────────────────────────

def test_every_slide_needs_notes(tmp_path: Path) -> None:
    prs = new_deck()
    add_slide(prs)
    add_slide(prs, notes=None)
    add_slide(prs, notes="   ")
    report = check(prs, tmp_path)
    assert [(f.rule, f.slide) for f in report.findings] == [("F2", 2), ("F2", 3)]


def test_click_markers_must_match_click_animations(tmp_path: Path) -> None:
    prs = new_deck()
    ok = add_slide(prs, notes="開場。【按】資料進來。【按】經過編碼器。")
    add_clicks(ok, 2)
    bad = add_slide(prs, notes="只有一次【按】")
    add_clicks(bad, 3)
    add_slide(prs, notes="沒有動畫，也沒有按。")
    dq.apply_font_pairing(prs, ZH)
    report = check(prs, tmp_path, ZH)
    assert [(f.rule, f.slide) for f in report.findings] == [("F3", 2)]
    assert "1 × 【按】" in report.findings[0].message
    # The core marker is [click]; the zh preset's 【按】 means nothing there.
    assert [(f.rule, f.slide) for f in check(prs, tmp_path).findings] == [("F3", 1), ("F3", 2)]


# ── exceptions ────────────────────────────────────────────────────────────

def _exceptions(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "deck.exceptions.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_listed_exceptions_waive_findings_with_their_reason(tmp_path: Path) -> None:
    prs = new_deck()
    add_text(add_slide(prs), "A100 GPU 上訓練")
    path = _exceptions(tmp_path, "exceptions:\n  - rule: B2\n    slide: 1\n    match: A100\n"
                                 "    reason: public GPU model name\n")
    report = check(prs, tmp_path, exceptions=dq.load_exceptions(path))
    assert report.passed
    assert report.waived[0][1].reason == "public GPU model name"
    assert "waived" in report.text()


def test_unused_exception_is_reported(tmp_path: Path) -> None:
    prs = new_deck()
    add_text(add_slide(prs), "沒有問題")
    path = _exceptions(tmp_path, "- rule: B1\n  match: nothing_here\n  reason: stale\n")
    report = check(prs, tmp_path, exceptions=dq.load_exceptions(path))
    assert rules_of(report) == ["EX"]


@pytest.mark.parametrize("body, message", [
    ("- rule: B2\n", "no reason"),
    ("- rule: Z9\n  reason: x\n", "unknown rule"),
    ("- rule: EX\n  reason: x\n", "unknown rule"),
    ("exceptions: 3\n", "expected a list"),
])
def test_bad_exceptions_are_rejected(tmp_path: Path, body: str, message: str) -> None:
    with pytest.raises(dq.ConfigError, match=message):
        dq.load_exceptions(_exceptions(tmp_path, body))


def test_unknown_preset_lists_the_available_ones() -> None:
    with pytest.raises(dq.ConfigError, match="zh-kai-times"):
        dq.load_preset("no-such-preset")


# ── G. output file and generator helpers ──────────────────────────────────

def test_timestamped_output_and_prune(tmp_path: Path) -> None:
    old = dq.timestamped_output(tmp_path, "deck", datetime(2026, 1, 1, 9, 0, 0))
    new = dq.timestamped_output(tmp_path, "deck", datetime(2026, 1, 2, 9, 0, 0))
    other = tmp_path / "other-20260101T090000.pptx"
    assert new.name == "deck-20260102T090000.pptx"
    for p in (old, new, other):
        p.write_bytes(b"x")
    assert [f.rule for f in dq.rules.check_output_name(new)] == ["G1"]
    assert dq.prune_older(new) == [old]
    assert dq.rules.check_output_name(new) == []
    assert other.exists()
    assert [f.rule for f in dq.rules.check_output_name(tmp_path / "deck.pptx")] == ["G1"]


def test_orthogonal_segments_raise_on_a_diagonal() -> None:
    assert len(dq.orthogonal_segments([(0, 0), (2, 0), (2, 3)])) == 2
    with pytest.raises(dq.DiagonalLineError, match=r"elbow at \(2, 0\)"):
        dq.orthogonal_segments([(0, 0), (2, 3)])


def test_enforce_raises_and_finish_build_rejects_the_file(tmp_path: Path, capsys) -> None:
    prs = new_deck()
    add_slide(prs, notes=None)
    path = save(prs, tmp_path)
    with pytest.raises(dq.DeckQualityError, match="F2"):
        dq.enforce(path)
    ap = argparse.ArgumentParser()
    add_gate_arguments(ap)
    assert finish_build(path, ap.parse_args([])) == 1
    assert not path.exists() and (tmp_path / "deck.rejected.pptx").exists()
    assert "FAIL: 1 finding(s)" in capsys.readouterr().out


def test_finish_build_passes_with_exceptions_and_prunes(tmp_path: Path) -> None:
    older = tmp_path / "deck-20260101T000000.pptx"
    older.write_bytes(b"x")
    prs = new_deck()
    add_slide(prs, notes=None)
    path = save(prs, tmp_path, "deck-20260102T000000.pptx")
    exc = _exceptions(tmp_path, "- rule: F2\n  reason: title card has no script\n")
    ap = argparse.ArgumentParser()
    add_gate_arguments(ap)
    args = ap.parse_args(["--quality-exceptions", str(exc), "--timestamp"])
    assert finish_build(path, args) == 0
    assert path.exists() and not older.exists()


def test_gate_arguments_reject_a_bad_preset_before_building() -> None:
    ap = argparse.ArgumentParser()
    add_gate_arguments(ap)
    with pytest.raises(SystemExit):
        ap.parse_args(["--quality-preset", "nope"])


def test_cli_exit_codes(tmp_path: Path) -> None:
    prs = new_deck()
    add_text(add_slide(prs), "誤差 Δx 小於 0.01 m")
    path = save(prs, tmp_path)
    assert cli_main([str(path)]) == 0
    assert cli_main([str(path), "--preset", "zh-kai-times"]) == 1
    assert cli_main([str(path), "--preset", "zh-kai-times", "--fix-fonts"]) == 0
    assert cli_main([str(path), "--preset", "nope"]) == 2
