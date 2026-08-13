"""架构导航器业务层：骨架校验 + 孤儿联动 + 模块读写包装。
依赖方向：web → arch → store（单向，不反向）。"""
import html as _html
import json as _json_mod
import re as _re
from . import store
from . import ui

# 节点类型 → 中文标签（router 显示「路由」，见验收测试 TestArchRouter）
KIND_LABEL = {"entry": "入口", "process": "处理", "storage": "存储",
              "gateway": "网关", "router": "路由", "plugin": "插件", "module": "模块"}


def put_graph(project: str, graph: dict) -> tuple[bool, str | None]:
    """整体覆盖骨架。project 必须已注册（先建项目）。
    覆盖后比对骨架节点集，骨架里消失的模块 → 标记孤儿。返回 (ok, err)。"""
    if not store.get_project(project):
        return False, f"项目 '{project}' 未注册——先建项目再建架构"
    if not isinstance(graph, dict) or "nodes" not in graph:
        return False, "graph 必须是含 nodes 的对象"
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not all(isinstance(n, dict) for n in nodes):
        return False, "graph.nodes 必须是节点对象数组"
    node_ids = [n.get("id") for n in nodes if n.get("id")]
    conn = store.get_db()
    try:
        store.save_arch_graph(project, graph, conn)
        store.mark_arch_orphans(project, node_ids, conn)
        conn.commit()
    finally:
        conn.close()
    publish_arch_pages(project)
    return True, None


def get_graph(project: str) -> dict | None:
    return store.get_arch_graph(project)


def put_module(project: str, node_id: str, kind: str, body_md: str) -> dict:
    """upsert 单模块。返回 {ok, warning?}。骨架里无此 node_id → warning（不拒收）。"""
    store.save_arch_module(project, node_id, kind or "module", body_md or "")
    warning = None
    g = store.get_arch_graph(project)
    if g and node_id not in {n.get("id") for n in g.get("nodes", [])}:
        warning = f"节点 '{node_id}' 不在骨架里——先补骨架或该模块暂为悬挂内容"
    publish_arch_pages(project)  # 模块正文变了 → 重生成导航页与子页
    return {"ok": True, "warning": warning}


def get_module(project: str, node_id: str) -> dict | None:
    return store.get_arch_module(project, node_id)


def search(project: str, q: str) -> list[dict]:
    """FTS 搜模块，结果补 node label（规格要求 {node_id, label, snippet}）。
    骨架里没有该 node 时 label=node_id（不改 store 层，避免 schema 变更）。"""
    g = store.get_arch_graph(project)
    labels = {n.get("id"): (n.get("label") or n.get("id"))
              for n in (g or {}).get("nodes", []) if isinstance(n, dict)}
    items = store.search_arch_modules(project, q)
    for it in items:
        it["label"] = labels.get(it["node_id"], it["node_id"])
    return items


def _inline(s: str) -> str:
    """行内 Markdown：**bold**、`code`（输入已整体转义）。"""
    s = _re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = _re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def render_md(md: str) -> str:
    """极简 Markdown → HTML（服务端，供模块子页）。先整体转义再应用语法：
    #~#### 标题、``` 代码块、-/数字 列表、**bold**、`code`、段落。
    ponytail：不引第三方库，够架构正文用；转义在前，杜绝 <script> 注入。"""
    lines = _html.escape(md or "").split("\n")
    out, in_code, code_buf, list_buf = [], False, [], []

    def flush_list():
        if list_buf:
            out.append("<ul>" + "".join(f"<li>{x}</li>" for x in list_buf) + "</ul>")
            list_buf.clear()

    for ln in lines:
        if ln.startswith("```"):
            if in_code:
                out.append("<pre><code>" + "\n".join(code_buf) + "</code></pre>")
                code_buf, in_code = [], False
            else:
                flush_list()
                in_code = True
            continue
        if in_code:
            code_buf.append(ln)
            continue
        m = _re.match(r"^(#{1,4})\s+(.*)", ln)
        if m:
            flush_list()
            lvl = len(m.group(1)) + 1
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            continue
        if _re.match(r"^\s*[-*]\s+", ln):
            list_buf.append(_inline(_re.sub(r"^\s*[-*]\s+", "", ln)))
            continue
        m = _re.match(r"^\s*\d+[.)]\s+(.*)", ln)
        if m:
            list_buf.append(_inline(m.group(1)))
            continue
        flush_list()
        if not ln.strip():
            continue
        out.append(f"<p>{_inline(ln)}</p>")
    flush_list()
    if in_code and code_buf:
        out.append("<pre><code>" + "\n".join(code_buf) + "</code></pre>")
    return "\n".join(out)


def render_arch_page(project: str, graph: dict) -> str:
    """骨架 JSON → arch.html：分层节点 + 服务端 SVG 边骨架。
    每边出一个 <path class=\"arch-edge\" data-from data-to>（含箭头 marker），
    condition 出 <text class=\"arch-edge-cond\">；节点 DOM 落位后由前端补连线坐标。
    模块正文不进导航页（渐进式：抽屉按需拉 /api/…，或走子页深读）。"""
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    layers = {}
    for n in nodes:
        layers.setdefault(n.get("layer", 1), []).append(n)
    parts = []
    for layer in sorted(layers):
        parts.append(f'<div class="arch-layer" data-layer="{layer}">')
        for n in layers[layer]:
            kind = str(n.get("kind", "module"))
            cls = "arch-node router" if kind == "router" else "arch-node"
            nid = _html.escape(str(n.get("id", "")), quote=True)
            label = _html.escape(str(n.get("label", n.get("id", ""))), quote=True)
            summary = _html.escape(str(n.get("summary", "")))
            klabel = _html.escape(KIND_LABEL.get(kind, kind))
            parts.append(f'<div class="{cls}" data-id="{nid}" data-label="{label}" '
                         f'data-kind="{_html.escape(kind, quote=True)}">'
                         f'<span class="arch-node-kind">{klabel}</span>'
                         f'<b>{label}</b><small>{summary}</small></div>')
        parts.append("</div>")
    # SVG 边骨架：server 出 <path>/<text>，前端按节点实际位置补 d/x/y
    edge_parts = [
        '<svg id="edges" aria-hidden="true">',
        '<defs><marker id="arch-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" '
        'orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#A63A2E"/></marker></defs>']
    for e in edges:
        f = _html.escape(str(e.get("from", "")), quote=True)
        t = _html.escape(str(e.get("to", "")), quote=True)
        edge_parts.append(f'<path class="arch-edge" data-from="{f}" data-to="{t}" '
                          f'marker-end="url(#arch-arrow)" d=""/>')
        if e.get("condition"):
            edge_parts.append(f'<text class="arch-edge-cond" data-from="{f}" data-to="{t}">'
                              f'{_html.escape(e["condition"])}</text>')
    edge_parts.append("</svg>")
    tpl = ui.load_view("arch.html")
    return (tpl.replace("__PROJECT_NAME__", _html.escape(project))
               .replace("__EDGES__", "\n".join(edge_parts))
               .replace("__TREE__", "\n".join(parts)))


def render_arch_module_page(project: str, node_id: str, label: str, kind: str,
                            body_md: str) -> str:
    """模块子页：服务端渲染正文（render_md），可链接、可深读的子文章。"""
    tpl = ui.load_view("arch-module.html")
    body = render_md(body_md) if (body_md or "").strip() else \
        '<p class="empty">模块正文待补。agent 可 PUT /api/arch/{p}/module/{n} 写入。</p>'
    return (tpl.replace("__PROJECT_NAME__", _html.escape(project))
               .replace("__MODULE_LABEL__", _html.escape(str(label)))
               .replace("__KIND__", _html.escape(KIND_LABEL.get(kind, kind)))
               .replace("__BODY__", body))


def publish_arch_pages(project: str) -> bool:
    """写 public/arch/{slug}.html（导航）+ {slug}/{node_id}.html（每节点一页，服务端渲染）。
    清理骨架里已不存在节点的孤儿子页。无骨架 → 不生成，返回 False。"""
    from . import config
    g = store.get_arch_graph(project)
    if not g:
        return False
    slug = ui.project_slug(project)
    out_dir = config.PUBLIC_DIR / "arch"
    mod_dir = out_dir / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{slug}.html").write_text(render_arch_page(project, g), encoding="utf-8")
    # 当前 active 模块正文（节点无正文 → 子页给占位）
    conn = store.get_db()
    try:
        rows = conn.execute(
            "SELECT node_id, body_md FROM arch_modules WHERE project=? AND status='active'",
            (project,)).fetchall()
        body_by = {r["node_id"]: r["body_md"] for r in rows}
    finally:
        conn.close()
    mod_dir.mkdir(parents=True, exist_ok=True)
    keep = set()
    for n in g.get("nodes", []):
        nid = n.get("id")
        if not nid:
            continue
        keep.add(f"{nid}.html")
        (mod_dir / f"{nid}.html").write_text(
            render_arch_module_page(project, nid, n.get("label", nid),
                                    str(n.get("kind", "module")), body_by.get(nid, "")),
            encoding="utf-8")
    # 孤儿清理：骨架里已没有的节点，其子页删除
    for f in mod_dir.glob("*.html"):
        if f.name not in keep:
            f.unlink()
    return True
