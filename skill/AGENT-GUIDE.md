# Vicky 平台 — Agent 写作指南

> 你写内容，平台负责渲染、发布、归档。所有报告共享同一套"书"风格视觉系统。
> 本指南是提交契约（`GET /api/guide` 返回本文）；叙事选型见 `GET /api/narratives`（`skill/NARRATIVES.md`）。

## 快速上手（3 步）

1. **读本指南** — 了解分类骨架、HTML 结构和门禁红线
2. **写内容** — 先选叙事方式（`GET /api/narratives`），再按规范组织 HTML 片段
3. **提交** — `POST /api/reports`（可先用 `POST /api/validate` dry 预检）

```bash
curl -X POST http://192.168.12.15:9093/api/reports \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "报告标题",
    "slug": "url-slug-english",
    "category": "research",
    "narrative": "黄金五章",
    "project": "项目名（项目文档必填，其余可选）",
    "tag": "分类标签",
    "template": "book",
    "subtitle": "一行副标题（可选）",
    "series": "丛书显示名（可选，与 order 同生共死）",
    "order": 1,
    "content": "<section class=\"reveal\"><div class=\"wrap\">...</div></section>"
  }'
```

- **投稿一律用正式环境**：`http://192.168.12.15:9093`（`localhost:9091` 仅本地开发调试用）
- 返回：`{"ok": true, "file": "...", "created": true, "components": ["mermaid"], "warnings": [...], "url": ".../reports/..."}`

> **修订即重交**：同 `slug` 再次 POST 会覆盖原文件（保留原日期，索引显示「订」徽章），不产生新报告。
> **链接约定**：报告间互链一律用 canonical 相对路径 `reports/{file}`（或同目录报告互链直接写文件名）。
> **MD 孪生链接**：每篇报告提交时自动生成同名的 `.md`——文件名 = HTML 文件名把 `.html` 换成 `.md`（如 `reports/2026-08-12-{slug}.md`，体积约 HTML 的 1/4）。**要把报告交给另一个 AI 执行/消费时，给 `.md` 链接而非 `.html`**——无视觉噪音、token 省 ~70%、MD 是 LLM 母语。人读用 `.html`，AI 读用 `.md`。

> **tag 约定**：一般技术报告用主题标签（如"向量检索"）；**平台介绍 / 设计说明类文档用 `META` 开头的 tag**（如"META · 关于这本书"）——会自动归入首页「卷首」区，不混进时间目录。

---

## 三个正交维度（先看懂这个）

报告有三个独立维度，**各管各的、互不越界**：

| 维度 | 决定什么 | 谁做主 |
|------|----------|--------|
| **骨架（category）** | 进不进知识库、门禁红线、归档去向 | 平台强制，agent 显式选择 |
| **叙事（narrative）** | 章节怎么组织、用什么节奏讲 | agent 按这篇内容从叙事库选 |
| **视觉** | 字体、配色、版式、组件样式 | `book-style.css` 独占，谁都碰不到 |

核心解耦：**归档（去哪）与模板（怎么讲）是两个正交字段**。一篇"项目里的技术方案"=
归档维度是 `project=某项目` + 骨架 `tech-solution` + 叙事 `对比擂台`——不需要为这种组合单独做模板。
**AI 不再猜分类**——旧模型的 `domain` 字段已彻底废弃，不要提交 `domain`，一律用 `category`（见下节）。

---

## 分类骨架（category）

`category` 决定内容类型与沉淀去向，可选值：

| category | 定位 | 沉淀去向 | 默认模板 | 门禁差异 |
|----------|------|----------|----------|----------|
| `research`（默认） | 技术调研长读——完整理解一个技术 | ✅ **进知识库**（L2 蒸馏成可查询条目） | `book` | 常规门禁 + 技术类必答三问 / 场景演练提醒 |
| `brief` | 决策简报 / 汇报领导 | 用完即弃，不污染检索 | `brief` | 常规门禁 |
| `tech-solution` | 技术方案——讲"做什么 / 为什么" | 归项目区聚合（建议带 `project`） | `book` | ⚠️ **止步示意层**：架构 + 表结构示意，**不含实施代码**（大段实施代码 server 给 warning） |
| `arch-doc` | 项目架构详情——当前架构全貌 + 演进 | 归项目区聚合（建议带 `project`） | `arch-overview` | 丛书卷号唯一；`arch-node` 节点卷三段 h2 硬契约（400 拒收） |

> **蒸馏只处理 `research`**——`brief` / `tech-solution` / `arch-doc` 不进知识库。

### 技术方案（tech-solution）的边界

方案讲"决定做什么、为什么这么做"，到架构与数据结构的**示意层**为止，代码级实施止步：

| 应该有 | 不应该有 |
|--------|----------|
| 问题定义、目标 | 具体代码实现 |
| 选型对比（带结论） | 函数 / 类 / API 签名 |
| 宏观架构图、产品 / 工作流程图 | 完整建表 DDL 逐字段 |
| 表结构示意（有哪些表、关系） | 部署脚本、配置文件 |
| 数据流向、**关键取舍（方案的灵魂）** | 实施步骤 / 排期 / 任务拆解 |

---

## 归档（project）与叙事（narrative）：两个正交字段

### project —— 归档去哪

`project` 把报告归入**项目区**，同一项目的 tech-solution + arch-doc 聚合在一起，
支持评审、回顾项目发展历程、通过 `.md` 给三方 agent 引用实现。

- **项目文档（tech-solution / arch-doc）建议必填**，如 `"project": "vicky"`
- research / brief 一般不填——它们按时间线归档
- **先建项目**：`POST /api/projects`（body `{"name": "..."}`，slug 由 name 规范化生成、统一 lowercase）
- 同一项目 = 同一个 `project` slug；先 `GET /api/projects` 查已建项目，未注册的 project 投稿给 warning 不拒收
- **`.vicky` 联动**：在项目仓库根目录放 `.vicky` 两行文件（`project=<slug>` / `endpoint=http://192.168.12.15:9093`），agent 投稿前读它自动带 project，无需每次手动传

```json
{ "category": "tech-solution", "project": "vicky", "title": "Vicky L2 蒸馏方案" }
```

### narrative —— 怎么讲

`narrative` 从叙事方式选型库（`GET /api/narratives`，`skill/NARRATIVES.md`）选一个，7 种：
金字塔/结论先行、对比擂台、问题拆解、场景演练、时间线/演进、总分总/地图、黄金五章。
不填走分类默认（research 默认黄金五章）。**叙事是章节组织指引，不是 HTML 模板**——不换视觉、不换归档。

```json
{ "category": "tech-solution", "narrative": "对比擂台", "title": "向量库选型方案" }
```

组合示例：

| category | project | narrative | 这是什么 |
|----------|---------|-----------|----------|
| `research` | — | `场景演练` | 讲算法机制的长文 |
| `brief` | — | `金字塔/结论先行` | 给领导的决策简报 |
| `tech-solution` | `vicky` | `对比擂台` | 项目里的选型方案 |
| `arch-doc` | `vicky` | `总分总/地图` | 项目架构总览卷 |

---

## ⭐ 第一原则：叙事宪法

写作前读 `GET /api/principles`（`skill/NARRATIVE-PRINCIPLES.md`）——
类型 → 目的 → 叙事的推导链与 9 条契约条目（8 不变量 + 元原则）。本指南只讲"如何用平台写作"，
方法论的"为什么"在宪法里。

**选叙事**：`GET /api/narratives`（`skill/NARRATIVES.md`）先看选型决策表——
内容特征 → 推荐叙事。拿不定就黄金五章。
**选模板**：`GET /api/templates` 看目录。默认按分类走（research→book、brief→brief、
tech-solution→book、arch-doc→arch-overview）；都不适配时 `POST /api/templates` 创建
（必须附 rationale + narrative_contract——见宪法 §4）。
**框架可以换，不变量不能丢；大标题顺序必须可从不变量推出。**

**读者即上级**：你调研完写的文档，本质是向上汇报——读者（人）时间以秒计，
不关心你做了多少，关心的是：这事值多少、你推荐什么、需要他决定什么。
结论先行（`conclusion-first`）、证据量化（`evidence-for-claims`）、
给选择题不给问答题（`verdict-on-comparison`）；段落怎么开口见
`skill/EXPRESSION-GRAMMAR.md` 表达框架速查（PREP / STAR / FAB / GRAO）。

---

## 三个工作流

平台按 `category` 路由三路内容，由模板承载形态。**平台不管来源**——AI 调研、人工撰写、Agent 代交都行，过了门禁照单发布归档。

### 工作流一 · 技术调研长文（category=research）

AI 调研自媒体/开源资料后，把成品按本指南规范直接提交，进知识库成为后续调研的素材。
- `category` 不填即为 `research`，模板默认 `book`，叙事默认黄金五章
- 技术 / 算法 / 机制类建议用「场景演练」叙事；选型类用「对比擂台」
- 技术类必有场景演练（小数据集、逐步计算、类比）——血泪教训："没有一个具体的例子和场景，我还是无法理解他的方式"

### 工作流二 · 临时简报（category=brief）

给人/领导看的汇报、周报、评审材料——**不进知识库、不污染检索**。
- `category: "brief"`，模板默认 `brief`（结论先行决策简报）
- 叙事建议 `金字塔/结论先行`：结论 → 依据 → 风险 → 行动
- 对外共享机制本期不做，按现有方式发链接即可

### 工作流三 · 项目文档（category=tech-solution / arch-doc + project）

一个项目的技术方案与架构详情，归入项目区，可评审、可回顾演进、可给三方 agent 引用。

**技术方案（tech-solution）**：讲"做什么 / 为什么"，止步示意层（见上「技术方案的边界」）。
**其 `.md` 孪生就是给三方 agent 的实现契约**——三方 agent 拿 .md 当输入去写代码。
- `category: "tech-solution"` + `project: "{项目名}"`，模板默认 `book`，叙事可选 `对比擂台` / `问题拆解` / `黄金五章`

**架构详情（arch-doc）**：项目当前架构全貌 + 演进，走丛书机制（见下）。
- `category: "arch-doc"` + `project: "{项目名}"`，总览卷模板 `arch-overview`，节点卷 `arch-node`
- 叙事总览卷用 `总分总/地图`，演进章节用 `时间线/演进`

#### 丛书机制（arch-doc 场景）

一个项目 = 一个丛书的多页站：总览卷 + 每模块一卷。每卷一份 MD 孪生，**总览 md 就是地图**——AI 先读地图，再按需钻节点卷。

丛书约定（复用 `series` + `order` 机制，仅 arch-doc 场景使用）：

```
{project}-arch-overview    series="{project}-arch"    order=1
{project}-arch-{module}    series="{project}-arch"    order=2..n
```

总览卷（模板 `arch-overview`）内容顺序：**定位段 → 全局 mermaid 流程图 → 模块索引 `data-table`**（模块 / 一句话职责 / 链接）。

##### 节点卷三段硬契约（门禁 400）

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

##### 总览卷流程图（arch-flow 首选 · mermaid 兜底）

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

### 标准组件库（10 个 · 写对类名就有样式）

写内容前先判定**这是哪种表述**——陈列 / 对比 / 图 / 论 / 警 / 序 / 列 / 码。同一种表述全书用同一个组件、同一个收尾方式，读者一次记住就形成阅读习惯。规范全貌（为什么这么定）见 `skill/EXPRESSION-GRAMMAR.md`。

| 组件 | 写法 | 何时用 |
|------|------|--------|
| 章节 | `<p class="section-label">` + `<h2>` | 结构单元，h2 自动进导航 |
| 卡片 | `<div class="card">` | 并列介绍条目 |
| 数据表 | `<table class="data-table">` | **只摆数据、不给结论** |
| 对比表 | `<div class="cmp">` 包 `<table class="cmp-table">` + `<div class="cmp-verdict">` | **有"选谁"的问题就用它**，见下 |
| 图 | `<figure class="figure">` + `<figcaption class="fig-cap">` + `<p class="fig-note">` | **图表 / 趋势 / 截图 / 示意图的固定装裱**，见下 |
| 引用 | `<blockquote>` | 引述 / 关键论断 |
| 强调框 | `<div class="callout note">` / `<div class="callout warn">` | 注意（靛蓝）/ 警告（朱砂） |
| 代码 | `<pre><code>` | 代码块 |
| 标签 | `<span class="tag">` | 分类徽章 |
| 步骤 | `<div class="steps">` 包 `<div class="step">` | 有序步骤 / 阶段 |

**对比表三条硬规则**（违反即不合格）：
1. 必须标出推荐列（`<th class="rec">选项<span class="cmp-rec-tag">推荐</span></th>`，整列加 `.rec`）；无单一最优就在结论里明说。
2. 取值统一：布尔写 `✓ 支持` / `✗ 需重建`；三档着色 `.g`（好）/ `.r`（差）/ `.m`（中性）。
3. 表尾必须接 `<div class="cmp-verdict">`（带 `怎么选 · VERDICT`）——**没有结论的对比表不合格**。

**数据表 vs 对比表**：摆数据用 `.data-table`（无结论）；要回答"选谁"用 `.cmp-table`（必须有结论）。

**图的两条硬规则**（违反即不合格）：
1. 必有图题：`<figcaption class="fig-cap">图 1 · 标题</figcaption>`（编号 + 标题）。
2. 必有图注：`<p class="fig-note">…</p>` 回答"所以呢"——只贴图不解释不合格。框里放什么自由（img / svg / canvas / 图表库 / 交互 demo），**框和图题图注固定**。

**颜色语义（全书同义，自定义图表也不许反转）**：靛蓝 `--accent` = 主线 / 推荐；朱砂 `--seal` = 警告 / 风险；绿 `#2e7d32` = 好 / 胜；灰 `--sub` = 中性。

**裸 `<table>` 会被 server 拒收**——模板没有裸表格样式，渲染必裸奔。这不是建议，是门禁。

**弃用类名同样被拒收**：`.ladder-*`（用 `.steps`）、`.quote-block`（用 `blockquote`）、`.concern-box`（用 `.callout`）、`.phase`（用 `.steps`）。

### 自定义组件

你可以在 content 中加 `<style>` 和 `<script>` 来实现自定义组件（图表、动画、交互 demo 等）——**发挥上限不受限制**，只有三条规矩：

- 自定义图表 / 示意图 / 截图必须装裱进 `<figure class="figure">`（图题 + 图注，见上方硬规则）
- 颜色用 CSS 变量和上方的语义，不重定义 `:root` 变量
- 不覆盖平台页面框架（见下方"固定"清单）

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

## 截图规范

带截图的报告统一按此抓图（走 `images` 字段随提交上传，落盘 `public/assets/img/{slug}/`）：

- **视口 1440×900**，PNG 格式
- 默认抓**产品主页**；可补 2–3 张关键页（列表 / 详情 / 设置等），一页一图
- `images: [{"name": "home.png", "b64": "<base64>"}]`，单张 ≤10MB，允许 png/jpg/jpeg/webp/svg
- 正文里以 `/assets/img/{slug}/{name}` 引用（如 `<figure>` 里 `<img src="/assets/img/card-xxx/home.png">`），HTML 里不内嵌 base64

---

## 什么是固定的（平台强制，不要改）

这些由模板 CSS 控制，你提交的内容会被自动包裹在统一框架中：

- **主题色**：纸 `#FBFAF7` / 墨 `#23272E` / 主色 `#0C4A6E` / 朱砂 `#A63A2E`
- **字体**：宋体标题 `Noto Serif SC` + 黑体正文 `Noto Sans SC` + 等宽 `JetBrains Mono`
- **版式**：1100px 宽版心，大量留白
- **页面框架**：书眉（返回索引 + 标题 + 藏书章）、章节 tab 导航、书签丝带（滚动进度）、页脚
- **标准组件样式**：card / data-table / cmp-table / figure / blockquote / callout / pre / tag / steps
- **提交门禁**：裸 `<table>`、无结论的 `cmp-table`、丛书卷号重复、arch-node 缺三段会被 `POST /api/reports` 拒收（400）

## 什么是自由的（发挥空间）

- 章节内的动效和交互（图表、动画、demo、可视化）
- 自定义组件和布局（在 `.wrap` 内部自由发挥）
- 内容组织方式（叙事库选型是底线，在此基础上灵活调整）
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

## 其他 API

| 端点 | 说明 |
|------|------|
| `POST /api/reports` | 提交 / 修订报告（带 category / narrative / project 字段） |
| `POST /api/validate` | 预检门禁与提醒，返回 `{ok, violations, warnings, components}`，不落盘 |
| `GET /api/narratives` | 叙事方式选型库（7 种：章节组织指引，`skill/NARRATIVES.md`） |
| `GET /api/principles` | 叙事宪法（类型 → 目的 → 叙事 + 9 条契约条目） |
| `GET /api/templates` | 模板目录与各模板的叙事契约 manifest |
| `POST /api/templates` | 创建新模板（须附 rationale + narrative_contract） |
| `GET /api/guide` | 本指南（text/markdown） |
| `GET /api/skill` | 下载规范 skill（vicky-writer/SKILL.md，含 frontmatter，可被 skill 系统识别） |
| `GET /api/template` | 查看完整 HTML 模板（了解页面框架） |
| `GET /api/design` | 设计 token 总纲（design.md，text/markdown；存量资源，稳定别名） |
| `GET /api/design.css` | 设计 CSS 资源包（下载 `book-style.css`，单文件） |
| `GET /api/reports` | 列出所有已发布报告 |
| `GET /api/reports/{slug}/content` | 取报告原始 content（修订 / 归项目前先取原文） |
| `PATCH /api/reports/{slug}` | 轻量更新元数据（project/tag/category/subtitle/narrative 等，不动 content） |
| `POST /api/projects` | 新建项目（body `{name, description?}`，slug 由 name 生成） |
| `GET /api/projects` | 项目清单（含已建项目 slug/name） |
| `DELETE /api/projects/{slug}` | 归档项目（软删除，可逆） |
| `GET /api/health` | 健康检查 |

> **平台无 MCP**：不提供 MCP 服务器，agent 交互一律走上面的 HTTP 端点。

## 写作语言

- 正文用**中文**
- 代码、命令、技术术语保留英文
- 朴素、具体、不堆砌
