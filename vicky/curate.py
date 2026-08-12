"""
审核治理（重构蓝图 2026-08-12 §04）——L3 层级，依赖方向 web → curate → l2 → l1 → l0 → store。
SQL 一律走 store 层，本模块只编排。

两层对象 × 两级操作：
- 源文章（L1 报告）：软下架（hidden，可恢复，L0 快照保留）/ 硬删除（级联物理删，不可逆）
- 知识条目（L2 蒸馏产物）：状态精修（active/hidden，单条踢掉或恢复）
- 审核视图：knowledge_audit 供人看「这篇报告蒸出了哪些条目」

约定：
- 删除/下架的确认逻辑在 API/CLI 层做，本模块不弹确认
- sources 匹配双口径：规则蒸馏路径记的是报告文件名（如 2026-08-12-x.html），
  编译路径记的是裸 slug——两条都要捞到
"""

import json
import shutil

from . import config
from . import store
from . import l1_publish  # 触发索引/项目页重渲染（l3 → l1 合法，非反向）

# 知识条目状态枚举
ITEM_STATUSES = ("active", "hidden")


# ============================================================
# 软下架 / 恢复
# ============================================================
def _items_linked_to(conn, slug: str, file: str = "") -> list:
    """sources 含 slug 或报告文件名（规则路径记文件名、编译路径记 slug）的知识条目，去重。"""
    seen, out = set(), []
    candidates = store.get_knowledge_items_by_source(slug, conn)
    if file:
        candidates += store.get_knowledge_items_by_source(file, conn)
    for it in candidates:
        if it["id"] not in seen:
            seen.add(it["id"])
            out.append(it)
    return out


def hide_report(slug: str, hidden: bool = True) -> dict:
    """软下架/恢复报告（可逆，L0 快照与 DB 行保留）。
    - 设 reports.hidden 标志
    - 同步：sources 含该 slug（或报告文件名）的知识条目一起 hidden/active（级联软下架）
    - 触发索引/项目页重渲染（l1_publish.rebuild_index：索引 + 首页 + 卡片墙 + 丛书）
    返回 {"ok", "slug", "hidden", "items_affected"}；slug 不存在返回 {"ok": False, "error"}。"""
    hidden = bool(hidden)
    store.create_knowledge_items_table()  # 幂等：新鲜库无知识条目表时先建（无条目 = 0 影响）
    conn = store.get_db()
    try:
        rep = store.get_report_by_slug(conn, slug)
        if not rep:
            return {"ok": False, "error": f"slug '{slug}' 不在 reports 表中"}
        items = _items_linked_to(conn, slug, rep.get("file") or "")
        store.set_report_hidden(slug, hidden, conn)
        for it in items:
            st = "hidden" if hidden else "active"
            store.set_knowledge_item_status(it["id"], st, conn)
            store.sync_item_fts(it["id"], st, conn)
        conn.commit()
    finally:
        conn.close()
    l1_publish.rebuild_index()
    return {"ok": True, "slug": slug, "hidden": hidden, "items_affected": len(items)}


# ============================================================
# 硬删除（级联物理删，不可逆——确认在 API/CLI 层）
# ============================================================
def _manifest(slug: str, conn) -> dict:
    """计算将被硬删除的完整清单（不执行删除）：
    报告行 + 产物文件（html/md）+ L0 目录 + img 目录 + submissions 行数 + 知识条目 id。"""
    rep = store.get_report_by_slug(conn, slug)
    items = _items_linked_to(conn, slug, (rep or {}).get("file") or "")
    html = md = None
    if rep:
        html = config.REPORTS_DIR / rep["file"]
        md = config.REPORTS_DIR / (rep["file"][:-5] + ".md") if rep["file"].endswith(".html") else None
    return {
        "slug": slug,
        "report": rep,
        "html": html,
        "md": md,
        "img_dir": config.IMG_DIR / slug,
        "l0_dir": config.DATA_DIR / "l0" / slug,
        "submissions": store.count_submissions(conn, slug),
        "knowledge_items": [it["id"] for it in items],
    }


def preview_delete(slug: str) -> dict:
    """硬删除清单（展示/确认用，不执行任何删除）。"""
    store.create_knowledge_items_table()
    conn = store.get_db()
    try:
        return _manifest(slug, conn)
    finally:
        conn.close()


def hard_delete_report(slug: str) -> dict:
    """级联物理删除（不可逆）。
    删除：public/reports/ 下 html+md、public/assets/img/{slug}/（若有）、
    data/l0/{slug}/ 整个目录、reports 行、submissions 行（先删 reports 行，FK 顺序）、
    sources 含该 slug 的知识条目（knowledge_items + FTS 同步删）。
    然后重渲染索引/项目页。返回删除清单；slug 不存在返回 {"ok": False, "error"}。"""
    store.create_knowledge_items_table()
    conn = store.get_db()
    try:
        m = _manifest(slug, conn)
        if not (m["report"] or m["submissions"] or m["knowledge_items"]):
            return {"ok": False, "error": f"slug '{slug}' 不存在，无可删除"}
        deleted = {
            "report_files": [],
            "img_dir": None,
            "l0_dir": None,
            "submissions": m["submissions"],
            "knowledge_items": m["knowledge_items"],
        }
        # 1. L1 产物文件（html + md 孪生）
        for p in (m["html"], m["md"]):
            if p and p.exists():
                p.unlink()
                deleted["report_files"].append(p.name)
        # 2. 图片目录 public/assets/img/{slug}/
        if m["img_dir"].exists():
            shutil.rmtree(m["img_dir"])
            deleted["img_dir"] = str(m["img_dir"])
        # 3. L0 不可变快照目录
        if m["l0_dir"].exists():
            shutil.rmtree(m["l0_dir"])
            deleted["l0_dir"] = str(m["l0_dir"])
        # 4. DB 行：先 reports 后 submissions（FK：reports.current_rev → submissions.id）
        if m["report"]:
            store.delete_report_row(slug, conn)
        if m["submissions"]:
            store.delete_submissions_for_slug(slug, conn)
        # 5. 级联删知识条目（含 FTS 索引同步）
        for iid in m["knowledge_items"]:
            store.delete_knowledge_item(iid, conn)
        conn.commit()
    finally:
        conn.close()
    l1_publish.rebuild_index()
    return {"ok": True, "slug": slug, "deleted": deleted}


# ============================================================
# 知识条目状态精修 + 审核视图
# ============================================================
def set_item_status(item_id: str, status: str) -> dict:
    """知识条目状态切换（active/hidden），同步 FTS 可见性（查询只返回 active）。
    返回 {"ok", "id", "topic", "status"}；非法 status / id 不存在返回 {"ok": False, "error"}。"""
    if status not in ITEM_STATUSES:
        return {"ok": False, "error": f"status 必须是 {'/'.join(ITEM_STATUSES)}"}
    store.create_knowledge_items_table()
    conn = store.get_db()
    try:
        it = store.get_knowledge_item(conn, item_id)
        if not it:
            return {"ok": False, "error": f"知识条目 {item_id} 不存在"}
        store.set_knowledge_item_status(item_id, status, conn)
        store.sync_item_fts(item_id, status, conn)
        conn.commit()
        topic = it["topic"]
    finally:
        conn.close()
    return {"ok": True, "id": item_id, "topic": topic, "status": status}


def knowledge_audit(topic: str | None = None) -> list[dict]:
    """审核视图数据：全部知识条目（含 hidden——审核就是要看到下架条目才能恢复），
    每条带 id/topic/kind/text/sources/created_at/status，可按 topic 过滤。"""
    store.create_knowledge_items_table()
    out = []
    for it in store.list_knowledge_items(topic=topic):
        try:
            srcs = json.loads(it["sources"] or "[]")
        except (ValueError, TypeError):
            srcs = []
        out.append({
            "id": it["id"],
            "topic": it["topic"],
            "kind": it["kind"],
            "text": it["text"],
            "sources": srcs,
            "created_at": it["created_at"],
            "status": it["status"],
        })
    return out
