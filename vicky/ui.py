"""
ui.py — HTML 片段构建器。全项目成段 HTML 标记只允许出现在 views/ 与 ui.py 两处。
P3 前端抢救：从 l1_publish / l2_distill 提取 toc_row、chips、frontmatter 条目、
_render_card、volume_nav_html 等循环标记。

铁律：此模块之外无人写成段 HTML（views/ 模板除外）。
"""

import html as html_mod
import re
from datetime import datetime

from . import config


def _clean_title(title: str) -> str:
    """标题展示兜底：排除混进标题字段的字面 HTML 标签残留（如 <br>）。
    不动数据/存档，仅在展示层 escape 前 strip 掉标签，避免转义后字面显示。"""
    return re.sub(r"<[^>]+>", " ", title or "").strip()

# ============================================================
# 知识卡片常量（从 l2_distill 迁出，避免跨层导入 l2）
# ============================================================
CONF_SEAL = {"high": ("可信", "hi"), "medium": ("可参", "mid"), "low": ("存疑", "lo")}
VER_LABEL = {"unverified": ("未验证", "v-unv"), "machine-confirmed": ("机确认", "v-mach"),
             "human-reviewed": ("人复核", "v-human")}
SEC_CLS = {"结论": "concl", "被否假设": "refut", "陷阱": "trap",
           "数据": "data", "分歧": "disag", "综合": "synth", "agree": "agree"}
STRUCT_SECS = {"一句话结论", "概述", "来源"}


# ============================================================
# 视图加载器（唯一加载入口，views/ 模板绑定数据）
# ============================================================
def load_view(name: str) -> str:
    """加载 views/{name} 模板，纯 HTML + __占位符__。"""
    path = config.VIEWS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"视图模板不存在: {path}")
    return path.read_text(encoding="utf-8")


# ============================================================
# 重构蓝图（2026-08-12）：四区索引 + 项目空间片段
# 分类徽章：.row-cat.{modifier} 色块，modifier 映射到 category 色
# （research/tech-solution→蓝、brief→灰、arch-doc→红）。domain 语义已彻底删除。
# ============================================================
CATEGORY_LABEL = {"research": "技术", "brief": "简报", "tech-solution": "方案",
                  "arch-doc": "架构", "design": "设计"}
CATEGORY_MOD_CLS = {"research": "tech", "tech-solution": "tech", "brief": "ephemeral",
                    "arch-doc": "arch", "design": "design"}


def project_slug(name: str) -> str:
    """项目 slug：由 name 规范化生成（保留中英文、统一 lowercase、其余替换为 -，URL 安全）。"""
    s = re.sub(r"[^\w-]+", "-", (name or "").strip(), flags=re.UNICODE)
    s = re.sub(r"-{2,}", "-", s).strip("-").lower()
    return s or "unnamed"


def _row_search(r: dict) -> str:
    """关键词搜索串：标题 + 副题 + 标签 + 项目 + 丛书，小写（Alpine 前端模糊匹配）。"""
    parts = [r["title"], r.get("subtitle") or "", r.get("_tag") or "",
             r.get("_project") or "", r.get("_series") or ""]
    return " ".join(p for p in parts if p).lower()


# ============================================================
# L1 索引页片段
# ============================================================
def toc_row(r: dict, num: int) -> str:
    """目录行——报告条目循环标记（四区索引技术文库 / 简报用）。
    新模型（重构蓝图）：徽章按 category 渲染（技术/简报/方案/架构），
    data-category / data-project / data-search 供 Alpine 按分类、项目、标签、关键词筛选。"""
    delay = (num % 12) * 0.04
    esc_tag = html_mod.escape(r["_tag"], quote=True)
    esc_series = html_mod.escape(r["_series"], quote=True)
    cat = r["_category"]
    label = CATEGORY_LABEL.get(cat, cat)
    mod = CATEGORY_MOD_CLS.get(cat, "tech")
    esc_proj = html_mod.escape(r.get("_project") or "", quote=True)
    search = html_mod.escape(_row_search(r), quote=True)
    badges = (f'<span class="row-cat {mod}" data-type="category" data-f="{cat}">'
              f'{html_mod.escape(label, quote=True)}</span> '
              f'<span class="row-tag" data-type="tag" data-f="{esc_tag}">{esc_tag}</span>')
    if r["_series"]:
        badges += (f' <span class="row-series" data-type="series" data-f="{esc_series}">'
                   f'《{esc_series}》第 {r.get("series_order") or "?"} 卷</span>')
    sub = (f'<span class="toc-sub">{html_mod.escape(r["subtitle"])}</span>'
           if r.get("subtitle") else "")
    updated = (' <span class="toc-updated">订</span>' if r.get("updated") else "")
    return (f'<a class="toc-item reveal" style="--d:{delay:.2f}s" href="/reports/{r["file"]}"'
            f' data-tag="{esc_tag}" data-series="{esc_series}"'
            f' data-category="{cat}" data-project="{esc_proj}" data-search="{search}"'
            f' x-show="visible($el)">'
            f'<span class="toc-num">{num:02d}</span>'
            f'<span class="toc-main"><span class="toc-line">'
            f'<span class="toc-title">{html_mod.escape(_clean_title(r["title"]))}</span>{badges}</span>{sub}</span>'
            f'<span class="toc-dots"></span>'
            f'<span class="toc-date">{r["date_display"]}{updated}</span></a>')


def index_chips(total: int, research_n: int, brief_n: int, project_n: int,
                tag_counts: list, projects: list) -> list[str]:
    """四区索引筹码（旧接口，向后兼容）：现拆成分类组 + 筛选组两次调用拼接。"""
    return (category_chips_html(total, research_n, brief_n, project_n)
            + filter_chips_html(tag_counts, projects))


def category_chips_html(total: int, research_n: int, brief_n: int, project_n: int) -> list[str]:
    """第一组筹码——分类（全部/技术文库/项目空间/简报）。
    切分类时同时清空 tag/proj（修复：跨分类残留的标签/项目筛选会在 AND 语义下
    把新分类的全部内容过滤掉，表现为"点了分类却是空的"）。"""
    return [
        f'<span class="chip on" data-type="all" @click="cat=\'all\';tag=\'\';proj=\'\'"'
        f' :class="cat===\'all\'&&\'on\'">全部<span class="n">{total}</span></span>',
        f'<span class="chip" data-type="category" @click="cat=\'research\';tag=\'\';proj=\'\'"'
        f' :class="cat===\'research\'&&\'on\'">技术文库<span class="n">{research_n}</span></span>',
        f'<span class="chip" data-type="category" @click="cat=\'project\';tag=\'\';proj=\'\'"'
        f' :class="cat===\'project\'&&\'on\'">项目空间<span class="n">{project_n}</span></span>',
        f'<span class="chip" data-type="category" @click="cat=\'brief\';tag=\'\';proj=\'\'"'
        f' :class="cat===\'brief\'&&\'on\'">简报<span class="n">{brief_n}</span></span>',
    ]


def filter_chips_html(tag_counts: list, projects: list) -> list[str]:
    """第二组筹码——标签 + 项目（细粒度叠加筛选，与分类组视觉隔开：chip-f 类）。
    tag_counts: [(tag, n)] 按计数倒序；projects: [(项目名, 篇数)]。"""
    chips = []
    for tag, n in tag_counts:
        esc = html_mod.escape(tag, quote=True)
        chips.append(
            f'<span class="chip chip-f" data-type="tag" @click="toggleTag(\'{esc}\')"'
            f' :class="tag===\'{esc}\'&&\'on\'" data-f="{esc}">'
            f'{html_mod.escape(tag)}<span class="n">{n}</span></span>')
    for name, n in projects:
        esc = html_mod.escape(name, quote=True)
        chips.append(
            f'<span class="chip chip-f" data-type="project" @click="toggleProj(\'{esc}\')"'
            f' :class="proj===\'{esc}\'&&\'on\'">'
            f'{html_mod.escape(name)}<span class="n">{n}</span></span>')
    return chips


def project_card(name: str, docs: list) -> str:
    """索引页项目空间卡片——项目名 + 文档数 + 最新日期，链到 /projects/{slug}.html。
    docs 为该项目的报告（时间倒序），用于计数与关键词搜索串。"""
    esc_name = html_mod.escape(name, quote=True)
    slug = html_mod.escape(project_slug(name), quote=True)
    latest = docs[0]["date"] if docs else ""
    latest_d = latest[5:] if len(latest) >= 10 else latest
    search = html_mod.escape((name + " " + " ".join(d["title"] for d in docs)).lower(),
                             quote=True)
    return (f'<a class="fm-item reveal" href="/projects/{slug}.html"'
            f' data-category="project" data-project="{esc_name}" data-tag=""'
            f' data-search="{search}" x-show="visible($el)">'
            f'<span class="fm-seal" aria-hidden="true">项</span>'
            f'<span class="fm-body"><span class="fm-title">{html_mod.escape(name)}</span>'
            f'<span class="fm-desc">{len(docs)} 篇文档 · 最新 {latest_d}</span></span>'
            f'<span class="fm-arrow">→</span></a>')


def project_doc_row(r: dict, num: int) -> str:
    """项目页文档时间线条目——标题 + 分类徽章（方案/架构/技术/简报）+ 日期，链到报告页。
    （项目页无 Alpine 筛选，不带 x-show。）"""
    cat = r["_category"]
    label = CATEGORY_LABEL.get(cat, cat)
    mod = CATEGORY_MOD_CLS.get(cat, "tech")
    esc_tag = html_mod.escape(r.get("_tag") or "", quote=True)
    sub = (f'<span class="toc-sub">{html_mod.escape(r["subtitle"])}</span>'
           if r.get("subtitle") else "")
    updated = (' <span class="toc-updated">订</span>' if r.get("updated") else "")
    return (f'<a class="toc-item reveal" style="--d:{(num % 12) * 0.04:.2f}s"'
            f' href="/reports/{r["file"]}" data-category="{cat}"'
            f' data-project="{html_mod.escape(r.get("_project") or "", quote=True)}">'
            f'<span class="toc-num">{num:02d}</span>'
            f'<span class="toc-main"><span class="toc-line">'
            f'<span class="toc-title">{html_mod.escape(_clean_title(r["title"]))}</span>'
            f'<span class="row-cat {mod}">{html_mod.escape(label, quote=True)}</span> '
            f'<span class="row-tag" data-f="{esc_tag}">{esc_tag}</span></span>{sub}</span>'
            f'<span class="toc-dots"></span>'
            f'<span class="toc-date">{r["date_display"]}{updated}</span></a>')


def project_nav(projects: list, current: str) -> str:
    """项目页间互链——其他项目 → 各自页面；当前项目高亮为纯文本筹码。"""
    items = []
    for p in projects:
        name = p["project"]
        esc = html_mod.escape(name, quote=True)
        if name == current:
            items.append(f'<span class="chip on">{esc}</span>')
        else:
            slug = html_mod.escape(project_slug(name), quote=True)
            items.append(f'<a class="chip" href="/projects/{slug}.html"'
                         f' style="text-decoration:none">{esc}</a>')
    return "\n    ".join(items)


def frontmatter_html(front: list[dict]) -> str:
    """卷首区（关于本书）的 frontmatter 条目——P3 从 l1_publish.build_index 提取。"""
    if not front:
        return ""
    fm = [
        f'<a class="fm-item reveal" href="/reports/{r["file"]}">'
        f'<span class="fm-seal" aria-hidden="true">序</span>'
        f'<span class="fm-body"><span class="fm-title">{html_mod.escape(_clean_title(r["title"]))}</span>'
        f'<span class="fm-desc">{html_mod.escape(r.get("subtitle") or "关于这个平台本身的设计说明。")}</span></span>'
        f'<span class="fm-arrow">→</span></a>'
        for r in front
    ]
    return ('<div class="frontmatter">\n    <div class="fm-label">卷首 · 关于本书</div>\n    '
            + "\n    ".join(fm) + "\n  </div>")


def volume_nav_html(series: str, order: int, siblings: list) -> str:
    """丛书卷内导航——P3 从 l1_publish 迁入 ui.py。"""
    prev_r = next((r for r in siblings if r["series_order"] == order - 1), None)
    next_r = next((r for r in siblings if r["series_order"] == order + 1), None)
    links = ""
    if prev_r:
        links += f'<a class="vol prev" href="{prev_r["file"]}">← 上一卷 · {html_mod.escape(_clean_title(prev_r["title"]))}</a>'
    if next_r:
        links += f'<a class="vol next" href="{next_r["file"]}">下一卷 · {html_mod.escape(_clean_title(next_r["title"]))} →</a>'
    safe_series = html_mod.escape(re.sub(r"\s+", " ", (series or "").strip()))
    return f'<nav class="volume-nav" data-series="{safe_series}">{links}</nav>'


# ============================================================
# L2 藏书楼片段
# ============================================================
def _src_link(src: str) -> str:
    """证据锚点 → 报告短链接。P3 从 l2_distill 迁入 ui.py。
    feedback#N 来源不是报告文件，只渲染纯文本标记，不生成断链。"""
    if not src:
        return ""
    if src.startswith("feedback#"):
        return f' <span class="src" title="使用写回">{html_mod.escape(src)}</span>'
    short = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", src).removesuffix(".html")
    href = src if src.endswith(".html") else src + ".html"
    return (f' <a class="src" href="/reports/{html_mod.escape(href)}" '
            f'title="{html_mod.escape(href)}">{html_mod.escape(short)}</a>')


def render_knowledge_card(category: str, topic: str, ov: dict, title_suffix: str = "",
                          fb_count: int = 0) -> str:
    """藏书楼知识卡——完整 kcard 格式（含各节全文）。
    保留供 B 阶段词条全文页（public/knowledge/{topic}.html）使用。
    索引页已改为轻量行格式（knowledge_index_row）。"""
    conf_label, conf_cls = CONF_SEAL.get(ov["confidence"], ("存疑", "lo"))
    # OKF 信任徽章
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
    # KSI 徽章
    badges = []
    for s in ov["sections"]:
        if s["label"] in STRUCT_SECS:
            continue
        cls = SEC_CLS.get(s["label"], "")
        n = len(s["items"])
        if s["label"] == "综合":
            badges.append(f'<span class="kbadge {cls}">综合 ✓</span>')
        elif n:
            badges.append(f'<span class="kbadge {cls}">{html_mod.escape(s["label"])} {n}</span>')
    # 正文分节（kcard-body 内，沿用 .ksec 标记）
    secs = []
    for s in ov["sections"]:
        if not s["items"]:
            continue
        cls = SEC_CLS.get(s["label"], "")
        if s["label"] in ("概述", "一句话结论"):
            prose = " ".join(html_mod.escape(it["text"]) for it in s["items"])
            secs.append(f'<div class="ksec {cls}"><div class="ksec-l">{html_mod.escape(s["label"])}</div>'
                        f'<p class="kprose">{prose}</p></div>')
            continue
        lis = "".join(
            f'<li>{html_mod.escape(it["text"])}{_src_link(it["source"])}</li>' for it in s["items"])
        secs.append(f'<div class="ksec {cls}"><div class="ksec-l">{html_mod.escape(s["label"])}</div>'
                    f'<ul>{lis}</ul></div>')
    # .ksum：概述/一句话结论节的首句（默认收起态的摘要）
    ksum = ""
    for s in ov["sections"]:
        if s["label"] in ("概述", "一句话结论") and s["items"]:
            ksum = html_mod.escape(s["items"][0]["text"])
            break
    # .tagchip 行（data-t 供前端按标签筛选；prompt 约束标签不含逗号，契约才成立）
    tags = ov.get("tags") or []
    tagrow = "".join(
        f'<span class="tagchip" data-t="{html_mod.escape(t, quote=True)}">{html_mod.escape(t)}</span>'
        for t in tags)
    tags_attr = ",".join(html_mod.escape(t, quote=True) for t in tags)
    # 全文小写（data-search 供搜索框过滤）
    search_blob = html_mod.escape((ov["title"] + " " + topic + " " +
                                   " ".join(it["text"] for s in ov["sections"] for it in s["items"])).lower(), quote=True)
    head = (f'<div class="kcard-head">'
            f'<h3 class="ktitle">{html_mod.escape(ov["title"])}{html_mod.escape(title_suffix)}</h3>'
            f'<div class="kmeta">更新于 {ov["updated"]} · {ov["sources"]} 篇来源 · '
            f'{f"{fb_count} 次写回 · " if fb_count else ""}'
            f'<code>{html_mod.escape(topic)}</code> {trust}</div>'
            f'<div class="tagrow">{tagrow}</div>'
            f'{f"<p class=\"ksum\">{ksum}</p>" if ksum else ""}'
            f'<div class="ksi">{"".join(badges)}</div>'
            f'</div>')
    body = f'<div class="kcard-body">{"".join(secs)}</div>'
    return (f'<article class="kcard reveal" data-category="{category}" '
            f'data-tags="{tags_attr}" data-search="{search_blob}">'
            f'{head}{body}</article>')


# ============================================================
# L2 藏书楼轻索引片段（B 方案：每主题一行，按专栏分组）
# ============================================================
def knowledge_index_row(topic: dict) -> str:
    """轻索引行——每主题一行：标题（链到词条页 entry_url）+ 一句话结论 + 来源数 + 信任徽章。
    topic 约定字段（B 阶段 collect_topics() 产出同形结构）：
    {slug, title, one_liner, sources, confidence, verified, category, entry_url}"""
    entry = html_mod.escape(topic.get("entry_url", f"/knowledge/{topic['slug']}.html"), quote=True)
    title = html_mod.escape(topic["title"])
    one_liner = html_mod.escape(topic.get("one_liner") or "")
    sources = topic.get("sources", 0)
    confidence = topic.get("confidence", "low")
    conf_label, conf_cls = CONF_SEAL.get(confidence, ("存疑", "lo"))
    verified = topic.get("verified", "unverified")
    vlabel, vcls = VER_LABEL.get(verified, ("未验证", "v-unv"))
    search = html_mod.escape(
        (topic["title"] + " " + (topic.get("one_liner") or "")).lower(), quote=True)
    cat = topic.get("category", "ai")
    return (f'<div class="krow reveal" data-category="{cat}" data-search="{search}">'
            f'<div class="krow-main">'
            f'<a class="krow-title" href="{entry}">{title}</a>'
            f'<p class="krow-oneliner">{one_liner}</p>'
            f'</div>'
            f'<div class="krow-meta">'
            f'<span class="krow-sources"><strong>{sources}</strong> 来源</span>'
            f'<span class="krow-confidence {conf_cls}" title="可信度：{conf_label}">{conf_label}</span>'
            f'<span class="vbadge {vcls}" title="验证层级：{vlabel}">{vlabel}</span>'
            f'</div>'
            f'</div>')


def knowledge_index_section(cat: str, cat_name: str, topics: list) -> str:
    """轻索引专栏分区——h2 锚点 + 该专栏全部主题行。
    topics 为 [{slug,title,one_liner,sources,confidence,verified,category,entry_url}, ...]。"""
    if not topics:
        return ""
    rows = "\n".join(knowledge_index_row(t) for t in topics)
    return (f'<section class="pavilion" id="sec-{cat}" data-category="{cat}">'
            f'<div class="pav-head reveal"><h2>{html_mod.escape(cat_name)}</h2>'
            f'<span class="pav-count">{len(topics)} 个主题</span></div>'
            f'{rows}'
            f'</section>')


def knowledge_pavilion_html(category: str, topics: list, title_count: dict | None = None,
                            fb_counts: dict | None = None) -> str:
    """藏书楼专栏分区——轻索引行格式（B 方案），每主题一行，替代旧 kcard 全文平铺。
    签名保持与旧版兼容（title_count / fb_counts 不再使用，但保留参数避免调用方报错）。"""
    cat_name = config.CATEGORIES.get(category, category)
    return knowledge_index_section(category, cat_name, topics)


def knowledge_anchors_html(topics_by_cat: dict) -> list[str]:
    """轻索引锚点导航——每专栏一个锚点链接，点击滚动到对应分区。"""
    anchors = []
    for k, name in config.CATEGORIES.items():
        n = len(topics_by_cat.get(k, []))
        if n > 0:
            anchors.append(
                f'<span class="k-anchor on" data-c="{k}"'
                f'>{html_mod.escape(name)}<span class="n">{n}</span></span>')
    return anchors


def knowledge_chips_html(topics_by_cat: dict) -> list[str]:
    """藏书楼专栏 chips——全部 + 五专栏（含 0 计数，筛选态稳定）。"""
    ntopics = sum(len(v) for v in topics_by_cat.values())
    chips = [f'<span class="chip on" data-c="all">全部<span class="n">{ntopics}</span></span>']
    for k, name in config.CATEGORIES.items():
        n = len(topics_by_cat.get(k, []))
        chips.append(f'<span class="chip" data-c="{k}">{html_mod.escape(name)}<span class="n">{n}</span></span>')
    return chips
