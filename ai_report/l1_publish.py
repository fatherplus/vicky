"""
L1 表述层——快照 → 门禁 → 模板 → HTML+MD + 索引 + 丛书维护。
P0 包化：从 server.py 搬迁 render/build_index/门禁/丛书/模板校验全部代码。
行为零变化——仅代码搬迁 + import 路径更新，不改逻辑。
"""

import base64
import html as html_mod
import json
import re
from datetime import datetime
from pathlib import Path

from . import config
from . import store
from . import l0_ingest
from . import ui
from .html_to_md import html_to_md

# ============================================================
# 本地别名（便捷访问 config 常量）
# ============================================================
REPO_DIR = config.REPO_DIR
TEMPLATES_DIR = config.TEMPLATES_DIR
DEFAULT_TEMPLATE = config.DEFAULT_TEMPLATE
REPORTS_DIR = config.REPORTS_DIR
INDEX_PATH = config.INDEX_PATH
PUBLIC_DIR = config.PUBLIC_DIR
IMG_DIR = config.IMG_DIR
NARRATIVE_CONTRACTS = config.NARRATIVE_CONTRACTS
DOMAINS = config.DOMAINS
COMPONENTS = config.COMPONENTS
FIGURE_RE = config.FIGURE_RE
AI_WORDS = config.AI_WORDS
EMOJI_RE = config.EMOJI_RE
DEPRECATED_CLASSES = config.DEPRECATED_CLASSES
ROOT_TOKEN_RE = config.ROOT_TOKEN_RE
REQUIRED_PLACEHOLDERS = config.REQUIRED_PLACEHOLDERS
IMG_EXTENSIONS = config.IMG_EXTENSIONS
IMG_MAX_BYTES = config.IMG_MAX_BYTES

# ============================================================
# 模板渲染
# ============================================================
def template_path(name: str) -> Path:
    """解析模板文件；未知模板抛 KeyError（handler 层转 400）"""
    p = TEMPLATES_DIR / name / "template.html"
    if not p.exists():
        raise KeyError(f"模板 '{name}' 不存在（GET /api/templates 查看可用模板）")
    return p


def list_templates() -> list:
    """模板目录：manifest 列表，default 排首"""
    out = []
    if TEMPLATES_DIR.exists():
        for m in sorted(TEMPLATES_DIR.glob("*/manifest.json")):
            out.append(json.loads(m.read_text(encoding="utf-8")))
    return sorted(out, key=lambda t: not t.get("default"))


def render(template: str, **kwargs) -> str:
    """替换 {{KEY}} 占位符"""
    for key, val in kwargs.items():
        template = template.replace("{{" + key + "}}", str(val))
    return template


# _INDEX_TPL 已迁出到 views/index.html，通过 ui.load_view("index.html") 加载
# 保留模块级别名供测试兼容（tests/util.py 注入 _INDEX_TPL 属性）
_INDEX_TPL = None  # P3 前端抢救：启动时由 _init_index_tpl() 填充


def build_index(reports: list[dict]) -> str:
    """生成书风格索引页。tag 以 META 开头的文档钉住「卷首」（关于本书），
    其余按时间倒序进目录流，类型筹码（tag / 丛书）前端筛选。
    P3 前端抢救：模板从 views/index.html 加载，片段用 ui.py。"""
    total = len(reports)
    front = [r for r in reports if r.get("tag", "").upper().startswith("META")]
    research = [r for r in reports if not r.get("tag", "").upper().startswith("META")]
    # 给每条 research 打上 _tag/_series/_domain 字段供 ui.chips_html / ui.toc_row 使用
    for r in research:
        r["_tag"] = (r.get("tag") or "研究报告").strip() or "研究报告"
        r["_series"] = normalize_series(r["series"]) if r.get("series") else ""
        r["_domain"] = r.get("domain") or "tech"

    frontmatter = ui.frontmatter_html(front)
    chips = ui.chips_html(research)
    rows = [ui.toc_row(r, i) for i, r in enumerate(research, 1)]
    year = reports[0]["date"][:4] if reports else str(datetime.now().year)

    tpl = ui.load_view("index.html")
    return (tpl
            .replace("__FRONTMATTER__", frontmatter)
            .replace("__CHIPS__", "\n    ".join(chips))
            .replace("__TOC__", "\n    ".join(rows))
            .replace("__TOTAL__", str(total))
            .replace("__YEAR__", year))


# ============================================================
# 核心操作
# ============================================================
def list_reports() -> list[dict]:
    """从 reports 表查全部报告，按日期倒序（P1：12 个正则刮 HTML 退休）。"""
    conn = store.get_db()
    try:
        return store.list_reports_from_db(conn)
    finally:
        conn.close()


# ============================================================
# 按需组件注入
# ============================================================
def component_head(content: str) -> tuple:
    """返回 (head 注入片段, 命中的组件名列表)。"""
    hits = [name for name, comp in COMPONENTS.items() if comp["detect"](content)]
    head = "\n    ".join(tag for name in hits for tag in COMPONENTS[name]["head"])
    return head, hits


# ============================================================
# 门禁
# ============================================================
def validate_template(name: str, manifest: dict, tpl_html: str, rationale: str) -> list:
    """模板创建门禁（机器可判定）：占位符齐全 / 不重定义视觉 token / 契约条目合法"""
    violations = []
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", name or ""):
        violations.append("模板名须为小写字母数字连字符（≤40 字符）")
    missing = [ph for ph in REQUIRED_PLACEHOLDERS if ph not in (tpl_html or "")]
    if missing:
        violations.append(f"模板缺少必需占位符：{' '.join(missing)}")
    if ROOT_TOKEN_RE.search(tpl_html or ""):
        violations.append("模板不得重定义 :root 视觉 token（调色板/字体由平台 book-style.css 拥有）")
    unknown = sorted(set(manifest.get("narrative_contract") or []) - NARRATIVE_CONTRACTS)
    if unknown:
        violations.append(f"未知契约条目：{unknown}（合法条目见 GET /api/principles §3）")
    if not (manifest.get("purpose") or "").strip():
        violations.append("manifest.purpose 必填：这个模板为哪类文档的什么目的而生")
    if not manifest.get("document_types"):
        violations.append("manifest.document_types 必填：至少一种文档类型")
    if not (rationale or "").strip():
        violations.append("rationale 必填：论证现有模板为何承载不了这个目的")
    return violations


# arch-node 节点卷三段硬契约（spec §2）：依序必含 输入与输出 → 内部工作流 → 架构方案
ARCH_NODE_SECTIONS = ("输入与输出", "内部工作流", "架构方案")
H2_RE = re.compile(r"<h2\b[^>]*>([\s\S]*?)</h2>", re.I)


def _h2_texts(content: str) -> list:
    """提取全部 <h2> 文本（去内层标签），按出现顺序。"""
    return [re.sub(r"<[^>]+>", "", h).strip() for h in H2_RE.findall(content)]


def validate_content(content: str, title: str = "", template: str = "") -> tuple:
    """表述规范门禁 + 软提醒（spec §7）。返回 (errors, warnings)：
    errors 触发 400 拒收；warnings 只随响应返回，agent 自觉修订。
    template="arch-node" 时追加节点卷三段硬契约校验（缺段/顺序错均拒收）。"""
    errors = []
    # --- errors：机器可判定的硬伤（原三条保留）---
    if template == "arch-node":
        headings = _h2_texts(content)
        pos = {s: next((i for i, h in enumerate(headings) if s in h), -1)
               for s in ARCH_NODE_SECTIONS}
        missing = [s for s in ARCH_NODE_SECTIONS if pos[s] == -1]
        if missing:
            errors.append(f"arch-node 节点卷缺段：{'、'.join(missing)}——三段依序必含："
                          f"{' → '.join(ARCH_NODE_SECTIONS)}")
        elif not (pos["输入与输出"] < pos["内部工作流"] < pos["架构方案"]):
            errors.append(f"arch-node 节点卷三段顺序错误：必须依序出现 {' → '.join(ARCH_NODE_SECTIONS)}")
    for tag in re.findall(r"<table\b[^>]*>", content, re.I):
        m = re.search(r"class\s*=\s*[\"']([^\"']*)[\"']", tag)
        classes = set(m.group(1).split()) if m else set()
        if not classes & {"data-table", "cmp-table"}:
            errors.append("裸 <table> 没有样式：摆数据用 <table class=\"data-table\">，回答\"选谁\"用 .cmp-table（见 GET /api/guide「对比表三条硬规则」）")
            break
    if "cmp-table" in content and "cmp-verdict" not in content:
        errors.append("cmp-table 缺少结论区：表尾必须接 <div class=\"cmp-verdict\">（带「怎么选 · VERDICT」）")
    used = set()
    for attr in re.findall(r"class\s*=\s*[\"']([^\"']*)[\"']", content):
        used |= set(attr.split())
    for c in sorted(used & DEPRECATED_CLASSES.keys()):
        errors.append(f"已弃用组件 .{c}（模板已删除其样式）：改用 {DEPRECATED_CLASSES[c]}")

    # --- warnings：零误伤取向的提醒（宁可漏报不误报）---
    warnings = []
    for i, fig in enumerate(FIGURE_RE.findall(content), 1):
        if "fig-cap" not in fig:
            warnings.append(f"第 {i} 个 figure 缺图题（图 N · 标题）")
        if "fig-note" not in fig:
            warnings.append(f"第 {i} 个 figure 缺图注（所以呢）")
    text = title + content
    hit = [w for w in AI_WORDS if w in text]
    if hit:
        warnings.append(f"AI 腔词 ×{sum(text.count(w) for w in hit)}：{'、'.join(hit)}（禁止清单）")
    emoji = EMOJI_RE.findall(text)
    if emoji:
        warnings.append(f"标题/正文含 emoji ×{len(emoji)}")
    if COMPONENTS["mermaid"]["detect"](content) and 'class="figure"' not in content:
        warnings.append("检测到 mermaid 但无任何 figure 装裱")
    bare = [m for m in SECTION_RE.findall(content) if _section_lacks_wrap(m[1])]
    if bare:
        warnings.append(f"{len(bare)} 个 section 缺 .wrap 版心（server 已自动补；提交时请包 <div class=\"wrap\">）")
    return errors, warnings


# ============================================================
# 丛书
# ============================================================
def normalize_series(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


SECTION_RE = re.compile(r"(<section\b[^>]*>)([\s\S]*?)</section>", re.I)


def _section_lacks_wrap(inner: str) -> bool:
    return not re.search(r'class\s*=\s*["\'][^"\']*\bwrap\b', inner)


def normalize_wrap(content: str) -> str:
    """section 缺 .wrap 版心时 server 自动补——版心宽/内边距全挂 .wrap，缺了整页裸奔。"""
    def fix(m):
        head, inner = m.group(1), m.group(2)
        if not _section_lacks_wrap(inner):
            return m.group(0)
        return f'{head}<div class="wrap">{inner}</div></section>'
    return SECTION_RE.sub(fix, content)


def check_series_conflict(series: str, order: int, exclude_file, reports: list) -> str | None:
    """同丛书同卷号已被其他文件占用 → 返回错误文案；否则 None。"""
    series = normalize_series(series)
    for r in reports:
        if (r.get("series") and normalize_series(r["series"]) == series
                and r.get("series_order") == order and r["file"] != exclude_file):
            return f"《{series}》第 {order} 卷已被 {r['file']} 占用"
    return None


def _series_siblings(series: str, reports: list) -> list:
    series = normalize_series(series)
    sibs = [r for r in reports if r.get("series") and normalize_series(r["series"]) == series]
    return sorted(sibs, key=lambda r: r["series_order"])


# P3 前端抢救：volume_nav_html 迁入 ui.py，此处保留别名供存量调用方（maintain_series_siblings 等）
volume_nav_html = ui.volume_nav_html


NAV_RE = re.compile(r'<nav class="volume-nav"[\s\S]*?</nav>')
TOTAL_META_RE = re.compile(r'(<meta name="series-total" content=")\d+(")')
BADGE_TOTAL_RE = re.compile(r'(第 \d+ 卷 · 共 )\d+( 卷)')


def maintain_series_siblings(series: str):
    """重算同丛书所有卷的导航/总数/徽章片段（定向替换，不碰正文与 head 资源）。"""
    reports = list_reports()
    siblings = _series_siblings(series, reports)
    total = len(siblings)
    for r in siblings:
        path = REPORTS_DIR / r["file"]
        text = path.read_text(encoding="utf-8")
        nav = volume_nav_html(series, r["series_order"], siblings)
        new = NAV_RE.sub(nav, text)
        new = TOTAL_META_RE.sub(rf"\g<1>{total}\g<2>", new)
        new = BADGE_TOTAL_RE.sub(rf"\g<1>{total}\g<2>", new)
        if new != text:
            path.write_text(new, encoding="utf-8")


def _existing_for_slug(slug: str) -> list:
    """按文件名格式精确匹配同 slug 报告（杜绝后缀误命中）"""
    pat = re.compile(rf"^\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(slug)}\.html$")
    return sorted(f for f in REPORTS_DIR.glob("*.html") if pat.match(f.name))


# ============================================================
# 创建/修订报告
# ============================================================
def create_report(title: str, slug: str, tag: str, content: str, subtitle: str = "",
                  series: str = "", order: int = 0, template: str = DEFAULT_TEMPLATE,
                  base_url: str = "", domain: str = "tech",
                  images: list | None = None, client_ip: str = "127.0.0.1") -> dict:
    """创建或修订报告（P1：L0 快照 → 渲染 → DB upsert）。
    同 slug 已存在 → 覆盖原文件、保留原日期、rev 递增。"""
    today = datetime.now().strftime("%Y-%m-%d")

    # ── 确定文件名与 created 标记 ──
    existing = _existing_for_slug(slug)
    warnings = []
    if existing:
        filename = existing[-1].name
        created = False
        if len(existing) > 1:
            warnings.append(f"同 slug 存在 {len(existing)} 份历史文件，覆盖最新 {filename}，其余建议人工清理")
    else:
        filename = f"{today}-{slug}.html"
        created = True

    # ── 模板级硬契约门禁（arch-node 三段）──
    # web.py 已预检过（400），此处兜底直调方（cli/测试），防止绕门禁
    violations, _ = validate_content(content, title, template)
    if violations:
        raise ValueError("内容不符合表述规范：" + "；".join(violations))

    # ── L0：不可变快照存档 ──
    payload = {
        "title": title, "slug": slug, "tag": tag, "content": content,
        "subtitle": subtitle, "series": series, "order": order,
        "template": template, "domain": domain,
    }
    if images:
        payload["images"] = [{"name": img.get("name", "")} for img in images]
    rev = l0_ingest.ingest_submission(slug, payload, client_ip=client_ip, provenance="api")

    # ── L0 图片原件保存 ──
    if images:
        l0_ingest.save_l0_images(slug, rev, images)

    # ── 渲染报告（模板 + 门禁 + 组件注入，逻辑不变）──
    tpl_path = template_path(template)
    tpl = tpl_path.read_text(encoding="utf-8")

    meta_tags = []
    meta_tags.append(f'<meta name="template" content="{template}">')
    meta_tags.append(f'<meta name="domain" content="{domain}">')
    if not created:
        meta_tags.append(f'<meta name="updated" content="{today}">')
    series = normalize_series(series)
    if series:
        meta_tags.append(f'<meta name="series" content="{html_mod.escape(series)}">')
        meta_tags.append(f'<meta name="series-order" content="{order}">')
        meta_tags.append(f'<meta name="series-total" content="1">')
    meta_html = "\n".join(meta_tags)

    series_badge = (f'<span class="series-badge">《{html_mod.escape(series)}》第 {order} 卷 · 共 1 卷</span>'
                    if series else "")
    volume_nav = f'<nav class="volume-nav" data-series="{html_mod.escape(series)}"></nav>' if series else ""

    content = normalize_wrap(content)
    comp_head, comp_hits = component_head(content)
    html_out = render(tpl,
        TITLE=title, HERO_TAG=tag, SUBTITLE=subtitle, DATE=today,
        CONTENT=content, COMPONENT_HEAD=comp_head, META=meta_html,
        SERIES_BADGE=series_badge, VOLUME_NAV=volume_nav,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / filename
    report_path.write_text(html_out, encoding="utf-8")
    (REPORTS_DIR / (filename[:-5] + ".md")).write_text(html_to_md(html_out), encoding="utf-8")

    # ── L1：DB upsert reports 表（P1：替代正则刮 HTML）──
    conn = store.get_db()
    try:
        # 获取 submission id（刚插入的那条）
        sub_row = conn.execute(
            "SELECT id FROM submissions WHERE slug=? AND rev=?", (slug, rev)).fetchone()
        sub_id = sub_row[0] if sub_row else 0
        created_date = filename[:10] if len(filename) >= 10 else today
        updated_date = today if not created else ""
        store.upsert_report(conn, slug, filename, title, tag, subtitle, domain,
                            template, series, order, created_date, updated_date, sub_id)
        conn.commit()
    finally:
        conn.close()

    # ── 重建索引 ──
    reports = list_reports()
    index_html = build_index(reports)
    INDEX_PATH.write_text(index_html, encoding="utf-8")
    refresh_card_wall()
    refresh_home()

    if series:
        maintain_series_siblings(series)

    result = {
        "ok": True,
        "file": filename,
        "created": created,
        "components": comp_hits,
        "warnings": warnings,
        "url": f"{base_url}/reports/{filename}" if base_url else f"/reports/{filename}",
    }
    if not created:
        result["updated"] = today
    return result


# ============================================================
# 从 L0 快照重渲染（render --all / --slug，P5 实现）
# 不创建新快照——仅从已有 L0 数据再生 L1 产物。
# ============================================================
def render_from_l0(slug: str) -> dict:
    """从 L0 快照再生单份报告的 HTML + MD，不创建新快照。
    返回 {"ok": bool, "file": str, "error": str | None}。"""
    conn = store.get_db()
    try:
        # 查 reports 表获取当前文件名与 current_rev
        rep = conn.execute(
            "SELECT file, title, tag, subtitle, domain, template, series, series_order, "
            "current_rev FROM reports WHERE slug=?", (slug,)).fetchone()
        if not rep:
            return {"ok": False, "error": f"slug '{slug}' 不在 reports 表中——先 backfill"}

        filename, title, tag, subtitle, domain, template, series, order, cur_rev = rep

        # 从 submissions 表取快照路径
        sub = conn.execute(
            "SELECT payload_path FROM submissions WHERE id=?", (cur_rev,)).fetchone()
        if not sub:
            return {"ok": False, "error": f"submission id={cur_rev} 不存在"}

        payload_path = Path(sub[0])
        if not payload_path.exists():
            return {"ok": False, "error": f"快照文件不存在: {payload_path}"}
    finally:
        conn.close()

    snap = json.loads(payload_path.read_text(encoding="utf-8"))
    data = snap["payload"]
    content = data["content"]
    date_str = filename[:10]  # 从文件名取原始日期，不再用今天

    # ── 渲染模板（复用 create_report 的渲染逻辑，但不写 L0 快照）──
    tpl_path = template_path(template)
    tpl = tpl_path.read_text(encoding="utf-8")

    meta_tags = [
        f'<meta name="template" content="{template}">',
        f'<meta name="domain" content="{domain}">',
    ]
    s = normalize_series(series)
    if s:
        meta_tags.append(f'<meta name="series" content="{html_mod.escape(s)}">')
        meta_tags.append(f'<meta name="series-order" content="{order}">')
        meta_tags.append(f'<meta name="series-total" content="1">')
    meta_html = "\n".join(meta_tags)

    series_badge = (f'<span class="series-badge">《{html_mod.escape(s)}》第 {order} 卷 · 共 1 卷</span>'
                    if s else "")
    volume_nav = f'<nav class="volume-nav" data-series="{html_mod.escape(s)}"></nav>' if s else ""

    content = normalize_wrap(content)
    comp_head, comp_hits = component_head(content)
    html_out = render(tpl,
        TITLE=title, HERO_TAG=tag, SUBTITLE=subtitle, DATE=date_str,
        CONTENT=content, COMPONENT_HEAD=comp_head, META=meta_html,
        SERIES_BADGE=series_badge, VOLUME_NAV=volume_nav,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / filename
    report_path.write_text(html_out, encoding="utf-8")
    (REPORTS_DIR / (filename[:-5] + ".md")).write_text(html_to_md(html_out), encoding="utf-8")

    return {"ok": True, "file": filename, "components": comp_hits}


def rebuild_index():
    """重建索引页（render --all 后调用）。"""
    reports = list_reports()
    INDEX_PATH.write_text(build_index(reports), encoding="utf-8")
    refresh_card_wall()
    refresh_home()
    # 全量丛书维护
    conn = store.get_db()
    try:
        for r in conn.execute("SELECT DISTINCT series FROM reports WHERE series!=''").fetchall():
            if r[0]:
                maintain_series_siblings(r[0])
    finally:
        conn.close()


# ============================================================
# 卡片墙（spec §3）——design 报告聚合页 public/design.html
# ============================================================
def design_reports() -> list:
    """domain=design 的报告（按 created_date 倒序）。"""
    conn = store.get_db()
    try:
        return [r for r in store.list_reports_from_db(conn) if r.get("domain") == "design"]
    finally:
        conn.close()


def build_card_wall() -> str:
    """生成卡片墙页：遍历 design 报告，卡片循环标记由 ui.card_wall_item 产出。"""
    design = design_reports()
    cards = [ui.card_wall_item(r) for r in design]
    year = design[0]["date"][:4] if design else str(datetime.now().year)
    tpl = ui.load_view("design.html")
    return (tpl
            .replace("__CARDS__", "\n    ".join(cards))
            .replace("__TOTAL__", str(len(design)))
            .replace("__YEAR__", year))


def refresh_card_wall():
    """刷新 public/design.html（与索引页同目录；随发布与 cli render 重渲染调用）。"""
    wall = config.INDEX_PATH.parent / "design.html"
    wall.write_text(build_card_wall(), encoding="utf-8")


# ============================================================
# 首页门户（P2）——public/home.html，与索引页同目录
# 占位符：__TOTAL_REPORTS__ / __TOTAL_CARDS__ / __TOTAL_TOPICS__ / __YEAR__
# ============================================================
def count_knowledge_topics() -> int:
    """knowledge/ 主题目录数：有 overview.md 的才算（与 GET /api/knowledge 列表口径一致）。"""
    kdir = config.KNOWLEDGE_DIR
    total = 0
    if kdir.exists():
        for dd in sorted(kdir.iterdir()):
            if not dd.is_dir() or dd.name.startswith("."):
                continue
            for td in sorted(dd.iterdir()):
                if (td / "overview.md").exists():
                    total += 1
    return total


def build_home() -> str:
    """生成首页门户：从 store 取 reports 总数 / design 数，扫 knowledge/ 主题数，填 views/home.html。"""
    conn = store.get_db()
    try:
        total_reports = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        total_cards = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE domain='design'").fetchone()[0]
    finally:
        conn.close()
    tpl = ui.load_view("home.html")
    return (tpl
            .replace("__TOTAL_REPORTS__", str(total_reports))
            .replace("__TOTAL_CARDS__", str(total_cards))
            .replace("__TOTAL_TOPICS__", str(count_knowledge_topics()))
            .replace("__YEAR__", str(datetime.now().year)))


def refresh_home():
    """刷新 public/home.html（与索引页同目录；随发布与 cli render 重渲染调用）。"""
    home = config.INDEX_PATH.parent / "home.html"
    home.write_text(build_home(), encoding="utf-8")
