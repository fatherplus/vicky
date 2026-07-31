#!/usr/bin/env python3
"""为存量报告补生成 .md 兄弟文件（新报告由 server.py 提交时自动生成）。

用法: python3 scripts/backfill_md.py [--force]
  默认只补缺失的 .md；--force 重生成全部。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from html_to_md import html_to_md

REPORTS_DIR = Path(__file__).resolve().parent.parent / "public" / "reports"
FORCE = "--force" in sys.argv


def main():
    made = skipped = 0
    for html_file in sorted(REPORTS_DIR.glob("*.html")):
        md_file = html_file.with_suffix(".md")
        if md_file.exists() and not FORCE:
            skipped += 1
            continue
        md_file.write_text(html_to_md(html_file.read_text(encoding="utf-8")), encoding="utf-8")
        made += 1
    print(f"生成 {made} 个 .md，跳过 {skipped} 个已存在")


if __name__ == "__main__":
    main()
