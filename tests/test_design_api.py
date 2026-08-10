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
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.2)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as r:
            out = (r.status, r.read(), r.headers)
    except urllib.error.HTTPError as e:
        out = (e.code, e.read(), e.headers)
    srv.shutdown()
    return out


class TestDesignApi(unittest.TestCase):
    def test_design_returns_md_twin(self):
        with tmp_env(server) as tmp:
            from ai_report import config as cfg
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
