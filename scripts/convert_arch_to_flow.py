#!/usr/bin/env python3
"""四篇旧架构方案 → arch-overview + arch-flow 节点架构站（upsert 同 slug）。
原文长文保留在 L0 快照；发布版变为：定位 → 全局 flow → 模块索引，模块详情在 flow 抽屉。
用法：python3 scripts/convert_arch_to_flow.py [base_url]"""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.1.100:9093"

EDGE3 = {
    "main": {"color": "#0C4A6E", "name": "请求 / 数据 / 控制"},
    "async": {"color": "#6E7278", "dash": "5,4", "name": "异步 / 依赖 / 持久化"},
    "warn": {"color": "#A63A2E", "dash": "5,4", "name": "拦截 / 拒绝"},
}

# ------------------------------------------------------------ GameKB
GAMEKB = {
    "layers": ["生产层", "入库层", "抽取判断", "存储层", "召回路由", "双通道召回", "融合扩展", "消费层"],
    "nodes": [
        {"id": "producer", "kind": "entry", "layer": 0, "label": "Markdown 文档", "sub": "标题约定结构 · 4 个人工 Meta 字段"},
        {"id": "ingest", "layer": 1, "label": "入库流水线", "sub": "解析建树 · 结构化切片 · 向量化", "module": "ingest"},
        {"id": "j-vocab", "kind": "judge", "layer": 2, "label": "实体在词表?", "sub": "受约束抽取", "module": "extract"},
        {"id": "review", "layer": 3, "label": "人工确认队列", "sub": "词表外实体 · 不入库"},
        {"id": "store", "kind": "store", "layer": 3, "label": "五存储", "sub": "文档库 · 节点树 · 图谱 · 向量 · 溯源", "module": "storage"},
        {"id": "j-route", "kind": "judge", "layer": 4, "label": "问关系吗?", "sub": "召回路由", "module": "retrieval"},
        {"id": "recall-v", "layer": 5, "label": "向量召回", "sub": "找相似"},
        {"id": "recall-g", "layer": 5, "label": "图谱召回", "sub": "找关系 · 邻居遍历"},
        {"id": "fuse", "layer": 6, "label": "融合排序", "sub": "depth 上下文扩展", "module": "retrieval"},
        {"id": "api", "layer": 7, "label": "消费 API", "sub": "/v1/retrieve · /v1/query", "module": "api"},
    ],
    "edges": [
        {"from": "producer", "to": "ingest", "label": "文档 + Meta", "type": "main"},
        {"from": "ingest", "to": "j-vocab", "label": "候选实体", "type": "main"},
        {"from": "j-vocab", "to": "store", "label": "词表内 · 入库", "type": "main"},
        {"from": "j-vocab", "to": "review", "label": "词表外", "type": "warn"},
        {"from": "store", "to": "j-route", "label": "查询", "type": "main"},
        {"from": "j-route", "to": "recall-v", "label": "否 · 相似", "type": "main", "side": "L"},
        {"from": "j-route", "to": "recall-g", "label": "是 · 关系", "type": "main", "side": "R"},
        {"from": "recall-v", "to": "fuse", "type": "main"},
        {"from": "recall-g", "to": "fuse", "type": "main"},
        {"from": "fuse", "to": "api", "label": "结构化知识", "type": "main"},
    ],
    "modules": {
        "ingest": {"label": "入库流水线", "purpose": "把 Markdown 变成节点树 + 向量 + 实体，标题即切分边界。",
                   "input": "Markdown 文档 + 4 个 Meta 字段", "output": "节点树 / 向量 / 候选实体",
                   "input_example": "# 麻将·番型\\n## 3.3 清一色 …（meta: game=mahjong）",
                   "logic": ["标题层级解析为节点树", "节点 = 最小存储单元", "切片即节点，不跨标题", "节点文本向量化"]},
        "extract": {"label": "受约束实体抽取", "purpose": "实体只能从既定词表选，抽不到就交人工，不让模型自由发挥。",
                    "input": "节点文本 + 实体词表", "output": "实体边 / 人工确认条目",
                    "decisions": [{"cond": "实体在词表", "to": "写图谱边"}, {"cond": "词表外", "to": "人工确认队列，不入库"}]},
        "storage": {"label": "五存储", "purpose": "五种存储各司其职，节点是共同锚点。",
                    "input": "入库产物", "output": "文档库 / 节点树 / 图谱 / 向量库 / 溯源索引",
                    "logic": ["节点 ID 贯穿五存储", "溯源索引保证答案有出处"]},
        "retrieval": {"label": "双通道检索", "purpose": "相似度找节点，关系找邻居，两条腿走路。",
                      "input": "查询文本", "output": "融合排序后的节点 + depth 级上下文",
                      "input_example": "清一色和混一色区别？",
                      "logic": ["向量召回相似节点", "图谱召回关系邻居", "融合排序", "depth 参数控制返回几级上下文"]},
        "api": {"label": "消费 API", "purpose": "消费方拿到结构化知识，不是一段话。",
                "input": "GET /v1/retrieve?q=…&depth=2", "output": "节点列表 + 出处 + 上下文",
                "output_example": '{"nodes":[{"id":"mahjong/fan/qingyise","score":0.87,"source":"…md"}]}'},
    },
}

# ------------------------------------------------------------ 企业知识库骨架
SKELETON = {
    "layers": ["契约层", "handler 层", "应用层", "流水线层", "基础设施层", "装配层"],
    "nodes": [
        {"id": "types", "kind": "store", "layer": 0, "label": "types/interfaces", "sub": "全部跨层契约 · 唯一真相", "module": "contracts"},
        {"id": "handler", "layer": 1, "label": "handler", "sub": "薄 · 参数绑定 / SSE 编排", "module": "handler"},
        {"id": "service", "layer": 2, "label": "application/service", "sub": "业务用例", "module": "service"},
        {"id": "pipe", "layer": 3, "label": "chat_pipeline", "sub": "插件链 · 检索到生成", "module": "pipeline"},
        {"id": "repo", "kind": "store", "layer": 4, "label": "repository", "sub": "GORM + retriever 注册表", "module": "repo"},
        {"id": "models", "layer": 4, "label": "models", "sub": "Chat / Embedder / Reranker"},
        {"id": "di", "layer": 5, "label": "container · dig", "sub": "Provide 装配", "module": "di"},
    ],
    "edges": [
        {"from": "handler", "to": "service", "label": "用例调用", "type": "main"},
        {"from": "service", "to": "pipe", "label": "插件链", "type": "main"},
        {"from": "pipe", "to": "repo", "label": "检索", "type": "main"},
        {"from": "service", "to": "models", "type": "main"},
        {"from": "types", "to": "handler", "label": "依赖", "type": "async", "side": "L"},
        {"from": "types", "to": "service", "label": "依赖", "type": "async"},
        {"from": "types", "to": "repo", "label": "依赖", "type": "async"},
        {"from": "di", "to": "handler", "label": "Provide 装配", "type": "async", "side": "R"},
    ],
    "modules": {
        "contracts": {"label": "契约集中", "purpose": "所有跨层接口放 types/interfaces，层与层只依赖契约不依赖实现。",
                      "input": "各层接口定义", "output": "interfaces 包", "logic": ["删掉任何功能模块契约仍成立"]},
        "handler": {"label": "薄 handler", "purpose": "只做参数绑定与 SSE 编排，不写业务。", "input": "HTTP 请求", "output": "用例调用"},
        "service": {"label": "业务用例", "purpose": "一个用例一个 service，编排 pipeline 与 repository。", "input": "用例参数", "output": "领域结果"},
        "pipeline": {"label": "插件流水线", "purpose": "检索→重排→生成做成插件链，可插拔可单测。", "input": "用例上下文", "output": "SSE 流",
                     "logic": ["每个插件独立验收", "三档功能按插件开关"]},
        "repo": {"label": "注册表适配器", "purpose": "retriever 注册表 + GORM repository，换实现不动上层。", "input": "领域调用", "output": "持久化/召回结果"},
        "di": {"label": "DI 装配", "purpose": "container·dig 把实现注入契约，装配点唯一。", "input": "实现注册", "output": "可运行对象图"},
    },
}

# ------------------------------------------------------------ xknow 消费层
XKNOW = {
    "layers": ["消费者", "凭据判断", "服务层", "召回路由", "存储层"],
    "nodes": [
        {"id": "c-web", "kind": "entry", "layer": 0, "label": "网站 UI", "sub": "既有会话凭据"},
        {"id": "c-mcp", "kind": "entry", "layer": 0, "label": "进程内 MCP", "sub": "三个工具 · 三种消费深度", "module": "mcp"},
        {"id": "c-api", "kind": "entry", "layer": 0, "label": "外部系统", "sub": "REST + API Key"},
        {"id": "j-auth", "kind": "judge", "layer": 1, "label": "凭据有效?", "sub": "双凭据中间件", "module": "keys"},
        {"id": "deny", "layer": 2, "label": "401 拒绝", "sub": "Key 死在可信会话里"},
        {"id": "svc", "layer": 2, "label": "收束服务层", "sub": "五个新端点", "module": "service"},
        {"id": "j-ent", "kind": "judge", "layer": 3, "label": "传实体吗?", "sub": "调用方传入 · 不服务端抽", "module": "multi"},
        {"id": "store", "kind": "store", "layer": 4, "label": "多库", "sub": "向量 + 图谱 · 同库两路", "module": "multi"},
    ],
    "edges": [
        {"from": "c-web", "to": "j-auth", "label": "session", "type": "main"},
        {"from": "c-mcp", "to": "j-auth", "label": "进程内可信", "type": "main"},
        {"from": "c-api", "to": "j-auth", "label": "sha256(Key)", "type": "main"},
        {"from": "j-auth", "to": "svc", "label": "有效", "type": "main"},
        {"from": "j-auth", "to": "deny", "label": "无效 · 吊销", "type": "warn"},
        {"from": "svc", "to": "j-ent", "type": "main"},
        {"from": "j-ent", "to": "store", "label": "传 · 向量+图谱组合", "type": "main", "side": "R"},
        {"from": "j-ent", "to": "store", "label": "不传 · 向量单路", "type": "main", "dx": -22},
    ],
    "modules": {
        "keys": {"label": "API Key 凭据体系", "purpose": "Key 生在可信会话里，死在可信会话里；存哈希用 sha256 不用 bcrypt。",
                 "input": "POST/GET/DELETE /api/v1/api-keys", "output": "裁决 { 有效 | 401 | 吊销 }",
                 "input_example": "Authorization: Bearer xk_a1b2…（明文仅创建时返回一次）",
                 "decisions": [{"cond": "sha256 命中且未吊销", "to": "放行"}, {"cond": "未命中/已吊销", "to": "401"}],
                 "logic": ["Key 格式双段：id + secret", "中间件先 session 后 Key", "一张 api_keys 表，两阶段 TDD"]},
        "mcp": {"label": "进程内 MCP", "purpose": "不做 Python 边车；三个工具对应三种消费深度。",
                "input": "MCP tool_call", "output": "检索结果（片段/聚合/原文三档）"},
        "service": {"label": "收束服务层", "purpose": "三类消费者一条服务层收束，五个新端点一张表看完。",
                    "input": "三类凭据后的统一请求", "output": "五个端点响应"},
        "multi": {"label": "多库开口", "purpose": "多库端点而非每库一路径；实体由调用方传入。",
                  "input": "{ libs: […], entities?: […] }", "output": "向量+图谱组合召回",
                  "decisions": [{"cond": "调用方传实体", "to": "向量+图谱两路组合"}, {"cond": "不传", "to": "向量单路"}]},
    },
}

# ------------------------------------------------------------ Memory Weaver × TDAI
MWTAI = {
    "layers": ["信号源", "增量队列", "策略层", "身份判断", "基础设施层", "召回层"],
    "nodes": [
        {"id": "src-auto", "kind": "entry", "layer": 0, "label": "自动提取", "sub": "轮次结束"},
        {"id": "src-fix", "kind": "entry", "layer": 0, "label": "纠正提取", "sub": "“不对/错了”信号"},
        {"id": "src-save", "kind": "entry", "layer": 0, "label": "压缩前抢救", "sub": "上下文压缩触发"},
        {"id": "queue", "layer": 1, "label": "共享增量队列", "sub": "三源一条队列 · 状态所有权", "module": "queue"},
        {"id": "mw", "layer": 2, "label": "Memory Weaver", "sub": "策略层：提取 / 压缩 / 沉淀", "module": "mw"},
        {"id": "j-id", "kind": "judge", "layer": 3, "label": "项目身份命中?", "sub": "身份模型 · 非目录隔离", "module": "tdai"},
        {"id": "tdai-p", "kind": "store", "layer": 4, "label": "项目知识库", "sub": "TDAI · 来源字段齐全"},
        {"id": "tdai-g", "kind": "store", "layer": 4, "label": "全局知识库", "sub": "跨项目共享"},
        {"id": "recall", "layer": 5, "label": "四级召回", "sub": "术语 → 项目 → 全局 → 按需原文", "module": "recall"},
    ],
    "edges": [
        {"from": "src-auto", "to": "queue", "type": "main"},
        {"from": "src-fix", "to": "queue", "type": "main"},
        {"from": "src-save", "to": "queue", "type": "main"},
        {"from": "queue", "to": "mw", "label": "消费增量", "type": "main"},
        {"from": "mw", "to": "j-id", "label": "写记忆", "type": "main"},
        {"from": "j-id", "to": "tdai-p", "label": "有身份", "type": "main", "side": "L"},
        {"from": "j-id", "to": "tdai-g", "label": "兜底全局", "type": "main", "side": "R"},
        {"from": "tdai-p", "to": "recall", "type": "main"},
        {"from": "tdai-g", "to": "recall", "type": "main"},
    ],
    "modules": {
        "queue": {"label": "共享增量队列", "purpose": "自动提取、纠正提取、压缩前抢救共享同一条增量队列；可靠性来自状态所有权。",
                  "input": "三类提取信号", "output": "有序增量条目",
                  "logic": ["队列状态单一所有者", "不靠更多 try/catch"]},
        "mw": {"label": "Memory Weaver 策略层", "purpose": "做策略不做存储：提取/压缩/沉淀语义字段保留。",
               "input": "增量条目", "output": "记忆写入指令（含语义字段）"},
        "tdai": {"label": "TDAI 基础设施", "purpose": "记忆基础设施：补齐来源字段，身份模型做项目隔离。",
                 "input": "写入指令", "output": "项目库/全局库条目",
                 "decisions": [{"cond": "项目身份命中", "to": "项目知识库"}, {"cond": "无身份", "to": "全局知识库"}]},
        "recall": {"label": "四级召回", "purpose": "精确术语 → 项目知识 → 全局知识 → 按需原文。",
                   "input": "查询 + 项目身份", "output": "三层证据链",
                   "output_example": "术语命中(glossary) → 项目记忆(adopted) → 全局记忆 → 原文片段"},
    },
}

PROJECTS = [
    {"slug": "gamekb-architecture", "title": "GameKB · 游戏知识存储基础设施",
     "tag": "项目架构", "graph": GAMEKB,
     "pos": "把游戏知识一块一块码进知识库：生产方只管写文档，消费方只碰 API，中间复杂度由平台吸收。五层流水线，每层解决一个具体痛点。",
     "note": "点节点看模块详情（输入/输出/逻辑/判断规则）。原文长文保留在 L0 快照。"},
    {"slug": "knowledge-base-skeleton-design", "title": "企业知识库项目骨架设计",
     "tag": "项目架构", "graph": SKELETON,
     "pos": "WeKnora 真正的骨架只有六件：分层目录、契约集中、DI 装配、注册表适配器、插件流水线、异步任务队列。实线是调用方向，虚线是依赖方向——所有层只依赖 interfaces。",
     "note": "实线 = 调用方向；虚线 = 依赖/装配方向。点节点看六件骨架各自职责。"},
    {"slug": "xknow-retrieval-exposure-apikey-design", "title": "检索能力外曝与 API Key 凭据体系",
     "tag": "项目架构", "graph": XKNOW,
     "pos": "把已有的检索能力交出去，而不是再造一套：三类消费者、一条收束服务层、双凭据中间件、多库开口向量图谱两路组合。",
     "note": "菱形为两个关键判断：凭据有效性、召回路径选择。点节点看端点与裁决规则。"},
    {"slug": "pi-memory-weaver-tdai-architecture-review-v2", "title": "Memory Weaver × TDAI：统一 Agent 记忆系统",
     "tag": "项目架构", "graph": MWTAI,
     "pos": "Memory Weaver 做策略，TDAI 做记忆基础设施：两套系统各存一部分真相的问题，用共享增量队列 + 身份模型 + 四级召回收束。",
     "note": "三个信号源共享一条增量队列；身份判断决定写入项目库还是全局库。点节点看细节。"},
]


def content_html(p):
    g = json.dumps(p["graph"], ensure_ascii=False)
    rows = "".join(
        f"<tr><td><code>{m}</code></td><td>{d['purpose'].split('：')[0].split('；')[0]}</td></tr>"
        for m, d in p["graph"]["modules"].items())
    return f"""<section class="reveal"><div class="wrap">
  <p class="section-label">01 · 定位</p>
  <h2>定位</h2>
  <p>{p["pos"]}</p>
</div></section>
<section class="reveal"><div class="wrap">
  <p class="section-label">02 · 全局流程图</p>
  <h2>全局流程图</h2>
  <figure class="figure">
    <div class="arch-flow">
      <script type="application/json">{g}</script>
    </div>
    <figcaption class="fig-cap">图 1 · {p["title"]} 架构总览</figcaption>
    <p class="fig-note">{p["note"]}</p>
  </figure>
</div></section>
<section class="reveal"><div class="wrap">
  <p class="section-label">03 · 模块索引</p>
  <h2>模块索引</h2>
  <table class="data-table">
    <thead><tr><th>模块</th><th>一句话职责</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div></section>"""


def main():
    for p in PROJECTS:
        p["graph"]["edgeTypes"] = EDGE3  # 三型语义边配色，缺了会落灰底默认
        body = json.dumps({
            "title": p["title"], "slug": p["slug"], "tag": p["tag"],
            "template": "arch-overview", "domain": "arch",
            "subtitle": p["pos"][:60],
            "content": content_html(p),
        }).encode()
        req = urllib.request.Request(f"{BASE}/api/reports", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            res = json.load(r)
        print(p["slug"], "->", res.get("url"), "| components:", res.get("components"),
              "| warnings:", res.get("warnings"))


if __name__ == "__main__":
    main()
