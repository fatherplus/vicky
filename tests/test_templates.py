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
        with tmp_env(server) as tmp:
            status, body = self.post_tpl(server, _post)
            self.assertEqual(status, 201, body)
            self.assertTrue(body["provisional"])
            self.assertTrue((server.TEMPLATES_DIR / "test-tpl" / "template.html").exists())
            self.assertIn("test-tpl", [t["name"] for t in server.list_templates()])

    def test_missing_placeholder_rejected(self):
        server = load_server()
        with tmp_env(server) as tmp:
            status, body = self.post_tpl(server, _post,
                                         template=GOOD_TPL.replace("{{CONTENT}}", ""))
            self.assertEqual(status, 400)
            self.assertTrue(any("CONTENT" in v for v in body["violations"]))

    def test_root_token_redefinition_rejected(self):
        server = load_server()
        evil = GOOD_TPL.replace("</head>", "<style>:root{--accent:#123456}</style></head>")
        with tmp_env(server) as tmp:
            status, body = self.post_tpl(server, _post, template=evil)
            self.assertEqual(status, 400)
            self.assertTrue(any(":root" in v for v in body["violations"]))

    def test_unknown_contract_entry_rejected(self):
        server = load_server()
        m = dict(GOOD_MANIFEST, narrative_contract=["not-a-principle"])
        with tmp_env(server) as tmp:
            status, body = self.post_tpl(server, _post, manifest=m)
            self.assertEqual(status, 400)

    def test_collision_rejected(self):
        server = load_server()
        with tmp_env(server) as tmp:
            self.post_tpl(server, _post)
            status, body = self.post_tpl(server, _post)   # 同名再投
            self.assertEqual(status, 400)
            self.assertIn("已存在", body["error"])

    def test_empty_rationale_rejected(self):
        server = load_server()
        with tmp_env(server) as tmp:
            status, _ = self.post_tpl(server, _post, rationale="   ")
            self.assertEqual(status, 400)


# 辅助：经真实 handler POST（复用 T9 集成矩阵的 ThreadingHTTPServer 模式）
def _post(server, path, body):
    """POST JSON → (status, parsed_json)。2026-08-12 重构后经 FastAPI TestClient。"""
    from tests.util import http_post
    return http_post(path, body)


class TestBriefTemplate(unittest.TestCase):
    def test_brief_registered(self):
        server = load_server()
        brief = next(t for t in server.list_templates() if t["name"] == "brief")
        self.assertFalse(brief["default"])
        self.assertIn("why-first", brief["narrative_contract"])
        self.assertIn("type-determines-narrative", brief["narrative_contract"])

    def test_brief_renders_with_all_placeholders_resolved(self):
        server = load_server()
        with tmp_env(server) as tmp:
            r = server.create_report("决策简报", "brief-render", "Executive Brief",
                '<section><div class="wrap"><div class="callout note"><h4>TL;DR</h4>'
                '<p>结论。</p></div><p>依据。</p></div></section>', template="brief")
            html = (tmp / "reports" / r["file"]).read_text(encoding="utf-8")
        self.assertIn('<meta name="template" content="brief">', html)
        self.assertNotIn("{{", html)                      # 占位符全部解析
        self.assertIn("../assets/book-style.css", html)   # 共享视觉语言
        self.assertNotIn("bar-tabs", html)                # brief 无章节 tab（单次阅读）


class TestContractVocabulary(unittest.TestCase):
    """契约词表同步：宪法 §3 / NARRATIVE_CONTRACTS / 各 manifest 三处一致。"""

    def test_book_declares_full_contract(self):
        server = load_server()
        book = next(t for t in server.list_templates() if t["name"] == "book")
        self.assertEqual(set(book["narrative_contract"]), server.NARRATIVE_CONTRACTS)

    def test_brief_contract_is_valid_subset(self):
        server = load_server()
        brief = next(t for t in server.list_templates() if t["name"] == "brief")
        self.assertIn("conclusion-first", brief["narrative_contract"])  # brief 即结论先行
        self.assertTrue(set(brief["narrative_contract"]) <= server.NARRATIVE_CONTRACTS)

    def test_principles_doc_lists_every_contract_id(self):
        server = load_server()
        text = (server.TEMPLATES_DIR.parent / "skill" / "NARRATIVE-PRINCIPLES.md").read_text(encoding="utf-8")
        for cid in server.NARRATIVE_CONTRACTS:
            self.assertIn(f"`{cid}`", text, f"宪法 §3 缺少契约条目 {cid}")
