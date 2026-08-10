import unittest
from tests.util import REPO, load_server, tmp_env


class TestSharedAssets(unittest.TestCase):
    def test_book_style_extracted(self):
        css = (REPO / "public/assets/book-style.css").read_text(encoding="utf-8")
        for marker in ("--paper", ".cmp-verdict", ".figure", "@view-transition"):
            self.assertIn(marker, css, f"book-style.css 缺少 {marker}")

    def test_index_style_extracted(self):
        css = (REPO / "public/assets/index.css").read_text(encoding="utf-8")
        for marker in ("--paper", ".toc-item", ".frontispiece"):
            self.assertIn(marker, css)

    def test_template_links_asset_no_inline_style(self):
        tpl = (REPO / "templates/book/template.html").read_text(encoding="utf-8")
        self.assertIn('<link rel="stylesheet" href="../assets/book-style.css">', tpl)
        self.assertNotIn("<style>", tpl)

    def test_index_tpl_links_asset_no_inline_style(self):
        # P3 前端抢救：_INDEX_TPL 迁到 views/index.html，检查视图文件本身
        tpl = (REPO / "views/index.html").read_text(encoding="utf-8")
        self.assertIn('<link rel="stylesheet" href="/assets/index.css">', tpl)
        self.assertNotIn("<style>", tpl)

    def test_knowledge_tpl_links_external_css_no_inline_style(self):
        # P3 前端抢救：knowledge.html 引外部 knowledge.css，无内联 style
        tpl = (REPO / "views/knowledge.html").read_text(encoding="utf-8")
        self.assertIn('<link rel="stylesheet" href="/assets/knowledge.css">', tpl)
        self.assertNotIn("<style>", tpl)
        # 验证 knowledge.css 存在并包含核心选择器
        css = (REPO / "public/assets/knowledge.css").read_text(encoding="utf-8")
        for marker in (".kcard", ".pavilion", ".seal-big", ".masthead"):
            self.assertIn(marker, css, f"knowledge.css 缺少 {marker}")


class TestTemplateRegistry(unittest.TestCase):
    def test_book_registered_with_manifest(self):
        server = load_server()
        names = [t["name"] for t in server.list_templates()]
        self.assertIn("book", names)
        book = next(t for t in server.list_templates() if t["name"] == "book")
        self.assertTrue(book["default"])
        self.assertTrue(book["narrative_contract"])   # 至少一条契约
        self.assertTrue((server.TEMPLATES_DIR / "book" / "template.html").exists())

    def test_template_path_resolution(self):
        server = load_server()
        self.assertEqual(server.template_path("book").name, "template.html")
        with self.assertRaises(KeyError):
            server.template_path("no-such-template")

    def test_create_report_bakes_template_meta(self):
        server = load_server()
        with tmp_env(server) as tmp:
            r = server.create_report("T", "tpl-meta", "测试",
                                     '<section><div class="wrap"><p>x</p></div></section>')
            html = (tmp / "reports" / r["file"]).read_text(encoding="utf-8")
        self.assertIn('<meta name="template" content="book">', html)

    def test_create_report_unknown_template_rejected(self):
        server = load_server()
        with tmp_env(server) as tmp:
            with self.assertRaises(KeyError):
                server.create_report("T", "tpl-x", "测试", "<p>x</p>", template="ghost")


if __name__ == "__main__":
    unittest.main()
