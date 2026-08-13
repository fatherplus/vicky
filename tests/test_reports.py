import re
import unittest
from tests.util import load_server, tmp_env

server = load_server()
CONTENT = '<section><div class="wrap"><p>正文</p></div></section>'


class TestUpsert(unittest.TestCase):
    def test_second_post_overwrites_same_file(self):
        with tmp_env(server) as tmp:
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
        with tmp_env(server) as tmp:
            server.create_report("新", "fresh-slug", "测试", CONTENT)
            html = next((tmp / "reports").glob("*.html")).read_text(encoding="utf-8")
        self.assertNotIn('name="updated"', html)

    def test_multiple_legacy_files_warns(self):
        with tmp_env(server) as tmp:
            (tmp / "reports" / "2026-01-01-dup.html").write_text("<title>旧1</title>", encoding="utf-8")
            (tmp / "reports" / "2026-01-02-dup.html").write_text("<title>旧2</title>", encoding="utf-8")
            r = server.create_report("新", "dup", "测试", CONTENT)
        self.assertFalse(r["created"])
        self.assertTrue(any("历史文件" in w for w in r["warnings"]))
        self.assertEqual(r["file"], "2026-01-02-dup.html")  # 覆盖最新一份

    def test_suffix_slug_no_clobber(self):
        """短 slug 是长 slug 的后缀 → 必须新建第二份，不得覆盖前者（数据丢失回归）"""
        with tmp_env(server) as tmp:
            r1 = server.create_report("长 slug", "top-k-adaptive-retrieval", "测试", CONTENT)
            r2 = server.create_report("短 slug", "adaptive-retrieval", "测试", CONTENT)
            files = sorted(f.name for f in (tmp / "reports").glob("*.html"))
            long_html = (tmp / "reports" / r1["file"]).read_text(encoding="utf-8")
        self.assertTrue(r1["created"])
        self.assertTrue(r2["created"])                  # 第二次是新建，不是覆盖
        self.assertNotEqual(r1["file"], r2["file"])
        self.assertEqual(len(files), 2)                 # 两文件都在
        self.assertIn("长 slug", long_html)             # 前者内容未被覆盖


class TestListReportsUpdated(unittest.TestCase):
    def test_updated_scraped_and_badge(self):
        with tmp_env(server) as tmp:
            server.create_report("原", "badge-case", "测试", CONTENT)
            server.create_report("订", "badge-case", "测试", CONTENT)
            reports = server.list_reports()
            idx = server.build_index(reports)
        self.assertEqual(reports[0]["updated"], __import__("datetime").datetime.now().strftime("%Y-%m-%d"))
        self.assertIn("订", idx)                            # 索引徽章


class TestIndexGrouping(unittest.TestCase):
    def test_chronological_stream_and_filter_attrs(self):
        with tmp_env(server) as tmp:
            server.create_report("卷一", "bk-ch1", "深度解析", CONTENT)
            server.create_report("卷二", "bk-ch2", "深度解析", CONTENT)
            server.create_report("甲", "r1", "向量检索", CONTENT)
            server.create_report("孤", "r4", "冷门tag", CONTENT)
            idx = server.build_index(server.list_reports())
        # 时间流：同日期按文件名倒序（新在上）
        self.assertLess(idx.index("孤"), idx.index("甲"))
        self.assertLess(idx.index("卷二"), idx.index("卷一"))
        self.assertNotIn("fascicle", idx)
        # 筹码：全部 + tag；小 tag 不再合并进「其他」，诚实展示
        self.assertIn('data-type="all"', idx)
        self.assertIn('data-f="向量检索"', idx)
        self.assertIn('data-f="冷门tag"', idx)
        self.assertNotIn("其他", idx)
        # 行携带筛选属性
        self.assertIn('data-tag="深度解析"', idx)


class TestIndexChips(unittest.TestCase):
    def test_chip_counts(self):
        with tmp_env(server) as tmp:
            server.create_report("甲", "c1", "向量检索", CONTENT)
            server.create_report("乙", "c2", "向量检索", CONTENT)
            server.create_report("丙", "c3", "向量检索", CONTENT)
            idx = server.build_index(server.list_reports())
        self.assertIn('data-f="向量检索">向量检索<span class="n">3</span>', idx)
        # 四区重构后筹码改为 分类（全部/技术文库/项目空间/简报）+ 标签 + 项目，丛书不再单独成筹码
        self.assertIn('技术文库<span class="n">3</span>', idx)
        self.assertIn('全部<span class="n">3</span>', idx)

if __name__ == "__main__":
    unittest.main()
