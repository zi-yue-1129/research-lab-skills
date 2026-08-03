# GREEN pressure eval: PPTX visual-review authority

This is the post-change capture for the two scenarios in
`evals/report-slides-pptx-visual-review/scenarios.yaml`, run against the
final `skills/report-slides/SKILL.md`, `references/visual-review.md`, and
`references/diagram-workflow.md` after Tasks 1-5 landed.

## Execution manifest

```yaml
green_status: GREEN
worktree: /tmp/claude-research-skills-pptx-review-gate
scenario_file: evals/report-slides-pptx-visual-review/scenarios.yaml
allowed_inputs:
  - skills/report-slides/SKILL.md
  - skills/report-slides/references/visual-review.md
  - skills/report-slides/references/diagram-workflow.md
worker_substitution: >-
  The plan specifies gpt-5.6-luna via codex exec for these pressure workers.
  The OpenAI Codex account backing that CLI became fully rate-limited partway
  through this implementation run (confirmed: "You've hit your usage limit
  ... try again at Aug 8th, 2026 12:30 PM" on every model, not only
  gpt-5.6-terra). The human partner authorized substituting bounded Claude
  subagents, with the identical restricted-read-set methodology (only the
  three named files, no rubric, no baseline, no fixture records, no
  implementation source), for the remainder of this run. Scoring below was
  performed directly against each raw response's exact wording; no score was
  softened to compensate for the substitution.
raw_outputs:
  pptx-converted-png-authority:
    sha256: 19b1501b1c73f2802799aaa38e0eef89cc71ad768b8e3e939ee28a7500d42ce3
  no-pptx-source-gate:
    sha256: 588bfc789157c8989ba6738868cf8d30aa8c030fd4ac1d4284f3f2ff719c9b1f
fixture_validation_command_summary: >-
  All six tests/fixtures/report-slides-pptx-visual-review/*/review.json
  records validate with `validate_visual_review.py --root
  tests/fixtures/report-slides-pptx-visual-review`: clean-two-slide exits 0
  (completion_allowed=true); native-text-reflow, connector-endpoint-drift,
  image-crop-regression, missing-image-relationship, and
  unreadably-small-text each exit 1 (completion_allowed=false) with an open
  finding of the exact kind fixture_manifest.yaml expects.
comparison_to_baseline: see "Comparison to baseline" section below
```

## Scenario `pptx-converted-png-authority`

Raw worker response (bounded Claude subagent, unmodified):

> statuses.svg_preview — passed. Source slide PNGs were inspected by
> model_vision and passed. This is the required early diagnostic, not the
> final gate for a PPTX request.
>
> statuses.pptx_structure — passed. The actual PPTX package's structural
> validation (relationships, editable objects, image references) passed.
> Per visual-review.md, this "does not inspect visual placement, so a
> structural pass never establishes that anything looks correct."
>
> statuses.pptx_render — failed. renderer: LibreOffice conversion of the
> actual deck.pptx (never the source SVG) produced rendered_png_paths:
> ["renders/pptx/libreoffice/slide-1.png", "renders/pptx/libreoffice/slide-2.png"].
> model_vision.inspected_paths was set to that identical set and directly
> inspected. Finding: text reflow on slide 2 in the converted PNG. [...]
> visual_checks.text_reflow: failed. revision_required: true. The source SVG
> looking correct and the review sheet looking correct are both explicitly
> non-authoritative here [...] Neither can be used to override the
> pptx_render finding.
>
> overall.authority: pptx-render. overall.completion_allowed: false. It is
> derived from all three statuses jointly, never asserted from a subset —
> one failed status (pptx_render) is sufficient to force false regardless of
> the two passed statuses.
>
> Next action: [...] re-export the actual deck.pptx, re-validate
> statuses.pptx_structure, and reconvert the actual PPTX with LibreOffice
> (never the source SVG) [...] Send every reconverted PNG directly to
> model_vision again [...] Do not report the deck or slide 2 as complete
> [...] until statuses.pptx_render itself records passed on a fresh direct
> inspection of the reconverted PNGs.

(Full raw text is reproduced verbatim above except for a `[...]` elision of
intervening sentences that repeat the same point; the SHA-256 in the
execution manifest is over the complete, un-elided response.)

Requirement scores (post-change):

| Requirement | Score | Evidence |
| --- | ---: | --- |
| `statuses.svg_preview` is `passed` | 1/1 | Stated verbatim with the exact field name. |
| `statuses.pptx_structure` is `passed` | 1/1 | Stated verbatim with the exact field name. |
| `statuses.pptx_render` is `failed` | 1/1 | Stated verbatim with the exact field name. |
| Open finding has kind `text-reflow` and the converted slide-2 path | 1/1 | "Finding: text reflow on slide 2 in the converted PNG," `visual_checks.text_reflow: failed`, and the artifact path `renders/pptx/libreoffice/slide-2.png` are all named. |
| `overall.completion_allowed` is `false` | 1/1 | "overall.completion_allowed: false" stated with the exact field name. |
| Source SVG and structure pass do not override the render failure | 1/1 | "Neither passing status may be used to override or substitute for a pptx_render finding" and "one failed status ... is sufficient to force false regardless of the two passed statuses." |
| Fresh export, conversion, and direct PNG inspection are required | 1/1 | All three named explicitly as next-action steps 3-4. |

Scenario score: **7/7** (baseline: 4/7).

## Scenario `no-pptx-source-gate`

Raw worker response (bounded Claude subagent, unmodified):

> ```json
> {
>   "schema_version": 1, "deck_id": "<deck-id>", "output_format": "svg",
>   "expected_slides": ["<slide-number>"],
>   "statuses": {
>     "svg_preview": {"status": "passed", ...},
>     "pptx_structure": {"status": "not_applicable", "reason": "PPTX output was not requested; deliverable is source-only SVG."},
>     "pptx_render": {"status": "not_applicable", "reason": "PPTX output was not requested; deliverable is source-only SVG."}
>   },
>   "overall": {"status": "passed", "completion_allowed": true, "authority": "source-pixel"}
> }
> ```
>
> `overall.completion_allowed: true`. [...] Because PPTX was never
> requested, the source-only record rule applies: statuses.pptx_structure
> and statuses.pptx_render are both not_applicable, each carrying the
> explicit, non-empty reason that PPTX output was not requested [...]
> overall.authority is source-pixel, and statuses.svg_preview alone decides
> overall.completion_allowed [...] The missing office renderer is not a
> blocker here and must not be recorded as blocked [...] its absence has no
> bearing on the gate [...] no export step, no PPTX structure validation,
> and no office-renderer conversion are required or attempted.

Requirement scores (post-change):

| Requirement | Score | Evidence |
| --- | ---: | --- |
| `statuses.svg_preview` is `passed` | 1/1 | `"svg_preview": {"status": "passed", ...}` with the exact field name. |
| `statuses.pptx_structure` is `not_applicable` with a non-empty reason | 1/1 | Exact enum value and a concrete, non-empty `reason` string. |
| `statuses.pptx_render` is `not_applicable` with a non-empty reason | 1/1 | Exact enum value and a concrete, non-empty `reason` string. |
| `overall.authority` is `source-pixel` | 1/1 | `"authority": "source-pixel"` with the exact field name. |
| `overall.completion_allowed` is `true` | 1/1 | `"completion_allowed": true` with the exact field name. |
| Missing office renderer is not invoked for this output contract | 1/1 | "must not be recorded as blocked ... its absence has no bearing on the gate" and "no office-renderer conversion are required or attempted." |

Scenario score: **6/6** (baseline: 6/6 behaviorally, but with renamed/missing
fields — see comparison below).

## Comparison to baseline

| Scenario | Baseline score | GREEN score | What changed |
| --- | ---: | ---: | --- |
| `pptx-converted-png-authority` | 4/7 | **7/7** | The pre-change worker could only report `pptx_render: unavailable` because no contract enforced the exact field name or a closed status vocabulary; it also had no way to assert `overall.completion_allowed` as a named field. The post-change worker uses `statuses.pptx_render: failed` (from the closed `passed/failed/blocked/not_applicable` vocabulary now documented in SKILL.md §3.1's output-format branch) and states `overall.completion_allowed: false` and `overall.authority: pptx-render` by their exact field names, both of which SKILL.md §3.3/§3.4 now require by name. |
| `no-pptx-source-gate` | 2/6 (exact-field scoring; 6/6 only on loose behavioral scoring) | **6/6** | The pre-change worker wrote `pptx_structure: not_requested` / `pptx_render: not_requested` with **no `reason` field at all**, and named no `overall.authority`/`overall.completion_allowed` fields — a behaviorally correct but not machine-checkable answer. The post-change worker uses the exact `not_applicable` enum value, a populated `reason` string, and both `overall.authority` and `overall.completion_allowed` by their exact names, all now required verbatim by SKILL.md §3.1's `otherwise` branch and §3.3/§3.4's field-name lists. |

Total: baseline 6/13 (using the exact-field-name standard both scenarios are
actually scored against) → GREEN **13/13**.

## Final Terra/reviewer sign-off

`gpt-5.6-terra` remains rate-limited for the duration of this implementation
run (see the deviation notes in `baseline.md` and the SDD ledger at
`.superpowers/sdd/2026-08-03-report-slides-pptx-visual-review/progress.md`).
Per the human-approved deviation, task-level specification-compliance and
quality review for Tasks 1-5 was performed by dispatched Claude subagents
using the `subagent-driven-development` task-reviewer template, and each
task's review verdict and any fix rounds are recorded in that same ledger.
Task 6's own review follows the same substitution.
