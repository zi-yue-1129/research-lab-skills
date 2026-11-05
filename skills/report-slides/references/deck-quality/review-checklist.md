# Research deck review checklist

The manual half of [`standard.md`](standard.md). Work from the exported page
images and one run of the slide show, after the automatic gate has passed.
Note the slide number for anything that fails and fix it before delivery.

## Wording
- [ ] **B3** Codes are replaced by scene descriptions, and each description holds for every case it names.

## Numbers
- [ ] **C1** Each number says what it is, how it is computed, on which data, and compared with what.
- [ ] **C2** Each threshold says how it was set: "set in advance, not tuned" (reason in the notes) or what it was tuned on.
- [ ] **C3** Each rejected version or method states the difference that decided it.
- [ ] **C4** The appendix numbers table lists every number on the main slides.

## Structure
- [ ] **D1** A full-architecture slide opens the deck, and each sub-topic reopens it with the current part framed.
- [ ] **D2** Every arrow on the architecture diagram ends at the module that uses it.
- [ ] **D3** One step per slide; mechanisms over three steps are split and follow one concrete example (fixed seed).
- [ ] **D4** Every title is a conclusion or a question.
- [ ] **D5** One shape means one component kind throughout, with a legend at first use (encoder/decoder trapezoids, rounded-rectangle modules, parallelogram data, cylinder storage, circle fusion, emphasised loss/output).
- [ ] **D6** Flowcharts use standard symbols (oval start/end, rectangle step, diamond decision with labelled exits, parallelogram I/O, cylinder store, double-bordered sub-process).
- [ ] **D7** Every diamond has at least two labelled exits.

## Layout (page images)
- [ ] **E2** No text is clipped, collides, or leaves the page. The checker only estimates this.
- [ ] **E3** Short boxes carry only their title; enclosing outlines are drawn with lines.
- [ ] Arrow endpoints touch their boxes, framing boxes sit on what they frame, fonts render as the preset says.

## Slide show
- [ ] **F1** Animations appear in data-flow order.
- [ ] **F3** Each click lands where the notes put a click marker.
- [ ] **F4** The notes explain why: thresholds, rejected versions, what each number means.

## Delivery report
State: the checker result (findings, waived exceptions and their reasons), the
pages viewed, and anything on this list left open.
