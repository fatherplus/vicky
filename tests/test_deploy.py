import unittest
from tests.util import load_server, tmp_env


class TestReportOutput(unittest.TestCase):
    """create_report 只写本地文件，不再 sudo cp 到 Nginx 目录（Nginx alias 直读 public/）"""

    def test_report_file_and_relative_url(self):
        server = load_server()
        with tmp_env(server) as tmp:
            result = server.create_report("T", "deploy-check", "测试",
                                          '<section><div class="wrap"><p>x</p></div></section>')
            self.assertTrue((tmp / "reports" / result["file"]).exists())
            # 无 base_url → 相对路径
            self.assertEqual(result["url"], f"/research/reports/{result['file']}")
            self.assertNotIn("deployed", result)

    def test_url_uses_base_url(self):
        server = load_server()
        with tmp_env(server) as tmp:
            result = server.create_report("T", "url-check", "测试",
                                          '<section><div class="wrap"><p>x</p></div></section>',
                                          base_url="http://example.com:9092")
            self.assertTrue(result["url"].startswith("http://example.com:9092/research/reports/"))


if __name__ == "__main__":
    unittest.main()
