"""P1 测试：store 层建表 / CRUD / 幂等。"""
import sqlite3
import tempfile
from pathlib import Path

from ai_report import store, config


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
