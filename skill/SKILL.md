---
name: research-report
description: >-
  Create research reports on open-source projects, technologies, or industry trends.
  Use when the user asks to research a GitHub project, technology, or topic and produce
  a structured report. All reports use the unified Apple-style template from the
  ai-report platform (https://github.com/fatherplus/vicky).
---

# Research Report — 统一研究平台

## 平台定位

`ai-report` 是一个**集中式研究报告管理平台**，包含：
- **统一模板**：`template/report.html` — Apple-style 设计，所有报告共享同一份 CSS
- **GitLab Pages**：`public/` 目录自动发布为静态站点
- **Skill**：本文件 — 定义报告生成的标准工作流

**仓库**：https://github.com/fatherplus/vicky
**在线浏览**：https://fatherplus.github.io/vicky/（GitLab Pages）

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

### 3. Load Template

Read the canonical template:
```bash
# Template is in the ai-report repo
read_file /home/deploy/ai-report/template/report.html
```

The template uses `{{PLACEHOLDER}}` markers:
- `{{TITLE}}` — report title
- `{{SUBTITLE}}` — one-line subtitle
- `{{HERO_TAG}}` — small tag above title (e.g. "向量检索", "开源研究")
- `{{DATE}}` — YYYY-MM-DD
- `{{AUTHOR}}` — "Hermes Agent"
- `{{CONTENT}}` — the body: `<section>...</section>` blocks

### 4. Write the Report

**File naming**: `public/reports/YYYY-MM-DD-slug.html`

**Design conventions** (from template):
- Hero section with tag, title, subtitle, date
- Sections: `<section>...</section>`, separated by `border-top: 1px solid #f0f0f0`
- Section labels: `<div class="section-label">LABEL</div>` — uppercase, #0C4A6E
- Card grids: `<div class="card-grid">` or `three-col` / `four-col`
- Cards: `border-radius: 18px`, subtle shadow, no borders
- `highlight` cards: gradient background
- `data-table` for comparison data
- `quote-block` for notable quotes
- `concern-box` (amber) for warnings/caveats
- `code-block` with dark background (#1d1d1f)
- `ladder-list` / `ladder-rung` for step-by-step
- `phase-list` / `phase` for numbered phases
- Responsive: single column on mobile

**Content structure** (tailor to the topic, but typical sections):
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

**Step A — Local Nginx** (for internal preview):
```bash
sudo cp /home/deploy/ai-report/public/reports/YYYY-MM-DD-slug.html /var/www/vicky/research/YYYY-MM-DD-slug.html
sudo chmod 644 /var/www/vicky/research/YYYY-MM-DD-slug.html
```

**Step B — Update Index Page**:
```bash
# Rebuild index from public/reports/
ls -1t /home/deploy/ai-report/public/reports/*.html | while read f; do
  name=$(basename "$f")
  title=$(grep -oP '<title>\K[^<]+' "$f" 2>/dev/null | head -1)
  [ -z "$title" ] && title="$name"
  date=$(echo "$name" | grep -oP '^\d{4}-\d{2}-\d{2}')
  echo "$date|$name|$title"
done | sort -r -t'|' -k1
```

Then write the index to `public/index.html` and sync to Nginx:
```bash
sudo cp /home/deploy/ai-report/public/index.html /var/www/vicky/research/index.html
```

**Step C — Git commit and push** (triggers GitLab Pages):
```bash
cd /home/deploy/ai-report
git add public/
git commit -m "docs: add report YYYY-MM-DD-slug"
git push origin main
```

### 6. Present Summary

Give the user:
- Local access URL: `http://192.168.1.100:9090/research/YYYY-MM-DD-slug.html`
- GitLab Pages URL (after CI): `https://fatherplus.github.io/vicky/reports/YYYY-MM-DD-slug.html`
- Concise bullet-point summary of key findings

## Pitfalls

- **Don't skip the critique section**: every project has limitations.
- **Don't fabricate data**: if a benchmark can't be found, say so.
- **Include concrete examples**: for technical topics, always include a hands-on scenario with concrete data, step-by-step walkthrough, and analogy. User said "没有一个具体的例子和场景，我还是无法理解他的方式".
- **Template is canonical**: always use `template/report.html` from the repo as the starting point. Do not copy-paste CSS from old reports.
- **Chinese content**: use Chinese for all body text; keep code/commands/technical terms in English.
- **Nginx permissions**: `sudo cp` + `sudo chmod 644` required.
- **GitLab Pages**: `public/` is the Pages root. Reports go in `public/reports/`. Index is `public/index.html`.
- **Git clone with PAT**: `https://oauth2:glpat-REVOKED@github.com/fatherplus/vicky.git`