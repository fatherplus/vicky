#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""存量报告迁移：剥离模板内联 CSS → 外链共享资产（spec §6.3，可选）。

安全策略：只剥离含 BOOK-STYLE/INDEX 指纹的模板样式块；
旧报告可能保留 convert_to_book.py 注入的自定义组件样式，那些块不动。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "public" / "reports"
FINGERPRINTS = ("BOOK-STYLE", "标准组件库", "opener")  # 模板样式指纹


def migrate_file(path: Path, dry: bool) -> str:
    text = path.read_text(encoding="utf-8")
    if 'href="../assets/book-style.css"' in text:
        return "skip（已迁移）"
    blocks = list(re.finditer(r'\n?<style>(.*?)</style>', text, re.S))
    strip = [b for b in blocks if any(fp in b.group(1) for fp in FINGERPRINTS)]
    if not strip:
        return "skip（无模板样式指纹）"
    new = text
    for b in reversed(strip):                      # 从后往前删，偏移不错位
        new = new[:b.start()] + new[b.end():]
    new = new.replace(
        'display=swap" rel="stylesheet">',
        'display=swap" rel="stylesheet">\n<link rel="stylesheet" href="../assets/book-style.css">', 1)
    if not dry:
        path.write_text(new, encoding="utf-8")
    return f"migrated（剥离 {len(strip)} 个样式块）"


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    for p in sorted(REPORTS.glob("*.html")):
        print(f"  {p.name}: {migrate_file(p, dry)}")
    print("（dry-run，未写盘）" if dry else "完成")
