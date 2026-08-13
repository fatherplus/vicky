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


if __name__ == "__main__":
    unittest.main()
