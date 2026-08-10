"""
CLI 命令入口——backfill / render / distill / judge。
P1：实现 backfill（存量报告 → L0 快照 + DB 注册）。
"""

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# 项目根（cli.py 在 ai_report/ 内，REPO_DIR 是父目录）
REPO_DIR = Path(__file__).resolve().parent.parent

from . import store
from . import config as _config
REPORTS_DIR = _config.REPORTS_DIR  # 测试 monkey-patch 兼容


# ============================================================
# backfill：存量 HTML → L0 快照 + reports 表
# ============================================================
def _extract_main_content(html: str) -> str:
    """从成品 HTML 反解 agent 提交的原始 content（<main> 反解）。
    依据：convert_to_book.py 验证过的反解路径 —— 从 <main> 取内容，
    去头（opener 区）去尾（colophon 脚注），中间为 agent 原始 content。"""
    m = re.search(r"<main>(.*?)</main>", html, re.S)
    if not m:
        return ""
    main = m.group(1)

    # 去掉 opener section
    main = re.sub(r"<section\s+class=\"opener\">.*?</section>", "", main, flags=re.S)

    # 去掉 volume-nav（如有）
    main = re.sub(r"<nav\s+class=\"volume-nav\"[\s\S]*?</nav>", "", main, flags=re.S)

    # 去掉 colophon 脚注
    main = re.sub(r"<footer\s+class=\"colophon\">.*?</footer>", "", main, flags=re.S)

    return main.strip()


def _extract_meta(html: str) -> dict:
    """从成品 HTML 提取元数据（tag / subtitle / series 等）。
    P1 backfill：存量报告无 <meta name="template"> 等标签，从 HTML 内容推断。"""
    meta = {"template": "book", "domain": "tech"}  # 默认值

    # tag：opener 区 <div class="kicker">
    km = re.search(r'<div\s+class="kicker">([^<]*)</div>', html)
    if km:
        meta["tag"] = km.group(1).strip()

    # subtitle：opener 区 <p class="subtitle">
    sm = re.search(r'<p\s+class="subtitle">([^<]*)</p>', html)
    if sm:
        meta["subtitle"] = sm.group(1).strip()

    # template（如有 meta 标签）
    tm = re.search(r'<meta\s+name="template"\s+content="([^"]*)"', html)
    if tm:
        meta["template"] = tm.group(1)

    # domain（如有 meta 标签）
    dm = re.search(r'<meta\s+name="domain"\s+content="([^"]*)"', html)
    if dm:
        meta["domain"] = dm.group(1)

    # series（如有 meta 标签）
    srm = re.search(r'<meta\s+name="series"\s+content="([^"]*)"', html)
    if srm:
        meta["series"] = srm.group(1)
    som = re.search(r'<meta\s+name="series-order"\s+content="(\d+)"', html)
    if som:
        meta["series_order"] = int(som.group(1))

    # updated（如有 meta 标签）
    um = re.search(r'<meta\s+name="updated"\s+content="([^"]*)"', html)
    if um:
        meta["updated"] = um.group(1)

    return meta


def backfill(force: bool = False):
    """存量 public/reports/*.html → L0 快照（rev 0001, provenance=backfill）+ reports 表。
    - 幂等：已有快照的 slug 跳过（除非 --force）
    - 不修改 public/reports/ 下任何文件（只读）"""
    html_files = sorted(REPORTS_DIR.glob("*.html"))
    if not html_files:
        print("📭 没有找到存量报告")
        return

    conn = store.get_db()
    try:
        done, skipped, failed = 0, 0, 0
        for f in html_files:
            name = f.name
            # 解析 slug 和 date
            m = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)\.html$", name)
            if not m:
                print(f"⚠️  跳过（无法解析文件名）: {name}")
                skipped += 1
                continue
            date_str, slug = m.group(1), m.group(2)

            # 幂等检查
            if not force and store.slug_has_submissions(conn, slug):
                skipped += 1
                continue

            try:
                html = f.read_text(encoding="utf-8")

                # 提取 title
                tm = re.search(r"<title>(.+?)</title>", html)
                title = tm.group(1).strip() if tm else slug

                # 提取 content（<main> 反解）
                content = _extract_main_content(html)
                if not content:
                    print(f"⚠️  {name}：<main> 内容为空，跳过")
                    skipped += 1
                    continue

                # 提取元数据
                meta = _extract_meta(html)
                tag = meta.get("tag", "研究报告")
                subtitle = meta.get("subtitle", "")
                template = meta.get("template", "book")
                domain = meta.get("domain", "tech")
                series = meta.get("series", "")
                series_order = meta.get("series_order", 0)

                # 构造 payload
                payload = {
                    "title": title, "slug": slug, "tag": tag,
                    "content": content, "subtitle": subtitle,
                    "series": series, "order": series_order,
                    "template": template, "domain": domain,
                }

                # 写 L0 快照（rev 0001）
                rev = 1
                l0_path = _config.DATA_DIR / "l0" / slug / "0001"
                l0_path.mkdir(parents=True, exist_ok=True)
                received_at = f"{date_str}T00:00:00+00:00"  # 用原报告日期
                envelope = {
                    "received_at": received_at,
                    "source_ip": "backfill",
                    "schema_version": "1.0",
                    "provenance": "backfill",
                    "payload": payload,
                }
                (l0_path / "submission.json").write_text(
                    json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")

                # 入库 submissions 表
                sub_id = store.insert_submission(
                    conn, slug, rev, received_at, str(l0_path / "submission.json"))

                # 入库 reports 表
                updated_date = meta.get("updated", "")
                store.upsert_report(
                    conn, slug, name, title, tag, subtitle, domain,
                    template, series, series_order, date_str, updated_date, sub_id)

                done += 1
                print(f"  ✓ {name} → {slug} rev=0001")

            except Exception as e:
                print(f"  ✗ {name}：{e}")
                failed += 1

        conn.commit()
        print(f"\n📊 backfill 完成：{done} 篇入库，{skipped} 篇跳过，{failed} 篇失败")
    finally:
        conn.close()


# ============================================================
# 入口
# ============================================================
def main():
    if len(sys.argv) < 2:
        print("用法: python3 -m ai_report.cli <命令>")
        print("命令: backfill [--force] | render | distill | judge")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "backfill":
        force = "--force" in sys.argv
        backfill(force=force)
    elif cmd == "render":
        print("render 命令将在 P3 实现")
    elif cmd == "distill":
        print("distill 命令将在 P2 实现")
    elif cmd == "judge":
        print("judge 命令将在 P2 实现")
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
