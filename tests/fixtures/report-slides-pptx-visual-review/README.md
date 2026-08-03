# PPTX visual review fixtures

Six concrete, real cases proving that source-SVG similarity cannot mask a
converted-PPTX-only visual defect. Every artifact below was produced by
actually running the pipeline the skill describes — not hand-drawn or
asserted:

1. `python3 -m svg_to_pptx --slides <case>/source --out <case>/deck.pptx --mode native`
   (the existing `skills/report-slides/scripts/svg_to_pptx` converter, unmodified)
2. `libreoffice --headless --convert-to pdf --outdir <case>/renders/pptx <case>/deck.pptx`
3. `pdftoppm -png -r 150 <case>/renders/pptx/deck.pdf <case>/renders/pptx/slide`
4. The source SVG(s) were independently rasterized with `cairosvg` (a
   transform-aware, standards-compliant SVG renderer) to
   `<case>/renders/source/slide-NN.png`, giving a ground-truth comparison
   image that is never derived from the PPTX pipeline.
5. Every `renders/source/*.png` and `renders/pptx/*.png` pair was directly
   inspected (by model vision) before `review.json` was written; each
   `review.json` finding describes only what was actually visible in that
   inspection.

Provenance: `LibreOffice 7.3.7.2`, `poppler/pdftoppm 22.02.0`, `cairosvg 2.9.0`
(installed in this environment; re-running the commands above on another
LibreOffice/poppler build may produce a different `renderer.version` — that
is expected and is exactly why `review.json` records the renderer identity
actually used for each run rather than a fixed constant).

## Case semantics

- **clean-two-slide** — a two-slide deck (a three-node pipeline diagram, and
  a text-plus-image slide) with no known converter limitation triggered.
  All three gates (`svg_preview`, `pptx_structure`, `pptx_render`) pass and
  `overall.completion_allowed` is `true`. This is the control case: it
  proves the other five cases fail because of a real, isolated defect, not
  because the harness always fails PPTX output.

- **native-text-reflow** — the converter's native-textbox width estimate
  (`skills/report-slides/scripts/svg_to_pptx/text_converter.py`,
  `_estimate_text_width`) is a character-count heuristic
  (`chars * font_size * 0.65`), not real font metrics. A long bold title
  renders wider than that estimate in LibreOffice, so the converted textbox
  (`word_wrap=False`) does not wrap — the run overruns the slide's right
  boundary and is sheared off there, instead of remaining a single fully
  visible line. `pptx_render` fails
  with an open `text-reflow` finding; `svg_preview` and `pptx_structure`
  both pass, and neither pass overrides the render failure.

- **connector-endpoint-drift** — the converter never applies the SVG
  `transform` attribute to shape or connector coordinates
  (`style_parser.apply_transform_to_pos` is defined but never called
  anywhere in the converter). A target shape authored inside
  `<g transform="translate(...)">` converts at its untransformed local
  coordinates, landing on top of a different shape; the straight connector
  keeps its own absolute coordinates and no longer touches anything.
  `pptx_render` fails with an open `connector-drift` finding.

- **image-crop-regression** — the same ignored-`transform` limitation
  applied to an `<image>` inside a translated group: the picture converts at
  its raw, untransformed x position, which extends past the 1200-unit
  canvas width. The PPTX slide boundary crops the picture's two rightmost
  data points that were fully visible in the source render.
  `pptx_render` fails with an open `crop` finding.

- **missing-image-relationship** — the source SVG references its image as a
  `data:` URI. `svg_to_pptx/shapes.py`'s `_add_image` explicitly returns
  `None` (adds no picture at all) whenever `href.startswith("data:")`.
  Confirmed by inspecting the exported package directly: `python-pptx`
  reports zero picture shapes on the slide, and unzipping the `.pptx` shows
  no `ppt/media/` entry at all. This is a **structural** failure —
  `pptx_structure` fails with an open `missing-image` finding — and the
  converted render independently and consistently shows the image absent,
  recorded as its own `pptx_render` finding under the render gate. The two
  findings are not merged into one status.

- **unreadably-small-text** — a text element authored at `font-size="10"`
  inside `<g transform="scale(3) ...">` renders at an effective, readable
  size in any transform-aware viewer (the source render). The converter
  ignores the transform and uses the literal `font-size="10"` at the raw,
  unscaled position, producing text that is both tiny and partly hidden
  behind the slide's top bar in the converted render. `pptx_render` fails
  with an open `unreadably-small-text` finding.

## Direct-inspection instructions

To re-verify any case's rendered evidence yourself:

1. Open `<case>/renders/source/slide-NN.png` — this is the ground-truth,
   transform-aware rendering of the source SVG.
2. Open `<case>/renders/pptx/slide-NN.png` — this is the actual converted
   PPTX, rasterized by the real office renderer named in `review.json`.
3. Compare them side by side. For every case except `clean-two-slide`, the
   two images visibly differ in exactly the way `review.json`'s finding
   `description` states; `renders/pptx/deck.pdf` is the retained
   intermediate conversion artifact between `deck.pptx` and the final PNGs.
4. Validate the record's shape and derived completion decision
   deterministically:
   ```bash
   python3 skills/report-slides/scripts/validate_visual_review.py \
     --record tests/fixtures/report-slides-pptx-visual-review/<case>/review.json \
     --root tests/fixtures/report-slides-pptx-visual-review
   ```
   Every path inside a case's `review.json` is written relative to this
   shared fixtures root (e.g. `clean-two-slide/source/slide-01.svg`), not
   relative to the case's own directory, so every case can be validated
   against the same `--root` argument.
   This checks record shape, path safety, and the derived `overall` result;
   it does not re-verify that the described visual defect is actually
   visible — only direct inspection of the PNGs (step 3) does that.
