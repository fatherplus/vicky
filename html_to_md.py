#!/usr/bin/env python3
"""P0 包化 shim：委托到 vicky.html_to_md。P4 阶段删除。"""
from vicky.html_to_md import html_to_md

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(html_to_md(open(sys.argv[1], encoding="utf-8").read()))
    else:
        print("用法: python3 html_to_md.py <report.html>", file=sys.stderr)
