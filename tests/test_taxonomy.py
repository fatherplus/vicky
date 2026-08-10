#!/usr/bin/env python3
"""知识库双层分类（专栏 × 标签）验收——分类规格 2026-08-10 §4。
覆盖：枚举校验 + 兜底、frontmatter 往返、classify 幂等（mock LLM）、
页面生成契约（chips data-c / pavilion data-category / kcard 三段结构）。
安全红线：全部 tmp 目录隔离，不碰真实 knowledge/、不调真实网关（mock llm_chat）。"""
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from tests.util import REPO
from vicky.l2_distill import (dump_frontmatter, parse_frontmatter, parse_overview,
                                  llm_compile_topic, write_knowledge_compiled,
                                  build_knowledge_page)
from vicky import config, cli


def _tmp_knowledge(tmp: Path, n: int = 2) -> None:
    """在 tmp 下建 n 个 tech 主题（frontmatter 无 category/tags）。"""
    (tmp / "tech").mkdir(parents=True, exist_ok=True)
    for i in range(n):
        topic = f"topic-{i}"
        d = tmp / "tech" / topic
        d.mkdir()
        meta = {"id": topic, "title": f"主题{i}", "type": "Topic", "domain": "tech",
                "status": "stable",
                "generated": {"by": "agent:glm", "at": "2026-08-01"},
                "verified": "machine-confirmed", "sources_count": 2,
                "stale_after": "2026-11-01", "confidence": "high",
                "source_reports": ["a", "b"]}
        (d / "overview.md").write_text(
            dump_frontmatter(meta) +
            f"\n## 概述\n\n这是主题{i}的概述，解决什么问题要讲清楚。\n\n"
            f"## 核心要点\n\n- 要点一 [a]\n- 要点二 [b]\n",
            encoding="utf-8")


def _tpl_with_chips(tmp: Path) -> None:
    """views 副本：把旧模板的硬编码 chips 换成 __CHIPS__ 占位（模拟 F 的新模板契约）。"""
    tpl = (REPO / "views" / "knowledge.html").read_text(encoding="utf-8")
    tpl = tpl.replace('<span class="chip on" data-d="all">全部<span class="n">__TOPICS__</span></span>',
                      "__CHIPS__")
    (tmp / "views").mkdir(parents=True, exist_ok=True)
    (tmp / "views" / "knowledge.html").write_text(tpl, encoding="utf-8")


# ============================================================
# 1. 枚举 + 兜底
# ============================================================
def test_category_enum():
    assert list(config.CATEGORIES) == ["ai", "infra", "eng", "ops", "design"]
    assert config.CATEGORIES["ai"] == "AI 专栏"
    assert config.CATEGORIES["design"] == "产品与设计专栏"


def test_compile_category_validation_and_fallback():
    member = [{"slug": "a", "title": "A", "conclusions": ["c"], "traps": [], "data": []}]
    # LLM 返回非法 category + 空 tags → 兜底 ai / 无标签
    with patch("vicky.l2_distill.llm_chat",
               return_value='{"summary": "s", "points": ["p [a]"], "category": "wrong!", "tags": []}'):
        out = llm_compile_topic("T", member)
    assert out["category"] == "ai"
    assert out["tags"] == []
    # 合法值透传
    with patch("vicky.l2_distill.llm_chat",
               return_value='{"summary": "s", "points": ["p [a]"], "category": "ops", "tags": ["用量分析", "监控"]}'):
        out = llm_compile_topic("T", member)
    assert out["category"] == "ops"
    assert out["tags"] == ["用量分析", "监控"]
    # 超 5 个截断；非字符串过滤
    with patch("vicky.l2_distill.llm_chat",
               return_value='{"summary": "s", "points": [], "category": "infra", "tags": ["a", "b", "c", "d", "e", "f", 7]}'):
        out = llm_compile_topic("T", member)
    assert out["tags"] == ["a", "b", "c", "d", "e"]


def test_compile_prompt_injects_tags_and_categories():
    captured = {}

    def fake_chat(messages, max_tokens=0, timeout=0):
        captured["prompt"] = messages[0]["content"]
        return '{"summary": "s", "points": [], "category": "ai", "tags": ["RAG"]}'

    member = [{"slug": "a", "title": "A", "conclusions": ["c"], "traps": [], "data": []}]
    with patch("vicky.l2_distill.llm_chat", side_effect=fake_chat), \
         patch("vicky.l2_distill.existing_tags", return_value=["RAG", "检索"]):
        llm_compile_topic("T", member)
    p = captured["prompt"]
    assert "RAG" in p and "检索" in p                      # 已有标签清单注入
    assert "后端与基础设施专栏" in p                        # 枚举注入
    assert "开源项目" in p and "2-5" in p                  # tags 规格注入


# ============================================================
# 2. frontmatter 往返（category/tags 字段）
# ============================================================
def test_frontmatter_category_tags_roundtrip():
    d = {"id": "x--1", "title": "T", "domain": "tech", "category": "infra",
         "status": "stable",
         "generated": {"by": "agent:glm", "at": "2026-08-01"},
         "verified": "machine-confirmed", "sources_count": 2,
         "stale_after": "2026-11-01", "confidence": "high",
         "source_reports": ["a"], "tags": ["数据库", "开源项目"]}
    meta, body = parse_frontmatter(dump_frontmatter(d) + "\n## 概述\n\nx\n")
    assert meta["category"] == "infra"
    assert meta["tags"] == ["数据库", "开源项目"]
    ov = parse_overview(dump_frontmatter(d) + "\n## 概述\n\nx\n")
    assert ov["category"] == "infra"
    assert ov["category_label"] == "后端与基础设施专栏"
    assert ov["tags"] == ["数据库", "开源项目"]


def test_parse_overview_category_fallback():
    # 无 frontmatter 旧格式 → 兜底 ai
    o = parse_overview("# 旧\n> Updated: 2026-07-31 | Sources: 2 | Confidence: medium\n\n## 概述\n\nz\n")
    assert o["category"] == "ai" and o["category_label"] == "AI 专栏" and o["tags"] == []
    # frontmatter 非法 category → 兜底 ai
    o2 = parse_overview(dump_frontmatter({"id": "x", "title": "T", "domain": "tech",
                                          "category": "nope", "tags": ["x"]}) + "\n## 概述\n\ny\n")
    assert o2["category"] == "ai"


def test_write_compiled_persists_category_tags():
    md = {"a": {"title": "A", "domain": "tech", "items": []}}
    comp = {"summary": "综合。", "points": [], "data": [], "traps": [],
            "contradictions": [], "category": "eng", "tags": ["CLI", "工作流"]}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "tech").mkdir(parents=True)
        with patch("vicky.l2_distill.KNOWLEDGE_DIR", tmp):
            p = write_knowledge_compiled({"topic": "T", "domain": "tech", "members": ["a"]}, md, comp)
            ov = parse_overview(p.read_text(encoding="utf-8"))
            assert ov["category"] == "eng" and ov["tags"] == ["CLI", "工作流"]
    # tags 为空 → frontmatter 不写字段（tags 为空则无）
    comp2 = dict(comp, category="ops", tags=[])
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "tech").mkdir(parents=True)
        with patch("vicky.l2_distill.KNOWLEDGE_DIR", tmp):
            p = write_knowledge_compiled({"topic": "T", "domain": "tech", "members": ["a"]}, md, comp2)
            meta, _ = parse_frontmatter(p.read_text(encoding="utf-8"))
            assert meta["category"] == "ops" and "tags" not in meta


# ============================================================
# 3. classify：幂等 + LLM 不可用跳过
# ============================================================
def test_classify_idempotent_mock_llm():
    calls = []
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _tmp_knowledge(tmp, n=2)

        def fake_chat(messages, max_tokens=0, timeout=0):
            calls.append(messages)
            return '{"category": "eng", "tags": ["CLI", "工作流"]}'

        with patch("vicky.l2_distill.KNOWLEDGE_DIR", tmp), \
             patch("vicky.l2_distill.LLM_ON", True), \
             patch("vicky.l2_distill.llm_chat", side_effect=fake_chat):
            cli.classify()
            cli.classify()  # 二跑：全部已有 category，零调用

        assert len(calls) == 2  # 只有首轮 2 主题各 1 次；二跑无新增
        ovf = tmp / "tech" / "topic-0" / "overview.md"
        meta, body = parse_frontmatter(ovf.read_text(encoding="utf-8"))
        assert meta["category"] == "eng"
        assert meta["tags"] == ["CLI", "工作流"]
        assert "## 核心要点" in body  # 正文未被重编译，原样保留


def test_classify_llm_unavailable_skips():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _tmp_knowledge(tmp, n=1)
        with patch("vicky.l2_distill.KNOWLEDGE_DIR", tmp), \
             patch("vicky.l2_distill.LLM_ON", False):
            cli.classify()
        ovf = tmp / "tech" / "topic-0" / "overview.md"
        meta, _ = parse_frontmatter(ovf.read_text(encoding="utf-8"))
        assert "category" not in meta  # 留白不误写


def test_classify_llm_failure_keeps_blank():
    """LLM 返回垃圾 → 也不写，留白不误分。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _tmp_knowledge(tmp, n=1)
        with patch("vicky.l2_distill.KNOWLEDGE_DIR", tmp), \
             patch("vicky.l2_distill.LLM_ON", True), \
             patch("vicky.l2_distill.llm_chat", return_value=None):
            cli.classify()
        ovf = tmp / "tech" / "topic-0" / "overview.md"
        meta, _ = parse_frontmatter(ovf.read_text(encoding="utf-8"))
        assert "category" not in meta


# ============================================================
# 4. 页面生成契约（spec §3）
# ============================================================
def test_build_page_contract():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "tech").mkdir(parents=True)
        _tmp_knowledge(tmp, n=2)
        # 手动给主题定分类/标签（模拟 distill/classify 产出）
        p0 = tmp / "tech" / "topic-0" / "overview.md"
        m0, b0 = parse_frontmatter(p0.read_text(encoding="utf-8"))
        m0["category"] = "ai"
        m0["tags"] = ["RAG", "检索"]
        p0.write_text(dump_frontmatter(m0) + b0, encoding="utf-8")
        p1 = tmp / "tech" / "topic-1" / "overview.md"
        m1, b1 = parse_frontmatter(p1.read_text(encoding="utf-8"))
        m1["category"] = "infra"
        m1["tags"] = ["数据库"]
        p1.write_text(dump_frontmatter(m1) + b1, encoding="utf-8")
        _tpl_with_chips(tmp)

        with patch("vicky.l2_distill.KNOWLEDGE_DIR", tmp), \
             patch("vicky.l2_distill.PUBLIC_DIR", tmp), \
             patch("vicky.config.DATA_DIR", tmp), \
             patch("vicky.config.VIEWS_DIR", tmp / "views"):
            out = build_knowledge_page()

        html = out.read_text(encoding="utf-8")
        # chips 契约（全部 + 五专栏，data-c）
        assert 'class="chip on" data-c="all">全部<span class="n">2</span>' in html
        assert 'data-c="ai">AI 专栏<span class="n">1</span>' in html
        assert 'data-c="infra">后端与基础设施专栏<span class="n">1</span>' in html
        assert 'data-c="design">产品与设计专栏<span class="n">0</span>' in html
        # 分节契约
        assert '<section class="pavilion" data-category="ai">' in html
        assert '<section class="pavilion" data-category="infra">' in html
        assert '<section class="pavilion" data-category="design">' not in html  # 空栏不出节
        assert "个主题</span>" in html
        # 卡片契约
        assert 'class="kcard reveal" data-category="ai" data-tags="RAG,检索"' in html
        assert 'class="kcard reveal" data-category="infra" data-tags="数据库"' in html
        assert 'class="kcard-head"' in html
        assert 'class="kcard-body"' in html
        assert 'class="tagchip" data-t="RAG"' in html
        assert 'class="ksec ' in html
        assert 'class="ksum"' in html  # 概述首句
        assert 'data-search="' in html


def test_kcard_search_blob_lowercase():
    """data-search 全文小写：标题 + 主题名 + 各节文本。"""
    from vicky.ui import render_knowledge_card
    ov = parse_overview(dump_frontmatter(
        {"id": "x", "title": "RAG 检索", "domain": "tech", "category": "ai",
         "status": "stable", "generated": {"by": "agent:glm", "at": "2026-08-01"},
         "verified": "unverified", "sources_count": 1,
         "stale_after": "2026-11-01", "confidence": "low",
         "source_reports": ["a"], "tags": ["RAG"]}) +
        "\n## 概述\n\n混合检索能提升召回。\n\n## 核心要点\n\n- 要点 [a]\n")
    card = render_knowledge_card("ai", "rag-hybrid", ov)
    assert 'data-category="ai"' in card
    assert 'data-tags="RAG"' in card
    assert "rag-hybrid" in card and "混合检索" in card  # data-search 含主题名与正文（小写）
    assert card.count("kcard-head") == 1 and card.count("kcard-body") == 1
    # 默认收起态由 CSS/类控制，生成侧只保证 body 独立容器
    assert card.index('class="kcard-head"') < card.index('class="kcard-body"')


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("ALL PASS")
