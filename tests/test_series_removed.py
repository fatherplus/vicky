"""D 阶段：arch-doc 退场 + series 丛书删除（test_series_removed）。

TestArchDocGone（D1）：四分类 → 三类，arch-doc 不再是合法分类。
TestSeriesGone（D3）：series/order 字段不再处理，产物无丛书导航残留。
"""
import unittest

from tests.util import load_server, tmp_env, http_post
from vicky import config

server = load_server()

CONTENT = '<section class="reveal"><div class="wrap"><p>正文</p></div></section>'


class TestArchDocGone(unittest.TestCase):
    def test_arch_doc_not_in_categories(self):
        self.assertNotIn("arch-doc", config.REPORT_CATEGORIES)

    def test_submit_arch_doc_rejected(self):
        with tmp_env(server):
            st, r = http_post("/api/reports", {
                "title": "x", "slug": "x-arch", "content": CONTENT,
                "category": "arch-doc"})
            # arch-doc 不再是合法分类 → 400 拒收；无论如何不得以 arch-doc 收录
            self.assertEqual(st, 400, r)
            self.assertNotEqual(r.get("category"), "arch-doc")


class TestSeriesGone(unittest.TestCase):
    def test_series_submit_no_volume_nav_in_output(self):
        with tmp_env(server):
            st, r = http_post("/api/reports", {
                "title": "卷一", "slug": "s1",
                "content": "<section class='reveal'><div class='wrap'><p>正文</p></div></section>",
                "category": "research", "series": "某丛书", "order": 1})
            # 带 series 字段的提交仍能成功（series 已不再处理，作为多余字段忽略，不报卷号冲突）
            self.assertEqual(st, 201, r)
            # 产物 HTML 无丛书导航 / series 徒章残留
            html = (config.REPORTS_DIR / r["file"]).read_text(encoding="utf-8") \
                if r.get("file") else ""
            if not html:
                # 后端未回 file 字段时，按目录取唯一产物
                htmls = list(config.REPORTS_DIR.glob("*s1*.html"))
                html = htmls[0].read_text(encoding="utf-8") if htmls else ""
            self.assertNotIn("volume-nav", html)
            self.assertNotIn("series-badge", html)

    def test_book_template_no_series_placeholder(self):
        tpl = (config.TEMPLATES_DIR / "book" / "template.html").read_text(encoding="utf-8")
        self.assertNotIn("SERIES_BADGE", tpl)
        self.assertNotIn("VOLUME_NAV", tpl)


if __name__ == "__main__":
    unittest.main()
