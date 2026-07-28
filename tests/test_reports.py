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


class TestSeries(unittest.TestCase):
    def post(self, tmp_env_cm, **kw):
        return server.create_report(**kw)

    def test_series_meta_and_badge_baked(self):
        with tmp_env(server) as tmp:
            r = server.create_report("卷一", "s-ch1", "测试", CONTENT,
                                     series="测试丛书", order=1)
            html = (tmp / "reports" / r["file"]).read_text(encoding="utf-8")
        self.assertIn('<meta name="series" content="测试丛书">', html)
        self.assertIn('<meta name="series-order" content="1">', html)
        self.assertIn('<meta name="series-total" content="1">', html)
        self.assertIn("《测试丛书》第 1 卷 · 共 1 卷", html)
        self.assertIn('<nav class="volume-nav"', html)

    def test_sibling_nav_maintained(self):
        with tmp_env(server) as tmp:
            r1 = server.create_report("卷一", "s-ch1", "测试", CONTENT, series="丛书A", order=1)
            r2 = server.create_report("卷二", "s-ch2", "测试", CONTENT, series="丛书A", order=2)
            h1 = (tmp / "reports" / r1["file"]).read_text(encoding="utf-8")
            h2 = (tmp / "reports" / r2["file"]).read_text(encoding="utf-8")
        self.assertIn(f'href="{r2["file"]}">下一卷 · 卷二', h1)   # 卷一获得下一卷
        self.assertIn(f'href="{r1["file"]}">← 上一卷 · 卷一', h2)
        self.assertIn('共 2 卷', h1)                              # total 同步更新
        self.assertNotIn("上一卷", h2.split('<nav class="volume-nav"')[1].split("上一卷")[0] if "上一卷" in h2 else "x")

    def test_conflict_same_order(self):
        with tmp_env(server) as tmp:
            server.create_report("卷一", "s-ch1", "测试", CONTENT, series="丛书B", order=1)
            err = server.check_series_conflict("丛书B", 1, exclude_file=None,
                                               reports=server.list_reports())
        self.assertIn("占用", err)

    def test_conflict_allows_upsert_same_slug(self):
        with tmp_env(server) as tmp:
            r = server.create_report("卷一", "s-ch1", "测试", CONTENT, series="丛书C", order=1)
            err = server.check_series_conflict("丛书C", 1, exclude_file=r["file"],
                                               reports=server.list_reports())
        self.assertIsNone(err)

    def test_handler_exclude_path_allows_upsert_same_slug(self):
        """handler 同款 exclude 计算（glob 取 [-1].name）：修订本卷不误报，另一 slug 占同卷号仍冲突。"""
        with tmp_env(server) as tmp:
            server.create_report("卷一", "s-ch1", "测试", CONTENT, series="丛书D", order=1)
            # 与 do_POST /api/reports 完全相同的 exclude 计算路径
            slug = "s-ch1"
            existing = sorted(server.REPORTS_DIR.glob(f"*-{slug}.html"))
            exclude_file = existing[-1].name if existing else None
            err = server.check_series_conflict("丛书D", 1, exclude_file=exclude_file,
                                               reports=server.list_reports())
            self.assertIsNone(err)                       # 修订本卷不自我冲突
            # 另一 slug 占同卷号 → 仍冲突（exclude 只排除本卷）
            other = sorted(server.REPORTS_DIR.glob("*-s-other.html"))
            other_exclude = other[-1].name if other else None
            err2 = server.check_series_conflict("丛书D", 1, exclude_file=other_exclude,
                                                reports=server.list_reports())
        self.assertIn("占用", err2)

    def test_conflict_detected_with_special_chars(self):
        """丛书名含 & < > 时：刮取侧 unescape 后，卷号门禁不漏判、兄弟导航不碎片化。"""
        with tmp_env(server) as tmp:
            server.create_report("卷一", "a1", "测试", CONTENT, series="ML & 系统", order=1)
            err = server.check_series_conflict("ML & 系统", 1, exclude_file=None,
                                               reports=server.list_reports())
            self.assertIn("占用", err)  # 转义不击穿门禁
            r2 = server.create_report("卷二", "a2", "测试", CONTENT, series="ML & 系统", order=2)
            h2 = (tmp / "reports" / r2["file"]).read_text(encoding="utf-8")
        self.assertIn("上一卷", h2)  # 兄弟集合不碎片化，maintain 正确互链

    def test_normalize_series(self):
        self.assertEqual(server.normalize_series("  测试   丛书 "), "测试 丛书")


class TestIndexGrouping(unittest.TestCase):
    def _mk(self, tmp, title, slug, tag, series="", order=0, date="2026-07-26"):
        server.create_report(title, slug, tag, CONTENT, series=series, order=order)

    def test_chronological_stream_and_filter_attrs(self):
        with tmp_env(server) as tmp:
            self._mk(tmp, "卷一", "bk-ch1", "深度解析", "丛书X", 1)
            self._mk(tmp, "卷二", "bk-ch2", "深度解析", "丛书X", 2)
            self._mk(tmp, "甲", "r1", "向量检索", None, 0)
            self._mk(tmp, "孤", "r4", "冷门tag", None, 0)
            idx = server.build_index(server.list_reports())
        # 时间流：同日期按文件名倒序（新在上），丛书卷不再单独分函
        self.assertLess(idx.index("孤"), idx.index("甲"))
        self.assertLess(idx.index("卷二"), idx.index("卷一"))
        self.assertNotIn("fascicle", idx)
        # 筹码：全部 + tag + 丛书；小 tag 不再合并进「其他」，诚实展示
        self.assertIn('data-type="all"', idx)
        self.assertIn('data-f="向量检索"', idx)
        self.assertIn('data-f="冷门tag"', idx)
        self.assertNotIn("其他", idx)
        self.assertIn("《丛书X》", idx)
        # 行携带筛选属性
        self.assertIn('data-tag="深度解析"', idx)
        self.assertIn('data-series="丛书X"', idx)
class TestIndexChips(unittest.TestCase):
    def test_chip_counts(self):
        with tmp_env(server) as tmp:
            server.create_report("甲", "c1", "向量检索", CONTENT)
            server.create_report("乙", "c2", "向量检索", CONTENT)
            server.create_report("丙", "c3", "向量检索", CONTENT, series="丛书Z", order=1)
            idx = server.build_index(server.list_reports())
        self.assertIn('data-f="向量检索">向量检索<span class="n">3</span>', idx)
        self.assertIn('data-f="丛书Z">《丛书Z》<span class="n">1</span>', idx)
        self.assertIn('全部<span class="n">3</span>', idx)

if __name__ == "__main__":
    unittest.main()
