"""
L0 存储层——sqlite3 唯一 DB 出口。
P0 占位：仅提供连接封装骨架。P1 阶段实现建表与查询。
"""

import sqlite3
from pathlib import Path

from .config import REPO_DIR

DB_PATH = REPO_DIR / "data" / "ai-report.db"


def get_db() -> sqlite3.Connection | None:
    """返回 sqlite3 连接。P0 返回 None（存储尚未启用）。
    P1 阶段改为返回 WAL 模式连接。"""
    # P1: DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # P1: conn = sqlite3.connect(str(DB_PATH)); conn.execute("PRAGMA journal_mode=WAL"); return conn
    return None
