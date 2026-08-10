# AGENTS.md — ai-report 项目上下文

## 这是什么

集中式技术研究报告平台。任何 AI Agent 研究完一个技术后，把内容 POST 过来，平台自动套用统一的"书"风格渲染、发布、归档。

**核心问题**：不同 agent、不同时间写的报告，风格五花八门。
**解法**：视觉 taste 由 server 端模板强制（agent 碰不到 CSS）；内容 taste 分三层——表述形态由 server 门禁强制（裸表格/无结论对比直接拒收），语义词汇由表述规范约束，框内的画完全放开。`/api/guide` 暴露写作规范。

## 架构

```
agent 写 HTML 内容 → POST /api/reports → L0 不可变快照存档（data/l0/）
                                              ↓
                                     L1 门禁 → 模板渲染 → public/reports/（HTML+MD 孪生）
                                              ↓
                                     L2 蒸馏 → knowledge/ Wiki（LLM 编译）
                                              ↓
                                     L3 反馈回灌 → 使用账本 + 仲裁 → 采纳进 L2
```

**L0-L3 四层数据管线**（每层产物可由下层再生）：

| 层 | 职责 | 存储 |
|----|------|------|
| L0 原始数据层 | 提交快照（不可变档案） | `data/l0/{slug}/{rev}/submission.json` + sqlite submissions 表 |
| L1 表述层 | 门禁→模板→HTML+MD 孪生报告 + 索引页 | `public/reports/` + sqlite reports 表 |
| L2 知识层 | knowledge Wiki（LLM 编译，输入 .md + adopted 反馈） | `knowledge/{domain}/{topic}/overview.md` |
| L3 回写层 | 使用账本 + 仲裁 → 采纳反馈回灌 L2 | sqlite feedbacks 表 |

**职责分离**：app（`ai_report/web.py`）自伺服全部 `/research/*` 静态文件 + `/api/*` 业务端点；Nginx 退化为可选纯反向代理。

## 文件地图

### 后端包 `ai_report/`

| 文件 | 角色 | 层 |
|------|------|----|
| `ai_report/config.py` | 路径、常量、端口、DOMAINS、DESIGN_DOC_SLUG | — |
| `ai_report/store.py` | sqlite3 唯一 DB 出口（建表、连接、查询封装） | — |
| `ai_report/l0_ingest.py` | 收提交 → 快照存档 + 入库登记 | L0 |
| `ai_report/l1_publish.py` | 快照 → 门禁 → 模板 → HTML+MD + 索引 + 卡片墙 + 丛书 | L1 |
| `ai_report/l2_distill.py` | .md → knowledge Wiki（LLM 编译 / 规则兜底） | L2 |
| `ai_report/l3_feedback.py` | 使用回写账本 + 仲裁 + 采纳进 L2 的来源组装 | L3 |
| `ai_report/ui.py` | HTML 片段构建器（目录行/知识卡等循环标记的唯一出处） | — |
| `ai_report/web.py` | 薄路由层：每端点小函数 + 静态自伺服（`/research/*`） | — |
| `ai_report/cli.py` | backfill / render / distill / judge 命令入口 | — |

依赖方向严格单向：`web → l3 → l2 → l1 → l0 → store`，禁止反向。L2 编译时直查 feedbacks 表取 adopted 条目（不 import l3_feedback），防环依赖。

### 旧入口（shim，指向包）

| 文件 | 角色 |
|------|------|
| `server.py` | shim → `ai_report.web` |
| `html_to_md.py` | shim → `ai_report.html_to_md` |
| `distill.py` | shim → `ai_report.l2_distill` |

### 前端

| 路径 | 角色 |
|------|------|
| `public/reports/` | 所有已发布报告（`YYYY-MM-DD-slug.html` + `.md` 孪生），只增不改 |
| `public/assets/` | 设计系统：`book-style.css`（唯一 CSS 来源）、`index.css`、`knowledge.css`、`components/`（mermaid 等按需 JS） |
| `public/index.html` | 索引页（server 自动生成，不要手改） |
| `public/design.html` | 前端卡片墙页（server 自动生成，domain=design 卡片聚合，不要手改） |
| `templates/{book,brief,arch-overview,arch-node,card}/` | 注册制报告模板（template.html + manifest.json） |
| `views/` | 平台整页模板（`index.html`、`knowledge.html`、`design.html`），纯 HTML + `__占位符__` |

### 数据

| 路径 | 角色 |
|------|------|
| `data/ai-report.db` | sqlite 数据库（submissions / reports / feedbacks 三表），WAL 模式 |
| `data/l0/{slug}/{rev:04d}/` | 不可变快照档案（submission.json + img/） |
| `knowledge/tech/{topic}/` | 蒸馏产出的知识 Wiki（overview.md；现只蒸 tech） |

### 规范与部署

| 文件 | 角色 |
|------|------|
| `skill/AGENT-GUIDE.md` | 面向外部 agent 的写作指南（`/api/guide` 返回） |
| `skill/SKILL.md` | 内部 skill（pi 用），含部署流程和完整方法论 |
| `skill/BOOK-STYLE.md` | 书风格设计硬约束（字体/配色/版式/动效/禁止清单） |
| `skill/EXPRESSION-GRAMMAR.md` | 表述规范——这本书的「内容语法」 |
| `skill/NARRATIVE-PRINCIPLES.md` | 叙事宪法——模板无关的不变量（`GET /api/principles`） |
| `scripts/nginx-research.conf` | 个人环境 Nginx 配置（纯反代） |
| `scripts/nginx-xlab.conf` | xlab-test Nginx 配置（纯反代） |
| `scripts/deploy.sh` | 个人环境部署（rsync 同步 + Nginx 重载） |
| `scripts/deploy-xlab.sh` | xlab-test 部署 |
| `scripts/backfill_md.py` | 存量报告补生成 .md（`--force` 重生成） |
| `tests/` | stdlib unittest |
| `convert_to_book.py` | 一次性脚本：旧格式报告 → 书风格 |

## API

```
POST /api/reports                    创建/修订报告（同 slug upsert）
POST /api/validate                   预检（violations/warnings/components，不落盘）
POST /api/templates                  创建模板（provisional；门禁：占位符/token/契约）
POST /api/knowledge/feedback         新：L3 写回（evidence 必填，topic 必须已存在）   body: {topic, domain, agent, evidence, opinion, cited?}
POST /api/knowledge/feedback/{id}/judge  新：人工裁决                                body: {verdict: "adopt"|"reject", note?}
GET  /api/reports                    列出所有报告
GET  /api/knowledge                  知识库（?domain=&topic= 查单页；不带参列全部；含 feedback_count/feedback_last_used）
GET  /api/knowledge/feedback         新：账本可查（?topic=&status=）
GET  /api/guide                      写作指南（markdown）
GET  /api/skill                      下载写作指南（.md 附件）
GET  /api/template                   查看 HTML 模板（?name=，默认 book）
GET  /api/templates                  模板目录
GET  /api/design                     设计 token 总纲（design.md 的 .md 孪生，稳定别名）
GET  /api/design.css                 设计 CSS 资源包（下载 book-style.css）
GET  /api/principles                 叙事宪法（markdown）
GET  /api/health                     健康检查
GET  /research/*                     静态自伺服（reports / assets / knowledge / index）
```

**报告李生 .md**：`POST /api/reports` 写 `reports/{slug}.html` 同时生成 `reports/{slug}.md`（`html_to_md.py` 确定性转换，体积约 1/4）。人读 `.html`，AI 消费给 `.md` 链接（省 token ~70%）。存量补生成：`python3 scripts/backfill_md.py`。

**domain 分区**：`domain` 枚举 `tech`（默认）/`design`/`ephemeral`/`arch`，决定蒸馏路由——只有 `tech` 进知识库蒸馏，`design`（前端卡片素材）/`ephemeral`（临时报告）/`arch`（架构站）均跳过。`design` 报告聚合成卡片墙 `public/design.html`；`arch` 报告为丛书机制多页站（`{project}-arch` 丛书：总览卷 + 节点卷）。`images: [{name, b64}]` 随报告上传截图，落盘 `public/assets/img/{slug}/`，HTML 里只留链接。

**L3 仲裁流**：反馈是带证据的陈述，不是分数；采纳是裁决，不是算术。状态机 pending → adopted | rejected，可翻案。裁决权始终可人工接管（judged_by 记 `human:{ip}`）。采纳后 feedback 作为 type=feedback 来源与报告平级进 L2 编译。证据为空直接拒收。

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
- `arch-node` 节点卷缺三段——h2 必须依序含「输入与输出 / 内部工作流 / 架构方案」

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
# 启动服务（自伺服静态文件 + API）
python3 -m ai_report.web [port] [host]  # 默认 9091 / 127.0.0.1，位置参数

# CLI 离线操作
python3 -m ai_report.cli backfill [--force]    # 存量报告 → L0 快照（一次性）
python3 -m ai_report.cli render --all          # L0 → L1 全量重渲染
python3 -m ai_report.cli render --slug <slug>  # 单篇重渲染
python3 -m ai_report.cli distill [--clean] [--dry-run]  # L2 蒸馏
python3 -m ai_report.cli judge                  # LLM 批量初裁 pending 反馈

# 测试
python3 -m pytest tests/ -q

# 冒烟
curl http://localhost:9091/api/health
```

## 部署

### 本地开发

- `python3 -m ai_report.web` 启动，自伺服全部内容
- 直连 `http://localhost:9091/` 即可浏览（首页门户；`/reports/*`、`/assets/*`、`/design.html`、`/knowledge` 根级直出，`/research/*` 旧前缀兼容保留）
- Nginx 不需要——app 内置静态文件伺服

### 个人环境（192.168.1.100）

- systemd 服务 `ai-report.service`，`ExecStart=python3 -m ai_report.web 9093 0.0.0.0`，绑定 0.0.0.0:9093（直连正门）
- Nginx 9090 纯反代：`/research/` 与 `/api/` 全部 `proxy_pass http://127.0.0.1:9093`（`/research/` 为兼容入口；9090 上其他目录不动）
- 内部访问正门：`http://192.168.1.100:9093/`（含首页门户，Nginx 不经手）
- 兼容入口：`http://192.168.1.100:9090/research/`（Nginx → app 9093）
- 外部访问：`https://fatherplus.github.io/vicky/`（GitLab Pages）
- 仓库：`https://github.com/fatherplus/vicky`
- 部署脚本：`scripts/deploy.sh`（rsync 同步代码 + Nginx 重载；排除 `data/` 保留远端快照）

### 公用测试环境（xlab-test / 192.168.1.200）

- systemd 服务 `ai-report.service`，绑定 127.0.0.1:9091
- Nginx 纯反向代理：端口 9092 → `proxy_pass http://127.0.0.1:9091`
- 内网访问：`http://192.168.1.200:9092/research/`
- 外网访问：`http://47.97.51.69:9092/research/`
- 路径：`/opt/ai-report`
- 部署脚本：`scripts/deploy-xlab.sh`（同步代码 + Nginx 配置，排除 `data/` 保留远端数据）
- 用途：公用实例，供团队 agent 提交报告；数据独立，不与个人环境混用

### GitLab Pages

- `public/` 目录自动发布为静态站点
- 不受 server 部署影响——Pages 与 app 独立
