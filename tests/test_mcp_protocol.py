"""P1: MCP 协议层（POST /mcp, JSON-RPC 2.0 over HTTP, stateless）。

覆盖：initialize / tools/list / ping / 方法不存在(-32601) / 非法 JSON(-32700) / 通知（无 id 不回体）。
"""
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from tests.util import load_server

server = load_server()


def _post_mcp(body, raw=False):
    """POST /mcp。raw=True 时 body 原样发送（测非法 JSON）。"""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.2)
    data = body.encode() if raw else json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp", data=data,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            out = (r.status, r.read())
    except urllib.error.HTTPError as e:
        out = (e.code, e.read())
    srv.shutdown()
    return out


class TestMcpProtocol(unittest.TestCase):
    def test_initialize(self):
        status, body = _post_mcp({"jsonrpc": "2.0", "method": "initialize",
                                  "params": {}, "id": 1})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["jsonrpc"], "2.0")
        self.assertEqual(data["id"], 1)
        result = data["result"]
        self.assertEqual(result["serverInfo"]["name"], "vicky")
        self.assertEqual(result["serverInfo"]["version"], "0.1.0")
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["protocolVersion"], "2024-11-05")

    def test_tools_list(self):
        status, body = _post_mcp({"jsonrpc": "2.0", "method": "tools/list",
                                  "params": {}, "id": 2})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["result"]["tools"], [])

    def test_ping(self):
        status, body = _post_mcp({"jsonrpc": "2.0", "method": "ping",
                                  "params": {}, "id": 3})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["result"], {})

    def test_method_not_found(self):
        status, body = _post_mcp({"jsonrpc": "2.0", "method": "bogus/method",
                                  "params": {}, "id": 4})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["error"]["code"], -32601)
        self.assertIn("bogus/method", data["error"]["message"])
        self.assertEqual(data["id"], 4)

    def test_invalid_json(self):
        status, body = _post_mcp('{"jsonrpc": "2.0", "method": ', raw=True)
        self.assertEqual(status, 400)
        data = json.loads(body)
        self.assertEqual(data["error"]["code"], -32700)
        self.assertEqual(data["id"], None)

    def test_notification(self):
        """无 id 的请求是通知：执行但不回响应体（HTTP 202 空体）。"""
        status, body = _post_mcp({"jsonrpc": "2.0", "method": "ping", "params": {}})
        self.assertEqual(status, 202)
        self.assertEqual(body, b"")

    def test_unknown_tool_call(self):
        """tools/call 未注册工具 → -32602 invalid params（MCP 约定）。"""
        status, body = _post_mcp({"jsonrpc": "2.0", "method": "tools/call",
                                  "params": {"name": "nope"}, "id": 5})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
