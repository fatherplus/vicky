"""项目空间入口测试：仅有架构、无报告的项目（pi 型）也要有卡片与项目页。"""
import unittest

from tests.util import load_server, tmp_env
from vicky import arch, config, l1_publish, store

server = load_server()


class TestArchOnlyProjectEntry(unittest.TestCase):
    def test_arch_only_project_has_card_and_page(self):
        with tmp_env(server):
            store.create_project("solo", "Solo", "仅架构项目")
            ok, err = arch.put_graph("solo", {
                "nodes": [{"id": "a", "label": "A", "layer": 1}], "edges": []})
            self.assertTrue(ok, err)

            # index 项目卡片含 solo（项目空间入口）
            index = l1_publish.build_index(l1_publish.list_reports())
            self.assertIn("projects/solo.html", index)

            # 项目页生成且含架构导航器入口
            l1_publish.build_project_pages()
            page = config.PUBLIC_DIR / "projects" / "solo.html"
            self.assertTrue(page.exists())
            self.assertIn("/arch/solo.html", page.read_text(encoding="utf-8"))
            page.unlink()  # 清理测试残留（public/projects/ 已 gitignore）


if __name__ == "__main__":
    unittest.main()
