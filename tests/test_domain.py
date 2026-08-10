#!/usr/bin/env python3
"""阶段1 验收：domain 字段 + ephemeral 隔离。
P0 包化：import 更新。P1：隔离 DATA_DIR 避免污染真实 DB。"""
from tests.util import load_server, tmp_env
from ai_report.config import DOMAINS
from ai_report.l2_distill import EXTRACTORS

server = load_server()


def test_domain_constant():
    assert DOMAINS == {"tech", "design", "ephemeral", "arch"}


def test_extractors_only_tech():
    """spec §1：design 退出自动蒸馏，EXTRACTORS 只留 tech。"""
    assert set(EXTRACTORS) == {"tech"}


def test_create_with_domain():
    with tmp_env(server) as tmp:
        r = server.create_report("T", "test-domain", "测试", "<p>hello</p>", domain="ephemeral")
        assert r["ok"]
        html = (tmp / "reports" / r["file"]).read_text(encoding="utf-8")
        assert '<meta name="domain" content="ephemeral">' in html


def test_create_default_domain():
    with tmp_env(server) as tmp:
        r = server.create_report("T2", "test-domain-default", "测试", "<p>hello</p>")
        assert r["ok"]
        html = (tmp / "reports" / r["file"]).read_text(encoding="utf-8")
        assert '<meta name="domain" content="tech">' in html


def test_create_with_arch_domain():
    with tmp_env(server) as tmp:
        r = server.create_report("T", "test-domain-arch", "测试", "<p>hello</p>", domain="arch")
        assert r["ok"]
        html = (tmp / "reports" / r["file"]).read_text(encoding="utf-8")
        assert '<meta name="domain" content="arch">' in html


def test_list_reports_reads_domain():
    with tmp_env(server) as tmp:
        server.create_report("T3", "test-domain-list", "测试", "<p>hello</p>", domain="design")
        reports = server.list_reports()
        match = [r for r in reports if r["file"].endswith("test-domain-list.html")]
        assert match, "report not found in list"
        assert match[0]["domain"] == "design"


def test_legacy_report_defaults_tech():
    with tmp_env(server) as tmp:
        server.create_report("T4", "test-domain-legacy", "测试", "<p>hello</p>")
        # 找实际文件名
        matches = list((tmp / "reports").glob("*test-domain-legacy*"))
        p = matches[0]
        html = p.read_text(encoding="utf-8")
        html = html.replace('<meta name="domain" content="tech">', '')
        p.write_text(html, encoding="utf-8")
        reports = server.list_reports()
        match = [r for r in reports if "test-domain-legacy" in r["file"]]
        assert match[0]["domain"] == "tech"


if __name__ == "__main__":
    test_domain_constant()
    test_extractors_only_tech()
    test_create_with_domain()
    test_create_with_arch_domain()
    test_create_default_domain()
    test_list_reports_reads_domain()
    test_legacy_report_defaults_tech()
    print("ALL PASS")
