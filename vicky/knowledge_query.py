"""P4：knowledge_query 检索管线——知识 Wiki 的读线（READ path）。
2026-08-12 重构：原 MCP 工具内核，现经 GET /api/knowledge?q= 暴露。

三阶段管线：
  Stage 1 Recall   store.search_items(q, limit=50, category, tag)（FTS5 trigram）
  Stage 2 Scoring  BM25 基分 × kind 加权（结论×1.5 / 陷阱×1.2 / 数据×1.0）
                    → 同主题同 kind 相似文本去重 → 截断 ≤30 条
  Stage 3 Packing  token 估算（中文字符×1.2 + 英文/数字词×0.7）贪婪装包，
                   预算默认 2000，硬顶 6000

q 为空 → 目录模式：按专栏 category 列出全部主题 + 条目计数（store.knowledge_catalog）。

纯 stdlib，无第三方依赖。错误策略：库空/无命中返回空 items + note（不抛错）；
参数类型非法由本模块容错归一（str()/int() + 默认值），永不抛错。

依赖方向：knowledge_query → store（只读），不反向。
"""

import re
from difflib import SequenceMatcher

from . import store

DEFAULT_BUDGET = 2000   # 预算默认（token）
MAX_BUDGET = 6000       # 预算硬顶（绝对上限）
MAX_ITEMS = 30          # 打分后保留的最大条目数
RECALL_LIMIT = 50       # Stage 1 召回上限（打分前）
MAX_QUERY_LEN = 200     # 查询词超长截断

# kind 加权（Stage 2）：结论最贵、陷阱次之、数据保底；未知 kind 按 1.0
KIND_MULTIPLIER = {
    "conclusion": 1.5,
    "trap": 1.2,
    "data": 1.0,
    "refuted": 1.0,
}

# 去重相似度阈值（同主题同 kind 下归一文本的 SequenceMatcher 比率）
DEDUP_RATIO = 0.9

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


# ============================================================
# Stage 2/3 辅助
# ============================================================
def estimate_tokens(text: str) -> float:
    """粗略 token 估算：中文字符数×1.2 + 英文/数字词数×0.7（启发式，够装包用）。"""
    cn = len(_CJK_RE.findall(text))
    words = len(_WORD_RE.findall(text))
    return cn * 1.2 + words * 0.7


def _norm(text: str) -> str:
    """去重用的归一化：去全部空白 + 小写（中文无大小写概念）。"""
    return re.sub(r"\s+", "", text).lower()


def _base_score(rank: float) -> float:
    """bm25 越小越相关（命中为负数）→ 取负转正，越大越好；
    LIKE 兜底 rank=0.0 时给中性基分 0.0。"""
    return -rank if rank else 0.0


def _clamp_budget(raw) -> int:
    """预算归一：非法/非正 → 默认 2000；超过 6000 → 6000。"""
    try:
        b = int(raw)
    except (TypeError, ValueError):
        b = DEFAULT_BUDGET
    if b <= 0:
        b = DEFAULT_BUDGET
    return min(b, MAX_BUDGET)


def _score_items(hits: list) -> list[dict]:
    """Stage 2：打分（rank×kind 加权）→ 排序 → 去重（同 topic+kind+相似文本保高分）→ 截断。"""
    scored = []
    for item_id, topic, text, kind, rank in hits:
        base = _base_score(rank)
        mult = KIND_MULTIPLIER.get(kind, 1.0)
        scored.append({"id": item_id, "topic": topic, "text": text, "kind": kind,
                       "score": base * mult})
    scored.sort(key=lambda x: x["score"], reverse=True)
    deduped, seen = [], []
    for s in scored:
        dup = False
        s_norm = _norm(s["text"])
        for ex in seen:
            if ex["topic"] != s["topic"] or ex["kind"] != s["kind"]:
                continue
            ex_norm = _norm(ex["text"])
            if ex_norm == s_norm or \
               SequenceMatcher(None, ex_norm, s_norm).ratio() >= DEDUP_RATIO:
                dup = True
                break
        if not dup:
            seen.append(s)
            deduped.append(s)
    return deduped[:MAX_ITEMS]


def _pack(items: list[dict], budget: int) -> tuple[list, float]:
    """Stage 3：贪婪装包——按打分序逐个加，预算超了即止（严格不超）。"""
    used, packed = 0.0, []
    for it in items:
        t = estimate_tokens(it["text"])
        if used + t > budget:
            continue
        packed.append(it)
        used += t
    return packed, used


def _stats(total: int, returned: int, used: float, budget: int) -> dict:
    return {"total": total, "returned": returned, "truncated": total - returned,
            "budget_used": round(used, 1), "budget_total": budget}


# ============================================================
# 引文：sources（items.json）→ url（报告 .md / 知识页锚点）
# ============================================================
def _item_url(conn, item_id: str, sources: list) -> str:
    """条目 url：优先首条可解析来源的报告 .md 链接；解析不出 → 知识页锚点。
    source 是报告 slug（reports 表有登记 → 带日期前缀的真实文件名；无 → 按源名兜底）。"""
    for src in sources:
        src = (src or "").strip()
        if not src or src.startswith("feedback#"):
            continue
        row = store.get_report_by_slug(conn, src)
        if row and row.get("file"):
            f = row["file"]
            md = f[:-5] + ".md" if f.endswith(".html") else f
            return f"../reports/{md}"
    if sources:
        s = (sources[0] or "").strip()
        if s and not s.startswith("feedback#"):
            return f"../reports/{s}.md"
    return f"../knowledge#{item_id}"


def _catalog() -> dict:
    """目录模式：全部主题按专栏 category 列出 + 计数。"""
    data = store.knowledge_catalog()
    return {"catalog": data["catalog"],
            "stats": {"total_topics": data["total_topics"],
                      "total_items": data["total_items"]}}


# ============================================================
# 工具入口
# ============================================================
def query(params: dict | None = None) -> dict:
    """knowledge_query 主入口。q 空 → 目录；否则三阶段检索。永不抛错（容错归一）。"""
    params = params or {}
    q = str(params.get("q") or "").strip()
    if len(q) > MAX_QUERY_LEN:
        q = q[:MAX_QUERY_LEN]
    budget = _clamp_budget(params.get("budget"))
    category = str(params.get("category") or "").strip() or None
    tag = str(params.get("tag") or "").strip() or None

    if not q:
        return _catalog()

    # Stage 1: Recall（category/tag 过滤由 store.search_items 原生支持）
    hits = store.search_items(q, limit=RECALL_LIMIT, category=category, tag=tag)
    if not hits:
        if store.count_knowledge_items() == 0:
            return {"items": [], "stats": _stats(0, 0, 0.0, budget),
                    "note": "知识库为空——尚未蒸馏出任何条目，先跑蒸馏再查询。"}
        return {"items": [], "stats": _stats(0, 0, 0.0, budget),
                "note": f"未找到与「{q}」匹配的知识条目。"}

    # Stage 2: Scoring + 去重 + 截断
    scored = _score_items(hits)

    # Stage 3: Budget packing
    packed, used = _pack(scored, budget)

    # 引文组装：sources 从 DB（items.json 的孪生列）取，url 解析到报告 .md
    conn = store.get_db()
    try:
        src_map = store.item_sources(conn, [s["id"] for s in packed])
        items = [{
            "id": s["id"], "text": s["text"], "kind": s["kind"], "topic": s["topic"],
            "sources": src_map.get(s["id"], []),
            "url": _item_url(conn, s["id"], src_map.get(s["id"], [])),
        } for s in packed]
    finally:
        conn.close()

    return {"items": items, "stats": _stats(len(scored), len(items), used, budget)}
