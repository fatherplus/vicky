# Vicky — AI 研究报告知识平台

个人知识平台：Agent 研究报告入库 → 知识蒸馏 → Agent 知识服务。统一模板、统一风格、自动发布。

## 开源协作

- 仓库：https://github.com/fatherplus/vicky
- 欢迎提交 Issue / PR：报告模板、蒸馏规则、门禁校验、组件库都值得打磨
- 本地一键起服务：`python3 -m vicky.web`（默认 9091 端口），浏览器打开 http://localhost:9091
- 所有报告内容仅作示例展示，欢迎用 `/api/guide` 规范生成你自己的报告

## 架构

```
vicky/
├── templates/                ← 注册制模板（各含 template.html + manifest.json）
│   ├── book/                 ← 默认：技术深度研究的逐章长读
│   └── brief/                ← 结论先行的决策简报
├── skill/
│   └── SKILL.md              ← Hermes Agent 技能文件（报告生成工作流）
├── public/                   ← 静态自伺服根目录（首页/索引/报告均为运行时生成，不入库）
│   └── assets/               ← 共享资产（book-style.css 唯一 CSS 来源 / components/mermaid 按需注入）
├── scripts/
│   └── deploy.sh             ← 一键部署（systemd + Nginx）
├── tests/                    ← stdlib unittest
└── README.md
```

## 使用方式

### 生成新报告（API 驱动）

```bash
curl -X POST http://localhost:9091/api/reports \
  -H 'Content-Type: application/json' \
  -d '{"title": "...", "slug": "...", "tag": "tech", "content": "<section>...</section>"}'
```

报告经 L0 快照 → L1 门禁校验 → 模板渲染 → HTML+MD 孪生发布，索引页与首页自动重建。

先读 `GET /api/guide`（写作规范）再用 `POST /api/validate` 预检，避免 400 拒收。

### 本地预览
```bash
python3 -m vicky.web        # 默认 127.0.0.1:9091
# 访问 http://localhost:9091
```

### 部署

```bash
bash scripts/deploy.sh      # systemd + Nginx（见 AGENTS.md 部署章节）
```

## API

```
POST /api/reports    创建/修订报告（同 slug upsert）  body: {title, slug, tag, subtitle?, series?, order?, template?, content}
POST /api/validate   预检（返回 ok/violations/warnings/components，不落盘）
POST /api/templates  创建模板（创建即收录 provisional；门禁：占位符/token/契约）
GET  /api/reports    列出所有报告
GET  /api/guide      写作指南（markdown）
GET  /api/template   查看 HTML 模板（?name=，默认 book）
GET  /api/templates  模板目录
GET  /api/principles 叙事宪法（markdown）
```

- **upsert**：同 `slug` 再次 POST 覆盖原文件（保留原日期，索引显示「订」徽章），不产生新报告。
- **丛书**：同时给 `series` + `order`（≥1 整数，同丛书内唯一）即成为丛书的一卷，报告页自动生成上下卷导航。
- **模板**：注册制（`templates/`），`POST /api/reports` 以 `template` 参数按名选择（默认 book）。模板拥有结构不拥有视觉——调色板/字体由平台 `book-style.css` 拥有，叙事不变量由 `skill/NARRATIVE-PRINCIPLES.md` 约束。
- 默认端口 9091：`python3 -m vicky.web`。

## 报告列表

报告由平台运行时生成（`public/reports/` 不入库）。

## 报告列表

| 日期 | 标题 |
|------|------|
| 2026-07-20 | HNSW 算法深度研究报告 |
| 2026-07-17 | 大模型网关 TokenPlan 配比优化方案 |
| 2026-07-14 | GBrain by Garry Tan |
| 2026-07-13 | RAG 动态 TOP-K 算法 — 永泽 |
| 2026-07-13 | Adaptive/Dynamic Top-k in RAG |
| 2026-07-13 | Dynamic Top-k & Adaptive Retrieval in RAG |
| 2026-07-06 | Hindsight 记忆研究 |
| 2026-07-06 | CodeGraph · Ponytail · Context7 三件套 |
| 2026-07-06 | Claude AI 模型使用分析报告 |
| 2026-07-05 | Ponytail 开源项目研究 |
| 2026-07-04 | Hermes Agent 知识数据源配置 |

## 规范（集中管理：内容 + 风格）

所有约束集中在本仓库，写报告前必读这两处：

| 约束 | 位置 | 内容 |
|------|------|------|
| **内容规范**（怎么写） | `skill/SKILL.md` | ⭐ 第一原则：先讲「为什么」再讲「是什么」；黄金结构（定位→场景痛点→为什么→方案→细节）；技术决策三问；反模式清单 |
| **风格规范**（长什么样） | `skill/BOOK-STYLE.md` + `templates/book/template.html` | 「书」风格硬约束：宋体标题 + 书眉 + 藏书章 + 书签丝带；纸 `#FBFAF7` / 墨 `#23272E` / 主色 `#0C4A6E` / 朱砂 `#A63A2E`；模板是唯一 CSS 来源；重量组件（mermaid）按需注入 |

> ⚠️ **技术方案/架构汇报**：必须先写「场景与痛点」「为什么是这套方案」，再讲架构。
> 详见 `skill/SKILL.md` 的「第一原则」。不要「硬甲架构图」。

## 设计规范（书风格）

整个仓库呈现为一本书：每篇报告 = 书的一页（风格统一），索引页 = 封面 + 目录。
所有报告由 `templates/` 下的模板渲染（默认 `book`），硬约束见 `skill/BOOK-STYLE.md`：
- 宋体标题（Noto Serif SC）+ 黑体正文（Noto Sans SC）+ 等宽元信息（JetBrains Mono）
- 纸 `#FBFAF7` / 墨 `#23272E` / 主色 `#0C4A6E` / 朱砂印章 `#A63A2E`（只用于小面积）
- 书眉（running head）+ 书签丝带（滚动进度）+ 章节开头带藏书章
- 720px 正文栏、大量留白、克制动效、尊重 prefers-reduced-motion