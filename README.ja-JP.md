# research-lab-skills

[![Version](https://img.shields.io/badge/version-v1.1.0-blue)](https://github.com/zi-yue-1129/research-lab-skills/releases/tag/v1.1.0)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/license-CC%20BY--NC%204.0-lightgrey)](https://creativecommons.org/licenses/by-nc/4.0/)
[![GitHub](https://img.shields.io/badge/GitHub-zi--yue--1129-black?logo=github)](https://github.com/zi-yue-1129/research-lab-skills)

[English](README.md) | [简体中文版](README.zh-CN.md) | [繁體中文版](README.zh-TW.md)

> 日々の実験ノートから学術論文の発表まで——研究プロセス全体をサポートする Claude Code スキル統合スイートです。

---

## このツールの目的

research-lab-skills は Claude Code 向けの**統合研究環境**で、2 つの要素を組み合わせています：

- **学術研究スキル（ARS）**（`deep-research`、`academic-paper`、`academic-paper-reviewer`、`academic-pipeline`）—— 13/12/7/10 エージェント構成の文献レビュー、論文執筆、ピアレビュー、パイプラインオーケストレーションのフレームワーク。これは**呉政宜（Cheng-I Wu）氏による上流の作品**（[`Imbad0202/academic-research-skills`](https://github.com/Imbad0202/academic-research-skills)、CC BY-NC 4.0）であり、本プロジェクトはこれをほぼそのまま取り込んで使用しています。
- **私が開発した Lab ワークフローとインフラ**（`research-log`、`report-slides`、`research-mode`、および両方のツールセットをインストール・連携動作させるための `resource-resolver`／`agent-state`／`research-project-init`、パッケージング／インストール層）—— 実験ジャーナル、進捗スライド生成、セッションモードルーティング、そして両ツールセットが統合される前には存在しなかった共有状態／リゾルバー基盤。

ARS のエージェントパイプラインは私が書いたものではありません。私が作ったのはその周りの日常研究レイヤーと、両者を1つのスイートとして統合するエンジニアリングです。パスレベルでの正確な帰属の内訳は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を、各スキルの詳細は以下のセクションを参照してください。

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

### curl / PowerShell（推奨）

**macOS / Linux / Git Bash / WSL：**

```bash
# 全スキル（グローバル）
curl -fsSL https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.sh | bash

# プロジェクトローカル
curl -fsSL https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.sh | bash -s -- --local

# ARSスキルのみ
curl -fsSL https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.sh | bash -s -- --ars-only

# Labスキルのみ
curl -fsSL https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.sh | bash -s -- --lab-only

# アンインストール
curl -fsSL https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.sh | bash -s -- uninstall
```

**Windows（PowerShell）** — Git BashやWSLは不要、ネイティブに動作します：

```powershell
# 全スキル（グローバル）
irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1 | iex

# フラグを渡す場合はパイプではなくスクリプト本体を取得してから実行する必要があるため、scriptblockで包みます：
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1))) -Local
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1))) -ArsOnly
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1))) -LabOnly
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1))) -Uninstall
```

**Windows（cmd.exe）：**

```bat
powershell -Command "irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1 | iex"
```

**上記コマンドがウイルス対策ソフト / EDR にブロックされる場合：** 一部のセキュリティソフトは、内容に関わらず `irm | iex`（ダウンロードして即実行）というコマンドパターン自体を検知してブロックします — 下記の[git clone](#git-clone)方式ならこの問題を完全に回避できます。

### git clone

macOS、Linux、Windows で同じ手順が使え、一部のウイルス対策/EDRソフトがブロックする `curl | bash` / `irm | iex`（ダウンロードして即実行）というコマンドパターンも回避できます：

```bash
git clone --depth 1 https://github.com/zi-yue-1129/research-lab-skills.git
cd research-lab-skills
```

**macOS / Linux / Git Bash / WSL：**

```bash
bash install.sh                # 全スキル（グローバル）
bash install.sh --local        # プロジェクトローカル
bash install.sh --ars-only     # ARSスキルのみ
bash install.sh --lab-only     # Labスキルのみ
bash install.sh uninstall      # アンインストール
```

**Windows（PowerShell）：**

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1                # 全スキル（グローバル）
powershell -ExecutionPolicy Bypass -File install.ps1 -Local          # プロジェクトローカル
powershell -ExecutionPolicy Bypass -File install.ps1 -ArsOnly        # ARSスキルのみ
powershell -ExecutionPolicy Bypass -File install.ps1 -LabOnly        # Labスキルのみ
powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall      # アンインストール
```

インストール後に Claude Code を再起動してください。詳細は [docs/SETUP.md](docs/SETUP.md) を参照してください。

> **注記：** 本プロジェクトは以前 npm パッケージ（`crs` CLI）を提供していました。現在 npm はサポートされたインストール方法として維持されていません。上記の curl／PowerShell／git clone をご利用ください。CLI ソースはリポジトリの `bin/crs.js` に参考として残されています。

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

- **Lab スキルと統合インフラ**（`research-log`、`report-slides`、`research-mode`、`resource-resolver`、`agent-state`、`research-project-init`、パッケージング／インストール層）— [ZI-YUE,CHAO](https://github.com/zi-yue-1129) によるオリジナル作品（CC BY-NC 4.0）
- **学術研究スキル**（`deep-research`、`academic-paper`、`academic-paper-reviewer`、`academic-pipeline`、および対応する `agents/`、`shared/`、`commands/`、`hooks/`）— 上流のオリジナル作品 [Cheng-I Wu（Imbad0202）](https://github.com/Imbad0202)（CC BY-NC 4.0）

詳細は [LICENSE](LICENSE)、[NOTICE.md](NOTICE.md)、パスごとの内訳は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) を参照してください。

日本語 README 翻訳：[eltociear](https://github.com/eltociear)（Ikko Eltociear Ashimine）
