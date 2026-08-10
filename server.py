#!/usr/bin/env python3
"""P0 包化 shim：委托到 ai_report.web。P4 阶段删除。"""
from ai_report.web import main

if __name__ == "__main__":
    main()
