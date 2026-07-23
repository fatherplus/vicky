# AI Report — 统一研究报告平台

集中式 AI 研究报告管理平台。统一模板、统一风格、自动发布。

## 架构

```
ai-report/
├── template/
│   └── report.html           ← 统一 Apple-style 模板（所有报告的唯一 CSS 来源）
├── skill/
│   └── SKILL.md              ← Hermes Agent 技能文件（报告生成工作流）
├── public/                   ← GitLab Pages 根目录
│   ├── index.html            ← 报告索引页
│   └── reports/              ← 所有报告（命名：YYYY-MM-DD-slug.html）
├── scripts/
│   └── deploy.sh             ← 一键部署到本地 Nginx
├── .gitlab-ci.yml            ← GitLab Pages 自动发布
└── README.md
```

## 使用方式

### 生成新报告

1. 从 `template/report.html` 复制模板
2. 替换 `{{PLACEHOLDER}}` 标记
3. 保存到 `public/reports/YYYY-MM-DD-slug.html`
4. 更新 `public/index.html`（添加新条目）
5. 提交并推送 → GitLab Pages 自动发布

### 本地预览

```bash
cd public && python3 -m http.server 8080
# 访问 http://localhost:8080
```

### 部署到内部 Nginx

```bash
bash scripts/deploy.sh
```

## 在线访问

- **GitLab Pages**：https://fatherplus.github.io/vicky/
- **内部 Nginx**：http://192.168.1.100:9090/research/

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
| **风格规范**（长什么样） | `template/report.html` | 唯一 CSS 来源：Apple-style、主色 `#0C4A6E`、卡片圆角 18px、响应式 |

> ⚠️ **技术方案/架构汇报**：必须先写「场景与痛点」「为什么是这套方案」，再讲架构。
> 详见 `skill/SKILL.md` 的「第一原则」。不要「硬甲架构图」。

## 设计规范

所有报告使用统一模板 `template/report.html`，特点：
- Apple-style 极简设计
- 主色调 `#0C4A6E`（深蓝灰）
- 卡片圆角 18px，无边框
- 响应式布局（移动端单列）
- 中文字体优先（PingFang SC / Microsoft YaHei）