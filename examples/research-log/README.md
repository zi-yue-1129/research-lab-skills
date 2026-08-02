# examples/research-log — 實驗日誌範例

這三篇日誌展示的是**研究過程本身**，不是事後整理的成果報告。

## 這是什麼？

場景：NLP 研究者正在開發跨語言自動作文評分系統（ESAS）。以下三篇日誌涵蓋三週的實驗歷程：

| 日誌 | 模式 | 那週發生了什麼 |
|------|------|--------------|
| [`2026-05-10_esa_baseline_quick.md`](2026-05-10_esa_baseline_quick.md) | Quick | 第一週。用 GPT-4 zero-shot 建立基準。主要發現：QWK=0.674 可用，但 zh-TW 遷移的困難比預期大得多。快速記錄，沒時間寫完整分析。 |
| [`2026-05-18_bert_finetuned_full.md`](2026-05-18_bert_finetuned_full.md) | Full | 第二週。Fine-tuning BERT，花了整週。有失敗（P7 梯度發散了兩次）、有修正（`amended: 2026-05-20`，因為 P3 QWK 算錯了）、有尚未解決的問題（score-boundary confusion）。 |
| [`2026-05-25_crosslingual_eval_full.md`](2026-05-25_crosslingual_eval_full.md) | Full | 第三週。跨語言評估。有兩筆 `amended` 修正記錄，研究還在進行中（P5–P8 資料集等待預算）。 |

## 日誌格式特點

每篇日誌都是一個 Markdown 檔案，YAML frontmatter 追蹤：

```yaml
---
date: 2026-05-18
experiment: bert_finetuned
mode: exp
tags: [nlp, bert, fine-tuning]
follows: 2026-05-10_esa_baseline_quick.md   # ← 接續哪一次
git_head: f2d8e31                           # ← 對應程式碼版本
slide_decks: []                             # ← 生成簡報後自動填入
amended:
  - date: 2026-05-20
    sections: [Results, Analysis]
    reason: 修正 P3 QWK 計算錯誤          # ← 事後修正，有理由
---
```

### 為什麼 `Failures` 章節很重要

第二篇日誌的 `Failures` 節記錄了：
- P7 在 3 次 seed 裡有 2 次梯度在 epoch 3 爆炸
- Rubric 截斷了 12% 的樣本
- Score-boundary confusion 尚未解決

這些不是「失敗要隱藏的事」。它們在寫論文的時候會成為：
- 方法論的設計說明（為什麼 P7 用 LR=1e-5）
- 討論章節的 Limitations 段落
- Future work 的具體方向

### `follows:` 串成時間線

```
2026-05-10 quick  →  2026-05-18 full  →  2026-05-25 full
(baseline)           (bert ft)            (cross-lingual)
```

`/research-log index` 指令會從所有日誌的 frontmatter 自動重建 `INDEX.md`，顯示完整的研究時間線。

## 查詢章節歷史

先尋找已安裝技能中的查詢腳本，再列出可查詢的章節類型、搜尋歷史，並讀取選定結果：

```bash
SECTION_QUERY="$(find ~/.claude -path "*/research-log/scripts/section_query.py" | head -1)"
python3 "$SECTION_QUERY" types --dir examples/research-log
python3 "$SECTION_QUERY" search \
  --dir examples/research-log \
  --sections Failures \
  --range all
python3 "$SECTION_QUERY" fetch \
  --dir examples/research-log \
  --ids "2026-05-18_bert_finetuned_full::failures"
```

若 `fetch` 回應溢位，回應不會包含任何部分正文。請使用每個 `suggested_batches[].ids` 群組重複執行 `fetch`，或使用回傳的 `chunk_cursor` 繼續讀取，直到 `next_chunk_cursor` 為 `null`。

## 生成的簡報

這三篇日誌生成了 [`../report-slides/`](../report-slides/) 裡的 7 張週報投影片。slide03 的時間線圖就是從 `follows:` 鏈與日期自動建構的。

使用 `/report-slides` 技能從你自己的日誌生成簡報時，Claude 會先讀取日誌，提出大綱讓你確認，再生成 SVG + PPTX。
