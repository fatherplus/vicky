"""D 阶段测试：先建项目 + .vicky 联动（POST/GET /api/projects、project 字段校验）。
所有测试走 tmp_env 隔离（临时 data/ 目录 + sqlite DB）。"""
import json
import unittest

from tests.util import load_server, tmp_env, http_get, http_post

server = load_server()

CONTENT = '<section class="reveal"><div class="wrap"><h2>定位</h2><p>内容。</p></div></section>'


class TestProjectsCRUD(unittest.TestCase):
    """POST /api/projects 建项目 + GET /api/projects 查清单。"""

    def test_create_project_success(self):
        """建项目→GET 清单含该项目→slug 由 name 自动生成。"""
        with tmp_env(server):
            status, data = http_post("/api/projects", {
                "name": "Vicky 知识平台", "description": "个人知识管理"})
            self.assertEqual(status, 201)
            self.assertTrue(data["ok"])
            proj = data["project"]
            self.assertEqual(proj["name"], "Vicky 知识平台")
            self.assertIn("Vicky", proj["slug"])  # ui.project_slug 生成，中文保留
            self.assertEqual(proj["description"], "个人知识管理")

    def test_create_project_with_explicit_slug(self):
        """显式指定 slug → 用传入值。"""
        with tmp_env(server):
            status, data = http_post("/api/projects", {
                "name": "冒烟", "slug": "smoke-test"})
            self.assertEqual(status, 201)
            self.assertEqual(data["project"]["slug"], "smoke-test")

    def test_create_duplicate_rejected(self):
        """重复 slug → 409 报错。"""
        with tmp_env(server):
            http_post("/api/projects", {"name": "第一次", "slug": "dup"})
            status, data = http_post("/api/projects", {"name": "第二次", "slug": "dup"})
            self.assertEqual(status, 409)
            self.assertFalse(data["ok"])
            self.assertIn("已存在", data["error"])

    def test_create_missing_name_rejected(self):
        """name 缺省 → 400。"""
        with tmp_env(server):
            status, data = http_post("/api/projects", {"slug": "no-name"})
            self.assertEqual(status, 400)
            self.assertFalse(data["ok"])

    def test_list_projects_empty(self):
        """无项目时返回空列表。"""
        with tmp_env(server):
            status, body, _ = http_get("/api/projects")
            self.assertEqual(status, 200)
            projects = json.loads(body)["projects"]
            self.assertEqual(projects, [])

    def test_list_projects_with_meta_and_aggregation(self):
        """建项目 + 投报告 → GET /api/projects 含 count/latest 聚合。"""
        with tmp_env(server):
            # 1. 先建项目
            http_post("/api/projects", {"name": "项目甲", "slug": "proj-a"})

            # 2. 投两篇报告该项目
            http_post("/api/reports", {
                "title": "方案1", "slug": "sol-1", "tag": "方案",
                "category": "tech-solution", "project": "proj-a",
                "content": CONTENT})
            http_post("/api/reports", {
                "title": "方案2", "slug": "sol-2", "tag": "方案",
                "category": "tech-solution", "project": "proj-a",
                "content": CONTENT})

            # 3. GET /api/projects
            status, body, _ = http_get("/api/projects")
            self.assertEqual(status, 200)
            projects = json.loads(body)["projects"]
            self.assertGreaterEqual(len(projects), 1)
            proj = next(p for p in projects if p["slug"] == "proj-a")
            self.assertEqual(proj["name"], "项目甲")
            self.assertEqual(proj["count"], 2)
            self.assertNotEqual(proj["latest"], "")


class TestProjectValidationInReports(unittest.TestCase):
    """POST /api/reports 的 project 字段校验（宽松匹配：slug → name）。"""

    def test_submit_with_registered_project_ok(self):
        """project 已注册 → 正常投稿，无 warning。"""
        with tmp_env(server):
            http_post("/api/projects", {"name": "已建项目", "slug": "registered"})
            status, data = http_post("/api/reports", {
                "title": "测试", "slug": "with-proj", "tag": "x",
                "category": "tech-solution", "project": "registered",
                "content": CONTENT})
            self.assertEqual(status, 201)
            warnings = data.get("warnings", [])
            proj_warnings = [w for w in warnings if "未注册" in w]
            self.assertEqual(proj_warnings, [], f"不应有未注册警告，实际: {warnings}")

    def test_submit_with_unregistered_project_warns(self):
        """project 未注册 → warning 提示，不拒收。"""
        with tmp_env(server):
            status, data = http_post("/api/reports", {
                "title": "未建项目", "slug": "no-proj", "tag": "x",
                "category": "tech-solution", "project": "幽灵",
                "content": CONTENT})
            self.assertEqual(status, 201)
            warnings = data.get("warnings", [])
            self.assertTrue(any("未注册" in w for w in warnings),
                            f"应包含项目未注册警告，实际 warnings: {warnings}")

    def test_submit_with_empty_project_no_warning(self):
        """project 为空 → 不触发校验。"""
        with tmp_env(server):
            status, data = http_post("/api/reports", {
                "title": "无项目", "slug": "no-proj2", "tag": "x",
                "category": "research", "content": CONTENT})
            self.assertEqual(status, 201)
            warnings = data.get("warnings", [])
            self.assertFalse(any("未注册" in w for w in warnings))

    def test_submit_project_by_name_loose_match(self):
        """project 填的是 name（如'Vicky 知识平台'），按 name 宽松匹配。"""
        with tmp_env(server):
            http_post("/api/projects", {"name": "Vicky 知识平台", "slug": "vicky"})
            # 投稿时 project 用完整名称
            status, data = http_post("/api/reports", {
                "title": "测试", "slug": "loose-match", "tag": "x",
                "category": "tech-solution", "project": "Vicky 知识平台",
                "content": CONTENT})
            self.assertEqual(status, 201)
            # 名称匹配已建项目 → 无"未注册" warning
            warnings = data.get("warnings", [])
            proj_warnings = [w for w in warnings if "未注册" in w]
            self.assertEqual(proj_warnings, [],
                            f"name 宽松匹配应消除警告，实际: {warnings}")


if __name__ == "__main__":
    unittest.main()
