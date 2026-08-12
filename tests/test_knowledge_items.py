#!/usr/bin/env python3
"""P3：VK 原子化——overview.md → items.json 知识条目 + sqlite FTS5 检索索引。
覆盖：_extract_items 三 kind 提取（spec 节名 + 存量实况节名 + 来源标记）、
citation ID 格式（topic#c1 / topic#d1 / topic#t1）、store 建表 / 重建幂等 / FTS5 检索、
cli index-knowledge 子命令注册与端到端（补全 items.json + 落库 + 可检索）。
安全红线：全部 tmp 目录隔离，不碰真实 knowledge/ 与 data/。"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from vicky import store, config, cli
from vicky.l2_distill import _extract_items, _write_items_json, dump_frontmatter

# spec 节名（## 结论 / ## 关键数据 / ## 常见陷阱）+ [来源: xxx] 标记
SAMPLE_MD = """---
id: demo
title: 演示主题
type: Topic
domain: tech
status: stable
generated: {by: "agent:test", at: 2026-08-10}
verified: unverified
sources_count: 2
stale_after: 2026-11-01
confidence: medium
source_reports:
  - report-a
  - report-b
category: ai
tags:
  - RAG
  - 检索
---
## 概述

演示主题是测试用的。

## 结论

- 结论一 [来源: report-a]
- 结论二 [来源: report-b]

## 关键数据

- 数据点一 [来源: report-a]

## 常见陷阱

- 陷阱一 [来源: report-b]
"""


def _tmp_knowledge(tmp: Path, n_topics: int = 1, with_items_json: bool = True) -> None:
    """tmp/knowledge 下建 n 个主题：overview.md（结论节）+ 可选 items.json。
    B 阶段目录扁平化：knowledge/{topic}/（不再有 domain 子层）。"""
    (tmp / "knowledge").mkdir(parents=True)
    for i in range(n_topics):
        topic = f"topic-{i}"
        d = tmp / "knowledge" / topic
        d.mkdir()
        ov = (dump_frontmatter({"id": topic, "title": f"主题{i}", "type": "Topic",
                                "category": "ai",
                                "tags": ["RAG", "检索"]}) +
              f"\n## 概述\n\n这是主题{i}的概述。\n\n"
              f"## 结论\n\n- 结论{i} [来源: report-{i}]\n")
        (d / "overview.md").write_text(ov, encoding="utf-8")
        if with_items_json:
            items = _extract_items(topic, ov)
            (d / "items.json").write_text(
                json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# 1. 条目提取
# ============================================================
def test_extract_items():
    """spec 节名 + [来源: xxx] 标记：三 kind 顺序、来源解析、anchors 空槽。"""
    items = _extract_items("demo", SAMPLE_MD)
    assert [i["kind"] for i in items] == ["conclusion", "conclusion", "data", "trap"]
    assert items[0]["text"] == "结论一"
    assert items[0]["sources"] == ["report-a"]
    assert items[1]["sources"] == ["report-b"]
    assert items[0]["anchors"] == []
    assert {i["kind"] for i in items} == {"conclusion", "data", "trap"}


def test_citation_id_format():
    """id = {topic}#{kind_short}{n}，n 按 kind 独立从 1 递增。"""
    items = _extract_items("demo", SAMPLE_MD)
    assert [i["id"] for i in items] == ["demo#c1", "demo#c2", "demo#d1", "demo#t1"]
    import re as _re
    for it in items:
        assert _re.fullmatch(r"demo#(?:c|d|t)\d+", it["id"])


def test_extract_items_real_sections():
    """存量 LLM 编译产物的节名（核心要点/陷阱与反模式）+ 行尾 [slug] 来源标记。"""
    md = (dump_frontmatter({"id": "hnsw-algorithm", "title": "X", "type": "Topic",
                            "domain": "tech", "category": "ai"}) +
          "\n## 概述\n\nx\n\n"
          "## 核心要点\n\n- HNSW 参数 M 决定图的连通性 [hnsw-algorithm]\n\n"
          "## 关键数据\n\n- L0 层每个节点的最大边数为 2×M [hnsw-algorithm]\n\n"
          "## 陷阱与反模式\n\n- 盲目增大 M 会内存膨胀 [hnsw-algorithm]\n")
    items = _extract_items("hnsw-algorithm", md)
    assert [i["id"] for i in items] == ["hnsw-algorithm#c1", "hnsw-algorithm#d1", "hnsw-algorithm#t1"]
    assert items[0]["sources"] == ["hnsw-algorithm"]
    assert items[0]["text"] == "HNSW 参数 M 决定图的连通性"


def test_extract_items_skips_non_kind_sections():
    """概述/来源/综合/分歧等节不产条目；列表项与段落都可作条目单元。"""
    md = ("---\nid: x\ntitle: X\ntype: Topic\ndomain: tech\ncategory: ai\n---\n\n"
          "## 概述\n\n这是概述。\n\n"
          "## 结论\n\n- 结论甲 [来源: a]\n\n一段落形式的结论 [来源: b]\n\n"
          "## 综合\n\n- 综合注记 [2026-08-01]\n\n"
          "## 来源\n\n- 报告 [a]\n")
    items = _extract_items("x", md)
    assert [i["kind"] for i in items] == ["conclusion", "conclusion"]
    assert items[1]["text"] == "一段落形式的结论"


def test_write_items_json_writes_sibling():
    """_write_items_json 只写 items.json，不碰 overview.md（正文逐字不变）。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _tmp_knowledge(tmp, n_topics=1)
        ovf = tmp / "knowledge" / "topic-0" / "overview.md"
        orig = ovf.read_text(encoding="utf-8")
        with patch("vicky.l2_distill.KNOWLEDGE_DIR", tmp / "knowledge"):
            out = _write_items_json("topic-0", orig)
        assert out == tmp / "knowledge" / "topic-0" / "items.json"
        assert out.exists()
        assert ovf.read_text(encoding="utf-8") == orig  # overview.md 未动
        items = json.loads(out.read_text(encoding="utf-8"))
        assert items[0]["id"] == "topic-0#c1"


# ============================================================
# 2. store：建表 / FTS5 检索 / 重建幂等
# ============================================================
def test_fts5_search():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _tmp_knowledge(tmp, n_topics=1)
        with patch("vicky.config.DATA_DIR", tmp / "data"), \
             patch("vicky.config.KNOWLEDGE_DIR", tmp / "knowledge"):
            store.create_knowledge_items_table()
            store.rebuild_items_index({"tech": ["topic-0"]})
            hits = store.search_items("结论0")
            assert len(hits) == 1
            assert hits[0][0] == "topic-0#c1"       # id
            assert hits[0][1] == "topic-0"          # topic
            assert hits[0][3] == "conclusion"       # kind
            # category 精确过滤
            assert len(store.search_items("结论0", category="ai")) == 1
            assert len(store.search_items("结论0", category="infra")) == 0
            # tag 子串过滤（FTS tag 列）
            assert len(store.search_items("结论0", tag="RAG")) == 1
            assert len(store.search_items("结论0", tag="不存在的标签")) == 0
            # limit
            assert store.search_items("结论0", limit=0) == []


def test_fts5_search_short_cjk_like_fallback():
    """1-2 字中文（trigram 盲区）退回 LIKE 兜底仍有命中。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _tmp_knowledge(tmp, n_topics=1)
        with patch("vicky.config.DATA_DIR", tmp / "data"), \
             patch("vicky.config.KNOWLEDGE_DIR", tmp / "knowledge"):
            store.create_knowledge_items_table()
            store.rebuild_items_index({"tech": ["topic-0"]})
            assert len(store.search_items("结论")) == 1
            # 无命中词返回空
            assert store.search_items("不存在的词xyz") == []


def test_fts5_rebuild_idempotent():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _tmp_knowledge(tmp, n_topics=2)
        with patch("vicky.config.DATA_DIR", tmp / "data"), \
             patch("vicky.config.KNOWLEDGE_DIR", tmp / "knowledge"):
            store.create_knowledge_items_table()
            n1 = store.rebuild_items_index({"tech": ["topic-0", "topic-1"]})
            n2 = store.rebuild_items_index({"tech": ["topic-0", "topic-1"]})
            assert n1 == n2 == 2
            conn = store.get_db()
            try:
                cnt = conn.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0]
                fts_cnt = conn.execute(
                    "SELECT COUNT(*) FROM knowledge_items_fts").fetchone()[0]
            finally:
                conn.close()
            assert cnt == 2          # 重建后条数不变（先清后插）
            assert fts_cnt == 2


# ============================================================
# 3. cli：index-knowledge 子命令
# ============================================================
def test_cli_index_knowledge_exists():
    """子命令已注册：main 派发分支 + index_knowledge 函数存在。"""
    src = Path(cli.__file__).read_text(encoding="utf-8")
    assert 'cmd == "index-knowledge"' in src
    assert "def index_knowledge(" in src
    # 帮助文案也列出
    assert "index-knowledge" in src.split('def main()')[1]


def test_cli_index_knowledge_end_to_end():
    """存量库（无 items.json）→ 补全 + 落库 + FTS 可检索。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _tmp_knowledge(tmp, n_topics=1, with_items_json=False)  # 模拟存量：只有 overview.md
        with patch("vicky.config.DATA_DIR", tmp / "data"), \
             patch("vicky.config.KNOWLEDGE_DIR", tmp / "knowledge"), \
             patch("vicky.l2_distill.KNOWLEDGE_DIR", tmp / "knowledge"):
            cli.index_knowledge()
        # items.json 已补全
        items_path = tmp / "knowledge" / "topic-0" / "items.json"
        assert items_path.exists()
        items = json.loads(items_path.read_text(encoding="utf-8"))
        assert items[0]["id"] == "topic-0#c1"
        # DB 落库
        with patch("vicky.config.DATA_DIR", tmp / "data"):
            conn = store.get_db()
            try:
                row = conn.execute("SELECT * FROM knowledge_items LIMIT 3").fetchone()
            finally:
                conn.close()
            assert row is not None
            assert row["topic"] == "topic-0"
            assert row["kind"] == "conclusion"
        # FTS 可检索
        with patch("vicky.config.DATA_DIR", tmp / "data"):
            hits = store.search_items("结论0")
            assert len(hits) == 1 and hits[0][0] == "topic-0#c1"


def test_cli_index_knowledge_topic_filter():
    """--topic 只处理指定主题。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _tmp_knowledge(tmp, n_topics=2, with_items_json=False)
        with patch("vicky.config.DATA_DIR", tmp / "data"), \
             patch("vicky.config.KNOWLEDGE_DIR", tmp / "knowledge"), \
             patch("vicky.l2_distill.KNOWLEDGE_DIR", tmp / "knowledge"):
            cli.index_knowledge(topic="topic-0")
        assert (tmp / "knowledge" / "topic-0" / "items.json").exists()
        assert not (tmp / "knowledge" / "topic-1" / "items.json").exists()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("ALL PASS")
