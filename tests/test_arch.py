import json
import unittest
from tests.util import load_server, tmp_env, http_get, http_post
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


if __name__ == "__main__":
    unittest.main()
