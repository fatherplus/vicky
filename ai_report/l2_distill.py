#!/usr/bin/env python3
"""
蒸馏器 — 从 HTML 报告中提取结构化知识，维护 knowledge/ Wiki。
L2 知识层（P0 包化：从 distill.py 搬迁，行为零变化）。

用法: python3 -m ai_report.cli distill [--dry-run]

流程（对应治理链路 关2-3）：
  1. 扫描 public/reports/*.html，对比 log.md 已处理列表
  2. 按 domain 路由：ephemeral 跳过、tech/design 进提取
  3. 提取知识条目（结论/被否假设/陷阱/数据），每条标来源
  4. AGREE 追加到 knowledge/{domain}/{topic}/overview.md
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


def extract_design(html_content: str, source: str) -> list[dict]:
    """从 HTML 报告提取设计知识条目（规则版）。

    提取四类：反模式 / 风格锚点 / 工具链 / 样本
    # ponytail: 规则版证明管线；LLM prompt 版等有真实设计报告积累后再调
    """
    items = []
    # 反模式：callout warn + 含「不要/禁止/避免/不许」的 blockquote
    for text in _extract_callouts(html_content, "warn"):
        items.append({"kind": "trap", "text": text, "source": source})
    for text in _extract_blockquotes(html_content):
        if re.search(r"不要|禁止|避免|不许|不能|别用", text):
            items.append({"kind": "trap", "text": text, "source": source})
        else:
            items.append({"kind": "conclusion", "text": text, "source": source})
    # 工具链：code 块中的 npx/npm/pip 命令
    for m in re.findall(r"<code>([^<]*(?:npx|npm|pip)[^<]*)</code>", html_content):
        items.append({"kind": "data", "text": f"工具: {html_mod.unescape(m).strip()}", "source": source})
    # 样本：figure 中的 img src（风格参考图）
    for m in re.findall(r'<img[^>]+src="([^"]+)"', html_content):
        if "/assets/img/" in m:
            items.append({"kind": "data", "text": f"风格样本: {m}", "source": source})
    return items


EXTRACTORS = {"tech": extract_tech, "design": extract_design}


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
    # 截取首个 [ 或 { 到末尾对应括号
    for open_c, close_c in (("[", "]"), ("{", "}")):
        i, j = t.find(open_c), t.rfind(close_c)
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except Exception:
                continue
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
    """宽容归一化 LLM 聚类输出，并解析概念 id（命中锚点才认，防幻觉 id）。"""
    anchors = anchors or []
    anchor_by_id = {a["id"]: a for a in anchors if a.get("id")}
    slug_domain = {r["slug"]: r["domain"] for r in reports}
    slug_title = {r["slug"]: r["title"] for r in reports}
    valid = set(slug_domain)
    groups = []  # (cid, topic, [slugs], domain|None)
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list):
                groups.append(("", str(k), [x for x in v if isinstance(x, str)], None))
            elif isinstance(v, dict):
                groups.append(("", str(k), [x for x in v.get("members", []) if isinstance(x, str)], v.get("domain")))
    elif isinstance(data, list):
        for c in data:
            if isinstance(c, dict):
                ms = c.get("members") or c.get("slugs") or []
                groups.append((str(c.get("id", "") or ""), str(c.get("topic", "")),
                               [x for x in ms if isinstance(x, str)], c.get("domain")))
            elif isinstance(c, list):
                groups.append(("", "", [x for x in c if isinstance(x, str)], None))
    out, seen = [], set()
    for cid, topic, slugs, dom in groups:
        members = [s for s in slugs if s in valid and s not in seen]
        if not members:
            continue
        seen.update(members)
        if dom not in ("tech", "design"):
            from collections import Counter
            dom = Counter(slug_domain[s] for s in members).most_common(1)[0][0]
        rid = cid if cid in anchor_by_id else ""  # 只认锚点里的 id，其余当新概念
        if not topic.strip():
            topic = (anchor_by_id[rid]["title"] if rid else
                     "、".join(slug_title[s] for s in members[:2]) + (" 等" if len(members) > 2 else ""))
        out.append({"id": rid, "topic": topic.strip(), "domain": dom, "members": members})
    for r in reports:
        if r["slug"] not in seen:
            out.append({"id": "", "topic": r["title"], "domain": r["domain"], "members": [r["slug"]]})
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
        "domain 只能是 tech 或 design；" + id_rule +
        "只输出 JSON 数组，不要任何解释。每个元素是含 id/topic/domain/members 的对象，禁止只输出 slug 数组。形如："
        '[{"id":"","topic":"向量检索","domain":"tech","members":["hnsw-algorithm"]},'
        '{"id":"usage--abc","topic":"用量分析","domain":"tech","members":["aws-claude-usage"]}]\n\n')
    raw = llm_chat([{"role": "user", "content": prompt}], max_tokens=6000, timeout=200)
    if not raw:
        return []
    data = _parse_json_loose(raw)
    if data is None:
        return []
    return _norm_clusters(data, batch, anchors)


def _load_existing_concepts() -> list:
    """读现有 knowledge 概念作增量聚类锚点（id + title + members）。兼容新旧格式。"""
    anchors = []
    for domain in ("tech", "design"):
        ddir = KNOWLEDGE_DIR / domain
        if not ddir.exists():
            continue
        for tdir in sorted(ddir.iterdir()):
            ovf = tdir / "overview.md"
            if not tdir.is_dir() or not ovf.exists():
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
    """全局语义聚类：分批（每批 12 篇）+ 跨批合并（id 优先，其次 topic 名）。失败返回 None。"""
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
            merged[key] = {"id": c["id"], "topic": c["topic"], "domain": c["domain"], "members": list(c["members"])}
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
            out.append({"id": "", "topic": r["title"], "domain": r["domain"], "members": [r["slug"]]})
    return out


def _heuristic_cluster(catalog: list) -> list:
    """启发式兆底聚类：网关不可用时按关键词把报告聚成多源主题。
    不完美但保证多源分组成立，比 1:1 垃圾强；网关恢复后 LLM 聚类会覆盖它。"""
    BUCKETS = [  # (主题名, domain, 关键词)
        ("向量检索与 RAG", "tech", ["rag", "retrieval", "top-k", "topk", "hnsw", "向量", "检索", "lightrag", "embed"]),
        ("Agent 记忆与上下文", "tech", ["memory", "hindsight", "记忆", "weaver", "上下文"]),
        ("图谱与知识库基础设施", "tech", ["pggraph", "pgcontext", "图谱", "graph", "gamekb", "知识库"]),
        ("用量与成本治理", "tech", ["用量", "usage", "cost", "成本", "aimeter", "治理", "token"]),
        ("Agent 工程工具链", "tech", ["codegraph", "ponytail", "context7", "skill", "工具链"]),
        ("知识数据源配置", "tech", ["knowledge-sources", "数据源", "知识源"]),
    ]
    groups = {name: {"topic": name, "domain": dom, "members": []} for name, dom, _ in BUCKETS}
    used = set()
    for r in catalog:
        hay = (r["slug"] + " " + r["title"]).lower()
        placed = False
        for name, dom, kws in BUCKETS:
            if any(k in hay for k in kws):
                groups[name]["members"].append(r["slug"]); used.add(r["slug"]); placed = True; break
        if not placed:
            groups[r["title"]] = {"topic": r["title"], "domain": r["domain"], "members": [r["slug"]]}
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
def llm_compile_topic(topic: str, members: list) -> dict:
    """LLM 读各篇原文，为主题编译一整篇浓缩 wiki（结构化 JSON）。
    返回 {summary, points:[..], data:[..], traps:[..], contradictions:[{point,sides}]}。
    正文主体全部由 LLM 从原文编译，不再拼规则抽取的碎片。"""
    blocks = []
    for m in members:
        # 喂规则抽的结构化摘要（短，网关能跑），而非全文 excerpt（长，整跑负载下网关 400/思考链爆）
        parts = ([f"    · 结论: {t}" for t in (m.get("conclusions") or [])]
                 + [f"    · 陷阱: {t}" for t in (m.get("traps") or [])]
                 + [f"    · 数据: {t}" for t in (m.get("data") or [])])
        if not parts:
            parts = ["    · （无结构化摘要）"]
        blocks.append(f"[{m['slug']}] 《{m['title']}》\n" + "\n".join(parts))
    body = "\n\n".join(blocks)
    n = len(members)
    cross = "交叉综合这些来源的共识、互补与演进脉络" if n >= 2 else "提炼这篇报告的核心知识"
    prompt = (
        f"你是知识库编辑，正在为主题『{topic}』编译一篇浓缩 wiki，材料来自 {n} 篇报告的结构化摘要（结论/陷阱/数据，每段以 [slug] 标注来源）。\n"
        f"请{cross}，产出一份读者读完即懂该主题的完整浓缩内容。要求：写实质内容，含具体机制/数字/名称，不要废话套话，不要说『缺乏结论』；"
        "每条要点/数据/陷阱末尾用 [slug] 标注它出自哪篇（可多个）。\n"
        "输出一个 JSON 对象，字段：\n"
        '- summary: 字符串，2-4 句概述该主题是什么、解决什么问题、各来源如何互补或演进；\n'
        '- points: 字符串数组，核心要点（3-8 条），每条一句实质陈述，编译自原文，不要照抄标题；\n'
        '- data: 字符串数组，真正有意义的数字/事实/对比（0-6 条），只收有信息量的，禁止空泛行；\n'
        '- traps: 字符串数组，陷阱/反模式/踩坑点（0-5 条）；\n'
        '- contradictions: 数组，来源间真正的观点冲突，每项 {point, sides:[\"[slugX] 原话\",...]}；无则空数组。\n'
        '只输出该 JSON 对象，不要任何解释。\n\n' + body)
    raw = llm_chat([{"role": "user", "content": prompt}], max_tokens=3000, timeout=300)
    empty = {"summary": "", "points": [], "data": [], "traps": [], "contradictions": []}
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
    return {
        "summary": str(data.get("summary", "")).strip(),
        "points": strs("points", 8),
        "data": strs("data", 6),
        "traps": strs("traps", 5),
        "contradictions": contra,
    }

# ============================================================
# 报告扫描与路由
# ============================================================

def _read_meta(html_content: str, name: str) -> str:
    m = re.search(rf'<meta name="{name}" content="([^"]*)"', html_content)
    return m.group(1) if m else ""


def scan_reports() -> list[dict]:
    """扫描 reports/，返回 [{file, domain, slug, title}]"""
    if not REPORTS_DIR.exists():
        return []
    out = []
    for f in sorted(REPORTS_DIR.glob("*.html")):
        content = f.read_text(encoding="utf-8")
        domain = _read_meta(content, "domain") or "tech"
        slug_m = re.match(r"\d{4}-\d{2}-\d{2}-(.+)\.html", f.name)
        slug = slug_m.group(1) if slug_m else f.stem
        title_m = re.search(r"<title>(.+?)</title>", content)
        title = title_m.group(1) if title_m else f.name
        out.append({"file": f.name, "path": f, "domain": domain,
                    "slug": slug, "title": title, "content": content})
    return out


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


def _topic_dir(domain: str, slug: str) -> Path:
    """知识目录：knowledge/{domain}/{slug}/"""
    return KNOWLEDGE_DIR / domain / slug


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


def write_knowledge(domain: str, slug: str, title: str,
                    items: list[dict], source: str) -> Path:
    """KSI 进化：AGREE 追加 / DISAGREE 标记分歧 / SYNTHESIZE 综合"""
    tdir = _topic_dir(domain, slug)
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
    return overview


def write_knowledge_compiled(cluster: dict, members_data: dict,
                             compiled: dict | None) -> Path:
    """LLM 编译路径：写一个语义主题的 overview.md（多源聚合 + 交叉引用）。"""
    topic, domain, member_slugs = cluster["topic"], cluster["domain"], cluster["members"]
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
        "id": slug, "title": topic, "type": "Topic", "domain": domain,
        "status": "stable",
        "generated": {"by": f"agent:{model_tag}", "at": today},
        "verified": verified, "sources_count": n, "stale_after": stale_after,
        "confidence": conf,
        "source_reports": list(dict.fromkeys(member_slugs)),
    }

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
    lines.append("")

    tdir = _topic_dir(domain, slug)
    tdir.mkdir(parents=True, exist_ok=True)
    overview = tdir / "overview.md"
    overview.write_text(dump_frontmatter(meta) + "\n".join(lines), encoding="utf-8")
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
    """重建 index.md：每个知识页一行"""
    lines = ["# 知识索引", "",
             f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    count = 0
    for domain_dir in sorted(KNOWLEDGE_DIR.iterdir()):
        if not domain_dir.is_dir() or domain_dir.name.startswith("."):
            continue
        domain = domain_dir.name
        for topic_dir in sorted(domain_dir.iterdir()):
            if not topic_dir.is_dir():
                continue
            overview = topic_dir / "overview.md"
            if not overview.exists():
                continue
            first_line = overview.read_text(encoding="utf-8").splitlines()[0]
            title = first_line.lstrip("# ").strip()
            src_m = re.search(r"Sources: (\d+)", overview.read_text(encoding="utf-8"))
            src = src_m.group(1) if src_m else "?"
            lines.append(f"- **[{domain}]** {title} — {src} source(s) → `{domain}/{topic_dir.name}/`")
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
# 藏书楼视图（knowledge/ → public/knowledge/index.html）
# ============================================================

CONF_SEAL = {"high": ("可信", "hi"), "medium": ("可参", "mid"), "low": ("存疑", "lo")}
VER_LABEL = {"unverified": ("未验证", "v-unv"), "machine-confirmed": ("机确认", "v-mach"),
             "human-reviewed": ("人审", "v-human")}  # OKF 信任层级
DOMAIN_NAME = {"tech": "tech 阁", "design": "design 阁"}
SEC_CLS = {"结论": "concl", "被否假设": "refut", "陷阱": "trap",
           "关键数据": "data", "分歧": "disag", "综合": "synth",
           "一句话结论": "concl", "共识": "agree", "来源": "src",
           "概述": "concl", "核心要点": "concl", "陷阱与反模式": "trap"}
# 结构性节（不进 KSI 计数徽章行，只作正文展示）
STRUCT_SECS = {"一句话结论", "概述", "来源"}

_KNOWLEDGE_TPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>藏书楼 · 知识库 — ai-report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@600;900&family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{--paper:#FBFAF7;--ink:#23272E;--sub:#6E7278;--accent:#0C4A6E;--seal:#A63A2E;
  --green:#2E7D4F;--amber:#B08D57;--hairline:rgba(0,0,0,.08);--card:#FDFCF9;
  --serif:'Noto Serif SC',serif;--sans:'Noto Sans SC',-apple-system,'PingFang SC',sans-serif;
  --mono:'JetBrains Mono','SF Mono',Menlo,monospace;}
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.7;
  -webkit-font-smoothing:antialiased;}
/* 栏线：古籍页面边框，双线 */
body::before{content:"";position:fixed;inset:14px;border:1px solid var(--hairline);pointer-events:none;z-index:50}
body::after{content:"";position:fixed;inset:19px;border:1px solid rgba(0,0,0,.045);pointer-events:none;z-index:50}
::selection{background:rgba(12,74,110,.16)}
.wrap{max-width:1080px;margin:0 auto;padding:0 44px}

/* ===== 卷首：藏印 + 账本 ===== */
.masthead{display:grid;grid-template-columns:auto 1fr auto;gap:36px;align-items:center;
  padding:72px 0 40px;border-bottom:2px solid var(--ink);position:relative}
.masthead::after{content:"";position:absolute;left:0;right:0;bottom:-6px;height:1px;background:var(--hairline)}
.seal-big{width:96px;height:96px;background:var(--seal);color:#FBFAF7;font-family:var(--serif);
  font-size:52px;font-weight:900;display:flex;align-items:center;justify-content:center;
  border-radius:8px;transform:rotate(-4deg);box-shadow:inset 0 0 0 3px rgba(251,250,247,.28),
  inset 0 0 18px rgba(0,0,0,.18),0 4px 14px rgba(166,58,46,.3);user-select:none;
  transition:transform .4s cubic-bezier(.34,1.56,.64,1)}
.masthead:hover .seal-big{transform:rotate(0deg) scale(1.03)}
.kicker{font-family:var(--mono);font-size:11px;letter-spacing:2.5px;color:var(--seal);
  text-transform:uppercase;font-weight:600;margin-bottom:10px}
h1{font-family:var(--serif);font-size:56px;font-weight:900;letter-spacing:6px;line-height:1.1}
.mast-sub{color:var(--sub);font-size:14px;margin-top:12px;max-width:460px}
.ledger{display:grid;grid-template-columns:repeat(2,minmax(96px,auto));gap:0;border-left:1px solid var(--hairline);padding-left:36px}
.stat{padding:10px 22px 10px 0;border-bottom:1px dashed var(--hairline)}
.stat:nth-child(even){border-left:1px dashed var(--hairline);padding-left:22px}
.stat:nth-child(3),.stat:nth-child(4){border-bottom:none}
.stat-n{display:block;font-family:var(--mono);font-size:30px;font-weight:600;color:var(--accent);line-height:1.1}
.stat:nth-child(3) .stat-n{color:var(--seal)}
.stat:nth-child(4) .stat-n{color:var(--green)}
.stat-l{font-size:11px;color:var(--sub);letter-spacing:1px}

/* ===== 检索 + 筛选 ===== */
.toolbar{position:sticky;top:0;z-index:40;background:rgba(251,250,247,.92);backdrop-filter:blur(6px);
  display:flex;gap:16px;align-items:center;padding:18px 0;border-bottom:1px solid var(--hairline)}
.search{flex:0 0 260px;font-family:var(--sans);font-size:14px;padding:9px 14px;border:1px solid var(--hairline);
  border-bottom:2px solid var(--sub);background:transparent;color:var(--ink);border-radius:2px;
  transition:border-color .2s,box-shadow .2s;outline:none}
.search:focus{border-bottom-color:var(--accent);box-shadow:0 2px 0 0 var(--accent)}
.search::placeholder{color:var(--sub)}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{font-size:12.5px;padding:6px 14px;border:1px solid var(--hairline);border-radius:2px;cursor:pointer;
  color:var(--sub);background:transparent;transition:all .2s;user-select:none}
.chip .n{font-family:var(--mono);font-size:10.5px;margin-left:5px;opacity:.7}
.chip:hover{border-color:var(--accent);color:var(--accent);transform:translateY(-1px)}
.chip.on{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.chip.on .n{opacity:.85}

/* ===== 阁（domain 分区）===== */
.pavilion{padding:44px 0 8px}
.pav-head{display:flex;align-items:baseline;gap:14px;margin-bottom:24px}
.pav-tab{width:8px;height:26px;align-self:center;border-radius:1px}
.pav-tab.tech{background:var(--accent)}
.pav-tab.design{background:var(--seal)}
.pav-head h2{font-family:var(--serif);font-size:26px;font-weight:700;letter-spacing:2px}
.pav-count{font-family:var(--mono);font-size:12px;color:var(--sub)}

/* ===== 藏书卡片（masonry）===== */
.cards{column-count:2;column-gap:22px}
@media(max-width:820px){.cards{column-count:1}.masthead{grid-template-columns:auto 1fr}.ledger{display:none}}
.kcard{break-inside:avoid;background:var(--card);border:1px solid var(--hairline);border-radius:3px;
  padding:24px 26px 20px;margin-bottom:22px;position:relative;
  transition:transform .25s ease,box-shadow .25s ease,border-color .25s ease}
.kcard::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;border-radius:3px 0 0 3px;
  background:var(--accent);opacity:.85;transition:width .25s}
.kcard[data-domain=design]::before{background:var(--seal)}
.kcard:hover{transform:translateY(-4px);box-shadow:0 10px 26px rgba(35,39,46,.1);border-color:rgba(0,0,0,.14)}
.kcard:hover::before{width:5px}
.kcard.hide{display:none}
.kcard-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.dtab{font-family:var(--mono);font-size:10px;letter-spacing:1.5px;text-transform:uppercase;
  padding:3px 9px;border-radius:2px;font-weight:600}
.dtab.tech{color:var(--accent);background:rgba(12,74,110,.09)}
.dtab.design{color:var(--seal);background:rgba(166,58,46,.09)}
.conf{font-family:var(--serif);font-size:12px;font-weight:700;padding:3px 10px;border-radius:2px;
  border:1.5px solid;transform:rotate(2deg);letter-spacing:2px;transition:transform .3s}
.kcard:hover .conf{transform:rotate(0deg)}
.conf.hi{color:var(--seal);border-color:var(--seal);background:rgba(166,58,46,.07)}
.conf.mid{color:var(--amber);border-color:var(--amber);background:rgba(176,141,87,.08)}
.conf.lo{color:var(--sub);border-color:var(--sub);opacity:.75}
.ktitle{font-family:var(--serif);font-size:19px;font-weight:700;line-height:1.4;margin-bottom:6px}
.kmeta{font-size:12px;color:var(--sub);margin-bottom:12px}
.kmeta code{font-family:var(--mono);font-size:10.5px;background:rgba(0,0,0,.05);padding:1px 6px;border-radius:2px}
/* OKF 信任徽章 */
.vbadge{font-size:10px;font-weight:600;letter-spacing:.5px;padding:2px 7px;border-radius:2px;border:1px solid;margin-left:6px;vertical-align:1px}
.v-unv{color:var(--sub);border-color:var(--sub);opacity:.8}
.v-mach{color:var(--accent);border-color:rgba(12,74,110,.4);background:rgba(12,74,110,.05)}
.v-human{color:var(--green);border-color:rgba(46,125,79,.45);background:rgba(46,125,79,.06)}
.stale{color:#A63A2E;border-color:rgba(166,58,46,.5);background:rgba(166,58,46,.06);font-size:10px;font-weight:700;padding:2px 7px;border-radius:2px;border:1px solid;margin-left:6px}
.st-deprecated{color:#FBFAF7;background:var(--sub);font-size:10px;font-weight:700;padding:2px 7px;border-radius:2px;margin-left:6px}
.st-draft{color:var(--amber);border-color:rgba(176,141,87,.5);background:rgba(176,141,87,.08);font-size:10px;font-weight:700;padding:2px 7px;border-radius:2px;border:1px solid;margin-left:6px}
.kcard[data-status=deprecated]{opacity:.55;filter:saturate(.6)}
.ksi{display:flex;gap:6px;flex-wrap:wrap;padding-bottom:14px;border-bottom:1px dashed var(--hairline);margin-bottom:14px}
.kbadge{font-size:11px;padding:3px 9px;border-radius:2px;font-weight:500}
.kbadge.concl{color:var(--accent);background:rgba(12,74,110,.09)}
.kbadge.refut{color:var(--sub);background:rgba(0,0,0,.05)}
.kbadge.trap{color:var(--amber);background:rgba(176,141,87,.12)}
.kbadge.data{color:var(--sub);background:rgba(0,0,0,.05);font-family:var(--mono);font-size:10.5px}
.kbadge.disag{color:#FBFAF7;background:var(--seal);font-weight:600}
.kbadge.synth{color:var(--green);background:rgba(46,125,79,.1);font-weight:600}
.kbadge.agree{color:var(--green);background:rgba(46,125,79,.1)}
.kbadge.src{color:var(--sub);background:rgba(0,0,0,.05);font-family:var(--mono);font-size:10.5px}
.ksec{margin-bottom:14px}
.ksec:last-child{margin-bottom:0}
.ksec-l{font-size:11px;font-weight:700;letter-spacing:1.5px;margin-bottom:6px;color:var(--sub)}
.ksec.concl .ksec-l{color:var(--accent)}
.ksec.disag .ksec-l{color:var(--seal)}
.ksec.synth .ksec-l{color:var(--green)}
.ksec.trap .ksec-l{color:var(--amber)}
.ksec ul{list-style:none}
.ksec li{font-size:13.5px;line-height:1.65;padding:5px 0 5px 16px;position:relative;color:var(--ink)}
.ksec li::before{content:"·";position:absolute;left:2px;color:var(--sub);font-weight:700}
.kprose{font-size:13.5px;line-height:1.75;color:var(--ink);margin:0;padding-left:12px;
  border-left:2px solid var(--accent);opacity:.92}
.ksec.disag{border-left:2px solid var(--seal);padding-left:12px;margin-left:-14px;background:rgba(166,58,46,.035);padding-top:8px;padding-bottom:8px;border-radius:0 2px 2px 0}
.ksec.synth{border-left:2px solid var(--green);padding-left:12px;margin-left:-14px;background:rgba(46,125,79,.04);padding-top:8px;padding-bottom:8px;border-radius:0 2px 2px 0}
.ksec.agree{border-left:2px solid var(--green);padding-left:12px;margin-left:-14px;background:rgba(46,125,79,.04);padding-top:8px;padding-bottom:8px;border-radius:0 2px 2px 0}
.ksec.src{border-top:1px dashed var(--hairline);padding-top:12px;margin-top:4px}
.ksec.src .ksec-l{color:var(--sub)}
.ksec.src li{font-size:12.5px}
.ksec.src li::before{content:"→";color:var(--accent);font-size:11px}
.src{font-family:var(--mono);font-size:10px;color:var(--accent);text-decoration:none;
  border-bottom:1px dotted var(--accent);opacity:.75;transition:opacity .2s;white-space:nowrap}
.src:hover{opacity:1}

/* ===== 空态 / 书尾 ===== */
.none{text-align:center;color:var(--sub);padding:80px 0;font-size:14px}
.none code{font-family:var(--mono);background:rgba(0,0,0,.05);padding:2px 8px;border-radius:2px}
#empty{display:none;text-align:center;color:var(--sub);padding:60px 0;font-size:14px}
#empty.show{display:block}
.colophon{margin-top:60px;padding:28px 0 44px;border-top:2px solid var(--ink);display:flex;
  justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--sub)}
.colophon a{color:var(--accent);text-decoration:none;border-bottom:1px solid rgba(12,74,110,.3);transition:border-color .2s}
.colophon a:hover{border-bottom-color:var(--accent)}
.colophon code{font-family:var(--mono);background:rgba(0,0,0,.05);padding:1px 6px;border-radius:2px}

/* ===== 动效（克制）===== */
.reveal{opacity:0;transform:translateY(16px);transition:opacity .6s ease,transform .6s cubic-bezier(.22,1,.36,1)}
.reveal.in{opacity:1;transform:translateY(0)}
@media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}.reveal{opacity:1;transform:none}}
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead reveal">
    <div class="seal-big" aria-hidden="true">藏</div>
    <div>
      <div class="kicker">Knowledge Archive · 自动蒸馏</div>
      <h1>藏书楼</h1>
      <p class="mast-sub">从研究报告中蒸馏的可持续知识。每一页由 distill 自动运维，随报告提交而进化。</p>
    </div>
    <div class="ledger">
      <div class="stat"><span class="stat-n" data-count="__TOPICS__">0</span><span class="stat-l">知识主题</span></div>
      <div class="stat"><span class="stat-n" data-count="__SOURCES__">0</span><span class="stat-l">报告来源</span></div>
      <div class="stat"><span class="stat-n" data-count="__DISAGREE__">0</span><span class="stat-l">分歧待裁</span></div>
      <div class="stat"><span class="stat-n" data-count="__SYNTH__">0</span><span class="stat-l">已综合</span></div>
    </div>
  </header>

  <div class="toolbar reveal">
    <input id="q" class="search" type="search" placeholder="检索知识…" aria-label="检索知识">
    <div class="chips">
      <span class="chip on" data-d="all">全部<span class="n">__TOPICS__</span></span>
      <span class="chip" data-d="tech">tech 阁<span class="n">__NTECH__</span></span>
      <span class="chip" data-d="design">design 阁<span class="n">__NDESIGN__</span></span>
    </div>
  </div>

  <main>
__SECTIONS__
    <div id="empty">无匹配的知识条目。</div>
  </main>

  <footer class="colophon">
    <a href="/research/">← 返回目录</a>
    <span>知识由 <code>distill.py</code> 自动蒸馏 · KSI 进化（AGREE · DISAGREE · SYNTHESIZE）· 生成于 __GEN__</span>
  </footer>
</div>

<script>
(function(){
  var q=document.getElementById('q'),chips=[].slice.call(document.querySelectorAll('.chip')),domain='all';
  function apply(){
    var term=q.value.trim().toLowerCase();
    [].forEach.call(document.querySelectorAll('.kcard'),function(c){
      var okD=domain==='all'||c.dataset.domain===domain;
      var okQ=!term||c.dataset.search.indexOf(term)>=0;
      c.classList.toggle('hide',!(okD&&okQ));
    });
    [].forEach.call(document.querySelectorAll('.pavilion'),function(p){
      var any=[].some.call(p.querySelectorAll('.kcard'),function(c){return !c.classList.contains('hide');});
      p.classList.toggle('hide',!any);
    });
    document.getElementById('empty').classList.toggle('show',!document.querySelector('.pavilion:not(.hide)'));
  }
  chips.forEach(function(c){c.addEventListener('click',function(){
    chips.forEach(function(x){x.classList.remove('on');});c.classList.add('on');domain=c.dataset.d;apply();});});
  q.addEventListener('input',apply);
  var io=new IntersectionObserver(function(es){es.forEach(function(e){
    if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target);}});},{threshold:.06});
  [].forEach.call(document.querySelectorAll('.reveal'),function(el){io.observe(el);});
  [].forEach.call(document.querySelectorAll('[data-count]'),function(el){
    var target=+el.dataset.count,t0=null,dur=900;
    function tick(t){if(t0===null)t0=t;var p=Math.min(1,(t-t0)/dur);
      el.textContent=Math.round(target*(1-Math.pow(1-p,3)));if(p<1)requestAnimationFrame(tick);}
    requestAnimationFrame(tick);});
})();
</script>
</body>
</html>"""

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
            "id": "", "generated": {}, "source_reports": []}
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


def _src_link(src: str) -> str:
    """证据锚点 → 报告短链接（去日期前缀，mono 小字）。"""
    if not src:
        return ""
    short = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", src).removesuffix(".html")
    href = src if src.endswith(".html") else src + ".html"
    return (f' <a class="src" href="/research/reports/{html.escape(href)}" '
            f'title="{html.escape(href)}">{html.escape(short)}</a>')


def _render_card(domain: str, topic: str, ov: dict, title_suffix: str = "") -> str:
    conf_label, conf_cls = CONF_SEAL.get(ov["confidence"], ("存疑", "lo"))
    # OKF 信任徽章：verified 层级 + status + 过期（纯视觉提示，不建过滤筹码——0 数据时 YAGNI）
    vlabel, vcls = VER_LABEL.get(ov.get("verified", "unverified"), ("未验证", "v-unv"))
    vbadge = f'<span class="vbadge {vcls}" title="验证层级：{vlabel}">{vlabel}</span>'
    status_tag = {"deprecated": '<span class="st-deprecated">已废弃</span>',
                  "draft": '<span class="st-draft">草稿</span>'}.get(ov.get("status", "stable"), "")
    stale = ""
    sa = ov.get("stale_after", "")
    if sa:
        try:
            if datetime.strptime(sa, "%Y-%m-%d") < datetime.now():
                stale = '<span class="stale" title="已过保鲜期，建议重新验证">已过期</span>'
        except ValueError:
            pass
    trust = f"{vbadge}{status_tag}{stale}"
    # KSI 徽章：只展示存在的节，数量诚实
    badges = []
    for s in ov["sections"]:
        if s["label"] in STRUCT_SECS:
            continue
        cls = SEC_CLS.get(s["label"], "")
        n = len(s["items"])
        if s["label"] == "综合":
            badges.append(f'<span class="kbadge {cls}">综合 ✓</span>')
        elif n:
            badges.append(f'<span class="kbadge {cls}">{html.escape(s["label"])} {n}</span>')
    # 正文分节
    secs = []
    for s in ov["sections"]:
        if not s["items"]:
            continue
        cls = SEC_CLS.get(s["label"], "")
        if s["label"] in ("概述", "一句话结论"):
            prose = " ".join(html.escape(it["text"]) for it in s["items"])
            secs.append(f'<div class="ksec {cls}"><div class="ksec-l">{html.escape(s["label"])}</div>'
                        f'<p class="kprose">{prose}</p></div>')
            continue
        lis = "".join(
            f'<li>{html.escape(it["text"])}{_src_link(it["source"])}</li>' for it in s["items"])
        secs.append(f'<div class="ksec {cls}"><div class="ksec-l">{html.escape(s["label"])}</div>'
                    f'<ul>{lis}</ul></div>')
    search_blob = html.escape((ov["title"] + " " + topic + " " +
                               " ".join(it["text"] for s in ov["sections"] for it in s["items"])).lower(), quote=True)
    return (f'<article class="kcard reveal" data-domain="{domain}" data-status="{ov.get("status", "stable")}" data-search="{search_blob}">'
            f'<div class="kcard-top"><span class="dtab {domain}">{domain}</span>'
            f'<span class="conf {conf_cls}" title="置信度：{conf_label}">{conf_label}</span></div>'
            f'<h3 class="ktitle">{html.escape(ov["title"])}{html.escape(title_suffix)}</h3>'
            f'<div class="kmeta">更新于 {ov["updated"]} · {ov["sources"]} 篇来源 · '
            f'<code>{html.escape(topic)}</code> {trust}</div>'
            f'<div class="ksi">{"".join(badges)}</div>'
            f'<div class="kbody">{"".join(secs)}</div></article>')


def build_knowledge_page() -> Path:
    """汇总 knowledge/ 全部主题，渲染藏书楼单页 → public/knowledge/index.html。"""
    topics_by_domain: dict[str, list] = {"tech": [], "design": []}
    total_sources = total_disag = total_synth = 0
    for domain in ("tech", "design"):
        ddir = KNOWLEDGE_DIR / domain
        if not ddir.exists():
            continue
        for tdir in sorted(ddir.iterdir()):
            ovf = tdir / "overview.md"
            if not ovf.exists():
                continue
            ov = parse_overview(ovf.read_text(encoding="utf-8"))
            topics_by_domain[domain].append((tdir.name, ov))
            total_sources += ov["sources"]
            for s in ov["sections"]:
                if s["label"] == "分歧": total_disag += len(s["items"])
            if ov["sources"] >= 2:  # 多源 = 经过 LLM 交叉综合
                total_synth += 1
    ntopics = sum(len(v) for v in topics_by_domain.values())
    # 同名主题（LLM 聚类随机性导致同名不同成员）加来源数后缀，便于区分
    from collections import Counter
    title_count = Counter(ov["title"] for dom in topics_by_domain.values() for _, ov in dom)

    sections_html = []
    for domain, topics in topics_by_domain.items():
        if not topics:
            continue
        cards = "\n".join(
            _render_card(domain, t, ov, f' · {ov["sources"]}源' if title_count.get(ov["title"], 0) > 1 else "")
            for t, ov in topics)
        sections_html.append(
            f'<section class="pavilion" data-domain="{domain}">'
            f'<div class="pav-head reveal"><span class="pav-tab {domain}"></span>'
            f'<h2>{DOMAIN_NAME[domain]}</h2>'
            f'<span class="pav-count">{len(topics)} 个主题</span></div>'
            f'<div class="cards">{cards}</div></section>')
    if not sections_html:
        sections_html.append('<p class="none reveal">知识库还是空的——提交报告后跑 <code>python3 distill.py</code>。</p>')

    out = (_KNOWLEDGE_TPL
           .replace("__TOPICS__", str(ntopics))
           .replace("__SOURCES__", str(total_sources))
           .replace("__DISAGREE__", str(total_disag))
           .replace("__SYNTH__", str(total_synth))
           .replace("__NTECH__", str(len(topics_by_domain["tech"])))
           .replace("__NDESIGN__", str(len(topics_by_domain["design"])))
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
        for d in ("tech", "design"):
            ddir = KNOWLEDGE_DIR / d
            if ddir.exists():
                for sub in ddir.iterdir():
                    if sub.is_dir():
                        shutil.rmtree(sub)
        print("[clean] 已清空 knowledge/{tech,design}")
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


def _run_incremental(reports: list):
    """规则路径：增量，1 报告 = 1 主题（无 key 时的兑底，保留原行为）。"""
    done = processed_files()
    log_entries, stats = [], {"skipped": 0, "processed": 0, "items": 0}
    for r in reports:
        fname, domain, source = r["file"], r["domain"], r["file"]
        if fname in done:
            continue
        if domain == "ephemeral":
            log_entries.append(f"[x] {fname} — skipped (ephemeral)"); stats["skipped"] += 1; continue
        extractor = EXTRACTORS.get(domain)
        if not extractor:
            log_entries.append(f"[x] {fname} — skipped (unknown domain)"); stats["skipped"] += 1; continue
        items = extractor(r["content"], source)
        if not items:
            log_entries.append(f"[x] {fname} — processed, 0 items extracted"); stats["processed"] += 1; continue
        write_knowledge(domain, r["slug"], r["title"], items, source)
        log_entries.append(f"[x] {fname} — {domain}/{r['slug']}/ → {len(items)} items")
        stats["processed"] += 1; stats["items"] += len(items)
    if log_entries:
        if not DRY_RUN:
            append_log(log_entries); update_index()
        print(f"蒸馏完成: {stats['processed']} 篇处理, {stats['skipped']} 篇跳过, {stats['items']} 条知识")
        if DRY_RUN:
            print("(dry-run, 未落盘)")
            for e in log_entries: print(f"  {e}")
    else:
        print("无新报告需要蒸馏")


def _run_compiled(reports: list):
    """LLM 路径：规则抽骨架 → LLM 语义聚类 → 每主题综合+矛盾 → 全量重编译。"""
    members_data = {}
    for r in reports:
        d = r["domain"]
        tag = _read_meta(r["content"], "tag")
        if d == "ephemeral" or d not in EXTRACTORS:
            continue
        if tag.upper().startswith("META"):
            continue  # 卷首/关于本书，非知识，不蒸馏
        items = EXTRACTORS[d](r["content"], r["file"])
        if not items:
            continue  # 抽不到骨架的不进编译
        members_data[r["slug"]] = {"title": r["title"], "domain": d, "items": items, "file": r["file"]}
    if not members_data:
        print("无可编译报告"); return

    catalog = [{"slug": s, "title": m["title"], "items": m["items"], "domain": m["domain"]}
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
    for c in clusters:
        ms = c["members"]
        payload = [{"slug": s, "title": members_data[s]["title"],
                    "conclusions": [it["text"] for it in members_data[s]["items"] if it["kind"] == "conclusion"],
                    "traps": [it["text"] for it in members_data[s]["items"] if it["kind"] == "trap"],
                    "data": [it["text"] for it in members_data[s]["items"] if it["kind"] == "data"]}
                   for s in ms]
        compiled = llm_compile_topic(c["topic"], payload)
        n_contra += len(compiled["contradictions"])
        if not DRY_RUN:
            written = write_knowledge_compiled(c, members_data, compiled)
            if written:
                if compiled["summary"] or compiled["points"]: n_synth += 1
            else:
                n_fail += 1  # compile 无实质内容，保留旧 overview
    if not DRY_RUN:
        append_log([f"[compiled] {datetime.now().strftime('%Y-%m-%d %H:%M')} "
                    f"model={DISTILL_MODEL} topics={len(clusters)} synth={n_synth} contra={n_contra} fail={n_fail}"])
        update_index()
    print(f"LLM 编译完成: {len(members_data)} 篇 → {len(clusters)} 主题, 综合 {n_synth}, 分歧 {n_contra}, 失败保留旧 {n_fail}")

if __name__ == "__main__":
    distill()
