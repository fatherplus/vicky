#!/usr/bin/env python3
"""P4: knowledge_query MCP 读线工具。

覆盖：三阶段管线（召回/打分/预算装包）、目录模式、预算硬顶与截断、
引文格式（id/topic/sources/url）、category/tag 过滤、空库 note、
MCP 注册（tools/list 含 knowledge_query）。

安全红线：全部 tmp 目录隔离（patch config.DATA_DIR + KNOWLEDGE_DIR），
不碰真实 knowledge/ 与 data/。本文件按字母序排在 test_mcp_protocol 之前——
绝不触发全局 register_default_tools（P1 契约 test_tools_list 断言 tools/list 为空），
注册验证用全新 MCPRouter 复现注册逻辑。
"""
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from vicky import store
from vicky.knowledge_query import query, estimate_tokens
from vicky.l2_distill import _extract_items, dump_frontmatter

# ── 测试知识库素材（两个主题：HNSW 向量检索 / 图数据库，跨 category/tag）──
HNSW_MD = """## 概述

HNSW 是分层可导航小世界图，用于向量检索。

## 核心要点

- HNSW 在 L0 层每个节点的最大边数为 2×M [来源: hnsw-algorithm]
- 调大 M 提高召回率，代价是内存与构建速度 [来源: hnsw-algorithm]

## 关键数据

- 100 万向量检索延迟 10ms，召回 95% [来源: hnsw-algorithm]

## 陷阱与反模式

- 盲目增大 M 会内存膨胀 [来源: hnsw-algorithm]
"""

GRAPH_MD = """## 概述

图数据库用 HNSW 索引支撑 RAG 检索管线。

## 核心要点

- HNSW 可作图索引的近似最近邻搜索层 [来源: graph-db]

## 关键数据

- RAG 检索端到端延迟降低 40% [来源: graph-db]
"""


def _write_topic(tmp: Path, topic: str, category: str, tags: list, md_text: str) -> None:
    """tmp/knowledge/tech/{topic}/overview.md + items.json（P3 原子化孪生）。"""
    d = tmp / "knowledge" / "tech" / topic
    d.mkdir(parents=True, exist_ok=True)
    meta = {"id": topic, "title": topic, "type": "Topic", "domain": "tech",
            "category": category}
    if tags:
        meta["tags"] = tags
    ov = dump_frontmatter(meta) + "\n" + md_text
    (d / "overview.md").write_text(ov, encoding="utf-8")
    (d / "items.json").write_text(
        json.dumps(_extract_items(topic, "tech", ov), ensure_ascii=False, indent=2),
        encoding="utf-8")


@contextmanager
def _env(topics: dict):
    """tmp 知识库（tech 域）+ 建索引 + patch config（DATA_DIR/KNOWLEDGE_DIR）。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for topic, (category, tags, md) in topics.items():
            _write_topic(tmp, topic, category, tags, md)
        with patch("vicky.config.DATA_DIR", tmp / "data"), \
             patch("vicky.config.KNOWLEDGE_DIR", tmp / "knowledge"):
            store.create_knowledge_items_table()
            store.rebuild_items_index({"tech": list(topics)})
            yield tmp


def _fresh_router():
    """全新 MCPRouter（复现 register_default_tools 的注册逻辑，不污染全局注册表）。"""
    from vicky import mcp
    r = mcp.MCPRouter()
    for name, handler, schema in mcp._DEFAULT_TOOLS:
        r.tool_schemas[name] = schema
        r.register(name, handler)
    return r


# ============================================================
# 三阶段检索
# ============================================================
def test_query_returns_items():
    """搜索 HNSW → 返回带完整结构的条目（id/text/kind/topic/sources/url）。"""
    with _env({"hnsw-algorithm": ("ai", ["RAG", "检索"], HNSW_MD),
               "graph-db": ("infra", ["图谱"], GRAPH_MD)}):
        result = query({"q": "HNSW", "budget": 3000})
        assert result["items"], "HNSW 查询应命中条目"
        assert result["stats"]["returned"] > 0
        for it in result["items"]:
            assert set(it) == {"id", "text", "kind", "topic", "sources", "url"}
            assert it["text"].strip()
        # 相关度优先：conclusion 加权最高，应有结论在列
        kinds = {it["kind"] for it in result["items"]}
        assert "conclusion" in kinds


def test_category_filter():
    """category 精确过滤：只回该专栏的主题条目。"""
    with _env({"hnsw-algorithm": ("ai", ["RAG", "检索"], HNSW_MD),
               "graph-db": ("infra", ["图谱"], GRAPH_MD)}):
        ai = query({"q": "HNSW", "category": "ai"})
        infra = query({"q": "HNSW", "category": "infra"})
        assert ai["items"] and all(it["topic"] == "hnsw-algorithm" for it in ai["items"])
        assert infra["items"] and all(it["topic"] == "graph-db" for it in infra["items"])
        assert query({"q": "HNSW", "category": "ops"})["items"] == []


def test_tag_filter():
    """tag 子串过滤（overview frontmatter tags → FTS tag 列）。"""
    with _env({"hnsw-algorithm": ("ai", ["RAG", "检索"], HNSW_MD),
               "graph-db": ("infra", ["图谱"], GRAPH_MD)}):
        hit = query({"q": "HNSW", "tag": "RAG"})
        assert hit["items"] and all(it["topic"] == "hnsw-algorithm" for it in hit["items"])
        assert query({"q": "HNSW", "tag": "不存在的标签"})["items"] == []


# ============================================================
# 预算装包
# ============================================================
def test_budget_enforced():
    """budget=100 → 返回条目的 token 估算和 ≤ 100（贪婪严格不超）。"""
    with _env({"hnsw-algorithm": ("ai", ["RAG", "检索"], HNSW_MD)}):
        result = query({"q": "HNSW", "budget": 100})
        assert result["stats"]["budget_total"] == 100
        assert result["stats"]["budget_used"] <= 100
        used = sum(estimate_tokens(it["text"]) for it in result["items"])
        assert used <= 100
        # 默认预算 2000 应能带回更多条目
        big = query({"q": "HNSW"})
        assert big["stats"]["budget_total"] == 2000
        assert big["stats"]["returned"] >= result["stats"]["returned"]


def test_budget_capped():
    """budget=99999 → 硬顶 6000。"""
    with _env({"hnsw-algorithm": ("ai", ["RAG", "检索"], HNSW_MD)}):
        result = query({"q": "HNSW", "budget": 99999})
        assert result["stats"]["budget_total"] == 6000
        assert result["stats"]["budget_used"] <= 6000


def test_budget_invalid_defaults():
    """budget 非法（负数/非数字）→ 默认 2000。"""
    with _env({"hnsw-algorithm": ("ai", ["RAG", "检索"], HNSW_MD)}):
        assert query({"q": "HNSW", "budget": -5})["stats"]["budget_total"] == 2000
        assert query({"q": "HNSW", "budget": "abc"})["stats"]["budget_total"] == 2000


# ============================================================
# 引文格式
# ============================================================
def test_citation_format():
    """每条目带 id/topic/sources/url；url 是报告 .md 链接或知识页锚点。"""
    with _env({"hnsw-algorithm": ("ai", ["RAG", "检索"], HNSW_MD)}):
        result = query({"q": "HNSW"})
        assert result["items"]
        for it in result["items"]:
            assert it["id"].startswith("hnsw-algorithm#")
            assert it["topic"] == "hnsw-algorithm"
            assert isinstance(it["sources"], list)
            assert it["sources"], "sources 应来自 items.json"
            assert it["sources"][0] == "hnsw-algorithm"
            # tmp 环境无 reports 表登记 → 按源名兜底 .md 链接
            assert it["url"] == "../reports/hnsw-algorithm.md" or \
                   it["url"].startswith("../knowledge#")


# ============================================================
# 目录模式 / 空库 / 超长查询
# ============================================================
def test_query_empty_returns_catalog():
    """q="" → 目录：按 category 列主题 + 计数。"""
    with _env({"hnsw-algorithm": ("ai", ["RAG", "检索"], HNSW_MD),
               "graph-db": ("infra", ["图谱"], GRAPH_MD)}):
        result = query({"q": ""})
        assert "catalog" in result
        cats = {c["category"]: c for c in result["catalog"]}
        assert set(cats) >= {"ai", "infra"}
        ai_topics = {t["topic"] for t in cats["ai"]["topics"]}
        assert "hnsw-algorithm" in ai_topics
        assert result["stats"]["total_topics"] >= 2
        assert result["stats"]["total_items"] >= 6


def test_empty_store_note():
    """库空（建表未重建索引）→ 空 items + note。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        with patch("vicky.config.DATA_DIR", tmp / "data"), \
             patch("vicky.config.KNOWLEDGE_DIR", tmp / "knowledge"):
            store.create_knowledge_items_table()
            result = query({"q": "HNSW"})
            assert result["items"] == []
            assert result["stats"]["total"] == 0
            assert "note" in result
            # 目录模式同样空
            catalog = query({"q": ""})
            assert catalog["catalog"] == []
            assert catalog["stats"]["total_items"] == 0


def test_query_too_long_truncated():
    """超长查询截断到 200 字符，不崩、结构完整。"""
    with _env({"hnsw-algorithm": ("ai", ["RAG", "检索"], HNSW_MD)}):
        long_q = "HNSW " + "向量" * 300  # > 200 字符
        result = query({"q": long_q})
        assert "items" in result and "stats" in result


# ============================================================
# MCP 注册（不触发全局注册，P1 空表契约不受影响）
# ============================================================
def test_mcp_tool_registered():
    """tools/list 含 knowledge_query，inputSchema 契约正确。"""
    r = _fresh_router()
    listing = r.dispatch("tools/list", {})
    names = [t["name"] for t in listing["tools"]]
    assert "knowledge_query" in names
    schema = r.tool_schemas["knowledge_query"]
    props = schema["inputSchema"]["properties"]
    assert set(props) >= {"q", "budget", "category", "tag"}
    assert props["budget"]["default"] == 2000


def test_mcp_tool_call_via_router():
    """经全新 router 的 tools/call 端到端：handler → knowledge_query.query → 结果入 content。"""
    with _env({"hnsw-algorithm": ("ai", ["RAG", "检索"], HNSW_MD)}):
        r = _fresh_router()
        res = r.dispatch("tools/call", {
            "name": "knowledge_query", "arguments": {"q": "HNSW", "budget": 300}})
        data = json.loads(res["content"][0]["text"])
        assert data["items"]
        assert data["stats"]["budget_total"] == 300
        # 目录模式走同一工具
        cat = r.dispatch("tools/call", {
            "name": "knowledge_query", "arguments": {"q": ""}})
        cat_data = json.loads(cat["content"][0]["text"])
        assert "catalog" in cat_data


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("ALL PASS")
