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
    "domain": "tech",
    "tag": "分类标签",
    "template": "book",
    "subtitle": "一行副标题（可选）",
    "series": "丛书显示名（可选，与 order 同生共死）",
    "order": 1,
    "content": "<section class=\"reveal\"><div class=\"wrap\">...</div></section>"
  }'
```

返回：`{"ok": true, "file": "...", "created": true, "components": ["mermaid"], "warnings": [...], "url": ".../research/reports/..."}`

> **domain 路由**：`domain` 决定内容类型与蒸馏去向，可选值：
>
> | domain | 内容类型 | 模板 | 蒸馏 |
> |--------|----------|------|------|
> | `tech`（默认，可不填） | 技术文章 | `book`（默认） | ✅ 进知识库 |
> | `ephemeral` | 临时报告（给人/领导看） | `book` / `brief` | ❌ 跳过 |
> | `design` | 前端卡片（一产品一卡） | `card` | ❌ 不进蒸馏（token 人工维护） |
> | `arch` | 项目架构多页站 | `arch-overview` / `arch-node` | ❌ 跳过 |
>
> 蒸馏只处理 `tech`——`ephemeral` / `design` / `arch` 不入知识库。四类内容各自的提交约定见下方「四类工作流」。

> **修订即重交**：同 `slug` 再次 POST 会覆盖原文件（保留原日期，索引显示「订」徽章），不产生新报告。
> **丛书**：同时给 `series` + `order`（≥1 整数，同丛书内唯一）即成为丛书的一卷；索引按丛书聚函，报告页自动生成上下卷导航。
> **链接约定**：报告间互链一律用 canonical 相对路径 `reports/{file}`（或同目录报告互链直接写文件名）。
> **MD 李生链接**：每篇报告提交时自动生成同名的 `.md`（`reports/{slug}.md`，体积约 HTML 的 1/4）。**要把报告交给另一个 AI 执行/消费时，给 `.md` 链接而非 `.html`**——无视觉噪音、token 省 ~70%、MD 是 LLM 母语。人读用 `.html`，AI 读用 `.md`。

> **tag 约定**：一般技术报告用主题标签（如“向量检索”）；**平台介绍 / 设计说明类文档用 `META` 开头的 tag**（如“META · 关于这本书”）——会自动归入首页「卷首」区，不混进时间目录。

---

## ⭐ 第一原则：叙事宪法

写作前读 `GET /api/principles`（`skill/NARRATIVE-PRINCIPLES.md`）——
类型 → 目的 → 叙事的推导链与 9 条契约条目（8 不变量 + 元原则）。本指南只讲"如何用平台写作"，
方法论的"为什么"在宪法里。

**选模板**：`GET /api/templates` 看目录。默认 `book`（逐章长读）；
`brief`（结论先行决策简报）。都不适配时 `POST /api/templates` 创建
（必须附 rationale + narrative_contract——见宪法 §4）。
**框架可以换，不变量不能丢；大标题顺序必须可从不变量推出。**

**读者即上级**：你调研完写的文档，本质是向上汇报——读者（人）时间以秒计，
不关心你做了多少，关心的是：这事值多少、你推荐什么、需要他决定什么。
结论先行（`conclusion-first`）、证据量化（`evidence-for-claims`）、
给选择题不给问答题（`verdict-on-comparison`）；段落怎么开口见
`skill/EXPRESSION-GRAMMAR.md` 表达框架速查（PREP / STAR / FAB / GRAO）。

---

## 文档类型骨架

各模板的叙事契约见其 manifest（`GET /api/templates`）。按场景选模板与框架：

| 场景 | 模板 | 叙事框架 | 表达框架 |
|------|------|----------|----------|
| 技术研究 / 方案深挖（3000+ 字） | `book` | 黄金结构五章（宪法 §4） | STAR 验证 + FAB 讲方案价值 |
| 决策简报 / 选型建议 / 电梯摘要 | `brief` | 结论 → 依据 → 风险 → 行动 | PREP |
| 问题报告 / 资源申请 | `brief`（短）/ `book`（长） | SCQA：现状 → 冲突 → 方案 | GRAO |
| 重大复盘 / 跨部门评审 | `book` | 背景 → 原因 → 做法 → 验证 → 讨论 → 结论 | STAR + GRAO |

---

## 四类工作流（domain 路由）

平台收四类内容，由 `domain` 路由、模板承载形态。**平台不管来源**——AI 调研、人工撰写、Agent 代交都行，过了门禁照单发布归档。

### 技术文章（domain=tech · 默认）

AI 调研自媒体/开源资料后，把成品按本指南规范直接提交。平台只负责渲染、发布、归档，不问内容从哪来。
- `domain` 不填即为 `tech`，模板默认 `book`
- 进知识库（L2 蒸馏），成为后续调研的素材

### 临时报告（domain=ephemeral）

给人/领导看的汇报、周报、评审材料——**不进知识库、不污染检索**。
- `domain: "ephemeral"`，模板 `book` 或 `brief`
- 对外共享机制本期不做，按现有方式发链接即可

### 前端卡片（domain=design）

**一产品一卡**：产品主页大图 + 风格说明，供设计参考。卡片是素材，**不蒸馏**——设计 token 总纲由人工维护（见「其他 API」`GET /api/design`）。
- `slug: "card-{product}"`（如 `card-why-this-book`），`template: "card"`，`domain: "design"`
- `tag` = 主题（如「侧边导航」），同主题产品互相参照
- 截图走 `images` 字段（见下）

#### 截图规范

卡片（及任何带截图的报告）统一按此抓图：

- **视口 1440×900**，PNG 格式
- 默认抓**产品主页**；可补 2–3 张关键页（列表 / 详情 / 设置等），一页一图
- 经 `images: [{"name": "home.png", "b64": "<base64>"}]` 字段随提交上传（单张 ≤10MB，允许 png/jpg/jpeg/webp/svg），落盘 `public/assets/img/{slug}/`
- 正文里以 `/research/assets/img/{slug}/{name}` 引用（如 `<figure>` 里 `<img src="/research/assets/img/card-xxx/home.png">`），HTML 里不内嵌 base64

### 项目架构多页（domain=arch）

一个项目 = 一个丛书的多页站：总览卷 + 每模块一卷。每卷一份 MD 孪生，**总览 md 就是地图**——AI 先读地图，再按需钻节点卷。

丛书约定（复用 `series` + `order` 机制）：

```
{project}-arch-overview    series="{project}-arch"    order=1
{project}-arch-{module}    series="{project}-arch"    order=2..n
```

总览卷（模板 `arch-overview`）内容顺序：**定位段 → 全局 mermaid 流程图 → 模块索引 `data-table`**（模块 / 一句话职责 / 链接）。

#### 节点卷三段硬契约（门禁 400）

节点卷（模板 `arch-node`）正文必须依序出现三个 h2，**缺段会被 `POST /api/reports` 拒收（400）**：

1. **输入与输出** —— 模块的边界契约：吃什么、吐什么
2. **内部工作流** —— 模块内部怎么流转
3. **架构方案** —— 每个技术决策必答三问：解决什么？为什么是它？不这么做呢？

```html
<section class="reveal"><div class="wrap">
  <p class="section-label">01 · 输入与输出</p>
  <h2>输入与输出</h2>
  <p>……</p>
  <!-- 02 内部工作流 → 03 架构方案，依此类推 -->
</div></section>
```

#### 总览卷流程图（arch-flow 首选 · mermaid 兜底）

全局流程图首选 `arch-flow` 组件（分层布局 + 判断器菱形 + 功能三色；契约与节点四类型 schema 见 `skill/EXPRESSION-GRAMMAR.md`「节点编排图 arch-flow」）。图形状简单时可继续用 mermaid `click`。无论哪种，**节点必须链到各节点卷**（canonical 相对路径 `reports/{file}`）：

```html
<figure class="figure">
  <div class="arch-flow">
    <script type="application/json">
    { "layers": ["接入", "服务"],
      "nodes": [ { "id": "gw", "kind": "entry", "layer": 0, "label": "网关" },
                 { "id": "auth", "kind": "process", "layer": 1, "label": "认证模块",
                   "href": "reports/{project}-arch-auth.html" } ],
      "edges": [ { "from": "gw", "to": "auth", "label": "请求", "type": "main" } ],
      "modules": { "auth": { "purpose": "…", "input": "…", "output": "…", "logic": ["…"] } } }
    </script>
  </div>
  <figcaption class="fig-cap">图 1 · {project} 模块全景</figcaption>
  <p class="fig-note">点节点直接跳到对应节点卷；总览 md 即地图，AI 先读地图再钻节点。</p>
</figure>
```

`modules` 字段与节点卷三段硬契约同构（input/output ↔ 01 段，logic/decisions ↔ 02 段）——同一事实两处表述，提交时保持一致。mermaid 写法见下：

```html
<figure class="figure">
  <pre class="mermaid">
flowchart LR
  A[网关] --> B[认证模块] --> C[订单模块]
  click B "reports/{project}-arch-auth.html" "认证模块"
  click C "reports/{project}-arch-order.html" "订单模块"
  </pre>
  <figcaption class="fig-cap">图 1 · {project} 模块全景</figcaption>
  <p class="fig-note">点节点直接跳到对应节点卷；总览 md 即地图，AI 先读地图再钻节点。</p>
</figure>
```

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
| `GET /api/principles` | 叙事宪法（类型 → 目的 → 叙事 + 9 条契约条目） |
| `GET /api/templates` | 模板目录与各模板的叙事契约 manifest |
| `POST /api/templates` | 创建新模板（须附 rationale + narrative_contract） |
| `GET /api/guide` | 本指南（text/markdown） |
| `GET /api/skill` | 下载本指南（.md 文件） |
| `GET /api/template` | 查看完整 HTML 模板（了解页面框架） |
| `GET /api/design` | 设计 token 总纲（design.md，text/markdown；稳定别名，屏蔽文件名日期） |
| `GET /api/design.css` | 设计 CSS 资源包（下载 `book-style.css`，单文件） |
| `GET /api/reports` | 列出所有已发布报告 |
| `GET /api/health` | 健康检查 |

## 写作语言

- 正文用**中文**
- 代码、命令、技术术语保留英文
- 朴素、具体、不堆砌
