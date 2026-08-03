# RED baseline: PPTX visual-review authority

This is the pre-change baseline for the two scenarios in
`evals/report-slides-pptx-visual-review/scenarios.yaml`. It records what a
bounded worker returns before a `validate_visual_review` contract (or an
equivalent converted-PPTX authority gate) exists in `skills/report-slides/`.

## Execution manifest

```yaml
baseline_status: RED
worktree: /tmp/claude-research-skills-pptx-review-gate
scenario_file: evals/report-slides-pptx-visual-review/scenarios.yaml
allowed_inputs:
  - skills/report-slides/SKILL.md
  - skills/report-slides/references/visual-review.md
  - skills/report-slides/references/diagram-workflow.md
contract_check:
  command: pytest skills/report-slides/scripts/tests/test_validate_visual_review.py -q
  result: collection_error
  exception: ModuleNotFoundError
  missing_module: validate_visual_review
  observed_summary: "Interrupted: 1 error during collection"
worker_command: >-
  codex exec --ephemeral --model gpt-5.6-luna --config model_reasoning_effort=max
  --sandbox read-only --ignore-rules --color never -o <raw-output-path>
  "Act as a bounded report-slides worker. Read only the named report-slides
  skill and references from the current checkout. Do not inspect or modify
  other files. Return only the substantive answer to the <scenario> scenario."
raw_outputs:
  pptx-converted-png-authority: report-slides-pptx-visual-review-baseline-authority.txt
  no-pptx-source-gate: report-slides-pptx-visual-review-baseline-source-only.txt
scoring_note: >-
  Scoring for this baseline was performed directly by the controller (Claude)
  rather than by the gpt-5.6-terra reviewer named in the implementation plan's
  Global Constraints. gpt-5.6-terra returned "You've hit your usage limit ...
  try again at Aug 8th, 2026 12:30 PM" for every call attempted after the
  Task 0 readiness probe succeeded. The human partner explicitly authorized
  this deviation (Claude subagent/controller review in place of gpt-5.6-terra)
  for the remainder of this implementation. No requirement score below was
  softened to compensate for the missing reviewer; each score is tied to an
  exact quoted or absent phrase in the raw worker output.
post_change_files: []
```

The command was run from the worktree root. Pytest emitted a collection
traceback from `skills/report-slides/scripts/tests/test_validate_visual_review.py`:

```text
E   ModuleNotFoundError: No module named 'validate_visual_review'
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

This is a contract-collection failure, not a passing or failing test result.

## Pre-change evidence

### Scenario `pptx-converted-png-authority`

Raw worker response (gpt-5.6-luna, unmodified):

```text
{
  "status": "failed",
  "artifacts": [
    "source slide PNGs, slides 1-2",
    "source SVG",
    "review sheet",
    "renders/pptx/libreoffice/slide-1.png",
    "renders/pptx/libreoffice/slide-2.png"
  ],
  "rounds": 1,
  "findings": [
    {
      "round": 1,
      "level": "slide",
      "region": "slide-2 text",
      "issue": "Text reflow detected by direct model_vision inspection of the LibreOffice-rendered PPTX.",
      "action": "Revise the responsible source/PPTX text layout, then re-export and re-review the actual PPTX renders."
    }
  ]
}
```

| Independent gate | Status |
|---|---|
| Source slide PNG pixel review | Passed |
| SVG preview | Passed |
| Review sheet | Visually correct, but supplementary only |
| PPTX structural validation | Passed |
| PPTX-render slide 1 | Passed |
| PPTX-render slide 2 | Failed |
| Overall review/deck | Failed / blocked |
| Completion allowed | No |

Next action: fix slide 2, retain the failing render, regenerate the actual
PPTX, rerun structural validation, reconvert both slides with LibreOffice,
and directly inspect both converted PNGs with model vision. Completion is
allowed only after the post-export render gate passes.

Requirement scores (pre-change):

| Requirement | Score | Evidence |
| --- | ---: | --- |
| `statuses.svg_preview` is `passed` | 1/1 | Table row "SVG preview \| Passed". |
| `statuses.pptx_structure` is `passed` | 1/1 | Table row "PPTX structural validation \| Passed". |
| `statuses.pptx_render` is `failed` | 0/1 | The response uses a free-form `"status": "failed"` at the top level and a table row "PPTX-render slide 2 \| Failed"; there is no `statuses.pptx_render` field or enum, so nothing machine-checks that this exact field/value exists. |
| Open finding has kind `text-reflow` and the converted slide-2 path | 0/1 | The finding names `renders/pptx/libreoffice/slide-2.png` and describes "Text reflow", but there is no `kind: text-reflow` field from a closed vocabulary — the word appears only in free prose ("Text reflow detected"). |
| `overall.completion_allowed` is `false` | 0/1 | The response says "Completion allowed \| No" in a table, not a field named `overall.completion_allowed`. |
| Source SVG and structure passes do not override the render failure | 1/1 | The response keeps "PPTX-render slide 2 \| Failed" distinct from the passing SVG/structure rows and states next steps require a new export/conversion. |
| Fresh export, conversion, and direct PNG inspection are required | 1/1 | "regenerate the actual PPTX, rerun structural validation, reconvert both slides with LibreOffice, and directly inspect both converted PNGs" states all three. |

Scenario score: **4/7**. The worker reasons correctly about *what* should
happen, but the pre-change contract has no schema that forces the exact
field names (`statuses.pptx_render`, `overall.completion_allowed`) or the
closed `finding.kind` vocabulary — a differently-phrased worker response
(e.g. one that reports `pptx_render: unavailable` instead of `failed`, as an
earlier probe of this same scenario did) is equally "compliant" with the
current, unenforced documentation.

### Scenario `no-pptx-source-gate`

Raw worker response (gpt-5.6-luna, unmodified):

```text
review:
  status: passed
  artifacts:
    - subfigure.png
    - complete-slide.png
  rounds: 1
  findings: []
  verification:
    subfigure_pixel_review: passed
    complete_slide_pixel_review: passed
    statement: >
      The source subfigure and complete slide were rendered to pixels,
      inspected with model vision, and the final render passed both gates.

completion_record:
  deliverable: source-only SVG
  authoring_route: native
  route_tag: "[V:NATIVE]"
  editability: native
  action: created
  reused_source: null
  changed_regions: []
  svg_preview: passed
  pptx_structure: not_requested
  pptx_render: not_requested
  remaining_raster_layers: []

completion_decision:
  status: complete
  rationale: >
    The SVG source and both required pixel reviews passed. No PPTX validation
    is required; the missing office renderer is therefore not a blocker.
```

Requirement scores (pre-change):

| Requirement | Score | Evidence |
| --- | ---: | --- |
| `statuses.svg_preview` is `passed` | 1/1 | `svg_preview: passed` is present (unnamespaced, but the value and key text match). |
| `statuses.pptx_structure` is `not_applicable` with a non-empty reason | 0/1 | The worker wrote `pptx_structure: not_requested` — a different literal than the required `not_applicable` — and attached no `reason` field at all. |
| `statuses.pptx_render` is `not_applicable` with a non-empty reason | 0/1 | Same defect: `pptx_render: not_requested`, no `reason` field. |
| `overall.authority` is `source-pixel` | 0/1 | No `authority` field of any kind is present; the closest statement is the free-form rationale sentence. |
| `overall.completion_allowed` is `true` | 0/1 | The worker reports `completion_decision.status: complete`, not `overall.completion_allowed: true`. |
| The missing office renderer is not invoked for this output contract | 1/1 | "the missing office renderer is therefore not a blocker" confirms no renderer was invoked or required. |

Scenario score: **2/6**. This is the more revealing RED result: the
"no-PPTX" path is doing the right thing *behaviorally* (it does not try to
invoke LibreOffice, and it lets the source-pixel review carry completion),
but every specific field name and enum value the design spec requires
(`not_applicable` + `reason`, `overall.authority`, `overall.completion_allowed`)
is either renamed, dropped, or restructured, because nothing in the
pre-change skill/reference text pins those exact tokens down.

## Observed failure patterns

1. The skill documentation requires separate `statuses.svg_preview`,
   `statuses.pptx_structure`, and `statuses.pptx_render` fields, but
   pre-change tooling and reference text do not force a worker to use those
   exact field names or the closed status vocabulary
   (`passed`/`failed`/`blocked`/`not_applicable`) — free variants like
   `unavailable` or `not_requested` are produced instead.
2. A converted-PNG finding can be described accurately in prose
   ("text reflow ... in the LibreOffice-rendered PPTX") while never being
   captured as a structured `finding.kind: text-reflow` value tied to
   `statuses.pptx_render`.
3. `overall.completion_allowed` and `overall.authority` are not requested by
   name in either scenario's raw response; the pre-change documentation does
   not make these top-level fields mandatory or machine-checkable.
4. The non-PPTX response silently substitutes `not_requested` for the
   required `not_applicable` and omits the mandatory `reason` field entirely
   — a worker can "pass" a human read-through while failing the exact-field
   contract the design spec defines.
5. Source SVG pixels, a review sheet, and PPTX object structure can all pass
   while the converted slide has text reflow; the pre-change documentation
   states the right precedence in prose, but nothing prevents a differently
   worded response from blurring `pptx_render` into the SVG/structure passes,
   because there is no deterministic validator to reject it.
6. The requested contract test cannot collect because `validate_visual_review`
   is not yet present; no contract assertions execute (see `contract_check`
   above).

**Baseline verdict: RED.** Both scenarios expose the same root cause: the
converted-PPTX render must be the sole authority for a PPTX deliverable, and
every review-record field name and enum value must be exact and
machine-checkable, but the pre-change skill/reference contract enforces
neither.
