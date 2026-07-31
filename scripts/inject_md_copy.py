#!/usr/bin/env python3
"""给存量报告注入「复制 MD 链接」悬浮球（md-copy.js）。

新报告由模板自动带 <script src="../assets/md-copy.js">；
存量报告用本脚本在 </body> 前补一行。幂等：已注入的跳过。

用法: python3 scripts/inject_md_copy.py [--dry-run]
"""
import sys
from pathlib import Path

REPORTS_DIR = Path(__file__).resolve().parent.parent / "public" / "reports"
TAG = '<script src="../assets/md-copy.js" defer></script>'
DRY = "--dry-run" in sys.argv


def main():
    injected = skipped = 0
    for f in sorted(REPORTS_DIR.glob("*.html")):
        html = f.read_text(encoding="utf-8")
        if "md-copy.js" in html:
            skipped += 1
            continue
        if "</body>" not in html:
            print(f"  ! 无 </body>，跳过: {f.name}")
            continue
        if DRY:
            print(f"  + 将注入: {f.name}")
            injected += 1
            continue
        f.write_text(html.replace("</body>", TAG + "\n</body>", 1), encoding="utf-8")
        injected += 1
    verb = "将注入" if DRY else "已注入"
    print(f"{verb} {injected} 篇，跳过 {skipped} 篇已注入")


if __name__ == "__main__":
    main()
