#!/usr/bin/env python3
"""P0 包化 shim：委托到 vicky.l2_distill。P4 阶段删除。"""
from vicky.l2_distill import distill

if __name__ == "__main__":
    distill()
