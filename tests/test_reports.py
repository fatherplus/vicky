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


class TestSeries(unittest.TestCase):
    def post(self, tmp_env_cm, **kw):
        return server.create_report(**kw)

    def test_series_meta_and_badge_baked(self):
        with tmp_env(server) as (tmp, _):
            r = server.create_report("卷一", "s-ch1", "测试", CONTENT,
                                     series="测试丛书", order=1)
            html = (tmp / "reports" / r["file"]).read_text(encoding="utf-8")
        self.assertIn('<meta name="series" content="测试丛书">', html)
        self.assertIn('<meta name="series-order" content="1">', html)
        self.assertIn('<meta name="series-total" content="1">', html)
        self.assertIn("《测试丛书》第 1 卷 · 共 1 卷", html)
        self.assertIn('<nav class="volume-nav"', html)

    def test_sibling_nav_maintained(self):
        with tmp_env(server) as (tmp, _):
            r1 = server.create_report("卷一", "s-ch1", "测试", CONTENT, series="丛书A", order=1)
            r2 = server.create_report("卷二", "s-ch2", "测试", CONTENT, series="丛书A", order=2)
            h1 = (tmp / "reports" / r1["file"]).read_text(encoding="utf-8")
            h2 = (tmp / "reports" / r2["file"]).read_text(encoding="utf-8")
        self.assertIn(f'href="{r2["file"]}">下一卷 · 卷二', h1)   # 卷一获得下一卷
        self.assertIn(f'href="{r1["file"]}">← 上一卷 · 卷一', h2)
        self.assertIn('共 2 卷', h1)                              # total 同步更新
        self.assertNotIn("上一卷", h2.split('<nav class="volume-nav"')[1].split("上一卷")[0] if "上一卷" in h2 else "x")

    def test_conflict_same_order(self):
        with tmp_env(server) as (tmp, _):
            server.create_report("卷一", "s-ch1", "测试", CONTENT, series="丛书B", order=1)
            err = server.check_series_conflict("丛书B", 1, exclude_file=None,
                                               reports=server.list_reports())
        self.assertIn("占用", err)

    def test_conflict_allows_upsert_same_slug(self):
        with tmp_env(server) as (tmp, _):
            r = server.create_report("卷一", "s-ch1", "测试", CONTENT, series="丛书C", order=1)
            err = server.check_series_conflict("丛书C", 1, exclude_file=r["file"],
                                               reports=server.list_reports())
        self.assertIsNone(err)

    def test_normalize_series(self):
        self.assertEqual(server.normalize_series("  测试   丛书 "), "测试 丛书")


if __name__ == "__main__":
    unittest.main()
