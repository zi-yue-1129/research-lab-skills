# research-lab-skills

[![Version](https://img.shields.io/badge/version-v1.1.0-blue)](https://github.com/zi-yue-1129/research-lab-skills/releases/tag/v1.1.0)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/license-CC%20BY--NC%204.0-lightgrey)](https://creativecommons.org/licenses/by-nc/4.0/)
[![GitHub](https://img.shields.io/badge/GitHub-zi--yue--1129-black?logo=github)](https://github.com/zi-yue-1129/research-lab-skills)

[English](README.md) | [繁體中文版](README.zh-TW.md) | [日本語版](README.ja-JP.md)

> **研究不该每开一次 AI 对话就归零。**

---

## 这是用来做什么

research-lab-skills 是**状态化的研究工作流基础设施**，把实验、失败、决策、证据跨工作阶段连接起来。以 [Agent Skills](https://agentskills.io/specification) 格式构建；Claude Code 是目前已验证的参考客户端，其他 Agent Skills 客户端的兼容性尚未验证。它结合了两个部分：

- **学术研究技能（ARS）**（`deep-research`、`academic-paper`、`academic-paper-reviewer`、`academic-pipeline`）—— 13/12/7/10-agent 的文献回顾、论文撰写、同行评审与全流程 pipeline 框架。这是**吴政宜（Cheng-I Wu）的上游作品**（[`Imbad0202/academic-research-skills`](https://github.com/Imbad0202/academic-research-skills)，CC BY-NC 4.0），本项目将其导入并大致沿用原样。
- **我开发的 Lab 工作流程与基础设施**（`research-log`、`report-slides`、`research-mode`，以及让两套工具能安装并协同运作的 `resource-resolver`／`agent-state`／`research-project-init` 与整合封装层）—— 实验日志、进度幻灯片生成、工作模式路由，以及两套工具合并前都不存在的共用状态／resolver 基础设施。

ARS 的 agent pipeline 不是我写的。我做的是围绕它的日常研究层，以及让两者合成一套工具的整合工程。精确到路径层级的归属拆解见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，各技能的详细说明见下方章节。

## 为什么需要它

研究室每周要花大量时间制作报告幻灯片。问题不在于幻灯片好不好看——大多数演示工具都能做出漂亮的版面。问题是它们完全不知道**这周的幻灯片应该放什么**。你最后对着空白的演示，努力回想自己这周到底做了什么。

这就是我先开发研究日志机制的原因。当你用结构化格式记录实验，AI 就已经知道这周跑了什么、失败了什么、数字长什么样、有哪些需要沟通的内容。幻灯片是那份记录的自然输出，而不是研究之外另一件要做的事。

同样的问题在更深的地方也存在。研究的日常过程——失败的实验、架构调整、两次跑结果之间的决定——往往在论文完成之前就消失了。等到要写方法论的时候，你已经在靠记忆重建自己当初做了什么、为什么这样做。正式的学术产出流程又往往从头开始，与那几个月实际产生洞察的过程完全脱节。

这套工具让那条线不断。你的日志记录每个决策背后的「为什么」；lab meeting 的幻灯片从那份日志来；论文的方法论章节也从那份日志来。工作模式（`exp` → `explore` → `publish`）追踪你在研究周期的哪个阶段，自动引导你到正确的工具。

从实验台到参考文献，每一步都有迹可循。

---

## 技能总览

| 技能 | 指令 | 功能 |
|------|------|------|
| `research-log` | `/research-log` | 结构化实验日志（新增、修订、索引） |
| `report-slides` | `/report-slides` | 从日志自动生成 SVG + PPTX 进度幻灯片 |
| `research-mode` | `/mode` | 工作模式路由（exp / daily / explore / report / publish） |
| `deep-research` | `/ars-full`, `/ars-lit-review`, … | 13 个 Agent 研究团队，Socratic / PRISMA / fact-check |
| `academic-paper` | `/ars-plan`, `/ars-outline`, … | 12 个 Agent 论文撰写，含引用验证 |
| `academic-paper-reviewer` | `/ars-review`, `/ars-re-review` | 多视角同行评审（主编 + 3 位审查者 + DA） |
| `academic-pipeline` | `/ars-pipeline` | 完整 10 阶段 pipeline 协调器 |

---

## 完整研究历程

**第一阶段 — 每日实验期**（`/mode exp`）

```bash
/mode exp                        # 启动实验模式
/research-log add                # 记录今天的实验（quick 3 问、full 9 节）
/report-slides                   # 将本周日志转成 SVG + PPTX 进度幻灯片
/mode end                        # 结束时从 git diff 自动起草下次记录
```

日志的 `follows:` 字段把实验串成可追溯的时间线；`amended:` 记录事后的修正；`slide_decks:` 在生成幻灯片后自动更新。每次实验的*目标*、*结果*、*失败*都被保存，等到写论文的时候，方法论和讨论章节的素材自然就在那里了。

**第二阶段 — 文献探索期**（`/mode explore`）

```bash
/mode explore
/ars-lit-review "你的主题"       # 13 个 Agent 文献回顾，含 PRISMA 支持
/ars-socratic                    # 苏格拉底对话，澄清研究问题
/mode end                        # 整理探索记录，提取 RQ 与关键发现
```

**第三阶段 — 论文撰写与发表期**（`/mode publish`）

```bash
/mode publish
/ars-plan                        # 苏格拉底引导规划章节结构
/ars-full                        # 12 个 Agent 撰写完整论文 + 引用验证
/ars-review                      # 多视角同行评审
/ars-re-review                   # 修订后验收
/ars-pipeline                    # 完整 10 阶段 pipeline（含诚信查验）
```

**日志如何连接到论文**

| 日志字段 | 论文对应 |
|---------|---------|
| `Goal` + `Setup` | 方法论 |
| `Results` + `Charts` | 结果与图表 |
| `Failures` + `Analysis` | 讨论 / 局限性 |
| `slide_decks:` 链接 | 图表素材 |
| `follows:` 时间链 | 研究设计演进说明 |

→ 查看 **[examples/](examples/)** 完整示例：三篇涵盖整个实验周期的日志、7 张 SVG 进度幻灯片（附可编辑 PPTX）。

---

## 安装

### curl / PowerShell（推荐）

**macOS / Linux / Git Bash / WSL：**

```bash
# 全部技能（全局）
curl -fsSL https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.sh | bash

# 项目本地
curl -fsSL https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.sh | bash -s -- --local

# 只安装 ARS 技能
curl -fsSL https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.sh | bash -s -- --ars-only

# 只安装 Lab 技能
curl -fsSL https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.sh | bash -s -- --lab-only

# 卸载
curl -fsSL https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.sh | bash -s -- uninstall
```

**Windows（PowerShell）**——原生支持，不需要 Git Bash 或 WSL：

```powershell
# 全部技能（全局）
irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1 | iex

# 带标志时需要取得脚本内容再执行，不能直接用管道传给 iex，改用 scriptblock 包装：
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1))) -Local
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1))) -ArsOnly
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1))) -LabOnly
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1))) -Uninstall
```

**Windows（cmd.exe）：**

```bat
powershell -Command "irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1 | iex"
```

**如果杀毒软件 / EDR 拦截了上面这行：**有些安全软件会直接拦截 `irm | iex`（下载后立即执行）这种命令样式，不论实际内容是什么——见下方的[git clone](#git-clone)方式，完全避开这个问题。

### git clone

在 macOS、Linux、Windows 上做法一致，也能避开部分杀毒/EDR 软件会拦截的 `curl | bash` / `irm | iex`（下载后立即执行）命令样式：

```bash
git clone --depth 1 https://github.com/zi-yue-1129/research-lab-skills.git
cd research-lab-skills
```

**macOS / Linux / Git Bash / WSL：**

```bash
bash install.sh                # 全部技能（全局）
bash install.sh --local        # 项目本地
bash install.sh --ars-only     # 只安装 ARS 技能
bash install.sh --lab-only     # 只安装 Lab 技能
bash install.sh uninstall      # 卸载
```

**Windows（PowerShell）：**

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1                # 全部技能（全局）
powershell -ExecutionPolicy Bypass -File install.ps1 -Local          # 项目本地
powershell -ExecutionPolicy Bypass -File install.ps1 -ArsOnly        # 只安装 ARS 技能
powershell -ExecutionPolicy Bypass -File install.ps1 -LabOnly        # 只安装 Lab 技能
powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall      # 卸载
```

安装后重启 Claude Code。详细说明见 [docs/SETUP.md](docs/SETUP.md)。

> **说明：** 本项目此前曾提供 npm 包（`crs` CLI）。目前未将 npm 作为受支持的安装方式维护，请改用上方的 curl／PowerShell／git clone。CLI 源码仍保留在仓库的 `bin/crs.js`，仅供参考。

---

## Lab 技能

### `/research-log` — 实验日志

**实验日志不是备忘录，而是研究过程的记忆体。**

实验往往有三种结局：成功、失败、或「成功但不是预期中的方式」。日志让三种都被保存下来，让你未来能回答「为什么没试过 X」这个问题。

| 指令 | 说明 |
|------|------|
| `/research-log add` | 新增记录（quick 3 问引导、full 9 节完整格式） |
| `/research-log amend` | 修订现有记录的某个章节 |
| `/research-log index` | 从 frontmatter 重建 `docs/research_log/INDEX.md` |
| `/research-log show [n]` | 显示最近 n 条记录的摘要（默认 5） |
| `/research-log query` | 按章节与日期搜索历史，再在安全 token 预算内读取选定结果 |

即使没有启用 `/mode`，Agent 也会在开始新实验、诊断异常、调整参数或启动成本高昂的重跑前，主动查阅相关历史。

---

### `/report-slides` — 进度幻灯片生成器

读取日志记录，提出幻灯片大纲确认后，通过三种渲染路径生成幻灯片：

- **[A] Python 脚本** — 数据驱动：柱状图、表格、指标卡、时间线
- **[B] Mermaid** — 流程图、架构图、状态机
- **[C] Claude SVG** — 自由排版的概念图、文字密集的内容

**输出格式：**
- 可编辑 SVG 原始文件
- **`deck.pptx` — 16:9 PPTX，原生 SVG 嵌入，可在 PowerPoint/Keynote 中直接编辑所有元素**
- `slide_data.json` — Path A 的数据来源

---

### `/mode` — 工作模式

| 模式 | 主要技能 | 适用时机 |
|------|---------|---------|
| `exp` | `research-log`（Full 模式）| 跑实验，想在会话结尾自动记录 |
| `daily` | 无（自由模式） | 轻量笔记、阅读 |
| `explore` | `deep-research` | 文献探索 |
| `report` | `report-slides` | 生成进度幻灯片 |
| `publish` | `academic-pipeline` | 撰写与投稿论文 |

---

## 学术研究技能（ARS）

> **AI 是你的副驾驶，不是机长。** 这个工具不会替你写论文。它处理繁琐工作，让你专注在真正需要思考的事上。

**👉 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** · **👉 [docs/SETUP.md](docs/SETUP.md)** · **👉 [docs/PERFORMANCE.md](docs/PERFORMANCE.md)**

- **Deep Research** — 13 个 Agent 研究团队。苏格拉底引导、PRISMA 系统性回顾、四索引引用三角验证。
- **Academic Paper** — 12 个 Agent 论文撰写。风格校准、三层引用 anchor、LaTeX 强化、VLM 图表验证。
- **Academic Paper Reviewer** — 7 个 Agent 多视角审查。主编 + 3 位动态审查者 + 魔鬼代言人。
- **Academic Pipeline** — 10 阶段端到端协调器。Stage 2.5 + 4.5 诚信闸门、素材护照、引用存在性查验。

---

## 授权与来源

本项目采用 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) 授权。

- **Lab 技能与整合基础设施**（`research-log`、`report-slides`、`research-mode`、`resource-resolver`、`agent-state`、`research-project-init`、封装／安装层）— [ZI-YUE,CHAO](https://github.com/zi-yue-1129) 原创（CC BY-NC 4.0）
- **学术研究技能**（`deep-research`、`academic-paper`、`academic-paper-reviewer`、`academic-pipeline`，及其对应的 `agents/`、`shared/`、`commands/`、`hooks/`）— 上游原作 [Cheng-I Wu（Imbad0202）](https://github.com/Imbad0202)（CC BY-NC 4.0）

详见 [LICENSE](LICENSE)、[NOTICE.md](NOTICE.md)，以及逐路径拆解的 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
