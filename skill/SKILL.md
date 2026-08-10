---
name: research-report
description: >-
  Create research reports on open-source projects, technologies, or industry trends.
  Use when the user asks to research a GitHub project, technology, or topic and produce
  a structured report. Content is submitted to the ai-report platform
  (https://github.com/fatherplus/vicky) via POST /api/reports, choosing a
  template (book / brief / arch-overview / arch-node / card) and a domain
  (tech / ephemeral / design / arch) by content type. Visual style is governed by the
  platform's book-style design system (skill/BOOK-STYLE.md); the submission contract
  lives in skill/AGENT-GUIDE.md.
---

# Research Report — 统一研究平台

## 平台定位

`ai-report` 是一个**集中式研究报告管理平台**，包含：
- **五个模板**：`templates/` 注册制 — `book`（默认，“书”页长读：宋体标题 + 书眉 + 藏书章 + 书签丝带）、`brief`（结论先行决策简报）、`arch-overview` / `arch-node`（项目架构多页站，骑丛书机制）、`card`（产品风格卡片，聚合成卡片墙）；所有报告共享同一份 CSS
- **四类内容域**（`domain` 字段路由）：`tech` 技术文章（唯一进知识蒸馏）/ `ephemeral` 临时报告 / `design` 前端卡片（不蒸馏；卡片墙 `/design.html`，token 总纲 `GET /api/design`，CSS 资源包 `GET /api/design.css`）/ `arch` 架构站（不蒸馏）
- **提交契约**：`skill/AGENT-GUIDE.md`（即 `GET /api/guide`）— domain 路由表、四类工作流、截图规范、arch 丛书约定
- **风格规范**：`skill/BOOK-STYLE.md` — 书风格的硬约束（字体/配色/版式/动效/绝对禁止清单）
- **GitLab Pages**：`public/` 目录自动发布为静态站点
- **Skill**：本文件 — 定义报告生成的标准工作流

**仓库**：https://github.com/fatherplus/vicky
**在线浏览**：https://fatherplus.github.io/vicky/（GitLab Pages）

## ⭐ 第一原则：先讲「为什么」，再讲「是什么」

> **这是所有报告的最高优先级规则，凌驾于任何排版/风格之上。**
> 读者（尤其是领导）关心的从来不是你用了什么技术，而是：
> **这套东西能帮我解决什么问题？为什么比别的方案好？**
> 技术的「优势」= 方案与痛点之间的对应关系。不讲痛点，优势无从谈起。

### 黄金结构（技术方案 / 架构汇报必用）

| 顺序 | 章节 | 回答的问题 | 常见错误 |
|------|------|-----------|---------|
| 1 | **定位与边界** | 它是什么、不是什么 | 边界模糊，需求没对齐 |
| 2 | **场景与痛点** | 什么情况下遇到什么问题？不解决会怎样？ | ❌ 跳过，直接讲方案 |
| 3 | **为什么是这套方案** | 每个关键决策：解决哪个痛点？为何不选替代方案？ | ❌ 只说「我用了 X」，不说「为什么是 X」 |
| 4 | **方案与架构** | 整体怎么做 | ❌ 在 2、3 之前「硬甩架构图」 |
| 5 | **细节与验证** | 机制/数据/demo 证明真能解决 | 有机制无验证 |

**核心顺序不可颠倒**：先让读者认同「问题存在且值得解决」，再给答案。
读者脑子里先有了问题，看到你的方案才会「啊，原来是这么解决的」。

### 每个技术决策的三问（硬性约束）

写下任何一个组件 / 分层 / 选型之前，必须能回答这三问，否则不要写：

1. **它解决什么场景的什么问题？**（具体、可感知，不用技术黑话）
2. **为什么是这个方案，而不是替代方案？**（对比，说出取舍）
3. **不这么做会怎样？**（反证：现状之痛 / 替代方案之短）

> 一个技术点如果答不上这三问，要么它不该出现在方案里，
> 要么报告还没把铺垫做到位。

### 反模式（血泪教训，务必避免）

- ❌ **定位之后直接甩架构图**（「硬讲架构」）。
  读者不知道「为什么要这样分层」，get 不到优势。
  → *2026-07 GameKB 方案汇报：领导反馈「只写了方案和技术，没写技术的原因和解决的场景，理解不了这套技术的优势」。*
- ❌ **通篇技术名词，没有业务场景**。领导不是来学技术的，是来判断价值的。
- ❌ **讲「我做了什么」，不讲「这解决了什么」**。主语错了。
- ❌ **场景痛点写成一句话带过**。痛点要具体到「谁、在什么情况、遇到什么、损失什么」。

### 两种文体的区别

| | 研究报告（介绍已有技术） | 技术方案 / 架构汇报（提出待建系统） |
|---|---|---|
| 目的 | 让读者**理解**一个技术 | 让读者**认同并批准**一个方案 |
| 场景的作用 | 「场景演练」辅助理解机制 | 「场景与痛点」是论证的**起点**，必须前置 |
| 关键章节 | 核心机制 + 场景演练 + 竞品对比 | 场景痛点 + 为什么是这套方案 + 架构 |
| 读者心态 | 「这东西怎么运作？」 | 「我该不该投入做这个？」 |

> 写之前先判断文体。**技术方案汇报，第 2、3 节（场景痛点、为什么）缺失 = 不及格。**

## Trigger

User asks to research a GitHub project, open-source tool, technology, or industry trend and produce a written report — especially when they say "出一篇研究报告" or "write a research report."

## Workflow

### 1. Gather Sources

- **GitHub**: `web_extract` the repo README for stats, install instructions, architecture
- **Community**: `web_extract` Hacker News, dev.to, Reddit for discussion and critique
- **Chinese coverage**: `web_search` with Chinese keywords (知乎, 微信公众号) for local perspective
- **Benchmarks/Data**: if the project has benchmarks, extract the raw results page

### 2. Check Existing Reports

Avoid duplicating work:
- `search_files` in `ai-report/public/reports/` for `*.html`
- If a report on the same topic exists, cross-reference. Link to it from the new report.

### 3. Choose Template & Domain

不手写整页 HTML——只写正文内容，`POST /api/reports` 时平台套模板、生成 .md 孪生、L0 存档。模板目录：`GET /api/templates`（或读 `templates/{name}/manifest.json`）。

| 内容 | domain | template | slug 约定 |
|---|---|---|---|
| 技术文章（默认） | `tech` | `book` | 主题 slug |
| 决策简报 | `tech` / `ephemeral` | `brief` | 主题 slug |
| 临时报告（给人/领导看，不蒸馏） | `ephemeral` | `book` / `brief` | 主题 slug |
| 产品风格卡片 | `design` | `card` | `card-{product}` |
| 架构总览卷 | `arch` | `arch-overview` | `{project}-arch-overview`（series `{project}-arch`，order=1） |
| 架构节点卷 | `arch` | `arch-node` | `{project}-arch-{module}`（同 series，order=2..n，三段 h2 硬契约） |

模板框架由平台用占位符填充（`{{TITLE}}` `{{SUBTITLE}}` `{{HERO_TAG}}` `{{DATE}}` `{{META}}` `{{CONTENT}}` `{{COMPONENT_HEAD}}` `{{SERIES_BADGE}}` `{{VOLUME_NAV}}`），agent 不碰。四类工作流、截图规范（视口 1440×900 / 默认抓主页 / PNG / 走 `images` 字段）、arch 节点卷「输入与输出 → 内部工作流 → 架构方案」三段契约与 mermaid click 跳转写法，全部见 `skill/AGENT-GUIDE.md`。

### 4. Write the Report

**命名**：只给 `slug`（英文小写连字符），平台自动加日期前缀生成 `public/reports/YYYY-MM-DD-slug.html` + `.md` 孪生

**Design conventions** (book style — full spec in `skill/BOOK-STYLE.md`):
- 模板是一页“书”：书眉（running head）+ 书签丝带（滚动进度）+ 章节开头（带藏书章）+ 720px 正文栏 + 页脚
- 字体：宋体标题 `Noto Serif SC` + 黑体正文 `Noto Sans SC` + 等宽元信息 `JetBrains Mono`
- 配色：纸 `#FBFAF7` / 墨 `#23272E` / 主色 `#0C4A6E` / 朱砂印章 `#A63A2E`（只用于小面积）
- 组件（10 个标准）：`.card` 卡片、`.data-table` 数据表（只摆数据）、`.cmp-table`+`.cmp-verdict` 对比表（必须有结论）、`.figure` 图（图表/趋势/截图装裱，必有图题+图注）、`blockquote` 引用、`.callout.note/.warn` 强调框、`pre` 代码、`.tag` 标签、`.steps` 步骤
- 表述规范（`skill/EXPRESSION-GRAMMAR.md`）：先判定表述类型再选组件；裸 `<table>` 和无结论对比表会被 server 拒收
- 章节：`<section class="reveal">` + `.section-label`（等宽小字）+ `h2`（宋体）
- 动效：克制的滚动进入 + 书签进度条，尊重 `prefers-reduced-motion`
- ⚠️ 硬约束：写之前读 BOOK-STYLE.md，对照其“绝对禁止”清单自查，违反即返工

**Content structure** — 先判断文档类型，套用 `AGENT-GUIDE.md` 的对应骨架（技术研究 / 技术方案 / 数据分析）。技术研究类的典型章节：
1. 项目概述 — what it is, core stats, key metrics
2. 核心机制 — how it works
3. **场景演练**（必选）— ⚠️ 对技术/算法类主题这是最重要的章节。用小规模数据集逐步演示，带实际数字计算。加类比。结尾对比暴力搜索 vs 该算法的计算量。用户反馈："没有一个具体的例子和场景，我还是无法理解他的方式"
4. 实战效果 / Before-After — concrete examples
5. 数据验证 — benchmarks, performance data
6. 生态兼容 — supported platforms, integrations
7. 技术细节 — implementation details
8. 社区反响 — HN/Reddit discussion
9. 局限性 / 批判性分析 — hard questions
10. 竞品对比 — alternative projects comparison
11. 总结与建议 — verdict, recommendations

### 5. Deploy

> **平台自动完成渲染与索引**：agent 只需 `POST /api/reports` 提交内容；server 自动写入 `public/reports/`、生成 .md 孪生、重建 `public/index.html`。部署是运维动作，agent 通常不需要手动执行。

**Step A — 部署到内部环境**（运维用，非 agent 必需）:
```bash
bash scripts/deploy.sh       # 个人环境 (192.168.1.100)
bash scripts/deploy-xlab.sh  # xlab-test 公用环境
```

部署脚本通过 rsync 同步代码到远端，排除 `data/`（保留远端快照与 DB）。远端 systemd 服务以 `python3 -m ai_report.web` 启动，Nginx 纯反向代理到 app 端口。

**Step B — Git commit and push** (triggers GitLab Pages):
```bash
cd /home/deploy/ai-report
git add public/
git commit -m "docs: add report YYYY-MM-DD-slug"
git push origin main
```

### 6. Present Summary

Give the user:
- Local access URL: `http://192.168.1.100:9093/reports/YYYY-MM-DD-slug.html`
- GitLab Pages URL (after CI): `https://fatherplus.github.io/vicky/reports/YYYY-MM-DD-slug.html`
- Concise bullet-point summary of key findings

## Pitfalls

- **Don't skip the critique section**: every project has limitations.
- **Don't fabricate data**: if a benchmark can't be found, say so.
- **Include concrete examples**: for technical topics, always include a hands-on scenario with concrete data, step-by-step walkthrough, and analogy. User said "没有一个具体的例子和场景，我还是无法理解他的方式".
- **Template is canonical**: pick a registered template under `templates/` via `GET /api/templates` (default `book`; arch/card content uses its own registered template). Do not copy-paste CSS from old reports.
- **Chinese content**: use Chinese for all body text; keep code/commands/technical terms in English.
- **Nginx permissions**: `sudo cp` + `sudo chmod 644` required.
- **GitLab Pages**: `public/` is the Pages root. Reports go in `public/reports/`. Index is `public/index.html`.
- **Git clone with PAT**: `https://oauth2:glpat-REVOKED@github.com/fatherplus/vicky.git`