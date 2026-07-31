#!/usr/bin/env python3
"""阶段1 验收：domain 字段 + ephemeral 隔离"""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from server import create_report, list_reports, DOMAINS, REPORTS_DIR

def test_domain_constant():
    assert DOMAINS == {"tech", "design", "ephemeral"}

def test_create_with_domain():
    r = create_report("T", "test-domain", "测试", "<p>hello</p>", domain="ephemeral")
    assert r["ok"]
    # 回读 HTML 确认 meta 烙入
    html = (REPORTS_DIR / r["file"]).read_text(encoding="utf-8")
    assert '<meta name="domain" content="ephemeral">' in html

def test_create_default_domain():
    r = create_report("T2", "test-domain-default", "测试", "<p>hello</p>")
    assert r["ok"]
    html = (REPORTS_DIR / r["file"]).read_text(encoding="utf-8")
    assert '<meta name="domain" content="tech">' in html

def test_list_reports_reads_domain():
    create_report("T3", "test-domain-list", "测试", "<p>hello</p>", domain="design")
    reports = list_reports()
    match = [r for r in reports if r["file"].endswith("test-domain-list.html")]
    assert match, "report not found in list"
    assert match[0]["domain"] == "design"

def test_legacy_report_defaults_tech():
    # 存量报告无 domain meta → list_reports 返回 tech
    create_report("T4", "test-domain-legacy", "测试", "<p>hello</p>")
    # 手动删掉 domain meta 模拟存量
    p = REPORTS_DIR / "2026-07-31-test-domain-legacy.html"
    if not p.exists():
        # 找实际文件名
        matches = list(REPORTS_DIR.glob("*test-domain-legacy*"))
        p = matches[0]
    html = p.read_text(encoding="utf-8")
    html = html.replace('<meta name="domain" content="tech">', '')
    p.write_text(html, encoding="utf-8")
    reports = list_reports()
    match = [r for r in reports if "test-domain-legacy" in r["file"]]
    assert match[0]["domain"] == "tech"

def cleanup():
    for f in REPORTS_DIR.glob("*test-domain*"):
        f.unlink()


import atexit
atexit.register(cleanup)  # pytest 不走 __main__，用 atexit 保证清场

if __name__ == "__main__":
    test_domain_constant()
    test_create_with_domain()
    test_create_default_domain()
    test_list_reports_reads_domain()
    test_legacy_report_defaults_tech()
    cleanup()
    print("ALL PASS")
