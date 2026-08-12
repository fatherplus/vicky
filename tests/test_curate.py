#!/usr/bin/env python3
"""审核治理（重构蓝图 2026-08-12 §04）测试：curate 软下架/硬删除/条目状态 +
L2 蒸馏跳过 hidden + CLI hide/restore/delete/audit 子命令 + 重建索引保状态。
安全红线：全部 tmp 目录隔离（tmp_env + 额外 patch l2 KNOWLEDGE_DIR/REPORTS_DIR/PUBLIC_DIR、
config KNOWLEDGE_DIR/IMG_DIR），不碰真实 knowledge/、public/、data/。"""
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from vicky import store, config, curate, cli
from vicky import l2_distill as l2

from tests.util import load_server, tmp_env

server = load_server()


# ============================================================
# 环境助手
# ============================================================
def _make_report(tmp, title: str, slug: str) -> dict:
    """create_report 建一篇 tech 报告（blockquote → md `> …` → 规则蒸馏 conclusion）。"""
    content = ('<section><div class="wrap">'
               f'<blockquote>核心结论：{title}的机制要点</blockquote>'
               '</div></section>')
    r = server.create_report(title, slug, "研究报告", content)
    assert r["ok"]
    return r


@contextmanager
def _env(tmp: Path):
    """distill + curate + store 全链路路径 patch。
    tmp_env 已 patch DATA_DIR/REPORTS_DIR/INDEX_PATH/VIEWS_DIR/TEMPLATES_DIR；
    这里补 l2 模块级绑定（KNOWLEDGE_DIR/LOG_PATH/INDEX_PATH/PUBLIC_DIR/REPORTS_DIR）
    与 config 的 KNOWLEDGE_DIR/IMG_DIR。"""
    with patch.multiple("vicky.l2_distill",
                        REPO_DIR=tmp,
                        REPORTS_DIR=tmp / "reports",
                        KNOWLEDGE_DIR=tmp / "knowledge",
                        LOG_PATH=tmp / "knowledge" / "log.md",
                        INDEX_PATH=tmp / "knowledge" / "index.md",
                        PUBLIC_DIR=tmp,
                        DRY_RUN=False), \
         patch.multiple("vicky.config",
                        KNOWLEDGE_DIR=tmp / "knowledge",
                        IMG_DIR=tmp / "assets" / "img"):
        yield tmp


def _distill_and_index():
    """规则路径蒸馏（无 LLM key）+ 知识条目入库（items.json → knowledge_items + FTS）。
    必须在 _env 上下文内调用。"""
    l2.distill()
    cli.index_knowledge()


def _item_texts():
    """当前库中全部知识条目的 (id, text)。"""
    return [(it["id"], it["text"]) for it in store.list_knowledge_items()]


# ============================================================
# 1. 软下架 / 恢复往返
# ============================================================
def test_hide_restore_roundtrip():
    with tmp_env(server) as tmp, _env(tmp):
        _make_report(tmp, "隐藏往返", "hide-roundtrip")
        _distill_and_index()
        items = store.list_knowledge_items()
        assert len(items) == 1
        iid = items[0]["id"]
        # 规则蒸馏路径 sources 记的是报告文件名（含日期前缀）
        srcs = json.loads(items[0]["sources"])
        assert any(s.endswith("hide-roundtrip.html") for s in srcs)

        # ── 软下架 ──
        r = curate.hide_report("hide-roundtrip", True)
        assert r == {"ok": True, "slug": "hide-roundtrip",
                     "hidden": True, "items_affected": 1}
        # 报告从文库消失（store.list_reports 默认不含 hidden；旧入口 list_reports_from_db 含，兼容不动）
        assert all(x["slug"] != "hide-roundtrip" for x in store.list_reports())
        # 知识条目同步 hidden，仍在库里（可恢复），FTS 查不到
        conn = store.get_db()
        try:
            it = store.get_knowledge_item(conn, iid)
        finally:
            conn.close()
        assert it["status"] == "hidden"
        assert store.search_items("核心结论") == []
        audit = curate.knowledge_audit()
        assert len(audit) == 1 and audit[0]["status"] == "hidden" and audit[0]["id"] == iid
        assert audit[0]["topic"] == "hide-roundtrip"

        # ── 恢复 ──
        r2 = curate.hide_report("hide-roundtrip", False)
        assert r2["hidden"] is False and r2["items_affected"] == 1
        assert any(x["slug"] == "hide-roundtrip" for x in store.list_reports())
        hits = store.search_items("核心结论")
        assert len(hits) == 1 and hits[0][0] == iid
        assert curate.knowledge_audit()[0]["status"] == "active"


def test_hide_report_missing_slug():
    with tmp_env(server) as tmp, _env(tmp):
        r = curate.hide_report("不存在-slug", True)
        assert r["ok"] is False and "不在 reports 表" in r["error"]


# ============================================================
# 2. 硬删除级联（文件 / DB 行 / L0 / 图片 / 知识条目 + FTS 全清）
# ============================================================
def test_hard_delete_cascade_clean():
    with tmp_env(server) as tmp, _env(tmp):
        r = _make_report(tmp, "级联删除", "nuke-me")
        file = r["file"]
        md_file = file[:-5] + ".md"
        _distill_and_index()
        # 造图片目录 + 确认 L0 快照目录存在
        img_dir = tmp / "assets" / "img" / "nuke-me"
        img_dir.mkdir(parents=True)
        (img_dir / "shot.png").write_text("fake", encoding="utf-8")
        l0_dir = tmp / "data" / "l0" / "nuke-me"
        assert l0_dir.exists()

        # ── 预检清单（不删）──
        m = curate.preview_delete("nuke-me")
        assert m["report"]["file"] == file
        assert m["submissions"] == 1
        assert len(m["knowledge_items"]) == 1

        # ── 执行删除 ──
        res = curate.hard_delete_report("nuke-me")
        assert res["ok"]
        d = res["deleted"]
        assert sorted(d["report_files"]) == sorted([file, md_file])
        assert d["img_dir"] and d["l0_dir"]
        assert d["submissions"] == 1
        assert len(d["knowledge_items"]) == 1

        # 文件全清
        assert not (tmp / "reports" / file).exists()
        assert not (tmp / "reports" / md_file).exists()
        assert not l0_dir.exists()
        assert not img_dir.exists()
        # DB 行全清
        conn = store.get_db()
        try:
            assert store.get_report_by_slug(conn, "nuke-me") is None
            assert store.count_submissions(conn, "nuke-me") == 0
            ki = conn.execute("SELECT COUNT(*) FROM knowledge_items").fetchone()[0]
            fts = conn.execute("SELECT COUNT(*) FROM knowledge_items_fts").fetchone()[0]
        finally:
            conn.close()
        assert ki == 0 and fts == 0
        assert store.search_items("核心结论") == []
        # 索引页不再含该报告
        assert "nuke-me" not in (tmp / "index.html").read_text(encoding="utf-8")
        # 重复删除报错
        assert curate.hard_delete_report("nuke-me")["ok"] is False
        # 不存在的 slug 报错
        assert curate.hard_delete_report("从不存在")["ok"] is False


# ============================================================
# 3. 知识条目状态切换（FTS 可见性同步）
# ============================================================
def test_set_item_status_switch():
    with tmp_env(server) as tmp, _env(tmp):
        _make_report(tmp, "条目切换", "item-switch")
        _distill_and_index()
        items = store.list_knowledge_items()
        assert len(items) == 1
        iid = items[0]["id"]
        assert items[0]["status"] == "active"

        # 非法 status / 不存在的 id → 错误
        assert curate.set_item_status(iid, "bogus")["ok"] is False
        assert curate.set_item_status("nope#c1", "hidden")["ok"] is False

        # 隐藏：FTS 查不到，但表里仍在（可恢复），审核视图可见
        r = curate.set_item_status(iid, "hidden")
        assert r["ok"] and r["status"] == "hidden" and r["id"] == iid
        assert store.search_items("核心结论") == []
        assert store.list_knowledge_items()[0]["status"] == "hidden"
        assert curate.knowledge_audit()[0]["status"] == "hidden"

        # 恢复：FTS 重新可见
        curate.set_item_status(iid, "active")
        hits = store.search_items("核心结论")
        assert len(hits) == 1 and hits[0][0] == iid


def test_rebuild_index_preserves_hidden_status():
    """index-knowledge 重建不吞掉人工下架：hidden 保留且不进 FTS。"""
    with tmp_env(server) as tmp, _env(tmp):
        _make_report(tmp, "重建保状态", "rebuild-keep")
        _distill_and_index()
        iid = store.list_knowledge_items()[0]["id"]
        curate.set_item_status(iid, "hidden")
        cli.index_knowledge()  # 重建索引
        assert store.list_knowledge_items()[0]["status"] == "hidden"
        assert store.search_items("核心结论") == []


def test_knowledge_audit_topic_filter():
    with tmp_env(server) as tmp, _env(tmp):
        _make_report(tmp, "主题甲", "audit-a")
        _make_report(tmp, "主题乙", "audit-b")
        _distill_and_index()
        assert len(curate.knowledge_audit()) == 2
        assert [x["topic"] for x in curate.knowledge_audit(topic="audit-a")] == ["audit-a"]
        assert curate.knowledge_audit(topic="不存在主题") == []


# ============================================================
# 4. 蒸馏跳过 hidden（L2 适配）
# ============================================================
def test_distill_skips_hidden():
    with tmp_env(server) as tmp, _env(tmp):
        _make_report(tmp, "可见报告", "visible-slug")
        l2.distill()
        # 新报告先下架，再蒸馏 → 不参与蒸馏
        _make_report(tmp, "待下架报告", "hidden-slug")
        curate.hide_report("hidden-slug", True)
        l2.distill()
        topics = sorted(p.name for p in (tmp / "knowledge" / "tech").iterdir()
                        if p.is_dir())
        assert topics == ["visible-slug"]
        # scan_reports 直接不含 hidden
        slugs = [r["slug"] for r in l2.scan_reports()]
        assert "visible-slug" in slugs and "hidden-slug" not in slugs


# ============================================================
# 5. CLI 子命令
# ============================================================
def test_cli_curate_commands_registered():
    """hide / restore / delete / audit 已注册：main 派发分支 + 函数存在。"""
    src = Path(cli.__file__).read_text(encoding="utf-8")
    for branch in ('cmd == "hide"', 'cmd == "restore"', 'cmd == "delete"', 'cmd == "audit"'):
        assert branch in src
    for fn in ("def hide(", "def restore(", "def delete(", "def audit("):
        assert fn in src


def test_cli_hide_restore():
    with tmp_env(server) as tmp, _env(tmp):
        _make_report(tmp, "CLI 隐藏", "cli-hide")
        cli.hide("cli-hide")
        conn = store.get_db()
        try:
            assert store.get_report_by_slug(conn, "cli-hide")["hidden"] == 1
        finally:
            conn.close()
        cli.restore("cli-hide")
        conn = store.get_db()
        try:
            assert store.get_report_by_slug(conn, "cli-hide")["hidden"] == 0
        finally:
            conn.close()


def test_cli_delete_without_yes_requires_confirmation():
    with tmp_env(server) as tmp, _env(tmp):
        _make_report(tmp, "CLI 删除", "cli-nuke")
        # 输入非 yes → 取消，不删
        with patch("builtins.input", return_value="no"):
            cli.delete("cli-nuke", yes=False)
        assert curate.preview_delete("cli-nuke")["report"] is not None
        # 输入 yes → 删
        with patch("builtins.input", return_value="yes"):
            cli.delete("cli-nuke", yes=False)
        assert curate.preview_delete("cli-nuke")["report"] is None


def test_cli_delete_yes_direct():
    with tmp_env(server) as tmp, _env(tmp):
        _make_report(tmp, "CLI 直删", "cli-nuke-yes")
        cli.delete("cli-nuke-yes", yes=True)
        assert curate.preview_delete("cli-nuke-yes")["report"] is None


def test_cli_audit():
    with tmp_env(server) as tmp, _env(tmp):
        _make_report(tmp, "审计视图", "audit-me")
        _distill_and_index()
        cli.audit()  # 打印表格不炸
        cli.audit(topic="audit-me")
        cli.audit(topic="不存在主题")  # 空视图提示


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("ALL PASS")
