"""README 种子自举测试：空库部署创建序，且幂等。"""
import unittest

from tests.util import load_server, tmp_env
from vicky import config, seed, store

server = load_server()


class TestSeedBootstrap(unittest.TestCase):
    def test_bootstrap_creates_readme_on_empty_db(self):
        with tmp_env(server):
            conn = store.get_db()
            try:
                before = conn.execute(
                    "SELECT COUNT(*) FROM reports WHERE slug=?",
                    (config.DESIGN_DOC_SLUG,)).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(before, 0)

            self.assertTrue(seed.bootstrap())  # 空库 → 创建

            conn = store.get_db()
            try:
                after = conn.execute(
                    "SELECT COUNT(*) FROM reports WHERE slug=?",
                    (config.DESIGN_DOC_SLUG,)).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(after, 1)

    def test_bootstrap_idempotent(self):
        with tmp_env(server):
            seed.bootstrap()
            self.assertFalse(seed.bootstrap())  # 已存在 → 跳过


if __name__ == "__main__":
    unittest.main()
