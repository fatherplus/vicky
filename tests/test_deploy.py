import unittest
from tests.util import load_server, tmp_env


class TestCanonicalDeploy(unittest.TestCase):
    def test_deploy_steps_no_flat_canonical_url(self):
        server = load_server()
        with tmp_env(server) as (tmp, run):
            result = server.create_report("T", "deploy-check", "测试",
                                          '<section><div class="wrap"><p>x</p></div></section>')
            # 本地文件落在 reports/ 目录（tmp 目录在 with 退出后清理，须在此断言）
            self.assertTrue((tmp / "reports" / result["file"]).exists())
        cps = [c.args[0] for c in run.call_args_list if c.args and c.args[0] == ["sudo", "cp"] or
               (c.args and len(c.args[0]) > 2 and c.args[0][:2] == ["sudo", "cp"])]
        cp_targets = [c.args[0][-1] for c in run.call_args_list
                      if c.args and c.args[0][:2] == ["sudo", "cp"]]
        nginx = str(tmp / "nginx")
        # 不再有平铺复制（目标直接落在 nginx 根 + 文件名的 cp）
        self.assertFalse(any(t == f"{nginx}/{result['file']}" for t in cp_targets),
                         "仍存在平铺复制")
        # 报告直传 reports/ 真实文件
        self.assertIn(f"{nginx}/reports/{result['file']}", cp_targets)
        # mkdir 含 assets
        mkdirs = [c.args[0] for c in run.call_args_list if c.args and c.args[0][:2] == ["sudo", "mkdir"]]
        self.assertTrue(any("assets" in " ".join(m) for m in mkdirs))
        # 响应 URL 为 canonical
        self.assertIn("/research/reports/", result["url"])


if __name__ == "__main__":
    unittest.main()
