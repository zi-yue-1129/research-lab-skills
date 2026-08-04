# research-lab-skills

[![npm](https://img.shields.io/npm/v/research-lab-skills)](https://www.npmjs.com/package/research-lab-skills)
[![Version](https://img.shields.io/badge/version-v1.1.0-blue)](https://github.com/starpig1129/research-lab-skills/releases/tag/v1.1.0)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/license-CC%20BY--NC%204.0-lightgrey)](https://creativecommons.org/licenses/by-nc/4.0/)
[![GitHub](https://img.shields.io/badge/GitHub-starpig1129-black?logo=github)](https://github.com/starpig1129/research-lab-skills)

[English](README.md) | [简体中文版](README.zh-CN.md) | [繁體中文版](README.zh-TW.md)

> 日々の実験ノートから学術論文の発表まで——研究プロセス全体をサポートする Claude Code スキル統合スイートです。

---

## このツールの目的

私は research-lab-skills を、学術研究の全ライフサイクルをカバーする Claude Code スキルスイートとして開発しました——日々の実験ジャーナルや進捗スライドから、系統的文献レビュー、論文執筆、ピアレビューシミュレーションまで。2つの互いに補完するツールセットを統合しています：

- **Lab スキル**（`research-log`、`report-slides`、`research-mode`）—— 実験ジャーナル、進捗スライド、セッションモードルーティング
- **学術研究スキル（ARS）**（`deep-research`、`academic-paper`、`academic-paper-reviewer`、`academic-pipeline`）—— 文献レビュー、論文執筆、ピアレビュー、フルパイプライン

各スキルの詳細は下のセクションを参照してください。

## なぜ必要なのか

研究室は毎週、進捗報告のスライド作成に膨大な時間を費やしています。問題はスライドのデザインではありません——ほとんどのプレゼンテーションツールはそこが得意です。問題は、**今週のスライドに何を入れるべきか**がわからないことです。結局、空白のスライドを前に、今週自分が何をしたのかを思い出そうとする羽目になります。

これが私がまず研究ジャーナルの仕組みを開発した理由です。構造化されたフォーマットで実験を記録すれば、AIは今週何を実行し、何が失敗し、数字がどうなっているか、何を伝える必要があるかをすでに把握しています。スライドはその記録の自然な出力であり、研究の上にさらに乗っかる別のタスクではありません。

同じ問題はもっと深いところにも存在します。研究の日常プロセス——うまくいかなかった実験、アーキテクチャの変更、実験の合間に下した判断——は、論文が完成するずっと前に消えてしまいます。方法論を書く頃には、当時何をして、なぜそうしたのかを記憶から再構築しています。正式な学術アウトプットのプロセスはまた一からスタートし、実際にインサイトを生んだ数ヶ月の作業とは切り離されています。

このスイートはその糸を繋ぎ止めます。ジャーナルがすべての意思決定の「なぜ」を記録し、ラボミーティングのスライドはそのジャーナルから生成され、論文の方法論セクションもそのジャーナルから来ます。セッションモード（`exp` → `explore` → `publish`）は研究サイクルのどのフェーズにいるかを追跡し、適切なツールへと自動的に誘導します。

実験台から参考文献リストまで、すべてのステップに記録が残ります。

---

## スキル一覧

| スキル | コマンド | 機能 |
|--------|----------|------|
| `research-log` | `/research-log` | 実験ジャーナル（追加・修正・インデックス） |
| `report-slides` | `/report-slides` | ジャーナルから SVG + PPTX 進捗スライドを自動生成 |
| `research-mode` | `/mode` | セッションモードルーティング（exp / daily / explore / report / publish） |
| `deep-research` | `/ars-full`, `/ars-lit-review`, … | 13エージェント研究チーム（Socratic / PRISMA / ファクトチェック） |
| `academic-paper` | `/ars-plan`, `/ars-outline`, … | 12エージェント論文執筆、引用検証付き |
| `academic-paper-reviewer` | `/ars-review`, `/ars-re-review` | 多視点ピアレビュー（EIC + レビュアー×3 + DA） |
| `academic-pipeline` | `/ars-pipeline` | 10ステージ完全パイプラインオーケストレーター |

---

## 研究ライフサイクル全体

**フェーズ1 — 日々の実験**（`/mode exp`）

```bash
/mode exp                        # 実験セッションを開始
/research-log add                # 今日の実験を記録（quick 3問 / full 9セクション）
/report-slides                   # 今週のジャーナルを SVG + PPTX スライドに変換
/mode end                        # git diff からドラフトを自動生成
```

ジャーナルの `follows:` フィールドが実験をトレース可能なタイムラインに繋ぎます。`amended:` は事後修正を記録し、`slide_decks:` はスライド生成時に自動更新されます。各実験の*目標*・*結果*・*失敗*の記録は、論文執筆時の方法論セクションと考察セクションの素材になります。

**フェーズ2 — 文献探索**（`/mode explore`）

```bash
/mode explore
/ars-lit-review "あなたのトピック"   # 13エージェント文献レビュー（PRISMA対応）
/ars-socratic                        # ソクラテス式対話で研究課題を明確化
/mode end                            # 探索記録を整理し、RQと主要発見を抽出
```

**フェーズ3 — 論文執筆と発表**（`/mode publish`）

```bash
/mode publish
/ars-plan                        # ソクラテス式ガイドによる章構成計画
/ars-full                        # 12エージェント論文執筆 + 引用検証
/ars-review                      # 多視点ピアレビュー
/ars-re-review                   # 修正後の受理確認
/ars-pipeline                    # 完全10ステージパイプライン（整合性ゲート付き）
```

**ジャーナルが論文に繋がる方法**

| ジャーナルフィールド | 論文のセクション |
|---------------------|----------------|
| `Goal` + `Setup` | 方法論 |
| `Results` + `Charts` | 結果と図表 |
| `Failures` + `Analysis` | 考察 / 限界 |
| `slide_decks:` リンク | 図表の素材 |
| `follows:` タイムライン | 研究設計の変遷説明 |

→ **[examples/](examples/)** で完全なサンプルを確認：3つの実験ジャーナル、7枚の SVG 進捗スライド（編集可能な PPTX 付き）。

---

## インストール

### curl / PowerShell（推奨、npmアカウント不要）

**macOS / Linux / Git Bash / WSL：**

```bash
# 全スキル（グローバル）
curl -fsSL https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.sh | bash

# プロジェクトローカル
curl -fsSL https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.sh | bash -s -- --local

# ARSスキルのみ
curl -fsSL https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.sh | bash -s -- --ars-only

# Labスキルのみ
curl -fsSL https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.sh | bash -s -- --lab-only

# アンインストール
curl -fsSL https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.sh | bash -s -- uninstall
```

**Windows（PowerShell）** — Git BashやWSLは不要、ネイティブに動作します：

```powershell
# 全スキル（グローバル）
irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1 | iex

# フラグを渡す場合はパイプではなくスクリプト本体を取得してから実行する必要があるため、scriptblockで包みます：
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1))) -Local
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1))) -ArsOnly
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1))) -LabOnly
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1))) -Uninstall
```

**Windows（cmd.exe）** — PowerShellコマンドでラップします：

```bat
powershell -Command "irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1 | iex"
```

`install.sh` と `install.ps1` はどちらも `PATH` 上に `git` があれば動作し、npmアカウントやログインは不要です。

### npm

```bash
npm install -g research-lab-skills
crs init --global          # 全7スキルをグローバルインストール
```

npxで一回限りの実行（npmグローバルインストール不要）：

```bash
npx research-lab-skills init --global
```

**オプション：**

| フラグ | インストール内容 |
|--------|----------------|
| （なし）| 全7スキル（プロジェクトローカル `.claude/skills/`） |
| `--global` | 全7スキル（グローバル `~/.claude/skills/`） |
| `--lab-only` | `research-log`、`report-slides`、`research-mode` |
| `--ars-only` | `deep-research`、`academic-paper`、`academic-paper-reviewer`、`academic-pipeline` |
| `--ai cursor` | Claude CodeではなくCursorにインストール |

```bash
crs update --global        # npmアップグレード後に再インストール
crs uninstall --global     # スキルを削除
```

インストール後に Claude Code を再起動してください。詳細は [docs/SETUP.md](docs/SETUP.md) を参照してください。

---

## Lab スキル

### `/research-log` — 実験ジャーナル

**実験ジャーナルはメモではなく、研究プロセスの記憶装置です。**

実験には３つの結末があります：成功、失敗、「成功だが期待通りではない」。日誌はこの３つすべてを保存し、将来「なぜ X を試さなかったのか」という問いに答えられるようにします。

| コマンド | 説明 |
|---------|------|
| `/research-log add` | 新しいエントリを追加（quick 3問 / full 9セクション） |
| `/research-log amend` | 既存エントリのセクションを修正 |
| `/research-log index` | `docs/research_log/INDEX.md` を frontmatter から再構築 |
| `/research-log show [n]` | 最近 n 件のサマリーを表示（デフォルト 5） |
| `/research-log query` | セクションと日付で履歴を検索し、安全なトークン予算内で選択結果を取得 |

`/mode` を有効にしていなくても、Agent は新しい実験の開始、異常の診断、パラメータ変更、または高コストな再実行の前に、関連する履歴を自発的に確認します。

---

### `/report-slides` — 進捗スライドジェネレーター

ジャーナルエントリを読み込み、スライドのアウトラインを提示して確認後、3つのレンダリングパスでスライドを生成します：

- **[A] Python スクリプト** — データ駆動：棒グラフ、テーブル、メトリクスカード、タイムライン
- **[B] Mermaid** — フローチャート、アーキテクチャ図、状態機械
- **[C] Claude SVG** — 自由レイアウトの概念図、テキスト重視のコンテンツ

**出力形式：**
- 編集可能な SVG ソースファイル
- **`deck.pptx` — 16:9 PPTX、ネイティブ SVG 埋め込み、PowerPoint/Keynote で全要素を直接編集可能**
- `slide_data.json` — Path A のデータソース

---

### `/mode` — ワークモード

| モード | 主要スキル | 使用タイミング |
|--------|----------|--------------|
| `exp` | `research-log`（Full モード）| 実験中、セッション終了時に自動記録したい |
| `daily` | なし（自由形式）| 軽いメモ、読書 |
| `explore` | `deep-research` | 文献探索 |
| `report` | `report-slides` | 進捗スライドの生成 |
| `publish` | `academic-pipeline` | 論文執筆と投稿 |

---

## 学術研究スキル（ARS）

> **AI はあなたの副操縦士であり、操縦士ではありません。** このツールはあなたの代わりに論文を書きません。本当に頭を使う必要のある部分に集中できるよう、泥臭い作業を引き受けます。

**👉 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** · **👉 [docs/SETUP.md](docs/SETUP.md)** · **👉 [docs/PERFORMANCE.md](docs/PERFORMANCE.md)**

- **Deep Research** — 13エージェント研究チーム。ソクラテス式ガイド、PRISMA系統的レビュー、4索引引用検証。
- **Academic Paper** — 12エージェント論文執筆。スタイルキャリブレーション、3層引用アンカー、LaTeX強化。
- **Academic Paper Reviewer** — 7エージェント多視点レビュー。EIC + 動的レビュアー×3 + 悪魔の代弁者。
- **Academic Pipeline** — 10ステージエンドツーエンドオーケストレーター。整合性ゲート、マテリアルパスポート。

---

## ライセンスとクレジット

本プロジェクトは [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) の下でライセンスされています。

- **Lab スキル** — [ZI-YUE,CHAO](https://github.com/starpig1129)（CC BY-NC 4.0）
- **学術研究スキル** — 原作者 [Cheng-I Wu（Imbad0202）](https://github.com/Imbad0202)（CC BY-NC 4.0）

[LICENSE](LICENSE) と [NOTICE.md](NOTICE.md) を参照してください。

日本語 README 翻訳：[eltociear](https://github.com/eltociear)（Ikko Eltociear Ashimine）
