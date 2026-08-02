# Report-slides Visual Authoring Baseline

This RED baseline records five independent `gpt-5.6-luna` responses against the
unchanged `skills/report-slides/SKILL.md`. Each raw response is preserved
verbatim, followed by explicit requirement scoring. A score is based only on
what the response states; unstated behavior is not inferred.

## Execution manifest

- Base commit: `8e9642817d41aad8bbb4c4d25b057603260cf018`
- Base skill SHA-256: `34d8ddbb41bb51ba5539029196ef95472dfb3acfbe2c5e95e485071239309ab4`
- Agent command template (scenario prompt substituted per case):
  `codex exec --ephemeral --model gpt-5.6-luna --config model_reasoning_effort=max --sandbox read-only --ignore-rules --color never -o <raw-output> 'Act as bounded luna_worker. Read only skills/report-slides/SKILL.md from the current checkout. Do not inspect or modify any other files, do not launch nested Codex, and return only the substantive answer to this scenario: <scenario prompt>'`
- Raw capture SHA-256 values:
  - architecture: `4877aa5433100de94759db65d44257d48120f17745fc5b7f94a7572d929af47d`
  - hybrid: `b2187c960a015eff4a29ad2ea4151fa3b929904d90b531736a6ab1a0d206d9e7`
  - statistics: `29f21722d242b8a30e5900eafa432a68de227248066408f647734244ca2d1c63`
  - reuse: `5f4bea229ae969bffec26602bc2916ee345e2ec231e10463ac1a7ad1d31eff84`
  - completion: `e75e952cb4646e695b4285871e8ad0c7d21b37a66e7171ff1e8295a085a5f97c`

## architecture-planning

Prompt: Use report-slides to plan one slide explaining ingestion, feature processing, training, evaluation, human approval, and publishing. Describe artifacts created before drawing and how PPTX stays editable.

### Raw response

````text
Create one [B] Mermaid diagram slide using `flowchart LR`:

`Ingestion → Feature processing → Training → Evaluation → Human approval → Publishing`

Before drawing:

- Create `docs/slides/reports/YYYY-MM-DD_<name>/`.
- Write `slide01.mmd` containing the six stages, concise descriptions, and representative artifacts:
  - raw data
  - feature set
  - trained model/checkpoint
  - evaluation report
  - approval record
  - published package
- No `slide_data.json` is needed because this is a Mermaid-only slide.

Render with `mmdc` to `slide01_diagram.svg`. Export using native mode:

```bash
python3 -m svg_to_pptx \
  --slides docs/slides/reports/YYYY-MM-DD_<name>/ \
  --out docs/slides/reports/YYYY-MM-DD_<name>/deck.pptx
```

Native mode converts SVG rectangles, text, connectors, and paths into editable PowerPoint shapes. Text remains directly editable, and connectors can reroute when shapes move. Avoid `--mode embed`, which preserves appearance but does not make individual shapes editable.
````

### Requirement scores

- [fail] Named subfigures or regions — the response names six pipeline stages but does not plan named subfigures or bounded regions.
- [pass] Editable nodes, labels, and connectors — it explicitly selects native mode and states that rectangles, text, connectors, and paths remain editable.
- [fail] Rendered-pixel review before completion — it specifies rendering and export, but no pixel inspection or revision gate.

Observed failure pattern: the existing skill can select a diagram route and native export, but it does not force subfigure planning or visual review.

## hybrid-generative-visual

Prompt: Plan a conceptual researcher-and-AI-lab slide. Use generated imagery where useful, keep factual annotations editable, and state files and disclosures.

### Raw response

````text
采用 `[C] Claude SVG` 路径，画布固定为 `1200×675`。

**概念布局**

- 标题：`Researcher + AI Lab: From Question to Evidence`
- 左侧：研究者、实验笔记与研究问题。
- 中部：可编辑流程环：`Question → Hypothesis → Experiment → Review → Insight`。
- 右侧：AI 实验室模块：模型、工具、计算资源、审计/复现。
- 用一张抽象的 AI 生成实验室图作为装饰或视觉参考；不放真实人物、品牌标志或虚构数据。
- 所有标题、箭头、标签、指标和来源注释使用 SVG 原生文本与形状，确保导出 PPTX 后可编辑。

由于该技能的直接 SVG 规则禁止 `<image>` 标签，规范的可编辑版本应保持矢量化；生成图像作为独立素材保存，或仅用于制作视觉参考。若放入最终幻灯片，则明确标注其为不可编辑的装饰性图像。

**建议文件**

- `docs/slides/reports/YYYY-MM-DD_researcher-ai-lab/slide01.svg`
- `docs/slides/reports/YYYY-MM-DD_researcher-ai-lab/hero_generated.png`（可选）
- `docs/slides/reports/YYYY-MM-DD_researcher-ai-lab/hero_prompt.txt`（可选）
- `docs/slides/reports/YYYY-MM-DD_researcher-ai-lab/disclosures.md`
- `docs/slides/reports/YYYY-MM-DD_researcher-ai-lab/deck.pptx`（可选，使用原生 SVG 转换）

**披露内容**

在页脚和 `disclosures.md` 中注明：

> Conceptual illustration. Any hero imagery is AI-generated and decorative, not a photograph or research evidence. Factual annotations require source citations and remain editable SVG/PPTX text.

来源编号、实验数据、样本量和性能数字只在有明确来源时加入；没有来源的内容标为 `illustrative` 或 `placeholder`。
````

### Requirement scores

- [pass] Raster illustration separated from editable factual overlays — it separates the hero image from native labels, arrows, metrics, captions, citations, and callouts.
- [pass] No generated prose labels, legends, or precise values — it requires factual overlays to be native rather than baked into generated imagery.
- [fail] Prompt sources and editability recorded — it names an optional prompt file and requires source citations, but does not record a concrete prompt source or source file/identifier; editability is described only at the policy level.

Observed failure pattern: the response handles the raster/editable boundary and disclosure language, but it does not record concrete prompt/source provenance or define a manifest, review artifact, or render-review loop.

## statistical-integrity

Prompt: Plan an accuracy chart from 72.1, 81.6, 98.4, and 100.0. Explain how data integrity and rendered visual quality are verified.

### Raw response

````text
Use the Python `[A]` `bar_chart` renderer with one series:

```json
{
  "type": "bar_chart",
  "title": "Accuracy by Evaluation Point",
  "categories": ["Point 1", "Point 2", "Point 3", "Point 4"],
  "series": [
    {
      "label": "Accuracy (%)",
      "color": "#059669",
      "values": [72.1, 81.6, 98.4, 100.0]
    }
  ],
  "y_max": 100
}
```

Verify data integrity by checking that there are exactly four numeric values, their order is unchanged, each lies between 0 and 100, and the displayed labels preserve one-decimal precision. Do not infer missing semantic labels or calculate an unrequested average.

Verify rendered quality by inspecting the generated SVG for a `1200 × 675` canvas, a 0–100 y-axis, proportional bar heights, visible value labels, readable text, sufficient contrast, and no clipping or overlap—especially for the 100.0% bar at the axis maximum. Re-render after correcting any layout or legibility issue.
````

### Requirement scores

- [pass] Deterministic rendering rather than image generation — it selects the Python bar-chart renderer.
- [pass] Reconstructable source data — it gives an explicit JSON payload containing all four values and chart settings.
- [fail] Chart and complete-slide pixel review — it requests inspection of the chart SVG, but does not require a separate complete-slide render review artifact.

Observed failure pattern: deterministic chart/data guidance exists, but the review scope stops at a single chart render and is not tied to a tracked review record.

## reuse-and-change-disclosure

Prompt: A project training-pipeline diagram gains a human-review branch and failure return path. Explain whether to redraw or modify and how to report location.

### Raw response

````text
Modify the existing Mermaid source rather than redraw from scratch. Preserve current nodes and layout, then add:

- A branch from the relevant training/validation stage to `Human Review`.
- An approval edge back to the normal pipeline.
- A failure edge returning to the corrective or retraining stage.

Regenerate the diagram with `flowchart TD` for training stages. Report the updated source and rendered diagram in `docs/slides/reports/YYYY-MM-DD_<name>/`, identifying the slide as `[B] Mermaid` and listing both `slideNN.mmd` and `slideNN_diagram.svg`. If Mermaid is unavailable, use a Claude SVG `[C]` fallback and note that in the summary.
````

### Requirement scores

- [fail] Asset-library search first — it says to modify existing Mermaid source but does not search a project asset library or identify a reusable asset.
- [pass] Previous source modified instead of unrelated regeneration — it explicitly says to modify the existing source and preserve current nodes/layout.
- [fail] `based_on_revision`, changed-region bounding box, and reason — none of these identity/change fields are recorded.
- [fail] Change-focused delivery summary — it lists files and route, but not named changed regions with reasons.

Observed failure pattern: source reuse is encouraged informally, but identity, revision lineage, changed regions, and disclosure are not machine-checkable.

## completion-report

Prompt: A deck contains a native architecture diagram, a hybrid conceptual image, and a data chart. Show the per-visual completion report you would return after export and validation.

### Raw response

````text
### Per-visual completion report

| Visual | Render path | Export result | Validation | Status |
|---|---|---|---|---|
| Architecture diagram | `[B] Mermaid` | Exported to native PPTX shapes; text, nodes, connectors, and paths remain editable | SVG rendered correctly; PPTX opened and editability verified | **PASS** |
| Hybrid conceptual image | `[C] Claude SVG` | Conceptual composition exported; native vector elements remain editable. Any embedded raster component is documented as view-only | Layout, text escaping, scaling, and visual fidelity verified | **PASS — hybrid boundary noted** |
| Data chart | `[A] Python renderer` | Chart exported as SVG/PPTX and remains re-renderable from `slide_data.json` | Values, labels, axes, legend, and rendering verified | **PASS** |

Deck export: **PASS**  
PPTX: `.../deck.pptx`  
Re-render source for the chart: `.../slide_data.json`  
Rendering paths are recorded as `[A]`, `[B]`, and `[C]` in the slide list.
````

### Requirement scores

- [fail] Diagram type, slide location, route, ID, and action — it gives visual names and broad export status, but no slide locations, asset IDs, route IDs, or actions.
- [fail] Reused source and changed regions with reasons — neither reuse lineage nor changed regions/reasons are reported.
- [fail] Editability and review rounds — editability is stated and validation is claimed, but review rounds are absent.
- [fail] Separate SVG preview, PPTX structure, and PPTX render validation — the table combines checks into one validation column and does not provide separate structure/render artifacts or check records.
- [fail] Remaining raster layers and rationale — it only says that any embedded raster component would be documented as view-only; it gives no concrete remaining-layer inventory or rationale.

Observed failure pattern: the report is a useful high-level pass/fail summary, but it cannot audit per-visual identity, provenance, review rounds, or export-layer evidence.

## RED conclusion

The baseline contains target failures in all five scenarios. The current skill provides rendering routes and native export guidance, but lacks mandatory subfigure planning, asset manifests and identity, generated-image provenance contracts, complete-slide pixel review, revision/change reporting, and auditable per-visual completion reports.
