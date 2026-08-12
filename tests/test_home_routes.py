"""首页门户 + URL 根级化（P2）：
- GET / 返回 public/home.html（五入口 + Agent 提交区）
- /reports/x.html 根级直出，与 /research/reports/x.html 同内容
- rebuild 后 home.html 存在且计数正确（reports 总数 / design 卡 / knowledge 主题）
- 路径穿越（/../ 与 /..%2f 之类）仍被拒

静态伺服走 config.PUBLIC_DIR（tmp_env 不 patch，本文件在 tmp 内显式覆盖）。
"""
import json
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from tests.util import load_server, tmp_env, http_get, live_server

server = load_server()

REPO = Path(__file__).resolve().parent.parent


def _get(server, path):
    """GET；返回 (status, body, headers)。2026-08-12 重构后经 FastAPI TestClient。"""
    return http_get(path)


def raw_status(port: int, path: str) -> int:
    """裸 socket 发原始请求行——绕过 urllib 对 ../ 的客户端归一化，真实打到服务端守卫。"""
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        req = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
        s.sendall(req.encode("utf-8"))
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    finally:
        s.close()
    return int(data.split(b"\r\n", 1)[0].split()[1])


def _mk_report(domain="tech", slug=None):
    """建一篇合法报告（走真实 create_report，含 L0 快照 + DB upsert + 重建索引/首页）。"""
    title = f"{domain} 主题报告 {slug or ''}"
    return server.create_report(
        title, slug or f"p2-{domain}-{abs(hash(title)) % 100000}", "研究报告",
        '<section><div class="wrap"><p>P2 集成测试内容。</p></div></section>',
        domain=domain)


class TestHomeRoutes(unittest.TestCase):
    def test_root_serves_home_with_entries(self):
        with tmp_env(server) as tmp:
            from vicky import config as cfg
            orig_public, orig_knowledge = cfg.PUBLIC_DIR, cfg.KNOWLEDGE_DIR
            cfg.PUBLIC_DIR, cfg.KNOWLEDGE_DIR = tmp, tmp / "knowledge"
            try:
                server.refresh_home()
                status, body, headers = _get(server, "/")
                html = body.decode("utf-8")
                self.assertEqual(status, 200)
                self.assertIn("text/html", headers.get("Content-Type", ""))
                # 首页门户特征：四区书架 + Agent 提交区（重构蓝图 2026-08-12 §04）
                for marker in ("技术文库", "项目空间", "简报", "知识库", "Agent 接入",
                               "写作指南", "CSS 资源包", "模板目录",
                               "index.html?cat=research", "href=\"knowledge\""):
                    self.assertIn(marker, html)
                # 占位符已填，未泄漏
                self.assertNotIn("__TOTAL_", html)
            finally:
                cfg.PUBLIC_DIR, cfg.KNOWLEDGE_DIR = orig_public, orig_knowledge

    def test_root_is_home_not_index(self):
        with tmp_env(server) as tmp:
            from vicky import config as cfg
            orig_public = cfg.PUBLIC_DIR
            cfg.PUBLIC_DIR = tmp
            try:
                server.rebuild_index()
                status, body, _ = _get(server, "/")
                self.assertEqual(status, 200)
                self.assertIn("首页门户", body.decode("utf-8"))
                status, body, _ = _get(server, "/index.html")
                self.assertEqual(status, 200)
                self.assertIn("目录 · CONTENTS", body.decode("utf-8"))
            finally:
                cfg.PUBLIC_DIR = orig_public

    def test_reports_root_and_research_same_content(self):
        with tmp_env(server) as tmp:
            from vicky import config as cfg
            orig_public = cfg.PUBLIC_DIR
            cfg.PUBLIC_DIR = tmp
            try:
                r = _mk_report()
                fname = r["file"]
                st1, b1, _ = _get(server, f"/reports/{fname}")
                st2, b2, _ = _get(server, f"/research/reports/{fname}")
                self.assertEqual(st1, 200)
                self.assertEqual(st1, st2)
                self.assertEqual(b1, b2)
                self.assertIn("P2 集成测试内容", b1.decode("utf-8"))
            finally:
                cfg.PUBLIC_DIR = orig_public

    def test_rebuild_generates_home_with_counts(self):
        with tmp_env(server) as tmp:
            from vicky import config as cfg
            orig_public, orig_knowledge = cfg.PUBLIC_DIR, cfg.KNOWLEDGE_DIR
            cfg.PUBLIC_DIR, cfg.KNOWLEDGE_DIR = tmp, tmp / "knowledge"
            try:
                # 知识库：两个主题（其中一个跨 domain），一个空目录不算
                (tmp / "knowledge" / "tech" / "topic-a").mkdir(parents=True)
                (tmp / "knowledge" / "tech" / "topic-a" / "overview.md").write_text("# A", encoding="utf-8")
                (tmp / "knowledge" / "design" / "topic-b").mkdir(parents=True)
                (tmp / "knowledge" / "design" / "topic-b" / "overview.md").write_text("# B", encoding="utf-8")
                (tmp / "knowledge" / "tech" / "empty").mkdir(parents=True)

                _mk_report(domain="tech", slug="p2-tech")
                _mk_report(domain="design", slug="p2-design")
                # create_report 已触发 refresh_home；再显式 rebuild 验证同触发点
                server.rebuild_index()

                home = tmp / "home.html"
                self.assertTrue(home.exists())
                html = home.read_text(encoding="utf-8")
                self.assertIn("共 2 篇报告", html)
                self.assertIn("<b>1</b> 篇", html)  # 技术文库计数（design 为 legacy，不入四区）
                self.assertIn("<b>2</b> 主题", html)
                self.assertNotIn("__TOTAL_", html)
                # 与真实 GET / 同内容
                status, body, _ = _get(server, "/")
                self.assertEqual(status, 200)
                self.assertEqual(body.decode("utf-8"), html)
            finally:
                cfg.PUBLIC_DIR, cfg.KNOWLEDGE_DIR = orig_public, orig_knowledge

    def test_traversal_still_rejected(self):
        with tmp_env(server) as tmp:
            from vicky import config as cfg
            orig_public = cfg.PUBLIC_DIR
            cfg.PUBLIC_DIR = tmp
            try:
                server.refresh_home()
                with live_server() as port:
                    # 裸 ../ 段：守卫 403
                    self.assertEqual(raw_status(port, "/../etc/passwd"), 403)
                    self.assertEqual(raw_status(port, "/research/../etc/passwd"), 403)
                    self.assertEqual(raw_status(port, "/reports/../../etc/passwd"), 403)
                    # 编码 %2f：Starlette 先解码再路由 → 还原为 ../ 段同样被守卫 403
                    # （比旧实现的 404 更严：编码穿越不再伪装成"文件不存在"）
                    self.assertEqual(raw_status(port, "/..%2fetc/passwd"), 403)
                    self.assertEqual(raw_status(port, "/reports%2f..%2f..%2fetc%2fpasswd"), 403)
            finally:
                cfg.PUBLIC_DIR = orig_public


if __name__ == "__main__":
    unittest.main()
