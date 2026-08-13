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


if __name__ == "__main__":
    unittest.main()
