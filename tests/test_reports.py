import re
import unittest
from tests.util import load_server, tmp_env

server = load_server()
CONTENT = '<section><div class="wrap"><p>正文</p></div></section>'


class TestUpsert(unittest.TestCase):
    def test_second_post_overwrites_same_file(self):
        with tmp_env(server) as (tmp, _):
            r1 = server.create_report("原稿", "upsert-case", "测试", CONTENT)
            r2 = server.create_report("修订稿", "upsert-case", "测试", CONTENT)
            files = list((tmp / "reports").glob("*-upsert-case.html"))
            html = files[0].read_text(encoding="utf-8") if files else ""
        self.assertEqual(r1["file"], r2["file"])          # 文件名（原日期）保留
        self.assertTrue(r1["created"])
        self.assertFalse(r2["created"])
        self.assertEqual(len(files), 1)
        self.assertIn("修订稿", html)                      # 内容已覆盖
        self.assertIn('<meta name="updated" content="', html)

    def test_fresh_slug_has_no_updated_meta(self):
        with tmp_env(server) as (tmp, _):
            server.create_report("新", "fresh-slug", "测试", CONTENT)
            html = next((tmp / "reports").glob("*.html")).read_text(encoding="utf-8")
        self.assertNotIn('name="updated"', html)

    def test_multiple_legacy_files_warns(self):
        with tmp_env(server) as (tmp, _):
            (tmp / "reports" / "2026-01-01-dup.html").write_text("<title>旧1</title>", encoding="utf-8")
            (tmp / "reports" / "2026-01-02-dup.html").write_text("<title>旧2</title>", encoding="utf-8")
            r = server.create_report("新", "dup", "测试", CONTENT)
        self.assertFalse(r["created"])
        self.assertTrue(any("历史文件" in w for w in r["warnings"]))
        self.assertEqual(r["file"], "2026-01-02-dup.html")  # 覆盖最新一份


class TestListReportsUpdated(unittest.TestCase):
    def test_updated_scraped_and_badge(self):
        with tmp_env(server) as (tmp, _):
            server.create_report("原", "badge-case", "测试", CONTENT)
            server.create_report("订", "badge-case", "测试", CONTENT)
            reports = server.list_reports()
            idx = server.build_index(reports)
        self.assertEqual(reports[0]["updated"], __import__("datetime").datetime.now().strftime("%Y-%m-%d"))
        self.assertIn("订", idx)                            # 索引徽章


if __name__ == "__main__":
    unittest.main()
