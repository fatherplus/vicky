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

    def test_orphan_revives_when_re_added(self):
        with tmp_env(server):
            store.save_arch_module("vicky", "core", "module", "会话运行时枢纽")
            store.mark_arch_orphans("vicky", [])  # core → orphan
            self.assertEqual(store.get_arch_module("vicky", "core")["status"], "orphan")
            store.mark_arch_orphans("vicky", ["core"])  # core → active（复活）
            self.assertEqual(store.get_arch_module("vicky", "core")["status"], "active")
            hits = store.search_arch_modules("vicky", "会话运行时")
            self.assertIn("core", {h["node_id"] for h in hits})


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

    def test_put_graph_bad_nodes_rejected(self):
        with tmp_env(server):
            from vicky import arch
            store.create_project("vicky", "vicky")
            ok, err = arch.put_graph("vicky",
                                     {"nodes": ["x"], "edges": [], "layout": {}})
            self.assertFalse(ok)
            self.assertIn("nodes", err)
            ok2, err2 = arch.put_graph("vicky",
                                       {"nodes": {}, "edges": [], "layout": {}})
            self.assertFalse(ok2)

    def test_search_returns_label(self):
        with tmp_env(server):
            from vicky import arch
            store.create_project("vicky", "vicky")
            g = {"nodes": [{"id": "core", "kind": "module", "layer": 1,
                            "label": "会话运行时", "summary": ""}],
                 "edges": [], "layout": {}}
            store.save_arch_graph("vicky", g)
            store.save_arch_module("vicky", "core", "module", "会话运行时枢纽")
            items = arch.search("vicky", "会话")
            self.assertTrue(items)
            self.assertEqual(items[0]["label"], "会话运行时")


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

# ============================================================
# 架构导航器（分层图渲染 / 深链 / router 语义 / 孤儿清理 / md 安全）
# ============================================================

PI_GRAPH = {
    "nodes": [
        {"id": "pi-entry", "label": "React Pi 入口", "kind": "entry", "layer": 0,
         "summary": "用户交互入口：承接终端 UI，将输入交给运行时。"},
        {"id": "pi-runtime", "label": "Pi 核心运行时", "kind": "process", "layer": 1,
         "summary": "最小编码代理内核。"},
        {"id": "pi-session", "label": "会话与上下文", "kind": "storage", "layer": 2,
         "summary": "JSONL 会话树。"},
        {"id": "pi-resources", "label": "资源与信任加载器", "kind": "process", "layer": 2,
         "summary": "加载 settings、skills。"},
        {"id": "pi-extension-host", "label": "扩展宿主", "kind": "gateway", "layer": 2,
         "summary": "ExtensionAPI 插件加载。"},
        {"id": "aimeter", "label": "Aimeter 模型网关插件", "kind": "plugin", "layer": 3,
         "summary": "动态发现网关模型。"},
        {"id": "memory-weaver", "label": "Memory Weaver 记忆插件", "kind": "plugin", "layer": 3,
         "summary": "记忆提取。"},
        {"id": "code-intelligence", "label": "代码理解插件组", "kind": "plugin", "layer": 3,
         "summary": "Hashline、LSP。"},
        {"id": "web-access", "label": "外部信息插件组", "kind": "plugin", "layer": 3,
         "summary": "网页搜索。"},
        {"id": "workflow-engine", "label": "工作流编排插件", "kind": "plugin", "layer": 3,
         "summary": "并行 agents。"},
        {"id": "guardrails", "label": "安全与行为约束插件组", "kind": "plugin", "layer": 3,
         "summary": "命令风险拦截。"},
        {"id": "interaction-tools", "label": "状态与交互插件组", "kind": "plugin", "layer": 3,
         "summary": "任务状态。"},
        {"id": "method-skills", "label": "方法论技能层", "kind": "plugin", "layer": 3,
         "summary": "按需加载技能。"},
    ],
    "edges": [
        {"from": "pi-entry", "to": "pi-runtime", "condition": "提交用户输入"},
        {"from": "pi-runtime", "to": "pi-session", "condition": "读取或写入会话上下文"},
        {"from": "pi-runtime", "to": "pi-resources", "condition": "启动与资源发现"},
        {"from": "pi-runtime", "to": "pi-extension-host", "condition": "注册与触发扩展事件"},
        {"from": "pi-extension-host", "to": "aimeter", "condition": "注册模型 provider"},
        {"from": "pi-extension-host", "to": "memory-weaver", "condition": "会话 hooks、工具和状态栏"},
        {"from": "pi-extension-host", "to": "code-intelligence", "condition": "注册代码理解工具"},
        {"from": "pi-extension-host", "to": "web-access", "condition": "注册信息获取工具"},
        {"from": "pi-extension-host", "to": "workflow-engine", "condition": "注册 agent 编排工具"},
        {"from": "pi-extension-host", "to": "guardrails", "condition": "拦截风险命令或注入约束"},
        {"from": "pi-extension-host", "to": "interaction-tools", "condition": "渲染状态与变更反馈"},
        {"from": "pi-resources", "to": "method-skills", "condition": "发现并按需加载技能"},
    ],
    "layout": {},
}

PI_RUNTIME_BODY = (
    "## 输入与输出\n"
    "输入为已处理的用户消息、上下文、模型配置与可用工具。\n\n"
    "## 内部工作流\n"
    "1. 启动时合并设置与发现资源。\n"
    "2. 驱动 LLM 与工具调用循环。\n\n"
    "## 架构方案\n"
    "- **最小核心 + 扩展机制**：解决不同团队工作流差异大。\n"
)


class TestArchGraphRender(unittest.TestCase):
    def test_pi_graph_edges_and_labels_reach_output(self):
        from vicky import arch
        html = arch.render_arch_page("pi", PI_GRAPH)
        self.assertEqual(html.count('<path class="arch-edge"'), 12)
        self.assertIn('marker-end="url(#arch-arrow)"', html)
        self.assertIn('data-from="pi-runtime"', html)
        self.assertIn('data-to="pi-session"', html)
        self.assertIn('data-from="pi-resources"', html)
        self.assertIn('data-to="method-skills"', html)
        for e in PI_GRAPH["edges"]:
            self.assertIn(e["condition"], html)

    def test_generated_page_excludes_module_body(self):
        from vicky import arch
        html = arch.render_arch_page("pi", PI_GRAPH)
        self.assertNotIn("输入为已处理的用户消息", html)
        self.assertNotIn("## 输入与输出", html)
        self.assertNotIn("ARCH_MODULES", html)


class TestArchDeepLink(unittest.TestCase):
    def test_module_deep_link_written_and_contains_content(self):
        import vicky.config as cfg
        with tmp_env(server) as tmp:
            _pub = cfg.PUBLIC_DIR
            cfg.PUBLIC_DIR = tmp / "public"
            try:
                from vicky import arch
                store.create_project("pi", "pi")
                store.save_arch_graph("pi", PI_GRAPH)
                store.save_arch_module("pi", "pi-runtime", "process", PI_RUNTIME_BODY)
                self.assertTrue(arch.publish_arch_pages("pi"))
                f = cfg.PUBLIC_DIR / "arch" / "pi" / "pi-runtime.html"
                self.assertTrue(f.exists())
                text = f.read_text(encoding="utf-8")
                self.assertIn("输入与输出", text)
                self.assertIn("Pi 核心运行时", text)
            finally:
                cfg.PUBLIC_DIR = _pub


class TestArchRouter(unittest.TestCase):
    def test_router_node_gets_router_semantics(self):
        from vicky import arch
        g = {"nodes": [
                {"id": "r1", "kind": "router", "layer": 1, "label": "模式路由", "summary": ""},
                {"id": "m1", "kind": "module", "layer": 2, "label": "模块", "summary": ""},
                {"id": "p1", "kind": "plugin", "layer": 2, "label": "插件", "summary": ""},
             ],
             "edges": [], "layout": {}}
        html = arch.render_arch_page("vicky", g)
        self.assertIn('data-kind="router"', html)
        self.assertIn('<span class="arch-node-kind">路由</span>', html)
        self.assertIn('data-kind="module"', html)
        self.assertIn('data-kind="plugin"', html)


class TestArchOrphanCleanup(unittest.TestCase):
    def test_removed_node_page_deleted(self):
        import vicky.config as cfg
        with tmp_env(server) as tmp:
            _pub = cfg.PUBLIC_DIR
            cfg.PUBLIC_DIR = tmp / "public"
            try:
                from vicky import arch
                store.create_project("pi", "pi")
                store.save_arch_graph("pi", PI_GRAPH)
                arch.publish_arch_pages("pi")
                stale = cfg.PUBLIC_DIR / "arch" / "pi" / "aimeter.html"
                self.assertTrue(stale.exists())
                g2 = {"nodes": [n for n in PI_GRAPH["nodes"] if n["id"] != "aimeter"],
                      "edges": [e for e in PI_GRAPH["edges"] if e["to"] != "aimeter"],
                      "layout": {}}
                store.save_arch_graph("pi", g2)
                arch.publish_arch_pages("pi")
                self.assertFalse(stale.exists())
            finally:
                cfg.PUBLIC_DIR = _pub


class TestArchMarkdownSafe(unittest.TestCase):
    def test_script_and_html_escaped(self):
        from vicky import arch
        html = arch.render_md("<script>alert(1)</script> **x**")
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertIn("<strong>x</strong>", html)


class TestArchMarkdownExtras(unittest.TestCase):
    def _render(self, md):
        from vicky import arch
        return arch.render_md(md)

    def test_table(self):
        md = "| 条件 | 走向 |\n|---|---|\n| 代码任务 | 代码理解插件组 |"
        html = self._render(md)
        self.assertIn('<table class="data-table">', html)
        self.assertIn("<th>条件</th>", html)
        self.assertIn("<td>代码理解插件组</td>", html)

    def test_blockquote_callout(self):
        html = self._render("> 进程内沙箱而非独立进程：延迟与调试体验优先")
        self.assertIn('<div class="arch-callout">', html)
        self.assertIn("进程内沙箱", html)

    def test_heading_badge(self):
        html = self._render("## 1. 输入与输出")
        self.assertIn('<h3><span class="n">1</span>输入与输出</h3>', html)

    def test_no_badge_plain_heading(self):
        html = self._render("## 输入与输出")
        self.assertIn("<h3>输入与输出</h3>", html)


if __name__ == "__main__":
    unittest.main()


class TestArchModuleBodyHtml(unittest.TestCase):
    def test_module_get_returns_body_html(self):
        with tmp_env(server):
            store.create_project("pi", "pi")
            store.save_arch_graph("pi", {"nodes": [{"id": "r", "kind": "router",
                "layer": 1, "label": "路由"}], "edges": []})
            store.save_arch_module("pi", "r", "router",
                                   "| 条件 | 走向 |\n|---|---|\n| 代码 | 代码组 |")
            st, body, _ = http_get("/api/arch/pi/module/r")
            data = json.loads(body)
            self.assertEqual(st, 200)
            self.assertIn('<table class="data-table">', data["body_html"])


class TestArchLayout(unittest.TestCase):
    def _page(self, g):
        from vicky import arch
        return arch.render_arch_page("demo", g)

    def test_same_layer_same_top(self):
        g = {"nodes": [{"id": "a", "kind": "module", "layer": 1, "label": "A"},
                       {"id": "b", "kind": "module", "layer": 1, "label": "B"},
                       {"id": "c", "kind": "module", "layer": 2, "label": "C"}],
             "edges": []}
        html = self._page(g)
        import re
        tops = {m.group(1): int(m.group(2)) for m in
                re.finditer(r'data-id="([^"]+)"[^>]*style="left:\d+px;top:(\d+)px"', html)}
        self.assertEqual(tops["a"], tops["b"])   # 同层同 y
        self.assertGreater(tops["c"], tops["a"])  # 下一层更靠下

    def test_world_size_on_svg(self):
        g = {"nodes": [{"id": "a", "kind": "module", "layer": 1, "label": "A"}], "edges": []}
        html = self._page(g)
        self.assertIn('<svg id="edges" width="', html)
        self.assertIn('height="', html)
