"""P1 测试：store 层建表 / CRUD / 幂等。"""
import sqlite3
import tempfile
from pathlib import Path

from vicky import store, config


def test_tables_created():
    """get_db 首次调用自动建三张表。"""
    with tempfile.TemporaryDirectory() as d:
        dd = Path(d)
        # 临时覆盖 DATA_DIR
        orig = config.DATA_DIR
        config.DATA_DIR = dd
        try:
            conn = store.get_db()
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            conn.close()
            assert "submissions" in tables
            assert "reports" in tables
            assert "feedbacks" in tables
        finally:
            config.DATA_DIR = orig


def test_submission_insert_and_query():
    with tempfile.TemporaryDirectory() as d:
        dd = Path(d)
        orig = config.DATA_DIR
        config.DATA_DIR = dd
        try:
            conn = store.get_db()
            sub_id = store.insert_submission(conn, "test-slug", 1,
                                             "2026-08-10T00:00:00+00:00",
                                             "/fake/path/submission.json")
            conn.commit()
            assert sub_id == 1

            # 按 id 查
            row = store.get_submission(conn, sub_id)
            assert row["slug"] == "test-slug"
            assert row["rev"] == 1

            # next_rev
            assert store.next_rev(conn, "test-slug") == 2
            assert store.next_rev(conn, "new-slug") == 1

            # slug_has_submissions
            assert store.slug_has_submissions(conn, "test-slug")
            assert not store.slug_has_submissions(conn, "nonexistent")

            # UNIQUE(slug, rev) 约束
            try:
                store.insert_submission(conn, "test-slug", 1,
                                        "2026-08-10T00:00:00+00:00", "/fake/dup.json")
                conn.commit()
                assert False, "应该抛 IntegrityError"
            except sqlite3.IntegrityError:
                conn.rollback()

            conn.close()
        finally:
            config.DATA_DIR = orig


def test_report_upsert():
    with tempfile.TemporaryDirectory() as d:
        dd = Path(d)
        orig = config.DATA_DIR
        config.DATA_DIR = dd
        try:
            conn = store.get_db()
            # 先插入一条 submission（reports.current_rev 的外键依赖）
            sub_id = store.insert_submission(conn, "r1", 1,
                                             "2026-08-10T00:00:00+00:00", "/fake/s.json")
            conn.commit()

            # INSERT
            store.upsert_report(conn, "r1", "2026-08-10-r1.html", "标题1",
                                tag="测试", subtitle="副标题", domain="tech",
                                template="book", series="", series_order=0,
                                created_date="2026-08-10", updated_date="",
                                current_rev=sub_id)
            conn.commit()

            rows = store.list_reports_from_db(conn)
            assert len(rows) == 1
            assert rows[0]["title"] == "标题1"
            assert rows[0]["tag"] == "测试"
            assert rows[0]["file"] == "2026-08-10-r1.html"

            # UPDATE (upsert)
            sub_id2 = store.insert_submission(conn, "r1", 2,
                                              "2026-08-11T00:00:00+00:00", "/fake/s2.json")
            conn.commit()
            store.upsert_report(conn, "r1", "2026-08-10-r1.html", "标题1修订",
                                tag="测试", subtitle="副标题2", domain="design",
                                template="book", series="", series_order=0,
                                created_date="2026-08-10", updated_date="2026-08-11",
                                current_rev=sub_id2)
            conn.commit()

            rows = store.list_reports_from_db(conn)
            assert len(rows) == 1  # 仍是 1 行
            assert rows[0]["title"] == "标题1修订"
            assert rows[0]["updated"] == "2026-08-11"
            assert rows[0]["domain"] == "design"

            # get_report_by_slug
            r = store.get_report_by_slug(conn, "r1")
            assert r["file"] == "2026-08-10-r1.html"

            conn.close()
        finally:
            config.DATA_DIR = orig


def test_list_reports_ordering():
    """验证按 created_date 倒序。"""
    with tempfile.TemporaryDirectory() as d:
        dd = Path(d)
        orig = config.DATA_DIR
        config.DATA_DIR = dd
        try:
            conn = store.get_db()
            for i, (slug, date) in enumerate([
                ("a", "2026-01-01"), ("b", "2026-06-15"), ("c", "2026-03-10")
            ], 1):
                sub_id = store.insert_submission(conn, slug, 1,
                                                 f"{date}T00:00:00+00:00", f"/fake/{slug}.json")
                conn.commit()
                store.upsert_report(conn, slug, f"{date}-{slug}.html", f"标题{slug}",
                                    created_date=date, current_rev=sub_id)
                conn.commit()

            rows = store.list_reports_from_db(conn)
            dates = [r["date"] for r in rows]
            assert dates == ["2026-06-15", "2026-03-10", "2026-01-01"]  # 倒序

            conn.close()
        finally:
            config.DATA_DIR = orig


# ============================================================
# 重构蓝图 2026-08-12 · schema 地基：迁移幂等 + 回填 + 新查询助手
# ============================================================

# 存量库（迁移前）的旧版建表 DDL，模拟真实旧库
_OLD_REPORTS_DDL = """
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
  current_rev INTEGER NOT NULL);
"""
_OLD_KNOWLEDGE_ITEMS_DDL = """
CREATE TABLE IF NOT EXISTS knowledge_items (
  id TEXT PRIMARY KEY,
  topic TEXT,
  domain TEXT,
  kind TEXT,
  text TEXT,
  sources TEXT,
  created_at TEXT);
"""


def _insert_legacy_report(conn, slug, domain, date="2026-01-01"):
    """按旧 schema 插一条存量报告（无新列）。"""
    conn.execute(
        "INSERT INTO reports (slug, file, title, domain, template, created_date, current_rev)"
        " VALUES (?,?,?,?,?,?,0)",
        (slug, f"{date}-{slug}.html", f"标题{slug}", domain, "book", date))


def test_fresh_db_has_new_columns():
    """新库：DDL 直接带新列，无需迁移即齐备。
    knowledge_items 是懒建表（create_knowledge_items_table），故先建再查。"""
    with tempfile.TemporaryDirectory() as d:
        orig = config.DATA_DIR
        config.DATA_DIR = Path(d)
        try:
            conn = store.get_db()
            rep_cols = {r[1] for r in conn.execute("PRAGMA table_info(reports)")}
            for col in ("category", "narrative", "project", "hidden"):
                assert col in rep_cols
            store.create_knowledge_items_table(conn)
            ki_cols = {r[1] for r in conn.execute("PRAGMA table_info(knowledge_items)")}
            assert "status" in ki_cols
            conn.close()
        finally:
            config.DATA_DIR = orig


def test_migration_backfills_legacy_domain_to_category():
    """存量库：get_db 触发迁移 → 新列补上 + domain 按 LEGACY 映射回填 category。"""
    with tempfile.TemporaryDirectory() as d:
        orig = config.DATA_DIR
        config.DATA_DIR = Path(d)
        try:
            # 手工造旧库（不经过 store.get_db）
            conn = sqlite3.connect(str(config.DATA_DIR / "vicky.db"))
            conn.executescript(_OLD_REPORTS_DDL)
            conn.executescript(_OLD_KNOWLEDGE_ITEMS_DDL)
            for slug, domain in [("a", "tech"), ("b", "ephemeral"),
                                 ("c", "arch"), ("d", "design")]:
                _insert_legacy_report(conn, slug, domain)
            conn.commit()
            conn.close()

            # 首次 get_db → 触发迁移
            conn = store.get_db()
            rows = {r["slug"]: dict(r) for r in conn.execute(
                "SELECT * FROM reports").fetchall()}
            assert rows["a"]["category"] == "research"   # tech → research
            assert rows["b"]["category"] == "brief"      # ephemeral → brief
            assert rows["c"]["category"] == "arch-doc"   # arch → arch-doc
            assert rows["d"]["category"] == "design"     # design → design（legacy 保留）
            # 新列默认值
            assert rows["a"]["narrative"] is None
            assert rows["a"]["project"] is None
            assert rows["a"]["hidden"] == 0
            conn.close()
        finally:
            config.DATA_DIR = orig


def test_migration_is_idempotent():
    """迁移幂等：同一库跑两轮不炸、不重复回填、结构性变更只发生一次。"""
    with tempfile.TemporaryDirectory() as d:
        orig = config.DATA_DIR
        config.DATA_DIR = Path(d)
        try:
            conn = sqlite3.connect(str(config.DATA_DIR / "vicky.db"))
            conn.executescript(_OLD_REPORTS_DDL)
            _insert_legacy_report(conn, "b", "ephemeral")
            conn.commit()
            conn.close()

            # 第一轮：对旧库显式迁移 → 发生结构性变更 + 回填
            conn = sqlite3.connect(str(config.DATA_DIR / "vicky.db"))
            assert store._migrate_schema(conn) is True
            row = conn.execute("SELECT category FROM reports WHERE slug='b'").fetchone()
            assert row[0] == "brief"
            conn.close()

            # get_db 首次调用即完成迁移（建表后跑 _migrate_schema），再迁不炸
            conn = store.get_db()
            assert store._migrate_schema(conn) is False
            row = conn.execute("SELECT category FROM reports WHERE slug='b'").fetchone()
            assert row[0] == "brief"
            conn.close()

            # 新连接再跑一轮也不炸、不覆盖
            conn = store.get_db()
            assert store._migrate_schema(conn) is False
            row = conn.execute("SELECT category FROM reports WHERE slug='b'").fetchone()
            assert row[0] == "brief"
            conn.close()
        finally:
            config.DATA_DIR = orig


def test_list_reports_filters():
    """新查询助手：默认不含 hidden，可按 category / project 过滤，created_date 倒序。"""
    with tempfile.TemporaryDirectory() as d:
        orig = config.DATA_DIR
        config.DATA_DIR = Path(d)
        try:
            conn = store.get_db()
            for i, (slug, date, cat, proj) in enumerate([
                ("r1", "2026-01-01", "research", "proj-a"),
                ("r2", "2026-06-15", "tech-solution", "proj-a"),
                ("r3", "2026-03-10", "arch-doc", "proj-b"),
                ("r4", "2026-02-01", "brief", ""),
            ], 1):
                sub_id = store.insert_submission(conn, slug, 1,
                                                 f"{date}T00:00:00+00:00", f"/fake/{slug}.json")
                conn.commit()
                store.upsert_report(conn, slug, f"{date}-{slug}.html", f"标题{slug}",
                                    created_date=date, current_rev=sub_id)
                conn.execute(
                    "UPDATE reports SET category=?, project=? WHERE slug=?",
                    (cat, proj, slug))
            conn.execute("UPDATE reports SET hidden=1 WHERE slug='r3'")
            conn.commit()

            # 默认不含 hidden
            rows = store.list_reports(conn)
            assert [r["file"] for r in rows] == [
                "2026-06-15-r2.html", "2026-02-01-r4.html", "2026-01-01-r1.html"]
            assert all(r["hidden"] is False for r in rows)

            # include_hidden=True 全量
            rows = store.list_reports(conn, include_hidden=True)
            assert len(rows) == 4

            # category 过滤
            rows = store.list_reports(conn, category="tech-solution")
            assert [r["slug"] for r in rows] == ["r2"]

            # project 过滤
            rows = store.list_reports(conn, project="proj-a")
            assert [r["slug"] for r in rows] == ["r2", "r1"]

            # 组合：category + project
            rows = store.list_reports(conn, category="research", project="proj-a")
            assert [r["slug"] for r in rows] == ["r1"]

            # 兼容旧入口仍全量
            assert len(store.list_reports_from_db(conn)) == 4
            conn.close()
        finally:
            config.DATA_DIR = orig


def test_list_projects():
    """项目空间聚合：项目名 + 篇数 + 最新日期，排除 hidden 与空 project。"""
    with tempfile.TemporaryDirectory() as d:
        orig = config.DATA_DIR
        config.DATA_DIR = Path(d)
        try:
            conn = store.get_db()
            for i, (slug, date, proj) in enumerate([
                ("p1", "2026-01-01", "proj-a"),
                ("p2", "2026-06-15", "proj-a"),
                ("p3", "2026-03-10", "proj-b"),
                ("p4", "2026-02-01", ""),   # 无项目，不算
                ("p5", "2026-05-01", "proj-c"),  # 下架，不算
            ], 1):
                sub_id = store.insert_submission(conn, slug, 1,
                                                 f"{date}T00:00:00+00:00", f"/fake/{slug}.json")
                conn.commit()
                store.upsert_report(conn, slug, f"{date}-{slug}.html", f"标题{slug}",
                                    created_date=date, current_rev=sub_id)
                conn.execute("UPDATE reports SET project=? WHERE slug=?", (proj, slug))
            conn.execute("UPDATE reports SET hidden=1 WHERE slug='p5'")
            conn.commit()

            projects = store.list_projects(conn)
            assert [p["project"] for p in projects] == ["proj-a", "proj-b"]  # 最新日期倒序
            assert projects[0]["count"] == 2 and projects[0]["latest"] == "2026-06-15"
            assert projects[1]["count"] == 1 and projects[1]["latest"] == "2026-03-10"
            conn.close()
        finally:
            config.DATA_DIR = orig


def test_set_report_hidden():
    """软下架/恢复：set_report_hidden 影响 list_reports 可见性。"""
    with tempfile.TemporaryDirectory() as d:
        orig = config.DATA_DIR
        config.DATA_DIR = Path(d)
        try:
            conn = store.get_db()
            sub_id = store.insert_submission(conn, "r1", 1,
                                             "2026-01-01T00:00:00+00:00", "/fake/r1.json")
            conn.commit()
            store.upsert_report(conn, "r1", "2026-01-01-r1.html", "标题",
                                created_date="2026-01-01", current_rev=sub_id)
            conn.commit()

            # 自开连接版本（不传 conn）
            store.set_report_hidden("r1", True)
            assert len(store.list_reports(conn)) == 0          # 下架后默认不可见
            assert len(store.list_reports(conn, include_hidden=True)) == 1

            # 显式 conn 版本（由调用方 commit）
            store.set_report_hidden("r1", False, conn=conn)
            conn.commit()
            assert len(store.list_reports(conn)) == 1          # 恢复后可见
            conn.close()
        finally:
            config.DATA_DIR = orig


def test_knowledge_items_by_source_and_status():
    """知识条目：按 sources 反查 + 状态变更。"""
    with tempfile.TemporaryDirectory() as d:
        orig = config.DATA_DIR
        config.DATA_DIR = Path(d)
        try:
            conn = store.get_db()
            store.create_knowledge_items_table(conn)
            now = "2026-08-01 00:00:00"
            conn.execute(
                "INSERT INTO knowledge_items (id, topic, domain, kind, text, sources, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                ("t1#data1", "topic-x", "tech", "data", "条目1",
                 '["2026-01-01-a.html", "2026-01-02-b.html"]', now))
            conn.execute(
                "INSERT INTO knowledge_items (id, topic, domain, kind, text, sources, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                ("t1#data2", "topic-x", "tech", "conclusion", "条目2",
                 '["2026-01-03-c.html"]', now))
            conn.execute(
                "INSERT INTO knowledge_items (id, topic, domain, kind, text, sources, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                ("t2#data1", "topic-y", "tech", "data", "条目3",
                 '["2026-01-01-a-suffix.html"]', now))  # 子串陷阱：不能误中 'a'
            conn.commit()

            # 精确匹配 sources 含该 slug 的条目
            hits = store.get_knowledge_items_by_source("2026-01-01-a.html", conn)
            assert [h["id"] for h in hits] == ["t1#data1"]
            # 子串安全：不带引号的模糊名不误中
            assert store.get_knowledge_items_by_source("a", conn) == []
            assert store.get_knowledge_items_by_source("2026-01-03-c.html", conn)[0]["id"] == "t1#data2"

            # 状态变更（自开连接版本）
            store.set_knowledge_item_status("t1#data1", "hidden")
            row = conn.execute(
                "SELECT status FROM knowledge_items WHERE id='t1#data1'").fetchone()
            assert row[0] == "hidden"
            # 未动过的条目保持默认 active
            row = conn.execute(
                "SELECT status FROM knowledge_items WHERE id='t1#data2'").fetchone()
            assert row[0] == "active"
            # 显式 conn 版本
            store.set_knowledge_item_status("t1#data1", "active", conn=conn)
            conn.commit()
            row = conn.execute(
                "SELECT status FROM knowledge_items WHERE id='t1#data1'").fetchone()
            assert row[0] == "active"
            conn.close()
        finally:
            config.DATA_DIR = orig
