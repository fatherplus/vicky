#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""存量报告迁移：剥离模板内联 CSS → 外链共享资产（spec §6.3，可选）。

安全策略（宁可漏剥不误剥）：
- 只剥离含 BOOK-STYLE 指纹的模板样式块（模板主样式块与 View Transitions 块）；
- 候选块含「原报告组件样式」标记 → 整篇 skip（convert_to_book.py 合并块，需人工处理）；
- 某块含旧松散指纹（标准组件库/opener）却不含 BOOK-STYLE → 整篇 skip
  （疑似自定义块与模板类名撞车，需人工核实；松散指纹绝不触发剥离）；
- 字体 link 注入锚点缺失 → 整篇 skip，杜绝剥光却没注入外链。
旧报告的自定义组件样式块一律不动。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "public" / "reports"
TEMPLATE_FP = "BOOK-STYLE"             # 模板块唯一指纹
MERGED_MARK = "原报告组件样式"           # convert_to_book.py 自定义 CSS 保留标记
LOOSE_FPS = ("标准组件库", "opener")     # 仅作撞车嫌疑判据，不触发剥离
ANCHOR = 'display=swap" rel="stylesheet">'


def migrate_file(path: Path, dry: bool) -> str:
    text = path.read_text(encoding="utf-8")
    if 'href="../assets/book-style.css"' in text:
        return "skip（已迁移）"
    blocks = list(re.finditer(r'\n?<style>(.*?)</style>', text, re.S))
    strip = [b for b in blocks if TEMPLATE_FP in b.group(1)]
    if not strip:
        return "skip（无模板样式指纹）"
    if any(MERGED_MARK in b.group(1) for b in strip):
        return "skip（合并块含自定义组件样式，需人工处理）"
    if any(TEMPLATE_FP not in b.group(1) and any(fp in b.group(1) for fp in LOOSE_FPS)
           for b in blocks):
        return "skip（自定义块疑似与模板类名撞车，需人工核实）"
    if ANCHOR not in text:
        return "skip（无注入锚点）"
    new = text
    for b in reversed(strip):                      # 从后往前删，偏移不错位
        new = new[:b.start()] + new[b.end():]
    new = new.replace(
        ANCHOR,
        ANCHOR + '\n<link rel="stylesheet" href="../assets/book-style.css">', 1)
    if not dry:
        path.write_text(new, encoding="utf-8")
    return f"migrated（剥离 {len(strip)} 个样式块）"


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    for p in sorted(REPORTS.glob("*.html")):
        print(f"  {p.name}: {migrate_file(p, dry)}")
    print("（dry-run，未写盘）" if dry else "完成")
