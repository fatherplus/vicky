"""
L0 原始数据层——提交快照处理（P1：快照存档 + 图片原样保存）。
提交 → 不可变存档 data/l0/{slug}/{rev:04d}/submission.json + img/ 原件。
upsert 变追加：同 slug 再次提交生成 rev+1，修订史白送。

设计决策（依据 specs §5）：
- submission.json = 原始 payload 全文 + 信封（received_at / 来源 IP / schema 版本 / provenance）
- 图片原样保存在 l0 目录下；发布时 L1 拷到 public/assets/img/{slug}/
"""

import base64
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from . import config as _config
from . import store

# 本地引用（方便访问，测试 monkey-patch 走 _config.XXX）
IMG_EXTENSIONS = _config.IMG_EXTENSIONS
IMG_MAX_BYTES = _config.IMG_MAX_BYTES
SCHEMA_VERSION = "1.0"


# ============================================================
# slug 校验（domain 校验已随二次重构删除，全面改用 category-only）
# ============================================================
def clean_slug(slug: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")


def validate_slug_not_empty(slug: str) -> str | None:
    cleaned = clean_slug(slug)
    if not cleaned:
        return "slug 清理后为空：至少包含一个字母或数字"
    return None


def validate_series_params(series: str, order) -> tuple[int, str | None]:
    has_series = bool((series or "").strip())
    has_order = order is not None
    if has_series != has_order:
        return 0, "series 与 order 必须同时提供"
    if not has_series:
        return 0, None
    try:
        order_int = int(order)
        if order_int < 1:
            raise ValueError
    except (TypeError, ValueError):
        return 0, "order 必须是 ≥1 的整数"
    return order_int, None


# ============================================================
# L0 快照目录
# ============================================================
def _l0_dir(slug: str, rev: int) -> Path:
    """data/l0/{slug}/{rev:04d}/"""
    return _config.DATA_DIR / "l0" / slug / f"{rev:04d}"


# ============================================================
# L0 快照写入
# ============================================================
def ingest_submission(slug: str, payload: dict, client_ip: str = "127.0.0.1",
                      provenance: str = "api") -> int:
    """将提交 payload 写入不可变快照，返回 rev 号。
    - upsert 变追加：同 slug → rev 递增
    - provenance: "api"（在线提交）或 "backfill"（存量迁移）
    """
    conn = store.get_db()
    try:
        rev = store.next_rev(conn, slug)
        received_at = datetime.now(timezone.utc).isoformat()
        l0_path = _l0_dir(slug, rev)
        l0_path.mkdir(parents=True, exist_ok=True)

        # 信封 + payload 全文合为 submission.json
        envelope = {
            "received_at": received_at,
            "source_ip": client_ip,
            "schema_version": SCHEMA_VERSION,
            "provenance": provenance,
            "payload": payload,
        }
        payload_path = l0_path / "submission.json"
        payload_path.write_text(
            json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")

        # 入库 submissions 表
        store.insert_submission(conn, slug, rev, received_at, str(payload_path))
        conn.commit()
        return rev
    finally:
        conn.close()


def load_report_payload(slug: str) -> dict | None:
    """读某报告最新快照的原始 payload（含 content 与全部元数据）。
    修订 / 元数据更新 / 归项目三类操作的地基：reports 表只存元数据，
    content 唯一真相在 L0 快照 submission.json。返回 None 表示 slug 不存在。"""
    conn = store.get_db()
    try:
        rep = store.get_report_by_slug(conn, slug)
        if not rep:
            return None
        sub = store.get_submission(conn, rep["current_rev"])
        if not sub:
            return None
        with open(sub["payload_path"], encoding="utf-8") as f:
            envelope = json.load(f)
        payload = envelope.get("payload")
        if payload is None:
            return None
        # 旧快照可能缺 category/project 等字段（category 机制引入前提交），
        # 用 reports 表当前元数据补齐（content 仍以快照为准）。
        for k, fallback in (
                ("category", rep.get("category") or "research"),
                ("project", rep.get("project") or ""),
                ("narrative", rep.get("narrative") or ""),
                ("tag", rep.get("tag") or ""),
                ("subtitle", rep.get("subtitle") or ""),
                ("template", rep.get("template") or "book"),
                ("series", rep.get("series") or ""),
        ):
            payload.setdefault(k, fallback)
        return payload
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    finally:
        conn.close()


def save_l0_images(slug: str, rev: int, images: list) -> tuple[list[str], str | None]:
    """保存上传图片到 data/l0/{slug}/{rev:04d}/img/（原件保留）。
    L1 发布时从这拷到 public/assets/img/{slug}/。
    返回 (saved_rel_paths, error_or_None)。"""
    if not images:
        return [], None

    img_dir = _l0_dir(slug, rev) / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for img in images:
        name = (img.get("name") or "").strip()
        b64 = img.get("b64") or ""
        ext = os.path.splitext(name)[1].lower()
        if ext not in IMG_EXTENSIONS:
            return [], f"图片格式不支持: {ext}（允许 {sorted(IMG_EXTENSIONS)}）"
        try:
            raw = base64.b64decode(b64)
        except Exception:
            return [], f"图片 base64 解码失败: {name}"
        if len(raw) > IMG_MAX_BYTES:
            return [], f"图片过大: {name}（上限 {IMG_MAX_BYTES // 1024 // 1024}MB）"
        safe_name = os.path.basename(name)
        (img_dir / safe_name).write_bytes(raw)
        saved.append(str(img_dir / safe_name))
    return saved, None


# ============================================================
# public/assets/img 图片落盘（P0 兼容：直接从 api 参数保存到 public）
# ============================================================
def save_images(images: list, slug: str) -> tuple[list[str], str | None]:
    """保存上传图片到 public/assets/img/{slug}/（P0 行为保留）。
    依据：server.py do_POST 中图片落盘逻辑。"""
    from .config import IMG_DIR
    if not images:
        return [], None
    img_dir = IMG_DIR / slug
    img_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for img in images:
        name = (img.get("name") or "").strip()
        b64 = img.get("b64") or ""
        ext = os.path.splitext(name)[1].lower()
        if ext not in IMG_EXTENSIONS:
            return [], f"图片格式不支持: {ext}（允许 {sorted(IMG_EXTENSIONS)}）"
        try:
            raw = base64.b64decode(b64)
        except Exception:
            return [], f"图片 base64 解码失败: {name}"
        if len(raw) > IMG_MAX_BYTES:
            return [], f"图片过大: {name}（上限 {IMG_MAX_BYTES // 1024 // 1024}MB）"
        safe_name = os.path.basename(name)
        (img_dir / safe_name).write_bytes(raw)
        saved.append(f"/assets/img/{slug}/{safe_name}")
    return saved, None
