# Research deck quality standard

Applies to technical and research-progress decks: lab meetings, advisor
updates, method talks. Teaching decks follow `lecture-slides` and its preset
instead (a lecture deck footnotes its sources on the slide, which B4 forbids
here).

Every rule gives its reason and how it is checked:

- **auto**: `deck_quality` decides it. The deck generators run it at the end,
  and any finding fails the build (see [Running the checker](#running-the-checker)).
- **manual**: a person decides it from the exported page images and the
  slide show. The rules are collected as a checklist in
  [`review-checklist.md`](review-checklist.md).

Language- and house-specific values (the font pairing, the click marker, the
words that open a source line) come from a named preset under `presets/`.
With no preset the core rules run without a font pairing.

| Preset | Sets |
|---|---|
| `zh-kai-times` | 標楷體 (DFKai-SB) for Chinese, Times New Roman for Latin text, digits and symbols; `【按】` click marker; 來源 / 資料來源 / 出處 source labels |

---

## A. Fonts

**A1 (auto). CJK text uses the preset's CJK face; Latin letters, digits and
symbols use its Latin face.** A fixed pairing keeps every page consistent.
*Check:* every run on every slide (tables and groups included) resolves to
the right face for its script. Runs that set no face are resolved through the
text body's list style and then the theme.

**A2 (auto). Each text run holds one script.** A CJK run sets both the `latin`
and `ea` faces to the CJK face; every other run sets the Latin face. Setting
only `ea` is not enough: some viewers draw CJK with the `latin` face.
*Check:* a run that mixes CJK and Latin text, or a CJK run whose `latin` face
is not the CJK face, is a finding.

**A3 (auto). The theme's major and minor fonts are the same pairing.**
Speaker notes and text added later in PowerPoint then use it too.
*Check:* each slide master's theme sets major and minor `latin` to the Latin
face and `ea` to the CJK face.

A generator does not need to get A1–A3 right by hand: with a font preset the
gate applies `deck_quality.apply_font_pairing` before checking, which splits
runs by script, sets their faces, and sets the theme fonts.

## B. Wording

**B1 (auto). Mathematical notation, not code identifiers.** Write Δx and σ,
not `dx`, `sigma`, or `some_threshold_m`. The audience is following the
method, not the code.
*Check:* backticked code, snake_case identifiers, `name()` calls, spelled-out
lowercase Greek letter names, and `dx`/`dy`/`dz`/`dt` on a slide are findings.

**B2 (auto). No internal version numbers, experiment codes, run ids, or
internal jargon** (v3.2, E5, R2, ids of six or more digits, commit hashes).
They only mean something inside the research log. Public model and dataset
names are fine (YOLOv8, ResNet50, ImageNet-1k).
*Check:* `v<digits>` versions, one- or two-letter codes with a number,
`run`/`exp`/`trial`/`ckpt` numbers, bare numbers of six or more digits (write
large counts with separators: 12,345,678), and hex hashes. `F1`, `L1`, `L2`
are allowed in the core; a preset or an exception can allow more.

**B3 (manual). Describe the scene instead of using a code.** Write "the run
along the right wall", not "R2". The description must hold for every case it
names.

**B4 (auto). No source footnotes on the slide.** File paths and "Source:"
lines go in the speaker notes.
*Check:* a source label followed by a colon (core: Source, Sources, Data
source, Credit; the preset adds its own language's), Windows paths, relative
or absolute paths ending in a file name, and bare data or code file names.

## C. Numbers

**C1 (manual).** Every number says what it is, how it is computed, on which
data, and against what it is compared.

**C2 (manual).** Every threshold can answer "how was it set?". A threshold set
in advance says "set in advance, not tuned", and the notes give the reason. A
tuned one states what it was tuned on.

**C3 (manual).** When a version or method is not adopted, say by how much it
differs ("only 0.01 m better, so we kept the current one").

**C4 (manual).** The appendix has a numbers table (number / what it is / how
it is computed) in which every number on the main slides can be found.

## D. Structure

**D1 (manual).** Open with one slide of the full architecture. Before each
sub-topic, show the same diagram again with the part being discussed framed,
then go into detail.

**D2 (manual).** Every arrow on the architecture diagram ends at the module
that uses it.

**D3 (manual).** One step per slide. A mechanism with more than three steps is
split over several slides that follow one concrete example (fix the random
seed of any demo data).

**D4 (manual).** Titles state a conclusion or a question, never a bare noun
such as "Architecture" or "Results".

### Shape semantics

**D5 (manual). Architecture diagrams use shape to mean component kind.**
Within one deck a shape means one thing, with a legend where it first
appears.

| Component | Shape |
|---|---|
| Encoder | trapezoid, wide side towards the input (the shape says information is compressed) |
| Decoder, upsampling | trapezoid, narrow side towards the input |
| Generic module, layer | rounded rectangle |
| Data, feature, tensor | parallelogram or flat rectangle |
| Storage, memory bank | cylinder |
| Fusion: add, concatenate | circle with +, ⊕ or ∥ |
| Loss, final output | rounded rectangle with a heavy border or a distinct colour |

**D6 (manual). Flowcharts use the standard symbols:** start and end are
ovals (stadium); a process step is a rectangle; a yes/no decision is a
diamond with its exits labelled; input and output are parallelograms; a data
store is a cylinder; a sub-process is a double-bordered rectangle.

**D7 (manual).** A diamond has two or more exits, each labelled with its
condition. A "decision" with one exit is a rectangle.

## E. Layout

**E1 (auto). Connections are horizontal and vertical segments only (right-
angle bends), never diagonal.** A generator that draws lines should fail on a
diagonal segment as it draws it: use `deck_quality.orthogonal_segments`.
*Check:* straight connectors and line shapes with both width and height, any
curved connector, rotated connectors, and diagonal or curved segments in open
freeform paths that carry an arrowhead. Elbow connectors pass. Closed
freeforms (trapezoids, parallelograms) and arrowless open paths (plotted data)
are not connections and are not checked.

**E2 (auto screen + manual). Text does not overlap other text or leave the
page.** *Check:* the checker estimates each text block's extent from its font
size, wrapping, alignment and anchor (CJK 1 em, Latin by glyph class) and
reports estimated overlaps and off-page text. Estimates are a screen; the
exported page images are the final word.

**E3 (manual).** If the conversion tool merges a box's text into the box shape
itself (as `svg_to_pptx` does), a short box carries only its title and the
details go outside it. An outline that encloses other text is drawn with
lines, not a rectangle.

## F. Animation and speaker notes

**F1 (manual).** Animation order follows the data flow: where data enters,
which module it passes, where it is output.

**F2 (auto). Every slide has speaker notes.**
*Check:* notes are present and not blank on every slide.

**F3 (auto). The notes carry one click marker per click.** The number of
markers (preset `notes.click_marker`; core `[click]`, `zh-kai-times` `【按】`)
equals the slide's on-click animation steps.
*Check:* marker count against the `clickEffect` nodes in the slide's timing.

**F4 (manual).** The notes answer "why": how thresholds were set, why a
version was not changed, what each number means.

## G. Files

**G1.** Each output carries a timestamp, `deck-YYYYMMDDTHHMMSS.pptx`, and only
the newest copy is kept.
*Check:* generators given `--timestamp` write that name, delete older
timestamped copies of the same deck once the new one passes, and fail on a
name without a timestamp. `deck_quality.timestamped_output` and
`prune_older` do the same for any script.

## H. Verification before delivery

1. Run the checker's own tests, from the skill's `scripts/` folder:
   `python3 -m pytest tests/test_deck_quality.py`.
2. Generate the deck. The generator runs the checker at the end, and any
   finding fails the build. To let one through, list it in an exceptions file
   with its reason.
3. Export every slide to PNG from PowerPoint and look at each page: clipped
   or colliding text, arrow endpoints, framing boxes, fonts.
4. Run the slide show once and confirm the animation order matches the
   notes' click markers.
5. Deliver only when all of that passes. Report the checker result (finding
   count, waived exceptions) and the pages you looked at.

---

## Running the checker

Generators in this skill run it automatically:

```bash
cd "$(find ~/.claude -path "*/report-slides/scripts" -type d | head -1)"
python3 -m svg_to_pptx --slides <dir> --out <dir>/deck.pptx --deck-id <id> \
    --quality-preset zh-kai-times --quality-exceptions <dir>/deck.exceptions.yaml \
    --timestamp
```

`to_pptx.py` takes the same three options. A build that fails the gate exits
1 and renames its output to `<name>.rejected.pptx`, so it cannot be mistaken
for a deliverable.

Any other deck script calls the gate as its last step:

```python
import sys; sys.path.insert(0, "<report-slides>/scripts")
from deck_quality import enforce, timestamped_output, prune_older

out = timestamped_output("out", "deck")
prs.save(out)
enforce(out, preset="zh-kai-times", exceptions="deck.exceptions.yaml",
        check_name=True, check_siblings=False)   # raises DeckQualityError
prune_older(out)
```

To check an existing file: `python3 -m deck_quality deck.pptx --preset
zh-kai-times [--exceptions FILE] [--check-name] [--json]` (exit 0 pass, 1
findings, 2 bad preset or exceptions file). It never edits the deck unless
given `--fix-fonts`.

### Exceptions

An exception waives findings explicitly. Each entry names a rule, gives a
reason, and may narrow itself to one slide and to text the finding contains:

```yaml
exceptions:
  - rule: B2
    slide: 6
    match: A100
    reason: public GPU model name
  - rule: F2
    slide: 1
    reason: title card, nothing is said over it
```

An entry with no reason or an unknown rule is rejected before the build
starts. An entry that matches no finding is itself a finding (`EX`), so stale
exceptions do not pile up. The report lists every waived finding with its
reason.

### Adding a preset

Copy `presets/zh-kai-times.yaml`, name it for what it does (never for a
person, course, lab, or school), and set `fonts.latin` and `fonts.cjk` (both
or neither), `notes.click_marker`, `terms.source_labels`, and `terms.allow`.
Lists extend the core's; the marker replaces it.
