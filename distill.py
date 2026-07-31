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
import html  # build_knowledge_page 用 html.escape
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
# 藏书楼视图（knowledge/ → public/knowledge/index.html）
# ============================================================

CONF_SEAL = {"high": ("可信", "hi"), "medium": ("可参", "mid"), "low": ("存疑", "lo")}
DOMAIN_NAME = {"tech": "tech 阁", "design": "design 阁"}
SEC_CLS = {"结论": "concl", "被否假设": "refut", "陷阱": "trap",
           "关键数据": "data", "分歧": "disag", "综合": "synth"}

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
.ksi{display:flex;gap:6px;flex-wrap:wrap;padding-bottom:14px;border-bottom:1px dashed var(--hairline);margin-bottom:14px}
.kbadge{font-size:11px;padding:3px 9px;border-radius:2px;font-weight:500}
.kbadge.concl{color:var(--accent);background:rgba(12,74,110,.09)}
.kbadge.refut{color:var(--sub);background:rgba(0,0,0,.05)}
.kbadge.trap{color:var(--amber);background:rgba(176,141,87,.12)}
.kbadge.data{color:var(--sub);background:rgba(0,0,0,.05);font-family:var(--mono);font-size:10.5px}
.kbadge.disag{color:#FBFAF7;background:var(--seal);font-weight:600}
.kbadge.synth{color:var(--green);background:rgba(46,125,79,.1);font-weight:600}
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
.ksec.disag{border-left:2px solid var(--seal);padding-left:12px;margin-left:-14px;background:rgba(166,58,46,.035);padding-top:8px;padding-bottom:8px;border-radius:0 2px 2px 0}
.ksec.synth{border-left:2px solid var(--green);padding-left:12px;margin-left:-14px;background:rgba(46,125,79,.04);padding-top:8px;padding-bottom:8px;border-radius:0 2px 2px 0}
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


def parse_overview(text: str) -> dict:
    """把 overview.md 解析成结构化数据（标题/元信息/分节条目）。"""
    title, meta, sections, cur = "", {"updated": "", "sources": 0, "confidence": "low"}, [], None
    for line in text.splitlines():
        if line.startswith("# "):
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
    return {"title": title, **meta, "sections": sections}


def _src_link(src: str) -> str:
    """证据锚点 → 报告短链接（去日期前缀，mono 小字）。"""
    if not src:
        return ""
    short = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", src).removesuffix(".html")
    return (f' <a class="src" href="/research/reports/{html.escape(src)}" '
            f'title="{html.escape(src)}">{html.escape(short)}</a>')


def _render_card(domain: str, topic: str, ov: dict) -> str:
    conf_label, conf_cls = CONF_SEAL.get(ov["confidence"], ("存疑", "lo"))
    # KSI 徽章：只展示存在的节，数量诚实
    badges = []
    for s in ov["sections"]:
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
        lis = "".join(
            f'<li>{html.escape(it["text"])}{_src_link(it["source"])}</li>' for it in s["items"])
        secs.append(f'<div class="ksec {cls}"><div class="ksec-l">{html.escape(s["label"])}</div>'
                    f'<ul>{lis}</ul></div>')
    search_blob = html.escape((ov["title"] + " " + topic + " " +
                               " ".join(it["text"] for s in ov["sections"] for it in s["items"])).lower(), quote=True)
    return (f'<article class="kcard reveal" data-domain="{domain}" data-search="{search_blob}">'
            f'<div class="kcard-top"><span class="dtab {domain}">{domain}</span>'
            f'<span class="conf {conf_cls}" title="置信度：{conf_label}">{conf_label}</span></div>'
            f'<h3 class="ktitle">{html.escape(ov["title"])}</h3>'
            f'<div class="kmeta">更新于 {ov["updated"]} · {ov["sources"]} 篇来源 · '
            f'<code>{html.escape(topic)}</code></div>'
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
                if s["label"] == "综合": total_synth += 1
    ntopics = sum(len(v) for v in topics_by_domain.values())

    sections_html = []
    for domain, topics in topics_by_domain.items():
        if not topics:
            continue
        cards = "\n".join(_render_card(domain, t, ov) for t, ov in topics)
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
    out_dir = REPO_DIR / "public" / "knowledge"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(out, encoding="utf-8")
    return out_path


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

    # 藏书楼视图：每次都重建，始终反映当前 knowledge/ 状态
    if not DRY_RUN:
        page = build_knowledge_page()
        print(f"藏书楼视图: {page.relative_to(REPO_DIR)}")


if __name__ == "__main__":
    distill()
