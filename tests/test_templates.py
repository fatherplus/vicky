import unittest
from tests.util import load_server, tmp_env

GOOD_TPL = "".join([
    "<html><head><title>{{TITLE}}</title>{{META}}",
    '<link rel="stylesheet" href="../assets/book-style.css">{{COMPONENT_HEAD}}</head>',
    "<body><h1>{{TITLE}}</h1><div>{{HERO_TAG}}{{SUBTITLE}}{{DATE}}{{SERIES_BADGE}}</div>",
    "{{VOLUME_NAV}}{{CONTENT}}</body></html>"])
GOOD_MANIFEST = {"name": "test-tpl", "purpose": "测试用模板",
                 "document_types": ["测试"], "narrative_contract": ["why-first"]}


class TestCreateTemplate(unittest.TestCase):
    def post_tpl(self, server, http, **over):
        body = {"name": "test-tpl", "manifest": dict(GOOD_MANIFEST),
                "template": GOOD_TPL, "rationale": "现有模板无法承载测试目的"}
        body.update(over)
        return http(server, "/api/templates", body)

    def test_happy_path_created_and_listed(self):
        server = load_server()
        with tmp_env(server) as (tmp, _):
            status, body = self.post_tpl(server, _post)
            self.assertEqual(status, 201, body)
            self.assertTrue(body["provisional"])
            self.assertTrue((server.TEMPLATES_DIR / "test-tpl" / "template.html").exists())
            self.assertIn("test-tpl", [t["name"] for t in server.list_templates()])

    def test_missing_placeholder_rejected(self):
        server = load_server()
        with tmp_env(server) as (tmp, _):
            status, body = self.post_tpl(server, _post,
                                         template=GOOD_TPL.replace("{{CONTENT}}", ""))
            self.assertEqual(status, 400)
            self.assertTrue(any("CONTENT" in v for v in body["violations"]))

    def test_root_token_redefinition_rejected(self):
        server = load_server()
        evil = GOOD_TPL.replace("</head>", "<style>:root{--accent:#123456}</style></head>")
        with tmp_env(server) as (tmp, _):
            status, body = self.post_tpl(server, _post, template=evil)
            self.assertEqual(status, 400)
            self.assertTrue(any(":root" in v for v in body["violations"]))

    def test_unknown_contract_entry_rejected(self):
        server = load_server()
        m = dict(GOOD_MANIFEST, narrative_contract=["not-a-principle"])
        with tmp_env(server) as (tmp, _):
            status, body = self.post_tpl(server, _post, manifest=m)
            self.assertEqual(status, 400)

    def test_collision_rejected(self):
        server = load_server()
        with tmp_env(server) as (tmp, _):
            self.post_tpl(server, _post)
            status, body = self.post_tpl(server, _post)   # 同名再投
            self.assertEqual(status, 400)
            self.assertIn("已存在", body["error"])

    def test_empty_rationale_rejected(self):
        server = load_server()
        with tmp_env(server) as (tmp, _):
            status, _ = self.post_tpl(server, _post, rationale="   ")
            self.assertEqual(status, 400)


# 辅助：经真实 handler POST（复用 T9 集成矩阵的 ThreadingHTTPServer 模式）
def _post(server, path, body):
    import json, threading, time, urllib.request, urllib.error
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    time.sleep(0.2)
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            out = (r.status, json.loads(r.read()))
    except urllib.error.HTTPError as e:
        out = (e.code, json.loads(e.read()))
    srv.shutdown()
    return out
