"""2026-08-12 重构：FastAPI 新端点覆盖（category/narrative/project、项目空间、
审核治理两级操作、叙事库）。全部 tmp_env 隔离。"""
import unittest

from tests.util import load_server, tmp_env, http_get, http_post

server = load_server()

CONTENT = '<section class="reveal"><div class="wrap"><h2>定位</h2><p>内容。</p></div></section>'


class TestNewEndpoints(unittest.TestCase):
    def test_narratives_served(self):
        status, body, headers = http_get("/api/narratives")
        self.assertEqual(status, 200)
        self.assertIn("text/markdown", headers.get("Content-Type", ""))
        self.assertIn("叙事", body.decode("utf-8"))

    def test_submit_with_category_narrative_project(self):
        with tmp_env(server):
            status, data = http_post("/api/reports", {
                "title": "方案甲", "slug": "smoke-sol", "tag": "方案",
                "category": "tech-solution", "narrative": "对比擂台",
                "project": "冒烟项目", "content": CONTENT})
            self.assertEqual(status, 201)
            # 项目空间清单含该项目（D 阶段：返回 slug 为主键，非 project 名）
            status, body, _ = http_get("/api/projects")
            self.assertEqual(status, 200)
            import json
            projects = json.loads(body)["projects"]
            # "冒烟项目" 作为 name→slug 的聚合项出现（slug 或 name）
            found = any("冒烟" in (p.get("name") or p.get("slug") or "") for p in projects)
            self.assertTrue(found, f"项目清单应含冒烟项目，实际: {projects}")

    def test_submit_invalid_category_rejected(self):
        with tmp_env(server):
            status, data = http_post("/api/reports", {
                "title": "坏分类", "slug": "bad-cat", "tag": "x",
                "category": "不存在", "content": CONTENT})
            self.assertEqual(status, 400)
            self.assertIn("category", data.get("error", ""))

    def test_domain_field_ignored_defaults_research(self):
        """domain 语义已彻底删除：传 domain 字段不再影响 category，未传 category 默认 research。"""
        with tmp_env(server):
            status, data = http_post("/api/reports", {
                "title": "旧协议", "slug": "legacy-eph", "tag": "x",
                "domain": "ephemeral", "content": CONTENT})
            self.assertEqual(status, 201)
            import json
            status, body, _ = http_get("/api/reports")
            rows = json.loads(body)["reports"]
            row = next(r for r in rows if r["slug"] == "legacy-eph")
            self.assertEqual(row.get("category"), "research")

    def test_hide_restore_roundtrip(self):
        with tmp_env(server):
            http_post("/api/reports", {"title": "下架测", "slug": "hide-me",
                                       "tag": "x", "content": CONTENT})
            status, data = http_post("/api/reports/hide-me/hide", {"hidden": True})
            self.assertTrue(data.get("ok"), data)
            import json
            _, body, _ = http_get("/api/reports")
            rows = json.loads(body)["reports"]
            self.assertNotIn("hide-me", [r["slug"] for r in rows if not r.get("hidden")])
            # 恢复
            status, data = http_post("/api/reports/hide-me/hide", {"hidden": False})
            self.assertTrue(data.get("ok"), data)

    def test_hard_delete_cascade(self):
        with tmp_env(server):
            http_post("/api/reports", {"title": "删测", "slug": "del-me",
                                       "tag": "x", "content": CONTENT})
            status, data = http_post("/api/reports/del-me/delete", {})
            self.assertTrue(data.get("ok"), data)
            self.assertTrue(data["deleted"]["report_files"])
            # 再删 → 404
            status, data = http_post("/api/reports/del-me/delete", {})
            self.assertEqual(status, 404)

    def test_knowledge_audit_and_item_status(self):
        with tmp_env(server):
            status, body, _ = http_get("/api/knowledge/audit")
            self.assertEqual(status, 200)
            # 非法 status → 400
            status, data = http_post("/api/knowledge/items/no-such-id/status",
                                     {"status": "wrong"})
            self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()


class TestSkillEndpoint(unittest.TestCase):
    def test_skill_returns_valid_frontmatter_skill(self):
        """/api/skill 返回对外分发的规范 skill（含 name+description frontmatter），
        不是裸的写作参考。文件名为 SKILL.md，可被 skill 系统识别。"""
        status, body, headers = http_get("/api/skill")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn("name: vicky-writer", text)
        self.assertIn("description:", text)
        # 下载头：attachment + SKILL.md
        self.assertIn("SKILL.md", headers.get("Content-Disposition", ""))
        # 区别于 /api/guide（详细参考，无 frontmatter）
        status2, body2, _ = http_get("/api/guide")
        self.assertEqual(status2, 200)
        self.assertNotIn("name: vicky-writer", body2.decode("utf-8"))
