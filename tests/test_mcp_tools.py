"""P2: MCP 写入线工具（submit_report / submit_feedback / register_template / authoring_guide）。

经真实 Handler POST /mcp 走 JSON-RPC tools/call；文件/DB 写入一律 tmp_env 隔离。

工具注册是显式的（register_default_tools），不在模块 import 期自动填充——
P1 协议测试（test_mcp_protocol::test_tools_list）断言 tools/list 为空。
本文件按字母序排在 test_mcp_protocol 之后运行，setUpClass 里注册不影响前者的空断言。

错误码约定：
- tools/call 未知工具 → -32602 invalid params（P1 契约 test_unknown_tool_call 固定，本文件沿用）
- 未知 JSON-RPC 方法 → -32601 method not found
"""
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from tests.util import load_server, tmp_env

server = load_server()


def _post_mcp(body):
    """POST /mcp，返回 (status, body_bytes)。"""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.2)
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            out = (r.status, r.read())
    except urllib.error.HTTPError as e:
        out = (e.code, e.read())
    srv.shutdown()
    return out


def _call_tool(name, arguments):
    """tools/call 封装：返回 (http_status, jsonrpc_data)。"""
    status, body = _post_mcp({"jsonrpc": "2.0", "method": "tools/call",
                              "params": {"name": name, "arguments": arguments}, "id": 1})
    return status, json.loads(body)


def _tool_result(data):
    """从成功响应的 result.content 解出 handler 返回的 dict。"""
    return json.loads(data["result"]["content"][0]["text"])


# 合法内容（通过表述规范门禁）
GOOD_CONTENT = ('<section><div class="wrap"><h2>为什么</h2>'
                '<p>场景痛点说明。</p></div></section>')

# 合法模板（占位符齐全、不重定义 :root token）
GOOD_TPL = "".join([
    "<html><head><title>{{TITLE}}</title>{{META}}",
    '<link rel="stylesheet" href="../assets/book-style.css">{{COMPONENT_HEAD}}</head>',
    "<body><h1>{{TITLE}}</h1><div>{{HERO_TAG}}{{SUBTITLE}}{{DATE}}{{SERIES_BADGE}}</div>",
    "{{VOLUME_NAV}}{{CONTENT}}</body></html>"])
GOOD_MANIFEST = {"name": "mcp-tpl", "purpose": "MCP 测试模板",
                 "document_types": ["测试"], "narrative_contract": ["why-first"]}


class TestMcpTools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 显式注册（幂等）：P1 协议测试在本文件之前运行，不受影响。
        from vicky.mcp import register_default_tools
        register_default_tools()

    # ── 注册表 ──
    def test_tools_list_has_four(self):
        status, body = _post_mcp({"jsonrpc": "2.0", "method": "tools/list",
                                  "params": {}, "id": 2})
        self.assertEqual(status, 200)
        names = [t["name"] for t in json.loads(body)["result"]["tools"]]
        self.assertEqual(sorted(names), ["authoring_guide", "register_template",
                                         "submit_feedback", "submit_report"])

    # ── Tool 1: submit_report ──
    def test_submit_report_dry_run(self):
        with tmp_env(server) as tmp:
            status, data = _call_tool("submit_report", {
                "title": "MCP 预检冒烟", "slug": "mcp-tool-smoke",
                "content": GOOD_CONTENT, "dry_run": True})
            self.assertEqual(status, 200)
            self.assertNotIn("error", data)
            result = _tool_result(data)
            self.assertTrue(result["dry_run"])
            self.assertIsInstance(result["violations"], list)
            self.assertIsInstance(result["warnings"], list)
            self.assertEqual(result["ok"], True)
            # 预检不落盘：无 HTML/MD 产物、无 L0 快照
            self.assertEqual(list(server.REPORTS_DIR.glob("*.html")), [])
            self.assertFalse((tmp / "data" / "l0").exists())

    def test_submit_report_gate_violations_returned_as_result(self):
        """门禁失败走 result content（violations 数组），不抛 JSON-RPC error。"""
        with tmp_env(server):
            bad = '<section><div class="wrap"><table><tr><td>x</td></tr></table></div></section>'
            status, data = _call_tool("submit_report", {
                "title": "坏表格", "slug": "mcp-bad-table",
                "content": bad, "dry_run": False})
            self.assertEqual(status, 200)
            self.assertNotIn("error", data)
            result = _tool_result(data)
            self.assertFalse(result["ok"])
            self.assertFalse(result["submitted"])
            self.assertTrue(any("table" in v.lower() or "裸" in v for v in result["violations"]))
            # 未落盘
            self.assertEqual(list(server.REPORTS_DIR.glob("*.html")), [])

    def test_submit_report_real_publishes_url_and_md(self):
        with tmp_env(server) as tmp:
            status, data = _call_tool("submit_report", {
                "title": "MCP 提交冒烟", "slug": "mcp-tool-real",
                "tag": "研究报告", "content": GOOD_CONTENT})
            self.assertEqual(status, 200)
            self.assertNotIn("error", data)
            result = _tool_result(data)
            self.assertTrue(result["ok"])
            self.assertTrue(result["submitted"])
            url, md_url = result["url"], result["md_url"]
            self.assertTrue(url.endswith(".html"), url)
            self.assertTrue(md_url.endswith(".md"), md_url)
            self.assertEqual(md_url, url[:-5] + ".md")
            # HTML + MD 孪生落盘
            fname = url.split("/")[-1]
            self.assertTrue((server.REPORTS_DIR / fname).exists())
            self.assertTrue((server.REPORTS_DIR / (fname[:-5] + ".md")).exists())
            # L0 快照落盘
            l0 = tmp / "data" / "l0"
            self.assertTrue(l0.exists())
            self.assertTrue(any(p.name == "submission.json" for p in l0.rglob("submission.json")))
            # 入库可查（list_reports 走 tmp DB；条目以 file 标识）
            self.assertTrue(any("mcp-tool-real" in r["file"] for r in server.list_reports()))

    def test_submit_report_missing_required_params_error(self):
        with tmp_env(server):
            status, data = _call_tool("submit_report", {"title": "无内容", "slug": "x"})
            self.assertEqual(data["error"]["code"], -32602)
            self.assertIn("content", data["error"]["message"])

    def test_submit_report_invalid_domain_error(self):
        with tmp_env(server):
            status, data = _call_tool("submit_report", {
                "title": "t", "slug": "t", "content": GOOD_CONTENT, "domain": "bogus"})
            self.assertEqual(data["error"]["code"], -32602)
            self.assertIn("domain", data["error"]["message"])

    # ── Tool 2: submit_feedback ──
    def test_submit_feedback_validation(self):
        """缺 evidence → JSON-RPC error（evidence 必填）。"""
        with tmp_env(server):
            status, data = _call_tool("submit_feedback",
                                      {"topic": "x", "domain": "tech"})
            self.assertEqual(status, 200)
            self.assertEqual(data["error"]["code"], -32602)
            self.assertIn("evidence", data["error"]["message"])

    def test_submit_feedback_happy_path(self):
        """合法反馈（topic 须已蒸馏存在）→ 返回 id + pending。"""
        with tmp_env(server):
            status, data = _call_tool("submit_feedback", {
                "topic": "hnsw-algorithm", "domain": "tech", "agent": "mcp-test",
                "evidence": "实测 hnsw 检索延迟符合 overview 描述（小数据集 10 万条 8ms）",
                "opinion": "建议补充索引构建耗时的对比", "cited": ["test-report-1"]})
            self.assertEqual(status, 200)
            self.assertNotIn("error", data)
            result = _tool_result(data)
            self.assertIsInstance(result["id"], int)
            self.assertEqual(result["status"], "pending")
            self.assertEqual(result["topic"], "hnsw-algorithm")

    def test_submit_feedback_nonexistent_topic_error(self):
        with tmp_env(server):
            status, data = _call_tool("submit_feedback", {
                "topic": "no-such-topic", "domain": "tech", "agent": "a",
                "evidence": "e", "opinion": "o"})
            self.assertEqual(data["error"]["code"], -32602)
            self.assertIn("不存在", data["error"]["message"])

    # ── Tool 3: register_template ──
    def test_register_template_happy_path(self):
        with tmp_env(server):
            status, data = _call_tool("register_template", {
                "name": "mcp-tpl", "manifest": dict(GOOD_MANIFEST),
                "template": GOOD_TPL, "rationale": "现有模板无法承载 MCP 测试目的"})
            self.assertEqual(status, 200)
            self.assertNotIn("error", data)
            result = _tool_result(data)
            self.assertTrue(result["ok"])
            self.assertTrue(result["provisional"])
            self.assertTrue((server.TEMPLATES_DIR / "mcp-tpl" / "template.html").exists())
            self.assertTrue((server.TEMPLATES_DIR / "mcp-tpl" / "manifest.json").exists())
            self.assertIn("mcp-tpl", [t["name"] for t in server.list_templates()])

    def test_register_template_duplicate_rejected(self):
        with tmp_env(server):
            body = {"name": "mcp-tpl", "manifest": dict(GOOD_MANIFEST),
                    "template": GOOD_TPL, "rationale": "现有模板无法承载 MCP 测试目的"}
            _call_tool("register_template", body)
            status, data = _call_tool("register_template", body)
            self.assertEqual(data["error"]["code"], -32602)
            self.assertIn("已存在", data["error"]["message"])

    def test_register_template_missing_placeholder_rejected(self):
        with tmp_env(server):
            status, data = _call_tool("register_template", {
                "name": "mcp-bad", "manifest": dict(GOOD_MANIFEST),
                "template": GOOD_TPL.replace("{{CONTENT}}", ""),
                "rationale": "x"})
            self.assertEqual(data["error"]["code"], -32602)
            self.assertIn("CONTENT", data["error"]["message"])

    # ── Tool 4: authoring_guide ──
    def test_authoring_guide(self):
        status, body = _post_mcp({"jsonrpc": "2.0", "method": "tools/call",
                                  "params": {"name": "authoring_guide", "arguments": {}},
                                  "id": 3})
        self.assertEqual(status, 200)
        result = json.loads(json.loads(body)["result"]["content"][0]["text"])
        # 四件套齐全
        self.assertIn("guide", result)
        self.assertIn("templates", result)
        self.assertIn("domains", result)
        self.assertIn("principles", result)
        # 内容非空且成结构
        self.assertTrue(result["guide"].strip())
        self.assertTrue(result["principles"].strip())
        self.assertTrue(any(t["name"] == "book" for t in result["templates"]))
        self.assertTrue(all(t.get("description") for t in result["templates"]))
        self.assertEqual(sorted(result["domains"].keys()), ["arch", "design", "ephemeral", "tech"])
        # 宪法要点在场（契约条目 ID 表）
        self.assertIn("type-determines-narrative", result["principles"])

    # ── 错误契约 ──
    def test_method_not_found(self):
        """tools/call 未注册工具 → JSON-RPC error。
        P1 契约（test_unknown_tool_call）固定 tools/call 未知工具为 -32602 invalid params；
        纯 JSON-RPC 未知方法才是 -32601（见 test_unknown_rpc_method_is_32601）。"""
        status, data = _call_tool("nonexistent-tool", {})
        self.assertEqual(status, 200)
        self.assertEqual(data["error"]["code"], -32602)
        self.assertIn("Unknown tool", data["error"]["message"])

    def test_unknown_rpc_method_is_32601(self):
        status, body = _post_mcp({"jsonrpc": "2.0", "method": "bogus/method",
                                  "params": {}, "id": 9})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
