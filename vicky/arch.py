"""架构导航器业务层：骨架校验 + 孤儿联动 + 模块读写包装。
依赖方向：web → arch → store（单向，不反向）。"""
import html as _html
import json as _json_mod
from . import store
from . import ui


def put_graph(project: str, graph: dict) -> tuple[bool, str | None]:
    """整体覆盖骨架。project 必须已注册（先建项目）。
    覆盖后比对骨架节点集，骨架里消失的模块 → 标记孤儿。返回 (ok, err)。"""
    if not store.get_project(project):
        return False, f"项目 '{project}' 未注册——先建项目再建架构"
    if not isinstance(graph, dict) or "nodes" not in graph:
        return False, "graph 必须是含 nodes 的对象"
    node_ids = [n.get("id") for n in graph.get("nodes", []) if n.get("id")]
    conn = store.get_db()
    try:
        store.save_arch_graph(project, graph, conn)
        store.mark_arch_orphans(project, node_ids, conn)
        conn.commit()
    finally:
        conn.close()
    publish_arch_page(project)
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
    return {"ok": True, "warning": warning}


def get_module(project: str, node_id: str) -> dict | None:
    return store.get_arch_module(project, node_id)


def search(project: str, q: str) -> list[dict]:
    return store.search_arch_modules(project, q)


def render_arch_page(project: str, graph: dict) -> str:
    """骨架 JSON → arch.html。分层渲染节点 + 路由条件出边（最简版本，后期优化）。"""
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    layers = {}
    for n in nodes:
        layers.setdefault(n.get("layer", 1), []).append(n)
    parts = []
    for layer in sorted(layers):
        parts.append(f'<div class="arch-layer" data-layer="{layer}">')
        for n in layers[layer]:
            cls = "arch-node router" if n.get("kind") == "router" else "arch-node"
            nid = _html.escape(str(n.get("id", "")), quote=True)
            label = _html.escape(str(n.get("label", n.get("id", ""))))
            summary = _html.escape(str(n.get("summary", "")))
            conds = [_html.escape(e.get("condition", "")) for e in edges
                     if e.get("from") == n.get("id") and e.get("condition")]
            cond_html = "".join(f'<span class="arch-cond">{c}</span>' for c in conds)
            parts.append(f'<div class="{cls}" data-id="{nid}"><b>{label}</b>'
                         f'<small>{summary}</small>{cond_html}</div>')
        parts.append("</div>")
    # 模块正文注入前端（最简：GET /api/arch 后前端也可动态拉，这里静态嵌 active 模块）
    mods = {}
    conn = store.get_db()
    try:
        rows = conn.execute(
            "SELECT node_id, body_md FROM arch_modules WHERE project=? AND status='active'",
            (project,)).fetchall()
        mods = {r["node_id"]: r["body_md"] for r in rows}
    finally:
        conn.close()
    data_js = "window.ARCH_MODULES=" + _json_mod.dumps(mods, ensure_ascii=False) + ";"
    tpl = ui.load_view("arch.html")
    return (tpl.replace("__PROJECT_NAME__", _html.escape(project))
               .replace("__TREE__", "\n".join(parts))
               .replace("__DATA_JSON__", data_js))


def publish_arch_page(project: str) -> bool:
    """把某项目架构树写到 public/arch/{project}.html。无骨架 → 不生成，返回 False。"""
    from . import config
    g = store.get_arch_graph(project)
    if not g:
        return False
    out_dir = config.PUBLIC_DIR / "arch"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{ui.project_slug(project)}.html").write_text(
        render_arch_page(project, g), encoding="utf-8")
    return True
