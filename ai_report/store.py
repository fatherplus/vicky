"""
L0 存储层——sqlite3 唯一 DB 出口（P1 完整实现）。
全项目 SQL 集中于此模块，其他模块不写 SQL。

设计决策（依据 specs/2026-08-10-l0-l3... §5）：
- WAL 模式：并发读不阻塞写，ThreadingHTTPServer 下最省事
- 每请求开连接：短连接避免跨请求状态泄漏，ThreadingHTTPServer 线程数不大
- 三张表：submissions（L0 不可变快照）、reports（L1 当前态）、feedbacks（L3 账本）
"""

import sqlite3
from pathlib import Path

from . import config as _config


def _db_path() -> Path:
    """每次调用从 _config.DATA_DIR 派生，方便测试 monkey-patch。"""
    return _config.DATA_DIR / "ai-report.db"

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
