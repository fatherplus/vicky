import unittest
from tests.util import REPO, load_server


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
        tpl = (REPO / "template/report.html").read_text(encoding="utf-8")
        self.assertIn('<link rel="stylesheet" href="../assets/book-style.css">', tpl)
        self.assertNotIn("<style>", tpl)

    def test_index_tpl_links_asset_no_inline_style(self):
        server = load_server()
        self.assertIn('<link rel="stylesheet" href="assets/index.css">', server._INDEX_TPL)
        self.assertNotIn("<style>", server._INDEX_TPL)


if __name__ == "__main__":
    unittest.main()
