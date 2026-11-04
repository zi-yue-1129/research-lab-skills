# Lecture deck style guide

Distilled from three reference lecture decks the lab supplied (2026-10):

| Deck | Slides | Theme it defines |
|---|---|---|
| 07 空間濾波 (Image Processing) | 35 | warm-paper, earlier variant |
| 第 06 週 U-Net 語意分割 (Deep-learning CV) | 38 | navy-academic |
| 第 06 週 判斷類別：分類與決策樹 (Intro to AI) | 28 | warm-paper |

The rules below are what the three decks do consistently. Each rule names the
slide that shows it, so the rule can be checked against the source.

---

## A. Teaching narrative

1. **Open with one concrete case, close by answering it.** The decision-tree
   deck opens on one Titanic passenger ("先問一個問題：她活下來了嗎？",
   slide 2) and answers that exact passenger on slide 19 ("回到開頭：她活下來
   了嗎？"). The U-Net deck opens on one cat photo and keeps using it to the
   end. Pick the case before writing any other slide.
2. **Show where it is used before how it works.** Real applications come
   early: 產線上的分類、拿現成的 AI 去看回收廠 (decision tree, slides 4–5),
   哪裡會用到 (U-Net, slide 5).
3. **Titles are questions or claims, never topic labels.** "電腦怎麼看一群人
   「混不混」？", "遮罩就是每個像素一個數字", "輸出：每個像素是寵物的機率".
   A reader who sees only the titles should be able to follow the lecture.
4. **Bridge from last week.** An early slide sets last week's idea beside this
   week's ("上週和這週：答案是數字，還是類別？"). Use the `compare` layout.
5. **Show the agenda, then a section nav on every slide.** A numbered
   agenda (U-Net slide 2, decision-tree slide 7) names 4–5 stages; afterwards,
   small chips in the top-right corner show which stage the slide belongs to.
6. **One idea per slide, built from a worked example.** Formulas arrive *after*
   a tiny worked case (3 × 3 grid, 10 dots, one passenger), and are restated in
   plain words immediately ("白話：隨便抽兩個人，一個活、一個沒活的機率").
7. **Real numbers, computed.** Every number is either measured in class
   ("我們用一個小 CNN 在筆電 CPU 上量：1.46 秒") or cited. Big stat numbers
   carry a one-line label saying what was counted.
8. **Each content slide ends with a takeaway sentence** centred above the
   footer, in muted text, with at most one emphasised phrase.
9. **Code is short and annotated.** A code panel holds at most ~12 lines,
   with call-outs beside it naming the 2–3 lines that matter.
10. **Test one change at a time.** Depth vs. accuracy (決策樹 slide 17),
    "拿掉跳接會怎樣" and "一次改一件事，分數差多少" (U-Net slides 22, 30).
11. **Close with the method in context, then what comes next.** "常見的分類
    方法" (decision tree, slide 20) puts the method among its neighbours, one
    slide per neighbour follows, a memorable anecdote (鴿子、聰明的漢斯) checks
    understanding, and "下週：…" previews the next lecture. Coursework decks
    end with the assignment (本週題目、要交的東西、規則).
12. **The last slide lists every source** (來源／參考資料與圖片來源), even
    though each slide already carries its own footnote.

## B. Speaker notes are the script

Every slide in all three decks has full notes, written as spoken Mandarin in
short lines, with `【按】` marking each click. Notes say what the slide shows,
then why it matters, then the transition. A deck without notes is not done.

## C. Visual language

1. **Everything is a native, editable shape.** Grids of numbers are
   rectangles, dots are ovals, charts are bars; nothing is a screenshot of a
   diagram the teacher could not edit. Photos and paper figures are the only
   raster images.
2. **Typography:** Times New Roman for Latin and digits, 標楷體 (DFKai-SB) for
   CJK. Title 26–28 pt; body 15–18 pt; captions 10–13 pt; stat numbers 30 pt.
3. **Colour is semantic, not decorative.** Four accent tones, each used for
   one meaning across the whole deck:
   - `positive` (green): correct, survived, the good outcome
   - `alert` (rust / crimson): the emphasis, the error, the thing to notice
   - `info` (navy / blue): neutral structure, headers, "the other class"
   - `highlight` (ochre / purple): formula bands, the answer column
   Each tone has a pale tint used as a card fill. Body text stays near-black;
   secondary text uses the muted grey-brown.
4. **Cards:** rounded rectangles with a soft shadow, either white with a
   coloured border (a choice or an outcome) or tint-filled (a group).
5. **Chrome** on every content slide (both week-06 decks): title top-left; section chips top-right;
   source footnote bottom-left in 9 pt; `n / N` bottom-right.
6. **Sources go in the footer, not the body.** Dataset, paper, image licence
   ("照片：…, Public domain（Wikimedia Commons）"), and "本課實際計算".
7. **Two page treatments:**
   - `warm-paper`: cream page `#FFF8EC`, plain title, earthy accents.
   - `navy-academic`: white page, a navy bar left of the title, crimson
     emphasis, cool grey panels.

## D. What to avoid

- Bullet-only slides. If a slide is only bullets, turn it into cards, a flow,
  or a compare.
- Decorative icons or stock imagery that carry no information.
- More than one emphasis colour in a sentence.
- A number without a unit, a source, or a label saying what it counts.
- A formula without the plain-language reading next to it.
