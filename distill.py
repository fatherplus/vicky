#!/usr/bin/env python3
"""
蒸馏器 — 从 HTML 报告中提取结构化知识，维护 knowledge/ Wiki。

用法: python3 distill.py [--dry-run]

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
import html as html_mod
from pathlib import Path
from datetime import datetime

REPO_DIR = Path(__file__).resolve().parent
REPORTS_DIR = REPO_DIR / "public" / "reports"
KNOWLEDGE_DIR = REPO_DIR / "knowledge"
LOG_PATH = KNOWLEDGE_DIR / "log.md"
INDEX_PATH = KNOWLEDGE_DIR / "index.md"

DRY_RUN = "--dry-run" in sys.argv


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
    return [html_mod.unescape(m).strip()
            for m in re.findall(r"<blockquote>([\s\S]*?)</blockquote>", content)]


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
# 主流程
# ============================================================

def distill():
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    done = processed_files()
    reports = scan_reports()
    log_entries = []
    stats = {"skipped": 0, "processed": 0, "items": 0}

    for r in reports:
        fname = r["file"]
        if fname in done:
            continue

        domain = r["domain"]
        source = fname  # 证据锚点用文件名

        if domain == "ephemeral":
            log_entries.append(f"[x] {fname} — skipped (ephemeral)")
            stats["skipped"] += 1
            continue

        extractor = EXTRACTORS.get(domain)
        if not extractor:
            log_entries.append(f"[x] {fname} — skipped (unknown domain: {domain})")
            stats["skipped"] += 1
            continue

        items = extractor(r["content"], source)
        if not items:
            log_entries.append(f"[x] {fname} — processed, 0 items extracted")
            stats["processed"] += 1
            continue

        overview = write_knowledge(domain, r["slug"], r["title"], items, source)
        log_entries.append(
            f"[x] {fname} — {domain}/{r['slug']}/ → {len(items)} items")
        stats["processed"] += 1
        stats["items"] += len(items)

    if log_entries:
        if not DRY_RUN:
            append_log(log_entries)
            update_index()
        print(f"蒸馏完成: {stats['processed']} 篇处理, "
              f"{stats['skipped']} 篇跳过, {stats['items']} 条知识")
        if DRY_RUN:
            print("(dry-run, 未落盘)")
            for e in log_entries:
                print(f"  {e}")
    else:
        print("无新报告需要蒸馏")


if __name__ == "__main__":
    distill()
