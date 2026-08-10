"""卡片墙（spec §3）：domain=design 报告 → public/design.html 生成，
封面取 assets/img/{slug}/ 按名排序第一张，无图给占位样式，随发布与 rebuild_index 刷新。"""
import unittest

from tests.util import load_server, tmp_env

server = load_server()


class TestCardWall(unittest.TestCase):
    def test_wall_generated_with_cover(self):
        with tmp_env(server) as tmp:
            import ai_report.config as cfg
            old = cfg.IMG_DIR
            cfg.IMG_DIR = tmp / "assets" / "img"
            try:
                img_dir = cfg.IMG_DIR / "card-foo"
                img_dir.mkdir(parents=True)
                (img_dir / "02-b.png").write_bytes(b"png2")
                (img_dir / "01-a.png").write_bytes(b"png1")
                server.create_report("侧边导航产品", "card-foo", "侧边导航",
                                     "<section><div class='wrap'><p>x</p></div></section>",
                                     subtitle="风格说明：克制灰 + 圆角大图",
                                     template="card", domain="design")
                wall = (tmp / "design.html").read_text(encoding="utf-8")
            finally:
                cfg.IMG_DIR = old
        self.assertIn("侧边导航产品", wall)                       # 标题入墙
        self.assertIn("风格说明", wall)                          # subtitle 入墙
        self.assertIn("assets/img/card-foo/01-a.png", wall)     # 按名排序第一张作封面
        self.assertNotIn("02-b.png", wall)                      # 第二张不出现在封面
        self.assertIn("共 1 张", wall)
        self.assertIn("/research/reports/", wall)               # 卡片链到报告页

    def test_placeholder_without_image(self):
        with tmp_env(server) as tmp:
            server.create_report("无图产品", "card-nopic", "主题",
                                 "<p>x</p>", template="card", domain="design")
            wall = (tmp / "design.html").read_text(encoding="utf-8")
        self.assertIn("暂无封面", wall)
        self.assertIn("card-nopic", wall)

    def test_tech_report_not_in_wall(self):
        with tmp_env(server) as tmp:
            server.create_report("技术文章", "tech-x", "技术", "<p>x</p>")
            wall = (tmp / "design.html").read_text(encoding="utf-8")
        self.assertNotIn("技术文章", wall)
        self.assertIn("共 0 张", wall)

    def test_rebuild_index_refreshes_wall(self):
        """cli render 重渲染路径：rebuild_index 也刷新墙页"""
        with tmp_env(server) as tmp:
            server.create_report("产品A", "card-a", "主题", "<p>x</p>",
                                 template="card", domain="design")
            wall_before = (tmp / "design.html").read_text(encoding="utf-8")
            server.create_report("产品B", "card-b", "主题", "<p>x</p>",
                                 template="card", domain="design")
            server.rebuild_index()
            wall_after = (tmp / "design.html").read_text(encoding="utf-8")
        self.assertIn("产品A", wall_before)
        self.assertIn("产品A", wall_after)
        self.assertIn("产品B", wall_after)

    def test_wall_output_uses_index_dir(self):
        """design.html 与 index.html 同目录（发布即 public/）"""
        with tmp_env(server) as tmp:
            server.create_report("产品C", "card-c", "主题", "<p>x</p>",
                                 template="card", domain="design")
            self.assertTrue((tmp / "index.html").exists())
            self.assertTrue((tmp / "design.html").exists())


if __name__ == "__main__":
    unittest.main()
