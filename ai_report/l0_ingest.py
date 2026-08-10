"""
L0 原始数据层——提交快照处理（P0：helper 函数集）。
P0 包化：从 server.py do_POST 提取 slug 清理/图片落盘/丛书参数校验。
行为零变化——仅代码搬迁，不改逻辑。
"""

import base64
import os
import re

from .config import IMG_DIR, IMG_EXTENSIONS, IMG_MAX_BYTES, DOMAINS


def clean_slug(slug: str) -> str:
    """清理 slug：去除非字母数字连字符，全小写，去首尾连字符。
    依据：server.py do_POST 中 slug 清理逻辑。"""
    return re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")


def validate_slug_not_empty(slug: str) -> str | None:
    """返回错误文案如果清理后 slug 为空，否则 None。"""
    cleaned = clean_slug(slug)
    if not cleaned:
        return "slug 清理后为空：至少包含一个字母或数字"
    return None


def validate_domain(domain: str) -> str | None:
    """返回错误文案如果 domain 不在合法集合。"""
    domain = (domain or "tech").strip()
    if domain not in DOMAINS:
        return f"domain 必须是 {sorted(DOMAINS)} 之一"
    return None


def save_images(images: list, slug: str) -> tuple[list[str], str | None]:
    """保存上传图片到 public/assets/img/{slug}/。
    返回 (saved_paths, error_or_None)。
    依据：server.py do_POST 中图片落盘逻辑（base64 只在传输瞬间存在，HTML 只留链接）。"""
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
        safe_name = os.path.basename(name)  # 防路径穿越
        (img_dir / safe_name).write_bytes(raw)
        saved.append(f"/research/assets/img/{slug}/{safe_name}")
    return saved, None


def validate_series_params(series: str, order) -> tuple[int, str | None]:
    """校验丛书参数。返回 (order_int, error_or_None)。
    series 与 order 必须同时提供；order 必须是 ≥1 的整数。"""
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
