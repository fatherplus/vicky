---
name: vicky-writer
description: 当用户要求把 AI 调研结果发布到 Vicky 知识平台、撰写向上汇报的决策简报、或为项目编写技术方案 / 架构文档并归档到项目区时使用
---

# Vicky Writer

向 Vicky 知识平台提交内容：agent 写 HTML 片段，平台负责渲染、发布、归档；
`category=research` 的长文还会被蒸馏进知识库供后续查询。**无 MCP，一切走直接 HTTP。**

## 三个工作流，先选 category

| 工作流 | category | 沉淀去向 | 模板默认 |
|--------|----------|----------|----------|
| 技术调研长文 | `research` | 进知识库（L2 蒸馏） | `book` |
| 临时简报 | `brief` | 用完即弃 | `brief` |
| 项目文档 | `tech-solution` | 归项目区（+`project`） | `book` |

## 核心流程

1. `GET /api/guide` — 读写作规范（HTML 结构、门禁红线、禁止清单，动笔前必读）
2. `GET /api/narratives` — 选叙事方式（7 种章节组织法）
3. `POST /api/validate` — dry 预检，`violations` 必改，`warnings` 自觉修订
4. `POST /api/reports` — 提交；同 `slug` 再次 POST = 修订
5. 项目架构 = 项目面板（不走报告、不走丛书）：`PUT /api/arch/{project}` 提交骨架、`PUT /api/arch/{project}/module/{id}` 写模块正文、`GET /api/arch/{project}/search` 搜模块——详见 `GET /api/guide`「架构导航器」

```bash
curl -s http://192.168.12.15:9093/api/guide
curl -s http://192.168.12.15:9093/api/narratives
```

## 提交字段

- `category` — 强烈建议显式指定（不填默认 `research`，易与真实意图不符）
- `narrative` — 选填，取值见 `/api/narratives`
- `project` — **项目文档必填**，归入项目区聚合
- `template` — 选填，按分类默认
- 完整字段、curl 示例与门禁红线（裸 table、cmp-table 无结论、弃用类名等 400 拒收项）见 `GET /api/guide`

## .vicky 项目联动

项目仓库根目录放 `.vicky` 两行文件，投稿时读它自动带 `project` 与 `endpoint`：

```
project=<项目slug>
endpoint=http://192.168.12.15:9093
```

- `project` 需先 `POST /api/projects` 注册（`GET /api/projects` 查看已建项目）
- 未注册的 project 投稿时给 warning，不拒收；`research` / `brief` 类 project 非必填

## 反模式

- ❌ 只写方案不写原因场景——读者是上级，关心值多少、推荐什么
- ❌ 定位后直接甩架构图、通篇技术名词无场景
- ✅ 结论先行 + 量化结果 + 给选择题不给问答题
