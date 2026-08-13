"""
L0 存储层——sqlite3 唯一 DB 出口（P1 完整实现）。
全项目 SQL 集中于此模块，其他模块不写 SQL。

设计决策（依据 specs/2026-08-10-l0-l3... §5）：
- WAL 模式：并发读不阻塞写，ThreadingHTTPServer 下最省事
- 每请求开连接：短连接避免跨请求状态泄漏，ThreadingHTTPServer 线程数不大
- 五张表：submissions（L0 不可变快照）、reports（L1 当前态）、feedbacks（L3 账本）、
  knowledge_items + knowledge_items_fts（P3 知识条目原子化检索索引）
"""

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from . import config as _config


def _db_path() -> Path:
    """每次调用从 _config.DATA_DIR 派生，方便测试 monkey-patch。"""
    return _config.DATA_DIR / "vicky.db"

# ============================================================
# DDL
# ============================================================
DDL = """
CREATE TABLE IF NOT EXISTS submissions (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL,
  rev INTEGER NOT NULL,
  received_at TEXT NOT NULL,
  payload_path TEXT NOT NULL,
  UNIQUE(slug, rev));

CREATE TABLE IF NOT EXISTS reports (
  slug TEXT PRIMARY KEY,
  file TEXT NOT NULL,
  title TEXT NOT NULL,
  tag TEXT,
  subtitle TEXT,
  template TEXT NOT NULL DEFAULT 'book',
  series TEXT,
  series_order INTEGER,
  created_date TEXT NOT NULL,
  updated_date TEXT,
  current_rev INTEGER NOT NULL REFERENCES submissions(id),
  category TEXT NOT NULL DEFAULT 'research',
  narrative TEXT,
  project TEXT,
  hidden INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS projects (
  slug TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS feedbacks (
  id INTEGER PRIMARY KEY,
  topic TEXT NOT NULL,
  domain TEXT NOT NULL,
  agent TEXT NOT NULL,
  cited TEXT,
  evidence TEXT NOT NULL,
  opinion TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  judged_by TEXT,
  judged_at TEXT,
  note TEXT,
  created_at TEXT NOT NULL);
"""


# ============================================================
# 连接
# ============================================================
def get_db() -> sqlite3.Connection:
    """返回 WAL 模式 sqlite3 连接，row_factory=Row（dict-like 访问）。
    首次调用自动建表；建表后跑一次幂等 schema 迁移（旧库补新列 + 回填）。"""
    _config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(DDL)
    conn.executescript(ARCH_DDL)   # 新增：arch 两表 + FTS（幂等，IF NOT EXISTS）
    _migrate_schema(conn)
    return conn


# ============================================================
# schema 迁移（A 阶段重构：domain 列已从 reports DDL 删除；
# 保留探列补列机制供未来扩展，但不再做 domain→category 回填）。
# sqlite 的 ALTER TABLE 不支持 IF NOT EXISTS，用 PRAGMA table_info 探测列再补。
# 幂等：重复执行不炸。
# ============================================================
_REPORT_MIGRATION_COLUMNS = [
    ("category", "TEXT NOT NULL DEFAULT 'research'"),
    ("narrative", "TEXT"),
    ("project", "TEXT"),
    ("hidden", "INTEGER NOT NULL DEFAULT 0"),
]
_KNOWLEDGE_ITEM_MIGRATION_COLUMNS = [
    ("status", "TEXT NOT NULL DEFAULT 'active'"),
    ("category", "TEXT NOT NULL DEFAULT 'ai'"),
]

_PROJECT_MIGRATION_COLUMNS = [
    ("archived", "INTEGER NOT NULL DEFAULT 0"),
]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """PRAGMA table_info 取表全部列名（sqlite 无 information_schema，这是标准探测法）。"""
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate_schema(conn: sqlite3.Connection) -> bool:
    """幂等 schema 迁移：探测缺失列 → ALTER 补列。
    A 阶段重构：domain 回填逻辑已删除；旧库 domain 列仍存在但不再使用。
    返回本次是否做过结构性变更（测试断言幂等用）。ALTER 自动提交。"""
    changed = False
    if _table_exists(conn, "reports"):
        cols = _table_columns(conn, "reports")
        missing = [c for c in _REPORT_MIGRATION_COLUMNS if c[0] not in cols]
        for name, ddl in missing:
            conn.execute(f"ALTER TABLE reports ADD COLUMN {name} {ddl}")
        if missing:
            changed = True
    if _table_exists(conn, "knowledge_items"):
        cols = _table_columns(conn, "knowledge_items")
        for name, ddl in _KNOWLEDGE_ITEM_MIGRATION_COLUMNS:
            if name not in cols:
                conn.execute(f"ALTER TABLE knowledge_items ADD COLUMN {name} {ddl}")
                changed = True
    if _table_exists(conn, "projects"):
        cols = _table_columns(conn, "projects")
        for name, ddl in _PROJECT_MIGRATION_COLUMNS:
            if name not in cols:
                conn.execute(f"ALTER TABLE projects ADD COLUMN {name} {ddl}")
                changed = True
    if changed:
        conn.commit()
    return changed


# ============================================================
# submissions 表操作
# ============================================================
def insert_submission(conn: sqlite3.Connection, slug: str, rev: int,
                      received_at: str, payload_path: str) -> int:
    """插入一条提交快照记录，返回 submissions.id。
    调用方负责管理 rev 递增与唯一约束。"""
    cur = conn.execute(
        "INSERT INTO submissions (slug, rev, received_at, payload_path) VALUES (?,?,?,?)",
        (slug, rev, received_at, payload_path))
    return cur.lastrowid


def get_submission(conn: sqlite3.Connection, sub_id: int) -> dict | None:
    """按 id 查单条 submission。"""
    row = conn.execute("SELECT * FROM submissions WHERE id=?", (sub_id,)).fetchone()
    if not row:
        return None
    return dict(row)


def next_rev(conn: sqlite3.Connection, slug: str) -> int:
    """返回某 slug 的下一个修订号（当前最大 rev+1，无记录则 1）。"""
    row = conn.execute(
        "SELECT MAX(rev) FROM submissions WHERE slug=?", (slug,)).fetchone()
    return (row[0] or 0) + 1


def slug_has_submissions(conn: sqlite3.Connection, slug: str) -> bool:
    """检查某 slug 是否已有快照（backfill 幂等用）。"""
    row = conn.execute(
        "SELECT 1 FROM submissions WHERE slug=? LIMIT 1", (slug,)).fetchone()
    return row is not None


# ============================================================
# reports 表操作
# ============================================================
def upsert_report(conn: sqlite3.Connection, slug: str, file: str, title: str,
                  tag: str = "", subtitle: str = "",
                  template: str = "book",
                  created_date: str = "", updated_date: str = "",
                  current_rev: int = 0, category: str = "research",
                  narrative: str = "", project: str = ""):
    """插入或更新 reports 表一行。slug 为主键，存在则 UPDATE。
    A 阶段重构：domain 参数已删除；category（三分类骨架）/ narrative（叙事方式）/
    project（归档维度）三字段与模板正交，一并落库。
    D 阶段：series/series_order 不再读写（DDL 物理列保留，仅停止读写）。"""
    conn.execute(
        """INSERT INTO reports (slug, file, title, tag, subtitle, template,
           created_date, updated_date, current_rev,
           category, narrative, project)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(slug) DO UPDATE SET
           file=excluded.file, title=excluded.title, tag=excluded.tag,
           subtitle=excluded.subtitle,
           template=excluded.template,
           updated_date=excluded.updated_date,
           current_rev=excluded.current_rev,
           category=excluded.category, narrative=excluded.narrative,
           project=excluded.project""",
        (slug, file, title, tag, subtitle, template,
         created_date, updated_date, current_rev,
         category, narrative, project))


def _report_row_dict(r: sqlite3.Row) -> dict:
    """reports 行 → 对外 dict。domain 键已彻底删除；category / narrative / project / hidden
    四字段保留。全部调用方已核实不再读 domain（2026-08-12 二次重构清理完成）。"""
    d = dict(r)
    date = d.get("created_date", "")
    return {
        "slug": d["slug"],
        "file": d["file"],
        "title": d["title"],
        "tag": d.get("tag") or "",
        "subtitle": d.get("subtitle") or "",
        "date": date,
        "date_display": date[5:] if len(date) >= 10 else date,
        "updated": d.get("updated_date") or "",
        "template": d.get("template") or "book",
        "category": d.get("category") or "research",
        "narrative": d.get("narrative") or "",
        "project": d.get("project") or "",
        "hidden": bool(d.get("hidden") or 0),
    }


def list_reports(conn: sqlite3.Connection | None = None,
                 include_hidden: bool = False,
                 category: str | None = None,
                 project: str | None = None) -> list[dict]:
    """新查询助手（重构蓝图）：按 include_hidden / category / project 过滤，
    按 created_date 倒序。默认不含 hidden（软下架报告从文库消失）。
    conn 可省略（自动开/关），也支持显式传入复用事务。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        sql, args = "SELECT * FROM reports", []
        conds = []
        if not include_hidden:
            conds.append("hidden = 0")
        if category:
            conds.append("category = ?")
            args.append(category)
        if project:
            conds.append("project = ?")
            args.append(project)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY created_date DESC, file DESC"
        return [_report_row_dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        if own:
            conn.close()


def list_reports_from_db(conn: sqlite3.Connection) -> list[dict]:
    """兼容旧入口：全量返回（含 hidden，形状与旧版一致，仅多 category/project/hidden 键）。
    由新 list_reports 实现，行为不变。"""
    return list_reports(conn, include_hidden=True)


def list_projects(conn: sqlite3.Connection | None = None) -> list[dict]:
    """项目空间聚合（重构蓝图）：project 名 + 篇数 + 最新日期，按最新日期倒序。
    排除 hidden 报告与空 project；conn 可省略（自动开/关）。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        rows = conn.execute(
            "SELECT project, COUNT(*) AS count, MAX(created_date) AS latest"
            " FROM reports WHERE hidden = 0 AND project IS NOT NULL AND project != ''"
            " GROUP BY project ORDER BY latest DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def set_report_hidden(slug: str, hidden: bool,
                      conn: sqlite3.Connection | None = None) -> None:
    """审核治理（重构蓝图）：软下架/恢复——hidden=True 下架（可逆），False 恢复。
    conn 省略时自动开连接并 commit；传入 conn 则由调用方负责 commit。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        conn.execute("UPDATE reports SET hidden=? WHERE slug=?",
                     (1 if hidden else 0, slug))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def get_report_by_slug(conn: sqlite3.Connection, slug: str) -> dict | None:
    """按 slug 查单条 report。"""
    row = conn.execute("SELECT * FROM reports WHERE slug=?", (slug,)).fetchone()
    return dict(row) if row else None


# ============================================================
# feedbacks 表操作（L3 账本，P2）
# 账本 append-only：插入后只有裁决会 UPDATE 状态列（可翻案，最新生效）。
# ============================================================
def insert_feedback(conn: sqlite3.Connection, topic: str, agent: str,
                    evidence: str, opinion: str, cited: str = "",
                    created_at: str = "", domain: str = "") -> int:
    """写回一条反馈（初始 status=pending），返回 feedbacks.id。
    domain 参数已随 domain 语义删除失去业务意义，仅为兼容旧 schema 列保留，默认空字符串。"""
    cur = conn.execute(
        """INSERT INTO feedbacks (topic, domain, agent, cited, evidence, opinion,
           status, created_at) VALUES (?,?,?,?,?,?, 'pending', ?)""",
        (topic, domain, agent, cited, evidence, opinion, created_at))
    return cur.lastrowid


def get_feedback(conn: sqlite3.Connection, fid: int) -> dict | None:
    row = conn.execute("SELECT * FROM feedbacks WHERE id=?", (fid,)).fetchone()
    return dict(row) if row else None


def list_feedbacks(conn: sqlite3.Connection, topic: str = None,
                   status: str = None, domain: str = None) -> list[dict]:
    """账本查询：topic/status/domain 均可选过滤，按 id 升序（账本序）。"""
    sql, args = "SELECT * FROM feedbacks", []
    conds = []
    if topic:
        conds.append("topic=?"); args.append(topic)
    if status:
        conds.append("status=?"); args.append(status)
    if domain:
        conds.append("domain=?"); args.append(domain)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY id"
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def adopted_feedbacks(conn: sqlite3.Connection, topic: str) -> list[dict]:
    """某主题已采纳的反馈（L2 编译的来源输入；l2_distill 直查防环，规格 §3）。"""
    rows = conn.execute(
        "SELECT * FROM feedbacks WHERE topic=? AND status='adopted' ORDER BY id", (topic,))
    return [dict(r) for r in rows.fetchall()]


def set_feedback_verdict(conn: sqlite3.Connection, fid: int, status: str,
                         judged_by: str, judged_at: str, note: str):
    """裁决落盘：状态机 pending→adopted|rejected，可再裁决，最新一次生效（直接覆盖）。"""
    conn.execute(
        "UPDATE feedbacks SET status=?, judged_by=?, judged_at=?, note=? WHERE id=?",
        (status, judged_by, judged_at, note, fid))


def feedback_stats(conn: sqlite3.Connection, topic: str) -> dict:
    """写回次数 + 最近使用时间（GET /api/knowledge?topic=X 与藏书楼卡片用）。"""
    row = conn.execute(
        "SELECT COUNT(*), MAX(created_at) FROM feedbacks WHERE topic=?", (topic,)).fetchone()
    return {"feedback_count": row[0] or 0, "feedback_last_used": row[1] or ""}


def feedback_counts(conn: sqlite3.Connection) -> dict:
    """全部主题的写回次数 {topic: count}（藏书楼卡片批量渲染用，一次查完）。"""
    rows = conn.execute("SELECT topic, COUNT(*) FROM feedbacks GROUP BY topic").fetchall()
    return {r[0]: r[1] for r in rows}


# ============================================================
# knowledge_items 表 + FTS5 检索索引（P3 VK 原子化）
# 知识条目原子化：overview.md → items.json → 本表 + FTS5（id/topic/text/kind/category/tag 可检索）。
# FTS 用 trigram 分词：支持中文子串检索（unicode61 会把整段中文当一个 token，搜不到）；
# 1-2 字中文片段（trigram 盲区）由 search_items 退回 LIKE 兜底。
# ============================================================
KNOWLEDGE_ITEMS_DDL = """
CREATE TABLE IF NOT EXISTS knowledge_items (
  id TEXT PRIMARY KEY,
  topic TEXT,
  kind TEXT,
  text TEXT,
  sources TEXT,
  category TEXT NOT NULL DEFAULT 'ai',
  created_at TEXT,
  status TEXT NOT NULL DEFAULT 'active');

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_items_fts USING fts5(
  id, topic, text, kind, category, tag, tokenize = "trigram");
"""

# ============================================================
# arch 两张表 + FTS5 检索索引（架构知识归档：project 级架构图 + 模块节点）。
# 节点正文走 trigram 分词（支持中文子串检索，与 knowledge_items_fts 一致）。
# ============================================================
ARCH_DDL = """
CREATE TABLE IF NOT EXISTS arch_graphs (
  project    TEXT PRIMARY KEY,
  graph      TEXT NOT NULL,
  updated_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS arch_modules (
  project    TEXT NOT NULL,
  node_id    TEXT NOT NULL,
  kind       TEXT NOT NULL DEFAULT 'module',
  body_md    TEXT NOT NULL DEFAULT '',
  status     TEXT NOT NULL DEFAULT 'active',
  updated_at TEXT NOT NULL,
  PRIMARY KEY (project, node_id));

CREATE VIRTUAL TABLE IF NOT EXISTS arch_modules_fts USING fts5(
  project, node_id, body_md, tokenize = "trigram");
"""

# overview.md frontmatter 里 category / tags 的轻量提取（FTS 过滤列用；
# 不引 l2_distill 的 parse_frontmatter——l2_distill import store，反向引用会成环）
_FM_CATEGORY_RE = re.compile(r"^category:\s*(\S+)", re.MULTILINE)
_FM_TAGS_RE = re.compile(r"^tags:\s*$([\s\S]*?)(?=^---$|^[a-zA-Z_]+:|\Z)", re.MULTILINE)


def _topic_category_tags(overview_path: Path) -> tuple[str, list]:
    """读 overview.md frontmatter 的 category + tags。缺省兜底 ('ai', []) 与 l2_distill 一致。"""
    cat, tags = "ai", []
    if not overview_path.exists():
        return cat, tags
    try:
        text = overview_path.read_text(encoding="utf-8")
    except OSError:
        return cat, tags
    m = _FM_CATEGORY_RE.search(text)
    if m:
        cat = m.group(1).strip()
    tm = _FM_TAGS_RE.search(text)
    if tm:
        for ln in tm.group(1).splitlines():
            lm = re.match(r"^\s*-\s*(.+)$", ln)
            if lm:
                tags.append(lm.group(1).strip())
    return cat, tags


def _has_short_cjk(q: str) -> bool:
    """查询里含 1-2 字中文片段（trigram 匹配不了的盲区，需 LIKE 兜底）。"""
    return any(len(seg) <= 2 for seg in re.findall(r"[\u4e00-\u9fff]+", q))


def create_knowledge_items_table(conn: sqlite3.Connection | None = None) -> None:
    """建 knowledge_items + knowledge_items_fts（FTS5）两表，幂等。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        conn.executescript(KNOWLEDGE_ITEMS_DDL)
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def rebuild_items_index(topics_by_domain: dict) -> int:
    """清空两表，按 knowledge/{topic}/items.json 重建检索索引。
    B 阶段重构：目录扁平 knowledge/{topic}/，不再按 domain 分层；
    topics_by_domain 参数保留兼容（忽略 domain 键，扁平取值）。
    幂等：结果与调用次数无关。返回入库条目数。
    审核治理：重建前先记存量 status——hidden 条目保留 hidden 且不进 FTS
    （查询只返回 active；审核视图仍可见，可恢复），重建不吞掉人工下架。"""
    conn = get_db()
    try:
        create_knowledge_items_table(conn)
        old_status = {r["id"]: r["status"] for r in conn.execute(
            "SELECT id, status FROM knowledge_items").fetchall()}
        conn.execute("DELETE FROM knowledge_items")
        conn.execute("DELETE FROM knowledge_items_fts")
        count = 0
        # B 阶段：扁平遍历——topics_by_domain 可能仍是 {domain: [topics]}，提取所有 topic 名再查文件
        all_topics = set()
        for topics in topics_by_domain.values():
            for t in (topics or []):
                all_topics.add(t if isinstance(t, str) else (t.get("topic") or t.get("slug") or ""))
        for topic in sorted(all_topics):
            if not topic:
                continue
            items_path = _config.KNOWLEDGE_DIR / topic / "items.json"
            if not items_path.exists():
                continue
            try:
                items = json.loads(items_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            cat, tags = _topic_category_tags(
                _config.KNOWLEDGE_DIR / topic / "overview.md")
            tag_str = " ".join(tags)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for it in items:
                if not isinstance(it, dict) or "id" not in it or "text" not in it:
                    continue
                status = old_status.get(it["id"], "active")
                conn.execute(
                    "INSERT INTO knowledge_items"
                    " (id, topic, kind, text, sources, created_at, status)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (it["id"], topic, it.get("kind", ""), it["text"],
                     json.dumps(it.get("sources") or [], ensure_ascii=False), now, status))
                if status == "active":
                    conn.execute(
                        "INSERT INTO knowledge_items_fts (id, topic, text, kind, category, tag)"
                        " VALUES (?,?,?,?,?,?)",
                        (it["id"], topic, it["text"], it.get("kind", ""), cat, tag_str))
                count += 1
        conn.commit()
        return count
    finally:
        conn.close()


def search_items(q: str, limit: int = 20, category: str | None = None,
                 tag: str | None = None):
    """FTS5 全文检索知识条目。返回 [(id, topic, text, kind, rank), ...]，按相关度升序
    （bm25 越小越相关）。category 精确过滤、tag 子串过滤（可选）。
    trigram 盲区（1-2 字中文）或无命中时退回 knowledge_items 表 LIKE 兜底。"""
    q = (q or "").strip()
    if not q:
        return []
    conn = get_db()
    try:
        where, args = "knowledge_items_fts MATCH ?", [q]
        if category:
            where += " AND category = ?"
            args.append(category)
        if tag:
            where += " AND tag LIKE ?"
            args.append(f"%{tag}%")
        sql = (f"SELECT id, topic, text, kind, bm25(knowledge_items_fts) AS rank "
               f"FROM knowledge_items_fts WHERE {where} ORDER BY rank LIMIT ?")
        args.append(limit)
        try:
            rows = conn.execute(sql, args).fetchall()
        except sqlite3.OperationalError:
            # FTS 语法错误（如查询含 - # 等）：整体当短语再试一次
            args[0] = '"' + q.replace('"', '""') + '"'
            rows = conn.execute(sql, args).fetchall()
        hits = [(r["id"], r["topic"], r["text"], r["kind"], r["rank"]) for r in rows]
        if not hits and _has_short_cjk(q):
            # trigram 对 1-2 字中文无效：LIKE 兜底（rank 无意义，统一给 0.0）
            base = "SELECT id, topic, text, kind FROM knowledge_items WHERE text LIKE ?"
            bargs = [f"%{q}%"]
            if category:
                base += " AND topic IN (SELECT topic FROM knowledge_items_fts" \
                         " WHERE category = ?)"
                bargs.append(category)
            if tag:
                base += " AND topic IN (SELECT topic FROM knowledge_items_fts" \
                         " WHERE tag LIKE ?)"
                bargs.append(f"%{tag}%")
            base += " ORDER BY id LIMIT ?"
            bargs.append(limit)
            hits = [(r["id"], r["topic"], r["text"], r["kind"], 0.0)
                    for r in conn.execute(base, bargs).fetchall()]
        return hits
    finally:
        conn.close()


# ============================================================
# knowledge_items 读辅助（P4 知识查询用；SQL 保持在本模块）
# ============================================================
def count_knowledge_items(conn: sqlite3.Connection | None = None) -> int:
    """知识条目总数（知识库空判定用：0 = 尚未蒸馏/未建索引）。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        row = conn.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()
        return row[0] or 0
    finally:
        if own:
            conn.close()


def knowledge_catalog(conn: sqlite3.Connection | None = None) -> dict:
    """目录模式数据源：全部知识条目按 (category, topic) 分组统计。
    category 只存于 FTS 列（overview frontmatter），knowledge_items 表无此列——
    聚合走 knowledge_items_fts；两表同 id 同插入，计数与 knowledge_items 对齐。
    返回 {"catalog": [{category, topics: [{topic, count}]}], "total_topics", "total_items"}。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        rows = conn.execute(
            "SELECT category, topic, COUNT(*) AS cnt FROM knowledge_items_fts"
            " GROUP BY category, topic ORDER BY category, topic").fetchall()
    finally:
        if own:
            conn.close()
    catalog, total_items = [], 0
    for cat, topic, cnt in rows:
        total_items += cnt
        bucket = next((b for b in catalog if b["category"] == cat), None)
        if bucket is None:
            bucket = {"category": cat or "ai", "topics": []}
            catalog.append(bucket)
        bucket["topics"].append({"topic": topic, "count": cnt})
    return {"catalog": catalog, "total_topics": len(rows), "total_items": total_items}


def item_sources(conn: sqlite3.Connection | None, item_ids: list[str]) -> dict:
    """按 id 批量取知识条目的 sources（knowledge_items.sources 为 JSON 数组文本）。
    返回 {id: [source, ...]}；缺失/非法一律空数组。"""
    if not item_ids:
        return {}
    own = conn is None
    if own:
        conn = get_db()
    try:
        placeholders = ",".join("?" for _ in item_ids)
        rows = conn.execute(
            f"SELECT id, sources FROM knowledge_items WHERE id IN ({placeholders})",
            list(item_ids)).fetchall()
        out = {}
        for r in rows:
            try:
                out[r["id"]] = json.loads(r["sources"] or "[]")
            except (ValueError, TypeError):
                out[r["id"]] = []
        return out
    finally:
        if own:
            conn.close()


def get_knowledge_items_by_source(slug: str,
                                   conn: sqlite3.Connection | None = None) -> list:
    """审核治理（重构蓝图）：查 sources（JSON 数组文本）含该 slug 的知识条目。
    用 Python 侧精确匹配（LIKE 会误伤子串、json_each 依赖 JSON1），条目量小性能无忧。
    conn 可省略（自动开/关）。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        out = []
        for r in conn.execute(
                "SELECT * FROM knowledge_items ORDER BY id").fetchall():
            try:
                srcs = json.loads(r["sources"] or "[]")
            except (ValueError, TypeError):
                continue
            if slug in srcs:
                out.append(dict(r))
        return out
    finally:
        if own:
            conn.close()


def set_knowledge_item_status(item_id: str, status: str,
                              conn: sqlite3.Connection | None = None) -> None:
    """审核治理（重构蓝图）：知识条目状态变更（active/hidden），供审核视图精修。
    conn 省略时自动开连接并 commit；传入 conn 则由调用方负责 commit。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        conn.execute("UPDATE knowledge_items SET status=? WHERE id=?",
                     (status, item_id))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


# ============================================================
# 审核治理 store 助手（重构蓝图 §04）
# 软下架/硬删除/条目状态精修全走本层 SQL；curate.py 只编排不写 SQL。
# ============================================================
def get_knowledge_item(conn: sqlite3.Connection, item_id: str) -> dict | None:
    """按 id 查单条知识条目（含 status）。conn 必传（调用方管理事务）。"""
    row = conn.execute("SELECT * FROM knowledge_items WHERE id=?", (item_id,)).fetchone()
    return dict(row) if row else None


def list_knowledge_items(conn: sqlite3.Connection | None = None,
                         topic: str | None = None) -> list[dict]:
    """全部知识条目（含 hidden——审核视图要看到下架条目才能恢复），
    topic 可选过滤，按 topic, id 排序。conn 可省略（自动开/关）。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        sql, args = "SELECT * FROM knowledge_items", []
        if topic:
            sql += " WHERE topic=?"
            args.append(topic)
        sql += " ORDER BY topic, id"
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        if own:
            conn.close()


def sync_item_fts(item_id: str, status: str,
                  conn: sqlite3.Connection | None = None) -> None:
    """知识条目状态变更时同步 FTS 可见性（审核治理）：
    hidden → 从 knowledge_items_fts 删行（search_items / 知识查询查不到）；
    active → 重新插入 FTS（category/tag 从该主题 overview frontmatter 现取，与重建口径一致）。
    knowledge_items 行本身由 set_knowledge_item_status 管理，本函数只动 FTS。
    B 阶段重构：路径扁平 knowledge/{topic}/overview.md。
    conn 省略时自动开连接并 commit；传入 conn 则由调用方负责 commit。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        row = conn.execute("SELECT * FROM knowledge_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            return
        conn.execute("DELETE FROM knowledge_items_fts WHERE id=?", (item_id,))
        if status == "active":
            cat, tags = _topic_category_tags(
                _config.KNOWLEDGE_DIR / row["topic"] / "overview.md")
            conn.execute(
                "INSERT INTO knowledge_items_fts (id, topic, text, kind, category, tag)"
                " VALUES (?,?,?,?,?,?)",
                (row["id"], row["topic"], row["text"], row["kind"], cat, " ".join(tags)))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def delete_knowledge_item(item_id: str, conn: sqlite3.Connection | None = None) -> bool:
    """级联删除一条知识条目：knowledge_items + knowledge_items_fts 同步删（FTS 索引不留孤儿）。
    返回是否删到。conn 省略时自动开连接并 commit；传入 conn 则由调用方负责 commit。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        conn.execute("DELETE FROM knowledge_items_fts WHERE id=?", (item_id,))
        cur = conn.execute("DELETE FROM knowledge_items WHERE id=?", (item_id,))
        if own:
            conn.commit()
        return cur.rowcount > 0
    finally:
        if own:
            conn.close()


def delete_report_row(slug: str, conn: sqlite3.Connection | None = None) -> bool:
    """删除 reports 表一行。返回是否删到。conn 省略时自动开连接并 commit。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        cur = conn.execute("DELETE FROM reports WHERE slug=?", (slug,))
        if own:
            conn.commit()
        return cur.rowcount > 0
    finally:
        if own:
            conn.close()


# ============================================================
# projects 表操作（A 阶段重构：
# 「先建项目」API 与 .vicky 联动）
# ============================================================
def create_project(slug: str, name: str, description: str = "",
                   conn: sqlite3.Connection | None = None) -> None:
    """新建项目元信息。slug 为主键，重复插入触发 IntegrityError（调用方处理）。
    conn 省略时自动开连接并 commit。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO projects (slug, name, description, created_at)"
            " VALUES (?,?,?,?)",
            (slug, name, description, now))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def get_project(slug: str, conn: sqlite3.Connection | None = None) -> dict | None:
    """按 slug 查单个项目元信息。返回 None 表示不存在。
    conn 省略时自动开/关。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        row = conn.execute("SELECT * FROM projects WHERE slug=?", (slug,)).fetchone()
        return dict(row) if row else None
    finally:
        if own:
            conn.close()


def archive_project(slug: str, archived: bool = True,
                   conn: sqlite3.Connection | None = None) -> bool:
    """软删除/归档项目元信息（projects.archived），可逆。返回是否命中行。
    仅动 projects 表；reports.project 引用不受影响（报告仍在，只是项目元信息归档）。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        cur = conn.execute("UPDATE projects SET archived=? WHERE slug=?",
                           (1 if archived else 0, slug))
        if own:
            conn.commit()
        return cur.rowcount > 0
    finally:
        if own:
            conn.close()


def list_projects_meta(conn: sqlite3.Connection | None = None,
                      include_archived: bool = False) -> list[dict]:
    """列出项目元信息（projects 表），按创建时间倒序，默认排除归档。
    区别于 list_projects（按 reports.project 聚合，用于索引页项目卡片）；
    本函数是「先建项目」API 的数据源——返回元信息版供 POST/GET /api/projects 使用。
    conn 省略时自动开/关。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        sql = "SELECT * FROM projects"
        if not include_archived:
            sql += " WHERE archived = 0"
        sql += " ORDER BY created_at DESC"
        rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


# ============================================================
# arch_graphs / arch_modules（架构导航器：骨架 + 模块正文）
# ============================================================
def save_arch_graph(project: str, graph: dict,
                    conn: sqlite3.Connection | None = None) -> None:
    """整体覆盖某项目的架构骨架（JSON）。upsert：主键 project。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO arch_graphs (project, graph, updated_at) VALUES (?,?,?)"
            " ON CONFLICT(project) DO UPDATE SET graph=excluded.graph,"
            " updated_at=excluded.updated_at",
            (project, json.dumps(graph, ensure_ascii=False), now))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def get_arch_graph(project: str,
                   conn: sqlite3.Connection | None = None) -> dict | None:
    """取某项目骨架 JSON（dict）；无 → None。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        row = conn.execute("SELECT graph FROM arch_graphs WHERE project=?",
                           (project,)).fetchone()
        return json.loads(row["graph"]) if row else None
    finally:
        if own:
            conn.close()


def save_arch_module(project: str, node_id: str, kind: str, body_md: str,
                     conn: sqlite3.Connection | None = None) -> None:
    """upsert 单个模块正文，并同步 FTS（active 才进索引）。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO arch_modules (project, node_id, kind, body_md, status, updated_at)"
            " VALUES (?,?,?,?, 'active', ?)"
            " ON CONFLICT(project, node_id) DO UPDATE SET kind=excluded.kind,"
            " body_md=excluded.body_md, status='active', updated_at=excluded.updated_at",
            (project, node_id, kind, body_md, now))
        conn.execute("DELETE FROM arch_modules_fts WHERE project=? AND node_id=?",
                     (project, node_id))
        conn.execute("INSERT INTO arch_modules_fts (project, node_id, body_md)"
                     " VALUES (?,?,?)", (project, node_id, body_md))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def get_arch_module(project: str, node_id: str,
                    conn: sqlite3.Connection | None = None) -> dict | None:
    own = conn is None
    if own:
        conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM arch_modules WHERE project=? AND node_id=?",
            (project, node_id)).fetchone()
        return dict(row) if row else None
    finally:
        if own:
            conn.close()


def mark_arch_orphans(project: str, keep_ids: list[str],
                      conn: sqlite3.Connection | None = None) -> int:
    """骨架里已消失的模块 → status='orphan' 且移出 FTS。keep_ids=骨架现存节点。
    返回被标记为孤儿的行数。软标记，不删正文（防误删）。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        rows = conn.execute(
            "SELECT node_id FROM arch_modules WHERE project=? AND status='active'",
            (project,)).fetchall()
        keep = set(keep_ids)
        orphaned = 0
        for r in rows:
            nid = r["node_id"]
            if nid not in keep:
                conn.execute(
                    "UPDATE arch_modules SET status='orphan' WHERE project=? AND node_id=?",
                    (project, nid))
                conn.execute("DELETE FROM arch_modules_fts WHERE project=? AND node_id=?",
                             (project, nid))
                orphaned += 1
        if own:
            conn.commit()
        return orphaned
    finally:
        if own:
            conn.close()


def search_arch_modules(project: str, q: str, limit: int = 20,
                        conn: sqlite3.Connection | None = None) -> list[dict]:
    """FTS 搜某项目 active 模块。返回 [{node_id, snippet}]，按相关度升序。"""
    q = (q or "").strip()
    if not q:
        return []
    own = conn is None
    if own:
        conn = get_db()
    try:
        sql = ("SELECT node_id, body_md FROM arch_modules_fts"
               " WHERE project=? AND arch_modules_fts MATCH ? LIMIT ?")
        try:
            rows = conn.execute(sql, (project, q, limit)).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(sql, (project, '"' + q.replace('"', '""') + '"',
                                      limit)).fetchall()
        return [{"node_id": r["node_id"],
                 "snippet": (r["body_md"] or "")[:160]} for r in rows]
    finally:
        if own:
            conn.close()


def count_submissions(conn: sqlite3.Connection, slug: str) -> int:
    """某 slug 的提交快照行数（审核清单展示用）。conn 必传。"""
    row = conn.execute(
        "SELECT COUNT(*) FROM submissions WHERE slug=?", (slug,)).fetchone()
    return row[0] or 0


def delete_submissions_for_slug(slug: str, conn: sqlite3.Connection | None = None) -> int:
    """删除某 slug 的全部 submissions 行（硬删除级联）。返回删除行数。
    注意 FK：reports.current_rev 引用 submissions.id，调用方必须先删 reports 行。
    conn 省略时自动开连接并 commit；传入 conn 则由调用方负责 commit。"""
    own = conn is None
    if own:
        conn = get_db()
    try:
        cur = conn.execute("DELETE FROM submissions WHERE slug=?", (slug,))
        if own:
            conn.commit()
        return cur.rowcount
    finally:
        if own:
            conn.close()


def validate_cited_ids(item_ids: list[str]) -> list[str]:
    """校验 cited 里的知识条目 ID 是否真实存在。
    返回无效 ID 列表（空=全部有效）。P5 引用回灌闭合用。"""
    if not item_ids:
        return []
    conn = get_db()
    try:
        placeholders = ",".join("?" for _ in item_ids)
        rows = conn.execute(
            f"SELECT id FROM knowledge_items WHERE id IN ({placeholders})",
            item_ids).fetchall()
        valid = {r["id"] for r in rows}
        return [iid for iid in item_ids if iid not in valid]
    finally:
        conn.close()
