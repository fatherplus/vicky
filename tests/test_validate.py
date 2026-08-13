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


class TestValidateContent(unittest.TestCase):
    def v(self, content, title=""):
        return server.validate_content(content, title)

    def test_bare_table_error(self):
        errors, _ = self.v("<table><tr><td>1</td></tr></table>")
        self.assertTrue(any("裸 <table>" in e for e in errors))

    def test_data_table_passes(self):
        errors, _ = self.v('<table class="data-table"><tr><td>1</td></tr></table>')
        self.assertEqual(errors, [])

    def test_cmp_without_verdict_error(self):
        errors, _ = self.v('<table class="cmp-table"></table>')
        self.assertTrue(any("cmp-verdict" in e for e in errors))

    def test_cmp_with_verdict_passes(self):
        errors, _ = self.v('<table class="cmp-table"></table><div class="cmp-verdict">x</div>')
        self.assertEqual(errors, [])

    def test_deprecated_class_error(self):
        errors, _ = self.v('<div class="quote-block">x</div>')
        self.assertTrue(any("quote-block" in e for e in errors))

    def test_figure_missing_cap_and_note_warnings(self):
        errors, warnings = self.v('<figure class="figure"><img src="x"></figure>')
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 2)
        self.assertTrue(any("图题" in w for w in warnings))
        self.assertTrue(any("图注" in w for w in warnings))

    def test_figure_complete_no_warning(self):
        _, warnings = self.v('<figure class="figure"><img src="x">'
                             '<figcaption class="fig-cap">图 1 · x</figcaption>'
                             '<p class="fig-note">y</p></figure>')
        self.assertEqual(warnings, [])

    def test_ai_words_warning(self):
        _, warnings = self.v("<p>形成闭环，全面赋能</p>")
        self.assertTrue(any("AI 腔词" in w and "闭环" in w for w in warnings))

    def test_emoji_warning(self):
        _, warnings = self.v("<p>hello</p>", title="研究 🚀 报告")
        self.assertTrue(any("emoji" in w for w in warnings))

    def test_emoji_whitelist_symbols_not_flagged(self):
        """平台规范符号 ✓ ✗ ⚠（guide 对比表硬规则）不算 emoji。"""
        _, warnings = self.v("<p>✓ 支持 / ✗ 需重建 / ⚠ 注意</p>")
        self.assertFalse(any("emoji" in w for w in warnings))

    def test_closed_loop_technical_term_not_flagged(self):
        """「生产-消费闭环」是正当技术术语，不算 AI 腔。"""
        _, warnings = self.v("<p>记忆系统生产-消费闭环</p>")
        self.assertFalse(any("闭环" in w for w in warnings))

    def test_closed_loop_ai_slang_still_flagged(self):
        """「形成闭环」仍是 AI 腔。"""
        _, warnings = self.v("<p>形成闭环</p>")
        self.assertTrue(any("闭环" in w for w in warnings))

    def test_mermaid_no_figure_warning(self):
        _, warnings = self.v('<pre class="mermaid">flowchart LR</pre>')
        self.assertTrue(any("装裱" in w for w in warnings))

    def test_clean_content(self):
        errors, warnings = self.v("<p>朴素具体的正文。</p>", title="HNSW 研究")
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()


def test_normalize_wrap():
    from vicky.l1_publish import normalize_wrap
    out = normalize_wrap('<section class="reveal"><h2>x</h2><p>y</p></section>')
    assert '<div class="wrap"><h2>x</h2>' in out and out.endswith("</div></section>")
    # 已有 wrap 的不重复包
    out2 = normalize_wrap('<section><div class="wrap"><p>z</p></div></section>')
    assert out2 == '<section><div class="wrap"><p>z</p></div></section>'
