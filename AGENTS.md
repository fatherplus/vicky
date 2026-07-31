# AGENTS.md — ai-report 项目上下文

## 这是什么

集中式技术研究报告平台。任何 AI Agent 研究完一个技术后，把内容 POST 过来，平台自动套用统一的"书"风格渲染、发布、归档。

**核心问题**：不同 agent、不同时间写的报告，风格五花八门。
**解法**：视觉 taste 由 server 端模板强制（agent 碰不到 CSS）；内容 taste 分三层——表述形态由 server 门禁强制（裸表格/无结论对比直接拒收），语义词汇由表述规范约束，框内的画完全放开。`/api/guide` 暴露写作规范。

## 架构

```
agent 写 HTML 内容 → POST /api/reports → server 按名套模板（templates/） → 写入 public/reports/
                                          ↑                                    ↓
                                    视觉 taste 在这一步强制注入      Nginx alias 直读 public/ → 用户
```

**职责分离**：server.py 只做 API（127.0.0.1:9091），Nginx 只做静态文件（alias 直读 `public/`）+ 反代 `/api/`。不再双写。

## 文件地图

| 文件 | 角色 | 改它之前注意 |
|------|------|-------------|
| `server.py` | HTTP API 服务（报告提交/列表/指南/模板） | 纯 stdlib，无依赖 |
| `templates/` | 注册制模板：book（默认）/ brief；各含 template.html + manifest.json | 模板拥有结构不拥有视觉（视觉 token 在 `public/assets/book-style.css`） |
| `skill/AGENT-GUIDE.md` | 面向外部 agent 的写作指南（`/api/guide` 返回它） | 这是 agent 的唯一入口文档 |
| `skill/SKILL.md` | 内部 skill（pi 用），含部署流程和完整方法论 | 比 AGENT-GUIDE 更详细 |
| `skill/BOOK-STYLE.md` | 书风格设计硬约束（字体/配色/版式/动效/禁止清单） | 设计规范源头 |
| `skill/EXPRESSION-GRAMMAR.md` | 表述规范——这本书的「内容语法」（形态/语义/自由区） | 改组件时同步这里 |
| `skill/NARRATIVE-PRINCIPLES.md` | 叙事宪法——模板无关的不变量，模板创建的依据 | `GET /api/principles` 返回它；manifest 契约条目取自其 §3 |
| `public/reports/` | 所有已发布报告（`YYYY-MM-DD-slug.html`） | 只增不改 |
| `public/assets/` | 共享资产（book-style.css / index.css / components/mermaid/） | book-style.css 是唯一 CSS 来源 |
| `scripts/nginx-research.conf` | 个人环境 Nginx 配置（alias + /api/ 反代） | deploy.sh 安装 |
| `scripts/nginx-xlab.conf` | xlab-test Nginx 配置（9092 server block） | deploy-xlab.sh 安装 |
| `tests/` | stdlib unittest | 改门禁/资产时同步 |
| `public/index.html` | 索引页（server 自动生成，不要手改） | `build_index()` 生成 |
| `convert_to_book.py` | 存量迁移：旧格式报告 → 书风格 | 一次性脚本 |
| `html_to_md.py` | 平台转换器：报告 HTML → 紧凑 MD（提交时生成 .md 李生） | 纯 stdlib，封闭组件集确定性映射 |
| `distill.py` | 知识蒸馏器：报告 → knowledge/ Wiki（KSI 进化） | 独立脚本，不 import server |
| `scripts/backfill_md.py` | 存量报告补生成 .md（`--force` 重生成） | 一次性/可重复 |
| `taste-skill/` | 上游参考（clone 自 GitHub），不直接使用 | 只读参考 |

## API

```
POST /api/reports    创建/修订报告（同 slug upsert）  body: {title, slug, tag, subtitle?, series?, order?, template?, domain?, images?, content}
POST /api/validate   预检（violations/warnings/components，不落盘）
POST /api/templates  创建模板（创建即收录 provisional；门禁：占位符/token/契约）
GET  /api/reports    列出所有报告
GET  /api/knowledge  知识库（?domain=&topic= 查单页；不带参列全部）
GET  /api/guide      写作指南（markdown）
GET  /api/skill      下载写作指南（.md 附件）
GET  /api/template   查看 HTML 模板（?name=，默认 book）
GET  /api/templates  模板目录
GET  /api/principles 叙事宪法（markdown）
GET  /api/health     健康检查
```

**报告李生 .md**：`POST /api/reports` 写 `reports/{slug}.html` 同时生成 `reports/{slug}.md`（`html_to_md.py` 确定性转换，体积约 1/4）。人读 `.html`，AI 消费给 `.md` 链接（省 token ~70%）。存量补生成：`python3 scripts/backfill_md.py`。

**domain 分区**：`domain` 枚举 `tech`（默认）/`design`/`ephemeral`，决定蒸馏路由——`ephemeral` 不进知识库。`images: [{name, b64}]` 随报告上传截图，落盘 `public/assets/img/{slug}/`，HTML 里只留链接。蒸馏：`python3 distill.py`。

默认端口 9091。启动：`python3 server.py [port]（位置参数，默认 9091）`

## Taste 约束分层

**模板层（注册制，框架可变）**：
- 模板注册在 `templates/{name}/`（template.html + manifest.json），`POST /api/templates` 创建即收录（provisional）
- 模板拥有结构不拥有视觉：重定义 `:root` 视觉 token 被门禁拒收，调色板/字体由平台 `book-style.css` 拥有
- 叙事不变量由宪法约束（`skill/NARRATIVE-PRINCIPLES.md`，`GET /api/principles`）：manifest 契约条目必须取自 §3 ID 表

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
5. **结论先行 + MECE**（2026-07 融入向上汇报方法论）：每一层先讲结论（只读结论句也能拿到论证骨架）；论点互不重叠、完全穷尽；结果量化（"从 3 天缩到 4 小时"而非"提升了效率"）；给选择题不给问答题
6. **读者即上级**：agent 的调研文档本质是向上汇报——读者关心值多少、推荐什么、需要他决定什么，不关心做了多少

## 开发

```bash
# 启动服务
python3 server.py

# 测试提交
curl -X POST http://localhost:9091/api/reports \
  -H 'Content-Type: application/json' \
  -d '{"title":"测试","slug":"test","tag":"测试","content":"<section class=\"reveal\"><div class=\"wrap\"><p>hello</p></div></section>"}'

# 部署：Nginx alias 直读 public/，不再 cp 报告
# GitLab Pages 自动发布 public/ 目录
```

## 部署

### 个人环境（192.168.1.100）

- systemd 服务 `ai-report.service`，绑定 127.0.0.1:9091（仅本地）
- 内部访问：`http://192.168.1.100:9090/research/`（Nginx alias 直读 `public/`）
- 外部访问：`https://fatherplus.github.io/vicky/`（GitLab Pages）
- 仓库：`https://github.com/fatherplus/vicky`
- 部署脚本：`scripts/deploy.sh`（安装 Nginx 配置）

### 公用测试环境（xlab-test / 192.168.1.200）

- systemd 服务 `ai-report.service`，绑定 127.0.0.1:9091（仅本地）
- 内网访问：`http://192.168.1.200:9092/research/`（Nginx alias 直读 `public/`）
- 外网访问：`http://47.97.51.69:9092/research/`
- 路径：`/opt/ai-report`
- 部署脚本：`scripts/deploy-xlab.sh`（同步代码 + Nginx 配置，保留远端报告数据）
- 用途：公用实例，供团队 agent 提交报告；数据独立，不与个人环境混用
