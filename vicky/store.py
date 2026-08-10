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
  domain TEXT NOT NULL DEFAULT 'tech',
  template TEXT NOT NULL DEFAULT 'book',
  series TEXT,
  series_order INTEGER,
  created_date TEXT NOT NULL,
  updated_date TEXT,
  current_rev INTEGER NOT NULL REFERENCES submissions(id));

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
    首次调用自动建表。"""
    _config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(DDL)
    return conn


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
                  tag: str = "", subtitle: str = "", domain: str = "tech",
                  template: str = "book", series: str = "", series_order: int = 0,
                  created_date: str = "", updated_date: str = "",
                  current_rev: int = 0):
    """插入或更新 reports 表一行。slug 为主键，存在则 UPDATE。"""
    conn.execute(
        """INSERT INTO reports (slug, file, title, tag, subtitle, domain, template,
           series, series_order, created_date, updated_date, current_rev)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(slug) DO UPDATE SET
           file=excluded.file, title=excluded.title, tag=excluded.tag,
           subtitle=excluded.subtitle, domain=excluded.domain,
           template=excluded.template, series=excluded.series,
           series_order=excluded.series_order, updated_date=excluded.updated_date,
           current_rev=excluded.current_rev""",
        (slug, file, title, tag, subtitle, domain, template,
         series, series_order, created_date, updated_date, current_rev))


def list_reports_from_db(conn: sqlite3.Connection) -> list[dict]:
    """从 reports 表查全部报告，按 created_date 倒序。
    替代原 12 个正则刮 HTML 的 list_reports()。"""
    rows = conn.execute(
        "SELECT * FROM reports ORDER BY created_date DESC, file DESC").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        # 兼容旧 list_reports 返回的字段名与形状
        date = d.get("created_date", "")
        result.append({
            "file": d["file"],
            "title": d["title"],
            "tag": d.get("tag") or "",
            "subtitle": d.get("subtitle") or "",
            "date": date,
            "date_display": date[5:] if len(date) >= 10 else date,
            "updated": d.get("updated_date") or "",
            "series": d.get("series") or "",
            "series_order": d.get("series_order") or 0,
            "series_total": 0,      # 丛书总数由 maintain_series_siblings 维护
            "template": d.get("template") or "book",
            "domain": d.get("domain") or "tech",
        })
    return result


def get_report_by_slug(conn: sqlite3.Connection, slug: str) -> dict | None:
    """按 slug 查单条 report。"""
    row = conn.execute("SELECT * FROM reports WHERE slug=?", (slug,)).fetchone()
    return dict(row) if row else None


# ============================================================
# feedbacks 表操作（L3 账本，P2）
# 账本 append-only：插入后只有裁决会 UPDATE 状态列（可翻案，最新生效）。
# ============================================================
def insert_feedback(conn: sqlite3.Connection, topic: str, domain: str, agent: str,
                    evidence: str, opinion: str, cited: str = "",
                    created_at: str = "") -> int:
    """写回一条反馈（初始 status=pending），返回 feedbacks.id。"""
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
  domain TEXT,
  kind TEXT,
  text TEXT,
  sources TEXT,
  created_at TEXT);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_items_fts USING fts5(
  id, topic, text, kind, category, tag, tokenize = "trigram");
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
    """清空两表，按 knowledge/{domain}/{topic}/items.json 重建检索索引。
    幂等：结果与调用次数无关。返回入库条目数。"""
    conn = get_db()
    try:
        create_knowledge_items_table(conn)
        conn.execute("DELETE FROM knowledge_items")
        conn.execute("DELETE FROM knowledge_items_fts")
        count = 0
        for domain, topics in topics_by_domain.items():
            for topic in topics:
                items_path = _config.KNOWLEDGE_DIR / domain / topic / "items.json"
                if not items_path.exists():
                    continue
                try:
                    items = json.loads(items_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                cat, tags = _topic_category_tags(
                    _config.KNOWLEDGE_DIR / domain / topic / "overview.md")
                tag_str = " ".join(tags)
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for it in items:
                    if not isinstance(it, dict) or "id" not in it or "text" not in it:
                        continue
                    conn.execute(
                        "INSERT INTO knowledge_items (id, topic, domain, kind, text, sources, created_at)"
                        " VALUES (?,?,?,?,?,?,?)",
                        (it["id"], topic, domain, it.get("kind", ""), it["text"],
                         json.dumps(it.get("sources") or [], ensure_ascii=False), now))
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
