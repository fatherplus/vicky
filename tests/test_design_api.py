"""design.md 总纲 + CSS 资源包端点（spec §3）：
GET /api/design 返回 DESIGN_DOC_SLUG 报告 .md 孪生（text/markdown）；
GET /api/design.css 附件下载 book-style.css。"""
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from tests.util import load_server, tmp_env

server = load_server()

REPO = Path(__file__).resolve().parent.parent


def _get(server, path):
    """GET；返回 (status, body, headers)。2026-08-12 重构后经 FastAPI TestClient。"""
    from tests.util import http_get
    return http_get(path)


class TestDesignApi(unittest.TestCase):
    def test_design_returns_md_twin(self):
        with tmp_env(server) as tmp:
            from vicky import config as cfg
            r = server.create_report(
                "为什么是这本书", cfg.DESIGN_DOC_SLUG, "META 关于本书",
                '<section><div class="wrap"><p>design token 总纲：一页讲清各项目 CSS 怎么存怎么维护。</p></div></section>')
            md = (tmp / "reports" / (r["file"][:-5] + ".md")).read_text(encoding="utf-8")
            status, body, headers = _get(server, "/api/design")
        self.assertEqual(status, 200)
        self.assertIn("text/markdown", headers.get("Content-Type", ""))
        self.assertEqual(body.decode("utf-8"), md)

    def test_design_404_when_not_published(self):
        with tmp_env(server) as tmp:
            status, body, _ = _get(server, "/api/design")
        self.assertEqual(status, 404)
        self.assertIn("design", body.decode("utf-8"))

    def test_design_css_download(self):
        with tmp_env(server) as tmp:
            status, body, headers = _get(server, "/api/design.css")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers.get("Content-Disposition", ""))
        self.assertEqual(body, (REPO / "public" / "assets" / "book-style.css").read_bytes())


if __name__ == "__main__":
    unittest.main()
