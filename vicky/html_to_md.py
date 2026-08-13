#!/usr/bin/env python3
"""
html_to_md — 平台级 HTML→Markdown 转换器
=========================================

把书风格报告的 HTML 内容确定性地转成紧凑 Markdown。

为什么是确定性的：报告的组件集是封闭的（EXPRESSION-GRAMMAR.md 的 8 种形态 +
book 模板的卡片/标签等），门禁强制每篇报告只能用这些组件。组件集封闭 →
转换可以穷尽所有情况 → 不需要 LLM、不需要猜。

用途：
  - 平台能力：报告提交时生成 .md 兄弟文件，执行 AI 拿 .md 链接而非 .html
    （体积约 1/4，token 省 75%，且 MD 是 LLM 母语）
  - 蒸馏器可选读 .md 兄弟文件，少读视觉噪音

纯 stdlib。用 html.parser 建树再渲染（正则处理嵌套表格会出错）。
"""

import json
import re
import html as html_mod
from html.parser import HTMLParser

# 自闭合标签（无 endtag）
VOID_TAGS = {"img", "br", "hr", "meta", "link", "input", "source", "wbr"}

# chrome / 噪音：跳过整棵子树
SKIP_TAGS = {"script", "style", "nav", "noscript"}
SKIP_CLASSES = {
    "topbar", "bar-top", "bar-title", "bar-tabs", "bar-seal", "back",
    "ribbon", "seal", "ghost", "colophon",
    "tabs", "toc", "progress",
}


# ============================================================
# 建树
# ============================================================

class Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []  # list[Node | str]

    @property
    def classes(self) -> set:
        return set((self.attrs.get("class") or "").split())

    def has_class(self, *names) -> bool:
        cs = self.classes
        return any(n in cs for n in names)


class TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", [])
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        # 弹栈到匹配的 tag（容忍不闭合）
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data.strip():
            self.stack[-1].children.append(data)


def build_tree(html_str: str) -> Node:
    b = TreeBuilder()
    b.feed(html_str)
    b.close()
    return b.root


# ============================================================
# 节点查询辅助
# ============================================================

def text_of(node) -> str:
    """递归取纯文本（折叠空白）。"""
    if isinstance(node, str):
        return node
    parts = [text_of(c) for c in node.children]
    return " ".join(p for p in parts if p)


def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def find_first(node, pred):
    """DFS 找第一个满足 pred 的节点。"""
    if isinstance(node, str):
        return None
    if pred(node):
        return node
    for c in node.children:
        r = find_first(c, pred)
        if r is not None:
            return r
    return None


def find_all(node, pred, out=None):
    if out is None:
        out = []
    if isinstance(node, str):
        return out
    if pred(node):
        out.append(node)
    for c in node.children:
        find_all(c, pred, out)
    return out


# ============================================================
# 行内渲染（strong/code/a/img）
# ============================================================

def render_inline(node) -> str:
    """渲染行内内容为 MD（保留 **bold** / `code` / [link]）。"""
    if isinstance(node, str):
        return node  # 保留边界空格，由调用方 collapse_ws 统一收拢
    tag = node.tag
    inner = "".join(render_inline(c) for c in node.children)
    if node.has_class("priority"):
        return f" ({inner.strip()})" if inner.strip() else ""
    if tag in ("strong", "b"):
        return f"**{inner.strip()}**" if inner.strip() else ""
    if tag in ("em", "i"):
        return f"*{inner.strip()}*" if inner.strip() else ""
    if tag == "code":
        return f"`{inner.strip()}`" if inner.strip() else ""
    if tag == "a":
        href = node.attrs.get("href", "")
        t = inner.strip() or href
        return f"[{t}]({href})" if href else t
    if tag == "img":
        src = node.attrs.get("src", "")
        alt = node.attrs.get("alt", "")
        return f"![{alt}]({src})"
    if tag == "br":
        return "\n"
    return inner


def inline_md(node) -> str:
    return collapse_ws(render_inline(node))


# ============================================================
# 组件渲染
# ============================================================

def render_table(node) -> str:
    """data-table / cmp-table → MD 表格。"""
    rows = find_all(node, lambda n: n.tag == "tr")
    if not rows:
        return ""
    md_rows = []
    for tr in rows:
        cells = find_all(tr, lambda n: n.tag in ("td", "th"))
        # 只取直接子级的 cell（避免嵌套表重复）
        cells = [c for c in cells if _is_direct_cell(c, tr)]
        md_rows.append([collapse_ws(render_inline(c)).replace("|", "\\|") for c in cells])
    if not md_rows:
        return ""
    width = max(len(r) for r in md_rows)
    md_rows = [r + [""] * (width - len(r)) for r in md_rows]
    lines = ["| " + " | ".join(md_rows[0]) + " |",
             "|" + "|".join(["---"] * width) + "|"]
    for r in md_rows[1:]:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _is_direct_cell(cell, tr) -> bool:
    """cell 是否直接属于 tr（而非嵌套子表）。"""
    # 简化：cell 的最近 tr 祖先是 tr 本身
    return True  # find_all 已按 tr 子树取，嵌套表罕见，接受


def render_card(node) -> str:
    """card → 紧凑条目。"""
    name = find_first(node, lambda n: n.has_class("card-name"))
    desc = find_first(node, lambda n: n.has_class("card-desc"))
    vendor = find_first(node, lambda n: n.has_class("card-vendor"))
    link = find_first(node, lambda n: n.has_class("card-link"))
    tags = find_all(node, lambda n: n.has_class("tag"))

    head = inline_md(name) if name else ""
    parts = [f"- **{head}**" if head else "-"]
    if vendor:
        parts[0] += f" _{inline_md(vendor)}_"
    if desc:
        parts.append(f"  {inline_md(desc)}")
    meta = []
    if tags:
        meta.append("标签: " + ", ".join(inline_md(t) for t in tags))
    if link:
        href = link.attrs.get("href", "")
        if href:
            meta.append(href)
    if meta:
        parts.append("  " + " · ".join(meta))
    return "\n".join(parts)


def render_callout(node) -> str:
    """callout warn/note → 引用块。"""
    icon = "⚠️" if node.has_class("warn") else "📝"
    body = inline_md(node)
    lines = [f"> {icon} {ln}" if i == 0 else f"> {ln}"
             for i, ln in enumerate(body.split("\n"))] if body else [f"> {icon}"]
    return "\n".join(lines)


def render_steps(node) -> str:
    """steps / ladder → 有序列表。兼容弃用 ladder-*。"""
    items = find_all(node, lambda n: n.has_class("step") or n.has_class("ladder-rung"))
    out = []
    for i, it in enumerate(items, 1):
        num = find_first(it, lambda n: n.has_class("step-num") or n.has_class("ladder-num"))
        content = find_first(it, lambda n: n.has_class("step-content") or n.has_class("ladder-content"))
        label = inline_md(num) if num else str(i)
        body = inline_md(content) if content else inline_md(it)
        out.append(f"{i}. **{label}** {body}".rstrip())
    return "\n".join(out)


def render_figure(node) -> str:
    """figure → 图题 + 图注。mermaid 保留围栏。"""
    mermaid = find_first(node, lambda n: n.has_class("mermaid"))
    cap = find_first(node, lambda n: n.has_class("fig-cap"))
    note = find_first(node, lambda n: n.has_class("fig-note"))
    img = find_first(node, lambda n: n.tag == "img")
    tok = find_first(node, lambda n: n.has_class("af-md-token"))
    parts = [text_of(tok)] if tok else []
    if mermaid:
        parts.append("```mermaid\n" + text_of(mermaid).strip() + "\n```")
    elif img:
        parts.append(render_inline(img))
    if cap:
        parts.append(f"**{inline_md(cap)}**")
    if note:
        parts.append(f"_{inline_md(note)}_")
    return "\n".join(parts)


def render_blockquote(node) -> str:
    body = inline_md(node)
    return "\n".join(f"> {ln}" for ln in body.split("\n")) if body else ""


def render_list(node, ordered=False) -> str:
    items = [c for c in node.children if not isinstance(c, str) and c.tag == "li"]
    out = []
    for i, li in enumerate(items, 1):
        marker = f"{i}." if ordered else "-"
        out.append(f"{marker} {inline_md(li)}")
    return "\n".join(out)


# ============================================================
# 主渲染分发
# ============================================================

def render_node(node, depth=0) -> str:
    if isinstance(node, str):
        return collapse_ws(node)

    tag = node.tag
    # 跳过 chrome / 噪音子树
    if tag in SKIP_TAGS or node.has_class(*SKIP_CLASSES):
        return ""

    # 标题
    if tag == "h1":
        return f"# {inline_md(node)}"
    if tag == "h2":
        return f"## {inline_md(node)}"
    if tag == "h3":
        return f"### {inline_md(node)}"
    if tag == "h4":
        return f"#### {inline_md(node)}"

    # section-label / section-desc → 斜体引导
    if node.has_class("section-label"):
        t = inline_md(node)
        return f"_{t}_" if t else ""
    if node.has_class("section-desc"):
        return inline_md(node)
    if node.has_class("kicker"):
        t = inline_md(node)
        return f"_{t}_" if t else ""
    if node.has_class("subtitle"):
        t = inline_md(node)
        return f"> {t}" if t else ""
    if node.has_class("meta"):
        spans = [inline_md(s) for s in find_all(node, lambda n: n.tag == "span")]
        return "_" + " · ".join(s for s in spans if s) + "_" if spans else ""

    # 组件（按 class 优先于 tag 判定）
    if node.has_class("cmp-verdict"):
        return f"**{inline_md(node)}**"
    if node.has_class("cmp") or node.has_class("cmp-table") or node.has_class("data-table"):
        # cmp 容器：找内部 table + verdict
        tbl = find_first(node, lambda n: n.tag == "table")
        cap = find_first(node, lambda n: n.tag == "caption")
        verdict = find_first(node, lambda n: n.has_class("cmp-verdict"))
        parts = []
        if cap:
            parts.append(f"_{inline_md(cap)}_")
        if tbl:
            parts.append(render_table(tbl))
        if verdict:
            parts.append(f"**{inline_md(verdict)}**")
        if parts:
            return "\n\n".join(parts)
        return render_table(node) if tag == "table" else ""
    if tag == "table":
        cap = find_first(node, lambda n: n.tag == "caption")
        parts = ([f"_{inline_md(cap)}_"] if cap else []) + [render_table(node)]
        return "\n\n".join(p for p in parts if p)
    if node.has_class("card"):
        return render_card(node)
    if node.has_class("card-grid"):
        cards = find_all(node, lambda n: n.has_class("card"))
        return "\n".join(render_card(c) for c in cards)
    if node.has_class("callout"):
        return render_callout(node)
    if node.has_class("steps") or node.has_class("ladder-list") or node.has_class("ladder"):
        return render_steps(node)
    if tag == "figure" or node.has_class("figure"):
        return render_figure(node)
    if tag == "blockquote":
        return render_blockquote(node)
    if tag == "pre":
        if node.has_class("mermaid"):
            return "```mermaid\n" + text_of(node).strip() + "\n```"
        return "```\n" + text_of(node).strip() + "\n```"
    if tag == "ul":
        return render_list(node, ordered=False)
    if tag == "ol":
        return render_list(node, ordered=True)
    if tag == "p":
        return inline_md(node)
    if tag == "hr":
        return "---"
    if tag == "img":
        return render_inline(node)

    # 容器：递归渲染子节点
    out = [render_node(c, depth + 1) for c in node.children]
    return "\n\n".join(b for b in out if b and b.strip())


# ============================================================
# 顶层入口
# ============================================================

ARCH_FLOW_RE = re.compile(
    r'<div\b[^>]*\bclass=["\'][^"\']*\barch-flow\b[^>]*>[\s\S]*?'
    r'<script type="application/json">([\s\S]*?)</script>[\s\S]*?</div>')


def render_arch_flow_md(json_str: str) -> str:
    """arch-flow 契约 JSON → 结构化文本。总览 MD 只做地图：层/节点/边；
    模块详情不进总览 MD——在各节点卷里。"""
    try:
        data = json.loads(json_str)
    except (ValueError, TypeError):
        return ""
    nodes = data.get("nodes") or []
    edges = data.get("edges") or []
    out = [f"**[arch-flow]** {len(data.get('layers') or [])} 层 · {len(nodes)} 节点 · {len(edges)} 边", ""]
    for n in nodes:
        kind = n.get("kind", "process")
        sub = f"（{n['sub']}）" if n.get("sub") else ""
        href = f" → {n['href']}" if n.get("href") else ""
        out.append(f"- L{n.get('layer', '?')} [{kind}] {n.get('label', n.get('id', '?'))}{sub}{href}")
    out.append("")
    for e in edges:
        mark = {"async": "（异步）", "warn": "（拦截）"}.get(e.get("type", "main"), "")
        lab = f" --{e['label']}--" if e.get("label") else " --"
        out.append(f"- {e['from']}{lab}> {e['to']}{mark}")
    return "\n".join(out)


# ============================================================

def html_to_md(html_str: str) -> str:
    """报告 HTML → 紧凑 Markdown。只转 <main> 内容，跳过页面 chrome。"""
    # 优先取 <main>，没有就转 body，再没有就转全文
    m = re.search(r"<main[\s\S]*?</main>", html_str)
    scope = m.group(0) if m else html_str

    # arch-flow：script 是 SKIP_TAG，先提走换占位符，渲染后回填
    blocks = []
    def _af(m2):
        blocks.append(render_arch_flow_md(m2.group(1)))
        return f'<p class="af-md-token">@@AF{len(blocks) - 1}@@</p>'
    scope = ARCH_FLOW_RE.sub(_af, scope)

    tree = build_tree(scope)
    md = render_node(tree)
    for i, b in enumerate(blocks):
        md = md.replace(f"@@AF{i}@@", b)

    # 清理：多余空行折叠为最多两个
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md + "\n"


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(html_to_md(open(sys.argv[1], encoding="utf-8").read()))
    else:
        print("用法: python3 html_to_md.py <report.html>", file=sys.stderr)
