import json
import unittest
from tests.util import load_server, tmp_env, http_get, http_post, http_put
from vicky import store

server = load_server()


class TestArchTables(unittest.TestCase):
    def test_arch_tables_created(self):
        with tmp_env(server):
            conn = store.get_db()
            try:
                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                ).fetchall()}
            finally:
                conn.close()
            self.assertIn("arch_graphs", tables)
            self.assertIn("arch_modules", tables)
            self.assertIn("arch_modules_fts", tables)


class TestArchGraph(unittest.TestCase):
    def test_graph_roundtrip(self):
        with tmp_env(server):
            g = {"nodes": [{"id": "core", "kind": "module", "layer": 2,
                            "label": "core", "summary": "枢纽"}],
                 "edges": [], "layout": {}}
            store.save_arch_graph("vicky", g)
            got = store.get_arch_graph("vicky")
            self.assertEqual(got, g)

    def test_graph_missing_returns_none(self):
        with tmp_env(server):
            self.assertIsNone(store.get_arch_graph("nope"))


class TestArchModule(unittest.TestCase):
    def test_module_upsert_and_get(self):
        with tmp_env(server):
            store.save_arch_module("vicky", "core", "module", "枢纽正文")
            m = store.get_arch_module("vicky", "core")
            self.assertEqual(m["kind"], "module")
            self.assertEqual(m["body_md"], "枢纽正文")
            self.assertEqual(m["status"], "active")

    def test_module_missing_returns_none(self):
        with tmp_env(server):
            self.assertIsNone(store.get_arch_module("vicky", "nope"))

    def test_search_hits_active_only(self):
        with tmp_env(server):
            store.save_arch_module("vicky", "core", "module", "会话运行时枢纽")
            store.save_arch_module("vicky", "old", "module", "会话运行时旧模块")
            store.mark_arch_orphans("vicky", ["core"])  # old 变孤儿
            hits = store.search_arch_modules("vicky", "会话运行时")
            ids = {h["node_id"] for h in hits}
            self.assertIn("core", ids)
            self.assertNotIn("old", ids)


class TestArchService(unittest.TestCase):
    def test_put_graph_requires_registered_project(self):
        with tmp_env(server):
            from vicky import arch
            ok, err = arch.put_graph("ghost", {"nodes": [], "edges": [], "layout": {}})
            self.assertFalse(ok)
            self.assertIn("未注册", err)

    def test_put_graph_marks_orphans(self):
        with tmp_env(server):
            from vicky import arch
            store.create_project("vicky", "vicky")
            store.save_arch_module("vicky", "old", "module", "旧内容")
            g = {"nodes": [{"id": "core", "kind": "module", "layer": 1,
                            "label": "core", "summary": ""}],
                 "edges": [], "layout": {}}
            ok, err = arch.put_graph("vicky", g)
            self.assertTrue(ok, err)
            m = store.get_arch_module("vicky", "old")
            self.assertEqual(m["status"], "orphan")


class TestArchAPI(unittest.TestCase):
    def test_full_arch_lifecycle(self):
        with tmp_env(server):
            http_post("/api/projects", {"name": "demo"})
            g = {"nodes": [{"id": "core", "kind": "module", "layer": 1,
                            "label": "core", "summary": "枢纽"}],
                 "edges": [], "layout": {}}
            # PUT 骨架
            st, r = http_put("/api/arch/demo", g)
            self.assertTrue(r["ok"], r)
            # GET 骨架
            st, body, _ = http_get("/api/arch/demo")
            data = json.loads(body)
            self.assertEqual(data["graph"]["nodes"][0]["id"], "core")
            # PUT 模块
            st, r = http_put("/api/arch/demo/module/core",
                             {"kind": "module", "body_md": "会话运行时枢纽"})
            self.assertTrue(r["ok"], r)
            # GET 模块
            st, body, _ = http_get("/api/arch/demo/module/core")
            data = json.loads(body)
            self.assertEqual(data["body_md"], "会话运行时枢纽")
            # search
            st, body, _ = http_get("/api/arch/demo/search?q=会话运行时")
            data = json.loads(body)
            self.assertTrue(any(i["node_id"] == "core" for i in data["items"]))

    def test_put_graph_unregistered_project_400(self):
        with tmp_env(server):
            st, r = http_put("/api/arch/ghost",
                             {"nodes": [], "edges": [], "layout": {}})
            self.assertEqual(st, 400)
            self.assertFalse(r["ok"])


class TestProjectPageArchEntry(unittest.TestCase):
    def test_arch_entry_present_with_graph(self):
        with tmp_env(server):
            from vicky import ui
            html = ui.arch_entry_html("vicky", has_arch=True)
            self.assertIn("架", html)
            self.assertIn("/arch/vicky.html", html)

    def test_arch_entry_empty_state(self):
        with tmp_env(server):
            from vicky import ui
            html = ui.arch_entry_html("vicky", has_arch=False)
            self.assertIn("待 agent 生成", html)
            self.assertNotIn("/arch/vicky.html", html)


class TestArchRender(unittest.TestCase):
    def test_render_contains_nodes_and_conditions(self):
        with tmp_env(server):
            from vicky import arch
            store.create_project("vicky", "vicky")
            g = {"nodes": [
                    {"id": "cli", "kind": "module", "layer": 1, "label": "cli", "summary": "入口"},
                    {"id": "r1", "kind": "router", "layer": 1, "label": "模式路由", "summary": "分流"}],
                 "edges": [{"from": "cli", "to": "r1"},
                           {"from": "r1", "to": "cli", "condition": "无参 → interactive"}],
                 "layout": {}}
            arch.put_graph("vicky", g)
            html = arch.render_arch_page("vicky", g)
            self.assertIn("cli", html)
            self.assertIn("模式路由", html)
            self.assertIn("无参 → interactive", html)


if __name__ == "__main__":
    unittest.main()
