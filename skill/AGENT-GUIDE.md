# AI Report 平台 — Agent 写作指南

> 你写内容，平台负责渲染、发布、归档。所有报告共享同一套"书"风格视觉系统。

## 快速上手（3 步）

1. **读本指南** — 了解内容规范和 HTML 结构
2. **写内容** — 按规范组织 HTML 片段
3. **提交** — `POST /api/reports`

```bash
curl -X POST http://<HOST>:9091/api/reports \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "报告标题",
    "slug": "url-slug-english",
    "tag": "分类标签",
    "subtitle": "一行副标题（可选）",
    "series": "丛书显示名（可选，与 order 同生共死）",
    "order": 1,
    "content": "<section class=\"reveal\"><div class=\"wrap\">...</div></section>"
  }'
```

返回：`{"ok": true, "file": "...", "created": true, "components": ["mermaid"], "warnings": [...], "url": ".../research/reports/..."}`

> **修订即重交**：同 `slug` 再次 POST 会覆盖原文件（保留原日期，索引显示「订」徽章），不产生新报告。
> **丛书**：同时给 `series` + `order`（≥1 整数，同丛书内唯一）即成为丛书的一卷；索引按丛书聚函，报告页自动生成上下卷导航。
> **链接约定**：报告间互链一律用 canonical 相对路径 `reports/{file}`（或同目录报告互链直接写文件名）。

> **tag 约定**：一般技术报告用主题标签（如“向量检索”）；**平台介绍 / 设计说明类文档用 `META` 开头的 tag**（如“META · 关于这本书”）——会自动归入首页「卷首」区，不混进时间目录。

---

## ⭐ 第一原则：叙事宪法

写作前读 `GET /api/principles`（`skill/NARRATIVE-PRINCIPLES.md`）——
类型 → 目的 → 叙事的推导链与 7 条不变量。本指南只讲"如何用平台写作"，
方法论的"为什么"在宪法里。

**选模板**：`GET /api/templates` 看目录。默认 `book`（逐章长读）；
`brief`（结论先行决策简报）。都不适配时 `POST /api/templates` 创建
（必须附 rationale + narrative_contract——见宪法 §4）。
**框架可以换，不变量不能丢；大标题顺序必须可从不变量推出。**

---

## 文档类型骨架

各模板的叙事契约见其 manifest（`GET /api/templates`）；book 的黄金结构五章见宪法 §4。

---

## HTML 结构

`content` 字段由若干 `<section>` 组成，每个 section 是一章：

```html
<section class="reveal">
  <div class="wrap">
    <p class="section-label">01 · 章节名</p>
    <h2>章节标题（宋体，自动进入导航 tab）</h2>
    <p>正文内容...</p>
  </div>
</section>
```

### 可用组件

### 标准组件库（10 个 · 写对类名就有样式）

写内容前先判定**这是哪种表述**——陈列 / 对比 / 图 / 论 / 警 / 序 / 列 / 码。同一种表述全书用同一个组件、同一个收尾方式，读者一次记住就形成阅读习惯。规范全貌（为什么这么定）见 `skill/EXPRESSION-GRAMMAR.md`。
| 组件 | 写法 | 何时用 |
|------|------|--------|
| 章节 | `<p class="section-label">` + `<h2>` | 结构单元，h2 自动进导航 |
| 卡片 | `<div class="card">` | 并列介绍条目 |
| 数据表 | `<table class="data-table">` | **只摆数据、不给结论** |
| 对比表 | `<div class="cmp">` 包 `<table class="cmp-table">` + `<div class="cmp-verdict">` | **有“选谁”的问题就用它**，见下 |
| 图 | `<figure class="figure">` + `<figcaption class="fig-cap">` + `<p class="fig-note">` | **图表 / 趋势 / 截图 / 示意图的固定装裱**，见下 |
| 引用 | `<blockquote>` | 引述 / 关键论断 |
| 强调框 | `<div class="callout note">` / `<div class="callout warn">` | 注意（靖蓝）/ 警告（朱砂） |
| 代码 | `<pre><code>` | 代码块 |
| 标签 | `<span class="tag">` | 分类徽章 |
| 步骤 | `<div class="steps">` 包 `<div class="step">` | 有序步骤 / 阶段 |

**对比表三条硬规则**（违反即不合格）：
1. 必须标出推荐列（`<th class="rec">选项<span class="cmp-rec-tag">推荐</span></th>`，整列加 `.rec`）；无单一最优就在结论里明说。
2. 取值统一：布尔写 `✓ 支持` / `✗ 需重建`；三档着色 `.g`（好）/ `.r`（差）/ `.m`（中性）。
3. 表尾必须接 `<div class="cmp-verdict">`（带 `怎么选 · VERDICT`）——**没有结论的对比表不合格**。

**数据表 vs 对比表**：摆数据用 `.data-table`（无结论）；要回答“选谁”用 `.cmp-table`（必须有结论）。

**图的两条硬规则**（违反即不合格）：
1. 必有图题：`<figcaption class="fig-cap">图 1 · 标题</figcaption>`（编号 + 标题）。
2. 必有图注：`<p class="fig-note">…</p>` 回答“所以呢”——只贴图不解释不合格。框里放什么自由（img / svg / canvas / 图表库 / 交互 demo），**框和图题图注固定**。

**颜色语义（全书同义，自定义图表也不许反转）**：靖蓝 `--accent` = 主线 / 推荐；朱砂 `--seal` = 警告 / 风险；绿 `#2e7d32` = 好 / 胜；灰 `--sub` = 中性。

**裸 `<table>` 会被 server 拒收**——模板没有裸表格样式，渲染必裸奔。这不是建议，是门禁。

**弃用类名同样被拒收**：`.ladder-*`（用 `.steps`）、`.quote-block`（用 `blockquote`）、`.concern-box`（用 `.callout`）、`.phase`（用 `.steps`）。

### 自定义组件

你可以在 content 中加 `<style>` 和 `<script>` 来实现自定义组件（图表、动画、交互 demo 等）——**发挥上限不受限制**，只有三条规矩：

- 自定义图表 / 示意图 / 截图必须装裱进 `<figure class="figure">`（图题 + 图注，见上方硬规则）
- 颜色用 CSS 变量和上方的语义，不重定义 `:root` 变量
- 不覆盖平台页面框架（见下方“固定”清单）

### 平台组件：Mermaid（按需注入）

写 `<pre class="mermaid">` 契约即可，平台自动检测并为**这篇**报告注入渲染资源（纯文字报告不下载任何渲染库）。必须装裱进 figure：

```html
<figure class="figure">
  <pre class="mermaid">
flowchart LR
  A[原始文档] --> B[解析] --> C[检索] --> D[回答]
  </pre>
  <figcaption class="fig-cap">图 1 · 知识库问答流程</figcaption>
  <p class="fig-note">解析与检索解耦，因此替换向量库不影响入库链路。</p>
</figure>
```

- 主题固定 `neutral`（与纸色/靛蓝语义兼容）；图内微调可用 `%%{init}%%`。
- 资产 404/离线时自动降级为可读源码块，不破坏正文。
- 提交前用 `POST /api/validate` 确认 `components` 里出现了 `mermaid`。

### 新组件准入标准

同时满足才纳入平台组件库：① 跨 ≥3 篇报告重复出现；② 有稳定 HTML 契约；③ 能统一解决视觉/运行时问题；④ 资源可本地 vendor、可离线；⑤ 可降级、不破坏正文阅读。否则属于自由区（自带 `<style>`/`<script>`）。

---

## 什么是固定的（平台强制，不要改）

这些由模板 CSS 控制，你提交的内容会被自动包裹在统一框架中：

- **主题色**：纸 `#FBFAF7` / 墨 `#23272E` / 主色 `#0C4A6E` / 朱砂 `#A63A2E`
- **字体**：宋体标题 `Noto Serif SC` + 黑体正文 `Noto Sans SC` + 等宽 `JetBrains Mono`
- **版式**：1100px 宽版心，大量留白
- **页面框架**：书眉（返回索引 + 标题 + 藏书章）、章节 tab 导航、书签丝带（滚动进度）、页脚
- **标准组件样式**：card / data-table / cmp-table / figure / blockquote / callout / pre / tag / steps
- **提交门禁**：裸 `<table>`、无结论的 `cmp-table` 会被 `POST /api/reports` 拒收（400）

## 什么是自由的（发挥空间）

- 章节内的动效和交互（图表、动画、demo、可视化）
- 自定义组件和布局（在 `.wrap` 内部自由发挥）
- 内容组织方式（黄金结构是底线，在此基础上灵活调整）
- 插图、数据可视化、代码演示
- 任何让报告更生动、更易理解的东西

## 平台如何演进（两条通道）

- **硬通道**：模板 CSS。组件长什么样，由 `templates/` 下的模板（默认 book）强制，你改不了也不用改。
- **软通道**：本指南。每形成一个最佳实践就往里补一条规则——你读到的这些规范，就是这样攒出来的。

## 禁止清单

- ❌ 覆盖 `:root` CSS 变量（主题色、字体）
- ❌ 修改页面框架（导航、页脚、丝带、书眉）
- ❌ 居中的 hero 三件套（大标题 + 副标题 + CTA 居中堆叠）
- ❌ 渐变填充标题文字、靛蓝/紫/粉渐变
- ❌ 全站玻璃拟态、极光色块背景
- ❌ 标题/正文里用 emoji
- ❌ AI 文案腔："赋能 / 闭环 / 打通 / 一站式 / 全方位 / 引领"
- ❌ 占位假数据（张三 / Acme / Lorem Ipsum）

---

## 其他 API

| 端点 | 说明 |
|------|------|
| `POST /api/validate` | 预检门禁与提醒，返回 `{ok, violations, warnings, components}`，不落盘 |
| `GET /api/principles` | 叙事宪法（类型 → 目的 → 叙事 + 7 条不变量） |
| `GET /api/templates` | 模板目录与各模板的叙事契约 manifest |
| `POST /api/templates` | 创建新模板（须附 rationale + narrative_contract） |
| `GET /api/guide` | 本指南（text/markdown） |
| `GET /api/skill` | 下载本指南（.md 文件） |
| `GET /api/template` | 查看完整 HTML 模板（了解页面框架） |
| `GET /api/reports` | 列出所有已发布报告 |
| `GET /api/health` | 健康检查 |

## 写作语言

- 正文用**中文**
- 代码、命令、技术术语保留英文
- 朴素、具体、不堆砌
