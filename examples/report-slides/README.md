# examples/report-slides — 週報簡報範例

這個目錄展示 `/report-slides` 技能的輸出樣貌。所有投影片都由 [`slide_data_weekly_progress.json`](slide_data_weekly_progress.json) 這個資料檔驅動，對應 `../research-log/` 裡三篇實驗日誌的內容。

## 這是什麼？

這是一份**每週 lab meeting 進度報告**，從實驗日誌自動生成。重點在：

- 這不是論文，這是**中繼匯報**——研究還在進行中
- slide03 的時間線顯示三週的演進，包含兩個 `amended` 修正標記
- 日誌裡的失敗（P7 梯度發散、rubric 截斷、score-boundary confusion）都反映在簡報的「下一步」裡
- 從 `slide_data.json` 到最終簡報，整個流程是資料驅動的，不是手工排版的

## 輸出格式

`/report-slides` 生成以下三種輸出：

### 1. SVG 原始檔（本目錄的 `.svg` 檔案）

每張投影片是一個獨立的 SVG 檔案，可以在任何向量編輯器（Inkscape、Figma、Illustrator）中直接開啟修改。尺寸固定為 1200×675（16:9）。

### 2. PPTX（`deck.pptx`）

**PPTX 的可編輯性是核心功能。** `deck.pptx` 用 `svg_to_pptx` 以 **native shapes** 方式生成——每個矩形、文字、線條、路徑都是獨立的 PowerPoint 物件，可以在 PowerPoint 365 / Keynote 裡直接點擊、移動、修改文字，不需要回來改原始 SVG。

Slides 08–09（架構圖與流程圖）共 28 + 38 個可編輯形狀，適合直接貼入論文簡報或進一步調整版面。

從 SVG 生成 PPTX（推薦方式，使用 svg_to_pptx）：

```bash
# 先確保 report-slides 技能已安裝
bash install.sh   # 在 repo 根目錄執行

# 切到 scripts 目錄執行 svg_to_pptx
SCRIPTS=$(find ~/.claude -path "*/report-slides/scripts" -type d | head -1)
cd "$SCRIPTS"
python3 -m svg_to_pptx \
    --slides /path/to/examples/report-slides/ \
    --out    /path/to/examples/report-slides/deck.pptx
```

或使用本目錄的 helper script：

```bash
# 從 repo 根目錄執行
python3 examples/report-slides/make_pptx.py \
    --slides examples/report-slides/ \
    --out    examples/report-slides/deck.pptx
```

> **相容性：** native shapes PPTX 適用 PowerPoint 365 / 2019+ / Keynote。  
> 如需相容舊版本，可加 `--mode embed` 改用 SVG embed 方式（形狀不可單獨編輯）。

### 3. `slide_data.json`（資料來源）

Path A（Python 資料驅動）投影片的資料定義檔。修改數字或文字後，用 `--slide N` 重新渲染單張投影片：

```bash
python scripts/generate_slides.py \
  --data examples/report-slides/slide_data_weekly_progress.json \
  --slide 4 \
  --out   examples/report-slides/
```

## 投影片列表

| 檔案 | 類型 | 說明 |
|------|------|------|
| `slide01_title.svg` | Title | 封面，作者、日期、研究主題 |
| `slide02_two_column.svg` | Two-column | 問題定義 vs. 本週方法 |
| `slide03_timeline.svg` | Timeline | 三週演進 + `amended` 修正標記 |
| `slide04_bar_chart.svg` | Bar chart | 分組長條圖，逐提示比較 QWK |
| `slide05_table.svg` | Table | 模型比較表，DIF 顏色標記 |
| `slide06_metric_cards.svg` | Metric cards | 4 張 KPI 卡，含 pending 樣式 |
| `slide07_conclusion.svg` | Conclusion | 結論 + next steps |
| `slide08_architecture.svg` | **Architecture** | **學術模板**：IEEE 風格系統架構圖，淺色底、標準標注、論文可用 |
| `slide09_flowchart.svg` | **Flowchart** | **學術模板**：標準流程圖符號（橢圓/矩形/菱形），決策迴路，右側標注欄 |

Slides 08–09 使用 `paper` 風格（`primary: #1f618d`、白色背景），適合直接插入學術論文簡報。

## 風格規範

Slides 01–07 使用 `default` 風格；slides 08–09 使用 `paper` 風格。

| 用途 | default | paper |
|------|---------|-------|
| Primary / 標題 | `#1e3a5f` | `#1f618d` |
| Positive / 達標 | `#059669` | `#1e8449` |
| Warning / 待定 | `#d97706` | `#d68910` |
| Danger / 失敗 | `#dc2626` | `#c0392b` |
| Muted / 標注 | `#64748b` | `#7f8c8d` |
| Background | `#f8fafc` | `#ffffff` |

切換整個 deck 的風格：

```bash
bash "$(find ~/.claude -path "*/report-slides/scripts/set-style.sh" | head -1)" paper
```

### Tracked visual-authoring fixture

`visual-authoring/` is a self-contained three-slide fixture for the reviewed
visual-authoring workflow. The architecture uses native editable SVG, the
researcher collaboration scene uses a hybrid raster base with separate SVG
overlays, and the accuracy comparison uses a deterministic data route from
`data.json`. The pipeline manifest records the reused baseline revision and
the evaluation-stage change bbox; the other manifests disclose their source,
overlay, and data provenance. Each visual includes rendered previews, a review
sheet, and a `review.json` record with separate pixel and structure statuses.
The tracked `deck.pptx` is exported with `svg_to_pptx --mode native` so the
architecture and chart objects remain editable, while the hybrid illustration
retains its declared raster layer alongside editable text and shapes.
