#!/usr/bin/env python3
"""
蒸馏器 — 从 HTML 报告中提取结构化知识，维护 knowledge/ Wiki。
L2 知识层（P0 包化：从 distill.py 搬迁，行为零变化）。

用法: python3 -m vicky.cli distill [--dry-run]

流程（对应治理链路 关2-3）：
  1. 扫描 public/reports/*.html，对比 log.md 已处理列表
  2. 只蒸 category==research 的报告（brief / tech-solution 跳过）
  3. 提取知识条目（结论/被否假设/陷阱/数据），每条标来源
  4. AGREE 追加到 knowledge/{topic}/overview.md（B 阶段：目录扁平，不再按 domain 分层）
  5. 更新 index.md、追加 log.md

# ponytail: 阶段2 提取器是规则存根版，证明管线跑通；阶段3 换 LLM prompt
# ponytail: 阶段2 只做 AGREE 追加，DISAGREE/SYNTHESIZE 留阶段4
"""

import re
import sys
import os
import json
import urllib.request
import urllib.error
import shutil
import html as html_mod
import html  # build_knowledge_page 用 html.escape
from pathlib import Path
from datetime import datetime, timedelta

from . import config
from . import store  # P2: adopted 反馈直查 feedbacks 表（不 import l3_feedback，防环，规格 §3）
from . import ui  # P3 前端抢救：HTML 片段归拢 ui.py

REPO_DIR = config.REPO_DIR
REPORTS_DIR = config.REPORTS_DIR
KNOWLEDGE_DIR = config.KNOWLEDGE_DIR
PUBLIC_DIR = config.PUBLIC_DIR
LOG_PATH = KNOWLEDGE_DIR / "log.md"
INDEX_PATH = KNOWLEDGE_DIR / "index.md"

DRY_RUN = "--dry-run" in sys.argv
CLEAN = "--clean" in sys.argv  # 显式清空 knowledge 重建（部署/换模型时用；日常增量不删，防网关抖动丢内容）

# LLM 编译配置（C 方案）：无 key 时 distill 退回纯规则路径，不破坏现有流程
AIMETER_KEY = os.environ.get("AIMETER_KEY", "").strip()
AIMETER_BASE = os.environ.get("AIMETER_BASE", "https://aimeter.xk-devops.com/v1").strip().rstrip("/")
DISTILL_MODEL = os.environ.get("DISTILL_MODEL", "glm-5.2-fast").strip()  # 非思考链、JSON 遵从好、整跑稳；deepseek-v4-flash 思考链易吃空 content
LLM_ON = bool(AIMETER_KEY)
STALE_DAYS = 90  # 编译知识的默认保鲜期（过期视图标红提示重验）；按 type/domain 分化时改这里

# 知识库专栏枚举（spec 2026-08-10-knowledge-taxonomy-design §1）——蒸馏时每主题必归其一
CATEGORIES = config.CATEGORIES
CATEGORY_KEYS = tuple(CATEGORIES.keys())


# ============================================================
# HTML → 结构化知识提取（规则存根版）
# ============================================================

def _strip_tags(html_str: str) -> str:
    """剥掉所有 HTML 标签，返回纯文本（用于日志/显示）"""
    text = re.sub(r"<script[\s\S]*?</script>", "", html_str)
    text = re.sub(r"<style[\s\S]*?</style>", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_blockquotes(content: str) -> list[str]:
    """<blockquote> → 结论性声明"""
    return [t for t in (_strip_tags(m) for m in re.findall(r"<blockquote>([\s\S]*?)</blockquote>", content)) if t]


def _extract_callouts(content: str, kind: str) -> list[str]:
    """<div class="callout {kind}"> → 陷阱(warn) / 提醒(note)"""
    pattern = rf'<div class="callout {kind}">([\s\S]*?)</div>'
    results = []
    for m in re.findall(pattern, content):
        text = _strip_tags(m)
        if text:
            results.append(text)
    return results


def _extract_data_tables(content: str) -> list[str]:
    """<table class="data-table"> → 关键数据点（取 caption + 首行数据）"""
    results = []
    for m in re.findall(r'<table class="data-table">([\s\S]*?)</table>', content):
        cap = re.search(r"<caption>([\s\S]*?)</caption>", m)
        caption = _strip_tags(cap.group(1)) if cap else "数据表"
        # 取 tbody 第一行作为数据摘要
        rows = re.findall(r"<tr>([\s\S]*?)</tr>", m)
        first_data = ""
        for row in rows:
            cells = re.findall(r"<t[dh]>([\s\S]*?)</t[dh]>", row)
            if cells and not re.search(r"<th", row):
                first_data = " | ".join(_strip_tags(c) for c in cells)
                break
        results.append(f"{caption}: {first_data}" if first_data else caption)
    return results


def _extract_refuted(content: str) -> list[str]:
    """被否假设：callout warn 中带 ~~删除线~~ 的条目，或 blockquote 中带「不」「别」「禁止」的"""
    results = []
    # 删除线标记
    for m in re.findall(r"~~([^~]+)~~", content):
        results.append(html_mod.unescape(m).strip())
    return results


def extract_tech(html_content: str, source: str) -> list[dict]:
    """从 HTML 报告提取技术知识条目（规则存根版）。

    返回 [{"kind": "conclusion|refuted|trap|data", "text": str, "source": str}]
    """
    items = []
    for text in _extract_blockquotes(html_content):
        items.append({"kind": "conclusion", "text": text, "source": source})
    for text in _extract_refuted(html_content):
        items.append({"kind": "refuted", "text": text, "source": source})
    for text in _extract_callouts(html_content, "warn"):
        items.append({"kind": "trap", "text": text, "source": source})
    for text in _extract_data_tables(html_content):
        items.append({"kind": "data", "text": text, "source": source})
    return items


def extract_tech_md(md_content: str, source: str) -> list[dict]:
    """P2：从 .md 孪生报告提取技术知识条目（extract_tech 的 md 对应版）。
    html_to_md 的映射：blockquote → `> …`；callout warn → `> ⚠️ …`；callout note → `> 📝 …`。
    note 类 HTML 版本就不抽（只抽 warn），这里保持一致跳过 📝。"""
    items = []
    for text in _md_blockquotes(md_content):
        if text.startswith("⚠️"):
            items.append({"kind": "trap", "text": text.lstrip("⚠️").strip(), "source": source})
        elif text.startswith("📝"):
            continue  # callout note：与 HTML 版一致，不进骨架
        else:
            items.append({"kind": "conclusion", "text": text, "source": source})
    for m in re.findall(r"~~([^~\n]+)~~", md_content):
        items.append({"kind": "refuted", "text": m.strip(), "source": source})
    for text in _md_tables(md_content):
        items.append({"kind": "data", "text": text, "source": source})
    return items


def _md_blockquotes(md_content: str) -> list[str]:
    """连续 `> ` 行合成一个引用块，返回去前缀文本列表。"""
    out, buf = [], []
    for ln in md_content.splitlines():
        if ln.startswith(">"):
            buf.append(ln.lstrip(">").strip())
        else:
            if buf:
                out.append(" ".join(x for x in buf if x).strip())
                buf = []
    if buf:
        out.append(" ".join(x for x in buf if x).strip())
    return [t for t in out if t]


def _md_tables(md_content: str) -> list[str]:
    """md 表格 → 关键数据点（对齐 HTML 版：取首行数据）。md 无 caption，用「数据表」。"""
    results = []
    lines = md_content.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append(lines[i].strip())
                i += 1
            data_rows = [b for b in block if not re.fullmatch(r"\|(\s*:?-+:?\s*\|)+", b)]
            # data_rows[0] 是表头，[1] 才是首行数据
            if len(data_rows) >= 2:
                cells = [c.strip() for c in data_rows[1].strip("|").split("|")]
                results.append("数据表: " + " | ".join(c.replace("\\|", "|") for c in cells))
        else:
            i += 1
    return results


# B 阶段重构：蒸馏只进 research 分类（brief/tech-solution 不进知识库）
# 统一走 extract_tech_md 一个提取器（不再按 domain 分发）
_DISTILL_CATEGORY = "research"


# ============================================================
# LLM 编译层（C 方案）——规则抽骨架，LLM 只做归类/综合/矛盾
# 无 key 时本层不被调用，distill 退回纯规则 1:1 路径
# ============================================================

def _parse_json_loose(text: str):
    """容错解析 LLM 返回的 JSON（剥 ```json 围栏 + 截取首尾括号）。"""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except Exception:
        pass
    # 截取括号结构（优先最外层：嵌套时取起始最早者，避免短对象里先抠到内层数组）
    cands = []
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i, j = t.find(open_c), t.rfind(close_c)
        if i != -1 and j > i:
            try:
                cands.append((i, json.loads(t[i:j + 1])))
            except Exception:
                continue
    if cands:
        cands.sort(key=lambda c: c[0])
        return cands[0][1]
    return None


def llm_chat(messages: list, max_tokens: int = 2000, timeout: int = 150):
    """纯 stdlib 调 OpenAI 兼容网关。失败返回 None（调用方降级）。"""
    if not LLM_ON:
        return None
    # 节流：网关在密集调用时限流（伪装 400/404），强制调用间最小间隔模拟稳定节奏
    import time as _t
    now = _t.time()
    gap = 4 - (now - getattr(llm_chat, "_last", 0))
    if gap > 0:
        _t.sleep(gap)
    llm_chat._last = _t.time()
    # 网关对部分模型要求 content 为数组格式，统一规范化（OpenAI 标准兼容）
    norm_msgs = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            c = [{"type": "text", "text": c}]
        norm_msgs.append({"role": m["role"], "content": c})
    body = json.dumps({
        "model": DISTILL_MODEL, "temperature": 0, "max_tokens": max_tokens,
        "messages": norm_msgs,
    }).encode()
    req = urllib.request.Request(
        AIMETER_BASE + "/chat/completions", data=body,
        headers={"Authorization": "Bearer " + AIMETER_KEY,
                 "Content-Type": "application/json"})
    # 不重试：失败重试会在网关限流时连发形成风暴（诊断证明无重试+固定间隔才稳）；
    # 丢的主题靠容错增量下一轮补。节奏完全由函数开头的节流控制。
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read())
        msg = d["choices"][0]["message"]
        content = msg.get("content")
        # 思考链模型长 prompt 下 content 可能被 reasoning 吃空：回退 reasoning 末尾供解析抠 JSON
        if not content:
            content = msg.get("reasoning_content") or ""
        return content
    except (urllib.error.HTTPError, urllib.error.URLError, KeyError, TimeoutError) as e:
        err = ""
        if isinstance(e, urllib.error.HTTPError):
            try: err = e.read().decode()[:160]
            except Exception: pass
        print(f"  ! LLM 调用失败: {e} {err}", file=sys.stderr)
        return None


def _norm_clusters(data, reports: list, anchors: list | None = None) -> list:
    """宽容归一化 LLM 聚类输出，并解析概念 id（命中锚点才认，防幻觉 id）。
    B 阶段重构：不再按 domain 回填，统一 category=research。"""
    anchors = anchors or []
    anchor_by_id = {a["id"]: a for a in anchors if a.get("id")}
    slug_title = {r["slug"]: r["title"] for r in reports}
    valid = {r["slug"] for r in reports}
    groups = []  # (cid, topic, [slugs])
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list):
                groups.append(("", str(k), [x for x in v if isinstance(x, str)]))
            elif isinstance(v, dict):
                groups.append(("", str(k), [x for x in v.get("members", []) if isinstance(x, str)]))
    elif isinstance(data, list):
        for c in data:
            if isinstance(c, dict):
                ms = c.get("members") or c.get("slugs") or []
                groups.append((str(c.get("id", "") or ""), str(c.get("topic", "")),
                               [x for x in ms if isinstance(x, str)]))
            elif isinstance(c, list):
                groups.append(("", "", [x for x in c if isinstance(x, str)]))
    out, seen = [], set()
    for cid, topic, slugs in groups:
        members = [s for s in slugs if s in valid and s not in seen]
        if not members:
            continue
        seen.update(members)
        rid = cid if cid in anchor_by_id else ""  # 只认锚点里的 id，其余当新概念
        if not topic.strip():
            topic = (anchor_by_id[rid]["title"] if rid else
                     "、".join(slug_title[s] for s in members[:2]) + (" 等" if len(members) > 2 else ""))
        out.append({"id": rid, "topic": topic.strip(), "members": members})
    for r in reports:
        if r["slug"] not in seen:
            out.append({"id": "", "topic": r["title"], "members": [r["slug"]]})
    return out


def _cluster_one_batch(batch: list, anchors: list | None = None) -> list:
    """对一批报告（≤12 篇）聚类。anchors 非空时做增量聚类：优先归入已有概念。"""
    anchors = anchors or []
    anchor_block = ""
    if anchors:
        alines = []
        for a in anchors:
            have = ", ".join(a["members"][:8]) + ("…" if len(a["members"]) > 8 else "")
            alines.append(f'- id={a["id"]} | {a["title"]} | 已含: {have or "无"}')
        anchor_block = ("【已有概念】（语义匹配时优先归入，复用其 id 与 topic）\n" + "\n".join(alines) +
                        "\n注意：members 只列下方【待归类报告】中你归进来的 slug，不要抄已含列表。\n\n")
    lines = [f'- slug={r["slug"]} | {r["title"]}' for r in batch]
    catalog = "\n".join(lines)
    extra = ("把每篇待归类报告归入最匹配的已有概念（输出该概念的 id 与 topic）；" if anchors else
             "把它们按【研究主题】聚类，语义相近的归为一组；")
    id_rule = ("已有概念复用其 id；语义都不符才开新概念，新概念 id 填空字符串 \"\"、topic 用简洁中文短语。" if anchors else
               "topic 用简洁中文短语。")
    prompt = (
        "你是知识库编辑。" + (anchor_block or "") + "【待归类报告】（slug + 标题）：\n" + catalog + "\n"
        + extra + "规则：members 必须是待归类报告里的 slug 原样字符串；每个 slug 恰好归一处；"
        + id_rule +
        "只输出 JSON 数组，不要任何解释。每个元素是含 id/topic/members 的对象，禁止只输出 slug 数组。形如："
        '[{"id":"","topic":"向量检索","members":["hnsw-algorithm"]},'
        '{"id":"usage--abc","topic":"用量分析","members":["aws-claude-usage"]}]\n\n')
    raw = llm_chat([{"role": "user", "content": prompt}], max_tokens=6000, timeout=200)
    if not raw:
        return []
    data = _parse_json_loose(raw)
    if data is None:
        return []
    return _norm_clusters(data, batch, anchors)


def _load_existing_concepts() -> list:
    """读现有 knowledge 概念作增量聚类锚点（id + title + members）。
    B 阶段重构：扁平扫描 knowledge/ 下所有 topic 目录（不再按 domain 分层）。"""
    anchors = []
    if not KNOWLEDGE_DIR.exists():
        return anchors
    for tdir in sorted(KNOWLEDGE_DIR.iterdir()):
        ovf = tdir / "overview.md"
        if not tdir.is_dir() or not ovf.exists() or tdir.name.startswith("."):
            continue
        ov = parse_overview(ovf.read_text(encoding="utf-8"))
        if not ov["title"]:
            continue
        cid = ov.get("id") or tdir.name
        members = ov.get("source_reports") or []
        if not members:  # 旧散文格式回退：从「来源」节抠 slug
            for s in ov["sections"]:
                if s["label"] == "来源":
                    members = [it["source"] for it in s["items"] if it["source"]]
        anchors.append({"id": cid, "title": ov["title"], "members": members})
    return anchors


def llm_cluster(reports: list, anchors: list | None = None) -> list:
    """全局语义聚类：分批（每批 12 篇）+ 跨批合并（id 优先，其次 topic 名）。失败返回 None。
    B 阶段重构：cluster 不再带 domain 字段。"""
    BATCH = 12
    all_clusters = []
    for i in range(0, len(reports), BATCH):
        all_clusters += _cluster_one_batch(reports[i:i + BATCH], anchors)
    if not all_clusters:
        return None
    merged, order = {}, []
    for c in all_clusters:
        key = c["id"] if c["id"] else ("T:" + (re.sub(r"\s+", "", c["topic"]).lower() or c["topic"]))
        if key not in merged:
            merged[key] = {"id": c["id"], "topic": c["topic"], "members": list(c["members"])}
            order.append(key)
        else:
            seen = set(merged[key]["members"])
            merged[key]["members"] += [m for m in c["members"] if m not in seen]
            if not merged[key]["id"]:  # 合并时若任一批带 id 则采纳
                merged[key]["id"] = c["id"]
    out = [merged[k] for k in order]
    seen = {m for c in out for m in c["members"]}
    for r in reports:
        if r["slug"] not in seen:
            out.append({"id": "", "topic": r["title"], "members": [r["slug"]]})
    return out


def _heuristic_cluster(catalog: list) -> list:
    """启发式兆底聚类：网关不可用时按关键词把报告聚成多源主题。
    不完美但保证多源分组成立，比 1:1 垃圾强；网关恢复后 LLM 聚类会覆盖它。
    B 阶段重构：不再带 domain 字段。"""
    BUCKETS = [  # (主题名, 关键词)
        ("向量检索与 RAG", ["rag", "retrieval", "top-k", "topk", "hnsw", "向量", "检索", "lightrag", "embed"]),
        ("Agent 记忆与上下文", ["memory", "hindsight", "记忆", "weaver", "上下文"]),
        ("图谱与知识库基础设施", ["pggraph", "pgcontext", "图谱", "graph", "gamekb", "知识库"]),
        ("用量与成本治理", ["用量", "usage", "cost", "成本", "aimeter", "治理", "token"]),
        ("Agent 工程工具链", ["codegraph", "ponytail", "context7", "skill", "工具链"]),
        ("知识数据源配置", ["knowledge-sources", "数据源", "知识源"]),
    ]
    groups = {name: {"topic": name, "members": []} for name, _, in BUCKETS}
    used = set()
    for r in catalog:
        hay = (r["slug"] + " " + r["title"]).lower()
        placed = False
        for name, kws in BUCKETS:
            if any(k in hay for k in kws):
                groups[name]["members"].append(r["slug"])
                used.add(r["slug"])
                placed = True
                break
        if not placed:
            groups[r["title"]] = {"topic": r["title"], "members": [r["slug"]]}
            used.add(r["slug"])
    out = [g for g in groups.values() if g["members"]]
    return out or None

def _read_md_excerpt(report_file: str, maxlen: int = 2000) -> str:
    """读报告的 .md 李生原文作 LLM 编译原料（信息比规则抽取完整得多）。无则空。"""
    name = report_file[:-5] if report_file.endswith(".html") else report_file
    md_path = REPORTS_DIR / (name + ".md")
    if not md_path.exists():
        return ""
    t = md_path.read_text(encoding="utf-8")
    return t[:maxlen] + ("…[截断]" if len(t) > maxlen else "")
def existing_tags() -> list[str]:
    """收集全库已有标签清单（frontmatter tags 字段，去重保序），供编译/classify prompt 优先复用。
    分类规格 §1：小标签无治理流程，靠 prompt 收敛，不做标签注册表。
    B 阶段重构：扁平扫描 knowledge/ 下所有 topic 目录。"""
    tags, seen = [], set()
    if KNOWLEDGE_DIR.exists():
        for tdir in sorted(p for p in KNOWLEDGE_DIR.iterdir()
                           if p.is_dir() and not p.name.startswith(".")):
            ovf = tdir / "overview.md"
            if not tdir.is_dir() or not ovf.exists():
                continue
            meta, _ = parse_frontmatter(ovf.read_text(encoding="utf-8"))
            for t in (meta.get("tags") or []):
                t = str(t).strip()
                if t and t not in seen:
                    seen.add(t)
                    tags.append(t)
    return tags


def llm_classify(topic: str, body: str, existing: list) -> dict | None:
    """LLM 为存量主题补 category + tags（cli classify 用，不重编译正文）。
    返回 {"category": key, "tags": [...]}；LLM 不可用/返回不可解析 → None（调用方留白不误分）。
    category 不在枚举内 → 兜底 'ai'；tags 为空 → []（写入时字段省略）。"""
    excerpt = body.strip()[:1500]
    cat_desc = "；".join(
        f"{k}（{CATEGORIES[k]}：收{v}" for k, v in config.CATEGORY_SCOPES.items())
    tag_pool = "、".join(existing) if existing else "（暂无）"
    prompt = (
        "你是知识库编辑，为下面的主题选专栏分类与标签。\n"
        f"专栏枚举（key 即输出值）: {cat_desc}\n"
        f"已有标签清单（优先复用，避免造新词）: {tag_pool}\n\n"
        f"主题: {topic}\n内容摘录:\n{excerpt}\n\n"
        '输出 JSON：{"category": "ai", "tags": ["RAG", "检索"]}\n'
        "category 必须取枚举 key 之一；tags 2-5 个，用简短短语、不要含逗号；"
        "拿不准分类时取 ai。只输出该 JSON 对象，不要任何解释。")
    raw = llm_chat([{"role": "user", "content": prompt}], max_tokens=300, timeout=120)
    if not raw:
        return None
    data = _parse_json_loose(raw)
    if not isinstance(data, dict):
        return None
    cat = str(data.get("category", "")).strip()
    if cat not in CATEGORIES:
        cat = "ai"
    tags = [str(t).strip() for t in (data.get("tags") or [])
            if isinstance(t, str) and t.strip()][:5]
    return {"category": cat, "tags": tags}


def llm_compile_topic(topic: str, members: list, feedbacks: list | None = None) -> dict:
    """LLM 读各篇原文，为主题编译一整篇浓缩 wiki（结构化 JSON）。
    返回 {summary, points:[..], data:[..], traps:[..], contradictions:[{point,sides}]}。
    正文主体全部由 LLM 从原文编译，不再拼规则抽取的碎片。
    P2（规格 §6③）：feedbacks 为 adopted 使用写回，以 type=feedback 来源与报告平级进综合，
    走既有 AGREE/DISAGREE/SYNTHESIZE 语义（[feedback#id] 可进 contradictions 的 sides）。"""
    feedbacks = feedbacks or []
    blocks = []
    for m in members:
        # 喂规则抽的结构化摘要（短，网关能跑），而非全文 excerpt（长，整跑负载下网关 400/思考链爆）
        parts = ([f"    · 结论: {t}" for t in (m.get("conclusions") or [])]
                 + [f"    · 陷阱: {t}" for t in (m.get("traps") or [])]
                 + [f"    · 数据: {t}" for t in (m.get("data") or [])])
        if not parts:
            parts = ["    · （无结构化摘要）"]
        blocks.append(f"[{m['slug']}] 《{m['title']}》\n" + "\n".join(parts))
    # P2：adopted 反馈作为平级来源进编译（证据+意见，agent 自报）
    for fb in feedbacks:
        blocks.append(f"[feedback#{fb['id']}] （使用写回 · {fb['agent']}）\n"
                      f"    · 证据: {fb['evidence']}\n"
                      f"    · 意见: {fb['opinion']}")
    body = "\n\n".join(blocks)
    n = len(members)
    src_desc = (f"{n} 篇报告的结构化摘要（结论/陷阱/数据，每段以 [slug] 标注来源）"
                if not feedbacks else
                f"{n} 篇报告的结构化摘要与 {len(feedbacks)} 条已采纳的使用写回反馈（每段以 [slug] 或 [feedback#id] 标注来源）")
    cross = "交叉综合这些来源的共识、互补与演进脉络" if (n + len(feedbacks)) >= 2 else "提炼这篇报告的核心知识"
    existing = existing_tags()
    tag_pool = "、".join(existing) if existing else "（暂无）"
    cat_desc = "；".join(f"{k}（{CATEGORIES[k]}）" for k in CATEGORIES)
    prompt = (
        f"你是知识库编辑，正在为主题『{topic}』编译一篇浓缩 wiki，材料来自 {src_desc}。\n"
        f"请{cross}，产出一份读者读完即懂该主题的完整浓缩内容。要求：写实质内容，含具体机制/数字/名称，不要废话套话，不要说『缺乏结论』；"
        "每条要点/数据/陷阱末尾用 [slug] 或 [feedback#id] 标注它出自哪个来源（可多个）。\n"
        "输出一个 JSON 对象，字段：\n"
        '- summary: 字符串，2-4 句概述该主题是什么、解决什么问题、各来源如何互补或演进；\n'
        '- points: 字符串数组，核心要点（3-8 条），每条一句实质陈述，编译自原文，不要照抄标题；\n'
        '- data: 字符串数组，真正有意义的数字/事实/对比（0-6 条），只收有信息量的，禁止空泛行；\n'
        '- traps: 字符串数组，陷阱/反模式/踩坑点（0-5 条）；\n'
        '- contradictions: 数组，来源间真正的观点冲突，每项 {point, sides:[\"[slugX] 原话\",...]}；无则空数组。\n'
        f'- category: 字符串，专栏归类，必须取枚举 key 之一：{cat_desc}；\n'
        '- tags: 字符串数组（2-5 个），主题的小标签（如「RAG」「检索」「开源项目」），'
        '用简短短语、不要含逗号，优先复用已有标签；\n'
        f"当前全库已有标签清单（优先复用，可按需新增）: {tag_pool}\n"
        '只输出该 JSON 对象，不要任何解释。\n\n' + body)
    raw = llm_chat([{"role": "user", "content": prompt}], max_tokens=3000, timeout=300)
    empty = {"summary": "", "points": [], "data": [], "traps": [], "contradictions": [],
             "category": "ai", "tags": []}
    if not raw:
        return empty
    data = _parse_json_loose(raw)
    if not isinstance(data, dict):
        return empty
    def strs(key, lim):
        out = []
        for x in (data.get(key) or [])[:lim]:
            if isinstance(x, str) and x.strip():
                out.append(x.strip())
        return out
    contra = []
    for c in (data.get("contradictions") or [])[:6]:
        if isinstance(c, dict) and c.get("point") and c.get("sides"):
            contra.append({"point": str(c["point"]).strip(),
                           "sides": [str(s).strip() for s in c["sides"]]})
    # 分类规格 §1：category 必须命中枚举，校验失败兜底 'ai'；tags 0-5 个，空则无
    cat = str(data.get("category", "")).strip()
    if cat not in CATEGORIES:
        cat = "ai"
    tags = [str(t).strip() for t in (data.get("tags") or [])
            if isinstance(t, str) and t.strip()][:5]
    return {
        "summary": str(data.get("summary", "")).strip(),
        "points": strs("points", 8),
        "data": strs("data", 6),
        "traps": strs("traps", 5),
        "contradictions": contra,
        "category": cat,
        "tags": tags,
    }

# ============================================================
# 报告扫描与路由
# ============================================================

def _read_meta(html_content: str, name: str) -> str:
    m = re.search(rf'<meta name="{name}" content="([^"]*)"', html_content)
    return m.group(1) if m else ""


def scan_reports() -> list[dict]:
    """扫描 reports/，返回 [{file, category, slug, title, content}]。
    审核治理：reports 表 hidden=1 的报告直接跳过（软下架不参与蒸馏，两路径统一生效）。
    B 阶段重构：只蒸 category==research 的报告；元数据读 category（不再读 domain）；
    content 读 .md 孪生文件；title 从 DB 取（元数据真相源），md 标题兜底。
    file 字段仍记 .html 名——log.md 存量条目按 .html 名记，保持 processed_files 兼容。"""
    if not REPORTS_DIR.exists():
        return []
    conn = store.get_db()
    try:
        out = []
        for f in sorted(REPORTS_DIR.glob("*.md")):
            slug_m = re.match(r"\d{4}-\d{2}-\d{2}-(.+)\.md", f.name)
            slug = slug_m.group(1) if slug_m else f.stem
            content = f.read_text(encoding="utf-8")
            title_m = re.search(r"^# (.+)$", content, re.MULTILINE)
            title = title_m.group(1).strip() if title_m else slug
            row = store.get_report_by_slug(conn, slug)
            if row and row.get("hidden"):
                continue  # 审核治理：软下架报告不参与蒸馏
            category = (row or {}).get("category") or "research"
            if row and row.get("title"):
                title = row["title"]  # DB 是元数据真相源，md 标题只是兜底
            out.append({"file": f.name[:-3] + ".html", "path": f, "category": category,
                        "slug": slug, "title": title, "content": content})
        return out
    finally:
        conn.close()


def processed_files() -> set[str]:
    """从 log.md 读取已处理文件列表"""
    if not LOG_PATH.exists():
        return set()
    return set(re.findall(r"^- \[x\] (\S+)", LOG_PATH.read_text(encoding="utf-8"), re.MULTILINE))


# ============================================================
# 知识落盘（KSI 进化：AGREE / DISAGREE / SYNTHESIZE）
# ============================================================

KIND_LABELS = {
    "conclusion": "结论",
    "refuted": "被否假设",
    "trap": "陷阱",
    "data": "关键数据",
    "disagree": "分歧",
}

NEGATION_RE = re.compile(r"不要|不适合|不应|别用|不能|禁止|避免|并非|不是|无需|不建议|\bnot\b|\bnever\b|\bdon't\b|\bavoid\b|\bunsuitable\b")

_STOP_WORDS = {"the", "and", "for", "with", "this", "that", "not", "are", "is", "was"}


def _keywords(text: str) -> set[str]:
    """提取关键词：中文用字符 bigram，英文用 3+ 字母词。"""
    words = set(re.findall(r"[a-zA-Z]{3,}", text.lower())) - _STOP_WORDS
    # 中文 bigram（无分词器的最懒替代）
    cn = re.findall(r"[\u4e00-\u9fff]+", text)
    for seg in cn:
        for i in range(len(seg) - 1):
            words.add(seg[i:i+2])
    return words

def _detect_contradiction(new_text: str, existing_texts: list[str]) -> str | None:
    """检测新条目是否与已有条目矛盾（规则存根版）。

    返回被矛盾的已有条目文本，无矛盾返回 None。
    # ponytail: bigram 重叠+否定词检测；LLM 版语义矛盾检测等有真实矛盾案例后再加
    """
    new_neg = bool(NEGATION_RE.search(new_text))
    new_words = _keywords(new_text)
    if len(new_words) < 2:
        return None
    for existing in existing_texts:
        ex_neg = bool(NEGATION_RE.search(existing))
        if ex_neg == new_neg:
            continue  # 同向，不矛盾
        ex_words = _keywords(existing)
        # 长度差异过大 → 限定条件而非矛盾（如「成本高」 vs「成本高不适合小团队」）
        if max(len(new_words), len(ex_words)) > min(len(new_words), len(ex_words)) * 2:
            continue
        overlap = new_words & ex_words
        if len(overlap) >= 3 and len(overlap) >= len(new_words) * 0.5:
            return existing
    return None


def _topic_dir(slug: str) -> Path:
    """知识目录（B 阶段扁平化）：knowledge/{slug}/"""
    return KNOWLEDGE_DIR / slug


def _read_existing_items(overview_path: Path) -> dict[str, list[str]]:
    """读已有 overview.md，按 kind 分组返回已有条目文本"""
    if not overview_path.exists():
        return {}
    text = overview_path.read_text(encoding="utf-8")
    items = {}
    current_kind = None
    for line in text.splitlines():
        # 匹配 ## 结论 / ## 被否假设 等
        h = re.match(r"^## (.+)$", line)
        if h:
            label = h.group(1).strip()
            current_kind = next((k for k, v in KIND_LABELS.items() if v == label), None)
            if current_kind:
                items.setdefault(current_kind, [])
            continue
        # 匹配 - text [source] 或 - ~~text~~ [source]
        m = re.match(r"^- (.+?) \[([^\]]+)\]$", line)
        if m and current_kind:
            items[current_kind].append(m.group(1))
    return items


def write_knowledge(slug: str, title: str,
                    items: list[dict], source: str) -> Path:
    """KSI 进化：AGREE 追加 / DISAGREE 标记分歧 / SYNTHESIZE 综合
    B 阶段重构：目录扁平 knowledge/{slug}/，不再按 domain 分层。"""
    tdir = _topic_dir(slug)
    tdir.mkdir(parents=True, exist_ok=True)
    overview = tdir / "overview.md"

    existing = _read_existing_items(overview)
    today = datetime.now().strftime("%Y-%m-%d")

    # 按 kind 分组新条目，检测矛盾
    new_by_kind: dict[str, list[str]] = {}
    disagree_items: list[str] = []
    for item in items:
        kind = item["kind"]
        text = item["text"]
        existing_texts = existing.get(kind, [])
        if text in existing_texts:
            continue  # 完全重复，跳过
        # DISAGREE 检测（仅对 conclusion 类）
        if kind == "conclusion":
            contradicted = _detect_contradiction(text, existing_texts)
            if contradicted:
                disagree_items.append(
                    f"新: {text} [{source}] ↔ 旧: {contradicted}")
                continue  # 不追加到结论，记入分歧
        new_by_kind.setdefault(kind, []).append(f"{text} [{source}]")

    # 统计来源数
    src_count = len(set(
        re.findall(r"\[([^\]]+)\]", overview.read_text(encoding="utf-8"))
    ) | {source}) if overview.exists() else 1

    # 重建 overview.md
    lines = [
        f"# {title}",
        "",
        f"> Updated: {today} | Sources: {src_count} report(s) | Confidence: {'high' if src_count >= 3 else 'medium' if src_count >= 2 else 'low'}",
        "",
    ]
    for kind in ("conclusion", "refuted", "trap", "data", "disagree"):
        label = KIND_LABELS[kind]
        all_items = []
        if overview.exists():
            in_section = False
            for line in overview.read_text(encoding="utf-8").splitlines():
                if re.match(rf"^## {re.escape(label)}$", line):
                    in_section = True
                    continue
                if in_section and line.startswith("## "):
                    break
                if in_section and line.startswith("- "):
                    all_items.append(line[2:])
        # 追加新条目
        source_items = disagree_items if kind == "disagree" else new_by_kind.get(kind, [])
        for new_text in source_items:
            if new_text not in all_items:
                all_items.append(new_text)
        if all_items:
            lines.append(f"## {label}")
            lines.append("")
            for item in all_items:
                lines.append(f"- {item}")
            lines.append("")

    # SYNTHESIZE：3+ 来源时添加综合注记
    if src_count >= 3:
        lines.append("## 综合")
        lines.append("")
        lines.append(f"- 本主题已由 {src_count} 篇报告交叉验证，结论可信度高。 [{today}]")
        lines.append("")

    overview.write_text("\n".join(lines), encoding="utf-8")
    # P3：知识条目原子化——items.json 孪生（只加新文件，不碰 overview.md）
    _write_items_json(slug, "\n".join(lines))
    return overview


def write_knowledge_compiled(cluster: dict, members_data: dict,
                             compiled: dict | None, feedbacks: list | None = None) -> Path:
    """LLM 编译路径：写一个语义主题的 overview.md（多源聚合 + 交叉引用）。
    B 阶段重构：目录扁平 knowledge/{slug}/；frontmatter 不再记 domain，只记 category。
    P2：feedbacks 为本轮消费的 adopted 写回——frontmatter 记 feedback_sources: N（信任元数据，规格 §6③）。"""
    feedbacks = feedbacks or []
    topic, member_slugs = cluster["topic"], cluster["members"]
    n = len(member_slugs)
    conf = "high" if n >= 3 else "medium" if n >= 2 else "low"
    today = datetime.now().strftime("%Y-%m-%d")
    model_tag = DISTILL_MODEL if (LLM_ON and compiled) else "规则"
    compiled = compiled or {"summary": "", "points": [], "data": [], "traps": [], "contradictions": []}
    # 容错：LLM 编译无实质内容时不写（不拿空页/标题兑底页覆盖旧的好内容）
    if not compiled["summary"] and not compiled["points"] and not compiled["contradictions"]:
        return None

    summary = compiled["summary"]
    if not summary:
        summary = members_data[member_slugs[0]]["title"]  # 有 points 但无 summary 时的兑底

    # 目录名 = 持久 id（增量聚类复用 existing_id；id 落盘即持久，与目录名恒等）
    slug = _safe_slug(topic, member_slugs, cluster.get("id", ""))
    verified = "machine-confirmed" if n >= 2 else "unverified"
    stale_after = (datetime.now() + timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d")
    meta = {
        "id": slug, "title": topic, "type": "Topic",
        "category": compiled.get("category", "ai"),  # 分类规格 §1：枚举 key，编译校验兜底 ai
        "status": "stable",
        "generated": {"by": f"agent:{model_tag}", "at": today},
        "verified": verified, "sources_count": n, "stale_after": stale_after,
        "confidence": conf,
        "source_reports": list(dict.fromkeys(member_slugs)),
        # P2（规格 §6③）：被使用、被检验写进信任元数据；0 也记，表明该主题尚未经使用回路
        "feedback_sources": len(feedbacks),
    }
    # 分类规格 §1：tags 为空则无（frontmatter 不写空列表字段）
    if compiled.get("tags"):
        meta["tags"] = compiled["tags"][:5]

    lines = ["## 概述", "", summary, ""]
    if compiled["points"]:
        lines += ["## 核心要点", ""] + [f"- {x}" for x in compiled["points"]] + [""]
    if compiled["data"]:
        lines += ["## 关键数据", ""] + [f"- {x}" for x in compiled["data"]] + [""]
    if compiled["traps"]:
        lines += ["## 陷阱与反模式", ""] + [f"- {x}" for x in compiled["traps"]] + [""]
    if compiled["contradictions"]:
        lines.append("## 分歧")
        lines.append("")
        for c in compiled["contradictions"]:
            sides = "　↔　".join(c["sides"])
            lines.append(f"- **{c['point']}**：{sides}")
        lines.append("")
    # 来源交叉引用（人类读 + 视图渲染；机器读走 frontmatter 的 source_reports）
    lines.append("## 来源")
    lines.append("")
    for s in dict.fromkeys(member_slugs):
        lines.append(f"- {members_data[s]['title']} [{s}]")
    for fb in feedbacks:  # P2：反馈即来源，与报告平级列在来源节
        lines.append(f"- 使用写回（{fb['agent']}）：{fb['opinion']} [feedback#{fb['id']}]")
    lines.append("")

    tdir = _topic_dir(slug)
    tdir.mkdir(parents=True, exist_ok=True)
    overview = tdir / "overview.md"
    md_text = dump_frontmatter(meta) + "\n".join(lines)
    overview.write_text(md_text, encoding="utf-8")
    # P3：知识条目原子化——items.json 孪生（只加新文件，不碰 overview.md）
    _write_items_json(slug, md_text)
    return overview


def _safe_slug(topic: str, member_slugs: list, existing_id: str = "") -> str:
    """主题 → 目录名。existing_id 非空时直接用（概念持久身份，增量聚类复用已有目录，
    id 落盘即持久，不再重算，根除同名/孤儿）；否则单源用 slug、多源用成员集合 hash。"""
    if existing_id:
        return existing_id
    if len(member_slugs) == 1:
        return member_slugs[0]
    # 多源：目录名 = 排序后成员 slug 集合的 hash（与 LLM 给的 topic 名解耦，稳定不产生孤儿）
    import hashlib
    sorted_ms = sorted(member_slugs)
    h = hashlib.md5("|".join(sorted_ms).encode()).hexdigest()[:6]
    base = re.sub(r"[^a-z0-9]+", "-", sorted_ms[0].lower()).strip("-") or "topic"
    return f"{base}--{h}"

# ============================================================
# index.md / log.md
# ============================================================

def update_index():
    """重建 index.md：每个知识页一行。
    B 阶段重构：扁平扫描 knowledge/ 下所有 topic 目录。"""
    lines = ["# 知识索引", "",
             f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    count = 0
    if KNOWLEDGE_DIR.exists():
        for topic_dir in sorted(KNOWLEDGE_DIR.iterdir()):
            if not topic_dir.is_dir() or topic_dir.name.startswith("."):
                continue
            overview = topic_dir / "overview.md"
            if not overview.exists():
                continue
            first_line = overview.read_text(encoding="utf-8").splitlines()[0]
            title = first_line.lstrip("# ").strip()
            src_m = re.search(r"Sources: (\d+)", overview.read_text(encoding="utf-8"))
            src = src_m.group(1) if src_m else "?"
            lines.append(f"- {title} — {src} source(s) → `{topic_dir.name}/`")
            count += 1
    lines.insert(3, f"共 {count} 个知识页。")
    INDEX_PATH.write_text("\n".join(lines), encoding="utf-8")


def append_log(entries: list[str]):
    """追加 log.md"""
    if not LOG_PATH.exists():
        LOG_PATH.write_text("# 蒸馏日志\n\n", encoding="utf-8")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        for e in entries:
            f.write(f"- {e}\n")


# ============================================================
# P2：反馈消费与翻案（规格 §6③）
# ============================================================

# overview 里的反馈证据行（规则路径 sweep 用）
FEEDBACK_LINE_RE = re.compile(r"^- .*\[feedback#\d+\].*$", re.MULTILINE)


def _last_consumed_sets() -> dict:
    """从 log.md 解析每主题最后一次消费的反馈 id 集：`- [fb] {topic} consumed: 1,2,3`。
    append-only 日志，后记覆盖前记——翻案/新采纳都与它对比，不一致即重编译（防重复消费）。"""
    sets = {}
    if LOG_PATH.exists():
        for m in re.finditer(r"^- \[fb\] (\S+) consumed: ([0-9, ]*)$",
                             LOG_PATH.read_text(encoding="utf-8"), re.MULTILINE):
            sets[m.group(1)] = {int(x) for x in re.findall(r"\d+", m.group(2))}
    return sets


def _sweep_feedbacks() -> list:
    """规则（无 LLM）路径的反馈回灌：把每个主题的 overview 对齐到当前 adopted 集合。
    - 新采纳 → 追加证据行；翻案（adopted→rejected）→ 删对应行，下轮即生效（规格 §6③）
    - 幂等：与 log 里最后消费集一致的主题跳过；变更后记 [fb] 日志防重复。
    - 外科式改文本（不走 write_knowledge 重建）：编译式/规则式 overview 都不破坏原结构。
    B 阶段重构：扁平扫描 knowledge/ 下所有 topic 目录。"""
    consumed = _last_consumed_sets()
    log_entries = []
    conn = store.get_db()
    try:
        if not KNOWLEDGE_DIR.exists():
            return log_entries
        for tdir in sorted(KNOWLEDGE_DIR.iterdir()):
            ovf = tdir / "overview.md"
            if not tdir.is_dir() or not ovf.exists() or tdir.name.startswith("."):
                continue
            topic = tdir.name
            adopted = store.adopted_feedbacks(conn, topic)
            adopted_ids = {fb["id"] for fb in adopted}
            if adopted_ids == consumed.get(topic, set()):
                continue  # 无变化（含「无反馈」主题），不碰文件
            text = ovf.read_text(encoding="utf-8")
            # 先清旧反馈行与旧「使用写回」整节（翻案即在这里生效）
            text = FEEDBACK_LINE_RE.sub("", text)
            text = re.sub(r"\n## 使用写回\s*\n(?:(?!## )[\s\S]*?)(?=\n## |\Z)", "\n", text)
            if adopted:
                lines = [f"- {fb['evidence']}——意见：{fb['opinion']}（{fb['agent']}） [feedback#{fb['id']}]"
                         for fb in adopted]
                text = text.rstrip() + "\n\n## 使用写回\n\n" + "\n".join(lines) + "\n"
            ovf.write_text(text, encoding="utf-8")
            ids = ",".join(str(i) for i in sorted(adopted_ids))
            log_entries.append(f"[fb] {topic} consumed: {ids}")
    finally:
        conn.close()
    return log_entries


# ============================================================
# 藏书楼视图（knowledge/ → public/knowledge/index.html）
# P3 前端抢救：_KNOWLEDGE_TPL 迁到 views/knowledge.html
# _render_card / _src_link 迁到 ui.py
# 内联 CSS 提取到 public/assets/knowledge.css
# ============================================================

# P3 前端抢救：卡片/分区片段归 ui.py（P4 分类规格后分区键为 category，DOMAIN_NAME 别名移除）
# 旧引用别名（build_knowledge_page 通过 _render_card 调用 ui.render_knowledge_card）
_render_card = ui.render_knowledge_card
_src_link = ui._src_link

# _KNOWLEDGE_TPL 已迁出到 views/knowledge.html，通过 ui.load_view("knowledge.html") 加载
_KNOWLEDGE_TPL = None  # P3 前端抢救


# ============================================================
# B 阶段词条页生成（决策 2-a：每 topic 静态生成 public/knowledge/{topic}.html）
# ============================================================

def _trust_badge(ov: dict) -> tuple[str, str]:
    """信任徽章：返回 (label, css_class)。
    high→可信(hi) / medium→可参(mid) / low→存疑(lo)。"""
    conf = ov.get("confidence", "low")
    badges = {"high": ("可信", "trust-hi"), "medium": ("可参", "trust-mid"), "low": ("存疑", "trust-lo")}
    return badges.get(conf, ("存疑", "trust-lo"))


def _entry_sections_html(ov: dict) -> str:
    """词条页正文分节 HTML：概述摘要 + 核心要点 + 关键数据 + 陷阱与反模式 + 分歧 + 来源。"""
    parts = []
    # 概述（摘要段）
    for s in ov["sections"]:
        if s["label"] in ("概述", "一句话结论") and s["items"]:
            text = html.escape(s["items"][0]["text"])
            parts.append(f'<div class="entry-summary">{text}</div>')
            break
    # 各知识节
    for s in ov["sections"]:
        if not s["items"] or s["label"] in ("概述", "一句话结论", "来源"):
            continue
        label = html.escape(s["label"])
        lis = ""
        for it in s["items"]:
            src_html = _src_link(it["source"]) if it.get("source") else ""
            lis += f'<li>{html.escape(it["text"])}{src_html}</li>'
        if lis:
            parts.append(f'<section><h2>{label}</h2><ul>{lis}</ul></section>')
    # 来源节
    src_labels = []
    for s in ov["sections"]:
        if s["label"] == "来源":
            for it in s["items"]:
                src_html = _src_link(it["source"]) if it.get("source") else ""
                src_labels.append(f'<li>{html.escape(it["text"])}{src_html}</li>')
    if src_labels:
        parts.append(f'<section><h2>来源</h2><ul>{"".join(src_labels)}</ul></section>')
    return "\n".join(parts)


def collect_topics() -> list[dict]:
    """扫描 knowledge/ 下所有 topic 目录，返回供 C 阶段索引用的话题摘要列表。
    每个 dict：{topic, title, summary, category, category_label, sources, confidence,
                trust_label, trust_cls, tags, updated, stale, stale_after, entry_url}。
    - topic: 目录名（slug）
    - summary: 概述首句（≤120 字），供轻索引用
    - entry_url: 词条页链接 /knowledge/{topic}.html
    本函数只读不写，不依赖 DB。"""
    topics = []
    if not KNOWLEDGE_DIR.exists():
        return topics
    for tdir in sorted(KNOWLEDGE_DIR.iterdir()):
        if not tdir.is_dir() or tdir.name.startswith("."):
            continue
        ovf = tdir / "overview.md"
        if not ovf.exists():
            continue
        ov = parse_overview(ovf.read_text(encoding="utf-8"))
        topic = tdir.name
        # 概述首句
        summary = ""
        for s in ov["sections"]:
            if s["label"] in ("概述", "一句话结论") and s["items"]:
                summary = s["items"][0]["text"][:120]
                break
        trust_label, trust_cls = _trust_badge(ov)
        stale = False
        sa = ov.get("stale_after", "")
        if sa:
            try:
                if datetime.strptime(sa, "%Y-%m-%d") < datetime.now():
                    stale = True
            except ValueError:
                pass
        topics.append({
            "topic": topic,
            "title": ov["title"],
            "summary": summary,
            "category": ov.get("category", "ai"),
            "category_label": CATEGORIES.get(ov.get("category", "ai"), ov.get("category", "ai")),
            "sources": ov["sources"],
            "confidence": ov.get("confidence", "low"),
            "trust_label": trust_label,
            "trust_cls": trust_cls,
            "tags": ov.get("tags") or [],
            "updated": ov.get("updated", ""),
            "stale": stale,
            "stale_after": sa,
            "entry_url": f"/knowledge/{topic}.html",
        })
    return topics


def build_entry_pages(topics: list[dict] | None = None) -> list[Path]:
    """为每个 topic 生成 public/knowledge/{topic}.html 全文词条页。
    topics 可选（传 collect_topics() 返回值节省一次扫描）；不传则自动扫描。
    返回生成的 Path 列表。模板：views/knowledge-entry.html。"""
    if topics is None:
        topics = collect_topics()
    out_dir = PUBLIC_DIR / "knowledge"
    out_dir.mkdir(parents=True, exist_ok=True)
    tpl = ui.load_view("knowledge-entry.html")
    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    paths = []
    for t in topics:
        stale_html = '<span class="badge trust-lo">已过期</span>' if t["stale"] else ""
        summary_html = ""
        if t["summary"]:
            summary_html = f'<div class="entry-summary">{html.escape(t["summary"])}</div>'
        # 读完整 overview 渲染分节
        ovf = KNOWLEDGE_DIR / t["topic"] / "overview.md"
        if ovf.exists():
            ov = parse_overview(ovf.read_text(encoding="utf-8"))
            sections_html = _entry_sections_html(ov)
        else:
            sections_html = ""
        out = (tpl
               .replace("__TITLE__", html.escape(t["title"]))
               .replace("__CAT_LABEL__", html.escape(t["category_label"]))
               .replace("__SRC_COUNT__", str(t["sources"]))
               .replace("__TRUST_CLS__", t["trust_cls"])
               .replace("__TRUST_LABEL__", t["trust_label"])
               .replace("__STALE_HTML__", stale_html)
               .replace("__UPDATED__", html.escape(t["updated"]))
               .replace("__SUMMARY_HTML__", summary_html)
               .replace("__SECTIONS_HTML__", sections_html)
               .replace("__TOPIC_ID__", html.escape(t["topic"]))
               .replace("__GEN_TIME__", gen_time))
        out_path = out_dir / f"{t['topic']}.html"
        out_path.write_text(out, encoding="utf-8")
        paths.append(out_path)
    return paths


# ============================================================
# OKF 风格 frontmatter（自写解析/序列化，纯 stdlib，不引 PyYAML）
# 只支持我们真用到的四种结构：标量 / 整数 / 内联映射 {} / 标量列表 -。
# 概念持久身份、信任信号、过期时间都走这里，替代旧的散文元行。
# ============================================================

def _fm_q(s: str) -> str:
    """标量序列化：需要时加双引号（含 : / # / 引号 / 花括号 / 逗号 / 空串 / 首尾空格）。"""
    if (s == "" or s != s.strip() or ":" in s or "#" in s or
            "\"" in s or "\\" in s or "{" in s or "}" in s or "," in s or "\n" in s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _fm_unq(s: str) -> str:
    """标量反序列化：去首尾空白 + 去配对双引号并反转义。"""
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return s


def _fm_dump_val(v) -> str:
    """值序列化：内联映射 → {k: v, ...}；其余当标量/整数。"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, dict):
        parts = [f"{k}: {_fm_q(str(vv))}" for k, vv in v.items()]
        return "{" + ", ".join(parts) + "}"
    return _fm_q(str(v))


def dump_frontmatter(d: dict) -> str:
    """dict → '---\\n...\\n---\\n'。列表写成多行 - 项。"""
    lines = ["---"]
    for k, v in d.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {_fm_dump_val(item)}")
        else:
            lines.append(f"{k}: {_fm_dump_val(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _fm_parse_inline(s: str) -> dict:
    """解析内联映射 '{a: 1, b: x:y}'。值用首个 ': ' 分割（值内冒号无空格故安全）。"""
    s = s.strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1].strip()
    out = {}
    if not s:
        return out
    for part in s.split(", "):
        if ": " in part:
            kk, vv = part.split(": ", 1)
            out[kk.strip()] = _fm_unq(vv)
        elif ":" in part:  # 值无空格的退化情况
            kk, vv = part.split(":", 1)
            out[kk.strip()] = _fm_unq(vv)
    return out


def parse_frontmatter(text: str):
    """解析 OKF frontmatter。返回 (meta_dict, body_str)；无 frontmatter 返回 ({}, text)。"""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    # 找第二个 ---
    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end == -1:
        return {}, text
    meta, i, cur_list = {}, 1, None
    for line in lines[1:end]:
        if line.startswith("  - ") or line.startswith("- "):
            if cur_list is not None:
                cur_list.append(_fm_unq(line.split("- ", 1)[1]))
            continue
        if ":" not in line:
            continue
        k, rest = line.split(":", 1)
        k = k.strip()
        rest = rest.strip()
        if rest == "":
            meta[k] = []
            cur_list = meta[k]
        elif rest.startswith("{"):
            meta[k] = _fm_parse_inline(rest)
            cur_list = None
        elif rest.lstrip("-").isdigit() and rest not in ("", "-"):
            meta[k] = int(rest)
            cur_list = None
        else:
            meta[k] = _fm_unq(rest)
            cur_list = None
    body = "\n".join(lines[end + 1:])
    return meta, body


def parse_overview(text: str) -> dict:
    """把 overview.md 解析成结构化数据。OKF frontmatter 优先，旧散文元行回退。"""
    meta_fm, body = parse_frontmatter(text)
    meta = {"updated": "", "sources": 0, "confidence": "low",
            "status": "stable", "verified": "unverified", "stale_after": "",
            "id": "", "generated": {}, "source_reports": [],
            "category": "ai", "category_label": CATEGORIES["ai"], "tags": []}
    title = ""
    if meta_fm:
        title = str(meta_fm.get("title", ""))
        gen = meta_fm.get("generated", {})
        meta["updated"] = gen.get("at", "") if isinstance(gen, dict) else ""
        meta["sources"] = meta_fm.get("sources_count", len(meta_fm.get("source_reports", [])))
        meta["confidence"] = str(meta_fm.get("confidence", "low"))
        meta["status"] = str(meta_fm.get("status", "stable"))
        meta["verified"] = str(meta_fm.get("verified", "unverified"))
        meta["stale_after"] = str(meta_fm.get("stale_after", ""))
        meta["id"] = str(meta_fm.get("id", ""))
        meta["generated"] = gen
        meta["source_reports"] = meta_fm.get("source_reports", []) or []
        # 分类规格 §1：category 枚举校验，非法/缺失兜底 ai；tags 0-5 个，空则 []
        _cat = str(meta_fm.get("category", "ai")).strip()
        if _cat not in CATEGORIES:
            _cat = "ai"
        meta["category"] = _cat
        meta["category_label"] = CATEGORIES[_cat]
        meta["tags"] = [str(t).strip() for t in (meta_fm.get("tags") or [])
                        if str(t).strip()][:5]
    sections, cur, scan = [], None, (body if meta_fm else text)
    for line in scan.splitlines():
        if line.startswith("# "):
            if not title:
                title = line[2:].strip()
        elif line.startswith("> "):
            m = re.search(r"Updated: ([\d-]+)", line)
            if m: meta["updated"] = m.group(1)
            m = re.search(r"Sources: (\d+)", line)
            if m: meta["sources"] = int(m.group(1))
            m = re.search(r"Confidence: (\w+)", line)
            if m: meta["confidence"] = m.group(1)
        elif line.startswith("## "):
            cur = {"label": line[3:].strip(), "items": []}
            sections.append(cur)
        elif line.startswith("- ") and cur is not None:
            item = line[2:].strip()
            sm = re.search(r"\[([^\]]+)\]$", item)
            src = sm.group(1) if sm else ""
            cur["items"].append({"text": _strip_tags(re.sub(r"\s*\[[^\]]+\]$", "", item)), "source": src})
        elif cur is not None and line.strip():
            cur["items"].append({"text": _strip_tags(line.strip()), "source": ""})
    return {"title": title, **meta, "sections": sections}


# ============================================================
# P3：知识条目原子化（VK atomization）——overview.md → items.json
# 只加同目录 items.json 孪生文件，不碰 overview.md 正文。
# ============================================================

# 小节名 → kind（兼容新旧节名：spec 的「结论/常见陷阱」与现有 overview 实况的「核心要点/陷阱与反模式」）
_SECTION_KINDS = {
    "结论": "conclusion",
    "核心要点": "conclusion",
    "关键数据": "data",
    "常见陷阱": "trap",
    "陷阱与反模式": "trap",
    "陷阱": "trap",
}
_KIND_SHORT = {"conclusion": "c", "data": "d", "trap": "t"}


def _item_sources(text: str) -> list[str]:
    """从条目文本抠来源标记：优先 [来源: xxx]（可顿号/逗号多个），否则行尾 [slug]。"""
    m = re.search(r"\[来源\s*[:：]\s*([^\]]+)\]", text)
    if m:
        return [s.strip() for s in re.split(r"[、,，]", m.group(1)) if s.strip()]
    m = re.search(r"\[([^\]]+)\]\s*$", text)
    if m:
        return [m.group(1).strip()]
    return []


def _extract_items(topic: str, md_text: str) -> list[dict]:
    """overview.md → 知识条目列表 [{id, kind, text, sources, anchors}]。
    B 阶段重构：不再需要 domain 参数。

    - kind: conclusion / data / trap，按节识别（## 结论 / ## 关键数据 / ## 常见陷阱）
    - id: {topic}#{kind_short}{n}，n 按 kind 独立从 1 递增（conclusion→c, data→d, trap→t）
    - sources: 条目里的 [来源: xxx] 或行尾 [slug] 标记解析出的报告名数组
    - anchors: 空数组（升级槽位）

    纯解析不写盘；items.json 由调用方落盘。其他节（概述/来源/综合/分歧/使用写回）不产条目。"""
    _, body = parse_frontmatter(md_text)
    items: list[dict] = []
    counters: dict[str, int] = {"conclusion": 0, "data": 0, "trap": 0}
    current_kind: str | None = None
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        h = re.match(r"^##\s+(.+)$", line)
        if h:
            current_kind = _SECTION_KINDS.get(h.group(1).strip())
            continue
        if current_kind is None:
            continue
        text = line[2:].strip() if line.startswith("- ") else line
        sources = _item_sources(text)
        text = re.sub(r"\s*\[[^\]]+\]\s*$", "", text).strip()
        if not text:
            continue
        counters[current_kind] += 1
        items.append({
            "id": f"{topic}#{_KIND_SHORT[current_kind]}{counters[current_kind]}",
            "kind": current_kind,
            "text": text,
            "sources": sources,
            "anchors": [],
        })
    return items


def _write_items_json(topic: str, md_text: str) -> Path:
    """overview.md 内容 → 同目录 items.json（P3 原子化；只加孪生文件，不碰 overview.md）。
    B 阶段重构：_topic_dir 不再需要 domain 参数。"""
    items = _extract_items(topic, md_text)
    out = _topic_dir(topic) / "items.json"
    out.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


# P3 前端抢救：_src_link 已迁入 ui.py，此处保留别名
def _src_link(src: str) -> str:
    return ui._src_link(src)


def _ingest_topic(name: str, ov: dict,
                  topics_by_cat: dict[str, list],
                  topics_flat: dict[str, list[dict]]) -> None:
    """将一个主题加入 topics_by_cat 与 topics_flat，供 build_knowledge_page 索引页拼装。"""
    cat = ov.get("category", "ai")
    topics_by_cat[cat].append((name, ov))
    # 展平为轻索引行所需字段
    one_liner = ""
    for s in ov.get("sections", []):
        if s.get("label") in ("一句话结论", "概述") and s.get("items"):
            one_liner = s["items"][0].get("text", "")
            break
    topics_flat[cat].append({
        "slug": name,
        "title": ov.get("title", name),
        "one_liner": one_liner,
        "sources": ov.get("sources", 1),
        "confidence": ov.get("confidence", "low"),
        "verified": ov.get("verified", "unverified"),
        "category": cat,
        "entry_url": f"/knowledge/{name}.html",
    })


def build_knowledge_page() -> Path:
    """汇总 knowledge/ 全部主题，渲染藏书楼单页 → public/knowledge/index.html。
    P3 前端抢救：模板从 views/knowledge.html 加载，卡片片段用 ui.py。
    P4 分类规格 §3：分区键 category（专栏枚举）；chips 走 data-c 契约。
    B 阶段重构：扁平扫描 knowledge/ 下所有 topic 目录（不再按 domain 分层）。
    B 方案轻索引：主题行格式（标题+一句话结论+来源数+信任徽章），替代旧 kcard 全文平铺。
    每 topic 展平为 {slug,title,one_liner,sources,confidence,verified,category,entry_url}。"""
    topics_by_cat: dict[str, list] = {k: [] for k in CATEGORIES}
    topics_flat: dict[str, list[dict]] = {k: [] for k in CATEGORIES}  # B 方案：展平 dict 列表
    total_sources = total_disag = total_synth = 0
    # P2：写回次数批量查（一次查完，卡片渲染用；循环可见，规格 §6④）
    conn = store.get_db()
    try:
        fb_counts = store.feedback_counts(conn)
    finally:
        conn.close()
    if KNOWLEDGE_DIR.exists():
        for tdir in sorted(KNOWLEDGE_DIR.iterdir()):
            if not tdir.is_dir() or tdir.name.startswith("."):
                continue
            ovf = tdir / "overview.md"
            # 兼容旧 domain 子目录（tech/topic/overview.md）：若 tdir 不含 overview.md，
            # 且是目录，则深入一层找子 topic 目录（B 阶段扁平化前过渡）
            if not ovf.exists():
                subtopics = [sd for sd in sorted(tdir.iterdir())
                             if sd.is_dir() and not sd.name.startswith(".")]
                for tdir2 in subtopics:
                    ovf2 = tdir2 / "overview.md"
                    if not ovf2.exists():
                        continue
                    ov = parse_overview(ovf2.read_text(encoding="utf-8"))
                    _ingest_topic(tdir2.name, ov, topics_by_cat, topics_flat)
                    total_sources += ov["sources"]
                    for s in ov["sections"]:
                        if s["label"] == "分歧": total_disag += len(s["items"])
                    if ov["sources"] >= 2:
                        total_synth += 1
                continue
            ov = parse_overview(ovf.read_text(encoding="utf-8"))
            _ingest_topic(tdir.name, ov, topics_by_cat, topics_flat)
            total_sources += ov["sources"]
            for s in ov["sections"]:
                if s["label"] == "分歧": total_disag += len(s["items"])
            if ov["sources"] >= 2:
                total_synth += 1
    ntopics = sum(len(v) for v in topics_by_cat.values())

    # 专栏 chips（全部 + 五专栏，data-c 契约；含 0 计数，筛选态稳定）
    chips_html = "\n".join(ui.knowledge_chips_html(topics_by_cat))
    # B 方案：锚点导航
    anchors_html = "\n".join(ui.knowledge_anchors_html(topics_by_cat))
    sections_html = []
    for cat, topics in topics_flat.items():
        if not topics:
            continue
        sections_html.append(ui.knowledge_pavilion_html(cat, topics))
    if not sections_html:
        sections_html.append('<p class="none reveal">知识库还是空的——提交报告后跑 <code>python3 distill.py</code>。</p>')

    tpl = ui.load_view("knowledge.html")
    out = (tpl
           .replace("__TOPICS__", str(ntopics))
           .replace("__SOURCES__", str(total_sources))
           .replace("__DISAGREE__", str(total_disag))
           .replace("__SYNTH__", str(total_synth))
           .replace("__CHIPS__", chips_html)
           .replace("__ANCHORS__", anchors_html)
           .replace("__SECTIONS__", "\n".join(sections_html))
           .replace("__GEN__", datetime.now().strftime("%Y-%m-%d %H:%M")))
    out_dir = PUBLIC_DIR / "knowledge"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(out, encoding="utf-8")
    return out_path


# ============================================================
# 主流程
# ============================================================

def distill():
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    if CLEAN:
        # B 阶段重构：清空 knowledge/ 下所有 topic 目录（扁平结构）
        if KNOWLEDGE_DIR.exists():
            for sub in KNOWLEDGE_DIR.iterdir():
                if sub.is_dir() and not sub.name.startswith("."):
                    shutil.rmtree(sub)
        print("[clean] 已清空 knowledge/")
    reports = scan_reports()
    if LLM_ON:
        print(f"[LLM 编译模式] model={DISTILL_MODEL}")
        _run_compiled(reports)
    else:
        print("[规则模式] 未设 AIMETER_KEY，走 1:1 增量蒸馏")
        _run_incremental(reports)
    if not DRY_RUN:
        page = build_knowledge_page()
        print(f"藏书楼视图: {page.relative_to(REPO_DIR)}")
        entry_paths = build_entry_pages()
        print(f"词条页: {len(entry_paths)} 篇")


def _md_tag(md_content: str) -> str:
    """md 孪生的 tag：首行 `_..._` 斜体 kicker（html_to_md 把 <div class=kicker> 映成它）。"""
    m = re.match(r"\A_(.+)_\s*$", md_content)
    return m.group(1).strip() if m else ""


def _run_incremental(reports: list):
    """规则路径：增量，1 报告 = 1 主题（无 key 时的兑底，保留原行为）。
    B 阶段重构：只蒸 category==research 的报告；统一用 extract_tech_md。
    P2：报告循环后追加反馈 sweep——adopted 写回进 overview，翻案即删（规格 §6③）。"""
    done = processed_files()
    log_entries, stats = [], {"skipped": 0, "processed": 0, "items": 0}
    for r in reports:
        fname, category, source = r["file"], r["category"], r["file"]
        if fname in done:
            continue
        if category != _DISTILL_CATEGORY:
            log_entries.append(f"[x] {fname} — skipped (category={category})")
            stats["skipped"] += 1
            continue
        items = extract_tech_md(r["content"], source)
        if not items:
            log_entries.append(f"[x] {fname} — processed, 0 items extracted")
            stats["processed"] += 1
            continue
        write_knowledge(r["slug"], r["title"], items, source)
        log_entries.append(f"[x] {fname} — {r['slug']}/ → {len(items)} items")
        stats["processed"] += 1
        stats["items"] += len(items)
    # P2：反馈回灌（新报告已处理/无新报告都要跑——反馈状态随时会变）
    fb_entries = _sweep_feedbacks()
    log_entries += fb_entries
    if log_entries:
        if not DRY_RUN:
            append_log(log_entries); update_index()
        print(f"蒸馏完成: {stats['processed']} 篇处理, {stats['skipped']} 篇跳过, "
              f"{stats['items']} 条知识, {len(fb_entries)} 个主题反馈更新")
        if DRY_RUN:
            print("(dry-run, 未落盘)")
            for e in log_entries: print(f"  {e}")
    else:
        print("无新报告需要蒸馏")


def _run_compiled(reports: list):
    """LLM 路径：规则抽骨架 → LLM 语义聚类 → 每主题综合+矛盾 → 全量重编译。
    B 阶段重构：只蒸 category==research 的报告；cluster 不再带 domain 字段。
    P2（规格 §6③）：每主题编译输入 += 该主题 adopted 反馈（直查 store，防环）；
    消费的 id 记 [fb] 日志；全量重编译天然覆盖翻案（adopted→rejected 下轮自动生效）。"""
    members_data = {}
    for r in reports:
        category = r["category"]
        tag = _md_tag(r["content"])  # P2：输入换 .md 后从 md kicker 读 tag
        if category != _DISTILL_CATEGORY:
            continue
        if tag.upper().startswith("META"):
            continue  # 卷首/关于本书，非知识，不蒸馏
        items = extract_tech_md(r["content"], r["file"])
        if not items:
            continue  # 抽不到骨架的不进编译
        members_data[r["slug"]] = {"title": r["title"], "category": category, "items": items, "file": r["file"]}
    if not members_data:
        print("无可编译报告"); return

    catalog = [{"slug": s, "title": m["title"], "items": m["items"], "category": m["category"]}
               for s, m in members_data.items()]
    anchors = _load_existing_concepts()  # 增量聚类：读现有概念作锚点（CLEAN 后为空→全量）
    if anchors:
        print(f"  增量聚类锚点: {len(anchors)} 个已有概念")
    clusters = llm_cluster(catalog, anchors)
    if not clusters:
        print("  ! LLM 聚类不可用（网关抖动），用启发式兆底聚类")
        clusters = _heuristic_cluster(catalog)
    if not clusters:
        print("无可聚类内容"); return

    # 容错增量：不清空旧目录。compile 成功的主题写盘，失败的保留旧内容（write 内部判空不写）。
    # 多次跑可累积成功编译；网关抖动时不会拿空页/垃圾覆盖已有的好内容。

    n_synth = n_contra = n_fail = 0
    fb_log_entries = []
    conn = store.get_db()
    try:
        for c in clusters:
            ms = c["members"]
            payload = [{"slug": s, "title": members_data[s]["title"],
                        "conclusions": [it["text"] for it in members_data[s]["items"] if it["kind"] == "conclusion"],
                        "traps": [it["text"] for it in members_data[s]["items"] if it["kind"] == "trap"],
                        "data": [it["text"] for it in members_data[s]["items"] if it["kind"] == "data"]}
                       for s in ms]
            # P2：主题目录 id 即反馈 topic——先算 id 再查 adopted（与 write 时的 _safe_slug 同参，恒等）
            tid = _safe_slug(c["topic"], ms, c.get("id", ""))
            fbs = store.adopted_feedbacks(conn, tid)
            compiled = llm_compile_topic(c["topic"], payload, fbs)
            n_contra += len(compiled["contradictions"])
            if not DRY_RUN:
                written = write_knowledge_compiled(c, members_data, compiled, fbs)
                if written:
                    if compiled["summary"] or compiled["points"]: n_synth += 1
                    if fbs:  # 消费落日志：防重复 + 翻案对比基线（规格 §6③）
                        fb_log_entries.append(
                            f"[fb] {tid} consumed: " + ",".join(str(f["id"]) for f in fbs))
                else:
                    n_fail += 1  # compile 无实质内容，保留旧 overview（反馈本轮未消费，不记日志）
    finally:
        conn.close()
    if not DRY_RUN:
        append_log([f"[compiled] {datetime.now().strftime('%Y-%m-%d %H:%M')} "
                    f"model={DISTILL_MODEL} topics={len(clusters)} synth={n_synth} contra={n_contra} fail={n_fail}"]
                   + fb_log_entries)
        update_index()
    print(f"LLM 编译完成: {len(members_data)} 篇 → {len(clusters)} 主题, 综合 {n_synth}, 分歧 {n_contra}, 失败保留旧 {n_fail}")

if __name__ == "__main__":
    distill()
