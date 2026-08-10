"""P1 测试：backfill 往返——抽一篇真实报告验证元数据齐全（只读不写）。"""
import json
import tempfile
from pathlib import Path

from vicky import config
from vicky.cli import _extract_main_content, _extract_meta

REPO_DIR = Path(__file__).resolve().parent.parent


def _pick_sample_report() -> Path:
    """选一篇真实报告用于往返验证。"""
    reports = sorted((REPO_DIR / "public" / "reports").glob("*.html"))
    # 优先选 why-this-book（元数据最全：有 kicker / subtitle / domain 信息）
    for name in ("why-this-book", "agent-knowledge-sources", "ponytail"):
        for r in reports:
            if name in r.name:
                return r
    return reports[0]


def test_backfill_extract_main_content():
    """验证 <main> 反解能剥离 opener 和 colophon，保留 agent 原始 content。"""
    sample = _pick_sample_report()
    html = sample.read_text(encoding="utf-8")
    content = _extract_main_content(html)
    assert content, f"{sample.name}: 反解内容不应为空"
    # 不应包含 opener 区的 kicker（那是模板烙入的）
    assert 'class="opener"' not in content
    # 不应包含 colophon
    assert 'class="colophon"' not in content
    # 应包含实际报告内容（至少有 section 或 wrap）
    assert '<section' in content or '<div class="wrap"' in content or '<div class="container"' in content


def test_backfill_extract_meta():
    """验证元数据提取：title/tag/subtitle/template/domain。"""
    sample = _pick_sample_report()
    html = sample.read_text(encoding="utf-8")
    meta = _extract_meta(html)

    # title 从 <title> 取（不在 _extract_meta 中，由 backfill 单独提取）
    import re
    tm = re.search(r"<title>(.+?)</title>", html)
    title = tm.group(1).strip() if tm else ""

    assert title, f"{sample.name}: 应能提取标题"
    assert "template" in meta
    assert meta["template"] in ("book", "brief")
    assert "domain" in meta
    assert meta["domain"] in ("tech", "design", "ephemeral")


def test_backfill_payload_roundtrip():
    """验证整条 backfill 链路：HTML → payload → submission.json（不污染真实 data/）。"""
    sample = _pick_sample_report()
    html = sample.read_text(encoding="utf-8")

    import re
    # 解析 slug 和 date
    m = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)\.html$", sample.name)
    assert m, f"文件名格式不匹配: {sample.name}"
    date_str, slug = m.group(1), m.group(2)

    # 提取
    tm = re.search(r"<title>(.+?)</title>", html)
    title = tm.group(1).strip() if tm else slug
    content = _extract_main_content(html)
    meta = _extract_meta(html)

    # 构造 payload（同 backfill 逻辑）
    payload = {
        "title": title, "slug": slug, "tag": meta.get("tag", "研究报告"),
        "content": content, "subtitle": meta.get("subtitle", ""),
        "series": meta.get("series", ""), "order": meta.get("series_order", 0),
        "template": meta.get("template", "book"), "domain": meta.get("domain", "tech"),
    }

    # 写入临时目录
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        l0_path = tmp / "l0" / slug / "0001"
        l0_path.mkdir(parents=True, exist_ok=True)
        envelope = {
            "received_at": f"{date_str}T00:00:00+00:00",
            "source_ip": "backfill",
            "schema_version": "1.0",
            "provenance": "backfill",
            "payload": payload,
        }
        (l0_path / "submission.json").write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")

        # 回读验证
        saved = json.loads((l0_path / "submission.json").read_text(encoding="utf-8"))
        assert saved["provenance"] == "backfill"
        assert saved["schema_version"] == "1.0"
        p = saved["payload"]
        assert p["title"] == title
        assert p["slug"] == slug
        assert len(p["content"]) > 0
        assert p["template"] in ("book", "brief")
        assert p["domain"] in ("tech", "design", "ephemeral")


def test_backfill_preserves_markup():
    """反解 content 保留 agent 原始标记（表格/图片/链接不丢）。"""
    sample = _pick_sample_report()
    html = sample.read_text(encoding="utf-8")
    content = _extract_main_content(html)

    # 至少保留一种 HTML 结构标记
    has_markup = any(tag in content for tag in
                     ["<table", "<img", "<a href", "<pre", "<code", "<figure", "<ul", "<ol", "<blockquote"])
    assert has_markup, f"{sample.name}: 反解内容应保留 HTML 标记"
