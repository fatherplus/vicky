#!/usr/bin/env python3
"""html_to_md 转换器验收：封闭组件集 → 确定性 MD。P0 包化：import 更新。"""
from ai_report.html_to_md import html_to_md


def _wrap(body):
    return f'<main><section><div class="wrap">{body}</div></section></main>'


def test_headings_and_para():
    md = html_to_md(_wrap("<h2>标题</h2><p>正文内容</p>"))
    assert "## 标题" in md and "正文内容" in md


def test_blockquote():
    assert "> 结论句" in html_to_md(_wrap("<blockquote>结论句</blockquote>"))


def test_callout_warn_note():
    assert "⚠️" in html_to_md(_wrap('<div class="callout warn">风险</div>'))
    assert "📝" in html_to_md(_wrap('<div class="callout note">提醒</div>'))


def test_data_table():
    md = html_to_md(_wrap(
        '<table class="data-table"><tr><th>A</th><th>B</th></tr>'
        '<tr><td>1</td><td>2</td></tr></table>'))
    assert "| A | B |" in md and "| 1 | 2 |" in md and "|---|---|" in md


def test_cmp_verdict():
    md = html_to_md(_wrap(
        '<div class="cmp"><table class="cmp-table"><tr><th>x</th></tr><tr><td>y</td></tr></table>'
        '<div class="cmp-verdict">怎么选 · VERDICT：选 A</div></div>'))
    assert "VERDICT" in md and "选 A" in md


def test_mermaid_figure():
    md = html_to_md(_wrap(
        '<figure class="figure"><pre class="mermaid">flowchart LR\nA-->B</pre>'
        '<figcaption class="fig-cap">图 1 · 流程</figcaption>'
        '<p class="fig-note">说明</p></figure>'))
    assert "```mermaid" in md and "图 1 · 流程" in md and "_说明_" in md


def test_steps_and_ladder_compat():
    md = html_to_md(_wrap(
        '<div class="steps"><div class="step"><span class="step-num">壹</span>'
        '<div class="step-content">第一步</div></div></div>'))
    assert "1. **壹** 第一步" in md
    # 弃用 ladder-* 兼容
    md2 = html_to_md(_wrap(
        '<div class="ladder-list"><div class="ladder-rung"><span class="ladder-num">1</span>'
        '<div class="ladder-content">旧步骤</div></div></div>'))
    assert "旧步骤" in md2


def test_card():
    md = html_to_md(_wrap(
        '<div class="card"><div class="card-name">工具X</div>'
        '<div class="card-desc">描述</div></div>'))
    assert "**工具X**" in md and "描述" in md


def test_chrome_skipped():
    md = html_to_md('<div class="topbar">导航</div>' + _wrap("<p>正文</p>")
                    + '<script>var x=1;</script>')
    assert "导航" not in md and "var x" not in md and "正文" in md


def test_no_residual_tags():
    import re
    md = html_to_md(_wrap(
        "<h2>T</h2><p>x</p><table class='data-table'><tr><td>a</td></tr></table>"))
    assert not re.findall(r"</?(?:div|span|section|table|tr|td)\b", md)


def test_empty_subtitle_no_bare_marker():
    md = html_to_md('<main><section class="opener"><div class="wrap">'
                    '<h1>题</h1><p class="subtitle"></p></div></section></main>')
    assert "> \n" not in md and not md.strip().endswith(">")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ALL PASS")
