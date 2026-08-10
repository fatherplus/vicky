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

# ============================================================
# 知识卡片常量（从 l2_distill 迁出，避免跨层导入 l2）
# ============================================================
CONF_SEAL = {"high": ("可信", "hi"), "medium": ("可参", "mid"), "low": ("存疑", "lo")}
VER_LABEL = {"unverified": ("未验证", "v-unv"), "machine-confirmed": ("机确认", "v-mach"),
             "human-reviewed": ("人复核", "v-human")}
DOMAIN_NAME = {"tech": "tech 阁"}
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
# L1 索引页片段
# ============================================================
def toc_row(r: dict, num: int) -> str:
    """目录行——报告条目循环标记。P3 从 l1_publish.build_index 提取。"""
    DOMAIN_LABEL = {"tech": "技术", "design": "设计", "ephemeral": "工作", "arch": "架构"}
    delay = (num % 12) * 0.04
    esc_tag = html_mod.escape(r["_tag"], quote=True)
    esc_series = html_mod.escape(r["_series"], quote=True)
    dom = r["_domain"]
    esc_dom = html_mod.escape(DOMAIN_LABEL.get(dom, dom), quote=True)
    badges = (f'<span class="row-domain {dom}" data-type="domain" data-f="{dom}">'
              f'{esc_dom}</span> '
              f'<span class="row-tag" data-type="tag" data-f="{esc_tag}">{esc_tag}</span>')
    if r["_series"]:
        badges += (f' <span class="row-series" data-type="series" data-f="{esc_series}">'
                   f'《{esc_series}》第 {r.get("series_order") or "?"} 卷</span>')
    sub = (f'<span class="toc-sub">{html_mod.escape(r["subtitle"])}</span>'
           if r.get("subtitle") else "")
    updated = (' <span class="toc-updated">订</span>' if r.get("updated") else "")
    return (f'<a class="toc-item reveal" style="--d:{delay:.2f}s" href="/reports/{r["file"]}"'
            f' data-tag="{esc_tag}" data-series="{esc_series}" data-domain="{dom}">'
            f'<span class="toc-num">{num:02d}</span>'
            f'<span class="toc-main"><span class="toc-line">'
            f'<span class="toc-title">{html_mod.escape(r["title"])}</span>{badges}</span>{sub}</span>'
            f'<span class="toc-dots"></span>'
            f'<span class="toc-date">{r["date_display"]}{updated}</span></a>')


def chips_html(research: list[dict]) -> list[str]:
    """类型筹码 HTML 列表——P3 从 l1_publish.build_index 提取。"""
    DOMAIN_LABEL = {"tech": "技术", "design": "设计", "ephemeral": "工作", "arch": "架构"}
    tag_count, series_count, domain_count = {}, {}, {}
    for r in research:
        tag = r.get("_tag", "研究报告").strip() or "研究报告"
        tag_count[tag] = tag_count.get(tag, 0) + 1
        sname = r.get("_series", "")
        if sname:
            series_count[sname] = series_count.get(sname, 0) + 1
        dom = r.get("_domain", "tech")
        domain_count[dom] = domain_count.get(dom, 0) + 1

    chips = [f'<span class="chip on" data-type="all" data-f="">全部<span class="n">{len(research)}</span></span>']
    for dom in ("tech", "design", "ephemeral", "arch"):
        dn = domain_count.get(dom, 0)
        if dn:
            chips.append(f'<span class="chip chip-domain {dom}" data-type="domain" data-f="{dom}">'
                         f'{html_mod.escape(DOMAIN_LABEL.get(dom, dom))}<span class="n">{dn}</span></span>')
    for tag, n in sorted(tag_count.items(), key=lambda kv: (-kv[1], kv[0])):
        chips.append(f'<span class="chip" data-type="tag" data-f="{html_mod.escape(tag, quote=True)}">'
                     f'{html_mod.escape(tag)}<span class="n">{n}</span></span>')
    for sname, n in sorted(series_count.items(), key=lambda kv: (-kv[1], kv[0])):
        chips.append(f'<span class="chip chip-series" data-type="series" data-f="{html_mod.escape(sname, quote=True)}">'
                     f'《{html_mod.escape(sname)}》<span class="n">{n}</span></span>')
    return chips


def frontmatter_html(front: list[dict]) -> str:
    """卷首区（关于本书）的 frontmatter 条目——P3 从 l1_publish.build_index 提取。"""
    if not front:
        return ""
    fm = [
        f'<a class="fm-item reveal" href="/reports/{r["file"]}">'
        f'<span class="fm-seal" aria-hidden="true">序</span>'
        f'<span class="fm-body"><span class="fm-title">{html_mod.escape(r["title"])}</span>'
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
        links += f'<a class="vol prev" href="{prev_r["file"]}">← 上一卷 · {html_mod.escape(prev_r["title"])}</a>'
    if next_r:
        links += f'<a class="vol next" href="{next_r["file"]}">下一卷 · {html_mod.escape(next_r["title"])} →</a>'
    safe_series = html_mod.escape(re.sub(r"\s+", " ", (series or "").strip()))
    return f'<nav class="volume-nav" data-series="{safe_series}">{links}</nav>'


# ============================================================
# L1 卡片墙片段（spec §3）——design 报告聚合页
# ============================================================
def _card_cover(slug: str) -> str:
    """封面图：assets/img/{slug}/ 按名排序第一张；无图给占位样式。"""
    img_dir = config.IMG_DIR / slug
    imgs = (sorted(p.name for p in img_dir.iterdir()
                   if p.suffix.lower() in config.IMG_EXTENSIONS)
            if img_dir.exists() else [])
    if imgs:
        name = html_mod.escape(imgs[0], quote=True)
        return (f'<img class="cwall-cover" src="/assets/img/{slug}/{name}" '
                f'alt="{html_mod.escape(slug)} 封面" loading="lazy">')
    return ('<div class="cwall-cover" style="display:flex;align-items:center;'
            'justify-content:center;color:var(--sub);font-family:var(--serif);font-size:14px">'
            '暂无封面</div>')


def card_wall_item(r: dict) -> str:
    """卡片墙条目——一产品一卡，链到报告页。slug 从文件名反推（date-slug.html）。"""
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", r["file"]).removesuffix(".html")
    cover = _card_cover(slug)
    title = html_mod.escape(r["title"])
    sub = r.get("subtitle") or r.get("tag") or ""
    esc_sub = html_mod.escape(sub, quote=True)
    href = html_mod.escape(r["file"], quote=True)
    return (f'<a class="cwall-card reveal" href="/reports/{href}">{cover}'
            f'<div class="cwall-body"><span class="cwall-title">{title}</span>'
            f'<span class="cwall-sub">{esc_sub}</span></div></a>')


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


def render_knowledge_card(domain: str, topic: str, ov: dict, title_suffix: str = "",
                          fb_count: int = 0) -> str:
    """藏书楼知识卡片——P3 从 l2_distill._render_card 迁入 ui.py。"""
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
    # 正文分节
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
    search_blob = html_mod.escape((ov["title"] + " " + topic + " " +
                                   " ".join(it["text"] for s in ov["sections"] for it in s["items"])).lower(), quote=True)
    return (f'<article class="kcard reveal" data-domain="{domain}" data-status="{ov.get("status", "stable")}" data-search="{search_blob}">'
            f'<div class="kcard-top"><span class="dtab {domain}">{domain}</span>'
            f'<span class="conf {conf_cls}" title="置信度：{conf_label}">{conf_label}</span></div>'
            f'<h3 class="ktitle">{html_mod.escape(ov["title"])}{html_mod.escape(title_suffix)}</h3>'
            f'<div class="kmeta">更新于 {ov["updated"]} · {ov["sources"]} 篇来源 · '
            f'{f"{fb_count} 次写回 · " if fb_count else ""}'
            f'<code>{html_mod.escape(topic)}</code> {trust}</div>'
            f'<div class="ksi">{"".join(badges)}</div>'
            f'<div class="kbody">{"".join(secs)}</div></article>')


def knowledge_pavilion_html(domain: str, topics: list, title_count: dict,
                            fb_counts: dict) -> str:
    """藏书楼 domain 分区（pavilion）→ cards——P3 从 l2_distill.build_knowledge_page 提取。"""
    cards = "\n".join(
        render_knowledge_card(domain, t, ov,
                              f' · {ov["sources"]}源' if title_count.get(ov["title"], 0) > 1 else "",
                              fb_count=fb_counts.get(t, 0))
        for t, ov in topics)
    return (f'<section class="pavilion" data-domain="{domain}">'
            f'<div class="pav-head reveal"><span class="pav-tab {domain}"></span>'
            f'<h2>{DOMAIN_NAME[domain]}</h2>'
            f'<span class="pav-count">{len(topics)} 个主题</span></div>'
            f'<div class="cards">{cards}</div></section>')
