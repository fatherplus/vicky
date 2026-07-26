# AGENTS.md — ai-report 项目上下文

## 这是什么

集中式技术研究报告平台。任何 AI Agent 研究完一个技术后，把内容 POST 过来，平台自动套用统一的"书"风格渲染、发布、归档。

**核心问题**：不同 agent、不同时间写的报告，风格五花八门。
**解法**：视觉 taste 由 server 端模板强制（agent 碰不到 CSS）；内容 taste 分三层——表述形态由 server 门禁强制（裸表格/无结论对比直接拒收），语义词汇由表述规范约束，框内的画完全放开。`/api/guide` 暴露写作规范。

## 架构

```
agent 写 HTML 内容 → POST /api/reports → server 套 template/report.html → 发布
                                          ↑
                                    视觉 taste 在这一步强制注入
```

## 文件地图

| 文件 | 角色 | 改它之前注意 |
|------|------|-------------|
| `server.py` | HTTP API 服务（报告提交/列表/指南/模板） | 纯 stdlib，无依赖 |
| `template/report.html` | **唯一 CSS 来源**，所有报告的视觉框架 | 改这里 = 改全站风格 |
| `skill/AGENT-GUIDE.md` | 面向外部 agent 的写作指南（`/api/guide` 返回它） | 这是 agent 的唯一入口文档 |
| `skill/SKILL.md` | 内部 skill（pi 用），含部署流程和完整方法论 | 比 AGENT-GUIDE 更详细 |
| `skill/BOOK-STYLE.md` | 书风格设计硬约束（字体/配色/版式/动效/禁止清单） | 设计规范源头 |
| `skill/EXPRESSION-GRAMMAR.md` | 表述规范——这本书的「内容语法」（形态/语义/自由区） | 改组件时同步这里 |
| `public/reports/` | 所有已发布报告（`YYYY-MM-DD-slug.html`） | 只增不改 |
| `public/assets/` | 共享资产（book-style.css / index.css / components/mermaid/） | book-style.css 是唯一 CSS 来源 |
| `scripts/nginx-research.conf` | canonical 301 + 资产 no-cache | deploy.sh 安装 |
| `tests/` | stdlib unittest | 改门禁/资产时同步 |
| `public/index.html` | 索引页（server 自动生成，不要手改） | `build_index()` 生成 |
| `convert_to_book.py` | 存量迁移：旧格式报告 → 书风格 | 一次性脚本 |
| `taste-skill/` | 上游参考（clone 自 GitHub），不直接使用 | 只读参考 |

## API

```
POST /api/reports   创建/修订报告（同 slug upsert）  body: {title, slug, tag, subtitle?, series?, order?, content}
POST /api/validate  预检（violations/warnings/components，不落盘）
GET  /api/reports   列出所有报告
GET  /api/guide     写作指南（markdown）
GET  /api/skill     下载写作指南（.md 附件）
GET  /api/template  查看 HTML 模板
GET  /api/health    健康检查
```

默认端口 9091。启动：`python3 server.py [port]（位置参数，默认 9091）`

## Taste 约束分层

**硬约束（模板 CSS 强制，agent 不可改）**：
- 主题色：纸 `#FBFAF7` / 墨 `#23272E` / 主色 `#0C4A6E` / 朱砂 `#A63A2E`
- 字体：宋体标题 `Noto Serif SC` + 黑体正文 `Noto Sans SC` + 等宽 `JetBrains Mono`
- 版式：1100px 宽版心、书眉、书签丝带、藏书章、章节 tab 导航、返回索引
- 基础组件：card / data-table / cmp-table / figure / blockquote / pre / callout / tag / steps

**门禁约束（server 校验，`POST /api/reports` 400 拒收）**：
- 裸 `<table>`——必须带 `data-table` 或 `cmp-table`
- `cmp-table` 无 `cmp-verdict`——对比必须有结论
- 弃用类名（`.ladder-*` / `.quote-block` / `.concern-box` / `.phase`）——模板已删除其样式
- 丛书卷号重复——同 `series` 同 `order` 已被其他文件占用（upsert 本卷除外）
- 模板对漏网裸表格有兜底样式（按 data-table 渲染），但门禁才是主防线

**提醒约束（server 校验，随响应返回 warnings，不拒收）**：
- figure 缺 fig-cap / fig-note
- AI 腔词（赋能/闭环/打通/一站式/全方位/引领）、标题正文 emoji
- mermaid 未装裱进 figure

重量级渲染资源（mermaid）由 server 检测 HTML 契约后按篇注入 `<head>`（`COMPONENTS` 注册表），模板不无条件加载。

**软约束（`/api/guide` 指导，agent 自觉遵循）**：
- 先讲「为什么」再讲「是什么」（黄金结构：定位→痛点→为什么→方案→验证）
- 每个技术决策必答三问（解决什么？为什么是它？不这么做呢？）
- 技术类必须有场景演练（小数据集、逐步计算、类比）
- 表述形态（EXPRESSION-GRAMMAR.md）：先判定表述类型再选组件；颜色语义全书同义；图必有图题图注

**自由空间（agent 发挥）**：
- 章节内的动效、交互、图表、可视化、自定义组件
- 在 `.wrap` 内部自由布局，可以加 `<style>` 和 `<script>`
- 不碰 CSS 变量和页面框架就行

## 内容方法论（写报告的核心规则）

1. **先为什么后是什么**：读者关心"帮我解决什么问题"，不是"你用了什么技术"
2. **黄金结构不可颠倒**：定位 → 场景痛点 → 为什么是这套方案 → 架构 → 验证
3. **反模式**：禁止定位后直接甩架构图、通篇技术名词无场景、讲"我做了什么"不讲"解决了什么"
4. **血泪教训**：2026-07 GameKB 汇报，领导反馈"只写方案和技术，没写原因和场景，理解不了优势"

## 开发

```bash
# 启动服务
python3 server.py

# 测试提交
curl -X POST http://localhost:9091/api/reports \
  -H 'Content-Type: application/json' \
  -d '{"title":"测试","slug":"test","tag":"测试","content":"<section class=\"reveal\"><div class=\"wrap\"><p>hello</p></div></section>"}'

# 部署到服务器后，Nginx 同步到 /var/www/vicky/research/
# GitLab Pages 自动发布 public/ 目录
```

## 部署

- 服务器：`192.168.1.100`，systemd 服务 `ai-report.service`
- 内部访问：`http://192.168.1.100:9090/research/`（Nginx）
- 外部访问：`https://fatherplus.github.io/vicky/`（GitLab Pages）
- 仓库：`https://github.com/fatherplus/vicky`
