#!/usr/bin/env python3
"""OKF frontmatter + 概念持久化（B 档）验收。不依赖网关（不测 llm_cluster/llm_chat）。P0 包化：import 更新。
P5 修复：write_knowledge_compiled 写入走 tempfile 临时目录——安全红线：禁止写真实 knowledge/。"""
import os
import shutil
import tempfile
from unittest.mock import patch

from ai_report.l2_distill import (dump_frontmatter, parse_frontmatter, parse_overview,
                     write_knowledge_compiled, _norm_clusters, _safe_slug,
                     _load_existing_concepts)


def _tmp_knowledge_dir():
    """为 write_knowledge_compiled 创建临时 knowledge 目录（P5 安全修复：不碰真实 knowledge/）。"""
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp(prefix="test_okf_"))
    (tmp / "tech").mkdir(parents=True, exist_ok=True)
    return tmp


def test_frontmatter_roundtrip():
    d = {"id": "x--1", "title": "T: 含冒号", "type": "Topic", "domain": "tech",
         "status": "stable", "generated": {"by": "agent:glm", "at": "2026-08-01"},
         "verified": "machine-confirmed", "sources_count": 2,
         "stale_after": "2026-11-01", "confidence": "high",
         "source_reports": ["a", "odd:colon", "with, comma"]}
    meta, body = parse_frontmatter(dump_frontmatter(d) + "\n## 概述\n\n正文\n")
    assert meta == d
    assert body.strip().startswith("## 概述")
    # 无 frontmatter 回退
    m2, b2 = parse_frontmatter("# 旧\n> x\n")
    assert m2 == {} and b2.startswith("# 旧")


def test_parse_overview_new_and_old():
    fm = dump_frontmatter({"id": "x--1", "title": "新", "domain": "tech", "status": "stable",
                           "generated": {"by": "agent:glm", "at": "2026-08-01"},
                           "verified": "machine-confirmed", "sources_count": 3,
                           "stale_after": "2026-11-01", "confidence": "high",
                           "source_reports": ["a", "b"]})
    n = parse_overview(fm + "\n## 概述\n\n散文。\n\n## 核心要点\n\n- 要点 [a]\n")
    assert n["title"] == "新" and n["sources"] == 3 and n["confidence"] == "high"
    assert n["verified"] == "machine-confirmed" and n["stale_after"] == "2026-11-01"
    assert n["source_reports"] == ["a", "b"] and n["id"] == "x--1"
    assert n["sections"][0]["label"] == "概述"
    # 旧散文格式
    o = parse_overview("# 旧\n> Updated: 2026-07-31 | Sources: 2 | Confidence: medium\n\n## 概述\n\nz\n")
    assert o["title"] == "旧" and o["sources"] == 2 and o["confidence"] == "medium"
    assert o["verified"] == "unverified" and o["status"] == "stable"  # 旧格式默认


def test_write_compiled_frontmatter_and_id():
    md = {"a": {"title": "A", "domain": "tech", "items": []},
          "b": {"title": "B", "domain": "tech", "items": []}}
    comp = {"summary": "综合。", "points": ["p [a]"], "data": [], "traps": [], "contradictions": []}
    tmp = _tmp_knowledge_dir()
    try:
        with patch("ai_report.l2_distill.KNOWLEDGE_DIR", tmp):
            p = write_knowledge_compiled({"topic": "T", "domain": "tech", "members": ["a", "b"]}, md, comp)
            ov = parse_overview(p.read_text(encoding="utf-8"))
            assert ov["id"] == p.parent.name  # id 与目录名恒等
            assert ov["verified"] == "machine-confirmed" and ov["sources"] == 2
            assert ov["generated"]["by"].startswith("agent:") and ov["stale_after"]
            # 单源 unverified
            p1 = write_knowledge_compiled({"topic": "S", "domain": "tech", "members": ["a"]}, md, comp)
            assert parse_overview(p1.read_text(encoding="utf-8"))["verified"] == "unverified"
            # existing_id 复用
            p2 = write_knowledge_compiled({"topic": "任意", "domain": "tech", "members": ["a", "b"],
                                           "id": "preset--z"}, md, comp)
            assert p2.parent.name == "preset--z"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_safe_slug_stability():
    ms = ["hnsw-algorithm", "rag-yongze"]
    assert _safe_slug("名一", ms) == _safe_slug("名二", list(reversed(ms)))  # 成员集合稳定
    assert _safe_slug("x", ms, existing_id="keep--1") == "keep--1"  # id 优先
    assert _safe_slug("x", ["solo"]) == "solo"  # 单源


def test_norm_clusters_id_resolution():
    reports = [{"slug": "a", "title": "A", "domain": "tech"},
               {"slug": "b", "title": "B", "domain": "tech"},
               {"slug": "c", "title": "C", "domain": "tech"}]
    anchors = [{"id": "vec--1", "title": "向量", "members": ["a", "b"]}]
    data = [{"id": "vec--1", "topic": "向量", "domain": "tech", "members": ["a", "b"]},
            {"id": "ghost--9", "topic": "幻觉", "domain": "tech", "members": ["c"]}]
    out = {c["topic"]: c for c in _norm_clusters(data, reports, anchors)}
    assert out["向量"]["id"] == "vec--1"  # 命中锚点
    assert out["幻觉"]["id"] == ""  # 幻觉 id 丢弃
    # 漏网自成无 id 组
    out2 = _norm_clusters([{"id": "vec--1", "topic": "向量", "domain": "tech", "members": ["a"]}],
                          reports, anchors)
    assert any(c["members"] == ["b"] and c["id"] == "" for c in out2)


def test_load_existing_concepts_compat():
    tmp = _tmp_knowledge_dir()
    d1 = os.path.join(tmp, "tech", "vec--1")
    d2 = os.path.join(tmp, "tech", "oldone")
    try:
        os.makedirs(d1, exist_ok=True)
        with open(os.path.join(d1, "overview.md"), "w", encoding="utf-8") as f:
            f.write(dump_frontmatter(
                {"id": "vec--1", "title": "向量", "domain": "tech", "status": "stable",
                 "generated": {"by": "agent:glm", "at": "2026-08-01"}, "verified": "machine-confirmed",
                 "sources_count": 2, "stale_after": "2026-11-01", "confidence": "medium",
                 "source_reports": ["a", "b"]}) + "\n## 概述\n\nx\n")
        os.makedirs(d2, exist_ok=True)
        with open(os.path.join(d2, "overview.md"), "w", encoding="utf-8") as f:
            f.write(
                "# 旧\n> Updated: 2026-07-31 | Sources: 1 | Confidence: low\n\n## 来源\n\n- A [slug-a]\n")
        with patch("ai_report.l2_distill.KNOWLEDGE_DIR", tmp):
            anchors = {a["id"]: a for a in _load_existing_concepts()}
        assert anchors["vec--1"]["members"] == ["a", "b"]
        assert anchors["oldone"]["members"] == ["slug-a"]  # 旧格式回退抠 members
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ALL PASS")
