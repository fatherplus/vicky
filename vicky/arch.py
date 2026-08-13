"""架构导航器业务层：骨架校验 + 孤儿联动 + 模块读写包装。
依赖方向：web → arch → store（单向，不反向）。"""
from . import store


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
