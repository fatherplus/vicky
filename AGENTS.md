# AGENTS.md — Vicky 项目上下文

## 这是什么

个人知识平台：任何 AI Agent 调研完一个技术后，把内容 POST 过来，平台自动套用统一的"书"风格渲染、发布、归档，并经 L0-L3 蒸馏成可持续演化的知识 Wiki。**2026-08-12 产品重构**：内容按「4 大分类骨架（research / brief / tech-solution / arch-doc）× 叙事方式 × 统一视觉」两层模型组织，归档（知识库 / 项目区 / 临时）与模板正交；agent 交互走 `skill/vicky-writer` + 直接 HTTP（MCP 已删除）；后端为 FastAPI，知识库支持人工审核（软下架 / 硬删除 / 单条知识状态）。

**核心问题**：不同 agent、不同时间写的报告，风格五花八门；研究结论散落在单篇报告里，难以被后续 Agent 直接复用。
**解法**：视觉 taste 由 server 端模板强制（agent 碰不到 CSS）；内容 taste 分三层——表述形态由 server 门禁强制（裸表格/无结论对比直接拒收），语义词汇由表述规范约束，框内的画完全放开。`/api/guide` 暴露写作规范。知识层由 L2 蒸馏沉淀、L3 反馈回灌，逐步长成可供 Agent 查询的知识服务。

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
| L1 表述层 | 门禁→模板→HTML+MD 孪生报告 + 索引页 + 首页门户 + 项目页 | `public/reports/` + sqlite reports 表 |
| L2 知识层 | knowledge Wiki（LLM 编译，输入 .md + adopted 反馈） | `knowledge/{domain}/{topic}/overview.md` |
| L3 回写层 | 使用账本 + 仲裁 → 采纳反馈回灌 L2 | sqlite feedbacks 表 |

**职责分离**：app（`vicky/web.py`）自伺服全部静态文件（public/ 根级直出，`/research/*` 旧前缀兼容保留）+ `/api/*` 业务端点；Nginx 退化为可选纯反向代理。

## 文件地图

### 后端包 `vicky/`

| 文件 | 角色 | 层 |
|------|------|----|
| `vicky/config.py` | 路径、常量、端口/绑定地址（argv[1]/[2]）、REPORT_CATEGORIES / LEGACY_DOMAIN_TO_CATEGORY / NARRATIVES、DESIGN_DOC_SLUG | — |
| `vicky/store.py` | sqlite3 唯一 DB 出口（建表、连接、查询封装） | — |
| `vicky/l0_ingest.py` | 收提交 → 快照存档 + 入库登记 | L0 |
| `vicky/l1_publish.py` | 快照 → 门禁 → 模板 → HTML+MD + 索引 + 首页门户 + 项目页 + 丛书 | L1 |
| `vicky/l2_distill.py` | .md → knowledge Wiki（LLM 编译 / 规则兜底） | L2 |
| `vicky/l3_feedback.py` | 使用回写账本 + 仲裁 + 采纳进 L2 的来源组装 | L3 |
| `vicky/ui.py` | HTML 片段构建器（目录行/知识卡等循环标记的唯一出处） | — |
| `vicky/curate.py` | 审核治理：软下架/硬删除级联 + 知识条目状态 + 审核视图 | L3 层 |
| `vicky/knowledge_query.py` | 知识库 FTS 三阶段检索（召回→打分→预算装包），`GET /api/knowledge?q=` 的内核 | — |
| `vicky/web.py` | FastAPI 薄路由层：每端点小函数 + 静态自伺服（根级直出 + `/research/*` 兼容） | — |
| `vicky/cli.py` | backfill / render / distill / judge / hide / delete / audit 命令入口 | — |

依赖方向严格单向：`web → curate/l3 → l2 → l1 → l0 → store`，禁止反向。L2 编译时直查 feedbacks 表取 adopted 条目（不 import l3_feedback），防环依赖。

### 旧入口（shim，指向包）

| 文件 | 角色 |
|------|------|
| `server.py` | shim → `vicky.web` |
| `html_to_md.py` | shim → `vicky.html_to_md` |
| `distill.py` | shim → `vicky.l2_distill` |

### 前端

| 路径 | 角色 |
|------|------|
| `public/reports/` | 所有已发布报告（`YYYY-MM-DD-slug.html` + `.md` 孪生），只增不改 |
| `public/assets/` | 设计系统：`book-style.css`（唯一 CSS 来源）、`index.css`、`knowledge.css`、`components/`（mermaid / arch-flow 等按需注入） |
| `public/home.html` | 首页门户（server 自动生成：人读五入口 + Agent 提交区 + 计数，不要手改） |
| `public/index.html` | 索引页（server 自动生成，不要手改） |
| `templates/{book,brief,arch-overview,arch-node,card}/` | 注册制报告模板（template.html + manifest.json） |
| `views/` | 平台整页模板（`home.html`、`index.html`、`knowledge.html`、`design.html`），纯 HTML + `__占位符__` |

### 数据

| 路径 | 角色 |
|------|------|
| `data/vicky.db` | sqlite 数据库（submissions / reports / feedbacks 三表），WAL 模式 |
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
| `skill/NARRATIVES.md` | 叙事方式选型库——7 种叙事的章节骨骼与选型决策表（`GET /api/narratives`） |
| `skill/vicky-writer/SKILL.md` | 外部 agent 投稿技能（2026-08-12 起替代 MCP：按需触发 + 直接 HTTP） |
| `scripts/nginx-research.conf` | 个人环境 Nginx 配置（纯反代） |
| `scripts/nginx-xlab.conf` | xlab-test Nginx 配置（纯反代） |
| `scripts/deploy.sh` | 个人环境部署（逐项内容级 rsync + backfill + Nginx 重载；macOS openrsync 目录级传输会静默跳过，勿改回批量） |
| `scripts/deploy-xlab.sh` | xlab-test 部署 |
| `scripts/backfill_md.py` | 存量报告补生成 .md（`--force` 重生成） |
| `tests/` | stdlib unittest |
| `docs/superpowers/specs/` | 历次已批准设计规格（内容分类 / 首页根级化 / L0-L3 等），改动前先读相关 spec |
| `convert_to_book.py` | 一次性脚本：旧格式报告 → 书风格 |

## API

### HTTP（唯一入口——agent 经 skill/vicky-writer 直接调用）

```
POST /api/reports                    创建/修订报告（同 slug upsert；category/narrative/project 三字段显式指定）
POST /api/validate                   预检（violations/warnings/components，不落盘）
POST /api/templates                  创建模板（provisional；门禁：占位符/token/契约）
POST /api/knowledge/feedback         L3 写回（evidence 必填，topic 必须已存在）
POST /api/knowledge/feedback/{id}/judge  人工裁决
GET  /api/reports                    列出所有报告
GET  /api/knowledge                  知识库（?domain=&topic= 查单页；不带参列全部；?q= FTS 检索）
GET  /api/knowledge/audit            知识条目审核视图（?topic=，含 hidden）
POST /api/knowledge/items/{id}/status  单条知识 active/hidden
POST /api/reports/{slug}/hide        软下架/恢复（body {"hidden": bool}，级联知识条目）
POST /api/reports/{slug}/delete      硬删除（L0+文件+DB+知识条目级联，不可逆）
GET  /api/narratives                 叙事方式选型库（markdown）
GET  /api/projects                   项目空间清单（已建项目元信息 + 报告聚合计数/最新日期）
POST /api/projects                   先建项目（body {name, slug?, description?}；slug 缺省由 name 生成；重复拒收）
GET  /api/knowledge/feedback         账本可查（?topic=&status=）
GET  /api/guide                      写作指南（markdown）
GET  /api/skill                      下载写作指南（.md 附件）
GET  /api/template                   查看 HTML 模板（?name=，默认 book）
GET  /api/templates                  模板目录
GET  /api/design                     设计 token 总纲
GET  /api/design.css                 设计 CSS 资源包
GET  /api/principles                 叙事宪法（markdown）
GET  /api/health                     健康检查
GET  /research/*                     静态自伺服兼容入口
```

### Agent 接入（Skill + HTTP，2026-08-12 起替代 MCP）

agent 触发 `skill/vicky-writer/SKILL.md` 后直接打 HTTP 端点，无常驻协议开销：

| 动作 | 端点 |
|---|---|
| 读写作规范 | `GET /api/guide`（`skill/AGENT-GUIDE.md`） |
| 选叙事方式 | `GET /api/narratives`（`skill/NARRATIVES.md`，7 种叙事选型库） |
| 看模板目录 | `GET /api/templates` |
| 预检 | `POST /api/validate` |
| 投稿 | `POST /api/reports`（category + narrative + project 显式指定） |
| 查知识 | `GET /api/knowledge?q=`（预算内片段流 + 引用 ID） |
| 写反馈 | `POST /api/knowledge/feedback`（L3 使用回写） |

人工裁决（judge / hide / delete）不经 agent——审核权在人。

**报告李生 .md**：`POST /api/reports` 写 `reports/{slug}.html` 同时生成 `reports/{slug}.md`（`html_to_md.py` 确定性转换，体积约 1/4）。人读 `.html`，AI 消费给 `.md` 链接（省 token ~70%）。存量补生成：`python3 scripts/backfill_md.py`。

**category 骨架（2026-08-12 重构 v2：domain 语义已彻底删除）**：`category` 枚举 `research`（技术调研长读，唯一进知识库蒸馏）/`brief`（决策简报/汇报，用完即弃）/`tech-solution`（技术方案，归项目区）/`arch-doc`（项目架构详情，归项目区）。旧 `domain` 字段与 `LEGACY_DOMAIN_TO_CATEGORY` 映射已从代码/schema 全部删除（破坏性清理，需代码定案后重蒸馏）。`narrative` 为叙事方式（自由文本，选型见 `/api/narratives`），`project` 关联「先建项目」的 slug（见下）。`tech-solution` 内容出现超过约 15 行代码块给 warning「方案不应包含实施代码」。`images: [{name, b64}]` 随报告上传截图，落盘 `public/assets/img/{slug}/`，HTML 里只留链接。

**先建项目 + `.vicky` 联动（2026-08-12 v2）**：项目是一等公民——先 `POST /api/projects`（或 CLI `python3 -m vicky.cli project --create`）建项目（`projects` 表：slug/name/description/created_at），再让报告 `project=<slug>` 归档进去。本地 agent 在项目仓库根目录放 `.vicky` 文件（两行：`project=<slug>` / `endpoint=http://192.168.12.15:9093`），`skill/vicky-writer` 读它自动带 project 投稿。投稿带未注册 project 返回 warning（不拒收）。

**知识库呈现（2026-08-12 v2：B 方案 Wiki 词条 + 轻索引）**：`knowledge/{topic}/overview.md` 扁平存储（专栏 category 存 overview.md 内，不做专栏目录层级）。蒸馏时每 topic 静态生成词条全文页 `public/knowledge/{topic}.html`；知识库首页 `public/knowledge/index.html` 是轻索引（每 topic 一行：标题+一句话结论+来源数+信任徽章，按专栏 ai/infra/eng/ops/design 分组锚点），点标题进词条页。蒸馏提取只抽提炼后的结论/关键数据/陷阱，不搬运整段。

**审核治理**：报告两级操作——软下架（`hidden`，索引/项目页/蒸馏全部隐藏，可恢复）与硬删除（L0 快照 + 文件 + DB 行 + 关联知识条目级联物理删，不可逆）。知识条目独立状态 active/hidden，审核视图 `GET /api/knowledge/audit`。CLI：`python3 -m vicky.cli hide/delete/audit`。

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
- `category=tech-solution` 内容出现超过约 15 行代码块——「方案不应包含实施代码」（止步于架构与表结构示意）

重量级渲染资源（mermaid / arch-flow）由 server 检测 HTML 契约后按篇注入 `<head>`（`COMPONENTS` 注册表），模板不无条件加载。

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
# 依赖（2026-08-12 起：FastAPI 换壳）
pip install -r requirements.txt    # fastapi + uvicorn + httpx(测试用)

# 启动服务（自伺服静态文件 + API）
python3 -m vicky.web [port] [host]  # 默认 9091 / 127.0.0.1，位置参数

# CLI 离线操作
python3 -m vicky.cli backfill [--force]    # 存量报告 → L0 快照（一次性）
python3 -m vicky.cli render --all          # L0 → L1 全量重渲染
python3 -m vicky.cli render --slug <slug>  # 单篇重渲染
python3 -m vicky.cli distill [--clean] [--dry-run]  # L2 蒸馏
python3 -m vicky.cli judge                  # LLM 批量初裁 pending 反馈
python3 -m vicky.cli hide --slug X          # 软下架（restore 恢复）
python3 -m vicky.cli delete --slug X --yes  # 硬删除（级联，不可逆）
python3 -m vicky.cli audit [--topic X]      # 知识条目审核视图
python3 -m vicky.cli project --create --name X [--slug Y] [--desc Z]  # 先建项目
python3 -m vicky.cli project --list         # 列项目（元信息 + 报告聚合计数）

# 测试
python3 -m pytest tests/ -q

# 冒烟
curl http://localhost:9091/api/health
```

## 部署

### 本地开发

- `python3 -m vicky.web` 启动，自伺服全部内容
- 直连 `http://localhost:9091/` 即可浏览（首页门户；`/reports/*`、`/assets/*`、`/design.html`、`/knowledge` 根级直出，`/research/*` 旧前缀兼容保留）
- Nginx 不需要——app 内置静态文件伺服

### 个人环境（192.168.1.100）

- systemd 服务 `vicky.service`，`ExecStart=python3 -m vicky.web 9093 0.0.0.0`，绑定 0.0.0.0:9093（直连正门）
- Nginx 9090 纯反代：`/research/` 与 `/api/` 全部 `proxy_pass http://127.0.0.1:9093`（`/research/` 为兼容入口；9090 上其他目录不动）
- 内部访问正门：`http://192.168.1.100:9093/`（含首页门户，Nginx 不经手）
- 兼容入口：`http://192.168.1.100:9090/research/`（Nginx → app 9093）
- 外部访问：`https://fatherplus.github.io/vicky/`（GitLab Pages）
- 仓库：`https://github.com/fatherplus/vicky`
- 部署脚本：`scripts/deploy.sh`（rsync 同步代码 + Nginx 重载；排除 `data/` 保留远端快照）

### 公用测试环境（xlab-test / 192.168.1.200）

- systemd 服务 `vicky.service`，绑定 127.0.0.1:9091
- Nginx 纯反向代理：端口 9092 → `proxy_pass http://127.0.0.1:9091`
- 内网访问：`http://192.168.1.200:9092/research/`
- 外网访问：`http://47.97.51.69:9092/research/`
- 路径：`/opt/vicky`
- 部署脚本：`scripts/deploy-xlab.sh`（同步代码 + Nginx 配置，排除 `data/` 保留远端数据）
- 用途：公用实例，供团队 agent 提交报告；数据独立，不与个人环境混用

### GitLab Pages

- `public/` 目录自动发布为静态站点
- 不受 server 部署影响——Pages 与 app 独立
