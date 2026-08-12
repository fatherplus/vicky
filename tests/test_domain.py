#!/usr/bin/env python3
"""B 阶段验收：domain 语义已彻底删除，改为 category-only。
从 test_domain.py 升级：测试 category 过滤 + extract_tech_md 统一提取。"""
from tests.util import load_server, tmp_env
from vicky.l2_distill import extract_tech_md, _DISTILL_CATEGORY

server = load_server()


def test_distill_category_is_research():
    """B 阶段：只蒸 category==research 的报告。"""
    assert _DISTILL_CATEGORY == "research"


def test_extract_tech_md_exists():
    """统一提取器 extract_tech_md 正常工作。"""
    items = extract_tech_md("# 测试\n\n> 这是一个结论性声明\n\n| col1 | col2 |\n|------|------|\n| a | b |\n", "test-source")
    # 至少抽到结论
    assert any(it["kind"] == "conclusion" for it in items)


def test_create_with_category():
    """category 替换 domain：创建报告使用 category 字段。"""
    with tmp_env(server) as tmp:
        r = server.create_report("T-cat", "test-category-brief", "测试", "<p>hello</p>", category="brief")
        assert r["ok"]
        # category 落库（元数据单一真相源在 DB，非 HTML 文本）
        from vicky import store
        rows = [x for x in store.list_reports(include_hidden=True) if x["slug"] == "test-category-brief"]
        assert rows and rows[0]["category"] == "brief"


def test_create_default_category():
    """未指定 category 时默认 research。"""
    with tmp_env(server) as tmp:
        r = server.create_report("T2-cat", "test-category-default", "测试", "<p>hello</p>")
        assert r["ok"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ALL PASS")
