import unittest
from tests.util import load_server

server = load_server()


class TestComponentHead(unittest.TestCase):
    def test_mermaid_detected(self):
        head, hits = server.component_head('<figure class="figure"><pre class="mermaid">flowchart LR\n A-->B</pre></figure>')
        self.assertEqual(hits, ["mermaid"])
        self.assertIn("mermaid-11.9.0.min.js", head)
        self.assertIn("init.v1.js", head)
        self.assertEqual(head.count("<script"), 2)

    def test_multi_class_detected(self):
        _, hits = server.component_head('<pre class="foo mermaid bar">x</pre>')
        self.assertEqual(hits, ["mermaid"])

    def test_prose_mention_not_detected(self):
        head, hits = server.component_head('<p>我们用 mermaid 画图</p><pre><code>mermaid</code></pre>')
        self.assertEqual(hits, [])
        self.assertEqual(head, "")

    def test_empty_content(self):
        head, hits = server.component_head("")
        self.assertEqual((head, hits), ("", []))


if __name__ == "__main__":
    unittest.main()
