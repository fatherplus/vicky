"""arch-node 节点卷三段硬契约门禁（spec §2）：
缺段 → 400（errors 非空）/ 三段齐整放行 / arch-overview 与默认模板不受限。"""
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from tests.util import load_server, tmp_env

server = load_server()

NODE_OK = ('<section><h2>输入与输出</h2><p>边界契约：上游事件与出参。</p>'
           '<h2>内部工作流</h2><p>状态流转与关键路径。</p>'
           '<h2>架构方案</h2><p>选型裁决：解决什么、为什么是它、不这么做呢。</p></section>')


def _post(server, path, body):
    """POST JSON → (status, parsed_json)。2026-08-12 重构后经 FastAPI TestClient。"""
    from tests.util import http_post
    return http_post(path, body)


class TestArchGate(unittest.TestCase):
    def test_missing_section_error(self):
        errors, _ = server.validate_content(
            '<h2>内部工作流</h2><h2>架构方案</h2>', template="arch-node")
        self.assertTrue(any("缺段" in e and "输入与输出" in e for e in errors))

    def test_two_sections_missing_error(self):
        errors, _ = server.validate_content('<h2>内部工作流</h2>', template="arch-node")
        self.assertTrue(any("缺段" in e and "输入与输出" in e and "架构方案" in e for e in errors))

    def test_wrong_order_error(self):
        errors, _ = server.validate_content(
            '<h2>输入与输出</h2><h2>架构方案</h2><h2>内部工作流</h2>',
            template="arch-node")
        self.assertTrue(any("顺序" in e for e in errors))

    def test_complete_passes(self):
        errors, _ = server.validate_content(NODE_OK, template="arch-node")
        self.assertEqual(errors, [])

    def test_heading_with_attrs_and_nested_tags(self):
        """h2 带 class/内嵌 span 也能命中（正则去内层标签取文本）"""
        errors, _ = server.validate_content(
            '<h2 class="sec"><span>输入</span>与输出</h2>'
            '<h2>内部工作流</h2><h2>架构方案</h2>', template="arch-node")
        self.assertEqual(errors, [])

    def test_arch_overview_not_restricted(self):
        errors, _ = server.validate_content('<h2>定位</h2><p>总览卷不受三段限制</p>',
                                            template="arch-overview")
        self.assertEqual(errors, [])

    def test_default_template_not_restricted(self):
        errors, _ = server.validate_content('<h2>只有一节</h2>')
        self.assertEqual(errors, [])

    def test_post_missing_section_400(self):
        with tmp_env(server):
            status, body = _post(server, "/api/reports", {
                "title": "坏卷", "slug": "arch-node-bad", "tag": "架构",
                "template": "arch-node", "domain": "arch",
                "content": "<h2>内部工作流</h2><h2>架构方案</h2>"})
            self.assertEqual(status, 400)
            self.assertTrue(body.get("violations"))
            self.assertTrue(any("缺段" in v for v in body["violations"]))

    def test_post_complete_created(self):
        with tmp_env(server):
            status, body = _post(server, "/api/reports", {
                "title": "好卷", "slug": "arch-node-ok", "tag": "架构",
                "template": "arch-node", "domain": "arch", "content": NODE_OK})
            self.assertEqual(status, 201)
            self.assertEqual(body["ok"], True)
    def test_validate_endpoint_honors_template(self):
        status, body = _post(server, "/api/validate", {
            "content": "<h2>架构方案</h2>", "template": "arch-node"})
        self.assertEqual(status, 200)
        self.assertTrue(body["violations"])
        status, body = _post(server, "/api/validate", {
            "content": NODE_OK, "template": "arch-node"})
        self.assertEqual(status, 200)
        self.assertEqual(body["violations"], [])

    def test_create_report_direct_call_raises(self):
        """create_report 内兜底门禁：直调方（cli/测试）绕不过三段契约"""
        with tmp_env(server) as tmp:
            with self.assertRaises(ValueError):
                server.create_report("坏卷", "arch-node-direct", "架构",
                                     "<h2>内部工作流</h2>", template="arch-node", domain="arch")


if __name__ == "__main__":
    unittest.main()
