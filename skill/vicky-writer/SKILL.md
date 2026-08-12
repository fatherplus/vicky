---
name: vicky-writer
description: >-
  向 Vicky 知识平台提交技术内容：技术调研长文（进知识库）、临时简报（用完即弃）、
  项目方案 / 架构文档（归项目区）。触发条件：用户要求把 AI 调研结果发布到 Vicky 平台、
  给上级写汇报简报、为项目写技术方案或架构文档、或需要让三方 agent 通过 .md 契约消费方案。
  平台无 MCP——一切交互走直接 HTTP（POST /api/reports、POST /api/validate）。
  完整提交契约见 GET /api/guide（即 skill/AGENT-GUIDE.md），叙事选型见 GET /api/narratives。
---

# Vicky Writer —— 向 Vicky 平台提交内容

Vicky 是个人知识平台：agent 把调研好的 HTML 内容 POST 过来，平台负责渲染、发布、归档；
`category=research` 的长文还会被 L2 蒸馏进知识库，供后续 agent 查询。**平台无 MCP**——
不调用任何 MCP 工具，一切走 HTTP。

## 三个工作流，先选一个

| 工作流 | category | 沉淀去向 | 模板默认 | 说明 |
|--------|----------|----------|----------|------|
| 技术调研长文 | `research` | **进知识库**（L2 蒸馏） | `book` | 完整理解一个技术，3000+ 字 |
| 临时简报 | `brief` | **用完即弃**，不污染检索 | `brief` | 结论先行、量化、读者即上级 |
| 项目文档 | `tech-solution` / `arch-doc` | **归项目区**（+ `project` 字段） | `book` / `arch-overview` | 技术方案 / 架构详情 |

> `design` 是存量 legacy 分类，**不再开放提交**。存量 `tech / ephemeral / arch` 已迁移为
> `research / brief / arch-doc`，提交时一律用新字段。

## 写作前：三步取料

1. **`GET /api/guide`** — 读写作规范（HTML 结构、组件库、门禁红线、禁止清单）
2. **`GET /api/narratives`** — 选叙事方式（7 种：章节怎么组织，由内容决定）
3. **`GET /api/templates`** — 看模板目录（默认 book / brief，都不适配才考虑自建）

```bash
curl -s http://192.168.12.15:9093/api/guide
curl -s http://192.168.12.15:9093/api/narratives
curl -s http://192.168.12.15:9093/api/templates
```

## 预检（先 dry 一把，再正式提交）

`POST /api/validate` 做 dry 校验：返回 `{ok, violations, warnings, components}`，**不落盘**。
`violations` 有内容就必须修（正式提交会 400）；`warnings` 是提醒（AI 腔词、figure 缺图注等），自觉修订。

```bash
curl -s -X POST http://192.168.12.15:9093/api/validate \
  -H 'Content-Type: application/json' \
  -d '{"title": "…", "slug": "…", "category": "research", "content": "<section…>"}'
```

## 提交：POST /api/reports

完整字段：`title` / `slug` / `category` / `content`（HTML 片段）+ 可选
`narrative` / `project` / `tag` / `template` / `subtitle` / `series` / `order` / `images`。

- `category` 强烈建议显式指定（research / brief / tech-solution / arch-doc）——不填默认落 `research`，容易和真实意图不符
- `narrative` 选填，不填走默认；取值见 `GET /api/narratives`（如 `黄金五章` / `对比擂台` / `场景演练`）
- `project` 选填——**项目文档必填**，用于归入项目区聚合（如 `"project": "vicky"`）
- `template` 选填，不填按分类默认（research→book、brief→brief、tech-solution→book、arch-doc→arch-overview）
- 同 `slug` 再次 POST = 修订（覆盖原文件，保留原日期，索引显示「订」徽章）

```bash
curl -X POST http://192.168.12.15:9093/api/reports \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "向量数据库选型调研",
    "slug": "vector-db-selection",
    "category": "research",
    "narrative": "对比擂台",
    "tag": "向量检索",
    "template": "book",
    "subtitle": "按数据量级选，不追热点",
    "content": "<section class=\"reveal\"><div class=\"wrap\"><p class=\"section-label\">01 · 参战选手</p><h2>三个候选</h2><p>…</p></div></section>"
  }'
```

- **正式环境**：`http://192.168.12.15:9093`
- **本地开发**：`http://localhost:9091`

返回：`{"ok": true, "file": "...", "created": true, "components": [...], "warnings": [...], "url": ".../reports/..."}`

## MD 孪生约定（AI 之间通信用 .md）

每篇报告提交时自动生成同名 `.md`（`reports/{slug}.md`，体积约 HTML 的 1/4）。
**要把报告交给另一个 AI 执行 / 消费时，给 `.md` 链接而非 `.html`**——无视觉噪音、省 token ~70%。

- **tech-solution 的 `.md` 就是给三方 agent 的实现契约**：方案止步于架构与表结构示意，三方 agent 拿 .md 当输入去写代码。
- 人读用 `.html`，AI 读用 `.md`。报告间互链用 canonical 相对路径 `reports/{file}`。

## 门禁红线速查（正式提交 400 拒收）

- ❌ 裸 `<table>`——必须带 `data-table` 或 `cmp-table`
- ❌ `cmp-table` 无 `cmp-verdict`——**对比必须有结论**，表尾必须接 `怎么选 · VERDICT`
- ❌ 弃用类名（`.ladder-*` / `.quote-block` / `.concern-box` / `.phase`）——模板已删样式
- ❌ 丛书卷号重复——同 `series` 同 `order` 已被其他文件占用（upsert 本卷除外）
- ❌ `arch-node` 节点卷缺三段——h2 必须依序含「输入与输出 / 内部工作流 / 架构方案」
- ⚠️ **tech-solution 不得含实施代码**——方案讲"决定做什么、为什么"，到架构 + 表结构**示意层**为止；出现大段实施代码 server 给 warning 提醒，自觉删掉
- ⚠️ figure 缺图题图注、AI 腔词（赋能/闭环/打通/一站式/全方位/引领）、标题正文 emoji——warning 提醒，自觉修订

## 平台无 MCP，一切走 HTTP

Vicky **没有 MCP 服务器**。不要尝试连接 `mcp://` 或调用 `submit_report` 等工具——
用下面的直接 HTTP 请求即可。写作规范类资源也走 HTTP：

| 端点 | 说明 |
|------|------|
| `GET /api/guide` | 写作规范（即 AGENT-GUIDE.md） |
| `GET /api/narratives` | 叙事方式选型库（7 种） |
| `GET /api/templates` | 模板目录与 manifest |
| `GET /api/principles` | 叙事宪法（9 条契约不变量） |
| `GET /api/projects` | 已建项目清单（用于选择 project 字段值） |
| `POST /api/projects` | 新建项目（投稿前先注册，body: `{name, slug?, description?}`） |
| `POST /api/validate` | dry 预检（violations / warnings / components） |
| `POST /api/reports` | 提交 / 修订报告 |

## .vicky 文件约定（先建项目联动）

在项目仓库根目录放置 `.vicky` 文件，agent 投稿前读它自动获取 `project` 与 `endpoint`，
无需每次手动传：

```
# 格式（两行 key=value，顺序固定）：
project=<项目slug>
endpoint=http://192.168.12.15:9093
```

- `project`：项目 slug（需先 `POST /api/projects` 注册；`GET /api/projects` 查看已建项目）
- `endpoint`：Vicky 服务器地址（默认 `http://192.168.12.15:9093`）

agent 投稿流程：

```bash
# 1. 读 .vicky 拿 project 与 endpoint
PROJECT=$(grep -s '^project=' .vicky 2>/dev/null | cut -d= -f2-)
ENDPOINT=$(grep -s '^endpoint=' .vicky 2>/dev/null | cut -d= -f2-)
ENDPOINT=${ENDPOINT:-http://192.168.12.15:9093}

# 2. 预检（可选）
curl -s -X POST "$ENDPOINT/api/validate" \
  -H 'Content-Type: application/json' \
  -d "{\"title\": \"...\", \"slug\": \"...\", \"category\": \"tech-solution\", \"content\": \"...\"}"

# 3. 投稿（自动带 project）
curl -X POST "$ENDPOINT/api/reports" \
  -H 'Content-Type: application/json' \
  -d "{
    \"title\": \"...\",
    \"slug\": \"...\",
    \"category\": \"tech-solution\",
    \"project\": \"$PROJECT\",
    \"content\": \"...\"
  }"
```

`.vicky` 不存在的处理：缺省 endpoint 用 `http://192.168.12.15:9093`，project 留空
（`research` / `brief` 类投稿 project 非必填，仅 `tech-solution` / `arch-doc` 建议带）。
未建项目的 slug 投稿时 server 会返回 warning 提醒「项目未注册，建议先 POST /api/projects」，
不拒收——agent 可补建项目后再修订报告。

## 反模式提醒（血泪教训）

- ❌ 只写方案和技术，不写原因和场景——2026-07 GameKB 汇报教训："理解不了这套技术的优势"
- ❌ 定位之后直接甩架构图；通篇技术名词无场景
- ❌ 占位假数据（张三 / Acme / Lorem Ipsum）；标题正文 emoji
- ✅ 结论先行 + MECE；结果量化（"从 3 天缩到 4 小时"而非"提升了效率"）；给选择题不给问答题
