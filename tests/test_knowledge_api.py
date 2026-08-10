"""GET /api/knowledge 分类字段（分类规格 2026-08-10 §3）：
列表条目含 category / category_label / tags（读 frontmatter，非法值兜底 ai）；
单页查询不受影响。"""
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from tests.util import load_server, tmp_env

server = load_server()

REPO = Path(__file__).resolve().parent.parent


def _get(server, path):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.2)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as r:
            out = (r.status, r.read())
    except urllib.error.HTTPError as e:
        out = (e.code, e.read())
    srv.shutdown()
    return out


def _write_topic(tmp: Path, topic: str, category: str = "", tags=None):
    d = tmp / "knowledge" / "tech" / topic
    d.mkdir(parents=True, exist_ok=True)
    fm = ["---", f"id: {topic}", f"title: 主题 {topic}", "domain: tech", "status: stable",
          "verified: unverified", "sources_count: 1", "stale_after: 2026-12-01",
          "confidence: medium"]
    if category:
        fm.append(f"category: {category}")
    if tags:
        fm.append("tags:")
        fm += [f"  - {t}" for t in tags]
    fm.append("---")
    (d / "overview.md").write_text("\n".join(fm) + "\n## 概述\n\n一句话结论。\n", encoding="utf-8")


class TestKnowledgeApi(unittest.TestCase):
    def _tmp_repo(self):
        """tmp_env + REPO_DIR 指向 tmp，使 web 的 knowledge 扫描落在隔离目录。"""
        from ai_report import config as cfg
        from ai_report import l2_distill
        import contextlib
        cm = tmp_env(server)
        tmp = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        _repo = cfg.REPO_DIR
        cfg.REPO_DIR = tmp
        self.addCleanup(setattr, cfg, "REPO_DIR", _repo)
        # l2_distill 的 KNOWLEDGE_DIR 由 REPO_DIR 派生，重绑避免读到真实库
        _kd = l2_distill.KNOWLEDGE_DIR
        l2_distill.KNOWLEDGE_DIR = tmp / "knowledge"
        self.addCleanup(setattr, l2_distill, "KNOWLEDGE_DIR", _kd)
        return tmp

    def test_list_entries_have_category_tags(self):
        tmp = self._tmp_repo()
        _write_topic(tmp, "topic-a", category="ops", tags=["成本", "用量"])
        _write_topic(tmp, "topic-b")  # 无 frontmatter category → 兜底 ai
        _write_topic(tmp, "topic-c", category="bogus", tags=["x"])  # 非法枚举 → 兜底 ai

        status, body = _get(server, "/api/knowledge")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        by_topic = {p["topic"]: p for p in data["pages"]}
        self.assertEqual(set(by_topic), {"topic-a", "topic-b", "topic-c"})

        a = by_topic["topic-a"]
        self.assertEqual(a["category"], "ops")
        self.assertEqual(a["category_label"], "成本与治理专栏")
        self.assertEqual(a["tags"], ["成本", "用量"])
        self.assertIn("content", a)

        b = by_topic["topic-b"]
        self.assertEqual(b["category"], "ai")
        self.assertEqual(b["category_label"], "AI 专栏")
        self.assertEqual(b["tags"], [])

        c = by_topic["topic-c"]
        self.assertEqual(c["category"], "ai")  # 非法枚举兜底 ai

    def test_single_page_unchanged(self):
        tmp = self._tmp_repo()
        _write_topic(tmp, "topic-a", category="ops", tags=["成本"])

        status, body = _get(server, "/api/knowledge?domain=tech&topic=topic-a")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["domain"], "tech")
        self.assertEqual(data["topic"], "topic-a")
        self.assertIn("content", data)
        self.assertIn("feedback_count", data)


if __name__ == "__main__":
    unittest.main()
